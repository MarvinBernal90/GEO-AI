import os


def resolve_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL no está definida en el entorno")
    override = os.getenv("DB_HOST_OVERRIDE")
    if override:
        import re

        url = re.sub(r"@[^:/]+:", f"@{override}:", url)
    return url