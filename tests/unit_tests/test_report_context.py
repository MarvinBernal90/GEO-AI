"""Unit tests for backend/ia/report_context.py (pure Python, no database, no AWS)."""

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
