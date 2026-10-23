"""
==============================================================================
RAG EVALS: DRAFT CANDIDATE QUESTIONS FROM THE CORPUS
==============================================================================
File: evals/draft_questions.py

    python -m evals.draft_questions --n 90 --seed 7

Samples articles from the evaluation database (every law gets a share, Catalan texts are always
included) and asks a strong model to write ONE realistic question per article plus the atomic
facts that a correct answer must contain. The output is a DRAFT: gold labels are only trustworthy
after a person has read the article and the question, which is why the draft goes to
evals/results/drafts/ and never straight into evals/questions/.

The question must not name the law or the article number, otherwise retrieval would be trivial.
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import LegalChunk
from backend.rag.bedrock_adapter import get_llm_adapter
from backend.rag.query_engine import DEFAULT_MODEL
from evals.cache import CACHE_DIR, RESULTS_DIR, CachedLLM, DiskCache
from evals.corpus import get_engine
from evals.metrics import detect_chunk_lang, extract_json

DRAFT_MODEL = DEFAULT_MODEL  # the production generation model (Nova)
# Articles shorter than this make no useful question; longer ones are too big to read for a draft.
ARTICLE_CHARS = (350, 6000)

PROMPT = """Eres quien prepara un examen para un asistente jurídico sobre normativa de hostelería y comercio en Barcelona.
Te doy UN artículo. Escribe UNA pregunta realista que haría una persona que quiere abrir o gestionar un negocio
(bar, restaurante, tienda) y que se pueda responder COMPLETAMENTE con el texto de este artículo.

Reglas:
- La pregunta debe entenderse sola. NO menciones el número de artículo ni el nombre exacto de la ley o decreto.
- Idioma de la pregunta: {lang_name}.
- Nada de preguntas de sí/no triviales ni que dependan de otros artículos. Si el artículo es solo una
  definición vacía, una derogación, una disposición final o no sirve para una pregunta útil, marca usable=false.
- "facts": entre 1 y 4 hechos atómicos y verificables que una respuesta correcta debe contener, copiados o
  resumidos fielmente del artículo (cifras, plazos, obligaciones, excepciones). Escríbelos en español.

Responde SOLO con JSON: {{"usable": true|false, "question": "...", "facts": ["...", "..."]}}

LEY: {fuente}
ARTÍCULO {numero}: {titulo}
TEXTO:
{contenido}"""


def sample_articles(session: Session, n: int, seed: int) -> list[LegalChunk]:
    rows = session.query(LegalChunk).filter(func.length(LegalChunk.contenido).between(*ARTICLE_CHARS)).all()
    rng = random.Random(seed)
    by_source: dict[str, list[LegalChunk]] = defaultdict(list)
    for r in rows:
        by_source[r.fuente_legal].append(r)
    chosen: list[LegalChunk] = []
    # Every PGM article and every Catalan text first: they are few, and they are the point of the experiment.
    for source, chunks in by_source.items():
        catalan = [c for c in chunks if detect_chunk_lang(c.contenido) == "ca"]
        if source.startswith("PGM") or catalan:
            chosen.extend(catalan or chunks)
    remaining = [c for c in rows if c not in chosen]
    rng.shuffle(remaining)
    # Spread the rest across laws in proportion to the square root of their size, so big codes do not drown small ones.
    weights = {s: len(c) ** 0.5 for s, c in by_source.items()}
    total = sum(weights.values())
    quota = {s: max(2, round((n - len(chosen)) * w / total)) for s, w in weights.items()}
    for c in remaining:
        if quota.get(c.fuente_legal, 0) > 0:
            chosen.append(c)
            quota[c.fuente_legal] -= 1
    return chosen[:n]


def draft_one(llm: CachedLLM, chunk: LegalChunk, lang: str) -> dict | None:
    prompt = PROMPT.format(
        lang_name="catalán" if lang == "ca" else "castellano",
        fuente=chunk.fuente_legal,
        numero=chunk.numero_articulo,
        titulo=chunk.titulo,
        contenido=chunk.contenido[:4500],
    )
    reply = llm.messages.create(
        model=DRAFT_MODEL, max_tokens=1500, system="", messages=[{"role": "user", "content": prompt}]
    )
    data = extract_json(reply.content[0].text)
    if not data.get("usable") or not data.get("question"):
        return None
    return {
        "question": data["question"].strip(),
        "lang": lang,
        "answerable": True,
        "gold": [{"fuente_legal": chunk.fuente_legal, "numero_articulo": chunk.numero_articulo}],
        "facts": [f.strip() for f in data.get("facts", [])][:4],
        "zona_pgm": chunk.zona_pgm,
        "doc_lang": detect_chunk_lang(chunk.contenido),
        "source_text": chunk.contenido[:1200],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=90, help="articles to draft from")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--catalan-share", type=float, default=0.12, help="share of questions written in Catalan")
    args = parser.parse_args(argv)

    engine = get_engine()
    with Session(engine) as session:
        chunks = sample_articles(session, args.n, args.seed)
        session.expunge_all()
    rng = random.Random(args.seed)
    jobs = [(c, "ca" if rng.random() < args.catalan_share else "es") for c in chunks]

    llm = CachedLLM(get_llm_adapter(), DiskCache("llm_draft", CACHE_DIR), temperature=0.0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        drafts = list(pool.map(lambda job: draft_one(llm, *job), jobs))
    drafts = [d for d in drafts if d]

    out_dir = RESULTS_DIR / "drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"draft_seed{args.seed}.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for i, d in enumerate(drafts, start=1):
            fh.write(json.dumps({"id": f"draft{i:03d}", **d}, ensure_ascii=False) + "\n")
    print(f"{len(drafts)} usable drafts from {len(chunks)} articles -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
