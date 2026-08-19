"""
Test del adaptador de Gemini (backend/rag/gemini_adapter.py).

Se simula el cliente de google-genai por debajo (no se llama a la API
real) para validar solo la lógica del adaptador: que expone la misma
interfaz que anthropic.Anthropic() y que traduce correctamente los
parámetros hacia generate_content().
"""

from unittest.mock import MagicMock, patch

from backend.rag.gemini_adapter import GeminiAsAnthropicAdapter


class TestGeminiAsAnthropicAdapter:
    def test_exposes_anthropic_shaped_interface(self):
        with patch("google.genai.Client") as MockClient:
            mock_instance = MockClient.return_value
            mock_response = MagicMock(text="respuesta de prueba")
            mock_response.candidates = []
            mock_instance.models.generate_content.return_value = mock_response

            adapter = GeminiAsAnthropicAdapter(api_key="fake-key")
            response = adapter.messages.create(
                model="gemini-2.5-flash",
                max_tokens=500,
                system="eres un asistente legal",
                messages=[{"role": "user", "content": "¿puedo abrir un bar aquí?"}],
            )

            # Misma forma que la respuesta real de anthropic.Anthropic().messages.create(...)
            assert response.content[0].text == "respuesta de prueba"

    def test_translates_parameters_correctly(self):
        with patch("google.genai.Client") as MockClient:
            mock_instance = MockClient.return_value
            mock_response = MagicMock(text="ok")
            mock_response.candidates = []  # sin candidates, no debe reventar al comprobar finish_reason
            mock_instance.models.generate_content.return_value = mock_response

            adapter = GeminiAsAnthropicAdapter(api_key="fake-key")
            adapter.messages.create(
                model="gemini-2.5-flash",
                max_tokens=777,
                system="instrucción de sistema de prueba",
                messages=[{"role": "user", "content": "contenido del mensaje"}],
            )

            call_kwargs = mock_instance.models.generate_content.call_args.kwargs
            assert call_kwargs["model"] == "gemini-2.5-flash"
            assert call_kwargs["contents"] == "contenido del mensaje"
            assert call_kwargs["config"].system_instruction == "instrucción de sistema de prueba"
            assert call_kwargs["config"].max_output_tokens == 777

    def test_leaves_thinking_config_automatic(self):
        # Corrección tras pruebas reales: desactivar el thinking del todo
        # (thinking_budget=0) evitaba el corte de respuesta, pero causaba
        # una regresión real de calidad (el modelo dejaba de conectar
        # "Eixample" con el artículo técnico correspondiente). Se deja el
        # thinking en automático (sin thinking_config) a propósito; el
        # presupuesto total se sube en su lugar (ver DEFAULT_MAX_TOKENS en
        # query_engine.py).
        with patch("google.genai.Client") as MockClient:
            mock_instance = MockClient.return_value
            mock_response = MagicMock(text="ok")
            mock_response.candidates = []
            mock_instance.models.generate_content.return_value = mock_response

            adapter = GeminiAsAnthropicAdapter(api_key="fake-key")
            adapter.messages.create(
                model="gemini-2.5-flash", max_tokens=2048, system="sistema", messages=[{"role": "user", "content": "x"}]
            )

            call_kwargs = mock_instance.models.generate_content.call_args.kwargs
            assert call_kwargs["config"].thinking_config is None

    def test_regression_warns_but_does_not_crash_on_truncated_response(self, caplog):
        # Regresión: si finish_reason indica que la respuesta se truncó
        # (MAX_TOKENS y similares), debe avisar en el log, no fallar ni
        # devolver la respuesta cortada en silencio sin ninguna señal.
        from google.genai import types

        with patch("google.genai.Client") as MockClient:
            mock_instance = MockClient.return_value
            mock_response = MagicMock(text="respuesta cortada a media f")
            mock_candidate = MagicMock(finish_reason=types.FinishReason.MAX_TOKENS)
            mock_response.candidates = [mock_candidate]
            mock_instance.models.generate_content.return_value = mock_response

            adapter = GeminiAsAnthropicAdapter(api_key="fake-key")
            response = adapter.messages.create(
                model="gemini-2.5-flash", max_tokens=10, system="sistema", messages=[{"role": "user", "content": "x"}]
            )

            assert response.content[0].text == "respuesta cortada a media f"
            assert "incompleta" in caplog.text or "MAX_TOKENS" in caplog.text