"""Fixed-window rate limiting — Redis when configured (shared across instances), else in-memory."""
from __future__ import annotations

import threading
import time

from app.log import get_logger

logger = get_logger("ratelimit")


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int, redis_url: str | None = None):
        self.limit = max(1, limit)
        self.window = max(1, window_seconds)
        self._redis = None
        if redis_url:
            import redis

            self._redis = redis.Redis.from_url(redis_url)
        self._counts: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> tuple[bool, int]:
        """Count one request. Returns (allowed, retry_after_seconds)."""
        now = time.time()
        bucket = int(now // self.window)
        retry_after = int(self.window - (now % self.window)) + 1
        if self._redis is not None:
            try:
                redis_key = f"rl:{key}:{bucket}"
                pipe = self._redis.pipeline()
                pipe.incr(redis_key)
                pipe.expire(redis_key, self.window + 1)
                count = int(pipe.execute()[0])
                return count <= self.limit, retry_after
            except Exception as exc:  # Redis outage must not take the API down
                logger.warning(f"Redis rate limit unavailable, using local counter: {exc}")
        with self._lock:
            for stale in [k for k in self._counts if k[1] < bucket]:
                del self._counts[stale]
            count = self._counts.get((key, bucket), 0) + 1
            self._counts[(key, bucket)] = count
        return count <= self.limit, retry_after
