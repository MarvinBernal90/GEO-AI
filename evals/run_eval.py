"""
==============================================================================
RAG EVALS: RUN ONE CONFIGURATION AGAINST A QUESTION SET
==============================================================================
File: evals/run_eval.py

    python -m evals.run_eval --set dev                       # retrieval only, cheap
    python -m evals.run_eval --set dev --answers             # + generation and judge
    python -m evals.run_eval --set dev --rewrite ca --name rewrite-ca
    python -m evals.run_eval --set holdout --answers         # once per decision, logged

What it does
  1. Retrieval: for each question, runs the production retrieval (backend.rag.query_engine) against the
     evaluation database and scores where the gold article lands (hit@k, MRR, nDCG).
  2. Optional query rewrite to Catalan (--rewrite ca) and Amazon reranking (--rerank), to test them.
  3. With --answers: generates the answer with the production prompt and model, then a judge from a
     second call to the same production model (Nova) checks facts, unsupported claims and abstention.
  4. Writes evals/results/runs/<run_id>.json, which the API serves to the dashboard (/evals).

Everything that costs money (embeddings, model replies) goes through the disk cache in evals/results/cache,
so repeating a run is free and gives identical numbers. Answers use temperature 0 so runs can be compared;
note that production generates at 0.7.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.db.models import LegalChunk
from backend.rag.bedrock_adapter import get_llm_adapter
from backend.rag.query_engine import (
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    build_context,
    retrieve_relevant_chunks,
    retrieve_relevant_chunks_with_rerank,
)
from evals import metrics as M
from evals.cache import CACHE_DIR, CORPUS_REPORT, RESULTS_DIR, CachedLLM, DiskCache
from evals.corpus import get_engine
from evals.embedders import get_embedder

QUESTIONS_DIR = Path(__file__).resolve().parent / "questions"
RUNS_DIR = RESULTS_DIR / "runs"

# The judge is the production generation model too: the project stays on the models it ships with.
# It is therefore grading its own family of answers, which can make scores a little lenient.
JUDGE_MODEL = DEFAULT_MODEL

RANK_DEPTH = 10  # how many results are ranked and scored per question
RERANK_POOL = 20  # candidates sent to the reranker, which keeps the best RANK_DEPTH
ANSWER_TEMPERATURE = 0.0  # production generates at 0.7; 0 makes two runs comparable
ANSWER_MAX_TOKENS = 1500
JUDGE_MAX_TOKENS = 1500
JUDGE_CONTEXT_CHARS = 9000
TOP_SHOWN = 6  # retrieved articles kept per question for the dashboard
UNSUPPORTED_SHOWN = 5
CORPUS_KEYS = (
    "total_chunks",
    "lang_chunks",
    "empty_sources",
    "oversized_chunks",
    "truncated_for_embedding",
    "sources",
    "skipped_files",
)

REWRITE_SYSTEM = (
    "Reescribe la pregunta del usuario como una consulta breve en catalán jurídico-administrativo, como si "
    "buscaras el artículo en una norma catalana. Conserva los términos clave. Responde SOLO con la consulta."
)

JUDGE_PROMPT = """Eres un evaluador estricto de un asistente jurídico (RAG). Recibes la pregunta, el CONTEXTO que se dio al asistente,
los HECHOS que una respuesta correcta debe contener y la RESPUESTA del asistente.

Devuelve SOLO JSON con esta forma exacta:
{{"abstains": true|false, "facts_present": [true|false, ...], "unsupported": ["afirmación", ...]}}

- "abstains": true si la CONCLUSIÓN principal de la respuesta es que el contexto no contiene la información pedida
  ("no establece", "no aborda", "no incluye", "no está disponible"), aunque además describa de qué trata el contexto,
  mencione artículos relacionados o añada comentarios generales. false solo si la respuesta afirma una solución concreta a
  la pregunta (cifras, plazos, obligaciones, requisitos) como si estuviera respaldada por el contexto.
- "facts_present": una entrada por cada HECHO, en el mismo orden. true solo si la respuesta lo contiene (en cualquier idioma o
  con otras palabras). Si no hay hechos, devuelve [].
- "unsupported": afirmaciones concretas de la respuesta (cifras, plazos, importes, obligaciones, normas, nombres de leyes) que NO
  aparecen en el CONTEXTO o lo contradicen. NO cuentan: paráfrasis o traducciones de lo que dice el contexto, resúmenes
  y consecuencias evidentes de ello, recomendaciones genéricas de confirmar con el ayuntamiento, ni la introducción o el cierre
  de la respuesta. Ante la duda, no lo marques. Lista solo lo claramente ausente.

PREGUNTA: {question}

CONTEXTO:
{context}

HECHOS:
{facts}

RESPUESTA:
{answer}"""


@dataclass
class Config:
    name: str
    rewrite: str = "none"  # "none" | "ca"
    rerank: bool = False
    answers: bool = False
    answer_k: int = 3


@dataclass
class LLMs:
    """The three cached model clients of a run. `judge` only exists when answers are evaluated."""

    gen: CachedLLM
    rewriter: CachedLLM
    judge: CachedLLM | None

    @property
    def calls(self) -> int:
        """Real (non-cached) model calls made so far."""
        return self.gen.calls + self.rewriter.calls + (self.judge.calls if self.judge else 0)


def build_llms(cfg: Config) -> LLMs:
    adapter = get_llm_adapter()

    def cached(name: str, temperature: float) -> CachedLLM:
        return CachedLLM(adapter, DiskCache(name, CACHE_DIR), temperature=temperature)

    return LLMs(
        gen=cached("llm_gen", ANSWER_TEMPERATURE),
        rewriter=cached("llm_rewrite", 0.0),
        judge=cached("llm_judge", 0.0) if cfg.answers else None,
    )


def load_questions(which: str) -> list[dict]:
    names = ["dev", "holdout"] if which == "all" else [which]
    lines = (
        line
        for name in names
        for line in (QUESTIONS_DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return [json.loads(line) for line in lines]


def _key(chunk) -> M.Key:
    return (chunk.fuente_legal, chunk.numero_articulo)


# ------------------------------------------------------------------------------
# Retrieval
# ------------------------------------------------------------------------------
def retrieve(session: Session, cfg: Config, q: dict, embed_fn, rewriter: CachedLLM):
    """Runs the production retrieval for one question. Returns (query used, ranked chunks, seconds)."""
    query = q["question"]
    if cfg.rewrite == "ca" and q["lang"] != "ca":
        reply = rewriter.messages.create(
            model=DEFAULT_MODEL, max_tokens=200, system=REWRITE_SYSTEM, messages=[{"role": "user", "content": query}]
        )
        query = reply.content[0].text.strip().strip('"')
    start = time.perf_counter()
    if cfg.rerank:
        chunks = retrieve_relevant_chunks_with_rerank(
            session, query, embed_fn=embed_fn, top_k=RERANK_POOL, zona_pgm=q.get("zona_pgm"), final_top_k=RANK_DEPTH
        )
    else:
        chunks = retrieve_relevant_chunks(
            session, query, embed_fn=embed_fn, top_k=RANK_DEPTH, zona_pgm=q.get("zona_pgm")
        )
    return query, chunks[:RANK_DEPTH], time.perf_counter() - start


def retrieval_row(q: dict, gold: list[M.Key], gold_lang: str | None, query: str, chunks: list, seconds: float) -> dict:
    """One question's retrieval outcome. Keys stay tuples here; json turns them into lists when saved."""
    ranked = [_key(c) for c in chunks]
    return {
        "id": q["id"],
        "question": q["question"],
        "lang": q["lang"],
        "kind": q["kind"],
        "answerable": q["answerable"],
        "zona_pgm": q.get("zona_pgm"),
        "doc_lang": gold_lang,
        "direction": f"{q['lang']}→{gold_lang}" if gold else None,
        "gold": gold,
        "ranked": ranked,
        "query_used": query if query != q["question"] else None,
        "rank_of_gold": M.first_hit_rank(ranked, gold) if gold else None,
        "best_distance": chunks[0].distancia if chunks else None,
        "top": [
            {
                "fuente_legal": c.fuente_legal,
                "numero_articulo": c.numero_articulo,
                "titulo": c.titulo[:90],
                "distance": round(float(c.distancia), 4),
                "is_gold": _key(c) in gold,
            }
            for c in chunks[:TOP_SHOWN]
        ],
        "retrieval_seconds": seconds,
        "facts": q.get("facts") or [],
    }


def retrieve_all(session: Session, cfg: Config, questions: list[dict], embed_fn, rewriter: CachedLLM):
    """Retrieval for every question. Returns the result rows and, per question id, the chunks the model would see."""
    article_text = {
        (fuente, numero): contenido
        for fuente, numero, contenido in session.query(
            LegalChunk.fuente_legal, LegalChunk.numero_articulo, LegalChunk.contenido
        )
    }
    rows, retrieved = [], {}
    for q in questions:
        gold = [(g["fuente_legal"], g["numero_articulo"]) for g in q.get("gold", [])]
        missing = [g for g in gold if g not in article_text]
        if missing:
            raise SystemExit(
                f"{q['id']}: gold article not in the database: {missing}. Rebuild the corpus or fix the question."
            )
        query, chunks, seconds = retrieve(session, cfg, q, embed_fn, rewriter)
        retrieved[q["id"]] = chunks
        gold_lang = M.detect_chunk_lang(article_text[gold[0]]) if gold else None
        rows.append(retrieval_row(q, gold, gold_lang, query, chunks, seconds))
    return rows, retrieved


# ------------------------------------------------------------------------------
# Answers and judging
# ------------------------------------------------------------------------------
def answer_question(q: dict, used: list, gen: CachedLLM):
    context = build_context(used)
    reply = gen.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=ANSWER_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"CONTEXT NORMATIU:\n{context}\n\nPREGUNTA: {q['question']}"}],
    )
    return context, reply.content[0].text.strip(), reply.seconds


def judge_answer(judge: CachedLLM, q: dict, context: str, answer: str) -> dict:
    """The judge's verdict, or a loud failure: an unreadable verdict would silently score as 'no facts found'."""
    facts = q.get("facts") or []
    prompt = JUDGE_PROMPT.format(
        question=q["question"],
        context=context[:JUDGE_CONTEXT_CHARS],
        facts="\n".join(f"{i + 1}. {f}" for i, f in enumerate(facts)) or "(ninguno)",
        answer=answer,
    )
    reply = judge.messages.create(
        model=JUDGE_MODEL, max_tokens=JUDGE_MAX_TOKENS, system="", messages=[{"role": "user", "content": prompt}]
    )
    verdict = M.extract_json(reply.content[0].text)
    if "facts_present" not in verdict or "abstains" not in verdict:
        raise SystemExit(f"{q['id']}: the judge did not return the expected JSON. Re-run, or adjust JUDGE_PROMPT.")
    # Exactly one flag per fact, whatever the judge returned.
    present = [bool(p) for p in ((verdict["facts_present"] or []) + [False] * len(facts))[: len(facts)]]
    return {
        "abstained": bool(verdict["abstains"]),
        "judge": {
            "fact_recall": sum(present) / len(facts) if facts else None,
            "facts_present": present,
            "unsupported": [str(u) for u in (verdict.get("unsupported") or [])][:UNSUPPORTED_SHOWN],
        },
    }


def answer_and_judge(cfg: Config, q: dict, chunks: list, llms: LLMs) -> dict:
    used = chunks[: cfg.answer_k]
    context, answer, seconds = answer_question(q, used, llms.gen)
    return {
        "answer": answer,
        "gen_seconds": seconds,
        **judge_answer(llms.judge, q, context, answer),
        "citations": M.citation_validity(M.extract_cited_articles(answer), [c.numero_articulo for c in used], context),
        "answer_lang": M.detect_lang(answer),
        "context_articles": [f"{c.fuente_legal[:40]} · art. {c.numero_articulo}" for c in used],
    }


def attach_answers(rows: list[dict], questions: list[dict], retrieved: dict, cfg: Config, llms: LLMs, max_calls: int):
    by_id = {q["id"]: q for q in questions}

    def work(row: dict) -> dict:
        if llms.calls > max_calls:
            raise SystemExit(f"Stopped: more than {max_calls} real model calls (--max-calls).")
        return answer_and_judge(cfg, by_id[row["id"]], retrieved[row["id"]], llms)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for row, extra in zip(rows, pool.map(work, rows), strict=True):
            row.update(extra)


# ------------------------------------------------------------------------------
# Aggregation
# ------------------------------------------------------------------------------
def summarize_answers(rows: list[dict]) -> dict:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    answered = [r for r in answerable if not r["abstained"]]
    recalls = [r["judge"]["fact_recall"] for r in answerable if r["judge"]["fact_recall"] is not None]
    cited = [r for r in rows if r["citations"]["cited"]]
    lang_rows = [r for r in rows if r["lang"] in ("es", "ca") and r["answer_lang"] != "unknown"]
    seconds = [r["gen_seconds"] for r in rows]
    return {
        "fact_recall": M.mean_with_ci(recalls),
        "faithfulness": M.rate(sum(1 for r in answered if not r["judge"]["unsupported"]), len(answered)),
        "over_abstention": M.rate(sum(1 for r in answerable if r["abstained"]), len(answerable)),
        "correct_abstention": M.rate(sum(1 for r in unanswerable if r["abstained"]), len(unanswerable)),
        "citation_validity": M.rate(sum(1 for r in cited if not r["citations"]["invalid"]), len(cited)),
        "answer_language": M.rate(sum(1 for r in lang_rows if r["answer_lang"] == r["lang"]), len(lang_rows)),
        "latency_p50_s": M.percentile(seconds, 0.5),
        "latency_p95_s": M.percentile(seconds, 0.95),
    }


def abstention_signal(rows: list[dict]) -> dict | None:
    """Can the best retrieval distance alone tell answerable questions from unanswerable ones?"""
    closeness = {
        answerable: [
            1 - r["best_distance"] for r in rows if r["answerable"] is answerable and r["best_distance"] is not None
        ]
        for answerable in (True, False)
    }
    auc = M.auroc(closeness[True], closeness[False])
    if auc is None:
        return None
    return {
        "auroc": auc,
        "answerable_median_distance": M.percentile([1 - c for c in closeness[True]], 0.5),
        "unanswerable_median_distance": M.percentile([1 - c for c in closeness[False]], 0.5),
        "n_answerable": len(closeness[True]),
        "n_unanswerable": len(closeness[False]),
    }


def corpus_summary() -> dict | None:
    if not CORPUS_REPORT.exists():
        return None
    corpus = json.loads(CORPUS_REPORT.read_text(encoding="utf-8"))
    return {k: corpus[k] for k in CORPUS_KEYS if k in corpus}


def build_result(cfg: Config, which: str, questions: list[dict], rows: list[dict], embed_model: str) -> dict:
    answerable = [r for r in rows if r["answerable"]]
    now = datetime.now(UTC)
    return {
        "run_id": f"{now:%Y%m%d-%H%M%S}-{cfg.name}-{which}",
        "created_at": now.isoformat(timespec="seconds"),
        "name": cfg.name,
        "set": which,
        "set_hash": M.set_hash(questions),
        "config": {
            **asdict(cfg),
            "rank_depth": RANK_DEPTH,
            "answer_temperature": ANSWER_TEMPERATURE,
            "embedding_model": embed_model,
            "generation_model": DEFAULT_MODEL.split("/")[-1],
            "judge_model": JUDGE_MODEL if cfg.answers else None,
        },
        "n_questions": len(rows),
        "n_answerable": len(answerable),
        "n_unanswerable": len(rows) - len(answerable),
        "retrieval": M.summarize_retrieval(answerable),
        "slices": {field: M.slice_retrieval(answerable, field) for field in ("direction", "doc_lang", "lang", "kind")},
        "abstention_signal": abstention_signal(rows),
        "answers": summarize_answers(rows) if cfg.answers else None,
        "failures": M.count_failures(rows),
        "corpus": corpus_summary(),
        "questions": rows,
    }


# ------------------------------------------------------------------------------
# Running and saving
# ------------------------------------------------------------------------------
def run(cfg: Config, which: str, max_calls: int, log=print) -> dict:
    questions = load_questions(which)
    embed_fn, embed_model = get_embedder()
    llms = build_llms(cfg)

    with Session(get_engine()) as session:
        rows, retrieved = retrieve_all(session, cfg, questions, embed_fn, llms.rewriter)
    log(f"  retrieval done ({len(rows)} questions)")

    if cfg.answers:
        attach_answers(rows, questions, retrieved, cfg, llms, max_calls)
        log(f"  answers done ({llms.gen.calls} new generations, {llms.judge.calls} new judgements)")

    for row in rows:
        row["failure"] = M.classify_failure(row)
    return build_result(cfg, which, questions, rows, embed_model)


def _append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def save(result: dict) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{result['run_id']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {
        **{k: result[k] for k in ("run_id", "created_at", "name", "set", "set_hash")},
        **{k: result["retrieval"][k]["value"] for k in ("hit@1", "hit@3", "hit@6", "mrr")},
    }
    _append_jsonl(RESULTS_DIR / "metrics_history.jsonl", summary)
    if result["set"] != "dev":
        _append_jsonl(RESULTS_DIR / "holdout_log.jsonl", summary)
    return path


def default_name(rewrite: str, rerank: bool) -> str:
    parts = [
        "baseline" if rewrite == "none" and not rerank else None,
        f"rewrite-{rewrite}" if rewrite != "none" else None,
        "rerank" if rerank else None,
    ]
    return "-".join(p for p in parts if p)


def print_summary(result: dict, path: Path) -> None:
    r = result["retrieval"]
    print(
        f"  hit@1 {r['hit@1']['value']:.2f}  hit@3 {r['hit@3']['value']:.2f}  hit@6 {r['hit@6']['value']:.2f}  "
        f"MRR {r['mrr']['value']:.2f}  nDCG@10 {r['ndcg@10']['value']:.2f}  (n={result['n_answerable']})"
    )
    for field, groups in result["slices"].items():
        print(
            f"  by {field}: "
            + "  ".join(f"{k} hit@3 {v['hit@3']['value']:.2f} (n={v['hit@3']['n']})" for k, v in groups.items())
        )
    if a := result["answers"]:
        print(
            f"  fact recall {a['fact_recall']['value']:.2f}  faithfulness {a['faithfulness']['value']:.2f}  "
            f"over-abstention {a['over_abstention']['value']:.2f}  "
            f"correct abstention {a['correct_abstention']['value']}"
        )
    print(f"  failures: {result['failures']}\n  saved {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", dest="which", choices=["dev", "holdout", "all"], default="dev")
    parser.add_argument("--name", default=None, help="label shown in the dashboard (default: built from the options)")
    parser.add_argument(
        "--rewrite",
        choices=["none", "ca"],
        default="none",
        help="rewrite Spanish questions to Catalan before searching",
    )
    parser.add_argument("--rerank", action="store_true", help=f"Amazon Rerank over the top {RERANK_POOL} candidates")
    parser.add_argument("--answers", action="store_true", help="also generate and judge answers")
    parser.add_argument(
        "--answer-k", type=int, default=3, help="chunks given to the model (production report path uses 3)"
    )
    parser.add_argument(
        "--max-calls", type=int, default=400, help="abort after this many real (non-cached) model calls"
    )
    args = parser.parse_args(argv)

    cfg = Config(
        name=args.name or default_name(args.rewrite, args.rerank),
        rewrite=args.rewrite,
        rerank=args.rerank,
        answers=args.answers,
        answer_k=args.answer_k,
    )
    print(f"Run '{cfg.name}' on {args.which}")
    result = run(cfg, args.which, args.max_calls)
    print_summary(result, save(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
