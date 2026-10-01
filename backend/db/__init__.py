# Imported for its side effect: loading `models` registers every table on
# `Base.metadata`, which Alembic and `create_all` rely on. Not an unused import.
from . import models  # noqa: F401
from .base import Base

__all__ = ["Base"]
