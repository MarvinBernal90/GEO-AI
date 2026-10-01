""" "
An agent is built in which an LLM processes the user prompt, breaks down the requested tasks, calls tools to complete them and, finally, when it considers it has all the information, composes a response for the user. This is a ReAct (Reasoning and Acting) architecture: https://www.ibm.com/think/topics/react-agent

It is an agent with per-user memory, which can choose to continue a previous conversation or start a new one. In the notebook each user is identified by a thread_id.
At the moment the agent has two tools:
- the model that infers the best places to locate a hospitality business given a set of characteristics (area, customer profile, characteristics of the service offered, etc.). It offers an API-style interface to the model. Since this is only an ad-hoc application, the use of MCP is not considered.
- a RAG that provides context on regulations and procedures.

The LangChain/LangGraph framework is used because it provides standard schemas that are considered particularly useful when getting started in this field: start generic so that it can evolve towards a specific provider or technology, if necessary.

The key feature of the model behind the agent, which decides whether a tool should be used, which one, and at what point it has all the information needed to finish, is 'reasoning'.
This was not done with Google because the generic project user (geoyield@gmail.com) cannot create an account in Google AI Studio. That is why groq is used: https://pricepertoken.com/endpoints/groq/free

The agent is designed with memory during the interaction, so that previous responses are added to the context. Each conversation has an identifier, so it can be resumed later. To avoid excessive growth of the context, the oldest messages are progressively added to a summary message at the base of the list.

Once the behaviour has been verified, user conversations will be persisted in postgis (https://docs.langchain.com/oss/python/langgraph/add-memory#example-using-postgres-checkpointer)
"""

import logging
import os
import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import MessagesState
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, "/home/claud/pontia/PJ")

from typing import Literal

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy import text

from backend.db.connection import resolve_database_url
from backend.geo.geocoding import geocodificar_direccion
from backend.rag.query_engine import build_context, retrieve_relevant_chunks_with_rerank

#### CONFIGURATION
logger = logging.getLogger("geoyield_agent")

load_dotenv()

GENERATION_MODEL = os.environ.get("GENERATION_MODEL", "models/gemini-3.6-flash")
MAX_NUM_MESSAGES = int(os.environ.get("MAX_NUM_MESSAGES", 5))
NUM_MESSGES_TO_SUMMARIZE = int(os.environ.get("NUM_MESSGES_TO_SUMMARIZE", 3))

GEODATA_BASEURL = resolve_database_url()

engine = create_engine(resolve_database_url())

#### STATE VARIABLE
# The predefined MessageState class holds a list of messages under the 'messages' key and the 'add_messages' reducer, which appends a message to the end of the queue and is used
# by LangChain to operate on a node's output (it adds the output message to the list).
# Each message has an 'id' field. If a message is added with an id that already exists, the message is overwritten. A message can be removed from the list with
# 'RemoveMessage(id)'

# The MessageState class is subclassed to introduce the 'summary' key, which holds a summary of messages. It is used to keep the context without increasing
# the number of tokens too much


class State(MessagesState):
    summary: str


#### TOOLS DEFINITION
def get_opportunity_score(dirección: str) -> float:
    """
    Returns a score for an address in the city of Barcelona.
    Calls the geocodificar_direccion function, which returns the district code among other data, and with it
    the 'district_scorecard' view is queried to return an opportunity_score.

    Args:
        a string representing an address in the city of Barcelona

    Returns:
        a float with the score (value between 0 and 1) or None if it cannot be processed
    """
    res = geocodificar_direccion(dirección)
    if res is not None:
        with Session(engine) as session:
            row = (
                session.execute(
                    text(
                        "SELECT ds.codi_districte, ds.nom_districte, ds.renta_media, ds.daily_foot_traffic, "
                        "ds.total_competitors, ds.opportunity_score, "
                        "dm.total_trips AS viajes_intraprovinciales, dm.predominant_age "
                        "FROM district_scorecard ds "
                        "LEFT JOIN district_mobility dm ON ds.codi_districte = dm.codi_districte "
                        "WHERE ds.codi_districte = :codi"
                    ),
                    {"codi": res["codi_districte"]},
                )
                .mappings()
                .first()
            )

        if row is None:
            logger.warning("No hay datos en district_scorecard para el distrito %s", res["codi_districte"])
            return {"datos_distrito": None}

        return {"datos_distrito": dict(row)}


def regulations_query(query: str) -> str:
    """
    RAG that provides information on regulatory and legal aspects.

    Args:
        query (str): Natural-language query.

    """
    documents = []
    with Session(engine) as session:
        documents = retrieve_relevant_chunks_with_rerank(session=session, query=query)
    return build_context(documents)


def summarize_conversation(state: State):
    if len(state["messages"]) > MAX_NUM_MESSAGES:
        summary = state.get("summary", "")
        if summary:
            summary_message = (
                f"Este es el resumen de la conversación hasta ahora: {summary}\n\n"
                "Extiende el resumen teniendo en cuenta los mensajes anteriores:"
            )
        else:
            summary_message = "Crea un resumen teniendo en cuenta los mensajes anteriores:"

        # the model, without tools, is called to generate the summary
        messages = state["messages"] + [HumanMessage(content=summary_message)]
        response = llm.invoke(messages)

        # Delete all but the 2 most recent messages
        num_messages_left = len(state["messages"]) - NUM_MESSGES_TO_SUMMARIZE
        delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][:-num_messages_left]]
        return {"summary": response.content, "messages": delete_messages}


#### TOOL BINDING
# the tools are bound so the model can reason about whether to use them to obtain information
# summarize_conversation is triggered deterministically by a 'router' based on the number of messages in the context
tools = [get_opportunity_score, regulations_query]
llm = ChatGoogleGenerativeAI(
    model=GENERATION_MODEL,
    temperature=0,
    max_retries=3,
)
llm_with_tools = llm.bind_tools(tools)

#### ASSISTANT
sys_msg = SystemMessage(
    content="""Eres un asistente experto en hostelería y restauración, especializado en la ciudad de Barcelona.
    Tu tarea es proporcionar información sobre aspectos regulatorios y legales relacionados con la apertura de negocios en esta ciudad y un opportunity_score
    Dispones de dos herramientas para ayudarte en tu tarea:
    1. get_opprotunity_score: devuelve un score a partir de una dirección en la ciudad de Barcelona.
    2. regulations_query: Esta herramienta te permite obtener información sobre aspectos regulatorios y legales relacionados con la apertura de negocios en Barcelona.
    Empieza la respuesta 'Dirección: [la dirección entrada en get_opportunity_score], score: [valor devuelto por get_opprotunity_score]
    Cuando respondas a las consultas de los usuarios, asegúrate de proporcionar información precisa y relevante, y de citar las fuentes de información cuando sea posible.
    Si no puedes encontrar información relevante, informa al usuario de que no se encontró información relevante."""
)


def assistant(state: State):
    """
    Main function of the assistant: receives a message state and returns a response generated by the language model.

    Args:
        state (MessagesState): Message state containing the current conversation.
        max_num_num_messages: when this number of messages in state['messages'] is exceeded, the first ones are replaced by a summary
        num_messages_to_summarize: the first 'num_messages_to_summarize' messages are summarized; must be less than 'max_num_messages'
    """

    summary = state.get("summary", "")
    if summary:
        system_message = f"Resumen de la conversación previa: {summary}"
        messages = [SystemMessage(content=system_message)] + state["messages"]
    else:
        messages = state["messages"]

    return {"messages": [llm_with_tools.invoke([sys_msg] + messages)]}


#### CREATE AND COMPILE GRAPH WITH MEMORY
# router that decides whether a summary should be created before going to the end
def summarize_check(state: State) -> Literal["summarize_conversation", END]:
    """Returns whether the next node is END or summarize_conversation"""

    if len(state["messages"]) > MAX_NUM_MESSAGES:
        return "summarize_conversation"
    return END


# Persistent memory in PostgreSQL
checkpointer_context = PostgresSaver.from_conn_string(resolve_database_url())
checkpointer = checkpointer_context.__enter__()
checkpointer.setup()

# Graph
builder = StateGraph(MessagesState)

# Node definitions
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_node("summarize", summarize_conversation)

# Definition of the connectors (edges) between nodes
builder.add_edge(START, "assistant")
# this connector routes to the tools if the last assistant message is a tool call, and towards the end otherwise
builder.add_conditional_edges("assistant", tools_condition, {"tools": "tools", "__end__": "summarize"})
builder.add_edge("tools", "assistant")
builder.add_edge("summarize", END)
react_graph = builder.compile(checkpointer=checkpointer)


#### ASSISTANT CALL FUNCTION
def request(content: str, thread: str) -> str:
    """ "
    Sends the user's latest request in the conversation thread to the chat assistant and returns the response

    Args:
        content: request text
        thread: conversation thread identifier

    Returns:
        a text with the assistant's response
    """
    messages = [{"role": "user", "content": {content}}]
    configurable = {"thread_id": thread}

    state = react_graph.invoke({"messages": messages}, {"configurable": configurable})

    return state["messages"][-1]


if __name__ == "__main__":
    print("para persistir la conversación me deberías dar tu usuario\nusuario:")
    print("quieres seguir alguna de estas conversacines o iniciar una nueva?")

    print(request(sys.argv[1], sys.argv[2]).text)
