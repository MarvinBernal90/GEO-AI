"""
==============================================================================
REDIS IN-MEMORY CACHE CLIENT (FAIL-SAFE / GRACEFUL DEGRADATION)
==============================================================================
File: backend/cache/redis_client.py

Provides a lightweight, fault-tolerant Redis caching layer for:
1. Geocoding (Nominatim) & Spatial Intersection (AMB Identify) — TTL 30 days.
2. District Socioeconomic Scorecards & Static Catalogs — TTL 24 hours.
3. Legal RAG Queries (Titan Embeddings + Rerank + Nova 2 Lite) — TTL 24 hours.

Architectural Design:
- Fail-Open (Graceful Degradation): If Redis is unreachable or disabled, the
  application logs a debug/warning message and continues normal execution
  against PostgreSQL/Bedrock/external APIs without crashing.
- Test Isolation: Automatically bypasses external Redis during pytest runs
  unless REDIS_FORCE_IN_TESTS=1 is explicitly set.
"""

import hashlib
import json
import os
from decimal import Decimal
from typing import Any

from backend.observability import get_logger
from backend.observability.metrics.collector import _current_span_id, get_collector

logger = get_logger("cache.redis")

# Default TTLs (in seconds)
TTL_GEOCODING_SECONDS = 30 * 24 * 3600  # 30 days (streets and PGM zones rarely change)
TTL_DISTRICT_SECONDS = 24 * 3600  # 24 hours (socioeconomic & mobility aggregates)
TTL_RAG_SECONDS = 24 * 3600  # 24 hours (legal RAG answers)

_redis_client: Any = None
_redis_unavailable: bool = False


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def _resolve_redis_url() -> str:
    """
    Resolves the Redis connection URL across Docker and local host environments.
    Mirrors backend/db/connection.py's DB_HOST_OVERRIDE pattern.
    """
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    host_override = os.getenv("REDIS_HOST_OVERRIDE") or os.getenv("DB_HOST_OVERRIDE")
    if host_override and "@redis:" not in url and "redis://redis:" in url:
        url = url.replace("redis://redis:", f"redis://{host_override}:")
    return url


def _is_cache_enabled() -> bool:
    if os.getenv("REDIS_CACHE_ENABLED", "true").lower() in ("0", "false", "no"):
        return False
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("REDIS_FORCE_IN_TESTS") != "1":
        return False
    return True


def get_redis_client() -> Any | None:
    """Returns a singleton Redis client, or None if Redis is unavailable."""
    global _redis_client, _redis_unavailable

    if not _is_cache_enabled() or _redis_unavailable:
        return None

    if _redis_client is not None:
        return _redis_client

    try:
        import redis

        url = _resolve_redis_url()
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        client.ping()
        _redis_client = client
        logger.info("Connected to Redis cache at %s", url)
        return _redis_client
    except Exception as exc:
        _redis_unavailable = True
        logger.debug("Redis cache unavailable (%s); continuing without cache.", exc)
        return None


def make_cache_key(prefix: str, *parts: Any) -> str:
    """Builds a deterministic, compact Redis key under the `geoyield:` namespace."""
    raw = "|".join(str(p).strip().lower() for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"geoyield:{prefix}:{digest}"


def _mark_span_cached(hit: bool) -> None:
    """Marks the currently active observability Span with cached=True/False for the /metrics dashboard."""
    try:
        collector = get_collector()
        if collector is not None:
            span_id = _current_span_id.get()
            target = collector._by_id.get(span_id) if span_id is not None else None
            if target is not None:
                target.cached = hit
    except Exception:
        pass


def cache_get_json(key: str) -> Any | None:
    """Fetches and deserializes a JSON payload from Redis. Returns None on miss/error."""
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            _mark_span_cached(False)
            return None
        _mark_span_cached(True)
        logger.debug("Cache HIT for key %s", key)
        return json.loads(raw)
    except Exception as exc:
        logger.debug("Redis GET failed for key %s: %s", key, exc)
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: int) -> bool:
    """Serializes and stores a JSON payload in Redis with a TTL."""
    client = get_redis_client()
    if client is None:
        return False
    try:
        payload = json.dumps(value, default=_json_default)
        client.setex(key, ttl_seconds, payload)
        logger.debug("Cache SET for key %s (ttl=%ss)", key, ttl_seconds)
        return True
    except Exception as exc:
        logger.debug("Redis SET failed for key %s: %s", key, exc)
        return False
