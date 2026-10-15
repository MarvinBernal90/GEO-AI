"""
==============================================================================
ETL SCRIPT: USERS INGESTION ORCHESTRATOR
==============================================================================
File: database/load_users.py

Imports user records from CSV or newline-delimited text files into the 
'users' table of the geoyield_db database.

Usage:
    python -m database.load_users
    python database/load_users.py --csv-path data/users/users.csv --truncate
"""

import argparse
import csv
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# -----------------------------------------------------------------------------
# DYNAMIC REPOSITORY ROOT RESOLUTION
# -----------------------------------------------------------------------------
def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load environment configuration (.env)
load_dotenv(REPO_ROOT / ".env")

from backend.db.connection import resolve_database_url
from backend.db.models import User
from backend.observability import configure_logging, get_logger

logger = get_logger("etl.load_users")

DEFAULT_CSV_PATH = REPO_ROOT / "data" / "users" / "users.csv"


def parse_users_file(file_path: Path | str) -> list[dict]:
    """
    Parses user records from a CSV or raw newline-delimited text file.

    Supports:
    1. Standard CSV with headers (e.g., 'user', 'username', and optional 'id').
    2. Headerless lists of usernames (one username per line).

    Returns:
        list[dict]: List of dictionaries with 'id' (UUID) and 'user' (str).
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Users file not found at: {path}")

    with open(path, mode="r", encoding="utf-8-sig") as f:
        raw_lines = [line.strip() for line in f if line.strip()]

    if not raw_lines:
        logger.warning(f"File {path} is empty. No users found.")
        return []

    records = []

    # Case 1: Standard comma-separated CSV
    if "," in raw_lines[0]:
        reader = csv.DictReader(raw_lines)
        for row in reader:
            username = (row.get("user") or row.get("username") or "").strip()
            if not username:
                continue

            raw_id = (row.get("id") or "").strip()
            user_id = uuid.UUID(raw_id) if raw_id else uuid.uuid4()
            records.append({"id": user_id, "user": username[:100]})
        return records

    # Case 2: Newline-delimited list of usernames (with optional 'user' / 'username' header)
    start_index = 0
    if raw_lines[0].lower() in {"user", "username"}:
        start_index = 1

    for line in raw_lines[start_index:]:
        username = line.strip()
        if username:
            records.append({"id": uuid.uuid4(), "user": username[:100]})

    return records


def load_users_from_csv(
    session: Session,
    csv_path: Path | str = DEFAULT_CSV_PATH,
    truncate: bool = False,
) -> int:
    """
    Loads users from the specified CSV file into the database.

    Args:
        session: Active SQLAlchemy session.
        csv_path: Path to the CSV file.
        truncate: If True, clears existing users prior to import.

    Returns:
        int: Number of new user records inserted.
    """
    path = Path(csv_path)
    logger.info(f"Reading users from {path}...")
    user_records = parse_users_file(path)

    if not user_records:
        logger.warning("No user records to import.")
        return 0

    if truncate:
        logger.warning("Truncate option enabled: deleting existing records in 'users' table.")
        session.query(User).delete()
        session.flush()

    # Query existing usernames to guarantee idempotency and avoid duplicates
    existing_users = set(session.scalars(select(User.user)).all())

    inserted_count = 0
    for record in user_records:
        username = record["user"]
        if username in existing_users:
            logger.info(f"User '{username}' already exists in database, skipping.")
            continue

        user_instance = User(id=record["id"], user=username)
        session.add(user_instance)
        existing_users.add(username)
        inserted_count += 1

    session.commit()
    logger.info(f"Successfully imported {inserted_count} user(s) into 'users' table.")
    return inserted_count


def run(csv_path: Path | str = DEFAULT_CSV_PATH, truncate: bool = False, engine=None) -> int:
    """
    Main entry point for user ingestion.
    """
    if engine is None:
        database_url = resolve_database_url()
        engine = create_engine(database_url, future=True)

    with Session(engine) as session:
        return load_users_from_csv(session=session, csv_path=csv_path, truncate=truncate)


def main() -> None:
    """CLI handler."""
    configure_logging()
    parser = argparse.ArgumentParser(
        description="Import data/users/users.csv into the 'users' table of geoyield_db."
    )
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"Path to the users CSV file (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Clear existing user records before importing.",
    )
    args = parser.parse_args()

    run(csv_path=args.csv_path, truncate=args.truncate)


if __name__ == "__main__":
    main()
