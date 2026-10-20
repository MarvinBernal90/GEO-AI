"""
==============================================================================
UNIT TESTS: METRICS RECORD BUILDER AND BACKGROUND WRITER
==============================================================================
File: tests/unit_tests/test_metrics_writer.py

Uses a fake session factory, so these tests need no database.
"""

import pytest

from backend.observability.metrics import MetricsCollector, add_usage, span, use_collector
from backend.observability.metrics import writer as writer_module
from backend.observability.metrics.writer import MetricsWriter, build_record, record_request


class _FakeSession:
    def __init__(self, store, fail_commit=False):
        self._store = store
        self._fail_commit = fail_commit

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def add(self, obj):
        self._store["added"].append(obj)

    def commit(self):
        if self._fail_commit:
            raise RuntimeError("database is down")
        self._store["commits"] += 1


def _factory(fail_commit=False):
    store = {"added": [], "commits": 0}
    return (lambda: _FakeSession(store, fail_commit)), store


def _finished_collector(trace_id="t1"):
    """A request with a tree: root -> embed_query (rag) and root -> llm_call_stream (llm)."""
    collector = MetricsCollector(trace_id=trace_id)
    with use_collector(collector):
        with span("agent", "viability_graph", input_summary="district 1"):
            with span("rag", "embed_query", model="amazon.titan-embed-text-v2:0"):
                pass
            with span("llm", "llm_call_stream", model="gemini-2.5-flash", input_summary="40 chars") as llm:
                llm.ttft_ms = 12.5
                add_usage("gemini-2.5-flash", 1000, 500, 0, target=llm)
    return collector


@pytest.fixture(autouse=True)
def _reset_global_writer():
    writer_module.shutdown_writer(timeout=1)
    yield
    writer_module.shutdown_writer(timeout=1)


class TestBuildRecord:
    def test_totals_models_and_span_tree(self):
        record = build_record(_finished_collector(), route="/api/reports/stream", status_code=200)

        assert record["trace_id"] == "t1"
        assert record["route"] == "/api/reports/stream"
        assert (record["status"], record["status_code"]) == ("ok", 200)
        assert (record["tokens_in"], record["tokens_out"]) == (1000, 500)
        assert record["llm_model"] == "gemini-2.5-flash"
        assert record["embedding_model"] == "amazon.titan-embed-text-v2:0"
        assert record["span_count"] == 3
        assert [s["name"] for s in record["spans"]] == ["viability_graph", "embed_query", "llm_call_stream"]
        root = record["spans"][0]
        assert root["parent_id"] is None
        assert {s["parent_id"] for s in record["spans"][1:]} == {root["span_id"]}

    def test_request_ttft_includes_the_time_before_the_llm_call(self):
        record = build_record(_finished_collector(), route="/x")

        assert record["ttft_ms"] is not None
        assert record["ttft_ms"] >= 12.5

    def test_error_in_the_root_span_marks_the_request_as_error(self):
        collector = MetricsCollector(trace_id="t2")
        with use_collector(collector):
            with pytest.raises(ValueError):
                with span("agent", "viability_graph"):
                    raise ValueError("secret detail")

        record = build_record(collector, route="/x")

        assert record["status"] == "error"
        assert record["spans"][0]["error"] == "ValueError"
        assert "secret" not in str(record)

    def test_explicit_status_wins_over_the_derived_one(self):
        record = build_record(_finished_collector(), route="/x", status="cancelled")

        assert record["status"] == "cancelled"

    def test_long_texts_are_cut_to_the_column_size(self):
        collector = MetricsCollector(trace_id="x" * 200)
        with use_collector(collector):
            with span("agent", "n" * 300, model="m" * 500):
                pass

        record = build_record(collector, route="r" * 500)

        assert len(record["trace_id"]) == 64
        assert len(record["route"]) == 100
        assert len(record["spans"][0]["name"]) == 100
        assert len(record["spans"][0]["model"]) == 200


class TestWriter:
    def test_records_are_saved_in_the_background(self):
        factory, store = _factory()
        writer = MetricsWriter(factory)
        writer.start()

        for i in range(3):
            assert writer.submit(build_record(_finished_collector(f"t{i}"), route="/x"))
        writer.stop(timeout=3)

        assert writer.written == 3
        assert len(store["added"]) == 3
        assert store["commits"] >= 1
        assert len(store["added"][0].spans) == 3

    def test_pending_records_are_saved_when_stopping(self):
        factory, store = _factory()
        writer = MetricsWriter(factory, batch_size=50)
        for i in range(120):
            writer.submit(build_record(_finished_collector(f"t{i}"), route="/x"))

        writer.start()
        writer.stop(timeout=5)

        assert writer.written == 120
        assert store["commits"] == 3  # batches of 50, 50 and 20

    def test_full_queue_drops_the_newest_record_and_counts_it(self):
        factory, _ = _factory()
        writer = MetricsWriter(factory, max_queue=2)

        results = [writer.submit({"n": i}) for i in range(3)]

        assert results == [True, True, False]
        assert writer.dropped == 1

    def test_database_failure_does_not_raise_and_is_counted(self):
        factory, store = _factory(fail_commit=True)
        writer = MetricsWriter(factory)
        writer.start()

        writer.submit(build_record(_finished_collector(), route="/x"))
        writer.stop(timeout=3)

        assert (writer.written, writer.failed) == (0, 1)
        assert store["commits"] == 0

    def test_start_twice_keeps_a_single_thread(self):
        factory, _ = _factory()
        writer = MetricsWriter(factory)

        writer.start()
        first_thread = writer._thread
        writer.start()

        assert writer._thread is first_thread
        writer.stop(timeout=3)


class TestProcessWideWriter:
    def test_record_request_without_a_writer_does_nothing(self):
        assert record_request(_finished_collector(), route="/x") is False

    def test_record_request_queues_the_record_and_shutdown_saves_it(self):
        factory, store = _factory()
        writer_module.init_writer(factory)

        assert record_request(_finished_collector(), route="/api/x") is True
        writer_module.shutdown_writer(timeout=3)

        assert len(store["added"]) == 1
        assert store["added"][0].route == "/api/x"
        assert writer_module.get_writer() is None
