"""
==============================================================================
UNIT TESTS: METRICS OF THE ASSISTANT (REACT AGENT)
==============================================================================
File: tests/unit_tests/test_assistant_metrics.py

Group 1 runs a REAL LangGraph graph (nodes and tools of backend.ia.chat) with a
fake LLM, to prove the collector reaches the threads where LangGraph runs them.
Group 2 tests the endpoint with a fake `request`. No database and no LLM needed.
"""

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from backend.api.api import app
from backend.api.routers import assistant as assistant_router
from backend.ia import chat
from backend.observability.metrics import MetricsCollector, span, use_collector

QUESTION = "¿Qué licencia necesito para una terraza en Carrer Provença?"


class _FakeLLM:
    """First call asks for a tool, second call answers. Both report token usage."""

    def __init__(self):
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[{"name": "regulations_query", "args": {"query": "terrazas"}, "id": "1", "type": "tool_call"}],
                usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            )
        return AIMessage(
            content="Respuesta final",
            usage_metadata={"input_tokens": 300, "output_tokens": 50, "total_tokens": 350},
        )


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _graph():
    builder = StateGraph(chat.State)
    builder.add_node("assistant", chat._node_assistant)
    builder.add_node("tools", ToolNode(chat.tools))
    builder.add_node("summarize", chat._node_summarize)
    builder.add_edge(START, "assistant")
    builder.add_conditional_edges("assistant", tools_condition, {"tools": "tools", END: "summarize"})
    builder.add_edge("tools", "assistant")
    builder.add_edge("summarize", END)
    return builder.compile(checkpointer=MemorySaver())


@pytest.fixture
def run_assistant(monkeypatch, tmp_path):
    """Run one question through the real graph and return the collector."""
    (tmp_path / "chat_history").mkdir()
    monkeypatch.setattr(chat, "REPO_ROOT", tmp_path)  # the history file goes to a temp folder
    monkeypatch.setattr(chat, "llm_with_tools", _FakeLLM())
    monkeypatch.setattr(chat, "Session", lambda engine: _NullSession())
    monkeypatch.setattr(chat, "retrieve_relevant_chunks_with_rerank", lambda session, query: ["c1", "c2"])
    monkeypatch.setattr(chat, "build_context", lambda documents: "contexto normativo")

    collector = MetricsCollector(trace_id="t")
    with use_collector(collector):
        with span("agent", "assistant_pipeline"):
            events = list(chat.request(QUESTION, thread="t1", graph=_graph()))
    assert events[-1]["type"] == "done"
    return collector


class TestRealGraph:
    def test_llm_calls_and_the_tool_are_spans_with_tokens(self, run_assistant):
        spans = run_assistant.spans
        by_name = {}
        for s in spans:
            by_name.setdefault(s.name, []).append(s)

        root = by_name["assistant_pipeline"][0]
        assert len(by_name["llm_call"]) == 2
        assert len(by_name["tool_regulations_query"]) == 1
        assert all(s.parent_id == root.id for s in by_name["llm_call"] + by_name["tool_regulations_query"])
        assert sorted(s.tokens_in for s in by_name["llm_call"]) == [100, 300]
        assert run_assistant.summary()["tokens_out"] == 70
        assert by_name["llm_call"][0].output_summary == "tool calls: regulations_query"

    def test_spans_keep_sizes_and_tool_names_but_never_the_user_text(self, run_assistant):
        dumped = json.dumps([s.to_dict() for s in run_assistant.spans], ensure_ascii=False)

        assert "terraza" not in dumped
        assert "Provença" not in dumped
        assert "licencia" not in dumped


def _post_assistant(monkeypatch, fake_request):
    monkeypatch.setattr(assistant_router, "request", fake_request)
    response = TestClient(app).post("/api/assistant", json={"prompt": QUESTION, "thread_id": "user:1"})
    assert response.status_code == 200
    return [json.loads(p[len("data: ") :]) for p in response.text.split("\n\n") if p.startswith("data: ")]


class TestEndpoint:
    def test_the_stream_carries_trace_events_and_the_time_to_the_first_token(self, monkeypatch):
        def fake_request(content, thread, stream=True, graph=None):
            yield {"type": "token", "text": "Hola"}
            yield {"type": "done", "text": "Hola"}

        events = _post_assistant(monkeypatch, fake_request)

        starts = [e["span"]["name"] for e in events if e["type"] == "trace" and e["phase"] == "start"]
        assert starts == ["assistant_pipeline"]
        summary = events[-1]
        assert summary["type"] == "metrics_summary"
        assert summary["status"] == "ok"
        assert summary["ttft_ms"] is not None
        metrics_text = json.dumps([e for e in events if e["type"] in ("trace", "metrics_summary")], ensure_ascii=False)
        assert "terraza" not in metrics_text

    def test_an_error_event_marks_the_request_as_error(self, monkeypatch):
        def failing_request(content, thread, stream=True, graph=None):
            yield {"type": "error", "detail": "No se pudo procesar tu mensaje."}

        events = _post_assistant(monkeypatch, failing_request)

        assert events[-1]["type"] == "metrics_summary"
        assert events[-1]["status"] == "error"
