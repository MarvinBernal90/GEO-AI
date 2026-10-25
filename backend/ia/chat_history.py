"""
==============================================================================
CHAT HISTORY FILES: SAFE THREAD IDS AND SAFE WRITES
==============================================================================
File: backend/ia/chat_history.py

The assistant keeps a text history per conversation in chat_history/{thread_id}.txt.
The thread id comes from the client, so it must never decide where a file is written.

Rules for a safe thread id: letters, digits, underscore, dot, @, colon, hyphen and
space; no slashes, no "..", no leading dot, no leading or trailing spaces; 1-150 chars.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger("geoyield_history")

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_HISTORY_DIR = REPO_ROOT / "chat_history"

# `\w` also accepts accented letters, so names like "Ana López" keep working.
_THREAD_ID_RE = re.compile(r"[\w.@: -]{1,150}")


def is_valid_thread_id(thread_id: object) -> bool:
    """True if the thread id can safely be used as a file name."""
    if not isinstance(thread_id, str):
        return False
    if _THREAD_ID_RE.fullmatch(thread_id) is None:
        return False
    return thread_id == thread_id.strip() and ".." not in thread_id and not thread_id.startswith(".")


def history_path(thread_id: str, history_dir: Path | None = None) -> Path:
    """
    Path of the history file of a thread. Raises ValueError if the thread id is not
    safe or if the final path would be outside the history folder.
    """
    if not is_valid_thread_id(thread_id):
        raise ValueError("Invalid thread_id.")
    base = (history_dir or CHAT_HISTORY_DIR).resolve()
    target = (base / f"{thread_id}.txt").resolve()
    if not target.is_relative_to(base):
        raise ValueError("Invalid thread_id.")
    return target


def append_history(
    thread_id: str,
    user_text: str,
    assistant_text: str,
    history_dir: Path | None = None,
) -> bool:
    """
    Add one question and its answer to the history of a thread.

    Returns True if saved. It NEVER raises: a history problem must not break an answer.
    The log never includes the text of the conversation.
    """
    try:
        target = history_path(thread_id, history_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as history_file:
            history_file.write(f"USUARIO:\n{user_text}\n\nASISTENTE:\n{assistant_text}\n\n")
        return True
    except Exception:
        logger.warning("Could not save the chat history", exc_info=True)
        return False
