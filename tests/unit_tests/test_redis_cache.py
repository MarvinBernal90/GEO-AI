"""Unit tests for the fail-safe Redis caching layer (backend/cache/redis_client.py)."""

from decimal import Decimal
from unittest.mock import MagicMock

from backend.cache import (
    TTL_DISTRICT_SECONDS,
    TTL_GEOCODING_SECONDS,
    TTL_RAG_SECONDS,
    cache_get_json,
    cache_set_json,
    make_cache_key,
)
from backend.cache import redis_client


def test_package_reexports():
    assert TTL_GEOCODING_SECONDS > 0
    assert TTL_DISTRICT_SECONDS > 0
    assert TTL_RAG_SECONDS > 0
    assert callable(cache_get_json)
    assert callable(cache_set_json)
    assert callable(make_cache_key)



def test_make_cache_key_is_deterministic_and_case_insensitive():
    k1 = redis_client.make_cache_key("nominatim", "  Carrer de Mallorca 401 ")
    k2 = redis_client.make_cache_key("nominatim", "carrer de mallorca 401")
    assert k1 == k2
    assert k1.startswith("geoyield:nominatim:")


def test_cache_set_and_get_roundtrip_with_decimals(monkeypatch):
    store = {}
    fake_client = MagicMock()
    fake_client.get.side_effect = lambda k: store.get(k)
    fake_client.setex.side_effect = lambda k, ttl, val: store.__setitem__(k, val)

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake_client)

    key = redis_client.make_cache_key("district_scorecard", 2)
    payload = {"codi_districte": 2, "renta_media": Decimal("24500.50")}

    assert redis_client.cache_set_json(key, payload, 60) is True
    recovered = redis_client.cache_get_json(key)
    assert recovered == {"codi_districte": 2, "renta_media": 24500.5}


def test_cache_fails_open_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: None)
    key = redis_client.make_cache_key("nominatim", "Diagonal 100")
    assert redis_client.cache_get_json(key) is None
    assert redis_client.cache_set_json(key, {"lat": 41.39}, 60) is False


def test_cache_marks_active_observability_span_cached_hit_and_miss(monkeypatch):
    from backend.observability.metrics.collector import MetricsCollector, _collector_var, span

    store = {}
    fake_client = MagicMock()
    fake_client.get.side_effect = lambda k: store.get(k)
    fake_client.setex.side_effect = lambda k, ttl, val: store.__setitem__(k, val)
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake_client)

    collector = MetricsCollector(trace_id="test-trace-redis")
    token = _collector_var.set(collector)
    try:
        key = redis_client.make_cache_key("nominatim", "Passeig de Gracia 92")

        with span("external", "geocode_address") as s_miss:
            assert redis_client.cache_get_json(key) is None
            assert s_miss.cached is False

        redis_client.cache_set_json(key, {"lat": 41.395, "lon": 2.161}, 60)

        with span("external", "geocode_address") as s_hit:
            assert redis_client.cache_get_json(key) == {"lat": 41.395, "lon": 2.161}
            assert s_hit.cached is True
    finally:
        _collector_var.reset(token)

