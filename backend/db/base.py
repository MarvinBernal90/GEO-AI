"""
==============================================================================
ORM DECLARATIVE BASE (SQLAlchemy)
==============================================================================
File: backend/db/base.py

This is the parent class from which all database models inherit
(District, Competitor, LegalChunk).

Software design lesson:
We decided to put this class in its own file
and not in `models.py`. If it lived in `models.py`, the Alembic migration tool
would have to import that whole giant file. Since our models include
AI tables, importing `models.py` would force loading heavy Machine Learning
dependencies (embeddings) just to read the database schema. Separating
'Base' here avoids circular imports and unnecessary coupling between the
database layer and the AI layer.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    SQLAlchemy registry class.
    Tracks and stores the structure (metadata) of every class that inherits from it.
    """

    pass
