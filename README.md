# Geo-Yield-AI

Plataforma de *Location Intelligence* para evaluar en segundos si abrir un bar o restaurante en Barcelona es viable. Combina **datos socioeconómicos por distrito** con la **normativa urbanística (PGM)**, citando siempre el artículo exacto, y devuelve un informe con semáforo (verde / ámbar / rojo).

Se usa por formulario con mapa, o escribiendo una frase libre en el chat ("quiero abrir un bar en tal calle, ¿puedo poner terraza?").

## Qué incluye

- **Motor RAG legal:** normativa del PGM, BOE y DOGC troceada por artículo, con embeddings en pgvector y respuestas con cita. Si el corpus no cubre la pregunta, lo dice en vez de inventar.
- **Agente de viabilidad (LangGraph):** cruza en paralelo datos del distrito y normativa de la zona PGM, y sintetiza el informe en streaming (SSE).
- **Zona PGM automática:** dirección → Nominatim → servicio Identify del AMB. Si no se puede confirmar, se pide selección manual; nunca se adivina.
- **Chat:** una frase libre se convierte en dirección/distrito/pregunta. Con sesión iniciada hay un asistente ReAct con memoria persistente por conversación.
- **Mapa y visor de normativa:** competidores agrupados (distrito o radio de 500 m) y texto completo de cada artículo citado.
- **Métricas:** panel `/metrics` con trazas por petición y una pestaña de calidad RAG (ver [`evals/`](evals/README.md)).

## Stack

| Capa | Tecnología |
| :--- | :--- |
| Backend | Python 3.12, FastAPI + Uvicorn, SQLAlchemy, Alembic |
| Datos | PostgreSQL 18 + PostGIS + pgvector en un solo contenedor ([ADR 0001](docs/adr/0001-pgvector-vs-qdrant.md)); Redis opcional como caché |
| IA | AWS Bedrock por defecto: Titan Embeddings V2 (1024 dim), Amazon Rerank 1.0 y Nova 2 Lite. Gemini con `LLM_PROVIDER=gemini` |
| Agentes | LangGraph (informe de viabilidad y asistente ReAct con `PostgresSaver`) |
| Frontend | Vue 3, Vite, Tailwind 4, Leaflet, ECharts |
| DevOps | Docker, GitHub Actions, AWS (EC2, S3, CloudFront, CloudWatch) |

## Arranque rápido

Requisitos: Docker, Python 3.12, Node.js, `poppler-utils` (`pdftotext`, para ingerir PDFs) y credenciales de AWS con acceso a Bedrock (o `GEMINI_API_KEY`).

```bash
cp .env.example .env            # edita POSTGRES_*, AWS_PROFILE / AWS_REGION
aws sso login --profile <tu-perfil>

# 1. Base de datos
docker compose --env-file .env -f deployment/docker-compose.yml up -d --build postgis
pip install -r backend/requirements.txt

# 2. Esquema y datos (DB_HOST_OVERRIDE=localhost permite conectar desde el host)
export DB_HOST_OVERRIDE=localhost
alembic -c database/alembic.ini upgrade head
python -m database.load_to_db                       # CSV en data/raw/
python -m database.load_legal_corpus data/raw/legal/  # PDFs del PGM
python -m database.load_users                       # data/users/users.csv
python -m backend.etl.tfidf                         # índice de calles (data/raw/nomenclator.csv)

# 3. API (http://localhost:8000, docs en /docs)
uvicorn backend.api.api:app --reload --port 8000

# 4. Frontend (http://localhost:5173)
cd frontend && npm install && npm run dev
```

`database/load_all.sh` carga además el resto de leyes con `database.load_general_law`. Para ampliar zonas del PGM, ver [`scripts/pgm_research/`](scripts/pgm_research/README.md).

## API

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/districts`, `/api/pgm-zones` | Opciones del formulario |
| `POST` | `/api/reports` · `/api/reports/stream` | Informe completo, en JSON o por SSE |
| `POST` | `/api` | Chat unificado: frase libre → informe, o asistente si hay `thread_id` |
| `POST` | `/api/assistant` | Asistente ReAct con memoria (SSE) |
| `GET` | `/api/geocode` | Dirección → distrito + zona PGM |
| `GET` | `/api/competitors` | Competidores por distrito o por radio |
| `GET` | `/api/articles` | Texto completo de un artículo |
| `POST` / `GET` | `/api/login` · `/api/gethistory` | Usuario y conversaciones |
| `GET` | `/api/metrics/*` · `/api/evals/*` | Datos de los paneles de métricas y de calidad RAG |
| `POST` | `/api/logs` | Logs del navegador |
| `POST` | `/api/etl/*` | Disparadores de ETL (token de webhook) |
| `GET` | `/health` · `/ready` · `/metrics` | Sondas y contador de peticiones |

## Desarrollo

```bash
pytest tests/unit_tests -q              # ~450 tests; los de BD se saltan si no hay base de datos
ruff check backend && ruff format --check backend
cd frontend && npm run lint && npm run format:check
```

CI (`integrate.yml`) ejecuta tests, Ruff y ESLint/Prettier en cada PR. `deploy.yml` y `deploy-frontend.yml` despliegan desde `develop` a EC2 (vía SSM) y a S3 + CloudFront. Los cambios de esquema son migraciones nuevas, nunca se edita una ya aplicada.

## Documentación

- [`docs/structure.md`](docs/structure.md): estructura del repositorio y comandos habituales
- [`docs/architecture-and-audit.md`](docs/architecture-and-audit.md) y [`docs/diagram.md`](docs/diagram.md): arquitectura y decisiones de diseño
- [`docs/observability.md`](docs/observability.md): logging estructurado, CloudWatch y privacidad
- [`docs/backend/`](docs/backend/api.md) y [`docs/frontend/`](docs/frontend/overview.md): un documento por módulo
- [`docs/data-sources.md`](docs/data-sources.md): fuentes de datos y linaje
- AWS: [migración](docs/aws-migration-assessment.md), [RDS](docs/aws-rds-migration.md), [CD](docs/aws-cd-assessment.md), [Cognito](docs/aws-cognito-assessment.md), [IaC](docs/IaC_generator.md)
- Calidad RAG: [`docs/rag_metrics_assessment.md`](docs/rag_metrics_assessment.md) y [`evals/README.md`](evals/README.md)

## Limitaciones conocidas

- Nominatim y el geoportal del AMB son servicios externos que pueden fallar; se reintenta, pero no se inventa un resultado.
- El corpus cubre 10 claves urbanísticas del PGM (más de 50 en total); para el resto se pide selección manual.
- Renta y afluencia son promedios por distrito, sin desagregar por zona ni franja horaria.
- El chat no recomienda distritos: pide al menos un distrito o dirección.
- El login es solo por nombre de usuario (usuarios precargados), sin contraseña. Ver la [propuesta con Cognito](docs/aws-cognito-assessment.md).

## Equipo

Proyecto del Máster en IA, Cloud y DevOps (Pontia): Manuel Yerbes García, Marvin Bernal, Enmanuel De Oleo y Claudi Berenguer Sabaté.
