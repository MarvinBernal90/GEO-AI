"""
Background writer for request metrics.

A request builds a plain-dict record with `build_record` and hands it to the
writer with `submit`. A background thread saves the records in batches, so saving
metrics never slows down an answer.

Rules:
- Metrics must NEVER break an answer: `submit` and the thread catch their own errors.
- The queue is bounded. If it is full, the NEWEST record is dropped and counted.
- A failed batch is logged and lost (no retries). Metrics are best-effort.

This module is not imported by `backend.observability.metrics.__init__` on purpose:
it needs the database models, and those import code that uses the metrics package.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from backend.observability import get_logger
from backend.observability.metrics.collector import MetricsCollector
from backend.observability.metrics.spans import Span

logger = get_logger("observability.metrics.writer")

DEFAULT_QUEUE_SIZE = 1000
DEFAULT_BATCH_SIZE = 50
_POLL_SECONDS = 0.5
_LOG_EVERY_DROPS = 100

# Span names that mean "an embedding call", used to find the embedding model of a request.
_EMBEDDING_SPAN_NAMES = frozenset({"embed_query", "bedrock_embeddings", "embed_local"})


def _cut(value: Any, limit: int) -> str | None:
    """Cut a text to the column size, so a long value can never make a whole batch fail."""
    return None if value is None else str(value)[:limit]


def _derive_status(spans: list[Span]) -> str:
    """Status of the request from its root spans: error, then cancelled, then ok."""
    roots = [s for s in spans if s.parent_id is None]
    if any(s.status == "error" for s in roots):
        return "error"
    if any(s.status == "cancelled" for s in roots):
        return "cancelled"
    return "ok"


def build_record(
    collector: MetricsCollector,
    *,
    route: str,
    status_code: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """
    Turn a finished collector into a plain dict (only numbers and short texts), so it can
    safely travel to the writer thread. Call it when the request has finished.
    """
    summary = collector.summary()
    spans = collector.spans

    # TTFT of the request: from the first step to the first streamed token.
    # The ttft_ms stored on a span is relative to its own start, so we add the offset.
    first_start = min((s.start_ms for s in spans), default=0)
    ttft_candidates = [(s.start_ms - first_start) + s.ttft_ms for s in spans if s.ttft_ms is not None]

    return {
        "trace_id": _cut(summary["trace_id"], 64) or "-",
        "route": _cut(route, 100) or "-",
        "status": status or _derive_status(spans),
        "status_code": status_code,
        "elapsed_ms": summary["elapsed_ms"],
        "ttft_ms": round(min(ttft_candidates), 2) if ttft_candidates else None,
        "tokens_in": summary["tokens_in"],
        "tokens_out": summary["tokens_out"],
        "thought_tokens": summary["thought_tokens"],
        "cost_usd": summary["cost_usd"],
        "llm_model": _cut(next((s.model for s in spans if s.actor == "llm" and s.model), None), 200),
        "embedding_model": _cut(
            next((s.model for s in spans if s.name in _EMBEDDING_SPAN_NAMES and s.model), None), 200
        ),
        "span_count": summary["span_count"],
        "dropped_spans": summary["dropped_spans"],
        "spans": [
            {
                "span_id": s.id,
                "parent_id": s.parent_id,
                "actor": s.actor,
                "name": _cut(s.name, 100),
                "start_ms": s.start_ms,
                "duration_ms": s.duration_ms,
                "status": s.status,
                "error": _cut(s.error, 100),
                "model": _cut(s.model, 200),
                "tokens_in": s.tokens_in,
                "tokens_out": s.tokens_out,
                "thought_tokens": s.thought_tokens,
                "cost_usd": s.cost_usd,
                "cached": s.cached,
                "input_summary": _cut(s.input_summary, 255),
                "output_summary": _cut(s.output_summary, 255),
                "ttft_ms": s.ttft_ms,
            }
            for s in spans
        ],
    }


def _to_orm(record: dict[str, Any]) -> Any:
    """Build the ORM objects of one record. The models are imported here to avoid a circular import."""
    from backend.db.metrics_models import RequestMetric, RequestSpan

    data = dict(record)
    span_rows = data.pop("spans", [])
    return RequestMetric(**data, spans=[RequestSpan(**row) for row in span_rows])


class MetricsWriter:
    """Bounded queue plus one background thread that saves the records in batches."""

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        max_queue: int = DEFAULT_QUEUE_SIZE,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self._session_factory = session_factory
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_queue)
        self._batch_size = batch_size
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.written = 0
        self.failed = 0
        self.dropped = 0

    def start(self) -> None:
        """Start the background thread. Calling it twice does nothing."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="metrics-writer", daemon=True)
        self._thread.start()

    def submit(self, record: dict[str, Any]) -> bool:
        """Queue a record without waiting. Returns False if it was dropped. Never raises."""
        try:
            self._queue.put_nowait(record)
            return True
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % _LOG_EVERY_DROPS == 0:
                logger.warning("Metrics queue is full: %d records dropped so far", self.dropped)
            return False
        except Exception:
            logger.warning("Could not queue a metrics record", exc_info=True)
            return False

    def stop(self, timeout: float = 5.0) -> None:
        """Save what is still in the queue, waiting at most `timeout` seconds, then stop the thread."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                logger.warning("Metrics writer did not finish in %.1fs; %d records left", timeout, self._queue.qsize())

    def _next_batch(self) -> list[dict[str, Any]]:
        """Wait for one record, then take more without waiting, up to the batch size."""
        batch: list[dict[str, Any]] = []
        wait = 0.0 if self._stop.is_set() else _POLL_SECONDS
        try:
            batch.append(self._queue.get(timeout=wait))
        except queue.Empty:
            return batch
        while len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _run(self) -> None:
        while True:
            batch = self._next_batch()
            if batch:
                self._write_batch(batch)
            elif self._stop.is_set():
                break

    def _write_batch(self, batch: list[dict[str, Any]]) -> None:
        try:
            with self._session_factory() as session:
                for record in batch:
                    session.add(_to_orm(record))
                session.commit()
            self.written += len(batch)
        except Exception:
            self.failed += len(batch)
            logger.warning("Could not write %d metrics records", len(batch), exc_info=True)


# ------------------------------------------------------------------------------
# Process-wide writer, used by the API (started and stopped in its lifespan).
# ------------------------------------------------------------------------------
_writer: MetricsWriter | None = None
_writer_lock = threading.Lock()


def init_writer(session_factory: Callable[[], Any], **kwargs: Any) -> MetricsWriter:
    """Create and start the process-wide writer. If one already exists, return it."""
    global _writer
    with _writer_lock:
        if _writer is None:
            _writer = MetricsWriter(session_factory, **kwargs)
            _writer.start()
        return _writer


def get_writer() -> MetricsWriter | None:
    return _writer


def shutdown_writer(timeout: float = 5.0) -> None:
    """Stop the process-wide writer, saving the pending records first."""
    global _writer
    with _writer_lock:
        writer, _writer = _writer, None
    if writer is not None:
        writer.stop(timeout)


def record_request(
    collector: MetricsCollector,
    *,
    route: str,
    status_code: int | None = None,
    status: str | None = None,
) -> bool:
    """
    One call for the API: build the record of a finished request and queue it.
    Does nothing (returns False) if there is no writer. Never raises.
    """
    writer = _writer
    if writer is None:
        return False
    try:
        return writer.submit(build_record(collector, route=route, status_code=status_code, status=status))
    except Exception:
        logger.warning("Could not build the metrics record", exc_info=True)
        return False
