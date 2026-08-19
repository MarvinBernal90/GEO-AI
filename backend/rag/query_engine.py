"""
Motor de consulta del RAG legal (Fase 2): recuperación por similitud
coseno contra `legal_chunks` + generación de la respuesta con Claude,
citando el número de artículo correspondiente.

Diseño testeable: tanto `embed_fn` como `llm_client` son inyectables, para
poder probar la tubería completa (recuperación + construcción del prompt)
sin depender de tener el modelo de embeddings descargado ni una API key de
Anthropic a mano — ver tests/unit_tests/test_query_engine.py.
"""

import os
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.db.models import LegalChunk
from backend.rag.embeddings import EmbeddingFunction, embed_texts

# claude-sonnet-5: modelo confirmado en la documentación oficial de
# Anthropic (docs.claude.com), no asumido de memoria. Configurable por
# variable de entorno para poder cambiar a un modelo más económico
# (p. ej. Haiku) sin tocar código.
DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """INSTRUCCIÓN DE IDIOMA (síguela siempre, sin excepción): responde en el MISMO idioma en el que esté escrita la pregunta del usuario. El contexto normativo que recibes está en catalán, pero eso NO determina el idioma de tu respuesta — solo el idioma de la pregunta del usuario lo determina. Si la pregunta está en castellano, responde en castellano, traduciendo o parafraseando el contenido normativo según haga falta.

Eres un asistente legal especializado en normativa urbanística de Barcelona (Pla General Metropolità, PGM).

Respondes ÚNICAMENTE basándote en los artículos normativos que se te proporcionan como contexto. Para cada afirmación, cita el número de artículo exacto (p. ej. "según el Artículo 302..."). Si el contexto proporcionado no contiene información suficiente para responder con seguridad, dilo explícitamente en vez de inventar o generalizar.

Esta respuesta es orientativa, no un dictamen legal vinculante — recomienda siempre confirmar con el ayuntamiento o un profesional antes de tomar una decisión."""


@dataclass
class RetrievedChunk:
    numero_articulo: str
    titulo: str
    contenido: str
    distancia: float


def retrieve_relevant_chunks(
    session: Session,
    query: str,
    embed_fn: EmbeddingFunction = embed_texts,
    top_k: int = 3,
) -> list[RetrievedChunk]:
    """Recupera los top_k artículos más cercanos por similitud coseno a `query`."""
    query_embedding = embed_fn([query])[0]

    results = (
        session.query(
            LegalChunk.numero_articulo,
            LegalChunk.titulo,
            LegalChunk.contenido,
            LegalChunk.embedding.cosine_distance(query_embedding).label("distancia"),
        )
        .order_by("distancia")
        .limit(top_k)
        .all()
    )
    return [RetrievedChunk(r.numero_articulo, r.titulo, r.contenido, r.distancia) for r in results]


def build_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"--- Article {c.numero_articulo}: {c.titulo} ---\n{c.contenido}" for c in chunks
    )


def generate_answer(
    session: Session,
    question: str,
    embed_fn: EmbeddingFunction = embed_texts,
    llm_client=None,
    model: str = DEFAULT_MODEL,
    top_k: int = 3,
    max_tokens: int = 2048,
) -> dict:
    """
    Pipeline completo: pregunta -> recuperación -> generación con Claude.

    `llm_client` es inyectable: por defecto crea un cliente real de
    anthropic (lee ANTHROPIC_API_KEY del entorno), pero los tests pueden
    pasar un doble que imite `.messages.create(...)` sin llamar a la API.
    """
    chunks = retrieve_relevant_chunks(session, question, embed_fn=embed_fn, top_k=top_k)
    if not chunks:
        return {"respuesta": "No hi ha normativa carregada a la base de dades encara.", "chunks_recuperados": []}

    context = build_context(chunks)
    user_message = f"CONTEXT NORMATIU:\n{context}\n\nPREGUNTA: {question}"

    if llm_client is None:
        import anthropic

        llm_client = anthropic.Anthropic()

    response = llm_client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return {"respuesta": response.content[0].text, "chunks_recuperados": chunks}