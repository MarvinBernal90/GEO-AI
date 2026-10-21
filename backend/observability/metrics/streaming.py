"""
Helpers to measure requests, including streamed (SSE) responses.

Problem with streams: Starlette reads a sync generator with one threadpool call per
item, and each call starts from a fresh COPY of the request context. A ContextVar set
in one step (the active collector, the current span) is lost in the next step, so
later spans would not be recorded.

Fix: run every step of the generator inside one single Context object.

Live events: while a stream runs, the spans that start and end are sent to the
frontend as `trace` events, and the totals as a final `metrics_summary` event.
Both carry only names, times and numbers, never user text.

Metrics must never break an answer: the helpers only add measuring around the code.
"""

from __future__ import annotations

import contextvars
import queue
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from backend.observability import get_logger
from backend.observability.context import get_trace_id
from backend.observability.metrics.collector import MetricsCollector, use_collector
from backend.observability.metrics.config import eur_per_usd, metrics_enabled, stream_events_enabled
from backend.observability.metrics.writer import build_record, record_request

logger = get_logger("observability.metrics.streaming")


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


def new_collector() -> MetricsCollector | None:
    """
    Collector for the current request, or None when metrics are turned off.
    It reuses the trace id of the logs, so logs and metrics share one identifier.
    Call it inside the endpoint, where the trace id of the middleware is visible.
    """
    if not metrics_enabled():
        return None
    return MetricsCollector(trace_id=get_trace_id())


def _with_collector[T](source: Iterable[T], collector: MetricsCollector) -> Generator[T, None, None]:
    """Keep the collector active while the source runs."""
    with use_collector(collector):
        yield from source


def build_summary_event(collector: MetricsCollector, *, route: str) -> dict[str, Any]:
    """
    The `metrics_summary` event: the same record that is saved in the database
    (without the spans), plus the time per actor and the cost in euros.
    """
    record = build_record(collector, route=route)
    event = {key: value for key, value in record.items() if key != "spans"}
    event["type"] = "metrics_summary"
    event["per_actor"] = collector.summary()["per_actor"]

    rate = eur_per_usd()
    cost_usd = event.get("cost_usd")
    event["eur_per_usd"] = rate
    event["cost_eur"] = round(float(cost_usd) * rate, 6) if cost_usd is not None and rate is not None else None
    return event


def _drain(events: queue.SimpleQueue | None) -> Iterator[dict[str, Any]]:
    """Yield, without waiting, every event that is in the queue now."""
    if events is None:
        return
    while True:
        try:
            yield events.get_nowait()
        except queue.Empty:
            return


def stream_with_metrics(
    source: Iterable[Any],
    collector: MetricsCollector | None,
    *,
    route: str,
    status_code: int | None = 200,
) -> Generator[Any, None, None]:
    """
    Yield the items of a streamed answer while measuring it.

    - The `trace` events of the spans that happened are sent before each item.
    - When the source ends, the rest of the `trace` events and the `metrics_summary` are sent.
    - When the stream ends, fails or is closed by the client, the request is queued for
      saving with status ok, error or cancelled.
    With no collector it only passes the items through.
    """
    if collector is None:
        yield from source
        return

    events: queue.SimpleQueue | None = None
    if stream_events_enabled():
        events = queue.SimpleQueue()
        sink = events  # the listener may run in worker threads; SimpleQueue is thread-safe
        collector.set_listener(lambda phase, current: sink.put({"type": "trace", "phase": phase, "span": current.to_dict()}))

    status = None
    try:
        for item in iterate_in_context(_with_collector(source, collector)):
            yield from _drain(events)
            yield item
        yield from _drain(events)
        if events is not None:
            try:
                summary_event = build_summary_event(collector, route=route)
            except Exception:
                logger.warning("Could not build the metrics summary event", exc_info=True)
            else:
                yield summary_event
    except GeneratorExit:
        status = "cancelled"
        raise
    except Exception:
        status = "error"
        raise
    finally:
        record_request(collector, route=route, status_code=status_code, status=status)


@contextmanager
def measure_request(
    collector: MetricsCollector | None,
    *,
    route: str,
    status_code: int | None = 200,
) -> Iterator[None]:
    """
    Measure a normal (not streamed) endpoint. Use it as a `with` block around the work.
    On an exception the request is saved with status error and the exception goes on.
    """
    if collector is None:
        yield
        return

    status = None
    try:
        with use_collector(collector):
            yield
    except Exception:
        status = "error"
        raise
    finally:
        record_request(
            collector,
            route=route,
            status_code=None if status == "error" else status_code,
            status=status,
        )
