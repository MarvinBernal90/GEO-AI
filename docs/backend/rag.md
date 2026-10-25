# Backend: RAG (`backend/rag`)

Retrieval-Augmented Generation over Barcelona's urbanism and hospitality regulations (PGM, plus national BOE and Catalan DOGC laws). It ingests PDFs into `legal_chunks` (pgvector) and answers legal questions with citations.

| File | Role |
| --- | --- |
| `pdf_extraction.py` | Wraps `pdftotext` (poppler-utils) in simple mode. Raises `RuntimeError` with stderr on failure |
| `chunking.py` | PGM parser. Splits on `Article N.` headers and keeps only the current consolidated version of each article. Maps articles 302, 303 and 311 to `zona_pgm` |
| `general_chunking.py` | Heuristic parser for BOE and DOGC laws: several header styles, table-of-contents filtering, repeated boilerplate removal, longest duplicate kept |
| `embeddings.py` | `embed_texts(texts)`. Default Amazon Titan Text Embeddings V2 on Bedrock (1024 dim). A local sentence-transformers model is used if `EMBEDDINGS_MODEL` is not a Bedrock model (it is not in `backend/requirements.txt`) |
| `query_engine.py` | Retrieval and generation (below) |
| `bedrock_adapter.py` | Bedrock Converse API behind an Anthropic-style interface (`messages.create` / `create_stream`) |
| `gemini_adapter.py` | Same interface over Google Gemini, with retries |

## Pipeline

```
PDF -> pdftotext -> chunking -> embed_texts -> legal_chunks (HNSW cosine index)      [offline: database/load_*.py]
question -> embed -> cosine search -> (optional rerank) -> build_context -> LLM -> cited answer   [online]
```

- **Retrieval** is zone-aware. With `zona_pgm`, it takes the top K chunks of that zone plus the top K general chunks (`zona_pgm IS NULL`), merges and sorts them by cosine distance. Without a zone it searches the whole corpus.
- **Rerank** (`retrieve_relevant_chunks_with_rerank`) re-orders candidates with Amazon Rerank 1.0 (`RERANK_MODEL`). The assistant's `regulations_query` tool uses it; the report pipeline (`generate_answer`) uses plain retrieval.
- **Generation** (`generate_answer`) answers only from the retrieved articles, cites both norm and article number, and says so when the context is insufficient. It answers in the user's language even though the corpus is Catalan, and uses no Markdown because the UI cannot render it.
- **Provider switch.** `get_llm_adapter()` returns Bedrock by default, or Gemini with `LLM_PROVIDER=gemini`.
- **Cache.** Answers are cached in Redis for 24 hours when available.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `EMBEDDINGS_MODEL` | `amazon.titan-embed-text-v2:0` | Bedrock Titan V2 |
| `EMBEDDINGS_DIMENSION` | `1024` | Must match the column from migration `0006_titan_embeddings_dim` |
| `RERANK_MODEL` | `amazon.rerank-v1:0` | Bedrock Rerank 1.0 |
| `GENERATION_MODEL` | Nova 2 Lite inference profile ARN (`.env.example`) | Falls back to `BEDROCK_MODEL`, then `amazon.nova-lite-v1:0` |
| `LLM_PROVIDER` / `GEMINI_MODEL` | `bedrock` / `gemini-2.5-flash` | Gemini only if selected |
| `AWS_RERANK_REGION` | falls back to `AWS_REGION`, then `eu-central-1` | |

Authentication uses the instance profile, `AWS_PROFILE` or environment credentials.

Dependencies: `boto3` / `botocore[crt]`, `pgvector`, `SQLAlchemy`, `google-genai` (optional). `poppler-utils` is needed for ingestion. Why pgvector: [ADR 0001](../adr/0001-pgvector-vs-qdrant.md). Quality is measured in [`evals/`](../../evals/README.md).
