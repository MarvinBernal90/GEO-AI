"""
Tests del motor de consulta RAG (backend/rag/query_engine.py).

Usa hash_embed (determinista, sin red ni modelo real) para poder probar la
mecánica de recuperación/construcción del prompt de forma reproducible.
No valida calidad semántica real -- eso requiere el modelo real descargado,
algo que no es posible en este sandbox (huggingface.co no está en la lista
de dominios permitidos). La validación semántica real queda para cuando el
usuario lo ejecute en su propia máquina.
"""

import hashlib

import pytest

from backend.rag.query_engine import build_context, generate_answer, retrieve_relevant_chunks


def hash_embed(texts: list[str]) -> list[list[float]]:
    """Embedding determinista basado en hash, solo para pruebas mecánicas."""
    result = []
    for t in texts:
        seed = int(hashlib.sha256(t.encode()).hexdigest(), 16)
        result.append([((seed >> (i % 64)) % 1000) / 1000.0 for i in range(384)])
    return result


class FakeContent:
    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeContent(text)]


class FakeLLMClient:
    """Doble de anthropic.Anthropic() que solo registra la llamada, sin red."""

    def __init__(self, response_text="[respuesta simulada]"):
        self.response_text = response_text
        self.last_call = None
        self.messages = self

    def create(self, model, max_tokens, system, messages):
        self.last_call = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
        return FakeResponse(self.response_text)


@pytest.fixture
def legal_chunk_factory(db_session):
    """
    Inserta un LegalChunk de prueba directamente en la BD, con un embedding
    determinista (hash_embed) para que las pruebas de recuperación sean
    reproducibles.
    """
    from backend.db.models import LegalChunk

    def _make(numero_articulo, contenido, titulo="Título de prueba"):
        chunk = LegalChunk(
            numero_articulo=numero_articulo,
            titulo=titulo,
            contenido=contenido,
            expedient="test/000000",
            versio="original",
            documento_origen="test.pdf",
            embedding=hash_embed([contenido])[0],
        )
        db_session.add(chunk)
        db_session.commit()
        return chunk

    return _make


class TestRetrieveRelevantChunks:
    def test_exact_match_returns_distance_zero(self, db_session, legal_chunk_factory):
        legal_chunk_factory("311", "S'admeten les cafeteries, restaurants, bars i similars.")
        legal_chunk_factory("302", "Comercial. S'admet en edificis exclusius.")

        results = retrieve_relevant_chunks(
            db_session,
            "S'admeten les cafeteries, restaurants, bars i similars.",
            embed_fn=hash_embed,
            top_k=2,
        )

        assert results[0].numero_articulo == "311"
        assert results[0].distancia == pytest.approx(0.0, abs=1e-6)

    def test_respects_top_k(self, db_session, legal_chunk_factory):
        for i in range(5):
            legal_chunk_factory(str(300 + i), f"Contenido de prueba número {i}.")

        results = retrieve_relevant_chunks(db_session, "consulta cualquiera", embed_fn=hash_embed, top_k=2)
        assert len(results) == 2


class TestBuildContext:
    def test_includes_article_number_and_content(self):
        from backend.rag.query_engine import RetrievedChunk

        chunks = [RetrievedChunk("311", "Zona industrial", "S'admeten bars.", 0.1)]
        context = build_context(chunks)
        assert "Article 311" in context
        assert "S'admeten bars." in context


class TestGenerateAnswer:
    def test_wires_retrieval_into_llm_prompt(self, db_session, legal_chunk_factory):
        legal_chunk_factory("311", "S'admeten les cafeteries, restaurants, bars i similars.", "Zona industrial")
        fake_client = FakeLLMClient(response_text="[RESPUESTA SIMULADA]")

        result = generate_answer(
            db_session,
            "¿Puedo abrir un bar aquí?",
            embed_fn=hash_embed,
            llm_client=fake_client,
            top_k=1,
        )

        assert result["respuesta"] == "[RESPUESTA SIMULADA]"
        assert len(result["chunks_recuperados"]) == 1
        # El contenido recuperado debe haber llegado de verdad al mensaje enviado al LLM
        assert "cafeteries" in fake_client.last_call["messages"][0]["content"]
        assert fake_client.last_call["model"] == "claude-sonnet-5"

    def test_returns_early_message_when_no_chunks_in_db(self, db_session):
        result = generate_answer(
            db_session, "cualquier pregunta", embed_fn=hash_embed, llm_client=FakeLLMClient()
        )
        assert result["chunks_recuperados"] == []
        assert "normativa" in result["respuesta"].lower()
