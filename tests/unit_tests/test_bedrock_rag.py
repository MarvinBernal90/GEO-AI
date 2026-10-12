"""
==============================================================================
UNIT TESTS: AMAZON BEDROCK EMBEDDINGS & RERANK
==============================================================================
File: tests/unit_tests/test_bedrock_rag.py

Tests the Amazon Bedrock Titan Text Embeddings V2 integration and Bedrock
Agent Runtime Rerank integration.
"""

import io
import json
from unittest.mock import MagicMock

import pytest

from backend.rag.embeddings import embed_texts
from backend.rag.query_engine import (
    RetrievedChunk,
    _is_bedrock_rerank_model,
    retrieve_relevant_chunks_with_rerank,
)


class TestBedrockEmbeddings:
    def test_embed_texts_titan_v2_call(self, monkeypatch):
        """Verifies invoke_model formatting and embedding extraction."""
        monkeypatch.setenv("EMBEDDINGS_MODEL", "amazon.titan-embed-text-v2:0")
        monkeypatch.setenv("EMBEDDINGS_DIMENSION", "1024")

        mock_client = MagicMock()
        fake_embedding_1 = [0.1] * 1024
        fake_embedding_2 = [0.2] * 1024

        def fake_invoke_model(modelId, body, contentType, accept):
            data = json.loads(body)
            emb = fake_embedding_1 if data["inputText"] == "primero" else fake_embedding_2
            return {"body": io.BytesIO(json.dumps({"embedding": emb}).encode("utf-8"))}

        mock_client.invoke_model.side_effect = fake_invoke_model

        result = embed_texts(["primero", "segundo"], client=mock_client)

        assert len(result) == 2
        assert len(result[0]) == 1024
        assert result[0] == fake_embedding_1
        assert result[1] == fake_embedding_2

        assert mock_client.invoke_model.call_count == 2
        first_call_body = json.loads(mock_client.invoke_model.call_args_list[0][1]["body"])
        assert first_call_body["dimensions"] == 1024
        assert first_call_body["normalize"] is True
        assert first_call_body["inputText"] == "primero"

    def test_embed_texts_empty_list(self):
        assert embed_texts([]) == []


class TestBedrockRerank:
    def test_is_bedrock_rerank_model_detection(self):
        assert _is_bedrock_rerank_model("amazon.rerank-v1:0") is True
        assert _is_bedrock_rerank_model("cohere.rerank-v3-5:0") is True
        assert _is_bedrock_rerank_model("arn:aws:bedrock:eu-central-1::foundation-model/amazon.rerank-v1:0") is True
        assert _is_bedrock_rerank_model("cross-encoder/ms-marco-MiniLM-L-6-v2") is False

    def test_rerank_invokes_bedrock_agent_runtime(self, monkeypatch):
        """Verifies bedrock-agent-runtime rerank parameter structure and reordering."""
        monkeypatch.setenv("RERANK_MODEL", "amazon.rerank-v1:0")
        monkeypatch.setenv("AWS_RERANK_REGION", "eu-central-1")

        mock_rerank_client = MagicMock()
        # Simulate reordering: second input chunk (index 1) becomes rank 1, first chunk (index 0) becomes rank 2
        mock_rerank_client.rerank.return_value = {
            "results": [
                {"index": 1, "relevanceScore": 0.95},
                {"index": 0, "relevanceScore": 0.42},
            ]
        }

        chunk_a = RetrievedChunk(
            numero_articulo="1",
            titulo="Articulo 1",
            contenido="Contenido 1",
            distancia=0.1,
            fuente_legal="PGM",
        )
        chunk_b = RetrievedChunk(
            numero_articulo="2",
            titulo="Articulo 2",
            contenido="Contenido 2",
            distancia=0.2,
            fuente_legal="PGM",
        )

        mock_session = MagicMock()

        # Patch retrieve_relevant_chunks to return our 2 test chunks
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "backend.rag.query_engine.retrieve_relevant_chunks",
                lambda session, query, embed_fn, top_k, zona_pgm: [chunk_a, chunk_b],
            )

            reranked = retrieve_relevant_chunks_with_rerank(
                session=mock_session,
                query="horario terrazas",
                cross_encoder_model="amazon.rerank-v1:0",
                final_top_k=2,
                rerank_client=mock_rerank_client,
            )

        assert len(reranked) == 2
        assert reranked[0] is chunk_b  # index 1 moved to top
        assert reranked[1] is chunk_a

        mock_rerank_client.rerank.assert_called_once()
        call_kwargs = mock_rerank_client.rerank.call_args[1]
        assert call_kwargs["queries"] == [{"type": "TEXT", "textQuery": {"text": "horario terrazas"}}]
        assert len(call_kwargs["sources"]) == 2
        assert call_kwargs["rerankingConfiguration"]["type"] == "BEDROCK_RERANKING_MODEL"
