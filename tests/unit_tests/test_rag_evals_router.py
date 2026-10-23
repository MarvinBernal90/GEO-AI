"""
==============================================================================
UNIT TESTS: RAG EVALS ROUTER
==============================================================================
File: tests/unit_tests/test_rag_evals_router.py

The router only reads JSON files, so the tests point it at a temporary folder.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.api.api import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALS_RESULTS_DIR", str(tmp_path))
    (tmp_path / "runs").mkdir()
    return tmp_path


def _write_run(results, run_id, **extra):
    run = {
        "run_id": run_id,
        "name": "baseline",
        "set": "dev",
        "retrieval": {"hit@3": {"value": 0.5}},
        "questions": [{"id": "q1"}],
        **extra,
    }
    (results / "runs" / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")


@pytest.mark.usefixtures("results")
class TestEmptyAndMissing:
    def test_empty_folder_gives_an_empty_list(self, client):
        assert client.get("/api/evals/runs").json() == {"runs": []}

    def test_unknown_run_is_404(self, client):
        assert client.get("/api/evals/runs/nope").status_code == 404

    def test_missing_corpus_report_is_404(self, client):
        assert client.get("/api/evals/corpus").status_code == 404

    @pytest.mark.parametrize("bad", ["..%2F..%2Fetc%2Fpasswd", "%2E%2E", ".hidden"])
    def test_path_traversal_ids_never_reach_the_filesystem(self, client, bad):
        assert client.get(f"/api/evals/runs/{bad}").status_code in (404, 422)


def test_missing_folder_gives_an_empty_list(client, tmp_path, monkeypatch):
    monkeypatch.setenv("EVALS_RESULTS_DIR", str(tmp_path / "nope"))
    assert client.get("/api/evals/runs").json() == {"runs": []}


class TestWithRuns:
    def test_list_is_newest_first_and_drops_the_question_rows(self, client, results):
        _write_run(results, "20260101-000000-a-dev")
        _write_run(results, "20260102-000000-b-dev")
        runs = client.get("/api/evals/runs").json()["runs"]
        assert [r["run_id"] for r in runs] == ["20260102-000000-b-dev", "20260101-000000-a-dev"]
        assert "questions" not in runs[0]

    def test_detail_returns_the_questions(self, client, results):
        _write_run(results, "20260101-000000-a-dev")
        assert client.get("/api/evals/runs/20260101-000000-a-dev").json()["questions"] == [{"id": "q1"}]

    def test_a_corrupt_file_is_skipped_not_fatal(self, client, results):
        (results / "runs" / "broken.json").write_text("{not json", encoding="utf-8")
        _write_run(results, "20260101-000000-a-dev")
        runs = client.get("/api/evals/runs").json()["runs"]
        assert [r["run_id"] for r in runs] == ["20260101-000000-a-dev"]

    def test_corpus_report_is_returned(self, client, results):
        (results / "corpus.json").write_text(json.dumps({"total_chunks": 5}), encoding="utf-8")
        assert client.get("/api/evals/corpus").json() == {"total_chunks": 5}
