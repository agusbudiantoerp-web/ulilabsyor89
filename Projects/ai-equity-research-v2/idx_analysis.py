"""Historical fundamental analysis for IDX non-financial companies."""
from __future__ import annotations

from typing import Any
import math
import pandas as pd


ROW_MAP = {
    "revenue": ("income_statement", ["Total Revenue", "Operating Revenue"]),
    "gross_profit": ("income_statement", ["Gross Profit"]),
    "operating_income": ("income_statement", ["Operating Income", "Total Operating Income As Reported"]),
    "ebitda": ("income_statement", ["EBITDA", "Normalized EBITDA"]),
    "net_income": ("income_statement", ["Net Income Common Stockholders", "Net Income", "Net Income From Continuing Operation Net Minority Interest"]),
    "total_assets": ("balance_sheet", ["Total Assets"]),
    "equity": ("balance_sheet", ["Stockholders Equity", "Common Stock Equity"]),
    "total_debt": ("balance_sheet", ["Total Debt"]),
    "cash": ("balance_sheet", ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]),
    "free_cash_flow": ("cash_flow", ["Free Cash Flow"]),
}


def _value_for_period(frame: pd.DataFrame, candidates: list[str], period: Any):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    period_column = None
    for column in frame.columns:
        try:
            if str(pd.Timestamp(column).date()) == str(period):
                period_column = column
                break
        except (TypeError, ValueError):
            continue
    if period_column is None:
        return None
    for candidate in candidates:
        matches = [label for label in frame.index if str(label).strip().casefold() == candidate.casefold()]
        for label in matches:
            row = frame.loc[label]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            value = pd.to_numeric(row.get(period_column), errors="coerce")
            if pd.notna(value) and math.isfinite(float(value)):
                return float(value)
    return None

def _safe_ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    result = numerator / denominator
    return result * 100 if math.isfinite(result) else None


def analyze_idx_fundamentals(data: dict[str, Any]) -> dict[str, Any]:
    """Calculate annual growth and profitability/leverage ratios from source statements.

    Source values are not rescaled. ROE and ROA use average opening/closing
    balances; ratios requiring missing inputs remain None.
    """
    statements = data.get("statements", {})
    period_values = data.get("periods", {})
    income = statements.get("income_statement", pd.DataFrame())
    balance = statements.get("balance_sheet", pd.DataFrame())
    cashflow = statements.get("cash_flow", pd.DataFrame())
    raw_periods = period_values.get("income_statement", [])
    periods = sorted(set(raw_periods), reverse=True)
    rows = []

    for period in periods:
        year = int(str(period)[:4])
        values = {}
        for key, (statement_name, candidates) in ROW_MAP.items():
            frame = statements.get(statement_name, pd.DataFrame())
            values[key] = _value_for_period(frame, candidates, period)

        previous_period = f"{year - 1}-12-31"
        previous_values = {}
        for key in ("revenue", "gross_profit", "operating_income", "ebitda", "net_income", "free_cash_flow"):
            statement_name, candidates = ROW_MAP[key]
            frame = statements.get(statement_name, pd.DataFrame())
            previous_values[key] = _value_for_period(frame, candidates, previous_period)

        opening_assets = _value_for_period(balance, ROW_MAP["total_assets"][1], previous_period)
        opening_equity = _value_for_period(balance, ROW_MAP["equity"][1], previous_period)
        average_assets = ((values["total_assets"] + opening_assets) / 2) if values["total_assets"] is not None and opening_assets is not None else None
        average_equity = ((values["equity"] + opening_equity) / 2) if values["equity"] is not None and opening_equity is not None else None
        net_debt = values["total_debt"] - values["cash"] if values["total_debt"] is not None and values["cash"] is not None else None

        row = {"period": period, "year": year, **values}
        for key in ("revenue", "gross_profit", "operating_income", "ebitda", "net_income", "free_cash_flow"):
            row[f"{key}_growth_pct"] = _safe_ratio(
                values[key] - previous_values[key], previous_values[key]
            ) if values[key] is not None and previous_values[key] not in (None, 0) else None

        row.update({
            "gross_margin_pct": _safe_ratio(values["gross_profit"], values["revenue"]),
            "operating_margin_pct": _safe_ratio(values["operating_income"], values["revenue"]),
            "ebitda_margin_pct": _safe_ratio(values["ebitda"], values["revenue"]),
            "net_margin_pct": _safe_ratio(values["net_income"], values["revenue"]),
            "average_assets": average_assets,
            "average_equity": average_equity,
            "roa_pct": _safe_ratio(values["net_income"], average_assets),
            "roe_pct": _safe_ratio(values["net_income"], average_equity),
            "debt_to_equity_pct": _safe_ratio(values["total_debt"], values["equity"]),
            "net_debt": net_debt,
            "net_debt_to_ebitda": net_debt / values["ebitda"] if net_debt is not None and values["ebitda"] not in (None, 0) else None,
            "fcf_margin_pct": _safe_ratio(values["free_cash_flow"], values["revenue"]),
        })
        rows.append(row)

    metrics = pd.DataFrame(rows).sort_values("year", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()
    warnings = list(data.get("warnings", []))
    if metrics.empty:
        warnings.append("Tidak ada periode laporan laba rugi yang dapat dianalisis.")
    if any(metrics.get("average_assets", pd.Series(dtype=float)).isna()):
        warnings.append("ROA tidak tersedia pada periode yang saldo aset awal atau akhirnya tidak lengkap.")
    if any(metrics.get("average_equity", pd.Series(dtype=float)).isna()):
        warnings.append("ROE tidak tersedia pada periode yang saldo ekuitas awal atau akhirnya tidak lengkap.")
    if any(metrics.get("free_cash_flow", pd.Series(dtype=float)).isna()):
        warnings.append("FCF tidak tersedia pada sebagian periode; periksa laporan arus kas.")

    return {
        "ticker": data.get("ticker"),
        "company_name": data.get("company_name"),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "reported_currency": data.get("reported_currency"),
        "source": data.get("source"),
        "annual_metrics": metrics,
        "warnings": list(dict.fromkeys(warnings)),
        "methodology": "Pertumbuhan YoY memakai periode tahunan sebelumnya; ROE/ROA memakai rata-rata saldo awal dan akhir tahun. Nilai sumber tidak dikonversi.",
    }
