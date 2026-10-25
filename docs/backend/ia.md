# Backend: AI agents (`backend/ia`)

LangGraph orchestration that combines socioeconomic and GIS data (Postgres) with the legal RAG. Two separate agents plus an intent extractor.

| File | Role |
| --- | --- |
| `agent.py` | Viability report graph (deterministic, not autonomous) |
| `chat.py` | ReAct assistant with persistent per-thread memory |
| `chat_intent.py` | `extraer_intencion(mensaje)`: one stateless LLM call returning JSON `{direccion, distrito_mencionado, pregunta_especifica}`. The NLU step in front of the geo pipeline |
| `chat_history.py` | Writes `chat_history/{thread_id}.txt` and validates thread ids (no path tricks) |
| `thinking_filter.py` | Strips `<thinking>...</thinking>` blocks from streamed model output, even when a tag is split across chunks |

## 1. Viability agent (`agent.py`)

```
START ─┬─> datos_socioeconomicos ─┐
       └─> normativa_legal ───────┴─> sintesis_final -> END
```

- The first two nodes run **in parallel**, each with its own DB session. The first reads one row of the `district_scorecard` view (income, foot traffic, competitors, score) joined with `district_mobility`. The second runs the RAG for the PGM zone and an optional specific question.
- `sintesis_final` asks the LLM for a verdict whose **first line is `verde`, `ambar` or `rojo`**, followed by a summary. `_parsear_semaforo_y_resumen` parses it defensively.
- `build_data_gathering_graph` is the same graph without synthesis, so the streaming variant can send data to the UI first.
- Entry points: `generar_informe_viabilidad(...)` returns a `ViabilityReport`; `generar_informe_viabilidad_stream(...)` yields data, then synthesis tokens, then the confirmed verdict. Used by `routers/reports.py` and `routers/chat.py`.

## 2. Assistant (`chat.py`)

- ReAct graph: `assistant` → (`tools` → `assistant`)* → `summarize` → END. `summarize` replaces old messages with a summary once there are more than `MAX_NUM_MESSAGES` (default 5), summarising `NUM_MESSAGES_TO_SUMMARIZE` (default 3). The full conversation is still kept in history.
- Tools: `find_in_nomenclator(address)` (TF-IDF match against the official street register), `get_opportunity_score(direccion)` (geocode + zone + district data) and `regulations_query(query)` (RAG with rerank).
- Memory: `PostgresSaver` checkpointer on the same database. `thread_id` is `"<user>:<n>"`; the login router lists a user's conversations from the `checkpoints` table.
- Entry point: `request(message, thread=..., stream=True)` yields token events, used by `POST /api/assistant` and by `POST /api` when a message has no location.
- LLM: `get_chat_llm()` uses `langchain-aws` (Bedrock, temperature 0) or Gemini with `LLM_PROVIDER=gemini`.

## Configuration

`LLM_PROVIDER`, `GENERATION_MODEL` / `BEDROCK_MODEL`, `AWS_REGION`, `MAX_NUM_MESSAGES`, `NUM_MESSAGES_TO_SUMMARIZE`, `DATABASE_URL`. Prompts are in Spanish. The assistant needs `data/processed/{streets_list,tfidf_vectorizer,tfidf_matrix}.pkl` (from `python -m backend.etl.tfidf`); without them `find_in_nomenclator` returns no matches.

Dependencies: `langgraph`, `langgraph-checkpoint-postgres`, `langchain-aws`, `psycopg[binary]`, plus [rag](rag.md) and [geo](geo.md).
