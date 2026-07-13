"""
ingest.py — Ingests the NYC 311 CSV into a DuckDB file for fast OLAP queries.

Run this ONCE before starting the application:
    python scripts/ingest.py

Input  : data/311_Service_Requests_from_2010_to_Present.csv
Output : data/nyc_311.duckdb  (table: service_requests)

Date columns created_date / closed_date are VARCHAR in the raw CSV with the
format 'MM/DD/YYYY HH:MM:SS AM'.  This script adds proper TIMESTAMP columns
(created_dt, closed_dt) for fast date arithmetic without repeated casting.
"""

from __future__ import annotations

import os
import sys

import duckdb

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(_ROOT, "data", "nyc_311.duckdb")
CSV_PATH = os.path.join(_ROOT, "data", "311_Service_Requests_from_2010_to_Present.csv")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

if not os.path.exists(CSV_PATH):
    # Allow alternate naming (copy, etc.)
    _alt = os.path.join(_ROOT, "data", "311_Service_Requests_from_2010_to_Present copy.csv")
    if os.path.exists(_alt):
        CSV_PATH = _alt
    else:
        print(f"ERROR: CSV not found at {CSV_PATH}", file=sys.stderr)
        sys.exit(1)

print(f"Ingesting: {CSV_PATH}")
print(f"Target DB: {DB_PATH}")

conn = duckdb.connect(DB_PATH)

# ── 1. Load CSV ─────────────────────────────────────────────────────────────
print("[1/3] Loading CSV into DuckDB (this may take 30-60 s for large files)...")
conn.execute("DROP TABLE IF EXISTS service_requests")
conn.execute(f"""
    CREATE TABLE service_requests AS
    SELECT * FROM read_csv_auto(
        '{CSV_PATH.replace(chr(92), '/')}',
        normalize_names = TRUE,
        all_varchar      = TRUE,
        ignore_errors    = TRUE
    )
""")
row_count = conn.execute("SELECT COUNT(*) FROM service_requests").fetchone()[0]
print(f"    Loaded {row_count:,} rows.")

# ── 2. Add TIMESTAMP columns ─────────────────────────────────────────────────
# Raw format: '12/31/2015 11:59:45 PM'  →  strptime format: '%m/%d/%Y %I:%M:%S %p'
print("[2/3] Parsing date strings -> TIMESTAMP columns...")

for src_col, dst_col in [("created_date", "created_dt"), ("closed_date", "closed_dt")]:
    # Add column (skip if already exists from a previous run)
    try:
        conn.execute(f"ALTER TABLE service_requests ADD COLUMN {dst_col} TIMESTAMP")
    except Exception:
        pass  # already exists

    conn.execute(f"""
        UPDATE service_requests
        SET {dst_col} = TRY_STRPTIME({src_col}, '%m/%d/%Y %I:%M:%S %p')
        WHERE {src_col} IS NOT NULL AND {src_col} != ''
    """)
    filled = conn.execute(
        f"SELECT COUNT(*) FROM service_requests WHERE {dst_col} IS NOT NULL"
    ).fetchone()[0]
    print(f"    {dst_col}: {filled:,} rows parsed successfully.")

# ── 3. Index ─────────────────────────────────────────────────────────────────
print("[3/3] Creating indexes for common query patterns…")
for col in ("complaint_type", "borough", "incident_zip", "agency", "status"):
    try:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{col} ON service_requests ({col})"
        )
    except Exception:
        pass  # DuckDB may not support all index types in older versions

conn.close()
print("\n[OK] Ingestion complete. Database is ready.")
print(f"   File: {DB_PATH}")
