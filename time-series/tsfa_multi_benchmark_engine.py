"""Multi-benchmark comparison engine for TSFA V1.4.

Benchmarks are compared on common dates with no forward-fill across missing
index sessions. Supports provider-backed and user-supplied historical series.
"""
from __future__ import annotations

from typing import Mapping
import numpy as np
import pandas as pd
from tsfa_benchmark_engine import calculate_benchmark_comparison

BENCHMARKS = {
    "IHSG": {"name": "IHSG", "ticker": "^JKSE", "provider": "Yahoo Finance", "automatic": True},
    "LQ45": {"name": "LQ45", "ticker": "^JKLQ45", "provider": "Yahoo Finance", "automatic": True},
    "IDX30": {"name": "IDX30", "ticker": None, "provider": "CSV / official index data", "automatic": False},
    "KOMPAS100": {"name": "Kompas100", "ticker": None, "provider": "CSV / official index data", "automatic": False},
}


def parse_benchmark_csv(payload: bytes) -> dict[str, pd.Series]:
    """Parse combined CSV with Date, Index, Close columns.

    Index values accepted: IHSG, LQ45, IDX30, KOMPAS100, KOMPAS 100.
    """
    if not payload:
        return {}
    from io import BytesIO
    frame = pd.read_csv(BytesIO(payload))
    normalized = {str(c).strip().lower().replace(" ", "_"): c for c in frame.columns}
    date_col = normalized.get("date")
    close_col = normalized.get("close") or normalized.get("value") or normalized.get("index_value")
    index_col = normalized.get("index") or normalized.get("benchmark") or normalized.get("ticker")
    if date_col is None or close_col is None or index_col is None:
        raise ValueError("CSV benchmark wajib memiliki kolom Date, Index, dan Close.")
    frame = frame[[date_col, index_col, close_col]].copy()
    frame.columns = ["Date", "Index", "Close"]
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    frame["Index"] = frame["Index"].astype(str).str.upper().str.strip().str.replace(" ", "", regex=False)
    aliases = {"KOMPAS100": "KOMPAS100", "KOMPAS100INDEX": "KOMPAS100"}
    frame["Index"] = frame["Index"].replace(aliases)
    frame = frame.dropna(subset=["Date", "Close"])
    if (frame["Close"] <= 0).any():
        raise ValueError("Nilai Close benchmark harus positif.")
    result: dict[str, pd.Series] = {}
    for key in BENCHMARKS:
        part = frame.loc[frame["Index"] == key, ["Date", "Close"]].sort_values("Date")
        if part.empty:
            continue
        if part["Date"].duplicated().any():
            raise ValueError(f"CSV memiliki tanggal duplikat untuk {key}.")
        series = part.set_index("Date")["Close"].astype(float)
        series.index = pd.DatetimeIndex(series.index).tz_localize(None).normalize()
        result[key] = series.sort_index()
    unknown = sorted(set(frame["Index"]) - set(BENCHMARKS))
    if unknown:
        raise ValueError("Nama indeks tidak dikenali di CSV: " + ", ".join(unknown))
    return result


def compare_all_benchmarks(
    portfolio_twr_index: pd.Series,
    benchmark_series: Mapping[str, pd.Series],
) -> tuple[dict[str, dict], pd.DataFrame]:
    """Return individual comparison objects and compact comparison table."""
    results: dict[str, dict] = {}
    rows = []
    for key, meta in BENCHMARKS.items():
        series = benchmark_series.get(key)
        if series is None or series.empty:
            rows.append({"Benchmark": meta["name"], "Ticker": meta["ticker"] or "CSV", "Status": "Unavailable", "Total Return": np.nan, "CAGR": np.nan, "Volatility": np.nan, "Sharpe": np.nan, "Max Drawdown": np.nan, "Active Return": np.nan, "Observations": 0, "Source": meta["provider"]})
            continue
        try:
            result = calculate_benchmark_comparison(
                portfolio_value=portfolio_twr_index,
                benchmark_prices=series,
                benchmark_name=meta["name"],
            )
            results[key] = result
            s = result["summary"]
            rows.append({
                "Benchmark": meta["name"], "Ticker": meta["ticker"] or "CSV",
                "Status": "Available", "Total Return": s["benchmark_total_return"],
                "CAGR": s["benchmark_cagr"], "Volatility": s["benchmark_volatility"],
                "Sharpe": s["benchmark_sharpe"], "Max Drawdown": s["benchmark_max_drawdown"],
                "Active Return": s["annualized_active_return"], "Observations": s["observations"],
                "Source": meta["provider"],
            })
        except Exception as exc:
            rows.append({"Benchmark": meta["name"], "Ticker": meta["ticker"] or "CSV", "Status": f"Unavailable: {exc}", "Total Return": np.nan, "CAGR": np.nan, "Volatility": np.nan, "Sharpe": np.nan, "Max Drawdown": np.nan, "Active Return": np.nan, "Observations": 0, "Source": meta["provider"]})
    return results, pd.DataFrame(rows)
