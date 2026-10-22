"""Unit tests for backend/ia/report_context.py (pure Python, no database, no AWS)."""

from enum import Enum

import pytest

from backend.ia import report_context as rc


@pytest.fixture(autouse=True)
def _empty_notes():
    rc.clear_all()
    yield
    rc.clear_all()


def test_build_note_has_all_the_parts():
    note = rc.build_note(
        direccion="Carrer de Mallorca 401",
        distrito="Eixample",
        zona_pgm="Conservació de l'estructura urbana",
        semaforo="amarillo",
        resumen="Viable con reservas.",
    )
    assert "Carrer de Mallorca 401" in note
    assert "Eixample" in note
    assert "Conservació" in note
    assert "amarillo" in note
    assert "Viable con reservas." in note


def test_build_note_skips_missing_values():
    note = rc.build_note(distrito="Gràcia", zona_pgm=None, semaforo="  ", resumen="")
    assert "Gràcia" in note
    assert "zona" not in note
    assert "semáforo" not in note
    assert "resumen" not in note


def test_build_note_is_empty_when_there_is_nothing():
    assert rc.build_note() == ""
    assert rc.build_note(distrito=" ", resumen=None) == ""


def test_build_note_is_cut_to_the_limit():
    note = rc.build_note(distrito="Eixample", resumen="x" * 5000)
    assert len(note) <= rc.MAX_NOTE_CHARS
    assert note.endswith("...")


def test_remember_and_recall():
    assert rc.remember("marvin:1", "nota uno") is True
    assert rc.recall("marvin:1") == "nota uno"


def test_recall_unknown_thread_is_none():
    assert rc.recall("nadie:9") is None


def test_remember_replaces_the_previous_note():
    rc.remember("marvin:1", "primera")
    rc.remember("marvin:1", "segunda")
    assert rc.recall("marvin:1") == "segunda"


def test_notes_of_different_threads_do_not_mix():
    rc.remember("marvin:1", "A")
    rc.remember("lili:1", "B")
    assert rc.recall("marvin:1") == "A"
    assert rc.recall("lili:1") == "B"


@pytest.mark.parametrize("thread_id", [None, "", "   ", 42, ["marvin:1"]])
def test_remember_ignores_bad_thread_ids(thread_id):
    assert rc.remember(thread_id, "nota") is False


@pytest.mark.parametrize("note", [None, "", "   "])
def test_remember_ignores_empty_notes(note):
    assert rc.remember("marvin:1", note) is False
    assert rc.recall("marvin:1") is None


def test_recall_with_a_bad_thread_id_does_not_raise():
    assert rc.recall(None) is None
    assert rc.recall(123) is None


def test_forget_removes_only_that_thread():
    rc.remember("marvin:1", "A")
    rc.remember("lili:1", "B")
    rc.forget("marvin:1")
    assert rc.recall("marvin:1") is None
    assert rc.recall("lili:1") == "B"
    rc.forget("nunca-existio")  # must not raise
    rc.forget(None)  # must not raise


def test_oldest_notes_are_dropped_when_the_limit_is_reached(monkeypatch):
    monkeypatch.setattr(rc, "MAX_THREADS", 3)
    for number in range(5):
        rc.remember(f"t:{number}", f"nota {number}")
    assert rc.recall("t:0") is None
    assert rc.recall("t:1") is None
    assert rc.recall("t:2") == "nota 2"
    assert rc.recall("t:4") == "nota 4"


def test_a_rewritten_note_counts_as_recent(monkeypatch):
    monkeypatch.setattr(rc, "MAX_THREADS", 2)
    rc.remember("a", "1")
    rc.remember("b", "2")
    rc.remember("a", "1 nueva")  # "a" is now the newest
    rc.remember("c", "3")  # drops the oldest, which is "b"
    assert rc.recall("a") == "1 nueva"
    assert rc.recall("b") is None
    assert rc.recall("c") == "3"


# ---------------------------------------------------------------------------
# track_report: wraps the event stream of a report
# ---------------------------------------------------------------------------


class _Semaforo(str, Enum):  # noqa: UP042 -- same as the real Semaforo of the API schemas
    AMBAR = "ambar"


def _report_events(semaforo="ambar", resumen="Viable con reservas."):
    return [
        {"type": "datos", "datos_distrito": {"nom_districte": "Eixample"}, "respuesta_legal": "x"},
        {"type": "token", "text": "Hola"},
        {"type": "token", "text": " mundo"},
        {"type": "done", "semaforo": semaforo, "resumen": resumen},
    ]


def test_build_note_accepts_an_enum_semaforo():
    assert "ambar" in rc.build_note(semaforo=_Semaforo.AMBAR)
    assert "Semaforo" not in rc.build_note(semaforo=_Semaforo.AMBAR)


def test_track_report_passes_every_event_unchanged(tmp_path):
    events = _report_events()
    result = list(rc.track_report(iter(events), "marvin:1", history_dir=tmp_path))
    assert result == events


def test_track_report_saves_the_note(tmp_path):
    stream = rc.track_report(
        _report_events(),
        "marvin:1",
        direccion="Carrer de Mallorca 401",
        zona_pgm="Zona 13",
        history_dir=tmp_path,
    )
    list(stream)
    note = rc.recall("marvin:1")
    assert "Eixample" in note
    assert "Carrer de Mallorca 401" in note
    assert "Zona 13" in note
    assert "ambar" in note
    assert "Viable con reservas." in note


def test_track_report_saves_the_typed_text_in_the_history(tmp_path):
    stream = rc.track_report(
        _report_events(),
        "marvin:1",
        user_text="quiero abrir un bar en Mallorca 401",
        history_dir=tmp_path,
    )
    list(stream)
    content = (tmp_path / "marvin:1.txt").read_text(encoding="utf-8")
    assert "USUARIO:\nquiero abrir un bar en Mallorca 401" in content
    assert "ASISTENTE:\nInforme de viabilidad (ambar): Viable con reservas." in content


def test_track_report_uses_a_label_for_a_form_report(tmp_path):
    list(rc.track_report(_report_events(), "marvin:1", zona_pgm="Zona 13", history_dir=tmp_path))
    content = (tmp_path / "marvin:1.txt").read_text(encoding="utf-8")
    assert "USUARIO:\nInforme de Eixample · Zona 13" in content


def test_track_report_without_a_thread_saves_nothing(tmp_path):
    events = _report_events()
    for thread_id in (None, "", "  "):
        assert list(rc.track_report(iter(events), thread_id, history_dir=tmp_path)) == events
    assert list(tmp_path.iterdir()) == []
    assert rc.recall("marvin:1") is None


def test_track_report_saves_before_the_done_event_is_sent(tmp_path):
    generator = rc.track_report(_report_events(), "marvin:1", history_dir=tmp_path)
    for event in generator:
        if event["type"] == "done":
            # the consumer has just received `done`: the note and the file must already exist
            assert rc.recall("marvin:1") is not None
            assert (tmp_path / "marvin:1.txt").exists()


def test_track_report_saves_nothing_if_the_client_leaves_early(tmp_path):
    generator = rc.track_report(_report_events(), "marvin:1", history_dir=tmp_path)
    next(generator)
    next(generator)
    generator.close()
    assert rc.recall("marvin:1") is None
    assert list(tmp_path.iterdir()) == []


def test_track_report_saves_nothing_if_the_stream_ends_with_an_error(tmp_path):
    events = [{"type": "datos", "datos_distrito": {}}, {"type": "error", "detail": "fallo"}]
    assert list(rc.track_report(events, "marvin:1", history_dir=tmp_path)) == events
    assert rc.recall("marvin:1") is None


def test_track_report_never_breaks_the_report(tmp_path):
    # odd events: not a dict, no "type", datos without a dict, done without fields
    events = ["texto", {"sin": "tipo"}, {"type": "datos", "datos_distrito": None}, {"type": "done"}]
    assert list(rc.track_report(events, "marvin:1", history_dir=tmp_path)) == events


def test_track_report_with_an_unsafe_thread_id_still_passes_the_events(tmp_path):
    events = _report_events()
    assert list(rc.track_report(iter(events), "../fuera", history_dir=tmp_path)) == events
    assert list(tmp_path.iterdir()) == []
