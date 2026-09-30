# Running Geo-Yield-AI locally

Local-only notes, not meant to be shared/committed. Run everything from `deployment/`:

```bash
cd deployment
```

## 1. Normal day-to-day run (DB + API, no data reload)

```bash
docker compose up -d
```

This starts `postgis` and `api` only. The `ingestion` service is **not** included in a
plain `up` (it has `profiles: ["ingestion"]` in docker-compose.yml specifically so it
never runs automatically) — the business census data already sitting in the `geoyield_db`
Docker volume from a previous ingestion run is reused as-is.

Check it's up:

```bash
curl localhost:8080/health
curl "localhost:8080/businesses?limit=3"
```

Stop it (data survives, since it lives in a named volume):

```bash
docker compose down
```

## 2. Loading/refreshing the census data (occasional, not every run)

Only needed:
- the very first time, before `business_census` has any rows, or
- when you deliberately want to pull a fresh snapshot from Open Data BCN (the source
  dataset updates in batches, not live — see `docs/data-sources.md` — so this is a
  "maybe monthly" thing, not something to run per session).

```bash
docker compose up -d postgis                 # make sure the DB is up first
docker compose run --rm ingestion             # one-shot job, downloads ~44k rows and upserts them
```

It's idempotent (upsert on `id_global`), so re-running it doesn't duplicate rows — safe
to run again if you just want the latest data.

Check row count directly if you want to confirm:

```bash
docker exec geoyield_db psql -U postgres -d geoyield -c "SELECT count(*) FROM business_census;"
```

## 3. Rebuilding the API after code changes

```bash
docker compose up -d --build api
docker logs geoyield_api --tail 40
```

## 4. Wiping everything (including the DB volume)

Only if you actually want to start from zero — you'll need to re-run the ingestion
step (§2) afterwards since this deletes the data too:

```bash
docker compose down -v
```

## Endpoints once it's running

- `GET /health`
- `GET /businesses` — list/filter, paginated
- `GET /businesses/{id_global}` — single record
- `GET /businesses/density` — competitor counts per barri/district
- `GET /businesses/geojson` — same filters as the list, GeoJSON `FeatureCollection`
- `POST /predict` — ML rent-prediction endpoint, separate concern, needs `GITHUB_REPO`/a
  published model release to work; not related to the census data above.

## Example business queries

Filters available on `/businesses` and `/businesses/geojson`: `codi_districte`, `codi_barri`,
`nom_activitat` (substring match), `q` (free text over name + activity), `min_lat`/`max_lat`/
`min_lon`/`max_lon` (bbox), `limit`/`offset`. `/businesses/density` takes `group_by`
(`districte` or `barri`) plus an optional `nom_activitat` filter.

Pretty-print any of these by piping to `python3 -m json.tool`.

### Basic listing

```bash
# First 5 rows, no filters
curl "localhost:8080/businesses?limit=5"

# All businesses in a district (1=Ciutat Vella, 2=Eixample, 3=Sants-Montjuïc, ... 10=Sant Martí)
curl "localhost:8080/businesses?codi_districte=2&limit=5"

# All businesses in a specific barri (barri codes/names come back from the density endpoint below)
curl "localhost:8080/businesses?codi_barri=31&limit=5"
```

### Filtering by activity

```bash
# Every restaurant citywide
curl "localhost:8080/businesses?nom_activitat=Restaurants&limit=5"

# Souvenir shops, restricted to Ciutat Vella
curl "localhost:8080/businesses?nom_activitat=Souvenirs&codi_districte=1&limit=10"
```

### Free-text search (matches nom_local OR nom_activitat)

```bash
curl "localhost:8080/businesses?q=pizza&limit=10"
```

### Pagination

```bash
curl "localhost:8080/businesses?limit=20&offset=40"
```

### Bounding-box (geographic) search

```bash
# Roughly the Sagrada Familia area
curl "localhost:8080/businesses?min_lat=41.400&max_lat=41.407&min_lon=2.170&max_lon=2.179&limit=10"
```

### Combining filters

```bash
curl "localhost:8080/businesses?codi_districte=2&nom_activitat=Roba&q=nens&limit=5"
```

### Single business lookup

```bash
ID=$(curl -s "localhost:8080/businesses?limit=1" | python3 -c "import json,sys; print(json.load(sys.stdin)['results'][0]['id_global'])")
curl "localhost:8080/businesses/$ID"
```

### Competitor density (the aggregation the scoring engine needs)

```bash
# Total businesses per district
curl "localhost:8080/businesses/density?group_by=districte" | python3 -m json.tool

# Total businesses per barri (neighborhood), most saturated first
curl "localhost:8080/businesses/density?group_by=barri" | python3 -m json.tool

# Restaurant density per barri — e.g. to check competitor saturation before opening one
curl "localhost:8080/businesses/density?group_by=barri&nom_activitat=Restaurants" | python3 -m json.tool
```

### GeoJSON export (for the Vue map layer)

```bash
# Everything in Ciutat Vella, ready to drop onto a map
curl "localhost:8080/businesses/geojson?codi_districte=1&limit=1000" -o ciutat_vella.geojson

# Just the restaurants in one barri
curl "localhost:8080/businesses/geojson?codi_barri=31&nom_activitat=Restaurants"
```

## Troubleshooting

- `docker compose ps -a` — see what's running/exited.
- `docker logs geoyield_db --tail 50` / `docker logs geoyield_api --tail 50`.
- If `postgis` never turns "healthy": `docker inspect --format='{{.State.Health.Status}}' geoyield_db`.
- `docker compose config -q` — validates the compose file + env resolution without starting anything.
