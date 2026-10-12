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
"""

import os
from collections.abc import Generator
from typing import Any

from backend.observability import get_logger

logger = get_logger("rag.bedrock_adapter")

# Resilience Settings
DEFAULT_AWS_REGION = "eu-central-1"
DEFAULT_BEDROCK_MODEL = "amazon.nova-lite-v1:0"


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

            bedrock_messages.append({
                "role": msg.get("role", "user"),
                "content": [{"text": text_content}],
            })

        # 3. Explicit inferenceConfig (critical: avoids silent 64K quota exhaustion)
        inference_config = {
            "maxTokens": max_tokens,
            "temperature": temperature,
        }

        response = self._client.converse(
            modelId=model,
            system=system_param,
            messages=bedrock_messages,
            inferenceConfig=inference_config,
        )

        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", [])
        text_out = "".join(b.get("text", "") for b in content_blocks if "text" in b)

        stop_reason = response.get("stopReason")
        if stop_reason == "max_tokens":
            logger.warning(
                f"Bedrock generation reached maxTokens ({max_tokens}). Response may be truncated."
            )

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

            bedrock_messages.append({
                "role": msg.get("role", "user"),
                "content": [{"text": text_content}],
            })

        inference_config = {
            "maxTokens": max_tokens,
        }

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
                    yield text_delta


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
