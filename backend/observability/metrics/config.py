"""Settings of the metrics system, read from environment variables."""

import os

_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def metrics_enabled() -> bool:
    """True unless METRICS_ENABLED is set to a false-like value. Read on every call."""
    return os.getenv("METRICS_ENABLED", "true").strip().lower() not in _FALSE_VALUES
