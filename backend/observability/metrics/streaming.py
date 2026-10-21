"""
Helper to keep metrics working inside streamed (SSE) responses.

Problem: Starlette reads a sync generator with one threadpool call per item, and each
call starts from a fresh COPY of the request context. A ContextVar set in one step
(the active collector, the current span) is lost in the next step, so later spans
would not be recorded.

Fix: run every step of the generator inside one single Context object.
"""

from __future__ import annotations

import contextvars
from collections.abc import Generator, Iterable


def iterate_in_context[T](source: Iterable[T]) -> Generator[T, None, None]:
    """
    Yield the items of `source`, always advancing it inside the same Context.

    The context is copied when the first item is requested, so it still holds
    the values set by the request (for example the trace id).
    """
    ctx = contextvars.copy_context()
    iterator = iter(source)
    try:
        while True:
            try:
                item = ctx.run(next, iterator)
            except StopIteration:
                return
            yield item
    finally:
        # Closing the source inside the same context lets its own `finally`
        # blocks (for example saving the metrics) see the same context vars.
        close = getattr(iterator, "close", None)
        if close is not None:
            try:
                ctx.run(close)
            except RuntimeError:
                # The context is busy in another thread: nothing safe to do.
                pass
