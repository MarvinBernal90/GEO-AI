# Measuring RAG quality — metrics and status

**Status:** Implemented in [`evals/`](../evals/README.md); results are shown in the app at `/metrics?tab=rag`. This document explains what the metrics mean and what is still missing.

## What is measured

Quality splits into retrieval (does the system find the right article?) and generation (is the answer correct, grounded and in scope?).

| Metric | Meaning | Where |
| --- | --- | --- |
| **hit@1/3/6, MRR, nDCG@10** | The gold article appears in the top results, and how high | `evals/metrics.py` |
| **Right-law hit** | The correct norm was retrieved even if the exact article was not | `evals/metrics.py` |
| **Fact recall** | The answer contains the key facts (LLM judge) | `evals/run_eval.py --answers` |
| **Faithfulness** | Every claim is supported by the retrieved context (LLM judge) | same |
| **Citation check** | Each cited article was in the context, or is a cross-reference the context names | same |
| **Correct abstention** | For questions the corpus does not cover, the answer says so. AUROC shows whether retrieval distance alone separates covered from uncovered questions | same |
| **Answer language** | The answer matches the user's language (the corpus is largely Catalan) | same |

Every number is sliced by question language → article language, because Catalan sources answering Spanish questions are the hardest case.

## Why the project is hard to score

| Feature | Consequence | How the evals handle it |
| --- | --- | --- |
| Cross-lingual corpus (Catalan law, Spanish questions) | Embeddings and judges must treat equivalent meaning across languages as correct | Slice results by language pair |
| Zone-aware retrieval (`zona_pgm` plus general chunks) | A wrong zone from the geocoder looks like a retrieval error | Questions carry an optional `zona_pgm`, as the app does when it knows the location |
| Two retrieval modes (plain vector search in reports; rerank in the assistant) | The final answer hides which stage failed | `--rerank` compares Amazon Rerank over the top 20 against the baseline |
| "Say so if the context is insufficient" | Answering an unanswerable question is a failure | The question sets include unanswerable items |
| No Markdown allowed in answers | Raw `**` or `#` would show in the UI | Still a candidate for a deterministic check; not implemented |

## Question sets

`evals/questions/dev.jsonl` (61 questions: 54 answerable, 7 not) is for tuning; `holdout.jsonl` (28: 25 answerable, 3 not) confirms a decision, once per decision (each non-dev run is logged in `holdout_log.jsonl`). Most were drafted by Nova from real articles with the law and article hidden, then filtered by hand. The gold labels were reviewed by an AI assistant, **not yet by a lawyer**.

## Reading results

- With ~50 questions, differences of a few points fall inside the 95% interval; prefer large changes that also hold on holdout.
- The judge is from the same model family as the answers (Nova), so absolute answer-quality scores are optimistic; use them to compare configurations.
- Compare runs only when `set_hash` matches.
- Evals generate at temperature 0; the report pipeline's adapter defaults to 0.7.

## Targets and remediation

| Metric | Target | If it fails |
| --- | :---: | --- |
| Context recall (hit@k) | ≥ 0.85 | Raise `top_k`; check `chunking.py` boundaries so articles are not split |
| Context precision | ≥ 0.80 | Tune or enable the reranker; lower the final `top_k` |
| Faithfulness | ≥ 0.95 | Tighten the system prompt; lower temperature |
| Citation precision | 1.00 | Post-check that cited article numbers exist in the retrieved chunks |
| Abstention | high | Add a retrieval-distance threshold; add more unanswerable questions |

These are aspirational targets, not current results; read the current numbers in the dashboard.

## Open work

- Have a domain expert review the gold labels and `facts`.
- Run evals in CI as a quality gate (today they are run by hand and the results are not committed).
- Add the deterministic no-Markdown check.
- Consider an external framework (Ragas, DeepEval) only if the in-house metrics prove insufficient.
