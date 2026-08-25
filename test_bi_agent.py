import os
import pytest
import pandas as pd
from fastapi.testclient import TestClient

from monday_client import MondayClient, required_board_id
from data_normalizer import (
    normalize_text,
    normalize_number,
    normalize_sector,
    normalize_date,
    board_to_dataframe,
    audit_data_quality,
)
from bi_engine import (
    get_pipeline_summary,
    get_revenue_summary,
    get_sector_performance,
    get_operational_metrics,
)
from leadership_updater import generate_leadership_update
from agent_service import BIAgentService
from api_server import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def sample_dataframes():
    deals_data = {
        "item_id": ["1", "2", "3"],
        "item_name": ["Client A", "Client B", "Client C"],
        "masked_deal_value": [100000.0, 200000.0, 50000.0],
        "closure_probability": ["High", "Medium", "Low"],
        "deal_stage": ["A. Qualified", "B. Proposal", "Closed Won"],
        "deal_status": ["Open", "Open", "Won"],
        "sector_service": ["Energy & Power", "Mining & Minerals", "Energy & Power"],
        "tentative_close_date": pd.to_datetime(["2026-03-31", "2026-06-30", "2026-02-15"], utc=True),
        "created_date": pd.to_datetime(["2026-01-01", "2026-01-10", "2025-12-01"], utc=True),
    }
    wo_data = {
        "item_id": ["101", "102"],
        "item_name": ["WO 1", "WO 2"],
        "amount_in_rupees_excl_of_gst_masked": [80000.0, 150000.0],
        "amount_in_rupees_incl_of_gst_masked": [94400.0, 177000.0],
        "billed_value_in_rupees_excl_of_gst_masked": [50000.0, 100000.0],
        "billed_value_in_rupees_incl_of_gst_masked": [59000.0, 118000.0],
        "collected_amount_in_rupees_incl_of_gst_masked": [40000.0, 80000.0],
        "amount_receivable_masked": [19000.0, 38000.0],
        "ar_priority_account": ["Yes", "No"],
        "execution_status": ["Ongoing", "Completed"],
        "sector": ["Energy & Power", "Mining & Minerals"],
        "quantities_as_per_po": [10.0, 25.0],
        "quantity_billed_till_date": [6.0, 25.0],
        "balance_in_quantity": [4.0, 0.0],
    }
    return pd.DataFrame(deals_data), pd.DataFrame(wo_data)


def test_normalizer_helpers():
    assert normalize_text("  Test Name  ") == "Test Name"
    assert normalize_text("None") is None
    assert normalize_text("") is None
    assert normalize_number("₹ 1,50,000.50") == 150000.50
    assert normalize_number("(500)") == -500.0
    assert normalize_sector("Solar Energy Project") == "Energy & Power"
    assert normalize_sector("Highway Construction") == "Infrastructure & Construction"
    assert normalize_date("2026-03-31") is not None


def test_bi_engine_pipeline(sample_dataframes):
    deals_df, _ = sample_dataframes
    summary = get_pipeline_summary(deals_df)
    assert summary["total_pipeline_value"] == 350000.0
    assert summary["total_deals_count"] == 3
    assert summary["weighted_pipeline_value"] > 0
    assert "Energy & Power" in summary["by_sector"]


def test_bi_engine_revenue(sample_dataframes):
    _, wo_df = sample_dataframes
    revenue = get_revenue_summary(wo_df)
    assert revenue["total_contract_value_excl_gst"] == 230000.0
    assert revenue["total_billed_value_excl_gst"] == 150000.0
    assert revenue["total_collected_value_incl_gst"] == 120000.0
    assert revenue["total_receivables"] == 57000.0
    assert revenue["ar_priority_exposure"] == 19000.0


def test_bi_engine_operations(sample_dataframes):
    _, wo_df = sample_dataframes
    ops = get_operational_metrics(wo_df)
    assert ops["total_work_orders"] == 2
    assert ops["quantities"]["po_total"] == 35.0
    assert ops["quantities"]["billed_total"] == 31.0


def test_leadership_updater(sample_dataframes):
    deals_df, wo_df = sample_dataframes
    briefing = generate_leadership_update(deals_df, wo_df, "Q1 2026")
    assert "scorecard" in briefing
    assert len(briefing["identified_risks"]) > 0
    assert len(briefing["strategic_recommendations"]) > 0


def test_agent_intent_and_ambiguity():
    agent = BIAgentService()
    
    # Ambiguous
    is_ambig, clarif = agent.is_ambiguous("How is it looking")
    assert is_ambig is True
    assert len(clarif) > 0
    
    # Specific intents
    assert agent.detect_intent("How is our pipeline looking for energy sector this quarter?") == "PIPELINE"
    assert agent.detect_intent("What is our billed and collected revenue?") == "REVENUE"
    assert agent.detect_intent("What is the execution status of work orders?") == "OPERATIONS"
    assert agent.detect_intent("Prepare executive leadership update") == "LEADERSHIP_UPDATE"


def test_api_endpoints(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"

    res = client.get("/")
    assert res.status_code == 200
    assert "BI Agent" in res.text

    # Test ambiguous query
    res = client.post("/api/query", json={"query": "status"})
    assert res.status_code == 200
    data = res.json()
    assert data["is_ambiguous"] is True
    assert len(data["clarifying_questions"]) > 0

    # Test specific query
    res = client.post("/api/query", json={"query": "What is our revenue collected vs receivables?"})
    assert res.status_code == 200
    data = res.json()
    assert data["is_ambiguous"] is False
    assert "Revenue" in data["answer"] or "Collected" in data["answer"]
