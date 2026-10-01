import time

from fastapi import APIRouter, BackgroundTasks

from backend.etl.etl_mitma import PROGRESS, run_etl
from backend.observability import get_logger

logger = get_logger("api.routers.etl")
router = APIRouter(prefix="/api/etl", tags=["ETL"])


@router.post("/mitma")
def trigger_mitma_etl(background_tasks: BackgroundTasks):
    """
    Triggers the ETL process for MITMA intraprovincial mobility data.
    Runs asynchronously so the frontend can poll for progress.
    """
    if PROGRESS["status"] == "running":
        return {"status": "error", "message": "ETL already running"}

    logger.info("API Request received to trigger MITMA ETL.")
    background_tasks.add_task(run_etl)
    return {"status": "success", "message": "ETL process started in background."}

@router.get("/mitma/progress")
def get_mitma_etl_progress():
    if PROGRESS["start_time"] and PROGRESS["status"] == "running":
        PROGRESS["elapsed"] = time.time() - PROGRESS["start_time"]
    return PROGRESS
