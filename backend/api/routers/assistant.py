"""
==============================================================================
API ROUTER: CONVERSATIONAL ASSISTANT STREAM (SSE)
==============================================================================
File: backend/api/routers/assistant.py

Streaming endpoint for the ReAct chat assistant.
Invokes the assistant via request() and streams token events to the frontend
for real-time display in the 'response-output' text area.

`stream_assistant` is also used by the chat router, which hands over the messages
that have no place in them (see routers/chat.py).

Metrics: the whole stream is one span (`assistant_pipeline`) and the live metrics
events travel in the same stream. Spans keep only sizes, never the text.
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.api.schemas.assistant import AssistantRequest
from backend.ia.chat import request
from backend.observability import get_logger
from backend.observability.metrics import span
from backend.observability.metrics.streaming import mark_stream_events, new_collector, stream_with_metrics

logger = get_logger("api.assistant")

router = APIRouter(prefix="/api", tags=["assistant"])


def stream_assistant(message: str, thread_id: str):
    """
    The assistant stream inside its own span.

    `request()` does not raise on errors: it yields an `error` event. `mark_stream_events`
    marks the span as failed when it sees one, and stores the time to the first token.
    """
    with span("agent", "assistant_pipeline", input_summary=f"{len(message)} chars") as root:
        yield from mark_stream_events(request(message, thread=thread_id, stream=True), root)


@router.post("/assistant")
def assistant_stream(payload: AssistantRequest):
    """
    SSE Endpoint for the conversational assistant.
    Receives thread_id and prompt, delegates to the ReAct agent in streaming mode,
    and yields SSE formatted token events.
    """
    logger.info("Starting assistant stream for thread_id=%s", payload.thread_id)
    # Created here, inside the endpoint, because the trace id of the middleware is visible here.
    collector = new_collector()

    def eventos():
        try:
            flujo = stream_assistant(payload.message, payload.thread_id)
            for evento in stream_with_metrics(flujo, collector, route="/api/assistant"):
                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("Error during assistant streaming: %s", exc)
            error_event = {"type": "error", "detail": "No se pudo procesar tu consulta. Inténtalo de nuevo."}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream")
