"""
==============================================================================
RAG PIPELINE: LLM ADAPTER PATTERN (AMAZON BEDROCK CONVERSE API)
==============================================================================
File: backend/rag/bedrock_adapter.py

This module implements the Adapter Pattern for Amazon Bedrock using the
official Converse and ConverseStream APIs (bedrock-runtime).
It exposes the standard Anthropic-compatible interface (.messages.create and
.messages.create_stream) so the rest of the application remains fully decoupled
from the underlying AI provider.

Default AWS Foundation Model:
- Amazon Nova Lite (amazon.nova-lite-v1:0)

Metrics: every call is recorded as an 'llm' span (tokens, cost, and time to
first token for streams), with the same names as the Gemini adapter so both
providers can be compared. If no metrics collector is active, nothing changes.
"""

import os
import time
from collections.abc import Generator
from typing import Any

from backend.observability import get_logger, log_event
from backend.observability.metrics import add_usage, span

logger = get_logger("rag.bedrock_adapter")

# Resilience Settings
DEFAULT_AWS_REGION = "eu-central-1"
DEFAULT_BEDROCK_MODEL = "amazon.nova-lite-v1:0"


def _usage_count(usage: Any, field: str) -> int:
    """Read one token counter from Bedrock's usage dict. Anything that is not a real int counts as 0."""
    value = usage.get(field) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _record_usage(model: str, usage: Any, current_span: Any) -> None:
    """Send the token counts to the span. Metrics must never break an answer, so this never raises."""
    if usage is None or current_span is None:
        return
    try:
        add_usage(
            model,
            _usage_count(usage, "inputTokens"),
            _usage_count(usage, "outputTokens"),
            0,
            target=current_span,
        )
    except Exception:
        logger.warning("Could not record Bedrock token usage", exc_info=True)


def _log_llm_call(
    model: str, started: float, usage: Any, *, stream: bool, outcome: str, stop_reason: str | None = None
) -> None:
    """One structured line per model call, so CloudWatch can chart latency, tokens and failures. Never raises."""
    try:
        log_event(
            logger,
            "ERROR" if outcome == "error" else "INFO",
            f"Bedrock {'stream' if stream else 'converse'} {outcome}",
            event="llm.invoke",
            duration_ms=(time.perf_counter() - started) * 1000,
            model=model,
            stream=stream,
            outcome=outcome,
            stop_reason=stop_reason,
            input_tokens=_usage_count(usage, "inputTokens"),
            output_tokens=_usage_count(usage, "outputTokens"),
        )
    except Exception:
        pass


def _prompt_chars(bedrock_messages: list[dict[str, Any]]) -> int:
    """Size of the prompt in characters. We keep only the size, never the text (it can contain personal data)."""
    return sum(len(block.get("text", "")) for msg in bedrock_messages for block in msg.get("content", []))


# ------------------------------------------------------------------------------
# MOCK ANTHROPIC RESPONSE CLASSES
# ------------------------------------------------------------------------------
class _FakeContentBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeAnthropicResponse:
    def __init__(self, text: str):
        self.content = [_FakeContentBlock(text)]


class BedrockAsAnthropicAdapter:
    """
    Adapter Pattern for Amazon Bedrock Converse API.
    Wraps the boto3 bedrock-runtime client to expose the standard
    `.messages.create(...)` and `.messages.create_stream(...)` interfaces.
    """

    def __init__(self, region_name: str | None = None, client: Any = None):
        self.region = region_name or os.getenv("AWS_REGION", DEFAULT_AWS_REGION)
        if client is not None:
            self._client = client
        else:
            self._client = self._init_client(self.region)
        self.messages = self

    @staticmethod
    def _init_client(region: str) -> Any:
        try:
            import boto3
            from botocore.config import Config

            return boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
            )
        except Exception as exc:
            logger.warning(f"Could not initialize Boto3 bedrock-runtime client: {exc}")
            return None

    def create(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
    ) -> _FakeAnthropicResponse:
        """
        Executes a non-streaming model invocation via Bedrock's Converse API.
        Translates input parameters into Bedrock's format and returns an
        Anthropic-compatible response object.
        """
        if self._client is None:
            raise RuntimeError(
                "Bedrock client is not initialized. Ensure 'boto3' is installed and AWS credentials are configured."
            )

        # 1. System instruction formatting
        system_param = [{"text": system}] if system else []

        # 2. Messages translation
        bedrock_messages = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                text_content = content
            elif isinstance(content, list) and content and isinstance(content[0], dict) and "text" in content[0]:
                text_content = content[0]["text"]
            else:
                text_content = str(content)

            bedrock_messages.append(
                {
                    "role": msg.get("role", "user"),
                    "content": [{"text": text_content}],
                }
            )

        # 3. Explicit inferenceConfig (critical: avoids silent 64K quota exhaustion)
        inference_config = {
            "maxTokens": max_tokens,
            "temperature": temperature,
        }

        started = time.perf_counter()
        with span("llm", "llm_call", model=model, input_summary=f"{_prompt_chars(bedrock_messages)} chars") as current:
            try:
                response = self._client.converse(
                    modelId=model,
                    system=system_param,
                    messages=bedrock_messages,
                    inferenceConfig=inference_config,
                )
            except Exception:
                _log_llm_call(model, started, None, stream=False, outcome="error")
                raise

            output_message = response.get("output", {}).get("message", {})
            content_blocks = output_message.get("content", [])
            text_out = "".join(b.get("text", "") for b in content_blocks if "text" in b)

            _record_usage(model, response.get("usage"), current)
            if current is not None:
                current.output_summary = f"{len(text_out)} chars"

        stop_reason = response.get("stopReason")
        _log_llm_call(model, started, response.get("usage"), stream=False, outcome="ok", stop_reason=stop_reason)
        if stop_reason == "max_tokens":
            logger.warning(f"Bedrock generation reached maxTokens ({max_tokens}). Response may be truncated.")

        return _FakeAnthropicResponse(text_out)

    def create_stream(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
    ) -> Generator[str, None, None]:
        """
        Executes a streaming invocation via Bedrock's ConverseStream API.
        Yields raw text delta tokens as they are produced by the foundation model.

        Metrics: Bedrock sends the token usage in a final 'metadata' event. We keep it
        and record it in `finally`, so it is also saved when the client disconnects early.
        """
        if self._client is None:
            raise RuntimeError(
                "Bedrock client is not initialized. Ensure 'boto3' is installed and AWS credentials are configured."
            )

        system_param = [{"text": system}] if system else []

        bedrock_messages = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                text_content = content
            elif isinstance(content, list) and content and isinstance(content[0], dict) and "text" in content[0]:
                text_content = content[0]["text"]
            else:
                text_content = str(content)

            bedrock_messages.append(
                {
                    "role": msg.get("role", "user"),
                    "content": [{"text": text_content}],
                }
            )

        inference_config = {
            "maxTokens": max_tokens,
        }

        with span(
            "llm", "llm_call_stream", model=model, input_summary=f"{_prompt_chars(bedrock_messages)} chars"
        ) as current:
            started = time.perf_counter()
            last_usage = None
            outcome = "error"
            try:
                response = self._client.converse_stream(
                    modelId=model,
                    system=system_param,
                    messages=bedrock_messages,
                    inferenceConfig=inference_config,
                )

                for event in response.get("stream", []):
                    if "contentBlockDelta" in event:
                        delta = event["contentBlockDelta"].get("delta", {})
                        text_delta = delta.get("text", "")
                        if text_delta:
                            if current is not None and current.ttft_ms is None:
                                current.ttft_ms = round((time.perf_counter() - started) * 1000, 2)
                            yield text_delta
                    elif "metadata" in event:
                        last_usage = event["metadata"].get("usage")
                outcome = "ok"
            except GeneratorExit:
                # The client closed the stream early; not a model failure.
                outcome = "cancelled"
                raise
            finally:
                _record_usage(model, last_usage, current)
                _log_llm_call(model, started, last_usage, stream=True, outcome=outcome)


def get_llm_adapter(client: Any = None) -> Any:
    """
    Factory function for the LLM Adapter.
    Prioritizes Bedrock by default, while allowing explicit override to Gemini
    via `LLM_PROVIDER=gemini`.
    """
    if client is not None:
        return client

    provider = os.getenv("LLM_PROVIDER", "bedrock").lower()
    if provider == "gemini":
        from backend.rag.gemini_adapter import GeminiAsAnthropicAdapter

        return GeminiAsAnthropicAdapter()

    return BedrockAsAnthropicAdapter()
