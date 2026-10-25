# Backend: Geo (`backend/geo`)

Two small clients for public GIS services. They turn free text into coordinates, a district and a PGM urban zone, which is what the RAG filter needs.

| File | Service | Role |
| --- | --- | --- |
| `geocoding.py` | OpenStreetMap Nominatim | `geocodificar_direccion(direccion)` returns `{lat, lon, district code, ...}` or `None`. `resolver_distrito_desde_suburb(name)` maps a district name to its code (1-10) |
| `amb_identify.py` | AMB geoportal `pla_general_metropolita_1976` `identify` | `identificar_zona_pgm(lat, lon)` does a point-in-polygon lookup and returns the PGM zone, or `None` |

## Behaviour

- **Geocoding** is limited to the Barcelona bounding box (`BARCELONA_VIEWBOX`) and sends the mandatory `User-Agent` (Nominatim answers 403 without one). The district comes from Nominatim's `suburb` field, matched case-insensitively against the 10 official districts.
- **Zoning** maps the AMB `CLAU_URB` code with an **allow-list** (`CLAU_URB_A_ZONA_PGM`: for example `12`/`12b` → `nucli_antic`, `13a`/`13b` → `densificacio_urbana`, `22a` → `industrial`). Codes without ingested legal text (roads, parks...) are discarded, so the RAG never filters on a zone it has no data for.
- **Resilience.** AMB calls use a timeout and retries. Failures return `None` instead of raising, so `GET /api/geocode` can return the district without the zone.
- **Cache.** Results go through the Redis cache (geocoding and zoning for 30 days) when available.

Used by `routers/geocoding.py`, `routers/chat.py` (clarify-or-continue flow) and the `get_opportunity_score` tool in `ia/chat.py`. Uses `requests` only, no API keys. Both services are public and rate-limited, so keep calls low-volume.
