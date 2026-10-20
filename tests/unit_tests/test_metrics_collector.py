"""
==============================================================================
UNIT TESTS: REQUEST METRICS CORE (SPANS + COLLECTOR + COST)
==============================================================================
File: tests/unit_tests/test_metrics_collector.py

Pure Python tests: no database, no network, no Gemini.
"""

import asyncio
import contextvars
import threading

import pytest

from backend.observability.metrics import (
    MetricsCollector,
    add_usage,
    clip_text,
    estimate_cost,
    set_output,
    span,
    use_collector,
)
from backend.observability.metrics.collector import _union_ms


class TestSpanTree:
    def test_nested_spans_form_a_tree(self):
        collector = MetricsCollector(trace_id="t1")
        with collector.span("rag", "search") as outer:
            with collector.span("db", "pgvector") as inner:
                pass
        assert inner.parent_id == outer.id
        assert outer.parent_id is None
        assert outer.status == "ok"
        assert outer.duration_ms is not None

    def test_exception_marks_error_keeps_only_class_name_and_reraises(self):
        collector = MetricsCollector(trace_id="t1")
        with pytest.raises(ValueError):
            with collector.span("agent", "node") as current:
                raise ValueError("secret address Carrer de Mallorca 1")
        assert current.status == "error"
        assert current.error == "ValueError"
        assert "Mallorca" not in str(current.to_dict())

    def test_max_spans_bounds_memory(self):
        collector = MetricsCollector(trace_id="t1", max_spans=2)
        for i in range(5):
            with collector.span("db", f"q{i}"):
                pass
        assert len(collector.spans) == 2
        assert collector.dropped_spans == 3


class TestFailSafe:
    def test_collector_failure_does_not_break_the_caller(self, monkeypatch):
        collector = MetricsCollector(trace_id="t1")

        def boom(*args, **kwargs):
            raise RuntimeError("metrics bug")

        monkeypatch.setattr(collector, "_open", boom)
        ran = False
        with collector.span("rag", "search") as current:
            ran = True
        assert ran
        assert current is None

    def test_span_without_collector_is_a_noop(self):
        with span("rag", "search") as current:
            add_usage("gemini-2.5-flash", 10, 10)
            set_output("whatever")
        assert current is None


class TestConcurrency:
    def test_concurrent_requests_do_not_mix_spans(self):
        async def one_request(name):
            collector = MetricsCollector(trace_id=name)
            with use_collector(collector):
                with span("rag", f"{name}-outer"):
                    await asyncio.sleep(0.01)
                    with span("db", f"{name}-inner"):
                        await asyncio.sleep(0.01)
            return collector

        async def main():
            return await asyncio.gather(one_request("a"), one_request("b"))

        a, b = asyncio.run(main())
        assert [s.name for s in a.spans] == ["a-outer", "a-inner"]
        assert [s.name for s in b.spans] == ["b-outer", "b-inner"]
        assert a.spans[1].parent_id == a.spans[0].id

    def test_worker_thread_with_copied_context_keeps_the_parent(self):
        collector = MetricsCollector(trace_id="t1")
        with use_collector(collector):
            with span("agent", "graph") as parent:
                ctx = contextvars.copy_context()

                def work():
                    with span("rag", "node"):
                        pass

                thread = threading.Thread(target=ctx.run, args=(work,))
                thread.start()
                thread.join()
        assert collector.spans[1].parent_id == parent.id


class TestUsageAndCost:
    def test_gemini_flash_cost_matches_a_hand_calculation(self):
        assert estimate_cost("gemini-2.5-flash", 1_000_000, 0) == pytest.approx(0.30)
        # 100k output + 100k thinking tokens are both billed at the output price: 200k * 2.50 / 1M
        assert estimate_cost("gemini-2.5-flash", 0, 100_000, 100_000) == pytest.approx(0.50)

    def test_unknown_model_has_no_cost_instead_of_zero(self):
        assert estimate_cost("some-new-model", 1000, 1000) is None

    def test_price_can_be_overridden_with_env_vars(self, monkeypatch):
        monkeypatch.setenv("METRICS_PRICE_GEMINI_2_5_FLASH_IN", "1.0")
        monkeypatch.setenv("METRICS_PRICE_GEMINI_2_5_FLASH_OUT", "2.0")
        assert estimate_cost("gemini-2.5-flash", 1_000_000, 1_000_000) == pytest.approx(3.0)

    def test_invalid_env_price_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("METRICS_PRICE_GEMINI_2_5_FLASH_IN", "not-a-number")
        assert estimate_cost("gemini-2.5-flash", 1_000_000, 0) == pytest.approx(0.30)

    def test_add_usage_fills_the_current_span(self):
        collector = MetricsCollector(trace_id="t1")
        with use_collector(collector):
            with span("llm", "answer", model="gemini-2.5-flash") as current:
                add_usage("gemini-2.5-flash", 1000, 200, 50)
                set_output("short answer")
        assert (current.tokens_in, current.tokens_out, current.thought_tokens) == (1000, 200, 50)
        assert current.cost_usd is not None
        assert current.output_summary == "short answer"


class TestSummary:
    def test_totals_and_per_actor(self):
        collector = MetricsCollector(trace_id="t1")
        with use_collector(collector):
            with span("rag", "search"):
                with span("db", "pgvector"):
                    pass
            with span("llm", "answer"):
                add_usage("gemini-2.5-flash", 1_000_000, 0, 0)
        result = collector.summary()
        assert result["span_count"] == 3
        assert result["tokens_in"] == 1_000_000
        assert result["cost_usd"] == pytest.approx(0.30)
        assert result["per_actor"]["llm"]["calls"] == 1
        assert set(result["per_actor"]) == {"rag", "db", "llm"}

    def test_cost_is_none_when_no_span_has_a_price(self):
        collector = MetricsCollector(trace_id="t1")
        with collector.span("db", "query"):
            pass
        assert collector.summary()["cost_usd"] is None

    def test_overlapping_spans_are_counted_once(self):
        assert _union_ms([(0, 100), (50, 150), (200, 250)]) == 200


class TestClipText:
    def test_long_text_is_cut_and_whitespace_collapsed(self):
        result = clip_text("a   b\n" + "x" * 500, limit=20)
        assert len(result) == 20
        assert result.startswith("a b ")

    def test_none_stays_none(self):
        assert clip_text(None) is None
