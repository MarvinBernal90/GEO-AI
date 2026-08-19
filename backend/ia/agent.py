"""
Agente orquestador de viabilidad (Fase 3).

Combina en un único informe:
    - Datos sociodemográficos del distrito (Fase 1: district_scorecard).
    - Normativa legal aplicable a la zona PGM elegida (Fase 2: RAG legal).
    - Una síntesis final generada por LLM que decide el semáforo de
      viabilidad, citando la normativa correspondiente.

Alcance de esta fase (decisiones validadas con el usuario):
    - Solo hostelería (bares/restaurantes) -- no se generaliza a otros
      tipos de negocio todavía.
    - La zona PGM la elige el usuario explícitamente (no se infiere del
      distrito): un mismo distrito puede abarcar varias zonas PGM, y sin
      datos geoespaciales reales del planeamiento no hay forma honesta de
      adivinarla. Ver la lista de zonas disponibles con
      `zonas_pgm_disponibles()`.
    - Orquestación con LangGraph: los nodos `datos_socioeconomicos` y
      `normativa_legal` son independientes entre sí (uno consulta SQL de
      la Fase 1, el otro el RAG de la Fase 2) y convergen en
      `sintesis_final`, que es donde entra el LLM.

Diseño testeable: `build_agent_graph()` recibe la sesión de BD y las
funciones de embedding/LLM inyectables por clausura -- mismo patrón usado
en el resto del proyecto (ver backend/rag/query_engine.py).
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

# Nombres legibles de cada zona PGM disponible, para mostrar en un
# desplegable de UI. Se deriva de la misma referencia que usa la ingesta
# legal (backend/rag/chunking.ARTICLE_TO_ZONA_PGM) -- si se ingiere un
# artículo de una zona nueva, basta con añadirlo ahí; esta lista no
# necesita tocarse.
ZONA_PGM_NOMBRES = {
    "nucli_antic": "Nucli antic / Centre històric (p. ej. Ciutat Vella)",
    "densificacio_urbana": "Densificació urbana (p. ej. gran part de l'Eixample)",
    "industrial": "Zona industrial",
}


def zonas_pgm_disponibles(session: Session) -> list[str]:
    """
    Zonas PGM que realmente tienen normativa cargada en legal_chunks.

    Se consulta la base de datos en vez de devolver una lista fija: así el
    desplegable de opciones nunca ofrece una zona sin normativa indexada
    detrás (lo que daría una recuperación vacía).
    """
    rows = session.execute(text("SELECT DISTINCT zona_pgm FROM legal_chunks WHERE zona_pgm IS NOT NULL")).all()
    return sorted(r[0] for r in rows)


class ViabilityState(TypedDict):
    # --- Entrada ---
    codi_districte: int
    zona_pgm: str

    # --- Resultados intermedios (rellenados por los nodos) ---
    datos_distrito: dict | None
    respuesta_legal: dict | None

    # --- Salida final ---
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
2. Una respuesta legal ya generada, que indica si el uso comercial/hostelería está permitido en la zona urbanística elegida, citando el artículo normativo correspondiente.

Tu tarea es sintetizar AMBOS en un informe de viabilidad breve para el usuario final (el dueño del negocio, no un desarrollador). Estructura tu respuesta EXACTAMENTE así:

Primera línea: una sola palabra, en mayúsculas, entre VERDE, AMBAR o ROJO -- nada más en esa línea.
    - ROJO: la normativa prohíbe explícitamente el uso, o el contexto legal no da certeza suficiente.
    - AMBAR: el uso está permitido, pero con restricciones relevantes o riesgos socioeconómicos notables (poca renta, mucha competencia).
    - VERDE: el uso está permitido y las condiciones socioeconómicas son favorables.

Después, un resumen de 3-5 frases en el mismo idioma en que esté escrita la información que recibas, dirigido al dueño del negocio: explica el veredicto, cita el artículo normativo relevante, y menciona el dato socioeconómico más relevante (positivo o negativo).

No inventes información que no esté en los dos bloques que recibes. Si falta algún dato, dilo explícitamente en vez de rellenar el hueco."""


def _construir_pregunta_legal(zona_pgm: str) -> str:
    nombre_zona = ZONA_PGM_NOMBRES.get(zona_pgm, zona_pgm)
    return f"¿Se permite abrir un bar o restaurante (uso comercial/hostelería) en una zona de tipo '{nombre_zona}'? ¿Con qué condiciones o límites?"


def build_agent_graph(
    session: Session,
    embed_fn: EmbeddingFunction = embed_texts,
    llm_client=None,
    model: str = DEFAULT_MODEL,
):
    """
    Construye y compila el grafo del agente.

    Las dependencias (sesión de BD, función de embedding, cliente LLM) se
    capturan por clausura en los nodos -- permite inyectar dobles de
    prueba sin tocar la lógica del grafo (ver tests/unit_tests/test_agent.py).
    """

    def datos_socioeconomicos(state: ViabilityState) -> dict:
        # Sesión propia, no la compartida por clausura: este nodo se
        # ejecuta en PARALELO con normativa_legal (ambos arrancan desde
        # START, ver grafo más abajo), y sqlalchemy.orm.Session no es
        # segura para acceso concurrente -- compartir una sola sesión
        # entre los dos nodos revienta con "This session is provisioning
        # a new connection; concurrent operations are not permitted"
        # (detectado en pruebas reales). Se deriva del mismo motor de
        # conexión que la sesión original, no de una nueva configuración.
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
        # Mismo motivo que en datos_socioeconomicos: sesión propia para
        # este nodo, ya que se ejecuta en paralelo con el anterior.
        with Session(session.get_bind()) as node_session:
            pregunta = _construir_pregunta_legal(state["zona_pgm"])
            resultado = generate_answer(
                node_session,
                pregunta,
                embed_fn=embed_fn,
                llm_client=llm_client,
                model=model,
                zona_pgm=state["zona_pgm"],
            )
        return {"respuesta_legal": resultado}

    def sintesis_final(state: ViabilityState) -> dict:
        import anthropic

        client = llm_client if llm_client is not None else anthropic.Anthropic()

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
            model=model,
            max_tokens=1024,
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mensaje}],
        )
        texto = response.content[0].text.strip()

        primera_linea, *resto = texto.splitlines()
        semaforo_texto = primera_linea.strip().upper()
        semaforo: Semaforo = semaforo_texto.lower() if semaforo_texto in ("VERDE", "AMBAR", "ROJO") else "ambar"
        if semaforo_texto not in ("VERDE", "AMBAR", "ROJO"):
            logger.warning(f"El LLM no devolvió un semáforo reconocible en la primera línea: {primera_linea!r}")
            resumen = texto  # no se pudo separar limpiamente; se devuelve todo como resumen
        else:
            resumen = "\n".join(resto).strip()

        informe = ViabilityReport(
            semaforo=semaforo,
            resumen=resumen,
            datos_distrito=datos or {},
            respuesta_legal=legal["respuesta"],
            articulos_citados=articulos_citados,
        )
        return {"informe": informe.__dict__}

    graph = StateGraph(ViabilityState)
    graph.add_node("datos_socioeconomicos", datos_socioeconomicos)
    graph.add_node("normativa_legal", normativa_legal)
    graph.add_node("sintesis_final", sintesis_final)

    # datos_socioeconomicos y normativa_legal son independientes entre sí
    # (uno consulta Fase 1, el otro Fase 2) -- ambos arrancan desde START y
    # convergen en sintesis_final.
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
) -> dict:
    """Punto de entrada de conveniencia: construye el grafo y lo invoca en un solo paso."""
    app = build_agent_graph(session, embed_fn=embed_fn, llm_client=llm_client, model=model)
    resultado = app.invoke({"codi_districte": codi_districte, "zona_pgm": zona_pgm})
    return resultado["informe"]
