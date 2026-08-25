import logging
from typing import Any, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger("bi_engine")

PROBABILITY_WEIGHTS = {
    "high": 0.80,
    "medium": 0.50,
    "low": 0.20,
    "100%": 1.00,
    "75%": 0.75,
    "50%": 0.50,
    "25%": 0.25,
    "0%": 0.00,
}


def _filter_by_quarter_or_date(
    df: pd.DataFrame,
    date_col: str,
    quarter: Optional[str] = None,
    year: Optional[int] = None,
) -> pd.DataFrame:
    """Filter DataFrame by quarter (Q1, Q2, Q3, Q4) or calendar year."""
    if date_col not in df.columns or df.empty:
        return df
    
    subset = df.copy()
    valid_dates = subset[date_col].dropna()
    if valid_dates.empty:
        return subset

    if year is not None:
        subset = subset[subset[date_col].dt.year == year]

    if quarter:
        q_clean = quarter.upper().strip()
        q_map = {"Q1": [1, 2, 3], "Q2": [4, 5, 6], "Q3": [7, 8, 9], "Q4": [10, 11, 12]}
        if q_clean in q_map:
            subset = subset[subset[date_col].dt.month.isin(q_map[q_clean])]
            
    return subset


def get_pipeline_summary(
    deals_df: pd.DataFrame,
    sector: Optional[str] = None,
    quarter: Optional[str] = None,
    year: Optional[int] = None,
) -> dict[str, Any]:
    """Calculate deep pipeline health, conversion stages, and weighted forecast."""
    df = deals_df.copy()
    if df.empty:
        return {
            "total_pipeline_value": 0.0,
            "weighted_pipeline_value": 0.0,
            "total_deals_count": 0,
            "avg_deal_size": 0.0,
            "by_stage": {},
            "by_status": {},
            "by_sector": {},
            "win_rate_pct": 0.0,
        }

    # Sector Filter
    sector_col = "sector_service" if "sector_service" in df.columns else ("sector" if "sector" in df.columns else None)
    if sector and sector_col:
        sector_clean = sector.lower()
        df = df[df[sector_col].astype(str).str.lower().str.contains(sector_clean, na=False)]

    # Temporal filter on tentative_close_date or created_date
    date_col = "tentative_close_date" if "tentative_close_date" in df.columns else "created_date"
    if date_col in df.columns:
        df = _filter_by_quarter_or_date(df, date_col, quarter, year)

    val_col = "masked_deal_value" if "masked_deal_value" in df.columns else None
    values = pd.to_numeric(df[val_col], errors="coerce").fillna(0) if val_col else pd.Series(0, index=df.index)
    total_val = float(values.sum())
    total_count = len(df)
    avg_size = round(total_val / total_count, 2) if total_count > 0 else 0.0

    # Calculate Probability Weighted Pipeline
    prob_col = "closure_probability" if "closure_probability" in df.columns else None
    if prob_col:
        weights = df[prob_col].astype(str).str.lower().map(PROBABILITY_WEIGHTS).fillna(0.40)
        weighted_val = float((values * weights).sum())
    else:
        weighted_val = total_val * 0.5

    # Group by Stage
    stage_col = "deal_stage" if "deal_stage" in df.columns else None
    by_stage = {}
    if stage_col:
        st_grp = df.assign(_val=values).groupby(stage_col, dropna=False)["_val"].agg(["count", "sum"])
        by_stage = {
            str(k): {"count": int(v["count"]), "value": round(float(v["sum"]), 2)}
            for k, v in st_grp.iterrows()
        }

    # Group by Status
    status_col = "deal_status" if "deal_status" in df.columns else None
    by_status = {}
    win_count = 0
    lost_count = 0
    if status_col:
        stat_grp = df.assign(_val=values).groupby(status_col, dropna=False)["_val"].agg(["count", "sum"])
        by_status = {
            str(k): {"count": int(v["count"]), "value": round(float(v["sum"]), 2)}
            for k, v in stat_grp.iterrows()
        }
        win_count = int(df[df[status_col].astype(str).str.lower().isin(["won", "closed won"])].shape[0])
        lost_count = int(df[df[status_col].astype(str).str.lower().isin(["lost", "closed lost"])].shape[0])

    closed_total = win_count + lost_count
    win_rate = round((win_count / closed_total) * 100, 2) if closed_total > 0 else 0.0

    # Group by Sector
    by_sector = {}
    if sector_col:
        sec_grp = df.assign(_val=values).groupby(sector_col, dropna=False)["_val"].agg(["count", "sum"])
        by_sector = {
            str(k): {"count": int(v["count"]), "value": round(float(v["sum"]), 2)}
            for k, v in sec_grp.sort_values("sum", ascending=False).iterrows()
        }

    return {
        "total_pipeline_value": round(total_val, 2),
        "weighted_pipeline_value": round(weighted_val, 2),
        "total_deals_count": total_count,
        "avg_deal_size": avg_size,
        "by_stage": by_stage,
        "by_status": by_status,
        "by_sector": by_sector,
        "win_rate_pct": win_rate,
    }


def get_revenue_summary(
    wo_df: pd.DataFrame,
    sector: Optional[str] = None,
) -> dict[str, Any]:
    """Calculate revenue realization, billed amounts, cash collected, and outstanding receivables."""
    df = wo_df.copy()
    if df.empty:
        return {
            "total_contract_value_excl_gst": 0.0,
            "total_contract_value_incl_gst": 0.0,
            "total_billed_value_excl_gst": 0.0,
            "total_billed_value_incl_gst": 0.0,
            "total_collected_value_incl_gst": 0.0,
            "total_receivables": 0.0,
            "realization_rate_pct": 0.0,
            "collection_efficiency_pct": 0.0,
            "ar_priority_exposure": 0.0,
        }

    if sector and "sector" in df.columns:
        df = df[df["sector"].astype(str).str.lower().str.contains(sector.lower(), na=False)]

    contract_excl = float(pd.to_numeric(df.get("amount_in_rupees_excl_of_gst_masked", 0), errors="coerce").fillna(0).sum())
    contract_incl = float(pd.to_numeric(df.get("amount_in_rupees_incl_of_gst_masked", 0), errors="coerce").fillna(0).sum())
    
    billed_excl = float(pd.to_numeric(df.get("billed_value_in_rupees_excl_of_gst_masked", 0), errors="coerce").fillna(0).sum())
    billed_incl = float(pd.to_numeric(df.get("billed_value_in_rupees_incl_of_gst_masked", 0), errors="coerce").fillna(0).sum())
    
    collected_incl = float(pd.to_numeric(df.get("collected_amount_in_rupees_incl_of_gst_masked", 0), errors="coerce").fillna(0).sum())
    
    receivables = float(pd.to_numeric(df.get("amount_receivable_masked", 0), errors="coerce").fillna(0).sum())
    if receivables == 0.0 and billed_incl > collected_incl:
        receivables = billed_incl - collected_incl

    # Realization & Collection percentages
    realization_rate = round((billed_excl / contract_excl) * 100, 2) if contract_excl > 0 else 0.0
    collection_eff = round((collected_incl / billed_incl) * 100, 2) if billed_incl > 0 else 0.0

    # AR Priority accounts
    ar_col = "ar_priority_account" if "ar_priority_account" in df.columns else None
    ar_exposure = 0.0
    if ar_col and "amount_receivable_masked" in df.columns:
        priority_df = df[df[ar_col].astype(str).str.lower().isin(["yes", "true", "priority", "high"])]
        ar_exposure = float(pd.to_numeric(priority_df["amount_receivable_masked"], errors="coerce").fillna(0).sum())

    return {
        "total_contract_value_excl_gst": round(contract_excl, 2),
        "total_contract_value_incl_gst": round(contract_incl, 2),
        "total_billed_value_excl_gst": round(billed_excl, 2),
        "total_billed_value_incl_gst": round(billed_incl, 2),
        "total_collected_value_incl_gst": round(collected_incl, 2),
        "total_receivables": round(receivables, 2),
        "realization_rate_pct": realization_rate,
        "collection_efficiency_pct": collection_eff,
        "ar_priority_exposure": round(ar_exposure, 2),
    }


def get_sector_performance(deals_df: pd.DataFrame, wo_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Synthesize cross-board sector performance across sales pipeline and execution delivery."""
    deals_sector_col = "sector_service" if "sector_service" in deals_df.columns else "sector"
    wo_sector_col = "sector" if "sector" in wo_df.columns else "sector"

    sectors = set()
    if deals_sector_col in deals_df.columns:
        sectors.update(deals_df[deals_sector_col].dropna().unique())
    if wo_sector_col in wo_df.columns:
        sectors.update(wo_df[wo_sector_col].dropna().unique())

    results = []
    for sector in sorted(sectors):
        d_sub = deals_df[deals_df[deals_sector_col] == sector] if deals_sector_col in deals_df.columns else pd.DataFrame()
        w_sub = wo_df[wo_df[wo_sector_col] == sector] if wo_sector_col in wo_df.columns else pd.DataFrame()

        pipe_val = float(pd.to_numeric(d_sub.get("masked_deal_value", 0), errors="coerce").fillna(0).sum())
        contract_val = float(pd.to_numeric(w_sub.get("amount_in_rupees_excl_of_gst_masked", 0), errors="coerce").fillna(0).sum())
        billed_val = float(pd.to_numeric(w_sub.get("billed_value_in_rupees_excl_of_gst_masked", 0), errors="coerce").fillna(0).sum())
        collected_val = float(pd.to_numeric(w_sub.get("collected_amount_in_rupees_incl_of_gst_masked", 0), errors="coerce").fillna(0).sum())
        receivables = float(pd.to_numeric(w_sub.get("amount_receivable_masked", 0), errors="coerce").fillna(0).sum())

        results.append({
            "sector": str(sector),
            "deals_count": len(d_sub),
            "pipeline_value": round(pipe_val, 2),
            "work_orders_count": len(w_sub),
            "contract_value_excl_gst": round(contract_val, 2),
            "billed_value_excl_gst": round(billed_val, 2),
            "collected_value_incl_gst": round(collected_val, 2),
            "receivables": round(receivables, 2),
            "realization_rate_pct": round((billed_val / contract_val) * 100, 1) if contract_val > 0 else 0.0,
        })

    results.sort(key=lambda x: x["pipeline_value"] + x["contract_value_excl_gst"], reverse=True)
    return results


def get_operational_metrics(wo_df: pd.DataFrame) -> dict[str, Any]:
    """Analyze work order execution statuses, operational quantities, and delivery health."""
    df = wo_df.copy()
    if df.empty:
        return {
            "total_work_orders": 0,
            "execution_status_breakdown": {},
            "billing_status_breakdown": {},
            "collection_status_breakdown": {},
            "quantities": {"po_total": 0, "billed_total": 0, "balance_total": 0},
        }

    exec_col = "execution_status" if "execution_status" in df.columns else "status"
    exec_counts = df[exec_col].fillna("Unknown").value_counts().to_dict() if exec_col in df.columns else {}

    bill_col = "billing_status" if "billing_status" in df.columns else None
    bill_counts = df[bill_col].fillna("Unknown").value_counts().to_dict() if bill_col in df.columns else {}

    coll_col = "collection_status" if "collection_status" in df.columns else None
    coll_counts = df[coll_col].fillna("Unknown").value_counts().to_dict() if coll_col in df.columns else {}

    po_qty = float(pd.to_numeric(df.get("quantities_as_per_po", 0), errors="coerce").fillna(0).sum())
    billed_qty = float(pd.to_numeric(df.get("quantity_billed_till_date", 0), errors="coerce").fillna(0).sum())
    bal_qty = float(pd.to_numeric(df.get("balance_in_quantity", 0), errors="coerce").fillna(0).sum())

    return {
        "total_work_orders": len(df),
        "execution_status_breakdown": {str(k): int(v) for k, v in exec_counts.items()},
        "billing_status_breakdown": {str(k): int(v) for k, v in bill_counts.items()},
        "collection_status_breakdown": {str(k): int(v) for k, v in coll_counts.items()},
        "quantities": {
            "po_total": round(po_qty, 2),
            "billed_total": round(billed_qty, 2),
            "balance_total": round(bal_qty, 2),
            "fulfillment_rate_pct": round((billed_qty / po_qty) * 100, 1) if po_qty > 0 else 0.0,
        },
    }
