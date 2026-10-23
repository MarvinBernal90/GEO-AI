"""
==============================================================================
UNIT TESTS: ONE CHAT FOR REPORTS AND FOR THE ASSISTANT
==============================================================================
File: tests/unit_tests/test_unified_chat.py

Uses the real app with every step replaced by a fake. No database, no LLM, no network.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.api import deps
from backend.api.api import app
from backend.api.routers import assistant as assistant_router
from backend.api.routers import chat
from backend.observability.metrics import MetricsCollector, add_usage, span, use_collector
from backend.observability.metrics.streaming import mark_stream_events

QUESTION = "¿Qué licencia necesito para una terraza?"
WITH_ADDRESS = "Quiero abrir un bar en Carrer Provença 123"
METRICS_TYPES = ("trace", "metrics_summary")
NO_PLACE = {"direccion": None, "distrito_mencionado": None, "pregunta_especifica": None}


def _chat_path():
    return next(r.path for r in app.routes if getattr(r, "endpoint", None) is chat.chat_informe_stream)


def _post(body):
    app.dependency_overrides[deps.get_session] = lambda: object()
    try:
        return TestClient(app).post(_chat_path(), json=body)
    finally:
        app.dependency_overrides.pop(deps.get_session, None)


def _events(response):
    assert response.status_code == 200
    return [json.loads(p[len("data: ") :]) for p in response.text.split("\n\n") if p.startswith("data: ")]


def _content(events):
    return [e for e in events if e["type"] not in METRICS_TYPES]


@pytest.fixture
def assistant_calls(monkeypatch):
    """Replace the assistant with a fake and return the list of its calls."""
    calls = []

    def fake_request(content, thread, stream=True, graph=None):
        calls.append((content, thread))
        with span("llm", "llm_call", model="gemini-2.5-flash") as llm:
            add_usage("gemini-2.5-flash", 10, 5, 0, target=llm)
        yield {"type": "token", "text": "Necesitas una licencia"}
        yield {"type": "done", "text": "Necesitas una licencia"}

    monkeypatch.setattr(assistant_router, "request", fake_request)
    return calls


def _fail(name):
    def fail(*args, **kwargs):
        pytest.fail(f"{name} must not run")

    return fail


def _fake_report(db, codi_districte, zona_pgm, **kwargs):
    with span("agent", "viability_graph"):
        yield {"type": "datos"}
        yield {"type": "done", "semaforo": "verde"}


class TestRouting:
    def test_without_a_thread_id_a_message_with_no_place_still_asks_for_clarification(self, monkeypatch):
        monkeypatch.setattr(chat, "extraer_intencion", lambda m: NO_PLACE)
        monkeypatch.setattr(assistant_router, "request", _fail("the assistant"))

        events = _events(_post({"mensaje": QUESTION}))

        assert [e["type"] for e in _content(events)] == ["aclaracion"]

    def test_with_a_thread_id_a_message_with_no_place_goes_to_the_assistant(self, monkeypatch, assistant_calls):
        monkeypatch.setattr(chat, "extraer_intencion", lambda m: NO_PLACE)
        monkeypatch.setattr(chat, "geocodificar_direccion", _fail("geocoding"))

        events = _events(_post({"mensaje": QUESTION, "thread_id": "alice:1"}))

        assert [e["type"] for e in _content(events)] == ["modo", "token", "done"]
        assert _content(events)[0]["modo"] == "asistente"
        assert assistant_calls == [(QUESTION, "alice:1")]

    def test_with_a_thread_id_an_address_still_gets_the_report(self, monkeypatch):
        monkeypatch.setattr(
            chat,
            "extraer_intencion",
            lambda m: {"direccion": "Carrer Provença 123", "distrito_mencionado": None, "pregunta_especifica": None},
        )
        monkeypatch.setattr(
            chat,
            "geocodificar_direccion",
            lambda d: {"lat": 41.39, "lon": 2.16, "codi_districte": 2, "direccion_encontrada": "Carrer Provença 123"},
        )
        monkeypatch.setattr(chat, "identificar_zona_pgm", lambda lat, lon: {"zona_pgm": "eixample"})
        monkeypatch.setattr(chat, "generar_informe_viabilidad_stream", _fake_report)
        monkeypatch.setattr(assistant_router, "request", _fail("the assistant"))

        events = _events(_post({"mensaje": WITH_ADDRESS, "thread_id": "alice:1"}))

        types = [e["type"] for e in _content(events)]
        assert types == ["ubicacion", "datos", "done"]

    def test_with_a_thread_id_a_district_alone_still_asks_for_the_zone(self, monkeypatch):
        monkeypatch.setattr(
            chat,
            "extraer_intencion",
            lambda m: {"direccion": None, "distrito_mencionado": "Les Corts", "pregunta_especifica": None},
        )
        monkeypatch.setattr(chat, "resolver_distrito_desde_suburb", lambda s: 4)
        monkeypatch.setattr(assistant_router, "request", _fail("the assistant"))

        events = _events(_post({"mensaje": "Quiero abrir en Les Corts", "thread_id": "alice:1"}))

        assert [e["type"] for e in _content(events)] == ["aclaracion"]

    def test_an_unsafe_thread_id_is_rejected_before_anything_runs(self, monkeypatch):
        monkeypatch.setattr(chat, "extraer_intencion", _fail("the NLU"))

        response = _post({"mensaje": QUESTION, "thread_id": "../requirements"})

        assert response.status_code == 422


class TestMetricsOfTheAssistantPath:
    def test_the_assistant_steps_nest_under_the_chat_pipeline_without_user_text(self, monkeypatch, assistant_calls):
        monkeypatch.setattr(chat, "extraer_intencion", lambda m: NO_PLACE)

        events = _events(_post({"mensaje": QUESTION, "thread_id": "alice:1"}))

        starts = {e["span"]["name"]: e["span"] for e in events if e["type"] == "trace" and e["phase"] == "start"}
        assert set(starts) >= {"chat_pipeline", "nlu_intent", "assistant_pipeline", "llm_call"}
        assert starts["assistant_pipeline"]["parent_id"] == starts["chat_pipeline"]["id"]
        assert starts["llm_call"]["parent_id"] == starts["assistant_pipeline"]["id"]
        summary = events[-1]
        assert summary["type"] == "metrics_summary"
        assert (summary["status"], summary["tokens_in"]) == ("ok", 10)
        assert summary["ttft_ms"] is not None
        dumped = json.dumps([e for e in events if e["type"] in METRICS_TYPES], ensure_ascii=False)
        assert "licencia" not in dumped
        assert "terraza" not in dumped

    def test_an_error_event_from_the_assistant_marks_the_request_as_error(self, monkeypatch):
        def failing_request(content, thread, stream=True, graph=None):
            yield {"type": "error", "detail": "No se pudo procesar tu mensaje."}

        monkeypatch.setattr(chat, "extraer_intencion", lambda m: NO_PLACE)
        monkeypatch.setattr(assistant_router, "request", failing_request)

        events = _events(_post({"mensaje": QUESTION, "thread_id": "alice:1"}))

        assert events[-1]["type"] == "metrics_summary"
        assert events[-1]["status"] == "error"


class TestMarkStreamEvents:
    def test_the_time_to_first_token_is_stored_only_once(self):
        collector = MetricsCollector(trace_id="t")
        with use_collector(collector):
            with span("agent", "root") as root:
                stream = mark_stream_events(iter([{"type": "status"}, {"type": "token"}, {"type": "token"}]), root)
                next(stream)
                assert root.ttft_ms is None
                next(stream)
                first = root.ttft_ms
                assert first is not None
                next(stream)
                assert root.ttft_ms == first

    def test_an_error_event_marks_the_span_as_failed(self):
        collector = MetricsCollector(trace_id="t")
        with use_collector(collector):
            with span("agent", "root") as root:
                list(mark_stream_events(iter([{"type": "error", "detail": "x"}]), root))

        assert (collector.spans[0].status, collector.spans[0].error) == ("error", "StreamError")

    def test_without_a_span_the_events_pass_through_unchanged(self):
        events = [{"type": "token", "text": "a"}, {"type": "error", "detail": "x"}]

        assert list(mark_stream_events(iter(events), None)) == events
