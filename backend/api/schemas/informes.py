"""
Esquemas de entrada/salida del endpoint de informes de viabilidad
(backend/api/routers/informes.py).
"""

from pydantic import BaseModel, Field


class InformeRequest(BaseModel):
    codi_districte: int = Field(..., ge=1, le=10, description="Código del distrito de Barcelona (1-10)")
    zona_pgm: str = Field(..., min_length=1, description="Zona urbanística del PGM -- ver GET /api/zonas-pgm")


class DatosDistrito(BaseModel):
    """
    Todos los campos son opcionales a propósito: cuando el distrito
    pedido no tiene datos en district_scorecard, generar_informe_viabilidad()
    devuelve un diccionario vacío en vez de fallar -- este esquema debe
    poder representar ese caso sin reventar la validación.
    """

    codi_districte: int | None = None
    nom_districte: str | None = None
    daily_foot_traffic: float | None = None
    renta_media: float | None = None
    total_competitors: int | None = None
    opportunity_score: float | None = None


class InformeResponse(BaseModel):
    semaforo: str
    resumen: str
    datos_distrito: DatosDistrito
    respuesta_legal: str
    articulos_citados: list[str]


class DistritoOut(BaseModel):
    codi_districte: int
    nom_districte: str


class ZonaPgmOut(BaseModel):
    id: str
    nombre: str