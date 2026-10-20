"""
==============================================================================
RAG PIPELINE: LLM ADAPTER PATTERN (GEMINI AS ANTHROPIC)
==============================================================================
File: backend/rag/gemini_adapter.py

This module implements the Gang of Four (GoF) 'Adapter' Design Pattern.
The core RAG engine was originally built expecting the Anthropic (Claude) API
interface. To switch to Google Gemini (to utilize the free tier during the MVP)
without rewriting the core engine, this class wraps the Gemini SDK so it
perfectly mimics the Anthropic SDK signatures.

Metrics: every call is recorded as an 'llm' span (tokens, cost, and time to
first token for streams). If no metrics collector is active, nothing changes.
"""

import os
import time

from backend.observability import get_logger
from backend.observability.metrics import add_usage, span

logger = get_logger("rag.gemini_adapter")

# Resilience Settings: Cloud LLMs often throw transient 5xx errors due to quota
# or server load. We implement a simple retry mechanism before failing.
MAX_REINTENTOS = 2
ESPERA_ENTRE_REINTENTOS_SEGUNDOS = 2


def _token_count(usage, field: str) -> int:
    """Read one token counter from Gemini's usage object. Anything that is not a real int counts as 0."""
    value = getattr(usage, field, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _record_usage(model: str, usage, current_span) -> None:
    """Send the token counts to the span. Metrics must never break an answer, so this never raises."""
    if usage is None or current_span is None:
        return
    try:
        add_usage(
            model,
            _token_count(usage, "prompt_token_count"),
            _token_count(usage, "candidates_token_count"),
            _token_count(usage, "thoughts_token_count"),
            target=current_span,
        )
    except Exception:
        logger.warning("Could not record Gemini token usage", exc_info=True)


# ------------------------------------------------------------------------------
# MOCK ANTHROPIC CLASSES
# ------------------------------------------------------------------------------
# These classes mock the exact data structure returned by the official
# Anthropic Python SDK: response.content[0].text
class _FakeContentBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeAnthropicResponse:
    def __init__(self, text: str):
        self.content = [_FakeContentBlock(text)]


class GeminiAsAnthropicAdapter:
    def __init__(self, api_key: str | None = None):
        # Lazy import to prevent failing if the user hasn't installed the SDK
        from google import genai

        self._client = genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))
        # Mimic Anthropic's `.messages` attribute
        self.messages = self

    def create(self, model: str, max_tokens: int, system: str, messages: list[dict]) -> _FakeAnthropicResponse:
        """
        Mimics `anthropic.Anthropic().messages.create(...)`.
        Includes robustness logic (retries) and token truncation warnings.
        """
        from google.genai import errors as genai_errors
        from google.genai import types

        # Translate Anthropic format to Gemini format
        user_content = messages[0]["content"]
        config = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens)

        # One span for the whole call, retries included. We store only the SIZE of the
        # prompt, never its text (it can contain personal data).
        with span("llm", "llm_call", model=model, input_summary=f"{len(str(user_content))} chars") as current:
            intentos_totales = MAX_REINTENTOS + 1
            for intento in range(1, intentos_totales + 1):
                try:
                    response = self._client.models.generate_content(
                        model=model, contents=user_content, config=config
                    )
                    break
                except genai_errors.ServerError as exc:
                    if intento == intentos_totales:
                        raise
                    logger.warning(
                        f"Gemini devolvió un error de servidor (intento {intento}/{intentos_totales}): {exc}. "
                        f"Reintentando en {ESPERA_ENTRE_REINTENTOS_SEGUNDOS}s..."
                    )
                    time.sleep(ESPERA_ENTRE_REINTENTOS_SEGUNDOS)

            _record_usage(model, getattr(response, "usage_metadata", None), current)
            if current is not None:
                current.output_summary = f"{len(response.text or '')} chars"

        # Truncation Detection: If the LLM stopped because it hit `max_tokens`
        # (FinishReason.MAX_TOKENS) instead of naturally finishing (FinishReason.STOP),
        # we log a warning so the developer knows the context window is too small.
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        if finish_reason is not None and finish_reason != types.FinishReason.STOP:
            logger.warning(
                f"Respuesta de Gemini incompleta (finish_reason={finish_reason}); "
                "considera subir max_tokens en generate_answer()."
            )

        # Return the response wrapped in our fake Anthropic objects
        return _FakeAnthropicResponse(response.text)

    def create_stream(self, model: str, max_tokens: int, system: str, messages: list[dict]):
        """
        Streaming generation (Server-Sent Events).

        Design Note: We intentionally omit the Retry logic here.
        If a stream fails halfway, retrying would restart the generation,
        sending duplicated or conflicting tokens to the frontend client.

        Metrics: Gemini repeats a running token total in the chunks, so we keep the
        last one and record it in `finally` (also when the client disconnects early).
        """
        from google.genai import types

        user_content = messages[0]["content"]
        config = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens)

        with span("llm", "llm_call_stream", model=model, input_summary=f"{len(str(user_content))} chars") as current:
            started = time.perf_counter()
            last_usage = None
            try:
                for chunk in self._client.models.generate_content_stream(
                    model=model, contents=user_content, config=config
                ):
                    if getattr(chunk, "usage_metadata", None) is not None:
                        last_usage = chunk.usage_metadata
                    if chunk.text:
                        if current is not None and current.ttft_ms is None:
                            current.ttft_ms = round((time.perf_counter() - started) * 1000, 2)
                        yield chunk.text
            finally:
                _record_usage(model, last_usage, current)
