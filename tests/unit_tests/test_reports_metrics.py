"""
==============================================================================
UNIT TESTS: METRICS OF THE REPORT ENDPOINTS (END TO END)
==============================================================================
File: tests/unit_tests/test_reports_metrics.py

Uses the real app (middleware, router, collector, writer) with a fake session
factory for the writer and a fake report stream. No database and no LLM needed.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api import deps
from backend.api.api import app
from backend.api.routers import reports
from backend.observability.metrics import add_usage, span
from backend.observability.metrics import writer as writer_module

PAYLOAD = {"codi_districte": 1, "zona_pgm": "x"}


class _FakeSession:
    def __init__(self, store):
        self._store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def add(self, obj):
        self._store.append(obj)

    def commit(self):
        pass


@pytest.fixture
def saved():
    """Start the process-wide writer with a fake session. Yields the list of saved rows."""
    rows = []
    writer_module.shutdown_writer(timeout=1)
    writer_module.init_writer(lambda: _FakeSession(rows))
    app.dependency_overrides[deps.get_session] = lambda: object()
    yield rows
    app.dependency_overrides.pop(deps.get_session, None)
    writer_module.shutdown_writer(timeout=1)


def _ok_stream(db, codi_districte, zona_pgm):
    with span("agent", "viability_graph"):
        yield {"type": "status", "message": "start"}
        with span("llm", "llm_call_stream", model="gemini-2.5-flash") as llm:
            add_usage("gemini-2.5-flash", 100, 50, 0, target=llm)
        yield {"type": "token", "text": "hello"}


def _failing_stream(db, codi_districte, zona_pgm):
    with span("agent", "viability_graph"):
        yield {"type": "status", "message": "start"}
        raise RuntimeError("secret detail")


def _stream_request(headers=None):
    client = TestClient(app)
    response = client.post("/api/reports/stream", json=PAYLOAD, headers=headers or {})
    writer_module.shutdown_writer(timeout=3)
    return response


class TestStreamEndpoint:
    def test_a_finished_stream_is_saved_with_the_trace_id_of_the_request(self, saved, monkeypatch):
        monkeypatch.setattr(reports, "generar_informe_viabilidad_stream", _ok_stream)

        response = _stream_request({"X-Request-ID": "abc-123"})

        assert response.status_code == 200
        assert "hello" in response.text
        assert len(saved) == 1
        row = saved[0]
        assert (row.trace_id, row.route, row.status) == ("abc-123", "/api/reports/stream", "ok")
        assert [s.name for s in row.spans] == ["viability_graph", "llm_call_stream"]
        assert (row.tokens_in, row.tokens_out) == (100, 50)

    def test_a_failing_stream_is_saved_as_error_without_the_message(self, saved, monkeypatch):
        monkeypatch.setattr(reports, "generar_informe_viabilidad_stream", _failing_stream)

        response = _stream_request()

        assert response.status_code == 200
        assert '"type": "error"' in response.text
        assert "secret" not in response.text
        assert len(saved) == 1
        row = saved[0]
        assert row.status == "error"
        assert row.spans[0].error == "RuntimeError"
        assert "secret" not in str([s.error for s in row.spans])

    def test_nothing_is_saved_when_metrics_are_disabled(self, saved, monkeypatch):
        monkeypatch.setattr(reports, "generar_informe_viabilidad_stream", _ok_stream)
        monkeypatch.setenv("METRICS_ENABLED", "false")

        response = _stream_request()

        assert response.status_code == 200
        assert "hello" in response.text
        assert saved == []


class TestReportEndpoint:
    def test_a_failing_report_returns_502_and_is_saved_as_error(self, saved, monkeypatch):
        def failing(db, codi_districte, zona_pgm):
            with span("agent", "viability_graph"):
                raise RuntimeError("secret detail")

        monkeypatch.setattr(reports, "generar_informe_viabilidad", failing)

        response = TestClient(app).post("/api/reports", json=PAYLOAD)
        writer_module.shutdown_writer(timeout=3)

        assert response.status_code == 502
        assert len(saved) == 1
        row = saved[0]
        assert (row.route, row.status, row.status_code) == ("/api/reports", "error", None)
        assert row.spans[0].error == "RuntimeError"
