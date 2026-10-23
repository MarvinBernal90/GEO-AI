"""
==============================================================================
API ROUTER: CONVERSATIONAL AGENT ORCHESTRATOR (SSE)
==============================================================================
File: backend/api/routers/chat.py

The master endpoint for the conversational chat (`/api/chat/informe/stream`).
Acts as a State Machine connecting NLU, GIS, and RAG into a single SSE stream.

Architectural Note:
This is NOT an autonomous agent. It translates free text into structured parameters
and routes them through the pre-existing, tested pipeline.
It strictly enforces Human-in-the-Loop: If intent or geolocation cannot be resolved
with certainty, it yields an 'aclaracion' event to trigger the manual UI form,
never guessing.

One chat for everything: when the request carries a `thread_id` and the message has no
address or district (for example "what licence do I need for a terrace?"), the message is
handed to the conversational assistant instead of asking for clarification. A `modo`
event announces it, so the UI knows the answer is free text and not a report.

Metrics: every step of the flow is a span (NLU, geocoding, zone lookup, then the
report pipeline or the assistant). Spans only hold sizes and yes/no results, never the
user text.
"""

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.api.deps import get_session
from backend.api.routers.assistant import stream_assistant
from backend.api.routers.reports import _json_default
from backend.api.schemas.chat import ChatRequest
from backend.geo.amb_identify import identificar_zona_pgm
from backend.geo.geocoding import geocodificar_direccion, resolver_distrito_desde_suburb
from backend.ia.agent import generar_informe_viabilidad_stream
from backend.ia.chat_intent import extraer_intencion
from backend.observability.metrics import set_output, span
from backend.observability.metrics.streaming import mark_stream_events, new_collector, stream_with_metrics

logger = logging.getLogger("geoyield_api")

router = APIRouter(prefix="/api", tags=["chat"])


def _evento_aclaracion(mensaje: str, **kwargs) -> dict:
    """Helper to construct standard fallback events for the UI."""
    return {"type": "aclaracion", "mensaje": mensaje, **kwargs}


def _si_no(valor) -> str:
    """Turns any value into 'yes' or 'no', so a span never keeps the value itself."""
    return "yes" if valor else "no"


def _responder_con_asistente(mensaje: str, thread_id: str):
    """Hands a message that has no place in it to the conversational assistant."""
    yield {"type": "modo", "modo": "asistente"}
    yield from stream_assistant(mensaje, thread_id)


def _procesar_chat(mensaje: str, db: Session, thread_id: str | None = None):
    """
    Generator function representing the State Machine of the conversational flow.
    """
    # ------------------------------------------------------------------------
    # STEP 1: Natural Language Understanding (NLU)
    # ------------------------------------------------------------------------
    with span("agent", "nlu_intent", input_summary=f"{len(mensaje)} chars"):
        intencion = extraer_intencion(mensaje)
        set_output(
            f"address {_si_no(intencion['direccion'])}, "
            f"district {_si_no(intencion['distrito_mencionado'])}, "
            f"question {_si_no(intencion['pregunta_especifica'])}"
        )
    direccion = intencion["direccion"]
    distrito_mencionado = intencion["distrito_mencionado"]
    pregunta_especifica = intencion["pregunta_especifica"]

    if direccion is None:
        # Fallback 1A: User gave a general district but no address ("I know Les Corts...")
        if distrito_mencionado is not None:
            codi_districte = resolver_distrito_desde_suburb(distrito_mencionado)
            if codi_districte is not None:
                yield _evento_aclaracion(
                    f"Localicé el distrito de {distrito_mencionado}, pero sin una dirección exacta "
                    "no puedo determinar automáticamente la zona urbanística -- selecciónala tú abajo "
                    "para generar el informe.",
                    codi_districte=codi_districte,
                )
                return

        # Fallback 1B: no location found. With a thread, the assistant answers general
        # questions (licences, schedules...); without one, we ask for clarification.
        if thread_id is not None:
            yield from _responder_con_asistente(mensaje, thread_id)
            return

        yield _evento_aclaracion(
            "No he podido identificar una dirección ni un distrito de Barcelona en tu mensaje. "
            "¿Puedes indicarme la calle, o al menos en qué distrito te gustaría abrir?"
        )
        return

    # ------------------------------------------------------------------------
    # STEP 2: Geospatial Pipeline (Text to Lat/Lon -> PGM Zone)
    # ------------------------------------------------------------------------
    with span("external", "geocode_address", input_summary=f"{len(direccion)} chars"):
        geo = geocodificar_direccion(direccion)
        set_output("found" if geo else "not found")

    if geo is None:
        # Fallback 2: Address not found by Nominatim
        yield _evento_aclaracion(
            f"No encontré '{direccion}' dentro de Barcelona. "
            "Puedes revisar la dirección o seleccionar distrito y zona manualmente abajo.",
            direccion_buscada=direccion,
        )
        return

    zona = None
    if geo["codi_districte"]:
        with span("external", "identify_pgm_zone"):
            zona = identificar_zona_pgm(geo["lat"], geo["lon"])
            set_output("zone found" if zona else "no zone")
    zona_pgm = zona["zona_pgm"] if zona else None

    if geo["codi_districte"] is None or zona_pgm is None:
        # Fallback 3: Graceful Degradation (Found Lat/Lon, but GIS failed)
        yield _evento_aclaracion(
            "Encontré la dirección, pero no pude determinar "
            + ("el distrito" if geo["codi_districte"] is None else "la zona urbanística")
            + " con precisión. Complétalo tú abajo para generar el informe.",
            direccion_encontrada=geo["direccion_encontrada"],
            lat=geo["lat"],
            lon=geo["lon"],
            codi_districte=geo["codi_districte"],
            zona_pgm=zona_pgm,
        )
        return

    # ------------------------------------------------------------------------
    # STEP 3: RAG Pre-Flight Event (UI Synchronization)
    # ------------------------------------------------------------------------
    # Yields the location to the Frontend immediately so the Map can pan/zoom
    # while the heavy LLM RAG engine boots up.
    yield {
        "type": "ubicacion",
        "direccion_encontrada": geo["direccion_encontrada"],
        "lat": geo["lat"],
        "lon": geo["lon"],
        "codi_districte": geo["codi_districte"],
        "zona_pgm": zona_pgm,
    }

    # ------------------------------------------------------------------------
    # STEP 4: RAG Legal Assessment (Streaming)
    # ------------------------------------------------------------------------

    yield from generar_informe_viabilidad_stream(
        db, codi_districte=geo["codi_districte"], zona_pgm=zona_pgm, pregunta_especifica=pregunta_especifica
    )


def _procesar_chat_medido(mensaje: str, db: Session, thread_id: str | None = None):
    """
    The same flow as `_procesar_chat`, inside one root span so every step nests under it.
    The root span also gets the time to the first token and any `error` event.
    """
    with span("agent", "chat_pipeline", input_summary=f"{len(mensaje)} chars") as root:
        yield from mark_stream_events(_procesar_chat(mensaje, db, thread_id), root)


@router.post("")
def chat_informe_stream(payload: ChatRequest, db: Session = Depends(get_session)):
    """SSE Endpoint. Serializes the generator chunks into standard SSE format."""
    # Created here, inside the endpoint, because the trace id of the middleware is visible here.
    collector = new_collector()

    def eventos():
        try:
            flujo = _procesar_chat_medido(payload.mensaje, db, payload.thread_id)
            # stream_with_metrics keeps the whole flow in one context, sends the live
            # metrics events and saves the request when the stream ends.
            for evento in stream_with_metrics(flujo, collector, route="/api/chat/informe/stream"):
                # Reuses _json_default from informes.py to handle Decimal database types
                yield f"data: {json.dumps(evento, ensure_ascii=False, default=_json_default)}\n\n"
        except Exception:
            logger.exception(f"Error procesando el chat para el mensaje: {payload.mensaje!r}")
            error = {"type": "error", "detail": "No se pudo procesar tu mensaje. Inténtalo de nuevo."}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream")
