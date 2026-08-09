"""
Resolución de DATABASE_URL con override de host para herramientas que se
ejecutan fuera de la red de Docker (Alembic, database/load_to_db.py, etc.).

Por qué existe esto: DATABASE_URL en el .env apunta a "postgis" (el nombre
del servicio dentro de la red de docker-compose), que solo resuelve DESDE
DENTRO de esa red. Cualquier herramienta ejecutada desde el host (tu shell)
necesita conectar a "localhost" en su lugar. En vez de mantener dos .env
distintos, se permite sobrescribir solo el host en tiempo de ejecución.
"""

import os
from urllib.parse import urlsplit, urlunsplit


def resolve_database_url() -> str:
    """
    Lee DATABASE_URL del entorno y, si está definida, sobrescribe el host
    con la variable DB_HOST_OVERRIDE (p. ej. DB_HOST_OVERRIDE=localhost al
    ejecutar Alembic o el loader desde fuera de Docker).
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL no está definida. Define un .env en la raíz del repo "
            "(ver .env.example)."
        )

    host_override = os.getenv("DB_HOST_OVERRIDE")
    if not host_override:
        return database_url

    parts = urlsplit(database_url)
    netloc = parts.netloc.replace(parts.hostname, host_override)
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))