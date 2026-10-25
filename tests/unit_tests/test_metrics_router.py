"""
==============================================================================
UNIT TESTS: REQUEST METRICS READ API (/api/metrics)
==============================================================================
File: tests/unit_tests/test_metrics_router.py

No Postgres and no LLM needed: the endpoints run against an in-memory SQLite
database that holds only the two metrics tables. The aggregation is done in
Python on purpose, so these tests cover the real code path.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.api import deps
from backend.api.api import app
from backend.api.routers import request_metrics
from backend.db.metrics_models import RequestMetric, RequestSpan


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    RequestMetric.__table__.create(engine)
    RequestSpan.__table__.create(engine)
    return engine


@pytest.fixture
def client(engine):
    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[deps.get_session] = override
    yield TestClient(app)
    app.dependency_overrides.pop(deps.get_session, None)


_ids = iter(range(1, 10_000))


def add_request(engine, *, minutes_ago=5, spans=(), **fields):
    """Insert one request (ids are explicit because SQLite does not autoincrement BIGINT keys)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    data = {
        "id": next(_ids),
        "trace_id": f"trace-{next(_ids)}",
        "created_at": now - timedelta(minutes=minutes_ago),
        "route": "/api/reports/stream",
        "status": "ok",
        "status_code": 200,
        "elapsed_ms": 1000.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "thought_tokens": 0,
        "span_count": len(spans),
        "dropped_spans": 0,
    }
    data.update(fields)
    with Session(engine) as session:
        metric = RequestMetric(**data)
        for index, span in enumerate(spans, start=1):
            span = {"span_id": index, "start_ms": 1_000_000 + index * 100, "status": "ok", **span}
            metric.spans.append(RequestSpan(id=next(_ids), **span))
        session.add(metric)
        session.commit()
        return data["id"]


class TestOverview:
    def test_empty_database_gives_zeros_not_errors(self, client):
        body = client.get("/api/metrics/overview").json()

        assert body["kpis"]["requests"] == 0
        assert body["kpis"]["error_rate"] == 0
        assert body["kpis"]["latency_ms"]["p95"] is None
        assert body["by_route"] == [] and body["by_model"] == []
        # The 24h chart still has its empty hourly buckets, so the axis is not blank.
        assert len(body["timeseries"]) >= 24
        assert all(b["requests"] == 0 for b in body["timeseries"])

    def test_kpis_add_up(self, client, engine):
        add_request(engine, elapsed_ms=1000, ttft_ms=200, tokens_in=100, tokens_out=50, cost_usd="0.010000")
        add_request(engine, elapsed_ms=3000, ttft_ms=400, tokens_in=300, tokens_out=150, cost_usd="0.030000")
        add_request(engine, elapsed_ms=2000, status="error", status_code=500)
        add_request(engine, elapsed_ms=500, status="cancelled")

        kpis = client.get("/api/metrics/overview").json()["kpis"]

        assert (kpis["requests"], kpis["ok"], kpis["errors"], kpis["cancelled"]) == (4, 2, 1, 1)
        assert kpis["error_rate"] == 0.25
        assert (kpis["tokens_in"], kpis["tokens_out"]) == (400, 200)
        assert kpis["cost_usd"] == pytest.approx(0.04)
        assert kpis["avg_cost_usd"] == pytest.approx(0.02)
        assert kpis["latency_ms"]["avg"] == 1625.0
        assert kpis["latency_ms"]["p50"] == 1500.0
        assert kpis["latency_ms"]["max"] == 3000.0
        # ttft only counts the requests that had a first token
        assert kpis["ttft_ms"]["avg"] == 300.0

    def test_unknown_price_is_counted_apart_and_never_treated_as_free(self, client, engine):
        add_request(engine, tokens_in=100, tokens_out=50, cost_usd=None)
        add_request(engine, tokens_in=0, tokens_out=0, cost_usd=None)  # no tokens: nothing to price
        add_request(engine, tokens_in=10, tokens_out=10, cost_usd="0.002000")

        kpis = client.get("/api/metrics/overview").json()["kpis"]

        assert kpis["unpriced_requests"] == 1
        assert kpis["cost_usd"] == pytest.approx(0.002)
        assert kpis["avg_cost_usd"] == pytest.approx(0.002)

    def test_the_window_leaves_old_requests_out(self, client, engine):
        add_request(engine, minutes_ago=30)
        add_request(engine, minutes_ago=60 * 24 * 3)  # 3 days ago

        assert client.get("/api/metrics/overview?range=24h").json()["kpis"]["requests"] == 1
        assert client.get("/api/metrics/overview?range=7d").json()["kpis"]["requests"] == 2
        everything = client.get("/api/metrics/overview?range=all").json()
        assert everything["kpis"]["requests"] == 2
        assert everything["since"] is None
        assert everything["bucket"] == "day"

    def test_unknown_range_is_rejected(self, client):
        assert client.get("/api/metrics/overview?range=5y").status_code == 422

    def test_time_series_sums_a_bucket_and_fills_the_gaps(self, client, engine):
        add_request(engine, minutes_ago=1, tokens_in=10, elapsed_ms=100)
        add_request(engine, minutes_ago=1, tokens_in=20, elapsed_ms=300, status="error")
        add_request(engine, minutes_ago=60 * 5, tokens_in=7, elapsed_ms=900)

        series = client.get("/api/metrics/overview?range=24h").json()["timeseries"]
        busy = [b for b in series if b["requests"]]

        assert [b["requests"] for b in busy] == [1, 2]
        assert busy[-1]["tokens_in"] == 30 and busy[-1]["errors"] == 1
        assert busy[-1]["avg_ms"] == 200.0
        # an hour with no traffic exists as an empty bucket between them
        assert any(b["requests"] == 0 and b["avg_ms"] is None for b in series)

    def test_breakdowns(self, client, engine):
        add_request(engine, route="/api/reports/stream", llm_model="gemini-2.5-flash", elapsed_ms=1000, tokens_in=10)
        add_request(engine, route="/api/reports/stream", llm_model="gemini-2.5-flash", elapsed_ms=3000, tokens_in=30)
        add_request(engine, route="/api", llm_model=None, elapsed_ms=50, status="error")

        body = client.get("/api/metrics/overview").json()

        routes = {r["route"]: r for r in body["by_route"]}
        assert routes["/api/reports/stream"]["requests"] == 2
        assert routes["/api/reports/stream"]["avg_ms"] == 2000.0
        assert routes["/api"]["errors"] == 1
        assert body["by_route"][0]["route"] == "/api/reports/stream"  # busiest first

        models = {m["model"]: m for m in body["by_model"]}
        assert models["gemini-2.5-flash"]["tokens_in"] == 40
        # no price at all stays distinguishable from "free"
        assert models["unknown"]["priced_requests"] == 0
        assert models["unknown"]["requests"] == 1

        assert {s["status"]: s["requests"] for s in body["by_status"]} == {"ok": 2, "error": 1}

    def test_latency_histogram_covers_every_request_once(self, client, engine):
        for ms in (100, 700, 1500, 3000, 7000, 15000, 30000, 90000):
            add_request(engine, elapsed_ms=ms)

        bins = client.get("/api/metrics/overview").json()["latency_histogram"]

        assert [b["requests"] for b in bins] == [1] * 8
        assert bins[0]["from_ms"] == 0 and bins[0]["to_ms"] == 500
        assert bins[-1]["to_ms"] is None  # open last bin

    def test_span_aggregates(self, client, engine):
        add_request(
            engine,
            spans=[
                {"actor": "agent", "name": "chat_pipeline", "duration_ms": 1000.0},
                {"actor": "llm", "name": "llm_call_stream", "duration_ms": 600.0, "tokens_in": 10, "tokens_out": 5},
                {"actor": "rag", "name": "embed_query", "duration_ms": 40.0, "cached": True},
            ],
        )
        add_request(
            engine,
            spans=[
                {"actor": "llm", "name": "llm_call_stream", "duration_ms": 200.0, "tokens_in": 1, "tokens_out": 1},
                {"actor": "rag", "name": "embed_query", "duration_ms": 80.0, "cached": False},
                {"actor": "db", "name": "query", "duration_ms": 10.0, "status": "error", "error": "OperationalError"},
            ],
        )

        body = client.get("/api/metrics/overview").json()

        actors = {a["actor"]: a for a in body["by_actor"]}
        assert actors["llm"]["calls"] == 2 and actors["llm"]["avg_ms"] == 400.0
        assert actors["db"]["errors"] == 1
        assert body["by_actor"][0]["actor"] == "agent"  # most accumulated time first

        spans = {s["name"]: s for s in body["top_spans"]}
        assert spans["llm_call_stream"]["calls"] == 2
        assert spans["llm_call_stream"]["max_ms"] == 600.0
        assert (spans["llm_call_stream"]["tokens_in"], spans["llm_call_stream"]["tokens_out"]) == (11, 6)

        assert body["top_errors"] == [{"error": "OperationalError", "count": 1}]
        assert body["cache"] == {"hits": 1, "total": 2}

    def test_spans_outside_the_window_are_not_counted(self, client, engine):
        add_request(engine, minutes_ago=60 * 24 * 3, spans=[{"actor": "llm", "name": "old", "duration_ms": 5.0}])

        assert client.get("/api/metrics/overview?range=24h").json()["top_spans"] == []
        assert len(client.get("/api/metrics/overview?range=7d").json()["top_spans"]) == 1

    def test_the_row_cap_is_reported(self, client, engine, monkeypatch):
        monkeypatch.setattr(request_metrics, "MAX_ROWS", 2)
        for minutes in (1, 2, 3):
            add_request(engine, minutes_ago=minutes)

        body = client.get("/api/metrics/overview").json()

        assert body["truncated"] is True
        assert body["kpis"]["requests"] == 2

    def test_missing_tables_answer_503_not_a_stack_trace(self):
        bare = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        def override():
            with Session(bare) as session:
                yield session

        app.dependency_overrides[deps.get_session] = override
        try:
            response = TestClient(app).get("/api/metrics/overview")
        finally:
            app.dependency_overrides.pop(deps.get_session, None)

        assert response.status_code == 503
        assert "not available" in response.json()["detail"]


class TestRequestList:
    def test_pages_and_total(self, client, engine):
        for minutes in range(1, 8):
            add_request(engine, minutes_ago=minutes)

        first = client.get("/api/metrics/requests?limit=3").json()
        last = client.get("/api/metrics/requests?limit=3&offset=6").json()

        assert (first["total"], len(first["items"]), first["limit"], first["offset"]) == (7, 3, 3, 0)
        assert len(last["items"]) == 1
        created = [r["created_at"] for r in first["items"]]
        assert created == sorted(created, reverse=True)  # newest first by default

    def test_filters(self, client, engine):
        add_request(engine, route="/api", status="error", llm_model="m1", trace_id="abc-111")
        add_request(engine, route="/api", status="ok", llm_model=None, trace_id="abc-222")
        add_request(engine, route="/api/assistant", status="ok", llm_model="m1", trace_id="zzz-333")

        def total(query):
            return client.get(f"/api/metrics/requests?{query}").json()["total"]

        assert total("status=error") == 1
        assert total("route=/api") == 2
        assert total("model=m1") == 2
        assert total("model=unknown") == 1
        assert total("trace_id=abc") == 2
        assert total("trace_id=%25") == 0  # a wildcard is searched literally
        assert total("status=error&route=/api/assistant") == 0

    def test_sort_puts_unknown_values_last_in_both_directions(self, client, engine):
        add_request(engine, cost_usd="0.5")
        add_request(engine, cost_usd=None)
        add_request(engine, cost_usd="0.1")

        for direction, expected in (("desc", [0.5, 0.1, None]), ("asc", [0.1, 0.5, None])):
            items = client.get(f"/api/metrics/requests?sort=cost_usd&direction={direction}").json()["items"]
            assert [i["cost_usd"] for i in items] == expected

    def test_bad_parameters_are_rejected(self, client):
        assert client.get("/api/metrics/requests?limit=1000").status_code == 422
        assert client.get("/api/metrics/requests?offset=-1").status_code == 422
        assert client.get("/api/metrics/requests?status=weird").status_code == 422
        assert client.get("/api/metrics/requests?sort=password").status_code == 422


class TestRequestDetail:
    def test_returns_the_steps_in_order_with_offsets(self, client, engine):
        request_id = add_request(
            engine,
            spans=[
                {
                    "span_id": 2,
                    "parent_id": 1,
                    "actor": "llm",
                    "name": "llm_call",
                    "start_ms": 5_250,
                    "duration_ms": 30.0,
                },
                {
                    "span_id": 1,
                    "parent_id": None,
                    "actor": "agent",
                    "name": "root",
                    "start_ms": 5_000,
                    "duration_ms": 300.0,
                },
            ],
        )

        body = client.get(f"/api/metrics/requests/{request_id}").json()

        assert [s["name"] for s in body["spans"]] == ["root", "llm_call"]
        assert [s["offset_ms"] for s in body["spans"]] == [0, 250]
        assert body["spans"][1]["parent_id"] == 1

    def test_unknown_id_is_a_404(self, client):
        assert client.get("/api/metrics/requests/999999").status_code == 404
