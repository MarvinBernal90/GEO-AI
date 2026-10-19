"""
==============================================================================
UNIT TESTS: HISTORY ROUTER
==============================================================================
File: tests/unit_tests/test_history_router.py

Tests the FastAPI history endpoint (/api/gethistory).
"""

from fastapi.testclient import TestClient

from backend.api.api import app
from backend.api.schemas.history import HistoryRequest, HistoryResponse


class TestHistoryEndpoint:
    def test_gethistory_success(self):
        """Verifies GET /api/gethistory returns the chat history file content for a valid thread_id."""
        with TestClient(app) as client:
            response = client.get("/api/gethistory", params={"thread_id": "claudiberenguer:4"})

        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "claudiberenguer:4"
        assert data["filename"] == "claudiberenguer:4.txt"
        assert "cuáles son los horarios de apertura" in data["content"]

    def test_gethistory_claudiberenguer_5(self):
        """Verifies GET /api/gethistory returns the full history for claudiberenguer:5."""
        with TestClient(app) as client:
            response = client.get("/api/gethistory", params={"thread_id": "claudiberenguer:5"})

        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "claudiberenguer:5"
        assert data["filename"] == "claudiberenguer:5.txt"
        assert "USER:" in data["content"]
        assert len(data["content"]) > 100

    def test_gethistory_by_path(self):
        """Verifies GET /api/gethistory/{thread_id} works identically to query param."""
        with TestClient(app) as client:
            response = client.get("/api/gethistory/claudiberenguer:4")

        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "claudiberenguer:4"
        assert data["filename"] == "claudiberenguer:4.txt"

    def test_gethistory_post(self):
        """Verifies POST /api/gethistory works with HistoryRequest body."""
        with TestClient(app) as client:
            response = client.post("/api/gethistory", json={"thread_id": "claudiberenguer:4"})

        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "claudiberenguer:4"
        assert data["filename"] == "claudiberenguer:4.txt"

    def test_gethistory_missing_thread_id_returns_422(self):
        """Verifies missing thread_id returns 422 Unprocessable Entity."""
        with TestClient(app) as client:
            response = client.get("/api/gethistory")

        assert response.status_code == 422

    def test_gethistory_empty_thread_id_returns_422(self):
        """Verifies empty or whitespace thread_id returns 422."""
        with TestClient(app) as client:
            response = client.get("/api/gethistory", params={"thread_id": "   "})

        assert response.status_code == 422

    def test_gethistory_not_found_returns_404(self):
        """Verifies non-existent thread_id returns 404 Not Found."""
        with TestClient(app) as client:
            response = client.get("/api/gethistory", params={"thread_id": "nonexistent_thread_xyz_123"})

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_gethistory_path_traversal_returns_400(self):
        """Verifies directory traversal attempt is rejected with 400 Bad Request."""
        with TestClient(app) as client:
            response = client.get("/api/gethistory", params={"thread_id": "../../etc/passwd"})

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_history_schemas(self):
        """Verifies HistoryRequest and HistoryResponse Pydantic models."""
        req = HistoryRequest(thread_id="test_thread")
        assert req.thread_id == "test_thread"

        res = HistoryResponse(thread_id="test_thread", content="hello", filename="test_thread.txt")
        assert res.thread_id == "test_thread"
        assert res.content == "hello"
        assert res.filename == "test_thread.txt"
