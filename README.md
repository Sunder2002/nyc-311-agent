# NYC 311 Data Analytics Agent

A conversational analytics agent designed to query the NYC 311 Service Requests dataset. Built using LangGraph, DeepSeek, DuckDB, and Streamlit.

## Overview

This application provides a chat interface allowing users to ask natural-language questions about NYC 311 data. The agent translates these queries into DuckDB SQL, executes them securely, and optionally generates visual charts using Matplotlib and Seaborn.

The system is designed for high performance and low memory overhead by utilizing DuckDB's columnar OLAP engine, avoiding the memory constraints typical of Pandas-based analysis on large datasets.

## Architecture

```text
Streamlit UI
 ├── Chat Interface & Session Manager
 └── Live Cost Dashboard (Token tracking)
      │
      ▼
LangGraph Agent (Stateful, Multi-turn)
 ├── Semantic Router
 │    ├── Casual Intent (cheap LLM response, no tools)
 │    └── Analytical Intent (full SQL agent)
 │
 └── SQL Agent (DeepSeek)
      ├── execute_sql_query (Firewall-protected SELECTs)
      └── generate_visualization (Matplotlib/Seaborn)
           │
           ▼
DuckDB (nyc_311.duckdb)
 └── service_requests table
```

## Security Model

The system implements a dual-layer security model to prevent SQL injection and unauthorized data access:

1. **Application-Level Firewall**: A regex-based interceptor blocks any destructive DDL/DML commands (e.g., `DROP`, `DELETE`, `UPDATE`, `CREATE`) before they reach the database engine.
2. **Database-Level Protection**: DuckDB is initialized in read-only mode (`read_only=True`), enforcing strict isolation at the driver level.

## Repository Structure

```text
.
├── data/
│   └── nyc_311.duckdb            # Generated via scripts/ingest.py
├── scripts/
│   └── ingest.py                 # CSV parsing and TIMESTAMP creation
├── src/
│   ├── agent.py                  # LangGraph architecture & LLM setup
│   ├── app.py                    # Streamlit frontend & state management
│   └── tools.py                  # SQL execution and visualization tools
├── logs/                         # Structured application logs and session history
├── outputs/                      # Generated visualization artifacts
├── requirements.txt              # Pinned Python dependencies
└── run.ps1 / run.bat             # Windows startup scripts
```

## Setup Instructions

### 1. Requirements
- Python 3.11 or higher
- DeepSeek API key

### 2. Environment Setup
Clone the repository and initialize a virtual environment:

```bash
python -m venv venv
# Windows
.\venv\Scripts\Activate.ps1
# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configuration
Copy the environment template and add your API key:
```bash
cp .env.example .env
# Open .env and set DEEPSEEK_API_KEY
```

### 4. Data Ingestion
Place the raw CSV file `311_Service_Requests_from_2010_to_Present.csv` into the `data/` directory.

Run the ingestion script to build the DuckDB file and parse timestamps:
```bash
python scripts/ingest.py
```

### 5. Start the Application
```bash
.\run.ps1
```
The application will be available at `http://localhost:8501`.

## Example Queries

Once running, you can test the agent with the following queries:
- What are the top 10 complaint types by total volume?
- Which ZIP code has the highest number of complaints?
- For the top 5 complaint types, what percentage were closed within 3 days?
- Show me a bar chart of complaints by borough.
- What is the average resolution time in days for noise complaints?
