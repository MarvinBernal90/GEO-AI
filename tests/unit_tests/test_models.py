"""
==============================================================================
UNIT TESTS: DATABASE DOMAIN MODELS
==============================================================================
File: tests/unit_tests/test_models.py

Tests the SQLAlchemy domain models schema definition, column data types,
primary key constraints, and default value generators.
"""

import uuid

from sqlalchemy import String, Uuid
from sqlalchemy.orm import DeclarativeBase

from backend.db.base import Base
from backend.db.models import User


def test_user_model_schema():
    """Verifies that the User model defines the expected table name and columns."""
    assert issubclass(User, Base)
    assert issubclass(Base, DeclarativeBase)
    assert User.__tablename__ == "users"

    table = User.__table__
    assert "id" in table.columns
    assert "user" in table.columns
    assert len(table.columns) == 2


def test_user_id_column():
    """Verifies that the 'id' column is the primary key and contains UUID data."""
    id_col = User.__table__.columns["id"]

    assert id_col.primary_key is True
    assert isinstance(id_col.type, Uuid)


def test_user_user_column():
    """Verifies that the 'user' column is a string with a 100 character maximum length."""
    user_col = User.__table__.columns["user"]

    assert user_col.primary_key is False
    assert isinstance(user_col.type, String)
    assert user_col.type.length == 100
    assert user_col.nullable is False


def test_user_instantiation_with_defaults():
    """Verifies default UUID generation upon instantiation or initialization."""
    user = User(user="test_username")
    assert user.user == "test_username"


def test_user_instantiation_with_explicit_id():
    """Verifies explicit UUID assignment."""
    custom_id = uuid.uuid4()
    user = User(id=custom_id, user="custom_username")
    assert user.id == custom_id
    assert user.user == "custom_username"
