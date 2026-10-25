# Observability

Backend and frontend emit the **same JSON log schema**, so one CloudWatch Logs Insights query covers both. Request metrics are stored separately in Postgres and shown at `/metrics`.

## Structured logs

```json
{"timestamp":"...","level":"ERROR","service":"geoyield-api","env":"production","version":"<sha>",
 "logger":"geoyield_api","message":"...","trace_id":"8f3c1a2b4d5e6f70","duration_ms":1234,
 "error":{"type":"","message":"","stack":""},"context":{"codi_districte":"01"}}
```

| Side | Code | Usage |
| --- | --- | --- |
| Backend | `backend/observability/` | `logging.getLogger("geoyield_api")`; for context use `log_event(logger, "INFO", "msg", codi_districte="01")` |
| Frontend | `frontend/src/services/logger.js` | `createLogger(...)` then `log.error('msg', { error })` or `log.event('informe.generado', {...})` |

**Correlation.** The frontend sends a `trace_id` in `X-Request-ID`; the backend adds it to every log line of that request (RAG, agent and database included).

```
fields @timestamp, service, level, message, duration_ms
| filter trace_id = "8f3c1a2b4d5e6f70"
| sort @timestamp asc
```

Each model call also emits an `llm.invoke` event (`model`, `duration_ms`, `input_tokens`, `output_tokens`, `outcome`).

## Local vs production

Behaviour follows `ENV` (and the Vite build mode); nothing to configure day to day.

| | Local (`ENV=development`, `npm run dev`) | Production (`ENV=production`, `npm run build`) |
| --- | --- | --- |
| Format | Coloured text | One JSON line per event |
| Level | DEBUG | INFO |
| Frontend logs | Browser console | Console + `POST /api/logs` |
| CloudWatch | Never | When shipping is configured |

Overrides: `LOG_LEVEL`, `LOG_FORMAT`, `LOG_CLOUDWATCH_ENABLED`, `VITE_LOG_REMOTE`. To reproduce production format locally: `LOG_FORMAT=json python -m backend.api.main`.

## CloudWatch

The browser cannot call CloudWatch without credentials, so it posts batches to `POST /api/logs` and the backend re-emits them. From there:

1. **stdout collected by the host (default).** `deployment/docker-compose.yml` sets the `awslogs` driver on `api` (group `/geoyield/api`, override with `LOG_CLOUDWATCH_DOCKER_GROUP`). The instance profile authenticates (policy in `aws/bedrock/bedrock-policy.json`). Leave `LOG_CLOUDWATCH_GROUP` **unset**, or every line is ingested twice.
2. **Direct shipping**, for hosts that do not collect stdout. Set `LOG_CLOUDWATCH_GROUP` and install `watchtower` (commented out in `backend/requirements.txt`). Only active with `ENV=production`.

Production `.env` checklist: `ENV=production`, `CORS_ORIGINS=<frontend origin>`, `TRUSTED_PROXY_HOPS` matching the proxies in front of the API. The deploy workflows set `SERVICE_VERSION` and `VITE_APP_VERSION` to the commit SHA.

## Request metrics and RAG quality

- **Traces.** Every request records spans (NLU, geocoding, zone lookup, RAG, LLM) in `request_metrics` and `request_spans` (migration `0009`). Spans store sizes and yes/no results, never user text. `GET /api/metrics/overview`, `/requests` and `/requests/{id}` feed the `/metrics` dashboard (the UI link is only shown to logged-in users).
- **RAG quality.** The dashboard's *Calidad RAG* tab reads eval runs through `GET /api/evals/*`. See [`evals/README.md`](../evals/README.md).
- **Probes.** `/health`, `/ready` and `/metrics` (a simple request counter) are not logged.

## Privacy (GDPR)

The free-text address is personal data and is never logged; the resulting district and zone are logged instead. `backend/observability/logging_config.py` redacts sensitive keys (`direccion`, `email`, `token`, `api_key`, ...) in backend logs and in those arriving from the browser.
