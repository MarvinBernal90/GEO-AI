"""
==============================================================================
API ROUTER: USER AUTHENTICATION & LOGIN
==============================================================================
File: backend/api/routers/login.py

Validates user identity against the 'users' table in the database and returns
available conversation sessions for the user, using the initial message of each
thread as its title.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.api.deps import get_session
from backend.api.schemas.login import ConversationOut, LoginRequest, LoginResponse
from backend.db.models import User
from backend.ia.chat import checkpointer
from backend.observability import get_logger, log_event

logger = get_logger("api.login")

router = APIRouter(prefix="/api", tags=["login"])


def _extract_message_text(message: Any) -> str:
    """Extracts plain text content from a LangChain or serialized message."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(parts).strip()
    return str(content).strip() if content is not None else ""


def get_user_conversations(
    username: str,
    db: Session,
    active_checkpointer: Any = None,
) -> list[ConversationOut]:
    """
    Finds all thread_ids starting with username in checkpoints,
    retrieves the first message for each thread, and uses it as the conversation title.
    """
    cp = active_checkpointer if active_checkpointer is not None else checkpointer

    try:
        query = text(
            "SELECT DISTINCT thread_id FROM checkpoints "
            "WHERE thread_id LIKE :prefix "
            "ORDER BY thread_id ASC"
        )
        rows = db.execute(query, {"prefix": f"{username}%"}).fetchall()
        thread_ids = [r[0] for r in rows if r[0].startswith(username)]
    except Exception as exc:
        logger.warning("Could not query thread IDs from checkpoints table: %s", exc)
        return []

    conversations: list[ConversationOut] = []
    for tid in thread_ids:
        title = ""
        if cp is not None:
            try:
                cp_tuple = cp.get_tuple({"configurable": {"thread_id": tid}})
                if cp_tuple and cp_tuple.checkpoint:
                    msgs = cp_tuple.checkpoint.get("channel_values", {}).get("messages", [])
                    if msgs:
                        title = _extract_message_text(msgs[0])
            except Exception as exc:
                logger.warning("Error loading checkpoint tuple for thread '%s': %s", tid, exc)

        if not title:
            title = f"Conversación {tid}"

        conversations.append(ConversationOut(id=tid, title=title))

    return conversations


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Valida un usuario y devuelve sus conversaciones",
    description="Comprueba si el usuario existe en la tabla 'users' y responde con su lista de conversaciones.",
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_session),
) -> LoginResponse:
    username = payload.user.strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario no puede estar vacío.",
        )

    user_record = db.execute(select(User).where(User.user == username)).scalar_one_or_none()
    if not user_record:
        logger.warning("Intento de login fallido para usuario inexistente: %s", username)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario '{username}' no encontrado en la base de datos.",
        )

    conversations = get_user_conversations(username=user_record.user, db=db)

    log_event(
        logger,
        "INFO",
        f"User '{username}' logged in successfully with {len(conversations)} conversations",
        event="user.login.success",
        user=username,
        conversations_count=len(conversations),
    )

    return LoginResponse(
        user=user_record.user,
        conversations=conversations,
    )

