from pydantic import BaseModel


class CentroOut(BaseModel):
    lat: float
    lng: float


class CompetidorOut(BaseModel):
    id_global: str
    nom_activitat: str
    lat: float
    lng: float


class CompetidoresResponse(BaseModel):
    centro: CentroOut | None
    total: int
    competidores: list[CompetidorOut]