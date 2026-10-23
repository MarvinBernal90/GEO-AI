# RAG evaluation

How good is the legal assistant, measured with questions whose correct answer is known.
Results are shown in the app at **`/metrics`**, tab **Calidad RAG** (`/metrics?tab=rag`; the old `/evals` address redirects there).

## What is measured

| Question | Metric |
|---|---|
| Does retrieval find the right article? | hit@1/3/6, MRR, nDCG@10, right-law hit, with 95 % intervals |
| Does the answer contain the key facts? | fact recall (judge) |
| Does it invent things? | faithfulness (judge) and citation check (cited article was in the context, or is a cross-reference the context itself names) |
| Does it stay quiet when the corpus does not cover the question? | correct abstention, plus whether retrieval distance alone separates covered from uncovered questions (AUROC) |
| Does it answer in the user's language? | answer language |
| Does Catalan matter? | every number is sliced by question language → article language |

Every model call, including the judge, uses the models the project already ships with (Nova for answers and judging).
The judge therefore grades its own family of answers, which can make scores a little lenient: treat the absolute
answer-quality numbers as optimistic and use them mainly to compare configurations.

## Run it

```bash
# once: build the evaluation database (never touches the dev database) from data/raw/legal/*.pdf
python -m evals.build_corpus

# every time
python -m evals.run_eval --set dev                              # retrieval only
python -m evals.run_eval --set dev --answers                    # + answers and judge
python -m evals.run_eval --set dev --rerank                     # Amazon Rerank over the top 20
python -m evals.run_eval --set holdout --answers                # confirm a decision, see below
```

Needs the repo `.env` (DB and AWS settings), and `DB_HOST_OVERRIDE=localhost DB_PORT_OVERRIDE=<POSTGRES_HOST_PORT>`
if you do not run from inside Docker. Embeddings and model replies are cached in `evals/results/cache/`
(gitignored), so a repeated run is free and gives identical numbers.

Results land in `evals/results/runs/*.json` (committed: they are the evidence behind the dashboard).
To serve them from a deployed API, mount that folder and set `EVALS_RESULTS_DIR`.

## The question sets (`evals/questions/*.jsonl`)

- `dev` (61: 54 answerable, 7 not) is for tuning. `holdout` (28: 25 answerable, 3 not) is for confirming.
- **Use holdout once per decision.** Every non-dev run is appended to `results/holdout_log.jsonl`.
  If you change something because of a holdout failure, that question has leaked: write new ones.
- Each line: `question`, `lang`, `gold` (`fuente_legal` + `numero_articulo`), `facts` the answer must contain,
  optional `zona_pgm` (the app passes it when the location is known), `kind`, `answerable`.
- 72 were drafted by Nova from real articles (`python -m evals.draft_questions`) with the instruction not to name
  the law or the article, then filtered by hand; 7 PGM and 10 unanswerable ones were written by hand.
  **The gold labels were reviewed by an AI assistant, not yet by a lawyer or a domain owner.** Have someone read the
  `facts` against the articles before relying on small differences.
- A gold label names one article, but a topic can be answered by several (e.g. Decreto 121/2013 and the Código de
  consumo both cover complaint sheets). Some "misses" are legitimate alternatives; the per-question view shows what was retrieved.

## Reading the results honestly

- With ~50 questions, differences of a few points are inside the interval. Prefer changes that are large and that hold on holdout.
- `set_hash` fingerprints the questions; only compare runs with the same hash.
- Answers are generated at temperature 0 for comparability. Production uses 0.7.

## Files

`corpus.py` manifest of PDFs → law names and the evaluation database · `embedders.py` the production embedding model, cached ·
`metrics.py` pure functions (tests: `tests/unit_tests/test_eval_metrics.py`) · `run_eval.py` the runner ·
`draft_questions.py` question drafting · `cache.py` disk cache.
