"""
==============================================================================
ETL PIPELINE: DISTRICT MOBILITY / FOOT TRAFFIC (MITMA)
==============================================================================
File: backend/etl/mobility.py

This module extracts and transforms massive mobile tracking data from MITMA
(Ministry of Transport). It processes nationwide data to calculate the exact
daily foot traffic (`daily_foot_traffic`) arriving at each Barcelona district.

Consolidates the logic from `notebooks/01_eda_mobility_mitma.ipynb`.
"""

import pandas as pd

from .config import BARCELONA_MUNICIPIO_CODE


def read_raw_mobility(path_or_paths) -> pd.DataFrame:
    """
    Reads one or multiple raw MITMA mobility CSV files.

    Data Engineering Note (Silent Bug Prevention):
    The `sep="|"` is intentional, as MITMA uses pipes instead of commas.
    Pandas automatically handles the .gz compression.

    CRITICAL: `dtype={"destino": str, "origen": str}` prevents the "Lost Zero" bug.
    INE zone codes often start with zero (e.g., "0801901" for District 1).
    If Pandas infers this as an `int64`, it silently drops the leading zero
    (becoming 801901). Later on, when we try to filter for strings starting
    with "08019", the filter fails completely, returning an empty table.
    Forcing `str` parsing protects the data integrity.
    """
    paths = path_or_paths if isinstance(path_or_paths, (list, tuple)) else [path_or_paths]
    dfs = []
    for p in paths:
        df = pd.read_csv(p, sep="|", dtype={"destino": str, "origen": str}, compression="infer")
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def build_district_mobility(raw_df: pd.DataFrame, num_files: int = 1) -> pd.DataFrame:
    """
    Transforms the raw MITMA Big Data into a simple district-level summary.

    Transformation Rules:
        1. The destination code format is "08" (Province) + "019" (Municipality)
           + "NN" (District 01-10). Example: "0801901".
        2. We filter the nationwide dataset to keep ONLY rows where the
           destination starts with "08019".
        3. We extract the last two characters to get the `codi_districte`.
        4. Group by district and sum the total trips to get foot traffic,
           dividing by the number of dates/files to obtain daily average.
    """
    df = raw_df.copy()
    df["destino"] = df["destino"].astype(str)

    # 1. Geographic Filtering: Keep only trips arriving in Barcelona
    is_barcelona = df["destino"].str.startswith(BARCELONA_MUNICIPIO_CODE)
    df = df[is_barcelona].copy()

    # Fail-Fast mechanism: Do not proceed silently if the filter fails.
    if df.empty:
        raise ValueError(
            "No mobility trips found ending in Barcelona."
            f"Expected 'destino' to start with '{BARCELONA_MUNICIPIO_CODE}'; "
            "Verify the source CSV format and its leading zeros."
        )

    # 2. Extract District ID (e.g., from "0801901" to 1)
    df["codi_districte"] = df["destino"].str[-2:].astype(int)

    # 3. Aggregation: Sum all trips and average by number of dates/files
    divisor = num_files if num_files > 0 else 1
    if "fecha" in df.columns and df["fecha"].nunique() > 1:
        divisor = df["fecha"].nunique()

    aggregated = df.groupby("codi_districte", as_index=False).agg(daily_foot_traffic=("viajes", "sum"))
    aggregated["daily_foot_traffic"] = aggregated["daily_foot_traffic"] / divisor

    # 4. Metadata: Take the date from the data or today's date
    if "fecha" in df.columns and not df["fecha"].empty:
        aggregated["fecha"] = pd.to_datetime(df["fecha"].iloc[0], format="%Y%m%d").date()
    else:
        aggregated["fecha"] = pd.Timestamp.today().date()

    return aggregated


def load_district_mobility(path_or_paths) -> pd.DataFrame:
    """Wrapper function: Reads and transforms the dataset(s) in a single call."""
    paths = path_or_paths if isinstance(path_or_paths, (list, tuple)) else [path_or_paths]
    raw_df = read_raw_mobility(paths)
    return build_district_mobility(raw_df, num_files=len(paths))
