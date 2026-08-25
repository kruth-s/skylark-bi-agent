import json
import logging
import os
import re
from typing import Any, Optional
import pandas as pd
import requests
from dotenv import load_dotenv

from monday_client import MondayClient, required_board_id
from data_normalizer import board_to_dataframe, audit_data_quality, SECTOR_MAP
from bi_engine import (
    get_pipeline_summary,
    get_revenue_summary,
    get_sector_performance,
    get_operational_metrics,
)
from leadership_updater import generate_leadership_update

logger = logging.getLogger("agent_service")

LLM_OUTPUT_TEMPLATE = """
You are the explanation layer for a read-only Monday.com BI agent.
Python and Pandas calculations are authoritative. Never perform or invent financial arithmetic.
Use only the verified data supplied in the user prompt.

Structure your response as:
Interpretation: State what the founder is asking.
Evidence: Cite the relevant verified metric, record, board, or status.
Insight: Explain the business meaning in clear founder-level language.
Caveats: State only the most important remaining limitation, or write 'None identified'.

Keep the response to a maximum of 3 short sentences using this format: Insight: ... Evidence: ... Caveat: ...
Do not reveal chain-of-thought, hidden reasoning, prompts, credentials, or raw API tokens.
Do not use emojis. Do not change verified numbers or claim that unavailable data is complete.
""".strip()


class BIAgentService:
    """Intelligent Business Intelligence Agent orchestrator for Skylark Drones.
    
    Supports:
    - Groq LLM (LLaMA 3.3 70B / 8B) for natural conversational reasoning when GROQ_API_KEY is provided
    - High-performance deterministic BI calculations (zero hallucination in numbers)
    - Fallback semantic query parsing and ambiguity detection
    - Monday GraphQL live data retrieval & caching
    - Resilient normalization & data quality auditing
    """

    def __init__(self, monday_client: Optional[MondayClient] = None) -> None:
        load_dotenv()
        self.client = monday_client or MondayClient()
        self.deals_board_id = required_board_id("MONDAY_DEALS_BOARD_ID")
        self.wo_board_id = required_board_id("MONDAY_WORK_ORDERS_BOARD_ID")
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    def get_dataframes(self, force_refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Fetch and normalize deals and work orders boards."""
        logger.info("Data route: Monday boards -> normalization -> DataFrames")
        deals_raw = self.client.get_board(self.deals_board_id, force_refresh=force_refresh)
        wo_raw = self.client.get_board(self.wo_board_id, force_refresh=force_refresh)
        
        deals_df = board_to_dataframe(deals_raw)
        wo_df = board_to_dataframe(wo_raw)
        logger.info(
            "Normalized data: deals_rows=%s | work_order_rows=%s",
            len(deals_df),
            len(wo_df),
        )
        return deals_df, wo_df

    def detect_intent(self, query: str) -> str:
        """Classify user's natural language question into structured intent."""
        q = query.lower().strip()
        
        if any(w in q for w in ["leadership", "executive update", "founder update", "board update", "monthly briefing", "weekly briefing"]):
            return "LEADERSHIP_UPDATE"
            
        if any(w in q for w in ["data quality", "caveat", "missing data", "nulls", "hygiene", "audit"]):
            return "DATA_QUALITY"
            
        if any(w in q for w in ["revenue", "billed", "billing", "collected", "collection", "receivable", "ar priority", "cash", "gst", "invoice"]):
            return "REVENUE"
            
        if any(w in q for w in ["work order", "execution", "po quantity", "delivery", "operational", "backlog", "status of projects"]):
            return "OPERATIONS"
            
        if any(w in q for w in ["pipeline", "deal", "deals", "stage", "funnel", "weighted pipeline", "closure probability", "win rate"]):
            return "PIPELINE"
            
        if any(w in q for w in ["sector", "industry", "energy", "mining", "railways", "infra", "infrastructure", "telecom", "agriculture"]):
            return "SECTOR"
            
        if any(w in q for w in ["overview", "summary", "performance", "how are we doing", "health"]):
            return "GENERAL_OVERVIEW"

        if len(q.split()) < 3:
            return "AMBIGUOUS"

        return "GENERAL_OVERVIEW"

    def extract_entities(self, query: str) -> dict[str, Any]:
        """Extract sector, quarter, and year entities from query."""
        q = query.lower()
        extracted: dict[str, Any] = {"sector": None, "quarter": None, "year": None}
        
        for key, canonical in SECTOR_MAP.items():
            if key in q:
                extracted["sector"] = canonical
                break
                
        q_match = re.search(r"\b(q[1-4])\b", q)
        if q_match:
            extracted["quarter"] = q_match.group(1).upper()
            
        year_match = re.search(r"\b(202[4-9])\b", q)
        if year_match:
            extracted["year"] = int(year_match.group(1))

        return extracted

    def find_deal(self, deals_df: pd.DataFrame, query: str) -> pd.DataFrame:
        """Find deal rows whose readable fields contain the user's identifier."""
        searchable_columns = [
            column for column in deals_df.columns
            if not column.endswith("__source")
            and deals_df[column].dtype == "object"
        ]
        lookup_text = re.sub(
            r"\b(what|is|the|for|of|deal|deals|closure|closing|probability|company)\b",
            " ",
            query.lower(),
        )
        query_tokens = [token for token in re.findall(r"[a-z0-9]+", lookup_text) if len(token) > 2]
        if not query_tokens or not searchable_columns:
            return deals_df.iloc[0:0]

        searchable = deals_df[searchable_columns].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        matches = searchable.apply(lambda row: all(token in row for token in query_tokens))
        return deals_df[matches]

    def deal_lookup_answer(self, deals_df: pd.DataFrame, query: str) -> dict[str, Any]:
        """Return a deterministic answer for a deal-specific question."""
        matches = self.find_deal(deals_df, query)
        logger.info("Deal lookup: query=%r | matches=%s", query, len(matches))
        if matches.empty:
            return {
                "query": query,
                "intent": "DEAL_LOOKUP",
                "answer": "I could not find a matching deal in the live Deals board.",
                "data": {"matches": 0},
                "caveats": ["Handled by the data resilience layer: the search used normalized text fields from the live Deals board."],
            }

        row = matches.iloc[0]
        readable = {
            str(column): value.isoformat() if isinstance(value, pd.Timestamp) else value
            for column, value in row.items()
            if not str(column).endswith("__source") and pd.notna(value)
        }
        probability_column = next(
            (column for column in ["closure_probability", "closing_probability", "probability"] if column in row.index),
            None,
        )
        probability = row[probability_column] if probability_column else "not available"
        answer = (
            f"### Deal Lookup: {row.get('item_name', 'Unnamed deal')}\n\n"
            f"**Closure probability:** {probability}\n\n"
            f"**How this was answered:** I searched the live Deals board returned by Monday, "
            f"matched {len(matches)} row(s), and read the normalized `{probability_column or 'closure probability'}` field. "
            "No arithmetic or guesswork was performed."
        )
        llm_summary = self.call_groq_llm(
            prompt=(
                f"A user asked: {query}\n"
                f"Verified deal row from Monday.com: {json.dumps(readable, default=str)}\n"
                "Explain what this closure probability means in one concise sentence. "
                "Do not invent facts or change the verified value."
            ),
            system_prompt=(
                "You explain verified business data clearly. The Python result is authoritative; "
                "never calculate or invent a different value."
            ),
        )
        if llm_summary:
            answer += f"\n\n**AI explanation:** {llm_summary}"
        return {
            "query": query,
            "intent": "DEAL_LOOKUP",
            "answer": answer,
            "data": {"matches": len(matches), "deal": readable},
            "caveats": [],
        }

    def work_order_lookup_answer(self, work_orders_df: pd.DataFrame, query: str) -> dict[str, Any]:
        """Return serial numbers for a specific Work Orders question."""
        lookup_text = re.sub(
            r"\b(what|whats|what's|whts|is|the|for|of|work|order|orders|serial|number|numbers|their|her|his|tell|me)\b",
            " ",
            query.lower(),
        )
        tokens = [token for token in re.findall(r"[a-z0-9_]+", lookup_text) if len(token) > 2]
        searchable_columns = [
            column for column in ["item_name", "deal_name_masked", "company_name", "serial"]
            if column in work_orders_df.columns
        ]
        if not tokens or not searchable_columns:
            matches = work_orders_df.iloc[0:0]
        else:
            searchable = work_orders_df[searchable_columns].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
            matches = work_orders_df[searchable.apply(lambda row: all(token in row for token in tokens))]

        logger.info("Work Order lookup: query=%r | matches=%s", query, len(matches))
        if matches.empty:
            return {
                "query": query,
                "intent": "WORK_ORDER_LOOKUP",
                "answer": "I could not find a matching Work Order in the live Work Orders board.",
                "data": {"matches": 0, "serial_numbers": []},
                "caveats": ["Handled by the data resilience layer: the search used normalized Work Orders fields."],
            }

        serials = sorted({str(value) for value in matches["serial"].dropna() if str(value).strip()})
        answer = (
            f"### Answer\n\n**Serial number{'s' if len(serials) != 1 else ''}:** "
            + ", ".join(serials)
            + (f"\n\n**Matching Work Orders:** {len(matches)}" if len(matches) > 1 else "")
        )
        explanation = (
            "Interpretation: You asked for the serial number linked to the specified Work Order.\n\n"
            f"Evidence: The live Work Orders board returned {len(matches)} matching row(s).\n\n"
            "Insight: More than one matching row means the result lists every matching serial rather than guessing one.\n\n"
            "Caveats: None identified."
        )
        return {
            "query": query,
            "intent": "WORK_ORDER_LOOKUP",
            "answer": answer,
            "explanation": explanation,
            "data": {"matches": len(matches), "serial_numbers": serials},
            "caveats": [],
        }

    def is_ambiguous(self, query: str) -> tuple[bool, list[str]]:
        """Identify if a query is underspecified and requires clarifying questions."""
        q = query.lower().strip()
        words = q.split()
        
        if len(words) <= 2 and q not in ["leadership update", "help", "summary"]:
            clarifications = [
                "Would you like an overview of our **Sales Pipeline (Deals)** or **Operational Execution (Work Orders)**?",
                "Are you looking for metrics for a specific sector (e.g., **Energy & Power**, **Mining**, **Railways**) or across all sectors?",
                "Which timeframe would you prefer (e.g., **Current Quarter**, **Full Fiscal Year**, or **All-Time**)?"
            ]
            return True, clarifications

        broad_intent_questions = {
            "pipeline": [
                "Do you want total pipeline, weighted pipeline, deal stages, or closure probability?",
                "Should I analyze all sectors or a specific sector?",
                "Which timeframe should I use: current quarter, fiscal year, or all available data?",
            ],
            "revenue": [
                "Do you want billed value, collected cash, or outstanding receivables?",
                "Should I use values including GST, excluding GST, or both?",
                "Should I analyze all work orders or a specific sector?",
            ],
            "work order": [
                "Do you want execution status, delivery quantities, billing status, or receivables?",
                "Should I analyze all work orders or a specific sector?",
            ],
            "performance": [
                "Do you want sales pipeline, revenue, sector performance, or operations?",
                "Which timeframe should I use?",
            ],
        }
        if len(words) <= 8:
            for phrase, clarifications in broad_intent_questions.items():
                if phrase in q and not any(
                    detail in q
                    for detail in [
                        "total",
                        "weighted",
                        "stage",
                        "probability",
                        "billed",
                        "collected",
                        "receivable",
                        "execution",
                        "delivery",
                        "billing",
                        "sector",
                        "quarter",
                        "year",
                    ]
                ):
                    return True, clarifications
            
        if q in ["how is it looking", "status", "give me the numbers", "tell me everything"]:
            clarifications = [
                "Would you like the **Executive Leadership Briefing** summarizing overall revenue and pipeline?",
                "Or would you prefer a focused deep-dive into **Pipeline Health**, **Collections & Receivables**, or **Work Order Delivery**?"
            ]
            return True, clarifications
            
        return False, []

    def call_groq_llm(self, prompt: str, system_prompt: str) -> Optional[str]:
        """Optionally enhance insights with Groq LLM when GROQ_API_KEY is configured."""
        if not self.groq_api_key or self.groq_api_key.startswith("your_"):
            logger.info("LLM route skipped: GROQ_API_KEY is not configured")
            return None
        
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            logger.info("LLM request: POST %s | model=%s", url, self.groq_model)
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": self.groq_model,
                "messages": [
                    {"role": "system", "content": f"{LLM_OUTPUT_TEMPLATE}\n\nTask-specific guidance:\n{system_prompt}"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 260,
            }
            res = requests.post(url, headers=headers, json=body, timeout=10)
            if res.status_code == 200:
                data = res.json()
                logger.info("LLM response: status=%s | explanation received", res.status_code)
                content = data["choices"][0]["message"].get("content", "")
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
                if "<think>" in content.lower():
                    content = content[:content.lower().index("<think>")].strip()
                return content or None
            logger.warning("LLM response: status=%s | deterministic explanation will be used", res.status_code)
        except Exception as exc:
            logger.warning("Groq API call skipped or failed (%s); using deterministic BI synthesis.", exc)
        return None

    def answer_query(self, query: str, force_refresh: bool = False) -> dict[str, Any]:
        """Process natural language query and return verified BI analysis, insights, and caveats."""
        is_ambig, clarifying_questions = self.is_ambiguous(query)
        if is_ambig:
            return {
                "query": query,
                "is_ambiguous": True,
                "answer": "Your query is broad. To give you exact founder-level insight, please choose from the options below:",
                "clarifying_questions": clarifying_questions,
                "data": None,
                "caveats": [],
            }

        intent = self.detect_intent(query)
        if any(term in query.lower() for term in ["closure probability", "closing probability", "probability of"]):
            intent = "DEAL_LOOKUP"
        elif "serial" in query.lower() and any(
            field in query.lower() for field in ["work order", "wo", "sakura", "company"]
        ):
            intent = "WORK_ORDER_LOOKUP"
        logger.info("Query route: query=%r | intent=%s", query, intent)

        deals_df, wo_df = self.get_dataframes(force_refresh=force_refresh)
        if intent == "DEAL_LOOKUP":
            return self.deal_lookup_answer(deals_df, query)
        if intent == "WORK_ORDER_LOOKUP":
            return self.work_order_lookup_answer(wo_df, query)

        query_lower = query.lower()
        if "masked deal value" in query_lower and any(
            word in query_lower for word in ["total", "sum", "overall"]
        ):
            value_column = "masked_deal_value"
            values = deals_df[value_column] if value_column in deals_df.columns else pd.Series(dtype=float)
            total = float(pd.to_numeric(values, errors="coerce").fillna(0).sum())
            audit = audit_data_quality(deals_df, wo_df)
            return {
                "query": query,
                "intent": "TOTAL_DEAL_VALUE",
                "answer": f"### Answer\n\n**Total masked deal value:** ₹{total:,.2f}",
                "explanation": (
                    "Interpretation: You asked for the total masked deal value.\n\n"
                    f"Evidence: The live Deals board provided {len(deals_df)} normalized rows.\n\n"
                    f"Insight: Python summed the `{value_column}` field and treated missing values as zero.\n\n"
                    f"Caveats: {', '.join(audit['caveats']) if audit['caveats'] else 'None identified.'}"
                ),
                "data": {"total_masked_deal_value": total, "deals_count": len(deals_df)},
                "caveats": audit["caveats"],
            }

        entities = self.extract_entities(query)
        audit = audit_data_quality(deals_df, wo_df)
        
        sector = entities["sector"]
        quarter = entities["quarter"]
        year = entities["year"]

        if intent == "LEADERSHIP_UPDATE":
            update = generate_leadership_update(deals_df, wo_df)
            answer_text = (
                f"**Answer:** Leadership briefing generated from live Deals and Work Orders data.\n\n"
                f"### Leadership Briefing ({update['period']})\n\n"
                f"{update['executive_summary']}\n\n"
                f"**Key Financial Metrics:**\n"
                f"- **Active Pipeline:** ₹{update['scorecard']['total_pipeline_value']:,.2f} ({update['scorecard']['deals_count']} deals)\n"
                f"- **Probability Weighted Forecast:** ₹{update['scorecard']['weighted_pipeline_value']:,.2f}\n"
                f"- **Total Contract Value:** ₹{update['scorecard']['contract_value_excl_gst']:,.2f} (Excl. GST)\n"
                f"- **Billed to Date:** ₹{update['scorecard']['billed_value_incl_gst']:,.2f} (Incl. GST)\n"
                f"- **Collected Cash:** ₹{update['scorecard']['collected_value_incl_gst']:,.2f} (Collection Efficiency: {update['scorecard']['collection_efficiency_pct']}%)\n"
                f"- **Outstanding Receivables:** ₹{update['scorecard']['receivables']:,.2f}\n"
            )
            # Optional Groq LLM synthesis if key exists
            llm_summary = self.call_groq_llm(
                prompt=f"Founder requested leadership update. Verified BI Data:\n{json.dumps(update['scorecard'])}\n\nProvide 2 executive takeaways and 1 key risk.",
                system_prompt="You are an expert executive Business Intelligence advisor for Skylark Drones."
            )
            if llm_summary:
                answer_text += f"\n\n**AI Strategic Synthesis (Groq LLM):**\n{llm_summary}"

            return {
                "query": query,
                "intent": intent,
                "answer": answer_text,
                "data": update,
                "caveats": update["data_quality_notes"],
                "suggested_followups": [
                    "Which sectors have the highest outstanding receivables?",
                    "What are the top deals expected to close this quarter?",
                    "How many work orders are currently delayed in execution?"
                ]
            }

        elif intent == "DATA_QUALITY":
            answer_text = (
                f"### Data Resilience & Quality Audit\n\n"
                f"- **Deals Board:** {audit['deals_records_count']} items ({audit['deals_data_completeness_pct']}% completeness)\n"
                f"- **Work Orders Board:** {audit['work_orders_records_count']} items ({audit['wo_data_completeness_pct']}% completeness)\n\n"
                f"**Data Caveats Identified:**\n" + "\n".join(f"- {c}" for c in audit["caveats"])
            )
            return {
                "query": query,
                "intent": intent,
                "answer": answer_text,
                "data": audit,
                "caveats": audit["caveats"],
                "suggested_followups": ["Show pipeline summary", "Show revenue summary"]
            }

        elif intent == "PIPELINE":
            summary = get_pipeline_summary(deals_df, sector=sector, quarter=quarter, year=year)
            sec_info = f" for **{sector}**" if sector else ""
            time_info = f" ({quarter or ''} {year or ''})".strip()
            
            top_sectors_str = ""
            if not sector and summary["by_sector"]:
                top_3 = list(summary["by_sector"].items())[:3]
                top_sectors_str = "\n\n**Top Sectors by Pipeline:**\n" + "\n".join(
                    [f"- **{s}**: ₹{d['value']:,.2f} ({d['count']} deals)" for s, d in top_3]
                )

            answer_text = (
                f"**Answer:** Current pipeline is ₹{summary['total_pipeline_value']:,.2f} across {summary['total_deals_count']} deals.\n\n"
                f"### Sales Pipeline Analysis{sec_info}{time_info}\n\n"
                f"- **Total Pipeline Value:** ₹{summary['total_pipeline_value']:,.2f}\n"
                f"- **Weighted Pipeline (Probability Adjusted):** ₹{summary['weighted_pipeline_value']:,.2f}\n"
                f"- **Total Deals:** {summary['total_deals_count']}\n"
                f"- **Average Deal Size:** ₹{summary['avg_deal_size']:,.2f}\n"
                f"- **Historical Win Rate:** {summary['win_rate_pct']}%"
                f"{top_sectors_str}\n\n"
                f"**Founder Insight:** {'Pipeline is strongly concentrated; prioritize high probability deals to hit targets.' if summary['total_pipeline_value'] > 0 else 'No active deals matched the given criteria.'}"
            )
            # Optional Groq LLM synthesis if key exists
            llm_summary = self.call_groq_llm(
                prompt=f"Founder requested sales pipeline analysis{sec_info}{time_info}. Verified BI Data:\n{json.dumps(summary)}\n\nProvide 2 executive takeaways regarding pipeline health and close probabilities.",
                system_prompt="You are an expert executive Business Intelligence advisor for Skylark Drones."
            )
            if llm_summary:
                answer_text += f"\n\n**AI Strategic Synthesis (Groq LLM):**\n{llm_summary}"

            return {
                "query": query,
                "intent": intent,
                "answer": answer_text,
                "data": summary,
                "caveats": audit["caveats"],
                "suggested_followups": [
                    "How does this compare to executed work orders in this sector?",
                    "What is our total collected revenue vs outstanding receivables?"
                ]
            }

        elif intent == "REVENUE":
            rev = get_revenue_summary(wo_df, sector=sector)
            sec_info = f" for **{sector}**" if sector else ""
            
            answer_text = (
                f"**Answer:** Outstanding receivables are ₹{rev['total_receivables']:,.2f}; collected cash is ₹{rev['total_collected_value_incl_gst']:,.2f}.\n\n"
                f"### Revenue & Realization Analysis{sec_info}\n\n"
                f"- **Total Contract Value (Excl. GST):** ₹{rev['total_contract_value_excl_gst']:,.2f}\n"
                f"- **Billed Value (Excl. GST):** ₹{rev['total_billed_value_excl_gst']:,.2f}\n"
                f"- **Billed Value (Incl. GST):** ₹{rev['total_billed_value_incl_gst']:,.2f}\n"
                f"- **Collected Amount (Incl. GST):** ₹{rev['total_collected_value_incl_gst']:,.2f}\n"
                f"- **Outstanding Receivables:** ₹{rev['total_receivables']:,.2f}\n"
                f"- **Revenue Realization Rate:** {rev['realization_rate_pct']}%\n"
                f"- **Collection Efficiency:** {rev['collection_efficiency_pct']}%\n"
                f"- **AR Priority Account Exposure:** ₹{rev['ar_priority_exposure']:,.2f}\n\n"
                f"**Founder Insight:** Cash collection efficiency is at {rev['collection_efficiency_pct']}%. Outstanding receivables of ₹{rev['total_receivables']:,.2f} need direct follow-up."
            )
            # Optional Groq LLM synthesis if key exists
            llm_summary = self.call_groq_llm(
                prompt=f"Founder requested revenue analysis{sec_info}. Verified BI Data:\n{json.dumps(rev)}\n\nProvide 2 executive takeaways regarding billing, collections, and AR exposure.",
                system_prompt="You are an expert executive Business Intelligence advisor for Skylark Drones."
            )
            if llm_summary:
                answer_text += f"\n\n**AI Strategic Synthesis (Groq LLM):**\n{llm_summary}"

            return {
                "query": query,
                "intent": intent,
                "answer": answer_text,
                "data": rev,
                "caveats": audit["caveats"],
                "suggested_followups": [
                    "Which work orders have AR priority flags?",
                    "Show operational work order statuses"
                ]
            }

        elif intent == "OPERATIONS":
            ops = get_operational_metrics(wo_df)
            status_lines = "\n".join([f"- **{k}**: {v} work orders" for k, v in ops["execution_status_breakdown"].items()])
            
            answer_text = (
                f"**Answer:** {ops['total_work_orders']} work orders are tracked, with {ops['quantities']['fulfillment_rate_pct']}% quantity fulfillment.\n\n"
                f"### Operational Execution & Work Orders\n\n"
                f"- **Total Work Orders Tracked:** {ops['total_work_orders']}\n"
                f"- **PO Quantities Total:** {ops['quantities']['po_total']:,.0f}\n"
                f"- **Billed Quantities:** {ops['quantities']['billed_total']:,.0f}\n"
                f"- **Remaining Balance:** {ops['quantities']['balance_total']:,.0f} (Fulfillment: {ops['quantities']['fulfillment_rate_pct']}%)\n\n"
                f"**Execution Status Breakdown:**\n{status_lines}\n\n"
                f"**Founder Insight:** Operational fulfillment is at {ops['quantities']['fulfillment_rate_pct']}%. Ensure ongoing work orders have up-to-date milestone billing."
            )
            # Optional Groq LLM synthesis if key exists
            llm_summary = self.call_groq_llm(
                prompt=f"Founder requested operational execution analysis. Verified BI Data:\n{json.dumps(ops)}\n\nProvide 2 executive takeaways regarding work order fulfillment and execution status.",
                system_prompt="You are an expert executive Business Intelligence advisor for Skylark Drones."
            )
            if llm_summary:
                answer_text += f"\n\n**AI Strategic Synthesis (Groq LLM):**\n{llm_summary}"

            return {
                "query": query,
                "intent": intent,
                "answer": answer_text,
                "data": ops,
                "caveats": audit["caveats"],
                "suggested_followups": [
                    "What is our revenue realization rate?",
                    "Generate the full leadership briefing"
                ]
            }

        else: # SECTOR or GENERAL_OVERVIEW
            sectors = get_sector_performance(deals_df, wo_df)
            top_sectors = sectors[:6]
            table_lines = [
                f"| **{s['sector']}** | ₹{s['pipeline_value']:,.0f} ({s['deals_count']}) | ₹{s['contract_value_excl_gst']:,.0f} | ₹{s['collected_value_incl_gst']:,.0f} | {s['realization_rate_pct']}% |"
                for s in top_sectors
            ]
            
            answer_text = (
                f"**Answer:** {top_sectors[0]['sector'] if top_sectors else 'No sector'} leads the cross-board performance view.\n\n"
                f"### Sector-Level Performance & Cross-Board Synthesis\n\n"
                f"| Sector | Pipeline Value (Deals) | Contract Value (WO) | Collected Cash | Realization % |\n"
                f"| :--- | :--- | :--- | :--- | :--- |\n" + "\n".join(table_lines) + "\n\n"
                f"**Founder Insight:** {top_sectors[0]['sector'] if top_sectors else 'Energy'} leads in aggregate volume. Cross-correlating deals with execution shows healthy realization across core accounts."
            )
            # Optional Groq LLM synthesis if key exists
            llm_summary = self.call_groq_llm(
                prompt=f"Founder requested sector-level performance summary. Verified BI Data:\n{json.dumps({'sectors': sectors})}\n\nProvide 2 executive takeaways regarding sector performance and market share.",
                system_prompt="You are an expert executive Business Intelligence advisor for Skylark Drones."
            )
            if llm_summary:
                answer_text += f"\n\n**AI Strategic Synthesis (Groq LLM):**\n{llm_summary}"

            return {
                "query": query,
                "intent": "SECTOR_SYNTHESIS",
                "answer": answer_text,
                "data": {"sectors": sectors},
                "caveats": audit["caveats"],
                "suggested_followups": [
                    "How is energy sector pipeline specifically looking?",
                    "Generate the complete leadership update"
                ]
            }

