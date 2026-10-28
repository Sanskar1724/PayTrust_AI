"""Live event bus for the dashboard feed (Server-Sent Events).

Single instance: in-process fan-out. With REDIS_URL set, events go through Redis pub/sub
so every API instance's subscribers see every decision.
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from typing import Any

from app.log import get_logger

logger = get_logger("events")
CHANNEL = "paytrust:events"
QUEUE_SIZE = 256


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()
        self._redis = None
        self._listener: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, redis_url: str | None) -> None:
        if not redis_url:
            return
        import redis

        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._stop.clear()
        self._listener = threading.Thread(target=self._listen, name="event-bus-redis", daemon=True)
        self._listener.start()
        logger.info("Event bus using Redis pub/sub")

    def stop(self) -> None:
        self._stop.set()

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        event = {"type": event_type, "data": data}
        if self._redis is not None:
            try:
                self._redis.publish(CHANNEL, json.dumps(event, default=str))
                return
            except Exception as exc:  # degrade to local fan-out rather than lose the event
                logger.warning(f"Redis publish failed, delivering locally: {exc}")
        self._fanout(event)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        entry = (loop, queue)
        with self._lock:
            self._subscribers.add(entry)
        try:
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                self._subscribers.discard(entry)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _fanout(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_offer, queue, event)
            except RuntimeError:  # loop closed
                pass

    def _listen(self) -> None:
        while not self._stop.is_set():
            try:
                pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(CHANNEL)
                for message in pubsub.listen():
                    if self._stop.is_set():
                        break
                    if message.get("type") == "message":
                        self._fanout(json.loads(message["data"]))
            except Exception as exc:
                logger.warning(f"Redis listener error, reconnecting: {exc}")
                self._stop.wait(2)


def _offer(queue: asyncio.Queue, event: dict[str, Any]) -> None:
    if queue.full():  # slow consumer: drop the oldest rather than block publishers
        queue.get_nowait()
    queue.put_nowait(event)


bus = EventBus()
