# Imported for its side effect: loading the model modules registers every table on
# `Base.metadata`, which Alembic and `create_all` rely on. Not unused imports.
from . import metrics_models, models  # noqa: F401
from .base import Base

__all__ = ["Base"]
