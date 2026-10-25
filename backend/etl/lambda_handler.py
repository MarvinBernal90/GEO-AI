"""
==============================================================================
AWS LAMBDA SERVERLESS HANDLER: S3 EVENT TRIGGER -> EC2 / POSTGRES ETL
==============================================================================
File: backend/etl/lambda_handler.py

Triggered automatically by Amazon S3 (`s3:ObjectCreated:*`) whenever a new file
is uploaded to `s3://geoyield-raw-data-192445490421-eu-central-1/raw/`:
  1. New Legal PDF (`raw/legal/*.pdf`) -> Extracts text, embeds with Titan V2, saves in pgvector.
  2. New MITMA Mobility CSV (`raw/*_Viajes_distritos.csv.gz`) -> Runs incremental MITMA ETL.

Supports two execution modes controlled by environment variables:
  - Mode A (Default / Zero-Dependency Webhook):
    Forwards the S3 event `(bucket, key)` to the internal EC2 FastAPI endpoint
    `POST /api/etl/s3-event` using only Python's standard library (`urllib.request`),
    so it can be pasted directly into the AWS Lambda console in `eu-central-1`
    without packaging heavy C-extensions.
  - Mode B (Direct In-Lambda Execution):
    If `LAMBDA_EXECUTION_MODE=direct` is set (when deployed as a container image
    with database access), calls `backend.etl.sync_and_load.process_s3_event_key` directly.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import unquote_plus

logger = logging.getLogger("geoyield_lambda")
logger.setLevel(logging.INFO)

DEFAULT_EC2_API_URL = "http://3.64.17.221:8080"


def _forward_to_ec2_api(bucket: str, key: str, api_base_url: str, secret_token: str | None = None) -> dict[str, Any]:
    """Sends an HTTP POST request to the EC2 FastAPI backend to trigger incremental S3 ingestion."""
    url = f"{api_base_url.rstrip('/')}/api/etl/s3-event"
    payload = json.dumps({"bucket": bucket, "s3_key": key}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret_token:
        headers["X-ETL-Token"] = secret_token

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8")
        return {"status_code": response.status, "response": json.loads(body) if body else {}}


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """
    AWS Lambda entrypoint for S3 `ObjectCreated` events.
    """
    execution_mode = os.getenv("LAMBDA_EXECUTION_MODE", "webhook").lower()
    api_base_url = os.getenv("GEOYIELD_API_URL", DEFAULT_EC2_API_URL)
    secret_token = os.getenv("ETL_WEBHOOK_SECRET")

    records = event.get("Records", [])
    if not records:
        logger.warning("Lambda invoked with no S3 Records in event.")
        return {"statusCode": 400, "body": json.dumps({"message": "No S3 records found"})}

    results = []
    for record in records:
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        raw_key = s3_info.get("object", {}).get("key", "")
        key = unquote_plus(raw_key)

        if not bucket or not key:
            continue

        logger.info(f"Processing S3 event: s3://{bucket}/{key} (mode={execution_mode})")

        if execution_mode == "direct":
            from backend.etl.sync_and_load import process_s3_event_key

            res = process_s3_event_key(s3_key=key, bucket=bucket)
            results.append(res)
        else:
            res = _forward_to_ec2_api(bucket=bucket, key=key, api_base_url=api_base_url, secret_token=secret_token)
            results.append({"bucket": bucket, "key": key, **res})

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "processed", "results": results}),
    }
