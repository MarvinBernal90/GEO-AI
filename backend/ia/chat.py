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

import json
import logging
import os
import pickle
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.cache import TTL_DISTRICT_SECONDS, TTL_RAG_SECONDS, cache_get_json, cache_set_json, make_cache_key
from backend.db.connection import resolve_database_url
from backend.geo.amb_identify import identificar_zona_pgm
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
MAX_NUM_MESSAGES = int(os.environ.get("MAX_NUM_MESSAGES", 5))
NUM_MESSAGES_TO_SUMMARIZE = int(os.environ.get("NUM_MESSAGES_TO_SUMMARIZE", 3))
# Output token limit of each LLM call of the assistant. At 2048 the answers of the assistant
# were cut in the middle of a sentence (the call ended with stopReason "max_tokens").
ASSISTANT_MAX_TOKENS = int(os.environ.get("ASSISTANT_MAX_TOKENS", 4096))

engine = create_engine(resolve_database_url())


def get_chat_llm(
    model: str | None = None,
    region_name: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = ASSISTANT_MAX_TOKENS,
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
        max_tokens: Maximum tokens to generate (defaults to ASSISTANT_MAX_TOKENS, 4096).
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
def _warn_if_truncated(response: Any) -> None:
    """Log a warning when the model stopped because it reached the output token limit."""
    metadata = getattr(response, "response_metadata", None) or {}
    if metadata.get("stopReason") == "max_tokens":
        logger.warning("LLM answer cut by the output token limit (ASSISTANT_MAX_TOKENS=%s)", ASSISTANT_MAX_TOKENS)


def _record_llm_result(response: Any, current_span: Any) -> None:
    """
    Store the token usage and a short output summary of an LLM call on its span.
    LangChain puts the usage in `response.usage_metadata`. Never raises: metrics
    must not break an answer.
    """
    try:
        _warn_if_truncated(response)
    except Exception:
        logger.debug("Could not check the stop reason", exc_info=True)
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

# Load precomputed tf-idf matrix with official street names to map directions to coordinates
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

STREETS_LIST: list[str] = []
TFIDF_VECTORIZER: Any = None
TFIDF_MATRIX: Any = None

try:
    with open(_PROCESSED_DIR / "streets_list.pkl", "rb") as _f:
        STREETS_LIST = pickle.load(_f)
    with open(_PROCESSED_DIR / "tfidf_vectorizer.pkl", "rb") as _f:
        TFIDF_VECTORIZER = pickle.load(_f)
    with open(_PROCESSED_DIR / "tfidf_matrix.pkl", "rb") as _f:
        TFIDF_MATRIX = pickle.load(_f)
    logger.info("Nomenclator TF-IDF model successfully loaded (%d streets)", len(STREETS_LIST))
except Exception as _exc:
    logger.warning(
        "Could not load nomenclator TF-IDF files from %s: %s. Address normalization tool will return empty matches.",
        _PROCESSED_DIR,
        _exc,
    )

SENSITIVITY = 0.1


def find_in_nomenclator(address: str) -> dict[str, list[str]]:
    """
    Args:
        address: a string indicating an address or part of it

        Returns a dictionary with 'match' item containing a list with the first ranked official addresses matching string up to a score distance less than SENSITIVITY (a global constant) from the first
    """
    if TFIDF_VECTORIZER is None or TFIDF_MATRIX is None or not STREETS_LIST:
        logger.warning("find_in_nomenclator called but nomenclator TF-IDF model is not loaded.")
        return {"match": []}

    try:
        query = TFIDF_VECTORIZER.transform([address])
        dp = (TFIDF_MATRIX @ query.T).toarray().ravel()
        ranking = sorted(zip(STREETS_LIST, dp, strict=True), key=lambda x: x[1], reverse=True)
        if not ranking or ranking[0][1] < 0.2:
            return {"match": []}
        res = []
        max_score = ranking[0][1]
        for doc, score in ranking:
            if max_score - score > SENSITIVITY:
                break
            res.append(doc)
        return {"match": res}
    except Exception as exc:
        logger.error("Error evaluating address in find_in_nomenclator: %s", exc)
        return {"match": []}


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

        if not res or not res.get("codi_districte"):
            return {"datos_distrito": None}

        lat = res.get("lat")
        lon = res.get("lon")
        zona_info = identificar_zona_pgm(lat, lon) if lat is not None and lon is not None else None
        zona_pgm = zona_info.get("zona_pgm") if zona_info else None
        if not zona_pgm and res.get("codi_districte"):
            zona_pgm = "nucli_antic" if res["codi_districte"] == 1 else "densificacio_urbana"

        with span("db", "district_scorecard_query"):
            cache_key = make_cache_key("chat_district_scorecard", res["codi_districte"])
            cached_row = cache_get_json(cache_key)
            if cached_row is not None:
                set_output("district found (redis cache hit)")
                return {
                    "datos_distrito": cached_row,
                    "codi_districte": res["codi_districte"],
                    "zona_pgm": zona_pgm,
                    "lat": lat,
                    "lon": lon,
                    "direccion_encontrada": res.get("direccion_encontrada"),
                }

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
            return {
                "datos_distrito": None,
                "codi_districte": res["codi_districte"],
                "zona_pgm": zona_pgm,
                "lat": lat,
                "lon": lon,
                "direccion_encontrada": res.get("direccion_encontrada"),
            }

        datos_dict = {k: float(v) if isinstance(v, Decimal) else v for k, v in dict(row).items()}
        cache_set_json(cache_key, datos_dict, TTL_DISTRICT_SECONDS)
        return {
            "datos_distrito": datos_dict,
            "codi_districte": res["codi_districte"],
            "zona_pgm": zona_pgm,
            "lat": lat,
            "lon": lon,
            "direccion_encontrada": res.get("direccion_encontrada"),
        }


def regulations_query(query: str) -> str:
    """
    RAG that provides information on regulatory and legal aspects.

    Args:
        query (str): Natural-language query.

    Returns:
        str: Built regulatory context from relevant chunks.
    """
    with span("agent", "tool_regulations_query", input_summary=f"{len(str(query))} chars"):
        cache_key = make_cache_key("regulations_query", query)
        cached_ctx = cache_get_json(cache_key)
        if cached_ctx is not None and isinstance(cached_ctx, str):
            set_output(f"{len(cached_ctx)} chars of context (redis cache hit)")
            return cached_ctx

        with Session(engine) as session:
            documents = retrieve_relevant_chunks_with_rerank(session=session, query=query)
        context = build_context(documents)
        if isinstance(context, str):
            if context:
                cache_set_json(cache_key, context, TTL_RAG_SECONDS)
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


#### TOOL BINDING & LLM INITIALIZATION
tools = [find_in_nomenclator, get_opportunity_score, regulations_query]
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
Dispones de tres herramientas para ayudarte en tu tarea:
1. find_in_nomenclator: devuelve una lista de direcciones oficiales que se corresponden a una direccion indicada como input
2. get_opportunity_score: devuelve un score a partir de una dirección en la ciudad de Barcelona.
3. regulations_query: Esta herramienta te permite obtener información sobre aspectos regulatorios y legales relacionados con la apertura de negocios en Barcelona.
Cuando identifiques una dirección o una calle o lgar en el prompt de usuario, usa find_in_nomenclator para intentar conretarlo:
    - Si no devuelve ninguna, responde al usuario diciéndole que no se ha encontrado esa dirección en Barcelona
    - Si devuelve más de una, responde con la lista y que debe escoger una
    - Solamente en case de devolver una sola, sigue adelante evaluando la necesidad de usar el resto de herramientas para responder al usuario
Cuando respondas a las consultas de los usuarios, asegúrate de proporcionar información precisa y relevante, y de citar las fuentes de información cuando sea posible.
Usa solamente datos que te proporcionen las herrmientas, de ningún otro lugar.
Lista las fuentes. Sé específico en cuales son.
Si no eres capaz dem responder a la petición del usuario con la información disponible, dilo claramente.
Responde siempre en español, aunque el usuario escriba en otro idioma.
Cuando necesites una herramienta, llámala directamente: no describas antes los pasos que vas a seguir.
Sé conciso: responde lo esencial sin repetir información.
No escribas tu razonamiento interno ni uses etiquetas como <thinking>: escribe solo la respuesta final para el usuario.
No admitas preguntas fuera del ámbito de de tu expertise
"""
)


#### CREATE AND COMPILE GRAPH WITH MEMORY

checkpointer = None
try:
    checkpointer_context = PostgresSaver.from_conn_string(resolve_database_url().replace("+psycopg2", ""))
    checkpointer = checkpointer_context.__enter__()
    checkpointer.setup()
except Exception as exc:
    logger.warning("Could not initialize PostgreSQL checkpointer: %s", exc)


def _node_assistant(state: State):
    """Main node of the assistant: receives a message state and returns a response generated by the language model."""
    summary = state.get("summary", "")
    if summary:
        system_message = f"Resumen de la conversación previa: {summary}"
        messages = [SystemMessage(content=system_message)] + state["messages"]
    else:
        messages = state["messages"]
    invoker = llm_with_tools or (llm.bind_tools(tools) if llm else get_chat_llm().bind_tools(tools))
    prompt = [sys_msg] + messages
    with span("llm", "llm_call", model=GENERATION_MODEL, input_summary=f"{len(prompt)} messages") as llm_span:
        response = invoker.invoke(prompt)
        _record_llm_result(response, llm_span)
    return {"messages": [response]}


# updates state['num_responses'], which keeps track of the number of answers given to the user
# if they exceed MAX_NUM_MESSAGES, the first NUM_MESSAGES_TO_SUMMARIZE are included in state['summary']
# and deleted from state['messages'] along with tool calling and tool response associated messages
def _node_summarize(state: State):
    num_responses = state.get("num_responses", 0) + 1
    if num_responses > MAX_NUM_MESSAGES:
        summary = state.get("summary", "")
        if summary:
            summary_message = f"""Actualiza el resumen de forma concisa teniendo en cuenta los mensajes que siguen.
                Este es un resumen de mensajes pasados:\n\n {summary}"""
        else:
            summary_message = "Crea un resumen conciso teniendo en cuenta los mensajes que siguen"

        # ToolMessages, HumanMessages and AiMessages with tool_calls are excluded, leaving the responses generated by de model to the user
        text = "nuevos mensajes a añadir al resumen de forma concisa:\n"
        num_ai_messages = 0
        last_msg_to_del_index = -1
        for m in state["messages"]:
            last_msg_to_del_index += 1
            if m.type == "ai" and not getattr(m, "tool_calls", []):
                text = text + "\n\n" + _extract_text_content(m.content)
                num_ai_messages += 1
                if num_ai_messages == NUM_MESSAGES_TO_SUMMARIZE:
                    break
        messages = [HumanMessage(content=summary_message + "\n\n" + text)]
        active_llm = llm or get_chat_llm()
        with span(
            "llm", "summarize_call", model=GENERATION_MODEL, input_summary=f"{len(messages)} messages"
        ) as llm_span:
            response = active_llm.invoke(messages)
            _record_llm_result(response, llm_span)

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
            # Intercept tool completion to emit spatial and report activation metadata to frontend
            if metadata.get("langgraph_node") == "tools":
                tool_name = getattr(chunk, "name", None) or (getattr(chunk, "additional_kwargs", {}) or {}).get("name")
                if tool_name == "get_opportunity_score":
                    raw_content = getattr(chunk, "content", None)
                    tool_data = None
                    if isinstance(raw_content, dict):
                        tool_data = raw_content
                    elif isinstance(raw_content, str):
                        try:
                            tool_data = json.loads(raw_content)
                        except Exception:
                            try:
                                import ast
                                import re

                                sanitized = re.sub(r"Decimal\((['\"]?)([\d.]+)\1\)", r"\2", raw_content)
                                tool_data = ast.literal_eval(sanitized)
                            except Exception:
                                pass
                        if not tool_data:
                            import re

                            m_dist = re.search(r"['\"]codi_districte['\"]:\s*(\d+)", raw_content)
                            m_zona = re.search(r"['\"]zona_pgm['\"]:\s*['\"]([^'\"]+)['\"]", raw_content)
                            m_lat = re.search(r"['\"]lat['\"]:\s*([-\d.]+)", raw_content)
                            m_lon = re.search(r"['\"]lon['\"]:\s*([-\d.]+)", raw_content)
                            m_dir = re.search(r"['\"]direccion_encontrada['\"]:\s*['\"]([^'\"]+)['\"]", raw_content)
                            if m_dist:
                                tool_data = {
                                    "codi_districte": int(m_dist.group(1)),
                                    "zona_pgm": m_zona.group(1) if m_zona else None,
                                    "lat": float(m_lat.group(1)) if m_lat else None,
                                    "lon": float(m_lon.group(1)) if m_lon else None,
                                    "direccion_encontrada": m_dir.group(1) if m_dir else None,
                                }
                    if tool_data and tool_data.get("codi_districte"):
                        zona_pgm = tool_data.get("zona_pgm") or (
                            "nucli_antic" if tool_data.get("codi_districte") == 1 else "densificacio_urbana"
                        )
                        yield {
                            "type": "ubicacion",
                            "tool": "get_opportunity_score",
                            "codi_districte": tool_data.get("codi_districte"),
                            "zona_pgm": zona_pgm,
                            "lat": tool_data.get("lat"),
                            "lon": tool_data.get("lon"),
                            "direccion_encontrada": tool_data.get("direccion_encontrada"),
                        }

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
        "viabilidad de abrir una discoteca en Carrer Paris",
        "claudiberenguer:47",
    )
    """ _print_stream(
        "y para un bar musical?",
        "claudiberenguer:27",
    )
    _print_stream(
        "hay algún tipo de normativa específica para bar musical?",
        "claudiberenguer:27",
    )
    _print_stream(
        "dime cuanto serían las tasas para una terraza de 15m2 en calle Creucoberta",
        "claudiberenguer:27",
    ) """
