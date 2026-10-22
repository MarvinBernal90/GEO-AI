# Backend: AI agents (`backend/ia`)

LangGraph orchestration that combines socioeconomic and GIS data (Postgres) with the legal RAG to produce a business verdict. There are two separate agents plus an intent extractor.

## Files

| File | Role |
| --- | --- |
| `agent.py` | Viability report graph (deterministic, not autonomous). |
| `chat.py` | ReAct chat agent with persistent per-thread memory. |
| `chat_intent.py` | `extraer_intencion(mensaje)`: one stateless LLM call that returns JSON `{direccion, distrito_mencionado, pregunta_especifica}`. It is the NLU step in front of the geo pipeline. |

## 1. Viability agent (`agent.py`)

```
START ─┬─> datos_socioeconomicos ─┐
       └─> normativa_legal ───────┴─> sintesis_final -> END
```

- The two first nodes run **in parallel**. The first reads one row from the `district_scorecard` view (income, foot traffic, total competitors, opportunity score), joined with `district_mobility` (trips, predominant age). The second runs RAG for the PGM zone (and an optional specific question).
- `sintesis_final` asks the LLM for a verdict whose **first line is `verde`, `ambar` or `rojo`**, followed by a summary. `_parsear_semaforo_y_resumen` parses it defensively.
- `build_data_gathering_graph` is the same graph without synthesis. It is used by the streaming variant so data can be sent to the UI first.
- Entry points: `generar_informe_viabilidad(...)` returns a `ViabilityReport`. `generar_informe_viabilidad_stream(...)` yields events (data first, then synthesis tokens, then the confirmed verdict). Both are used by `api/routers/reports.py` and `chat.py`.

## 2. Chat agent (`chat.py`)

- ReAct graph: `assistant` -> (`tools` -> `assistant`)* -> `summarize` -> END. `summarize` condenses old messages so the context stays bounded.
- Tools: `get_opportunity_score(direccion)` (geocode + zone + district data) and `regulations_query(query)` (RAG with rerank).
- Memory: `PostgresSaver` checkpointer on the same database (`langgraph-checkpoint-postgres`, `psycopg`). `thread_id` is `"<user>:<n>"`. The login router lists conversations from the `checkpoints` table.
- Entry point: `request(message, thread=..., stream=True)` yields token events. It is used by `POST /api/assistant`.
- LLM: `get_chat_llm()` uses `langchain-aws` (Bedrock) by default, or Gemini when `LLM_PROVIDER=gemini`.

## Configuration

`LLM_PROVIDER`, `GENERATION_MODEL` / `BEDROCK_MODEL`, `AWS_REGION` / `AWS_DEFAULT_REGION`, `DATABASE_URL` (shared with the API). Prompts are in Spanish.

## Dependencies

`langgraph`, `langgraph-checkpoint-postgres`, `langchain-aws`, `psycopg[binary]`, `SQLAlchemy`, plus [rag.md](rag.md) and [geo.md](geo.md) as internal dependencies.
