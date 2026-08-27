"""
Agente orquestador de viabilidad de locales de hostelería en Barcelona.

Combina en un grafo de LangGraph dos fuentes de información en paralelo
-- datos socioeconómicos del distrito (renta, afluencia peatonal,
competencia) y normativa legal aplicable (zona PGM más leyes generales)
-- y las sintetiza en un informe final con un veredicto tipo semáforo
(verde, ámbar, rojo).

Funciones principales:
- generar_informe_viabilidad: punto de entrada público; genera el informe completo para un distrito y una zona PGM dados.
- build_agent_graph: construye el grafo de LangGraph (nodos en paralelo + síntesis final).
- zonas_pgm_disponibles: lista las zonas PGM que tienen normativa cargada en la base de datos.
"""

import logging
from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.rag.embeddings import EmbeddingFunction, embed_texts
from backend.rag.query_engine import DEFAULT_MODEL, generate_answer

logger = logging.getLogger("geoyield_agent")

Semaforo = Literal["verde", "ambar", "rojo"]

ZONA_PGM_NOMBRES = {
    "nucli_antic": "Nucli antic / Centre històric (p. ej. Ciutat Vella)",
    "densificacio_urbana": "Densificació urbana (p. ej. gran part de l'Eixample)",
    "industrial": "Zona industrial",
}


def zonas_pgm_disponibles(session: Session) -> list[str]:
    rows = session.execute(text("SELECT DISTINCT zona_pgm FROM legal_chunks WHERE zona_pgm IS NOT NULL")).all()
    return sorted(r[0] for r in rows)


class ViabilityState(TypedDict):
    codi_districte: int
    zona_pgm: str
    datos_distrito: dict | None
    respuesta_legal: dict | None
    informe: dict | None


@dataclass
class ViabilityReport:
    semaforo: Semaforo
    resumen: str
    datos_distrito: dict
    respuesta_legal: str
    articulos_citados: list[str]


SYNTHESIS_SYSTEM_PROMPT = """Eres un consultor de viabilidad para negocios de hostelería (bares, restaurantes) en Barcelona.

Recibes dos bloques de información ya verificados:
1. Datos socioeconómicos del distrito (renta, afluencia peatonal, saturación de competencia, y un índice de oportunidad de 0 a 100).
2. Una respuesta legal ya generada, que puede combinar normativa específica de la zona urbanística Y normativa general (horarios, consumo, etc.) que aplica en toda la ciudad, citando el artículo y la norma correspondiente.

Tu tarea es sintetizar AMBOS en un informe de viabilidad breve para el usuario final (el dueño del negocio, no un desarrollador). Estructura tu respuesta EXACTAMENTE así:

Primera línea: una sola palabra, en mayúsculas, entre VERDE, AMBAR o ROJO -- nada más en esa línea.
    - ROJO: la normativa prohíbe explícitamente el uso, o el contexto legal no da certeza suficiente.
    - AMBAR: el uso está permitido, pero con restricciones relevantes o riesgos socioeconómicos notables.
    - VERDE: el uso está permitido y las condiciones socioeconómicas son favorables.

Después, un resumen de 3-5 frases dirigido al dueño del negocio: explica el veredicto, cita la normativa relevante (zona y/o general), y menciona el dato socioeconómico más relevante.

No inventes información que no esté en los dos bloques que recibes. Si falta algún dato, dilo explícitamente en vez de rellenar el hueco."""


def _construir_pregunta_legal(zona_pgm: str) -> str:
    nombre_zona = ZONA_PGM_NOMBRES.get(zona_pgm, zona_pgm)
    return f"¿Se permite abrir un bar o restaurante (uso comercial/hostelería) en una zona de tipo '{nombre_zona}'? ¿Con qué condiciones o límites?"


def build_agent_graph(
    session: Session,
    embed_fn: EmbeddingFunction = embed_texts,
    llm_client=None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
):
    def datos_socioeconomicos(state: ViabilityState) -> dict:
        with Session(session.get_bind()) as node_session:
            row = node_session.execute(
                text("SELECT * FROM district_scorecard WHERE codi_districte = :codi"),
                {"codi": state["codi_districte"]},
            ).mappings().first()
        if row is None:
            logger.warning(f"No hay datos en district_scorecard para el distrito {state['codi_districte']}")
            return {"datos_distrito": None}
        return {"datos_distrito": dict(row)}

    def normativa_legal(state: ViabilityState) -> dict:
        with Session(session.get_bind()) as node_session:
            pregunta = _construir_pregunta_legal(state["zona_pgm"])
            resultado = generate_answer(
                node_session, pregunta, embed_fn=embed_fn, llm_client=llm_client,
                model=model, zona_pgm=state["zona_pgm"],
            )
        return {"respuesta_legal": resultado}

    def sintesis_final(state: ViabilityState) -> dict:
        from backend.rag.gemini_adapter import GeminiAsAnthropicAdapter

        client = llm_client if llm_client is not None else GeminiAsAnthropicAdapter()
        datos = state["datos_distrito"]
        legal = state["respuesta_legal"]

        if datos is None:
            bloque_datos = "No hay datos socioeconómicos disponibles para este distrito."
        else:
            bloque_datos = (
                f"Distrito: {datos['nom_districte']}\n"
                f"Renta media: {datos['renta_media']}€\n"
                f"Afluencia peatonal diaria: {datos['daily_foot_traffic']}\n"
                f"Competidores de hostelería en el distrito: {datos['total_competitors']}\n"
                f"Índice de oportunidad (0-100): {datos['opportunity_score']}"
            )

        articulos_citados = [c.numero_articulo for c in legal["chunks_recuperados"]]
        bloque_legal = f"{legal['respuesta']}\n\n(Artículos consultados: {', '.join(articulos_citados) or 'ninguno'})"
        mensaje = f"DATOS SOCIOECONÓMICOS:\n{bloque_datos}\n\nRESPUESTA LEGAL:\n{bloque_legal}"

        response = client.messages.create(
            model=model, max_tokens=max_tokens, system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mensaje}],
        )
        texto = response.content[0].text.strip()
        primera_linea, *resto = texto.splitlines()
        semaforo_texto = primera_linea.strip().upper()
        semaforo: Semaforo = semaforo_texto.lower() if semaforo_texto in ("VERDE", "AMBAR", "ROJO") else "ambar"
        if semaforo_texto not in ("VERDE", "AMBAR", "ROJO"):
            logger.warning(f"El LLM no devolvió un semáforo reconocible en la primera línea: {primera_linea!r}")
            resumen = texto
        else:
            resumen = "\n".join(resto).strip()

        informe = ViabilityReport(
            semaforo=semaforo, resumen=resumen, datos_distrito=datos or {},
            respuesta_legal=legal["respuesta"], articulos_citados=articulos_citados,
        )
        return {"informe": informe.__dict__}

    graph = StateGraph(ViabilityState)
    graph.add_node("datos_socioeconomicos", datos_socioeconomicos)
    graph.add_node("normativa_legal", normativa_legal)
    graph.add_node("sintesis_final", sintesis_final)
    graph.add_edge(START, "datos_socioeconomicos")
    graph.add_edge(START, "normativa_legal")
    graph.add_edge("datos_socioeconomicos", "sintesis_final")
    graph.add_edge("normativa_legal", "sintesis_final")
    graph.add_edge("sintesis_final", END)
    return graph.compile()


def generar_informe_viabilidad(
    session: Session,
    codi_districte: int,
    zona_pgm: str,
    embed_fn: EmbeddingFunction = embed_texts,
    llm_client=None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
) -> dict:
    app = build_agent_graph(session, embed_fn=embed_fn, llm_client=llm_client, model=model, max_tokens=max_tokens)
    resultado = app.invoke({"codi_districte": codi_districte, "zona_pgm": zona_pgm})
    return resultado["informe"]