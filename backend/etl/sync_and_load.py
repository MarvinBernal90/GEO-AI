"""
==============================================================================
S3 DATA LAKE SYNCHRONIZATION & FULL DATABASE INGESTION ORCHESTRATOR
==============================================================================
File: backend/etl/sync_and_load.py

Executes inside the `geoyield_api` container on the EC2 host (or locally).
Downloads raw datasets (CSVs, GZIPs, and legal PDFs) from the S3 Data Lake
(`s3://geoyield-raw-data-192445490421-eu-central-1/raw/`) via boto3 and runs
the complete ingestion pipeline against the internal PostgreSQL/PostGIS/pgvector
database (`postgis:5432`), removing any need to open port 5432 externally.

Usage:
    # Full sync + load (migrations, users, census, income, MITMA, legal corpus):
    python -m backend.etl.sync_and_load

    # Process a single newly uploaded S3 object (invoked by Lambda / S3 event):
    python -m backend.etl.sync_and_load --s3-key raw/legal/Article_302.pdf
"""

import argparse
import os
import re
from pathlib import Path
from urllib.parse import unquote_plus

import boto3
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.connection import resolve_database_url
from backend.etl import config, etl_mitma
from backend.etl.competitors import read_raw_census
from backend.observability import configure_logging, get_logger
from database.load_general_law import load_general_law
from database.load_legal_corpus import load_corpus_from_directory
from database.load_to_db import load_competitors, load_dimensions, load_income
from database.load_users import load_users_from_csv

logger = get_logger("etl.sync_and_load")

DEFAULT_S3_BUCKET = "geoyield-raw-data-192445490421-eu-central-1"
DEFAULT_S3_PREFIX = "raw/"

# Mapping from general law PDF filename patterns in S3 (`raw/legal/*.pdf`)
# to their canonical `fuente_legal` identifier stored in `legal_chunks`.
GENERAL_LAW_SOURCES: dict[str, str] = {
    "352884_03_es": "Decreto 322005, sobre la señalización de las limitaciones en la venta de bebidas alcohólicas.",
    "540841_02_es": "Decreto 1122010, de 31 de agosto, por el que se aprueba el Reglamento de espectáculos públicos y actividades recreativas",
    "629662_03_es": "Decreto 1212013, sobre las hojas oficiales de queja, reclamación y denuncia en las relaciones de consumo",
    "1214729": "horarios de los establecimientos abiertos al público, de los espectáculos públicos y de las actividades recreativas sometidos a la Ley 112009",
    "BOE-A-1996-1072": "Ley 182017, de 1 de agosto, de comercio, servicios y ferias.",
    "BOE-A-1996-4447": "Reglamento General sobre inscripción de empresas y afiliación, altas, bajas y variaciones de datos de trabajadores en la Seguridad Social",
    "BOE-A-1998-2989": "política lingüística",
    "BOE-A-2004-21421": "horarios comerciales",
    "BOE-A-2009-12856": "Ley 71996, de 15 de enero, de ordenación del comercio minorista",
    "BOE-A-2009-18731": "Ley 172009, de 23 de noviembre, sobre el libre acceso a las actividades de servicios y su ejercicio",
    "código de consumo": "código de consumo de Cataluña.",
    "Codigo de Consumo": "código de consumo de Cataluña.",
    "Ley 112009": "Ley 112009, de 6 de julio, de regulación administrativa de los espectáculos públicos y de las actividades recreativas",
}


def resolve_fuente_legal(pdf_filename: str) -> str:
    """Infers the canonical `fuente_legal` from a PDF filename."""
    for pattern, fuente in GENERAL_LAW_SOURCES.items():
        if pattern.lower() in pdf_filename.lower():
            return fuente
    # Fallback: strip code prefix (e.g. "BOE-A-XXXX - Law Name.pdf" -> "Law Name")
    stem = Path(pdf_filename).stem
    if " - " in stem:
        return stem.split(" - ", 1)[1].strip()
    return stem


def get_s3_client():
    region = os.getenv("AWS_REGION", "eu-central-1")
    return boto3.client("s3", region_name=region)


def sync_from_s3(
    bucket: str | None = None,
    prefix: str = DEFAULT_S3_PREFIX,
    local_raw_dir: Path | None = None,
    s3_client=None,
) -> list[Path]:
    """
    Synchronizes files from `s3://<bucket>/<prefix>` into `data/raw/`.
    Skips files that already exist locally with the exact same byte size.
    """
    bucket_name = bucket or os.getenv("S3_RAW_BUCKET", DEFAULT_S3_BUCKET)
    target_dir = local_raw_dir or config.RAW_DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    client = s3_client or get_s3_client()
    paginator = client.get_paginator("list_objects_v2")

    downloaded: list[Path] = []
    logger.info(f"Synchronizing S3 bucket s3://{bucket_name}/{prefix} -> {target_dir} ...")

    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for obj in page.get("Contents", []):
            key: str = obj["Key"]
            size: int = obj["Size"]
            if key.endswith("/") or size == 0:
                continue

            # Map `raw/foo.csv` -> `data/raw/foo.csv`, `raw/legal/bar.pdf` -> `data/raw/legal/bar.pdf`
            rel_path = key[len(prefix) :] if key.startswith(prefix) else key
            local_path = target_dir / rel_path
            local_path.parent.mkdir(parents=True, exist_ok=True)

            if local_path.exists() and local_path.stat().st_size == size:
                logger.info(f"  [SKIP] {rel_path} already exists ({size / (1024 * 1024):.2f} MB)")
                continue

            logger.info(f"  [DOWN] Downloading s3://{bucket_name}/{key} ({size / (1024 * 1024):.2f} MB)...")
            client.download_file(bucket_name, key, str(local_path))
            downloaded.append(local_path)

    logger.info(f"S3 sync finished. {len(downloaded)} new/updated file(s) downloaded.")
    return downloaded


def download_single_s3_key(
    s3_key: str,
    bucket: str | None = None,
    local_raw_dir: Path | None = None,
    s3_client=None,
) -> Path:
    """Downloads a single object from S3 into the corresponding local `data/raw/` path."""
    bucket_name = bucket or os.getenv("S3_RAW_BUCKET", DEFAULT_S3_BUCKET)
    target_dir = local_raw_dir or config.RAW_DATA_DIR
    decoded_key = unquote_plus(s3_key)
    rel_path = decoded_key[len(DEFAULT_S3_PREFIX) :] if decoded_key.startswith(DEFAULT_S3_PREFIX) else decoded_key
    local_path = target_dir / rel_path
    local_path.parent.mkdir(parents=True, exist_ok=True)

    client = s3_client or get_s3_client()
    logger.info(f"Downloading single S3 object s3://{bucket_name}/{decoded_key} -> {local_path}...")
    client.download_file(bucket_name, decoded_key, str(local_path))
    return local_path


def load_all_legal_pdfs(session: Session, legal_dir: Path | None = None) -> int:
    """
    Loads both PGM articles (`Article *.pdf` + researched PGM articles) and
    general laws (BOE/DOGC PDFs) into `legal_chunks` using Bedrock Titan V2.
    """
    base_legal_dir = legal_dir or (config.RAW_DATA_DIR / "legal")
    total_chunks = 0

    if base_legal_dir.is_dir():
        # 1. PGM single-article PDFs (Article 302.pdf, Article 303.pdf, Article 311.pdf)
        pgm_pdfs = sorted(base_legal_dir.glob("Article*.pdf"))
        if pgm_pdfs:
            pgm_tmp_dir = base_legal_dir / "_pgm_only"
            pgm_tmp_dir.mkdir(exist_ok=True)
            for p in pgm_pdfs:
                target = pgm_tmp_dir / p.name
                if not target.exists():
                    target.write_bytes(p.read_bytes())
            total_chunks += load_corpus_from_directory(session, pgm_tmp_dir)

        # 2. General Law PDFs (Decrees, BOE, DOGC)
        for pdf_path in sorted(base_legal_dir.glob("*.pdf")):
            if pdf_path.name.startswith("Article") or pdf_path.name == "OMAIIAA_Barcelona.pdf":
                continue
            fuente = resolve_fuente_legal(pdf_path.name)
            try:
                total_chunks += load_general_law(session, pdf_path, fuente)
            except Exception as exc:
                logger.warning(f"Skipping {pdf_path.name} due to error: {exc}")

    # 3. Load researched PGM zones from `candidatos_para_revisar.json` if present
    candidatos_path = config.REPO_ROOT / "candidatos_para_revisar.json"
    if candidatos_path.is_file():
        import json

        from backend.db.models import LegalChunk
        from backend.rag.embeddings import embed_texts
        from scripts.pgm_research.load_new_articles import ARTICULO_304, FUENTE, ZONA_PGM_POR_ARTICULO, limpiar_titulo

        candidatos = json.loads(candidatos_path.read_text(encoding="utf-8"))
        articulos_a_insertar = [("304", ARTICULO_304["titulo"], ARTICULO_304["contenido"], ARTICULO_304["zona_pgm"])]
        for numero, zona_pgm in ZONA_PGM_POR_ARTICULO.items():
            if numero in candidatos:
                titulo = limpiar_titulo(candidatos[numero]["titulo"])
                articulos_a_insertar.append((numero, titulo, candidatos[numero]["contenido"], zona_pgm))

        for numero, titulo, contenido, zona_pgm in articulos_a_insertar:
            existe = session.query(LegalChunk).filter_by(fuente_legal=FUENTE, numero_articulo=numero).first()
            if not existe:
                embedding = embed_texts([f"{titulo}\n{contenido}"])[0]
                session.add(
                    LegalChunk(
                        fuente_legal=FUENTE,
                        numero_articulo=numero,
                        titulo=titulo,
                        contenido=contenido,
                        versio="consolidat",
                        zona_pgm=zona_pgm,
                        embedding=embedding,
                    )
                )
                total_chunks += 1

    return total_chunks


def process_s3_event_key(s3_key: str, bucket: str | None = None, engine=None) -> dict:
    """
    Handles incremental updates when a single file is uploaded to S3:
    - If a PDF is uploaded under `raw/legal/`, extracts text, embeds with Titan V2, and upserts into `legal_chunks`.
    - If a MITMA CSV (`*_Viajes_distritos.csv.gz`) is uploaded under `raw/`, downloads it and runs `etl_mitma.run_etl()`.
    """
    load_dotenv()
    local_path = download_single_s3_key(s3_key, bucket=bucket)
    if engine is None:
        engine = create_engine(resolve_database_url(), future=True)

    filename = local_path.name
    if filename.lower().endswith(".pdf"):
        with Session(engine) as session:
            if re.match(r"^Article\s*\d+", filename, re.IGNORECASE):
                tmp_dir = local_path.parent / "_single_pgm"
                tmp_dir.mkdir(exist_ok=True)
                for old in tmp_dir.glob("*.pdf"):
                    old.unlink()
                (tmp_dir / filename).write_bytes(local_path.read_bytes())
                count = load_corpus_from_directory(session, tmp_dir)
            else:
                fuente = resolve_fuente_legal(filename)
                count = load_general_law(session, local_path, fuente)
            session.commit()
        return {"status": "completed", "type": "legal_pdf", "file": filename, "chunks_upserted": count}

    if filename.endswith("_Viajes_distritos.csv.gz"):
        etl_mitma.run_etl()
        return {"status": etl_mitma.PROGRESS["status"], "type": "mitma_csv", "file": filename}

    return {"status": "ignored", "file": filename, "reason": "Unsupported file pattern"}


def run_full_sync_and_load(
    bucket: str | None = None,
    skip_mitma: bool = False,
    skip_legal: bool = False,
    engine=None,
) -> dict:
    """
    Executes the complete S3 sync + PostgreSQL ingestion pipeline inside EC2.
    """
    load_dotenv()
    sync_from_s3(bucket=bucket)

    if engine is None:
        engine = create_engine(resolve_database_url(), future=True)

    # 1. Users
    with Session(engine) as session:
        users_loaded = load_users_from_csv(session)

    # 2. Census (Districts, Neighborhoods, Competitors) + Income
    logger.info("Loading commercial census (districts, neighborhoods, competitors) and INE income...")
    raw_census_df = read_raw_census(config.PATH_CENSCOMER)
    with Session(engine) as session:
        load_dimensions(session, raw_census_df)
        session.flush()
        load_competitors(session, raw_census_df)
        load_income(session, config.PATH_INE_RENTA)
        session.commit()

    # 3. MITMA Mobility
    if not skip_mitma:
        logger.info("Running MITMA mobility ETL...")
        etl_mitma.run_etl()
        if etl_mitma.PROGRESS["status"] == "error":
            raise RuntimeError(f"MITMA ETL failed: {etl_mitma.PROGRESS['message']}")

    # 4. Legal Corpus (PGM + General Laws)
    legal_chunks_loaded = 0
    if not skip_legal:
        logger.info("Loading and vectorizing legal corpus via Bedrock Titan V2...")
        with Session(engine) as session:
            legal_chunks_loaded = load_all_legal_pdfs(session)
            session.commit()

    summary = {
        "status": "completed",
        "users_loaded": users_loaded,
        "mitma_status": "skipped" if skip_mitma else etl_mitma.PROGRESS["status"],
        "legal_chunks_loaded": legal_chunks_loaded,
    }
    logger.info(f"Full S3 Sync & Load completed: {summary}")
    return summary


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Synchronize S3 Data Lake and load into PostgreSQL/PostGIS/pgvector.")
    parser.add_argument("--bucket", default=None, help="S3 bucket name override.")
    parser.add_argument("--s3-key", default=None, help="Process only a specific S3 object key (incremental mode).")
    parser.add_argument("--skip-mitma", action="store_true", help="Skip the heavy MITMA CSV processing step.")
    parser.add_argument("--skip-legal", action="store_true", help="Skip the legal PDF vectorization step.")
    args = parser.parse_args()

    if args.s3_key:
        process_s3_event_key(args.s3_key, bucket=args.bucket)
    else:
        run_full_sync_and_load(bucket=args.bucket, skip_mitma=args.skip_mitma, skip_legal=args.skip_legal)


if __name__ == "__main__":
    main()
