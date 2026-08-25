"""Analytics compatibility layer bridging to high-performance BI Engine."""
from collections.abc import Mapping
from typing import Any
import pandas as pd

from bi_engine import (
    get_pipeline_summary,
    get_revenue_summary,
    get_sector_performance,
    get_operational_metrics,
)


def _numeric_column(data: pd.DataFrame, column: str) -> pd.Series:
    if column not in data.columns:
        raise KeyError(f"Column '{column}' was not found in the normalized data.")
    return pd.to_numeric(data[column], errors="coerce").fillna(0)


def calculate_pipeline(data: pd.DataFrame, value_column: str = "masked_deal_value") -> float:
    return float(_numeric_column(data, value_column).sum())


def calculate_pipeline_by_sector(
    data: pd.DataFrame, value_column: str = "masked_deal_value", sector_column: str = "sector_service"
) -> pd.DataFrame:
    col = sector_column if sector_column in data.columns else "sector"
    values = _numeric_column(data, value_column)
    if col not in data.columns:
        raise KeyError(f"Column '{col}' was not found in the normalized data.")
    result = data.assign(_value=values).groupby(col, dropna=False)["_value"].sum()
    result = result.rename("pipeline").reset_index()
    total = result["pipeline"].sum()
    result["percentage"] = (result["pipeline"] / total * 100).round(2) if total else 0.0
    return result.sort_values("pipeline", ascending=False, ignore_index=True)


def calculate_billed_value(data: pd.DataFrame, value_column: str = "billed_value_in_rupees_excl_of_gst_masked") -> float:
    return calculate_pipeline(data, value_column)


def calculate_collected_value(data: pd.DataFrame, value_column: str = "collected_amount_in_rupees_incl_of_gst_masked") -> float:
    return calculate_pipeline(data, value_column)


def calculate_receivables(
    data: pd.DataFrame,
    billed_column: str = "billed_value_in_rupees_incl_of_gst_masked",
    collected_column: str = "collected_amount_in_rupees_incl_of_gst_masked",
) -> float:
    if "amount_receivable_masked" in data.columns:
        return float(pd.to_numeric(data["amount_receivable_masked"], errors="coerce").fillna(0).sum())
    return calculate_billed_value(data, billed_column) - calculate_collected_value(data, collected_column)


def _status_counts(data: pd.DataFrame, status_column: str) -> Mapping[str, int]:
    if status_column not in data.columns:
        raise KeyError(f"Column '{status_column}' was not found in the normalized data.")
    counts = data[status_column].fillna("Unknown").value_counts().sort_index()
    return {str(status): int(count) for status, count in counts.items()}


def calculate_work_order_status(
    data: pd.DataFrame, status_column: str = "execution_status"
) -> Mapping[str, int]:
    col = status_column if status_column in data.columns else "status"
    return _status_counts(data, col)


def calculate_billing_status(
    data: pd.DataFrame, status_column: str = "billing_status"
) -> Mapping[str, int]:
    return _status_counts(data, status_column)