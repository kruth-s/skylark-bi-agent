# Skylark Drones - Business Intelligence Agent Decision Log

**Candidate / Engineering Assessment**  
**Role:** AI / Backend Engineer  
**Project:** Monday.com Business Intelligence Agent  

---

## 1. Key Assumptions Made

1. **Read-Only Data Contract & Live Retrieval:**  
   The agent operates strictly in **read-only** mode against Monday.com boards (`Deals` and `Work Orders`). As specified in the prompt, raw CSV data is never hardcoded; live data is dynamically queried, paginated via GraphQL `items_page`, and processed on-the-fly.

2. **Sector Harmonization Taxonomy:**  
   The incoming data features messy, non-standardized sector strings (e.g., `"Power"`, `"Solar"`, `"Energy"`, `"Mining"`, `"Roads"`, `"Infra"`). We assumed a canonical 8-sector taxonomy (`Energy & Power`, `Mining & Minerals`, `Railways`, `Infrastructure & Construction`, `Telecom & Utilities`, `Agriculture & Forestry`, `Defence & Aerospace`, `Others`) to ensure resilient cross-board aggregation.

3. **Financial Realization & GST Semantics:**  
   - Pipeline value from Deals is treated as potential revenue.
   - Work Orders contain contracted values (`Excl. GST` and `Incl. GST`), actual billed values, and collected cash.
   - `Receivables = Billed (Incl. GST) - Collected (Incl. GST)`. When explicit receivables columns exist, priority account flags (`AR Priority`) are used to gauge liquidity risk exposure.

4. **Weighted Pipeline Heuristic:**  
   Where deal closure probability was qualitative (`High`, `Medium`, `Low`), we applied empirical weights ($0.80$, $0.50$, $0.20$ respectively) to provide founders with realistic probability-adjusted pipeline forecasts rather than inflated raw sums.

---

## 2. Trade-offs Chosen & Why

| Design Decision | Alternative Considered | Rationale & Trade-off |
| :--- | :--- | :--- |
| **In-Memory TTL Caching (120s)** | Querying Monday GraphQL on every single prompt keystroke | Eliminates API rate-limiting risks (`429 Too Many Requests`) and provides sub-millisecond response latency during multi-turn founder sessions while keeping data fresh. |
| **Deterministic BI Engine + LLM Insight Synthesis** | Pure LLM-generated SQL / Python code generation | **Zero hallucination in financial calculations**. Math (revenue, receivables, pipeline sums) is computed deterministically in Python/Pandas; the LLM/Agent layer focuses on intent classification, ambiguity resolution, and executive strategic synthesis. |
| **Hybrid Intent Parser + Ambiguity Detection** | Freeform unconstrained completion | Enables proactive clarifying questions whenever a query is underspecified (e.g., asking *"How are we doing?"*), preventing misleading or overly generic answers. |
| **FastAPI + Async REST Service** | CLI-only script | Provides an instant, testable REST API and modern interactive web console testable without complex local setup. |

---

## 3. How "Leadership Updates" Was Interpreted & Implemented

We interpreted the optional requirement **"The agent should help prepare data for leadership updates"** as a **C-Suite Executive Intelligence Briefing Workflow**:

1. **Executive Headline:** A high-level macro synthesis of overall business health across both sales pipeline and operational delivery.
2. **Financial Scorecard:** Consolidated active pipeline, weighted forecast, contract backlog, cash collected, and outstanding receivables.
3. **Sector Performance Matrix:** Cross-board synthesis mapping top-performing sectors and revenue realization rates.
4. **Operational Health:** Work order execution status (ongoing, completed, delayed) and quantity delivery fulfillment.
5. **Risk Matrix & Watchlist:** Immediate highlighting of high AR priority accounts, overdue collections, and data hygiene caveats.
6. **Strategic Action Items:** Actionable recommendations for the leadership team (e.g., accelerating milestone invoicing on completed projects).

---

## 4. What Would Be Done Differently With More Time

1. **OAuth 2.0 Multi-Tenant Monday App:** Convert the backend into an installable Monday.com app with webhook subscriptions for real-time delta updates instead of polling.
2. **Dynamic Vector/SQL Tool-Use (MCP Tool Server):** Integrate a full Model Context Protocol (MCP) server stdio/SSE bridge for plug-and-play compatibility with Claude Desktop and custom LLM sidecars.
3. **Predictive Churn & Revenue Forecasting:** Train lightweight time-series/ML models to predict payment default risks and deal slip probabilities based on historical cycle times.
4. **Export to Executive Formats:** Add automated one-click PDF and slide deck (`.pptx`) export for Monday morning board meetings.

---

## 5. Tech Stack Justification

- **Language & Runtime:** Python 3.13 — rich data science ecosystem (Pandas) and rapid API development.
- **Web Framework:** FastAPI + Uvicorn — high-performance async API with automatic OpenAPI documentation (`/docs`).
- **Data Engine:** Pandas & NumPy — vectorized calculations guaranteeing arithmetic accuracy.
- **Integration Layer:** Monday.com GraphQL v2 with cursor pagination and in-memory TTL caching.
- **Frontend Console:** Responsive Vanilla HTML5/CSS3 Dashboard with dark mode and zero client-side build steps.
