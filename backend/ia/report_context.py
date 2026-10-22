"""
==============================================================================
REPORT CONTEXT: SHORT NOTE OF THE LAST REPORT OF EACH CONVERSATION
==============================================================================
File: backend/ia/report_context.py

The report pipeline and the conversational assistant are two separate flows: the
assistant only knows what happened inside its own conversation thread. This module
keeps a short note about the last viability report of each thread, so the assistant
can understand follow-up questions such as "and what rules apply there?".

The notes live in the memory of the process: they are lost on restart and they are
not shared between workers. That is enough for the MVP. A note never stores the text
the user typed, only the address found, the district, the zone, the traffic light and
the summary of the verdict.

Every public function never raises: the context is an extra and must not break a report.
"""

import logging
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger("geoyield_report_context")

MAX_THREADS = 200  # oldest notes are dropped first, so the memory cannot grow forever
MAX_NOTE_CHARS = 600

_notes: OrderedDict[str, str] = OrderedDict()
_lock = Lock()


def _clean(value: object) -> str:
    """Text of a value without surrounding spaces. Empty string if it is None or blank."""
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
