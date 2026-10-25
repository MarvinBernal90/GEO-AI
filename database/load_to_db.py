"""
==============================================================================
ETL LOAD ORCHESTRATOR (PHASE 1)
==============================================================================
File: database/load_to_db.py

This script is the main controller of the data pipeline. It reads the raw
files (CSV/Excel), applies the transformations from the ETL layer
(backend/etl/) and writes the resulting DataFrames into PostgreSQL/PostGIS.

Usage:
    python -m database.load_to_db

Hybrid loading strategies:
    1. Dimension tables (districts, neighborhoods, income):
       We use an "Upsert" (INSERT ... ON CONFLICT DO UPDATE). It updates
       existing rows (for example, a new income value) without creating
       duplicates and without deleting the table structure.
    2. Commercial census table (competitors):
       We use a full replacement inside one transaction (DELETE + INSERT).
       Businesses open and close, so an Upsert would keep "ghost" businesses
       that no longer exist in the real census. Deleting everything first
       guarantees that the table matches the latest city council snapshot.
    3. Mobility table (district_mobility):
       It is loaded by backend/etl/etl_mitma.py, which reads the big MITMA
       files in chunks to avoid running out of memory. That module opens its
       own database connection, so it runs after the main commit.
"""

import pandas as pd
from dotenv import load_dotenv
from geoalchemy2.elements import WKTElement
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.db.connection import resolve_database_url
from backend.db.models import Competitor, District, DistrictIncome, Neighborhood
from backend.etl import config, etl_mitma
from backend.etl.competitors import build_competitors, build_districts, build_neighborhoods, read_raw_census
from backend.etl.income import load_district_income
from backend.observability import configure_logging, get_logger

logger = get_logger("etl.load_to_db")


def _upsert_dataframe(session: Session, model, df: pd.DataFrame, pk_column: str) -> None:
    """
    Helper that runs a bulk Upsert in PostgreSQL.
    It turns a Pandas DataFrame into an ON CONFLICT DO UPDATE statement.
    """
    if df.empty:
        logger.warning(f"DataFrame vacío para {model.__tablename__}, no se carga nada.")
        return

    records = df.to_dict(orient="records")
    stmt = pg_insert(model).values(records)

    # If a row with the same primary key exists, update every other column.
    update_columns = {col: getattr(stmt.excluded, col) for col in df.columns if col != pk_column}
    stmt = stmt.on_conflict_do_update(index_elements=[pk_column], set_=update_columns)
    session.execute(stmt)
    logger.info(f"{model.__tablename__}: {len(records)} filas upsert-eadas.")


def load_dimensions(session: Session, raw_census_df: pd.DataFrame) -> None:
    """Load the static tables (geographic dictionaries)."""
    districts_df = build_districts(raw_census_df)
    _upsert_dataframe(session, District, districts_df, pk_column="codi_districte")

    neighborhoods_df = build_neighborhoods(raw_census_df)
    _upsert_dataframe(session, Neighborhood, neighborhoods_df, pk_column="codi_barri")


def load_competitors(session: Session, raw_census_df: pd.DataFrame) -> None:
    """Load the business census with a full replacement and PostGIS types."""
    competitors_df = build_competitors(raw_census_df)

    # 1. Delete the previous snapshot (avoids "ghost" businesses).
    session.query(Competitor).delete()

    # 2. Rebuild the table, converting coordinates into PostGIS points.
    records = []
    for row in competitors_df.itertuples(index=False):
        # Some businesses have no neighborhood, so we store NULL in that case.
        codi_barri = None if pd.isna(row.codi_barri) else int(row.codi_barri)
        records.append(
            {
                "id_global": row.id_global,
                "nom_local": row.nom_local,
                "nom_activitat": row.nom_activitat,
                "nom_grup_activitat": row.nom_grup_activitat,
                "nom_sector_activitat": row.nom_sector_activitat,
                "codi_barri": codi_barri,
                "codi_districte": row.codi_districte,
                # Convert longitude/latitude to a standard geographic point (SRID 4326).
                "geom": WKTElement(f"POINT({row.longitud} {row.latitud})", srid=4326),
            }
        )

    if records:
        session.execute(pg_insert(Competitor), records)
    logger.info(f"competitors: {len(records)} filas cargadas (reemplazo completo).")


def load_income(session: Session, path) -> None:
    """Load the income data (INE)."""
    income_df = load_district_income(path)
    _upsert_dataframe(session, DistrictIncome, income_df, pk_column="codi_districte")


def run(engine=None) -> None:
    """Entry point of the ETL orchestrator."""
    load_dotenv()

    if engine is None:
        database_url = resolve_database_url()
        engine = create_engine(database_url, future=True)

    logger.info("Cargando censo comercial (dimensiones + competidores)...")
    raw_census_df = read_raw_census(config.PATH_CENSCOMER)

    # The `with` block handles the transaction: commit on success, rollback on error.
    with Session(engine) as session:
        load_dimensions(session, raw_census_df)

        # flush() sends the pending rows to the database without ending the
        # transaction. It is required because 'competitors' has foreign keys to
        # districts/neighborhoods, so those rows must exist before we insert them.
        session.flush()

        load_competitors(session, raw_census_df)

        logger.info("Cargando renta media por distrito...")
        load_income(session, config.PATH_INE_RENTA)

        # If we reach this point without errors, we save everything.
        session.commit()

    # The MITMA ETL creates its own engine and transaction, so it runs after the
    # commit above: the districts must already be saved for the foreign key.
    logger.info("Cargando movilidad/afluencia por distrito...")
    etl_mitma.run_etl()

    # run_etl() catches its own exceptions instead of raising them, so we check
    # the final status ourselves to avoid reporting success after a failure.
    if etl_mitma.PROGRESS["status"] == "error":
        raise RuntimeError(f"MITMA ETL failed: {etl_mitma.PROGRESS['message']}")

    logger.info("Carga completada.")


if __name__ == "__main__":
    configure_logging()
    run()
