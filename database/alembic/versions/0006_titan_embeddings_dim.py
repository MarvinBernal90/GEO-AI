"""
==============================================================================
ALEMBIC MIGRATION: UPGRADE EMBEDDINGS DIMENSION TO TITAN V2 (1024)
==============================================================================
File: database/alembic/versions/0006_titan_embeddings_dim.py
Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10

Architectural Decision:
Migrates the vector dimensionality of the legal chunks table from 384 
(sentence-transformers/all-MiniLM-L6-v2) to 1024 (Amazon Titan Text Embeddings V2:
amazon.titan-embed-text-v2:0).

Changes:
    1. Drops the existing HNSW index tied to the 384-dimensional vector space.
    2. Alters the `embedding` column from `vector(384)` to `vector(1024)`.
    3. Recreates the HNSW index using `vector_cosine_ops` on the 1024-dimensional column.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ------------------------------------------------------------------------------
# IMMUTABILITY PRINCIPLE (Hardcoded Values)
# ------------------------------------------------------------------------------
OLD_EMBEDDING_DIM = 384
NEW_EMBEDDING_DIM = 1024


def upgrade() -> None:
    # 1. Drop the existing HNSW index that depends on the 384-dimensional column
    op.drop_index("idx_legal_chunks_embedding", table_name="legal_chunks")

    # 2. Alter column type to 1024 dimensions
    op.alter_column(
        "legal_chunks",
        "embedding",
        type_=Vector(NEW_EMBEDDING_DIM),
        existing_type=Vector(OLD_EMBEDDING_DIM),
        nullable=False,
    )

    # 3. Rebuild the HNSW index for the new 1024-dimensional vector space
    op.execute(
        "CREATE INDEX idx_legal_chunks_embedding ON legal_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    # 1. Drop the HNSW index that depends on the 1024-dimensional column
    op.drop_index("idx_legal_chunks_embedding", table_name="legal_chunks")

    # 2. Revert column type to 384 dimensions
    op.alter_column(
        "legal_chunks",
        "embedding",
        type_=Vector(OLD_EMBEDDING_DIM),
        existing_type=Vector(NEW_EMBEDDING_DIM),
        nullable=False,
    )

    # 3. Rebuild the HNSW index for the 384-dimensional vector space
    op.execute(
        "CREATE INDEX idx_legal_chunks_embedding ON legal_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
