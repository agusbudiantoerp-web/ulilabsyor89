"""Historical financial statements reader for IDX equities."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from market_engine import resolve_market_ticker


STATEMENT_MAP = {
    "income_statement": "income_stmt",
    "balance_sheet": "balance_sheet",
    "cash_flow": "cashflow",
}


def fetch_idx_fundamentals(symbol: str) -> dict[str, Any]:
    """Fetch historical annual statements from Yahoo Finance for an IDX ticker.

    Original values, reported periods, and missing values are preserved.
    No currency or unit conversion is performed.
    """
    resolved = resolve_market_ticker(symbol, "IDX")
    ticker_symbol = resolved["ticker"]
    ticker = yf.Ticker(ticker_symbol)

    statements: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []

    for output_name, yahoo_attribute in STATEMENT_MAP.items():
        try:
            frame = getattr(ticker, yahoo_attribute)
            if not isinstance(frame, pd.DataFrame):
                frame = pd.DataFrame()
            else:
                frame = frame.copy()
        except Exception as exc:
            frame = pd.DataFrame()
            warnings.append(
                f"Gagal mengambil {output_name}: {type(exc).__name__}: {exc}"
            )

        statements[output_name] = frame
        if frame.empty:
            warnings.append(f"Data {output_name} kosong atau tidak tersedia.")
        else:
            total_cells = int(frame.size)
            missing_cells = int(frame.isna().sum().sum())
            if missing_cells:
                warnings.append(
                    f"Data {output_name} tidak lengkap: {missing_cells} dari "
                    f"{total_cells} sel kosong; periksa periode dan pos laporan."
                )

    try:
        info = ticker.get_info()
        if not isinstance(info, dict):
            info = {}
    except Exception as exc:
        info = {}
        warnings.append(
            f"Metadata perusahaan tidak tersedia: {type(exc).__name__}: {exc}"
        )

    reported_currency = info.get("financialCurrency") or info.get("currency")
    if reported_currency and reported_currency != resolved["currency"]:
        warnings.append(
            f"Mata uang laporan ({reported_currency}) berbeda dari mata uang pasar "
            f"({resolved['currency']}); verifikasi sebelum analisis."
        )
    elif not reported_currency:
        warnings.append(
            "Mata uang laporan belum dapat diverifikasi dari metadata Yahoo Finance."
        )

    periods: dict[str, list[str]] = {}
    for name, frame in statements.items():
        periods[name] = [str(pd.Timestamp(column).date()) for column in frame.columns]

    available_period_sets = {
        name: set(values) for name, values in periods.items() if values
    }
    if len(available_period_sets) > 1:
        reference_name = next(iter(available_period_sets))
        reference_periods = available_period_sets[reference_name]
        for name, period_set in available_period_sets.items():
            if period_set != reference_periods:
                warnings.append(
                    f"Cakupan periode {name} berbeda dari {reference_name}; "
                    "jangan membandingkan laporan tanpa penyelarasan periode."
                )

    return {
        **resolved,
        "company_name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "reported_currency": reported_currency,
        "source": "Yahoo Finance via yfinance",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "statements": statements,
        "periods": periods,
        "warnings": warnings,
    }


def get_fundamentals_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Summarize statement coverage without changing source financial values."""
    statements = data.get("statements", {})
    summary: dict[str, Any] = {}

    for name in STATEMENT_MAP:
        frame = statements.get(name, pd.DataFrame())
        if not isinstance(frame, pd.DataFrame):
            frame = pd.DataFrame()

        summary[name] = {
            "rows": len(frame.index),
            "period_count": len(frame.columns),
            "periods": data.get("periods", {}).get(name, []),
            "non_null_cells": int(frame.notna().sum().sum()),
            "missing_cells": int(frame.isna().sum().sum()),
        }

    return {
        "ticker": data.get("ticker"),
        "company_name": data.get("company_name"),
        "reported_currency": data.get("reported_currency"),
        "source": data.get("source"),
        "statements": summary,
        "warnings": list(data.get("warnings", [])),
    }
