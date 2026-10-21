"""
==============================================================================
UNIT TESTS: SAFE THREAD IDS AND CHAT HISTORY FILES
==============================================================================
File: tests/unit_tests/test_chat_history.py

No database and no LLM needed. Files are written in temporary folders.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from backend.api.api import app
from backend.api.routers import assistant as assistant_router
from backend.api.schemas.assistant import AssistantRequest
from backend.ia import chat
from backend.ia.chat_history import append_history, is_valid_thread_id


class TestThreadIdValidation:
    @pytest.mark.parametrize(
        "thread_id",
        ["alice:1", "claudiberenguer:5", "test_thread_42", "Ana López:2", "a.b@example.com:3"],
    )
    def test_normal_thread_ids_are_accepted(self, thread_id):
        assert is_valid_thread_id(thread_id)

    @pytest.mark.parametrize(
        "thread_id",
        [
            "../requirements",
            "..",
            "a/b:1",
            "a\\b:1",
            "",
            "x" * 151,
            ".hidden:1",
            "a..b:1",
            "a:1\n",
            "a\x00b:1",
            " alice:1",
            None,
        ],
    )
    def test_unsafe_thread_ids_are_rejected(self, thread_id):
        assert not is_valid_thread_id(thread_id)


class TestAppendHistory:
    def test_it_creates_the_folder_and_saves_utf8_turns_separated_by_a_blank_line(self, tmp_path):
        folder = tmp_path / "chat_history"

        assert append_history("alice:1", "¿Horarios?", "De 06:00 a 02:00", history_dir=folder)
        assert append_history("alice:1", "¿Y terrazas?", "Depende", history_dir=folder)

        text = (folder / "alice:1.txt").read_text(encoding="utf-8")
        assert "USUARIO:\n¿Horarios?\n\nASISTENTE:\nDe 06:00 a 02:00\n\nUSUARIO:\n¿Y terrazas?" in text

    def test_an_unsafe_thread_id_writes_nothing_and_does_not_raise(self, tmp_path):
        folder = tmp_path / "chat_history"

        assert append_history("../outside:1", "pregunta", "respuesta", history_dir=folder) is False

        assert not (tmp_path / "outside:1.txt").exists()
        assert not folder.exists()

    def test_a_folder_that_cannot_be_created_returns_false_and_does_not_raise(self, tmp_path):
        not_a_folder = tmp_path / "file"
        not_a_folder.write_text("x")

        assert append_history("alice:1", "pregunta", "respuesta", history_dir=not_a_folder / "chat_history") is False


class TestAssistantSchema:
    def test_the_schema_rejects_a_path_as_thread_id(self):
        with pytest.raises(ValidationError):
            AssistantRequest(thread_id="../requirements", prompt="hola")

    def test_the_endpoint_answers_422_without_running_the_assistant(self, monkeypatch):
        def must_not_run(*args, **kwargs):
            pytest.fail("the assistant must not run with an unsafe thread id")

        monkeypatch.setattr(assistant_router, "request", must_not_run)

        response = TestClient(app).post("/api/assistant", json={"thread_id": "../requirements", "prompt": "hola"})

        assert response.status_code == 422


class TestChatRequestHistory:
    def test_the_history_is_saved_before_the_done_event(self, tmp_path, monkeypatch):
        monkeypatch.setattr(chat, "REPO_ROOT", tmp_path)
        stream = [(AIMessage(content="Hola"), {"langgraph_node": "assistant"})]

        with patch.object(chat.react_graph, "stream", return_value=stream):
            events = chat.request("pregunta", thread="alice:1")
            for event in events:
                if event["type"] == "done":
                    saved = (tmp_path / "chat_history" / "alice:1.txt").read_text(encoding="utf-8")
                    assert "USUARIO:\npregunta" in saved
                    assert "ASISTENTE:\nHola" in saved
                    break
            else:
                pytest.fail("the stream ended without a done event")
            events.close()

    def test_a_history_write_failure_does_not_add_an_error_after_done(self, tmp_path, monkeypatch):
        not_a_folder = tmp_path / "file"
        not_a_folder.write_text("x")
        monkeypatch.setattr(chat, "REPO_ROOT", not_a_folder)
        stream = [(AIMessage(content="Hola"), {"langgraph_node": "assistant"})]

        with patch.object(chat.react_graph, "stream", return_value=stream):
            events = list(chat.request("pregunta", thread="alice:1"))

        assert [e["type"] for e in events] == ["token", "done"]
