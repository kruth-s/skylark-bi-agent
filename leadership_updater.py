import logging
from datetime import datetime
from typing import Any, Optional
import pandas as pd

from bi_engine import (
    get_pipeline_summary,
    get_revenue_summary,
    get_sector_performance,
    get_operational_metrics,
)
from data_normalizer import audit_data_quality

logger = logging.getLogger("leadership_updater")


def generate_leadership_update(
    deals_df: pd.DataFrame,
    wo_df: pd.DataFrame,
    period_title: Optional[str] = None,
) -> dict[str, Any]:
    """Generate an executive-ready leadership briefing synthesizing multi-board intelligence."""
    current_period = period_title or datetime.now().strftime("%B %Y")
    
    pipeline = get_pipeline_summary(deals_df)
    revenue = get_revenue_summary(wo_df)
    sectors = get_sector_performance(deals_df, wo_df)
    operations = get_operational_metrics(wo_df)
    audit = audit_data_quality(deals_df, wo_df)

    # Key strategic takeaways
    top_sector = sectors[0]["sector"] if sectors else "N/A"
    top_sector_pipe = sectors[0]["pipeline_value"] if sectors else 0.0
    
    # Financial realization insights
    billed_val = revenue["total_billed_value_incl_gst"]
    collected_val = revenue["total_collected_value_incl_gst"]
    receivables = revenue["total_receivables"]
    ar_exposure = revenue["ar_priority_exposure"]
    
    # Identify key risks
    risks = []
    if receivables > (collected_val * 0.4) and receivables > 0:
        risks.append(f"High Outstanding Receivables (₹{receivables:,.2f}) represents significant liquidity tied up in uncollected invoices.")
    if ar_exposure > 0:
        risks.append(f"AR Priority accounts hold ₹{ar_exposure:,.2f} in exposure requiring urgent collection intervention.")
    if audit.get("caveats"):
        risks.append(f"Data Hygiene: {audit['caveats'][0]}")

    # Strategic recommendations
    recommendations = [
        f"Capitalize on strong traction in the {top_sector} sector (₹{top_sector_pipe:,.2f} pipeline).",
        f"Tighten milestone billing cycles to convert the unbilled backlog of ₹{revenue['total_contract_value_excl_gst'] - revenue['total_billed_value_excl_gst']:,.2f} into realized revenue.",
        "Prioritize outreach to high AR priority clients to accelerate cash collection."
    ]

    executive_summary = (
        f"Executive Briefing for {current_period}: Total active pipeline stands at ₹{pipeline['total_pipeline_value']:,.2f} "
        f"(weighted at ₹{pipeline['weighted_pipeline_value']:,.2f} across {pipeline['total_deals_count']} deals). "
        f"Executed work orders total ₹{revenue['total_contract_value_excl_gst']:,.2f} in contracts, with ₹{billed_val:,.2f} billed "
        f"and ₹{collected_val:,.2f} collected. Outstanding receivables total ₹{receivables:,.2f}."
    )

    return {
        "period": current_period,
        "executive_summary": executive_summary,
        "scorecard": {
            "total_pipeline_value": pipeline["total_pipeline_value"],
            "weighted_pipeline_value": pipeline["weighted_pipeline_value"],
            "deals_count": pipeline["total_deals_count"],
            "win_rate_pct": pipeline["win_rate_pct"],
            "contract_value_excl_gst": revenue["total_contract_value_excl_gst"],
            "billed_value_incl_gst": billed_val,
            "collected_value_incl_gst": collected_val,
            "receivables": receivables,
            "collection_efficiency_pct": revenue["collection_efficiency_pct"],
            "ar_priority_exposure": ar_exposure,
        },
        "sector_highlights": sectors[:5],
        "operational_health": {
            "total_work_orders": operations["total_work_orders"],
            "execution_status": operations["execution_status_breakdown"],
            "quantities": operations["quantities"],
        },
        "identified_risks": risks,
        "strategic_recommendations": recommendations,
        "data_quality_notes": audit.get("caveats", []),
    }
