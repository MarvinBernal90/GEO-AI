"""
Fixtures compartidas de pytest.

`db_session` requiere una base de datos Postgres+pgvector real y accesible
(la de `docker-compose up`, con DB_HOST_OVERRIDE=localhost si se corre
fuera de Docker). La CI actual (integrate.yml) no levanta ningún servicio
de base de datos, así que estos tests se SALTAN con gracia (pytest.skip)
en vez de fallar cuando no hay conexión disponible — dan valor real cuando
se ejecutan en local (o en una CI futura que sí levante Postgres), sin
romper la CI actual.
"""

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.db.connection import resolve_database_url

load_dotenv()


@pytest.fixture(scope="session")
def db_engine():
    try:
        url = resolve_database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL no definida: se omiten los tests que necesitan una base de datos real.")

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"No se pudo conectar a la base de datos ({exc}); se omiten los tests que la necesitan.")
    return engine


@pytest.fixture
def db_session(db_engine):
    session = Session(db_engine)
    # Se trunca ANTES de cada test, no solo después: si algo fuera de la
    # suite (una carga manual, una prueba anterior interrumpida a medias)
    # dejó datos residuales, no deben chocar con las claves primarias que
    # use el propio test.
    session.execute(text("TRUNCATE TABLE legal_chunks"))
    session.commit()

    yield session

    session.rollback()
    session.execute(text("TRUNCATE TABLE legal_chunks"))
    session.commit()
    session.close()
