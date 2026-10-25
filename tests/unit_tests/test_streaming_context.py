"""
==============================================================================
UNIT TESTS: METRICS INSIDE STREAMED RESPONSES
==============================================================================
File: tests/unit_tests/test_streaming_context.py

Uses a real StreamingResponse through TestClient, because the problem only
appears when Starlette reads the generator step by step in the threadpool.
"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend.observability.metrics import MetricsCollector, span, use_collector
from backend.observability.metrics.streaming import iterate_in_context


def _source(collector):
    """A stream with a parent span that stays open across two yields."""
    with use_collector(collector):
        with span("agent", "root"):
            yield "a"
            with span("rag", "child"):
                pass
            yield "b"


def _serve(wrap):
    """Serve the stream through a real app and return the collector."""
    collector = MetricsCollector(trace_id="t")
    app = FastAPI()

    @app.get("/stream")
    def stream():
        return StreamingResponse(wrap(_source(collector)), media_type="text/plain")

    with TestClient(app) as client:
        body = client.get("/stream").text
    assert body == "ab"
    return collector


class TestStreamingContext:
    def test_without_the_helper_later_spans_are_lost(self):
        """Documents the problem. If this fails, Starlette changed and the helper is not needed."""
        collector = _serve(lambda source: source)

        assert [s.name for s in collector.spans] == ["root"]

    def test_with_the_helper_the_span_tree_is_complete(self):
        collector = _serve(iterate_in_context)

        by_name = {s.name: s for s in collector.spans}
        assert set(by_name) == {"root", "child"}
        assert by_name["child"].parent_id == by_name["root"].id
        assert all(s.status == "ok" for s in collector.spans)

    def test_closing_early_runs_the_finally_of_the_source(self):
        done = []

        def source():
            try:
                yield 1
                yield 2
            finally:
                done.append(True)

        wrapped = iterate_in_context(source())
        assert next(wrapped) == 1
        wrapped.close()

        assert done == [True]
