"""
==============================================================================
ALEMBIC MIGRATION: ADD USERS TABLE
==============================================================================
File: database/alembic/versions/0007_add_users_table.py
Revision ID: 0007
Revises: 0006, bc017c2708a3
Create Date: 2026-10-15

Architectural Purpose:
Adds the 'users' table to support user identity management and multi-tenant
session isolation for conversational memory and administrative operations.

Schema:
    - id: UUID Primary Key.
    - user: VARCHAR(100) NOT NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = ("0006", "bc017c2708a3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Creates the users table with UUID primary key and user string column."""
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drops the users table."""
    op.drop_table("users")
