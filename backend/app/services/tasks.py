"""Small in-process worker pool for work that must not block a decision response
(AI explanations, Razorpay orders, agent callbacks). Every task is idempotent and
failures are logged, never raised to the caller."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from app.log import get_logger, get_request_id, set_request_id

logger = get_logger("tasks")
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="paytrust-task")
_run_inline = False


def run_inline(enabled: bool) -> None:
    """Tests run tasks synchronously so assertions see their effects."""
    global _run_inline
    _run_inline = enabled


def submit(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future | None:
    trace_id = get_request_id()

    def _wrapped() -> Any:
        set_request_id(trace_id)
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception(f"Background task {fn.__name__} failed")
            return None

    if _run_inline:
        _wrapped()
        return None
    return _executor.submit(_wrapped)


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
