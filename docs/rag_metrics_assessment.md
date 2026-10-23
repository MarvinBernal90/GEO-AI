# Assessment: Measuring RAG Quality in the Urbanism Legal Assistant

This document provides a comprehensive technical guide and architectural assessment on how to evaluate the Retrieval-Augmented Generation (RAG) pipeline in the **PJ** codebase (`backend/rag`).

---

## 1. Executive Summary & The RAG Triad

In Retrieval-Augmented Generation (RAG), system quality cannot be measured as a single monolithic metric. It decomposes into two decoupled sub-systems:
1. **The Retrieval Pipeline** (`pgvector` cosine similarity + zone-aware filtering + Bedrock Reranker).
2. **The Generation Pipeline** (Context synthesis + cross-lingual translation + Bedrock Nova Lite LLM).

Evaluating RAG requires assessing the **RAG Triad** (Retrieval $\rightarrow$ Augmentation $\rightarrow$ Generation) across five foundational dimensions:

```
                    ┌──────────────────────────────────────────────┐
                    │               User Query (Q)                 │
                    └───────────┬──────────────────────┬───────────┘
                                │                      │
                        Context │              Answer  │
                        Recall  │ Context            Relevancy
                                │ Precision            │
                                ▼                      ▼
                    ┌───────────────────┐      ┌───────────────────┐
                    │ Retrieved Context │─────▶│ Generated Answer  │
                    │    Chunks (C)     │      │       (A)         │
                    └───────────────────┘      └───────────────────┘
                                  ▲                      │
                                  │    Faithfulness /    │
                                  └──── Groundedness ────┘
```

---

## 2. Core Metrics: Definitions & Formulations

To measure these metrics systematically, each evaluation record in the benchmark dataset requires:
- **$Q$** (User Query)
- **$C$** (Retrieved Context Chunks)
- **$A$** (Generated Answer)
- **$G_A$** (Ground Truth Answer — required for Context Recall)
- **$G_C$** (Ground Truth Context Chunks — optional, enhances retrieval verification)

---

### A. Retrieval Metrics

#### 1. Context Precision (Signal-to-Noise & Rank Ordering)
* **Definition:** Evaluates whether retrieved chunks are relevant to the query and, crucially, whether the most relevant chunks appear at top ranks.
* **PJ Context:** In `backend/rag/query_engine.py`, retrieval fetches `top_k=10` candidate chunks across specific zones and general laws, then narrows down to `final_top_k=4` via `amazon.rerank-v1:0`. High precision ensures that the operative PGM articles are prioritized at ranks 1–2, minimizing context noise and preventing "lost-in-the-middle" LLM degradation.
* **Mathematical Formulation (Mean Average Precision):**
  $$\text{Context Precision@K} = \frac{\sum_{k=1}^K (\text{Precision@}k \times v_k)}{\text{Total Relevant Chunks in Top } K}$$
  *(where $v_k \in \{0, 1\}$ indicates whether chunk $k$ is relevant to answering the query).*

#### 2. Context Recall (Retrieval Completeness)
* **Definition:** Measures whether the vector search and reranker retrieved *all* the necessary legal provisions needed to answer the question comprehensively.
* **PJ Context:** Municipal regulations in Barcelona frequently combine general city rules with district- or zone-specific nuances (e.g., Article 302 of the PGM for zoning classification combined with Ordre INT/358/2011 for closing times). Missing either chunk leads to an incomplete or legally incorrect answer.
* **Sentence Attribution Formulation:**
  $$\text{Context Recall} = \frac{|\{s_i \in G_A \mid s_i \text{ is attributed to } C\}|}{|G_A|}$$
  *(where each claim/sentence $s_i$ in ground truth $G_A$ is checked for semantic presence in $C$).*

---

### B. Generation Metrics

#### 3. Faithfulness (Anti-Hallucination & Factual Consistency)
* **Definition:** Measures whether every factual claim in the generated answer $A$ is strictly supported by and entailed from the retrieved context $C$. It evaluates factual consistency with respect to the retrieved text, not external world knowledge.
* **PJ Context:** The prompt in `backend/rag/query_engine.py` mandates: `"Respondes ÚNICAMENTE basándote en los artículos normativos que se te proporcionan como contexto"`. Any score below 1.0 indicates hallucinations, invented article numbers, or unauthorized extrapolations.
* **Formulation:**
  1. Deconstruct answer $A$ into atomic statements: $S(A) = \{s_1, s_2, \dots, s_n\}$.
  2. For each statement $s_i$, determine logical entailment: $E(s_i, C) \in \{0, 1\}$.
  $$\text{Faithfulness} = \frac{\sum_{i=1}^n E(s_i, C)}{|S(A)|}$$

#### 4. Groundedness vs. Faithfulness (and Citation Fidelity)
* **Distinction:** While often used synonymously with Faithfulness, in legal/regulatory RAG, **Groundedness** is best measured through **Citation Fidelity / Claim-to-Source Attribution**:
  * **Citation Precision:** When the model outputs `"según el Artículo 302 del PGM..."`, does the cited article actually support the specific claim made in that sentence?
  * **Citation Recall:** Did the model cite all articles from the context that contributed information to the response?
* **Formulation:**
  $$\text{Citation Precision} = \frac{\text{Number of correctly supported legal citations}}{\text{Total legal citations emitted in answer}}$$

#### 5. Answer Relevancy (Query Fulfillment)
* **Definition:** Measures how directly and concisely the generated answer addresses the user's intent without wandering off-topic or including redundant filler.
* **Formulation:** An evaluator LLM generates $M$ potential questions $\{q_1, \dots, q_m\}$ that the answer $A$ would address. The metric is the mean cosine similarity between the original query $Q$ and the generated questions:
  $$\text{Answer Relevancy} = \frac{1}{m} \sum_{j=1}^m \frac{E(Q) \cdot E(q_j)}{\|E(Q)\| \|E(q_j)\|}$$

---

## 3. Specific Challenges & Nuances in the `PJ` Architecture

| Architectural Feature in `PJ` | Impact on Evaluation | Mitigation / Evaluation Strategy |
| :--- | :--- | :--- |
| **Cross-Lingual RAG** (Catalan legal corpus $\rightarrow$ Spanish/English queries & answers) | Embeddings and semantic evaluations must bridge the language gap without penalizing valid translations. | Evaluator LLM prompts must explicitly state that semantic equivalence across Catalan and Spanish counts as valid entailment. |
| **Zone-Aware Hybrid Search** (`zona_pgm` specific + `zona_pgm IS NULL` general) | Retrieval quality depends on upstream NLU / geocoding identifying the zone code correctly. | Benchmark retrieval with explicit zone tags, unzoned queries, and invalid zones to isolate routing errors from vector distance errors. |
| **Two-Stage Retrieval** (`pgvector` top-10 $\rightarrow$ Bedrock Rerank top-4) | Evaluating only the final output obscures whether failures originate in initial vector recall or reranker pruning. | Track **Recall@10** at the pgvector stage and **Precision@4** post-rerank. |
| **Negative Rejection / Abstention** (`"Si el contexto no contiene información suficiente, dilo explícitamente"`) | If context lacks the answer, generating an answer is a failure, while abstaining is a success. | Include adversarial / unanswerable questions in your benchmark to measure **Abstention Accuracy** (specificity). |
| **UI Constraints (No Markdown)** | System prompt forbids `**bold**`, `#`, or list bullets `*`/`-` to prevent raw tokens in frontend popups. | Add a deterministic lint check verifying zero Markdown syntax tokens in the response payload. |

---

## 4. Recommended Tooling & Evaluation Frameworks

1. **Ragas (`ragas`) — *Recommended for batch benchmarks***
   * Implements the full RAG triad (`context_precision`, `context_recall`, `faithfulness`, `answer_relevancy`).
   * Seamless integration with Amazon Bedrock via `langchain-aws`.
   * Provides `TestsetGenerator` to synthetically bootstrap legal QA pairs from `legal_chunks`.

2. **DeepEval (`deepeval`) — *Recommended for CI/CD Pytest integration***
   * Unit-test native: tests execute directly inside `pytest`.
   * Enables assertion of quality gates (e.g., `assert_test(test_case, [faithfulness_metric >= 0.95])`).

3. **Amazon Bedrock Model Evaluation / FMEval**
   * Managed AWS evaluation service (`bedrock.create_evaluation_job`).
   * Useful for foundational model benchmarking (e.g., comparing Amazon Nova Lite against Claude 3.5 Sonnet on regulatory accuracy).

---

## 5. Implementation Guide for `PJ`

### Phase 1: Golden Dataset Structure
Construct a test dataset (50–100 examples) covering:
1. **Single-Hop Lookup (60%):** Direct lookup (e.g., *"¿Cuál es la altura máxima en zona 12?"* $\rightarrow$ Articles 280–285).
2. **Multi-Regulation Synthesis (25%):** Combining local PGM zoning with municipal decrees (e.g., opening hours in Ciutat Vella for musical bars).
3. **Out-of-Scope / Unanswerable (15%):** Testing negative rejection (e.g., questions regarding Madrid zoning or unlegislated activities).

Save this dataset as `tests/evaluation/golden_dataset.json`:
```json
[
  {
    "query": "¿Qué limitaciones de horario tiene un bar musical en Ciutat Vella?",
    "ground_truth_answer": "Según la Ordre INT/358/2011, el horario de cierre máximo general es hasta las 2:30 horas...",
    "expected_articles": ["Ordre INT/358/2011:4", "PGM:302"],
    "zona_pgm": "nucli_antic"
  }
]
```

### Phase 2: Evaluation Script (`backend/rag/evaluation.py`)

```python
"""
RAG Evaluation Pipeline using Ragas with Amazon Bedrock.
"""
from datasets import Dataset
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from backend.db.connection import get_db_session
from backend.rag.query_engine import (
    generate_answer,
    retrieve_relevant_chunks_with_rerank,
)


def run_rag_assessment(golden_dataset: list[dict]):
    eval_records = []

    with get_db_session() as session:
        for item in golden_dataset:
            query = item["query"]
            zona = item.get("zona_pgm")

            # 1. Retrieve candidates
            chunks = retrieve_relevant_chunks_with_rerank(
                session=session,
                query=query,
                zona_pgm=zona,
                final_top_k=4,
            )

            # 2. Generate answer
            result = generate_answer(
                session=session,
                question=query,
                zona_pgm=zona,
            )

            eval_records.append(
                {
                    "question": query,
                    "contexts": [
                        f"{c.fuente_legal} Art. {c.numero_articulo}: {c.contenido}"
                        for c in chunks
                    ],
                    "answer": result["respuesta"],
                    "ground_truth": item["ground_truth_answer"],
                }
            )

    # 3. Configure Evaluator Models (Bedrock)
    evaluator_llm = ChatBedrockConverse(
        model_id="eu.anthropic.claude-3-5-sonnet-20240620-v1:0",
        region_name="eu-central-1",
    )
    evaluator_embeddings = BedrockEmbeddings(
        model_id="amazon.titan-embed-text-v2:0",
        region_name="eu-central-1",
    )

    dataset = Dataset.from_list(eval_records)

    # 4. Compute Ragas Metrics
    results = evaluate(
        dataset=dataset,
        metrics=[
            context_precision,
            context_recall,
            faithfulness,
            answer_relevancy,
        ],
        llm=evaluator_llm,
        embeddings=evaluator_embeddings,
    )

    return results
```

---

## 6. Target Production Thresholds & Remediation Strategies

| Metric | Target | Failure Root Cause | Remediation Strategy |
| :--- | :---: | :--- | :--- |
| **Context Recall** | $\ge 0.85$ | Vector similarity missed relevant sections; or chunk boundaries split an article across chunks. | Increase initial `top_k` (from 10 to 20); inspect `chunking.py` regex boundaries to ensure articles are preserved intact. |
| **Context Precision** | $\ge 0.80$ | Unrelated municipal laws ranked above operative articles. | Tune reranker; lower `final_top_k` (from 4 to 3) to exclude marginal chunks. |
| **Faithfulness** | $\ge 0.95$ | LLM hallucinated ungrounded requirements or invented article numbers. | Enforce zero temperature (`temperature=0.0`); tighten system prompt constraints. |
| **Answer Relevancy** | $\ge 0.85$ | Response is conversational or wanders off topic. | Refine system prompt instructions; apply query rewriting prior to retrieval. |
| **Citation Precision** | $1.00$ | Model cited an article not in the retrieved context. | Add a deterministic post-processing check matching cited article numbers against retrieved chunk metadata. |
