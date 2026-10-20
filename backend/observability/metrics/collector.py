"""
Per-request metrics collector.

One MetricsCollector lives for one request. Code anywhere in the request opens
spans with the module-level `span()` helper, without receiving the collector as
an argument. Two ContextVars make that possible:
  - _collector_var: which collector belongs to the current request
  - _current_span_id: which span is the parent of the next span

Metrics must NEVER break an answer: every public method catches its own errors
and only logs them.

Threads: a new thread does not inherit ContextVars. When a step runs in a worker
thread, start it with `contextvars.copy_context().run(...)` so it keeps the
collector and the parent span.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from backend.observability import get_logger, get_trace_id
from backend.observability.metrics.spans import Actor, Span, clip_text, estimate_cost

logger = get_logger("observability.metrics.collector")

DEFAULT_MAX_SPANS = 500  # upper bound per request, so memory cannot grow without limit

_collector_var: ContextVar[MetricsCollector | None] = ContextVar("metrics_collector", default=None)
_current_span_id: ContextVar[int | None] = ContextVar("metrics_current_span", default=None)


def _union_ms(intervals: list[tuple[float, float]]) -> float:
    """
    Total time covered by (start, end) intervals. Overlapping intervals count once,
    so two parallel steps of 100 ms starting together add up to 100 ms, not 200 ms.
    """
    total = 0.0
    edge = float("-inf")
    for start, end in sorted(intervals):
        if end <= edge:
            continue
        total += end - max(start, edge)
        edge = end
    return total


class MetricsCollector:
    """Keeps the spans of one request and builds the totals."""

    def __init__(self, trace_id: str | None = None, max_spans: int = DEFAULT_MAX_SPANS):
        self.trace_id = trace_id or get_trace_id()
        self.dropped_spans = 0
        self._max_spans = max_spans
        self._spans: list[Span] = []
        self._by_id: dict[int, Span] = {}
        self._next_id = 1
        self._lock = threading.Lock()  # parallel graph nodes may open spans at the same time
        self._started = time.perf_counter()

    @property
    def spans(self) -> list[Span]:
        with self._lock:
            return list(self._spans)

    def _open(
        self, actor: Actor, name: str, model: str | None, cached: bool | None, input_summary: str | None
    ) -> Span | None:
        with self._lock:
            if len(self._spans) >= self._max_spans:
                self.dropped_spans += 1
                return None
            new_span = Span(
                id=self._next_id,
                parent_id=_current_span_id.get(),
                actor=actor,
                name=name,
                start_ms=int(time.time() * 1000),
                model=model,
                cached=cached,
                input_summary=clip_text(input_summary),
            )
            self._next_id += 1
            self._spans.append(new_span)
            self._by_id[new_span.id] = new_span
            return new_span

    @contextmanager
    def span(
        self,
        actor: Actor,
        name: str,
        *,
        model: str | None = None,
        cached: bool | None = None,
        input_summary: str | None = None,
    ) -> Iterator[Span | None]:
        """
        Time a block of code as one span. Yields the Span, or None if it could not
        be recorded (the block still runs). Exceptions are re-raised after the
        span is marked as 'error'.
        """
        try:
            current = self._open(actor, name, model, cached, input_summary)
        except Exception:
            logger.warning("Could not open span %s/%s", actor, name, exc_info=True)
            current = None

        if current is None:
            yield None
            return

        token = _current_span_id.set(current.id)
        started = time.perf_counter()
        try:
            yield current
        except BaseException as exc:
            current.status = "error"
            current.error = type(exc).__name__  # class only: the message may hold personal data
            raise
        finally:
            self._close(current, started, token)

    def _close(self, current: Span, started: float, token: Any) -> None:
        try:
            current.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if current.status == "running":
                current.status = "ok"
        except Exception:
            logger.warning("Could not close span %s", current.name, exc_info=True)
        try:
            _current_span_id.reset(token)
        except (ValueError, RuntimeError):
            # The token belongs to another context (for example a generator resumed elsewhere).
            logger.debug("Span context token could not be reset for %s", current.name)

    def add_usage(
        self, model: str, tokens_in: int | None, tokens_out: int | None, thought_tokens: int | None = 0
    ) -> None:
        """
        Store token usage and cost on the current span. It REPLACES any earlier value,
        so call it once with the final totals (streaming chunks report running totals).
        """
        try:
            target = self._by_id.get(_current_span_id.get())  # type: ignore[arg-type]
            if target is None:
                logger.debug("add_usage called outside a span; ignored")
                return
            target.model = model
            target.tokens_in = int(tokens_in or 0)
            target.tokens_out = int(tokens_out or 0)
            target.thought_tokens = int(thought_tokens or 0)
            target.cost_usd = estimate_cost(model, target.tokens_in, target.tokens_out, target.thought_tokens)
        except Exception:
            logger.warning("Could not store token usage", exc_info=True)

    def set_output(self, text: str | None) -> None:
        """Store a short summary of the result on the current span."""
        try:
            target = self._by_id.get(_current_span_id.get())  # type: ignore[arg-type]
            if target is not None:
                target.output_summary = clip_text(text)
        except Exception:
            logger.warning("Could not store span output", exc_info=True)

    def summary(self) -> dict[str, Any]:
        """Totals of the request: time, tokens, cost and calls/busy time per actor."""
        spans = self.spans
        costs = [s.cost_usd for s in spans if s.cost_usd is not None]

        per_actor: dict[str, dict[str, float]] = {}
        for actor in sorted({s.actor for s in spans}):
            own = [s for s in spans if s.actor == actor]
            finished = [(s.start_ms, s.start_ms + s.duration_ms) for s in own if s.duration_ms is not None]
            per_actor[actor] = {"calls": len(own), "ms": round(_union_ms(finished), 2)}

        return {
            "trace_id": self.trace_id,
            "span_count": len(spans),
            "dropped_spans": self.dropped_spans,
            "elapsed_ms": round((time.perf_counter() - self._started) * 1000, 2),
            "tokens_in": sum(s.tokens_in or 0 for s in spans),
            "tokens_out": sum(s.tokens_out or 0 for s in spans),
            "thought_tokens": sum(s.thought_tokens or 0 for s in spans),
            "cost_usd": round(sum(costs), 6) if costs else None,
            "per_actor": per_actor,
        }


def get_collector() -> MetricsCollector | None:
    return _collector_var.get()


@contextmanager
def use_collector(collector: MetricsCollector) -> Iterator[MetricsCollector]:
    """Make `collector` the active one for the current request."""
    token = _collector_var.set(collector)
    try:
        yield collector
    finally:
        try:
            _collector_var.reset(token)
        except (ValueError, RuntimeError):
            logger.debug("Collector context token could not be reset")


@contextmanager
def span(actor: Actor, name: str, **kwargs: Any) -> Iterator[Span | None]:
    """
    Open a span on the active collector. Without a collector (tests, ETL scripts)
    it does nothing, so instrumented code works everywhere.
    """
    collector = get_collector()
    if collector is None:
        yield None
        return
    with collector.span(actor, name, **kwargs) as current:
        yield current


def add_usage(model: str, tokens_in: int | None, tokens_out: int | None, thought_tokens: int | None = 0) -> None:
    collector = get_collector()
    if collector is not None:
        collector.add_usage(model, tokens_in, tokens_out, thought_tokens)


def set_output(text: str | None) -> None:
    collector = get_collector()
    if collector is not None:
        collector.set_output(text)
