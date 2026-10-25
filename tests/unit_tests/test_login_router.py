"""
==============================================================================
UNIT TESTS: LOGIN ROUTER
==============================================================================
File: tests/unit_tests/test_login_router.py

Tests the FastAPI login endpoint (`backend/api/routers/login.py`).
Uses FastAPI `dependency_overrides` to mock `get_session` without needing a
live database.
"""

import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from backend.api.api import app
from backend.api.deps import get_session
from backend.db.models import User


class FakeSession:
    """Mock class simulating a SQLAlchemy Session for User queries and checkpoints."""

    def __init__(self, user_record: User | None = None, thread_ids: list[str] | None = None):
        self._user_record = user_record
        self._thread_ids = thread_ids or []

    def execute(self, statement, params=None):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._user_record
        result.fetchall.return_value = [(tid,) for tid in self._thread_ids]
        return result


class TestLoginEndpoint:
    def test_login_success_with_first_message_as_title(self):
        """Verifies POST /api/login extracts the first message of each thread as its title."""
        fake_user = User(id=uuid.uuid4(), user="alice")
        thread_ids = ["alice:1", "alice:2"]

        mock_checkpointer = MagicMock()

        def fake_get_tuple(config):
            tid = config.get("configurable", {}).get("thread_id")
            cp_tuple = MagicMock()
            if tid == "alice:1":
                cp_tuple.checkpoint = {
                    "channel_values": {
                        "messages": [
                            HumanMessage(content="¿Cuáles son los requisitos para abrir un bar?"),
                            AIMessage(content="Los requisitos son..."),
                        ]
                    }
                }
            elif tid == "alice:2":
                cp_tuple.checkpoint = {
                    "channel_values": {
                        "messages": [
                            HumanMessage(content="Normativa acústica en Eixample"),
                            AIMessage(content="La ordenanza acústica indica..."),
                        ]
                    }
                }
            else:
                cp_tuple = None
            return cp_tuple

        mock_checkpointer.get_tuple.side_effect = fake_get_tuple

        app.dependency_overrides[get_session] = lambda: FakeSession(fake_user, thread_ids)
        client = TestClient(app)

        with patch("backend.api.routers.login.checkpointer", mock_checkpointer):
            response = client.post("/api/login", json={"user": "alice"})
        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["user"] == "alice"
        assert len(data["conversations"]) == 2
        assert data["conversations"][0]["id"] == "alice:1"
        assert data["conversations"][0]["title"] == "¿Cuáles son los requisitos para abrir un bar?"
        assert data["conversations"][1]["id"] == "alice:2"
        assert data["conversations"][1]["title"] == "Normativa acústica en Eixample"

    def test_login_success_no_conversations(self):
        """Verifies POST /api/login returns an empty conversations list when no threads exist."""
        fake_user = User(id=uuid.uuid4(), user="bob")
        app.dependency_overrides[get_session] = lambda: FakeSession(fake_user, thread_ids=[])
        client = TestClient(app)

        response = client.post("/api/login", json={"user": "bob"})
        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["user"] == "bob"
        assert data["conversations"] == []

    def test_login_user_not_found(self):
        """Verifies POST /api/login returns 404 when user is not in users table."""
        app.dependency_overrides[get_session] = lambda: FakeSession(None)
        client = TestClient(app)

        response = client.post("/api/login", json={"user": "unknown_user"})
        app.dependency_overrides.clear()

        assert response.status_code == 404
        data = response.json()
        assert "no encontrado" in data["detail"]

    def test_login_empty_user_validation(self):
        """Verifies empty or whitespace user triggers validation error."""
        fake_user = User(id=uuid.uuid4(), user="alice")
        app.dependency_overrides[get_session] = lambda: FakeSession(fake_user)
        client = TestClient(app)

        response = client.post("/api/login", json={"user": "   "})
        app.dependency_overrides.clear()

        assert response.status_code == 400
