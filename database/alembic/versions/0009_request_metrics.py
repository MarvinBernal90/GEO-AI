"""
==============================================================================
ALEMBIC MIGRATION: REQUEST METRICS TABLES
==============================================================================
File: database/alembic/versions/0009_request_metrics.py
Revision ID: 0009
Revises: 0007
Create Date: 2026-10-21

Purpose:
Adds the tables that store the metrics of every request:
    - request_metrics: one row per request (time, tokens, cost, models).
    - request_spans: one row per step, linked to its request. Rows are deleted
      with their request (ON DELETE CASCADE).

Note: the number 0008 is skipped on purpose. The file 0008_add_mobility_columns.py
is the old bc017c2708a3 migration with a new file name, and its revision id is
still bc017c2708a3. If the head of the migrations changes before this is merged,
update `down_revision` below.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("route", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("elapsed_ms", sa.Float(), nullable=False),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("thought_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("llm_model", sa.String(length=200), nullable=True),
        sa.Column("embedding_model", sa.String(length=200), nullable=True),
        sa.Column("span_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dropped_spans", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_request_metrics_trace_id"), "request_metrics", ["trace_id"], unique=False)
    op.create_index(op.f("ix_request_metrics_created_at"), "request_metrics", ["created_at"], unique=False)

    op.create_table(
        "request_spans",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("span_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("thought_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("cached", sa.Boolean(), nullable=True),
        sa.Column("input_summary", sa.String(length=255), nullable=True),
        sa.Column("output_summary", sa.String(length=255), nullable=True),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["request_metrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_request_spans_request_id"), "request_spans", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_request_spans_request_id"), table_name="request_spans")
    op.drop_table("request_spans")
    op.drop_index(op.f("ix_request_metrics_created_at"), table_name="request_metrics")
    op.drop_index(op.f("ix_request_metrics_trace_id"), table_name="request_metrics")
    op.drop_table("request_metrics")
