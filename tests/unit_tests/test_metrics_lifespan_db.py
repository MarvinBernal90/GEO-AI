"""
==============================================================================
DB TEST: API LIFESPAN + METRICS WRITER + REAL TABLES
==============================================================================
File: tests/unit_tests/test_metrics_lifespan_db.py

Starts the real app (so the real lifespan runs), makes one streamed request with
a fake report stream, stops the app and checks the rows in the test database.
Skipped when DATABASE_URL does not point to a test database.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.api.api import app
from backend.api.routers import reports
from backend.db.metrics_models import RequestMetric
from backend.observability.metrics import add_usage, span

PAYLOAD = {"codi_districte": 1, "zona_pgm": "x"}


@pytest.fixture
def clean_metrics(db_engine):
    """Empty metrics tables before and after the test."""
    with Session(db_engine) as session:
        session.execute(text("TRUNCATE TABLE request_metrics CASCADE"))
        session.commit()
    yield
    with Session(db_engine) as session:
        session.execute(text("TRUNCATE TABLE request_metrics CASCADE"))
        session.commit()


def _fake_stream(db, codi_districte, zona_pgm):
    with span("agent", "viability_graph"):
        yield {"type": "status", "message": "start"}
        with span("llm", "llm_call_stream", model="gemini-2.5-flash") as llm:
            add_usage("gemini-2.5-flash", 100, 50, 0, target=llm)
        yield {"type": "token", "text": "hello"}


def test_a_request_is_saved_in_the_database_when_the_api_stops(db_engine, clean_metrics, monkeypatch):
    monkeypatch.setattr(reports, "generar_informe_viabilidad_stream", _fake_stream)

    with TestClient(app) as client:  # runs the real lifespan: starts the writer
        response = client.post("/api/reports/stream", json=PAYLOAD, headers={"X-Request-ID": "lifespan-1"})
        assert response.status_code == 200
    # Leaving the block stopped the app, which saves the pending metrics.

    with Session(db_engine) as session:
        row = session.execute(select(RequestMetric)).scalar_one()
        assert (row.trace_id, row.route, row.status) == ("lifespan-1", "/api/reports/stream", "ok")
        assert (row.tokens_in, row.tokens_out) == (100, 50)
        assert row.llm_model == "gemini-2.5-flash"
        assert [s.name for s in row.spans] == ["viability_graph", "llm_call_stream"]
