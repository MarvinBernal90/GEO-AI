"""
==============================================================================
UNIT TESTS: METRICS SPANS IN THE RAG + AGENT PIPELINE
==============================================================================
File: tests/unit_tests/test_pipeline_spans.py

Checks that the pipeline records the expected spans, that they form a tree,
and that the user's text never reaches them. No network and no LLM calls.
"""

import time
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from backend.db.models import LegalChunk
from backend.ia import agent
from backend.observability.metrics import MetricsCollector, span, use_collector
from backend.rag.embeddings import EMBEDDING_DIM
from backend.rag.query_engine import retrieve_relevant_chunks


class _ParallelState(TypedDict, total=False):
    left: str
    right: str


class TestLangGraphContext:
    def test_parallel_nodes_keep_the_collector_and_the_parent_span(self):
        """
        LangGraph runs parallel nodes in worker threads. If it did not copy the
        context, the node spans would be lost or have no parent. This test checks
        the behaviour of the LangGraph version installed in this project.
        """

        def left_node(state):
            with span("agent", "left_step"):
                time.sleep(0.01)
            return {"left": "ok"}

        def right_node(state):
            with span("agent", "right_step"):
                time.sleep(0.01)
            return {"right": "ok"}

        graph = StateGraph(_ParallelState)
        graph.add_node("node_left", left_node)
        graph.add_node("node_right", right_node)
        graph.add_edge(START, "node_left")
        graph.add_edge(START, "node_right")
        graph.add_edge("node_left", END)
        graph.add_edge("node_right", END)
        app = graph.compile()

        collector = MetricsCollector(trace_id="t1")
        with use_collector(collector):
            with span("agent", "viability_graph") as parent:
                app.invoke({"left": "", "right": ""})

        by_name = {s.name: s for s in collector.spans}
        assert {"left_step", "right_step"} <= set(by_name), "node spans were lost in the worker threads"
        assert by_name["left_step"].parent_id == parent.id
        assert by_name["right_step"].parent_id == parent.id


class _FakeGraph:
    """Stands in for the data-gathering graph, so no database is needed."""

    def invoke(self, state):
        return {
            "datos_distrito": None,
            "respuesta_legal": {"respuesta": "legal text", "chunks_recuperados": []},
        }


class _FakeStreamingLLM:
    def __init__(self):
        self.messages = self

    def create_stream(self, model, max_tokens, system, messages):
        yield "VERDE\n"
        yield "Todo bien."


class TestStreamReportSpans:
    def test_stream_records_graph_and_synthesis_spans(self, monkeypatch):
        monkeypatch.setattr(agent, "build_data_gathering_graph", lambda *args, **kwargs: _FakeGraph())
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            events = list(
                agent.generar_informe_viabilidad_stream(
                    session=None, codi_districte=1, zona_pgm="industrial", llm_client=_FakeStreamingLLM()
                )
            )

        assert [e["type"] for e in events] == ["datos", "token", "token", "done"]
        assert events[-1]["semaforo"] == "verde"
        assert [s.name for s in collector.spans] == ["viability_graph", "sintesis_final"]
        assert all(s.status == "ok" for s in collector.spans)


def _constant_embed(texts):
    """Fake embedding: every text gets the same vector."""
    return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in texts]


@pytest.fixture
def two_chunks(db_session):
    db_session.add(
        LegalChunk(
            fuente_legal="PGM (Secció V)",
            numero_articulo="1",
            titulo="t",
            contenido="zone article",
            versio="original",
            zona_pgm="industrial",
            embedding=[0.9] + [0.0] * (EMBEDDING_DIM - 1),
        )
    )
    db_session.add(
        LegalChunk(
            fuente_legal="Ordre INT/358/2011",
            numero_articulo="2",
            titulo="t",
            contenido="general article",
            versio="vigente",
            zona_pgm=None,
            embedding=[0.8] + [0.0] * (EMBEDDING_DIM - 1),
        )
    )
    db_session.commit()


class TestRetrievalSpans:
    def test_retrieve_records_a_span_tree_without_the_question_text(self, db_session, two_chunks):
        collector = MetricsCollector(trace_id="t1")

        with use_collector(collector):
            retrieve_relevant_chunks(
                db_session, "consulta con calle Mallorca 123", embed_fn=_constant_embed, top_k=2, zona_pgm="industrial"
            )

        retrieve = next(s for s in collector.spans if s.name == "retrieve")
        children = sorted(s.name for s in collector.spans if s.parent_id == retrieve.id)
        # With a zone there are two vector queries: the zone one and the general one.
        assert children == ["embed_query", "pgvector_query", "pgvector_query"]
        assert "chunks" in retrieve.output_summary
        assert "Mallorca" not in str([s.to_dict() for s in collector.spans])
