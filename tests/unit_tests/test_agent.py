"""
Tests del agente orquestador (backend/ia/agent.py).

Usa hash_embed (determinista, sin red ni modelo real) y un cliente LLM
programable que distingue la llamada del nodo legal de la de síntesis por
el system prompt recibido -- necesario para validar que el informe final
combina de verdad ambos bloques y no solo repite uno de ellos.
"""

import hashlib

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import text

from backend.db.models import Competitor, District, DistrictIncome, DistrictMobility, LegalChunk
from backend.ia.agent import SYNTHESIS_SYSTEM_PROMPT, generar_informe_viabilidad, zonas_pgm_disponibles


def hash_embed(texts: list[str]) -> list[list[float]]:
    result = []
    for t in texts:
        seed = int(hashlib.sha256(t.encode()).hexdigest(), 16)
        result.append([((seed >> (i % 64)) % 1000) / 1000.0 for i in range(384)])
    return result


class FakeContent:
    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeContent(text)]


class ScriptedLLMClient:
    """
    Devuelve una respuesta distinta según el system prompt recibido, para
    poder distinguir la llamada del nodo legal (normativa_legal) de la del
    nodo de síntesis (sintesis_final) -- con un doble que siempre
    devolviera el mismo texto no se podría comprobar que el informe final
    combina de verdad ambos bloques, y no solo repite uno de ellos.
    """

    def __init__(self, synthesis_response: str, legal_response: str = "[respuesta legal de prueba]"):
        self.synthesis_response = synthesis_response
        self.legal_response = legal_response
        self.messages = self

    def create(self, model, max_tokens, system, messages):
        if system == SYNTHESIS_SYSTEM_PROMPT:
            return FakeResponse(self.synthesis_response)
        return FakeResponse(self.legal_response)


@pytest.fixture
def distrito_ciutat_vella(db_session):
    # codi_districte=999 a propósito: Barcelona solo tiene distritos 1-10
    # (BARCELONA_DISTRICTS en backend/etl/competitors.py), así que este
    # valor nunca puede coincidir con datos reales ya cargados en un
    # entorno de desarrollo con la Fase 1 completada -- evita el riesgo de
    # borrar o pisar datos reales del usuario al limpiar tras el test.
    codi = 999
    db_session.add(District(codi_districte=codi, nom_districte="Ciutat Vella (dato de prueba)"))
    db_session.add(DistrictIncome(codi_districte=codi, renta_media=15000, periodo=2023))
    db_session.add(DistrictMobility(codi_districte=codi, daily_foot_traffic=400000))
    db_session.add(
        Competitor(
            id_global="test-1",
            nom_activitat="Bars",
            nom_grup_activitat="Restaurants, bars i hotels",
            codi_districte=codi,
            geom=WKTElement("POINT(2.17 41.38)", srid=4326),
        )
    )
    db_session.commit()
    yield codi
    db_session.execute(text("DELETE FROM competitors WHERE codi_districte = :codi"), {"codi": codi})
    db_session.execute(text("DELETE FROM district_income WHERE codi_districte = :codi"), {"codi": codi})
    db_session.execute(text("DELETE FROM district_mobility WHERE codi_districte = :codi"), {"codi": codi})
    db_session.execute(text("DELETE FROM districts WHERE codi_districte = :codi"), {"codi": codi})
    db_session.commit()


@pytest.fixture
def articulo_302(db_session):
    contenido = "Comercial: se permite en edificios exclusivos."
    db_session.add(
        LegalChunk(
            numero_articulo="302",
            titulo="Zona de nucli antic",
            contenido=contenido,
            expedient="test/000000",
            versio="consolidat",
            zona_pgm="nucli_antic",
            documento_origen="test.pdf",
            embedding=hash_embed([contenido])[0],
        )
    )
    db_session.commit()


class TestZonasPgmDisponibles:
    def test_returns_only_zones_with_data(self, db_session, articulo_302):
        assert zonas_pgm_disponibles(db_session) == ["nucli_antic"]

    def test_empty_when_no_legal_chunks(self, db_session):
        assert zonas_pgm_disponibles(db_session) == []


class TestGenerarInformeViabilidad:
    def test_regression_parallel_nodes_do_not_crash(self, db_session, distrito_ciutat_vella, articulo_302):
        # Regresión de un bug real: datos_socioeconomicos y normativa_legal
        # se ejecutan en PARALELO (ambos arrancan desde START en el grafo).
        # Compartir una única Session de SQLAlchemy entre nodos que corren
        # a la vez revienta con "This session is provisioning a new
        # connection; concurrent operations are not permitted". Cada nodo
        # paralelo debe usar su propia sesión, derivada del mismo motor.
        client = ScriptedLLMClient(synthesis_response="VERDE\nresumen de prueba")
        informe = generar_informe_viabilidad(
            db_session,
            codi_districte=distrito_ciutat_vella,
            zona_pgm="nucli_antic",
            embed_fn=hash_embed,
            llm_client=client,
        )
        assert informe["semaforo"] == "verde"

    def test_combines_both_blocks_correctly(self, db_session, distrito_ciutat_vella, articulo_302):
        client = ScriptedLLMClient(
            synthesis_response="AMBAR\nresumen de sintesis",
            legal_response="[texto legal distintivo]",
        )
        informe = generar_informe_viabilidad(
            db_session,
            codi_districte=distrito_ciutat_vella,
            zona_pgm="nucli_antic",
            embed_fn=hash_embed,
            llm_client=client,
        )
        assert informe["semaforo"] == "ambar"
        assert informe["resumen"] == "resumen de sintesis"
        assert informe["respuesta_legal"] == "[texto legal distintivo]"
        assert informe["articulos_citados"] == ["302"]
        assert informe["datos_distrito"]["nom_districte"] == "Ciutat Vella (dato de prueba)"

    def test_missing_district_data_does_not_crash(self, db_session, articulo_302):
        client = ScriptedLLMClient(synthesis_response="ROJO\nsin datos de distrito")
        informe = generar_informe_viabilidad(
            db_session,
            codi_districte=9999,  # distrito que no existe, distinto del 999 de la otra fixture
            zona_pgm="nucli_antic",
            embed_fn=hash_embed,
            llm_client=client,
        )
        assert informe["datos_distrito"] == {}
        assert informe["semaforo"] == "rojo"

    def test_falls_back_gracefully_on_unrecognized_semaforo(self, db_session, distrito_ciutat_vella, articulo_302):
        client = ScriptedLLMClient(synthesis_response="Esto no empieza con un semáforo válido.")
        informe = generar_informe_viabilidad(
            db_session,
            codi_districte=distrito_ciutat_vella,
            zona_pgm="nucli_antic",
            embed_fn=hash_embed,
            llm_client=client,
        )
        assert informe["semaforo"] == "ambar"  # fallback neutro, no revienta