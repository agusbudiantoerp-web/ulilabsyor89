"""Industry- and currency-aware peer valuation summaries."""
from __future__ import annotations

import math
from collections.abc import Iterable

import pandas as pd

METRICS = ("pe_ttm", "pb", "ev_ebitda", "ev_sales", "roe", "roic", "revenue_growth", "operating_margin")


def build_peer_comparison(records: Iterable[dict], *, industry: str, currency: str) -> dict:
    frame = pd.DataFrame(list(records))
    required = {"ticker", "industry", "currency"}
    if not required.issubset(frame.columns):
        raise ValueError("Data peer wajib memiliki ticker, industry dan currency.")
    selected = frame[
        frame["industry"].astype(str).str.casefold().eq(str(industry).casefold())
        & frame["currency"].astype(str).str.upper().eq(str(currency).upper())
    ].copy()
    if selected.empty:
        raise ValueError("Tidak ada peer dengan industri dan mata uang yang sama.")
    for metric in METRICS:
        if metric not in selected:
            selected[metric] = float("nan")
        selected[metric] = pd.to_numeric(selected[metric], errors="coerce")
        selected.loc[~selected[metric].map(lambda x: math.isfinite(float(x)) if pd.notna(x) else False), metric] = float("nan")
    positive_only = ("pe_ttm", "pb", "ev_ebitda", "ev_sales")
    for metric in positive_only:
        selected.loc[selected[metric] <= 0, metric] = float("nan")
    summaries = {}
    for metric in METRICS:
        values = selected[metric].dropna()
        summaries[metric] = {
            "median": float(values.median()) if len(values) else None,
            "mean": float(values.mean()) if len(values) else None,
            "min": float(values.min()) if len(values) else None,
            "max": float(values.max()) if len(values) else None,
            "coverage": int(len(values)),
            "coverage_pct": float(len(values) / len(selected) * 100.0),
        }
    return {
        "industry": industry,
        "currency": str(currency).upper(),
        "peer_count": int(len(selected)),
        "tickers": selected["ticker"].astype(str).tolist(),
        "metrics": summaries,
        "records": selected[["ticker", "industry", "currency", *METRICS]].to_dict("records"),
        "limitations": (
            "Peer set harus ditinjau manual. Trailing/forward period, fiscal year, "
            "net debt, minority interest, diluted shares dan definisi provider dapat berbeda. "
            "Median tidak menggantikan pembacaan laporan keuangan."
        ),
    }


def compare_company_to_peers(comparison: dict, ticker: str) -> dict:
    records = pd.DataFrame(comparison.get("records", []))
    match = records[records["ticker"].astype(str).str.upper().eq(str(ticker).upper())]
    if match.empty:
        raise KeyError(f"Ticker {ticker} tidak ada dalam peer group.")
    company = match.iloc[0].to_dict()
    result = {}
    for metric, summary in comparison["metrics"].items():
        value, median = company.get(metric), summary.get("median")
        result[metric] = {
            "company_value": float(value) if pd.notna(value) else None,
            "peer_median": median,
            "premium_discount_pct": (
                (float(value) / median - 1.0) * 100.0
                if value is not None and pd.notna(value) and median not in (None, 0)
                else None
            ),
        }
    return {"ticker": str(ticker).upper(), "metrics": result}
