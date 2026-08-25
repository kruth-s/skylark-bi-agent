import json
import logging
import re
from typing import Any, Optional
import pandas as pd

logger = logging.getLogger("data_normalizer")

# Canonical Sector Mapping for resilience across inconsistent text
SECTOR_MAP = {
    "energy": "Energy & Power",
    "power": "Energy & Power",
    "solar": "Energy & Power",
    "wind": "Energy & Power",
    "renewables": "Energy & Power",
    "mining": "Mining & Minerals",
    "minerals": "Mining & Minerals",
    "coal": "Mining & Minerals",
    "railways": "Railways",
    "railway": "Railways",
    "infra": "Infrastructure & Construction",
    "infrastructure": "Infrastructure & Construction",
    "construction": "Infrastructure & Construction",
    "roads": "Infrastructure & Construction",
    "highways": "Infrastructure & Construction",
    "telecom": "Telecom & Utilities",
    "utilities": "Telecom & Utilities",
    "agriculture": "Agriculture & Forestry",
    "forestry": "Agriculture & Forestry",
    "defence": "Defence & Aerospace",
    "defense": "Defence & Aerospace",
    "aerospace": "Defence & Aerospace",
    "surveillance": "Security & Surveillance",
    "security": "Security & Surveillance",
    "government": "Government & Public Sector",
    "others": "Others",
    "other": "Others",
}


def _clean_key_name(value: str) -> str:
    """Normalize column header into snake_case."""
    name = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return name or "unnamed_column"


def normalize_text(value: Any) -> Optional[str]:
    """Strip whitespace and return clean string or None."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    if not text or text.lower() in {"none", "null", "nan", "n/a", "undefined", "{}"}:
        return None
    return text


def normalize_category(value: Any) -> Optional[str]:
    """Normalize category / status strings to Title Case."""
    text = normalize_text(value)
    if not text:
        return None
    # Handle boolean or numeric representations
    if text.lower() in {"true", "yes", "1"}:
        return "Yes"
    if text.lower() in {"false", "no", "0"}:
        return "No"
    return text.title()


def normalize_sector(value: Any) -> str:
    """Harmonize messy sector strings into standardized industry sectors."""
    text = normalize_text(value)
    if not text:
        return "Unspecified"
    
    clean = text.lower()
    for keyword, canonical in SECTOR_MAP.items():
        if keyword in clean:
            return canonical
    return text.title()


def normalize_date(value: Any) -> Optional[pd.Timestamp]:
    """Parse dates from diverse formats (ISO, UTC, timestamps, YYYY-MM-DD) gracefully."""
    text = normalize_text(value)
    if not text:
        return None
    try:
        # Check if text is JSON string containing date
        if "{" in text and "date" in text:
            try:
                parsed_json = json.loads(text)
                if isinstance(parsed_json, dict) and "date" in parsed_json:
                    text = parsed_json["date"]
            except Exception:
                pass
        parsed = pd.to_datetime(text, errors="coerce", utc=True)
        return None if pd.isna(parsed) else parsed
    except Exception:
        return None


def normalize_number(value: Any) -> float:
    """Parse and clean numeric values (handling currencies, symbols, negative brackets)."""
    if value is None or pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    
    text = str(value).strip()
    if not text:
        return 0.0
    
    # Handle json wrapped value
    if "{" in text:
        try:
            parsed_json = json.loads(text)
            if isinstance(parsed_json, dict):
                text = str(parsed_json.get("value") or parsed_json.get("text") or "")
        except Exception:
            pass

    is_negative = "(" in text and ")" in text or text.startswith("-")
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned:
        return 0.0
    try:
        num = float(cleaned)
        return -num if is_negative else num
    except ValueError:
        return 0.0


def _extract_column_display_text(column_value: dict[str, Any]) -> Optional[str]:
    """Safely extract readable human text from Monday column_values payload."""
    text = column_value.get("text")
    if text is not None and str(text).strip():
        return str(text).strip()
    
    raw_value = column_value.get("value")
    if not raw_value:
        return None
    
    try:
        data = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
        if isinstance(data, dict):
            # Check for label / chosen values
            if "label" in data and isinstance(data["label"], dict) and "text" in data["label"]:
                return data["label"]["text"]
            if "chosen_values" in data and isinstance(data["chosen_values"], list) and data["chosen_values"]:
                return ", ".join(str(v) for v in data["chosen_values"])
            if "date" in data and data["date"]:
                return str(data["date"])
            if "text" in data and data["text"]:
                return str(data["text"])
            # Do NOT return empty metadata structures like {"ids": []}
            return None
        elif isinstance(data, (int, float, str)):
            return str(data)
    except (TypeError, json.JSONDecodeError):
        pass
    
    return None


def board_to_dataframe(board: dict[str, Any]) -> pd.DataFrame:
    """Convert Monday board dictionary into a normalized DataFrame with canonical fields."""
    columns = {col["id"]: col for col in board.get("columns", [])}
    items = board.get("items_page", {}).get("items", [])
    
    rows: list[dict[str, Any]] = []
    for item in items:
        row: dict[str, Any] = {
            "item_id": str(item.get("id")),
            "item_name": normalize_text(item.get("name")) or f"Item-{item.get('id')}",
            "updated_at": normalize_date(item.get("updated_at")),
        }
        
        for col_val in item.get("column_values", []):
            col_id = col_val.get("id", "")
            column_def = columns.get(col_id, {})
            title = column_def.get("title", col_id)
            field_name = _clean_key_name(title)
            col_type = (column_def.get("type") or col_val.get("type") or "").lower()
            
            display_text = _extract_column_display_text(col_val)
            row[f"{field_name}__source"] = col_val.get("value") or display_text
            
            if col_type in {"date", "timeline"}:
                row[field_name] = normalize_date(display_text)
            elif col_type in {"numbers", "numeric", "formula"}:
                row[field_name] = normalize_number(display_text)
            elif col_type in {"status", "dropdown", "color"}:
                if "sector" in field_name:
                    row[field_name] = normalize_sector(display_text)
                else:
                    row[field_name] = normalize_category(display_text)
            else:
                if "sector" in field_name:
                    row[field_name] = normalize_sector(display_text)
                else:
                    row[field_name] = normalize_text(display_text)
                    
        rows.append(row)
        
    df = pd.DataFrame(rows)
    return df


def audit_data_quality(deals_df: pd.DataFrame, wo_df: pd.DataFrame) -> dict[str, Any]:
    """Inspect data resilience metrics, identify null rates, and produce executive caveats."""
    caveats = []
    
    # Deals audit
    total_deals = len(deals_df)
    deals_value_col = "masked_deal_value" if "masked_deal_value" in deals_df.columns else None
    zero_value_deals = int((deals_df[deals_value_col] == 0).sum()) if deals_value_col else 0
    missing_close_dates = int(deals_df["tentative_close_date"].isna().sum()) if "tentative_close_date" in deals_df.columns else 0
    
    if total_deals > 0:
        if zero_value_deals > 0:
            pct = round((zero_value_deals / total_deals) * 100, 1)
            caveats.append(f"{zero_value_deals} of {total_deals} deals ({pct}%) have zero or unrecorded deal value.")
        if missing_close_dates > 0:
            pct = round((missing_close_dates / total_deals) * 100, 1)
            caveats.append(f"{missing_close_dates} deals ({pct}%) are missing tentative close dates.")

    # Work orders audit
    total_wo = len(wo_df)
    receivable_col = "amount_receivable_masked" if "amount_receivable_masked" in wo_df.columns else None
    uncollected_count = int((wo_df[receivable_col] > 0).sum()) if receivable_col else 0
    missing_sectors = int(wo_df["sector"].isna().sum() + (wo_df["sector"] == "Unspecified").sum()) if "sector" in wo_df.columns else 0
    
    if total_wo > 0:
        if missing_sectors > 0:
            pct = round((missing_sectors / total_wo) * 100, 1)
            caveats.append(f"{missing_sectors} work orders ({pct}%) have unassigned or generic sector tags.")
        if uncollected_count > 0:
            caveats.append(f"{uncollected_count} work orders have outstanding uncollected receivables.")

    caveat_notes = [
        "Handled by the data resilience layer: the analysis continued safely despite the following limitation. "
        f"Remaining limitation: {caveat}"
        for caveat in caveats
    ]

    return {
        "deals_records_count": total_deals,
        "work_orders_records_count": total_wo,
        "deals_data_completeness_pct": round((1.0 - (zero_value_deals / max(total_deals, 1))) * 100, 1),
        "wo_data_completeness_pct": round((1.0 - (missing_sectors / max(total_wo, 1))) * 100, 1),
        "caveats": caveat_notes,
    }

