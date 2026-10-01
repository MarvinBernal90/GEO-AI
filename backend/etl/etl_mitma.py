import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

# Import Settings and Connection
from backend.db.connection import resolve_database_url
from backend.db.models import DistrictMobility
from backend.etl import config

# Structured logging system
from backend.observability import configure_logging, get_logger

logger = get_logger("etl.mitma")


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
        dtype={"ID": str, "poblacion": float}
    )

    # List the districts of Barcelona (INE code: 08019)
    df_bcn = df_nombres[df_nombres["ID"].str.startswith(config.BARCELONA_MUNICIPIO_CODE, na=False)].copy()
    df_bcn = df_bcn.merge(df_pob, on="ID", how="left")

    if df_bcn.empty:
        raise ValueError("No districts in Barcelona were found in the CSV files.")

    # Process each mobility file from MITMA
    all_trips = []

    # Tamaño del trozo (chunk) para no saturar memoria y ver el progreso
    chunk_size = 2_000_000

    for path in config.PATHS_MITMA_MOBILITY:
        file_size_mb = path.stat().st_size / (1024 * 1024)
        logger.info(f"Processing file: {path.name} (Size: {file_size_mb:.1f} MB)")

        trips_in_chunks = []
        trips_out_chunks = []

        # Leemos el archivo poco a poco (en chunks)
        csv_iterator = pd.read_csv(
            path, sep="|", dtype={"destino": str, "origen": str},
            compression='infer', chunksize=chunk_size
        )

        for i, chunk in enumerate(csv_iterator):
            logger.info(f"  -> {path.name}: Leyendo bloque {i+1} (~{chunk_size * (i+1):,} filas...)")

            # Limpieza: eliminar filas con nulos en las columnas clave
            chunk = chunk.dropna(subset=["origen", "destino", "viajes"])

            # 1. Viajes que llegan al distrito (destino)
            is_bcn_dest = chunk["destino"].str.startswith(config.BARCELONA_MUNICIPIO_CODE, na=False)
            trips_in_chunk = chunk[is_bcn_dest].groupby("destino", as_index=False)["viajes"].sum()
            trips_in_chunks.append(trips_in_chunk)

            # 2. Viajes que salen del distrito (origen)
            is_bcn_orig = chunk["origen"].str.startswith(config.BARCELONA_MUNICIPIO_CODE, na=False)
            trips_out_chunk = chunk[is_bcn_orig].groupby("origen", as_index=False)["viajes"].sum()
            trips_out_chunks.append(trips_out_chunk)

        # Consolidar los trozos de este archivo
        logger.info(f"  -> {path.name}: Consolidando datos del archivo...")
        trips_in = pd.concat(trips_in_chunks).groupby("destino", as_index=False)["viajes"].sum()
        trips_in.rename(columns={"destino": "distrito_id", "viajes": "viajes_in"}, inplace=True)

        trips_out = pd.concat(trips_out_chunks).groupby("origen", as_index=False)["viajes"].sum()
        trips_out.rename(columns={"origen": "distrito_id", "viajes": "viajes_out"}, inplace=True)

        # 3. Consolidar entradas y salidas por archivo
        trips_file = pd.merge(trips_in, trips_out, on="distrito_id", how="outer").fillna(0)

        all_trips.append(trips_file[["distrito_id", "viajes_in", "viajes_out"]])
        logger.info(f"Terminado con {path.name}")

    if not all_trips:
        raise ValueError("No se encontraron archivos CSV de MITMA para procesar.")

    # 4. Consolidar todas las fechas
    logger.info("Consolidando fechas y cruzando con población...")
    df_all = pd.concat(all_trips)

    # Sumarizamos los viajes in y out de todos los días y calculamos el promedio
    num_dias = len(config.PATHS_MITMA_MOBILITY)
    df_grouped = df_all.groupby("distrito_id", as_index=False)[["viajes_in", "viajes_out"]].sum()
    df_grouped["viajes_in_promedio"] = df_grouped["viajes_in"] / num_dias
    df_grouped["viajes_out_promedio"] = df_grouped["viajes_out"] / num_dias

    # 5. Cruzar con metadatos de Barcelona y calcular la métrica final
    df_final = df_bcn.merge(df_grouped, left_on="ID", right_on="distrito_id", how="left")
    df_final["viajes_in_promedio"] = df_final["viajes_in_promedio"].fillna(0)
    df_final["viajes_out_promedio"] = df_final["viajes_out_promedio"].fillna(0)

    # Población Flotante: Población residente + Los que entran - Los que salen
    df_final["poblacion_flotante"] = df_final["poblacion"] + df_final["viajes_in_promedio"] - df_final["viajes_out_promedio"]

    # Calculamos el daily_foot_traffic (índice de afluencia respecto a la población base)
    # Ejemplo: Si hay 110 flotantes y 100 residentes -> índice de 1.10
    df_final["daily_foot_traffic"] = df_final.apply(
        lambda row: row["poblacion_flotante"] / row["poblacion"] if row["poblacion"] > 0 else 0,
        axis=1
    )

    # 6. Preparar DataFrame para la base de datos (extraer el codi_districte, ej. de 0801901 -> 1)
    df_final["codi_districte"] = df_final["ID"].str[-2:].astype(int)

    # Asignamos una fecha representativa (hoy) o la última fecha procesada
    df_final["fecha"] = pd.Timestamp.today().date()

    # Seleccionar solo las columnas necesarias para la BD
    db_df = df_final[["codi_districte", "daily_foot_traffic", "poblacion_flotante", "fecha"]].copy()
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
    update_columns = {
        col: getattr(stmt.excluded, col) for col in df.columns if col != "codi_districte"
    }
    stmt = stmt.on_conflict_do_update(index_elements=["codi_districte"], set_=update_columns)

    session.execute(stmt)
    logger.info(f"DistrictMobility: {len(records)} districts that have been correctly added or updated.")


def run_etl():
    """Main function that performs the three steps: Extract, Transform, Load."""
    logger.info("Starting the Mobility (MITMA) ETL process with multiple files and population...")

    # 1. Extract and Transform
    try:
        mobility_df = process_mitma_data()
        logger.info("Pandas cleanup and aggregation completed successfully.")
    except Exception as e:
        logger.error(f"Error during extraction and cleaning: {e}")
        return

    # 2. Connect to Database
    from dotenv import load_dotenv
    load_dotenv()  # ¡IMPORTANTE! Lee las variables del archivo .env local

    url = resolve_database_url()
    engine = create_engine(url)

    # 3. Load to Database
    logger.info("Starting data dump to PostgreSQL...")
    with Session(engine) as session:
        _upsert_mobility(session, mobility_df)
        session.commit()

    logger.info("MITMA's ETL process was successfully completed.")

if __name__ == "__main__":
    configure_logging()
    run_etl()
