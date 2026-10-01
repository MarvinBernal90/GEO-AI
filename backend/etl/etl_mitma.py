import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

# Import Settings and Connection
from backend.db.connection import resolve_database_url
from backend.db.models import DistrictMobility
from backend.etl import config
import time

# Structured logging system
from backend.observability import configure_logging, get_logger

logger = get_logger("etl.mitma")

PROGRESS = {
    "status": "idle",
    "progress": 0,
    "start_time": None,
    "elapsed": 0,
    "message": ""
}


def process_mitma_data() -> pd.DataFrame:
    """
    Reads and cleans the names, population, and mobility data from MITMA.
    Processes multiple files from different dates and calculates pedestrian traffic.
    """
    # 1. Load district metadata
    logger.info("Loading district names and populations...")
    df_nombres = pd.read_csv(config.PATH_NOMBRES_DISTRITOS, sep="|", dtype=str)

    # The population CSV seems to have no header in the first row, forcing names
    df_pob = pd.read_csv(
        config.PATH_POBLACION_DISTRITOS,
        sep="|",
        header=None,
        names=["ID", "poblacion"],
        dtype={"ID": str, "poblacion": float},
    )

    # List the districts of Barcelona (INE code: 08019)
    df_bcn = df_nombres[df_nombres["ID"].str.startswith(config.BARCELONA_MUNICIPIO_CODE, na=False)].copy()
    df_bcn = df_bcn.merge(df_pob, on="ID", how="left")

    if df_bcn.empty:
        raise ValueError("No districts in Barcelona were found in the CSV files.")

    # Process each mobility file from MITMA
    all_trips = []

    # Size of chunk
    chunk_size = 2_000_000
    num_files = len(config.PATHS_MITMA_MOBILITY)

    for file_idx, path in enumerate(config.PATHS_MITMA_MOBILITY):
        PROGRESS["progress"] = int((file_idx / num_files) * 80)
        PROGRESS["message"] = f"Procesando archivo {file_idx + 1}/{num_files}: {path.name}"
        file_size_mb = path.stat().st_size / (1024 * 1024)
        logger.info(f"Processing file: {path.name} (Size: {file_size_mb:.1f} MB)")

        trips_in_chunks = []
        trips_out_chunks = []

        # Reading in chunks
        csv_iterator = pd.read_csv(
            path, sep="|", dtype={"destino": str, "origen": str, "edad": str}, compression="infer", chunksize=chunk_size
        )

        for i, chunk in enumerate(csv_iterator):
            logger.info(f"  -> {path.name}: Leyendo bloque {i + 1} (~{chunk_size * (i + 1):,} filas...)")

            # Delete rows with missing values in critical columns and filter out 'NA' ages
            chunk = chunk.dropna(subset=["origen", "destino", "edad", "viajes"])
            chunk = chunk[chunk["edad"] != "NA"]

            # Trips that enter the district (destino)
            is_bcn_dest = chunk["destino"].str.startswith(config.BARCELONA_MUNICIPIO_CODE, na=False)
            trips_in_chunk = chunk[is_bcn_dest].groupby(["destino", "edad"], as_index=False)["viajes"].sum()
            trips_in_chunks.append(trips_in_chunk)

            # Trips that leave the district (origen)
            is_bcn_orig = chunk["origen"].str.startswith(config.BARCELONA_MUNICIPIO_CODE, na=False)
            trips_out_chunk = chunk[is_bcn_orig].groupby("origen", as_index=False)["viajes"].sum()
            trips_out_chunks.append(trips_out_chunk)

        # Consolidate the segments of this file
        logger.info(f"  -> {path.name}: Consolidando datos del archivo...")
        trips_in_with_age = pd.concat(trips_in_chunks).groupby(["destino", "edad"], as_index=False)["viajes"].sum()

        trips_in = trips_in_with_age.groupby("destino", as_index=False)["viajes"].sum()
        trips_in.rename(columns={"destino": "distrito_id", "viajes": "viajes_in"}, inplace=True)

        trips_out = pd.concat(trips_out_chunks).groupby("origen", as_index=False)["viajes"].sum()
        trips_out.rename(columns={"origen": "distrito_id", "viajes": "viajes_out"}, inplace=True)

        # Consolidate Incoming and Outgoing Transactions by File
        trips_file = pd.merge(trips_in, trips_out, on="distrito_id", how="outer").fillna(0)

        #  Save the age information to add it later
        trips_in_with_age.rename(columns={"destino": "distrito_id"}, inplace=True)
        all_trips.append({"totals": trips_file[["distrito_id", "viajes_in", "viajes_out"]], "ages": trips_in_with_age})
        logger.info(f"Terminado con {path.name}")

    if not all_trips:
        raise ValueError("No se encontraron archivos CSV de MITMA para procesar.")

    PROGRESS["progress"] = 80
    PROGRESS["message"] = "Consolidando fechas y cruzando con población..."
    # Consolidate all dates
    logger.info("Consolidando fechas y cruzando con población...")
    df_all_totals = pd.concat([t["totals"] for t in all_trips])
    df_all_ages = pd.concat([t["ages"] for t in all_trips])

    # We tally the daily inbound and outbound trips and calculate the average
    num_dias = len(config.PATHS_MITMA_MOBILITY)
    df_grouped = df_all_totals.groupby("distrito_id", as_index=False)[["viajes_in", "viajes_out"]].sum()
    df_grouped["viajes_in_promedio"] = df_grouped["viajes_in"] / num_dias
    df_grouped["viajes_out_promedio"] = df_grouped["viajes_out"] / num_dias

    # Calculate the predominant age by district
    df_ages_sum = df_all_ages.groupby(["distrito_id", "edad"], as_index=False)["viajes"].sum()
    pred_age = df_ages_sum.loc[df_ages_sum.groupby("distrito_id")["viajes"].idxmax()][["distrito_id", "edad"]]
    pred_age.rename(columns={"edad": "predominant_age"}, inplace=True)
    df_grouped = df_grouped.merge(pred_age, on="distrito_id", how="left")

    # Cross-reference with metadata from Barcelona and calculate the final metric
    df_final = df_bcn.merge(df_grouped, left_on="ID", right_on="distrito_id", how="left")
    df_final["viajes_in_promedio"] = df_final["viajes_in_promedio"].fillna(0)
    df_final["viajes_out_promedio"] = df_final["viajes_out_promedio"].fillna(0)

    # Floating Population: Resident Population + In-migrants - Out-migrants
    df_final["poblacion_flotante"] = (
        df_final["poblacion"] + df_final["viajes_in_promedio"] - df_final["viajes_out_promedio"]
    )

    # Calculating the daily_foot_traffic (foot traffic index relative to the base population)
    # Example: If there are 110 non-residents and 100 residents -> ratio of 1.10
    df_final["daily_foot_traffic"] = df_final.apply(
        lambda row: row["poblacion_flotante"] / row["poblacion"] if row["poblacion"] > 0 else 0, axis=1
    )

    # Prepare the DataFrame for the database (extract the codi_districte, e.g., from 0801901 to 1)
    df_final["codi_districte"] = df_final["ID"].str[-2:].astype(int)

    # Set a representative date (today) or the most recent processed date
    df_final["fecha"] = pd.Timestamp.today().date()

    # Select only the columns needed for the database
    db_df = df_final[["codi_districte", "daily_foot_traffic", "poblacion_flotante", "predominant_age", "fecha"]].copy()
    db_df.rename(columns={"poblacion_flotante": "total_trips"}, inplace=True)

    return db_df


def _upsert_mobility(session: Session, df: pd.DataFrame) -> None:
    """
    Load the DataFrame into PostgreSQL.
    Use Upsert so that if the district already exists, the values (daily_foot_traffic)
    are updated instead of being duplicated or causing an error.
    """
    if df.empty:
        logger.warning("Empty DataFrame, nothing is loaded from MITMA.")
        return

    records = df.to_dict(orient="records")
    stmt = pg_insert(DistrictMobility).values(records)

    # Todo lo que no sea la Primary Key ('codi_districte') se actualiza en caso de conflicto
    update_columns = {col: getattr(stmt.excluded, col) for col in df.columns if col != "codi_districte"}
    stmt = stmt.on_conflict_do_update(index_elements=["codi_districte"], set_=update_columns)

    session.execute(stmt)
    logger.info(f"DistrictMobility: {len(records)} districts that have been correctly added or updated.")


def run_etl():
    """Main function that performs the three steps: Extract, Transform, Load."""
    logger.info("Starting the Mobility (MITMA) ETL process with multiple files and population...")
    PROGRESS["status"] = "running"
    PROGRESS["progress"] = 0
    PROGRESS["start_time"] = time.time()
    PROGRESS["message"] = "Iniciando proceso ETL MITMA..."

    # 1. Extract and Transform
    try:
        mobility_df = process_mitma_data()
        logger.info("Pandas cleanup and aggregation completed successfully.")
        
        PROGRESS["progress"] = 90
        PROGRESS["message"] = "Volcando a PostgreSQL..."
    except Exception as e:
        logger.error(f"Error during extraction and cleaning: {e}")
        PROGRESS["status"] = "error"
        PROGRESS["message"] = f"Error: {e}"
        PROGRESS["elapsed"] = time.time() - PROGRESS["start_time"]
        return

    # 2. Connect to Database
    from dotenv import load_dotenv

    load_dotenv()  # ¡IMPORTANTE! Lee las variables del archivo .env local

    url = resolve_database_url()
    engine = create_engine(url)

    # 3. Load to Database
    logger.info("Starting data dump to PostgreSQL...")
    try:
        with Session(engine) as session:
            _upsert_mobility(session, mobility_df)
            session.commit()

        logger.info("MITMA's ETL process was successfully completed.")
        PROGRESS["status"] = "completed"
        PROGRESS["progress"] = 100
        PROGRESS["message"] = "Proceso ETL terminado con éxito."
    except Exception as e:
        logger.error(f"Error during database dump: {e}")
        PROGRESS["status"] = "error"
        PROGRESS["message"] = f"DB Error: {e}"
    finally:
        PROGRESS["elapsed"] = time.time() - PROGRESS["start_time"]


if __name__ == "__main__":
    configure_logging()
    run_etl()
