# Backend: ETL (`backend/etl`)

Pure transformation pipelines (pandas) that turn open-data CSVs into the tables the agents read. Loading into the DB is done by scripts in `database/` (`load_all.sh`, `load_to_db.py`) and by `etl_mitma.py`.

## Files

| File | Source | Output |
| --- | --- | --- |
| `config.py` | n/a | Portable paths (`data/raw`, `data/processed`), raw filenames and `BARCELONA_MUNICIPIO_CODE = "08019"`. Raw files keep their original government names, so new releases can be dropped in. |
| `competitors.py` | Open Data BCN commercial census | `build_districts` (static 10-row dimension, so partial CSVs cannot break foreign keys), `build_neighborhoods`, `build_competitors` (bars, restaurants, cafes, pubs, etc., filtered by group plus activity keywords, with required columns checked) |
| `income.py` | INE net income per person | `load_district_income`. Reads as `dtype=str` and parses the Spanish number format (`13.990` = 13,990) manually. |
| `mobility.py` | MITMA district trips (`*_Viajes_distritos.csv.gz`, pipe-separated) | `load_district_mobility`. Computes daily foot traffic arriving at each district. Codes are read as strings to keep leading zeros. |
| `etl_mitma.py` | MITMA + district names and population | Larger variant. `process_mitma_data()` plus an idempotent upsert into `district_mobility`. `run_etl()` updates the in-memory `PROGRESS` dict. |

## Running

- Command line: `database/load_all.sh` (see [structure.md](../structure.md)). Schema comes from Alembic migrations in `database/alembic/versions`.
- Through the API: `POST /api/etl/mitma` starts `run_etl` as a background task, and `GET /api/etl/mitma/progress` returns `{status, progress, elapsed, message}`. Only one run at a time. `PROGRESS` is in memory, so it resets on restart.

## Target tables (`backend/db/models.py`)

`districts`, `neighborhoods`, `competitors`, `district_income`, `district_mobility`. The RAG uses `legal_chunks`, and login uses `users`.

## Gotchas handled in code

- Read codes and numbers as strings (leading zeros, Spanish decimal and thousands separators).
- Static district dimension instead of one derived from the CSV.
- `sep="|"` for MITMA files, with gzip handled by pandas.

## Dependencies

`pandas` 3.x, `SQLAlchemy`, `psycopg2-binary`. Raw data files must exist under `data/raw/`. See [data-sources.md](../data-sources.md) for where to get them.
