"""
agent.py — LangGraph agent definition for the NYC 311 Data Analytics Agent.

Architecture:
  entry → route_intent → [casual | agent] → (tools →)* agent → END

- route_intent  : Zero-cost semantic router. Sends greetings to a cheap
                  no-tools responder and data questions to the full SQL agent.
- call_casual   : LLM without tools. ~50 tokens per call.
- call_model    : LLM with SQL + visualization tools bound.
- ToolNode      : Executes the tool the LLM requested.
- MemorySaver   : In-process conversation memory (thread-scoped).
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, TypedDict

import duckdb
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tools import execute_sql_query, generate_visualization

load_dotenv()

# ---------------------------------------------------------------------------
# Logging — guard against duplicate handlers when Streamlit hot-reloads
# ---------------------------------------------------------------------------
logger = logging.getLogger("agent")
if not logger.handlers:
    _log_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "logs", "app.log")
    )
    os.makedirs(os.path.dirname(_log_path), exist_ok=True)
    _handler_file = logging.FileHandler(_log_path, encoding="utf-8")
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    _handler_file.setFormatter(_fmt)
    logger.setLevel(logging.INFO)
    logger.addHandler(_handler_file)
    logger.propagate = True


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
selected_model = "deepseek-chat"
_api_key = os.environ.get("DEEPSEEK_API_KEY", "")

logger.info("Initializing LLM: model=%s", selected_model)
llm = ChatOpenAI(
    model=selected_model,
    api_key=_api_key,
    base_url="https://api.deepseek.com",
    temperature=0,
    max_retries=2,
)

_tools = [execute_sql_query, generate_visualization]
llm_with_tools = llm.bind_tools(_tools)


# ---------------------------------------------------------------------------
# Dynamic schema — fetched once at boot, trimmed for token efficiency
# ---------------------------------------------------------------------------
# Only expose the analytically relevant columns to the LLM.
# The other ~35 columns (school-related, taxi, ferry, BBL, etc.) are
# rarely queried and bloat every single API call.
_USEFUL_COLUMNS = {
    "unique_key", "created_date", "closed_date",
    "agency", "agency_name",
    "complaint_type", "descriptor", "location_type",
    "incident_zip", "incident_address", "street_name", "city",
    "status", "borough", "community_board",
    "latitude", "longitude",
    "created_dt", "closed_dt",      # TIMESTAMP columns added during ingest
}


def get_live_schema() -> str:
    """Return a compact schema string for the `service_requests` table."""
    try:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "data", "nyc_311.duckdb")
        )
        with duckdb.connect(db_path, read_only=True) as conn:
            df = conn.execute("PRAGMA table_info('service_requests')").df()
        lines = [
            f"  {row['name']} ({row['type']})"
            for _, row in df.iterrows()
            if row["name"] in _USEFUL_COLUMNS
        ]
        return "\n".join(lines) if lines else "  (no schema available)"
    except Exception as exc:
        logger.error("Schema fetch failed: %s", exc)
        return "  (schema unavailable — check DuckDB path)"


LIVE_SCHEMA = get_live_schema()

# ---------------------------------------------------------------------------
# System prompt — plain string (never f-string) so .format() is safe
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a Senior Data Analyst Agent. Your job is to answer analytical questions
about the NYC 311 Service Requests dataset stored in a DuckDB database.

DATABASE
  Table : service_requests
  Columns (key subset):
{schema}

SQL RULES — follow these precisely:
  1. Only write DuckDB-compatible SELECT statements.
  2. NEVER use: DROP, DELETE, UPDATE, INSERT, CREATE, ALTER, TRUNCATE, COPY,
     ATTACH, DETACH, INSTALL, LOAD, or file-reading functions.
  3. Use TIMESTAMP columns created_dt / closed_dt for all date arithmetic.
     Example — days to close:
       epoch(closed_dt - created_dt) / 86400.0
  4. created_date / closed_date are VARCHAR. Cast with TRY_CAST if needed.
  5. CAST latitude/longitude to DOUBLE before numeric operations.
  6. Always alias computed columns: COUNT(*) AS total, AVG(...) AS avg_days.
  7. Use LIMIT to keep result sets manageable (≤ 20 rows for charts).

WORKFLOW
  Step 1 — Execute a SQL query with execute_sql_query.
  Step 2 — If a chart was requested, call generate_visualization with the
            SAME or a simplified query (LIMIT ≤ 15 for readability).
  Step 3 — Summarise findings in plain English referencing exact numbers
            from the tool output. Never invent figures.

EDGE CASES
  • If a query returns SQL_ERROR, diagnose and retry with a corrected query.
  • If the user asks something unrelated to NYC 311 data, politely decline.
  • If closed_dt values are NULL, exclude those rows: WHERE closed_dt IS NOT NULL.
"""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def route_intent(state: AgentState) -> str:
    """Zero-cost semantic router.

    Sends greetings/thanks to call_casual (no tools, ~50 tokens).
    Everything else goes to the full SQL agent.
    """
    raw = state["messages"][-1].content
    msg = (str(raw) if not isinstance(raw, str) else raw).lower().strip()

    # Exact-match or prefix-match casual triggers
    _casual = {
        "hi", "hello", "hey", "hiya", "sup", "yo",
        "who are you", "what are you",
        "thanks", "thank you", "thx", "ty",
        "bye", "goodbye", "good morning", "good evening", "good afternoon",
    }
    # Data-bearing keywords — any of these → route to agent
    _data_kw = {
        "data", "plot", "chart", "graph", "visuali", "analyz", "analys",
        "sql", "311", "complaint", "zip", "borough", "time", "date",
        "count", "average", "avg", "top", "show", "how many", "which",
        "percent", "%", "rate", "trend", "distribution", "break", "compar",
        "pie", "bar", "scatter", "line", "histogram", "map",
    }

    is_casual = (
        any(msg == t or msg.startswith(t + " ") or msg.startswith(t + ",") for t in _casual)
        and not any(kw in msg for kw in _data_kw)
        and len(msg.split()) < 10
    )

    route = "casual" if is_casual else "agent"
    logger.info("Router → %s | msg='%s'", route, msg[:80])
    return route


def call_casual(state: AgentState) -> dict:
    """Lightweight responder for greetings. Uses bare LLM (no tools)."""
    logger.info("Casual responder invoked.")
    sys = SystemMessage(
        content=(
            "You are a friendly data analytics assistant for NYC 311 data. "
            "The user sent a casual message. Respond warmly in 1–2 sentences "
            "and invite them to ask an analytical question about the data."
        )
    )
    response = llm.invoke([sys] + state["messages"])
    return {"messages": [response]}


def call_model(state: AgentState) -> dict:
    """Full SQL agent node — LLM with tools bound."""
    logger.info("Agent node invoked.")
    messages = state["messages"]
    # Prepend system prompt if not already present (first turn in this thread).
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT.format(schema=LIVE_SCHEMA))] + list(messages)
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """Route to tools if the LLM requested tool calls, else END."""
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None)
    if calls:
        names = [c.get("name", "?") if isinstance(c, dict) else getattr(c, "name", "?") for c in calls]
        logger.info("Tool calls requested: %s", names)
        return "tools"
    logger.info("Agent finished — no tool calls.")
    return END


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
_workflow = StateGraph(AgentState)
_workflow.add_node("agent", call_model)
_workflow.add_node("casual", call_casual)
_workflow.add_node("tools", ToolNode(_tools))

_workflow.set_conditional_entry_point(
    route_intent,
    {"agent": "agent", "casual": "casual"},
)
_workflow.add_conditional_edges("agent", should_continue)
_workflow.add_edge("tools", "agent")
_workflow.add_edge("casual", END)

memory = MemorySaver()
app = _workflow.compile(checkpointer=memory)
