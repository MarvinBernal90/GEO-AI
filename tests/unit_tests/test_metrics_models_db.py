"""
==============================================================================
DB TESTS: REQUEST METRICS TABLES
==============================================================================
File: tests/unit_tests/test_metrics_models_db.py

Needs the test database with migration 0009 applied. Like the other DB tests,
it is skipped when DATABASE_URL does not point to a test database.
"""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.db.metrics_models import RequestMetric, RequestSpan
from backend.observability.metrics import MetricsCollector, add_usage, span, use_collector
from backend.observability.metrics.writer import MetricsWriter, build_record


@pytest.fixture
def metrics_session(db_engine):
    """A session with empty metrics tables before and after the test."""
    session = Session(db_engine)
    session.execute(text("TRUNCATE TABLE request_metrics CASCADE"))
    session.commit()
    yield session
    session.rollback()
    session.execute(text("TRUNCATE TABLE request_metrics CASCADE"))
    session.commit()
    session.close()


def _record():
    collector = MetricsCollector(trace_id="trace-db-1")
    with use_collector(collector):
        with span("agent", "viability_graph", input_summary="district 1"):
            with span("llm", "llm_call", model="gemini-2.5-flash") as llm:
                add_usage("gemini-2.5-flash", 1000, 500, 0, target=llm)
    return build_record(collector, route="/api/reports", status_code=200)


class TestMetricsTables:
    def test_the_writer_saves_a_request_with_its_spans(self, db_engine, metrics_session):
        writer = MetricsWriter(lambda: Session(db_engine))
        writer.start()
        writer.submit(_record())
        writer.stop(timeout=5)

        assert (writer.written, writer.failed) == (1, 0)
        row = metrics_session.execute(select(RequestMetric)).scalar_one()
        assert (row.trace_id, row.route, row.status, row.status_code) == ("trace-db-1", "/api/reports", "ok", 200)
        assert (row.tokens_in, row.tokens_out) == (1000, 500)
        assert row.created_at is not None
        assert sorted(s.name for s in row.spans) == ["llm_call", "viability_graph"]

    def test_deleting_a_request_deletes_its_spans(self, db_engine, metrics_session):
        writer = MetricsWriter(lambda: Session(db_engine))
        writer.start()
        writer.submit(_record())
        writer.stop(timeout=5)

        metrics_session.execute(text("DELETE FROM request_metrics"))
        metrics_session.commit()

        assert metrics_session.scalar(select(func.count()).select_from(RequestSpan)) == 0

    def test_the_same_trace_id_can_be_saved_twice(self, db_engine, metrics_session):
        writer = MetricsWriter(lambda: Session(db_engine))
        writer.start()
        writer.submit(_record())
        writer.submit(_record())
        writer.stop(timeout=5)

        assert (writer.written, writer.failed) == (2, 0)
