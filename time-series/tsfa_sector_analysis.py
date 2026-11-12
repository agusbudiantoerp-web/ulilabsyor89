
"""
TSFA Sector Exposure Analysis
V1.3 - Initial Sector Analysis Module
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# Initial mapping for the user's current Indonesian stock portfolio.
# Review and verify classifications before using them for investment decisions.

DEFAULT_SECTOR_MAP = {
    "BBRI": "Financials",
    "BBNI": "Financials",
    "BMRI": "Financials",
    "TLKM": "Infrastructure",
    "TOWR": "Infrastructure",
    "HRUM": "Energy",
    "TPIA": "Basic Materials",
    "MBMA": "Basic Materials",
    "PWON": "Properties & Real Estate",
    "ICBP": "Consumer Non-Cyclicals",
    "ACES": "Consumer Cyclicals",
    "RALS": "Consumer Cyclicals",
    "WIRG": "Technology",
}


def calculate_sector_exposure(
    positions: pd.DataFrame,
    sector_mapping: dict[str, str] | None = None,
    risk_contribution: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Calculate portfolio market value and risk exposure by sector.

    Required positions columns:
        Ticker
        Market_Value

    Optional risk_contribution columns:
        Ticker
        Risk_Contribution_Pct
    """

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

    mapping = (
        DEFAULT_SECTOR_MAP.copy()
        if sector_mapping is None
        else {
            str(ticker).strip().upper(): str(sector).strip()
            for ticker, sector in sector_mapping.items()
        }
    )

    data = positions[["Ticker", "Market_Value"]].copy()

    data["Ticker"] = (
        data["Ticker"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    data["Market_Value"] = pd.to_numeric(
        data["Market_Value"],
        errors="coerce",
    )

    if data["Ticker"].eq("").any():
        raise ValueError("Ticker kosong ditemukan.")

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
            "Tidak ada posisi dengan Market_Value lebih besar dari nol."
        )

    data["Sector"] = data["Ticker"].map(mapping).fillna(
        "Unclassified"
    )

    if data["Sector"].astype(str).str.strip().eq("").any():
        raise ValueError("Nama sektor tidak boleh kosong.")

    total_market_value = float(data["Market_Value"].sum())

    if total_market_value <= 0:
        raise ValueError("Total market value harus lebih besar dari nol.")

    data["Weight_Pct"] = (
        data["Market_Value"] / total_market_value * 100.0
    )

    sector_exposure = (
        data.groupby("Sector", as_index=False)
        .agg(
            Market_Value=("Market_Value", "sum"),
            Stock_Count=("Ticker", "nunique"),
            Tickers=(
                "Ticker",
                lambda values: ", ".join(sorted(set(values))),
            ),
        )
    )

    sector_exposure["Weight_Pct"] = (
        sector_exposure["Market_Value"]
        / total_market_value
        * 100.0
    )

    # Aggregate stock-level risk contribution into sector-level risk.
    if risk_contribution is not None:
        required_risk_columns = {
            "Ticker",
            "Risk_Contribution_Pct",
        }

        if not isinstance(risk_contribution, pd.DataFrame):
            raise TypeError(
                "Risk contribution harus berupa pandas DataFrame."
            )

        missing_risk = (
            required_risk_columns - set(risk_contribution.columns)
        )

        if missing_risk:
            raise ValueError(
                "Kolom risk contribution tidak lengkap: "
                f"{sorted(missing_risk)}"
            )

        risk_data = risk_contribution[
            ["Ticker", "Risk_Contribution_Pct"]
        ].copy()

        risk_data["Ticker"] = (
            risk_data["Ticker"]
            .astype(str)
            .str.strip()
            .str.upper()
        )

        risk_data["Risk_Contribution_Pct"] = pd.to_numeric(
            risk_data["Risk_Contribution_Pct"],
            errors="coerce",
        )

        if (
            risk_data["Risk_Contribution_Pct"].isna().any()
            or not np.isfinite(
                risk_data["Risk_Contribution_Pct"]
            ).all()
        ):
            raise ValueError(
                "Risk contribution mengandung nilai tidak valid."
            )

        risk_data = risk_data.merge(
            data[["Ticker", "Sector"]],
            on="Ticker",
            how="inner",
            validate="one_to_one",
        )

        sector_risk = (
            risk_data.groupby("Sector", as_index=False)
            ["Risk_Contribution_Pct"]
            .sum()
        )

        sector_exposure = sector_exposure.merge(
            sector_risk,
            on="Sector",
            how="left",
        )

    sector_exposure = sector_exposure.sort_values(
        "Market_Value",
        ascending=False,
    ).reset_index(drop=True)

    data = data.sort_values(
        "Market_Value",
        ascending=False,
    ).reset_index(drop=True)

    return {
        "positions": data,
        "sector_exposure": sector_exposure,
        "total_market_value": total_market_value,
        "sector_count": int(sector_exposure["Sector"].nunique()),
        "unclassified_tickers": data.loc[
            data["Sector"] == "Unclassified",
            "Ticker",
        ].tolist(),
    }
