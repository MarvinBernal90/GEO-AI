# Repository structure

```text
.
├── backend/                 # Python package root (run everything from the repo root with -m)
│   ├── api/                 # FastAPI app: main.py (launcher), api.py (app, middleware, probes), deps.py,
│   │                        #   routers/, schemas/, metrics/ (request counter)
│   ├── db/                  # SQLAlchemy base, ORM models, metrics models, connection resolver
│   ├── etl/                 # Pandas pipelines (competitors, income, MITMA), S3 sync, TF-IDF, Lambda handler
│   ├── rag/                 # PDF extraction, chunking, embeddings, query engine, Bedrock/Gemini adapters
│   ├── ia/                  # LangGraph agents (agent.py, chat.py), intent extraction, chat history files
│   ├── geo/                 # Nominatim geocoding and AMB zone lookup
│   ├── cache/               # Optional Redis cache (fails open)
│   ├── observability/       # JSON logging, trace context, CloudWatch, per-request metrics spans
│   └── requirements*.txt
├── database/                # Alembic (alembic/versions 0001-0009) and the load_* scripts
├── frontend/                # Vue 3 + Vite SPA (see frontend/overview.md)
├── evals/                   # RAG quality evaluation: question sets, runner, metrics
├── deployment/              # Dockerfile (API), Dockerfile.postgis, docker-compose.yml
├── aws/bedrock/             # IAM policies for Bedrock and CloudWatch
├── scripts/                 # check_logging.py and one-off pgm_research tools
├── tests/                   # conftest.py and unit_tests/
├── notebooks/               # Exploratory analysis
├── data/                    # raw/ and processed/ (git-ignored)
├── docs/                    # This documentation
├── .github/workflows/       # integrate.yml, check-branch-name.yml, deploy.yml, deploy-frontend.yml
├── chat_history/            # Per-conversation text files written by the assistant
└── .env.example             # Template for the single root .env
```

Per-module documentation: [api](backend/api.md), [etl](backend/etl.md), [rag](backend/rag.md), [ia](backend/ia.md), [geo](backend/geo.md), [frontend](frontend/overview.md).

## Conventions

- **One `.env` at the repo root** feeds Docker (`env_file`), Alembic and the API.
- **Run from the root with `-m`** (for example `python -m backend.api.main`) so imports behave the same locally and in Docker.
- **Geo hierarchy:** `districts` (static, 10 rows) → `neighborhoods` → `competitors` (points).
- **`district_scorecard` is a SQL view**, so the opportunity score is always computed from the current income, mobility and competitor data.
- **Migrations are append-only.** Never edit an applied one; add a new file.
- **Dependency injection for tests.** Embedding functions and LLM clients are parameters, so tests run without network or API quota.

## Common commands

```bash
export DB_HOST_OVERRIDE=localhost        # reach the Docker database from the host
alembic -c database/alembic.ini upgrade head
python -m database.load_to_db
python -m database.load_legal_corpus data/raw/legal/
pytest tests/unit_tests -q
```

`DB_HOST_OVERRIDE` (and `DB_PORT_OVERRIDE`) replace the Docker hostname `postgis` in `DATABASE_URL`; leave them empty inside containers and in production.
