"""
Orquestador de carga del corpus legal (Fase 2): lee los PDF de artículos
normativos, los parte por artículo (quedándose solo con la versión
vigente), genera embeddings y los escribe en `legal_chunks`.

Uso:
    DB_HOST_OVERRIDE=localhost python -m database.load_legal_corpus data/raw/legal/

Diseño testeable: `run()` acepta una función de embedding inyectable
(`embed_fn`), igual que el resto del pipeline acepta un `engine` inyectable
(ver database/load_to_db.py de la Fase 1). Por defecto usa el modelo local
real (backend/rag/embeddings.embed_texts), pero los tests pueden inyectar
una función falsa para no depender de tener el modelo descargado.
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.db.connection import resolve_database_url
from backend.db.models import LegalChunk
from backend.rag.chunking import ARTICLE_TO_ZONA_PGM, parse_legal_chunks, select_current_versions
from backend.rag.embeddings import EmbeddingFunction, embed_texts
from backend.rag.pdf_extraction import extract_text_from_pdf

logger = logging.getLogger("geoyield_rag")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def load_corpus_from_directory(
    session: Session, pdf_dir: Path, embed_fn: EmbeddingFunction = embed_texts
) -> int:
    """
    Procesa todos los .pdf de `pdf_dir`, cada uno con potencialmente varias
    versiones históricas de un artículo, y deja en `legal_chunks` solo la
    vigente de cada uno. Devuelve el número de artículos cargados.
    """
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        logger.warning(f"No se encontraron PDF en {pdf_dir}")
        return 0

    all_current_chunks = []
    for pdf_path in pdf_paths:
        logger.info(f"Procesando {pdf_path.name}...")
        text = extract_text_from_pdf(pdf_path)
        versions = parse_legal_chunks(text)
        if not versions:
            logger.warning(f"{pdf_path.name}: no se detectó ningún artículo, se omite.")
            continue
        current = select_current_versions(versions)
        for chunk in current:
            all_current_chunks.append((chunk, pdf_path.name))

    if not all_current_chunks:
        logger.warning("Ningún artículo válido tras procesar los PDF.")
        return 0

    logger.info(f"Generando embeddings para {len(all_current_chunks)} artículos...")
    embeddings = embed_fn([chunk.contenido for chunk, _ in all_current_chunks])

    records = [
        {
            "numero_articulo": chunk.numero_articulo,
            "titulo": chunk.titulo,
            "contenido": chunk.contenido,
            "expedient": chunk.expedient,
            "versio": chunk.versio.value,
            "zona_pgm": ARTICLE_TO_ZONA_PGM.get(chunk.numero_articulo),
            "documento_origen": source_filename,
            "embedding": embedding,
        }
        for (chunk, source_filename), embedding in zip(all_current_chunks, embeddings)
    ]

    stmt = pg_insert(LegalChunk).values(records)
    update_columns = {
        col: getattr(stmt.excluded, col)
        for col in ("titulo", "contenido", "expedient", "versio", "zona_pgm", "documento_origen", "embedding")
    }
    stmt = stmt.on_conflict_do_update(index_elements=["numero_articulo"], set_=update_columns)
    session.execute(stmt)

    logger.info(f"legal_chunks: {len(records)} artículos upsert-eados.")
    return len(records)


def run(pdf_dir: Path, engine=None, embed_fn: EmbeddingFunction = embed_texts) -> int:
    load_dotenv()

    if engine is None:
        engine = create_engine(resolve_database_url(), future=True)

    with Session(engine) as session:
        count = load_corpus_from_directory(session, pdf_dir, embed_fn=embed_fn)
        session.commit()

    logger.info("Carga del corpus legal completada.")
    return count


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m database.load_legal_corpus <directorio con los PDF>")
        sys.exit(1)
    run(Path(sys.argv[1]))
