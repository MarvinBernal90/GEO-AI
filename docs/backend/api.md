# Backend: API (`backend/api`)

FastAPI application that exposes the rest of the backend (geo, RAG, agents, ETL) to the frontend.

## Files

```
backend/api/
├── main.py       # Launcher: load_dotenv, configure logging, uvicorn (port 8000, reload only when ENV=development)
├── api.py        # App factory: lifespan, CORS, request middleware, router registration, /health /ready /metrics
├── deps.py       # DB engine + SessionLocal (lifespan, fail-fast SELECT 1) and the get_session dependency
├── routers/      # One module per domain (below)
├── schemas/      # Pydantic request/response models, one per router
├── models/       # Small non-ORM domain models (business.py)
└── metrics/      # In-memory request counter (resets on restart; roadmap in the file)
```

Run: `python -m backend.api.main` or `uvicorn backend.api.api:app`. Interactive docs are at `/docs`.

## Endpoints

| Method and path | Router | Purpose |
| --- | --- | --- |
| `GET /api/districts`, `GET /api/pgm-zones` | reports | Form options |
| `POST /api/reports` | reports | Full viability report (JSON) |
| `POST /api/reports/stream` | reports | Same report as SSE (`datos`, `token`, `done`, `error`) |
| `POST /api/chat/informe/stream` | chat | Free text -> intent extraction -> geocode -> zoning -> report stream. Sends `aclaracion` when it cannot resolve the location and never guesses |
| `POST /api/assistant` | assistant | SSE stream from the ReAct chat agent, using `thread_id` for memory |
| `GET /api/geocode` | geocoding | Address -> lat/lon, district and PGM zone. Degrades gracefully: 404 only if the address is not found |
| `GET /api/competitors` | competitors | Competitors by district or by point, plus map center |
| `GET /api/articles` | articles | Raw text of a legal article, by query params `fuente_legal` and `numero_articulo` |
| `POST /api/login`, `GET /api/gethistory` | login, history | User check against `users`, list of conversations (distinct `thread_id` in the `checkpoints` table), history files from `chat_history/` |
| `POST /api/logs` | logs | Browser log ingest. Public, so it is size-capped, rate-limited and sanitised |
| `GET /health`, `/ready`, `/metrics` | api.py | Liveness, readiness (checks the DB) and a Prometheus-style counter. Not logged |

## Cross-cutting behaviour

- **Database.** `DATABASE_URL` is required, or startup fails. `pool_pre_ping` is on. `DB_HOST_OVERRIDE` and `DB_PORT_OVERRIDE` switch Docker hostnames to localhost (see `backend/db/connection.py`).
- **CORS.** Controlled by `CORS_ORIGINS` (comma-separated). It defaults to the Vite dev ports. The `X-Request-ID` header is exposed.
- **Tracing.** The middleware reads or creates an `X-Request-ID` and puts it in the logging context (`backend/observability`).
- **SSE errors.** Streaming endpoints report failures as an `{"type": "error", "detail": ...}` event instead of an HTTP error.

## Dependencies

`fastapi`, `uvicorn`, `starlette`, `pydantic`, `python-dotenv`, `SQLAlchemy`, `psycopg2-binary`, `httpx` (tests). Versions are pinned in `backend/requirements.txt`. Other backend modules are documented in [rag.md](rag.md), [ia.md](ia.md), [geo.md](geo.md) and [etl.md](etl.md).
