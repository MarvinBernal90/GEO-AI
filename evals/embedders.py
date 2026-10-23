"""
==============================================================================
RAG EVALS: THE EMBEDDING MODEL
==============================================================================
File: evals/embedders.py

The evals use exactly the embedding model production uses (backend.rag.embeddings.embed_texts,
Amazon Titan Text Embeddings v2), behind a disk cache so each text is only ever embedded once.
No other model is evaluated: the project stays on the models it already ships with.
"""

from collections.abc import Callable

from evals.cache import DiskCache, cached_embedder

EmbedFn = Callable[[list[str]], list[list[float]]]

TITAN_MODEL = "amazon.titan-embed-text-v2:0"


def _titan_embed(texts: list[str]) -> list[list[float]]:
    # Imported here so importing this module does not need AWS credentials.
    from backend.rag.embeddings import embed_texts

    return embed_texts(texts)


def get_embedder() -> tuple[EmbedFn, str]:
    """Returns (cached embed function, model id)."""
    return cached_embedder(_titan_embed, TITAN_MODEL, DiskCache("emb_titan")), TITAN_MODEL
