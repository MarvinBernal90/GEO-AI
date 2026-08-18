"""
Modelos ORM de la capa de datos sociodemográficos y geoespaciales.

Jerarquía geográfica reflejada en el censo comercial de Barcelona:
    District (10)  ->  Neighborhood (barrio)  ->  Competitor (local individual)

Decisiones de diseño (Fase 1, validadas con el usuario):
    - Snapshot único para `district_income` y `district_mobility`: cada
      ejecución del pipeline de carga sobrescribe (upsert) los valores por
      distrito, en vez de acumular histórico con clave compuesta por fecha.
      Se guarda igualmente `periodo`/`fecha` de forma informativa.
    - `Competitor.geom` usa el tipo `Geography(POINT, 4326)` de PostGIS (no
      `Geometry`): con `geography`, funciones como `ST_DWithin`/`ST_Distance`
      devuelven metros directamente sin necesidad de reproyectar a mano, que
      es exactamente el tipo de consulta que se espera para este dominio
      ("competidores en un radio de 300 m").
    - `Opportunity_Score` NO se modela como columna física en ninguna tabla:
      se calcula en la vista SQL `district_scorecard` (ver migración
      0001_initial_schema) a partir de estas tablas base, para que nunca
      quede desincronizado si cambian los pesos o los datos de origen.
"""

from datetime import date, datetime

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.rag.embeddings import EMBEDDING_DIM as LEGAL_EMBEDDING_DIM

from .base import Base


class District(Base):
    """Distrito de Barcelona (10 en total)."""

    __tablename__ = "districts"

    codi_districte: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    nom_districte: Mapped[str] = mapped_column(String(100), nullable=False)

    neighborhoods: Mapped[list["Neighborhood"]] = relationship(back_populates="district")
    competitors: Mapped[list["Competitor"]] = relationship(back_populates="district")


class Neighborhood(Base):
    """Barrio (Codi_Barri), nivel intermedio entre distrito y sección censal."""

    __tablename__ = "neighborhoods"

    codi_barri: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    nom_barri: Mapped[str] = mapped_column(String(100), nullable=False)
    codi_districte: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("districts.codi_districte"), nullable=False, index=True
    )

    district: Mapped["District"] = relationship(back_populates="neighborhoods")
    competitors: Mapped[list["Competitor"]] = relationship(back_populates="neighborhood")


class Competitor(Base):
    """
    Local de hostelería del censo comercial de Barcelona (competencia).

    id_global es el UUID que ya trae el dataset de origen (columna
    `ID_Global`) — se reutiliza como PK en vez de generar un surrogate key,
    porque ya es único y estable entre ejecuciones del pipeline.
    """

    __tablename__ = "competitors"

    # String(64), no String(36): aunque ID_Global suele ser un UUID
    # estándar (36 caracteres), el dataset real de Open Data BCN contiene
    # al menos un valor de 37 caracteres (detectado en carga real contra
    # datos de producción) — no son UUIDs canónicos estrictos. Se da
    # margen sin quitar la protección contra datos verdaderamente anómalos.
    id_global: Mapped[str] = mapped_column(String(64), primary_key=True)
    nom_local: Mapped[str | None] = mapped_column(String(255))
    nom_activitat: Mapped[str] = mapped_column(String(255), nullable=False)
    nom_grup_activitat: Mapped[str | None] = mapped_column(String(255))
    nom_sector_activitat: Mapped[str | None] = mapped_column(String(255))

    codi_barri: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("neighborhoods.codi_barri"), index=True
    )
    codi_districte: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("districts.codi_districte"), nullable=False, index=True
    )

    # SRID 4326 = WGS84, el sistema de coordenadas estándar de GPS/lat-lon,
    # el mismo en el que vienen Latitud/Longitud en el dataset de origen.
    geom: Mapped[str] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)

    loaded_at: Mapped[datetime] = mapped_column(server_default=func.now())

    district: Mapped["District"] = relationship(back_populates="competitors")
    neighborhood: Mapped["Neighborhood | None"] = relationship(back_populates="competitors")


class DistrictIncome(Base):
    """Renta media por distrito (snapshot único, se sobrescribe en cada carga)."""

    __tablename__ = "district_income"

    codi_districte: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("districts.codi_districte"), primary_key=True
    )
    renta_media: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    periodo: Mapped[int | None] = mapped_column(SmallInteger)  # año del dato INE, informativo
    loaded_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DistrictMobility(Base):
    """Afluencia peatonal diaria por distrito (snapshot único)."""

    __tablename__ = "district_mobility"

    codi_districte: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("districts.codi_districte"), primary_key=True
    )
    daily_foot_traffic: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    fecha: Mapped[date | None] = mapped_column(Date)  # fecha del dato MITMA, informativo
    loaded_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LegalChunk(Base):
    """
    Un chunk de normativa legal (un artículo del PGM de Barcelona, portal
    NUMAMB) con su embedding para búsqueda por similitud (Fase 2).

    numero_articulo como PK: tras aplicar select_current_versions()
    (backend/rag/chunking.py) solo debe quedar una versión vigente por
    artículo, así que es una clave natural válida. Snapshot único (mismo
    criterio que las tablas de la Fase 1): cada ejecución de la ingesta
    reemplaza el contenido en vez de acumular histórico.
    """

    __tablename__ = "legal_chunks"

    numero_articulo: Mapped[str] = mapped_column(String(20), primary_key=True)
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    contenido: Mapped[str] = mapped_column(Text, nullable=False)
    expedient: Mapped[str | None] = mapped_column(String(100))
    versio: Mapped[str] = mapped_column(String(30), nullable=False)
    documento_origen: Mapped[str | None] = mapped_column(String(255))
    embedding: Mapped[list[float]] = mapped_column(Vector(LEGAL_EMBEDDING_DIM), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(server_default=func.now())