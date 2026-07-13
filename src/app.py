"""
app.py — Streamlit frontend for the NYC 311 Enterprise Data Analytics Agent.

Responsibilities:
  - Page config, CSS theming
  - Fail-fast environment validation
  - Chat session management (per-thread JSON persistence)
  - Live token/cost dashboard in sidebar
  - LangGraph invocation and streamed-result rendering
  - Permanent chart archiving per session
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import app as graph_app, selected_model

# ---------------------------------------------------------------------------
# Logging — guard against duplicate handlers on Streamlit hot-reload
# ---------------------------------------------------------------------------
logger = logging.getLogger("streamlit_app")
if not logger.handlers:
    _log_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "logs", "app.log")
    )
    os.makedirs(os.path.dirname(_log_path), exist_ok=True)
    _h_file = logging.FileHandler(_log_path, encoding="utf-8")
    _h_stream = logging.StreamHandler()
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    _h_file.setFormatter(_fmt)
    _h_stream.setFormatter(_fmt)
    logger.setLevel(logging.INFO)
    logger.addHandler(_h_file)
    logger.addHandler(_h_stream)
    logger.propagate = False

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="NYC 311 Data Agent",
    page_icon="🗽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Premium CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
        /* Gradient title */
        h1 {
            background: linear-gradient(90deg, #00d2ff 0%, #3a7bd5 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 800;
            margin-bottom: 1rem;
        }
        /* Chat bubbles */
        .stChatMessage {
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }
        /* Sidebar metric labels */
        [data-testid="stMetricLabel"] { font-size: 0.78rem; }
        /* Code blocks inside expanders */
        .stExpander pre { font-size: 0.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Fail-fast environment validation
# ---------------------------------------------------------------------------
_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "nyc_311.duckdb")
)
_issues: list[str] = []
if not os.environ.get("DEEPSEEK_API_KEY"):
    _issues.append("❌ `DEEPSEEK_API_KEY` not found in `.env`.")
if not os.path.exists(_DB_PATH):
    _issues.append(f"❌ DuckDB file not found: `{_DB_PATH}`. Run `scripts/ingest.py` first.")

if _issues:
    st.title("🗽 NYC 311 Data Agent")
    st.error("### 🛑 Cannot start — environment problems detected")
    for issue in _issues:
        st.error(issue)
    st.info("Fix the above, then restart with `.\\run.ps1`.")
    st.stop()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_HISTORY_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "logs", "sessions")
)
_OUTPUTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "outputs")
)
_CURRENT_PLOT = os.path.join(_OUTPUTS_DIR, "current_plot.png")
_IN_RATE = 0.14   # $/1 M input tokens  (deepseek-chat, July 2025)
_OUT_RATE = 0.28  # $/1 M output tokens

os.makedirs(_HISTORY_DIR, exist_ok=True)
os.makedirs(_OUTPUTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Session-history helpers
# ---------------------------------------------------------------------------

def _history_path(thread_id: str) -> str:
    return os.path.join(_HISTORY_DIR, f"{thread_id}.json")


def _load_history(thread_id: str) -> list[dict]:
    path = _history_path(thread_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt session file, resetting: %s", path)
    return []


def _save_history(thread_id: str, history: list[dict]) -> None:
    try:
        with open(_history_path(thread_id), "w", encoding="utf-8") as fh:
            json.dump(history, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.error("Failed to save history: %s", exc)


def _extract_text(content) -> str:
    """Safely extract plain text from LangChain message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


# ---------------------------------------------------------------------------
# Session-state initialisation
# ---------------------------------------------------------------------------
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    logger.info("New session: %s", st.session_state.thread_id)

if "chat_history" not in st.session_state:
    st.session_state.chat_history = _load_history(st.session_state.thread_id)

for _key in ("total_input_tokens", "total_output_tokens", "last_msg_count"):
    if _key not in st.session_state:
        st.session_state[_key] = 0

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 Chat Sessions")

    _session_files = sorted(
        [f.replace(".json", "") for f in os.listdir(_HISTORY_DIR) if f.endswith(".json")],
        key=lambda x: os.path.getmtime(_history_path(x)) if os.path.exists(_history_path(x)) else 0,
        reverse=True,
    )
    if st.session_state.thread_id not in _session_files:
        _session_files.insert(0, st.session_state.thread_id)

    _selected = st.selectbox(
        "Select Session",
        _session_files,
        index=_session_files.index(st.session_state.thread_id),
    )
    if _selected != st.session_state.thread_id:
        st.session_state.thread_id = _selected
        st.session_state.chat_history = _load_history(_selected)
        st.session_state.total_input_tokens = sum(
            m.get("input_tokens", 0) for m in st.session_state.chat_history
        )
        st.session_state.total_output_tokens = sum(
            m.get("output_tokens", 0) for m in st.session_state.chat_history
        )
        st.session_state.last_msg_count = 0
        st.rerun()

    st.markdown("---")
    if st.button("➕ New Chat Session", type="primary", use_container_width=True):
        # Clean up any stale current_plot from previous session
        if os.path.exists(_CURRENT_PLOT):
            os.remove(_CURRENT_PLOT)
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.chat_history = []
        st.session_state.total_input_tokens = 0
        st.session_state.total_output_tokens = 0
        st.session_state.last_msg_count = 0
        st.rerun()

    st.markdown("---")
    st.header("💸 Live Cost Dashboard")
    st.markdown(f"**Model:** `{selected_model}`")
    st.caption(f"Input: ${_IN_RATE}/1M · Output: ${_OUT_RATE}/1M")

    _cost_placeholder = st.empty()


def _render_cost() -> None:
    cost = (
        (st.session_state.total_input_tokens / 1_000_000) * _IN_RATE
        + (st.session_state.total_output_tokens / 1_000_000) * _OUT_RATE
    )
    with _cost_placeholder.container():
        col1, col2 = st.columns(2)
        col1.metric("Input Tokens", f"{st.session_state.total_input_tokens:,}")
        col2.metric("Output Tokens", f"{st.session_state.total_output_tokens:,}")
        st.metric("Session Cost", f"${cost:.5f}")


_render_cost()

# ---------------------------------------------------------------------------
# Main area — title + chat history
# ---------------------------------------------------------------------------
st.title("🗽 NYC 311 Data Agent")
st.caption("Powered by DeepSeek · DuckDB · LangGraph")

for _msg in st.session_state.chat_history:
    role = _msg.get("role")
    if role == "user":
        st.chat_message("user").write(_msg["content"])
    elif role == "assistant":
        st.chat_message("assistant").markdown(_extract_text(_msg["content"]))
    elif role == "image":
        with st.chat_message("assistant"):
            _img_path = _msg.get("content", "")
            if os.path.exists(_img_path):
                st.image(_img_path)
            else:
                st.warning("⚠️ Chart file no longer available.")
    elif role == "tool":
        with st.chat_message("assistant"):
            with st.expander("🔍 Tool Output"):
                _txt = str(_msg.get("content", ""))
                st.text(_txt[:3000] + (" [truncated]" if len(_txt) > 3000 else ""))

# ---------------------------------------------------------------------------
# Chat input + agent invocation
# ---------------------------------------------------------------------------
if _user_input := st.chat_input("Ask anything about NYC 311 data…"):
    logger.info("User: %s", _user_input)
    st.session_state.chat_history.append({"role": "user", "content": _user_input})
    st.chat_message("user").write(_user_input)

    with st.chat_message("assistant"):
        _placeholder = st.empty()
        _placeholder.markdown("⏳ Analyzing…")

        # Remove stale current_plot before each invocation
        if os.path.exists(_CURRENT_PLOT):
            os.remove(_CURRENT_PLOT)

        _config = {
            "configurable": {"thread_id": st.session_state.thread_id},
            "recursion_limit": 25,   # 25 tool-call cycles is more than enough
        }

        try:
            logger.info("Invoking LangGraph agent (thread=%s)…", st.session_state.thread_id)
            _result = graph_app.invoke(
                {"messages": [HumanMessage(content=_user_input)]},
                config=_config,
            )
            logger.info("Agent complete.")

            _all_msgs = _result["messages"]
            # Slice from the message count at the START of this turn
            _new_msgs = _all_msgs[st.session_state.last_msg_count + 1:]
            st.session_state.last_msg_count = len(_all_msgs)
            _placeholder.empty()

            for _m in _new_msgs:
                if isinstance(_m, ToolMessage):
                    with st.expander(f"🔍 Tool: {_m.name}"):
                        _tc = str(_m.content)
                        st.text(_tc[:3000] + (" [truncated]" if len(_tc) > 3000 else ""))
                    st.session_state.chat_history.append(
                        {"role": "tool", "content": str(_m.content)}
                    )

                elif isinstance(_m, AIMessage) and _m.content:
                    # Skip pre-tool "thinking" messages (they have tool_calls set)
                    if getattr(_m, "tool_calls", None):
                        continue

                    _in, _out = 0, 0
                    if getattr(_m, "usage_metadata", None):
                        _in = _m.usage_metadata.get("input_tokens", 0)
                        _out = _m.usage_metadata.get("output_tokens", 0)
                        st.session_state.total_input_tokens += _in
                        st.session_state.total_output_tokens += _out

                    _text = _extract_text(_m.content)
                    if _text.strip():
                        st.markdown(_text)
                    st.session_state.chat_history.append(
                        {
                            "role": "assistant",
                            "content": _text,
                            "input_tokens": _in,
                            "output_tokens": _out,
                        }
                    )

            _save_history(st.session_state.thread_id, st.session_state.chat_history)
            _render_cost()

            # Archive chart if one was generated this turn
            if os.path.exists(_CURRENT_PLOT):
                _perm = os.path.join(
                    _OUTPUTS_DIR,
                    f"{st.session_state.thread_id}_{int(time.time())}.png",
                )
                os.rename(_CURRENT_PLOT, _perm)
                st.image(_perm)
                st.session_state.chat_history.append({"role": "image", "content": _perm})
                _save_history(st.session_state.thread_id, st.session_state.chat_history)
                logger.info("Chart archived: %s", _perm)

        except Exception as _exc:
            _placeholder.empty()
            _err = str(_exc)
            logger.error("Agent error: %s", _exc, exc_info=True)

            if "402" in _err or "Insufficient Balance" in _err or "quota" in _err.lower():
                st.error("💳 **API credits exhausted.** Top up or replace the key in `.env`.")
            elif "recursion" in _err.lower():
                st.error(
                    "⚠️ **The agent got stuck in a loop** on this query. "
                    "Try rephrasing — e.g. be more specific about the date range or columns."
                )
            elif "authentication" in _err.lower() or "401" in _err:
                st.error("🔑 **Invalid API key.** Check `DEEPSEEK_API_KEY` in `.env`.")
            else:
                st.error(f"⚠️ **Unexpected error:** {_exc}")
                st.info("See `logs/app.log` for the full traceback.")
