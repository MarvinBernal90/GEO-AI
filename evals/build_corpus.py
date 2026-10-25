"""
==============================================================================
RAG EVALS: BUILD THE EVALUATION DATABASE
==============================================================================
File: evals/build_corpus.py

    python -m evals.build_corpus            # build or refresh the evaluation database
    python -m evals.build_corpus --rebuild  # empty the table first

Creates (if missing) and migrates the evaluation database, loads every PDF listed in
evals/corpus.py through the production loaders, and writes evals/results/corpus.json
with what ended up inside: chunks per law, language mix, empty laws, oversized chunks.
It is idempotent: loaders upsert, and embeddings come from the disk cache.
"""

import argparse
import json
import sys
from datetime import UTC, datetime

from sqlalchemy import text

from evals.cache import CORPUS_REPORT, RESULTS_DIR
from evals.corpus import build_corpus, corpus_report, ensure_database, eval_db_url, get_engine
from evals.embedders import get_embedder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="delete every chunk first")
    args = parser.parse_args(argv)

    url = eval_db_url()
    created = ensure_database(url)
    print(f"Database {'created' if created else 'ready'}: {url.rsplit('/', 1)[-1]}")
    engine = get_engine()
    if args.rebuild:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE legal_chunks RESTART IDENTITY"))

    embed_fn, model = get_embedder()
    reports, truncated = build_corpus(engine, embed_fn)
    report = corpus_report(engine, reports)
    report.update(
        embedding_model=model,
        built_at=datetime.now(UTC).isoformat(timespec="seconds"),
        truncated_for_embedding=truncated,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CORPUS_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['total_chunks']} chunks in {len(report['sources'])} sources -> {CORPUS_REPORT}")
    for empty in report["empty_sources"]:
        print(f"  WARNING no chunks: {empty['fuente_legal'][:70]} {empty['note'] or empty['error'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
