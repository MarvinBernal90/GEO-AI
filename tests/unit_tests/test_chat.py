"""
==============================================================================
UNIT TESTS: REACT CHAT AGENT (BEDROCK GENERATION MODEL)
==============================================================================
File: tests/unit_tests/test_chat.py

Comprehensive unit tests for the ReAct chat agent in backend.ia.chat.
Validates:
1. Bedrock model resolution (GENERATION_MODEL) using ChatBedrockConverse.
2. Provider fallback support (Gemini) and explicit argument overrides.
3. Content extraction across diverse LangChain response formats.
4. Tool executions (geocoding, scorecard database querying, and RAG).
5. Assistant node prompt formatting with and without prior conversational summary.
6. Conversation summarization logic and memory compression.
7. Graph execution and request dispatching.
"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from backend.ia.chat import (
    DEFAULT_AWS_REGION,
    DEFAULT_BEDROCK_MODEL,
    MAX_NUM_MESSAGES,
    NUM_MESSAGES_TO_SUMMARIZE,
    State,
    _extract_text_content,
    _node_assistant,
    _node_summarize,
    get_chat_llm,
    get_generation_model,
    get_opportunity_score,
    react_graph,
    regulations_query,
    request,
    sys_msg,
    tools,
)


@pytest.fixture(autouse=True)
def history_in_a_temp_folder(tmp_path, monkeypatch):
    """The tests must not write chat history files inside the repository."""
    monkeypatch.setattr("backend.ia.chat.REPO_ROOT", tmp_path)


class TestChatLLMResolution:
    def test_default_chat_llm_is_bedrock(self):
        """Chat LLM defaults to ChatBedrockConverse with Bedrock GENERATION_MODEL."""
        with patch.dict("os.environ", {}, clear=True):
            model_name = get_generation_model()
            assert model_name == DEFAULT_BEDROCK_MODEL
            llm = get_chat_llm()
            assert llm.__class__.__name__ == "ChatBedrockConverse"
            assert llm.model_id == DEFAULT_BEDROCK_MODEL
            assert llm.region_name == DEFAULT_AWS_REGION
            assert llm.provider == "amazon"
            assert llm.max_tokens == 2048
            assert llm.disable_streaming is False

    def test_custom_generation_model_env(self):
        """Chat LLM respects custom GENERATION_MODEL and AWS_REGION in environment."""
        custom_model = "amazon.nova-pro-v1:0"
        with patch.dict("os.environ", {"GENERATION_MODEL": custom_model, "AWS_REGION": "us-east-1"}, clear=True):
            assert get_generation_model() == custom_model
            llm = get_chat_llm()
            assert llm.__class__.__name__ == "ChatBedrockConverse"
            assert llm.model_id == custom_model
            assert llm.region_name == "us-east-1"
            assert llm.provider == "amazon"

    def test_legacy_gemini_string_in_bedrock_mode_resolves_to_bedrock_default(self):
        """If legacy models/gemini string is in GENERATION_MODEL without LLM_PROVIDER=gemini, it resolves to Bedrock."""
        with patch.dict("os.environ", {"GENERATION_MODEL": "models/gemini-3.6-flash"}, clear=True):
            assert get_generation_model() == DEFAULT_BEDROCK_MODEL
            llm = get_chat_llm()
            assert llm.__class__.__name__ == "ChatBedrockConverse"
            assert llm.model_id == DEFAULT_BEDROCK_MODEL

    def test_explicit_gemini_fallback(self):
        """Chat LLM falls back to ChatGoogleGenerativeAI when LLM_PROVIDER=gemini."""
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "gemini",
                "GENERATION_MODEL": "gemini-2.5-flash",
                "GOOGLE_API_KEY": "fake_key_for_testing",
            },
            clear=True,
        ):
            assert get_generation_model() == "gemini-2.5-flash"
            llm = get_chat_llm()
            assert llm.__class__.__name__ == "ChatGoogleGenerativeAI"
            assert llm.model == "gemini-2.5-flash"

    def test_get_chat_llm_explicit_parameters(self):
        """Passing explicit arguments to get_chat_llm overrides environment defaults."""
        llm = get_chat_llm(
            model="amazon.nova-micro-v1:0",
            region_name="eu-west-1",
            temperature=0.5,
            max_tokens=1024,
            disable_streaming=True,
        )
        assert llm.__class__.__name__ == "ChatBedrockConverse"
        assert llm.model_id == "amazon.nova-micro-v1:0"
        assert llm.region_name == "eu-west-1"
        assert llm.temperature == 0.5
        assert llm.max_tokens == 1024
        assert llm.disable_streaming is True


class TestContentExtraction:
    def test_extract_text_from_string(self):
        assert _extract_text_content("Resumen de prueba") == "Resumen de prueba"

    def test_extract_text_from_list_of_dicts(self):
        blocks = [{"type": "text", "text": "Parte 1. "}, {"type": "text", "text": "Parte 2."}]
        assert _extract_text_content(blocks) == "Parte 1. Parte 2."

    def test_extract_text_from_objects_with_text_attribute(self):
        block = type("Block", (), {"text": "Texto extraído"})()
        assert _extract_text_content([block]) == "Texto extraído"

    def test_extract_text_fallback_to_str(self):
        assert _extract_text_content([123, 456]) == "123456"
        assert _extract_text_content(999) == "999"


class TestTools:
    def test_tools_list_registered(self):
        """Verifies that tools registered in backend.ia.chat contain the expected functions."""
        tool_names = [t.__name__ for t in tools]
        assert "get_opportunity_score" in tool_names
        assert "regulations_query" in tool_names

    @patch("backend.ia.chat.geocodificar_direccion")
    def test_get_opportunity_score_no_geocoding(self, mock_geo):
        """When geocoding fails, returns datos_distrito: None."""
        mock_geo.return_value = None
        result = get_opportunity_score("calle inexistente 999")
        assert result == {"datos_distrito": None}

    @patch("backend.ia.chat.geocodificar_direccion")
    @patch("backend.ia.chat.Session")
    def test_get_opportunity_score_success(self, mock_session_cls, mock_geo):
        """When geocoding and database row exist, returns populated datos_distrito."""
        mock_geo.return_value = {"codi_districte": 2}
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session

        row_dict = {
            "codi_districte": 2,
            "nom_districte": "Eixample",
            "renta_media": 22000.0,
            "daily_foot_traffic": 15000,
            "total_competitors": 250,
            "opportunity_score": 85.5,
        }
        mock_mappings = MagicMock()
        mock_mappings.first.return_value = row_dict
        mock_session.execute.return_value.mappings.return_value = mock_mappings

        result = get_opportunity_score("Carrer de Mallorca 200")
        assert result == {"datos_distrito": row_dict}

    @patch("backend.ia.chat.geocodificar_direccion")
    @patch("backend.ia.chat.Session")
    def test_get_opportunity_score_not_found_in_db(self, mock_session_cls, mock_geo):
        """When geocoding succeeds but database has no record for the district, returns None."""
        mock_geo.return_value = {"codi_districte": 99}
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session

        mock_mappings = MagicMock()
        mock_mappings.first.return_value = None
        mock_session.execute.return_value.mappings.return_value = mock_mappings

        result = get_opportunity_score("Dirección sin datos")
        assert result == {"datos_distrito": None}

    @patch("backend.ia.chat.retrieve_relevant_chunks_with_rerank")
    @patch("backend.ia.chat.build_context")
    @patch("backend.ia.chat.Session")
    def test_regulations_query(self, mock_session_cls, mock_build_context, mock_retrieve):
        """RAG query retrieves relevant chunks and formats regulatory context."""
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_retrieve.return_value = ["chunk1", "chunk2"]
        mock_build_context.return_value = "Contexto normativo sintetizado"

        res = regulations_query("horarios cafetería")
        assert res == "Contexto normativo sintetizado"
        mock_retrieve.assert_called_once()
        mock_build_context.assert_called_once_with(["chunk1", "chunk2"])


class TestGraphNodes:
    @patch("backend.ia.chat.llm_with_tools")
    def test_node_assistant(self, mock_llm_tools):
        """_node_assistant properly prepares context and invokes llm_with_tools."""
        mock_llm_tools.invoke.return_value = AIMessage(content="OK")
        state: State = {
            "messages": [HumanMessage(content="hola")],
            "num_responses": 0,
            "summary": "Resumen previo",
        }
        res = _node_assistant(state)
        assert res == {"messages": [mock_llm_tools.invoke.return_value]}
        called_messages = mock_llm_tools.invoke.call_args[0][0]
        assert called_messages[0] == sys_msg
        assert "Resumen de la conversación previa: Resumen previo" in called_messages[1].content

    @patch("backend.ia.chat.llm_with_tools")
    def test_node_assistant_without_summary(self, mock_llm_tools):
        """_node_assistant sends the system message and the raw messages when no summary exists."""
        mock_llm_tools.invoke.return_value = AIMessage(content="Respuesta sin resumen")
        state: State = {
            "messages": [HumanMessage(content="¿Cuál es la normativa?")],
            "num_responses": 1,
            "summary": "",
        }
        res = _node_assistant(state)
        assert res == {"messages": [mock_llm_tools.invoke.return_value]}
        called_messages = mock_llm_tools.invoke.call_args[0][0]
        assert called_messages == [sys_msg, state["messages"][0]]

    def test_node_summarize_under_limit(self):
        """_node_summarize increments counter when below MAX_NUM_MESSAGES."""
        state: State = {
            "messages": [HumanMessage(content="msg")],
            "num_responses": 1,
            "summary": "",
        }
        res = _node_summarize(state)
        assert res == {"num_responses": 2}

    @patch("backend.ia.chat.llm")
    def test_node_summarize_over_limit(self, mock_llm):
        """_node_summarize triggers summary via llm when exceeding MAX_NUM_MESSAGES."""
        mock_llm.invoke.return_value = AIMessage(content="Resumen compilado")
        state: State = {
            "messages": [
                HumanMessage(id="h1", content="q1"),
                AIMessage(id="a1", content="r1"),
                HumanMessage(id="h2", content="q2"),
                AIMessage(id="a2", content="r2"),
                HumanMessage(id="h3", content="q3"),
                AIMessage(id="a3", content="r3"),
                HumanMessage(id="h4", content="q4"),
                AIMessage(id="a4", content="r4"),
            ],
            "num_responses": 6,
            "summary": "",
        }
        res = _node_summarize(state)
        assert res["summary"] == "Resumen compilado"
        assert res["num_responses"] == 4
        assert len(res["messages"]) > 0


class TestNodeSummarizePrompt:
    @patch("backend.ia.chat.llm")
    def test_over_max_num_messages_triggers_summary_initial(self, mock_llm):
        """When num_responses exceeds MAX_NUM_MESSAGES without previous summary, creates new summary."""
        mock_llm.invoke.return_value = AIMessage(content="Nuevo resumen creado")
        state: State = {
            "messages": [
                HumanMessage(id="h1", content="q1"),
                AIMessage(id="a1", content="r1"),
                HumanMessage(id="h2", content="q2"),
                AIMessage(id="a2", content="r2"),
                HumanMessage(id="h3", content="q3"),
                AIMessage(id="a3", content="r3"),
                HumanMessage(id="h4", content="q4"),
                AIMessage(id="a4", content="r4"),
            ],
            "num_responses": MAX_NUM_MESSAGES + 1,
            "summary": "",
        }
        res = _node_summarize(state)
        assert "summary" in res
        assert res["summary"] == "Nuevo resumen creado"
        assert res["num_responses"] == (MAX_NUM_MESSAGES + 2) - NUM_MESSAGES_TO_SUMMARIZE
        assert len(res["messages"]) > 0

        # Verify summary prompt wording for initial summary
        called_human_msg = mock_llm.invoke.call_args[0][0][-1]
        assert "Crea un resumen teniendo en cuenta los mensajes" in called_human_msg.content

    @patch("backend.ia.chat.llm")
    def test_over_max_num_messages_updates_existing_summary(self, mock_llm):
        """When previous summary exists, updates summary prompt includes existing summary."""
        mock_llm.invoke.return_value = AIMessage(content="Resumen actualizado")
        state: State = {
            "messages": [
                HumanMessage(id="h1", content="q1"),
                AIMessage(id="a1", content="r1"),
                HumanMessage(id="h2", content="q2"),
                AIMessage(id="a2", content="r2"),
                HumanMessage(id="h3", content="q3"),
                AIMessage(id="a3", content="r3"),
                HumanMessage(id="h4", content="q4"),
                AIMessage(id="a4", content="r4"),
            ],
            "num_responses": 6,
            "summary": "Resumen de la ronda 1",
        }
        res = _node_summarize(state)
        assert res["summary"] == "Resumen actualizado"

        called_human_msg = mock_llm.invoke.call_args[0][0][-1]
        assert "Este es un resumen de mensajes pasados: Resumen de la ronda 1" in called_human_msg.content


class TestReActGraphAndRequest:
    def test_react_graph_nodes_and_edges(self):
        """Verifies that the compiled react_graph contains the expected state nodes."""
        expected_nodes = {"__start__", "assistant", "tools", "summarize"}
        assert expected_nodes.issubset(set(react_graph.nodes.keys()))

    @patch("backend.ia.chat.react_graph.invoke")
    def test_request_dispatches_to_graph_and_returns_last_message_when_not_streaming(self, mock_invoke):
        """request function dispatches user content and thread_id to react_graph.invoke when stream=False."""
        mock_response = AIMessage(content="Horarios de cafetería: 06:00 a 02:00")
        mock_invoke.return_value = {
            "messages": [
                HumanMessage(content="horarios cafetería"),
                mock_response,
            ]
        }

        result = request("horarios cafetería", thread="test_thread_42", stream=False)
        assert result == mock_response
        assert result.content == "Horarios de cafetería: 06:00 a 02:00"

        mock_invoke.assert_called_once_with(
            {"messages": [{"role": "user", "content": "horarios cafetería"}]},
            {"configurable": {"thread_id": "test_thread_42"}},
        )

    @patch("backend.ia.chat.react_graph.stream")
    def test_request_stream_yields_tokens_and_done(self, mock_stream):
        """request function streams assistant tokens and finishes with done event."""
        mock_stream.return_value = [
            (AIMessage(content="Horarios "), {"langgraph_node": "assistant"}),
            (AIMessage(content="de cafetería"), {"langgraph_node": "assistant"}),
        ]

        events = list(request("horarios cafetería", thread="test_thread_42"))
        assert events == [
            {"type": "token", "text": "Horarios "},
            {"type": "token", "text": "de cafetería"},
            {"type": "done", "text": "Horarios de cafetería"},
        ]

        mock_stream.assert_called_once_with(
            {"messages": [{"role": "user", "content": "horarios cafetería"}]},
            {"configurable": {"thread_id": "test_thread_42"}},
            stream_mode="messages",
        )

    @patch("backend.ia.chat.react_graph.stream")
    def test_request_stream_filters_tool_calls_and_non_assistant_nodes(self, mock_stream):
        """request function ignores tool calls and nodes other than assistant."""
        tool_call_msg = AIMessage(
            content="",
            tool_calls=[{"name": "regulations_query", "args": {"query": "horarios"}, "id": "1", "type": "tool_call"}],
        )
        tool_msg = AIMessage(content="Raw regulations context")
        assistant_ans = AIMessage(content="Respuesta al usuario")
        summary_msg = AIMessage(content="Resumen interno")

        mock_stream.return_value = [
            (tool_call_msg, {"langgraph_node": "assistant"}),
            (tool_msg, {"langgraph_node": "tools"}),
            (assistant_ans, {"langgraph_node": "assistant"}),
            (summary_msg, {"langgraph_node": "summarize"}),
        ]

        events = list(request("horarios cafetería", thread="test_thread_42"))
        assert events == [
            {"type": "token", "text": "Respuesta al usuario"},
            {"type": "done", "text": "Respuesta al usuario"},
        ]

    @patch("backend.ia.chat.react_graph.stream")
    def test_request_stream_handles_exceptions_gracefully(self, mock_stream):
        """request function yields an error event if graph streaming fails."""
        mock_stream.side_effect = RuntimeError("Bedrock connection timeout")

        events = list(request("horarios cafetería", thread="test_thread_42"))
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "detail" in events[0]
