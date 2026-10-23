"""Settings of the metrics system, read from environment variables."""

import math
import os

_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _env_flag(name: str) -> bool:
    """True unless the variable is set to a false-like value. Read on every call."""
    return os.getenv(name, "true").strip().lower() not in _FALSE_VALUES


def metrics_enabled() -> bool:
    """Master switch: measure requests and save them."""
    return _env_flag("METRICS_ENABLED")


def stream_events_enabled() -> bool:
    """Send the `trace` and `metrics_summary` events inside the SSE streams."""
    return metrics_enabled() and _env_flag("METRICS_STREAM_EVENTS")


def eur_per_usd() -> float | None:
    """
    Exchange rate used to show costs in euros, or None if it is not set or not valid.
    Costs are always stored in USD; the rate is only used for display.
    """
    raw = os.getenv("METRICS_EUR_PER_USD", "").strip().replace(",", ".")
    try:
        rate = float(raw)
    except ValueError:
        return None
    return rate if math.isfinite(rate) and rate > 0 else None
