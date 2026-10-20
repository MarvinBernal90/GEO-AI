"""
==============================================================================
RAG PIPELINE: EMBEDDINGS MODEL (AMAZON BEDROCK TITAN V2)
==============================================================================
File: backend/rag/embeddings.py

This module handles the mathematical vectorization of legal texts.
By default, it uses Amazon Titan Text Embeddings V2 (amazon.titan-embed-text-v2:0)
via Amazon Bedrock, generating 1024-dimensional normalized vectors.

Architectural Alignment:
- Corresponds to Alembic migration 0006_titan_embeddings_dim.py (1024 dimensions).
- Uses AWS SDK (boto3) with SigV4 authentication and adaptive retries.
- Maintains compatibility with local sentence-transformers models when explicitly
  configured via EMBEDDINGS_MODEL.
"""

import json
import os
from typing import Any, Protocol

from backend.observability import get_logger

logger = get_logger("rag.embeddings")

DEFAULT_EMBEDDINGS_MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", DEFAULT_EMBEDDINGS_MODEL)
MODEL_NAME = EMBEDDINGS_MODEL  # Backwards compatibility alias

DEFAULT_EMBEDDING_DIM = 1024
EMBEDDING_DIM = int(os.getenv("EMBEDDINGS_DIMENSION", os.getenv("EMBEDDING_DIM", str(DEFAULT_EMBEDDING_DIM))))

# Singleton caches
_local_model = None
_bedrock_client = None


class EmbeddingFunction(Protocol):
    """
    Dependency Injection Interface (Protocol).
    Any function used to embed text (e.g., in `database/load_legal_corpus.py`
    or inside Unit Tests) must match this signature.
    """

    def __call__(self, texts: list[str]) -> list[list[float]]: ...


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        import boto3
        from botocore.config import Config

        region = os.getenv("AWS_REGION", "eu-central-1")
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
        )
    return _bedrock_client


def _get_local_model():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        _local_model = SentenceTransformer(EMBEDDINGS_MODEL)
    return _local_model


def _is_bedrock_model(model_name: str) -> bool:
    """Checks whether the configured model name refers to an Amazon Bedrock model."""
    return (
        model_name.startswith("amazon.")
        or model_name.startswith("cohere.")
        or model_name.startswith("arn:aws:bedrock:")
    )


def embed_texts(texts: list[str], client: Any = None) -> list[list[float]]:
    """
    Concrete implementation of EmbeddingFunction.
    Generates 1024-dimensional normalized vectors via Amazon Bedrock Titan Text V2
    (or falls back to SentenceTransformers if a HuggingFace model path is configured).
    """
    if not texts:
        return []

    if _is_bedrock_model(EMBEDDINGS_MODEL):
        bedrock = client if client is not None else _get_bedrock_client()
        embeddings: list[list[float]] = []

        for text in texts:
            body = json.dumps(
                {
                    "inputText": text,
                    "dimensions": EMBEDDING_DIM,
                    "normalize": True,
                }
            )
            response = bedrock.invoke_model(
                modelId=EMBEDDINGS_MODEL,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            response_body = json.loads(response["body"].read().decode("utf-8"))
            embeddings.append(response_body["embedding"])

        return embeddings

    # Fallback to local HuggingFace / SentenceTransformers model
    model = _get_local_model()
    embeddings_array = model.encode(texts, normalize_embeddings=True)
    return embeddings_array.tolist()
