"""
==============================================================================
RAG EVALS: DISK CACHE FOR EMBEDDINGS AND LLM CALLS
==============================================================================
File: evals/cache.py

Every embedding and every model reply made by the evals is stored in an
append-only JSONL file, keyed by a hash of everything that influences the result.
Re-running an evaluation is therefore free and deterministic, and changing one
setting (the prompt, the model, the chunk text) only pays for what actually changed.

A cached LLM reply keeps the seconds the original call took, so latency numbers
stay honest on a cached re-run.
"""

import hashlib
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parent / "results"
CACHE_DIR = RESULTS_DIR / "cache"
CORPUS_REPORT = RESULTS_DIR / "corpus.json"


def _hash(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DiskCache:
    """Append-only key -> JSON value store. Safe to use from several threads."""

    def __init__(self, name: str, directory: Path = CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{name}.jsonl"
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self._data[record["k"]] = record["v"]

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"k": key, "v": value}, ensure_ascii=False) + "\n")

    def __len__(self) -> int:
        return len(self._data)


def cached_embedder(embed_fn: Callable[[list[str]], list[list[float]]], model_name: str, cache: DiskCache):
    """Wraps an embedding function so each distinct text is embedded once, ever."""

    def embed(texts: list[str]) -> list[list[float]]:
        keys = [_hash("embed", model_name, t) for t in texts]
        missing = [i for i, k in enumerate(keys) if cache.get(k) is None]
        if missing:
            # Small batches keep a failure from throwing away a whole law's worth of work.
            for start in range(0, len(missing), 32):
                batch = missing[start : start + 32]
                vectors = embed_fn([texts[i] for i in batch])
                for i, vector in zip(batch, vectors, strict=True):
                    cache.put(keys[i], vector)
        return [cache.get(k) for k in keys]

    return embed


class _Block:
    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, text: str, seconds: float):
        self.content = [_Block(text)]
        self.seconds = seconds


class CachedLLM:
    """
    Same `.messages.create(...)` surface as the Bedrock adapter, with a disk cache in front.
    The evals choose the temperature, so it is part of the cache key.
    """

    def __init__(self, client: Any, cache: DiskCache, temperature: float = 0.0):
        self._client = client
        self._cache = cache
        self._temperature = temperature
        self.messages = self
        self.calls = 0  # real (non-cached) calls made in this process

    def create(self, model: str, max_tokens: int, system: str, messages: list[dict[str, Any]]):
        key = _hash("llm", model, max_tokens, system, messages, self._temperature)
        hit = self._cache.get(key)
        if hit is not None:
            return _Response(hit["text"], hit["seconds"])
        start = time.perf_counter()
        response = self._client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=messages, temperature=self._temperature
        )
        seconds = time.perf_counter() - start
        text = response.content[0].text
        self.calls += 1
        self._cache.put(key, {"text": text, "seconds": seconds})
        return _Response(text, seconds)
