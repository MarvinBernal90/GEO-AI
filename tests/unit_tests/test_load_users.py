"""
==============================================================================
UNIT TESTS: USERS IMPORT ETL PIPELINE
==============================================================================
File: tests/unit_tests/test_load_users.py

Tests parsing of CSV and newline-delimited users files, as well as database
ingestion, idempotency, and truncation operations.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from database.load_users import load_users_from_csv, parse_users_file
from backend.db.models import User


@pytest.fixture
def test_db_session():
    """In-memory SQLite session for isolated database testing."""
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    with Session(engine) as session:
        yield session


def test_parse_users_file_plain_list(tmp_path: Path):
    """Verifies parsing of newline-delimited usernames without headers."""
    file = tmp_path / "users.csv"
    file.write_text("alice\nbob\ncharlie\n", encoding="utf-8")

    records = parse_users_file(file)
    assert len(records) == 3
    assert [r["user"] for r in records] == ["alice", "bob", "charlie"]
    for r in records:
        assert isinstance(r["id"], uuid.UUID)


def test_parse_users_file_with_header(tmp_path: Path):
    """Verifies that a 'user' or 'username' header line is ignored."""
    file = tmp_path / "users.csv"
    file.write_text("user\nalice\nbob\n", encoding="utf-8")

    records = parse_users_file(file)
    assert len(records) == 2
    assert [r["user"] for r in records] == ["alice", "bob"]


def test_parse_users_file_csv_with_ids(tmp_path: Path):
    """Verifies parsing standard CSV containing id and user columns."""
    id1 = uuid.uuid4()
    id2 = uuid.uuid4()
    file = tmp_path / "users.csv"
    file.write_text(f"id,user\n{id1},alice\n{id2},bob\n", encoding="utf-8")

    records = parse_users_file(file)
    assert len(records) == 2
    assert records[0] == {"id": id1, "user": "alice"}
    assert records[1] == {"id": id2, "user": "bob"}


def test_parse_users_file_empty(tmp_path: Path):
    """Verifies handling of empty file."""
    file = tmp_path / "empty.csv"
    file.write_text("", encoding="utf-8")

    records = parse_users_file(file)
    assert records == []


def test_parse_users_file_not_found(tmp_path: Path):
    """Verifies error on non-existent file."""
    with pytest.raises(FileNotFoundError):
        parse_users_file(tmp_path / "nonexistent.csv")


def test_load_users_from_csv(test_db_session: Session, tmp_path: Path):
    """Verifies importing users into database."""
    file = tmp_path / "users.csv"
    file.write_text("Emmy02\nMarliakanemon\nmayerga\nclaudiberenguer\n", encoding="utf-8")

    inserted = load_users_from_csv(test_db_session, file)
    assert inserted == 4

    users = test_db_session.scalars(select(User.user)).all()
    assert set(users) == {"Emmy02", "Marliakanemon", "mayerga", "claudiberenguer"}


def test_load_users_from_csv_idempotency(test_db_session: Session, tmp_path: Path):
    """Verifies running import multiple times does not duplicate users."""
    file = tmp_path / "users.csv"
    file.write_text("alice\nbob\n", encoding="utf-8")

    first_run = load_users_from_csv(test_db_session, file)
    assert first_run == 2

    second_run = load_users_from_csv(test_db_session, file)
    assert second_run == 0

    users = test_db_session.scalars(select(User.user)).all()
    assert len(users) == 2


def test_load_users_from_csv_truncate(test_db_session: Session, tmp_path: Path):
    """Verifies truncate flag removes old records before loading."""
    file1 = tmp_path / "users1.csv"
    file1.write_text("old_user\n", encoding="utf-8")
    load_users_from_csv(test_db_session, file1)

    file2 = tmp_path / "users2.csv"
    file2.write_text("new_user\n", encoding="utf-8")
    inserted = load_users_from_csv(test_db_session, file2, truncate=True)

    assert inserted == 1
    users = test_db_session.scalars(select(User.user)).all()
    assert users == ["new_user"]
