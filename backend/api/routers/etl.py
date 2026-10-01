from fastapi import APIRouter

from backend.etl.etl_mitma import run_etl
from backend.observability import get_logger

logger = get_logger("api.routers.etl")
router = APIRouter(prefix="/api/etl", tags=["ETL"])


@router.post("/mitma")
def trigger_mitma_etl():
    """
    Triggers the ETL process for MITMA intraprovincial mobility data.
    Runs synchronously so the frontend can show a loading state until it finishes.
    """
    logger.info("API Request received to trigger MITMA ETL.")
    run_etl()
    return {"status": "success", "message": "ETL process for MITMA completed successfully."}
