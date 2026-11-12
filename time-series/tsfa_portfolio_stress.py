"""
TSFA Portfolio Stress Testing
V1.3 - Market-wide and Sector Stress Scenarios

Stress assumptions are user-defined scenarios, not forecasts.
All shock values are percentages, e.g. -10 means a 10% decline.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tsfa_sector_analysis import calculate_sector_exposure


DEFAULT_MARKET_SHOCKS = (-5.0, -10.0, -15.0, -20.0)


def _prepare_positions(
    positions: pd.DataFrame,
    cash_balance: float,
) -> tuple[pd.DataFrame, float, float]:
    """Validate portfolio positions and cash balance."""

    if not isinstance(positions, pd.DataFrame):
        raise TypeError("Positions harus berupa pandas DataFrame.")

    required_columns = {"Ticker", "Market_Value"}
    missing = required_columns - set(positions.columns)

    if missing:
        raise ValueError(
            f"Kolom positions tidak lengkap: {sorted(missing)}"
        )

    if positions.empty:
        raise ValueError("Positions tidak boleh kosong.")

    data = positions[["Ticker", "Market_Value"]].copy()

    if data["Ticker"].isna().any():
        raise ValueError("Ticker kosong ditemukan.")

    data["Ticker"] = (
        data["Ticker"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    if data["Ticker"].eq("").any():
        raise ValueError("Ticker kosong ditemukan.")

    data["Market_Value"] = pd.to_numeric(
        data["Market_Value"],
        errors="coerce",
    )

    if data["Market_Value"].isna().any():
        raise ValueError(
            "Market_Value kosong atau tidak valid ditemukan."
        )

    if not np.isfinite(data["Market_Value"]).all():
        raise ValueError("Market_Value harus berupa angka finite.")

    if (data["Market_Value"] < 0).any():
        raise ValueError("Market_Value tidak boleh negatif.")

    data = data[data["Market_Value"] > 0].copy()

    if data.empty:
        raise ValueError(
            "Tidak ada saham dengan Market_Value lebih besar dari nol."
        )

    try:
        cash = float(cash_balance)
    except (TypeError, ValueError):
        raise ValueError("Cash balance harus berupa angka.")

    if not np.isfinite(cash) or cash < 0:
        raise ValueError(
            "Cash balance harus berupa angka finite dan tidak negatif."
        )

    equity_market_value = float(data["Market_Value"].sum())
    total_portfolio_value = equity_market_value + cash

    if total_portfolio_value <= 0:
        raise ValueError(
            "Total portfolio value harus lebih besar dari nol."
        )

    data = data.reset_index(drop=True)

    return data, cash, total_portfolio_value


def _validate_shock(
    shock: Any,
    label: str,
) -> float:
    """Validate a decline scenario between -100% and 0%."""

    try:
        value = float(shock)
    except (TypeError, ValueError):
        raise ValueError(f"Shock {label} harus berupa angka.")

    if not np.isfinite(value):
        raise ValueError(f"Shock {label} harus berupa angka finite.")

    if value < -100.0 or value > 0.0:
        raise ValueError(
            f"Shock {label} harus berada antara -100% dan 0%."
        )

    return value


def calculate_market_stress(
    positions: pd.DataFrame,
    cash_balance: float = 0.0,
    market_shocks: tuple[float, ...] | list[float] = DEFAULT_MARKET_SHOCKS,
) -> dict[str, Any]:
    """
    Calculate portfolio impact under uniform market-wide declines.

    Required positions columns:
        Ticker
        Market_Value

    Cash remains unchanged during the stress scenario.
    """

    data, cash, total_portfolio_value = _prepare_positions(
        positions,
        cash_balance,
    )

    if not isinstance(market_shocks, (tuple, list)):
        raise TypeError("Market shocks harus berupa list atau tuple.")

    if not market_shocks:
        raise ValueError("Market shocks tidak boleh kosong.")

    equity_market_value = float(data["Market_Value"].sum())
    rows = []

    for raw_shock in market_shocks:
        shock = _validate_shock(
            raw_shock,
            "market-wide",
        )

        estimated_pnl = equity_market_value * shock / 100.0
        stressed_equity_value = equity_market_value + estimated_pnl
        stressed_portfolio_value = cash + stressed_equity_value

        rows.append({
            "Scenario": f"Market Stress {shock:.1f}%",
            "Shock_Pct": shock,
            "Equity_Market_Value_Before": equity_market_value,
            "Cash_Balance": cash,
            "Total_Portfolio_Value_Before": total_portfolio_value,
            "Estimated_PnL": estimated_pnl,
            "Portfolio_Impact_Pct": (
                estimated_pnl / total_portfolio_value * 100.0
            ),
            "Equity_Market_Value_After": stressed_equity_value,
            "Stressed_Portfolio_Value": stressed_portfolio_value,
        })

    scenario_results = pd.DataFrame(rows)

    return {
        "status": "success",
        "scenario_results": scenario_results,
        "equity_market_value": equity_market_value,
        "cash_balance": cash,
        "total_portfolio_value": total_portfolio_value,
    }


def calculate_sector_stress(
    positions: pd.DataFrame,
    sector_shocks: dict[str, float] | None = None,
    cash_balance: float = 0.0,
    sector_mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Calculate portfolio impact from different shocks per sector.

    Sector names follow tsfa_sector_analysis.DEFAULT_SECTOR_MAP.
    Sectors without an assigned shock use 0% by default.
    """

    data, cash, total_portfolio_value = _prepare_positions(
        positions,
        cash_balance,
    )

    if sector_shocks is None:
        sector_shocks = {}

    if not isinstance(sector_shocks, dict):
        raise TypeError("Sector shocks harus berupa dictionary.")

    sector_result = calculate_sector_exposure(
        positions=data,
        sector_mapping=sector_mapping,
    )

    sector_exposure = sector_result["sector_exposure"].copy()

    validated_shocks = {}

    for raw_sector, raw_shock in sector_shocks.items():
        sector = str(raw_sector).strip()

        if not sector:
            raise ValueError("Nama sektor pada shock tidak boleh kosong.")

        validated_shocks[sector] = _validate_shock(
            raw_shock,
            sector,
        )

    available_sectors = set(
        sector_exposure["Sector"].astype(str)
    )

    unknown_sectors = (
        set(validated_shocks) - available_sectors
    )

    if unknown_sectors:
        raise ValueError(
            "Sektor tidak ditemukan dalam portfolio: "
            + ", ".join(sorted(unknown_sectors))
        )

    sector_exposure["Shock_Pct"] = (
        sector_exposure["Sector"]
        .map(validated_shocks)
        .fillna(0.0)
    )

    sector_exposure["Estimated_PnL"] = (
        sector_exposure["Market_Value"]
        * sector_exposure["Shock_Pct"]
        / 100.0
    )

    sector_exposure["Stressed_Market_Value"] = (
        sector_exposure["Market_Value"]
        + sector_exposure["Estimated_PnL"]
    )

    sector_exposure["Portfolio_Impact_Pct"] = (
        sector_exposure["Estimated_PnL"]
        / total_portfolio_value
        * 100.0
    )

    equity_market_value = float(data["Market_Value"].sum())
    total_estimated_pnl = float(
        sector_exposure["Estimated_PnL"].sum()
    )

    stressed_equity_value = (
        equity_market_value + total_estimated_pnl
    )

    stressed_portfolio_value = (
        cash + stressed_equity_value
    )

    portfolio_impact_pct = (
        total_estimated_pnl
        / total_portfolio_value
        * 100.0
    )

    sector_exposure = sector_exposure.sort_values(
        "Market_Value",
        ascending=False,
    ).reset_index(drop=True)

    return {
        "status": "success",
        "sector_stress": sector_exposure,
        "positions": sector_result["positions"],
        "equity_market_value": equity_market_value,
        "cash_balance": cash,
        "total_portfolio_value": total_portfolio_value,
        "estimated_pnl": total_estimated_pnl,
        "portfolio_impact_pct": portfolio_impact_pct,
        "stressed_portfolio_value": stressed_portfolio_value,
        "unclassified_tickers": sector_result[
            "unclassified_tickers"
        ],
    }