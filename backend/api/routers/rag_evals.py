"""
==============================================================================
API ROUTER: RAG EVALUATION RESULTS (READ-ONLY)
==============================================================================
File: backend/api/routers/rag_evals.py

Feeds the /evals dashboard of the frontend. It only READS the JSON files written by
the evaluation harness (evals/run_eval.py, evals/build_corpus.py); it never runs an
evaluation and never touches the database.

Endpoints:
    GET /api/evals/runs              one summary per run, newest first
    GET /api/evals/runs/{run_id}     one run with every question (ranking, answer, judge verdict)
    GET /api/evals/corpus            what the evaluation corpus contains (chunks per law, gaps)

Where the files live: EVALS_RESULTS_DIR, or <repo>/evals/results. The Docker image only
copies backend/, so a deployed API shows an empty dashboard unless that folder is mounted.
The files hold only the public legal corpus and the gold questions, never user text.
"""

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.observability import get_logger

logger = get_logger("api.rag_evals")

router = APIRouter(prefix="/api/evals", tags=["rag-evals"])

# run ids are built from a timestamp, a config name and the set; nothing else may reach the filesystem.
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def results_dir() -> Path:
    override = os.getenv("EVALS_RESULTS_DIR")
    return Path(override) if override else Path(__file__).resolve().parents[3] / "evals" / "results"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        logger.warning("evals.unreadable_file", extra={"file": path.name})
        return None


def _summary(run: dict[str, Any]) -> dict[str, Any]:
    """Everything the run list and the comparison charts need, without the per-question rows."""
    return {
        key: run.get(key)
        for key in (
            "run_id",
            "created_at",
            "name",
            "set",
            "set_hash",
            "config",
            "n_questions",
            "n_answerable",
            "n_unanswerable",
            "retrieval",
            "slices",
            "abstention_signal",
            "answers",
            "failures",
        )
    }


@router.get("/runs")
def list_runs(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    runs_dir = results_dir() / "runs"
    runs = []
    for path in sorted(runs_dir.glob("*.json"), reverse=True)[:limit] if runs_dir.is_dir() else []:
        run = _read(path)
        if run and "run_id" in run:
            runs.append(_summary(run))
    return {"runs": runs}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    if not _RUN_ID.match(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    run = _read(results_dir() / "runs" / f"{run_id}.json")
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/corpus")
def get_corpus() -> dict[str, Any]:
    corpus = _read(results_dir() / "corpus.json")
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus report not found. Run `python -m evals.build_corpus`.")
    return corpus
