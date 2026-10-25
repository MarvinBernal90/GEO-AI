# Frontend

Vue 3 + Vite single-page app. The user picks (or describes) a location in Barcelona and gets district data, a competitor map, legal citations and a traffic-light verdict (`verde` / `ambar` / `rojo`) streamed from the backend. A second page shows request metrics and RAG quality.

## Stack

| Package | Role |
| --- | --- |
| `vue` 3.5, `vue-router` 4 | `<script setup>` components; two routes, no global store |
| `vite` 8 + `@vitejs/plugin-vue` | Dev server and bundler |
| `tailwindcss` 4 + `@tailwindcss/vite` | Styling (`src/style.css`) |
| `leaflet`, `@vue-leaflet/vue-leaflet`, `vue-leaflet-markercluster` | District map and clustered competitors |
| `echarts` 6 | Charts in the metrics dashboard |
| `eslint`, `eslint-plugin-vue`, `prettier` | Lint and format |

Fonts (Fraunces, IBM Plex) load from Google Fonts in `index.html`.

## Commands

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # dist/
npm run lint         # or lint:fix
npm run format       # or format:check
```

## Configuration (`frontend/.env`, see `.env.example`)

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Backend URL, default `http://localhost:8000` (docker-compose publishes the API on `8080`) |
| `VITE_APP_VERSION` | Added to every log as `version` (the deploy workflow sets the commit SHA) |
| `VITE_LOG_LEVEL`, `VITE_LOG_REMOTE` | Optional logger overrides |

Only `VITE_`-prefixed variables reach the browser. The backend must list the frontend origin in `CORS_ORIGINS`.

## Layout

```
frontend/src/
├── main.js, App.vue          # App bootstrap, global error handlers; App hosts the RouterView
├── router/index.js           # /  (HomeView), /metrics (lazy), /evals → /metrics?tab=rag
├── views/
│   ├── HomeView.vue          # Viability dossier: all state and orchestration
│   └── MetricsView.vue       # Request metrics and RAG quality tabs
├── components/               # ViabilityForm, VerdictCard, DistrictMap, RegulationsViewer, ChatBubble
│   └── metrics/              # KpiCard, ChartCard, EChart, RequestsTable, RequestDetail, RagEvalsPanel
├── composables/              # useMetrics, useRagEvals
├── services/                 # api.js (every backend call and SSE parsing), logger.js
├── constants/, utils/        # Logger limits; chart theme and formatters
```

## How it works

`HomeView` owns the state and passes it to children by props; children answer with emits.

1. **Form flow.** `ViabilityForm` loads districts and PGM zones, and can geocode an address (`GET /api/geocode`). On submit, `generarInformeStream` calls `POST /api/reports/stream`.
2. **Streaming.** The report arrives as SSE: a `datos` event (district data, legal answer, cited articles), `token` events for the synthesis, then `done` (confirmed verdict and summary) or `error`. While tokens arrive the UI guesses the verdict from the first line; `done` overrides it.
3. **Chat, anonymous.** The free-text prompt goes to `POST /api`. The backend may answer with `aclaracion` (needs a clearer address or district) or `ubicacion` (resolved location) before streaming the report.
4. **Chat, logged in.** After `POST /api/login` (username only, returns past conversations), messages go to `POST /api/assistant`, the ReAct agent with memory, using `thread_id = "<user>:<n>"`. History loads from `GET /api/gethistory`. User and conversation are kept in `localStorage`.
5. **Map.** `DistrictMap` fetches competitors by district or point and clusters them.
6. **Citations.** Clicking a cited article opens `RegulationsViewer` (`GET /api/articles`) so the user can read the source.
7. **Metrics.** `/metrics` shows request KPIs, charts, a request table with span detail, and the *Calidad RAG* tab (`?tab=rag`). The link appears only for logged-in users.

## Observability

`services/logger.js` emits the same JSON schema as the backend. In `dev` it prints readable logs; in a production build it also ships batches to `POST /api/logs`. Every request carries an `X-Request-ID`. Logging never breaks the app: the buffer is capped, retries are bounded, and shipping disables itself after repeated failures. See [observability](../observability.md).
