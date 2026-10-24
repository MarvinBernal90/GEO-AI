import os
import time

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from pydantic import BaseModel

from backend.etl.etl_mitma import PROGRESS, run_etl
from backend.etl.sync_and_load import process_s3_event_key, run_full_sync_and_load
from backend.observability import get_logger

logger = get_logger("api.routers.etl")
router = APIRouter(prefix="/api/etl", tags=["ETL"])


class S3EventPayload(BaseModel):
    bucket: str | None = None
    s3_key: str


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


@router.post("/s3-event")
def trigger_s3_event_etl(
    payload: S3EventPayload,
    background_tasks: BackgroundTasks,
    x_etl_token: str | None = Header(default=None),
):
    """
    Webhook endpoint invoked by AWS Lambda (`lambda_handler.py`) when a new PDF or
    MITMA CSV is uploaded to the S3 Data Lake. Downloads and ingests the file in background.
    """
    expected_secret = os.getenv("ETL_WEBHOOK_SECRET")
    if expected_secret and x_etl_token != expected_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ETL webhook token.")

    logger.info("S3 event received via Lambda for key=%s (bucket=%s)", payload.s3_key, payload.bucket)
    background_tasks.add_task(process_s3_event_key, payload.s3_key, payload.bucket)
    return {"status": "accepted", "s3_key": payload.s3_key}


@router.post("/sync-all")
def trigger_full_sync_and_load(
    background_tasks: BackgroundTasks,
    skip_mitma: bool = False,
    x_etl_token: str | None = Header(default=None),
):
    """
    Triggers a complete S3 Data Lake synchronization and database ingestion in background.
    """
    expected_secret = os.getenv("ETL_WEBHOOK_SECRET")
    if expected_secret and x_etl_token != expected_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ETL webhook token.")

    logger.info("Full S3 sync and load triggered via API (skip_mitma=%s).", skip_mitma)
    background_tasks.add_task(run_full_sync_and_load, None, skip_mitma)
    return {"status": "accepted", "message": "Full S3 sync and load started in background."}
