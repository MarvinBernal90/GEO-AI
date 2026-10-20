"""
==============================================================================
API ROUTER: CONVERSATIONAL ASSISTANT STREAM (SSE)
==============================================================================
File: backend/api/routers/assistant.py

Streaming endpoint for the ReAct chat assistant.
Invokes the assistant via request() and streams token events to the frontend
for real-time display in the 'response-output' text area.
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.api.schemas.assistant import AssistantRequest
from backend.ia.chat import request
from backend.observability import get_logger

logger = get_logger("api.assistant")

router = APIRouter(prefix="/api", tags=["assistant"])


@router.post("/assistant")
def assistant_stream(payload: AssistantRequest):
    """
    SSE Endpoint for the conversational assistant.
    Receives thread_id and prompt, delegates to the ReAct agent in streaming mode,
    and yields SSE formatted token events.
    """
    logger.info("Starting assistant stream for thread_id=%s", payload.thread_id)

    def eventos():
        try:
            for evento in request(payload.message, thread=payload.thread_id, stream=True):
                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("Error during assistant streaming: %s", exc)
            error_event = {"type": "error", "detail": "No se pudo procesar tu consulta. Inténtalo de nuevo."}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream")
