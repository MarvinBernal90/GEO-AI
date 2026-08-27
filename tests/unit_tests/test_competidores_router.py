"""
Tests del router de competidores (backend/api/routers/competidores.py).

Usa dependency_overrides para sustituir get_session -- sin BD real.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.api import app
from backend.api.deps import get_session


class FakeSessionConDatos:
    """Simula las dos consultas del endpoint: centroide+total, y el listado."""

    def __init__(self, centro_row, filas):
        self._centro_row = centro_row
        self._filas = filas

    def execute(self, statement, params=None):
        result = MagicMock()
        sql = str(statement)
        if "AVG(" in sql:
            result.mappings.return_value.first.return_value = self._centro_row
        else:
            result.mappings.return_value.all.return_value = self._filas
        return result


class TestListarCompetidores:
    def test_returns_centro_and_competidores(self):
        centro_row = {"lat": 41.38, "lng": 2.17, "total": 2}
        filas = [
            {"id_global": "a1", "nom_activitat": "Bar", "lat": 41.379, "lng": 2.171},
            {"id_global": "a2", "nom_activitat": "Restaurant", "lat": 41.381, "lng": 2.169},
        ]
        app.dependency_overrides[get_session] = lambda: FakeSessionConDatos(centro_row, filas)
        client = TestClient(app)
        response = client.get("/api/competidores", params={"codi_districte": 1})
        app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["centro"] == {"lat": 41.38, "lng": 2.17}
        assert len(body["competidores"]) == 2

    def test_regression_empty_district_returns_null_centro_not_error(self):
        # Regresión: un distrito sin competidores no debe reventar con un
        # AVG(NULL) mal manejado -- debe devolver centro=None y lista vacía.
        centro_row = {"lat": None, "lng": None, "total": 0}
        app.dependency_overrides[get_session] = lambda: FakeSessionConDatos(centro_row, [])
        client = TestClient(app)
        response = client.get("/api/competidores", params={"codi_districte": 5})
        app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["centro"] is None
        assert body["total"] == 0
        assert body["competidores"] == []

    def test_invalid_codi_districte_returns_422(self):
        app.dependency_overrides[get_session] = lambda: FakeSessionConDatos({"lat": None, "lng": None, "total": 0}, [])
        client = TestClient(app)
        response = client.get("/api/competidores", params={"codi_districte": 99})
        app.dependency_overrides.clear()
        assert response.status_code == 422