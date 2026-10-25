"""
==============================================================================
UNIT TESTS: AMAZON BEDROCK LLM ADAPTER
==============================================================================
File: tests/unit_tests/test_bedrock_adapter.py

Tests the BedrockAsAnthropicAdapter class and factory function, verifying
proper message formatting, inferenceConfig construction, streaming deltas,
and fallback logic using mock Boto3 clients.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.rag.bedrock_adapter import BedrockAsAnthropicAdapter, get_llm_adapter


class TestBedrockAsAnthropicAdapter:
    def test_create_successful_invocation(self):
        """Verifies converse parameters formatting and output extraction."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "El Pla General Metropolità regula..."}],
                }
            },
            "stopReason": "end_turn",
        }

        adapter = BedrockAsAnthropicAdapter(region_name="eu-central-1", client=mock_client)
        response = adapter.create(
            model="amazon.nova-lite-v1:0",
            max_tokens=1024,
            system="Eres un asistente legal.",
            messages=[{"role": "user", "content": "¿Puedo abrir un bar?"}],
        )

        assert response.content[0].text == "El Pla General Metropolità regula..."

        mock_client.converse.assert_called_once_with(
            modelId="amazon.nova-lite-v1:0",
            system=[{"text": "Eres un asistente legal."}],
            messages=[{"role": "user", "content": [{"text": "¿Puedo abrir un bar?"}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.7},
        )

    def test_create_handles_structured_content_list(self):
        """Verifies handling when messages contain content as a list of dicts."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Respuesta correcta"}],
                }
            },
            "stopReason": "end_turn",
        }

        adapter = BedrockAsAnthropicAdapter(client=mock_client)
        response = adapter.create(
            model="amazon.nova-lite-v1:0",
            max_tokens=500,
            system="",
            messages=[{"role": "user", "content": [{"text": "Hola mundo"}]}],
        )

        assert response.content[0].text == "Respuesta correcta"
        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["messages"][0]["content"] == [{"text": "Hola mundo"}]

    def test_create_logs_warning_on_max_tokens_truncation(self, caplog):
        """Verifies truncation warning when stopReason is max_tokens."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Texto incompleto..."}],
                }
            },
            "stopReason": "max_tokens",
        }

        adapter = BedrockAsAnthropicAdapter(client=mock_client)
        adapter.create(
            model="amazon.nova-lite-v1:0",
            max_tokens=100,
            system="Prompt",
            messages=[{"role": "user", "content": "Pregunta"}],
        )

        assert any("reached maxTokens" in record.message for record in caplog.records)

    def test_create_stream_yields_deltas(self):
        """Verifies create_stream yields text deltas in correct order."""
        mock_client = MagicMock()
        mock_client.converse_stream.return_value = {
            "stream": [
                {"messageStart": {"role": "assistant"}},
                {"contentBlockDelta": {"delta": {"text": "Hola"}}},
                {"contentBlockDelta": {"delta": {"text": " "}}},
                {"contentBlockDelta": {"delta": {"text": "Barcelona"}}},
                {"messageStop": {"stopReason": "end_turn"}},
            ]
        }

        adapter = BedrockAsAnthropicAdapter(client=mock_client)
        chunks = list(
            adapter.create_stream(
                model="amazon.nova-lite-v1:0",
                max_tokens=1024,
                system="Instrucción",
                messages=[{"role": "user", "content": "Saludos"}],
            )
        )

        assert chunks == ["Hola", " ", "Barcelona"]
        mock_client.converse_stream.assert_called_once_with(
            modelId="amazon.nova-lite-v1:0",
            system=[{"text": "Instrucción"}],
            messages=[{"role": "user", "content": [{"text": "Saludos"}]}],
            inferenceConfig={"maxTokens": 1024},
        )

    def test_raises_when_client_uninitialized(self):
        """Verifies RuntimeError when boto3 client is not available."""
        adapter = BedrockAsAnthropicAdapter(client=None)
        adapter._client = None
        with pytest.raises(RuntimeError, match="Bedrock client is not initialized"):
            adapter.create("model", 100, "", [{"role": "user", "content": "hi"}])


class TestGetLLMAdapterFactory:
    def test_returns_injected_client_if_provided(self):
        custom_client = object()
        assert get_llm_adapter(custom_client) is custom_client

    def test_returns_bedrock_adapter_by_default(self):
        adapter = get_llm_adapter()
        assert isinstance(adapter, BedrockAsAnthropicAdapter)

    def test_returns_gemini_adapter_when_configured(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        with patch("google.genai.Client"):
            from backend.rag.gemini_adapter import GeminiAsAnthropicAdapter

            adapter = get_llm_adapter()
            assert isinstance(adapter, GeminiAsAnthropicAdapter)


class TestLlmInvokeLogEvent:
    """Every model call must leave one structured `llm.invoke` line for CloudWatch."""

    @staticmethod
    def _events(caplog):
        return [r for r in caplog.records if getattr(r, "event", None) == "llm.invoke"]

    def test_create_logs_tokens_and_outcome(self, caplog):
        client = MagicMock()
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 12, "outputTokens": 3},
        }
        adapter = BedrockAsAnthropicAdapter(region_name="eu-central-1", client=client)

        with caplog.at_level("INFO", logger="geoyield.rag.bedrock_adapter"):
            adapter.create(model="m", max_tokens=10, system="s", messages=[{"role": "user", "content": "hola"}])

        (record,) = self._events(caplog)
        assert record.context["outcome"] == "ok"
        assert record.context["input_tokens"] == 12
        assert record.context["output_tokens"] == 3
        assert "hola" not in record.getMessage(), "the prompt text must never be logged"

    def test_create_logs_an_error_when_bedrock_fails(self, caplog):
        client = MagicMock()
        client.converse.side_effect = RuntimeError("throttled")
        adapter = BedrockAsAnthropicAdapter(region_name="eu-central-1", client=client)

        with caplog.at_level("INFO", logger="geoyield.rag.bedrock_adapter"):
            with pytest.raises(RuntimeError):
                adapter.create(model="m", max_tokens=10, system="s", messages=[{"role": "user", "content": "x"}])

        (record,) = self._events(caplog)
        assert record.levelname == "ERROR"
        assert record.context["outcome"] == "error"

    def test_stream_logs_one_event_when_the_client_disconnects(self, caplog):
        client = MagicMock()
        client.converse_stream.return_value = {
            "stream": [{"contentBlockDelta": {"delta": {"text": "a"}}}, {"contentBlockDelta": {"delta": {"text": "b"}}}]
        }
        adapter = BedrockAsAnthropicAdapter(region_name="eu-central-1", client=client)

        with caplog.at_level("INFO", logger="geoyield.rag.bedrock_adapter"):
            stream = adapter.create_stream(
                model="m", max_tokens=10, system="s", messages=[{"role": "user", "content": "x"}]
            )
            next(stream)
            stream.close()

        (record,) = self._events(caplog)
        assert record.context["outcome"] == "cancelled"
