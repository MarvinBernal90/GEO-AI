"""
==============================================================================
API ROUTER: REQUEST METRICS (READ-ONLY)
==============================================================================
File: backend/api/routers/request_metrics.py

Feeds the /metrics dashboard of the frontend. It only READS what the metrics
writer already saves in `request_metrics` and `request_spans`
(see backend/observability/metrics/writer.py).

Endpoints:
    GET /api/metrics/overview        KPIs, time series and breakdowns of a time window
    GET /api/metrics/requests        paginated, filterable list of request records
    GET /api/metrics/requests/{id}   one request with all its steps (spans)

Design:
    - Request rows are narrow, so the overview reads only the columns it needs and
      aggregates in Python. That keeps percentiles and time buckets portable (no
      Postgres-only functions) and unit-testable without a Postgres. A safety cap
      (MAX_ROWS) protects the API; `truncated` tells the screen when it was hit.
    - Spans can be many per request, so those are grouped in SQL.
    - Nothing here can store or reveal user text: the tables never hold it.

Not to be confused with GET /metrics (root), the plain-text request counter used
by monitoring tools.
"""

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from backend.api.deps import get_session
from backend.api.schemas.metrics import (
    ActorStat,
    CacheStat,
    ErrorStat,
    HistogramBin,
    Kpis,
    MetricsOverview,
    MetricsRange,
    ModelStat,
    Percentiles,
    RequestDetail,
    RequestPage,
    RequestRow,
    RequestStatus,
    RouteStat,
    SpanRow,
    SpanStat,
    StatusStat,
    TimeBucket,
)
from backend.db.metrics_models import RequestMetric, RequestSpan
from backend.observability import get_logger
from backend.observability.metrics.config import eur_per_usd, metrics_enabled

logger = get_logger("api.metrics")

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

# Safety cap on the requests read for one overview. The newest rows are kept.
MAX_ROWS = 50_000
# More buckets than this would only make the chart unreadable; "all" over many years stops filling gaps.
MAX_FILLED_BUCKETS = 400
TOP_SPANS = 12
TOP_ERRORS = 8

_WINDOWS: dict[str, timedelta] = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}

# Lower edge of every latency bin, in milliseconds. The last bin is open.
_LATENCY_EDGES_MS = (0, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 40_000)

_SORTABLE = {
    "created_at": RequestMetric.created_at,
    "elapsed_ms": RequestMetric.elapsed_ms,
    "ttft_ms": RequestMetric.ttft_ms,
    "tokens_out": RequestMetric.tokens_out,
    "cost_usd": RequestMetric.cost_usd,
}


# ------------------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------------------
def _utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes and Postgres aware ones; the API always speaks UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _num(value: Any) -> float | None:
    """Decimal/int/float -> float, keeping None (unknown) as None."""
    return None if value is None else float(value)


def _percentile(sorted_values: list[float], q: float) -> float:
    """Percentile by linear interpolation between the two closest values. `sorted_values` must not be empty."""
    position = (len(sorted_values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def _distribution(values: list[float]) -> Percentiles:
    if not values:
        return Percentiles()
    ordered = sorted(values)
    return Percentiles(
        avg=round(sum(ordered) / len(ordered), 1),
        p50=round(_percentile(ordered, 0.50), 1),
        p95=round(_percentile(ordered, 0.95), 1),
        p99=round(_percentile(ordered, 0.99), 1),
        max=round(ordered[-1], 1),
    )


def _floor(moment: datetime, bucket: Literal["hour", "day"]) -> datetime:
    if bucket == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _since(range_: str, now: datetime) -> datetime | None:
    window = _WINDOWS.get(range_)
    return now - window if window else None


def _unavailable(exc: Exception) -> HTTPException:
    """The tables are missing (migration 0009 not applied) or the database is unreachable."""
    logger.warning("Request metrics could not be read: %s", exc)
    return HTTPException(status_code=503, detail="Request metrics are not available right now.")


def _request_row(metric: RequestMetric) -> RequestRow:
    return RequestRow(
        id=metric.id,
        trace_id=metric.trace_id,
        created_at=_utc(metric.created_at),
        route=metric.route,
        status=metric.status,
        status_code=metric.status_code,
        elapsed_ms=metric.elapsed_ms,
        ttft_ms=metric.ttft_ms,
        tokens_in=metric.tokens_in,
        tokens_out=metric.tokens_out,
        thought_tokens=metric.thought_tokens,
        cost_usd=_num(metric.cost_usd),
        llm_model=metric.llm_model,
        embedding_model=metric.embedding_model,
        span_count=metric.span_count,
        dropped_spans=metric.dropped_spans,
    )


# ------------------------------------------------------------------------------
# Overview
# ------------------------------------------------------------------------------
def _kpis(rows: list[Any]) -> Kpis:
    counts = defaultdict(int)
    for row in rows:
        counts[row.status] += 1
    priced = [_num(r.cost_usd) for r in rows if r.cost_usd is not None]
    total_cost = sum(priced)
    return Kpis(
        requests=len(rows),
        ok=counts["ok"],
        errors=counts["error"],
        cancelled=counts["cancelled"],
        error_rate=round(counts["error"] / len(rows), 4) if rows else 0.0,
        latency_ms=_distribution([r.elapsed_ms for r in rows]),
        ttft_ms=_distribution([r.ttft_ms for r in rows if r.ttft_ms is not None]),
        tokens_in=sum(r.tokens_in for r in rows),
        tokens_out=sum(r.tokens_out for r in rows),
        thought_tokens=sum(r.thought_tokens for r in rows),
        cost_usd=round(total_cost, 6),
        # No price means "unknown", not "free": count them apart instead of hiding them in the total.
        unpriced_requests=sum(1 for r in rows if r.cost_usd is None and (r.tokens_in + r.tokens_out) > 0),
        avg_cost_usd=round(total_cost / len(priced), 6) if priced else None,
    )


def _timeseries(
    rows: list[Any], bucket: Literal["hour", "day"], first: datetime | None, last: datetime
) -> list[TimeBucket]:
    """One entry per bucket, empty buckets included, so a chart does not join across a quiet gap."""
    grouped: dict[datetime, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[_floor(_utc(row.created_at), bucket)].append(row)
    if first is None:
        return []

    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    start, end = _floor(first, bucket), _floor(last, bucket)
    if (end - start) / step > MAX_FILLED_BUCKETS:
        starts = sorted(grouped)  # too long to fill: show only the buckets that have data
    else:
        starts = [start + step * i for i in range(int((end - start) / step) + 1)]

    series = []
    for moment in starts:
        group = grouped.get(moment, [])
        durations = sorted(r.elapsed_ms for r in group)
        series.append(
            TimeBucket(
                t=moment,
                requests=len(group),
                errors=sum(1 for r in group if r.status == "error"),
                tokens_in=sum(r.tokens_in for r in group),
                tokens_out=sum(r.tokens_out for r in group),
                cost_usd=round(sum(_num(r.cost_usd) or 0.0 for r in group), 6),
                avg_ms=round(sum(durations) / len(durations), 1) if durations else None,
                p95_ms=round(_percentile(durations, 0.95), 1) if durations else None,
            )
        )
    return series


def _by_route(rows: list[Any]) -> list[RouteStat]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[row.route].append(row)
    stats = []
    for route, group in grouped.items():
        dist = _distribution([r.elapsed_ms for r in group])
        stats.append(
            RouteStat(
                route=route,
                requests=len(group),
                errors=sum(1 for r in group if r.status == "error"),
                avg_ms=dist.avg,
                p95_ms=dist.p95,
                tokens_in=sum(r.tokens_in for r in group),
                tokens_out=sum(r.tokens_out for r in group),
                cost_usd=round(sum(_num(r.cost_usd) or 0.0 for r in group), 6),
                priced_requests=sum(1 for r in group if r.cost_usd is not None),
            )
        )
    return sorted(stats, key=lambda s: s.requests, reverse=True)


def _by_model(rows: list[Any]) -> list[ModelStat]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[row.llm_model or "unknown"].append(row)
    stats = [
        ModelStat(
            model=model,
            requests=len(group),
            tokens_in=sum(r.tokens_in for r in group),
            tokens_out=sum(r.tokens_out for r in group),
            cost_usd=round(sum(_num(r.cost_usd) or 0.0 for r in group), 6),
            priced_requests=sum(1 for r in group if r.cost_usd is not None),
            avg_ms=_distribution([r.elapsed_ms for r in group]).avg,
        )
        for model, group in grouped.items()
    ]
    return sorted(stats, key=lambda s: s.requests, reverse=True)


def _latency_histogram(rows: list[Any]) -> list[HistogramBin]:
    edges = _LATENCY_EDGES_MS
    bins = []
    for i, low in enumerate(edges):
        high = edges[i + 1] if i + 1 < len(edges) else None
        if high is None:
            label = f"≥{low / 1000:g} s"
            count = sum(1 for r in rows if r.elapsed_ms >= low)
        else:
            label = f"{low / 1000:g}–{high / 1000:g} s"
            count = sum(1 for r in rows if low <= r.elapsed_ms < high)
        bins.append(HistogramBin(label=label, from_ms=low, to_ms=high, requests=count))
    return bins


def _span_stats(
    db: Session, since: datetime | None
) -> tuple[list[ActorStat], list[SpanStat], list[ErrorStat], CacheStat]:
    """Everything that comes from `request_spans`, grouped in SQL."""
    is_error = case((RequestSpan.status == "error", 1), else_=0)
    stmt = (
        select(
            RequestSpan.actor,
            RequestSpan.name,
            func.count().label("calls"),
            func.sum(is_error).label("errors"),
            func.count(RequestSpan.duration_ms).label("timed"),
            func.sum(func.coalesce(RequestSpan.duration_ms, 0.0)).label("total_ms"),
            func.max(RequestSpan.duration_ms).label("max_ms"),
            func.sum(func.coalesce(RequestSpan.tokens_in, 0)).label("tokens_in"),
            func.sum(func.coalesce(RequestSpan.tokens_out, 0)).label("tokens_out"),
        )
        .join(RequestMetric, RequestMetric.id == RequestSpan.request_id)
        .group_by(RequestSpan.actor, RequestSpan.name)
    )
    error_stmt = (
        select(RequestSpan.error, func.count().label("n"))
        .join(RequestMetric, RequestMetric.id == RequestSpan.request_id)
        .where(RequestSpan.error.is_not(None))
        .group_by(RequestSpan.error)
        .order_by(func.count().desc(), RequestSpan.error)
        .limit(TOP_ERRORS)
    )
    cache_stmt = (
        select(func.count(), func.sum(case((RequestSpan.cached.is_(True), 1), else_=0)))
        .join(RequestMetric, RequestMetric.id == RequestSpan.request_id)
        .where(RequestSpan.cached.is_not(None))
    )
    if since is not None:
        stmt = stmt.where(RequestMetric.created_at >= since)
        error_stmt = error_stmt.where(RequestMetric.created_at >= since)
        cache_stmt = cache_stmt.where(RequestMetric.created_at >= since)

    groups = db.execute(stmt).all()

    spans = [
        SpanStat(
            actor=g.actor,
            name=g.name,
            calls=g.calls,
            errors=int(g.errors or 0),
            avg_ms=round(float(g.total_ms) / g.timed, 1) if g.timed else None,
            max_ms=round(float(g.max_ms), 1) if g.max_ms is not None else None,
            total_ms=round(float(g.total_ms), 1),
            tokens_in=int(g.tokens_in or 0),
            tokens_out=int(g.tokens_out or 0),
        )
        for g in groups
    ]

    actors: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "errors": 0, "timed": 0, "total_ms": 0.0})
    for g in groups:
        acc = actors[g.actor]
        acc["calls"] += g.calls
        acc["errors"] += int(g.errors or 0)
        acc["timed"] += g.timed
        acc["total_ms"] += float(g.total_ms)
    by_actor = [
        ActorStat(
            actor=actor,
            calls=int(acc["calls"]),
            errors=int(acc["errors"]),
            avg_ms=round(acc["total_ms"] / acc["timed"], 1) if acc["timed"] else None,
            total_ms=round(acc["total_ms"], 1),
        )
        for actor, acc in actors.items()
    ]

    cache_total, cache_hits = db.execute(cache_stmt).one()
    return (
        sorted(by_actor, key=lambda a: a.total_ms, reverse=True),
        sorted(spans, key=lambda s: s.total_ms, reverse=True)[:TOP_SPANS],
        [ErrorStat(error=e, count=n) for e, n in db.execute(error_stmt).all()],
        CacheStat(hits=int(cache_hits or 0), total=int(cache_total or 0)),
    )


@router.get(
    "/overview",
    response_model=MetricsOverview,
    summary="Aggregated request metrics of a time window",
)
def overview(
    range_: MetricsRange = Query("24h", alias="range", description="Time window ending now"),
    db: Session = Depends(get_session),
) -> MetricsOverview:
    now = datetime.now(UTC)
    since = _since(range_, now)
    bucket: Literal["hour", "day"] = "hour" if range_ in ("24h", "7d") else "day"

    columns = (
        RequestMetric.created_at,
        RequestMetric.route,
        RequestMetric.status,
        RequestMetric.elapsed_ms,
        RequestMetric.ttft_ms,
        RequestMetric.tokens_in,
        RequestMetric.tokens_out,
        RequestMetric.thought_tokens,
        RequestMetric.cost_usd,
        RequestMetric.llm_model,
    )
    stmt = select(*columns).order_by(RequestMetric.created_at.desc()).limit(MAX_ROWS + 1)
    if since is not None:
        stmt = stmt.where(RequestMetric.created_at >= since)

    try:
        rows = db.execute(stmt).all()
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        # When rows were cut, the steps must be cut at the same point or the two halves would disagree.
        span_since = _utc(rows[-1].created_at) if truncated else since
        by_actor, top_spans, top_errors, cache = _span_stats(db, span_since)
    except (ProgrammingError, OperationalError) as exc:
        raise _unavailable(exc) from exc

    if truncated:
        logger.warning("Metrics overview read %d rows (the cap); older requests were left out", MAX_ROWS)

    # Fill the chart from the window start, or from the oldest request when the window is open.
    oldest = _utc(rows[-1].created_at) if rows else None
    first = since if since is not None else oldest
    if truncated and oldest is not None and (first is None or oldest > first):
        first = oldest

    by_status: dict[str, int] = defaultdict(int)
    for row in rows:
        by_status[row.status] += 1

    return MetricsOverview(
        range=range_,
        since=since,
        until=now,
        bucket=bucket,
        metrics_enabled=metrics_enabled(),
        truncated=truncated,
        eur_per_usd=eur_per_usd(),
        kpis=_kpis(rows),
        timeseries=_timeseries(rows, bucket, first, now),
        by_route=_by_route(rows),
        by_model=_by_model(rows),
        by_status=[StatusStat(status=s, requests=n) for s, n in sorted(by_status.items(), key=lambda kv: -kv[1])],
        latency_histogram=_latency_histogram(rows),
        by_actor=by_actor,
        top_spans=top_spans,
        top_errors=top_errors,
        cache=cache,
    )


# ------------------------------------------------------------------------------
# Records
# ------------------------------------------------------------------------------
@router.get(
    "/requests",
    response_model=RequestPage,
    summary="Paginated list of request records",
)
def list_requests(
    range_: MetricsRange = Query("24h", alias="range"),
    status: RequestStatus | None = Query(None),
    route: str | None = Query(None, max_length=100),
    model: str | None = Query(None, max_length=200, description="LLM model name, or 'unknown' for none"),
    trace_id: str | None = Query(None, max_length=64, description="Part of a trace id"),
    sort: Literal["created_at", "elapsed_ms", "ttft_ms", "tokens_out", "cost_usd"] = Query("created_at"),
    direction: Literal["asc", "desc"] = Query("desc"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
) -> RequestPage:
    filters = []
    since = _since(range_, datetime.now(UTC))
    if since is not None:
        filters.append(RequestMetric.created_at >= since)
    if status:
        filters.append(RequestMetric.status == status)
    if route:
        filters.append(RequestMetric.route == route)
    if model:
        filters.append(RequestMetric.llm_model.is_(None) if model == "unknown" else RequestMetric.llm_model == model)
    if trace_id:
        filters.append(RequestMetric.trace_id.contains(trace_id, autoescape=True))

    column = _SORTABLE[sort]
    ordering = column.desc() if direction == "desc" else column.asc()
    # NULLs (unknown price, no first token) go last either way, and id keeps pages stable on ties.
    page_stmt = (
        select(RequestMetric)
        .where(*filters)
        .order_by(column.is_(None), ordering, RequestMetric.id.desc())
        .limit(limit)
        .offset(offset)
    )
    count_stmt = select(func.count()).select_from(RequestMetric).where(*filters)

    try:
        total = db.execute(count_stmt).scalar_one()
        items = [_request_row(m) for m in db.execute(page_stmt).scalars()]
    except (ProgrammingError, OperationalError) as exc:
        raise _unavailable(exc) from exc

    return RequestPage(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/requests/{request_id}",
    response_model=RequestDetail,
    summary="One request with all its steps",
)
def get_request(request_id: int, db: Session = Depends(get_session)) -> RequestDetail:
    try:
        metric = db.get(RequestMetric, request_id)
        if metric is None:
            raise HTTPException(status_code=404, detail="Request not found.")
        spans = sorted(metric.spans, key=lambda s: (s.start_ms, s.span_id))
    except (ProgrammingError, OperationalError) as exc:
        raise _unavailable(exc) from exc

    origin = min((s.start_ms for s in spans), default=0)
    return RequestDetail(
        **_request_row(metric).model_dump(),
        spans=[
            SpanRow(
                span_id=s.span_id,
                parent_id=s.parent_id,
                actor=s.actor,
                name=s.name,
                start_ms=s.start_ms,
                offset_ms=float(s.start_ms - origin),
                duration_ms=s.duration_ms,
                status=s.status,
                error=s.error,
                model=s.model,
                tokens_in=s.tokens_in,
                tokens_out=s.tokens_out,
                thought_tokens=s.thought_tokens,
                cost_usd=_num(s.cost_usd),
                cached=s.cached,
                input_summary=s.input_summary,
                output_summary=s.output_summary,
                ttft_ms=s.ttft_ms,
            )
            for s in spans
        ],
    )
