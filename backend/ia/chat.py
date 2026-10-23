"""
==============================================================================
AI ORCHESTRATOR: REACT CHAT AGENT WITH PERSISTENT MEMORY
==============================================================================
File: backend/ia/chat.py

An agent is built in which an LLM processes the user prompt, breaks down the
requested tasks, calls tools to complete them, and finally, when it considers it
has all the information, composes a response for the user. This is a ReAct
(Reasoning and Acting) architecture: https://www.ibm.com/think/topics/react-agent

It is an agent with per-user conversational memory, which can choose to continue
a previous conversation or start a new one. Each user is identified by a thread_id.
At the moment the agent has two tools:
- get_opportunity_score: infers location viability given spatial and socioeconomic data.
- regulations_query: RAG engine that provides context on municipal regulations and procedures.

The LangChain/LangGraph framework provides standard schemas that allow starting
generic and evolving towards AWS Bedrock Foundation Models (Amazon Nova / Claude).

Conversation persistence is managed with PostgresSaver (PostgreSQL / PostGIS).

Metrics: the LLM calls and the tools are measured with spans (time, tokens, steps).
Spans only keep sizes and tool names, never the text of the user.
"""

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.db.connection import resolve_database_url
from backend.geo.geocoding import geocodificar_direccion
from backend.ia.chat_history import append_history
from backend.ia.thinking_filter import ThinkingStripper
from backend.observability.metrics import add_usage, set_output, span
from backend.rag.query_engine import build_context, retrieve_relevant_chunks_with_rerank

REPO_ROOT = Path(__file__).resolve().parents[2]

#### CONFIGURATION
logger = logging.getLogger("geoyield_agent")

load_dotenv()

DEFAULT_AWS_REGION = "eu-central-1"
DEFAULT_BEDROCK_MODEL = "amazon.nova-lite-v1:0"


def get_generation_model() -> str:
    """
    Resolves the foundation model identifier.
    Prioritizes GENERATION_MODEL / BEDROCK_MODEL. If the environment variable
    still holds a legacy Gemini model string while running in Bedrock mode,
    it automatically resolves to the default Bedrock model.
    """
    model = os.getenv("GENERATION_MODEL") or os.getenv("BEDROCK_MODEL") or DEFAULT_BEDROCK_MODEL
    provider = os.getenv("LLM_PROVIDER", "bedrock").lower()
    if provider != "gemini" and (model.startswith("models/") or model.startswith("gemini")):
        return os.getenv("BEDROCK_MODEL") or DEFAULT_BEDROCK_MODEL
    return model


# Foundation Model configured via GENERATION_MODEL (Amazon Nova Lite by default)
GENERATION_MODEL = get_generation_model()
AWS_REGION = os.getenv(
    "AWS_REGION",
    os.getenv("AWS_DEFAULT_REGION", DEFAULT_AWS_REGION),
)
MAX_NUM_MESSAGES = int(os.environ.get("MAX_NUM_MESSAGES", 5))
NUM_MESSAGES_TO_SUMMARIZE = int(os.environ.get("NUM_MESSAGES_TO_SUMMARIZE", 3))

GEODATA_BASEURL = resolve_database_url()
engine = create_engine(resolve_database_url())


def get_chat_llm(
    model: str | None = None,
    region_name: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    disable_streaming: bool = False,
) -> Any:
    """
    Initializes the LLM chat model.
    Defaults to Bedrock Converse API (via ChatBedrockConverse) using GENERATION_MODEL.
    Supports explicit fallback to Gemini (via ChatGoogleGenerativeAI) if LLM_PROVIDER=gemini.

    Args:
        model: Foundation model identifier (defaults to GENERATION_MODEL).
        region_name: AWS region (defaults to AWS_REGION).
        temperature: Sampling temperature (defaults to 0.0).
        max_tokens: Maximum tokens to generate (defaults to 2048).
        disable_streaming: Whether to disable Converse streaming (defaults to False,
            as Amazon Nova natively supports ConverseStream token streaming).
    """
    selected_model = model or get_generation_model()
    region = region_name or os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", DEFAULT_AWS_REGION))
    provider = os.getenv("LLM_PROVIDER", "bedrock").lower()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=selected_model,
            temperature=temperature,
            max_retries=3,
        )

    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=selected_model,
        region_name=region,
        provider="amazon",
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=3,
        disable_streaming=disable_streaming,
    )


#### STATE VARIABLE
class State(MessagesState):
    """
    Extended MessagesState introducing a summary field to compress old context
    without growing token length indefinitely.
    """

    summary: str
    num_responses: int


#### METRICS HELPER
def _record_llm_result(response: Any, current_span: Any) -> None:
    """
    Store the token usage and a short output summary of an LLM call on its span.
    LangChain puts the usage in `response.usage_metadata`. Never raises: metrics
    must not break an answer.
    """
    if current_span is None:
        return
    try:
        usage = getattr(response, "usage_metadata", None) or {}
        add_usage(GENERATION_MODEL, usage.get("input_tokens"), usage.get("output_tokens"), 0, target=current_span)
        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            names = ", ".join(str(call.get("name", "?")) for call in tool_calls)
            set_output(f"tool calls: {names}")
        else:
            set_output(f"{len(_extract_text_content(response.content))} chars")
    except Exception:
        logger.debug("Could not record the LLM metrics", exc_info=True)


#### TOOLS DEFINITION
def get_opportunity_score(direccion: str) -> dict[str, Any]:
    """
    Returns a score for an address in the city of Barcelona.
    Calls the geocodificar_direccion function, which returns the district code among other data, and with it
    the 'district_scorecard' view is queried to return an opportunity_score.

    Args:
        direccion: a string representing an address in the city of Barcelona

    Returns:
        dict: A dictionary containing district metrics or None if not found
    """
    with span("agent", "tool_get_opportunity_score", input_summary=f"{len(str(direccion))} chars"):
        with span("external", "geocode_address", input_summary=f"{len(str(direccion))} chars"):
            res = geocodificar_direccion(direccion)
            set_output("found" if res else "not found")

        if res is None:
            return {"datos_distrito": None}

        with span("db", "district_scorecard_query"):
            with Session(engine) as session:
                row = (
                    session.execute(
                        text(
                            "SELECT ds.codi_districte, ds.nom_districte, ds.renta_media, ds.daily_foot_traffic, "
                            "ds.total_competitors, ds.opportunity_score "
                            "FROM district_scorecard ds "
                            "LEFT JOIN district_mobility dm ON ds.codi_districte = dm.codi_districte "
                            "WHERE ds.codi_districte = :codi"
                        ),
                        {"codi": res["codi_districte"]},
                    )
                    .mappings()
                    .first()
                )
            set_output("district found" if row else "no data for the district")

        if row is None:
            logger.warning("No hay datos en district_scorecard para el distrito %s", res["codi_districte"])
            return {"datos_distrito": None}

        return {"datos_distrito": dict(row)}


def regulations_query(query: str) -> str:
    """
    RAG that provides information on regulatory and legal aspects.

    Args:
        query (str): Natural-language query.

    Returns:
        str: Built regulatory context from relevant chunks.
    """
    with span("agent", "tool_regulations_query", input_summary=f"{len(str(query))} chars"):
        with Session(engine) as session:
            documents = retrieve_relevant_chunks_with_rerank(session=session, query=query)
        context = build_context(documents)
        if isinstance(context, str):
            set_output(f"{len(context)} chars of context")
    return context


def _extract_text_content(content: Any) -> str:
    """Helper to extract plain text safely from string or list content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif hasattr(block, "text"):
                parts.append(str(block.text))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


# updates state['num_responses'], which keeps track of the number of answers given to the user
# if they exceed MAX_NUM_MESSAGES, the first NUM_MESSAGES_TO_SUMMARIZE are included in state['summary']
# and deleted from state['messages'] along with tool calling and tool response associated messages
def summarize_conversation(state: State) -> dict[str, Any]:
    num_responses = state.get("num_responses", 0) + 1
    if num_responses > MAX_NUM_MESSAGES:
        summary = state.get("summary", "")
        if summary:
            summary_message = (
                f"Este es un resumen de mensajes pasados: {summary}\n\n"
                "Actualiza el resumen teniendo en cuenta los mensajes en la lista de arriba"
            )
        else:
            summary_message = "Crea un resumen teniendo en cuenta los mensajes en la lista de arriba"

        # HumanMessages y ToolMessages excluded, only AiMessages, which are the responses generated by de model to the user, are kept
        responses = [m for m in state["messages"] if m.type == "ai" and m.content]
        messages = responses[:NUM_MESSAGES_TO_SUMMARIZE] + [HumanMessage(content=summary_message)]
        active_llm = llm or target_llm or get_chat_llm()
        response = active_llm.invoke(messages)

        # first message is the HumanMessage that initated the conversation. This message is always kept and serves as 'title' of th conversation
        last_msg_to_del_index = state["messages"].index(responses[NUM_MESSAGES_TO_SUMMARIZE])
        delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][1:last_msg_to_del_index]]
        return {
            "summary": _extract_text_content(response.content),
            "num_responses": num_responses - NUM_MESSAGES_TO_SUMMARIZE,
            "messages": delete_messages,
        }

    return {"num_responses": num_responses}


#### TOOL BINDING & LLM INITIALIZATION
tools = [get_opportunity_score, regulations_query]
try:
    llm = get_chat_llm()
    llm_with_tools = llm.bind_tools(tools)
except Exception as exc:
    logger.warning("Could not initialize chat LLM at module load: %s", exc)
    llm = None
    llm_with_tools = None

#### ASSISTANT
sys_msg = SystemMessage(
    content="""Eres un asistente experto en hostelería y restauración, especializado en la ciudad de Barcelona.
Tu tarea es proporcionar información sobre aspectos regulatorios y legales relacionados con la apertura de negocios en esta ciudad y un opportunity_score, si se te pide.
Dispones de dos herramientas para ayudarte en tu tarea:
1. get_opportunity_score: devuelve un score a partir de una dirección en la ciudad de Barcelona.
2. regulations_query: Esta herramienta te permite obtener información sobre aspectos regulatorios y legales relacionados con la apertura de negocios en Barcelona.
Cuando respondas a las consultas de los usuarios, asegúrate de proporcionar información precisa y relevante, y de citar las fuentes de información cuando sea posible.
Usa solamente datos que te proporcionen las herrmientas, de ningún otro lugar.
Lista las fuentes.
Si no eres capaz dem responder a la petición del usuario con la información disponible, dilo claramente.
Responde siempre en español, aunque el usuario escriba en otro idioma.
No escribas tu razonamiento interno ni uses etiquetas como <thinking>: escribe solo la respuesta final para el usuario.
"""
)


def assistant(state: State) -> dict[str, Any]:
    """
    Main function of the assistant: receives a message state and returns a response generated by the language model.
    """
    summary = state.get("summary", "")
    if summary:
        system_message = f"Resumen de la conversación previa: {summary}"
        messages = [SystemMessage(content=system_message)] + state["messages"]
    else:
        messages = state["messages"]

    invoker = llm_with_tools or (llm.bind_tools(tools) if llm else get_chat_llm().bind_tools(tools))
    return {"messages": [invoker.invoke([sys_msg] + messages)]}


#### CREATE AND COMPILE GRAPH WITH MEMORY

checkpointer = None
try:
    checkpointer_context = PostgresSaver.from_conn_string(resolve_database_url().replace("+psycopg2", ""))
    checkpointer = checkpointer_context.__enter__()
    checkpointer.setup()
except Exception as exc:
    logger.warning("Could not initialize PostgreSQL checkpointer: %s", exc)

target_llm = llm
target_llm_with_tools = llm_with_tools


def _node_assistant(state: State):
    summary = state.get("summary", "")
    if summary:
        system_message = f"Resumen de la conversación previa: {summary}"
        messages = [SystemMessage(content=system_message)] + state["messages"]
    else:
        messages = state["messages"]
    invoker = target_llm_with_tools or (
        target_llm.bind_tools(tools) if target_llm else get_chat_llm().bind_tools(tools)
    )
    prompt = [sys_msg] + messages
    with span("llm", "llm_call", model=GENERATION_MODEL, input_summary=f"{len(prompt)} messages") as llm_span:
        response = invoker.invoke(prompt)
        _record_llm_result(response, llm_span)
    return {"messages": [response]}


def _node_summarize(state: State):
    num_responses = state.get("num_responses", 0) + 1
    if num_responses > MAX_NUM_MESSAGES:
        summary = state.get("summary", "")
        if summary:
            summary_message = (
                f"Este es un resumen de mensajes pasados: {summary}\n\n"
                "Actualiza el resumen teniendo en cuenta los mensajes en la lista de arriba"
            )
        else:
            summary_message = "Crea un resumen teniendo en cuenta los mensajes en la lista de arriba"

        # HumanMessages y ToolMessages excluded, only AiMessages, which are the responses generated by de model to the user, are kept
        responses = [m for m in state["messages"] if m.type == "ai" and m.content]
        messages = responses[:NUM_MESSAGES_TO_SUMMARIZE] + [HumanMessage(content=summary_message)]
        active_llm = target_llm or llm or get_chat_llm()
        with span(
            "llm", "summarize_call", model=GENERATION_MODEL, input_summary=f"{len(messages)} messages"
        ) as llm_span:
            response = active_llm.invoke(messages)
            _record_llm_result(response, llm_span)

        last_msg_to_del_index = state["messages"].index(responses[NUM_MESSAGES_TO_SUMMARIZE])
        # first message is the HumanMessage that initated the conversation. This message is always kept and serves as 'title' of th conversation
        delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][1:last_msg_to_del_index]]
        return {
            "summary": _extract_text_content(response.content),
            "num_responses": num_responses - NUM_MESSAGES_TO_SUMMARIZE,
            "messages": delete_messages,
        }

    return {"num_responses": num_responses}


builder = StateGraph(State)
builder.add_node("assistant", _node_assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_node("summarize", _node_summarize)

builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", tools_condition, {"tools": "tools", END: "summarize"})
builder.add_edge("tools", "assistant")
builder.add_edge("summarize", END)

react_graph = builder.compile(checkpointer=checkpointer)


#### ASSISTANT CALL FUNCTIONS
def _request_stream(
    content: str,
    thread: str,
    graph: Any = None,
) -> Iterator[dict[str, Any]]:
    """Internal generator that streams assistant tokens from react_graph."""
    active_graph = graph or react_graph
    messages = [{"role": "user", "content": content}]
    configurable = {"thread_id": thread}
    full_response: list[str] = []
    stripper = ThinkingStripper()  # hides <thinking> blocks, even when split across tokens

    try:
        for chunk, metadata in active_graph.stream(
            {"messages": messages},
            {"configurable": configurable},
            stream_mode="messages",
        ):
            # Only stream tokens from the assistant node intended for the user
            if metadata.get("langgraph_node") == "assistant":
                # Filter out internal tool call argument tokens
                is_tool_call = bool(
                    getattr(chunk, "tool_calls", None)
                    or getattr(chunk, "tool_call_chunks", None)
                    or (
                        isinstance(getattr(chunk, "additional_kwargs", None), dict)
                        and chunk.additional_kwargs.get("tool_calls")
                    )
                )
                if is_tool_call:
                    continue

                text = stripper.feed(_extract_text_content(chunk.content) or "")
                if text:
                    full_response.append(text)
                    yield {"type": "token", "text": text}

        # Release any text still held back by the filter (e.g. a lone "<").
        rest = stripper.flush()
        if rest:
            full_response.append(rest)
            yield {"type": "token", "text": rest}

        full_text = "".join(full_response)
        # Saved BEFORE the done event. It never raises, and the history is not lost
        # if the client leaves right after the last event.
        append_history(thread, content, full_text, history_dir=REPO_ROOT / "chat_history")
        yield {"type": "done", "text": full_text}
        with open(f"{REPO_ROOT}/chat_history/{thread.replace(':', '_')}.txt", "a") as f:
            f.write(f"USUARIO:\n{content}\n\n")  # saves user input to history
            f.write(f"ASISTENTE:\n{full_text}")  # saves assistant output input to history
    except Exception as exc:
        logger.exception("Error streaming chat request for thread %s: %s", thread, exc)
        yield {"type": "error", "detail": "No se pudo procesar tu mensaje. Inténtalo de nuevo."}


def _request_invoke(
    content: str,
    thread: str,
    graph: Any = None,
) -> Any:
    """Internal invocation that returns the full AIMessage."""
    active_graph = graph or react_graph
    messages = [{"role": "user", "content": content}]
    configurable = {"thread_id": thread}

    state = active_graph.invoke({"messages": messages}, {"configurable": configurable})
    response = state["messages"][-1]

    append_history(
        thread,
        content,
        _extract_text_content(response.content),
        history_dir=REPO_ROOT / "chat_history",
    )
    with open(f"{REPO_ROOT}/chat_history/{thread.replace(':', '_')}.txt", "a") as f:
        f.write(f"USUARIO:\n{content}\n\n")  # saves user input to history
        f.write(f"ASISTENTE:\n{response}")  # saves assistant output input to history

    return response


def request(
    content: str,
    thread: str,
    graph: Any = None,
    stream: bool = True,
) -> Iterator[dict[str, Any]] | Any:
    """
    Sends the user's latest request in the conversation thread to the chat assistant.

    When stream=True (default), streams SSE-compatible token events for real-time
    publishing in the frontend's response-output text area.
    When stream=False, synchronously invokes the agent graph and returns the final AIMessage.

    Args:
        content: request text from the user
        thread: conversation thread identifier. Has the form user:conversation_id
        graph: optional compiled StateGraph instance (defaults to react_graph)
        stream: whether to stream response tokens (defaults to True)

    Returns:
        If stream=True: Iterator of event dicts ({"type": "token", "text": ...}, {"type": "done", ...})
        If stream=False: The assistant's response message (AIMessage)
    """
    if stream:
        return _request_stream(content, thread, graph=graph)
    return _request_invoke(content, thread, graph=graph)


if __name__ == "__main__":

    def _print_stream(prompt: str, thread_id: str):
        print(f"\nUser: {prompt}\nAssistant: ", end="", flush=True)
        for event in request(prompt, thread_id):
            if event.get("type") == "token":
                print(event["text"], end="", flush=True)
            elif event.get("type") == "error":
                print(f"\n[Error: {event['detail']}]")
        print()

    _print_stream(
        "cuáles son los horarios de apertura para una cafetería?",
        "claudiberenguer:5",
    )
    _print_stream(
        "y para un bar musical?",
        "claudiberenguer:5",
    )
    _print_stream(
        "hay algún tipo de normativa específica para bar musical?",
        "claudiberenguer:5",
    )
    _print_stream(
        "dime cuanto serían las tasas para una terraza de 15m2 en calle Creucoberta",
        "claudiberenguer:5",
    )
