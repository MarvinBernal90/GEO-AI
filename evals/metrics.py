"""
==============================================================================
RAG EVALS: METRICS (PURE FUNCTIONS, NO I/O)
==============================================================================
File: evals/metrics.py

Everything here takes plain Python values and returns plain values, so it can be unit
tested with hand-computed cases (tests/unit_tests/test_eval_metrics.py).

A "key" identifies one chunk: (fuente_legal, numero_articulo). A question is "answerable"
when the corpus contains the article that answers it; unanswerable questions have no gold
and the right behaviour is to abstain.

Intervals: proportions use the Wilson score interval, means use a seeded bootstrap. With
only a few dozen questions the intervals are wide on purpose: they tell you how much a
difference between two runs is worth.
"""

import hashlib
import json
import math
import random
import re
from collections import Counter
from collections.abc import Iterable, Sequence

Key = tuple[str, str]

RETRIEVAL_KS = (1, 3, 6, 10)


# ------------------------------------------------------------------------------
# Ranking metrics (one question)
# ------------------------------------------------------------------------------
def first_hit_rank(ranked: Sequence[Key], gold: Iterable[Key]) -> int | None:
    """1-based position of the first gold chunk in the ranking, or None if it is missing."""
    gold_set = set(gold)
    for position, key in enumerate(ranked, start=1):
        if key in gold_set:
            return position
    return None


def hit_at_k(ranked: Sequence[Key], gold: Iterable[Key], k: int) -> bool:
    rank = first_hit_rank(ranked, gold)
    return rank is not None and rank <= k


def reciprocal_rank(ranked: Sequence[Key], gold: Iterable[Key]) -> float:
    rank = first_hit_rank(ranked, gold)
    return 0.0 if rank is None else 1.0 / rank


def recall_at_k(ranked: Sequence[Key], gold: Iterable[Key], k: int) -> float:
    """Share of the gold chunks that appear in the top k (matters for multi-article questions)."""
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    return len(gold_set & set(ranked[:k])) / len(gold_set)


def ndcg_at_k(ranked: Sequence[Key], gold: Iterable[Key], k: int) -> float:
    """Binary-relevance nDCG: 1.0 when every gold chunk is ranked before every other chunk."""
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    dcg = sum(1.0 / math.log2(i + 1) for i, key in enumerate(ranked[:k], start=1) if key in gold_set)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold_set), k) + 1))
    return dcg / ideal


def doc_hit_at_k(ranked: Sequence[Key], gold: Iterable[Key], k: int) -> bool:
    """Right law, maybe wrong article. Separates 'found the document' from 'found the article'."""
    gold_docs = {fuente for fuente, _ in gold}
    return any(fuente in gold_docs for fuente, _ in ranked[:k])


# ------------------------------------------------------------------------------
# Intervals
# ------------------------------------------------------------------------------
def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion. (0, 0) when there are no observations."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def bootstrap_ci(values: Sequence[float], iterations: int = 2000, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap 95% interval of the mean. Seeded, so the same data gives the same interval."""
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(iterations))
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def rate(successes: int, n: int) -> dict:
    """A proportion with its Wilson interval, in the shape the API and the dashboard use."""
    lo, hi = wilson(successes, n)
    return {"value": (successes / n) if n else None, "lo": lo, "hi": hi, "n": n}


def mean_with_ci(values: Sequence[float]) -> dict:
    lo, hi = bootstrap_ci(values)
    return {"value": (sum(values) / len(values)) if values else None, "lo": lo, "hi": hi, "n": len(values)}


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (q in 0..1)."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def auroc(positives: Sequence[float], negatives: Sequence[float]) -> float | None:
    """
    Probability that a random positive scores HIGHER than a random negative (ties count half).
    Used on 'closeness' (1 - best distance): 1.0 means a distance threshold separates answerable
    from unanswerable questions perfectly, 0.5 means the distance says nothing.
    """
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


# ------------------------------------------------------------------------------
# Question sets
# ------------------------------------------------------------------------------
def set_hash(questions: Iterable[dict]) -> str:
    """
    Fingerprint of a question set. Two runs are comparable only when it matches. Only the fields
    that change what is being measured are hashed, so fixing a typo in a tag does not invalidate history.
    """
    canonical = sorted(
        (
            q["id"],
            q["question"],
            q.get("answerable", True),
            sorted((g["fuente_legal"], g["numero_articulo"]) for g in q.get("gold", [])),
        )
        for q in questions
    )
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def extract_json(text: str) -> dict:
    """
    The JSON object in a model reply, or {} if there is none. Nova may put reasoning in <thinking>
    tags before the answer; those can contain braces, so they are removed first.
    """
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


# ------------------------------------------------------------------------------
# Language and citations (answer side)
# ------------------------------------------------------------------------------
_STOPWORDS = {
    "es": {
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "que",
        "y",
        "en",
        "un",
        "una",
        "por",
        "con",
        "para",
        "es",
        "se",
        "no",
        "según",
        "artículo",
        "su",
        "al",
        "como",
        "más",
        "este",
        "esta",
        "puede",
        "deben",
        "debe",
        "sobre",
    },
    "ca": {
        "el",
        "la",
        "els",
        "les",
        "de",
        "del",
        "que",
        "i",
        "en",
        "un",
        "una",
        "per",
        "amb",
        "és",
        "es",
        "no",
        "segons",
        "article",
        "seu",
        "al",
        "com",
        "més",
        "aquest",
        "aquesta",
        "pot",
        "han",
        "ha",
        "sobre",
        "dels",
        "als",
        "són",
        "això",
    },
    "en": {
        "the",
        "of",
        "and",
        "to",
        "in",
        "is",
        "that",
        "for",
        "with",
        "as",
        "on",
        "by",
        "this",
        "are",
        "be",
        "or",
        "article",
        "according",
        "not",
        "which",
        "may",
        "must",
    },
}
# Words that belong to one language only count double: "el/la/de" are shared by es and ca.
_UNIQUE = {
    lang: words - set().union(*(w for other, w in _STOPWORDS.items() if other != lang))
    for lang, words in _STOPWORDS.items()
}
_WORD = re.compile(r"[a-zA-ZÀ-ÿ·'’]+")


def detect_lang(text: str) -> str:
    """'es', 'ca', 'en' or 'unknown' by stopword counts. Meant for paragraphs, not single words."""
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 4:
        return "unknown"
    scores = {}
    for lang, stop in _STOPWORDS.items():
        scores[lang] = sum(2 if w in _UNIQUE[lang] else 1 for w in words if w in stop)
    best, runner_up = sorted(scores.values(), reverse=True)[:2]
    if best == 0 or best == runner_up:
        return "unknown"
    return max(scores, key=scores.get)


LANG_SAMPLE_CHARS = 1500


def detect_chunk_lang(text: str) -> str:
    """Language of an article, judged from its opening: long articles can quote other languages further in."""
    return detect_lang(text[:LANG_SAMPLE_CHARS])


_CITATION = re.compile(
    r"\b(?:art[íi]cul(?:os?)?|articles?|arts?\.)\s*(\d+(?:[-.]\d+)*(?:\s*(?:bis|ter|quater))?)", re.IGNORECASE
)


def _norm_article(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _base_article(value: str) -> str:
    """'7.1' (article 7, paragraph 1) -> '7'. Hyphens stay: '131-1' is a real article number in the Código de consumo."""
    return re.sub(r"(?:\.\d+)+$", "", _norm_article(value))


def extract_cited_articles(answer: str) -> set[str]:
    """Article numbers a text names ("según el Artículo 131-1 ..."). Normalised like numero_articulo."""
    return {_base_article(m.group(1)) for m in _CITATION.finditer(answer)}


def citation_validity(cited: set[str], retrieved: Iterable[str], context: str = "") -> dict:
    """
    Sorts the articles an answer cites into three groups:
    - valid: the article was in the context the model was given
    - cross_reference: not retrieved, but the context itself names it ("de acuerdo con el artículo 71 del Reglamento"),
      so the model is relaying a real reference, not inventing one
    - invalid: neither, which is where a hallucinated citation shows up
    """
    available = {_norm_article(a) for a in retrieved}
    in_context = extract_cited_articles(context)
    valid = cited & available
    cross = (cited - available) & in_context
    return {
        "cited": sorted(cited),
        "valid": sorted(valid),
        "cross_reference": sorted(cross),
        "invalid": sorted(cited - valid - cross),
    }


# ------------------------------------------------------------------------------
# Aggregation
# ------------------------------------------------------------------------------
def summarize_retrieval(rows: Sequence[dict], ks: Sequence[int] = RETRIEVAL_KS) -> dict:
    """
    rows: answerable questions only, each with `gold` (list of keys) and `ranked` (list of keys).
    Returns the headline retrieval numbers with intervals.
    """
    out: dict = {}
    n = len(rows)
    for k in ks:
        out[f"hit@{k}"] = rate(sum(hit_at_k(r["ranked"], r["gold"], k) for r in rows), n)
    out["doc_hit@10"] = rate(sum(doc_hit_at_k(r["ranked"], r["gold"], 10) for r in rows), n)
    out["mrr"] = mean_with_ci([reciprocal_rank(r["ranked"], r["gold"]) for r in rows])
    out["ndcg@10"] = mean_with_ci([ndcg_at_k(r["ranked"], r["gold"], 10) for r in rows])
    multi = [r for r in rows if len(set(r["gold"])) > 1]
    out["recall@6_multi"] = mean_with_ci([recall_at_k(r["ranked"], r["gold"], 6) for r in multi])
    return out


def slice_retrieval(rows: Sequence[dict], field: str) -> dict:
    """The same retrieval summary for every value of a row field (doc_lang, lang, kind...)."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(str(r.get(field) or "unknown"), []).append(r)
    return {
        value: {
            k: v for k, v in summarize_retrieval(group, ks=(1, 3, 6)).items() if k in ("hit@1", "hit@3", "hit@6", "mrr")
        }
        for value, group in sorted(groups.items())
    }


def classify_failure(row: dict) -> str | None:
    """
    Why a question went wrong, from the cheapest signal available. None means it did not fail.
    - retrieval_miss: the gold article is not in the top 6 (the model never saw the answer)
    - over_abstention: it was there, but the model declined to answer
    - unsupported: the judge found claims the context does not support, or a cited article that was not retrieved
    - generation_error: it was there and the model answered, but missed the facts
    - wrongly_answered: the question is unanswerable and the model answered anyway
    """
    if not row["answerable"]:
        return "wrongly_answered" if row.get("answer") and row.get("abstained") is False else None
    if not hit_at_k(row["ranked"], row["gold"], 6):
        return "retrieval_miss"
    judge = row.get("judge")
    if judge is None:
        return None
    if row.get("abstained"):
        return "over_abstention"
    if judge.get("unsupported") or (row.get("citations") or {}).get("invalid"):
        return "unsupported"
    if judge.get("fact_recall", 1.0) < 1.0:
        return "generation_error"
    return None


def count_failures(rows: Iterable[dict]) -> dict[str, int]:
    return dict(Counter(f for f in (classify_failure(r) for r in rows) if f))
