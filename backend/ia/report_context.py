"""
==============================================================================
REPORT CONTEXT: SHORT NOTE OF THE LAST REPORT OF EACH CONVERSATION
==============================================================================
File: backend/ia/report_context.py

The report pipeline and the conversational assistant are two separate flows: the
assistant only knows what happened inside its own conversation thread. This module
keeps a short note about the last viability report of each thread, so the assistant
can understand follow-up questions such as "and what rules apply there?".

`track_report` wraps the event stream of a report. It does not change any event: when
the report ends, it saves the note and adds the report to the history file of the
conversation, so it can be listed and resumed like any other conversation.

The notes live in the memory of the process: they are lost on restart and they are
not shared between workers. That is enough for the MVP. A note never stores the text
the user typed, only the address found, the district, the zone, the traffic light and
the summary of the verdict.

Every public function never raises: the context is an extra and must not break a report.
"""

import logging
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any

from backend.ia.chat_history import append_history

logger = logging.getLogger("geoyield_report_context")

MAX_THREADS = 200  # oldest notes are dropped first, so the memory cannot grow forever
MAX_NOTE_CHARS = 600

_notes: OrderedDict[str, str] = OrderedDict()
_lock = Lock()


def _clean(value: object) -> str:
    """Text of a value without surrounding spaces. Empty string if it is None or blank."""
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return ""
    return str(value).strip()


def build_note(
    *,
    direccion: object = None,
    distrito: object = None,
    zona_pgm: object = None,
    semaforo: object = None,
    resumen: object = None,
) -> str:
    """
    Build the note text from the data of a report. Missing values are skipped.
    Returns an empty string if there is nothing to say. The note is written in Spanish
    because it is read by the assistant model, which answers in Spanish.
    """
    try:
        labels = (
            ("dirección", direccion),
            ("distrito", distrito),
            ("zona urbanística PGM", zona_pgm),
            ("semáforo de viabilidad", semaforo),
            ("resumen del veredicto", resumen),
        )
        parts = [f"{label}: {text}" for label, value in labels if (text := _clean(value))]
        if not parts:
            return ""
        note = "Último informe de viabilidad generado en esta conversación -> " + "; ".join(parts)
        if len(note) > MAX_NOTE_CHARS:
            note = note[: MAX_NOTE_CHARS - 3].rstrip() + "..."
        return note
    except Exception:
        logger.warning("Could not build the report note", exc_info=True)
        return ""


def remember(thread_id: object, note: object) -> bool:
    """Save the note of the last report of a thread. Returns True if it was saved."""
    try:
        if not isinstance(thread_id, str) or not thread_id.strip():
            return False
        text = _clean(note)
        if not text:
            return False
        with _lock:
            _notes[thread_id] = text
            _notes.move_to_end(thread_id)
            while len(_notes) > MAX_THREADS:
                _notes.popitem(last=False)
        return True
    except Exception:
        logger.warning("Could not save the report note", exc_info=True)
        return False


def recall(thread_id: object) -> str | None:
    """Note of the last report of a thread, or None if there is not one."""
    try:
        if not isinstance(thread_id, str):
            return None
        with _lock:
            return _notes.get(thread_id)
    except Exception:
        logger.warning("Could not read the report note", exc_info=True)
        return None


def forget(thread_id: object) -> None:
    """Remove the note of a thread, if any."""
    try:
        if isinstance(thread_id, str):
            with _lock:
                _notes.pop(thread_id, None)
    except Exception:
        logger.warning("Could not remove the report note", exc_info=True)


def clear_all() -> None:
    """Remove every note. Meant for tests."""
    with _lock:
        _notes.clear()


def _history_question(user_text: object, distrito: str, zona_pgm: str) -> str:
    """Question line of the history: what the user typed, or a label for a form report."""
    typed = _clean(user_text)
    if typed:
        return typed
    label = " · ".join(part for part in (distrito, zona_pgm) if part)
    return f"Informe de {label}" if label else "Informe de viabilidad"


def _history_answer(semaforo: str, resumen: str) -> str:
    """Answer line of the history: the verdict of the report, short."""
    head = f"Informe de viabilidad ({semaforo})" if semaforo else "Informe de viabilidad"
    return f"{head}: {resumen}" if resumen else head


def _save_report(
    thread_id: str,
    done_event: dict[str, Any],
    *,
    user_text: object,
    direccion: object,
    distrito: str,
    zona_pgm: object,
    history_dir: Path | None,
) -> None:
    """Save the note and the history lines of a finished report."""
    semaforo = _clean(done_event.get("semaforo"))
    resumen = _clean(done_event.get("resumen"))
    zona = _clean(zona_pgm)
    remember(
        thread_id,
        build_note(direccion=direccion, distrito=distrito, zona_pgm=zona, semaforo=semaforo, resumen=resumen),
    )
    append_history(
        thread_id,
        _history_question(user_text, distrito, zona),
        _history_answer(semaforo, resumen),
        history_dir=history_dir,
    )


def track_report(
    stream: Iterable[dict[str, Any]],
    thread_id: object,
    *,
    user_text: object = None,
    direccion: object = None,
    zona_pgm: object = None,
    history_dir: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Pass the events of a report stream through, unchanged and in the same order.

    Without a thread id (the user is not logged in) it does nothing. When the `done` event
    arrives, the note and the history are saved BEFORE the event is sent on, so nothing is
    lost if the client leaves right after it. If the stream fails or is closed before the
    `done` event, nothing is saved. A problem while saving never reaches the report.

    Args:
        stream: events of `generar_informe_viabilidad_stream` ("datos", "token", "done").
        thread_id: conversation thread, or None.
        user_text: what the user typed. None for a form report: a label is used instead.
        direccion: address found, if the report came from an address.
        zona_pgm: PGM zone of the report.
        history_dir: folder of the history files (tests use a temporary one).
    """
    track = isinstance(thread_id, str) and bool(thread_id.strip())
    distrito = ""
    for event in stream:
        if track and isinstance(event, dict):
            try:
                kind = event.get("type")
                if kind == "datos":
                    datos = event.get("datos_distrito")
                    if isinstance(datos, dict):
                        distrito = _clean(datos.get("nom_districte"))
                elif kind == "done":
                    _save_report(
                        str(thread_id),
                        event,
                        user_text=user_text,
                        direccion=direccion,
                        distrito=distrito,
                        zona_pgm=zona_pgm,
                        history_dir=history_dir,
                    )
            except Exception:
                logger.warning("Could not save the report context", exc_info=True)
        yield event
