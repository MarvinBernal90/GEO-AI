# Estructura del repositorio

Esta es la estructura vigente del proyecto (Fase 0 en adelante). Sustituye a
`README_repo_desc.md`, que describía una estructura de un ejercicio anterior
del máster (`src/model.py`, `unit_tests/`, `model tests/`) ya no aplicable a
Geo-Yield-AI — ese fichero debe eliminarse del repo.

```
.
├── backend/
│   ├── api/
│   │   ├── main.py          # Punto de entrada (uvicorn), logging, carga de .env
│   │   ├── api.py           # App FastAPI: lifespan, /health, /ready, /metrics
│   │   ├── schemas/         # DTOs Pydantic del dominio (Fase 3-4)
│   │   └── metrics/         # Métricas in-memory básicas
│   ├── ia/
│   │   └── agent.py         # Orquestador del agente RAG (Fase 3, pendiente)
│   └── requirements.txt
│
├── database/
│   └── seed_data.sql        # Migraciones/carga inicial (Fase 1, pendiente)
│
├── notebooks/                # EDA y prototipado de datos (MITMA, INE, GenCAT)
│
├── frontend/                  # Vue 3 + Vite
│
├── deployment/
│   ├── Dockerfile             # Build con contexto en la raíz del repo
│   ├── docker-compose.yml     # api + postgis (Postgres/PostGIS + pgvector)
│   └── .dockerignore
│
├── docs/
│   ├── structure.md            # Este documento
│   ├── data-sources.md         # Fuentes de datos (pendiente de completar)
│   ├── diagram.md              # Diagrama de arquitectura de alto nivel
│   └── adr/                    # Decisiones de arquitectura (Architecture Decision Records)
│
├── tests/
│   ├── unit_tests/
│   └── model_tests/             # Se reutilizará para tests del agente/RAG en fases posteriores
│
├── .github/workflows/
│   ├── integrate.yml            # CI: tests en pull request
│   ├── check-branch-name.yml    # Valida convención de nombres de rama y Git-Flow
│   └── deploy.yml               # CD manual a Render
│
├── .env.example                 # Plantilla única de variables de entorno
└── README.md
```

## Notas

- **Un único `.env`** vive en la raíz del repo. `docker-compose.yml` lo
  referencia como `../.env` en vez de duplicar variables en un `.env`
  aparte dentro de `deployment/`.
- El paquete Python raíz es `backend` (`backend/__init__.py`), de modo que
  la app se ejecuta como `python -m backend.api.main` desde la raíz del
  repo, tanto en local como dentro del contenedor Docker.
- `backend/ia/agent.py` es el punto de entrada previsto para el orquestador
  del agente (Fase 3). Hoy está vacío intencionadamente.
