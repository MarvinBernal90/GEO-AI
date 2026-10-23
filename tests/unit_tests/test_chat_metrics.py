"""
==============================================================================
UNIT TESTS: METRICS OF THE CHAT ENDPOINT
==============================================================================
File: tests/unit_tests/test_chat_metrics.py

Uses the real app with every step of the chat flow replaced by a fake.
No database, no LLM and no network needed.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.api import deps
from backend.api.api import app
from backend.api.routers import chat
from backend.observability.metrics import span

MESSAGE = "Quiero abrir un bar en Carrer Provença 123"


def _chat_path():
    """Path of the chat endpoint, read from the app so the test does not repeat it."""
    return next(r.path for r in app.routes if getattr(r, "endpoint", None) is chat.chat_informe_stream)


def _events(body):
    return [json.loads(part[len("data: ") :]) for part in body.split("\n\n") if part.startswith("data: ")]


def _post_chat():
    app.dependency_overrides[deps.get_session] = lambda: object()
    try:
        response = TestClient(app).post(_chat_path(), json={"mensaje": MESSAGE})
    finally:
        app.dependency_overrides.pop(deps.get_session, None)
    assert response.status_code == 200
    return _events(response.text)


def _fake_report(db, codi_districte, zona_pgm, **kwargs):
    with span("agent", "viability_graph"):
        yield {"type": "datos"}
        yield {"type": "done", "semaforo": "verde"}


@pytest.fixture
def full_flow(monkeypatch):
    monkeypatch.setattr(
        chat,
        "extraer_intencion",
        lambda mensaje: {"direccion": "Carrer Provença 123", "distrito_mencionado": None, "pregunta_especifica": None},
    )
    monkeypatch.setattr(
        chat,
        "geocodificar_direccion",
        lambda d: {"lat": 41.39, "lon": 2.16, "codi_districte": 2, "direccion_encontrada": "Carrer Provença 123"},
    )
    monkeypatch.setattr(chat, "identificar_zona_pgm", lambda lat, lon: {"zona_pgm": "eixample"})
    monkeypatch.setattr(chat, "generar_informe_viabilidad_stream", _fake_report)


class TestChatMetrics:
    def test_every_step_is_a_span_nested_under_the_chat_pipeline(self, full_flow):
        events = _post_chat()

        starts = {e["span"]["name"]: e["span"] for e in events if e["type"] == "trace" and e["phase"] == "start"}
        steps = ("nlu_intent", "geocode_address", "identify_pgm_zone", "viability_graph")
        assert set(starts) >= {"chat_pipeline", *steps}
        root = starts["chat_pipeline"]
        assert root["parent_id"] is None
        assert all(starts[name]["parent_id"] == root["id"] for name in steps)
        assert events[-1]["type"] == "metrics_summary"
        assert {"ubicacion", "datos", "done"} <= {e["type"] for e in events}

    def test_metrics_events_never_carry_the_user_text(self, full_flow):
        events = _post_chat()

        metrics_events = [e for e in events if e["type"] in ("trace", "metrics_summary")]
        assert metrics_events
        dumped = json.dumps(metrics_events, ensure_ascii=False)
        assert "Provença" not in dumped
        assert "Quiero abrir" not in dumped

    def test_a_clarification_still_reports_the_steps_that_ran(self, monkeypatch):
        monkeypatch.setattr(
            chat,
            "extraer_intencion",
            lambda mensaje: {"direccion": None, "distrito_mencionado": None, "pregunta_especifica": None},
        )
        monkeypatch.setattr(chat, "geocodificar_direccion", lambda d: pytest.fail("geocoding must not run"))

        events = _post_chat()

        names = {e["span"]["name"] for e in events if e["type"] == "trace"}
        assert names == {"chat_pipeline", "nlu_intent"}
        assert "aclaracion" in [e["type"] for e in events]
        assert events[-1]["type"] == "metrics_summary"
