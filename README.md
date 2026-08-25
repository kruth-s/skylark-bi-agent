# Skylark Drones - Monday.com Business Intelligence Agent

> **An intelligent, resilient, founder-level BI Agent that dynamically queries Monday.com Deals & Work Orders boards, cleans messy real-world data, resolves ambiguity, and generates strategic executive insights.**

---

## 🏛️ System Architecture

```
┌────────────────────────────────────────────────────────┐
│                        User                            │
└──────────────────────────┬─────────────────────────────┘
                           │ Natural Language Query
                           ▼
┌────────────────────────────────────────────────────────┐
│                   BI Agent (LLM)                       │
│    - Query Understanding & Intent Classification       │
│    - Ambiguity Detection & Clarifying Questions        │
│    - Tool Calling & Contextual Synthesis               │
└──────────────────────────┬─────────────────────────────┘
                           │ Structured Query / Intent
                           ▼
┌────────────────────────────────────────────────────────┐
│         MCP Server / Monday Data Tools Layer           │
│    - Dynamic GraphQL queries with pagination           │
│    - Token & Authentication management                 │
│    - Board caching & rate-limit resilience             │
└──────────────────────────┬─────────────────────────────┘
                           │ GraphQL Query (Read-Only)
                           ▼
┌────────────────────────────────────────────────────────┐
│                   Monday.com API                       │
│    - Deals Board (Sales Pipeline Data)                 │
│    - Work Orders Board (Project Execution Data)        │
└──────────────────────────┬─────────────────────────────┘
                           │ Raw JSON Records
                           ▼
┌────────────────────────────────────────────────────────┐
│               Data Resilience Layer                    │
│    - Null & Missing Value Handling                     │
│    - Multi-format Date Normalization                   │
│    - Sector & Status Naming Harmonization              │
│    - Schema Validation & Data Quality Caveats          │
└──────────────────────────┬─────────────────────────────┘
                           │ Cleaned & Unified DataFrames
                           ▼
┌────────────────────────────────────────────────────────┐
│                    BI Engine                           │
│    - Revenue Realization & Collections (Excl/Incl GST) │
│    - Pipeline Health (Stages, Value, Probabilities)    │
│    - Sector Analysis (Energy, Mining, Infra, etc.)     │
│    - Operational Metrics (WO Status, Delays, AR)       │
│    - Cross-Board Correlation (Deal <-> Work Order)     │
│    - Temporal & Quarterly Trend Analysis               │
└──────────────────────────┬─────────────────────────────┘
                           │ Computed Metrics & Evidence
                           ▼
┌────────────────────────────────────────────────────────┐
│      Insight Generator + Leadership Update Engine      │
│    - Contextual Strategic Synthesis                    │
│    - High-Impact Executive Summaries                   │
│    - Risk Matrix & Actionable Recommendations          │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│              Final Verified Answer / Output            │
└──────────────────────────┬─────────────────────────────┘
```

---

## Requirements to Implementation Mapping

| Requirement (Company Specification) | Implementation in Skylark BI Agent |
| :--- | :--- |
| **Monday.com Integration** | Dynamic GraphQL API queries with cursor-based pagination, token authentication via `.env`, read-only operations. |
| **Authentication** | Secure API token management with graceful error handling if missing or expired. |
| **Data Resilience** | Robust normalization layer: regex currency stripper, multi-format timestamp parser, sector aliasing, null imputation, and automated data quality audits. |
| **Query Understanding** | Intelligent query classifier supporting natural language business questions, keyword extraction, temporal scoping (quarterly, fiscal year), and entity linking. |
| **Clarifying Questions** | Dynamic detection of ambiguous or underspecified queries (e.g., unspecified sector, undefined timeframe, or missing metric scope) prompting targeted clarifying questions. |
| **Revenue Analysis** | Exact BI calculations for Billed Value (Excl/Incl GST), Collected Revenue, Outstanding Receivables, and Billing vs Collection variance. |
| **Pipeline Health** | Analysis of Total Pipeline Value, Stage Conversion Funnel (Leads, Qualified, Proposal, Won, Lost), Weighted Probability values, and Tentative Close dates. |
| **Sector Performance** | Unified cross-board sector aggregation (Energy/Power, Mining, Railways, Infra, Telecom, Agriculture, etc.) with deal volume, realization rates, and market share. |
| **Operational Metrics** | Work-order progress tracking: Execution Status, Backlog quantities, Delay flags, Invoice generation vs Collection turnaround, and AR priority accounts. |
| **Cross-Board Queries** | Seamless joining of Deals and Work Orders across common identifiers (Deal Name, Serial #, Company Name, Sector) to correlate sales pipeline with execution reality. |
| **Context & Insights** | High-level synthesis connecting raw data points to business implications (e.g., bottleneck warnings, conversion drop-offs, AR concentration risks). |
| **Leadership Updates** | Dedicated executive-ready briefing workflow generating structured executive KPI dashboards, operational risks, revenue outlook, and strategic next steps. |

## Response Output Contract

Every completed chatbot response is designed to communicate:

- **Interpretation:** what the founder-level question means.
- **Evidence:** the verified record or metric from the live Deals and/or Work Orders board.
- **Insight:** the business meaning of the result, without shifting arithmetic to the LLM.
- **Caveats:** missing, null, normalized, filtered, or incomplete data that could affect interpretation.

Financial calculations are performed by Python/Pandas and supplied to the optional Groq explanation layer as authoritative evidence. The LLM may explain the result, but it must not calculate, replace, or invent values.

## Assignment Acceptance Checklist

- [x] Monday.com integration implemented with the GraphQL API.
- [x] Monday API authentication loaded from environment configuration.
- [x] Pooled HTTP connections, timeouts, retries, backoff, and `Retry-After` handling implemented.
- [x] Deals board ID loaded dynamically from `MONDAY_DEALS_BOARD_ID`.
- [x] Work Orders board ID loaded dynamically from `MONDAY_WORK_ORDERS_BOARD_ID`.
- [x] All items from both boards fetched dynamically with cursor pagination.
- [x] Monday integration is read-only; no mutation operations are present.
- [x] Missing and null values handled without stopping the normalization pipeline.
- [x] Dates normalized to UTC timestamps.
- [x] Currency and numeric text normalized to numeric values.
- [x] Inconsistent sectors and categories normalized to canonical values.
- [x] Original source values preserved in `__source` columns for traceability.
- [x] Data quality audits report missing values and caveats to users.
- [x] Founder-level intent detection implemented for pipeline, revenue, operations, sectors, and leadership updates.
- [x] Ambiguous questions return clarifying questions.
- [x] Deterministic Python calculations handle pipeline, revenue, receivables, sectors, and operations.
- [x] Cross-board sector performance combines Deals and Work Orders data.
- [x] Leadership update preparation includes scorecard, risks, recommendations, and data caveats.
- [x] Chat UI sends natural-language questions to `POST /api/query`.
- [x] Automated test suite passes (`7 passed`).

### Deliberate Scope Choices

- [x] Monday API was selected instead of MCP; the assignment allows either option.
- [ ] OAuth multi-tenant Monday app; not required for this single-workspace assignment.
- [ ] Persistent database or distributed cache; not required for the current read-only BI workflow.
- [ ] LLM arithmetic; intentionally excluded so financial calculations remain deterministic in Python.

---

## 🚀 Quick Start & Setup

### 1. Environment Configuration

Create or edit `.env` in the `skylark-bi-agent` directory:

```env
MONDAY_API_TOKEN=your_monday_api_token
MONDAY_DEALS_BOARD_ID=5030843498
MONDAY_WORK_ORDERS_BOARD_ID=5030843991
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the Backend API & Interactive Dashboard

Run using standard Python:

```bash
python api_server.py
```

Or via Python's module runner:

```bash
python -m uvicorn api_server:app --reload --port 8000
```

Open your browser at **`http://localhost:8000`** to access the interactive web interface and chat console.

API Documentation is accessible at **`http://localhost:8000/docs`**.

---

## 🧪 Running the Test Suite

Execute the full suite of automated unit and integration tests:

```bash
python -m pytest test_bi_agent.py -v
```

All 7 test suites verify:
- Monday GraphQL connection and schema introspection
- Data resilience, null handling, and sector harmonization
- BI Engine arithmetic (Pipeline, Revenue, Operations)
- Ambiguity detection and clarifying question triggers
- Leadership update briefing generation
- REST API endpoint contracts

---

## 📡 API Endpoints Reference

- **`POST /api/query`**: Process natural language queries with intent classification, ambiguity resolution, and contextual insights.
- **`GET /api/leadership-update`**: Fetch executive leadership briefing with financial scorecards, sector highlights, operational status, risk matrix, and strategic recommendations.
- **`GET /api/metrics/summary`**: Retrieve high-level consolidated KPI scorecard.
- **`GET /api/data-quality`**: Audit data hygiene, completeness rates, and data caveats.
- **`GET /api/boards/status`**: Verify live Monday.com connection health and record counts.
- **`GET /api/health`**: Service health check.

---

## 📁 Repository Structure

```
skylark-bi-agent/
├── monday_client.py       # Monday.com GraphQL API client with cursor pagination and caching
├── data_normalizer.py     # Data resilience, null handling, sector mapping, data quality audit
├── bi_engine.py           # Core analytics engine (Revenue, Pipeline, Sector, Operations)
├── agent_service.py       # Query understanding, ambiguity detection, insight generator
├── leadership_updater.py  # Dedicated executive leadership update generator
├── api_server.py          # FastAPI application & web console UI
├── test_bi_agent.py       # Pytest unit & integration test suite
├── DECISION_LOG.md        # 2-page decision log (assumptions, trade-offs, architecture)
├── requirements.txt       # Python dependencies
└── .env                   # Configuration & API tokens
```
