# Backend: RAG (`backend/rag`)

Retrieval-Augmented Generation over Barcelona's urbanism and hospitality regulations (PGM, plus national BOE and regional DOGC laws). It ingests PDFs into `legal_chunks` (pgvector) and answers legal questions with citations.

## Files

| File | Role |
| --- | --- |
| `pdf_extraction.py` | Wraps the system binary `pdftotext` (poppler-utils), simple mode without `-layout`. Raises `RuntimeError` with stderr on failure. |
| `chunking.py` | PGM parser. Splits on `Article N.` headers and keeps only the current consolidated version of each article, dropping the historic versions. Maps articles 302, 303 and 311 to `zona_pgm`. |
| `general_chunking.py` | Heuristic parser for BOE and DOGC laws. Handles several header styles, filters table-of-contents dot leaders, strips repeated boilerplate and keeps the longest duplicate. |
| `embeddings.py` | `embed_texts(texts)`. Default is Amazon Titan Text Embeddings V2 via Bedrock (1024-dim). A local sentence-transformers model is used if `EMBEDDINGS_MODEL` is not a Bedrock model. |
| `query_engine.py` | Retrieval and generation (below). |
| `bedrock_adapter.py` | Wraps the Bedrock Converse API behind an Anthropic-style interface (`messages.create` / `create_stream`). |
| `gemini_adapter.py` | Same interface over Google Gemini, with retries. For free-tier testing. |

## Pipeline

```
PDF -> pdftotext -> chunking / general_chunking -> embed_texts -> legal_chunks (pgvector)   [offline, database/load_*.py]

question -> embed -> cosine search (top_k) -> optional rerank -> build_context -> LLM -> cited answer   [online]
```

- **Retrieval** is zone-aware. With `zona_pgm`, it takes the top K chunks for that zone plus the top K general chunks (`zona_pgm IS NULL`), merges them and sorts by cosine distance. Without a zone it searches the whole corpus.
- **Rerank** (`retrieve_relevant_chunks_with_rerank`) uses Amazon Rerank 1.0 on Bedrock (`RERANK_MODEL`).
- **Generation** (`generate_answer`) uses a system prompt that answers only from the retrieved articles, cites both the norm and the article number, and says so when the context is insufficient. It answers in the user's language even though the corpus is in Catalan. It uses no Markdown, because the UI cannot render it.
- **Provider switch.** `get_llm_adapter()` returns Bedrock by default, or Gemini with `LLM_PROVIDER=gemini`.

## Configuration

Default values (from `.env.example`):

| Variable | Default | Notes |
| --- | --- | --- |
| `EMBEDDINGS_MODEL` | `amazon.titan-embed-text-v2:0` | Bedrock Titan V2 |
| `EMBEDDINGS_DIMENSION` | `1024` | Must match the DB column from migration `0006_titan_embeddings_dim` |
| `RERANK_MODEL` | `amazon.rerank-v1:0` | Bedrock Rerank 1.0 |
| `GENERATION_MODEL` | `arn:aws:bedrock:eu-central-1:<account-id>:inference-profile/eu.amazon.nova-2-lite-v1:0` | Nova 2 Lite through an EU inference profile |
| `BEDROCK_MODEL` | `amazon.nova-lite-v1:0` (commented out) | Fallback if `GENERATION_MODEL` is unset |
| `AWS_RERANK_REGION` | `eu-central-1` (commented out) | Falls back to `AWS_REGION`, then `eu-central-1` |

Authentication uses the IAM instance profile, `AWS_PROFILE` or environment credentials. Other settings: `LLM_PROVIDER` (`bedrock` | `gemini`, default `bedrock`) and `GEMINI_MODEL` (Gemini only). If no env var is set, the code itself falls back to `amazon.nova-lite-v1:0` for generation.

## Dependencies

`boto3` / `botocore[crt]` (Bedrock), `pgvector`, `SQLAlchemy`, `sentence-transformers` (local embeddings), `google-genai` (optional), `anthropic` (listed in requirements). The system package `poppler-utils` is needed for ingestion. Design rationale for pgvector is in [../adr/0001-pgvector-vs-qdrant.md](../adr/0001-pgvector-vs-qdrant.md).
