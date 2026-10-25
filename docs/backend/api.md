# Backend: API (`backend/api`)

FastAPI app that exposes geo, RAG, agents and ETL to the frontend. Interactive docs at `/docs`.

```
backend/api/
├── main.py      # Launcher: load .env, logging, uvicorn on :8000 (reload only when ENV=development)
├── api.py       # App: lifespan, CORS, request middleware, routers, /health /ready /metrics
├── deps.py      # DB engine + SessionLocal (fail-fast SELECT 1) and the get_session dependency
├── routers/     # One module per domain
├── schemas/     # Pydantic request/response models, one per router
└── metrics/     # In-memory request counter (resets on restart)
```

Run: `python -m backend.api.main` or `uvicorn backend.api.api:app`.

## Endpoints

| Method and path | Router | Purpose |
| --- | --- | --- |
| `GET /api/districts`, `/api/pgm-zones` | reports | Form options (zones come from what is loaded in the DB) |
| `POST /api/reports` | reports | Full viability report (JSON) |
| `POST /api/reports/stream` | reports | Same report as SSE: `datos`, `token`, `done`, `error` |
| `POST /api` | chat | Free text → intent → geocode → zone → report stream. Sends `aclaracion` when it cannot resolve the location and never guesses. With a `thread_id` and no location, it hands the message to the assistant and sends a `modo` event |
| `POST /api/assistant` | assistant | SSE from the ReAct agent, memory keyed by `thread_id` |
| `GET /api/geocode` | geocoding | Address → lat/lon, district, PGM zone. 404 only if the address is not found |
| `GET /api/competitors` | competitors | Competitors by district or point, plus map center |
| `GET /api/articles` | articles | Text of one legal article (`fuente_legal`, `numero_articulo`) |
| `POST /api/login` | login | Checks the user in `users` and returns their conversations (distinct `thread_id` in `checkpoints`) |
| `GET /api/gethistory` | history | History file from `chat_history/` for a `thread_id` |
| `GET /api/metrics/overview`, `/requests`, `/requests/{id}` | request_metrics | Data for the `/metrics` dashboard |
| `GET /api/evals/runs`, `/runs/{id}`, `/corpus` | rag_evals | RAG eval results read from `evals/results/` (`EVALS_RESULTS_DIR`) |
| `POST /api/logs` | logs | Browser log ingest. Public, so size-capped, rate-limited and sanitised |
| `POST /api/etl/mitma`, `/s3-event`, `/sync-all`; `GET /api/etl/mitma/progress` | etl | ETL triggers. `s3-event` and `sync-all` require `ETL_WEBHOOK_SECRET` |
| `GET /health`, `/ready`, `/metrics` | api.py | Liveness, readiness (checks the DB) and a Prometheus-style counter. Not logged |

## Cross-cutting behaviour

- **Database.** `DATABASE_URL` is required or startup fails. `pool_pre_ping` is on. `DB_HOST_OVERRIDE` / `DB_PORT_OVERRIDE` switch the Docker hostname to localhost (`backend/db/connection.py`).
- **CORS.** `CORS_ORIGINS` (comma-separated), defaulting to the Vite dev ports. `X-Request-ID` is exposed.
- **Tracing.** The middleware reads or creates `X-Request-ID` and puts it in the logging context ([observability](../observability.md)).
- **SSE errors.** Streams report failures as an `{"type": "error", "detail": ...}` event instead of an HTTP error.
- **Cache.** Geocoding, zone lookups, scorecards and RAG answers use the optional Redis cache (`backend/cache/`, `REDIS_URL`). If Redis is down, requests go straight to the source.

Versions are pinned in `backend/requirements.txt`. Related: [rag](rag.md), [ia](ia.md), [geo](geo.md), [etl](etl.md).
