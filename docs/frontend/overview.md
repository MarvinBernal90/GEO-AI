# Frontend

Single-page app (Vue 3 + Vite) for the "viability dossier": the user picks (or describes) a location in Barcelona and gets district data, a competitor map, legal citations and a traffic-light verdict (`verde` / `ambar` / `rojo`) streamed from the backend.

## Stack and dependencies

| Package | Role |
| --- | --- |
| `vue` 3.5 | UI, `<script setup>` SFCs, no router, no store |
| `vite` 8 + `@vitejs/plugin-vue` | Dev server and bundler |
| `tailwindcss` 4 + `@tailwindcss/vite` | Styling (imported in `src/style.css`) |
| `leaflet`, `@vue-leaflet/vue-leaflet`, `leaflet.markercluster`, `vue-leaflet-markercluster` | District map and clustered competitor markers |
| `eslint` 10, `eslint-plugin-vue`, `prettier` | Lint and format |

Requires Node.js and npm. Fonts (Fraunces, IBM Plex) load from Google Fonts in `index.html`.

## Commands

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # outputs dist/
npm run lint         # or lint:fix
npm run format       # or format:check
```

## Configuration (`frontend/.env`, see `.env.example`)

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Backend URL. Defaults to `http://localhost:8000`. docker-compose publishes the API on `8080`. |
| `VITE_APP_VERSION` | Added to every log as `version`. |
| `VITE_LOG_LEVEL`, `VITE_LOG_REMOTE` | Optional logger overrides. |

Only `VITE_`-prefixed variables reach the browser. The backend must list the frontend origin in its `CORS_ORIGINS`.

## Layout

```
frontend/src/
├── main.js                 # createApp + global error handlers (Vue, window.error, unhandledrejection) -> logger
├── App.vue                 # Root component: all state, orchestration, two-column layout
├── style.css               # Tailwind entry
├── components/
│   ├── ViabilityForm.vue   # District / PGM zone / address inputs; emits `generar`
│   ├── VerdictCard.vue     # Traffic-light verdict and summary
│   ├── DistrictMap.vue     # Leaflet map + competitor clusters
│   ├── RegulationsViewer.vue # Side panel with the raw text of a cited article
│   └── ChatBubble.vue      # Chat message / clarification rendering; emits `ver-articulo`
├── services/
│   ├── api.js              # Every backend call (fetch + SSE parsing)
│   └── logger.js           # Structured logger, batches events to POST /api/logs
└── constants/logger.constant.js  # Logger limits, levels and env-derived flags
```

## How it works

`App.vue` owns all state and passes it to children via props; children talk back with emits. There is no router or global store.

1. **Form flow.** `ViabilityForm` loads districts (`GET /api/districts`) and PGM zones (`GET /api/pgm-zones`), and can geocode an address (`GET /api/geocode`). On submit, `App.vue` calls `generarInformeStream` (`POST /api/reports/stream`).
2. **Streaming.** The report arrives as Server-Sent Events: a `datos` event (district data, legal answer, cited articles), then `token` events for the synthesis text, then `done` (confirmed `semaforo` and `resumen`) or `error`. While tokens arrive, the UI guesses the verdict from the first line of text; `done` overrides it.
3. **Chat flow, anonymous.** The free-text prompt goes to `POST /api/chat/informe/stream`. The backend may answer with an `aclaracion` event (needs a clearer address or district) or a `ubicacion` event (resolved location) before streaming the report.
4. **Chat flow, logged in.** After `POST /api/login` (username only, returns the user's past conversations), messages go to `POST /api/assistant`, a ReAct agent with memory. The conversation id is `thread_id = "<user>:<n>"`, and history is loaded with `GET /api/gethistory`. The selected conversation and user are kept in `localStorage`.
5. **Map.** `DistrictMap` fetches competitors (`GET /api/competitors`) by district or by point and clusters them.
6. **Citations.** Clicking a cited article opens `RegulationsViewer`, which calls `GET /api/articles` so the user can check the source.

## Observability

`services/logger.js` emits the same JSON schema as the backend logger. In `dev` it prints readable logs to the console. In a production build it also ships batches to `POST /api/logs`, which the backend forwards to CloudWatch. Every request carries an `X-Request-ID` trace id. Logging is wrapped so it can never break the app. The buffer is capped, retries are bounded, and shipping disables itself after repeated failures.
