"""
==============================================================================
UNIT TESTS: LIVE TRACE EVENTS AND METRICS SUMMARY
==============================================================================
File: tests/unit_tests/test_trace_events.py

No database and no LLM needed.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.api import deps
from backend.api.api import app
from backend.api.routers import reports
from backend.observability.metrics import MetricsCollector, add_usage, span, use_collector
from backend.observability.metrics.config import eur_per_usd
from backend.observability.metrics.streaming import stream_with_metrics

PAYLOAD = {"codi_districte": 1, "zona_pgm": "x"}


def _source(model="gemini-2.5-flash"):
    """root span -> one LLM span; two items are yielded."""
    with span("agent", "root"):
        yield {"type": "status"}
        with span("llm", "llm_call_stream", model=model) as llm:
            llm.ttft_ms = 5.0
            add_usage(model, 1_000_000, 1_000_000, 0, target=llm)
        yield {"type": "token"}


def _run(model="gemini-2.5-flash"):
    collector = MetricsCollector(trace_id="t")
    return list(stream_with_metrics(_source(model), collector, route="/x"))


class TestListener:
    def test_listener_gets_the_start_and_end_of_every_span(self):
        calls = []
        collector = MetricsCollector(trace_id="t")
        collector.set_listener(lambda phase, s: calls.append((phase, s.name, s.status)))

        with use_collector(collector):
            with span("agent", "a"):
                with span("rag", "b"):
                    pass

        assert calls == [("start", "a", "running"), ("start", "b", "running"), ("end", "b", "ok"), ("end", "a", "ok")]

    def test_the_end_of_a_failed_span_has_the_error_status(self):
        calls = []
        collector = MetricsCollector(trace_id="t")
        collector.set_listener(lambda phase, s: calls.append((phase, s.status, s.error)))

        with use_collector(collector):
            with pytest.raises(ValueError):
                with span("agent", "a"):
                    raise ValueError("secret detail")

        assert calls[-1] == ("end", "error", "ValueError")

    def test_a_failing_listener_does_not_break_the_request(self):
        def broken(phase, s):
            raise RuntimeError("listener bug")

        collector = MetricsCollector(trace_id="t")
        collector.set_listener(broken)

        with use_collector(collector):
            with span("agent", "a"):
                pass

        assert [s.status for s in collector.spans] == ["ok"]


class TestStreamEvents:
    def test_trace_events_come_in_order_and_the_summary_is_last(self):
        events = _run()

        sequence = [(e["type"], e.get("phase"), e.get("span", {}).get("name")) for e in events]
        assert sequence == [
            ("trace", "start", "root"),
            ("status", None, None),
            ("trace", "start", "llm_call_stream"),
            ("trace", "end", "llm_call_stream"),
            ("token", None, None),
            ("trace", "end", "root"),
            ("metrics_summary", None, None),
        ]

    def test_the_summary_has_the_totals_and_no_spans(self):
        summary = _run()[-1]

        assert summary["trace_id"] == "t"
        assert summary["status"] == "ok"
        assert summary["tokens_in"] == 1_000_000
        assert summary["cost_usd"] == pytest.approx(2.80)
        assert summary["ttft_ms"] is not None
        assert summary["llm_model"] == "gemini-2.5-flash"
        assert set(summary["per_actor"]) == {"agent", "llm"}
        assert "spans" not in summary

    def test_no_events_are_added_when_stream_events_are_disabled(self, monkeypatch):
        monkeypatch.setenv("METRICS_STREAM_EVENTS", "false")

        assert [e["type"] for e in _run()] == ["status", "token"]

    def test_cost_in_euros_uses_the_configured_rate(self, monkeypatch):
        monkeypatch.setenv("METRICS_EUR_PER_USD", "0.9")

        summary = _run()[-1]

        assert summary["eur_per_usd"] == 0.9
        assert summary["cost_eur"] == pytest.approx(summary["cost_usd"] * 0.9)

    def test_without_a_rate_the_cost_in_euros_is_null(self, monkeypatch):
        monkeypatch.delenv("METRICS_EUR_PER_USD", raising=False)

        summary = _run()[-1]

        assert summary["cost_usd"] is not None
        assert (summary["eur_per_usd"], summary["cost_eur"]) == (None, None)

    def test_an_unknown_price_gives_a_null_cost_never_zero(self, monkeypatch):
        monkeypatch.setenv("METRICS_EUR_PER_USD", "0.9")

        summary = _run(model="some-unpriced-model")[-1]

        assert (summary["cost_usd"], summary["cost_eur"]) == (None, None)


class TestConfig:
    @pytest.mark.parametrize("raw", ["abc", "0", "-1", "inf"])
    def test_invalid_rates_are_ignored(self, monkeypatch, raw):
        monkeypatch.setenv("METRICS_EUR_PER_USD", raw)

        assert eur_per_usd() is None

    def test_a_comma_decimal_is_accepted(self, monkeypatch):
        monkeypatch.setenv("METRICS_EUR_PER_USD", "0,92")

        assert eur_per_usd() == 0.92


class TestApi:
    def test_the_sse_stream_carries_trace_events_and_ends_with_the_summary(self, monkeypatch):
        monkeypatch.setattr(reports, "generar_informe_viabilidad_stream", lambda db, codi_districte, zona_pgm: _source())
        app.dependency_overrides[deps.get_session] = lambda: object()
        try:
            response = TestClient(app).post("/api/reports/stream", json=PAYLOAD)
        finally:
            app.dependency_overrides.pop(deps.get_session, None)

        lines = [part[len("data: ") :] for part in response.text.split("\n\n") if part.startswith("data: ")]
        types = [json.loads(line)["type"] for line in lines]
        assert types[-1] == "metrics_summary"
        assert types.count("trace") == 4
        assert types.index("trace") < types.index("token")
