"""
==============================================================================
API SCHEMAS: REQUEST METRICS (DTOs)
==============================================================================
File: backend/api/schemas/metrics.py

Response models of the read-only metrics API that feeds the /metrics dashboard.
They describe what `request_metrics` and `request_spans` already store: sizes,
counts, times, model names and the class name of an error. Never user text.

Costs are in USD, as stored. `eur_per_usd` travels in the overview so the screen
can show euros with the same rate the backend is configured with.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Time windows accepted by the endpoints. "all" means no lower bound.
MetricsRange = Literal["24h", "7d", "30d", "all"]
RequestStatus = Literal["ok", "error", "cancelled"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Percentiles(_Out):
    """Distribution of one number. All fields are None when there is nothing to measure."""

    avg: float | None = None
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None
    max: float | None = None


class Kpis(_Out):
    requests: int = 0
    ok: int = 0
    errors: int = 0
    cancelled: int = 0
    error_rate: float = Field(0.0, description="errors / requests, between 0 and 1")
    latency_ms: Percentiles = Field(default_factory=Percentiles)
    ttft_ms: Percentiles = Field(default_factory=Percentiles)
    tokens_in: int = 0
    tokens_out: int = 0
    thought_tokens: int = 0
    cost_usd: float = Field(0.0, description="Sum of the requests that have a known price")
    unpriced_requests: int = Field(0, description="Requests that used tokens but have no price (cost is unknown)")
    avg_cost_usd: float | None = Field(None, description="Average over the priced requests only")


class TimeBucket(_Out):
    t: datetime = Field(..., description="Start of the bucket (UTC)")
    requests: int = 0
    errors: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    avg_ms: float | None = None
    p95_ms: float | None = None


class RouteStat(_Out):
    route: str
    requests: int = 0
    errors: int = 0
    avg_ms: float | None = None
    p95_ms: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    priced_requests: int = Field(0, description="Requests with a known price; 0 means cost_usd is unknown, not free")


class ModelStat(_Out):
    model: str = Field(..., description="'unknown' when the request has no LLM model")
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    priced_requests: int = Field(0, description="Requests with a known price; 0 means cost_usd is unknown, not free")
    avg_ms: float | None = None


class StatusStat(_Out):
    status: str
    requests: int = 0


class HistogramBin(_Out):
    label: str
    from_ms: float
    to_ms: float | None = Field(None, description="None for the open last bin")
    requests: int = 0


class ActorStat(_Out):
    actor: str
    calls: int = 0
    errors: int = 0
    avg_ms: float | None = None
    total_ms: float = Field(0.0, description="Added up over all calls; steps can overlap or contain each other")


class SpanStat(_Out):
    actor: str
    name: str
    calls: int = 0
    errors: int = 0
    avg_ms: float | None = None
    max_ms: float | None = None
    total_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


class ErrorStat(_Out):
    error: str = Field(..., description="Exception class name")
    count: int = 0


class CacheStat(_Out):
    hits: int = 0
    total: int = Field(0, description="Steps that report whether they used a cache")


class MetricsOverview(_Out):
    range: MetricsRange
    since: datetime | None = None
    until: datetime
    bucket: Literal["hour", "day"]
    metrics_enabled: bool = Field(True, description="False when METRICS_ENABLED switches measuring off")
    truncated: bool = Field(False, description="True when the window had more requests than the safety cap")
    eur_per_usd: float | None = None
    kpis: Kpis
    timeseries: list[TimeBucket] = Field(default_factory=list)
    by_route: list[RouteStat] = Field(default_factory=list)
    by_model: list[ModelStat] = Field(default_factory=list)
    by_status: list[StatusStat] = Field(default_factory=list)
    latency_histogram: list[HistogramBin] = Field(default_factory=list)
    by_actor: list[ActorStat] = Field(default_factory=list)
    top_spans: list[SpanStat] = Field(default_factory=list)
    top_errors: list[ErrorStat] = Field(default_factory=list)
    cache: CacheStat = Field(default_factory=CacheStat)


class RequestRow(_Out):
    id: int
    trace_id: str
    created_at: datetime
    route: str
    status: str
    status_code: int | None = None
    elapsed_ms: float
    ttft_ms: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    thought_tokens: int = 0
    cost_usd: float | None = Field(None, description="None means unknown price, never free")
    llm_model: str | None = None
    embedding_model: str | None = None
    span_count: int = 0
    dropped_spans: int = 0


class RequestPage(_Out):
    total: int
    limit: int
    offset: int
    items: list[RequestRow]


class SpanRow(_Out):
    span_id: int
    parent_id: int | None = None
    actor: str
    name: str
    start_ms: int = Field(..., description="Epoch milliseconds")
    offset_ms: float = Field(..., description="Milliseconds since the first step of the request")
    duration_ms: float | None = None
    status: str
    error: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    thought_tokens: int | None = None
    cost_usd: float | None = None
    cached: bool | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    ttft_ms: float | None = None


class RequestDetail(RequestRow):
    spans: list[SpanRow] = Field(default_factory=list)
