"""
==============================================================================
API ROUTER: CONVERSATIONAL ASSISTANT STREAM (SSE)
==============================================================================
File: backend/api/routers/assistant.py

Streaming endpoint for the ReAct chat assistant.
Invokes the assistant via request() and streams token events to the frontend
for real-time display in the 'response-output' text area.

Metrics: the whole stream is one root span (`assistant_pipeline`) and the live
metrics events travel in the same stream. Spans keep only sizes, never the text.
"""

import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.api.schemas.assistant import AssistantRequest
from backend.ia.chat import request
from backend.observability import get_logger
from backend.observability.metrics import span
from backend.observability.metrics.streaming import new_collector, stream_with_metrics

logger = get_logger("api.assistant")

router = APIRouter(prefix="/api", tags=["assistant"])


def _flujo_medido(payload: AssistantRequest):
    """
    The assistant stream inside one root span.

    - The time to the first token is stored on the root span (the assistant does not
      go through our LLM adapter, so nobody else measures it).
    - `request()` does not raise on errors: it yields an `error` event. We mark the
      root span as failed when we see one, so the request is not saved as ok.
    """
    with span("agent", "assistant_pipeline", input_summary=f"{len(payload.message)} chars") as root:
        started = time.perf_counter()
        for evento in request(payload.message, thread=payload.thread_id, stream=True):
            if root is not None:
                tipo = evento.get("type")
                if tipo == "token" and root.ttft_ms is None:
                    root.ttft_ms = round((time.perf_counter() - started) * 1000, 2)
                elif tipo == "error":
                    root.status = "error"
                    root.error = "StreamError"
            yield evento


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
            for evento in stream_with_metrics(_flujo_medido(payload), collector, route="/api/assistant"):
                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("Error during assistant streaming: %s", exc)
            error_event = {"type": "error", "detail": "No se pudo procesar tu consulta. Inténtalo de nuevo."}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream")
