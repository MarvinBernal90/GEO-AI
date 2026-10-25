"""
Span model and cost helpers for request metrics.

A span is one step of the work done to answer a request (a database query,
an embedding call, an LLM call...). Spans form a tree through `parent_id`.

Privacy: spans only keep SHORT summaries of inputs and outputs. Never put the
user message or a typed address in them (GDPR).
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from backend.observability import get_logger

logger = get_logger("observability.metrics.spans")

Actor = Literal["agent", "llm", "rag", "db", "external"]
Status = Literal["running", "ok", "error", "cancelled"]

MAX_SUMMARY_CHARS = 200

# Default prices in USD per 1 million tokens: (input, output).
# For Gemini the output price also covers the "thinking" tokens.
# Source: ai.google.dev/gemini-api/docs/pricing, standard paid tier, checked on 2026-10-20.
#
# Bedrock models are NOT listed on purpose: their price depends on the region and
# the AWS contract, and we could not confirm it from the official page. Without a
# price the cost is None ("unknown"), never 0. Set both variables to enable it:
#   METRICS_PRICE_<MODEL>_IN and METRICS_PRICE_<MODEL>_OUT
# where <MODEL> is the key returned by `_model_key`, for example
#   METRICS_PRICE_AMAZON_NOVA_2_LITE_V1_0_IN=...
#   METRICS_PRICE_AMAZON_NOVA_2_LITE_V1_0_OUT=...
_DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "GEMINI_2_5_FLASH": (0.30, 2.50),
}

# Cross-region inference profiles add one of these prefixes to the model id.
_REGION_PREFIXES = ("eu.", "us.", "apac.", "global.", "us-gov.", "ca.", "jp.", "au.")


@dataclass
class Span:
    """One step of a request. Times are in milliseconds."""

    id: int
    parent_id: int | None
    actor: Actor
    name: str
    start_ms: int  # epoch time when the step started
    duration_ms: float | None = None  # None while the step is still running
    status: Status = "running"
    error: str | None = None  # only the exception class name, never the message
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    thought_tokens: int | None = None
    cost_usd: float | None = None
    cached: bool | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    ttft_ms: float | None = None  # time to first token (streaming calls only)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def clip_text(text: str | None, limit: int = MAX_SUMMARY_CHARS) -> str | None:
    """Collapse whitespace and cut the text so a summary can never grow too big."""
    if text is None:
        return None
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def _model_key(model: str) -> str:
    """
    Turn a model name into the key used to look up prices and env vars.

    'gemini-2.5-flash' -> 'GEMINI_2_5_FLASH'
    'arn:aws:bedrock:eu-central-1:123:inference-profile/eu.amazon.nova-2-lite-v1:0'
        -> 'AMAZON_NOVA_2_LITE_V1_0'  (the ARN and the region prefix are removed)
    """
    name = model
    if name.startswith("arn:"):
        # An ARN ends with '<resource type>/<model or profile id>': keep the id only.
        name = name.rsplit("/", 1)[-1]
    for prefix in _REGION_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()


def _read_price(env_name: str, default: float | None) -> float | None:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring invalid price in %s=%r", env_name, raw)
        return default


def estimate_cost(
    model: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    thought_tokens: int | None = 0,
) -> float | None:
    """
    Estimated cost in USD, or None when we do not know the price of the model.

    Thinking tokens are billed as output tokens. We return None instead of 0
    for unknown models, so a missing price is never shown as "free".
    """
    if not model:
        return None
    key = _model_key(model)
    default_in, default_out = _DEFAULT_PRICES.get(key, (None, None))
    price_in = _read_price(f"METRICS_PRICE_{key}_IN", default_in)
    price_out = _read_price(f"METRICS_PRICE_{key}_OUT", default_out)
    if price_in is None or price_out is None:
        return None
    billed_out = (tokens_out or 0) + (thought_tokens or 0)
    cost = ((tokens_in or 0) * price_in + billed_out * price_out) / 1_000_000
    return round(cost, 6)


def apply_usage(
    target: Span,
    model: str,
    tokens_in: int | None,
    tokens_out: int | None,
    thought_tokens: int | None = 0,
) -> None:
    """Write token counts and the estimated cost on a span. It replaces any earlier value."""
    target.model = model
    target.tokens_in = int(tokens_in or 0)
    target.tokens_out = int(tokens_out or 0)
    target.thought_tokens = int(thought_tokens or 0)
    target.cost_usd = estimate_cost(model, target.tokens_in, target.tokens_out, target.thought_tokens)
