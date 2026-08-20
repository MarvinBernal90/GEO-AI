import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .metrics.metrics import metrics

# El logging global se configura en main.py (punto de entrada). Aquí solo se
# obtiene el logger ya configurado, para mantener un único punto de control
# del nivel de log (variable de entorno LOG_LEVEL).
logger = logging.getLogger("geoyield_api")

# Estado de aplicación gestionado por el lifespan. Se evita usar variables
# globales mutables fuera de este patrón para no acoplar el estado a nivel
# de módulo con la lógica de negocio futura.
db_engine: Engine | None = None
SessionLocal: sessionmaker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida de la aplicación.

    Al arrancar: crea el engine de SQLAlchemy contra Postgres/PostGIS.
    Se falla rápido (fail-fast) si la variable DATABASE_URL no está definida
    o la base de datos no es accesible, para no servir tráfico con un estado
    inconsistente.
    """
    global db_engine, SessionLocal

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL no está definida en el entorno.")
        raise RuntimeError("DATABASE_URL no está definida en el entorno.")

    try:
        # pool_pre_ping evita servir conexiones muertas del pool (p. ej. tras
        # un reinicio de la base de datos) haciendo un ping ligero antes de
        # reutilizar cada conexión.
        db_engine = create_engine(database_url, pool_pre_ping=True, future=True)
        SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

        # Verificación de conectividad real en el arranque, no solo de que
        # el engine se haya podido instanciar (create_engine es perezoso y
        # no abre conexión por sí solo).
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Conexión a la base de datos establecida correctamente.")

    except Exception:
        logger.exception("Fallo al inicializar la conexión a la base de datos.")
        raise

    yield

    if db_engine is not None:
        db_engine.dispose()
        logger.info("Conexiones a la base de datos cerradas.")


app = FastAPI(
    title="Geo-Yield-AI API",
    description="API del agente de viabilidad de locales de hostelería.",
    lifespan=lifespan,
)


def get_session():
    """
    Crea una sesión de base de datos.

    Debe llamarse únicamente después de que el lifespan haya inicializado
    SessionLocal. Pensada para usarse como dependencia de FastAPI
    (`Depends(get_session)`) en los endpoints de dominio futuros.
    """
    if SessionLocal is None:
        raise RuntimeError("La base de datos no se ha inicializado todavía.")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.get("/health")
def health():
    """
    Liveness probe: confirma que el proceso está arriba.
    No depende de la base de datos a propósito, para que un contenedor
    orquestado (Docker/K8s) no lo reinicie en bucle si la BD está caída.
    """
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """
    Readiness probe: confirma que la aplicación puede atender tráfico real,
    es decir, que la base de datos está accesible.
    """
    if db_engine is None:
        return PlainTextResponse("database not initialized", status_code=503)

    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        logger.error(f"Readiness check falló: {exc}")
        return PlainTextResponse("database unreachable", status_code=503)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics_endpoint():
    return f'total_requests {metrics["total_requests"]}\n'


@app.middleware("http")
async def track_request_count(request, call_next):
    """Middleware mínimo de observabilidad: cuenta peticiones y su duración."""
    start = time.time()
    metrics["total_requests"] += 1
    response = await call_next(request)
    duration = time.time() - start
    logger.debug(f"{request.method} {request.url.path} - {duration:.3f}s")
    return response
