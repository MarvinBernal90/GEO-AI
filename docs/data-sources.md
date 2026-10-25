# Data sources

Every dataset the system ingests, so each answer can be traced to its origin. The agent never browses the web for answers: it reasons only over the data below (plus two live lookups, geocoding and zoning, listed at the end).

## Socioeconomic and geospatial data (ETL into PostGIS)

Raw files go in `data/raw/` (git-ignored); file names are set in `backend/etl/config.py`.

| Source | Dataset | Used for |
| --- | --- | --- |
| Open Data BCN | *Cens comercial de la ciutat de Barcelona* (CSV) | Competitor locations (bars, restaurants, cafes) and market saturation |
| INE | *Atlas de Distribución de Renta de los Hogares* | Average income per district (`renta_media`) |
| MITMA | *Estudio de Movilidad con Big Data* (`*_Viajes_distritos.csv.gz`) | Foot traffic and trips per district (`district_mobility`) |
| Ajuntament de Barcelona | District names, population and the official street register (`nomenclator.csv`) | District dimension and address matching (TF-IDF) |

MITMA data is only available at district level, so the opportunity score is computed deterministically from foot traffic, income and competition (view `district_scorecard`).

## Legal corpus (embedded into pgvector)

Raw PDFs go in `data/raw/legal/`.

| Source | Content |
| --- | --- |
| AMB, NUMAMB portal | *Pla General Metropolità* (PGM) zoning articles. Only the current consolidated version of each article is kept |
| BOE and DOGC | National and Catalan laws and decrees on commerce, hospitality, consumer protection and opening hours (for example Decreto 112/2010, Ley 11/2009, Ley 18/2017, Código de Consumo de Cataluña) |

## Live lookups at request time

| Service | Used for |
| --- | --- |
| Nominatim (OpenStreetMap) | Address to coordinates and district |
| AMB geoportal `identify` (`pla_general_metropolita_1976`) | Coordinates to PGM zone |

Both are public and rate-limited, results are cached, and the system never invents a result when they fail.
