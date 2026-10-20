"""
==============================================================================
UNIT TESTS: ASSISTANT ROUTER (SSE STREAMING)
==============================================================================
File: tests/unit_tests/test_assistant_router.py

Tests the FastAPI assistant endpoint (`backend/api/routers/assistant.py`).
"""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.api import app


class TestAssistantEndpoint:
    @patch("backend.api.routers.assistant.request")
    def test_assistant_stream_success(self, mock_request):
        """Verifies POST /api/assistant streams tokens and finishes with done event."""
        mock_request.return_value = iter([
            {"type": "token", "text": "Horarios: "},
            {"type": "token", "text": "de 06:00 a 02:00."},
            {"type": "done", "text": "Horarios: de 06:00 a 02:00."},
        ])

        client = TestClient(app)
        response = client.post(
            "/api/assistant",
            json={"thread_id": "alice:1", "prompt": "¿cuáles son los horarios?"},
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        lines = [line for line in response.text.split("\n\n") if line.startswith("data: ")]
        events = [json.loads(line[6:]) for line in lines]

        assert events == [
            {"type": "token", "text": "Horarios: "},
            {"type": "token", "text": "de 06:00 a 02:00."},
            {"type": "done", "text": "Horarios: de 06:00 a 02:00."},
        ]
        mock_request.assert_called_once_with("¿cuáles son los horarios?", thread="alice:1", stream=True)

    @patch("backend.api.routers.assistant.request")
    def test_assistant_stream_with_content_alias(self, mock_request):
        """Verifies POST /api/assistant accepts 'content' as an alias for 'prompt'."""
        mock_request.return_value = iter([
            {"type": "token", "text": "OK"},
            {"type": "done", "text": "OK"},
        ])

        client = TestClient(app)
        response = client.post(
            "/api/assistant",
            json={"thread_id": "bob:2", "content": "consulta sobre licencias"},
        )

        assert response.status_code == 200
        mock_request.assert_called_once_with("consulta sobre licencias", thread="bob:2", stream=True)

    def test_assistant_validation_error_empty_message(self):
        """Returns 422 if neither prompt nor content is provided or both are empty."""
        client = TestClient(app)
        res1 = client.post("/api/assistant", json={"thread_id": "alice:1", "prompt": "   "})
        assert res1.status_code == 422

        res2 = client.post("/api/assistant", json={"thread_id": "alice:1"})
        assert res2.status_code == 422

    def test_assistant_validation_error_missing_thread_id(self):
        """Returns 422 if thread_id is missing or empty."""
        client = TestClient(app)
        res = client.post("/api/assistant", json={"prompt": "hola", "thread_id": ""})
        assert res.status_code == 422

    @patch("backend.api.routers.assistant.request")
    def test_assistant_stream_exception_handling(self, mock_request):
        """Yields an error event when an unexpected exception occurs during stream iteration."""
        def broken_generator():
            yield {"type": "token", "text": "Part 1"}
            raise RuntimeError("Bedrock connection error")

        mock_request.return_value = broken_generator()

        client = TestClient(app)
        response = client.post(
            "/api/assistant",
            json={"thread_id": "alice:1", "prompt": "hola"},
        )

        assert response.status_code == 200
        lines = [line for line in response.text.split("\n\n") if line.startswith("data: ")]
        events = [json.loads(line[6:]) for line in lines]
        assert events[0] == {"type": "token", "text": "Part 1"}
        assert events[1]["type"] == "error"
