"""
==============================================================================
RAG EVALS: THE EVALUATION CORPUS AND ITS DATABASE
==============================================================================
File: evals/corpus.py

The evals never touch the development database. They build their own Postgres database
(`geoyield_eval`) with the same Alembic schema as production,
and fill it by calling the SAME chunking and loading code production uses
(database.load_legal_corpus / database.load_general_law). What is measured is therefore what ships.

The manifest below maps each PDF to the `fuente_legal` name used in the database. File names in
data/raw/legal are unreliable (e.g. "BOE-A-2009-12856 - Ley 71996..." is really Ley 11/2009), so the
mapping was made from the CONTENT of each PDF.

Only one thing differs from production: texts longer than MAX_EMBED_CHARS are cut before embedding,
because Titan v2 rejects inputs over 8192 tokens. Production has no such guard (see `truncated` in the
corpus report). The stored article text is never cut.
"""

import os
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.db.connection import resolve_database_url
from backend.db.models import LegalChunk
from database.load_general_law import load_general_law
from database.load_legal_corpus import load_corpus_from_directory
from evals.metrics import detect_chunk_lang

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGAL_DIR = REPO_ROOT / "data" / "raw" / "legal"

# Titan Text Embeddings v2 accepts up to 8192 tokens; Spanish legal text is ~3.5 characters per token.
MAX_EMBED_CHARS = 24_000


@dataclass(frozen=True)
class CorpusDoc:
    file: str
    fuente_legal: str
    kind: str  # "pgm" | "general"
    in_eval: bool = True
    note: str = ""


PGM_FILES = ("Article 302.pdf", "Article 303.pdf", "Article 311.pdf")

MANIFEST: tuple[CorpusDoc, ...] = (
    *(CorpusDoc(f, "PGM (Secció V)", "pgm", note="Catalan, AMB consolidated text") for f in PGM_FILES),
    CorpusDoc(
        "352884_03_es - Decreto 322005, sobre la señalización de las limitaciones en la venta de bebidas alcohólicas..pdf",
        "Decreto 322005, sobre la señalización de las limitaciones en la venta de bebidas alcohólicas.",
        "general",
        note="file name says _es but the text is Catalan",
    ),
    CorpusDoc(
        "540841_02_es - Decreto 1122010, de 31 de agosto, por el que se aprueba el Reglamento de espectáculos públicos y actividades recreativas.pdf",
        "Decreto 1122010, de 31 de agosto, por el que se aprueba el Reglamento de espectáculos públicos y actividades recreativas",
        "general",
        note="scanned PDF without a text layer: 0 chunks, needs OCR",
    ),
    CorpusDoc(
        "629662_03_es - Decreto 1212013, sobre las hojas oficiales de queja, reclamación y denuncia en las relaciones de consumo.pdf",
        "Decreto 1212013, sobre las hojas oficiales de queja, reclamación y denuncia en las relaciones de consumo",
        "general",
        note="file name says _es but the text is Catalan",
    ),
    CorpusDoc(
        "1214729 - horarios de los establecimientos abiertos al público, de los espectáculos públicos y de las actividades recreativas sometidos a la Ley 112009.pdf",
        "horarios de los establecimientos abiertos al público, de los espectáculos públicos y de las actividades recreativas sometidos a la Ley 112009",
        "general",
    ),
    CorpusDoc(
        "BOE-A-1996-1072 - Ley 182017, de 1 de agosto, de comercio, servicios y ferias..pdf",
        "Ley 71996, de 15 de enero, de ordenación del comercio minorista",
        "general",
        note="file name says Ley 18/2017 but the content is Ley 7/1996",
    ),
    CorpusDoc(
        "BOE-A-1996-4447- Reglamento General sobre inscripción de empresas y afiliación, altas, bajas y variaciones de datos de trabajadores en la Seguridad Social.pdf",
        "Reglamento General sobre inscripción de empresas y afiliación, altas, bajas y variaciones de datos de trabajadores en la Seguridad Social",
        "general",
    ),
    CorpusDoc("BOE-A-1998-2989 - política lingüística.pdf", "política lingüística", "general"),
    CorpusDoc("BOE-A-2004-21421 - horarios comerciales.pdf", "horarios comerciales", "general"),
    CorpusDoc(
        "BOE-A-2009-12856 - Ley 71996, de 15 de enero, de ordenación del comercio minorista.pdf",
        "Ley 112009, de 6 de julio, de regulación administrativa de los espectáculos públicos y de las actividades recreativas",
        "general",
        note="file name says Ley 7/1996 but the content is Ley 11/2009",
    ),
    CorpusDoc(
        "BOE-A-2009-18731- Ley 172009, de 23 de noviembre, sobre el libre acceso a las actividades de servicios y su ejercicio.pdf",
        "Ley 172009, de 23 de noviembre, sobre el libre acceso a las actividades de servicios y su ejercicio",
        "general",
    ),
    CorpusDoc(
        "BOE-A-2010-13115 - código de consumo de Cataluña..pdf",
        "código de consumo de Cataluña.",
        "general",
        note="Ley 22/2010",
    ),
    CorpusDoc(
        "BOE-A-2010-13115 - Ley 112009, de 6 de julio, de regulación administrativa de los espectáculos públicos y de las actividades recreativas.pdf",
        "",
        "general",
        in_eval=False,
        note="byte-identical duplicate of the Código de consumo (Ley 22/2010) under a wrong name",
    ),
    CorpusDoc(
        "BOE-A-2017-11320 - Ley 222010, de 20 de julio, del Código de Consumo de Cataluña.pdf",
        "",
        "general",
        in_eval=False,
        note="BOE amendment text of the Código de consumo, not a stand-alone law; not loaded by load_all.sh",
    ),
    CorpusDoc(
        "OMAIIAA_Barcelona.pdf",
        "Ordenanza municipal de actividades y de intervención integral de la administración ambiental de Barcelona",
        "general",
        in_eval=False,
        note="Catalan; its load line is commented out in database/load_all.sh and the parser makes 80 000-character chunks",
    ),
)

EVAL_DB = "geoyield_eval"


# ------------------------------------------------------------------------------
# Database
# ------------------------------------------------------------------------------
def _base_url() -> str:
    """The configured DATABASE_URL, with the Docker-only host swapped for the published port when run from the host."""
    load_dotenv(REPO_ROOT / ".env")
    url = make_url(resolve_database_url())
    if url.host == "postgis":
        url = url.set(host="localhost", port=int(os.getenv("POSTGRES_HOST_PORT", "5432")))
    return url.render_as_string(hide_password=False)


def eval_db_url() -> str:
    override = os.getenv("EVAL_DATABASE_URL")
    if override:
        return override
    return make_url(_base_url()).set(database=EVAL_DB).render_as_string(hide_password=False)


def ensure_database(url: str) -> bool:
    """Creates the database if missing and migrates it to head. Returns True when it was created."""
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created = False
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
            created = True
    admin.dispose()
    env = {**os.environ, "DATABASE_URL": url, "DB_HOST_OVERRIDE": "", "DB_PORT_OVERRIDE": ""}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "database/alembic.ini", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    return created


def get_engine() -> Engine:
    return create_engine(eval_db_url(), future=True)


# ------------------------------------------------------------------------------
# Loading
# ------------------------------------------------------------------------------
def truncating(embed_fn: Callable[[list[str]], list[list[float]]], counter: Counter):
    """Cuts over-long inputs before embedding (and counts them), see the module docstring."""

    def embed(texts: list[str]) -> list[list[float]]:
        cut = []
        for t in texts:
            if len(t) > MAX_EMBED_CHARS:
                counter["truncated"] += 1
                t = t[:MAX_EMBED_CHARS]
            cut.append(t)
        return embed_fn(cut)

    return embed


def build_corpus(
    engine: Engine, embed_fn: Callable[[list[str]], list[list[float]]], log=print
) -> tuple[list[dict], int]:
    """
    Loads every in-eval PDF with the production loaders.
    Returns one report row per general-law manifest entry, and how many texts were cut before embedding.
    """
    truncated: Counter = Counter()
    embed = truncating(embed_fn, truncated)
    reports: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        pgm_dir = Path(tmp)
        for name in PGM_FILES:
            (pgm_dir / name).symlink_to(LEGAL_DIR / name)
        with Session(engine) as session:
            n = load_corpus_from_directory(session, pgm_dir, embed_fn=embed)
            session.commit()
        log(f"  PGM (Secció V): {n} chunks")

    for doc in MANIFEST:
        if doc.kind == "pgm":
            continue
        if not doc.in_eval:
            reports.append({**asdict(doc), "chunks": 0, "error": None, "skipped": True})
            continue
        error = None
        n = 0
        try:
            with Session(engine) as session:
                n = load_general_law(session, LEGAL_DIR / doc.file, doc.fuente_legal, embed_fn=embed)
                session.commit()
        except Exception as exc:  # one broken law must not hide the rest of the corpus
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
        log(f"  {doc.fuente_legal[:60]}: {n} chunks" + (f"  ERROR {error}" if error else ""))
        reports.append({**asdict(doc), "chunks": n, "error": error, "skipped": False})
    return reports, truncated["truncated"]


def corpus_report(engine: Engine, manifest_reports: list[dict]) -> dict:
    """What is actually in the database: chunks per source, size, language mix. Saved in every result."""
    with Session(engine) as session:
        rows = session.query(LegalChunk.fuente_legal, LegalChunk.contenido).all()
    notes = {r["fuente_legal"]: r["note"] for r in manifest_reports if r["fuente_legal"]}

    by_source: dict[str, dict] = {}
    lang_chunks: Counter = Counter()
    for fuente, contenido in rows:
        lang = detect_chunk_lang(contenido)
        lang_chunks[lang] += 1
        source = by_source.setdefault(
            fuente,
            {"fuente_legal": fuente, "chunks": 0, "max_chars": 0, "langs": Counter(), "note": notes.get(fuente, "")},
        )
        source["chunks"] += 1
        source["max_chars"] = max(source["max_chars"], len(contenido))
        source["langs"][lang] += 1

    sources = sorted(
        ({**s, "langs": dict(s["langs"]), "lang": s["langs"].most_common(1)[0][0]} for s in by_source.values()),
        key=lambda s: -s["chunks"],
    )
    return {
        "total_chunks": len(rows),
        "sources": sources,
        "empty_sources": [
            {"fuente_legal": r["fuente_legal"], "note": r["note"], "error": r["error"]}
            for r in manifest_reports
            if r["fuente_legal"] and not r["skipped"] and not r["chunks"]
        ],
        "skipped_files": [{"file": r["file"], "note": r["note"]} for r in manifest_reports if r["skipped"]],
        "oversized_chunks": sum(1 for _, contenido in rows if len(contenido) > MAX_EMBED_CHARS),
        "lang_chunks": dict(lang_chunks),
    }
