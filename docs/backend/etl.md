# Backend: ETL (`backend/etl`)

Pandas pipelines that turn open-data CSVs into the tables the agents read. Loading into the database is done by `database/load_*.py` and by `sync_and_load.py`.

| File | Source | Output |
| --- | --- | --- |
| `config.py` | n/a | Portable paths (`data/raw`, `data/processed`), raw file names, `BARCELONA_MUNICIPIO_CODE = "08019"`. Raw files keep their government names so new releases can be dropped in |
| `competitors.py` | Open Data BCN commercial census | `build_districts` (static 10-row dimension, so partial CSVs cannot break foreign keys), `build_neighborhoods`, `build_competitors` (bars, restaurants, cafes, pubs, filtered by group and activity keywords) |
| `income.py` | INE net income | `load_district_income`. Reads as `dtype=str` and parses the Spanish number format (`13.990` = 13,990) manually |
| `etl_mitma.py` | MITMA + district names and population | `process_mitma_data()` and an idempotent upsert into `district_mobility`. `run_etl()` updates the in-memory `PROGRESS` dict |
| `tfidf.py` | `data/raw/nomenclator.csv` | TF-IDF vectorizer and matrix of official street names in `data/processed/`, used by the assistant's `find_in_nomenclator` tool. Run `python -m backend.etl.tfidf` |
| `sync_and_load.py` | S3 data lake | Downloads raw data from S3 and runs the full ingestion (migrations, users, census, income, MITMA, legal corpus), or one object with `--s3-key` |
| `lambda_handler.py` | S3 `ObjectCreated` events | Forwards the event to `POST /api/etl/s3-event`, or runs `process_s3_event_key` directly (`LAMBDA_EXECUTION_MODE=direct`) |

## Running

- Local: `database/load_to_db.py` (socioeconomic), `database/load_legal_corpus.py` and `load_general_law.py` (legal), `load_users.py`. `database/load_all.sh` chains them. Schema comes from Alembic.
- Deployed: `sync_and_load.py` inside the API container, or the S3 → Lambda → `/api/etl/s3-event` path.

## Tables (`backend/db/models.py`, `metrics_models.py`)

`districts`, `neighborhoods`, `competitors`, `district_income`, `district_mobility` (this ETL); `legal_chunks` (RAG); `users` (login); `request_metrics`, `request_spans` (observability). The `district_scorecard` view is created by migration.

## Gotchas handled in code

- Read codes and numbers as strings (leading zeros, Spanish decimal and thousands separators).
- Static district dimension instead of one derived from the CSV.
- `sep="|"` for MITMA files, with gzip handled by pandas.

Dependencies: `pandas` 3.x, `scikit-learn`, `SQLAlchemy`, `psycopg2-binary`, `boto3` (S3). Raw files must exist under `data/raw/`; see [data-sources](../data-sources.md).
