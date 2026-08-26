"""
Motor de consulta del RAG legal. Reconstruido tras reinicio de sandbox --
ver conversación previa para el diseño completo.
"""

import os
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.db.models import LegalChunk
from backend.rag.embeddings import EmbeddingFunction, embed_texts

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = """INSTRUCCIÓN DE IDIOMA (síguela siempre, sin excepción): responde en el MISMO idioma en el que esté escrita la pregunta del usuario. El contexto normativo que recibes está en catalán, pero eso NO determina el idioma de tu respuesta — solo el idioma de la pregunta del usuario lo determina. Si la pregunta está en castellano, responde en castellano, traduciendo o parafraseando el contenido normativo según haga falta.

Eres un asistente legal especializado en normativa urbanística de Barcelona (Pla General Metropolità, PGM).

Respondes ÚNICAMENTE basándote en los artículos normativos que se te proporcionan como contexto. Para cada afirmación, cita tanto la norma como el número de artículo exacto (p. ej. "según el Artículo 302 del PGM..." o "según el Artículo 4 de la Ordre INT/358/2011..."), ya que puede haber varias normas distintas en el contexto y el número de artículo por sí solo no las distingue. Si el contexto proporcionado no contiene información suficiente para responder con seguridad, dilo explícitamente en vez de inventar o generalizar.

Esta respuesta es orientativa, no un dictamen legal vinculante — recomienda siempre confirmar con el ayuntamiento o un profesional antes de tomar una decisión."""


@dataclass
class RetrievedChunk:
    numero_articulo: str
    titulo: str
    contenido: str
    distancia: float
    fuente_legal: str = "PGM"


def _query_chunks(session, query_embedding, top_k, zona_filter):
    """
    zona_filter:
        - un str -> filtra a esa zona_pgm exacta
        - False  -> filtra a zona_pgm IS NULL (normativa general, aplica en toda la ciudad)
        - None   -> sin filtro (todo)
    """
    stmt = session.query(
        LegalChunk.numero_articulo,
        LegalChunk.titulo,
        LegalChunk.contenido,
        LegalChunk.fuente_legal,
        LegalChunk.embedding.cosine_distance(query_embedding).label("distancia"),
    )
    if zona_filter is False:
        stmt = stmt.filter(LegalChunk.zona_pgm.is_(None))
    elif zona_filter is not None:
        stmt = stmt.filter(LegalChunk.zona_pgm == zona_filter)
    return stmt.order_by("distancia").limit(top_k).all()


def retrieve_relevant_chunks(
    session: Session,
    query: str,
    embed_fn: EmbeddingFunction = embed_texts,
    top_k: int = 3,
    zona_pgm: str | None = None,
) -> list[RetrievedChunk]:
    """
    Recupera los top_k artículos más cercanos por similitud coseno a `query`.

    Si se indica `zona_pgm`, combina DOS búsquedas: los `top_k` artículos
    de esa zona exacta (columna zona_pgm, migración 0004) MÁS los `top_k`
    artículos de normativa general que aplica en toda la ciudad
    (zona_pgm IS NULL, p. ej. horarios comerciales, venta de alcohol --
    migración 0005). Sin esto, una norma general nunca podría aparecer en
    una consulta filtrada por zona, aunque sea justo la que el usuario
    necesita (p. ej. preguntar por horarios de un bar en una zona
    concreta antes solo devolvía normativa de zonificación, nunca la
    norma de horarios).
    """
    query_embedding = embed_fn([query])[0]

    if zona_pgm is not None:
        especifica = _query_chunks(session, query_embedding, top_k, zona_pgm)
        general = _query_chunks(session, query_embedding, top_k, False)
        results = list(especifica) + list(general)
    else:
        results = _query_chunks(session, query_embedding, top_k, None)

    return [
        RetrievedChunk(r.numero_articulo, r.titulo, r.contenido, r.distancia, r.fuente_legal)
        for r in results
    ]


def build_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"--- {c.fuente_legal}, Artículo {c.numero_articulo}: {c.titulo} ---\n{c.contenido}" for c in chunks
    )


def generate_answer(
    session: Session,
    question: str,
    embed_fn: EmbeddingFunction = embed_texts,
    llm_client=None,
    model: str = DEFAULT_MODEL,
    top_k: int = 3,
    max_tokens: int = 2048,
    zona_pgm: str | None = None,
) -> dict:
    chunks = retrieve_relevant_chunks(session, question, embed_fn=embed_fn, top_k=top_k, zona_pgm=zona_pgm)
    if not chunks:
        return {"respuesta": "No hi ha normativa carregada a la base de dades encara.", "chunks_recuperados": []}
    context = build_context(chunks)
    user_message = f"CONTEXT NORMATIU:\n{context}\n\nPREGUNTA: {question}"
    if llm_client is None:
        from backend.rag.gemini_adapter import GeminiAsAnthropicAdapter
        llm_client = GeminiAsAnthropicAdapter()
    response = llm_client.messages.create(
        model=model, max_tokens=max_tokens, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return {"respuesta": response.content[0].text, "chunks_recuperados": chunks}