"""
==============================================================================
REQUEST METRICS MODELS (ORM)
==============================================================================
File: backend/db/metrics_models.py

Two tables that store the metrics of every request:
- request_metrics: one row per request (totals, time, tokens, cost).
- request_spans: one row per step of that request (a tree through parent_id).

Privacy: these tables never store the user message or a typed address. Only
sizes, counts, model names and the class name of an error.

They live in their own module so `models.py` (shared with the rest of the team)
does not change.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class RequestMetric(Base):
    """Totals of one request."""

    __tablename__ = "request_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Not unique: a client can send its own X-Request-ID, so it may repeat.
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    route: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # ok | error | cancelled
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    elapsed_ms: Mapped[float] = mapped_column(Float, nullable=False)
    # Time from the first step of the request to the first streamed token.
    ttft_ms: Mapped[float | None] = mapped_column(Float)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    thought_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # None means "unknown price", never "free".
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    llm_model: Mapped[str | None] = mapped_column(String(200))
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    span_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    dropped_spans: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    spans: Mapped[list["RequestSpan"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", passive_deletes=True
    )


class RequestSpan(Base):
    """One step of a request. Times are in milliseconds."""

    __tablename__ = "request_spans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("request_metrics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    span_id: Mapped[int] = mapped_column(Integer, nullable=False)  # id inside the request
    parent_id: Mapped[int | None] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)  # epoch time
    duration_ms: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(String(100))  # exception class name only
    model: Mapped[str | None] = mapped_column(String(200))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    thought_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cached: Mapped[bool | None] = mapped_column(Boolean)
    input_summary: Mapped[str | None] = mapped_column(String(255))
    output_summary: Mapped[str | None] = mapped_column(String(255))
    ttft_ms: Mapped[float | None] = mapped_column(Float)

    request: Mapped[RequestMetric] = relationship(back_populates="spans")
