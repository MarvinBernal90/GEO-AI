"""
==============================================================================
UNIT TESTS: METRICS FOR BEDROCK (LLM ADAPTER, EMBEDDINGS AND MODEL KEYS)
==============================================================================
File: tests/unit_tests/test_bedrock_metrics.py

Uses fake Bedrock clients: no network, no AWS credentials and no cost.
"""

import io
import json

import pytest

from backend.observability.metrics import MetricsCollector, use_collector
from backend.observability.metrics.spans import _model_key
from backend.rag import embeddings
from backend.rag.bedrock_adapter import BedrockAsAnthropicAdapter

PROFILE_ARN = "arn:aws:bedrock:eu-central-1:123456789012:inference-profile/eu.amazon.nova-2-lite-v1:0"
PRICE_ENV = "METRICS_PRICE_AMAZON_NOVA_2_LITE_V1_0"
SECRET_PROMPT = "direccion privada: calle Mallorca 123"
MESSAGES = [{"role": "user", "content": SECRET_PROMPT}]


def _converse_response(text="hola", usage=None):
    response = {"output": {"message": {"content": [{"text": text}]}}, "stopReason": "end_turn"}
    if usage is not None:
        response["usage"] = usage
    return response


class _FakeBedrockClient:
    def __init__(self, response=None, events=None, error=None):
        self._response = response
        self._events = events or []
        self._error = error

    def converse(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._response

    def converse_stream(self, **kwargs):
        if self._error is not None:
            raise self._error
        return {"stream": iter(self._events)}


def _delta(text):
    return {"contentBlockDelta": {"delta": {"text": text}}}


def _adapter(client):
    return BedrockAsAnthropicAdapter(client=client)


class TestModelKey:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            (PROFILE_ARN, "AMAZON_NOVA_2_LITE_V1_0"),
            ("eu.amazon.nova-lite-v1:0", "AMAZON_NOVA_LITE_V1_0"),
            ("amazon.nova-lite-v1:0", "AMAZON_NOVA_LITE_V1_0"),
            ("arn:aws:bedrock:eu-central-1::foundation-model/amazon.titan-embed-text-v2:0", "AMAZON_TITAN_EMBED_TEXT_V2_0"),
            ("gemini-2.5-flash", "GEMINI_2_5_FLASH"),
        ],
    )
    def test_arn_and_region_prefix_are_removed(self, model, expected):
        assert _model_key(model) == expected


class TestBedrockCreateMetrics:
    def test_tokens_and_cost_come_from_the_usage_and_the_env_price(self, monkeypatch):
        monkeypatch.setenv(f"{PRICE_ENV}_IN", "0.5")
        monkeypatch.setenv(f"{PRICE_ENV}_OUT", "2")
        usage = {"inputTokens": 1000, "outputTokens": 500, "totalTokens": 1500}
        adapter = _adapter(_FakeBedrockClient(response=_converse_response(usage=usage)))
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            answer = adapter.messages.create(model=PROFILE_ARN, max_tokens=100, system="s", messages=MESSAGES)

        assert answer.content[0].text == "hola"
        llm = collector.spans[0]
        assert (llm.actor, llm.name, llm.status) == ("llm", "llm_call", "ok")
        assert llm.model == PROFILE_ARN
        assert (llm.tokens_in, llm.tokens_out) == (1000, 500)
        assert llm.cost_usd == pytest.approx(0.0015)

    def test_without_a_price_the_cost_is_unknown_not_zero(self, monkeypatch):
        monkeypatch.delenv(f"{PRICE_ENV}_IN", raising=False)
        monkeypatch.delenv(f"{PRICE_ENV}_OUT", raising=False)
        usage = {"inputTokens": 10, "outputTokens": 5}
        adapter = _adapter(_FakeBedrockClient(response=_converse_response(usage=usage)))
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            adapter.messages.create(model=PROFILE_ARN, max_tokens=100, system="s", messages=MESSAGES)

        llm = collector.spans[0]
        assert (llm.tokens_in, llm.tokens_out) == (10, 5)
        assert llm.cost_usd is None

    def test_prompt_text_is_never_stored(self):
        adapter = _adapter(_FakeBedrockClient(response=_converse_response(usage={"inputTokens": 1})))
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            adapter.messages.create(model="amazon.nova-lite-v1:0", max_tokens=100, system="s", messages=MESSAGES)

        assert "Mallorca" not in str([s.to_dict() for s in collector.spans])
        assert collector.spans[0].input_summary == f"{len(SECRET_PROMPT)} chars"

    def test_missing_usage_still_records_the_span(self):
        adapter = _adapter(_FakeBedrockClient(response=_converse_response()))
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            adapter.messages.create(model="amazon.nova-lite-v1:0", max_tokens=100, system="s", messages=MESSAGES)

        llm = collector.spans[0]
        assert llm.status == "ok"
        assert llm.tokens_in is None

    def test_failure_marks_error_and_keeps_only_the_class_name(self):
        adapter = _adapter(_FakeBedrockClient(error=RuntimeError("secret detail")))
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            with pytest.raises(RuntimeError):
                adapter.messages.create(model="amazon.nova-lite-v1:0", max_tokens=100, system="s", messages=MESSAGES)

        llm = collector.spans[0]
        assert (llm.status, llm.error) == ("error", "RuntimeError")
        assert "secret" not in str(llm.to_dict())

    def test_without_a_collector_nothing_changes(self):
        adapter = _adapter(_FakeBedrockClient(response=_converse_response(usage={"inputTokens": 1})))

        answer = adapter.messages.create(model="amazon.nova-lite-v1:0", max_tokens=100, system="s", messages=MESSAGES)

        assert answer.content[0].text == "hola"


class TestBedrockStreamMetrics:
    def test_stream_records_ttft_and_the_usage_from_the_metadata_event(self):
        events = [_delta("Hola "), _delta("mundo"), {"metadata": {"usage": {"inputTokens": 12, "outputTokens": 3}}}]
        adapter = _adapter(_FakeBedrockClient(events=events))
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            text = "".join(
                adapter.messages.create_stream(
                    model="amazon.nova-lite-v1:0", max_tokens=100, system="s", messages=MESSAGES
                )
            )

        assert text == "Hola mundo"
        llm = collector.spans[0]
        assert (llm.name, llm.status) == ("llm_call_stream", "ok")
        assert (llm.tokens_in, llm.tokens_out) == (12, 3)
        assert llm.ttft_ms is not None and llm.ttft_ms >= 0

    def test_stream_closed_early_is_cancelled(self):
        adapter = _adapter(_FakeBedrockClient(events=[_delta("uno"), _delta("dos")]))
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            stream = adapter.messages.create_stream(
                model="amazon.nova-lite-v1:0", max_tokens=100, system="s", messages=MESSAGES
            )
            next(stream)
            stream.close()

        assert collector.spans[0].status == "cancelled"

    def test_stream_without_metadata_event_has_no_tokens(self):
        adapter = _adapter(_FakeBedrockClient(events=[_delta("solo texto")]))
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            list(
                adapter.messages.create_stream(
                    model="amazon.nova-lite-v1:0", max_tokens=100, system="s", messages=MESSAGES
                )
            )

        llm = collector.spans[0]
        assert llm.status == "ok"
        assert llm.tokens_in is None


class _FakeEmbeddingClient:
    def __init__(self, token_count=7):
        self._token_count = token_count

    def invoke_model(self, **kwargs):
        body = json.dumps({"embedding": [0.1, 0.2], "inputTextTokenCount": self._token_count})
        return {"body": io.BytesIO(body.encode("utf-8"))}


class TestEmbeddingsMetrics:
    def test_one_span_per_call_with_the_total_input_tokens(self, monkeypatch):
        monkeypatch.setattr(embeddings, "EMBEDDINGS_MODEL", "amazon.titan-embed-text-v2:0")
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            vectors = embeddings.embed_texts(["uno", "dos"], client=_FakeEmbeddingClient(token_count=7))

        assert vectors == [[0.1, 0.2], [0.1, 0.2]]
        assert len(collector.spans) == 1
        emb = collector.spans[0]
        assert (emb.actor, emb.name, emb.status) == ("external", "bedrock_embeddings", "ok")
        assert (emb.tokens_in, emb.tokens_out) == (14, 0)
        assert emb.input_summary == "2 texts, 6 chars"

    def test_without_a_collector_the_vectors_are_the_same(self, monkeypatch):
        monkeypatch.setattr(embeddings, "EMBEDDINGS_MODEL", "amazon.titan-embed-text-v2:0")

        vectors = embeddings.embed_texts(["uno"], client=_FakeEmbeddingClient())

        assert vectors == [[0.1, 0.2]]
