"""
Endpoints del agente de viabilidad, para que el frontend pueda pedir
distritos/zonas disponibles y generar el informe completo.

Diseño:
    - Endpoints síncronos (`def`, no `async def`) a propósito: todo el
      pipeline por debajo (SQLAlchemy, sentence-transformers, el cliente
      de Gemini) es síncrono. FastAPI ejecuta los endpoints síncronos en
      un threadpool automáticamente, así que esto no bloquea el bucle de
      eventos -- reescribir todo el pipeline a async sería un cambio de
      arquitectura mucho mayor, sin necesidad real para el volumen de
      peticiones de este MVP.
    - Errores del LLM o de la base de datos se capturan y se traducen a
      un 502 con un mensaje claro, en vez de dejar que FastAPI devuelva
      un stack trace crudo al frontend.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.deps import get_session
from backend.api.schemas.informes import DistritoOut, InformeRequest, InformeResponse, ZonaPgmOut
from backend.ia.agent import ZONA_PGM_NOMBRES, generar_informe_viabilidad, zonas_pgm_disponibles

logger = logging.getLogger("geoyield_api")

router = APIRouter(prefix="/api", tags=["informes"])


@router.get("/distritos", response_model=list[DistritoOut])
def listar_distritos(db: Session = Depends(get_session)):
    rows = db.execute(text("SELECT codi_districte, nom_districte FROM districts ORDER BY codi_districte")).all()
    return [DistritoOut(codi_districte=r.codi_districte, nom_districte=r.nom_districte) for r in rows]


@router.get("/zonas-pgm", response_model=list[ZonaPgmOut])
def listar_zonas_pgm(db: Session = Depends(get_session)):
    """
    Solo devuelve zonas que de verdad tienen normativa cargada (ver
    zonas_pgm_disponibles) -- el desplegable del frontend nunca debe
    ofrecer una opción que vaya a devolver una recuperación vacía.
    """
    zonas = zonas_pgm_disponibles(db)
    return [ZonaPgmOut(id=z, nombre=ZONA_PGM_NOMBRES.get(z, z)) for z in zonas]


@router.post("/informes", response_model=InformeResponse)
def crear_informe(payload: InformeRequest, db: Session = Depends(get_session)):
    try:
        informe = generar_informe_viabilidad(
            db, codi_districte=payload.codi_districte, zona_pgm=payload.zona_pgm
        )
    except Exception:
        logger.exception(
            f"Error generando el informe (distrito={payload.codi_districte}, zona={payload.zona_pgm})"
        )
        raise HTTPException(
            status_code=502,
            detail="No se pudo generar el informe (fallo al contactar el modelo de IA o la base de datos). Inténtalo de nuevo en unos segundos.",
        )
    return informe