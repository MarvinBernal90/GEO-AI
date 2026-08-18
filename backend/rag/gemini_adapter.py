"""
Adaptador de Gemini para usar con backend.rag.query_engine.generate_answer().

Por qué existe: generate_answer() acepta un `llm_client` inyectable con la
forma de anthropic.Anthropic() (`.messages.create(...)` devolviendo un
objeto con `.content[0].text`). Este adaptador implementa esa misma forma
por encima de la API de Gemini (google-genai), para poder probar el motor
RAG con una clave gratuita mientras se financia la cuenta de Anthropic —
sin tocar query_engine.py ni duplicar la lógica de recuperación/prompt.

Es un medio temporal de prueba, no la decisión final de proveedor (que
sigue siendo Claude, según lo ya acordado). Cuando haya presupuesto para
Anthropic, basta con no pasar `llm_client` a generate_answer() y usará el
cliente real de Claude por defecto.
"""

import logging
import os

logger = logging.getLogger("geoyield_rag")


class _FakeContentBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeAnthropicResponse:
    def __init__(self, text: str):
        self.content = [_FakeContentBlock(text)]


class GeminiAsAnthropicAdapter:
    """
    Envuelve google-genai para que se comporte, de cara a generate_answer(),
    igual que anthropic.Anthropic().

    Uso:
        from backend.rag.gemini_adapter import GeminiAsAnthropicAdapter
        from backend.rag.query_engine import generate_answer

        result = generate_answer(
            session, pregunta,
            llm_client=GeminiAsAnthropicAdapter(),
            model="gemini-2.5-flash",  # el default de query_engine es de Claude, hay que sobrescribirlo
        )
    """

    def __init__(self, api_key: str | None = None):
        from google import genai

        self._client = genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))
        self.messages = self  # para que `llm_client.messages.create(...)` funcione igual que con Anthropic

    def create(self, model: str, max_tokens: int, system: str, messages: list[dict]) -> _FakeAnthropicResponse:
        from google.genai import types

        # generate_answer() solo manda un único mensaje de usuario (sin
        # histórico multi-turno), así que basta con tomar el content del
        # primer mensaje.
        user_content = messages[0]["content"]

        response = self._client.models.generate_content(
            model=model,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )

        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        if finish_reason is not None and finish_reason != types.FinishReason.STOP:
            logger.warning(
                f"Respuesta de Gemini incompleta (finish_reason={finish_reason}); "
                "considera subir max_tokens en generate_answer()."
            )

        return _FakeAnthropicResponse(response.text)