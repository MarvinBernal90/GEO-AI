"""
==============================================================================
UNIT TESTS: RAG EVALUATION METRICS
==============================================================================
File: tests/unit_tests/test_eval_metrics.py

Every number here is worked out by hand, because a metric nobody has checked
is worse than no metric.
"""

import math

import pytest

from evals import metrics as M

A, B, C, D = ("L", "1"), ("L", "2"), ("L", "3"), ("M", "9")


class TestRanking:
    def test_first_hit_rank_is_one_based_and_none_when_missing(self):
        assert M.first_hit_rank([A, B, C], [B]) == 2
        assert M.first_hit_rank([A, B, C], [D]) is None

    def test_hit_at_k_respects_the_cutoff(self):
        assert M.hit_at_k([A, B, C], [C], 3) is True
        assert M.hit_at_k([A, B, C], [C], 2) is False

    def test_reciprocal_rank(self):
        assert M.reciprocal_rank([A, B, C], [C]) == pytest.approx(1 / 3)
        assert M.reciprocal_rank([A, B, C], [D]) == 0.0

    def test_ndcg_is_one_when_gold_is_first_and_discounted_otherwise(self):
        assert M.ndcg_at_k([A, B], [A], 10) == pytest.approx(1.0)
        # gold at rank 2: (1/log2(3)) / (1/log2(2)) = 0.6309...
        assert M.ndcg_at_k([A, B], [B], 10) == pytest.approx(1 / math.log2(3))

    def test_ndcg_with_two_gold_chunks(self):
        # gold at ranks 1 and 3: dcg = 1 + 1/log2(4) = 1.5 ; ideal = 1 + 1/log2(3)
        expected = 1.5 / (1 + 1 / math.log2(3))
        assert M.ndcg_at_k([A, B, C], [A, C], 10) == pytest.approx(expected)

    def test_recall_at_k_counts_the_share_of_gold_found(self):
        assert M.recall_at_k([A, B, C], [A, C, D], 3) == pytest.approx(2 / 3)

    def test_doc_hit_finds_the_right_law_even_with_the_wrong_article(self):
        assert M.doc_hit_at_k([("L", "7")], [("L", "1")], 5) is True
        assert M.doc_hit_at_k([("M", "7")], [("L", "1")], 5) is False


class TestIntervals:
    def test_wilson_matches_the_textbook_value(self):
        lo, hi = M.wilson(8, 10)
        assert lo == pytest.approx(0.490, abs=0.002)
        assert hi == pytest.approx(0.943, abs=0.002)

    def test_wilson_with_no_data(self):
        assert M.wilson(0, 0) == (0.0, 0.0)

    def test_bootstrap_is_seeded_and_brackets_the_mean(self):
        values = [0, 1, 1, 1, 0, 1, 1, 0, 1, 1]
        assert M.bootstrap_ci(values) == M.bootstrap_ci(values)
        lo, hi = M.bootstrap_ci(values)
        assert lo <= 0.7 <= hi

    def test_rate_reports_value_interval_and_n(self):
        r = M.rate(3, 4)
        assert r["value"] == 0.75 and r["n"] == 4 and r["lo"] < 0.75 < r["hi"]
        assert M.rate(0, 0)["value"] is None

    def test_percentile_interpolates(self):
        assert M.percentile([1, 2, 3, 4], 0.5) == 2.5
        assert M.percentile([], 0.5) is None


class TestAbstentionSignal:
    def test_auroc_perfect_random_and_ties(self):
        assert M.auroc([0.9, 0.8], [0.3, 0.2]) == 1.0
        assert M.auroc([0.3, 0.2], [0.9, 0.8]) == 0.0
        assert M.auroc([0.5], [0.5]) == 0.5
        assert M.auroc([], [0.5]) is None


class TestSetHash:
    BASE = [{"id": "a", "question": "q1", "gold": [{"fuente_legal": "L", "numero_articulo": "1"}]}]

    def test_ignores_order_and_irrelevant_fields(self):
        other = [{**self.BASE[0], "tags": ["x"], "facts": ["whatever"]}]
        assert M.set_hash(self.BASE) == M.set_hash(other)

    def test_changes_when_a_gold_label_or_question_changes(self):
        moved = [{**self.BASE[0], "gold": [{"fuente_legal": "L", "numero_articulo": "2"}]}]
        reworded = [{**self.BASE[0], "question": "q2"}]
        assert len({M.set_hash(self.BASE), M.set_hash(moved), M.set_hash(reworded)}) == 3


class TestLanguage:
    def test_detects_spanish_catalan_and_english(self):
        assert M.detect_lang("Según el artículo, el titular de la actividad debe presentar una solicitud.") == "es"
        assert M.detect_lang("Segons l'article, el titular de l'activitat ha de presentar una sol·licitud.") == "ca"
        assert M.detect_lang("According to the article, the owner of the business must file a request.") == "en"

    def test_short_text_is_unknown(self):
        assert M.detect_lang("hola") == "unknown"


class TestCitations:
    def test_extracts_articles_in_spanish_and_catalan(self):
        text = "Según el Artículo 302 y el artículo 131-1, y l'Article 7. També Art. 12 bis."
        assert M.extract_cited_articles(text) == {"302", "131-1", "7", "12 bis"}

    def test_paragraph_references_collapse_to_the_article(self):
        assert M.extract_cited_articles("Artículo 7.1 y artículo 7.3") == {"7"}

    def test_hyphenated_numbers_are_kept_whole(self):
        assert M.extract_cited_articles("artículo 131-1") == {"131-1"}

    def test_validity_separates_valid_cross_reference_and_invented(self):
        context = "De acuerdo con el artículo 71 del Reglamento, no se puede servir."
        result = M.citation_validity({"8", "71", "999"}, ["8", "9"], context)
        assert result["valid"] == ["8"]
        assert result["cross_reference"] == ["71"]
        assert result["invalid"] == ["999"]


class TestExtractJson:
    def test_plain_and_wrapped_json(self):
        assert M.extract_json('{"a": 1}') == {"a": 1}
        assert M.extract_json('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}

    def test_thinking_block_with_braces_is_ignored(self):
        text = '<thinking>maybe {not json} here</thinking>{"abstains": false}'
        assert M.extract_json(text) == {"abstains": False}

    def test_garbage_gives_empty_dict(self):
        assert M.extract_json("no json at all") == {}
        assert M.extract_json("{broken") == {}
        assert M.extract_json("[1, 2]") == {}


class TestAggregation:
    ROWS = [
        {"gold": [A], "ranked": [A, B], "lang": "es"},
        {"gold": [B], "ranked": [A, B, C], "lang": "es"},
        {"gold": [D], "ranked": [A, B, C], "lang": "ca"},
    ]

    def test_summary_numbers(self):
        s = M.summarize_retrieval(self.ROWS)
        assert s["hit@1"]["value"] == pytest.approx(1 / 3)
        assert s["hit@3"]["value"] == pytest.approx(2 / 3)
        assert s["mrr"]["value"] == pytest.approx((1 + 0.5 + 0) / 3)
        assert s["hit@1"]["n"] == 3

    def test_slices_group_by_field(self):
        s = M.slice_retrieval(self.ROWS, "lang")
        assert set(s) == {"es", "ca"}
        assert s["es"]["hit@3"]["value"] == 1.0
        assert s["ca"]["hit@3"]["value"] == 0.0


class TestFailureClassification:
    def base(self, **kw):
        return {"answerable": True, "gold": [A], "ranked": [A, B], **kw}

    def test_retrieval_miss_beats_everything(self):
        assert (
            M.classify_failure(self.base(ranked=[B, C, D, ("X", "1"), ("X", "2"), ("X", "3"), A])) == "retrieval_miss"
        )

    def test_no_failure_without_a_judge_when_retrieval_is_fine(self):
        assert M.classify_failure(self.base()) is None

    def test_over_abstention_unsupported_and_generation_error(self):
        ok = {"fact_recall": 1.0, "unsupported": []}
        assert M.classify_failure(self.base(judge=ok, abstained=True)) == "over_abstention"
        assert M.classify_failure(self.base(judge={**ok, "unsupported": ["x"]}, abstained=False)) == "unsupported"
        assert M.classify_failure(self.base(judge={**ok, "fact_recall": 0.5}, abstained=False)) == "generation_error"
        assert M.classify_failure(self.base(judge=ok, abstained=False)) is None

    def test_unanswerable_answered_is_a_failure_and_abstaining_is_not(self):
        row = {"answerable": False, "gold": [], "ranked": [A], "answer": "text"}
        assert M.classify_failure({**row, "abstained": False}) == "wrongly_answered"
        assert M.classify_failure({**row, "abstained": True}) is None
