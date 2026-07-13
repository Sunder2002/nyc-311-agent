"""
tools.py — Secure, production-grade tool definitions for the NYC 311 LangGraph agent.

Tools exposed to the LLM:
  - execute_sql_query  : Read-only DuckDB query executor with SQL firewall.
  - generate_visualization : Chart generator (bar/line/scatter/pie).
"""

from __future__ import annotations

import logging
import os
import re

import duckdb
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
from langchain_core.tools import tool

# Use non-interactive backend so matplotlib never tries to open a display window.
matplotlib.use("Agg")

logger = logging.getLogger("tools")

# Absolute-safe path to the DuckDB file (resolved relative to this module).
DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "nyc_311.duckdb"))
OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# SQL Firewall — word-boundary regex so `created_dt` is never blocked by CREATE
# ---------------------------------------------------------------------------
_FORBIDDEN_SQL = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|REPLACE|COPY|ATTACH|DETACH|INSTALL|LOAD)\b"
    r"|READ_CSV|READ_JSON|READ_PARQUET|WRITE_CSV|EXPORT",
    re.IGNORECASE,
)


@tool
def execute_sql_query(query: str) -> str:
    """Execute a read-only SQL SELECT query against the DuckDB service_requests table.

    Use this tool to answer quantitative questions: counts, aggregations,
    percentages, rankings, date-based calculations, and data exploration.
    The only table is `service_requests`.

    Args:
        query: A valid DuckDB SQL SELECT statement. Must not contain DDL or DML.

    Returns:
        Query results as a markdown table, or an error string.
    """
    logger.info("SQL Query requested:\n%s", query)

    # Security firewall — block any destructive statement.
    if _FORBIDDEN_SQL.search(query):
        logger.warning("Security firewall blocked query: %s", query)
        return (
            "SECURITY_BLOCK: Your query contains a forbidden keyword "
            "(DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/COPY/ATTACH etc.). "
            "Only SELECT statements are allowed. Please rewrite your query."
        )

    try:
        with duckdb.connect(DB_PATH, read_only=True) as conn:
            df = conn.execute(query).df()

        if df.empty:
            return "Query executed successfully but returned no results."

        # Cap display at 200 rows; return a note if truncated.
        if len(df) > 200:
            logger.info("Result truncated from %d to 200 rows.", len(df))
            return (
                f"Result truncated — showing 200 of {len(df)} rows:\n\n"
                + df.head(200).to_markdown(index=False)
            )

        logger.info("Query returned %d rows.", len(df))
        return df.to_markdown(index=False)

    except Exception as exc:
        logger.error("SQL execution error: %s", exc, exc_info=True)
        return f"SQL_ERROR: {exc}"


@tool
def generate_visualization(
    query: str,
    chart_type: str,
    x_col: str,
    y_col: str,
    title: str,
) -> str:
    """Generate a chart from SQL query results and save it for display in the UI.

    Run a SQL query, then render the results as a chart. The query should
    produce aggregated, plot-ready data (e.g. LIMIT 15 for readability).

    Args:
        query:      A SQL SELECT that returns the data to plot.
        chart_type: One of 'bar', 'horizontal_bar', 'line', 'scatter', 'pie'.
        x_col:      Column name for the X-axis (numeric length for horizontal_bar, or pie labels).
        y_col:      Column name for the Y-axis (categorical labels for horizontal_bar, or pie values).
        title:      Human-readable chart title.

    Returns:
        A status string. The UI reads the saved PNG automatically.
    """
    logger.info("Visualization requested — type=%s, x=%s, y=%s", chart_type, x_col, y_col)

    # Reuse the security firewall for the inner SQL.
    if _FORBIDDEN_SQL.search(query):
        logger.warning("Security firewall blocked visualization query.")
        return "SECURITY_BLOCK: Visualization query contains a forbidden keyword."

    try:
        with duckdb.connect(DB_PATH, read_only=True) as conn:
            df = conn.execute(query).df()
    except Exception as exc:
        logger.error("Visualization SQL error: %s", exc, exc_info=True)
        return f"SQL_ERROR fetching chart data: {exc}"

    if df.empty:
        return "No data returned by the query — cannot generate chart."

    if x_col not in df.columns or (chart_type != "pie" and y_col not in df.columns):
        available = ", ".join(df.columns)
        return (
            f"Column mismatch. Requested x='{x_col}', y='{y_col}'. "
            f"Available columns: {available}"
        )

    # --- Render ---
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        ct = chart_type.lower()

        if ct == "bar":
            sns.barplot(data=df, x=x_col, y=y_col, ax=ax)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
            plt.xticks(rotation=45, ha="right")

        elif ct == "horizontal_bar":
            sns.barplot(data=df, x=x_col, y=y_col, orient="h", ax=ax)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)

        elif ct == "line":
            sns.lineplot(data=df, x=x_col, y=y_col, ax=ax, marker="o")
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
            plt.xticks(rotation=45, ha="right")

        elif ct == "scatter":
            sns.scatterplot(data=df, x=x_col, y=y_col, ax=ax)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)

        elif ct == "pie":
            values = df[y_col].tolist()
            labels = df[x_col].tolist()
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=140)
            ax.set_aspect("equal")

        else:
            plt.close(fig)
            return (
                f"Unknown chart_type '{chart_type}'. "
                "Use one of: bar, horizontal_bar, line, scatter, pie."
            )

        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
        plt.tight_layout()

        out_path = os.path.join(OUT_DIR, "current_plot.png")
        if os.path.exists(out_path):
            os.remove(out_path)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info("Chart saved to %s", out_path)
        return f"Chart '{title}' generated and saved. The UI will display it automatically."

    except Exception as exc:
        plt.close("all")
        logger.error("Visualization render error: %s", exc, exc_info=True)
        return f"RENDER_ERROR: {exc}"
