"""
==============================================================================
API ROUTER: CHAT HISTORY
==============================================================================
File: backend/api/routers/history.py

Endpoint for retrieving conversation history files from REPO_ROOT/chat_history.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status

from backend.api.schemas.history import HistoryRequest, HistoryResponse
from backend.observability import get_logger

logger = get_logger("api.history")

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_HISTORY_DIR = REPO_ROOT / "chat_history"

router = APIRouter(prefix="/api", tags=["history"])


def resolve_chat_history_file(thread_id: str) -> Path:
    """
    Resolves the history file in CHAT_HISTORY_DIR named after thread_id ({thread_id}.txt).

    Validates against directory traversal and ensures the file exists.
    """
    clean_id = (thread_id or "").strip()
    if not clean_id:
        raise HTTPException(
            status_code=422,
            detail="Field 'thread_id' is required.",
        )

    target_file = (CHAT_HISTORY_DIR / f"{clean_id}.txt").resolve()

    # Prevent directory traversal
    if not target_file.is_relative_to(CHAT_HISTORY_DIR.resolve()):
        logger.warning("Attempted path traversal with thread_id='%s'", thread_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid thread_id parameter.",
        )

    if not target_file.is_file():
        logger.info("History file for thread '%s' not found at %s", clean_id, target_file)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"History file for thread '{clean_id}' not found.",
        )

    return target_file


@router.get(
    "/gethistory",
    response_model=HistoryResponse,
    name="gethistory",
    operation_id="gethistory",
    summary="Get conversation chat history",
    description="Responds with the file in directory chat_history named after thread_id.",
)
def gethistory(
    thread_id: str = Query(
        ...,
        min_length=1,
        description="files named after it in REPO_ROOT/chat_history contain thread history",
    ),
) -> HistoryResponse:
    clean_id = thread_id.strip()
    target_file = resolve_chat_history_file(clean_id)

    try:
        content = target_file.read_text(encoding="utf-8")
    except Exception as exc:
        logger.exception("Failed to read chat history file %s: %s", target_file, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error reading chat history file.",
        )

    return HistoryResponse(
        thread_id=clean_id,
        content=content,
        filename=target_file.name,
    )


@router.get(
    "/gethistory/{thread_id:path}",
    response_model=HistoryResponse,
    include_in_schema=False,
)
def gethistory_by_path(thread_id: str) -> HistoryResponse:
    return gethistory(thread_id=thread_id)


@router.post(
    "/gethistory",
    response_model=HistoryResponse,
    include_in_schema=False,
)
def gethistory_post(payload: HistoryRequest) -> HistoryResponse:
    return gethistory(thread_id=payload.thread_id)
