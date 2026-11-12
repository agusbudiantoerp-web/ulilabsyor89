
"""
TSFA Portfolio Risk Engine - V1.0

Menghitung risiko historis portofolio saham berdasarkan:
- Harga penutupan harian
- Bobot berdasarkan Market_Value
- Historical daily returns
- Covariance dan correlation matrix

Modul ini berdiri sendiri dan tidak mengubah Portfolio Engine.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def calculate_portfolio_risk(
    price_history: pd.DataFrame,
    positions: pd.DataFrame,
    min_observations: int = 60,
) -> dict[str, Any]:
    """
    Menghitung risiko historis portofolio.

    Parameters
    ----------
    price_history:
        DataFrame format panjang dengan kolom:
        Date, Ticker, Close.

    positions:
        DataFrame posisi portofolio dengan kolom:
        Ticker, Market_Value.

    min_observations:
        Minimum jumlah observasi return harian yang lengkap.

    Returns
    -------
    dict:
        Status, metrik risiko, bobot, correlation matrix,
        dan kontribusi risiko.
    """

    required_history = {"Date", "Ticker", "Close"}
    required_positions = {"Ticker", "Market_Value"}

    if not isinstance(price_history, pd.DataFrame):
        raise TypeError("price_history harus berupa pandas DataFrame.")

    if not isinstance(positions, pd.DataFrame):
        raise TypeError("positions harus berupa pandas DataFrame.")

    if min_observations < 2:
        raise ValueError("min_observations minimal 2.")

    missing_history = required_history - set(price_history.columns)
    missing_positions = required_positions - set(positions.columns)

    if missing_history:
        raise ValueError(
            f"Kolom price_history tidak lengkap: {sorted(missing_history)}"
        )

    if missing_positions:
        raise ValueError(
            f"Kolom positions tidak lengkap: {sorted(missing_positions)}"
        )

    def insufficient(message: str, **details: Any) -> dict[str, Any]:
        return {
            "status": "insufficient_data",
            "message": message,
            **details,
        }

    # ---------------------------------------------------------
    # 1. Persiapan posisi dan bobot portofolio
    # ---------------------------------------------------------

    pos = positions[["Ticker", "Market_Value"]].copy()

    pos["Ticker"] = (
        pos["Ticker"].astype(str).str.strip().str.upper()
    )
    pos["Market_Value"] = pd.to_numeric(
        pos["Market_Value"], errors="coerce"
    )

    pos = pos[
        pos["Ticker"].ne("")
        & pos["Market_Value"].notna()
        & (pos["Market_Value"] > 0)
    ].copy()

    if pos.empty:
        return insufficient(
            "Tidak ada posisi dengan Market_Value positif dan valid."
        )

    if pos["Ticker"].duplicated().any():
        return insufficient(
            "Ticker duplikat ditemukan pada positions."
        )

    pos = pos.sort_values("Ticker").reset_index(drop=True)

    tickers = pos["Ticker"].tolist()

    total_market_value = float(pos["Market_Value"].sum())

    if not np.isfinite(total_market_value) or total_market_value <= 0:
        return insufficient("Total Market_Value tidak valid.")

    weights = (
        pos.set_index("Ticker")["Market_Value"]
        / total_market_value
    )

    # ---------------------------------------------------------
    # 2. Persiapan harga historis
    # ---------------------------------------------------------

    history = price_history[
        ["Date", "Ticker", "Close"]
    ].copy()

    history["Ticker"] = (
        history["Ticker"].astype(str).str.strip().str.upper()
    )
    history["Date"] = pd.to_datetime(
        history["Date"], errors="coerce"
    ).dt.normalize()
    history["Close"] = pd.to_numeric(
        history["Close"], errors="coerce"
    )

    history = history[
        history["Ticker"].isin(tickers)
        & history["Date"].notna()
        & history["Close"].notna()
        & np.isfinite(history["Close"])
        & (history["Close"] > 0)
    ].copy()

    if history.empty:
        return insufficient(
            "Tidak ditemukan harga historis valid untuk posisi portofolio.",
            tickers=tickers,
        )

    # Jika ada duplikasi ticker dan tanggal, gunakan catatan terakhir.
    history = (
        history.sort_values(["Ticker", "Date"])
        .drop_duplicates(
            subset=["Date", "Ticker"],
            keep="last",
        )
    )

    price_matrix = history.pivot(
        index="Date",
        columns="Ticker",
        values="Close",
    ).sort_index()

    missing_tickers = [
        ticker for ticker in tickers
        if ticker not in price_matrix.columns
    ]

    if missing_tickers:
        return insufficient(
            "Sebagian saham tidak memiliki data harga historis.",
            missing_tickers=missing_tickers,
            tickers=tickers,
        )

    price_matrix = price_matrix[tickers]

    # ---------------------------------------------------------
    # 3. Menghitung return harian
    # ---------------------------------------------------------

    daily_returns = price_matrix.pct_change(fill_method=None)

    # Gunakan hanya tanggal ketika semua saham memiliki return.
    daily_returns = daily_returns.replace(
        [np.inf, -np.inf], np.nan
    ).dropna(how="any")

    observation_count = len(daily_returns)

    if observation_count < min_observations:
        return insufficient(
            (
                f"Data return lengkap hanya {observation_count} hari. "
                f"Minimal diperlukan {min_observations} hari."
            ),
            observations=observation_count,
            minimum_required=min_observations,
            tickers=tickers,
        )

    # ---------------------------------------------------------
    # 4. Return portofolio
    # ---------------------------------------------------------

    weight_vector = weights.reindex(tickers).to_numpy(dtype=float)

    portfolio_daily_returns = daily_returns.dot(weight_vector)

    if not np.isfinite(portfolio_daily_returns).all():
        return insufficient(
            "Return harian portofolio mengandung nilai tidak valid."
        )

    cumulative_returns = (1 + portfolio_daily_returns).cumprod()

    if cumulative_returns.empty or (cumulative_returns <= 0).any():
        return insufficient(
            "Indeks pertumbuhan portofolio tidak valid untuk menghitung CAGR."
        )

    periods = len(portfolio_daily_returns)

    annualized_return = float(
        cumulative_returns.iloc[-1] ** (252 / periods) - 1
    )

    annualized_volatility = float(
        portfolio_daily_returns.std(ddof=1) * np.sqrt(252)
    )

    running_peak = cumulative_returns.cummax()
    drawdown = cumulative_returns / running_peak - 1
    max_drawdown = float(drawdown.min())

    # ---------------------------------------------------------
    # 5. Correlation dan covariance matrix
    # ---------------------------------------------------------

    correlation_matrix = daily_returns.corr()

    covariance_matrix = daily_returns.cov()

    # ---------------------------------------------------------
    # 6. Individual volatility
    # ---------------------------------------------------------

    individual_volatility = (
        daily_returns.std(ddof=1) * np.sqrt(252)
    )

    # ---------------------------------------------------------
    # 7. Risk contribution
    # ---------------------------------------------------------

    covariance_values = covariance_matrix.to_numpy(dtype=float)

    portfolio_variance_daily = float(
        weight_vector @ covariance_values @ weight_vector
    )

    if (
        not np.isfinite(portfolio_variance_daily)
        or portfolio_variance_daily <= 0
    ):
        return insufficient(
            "Varians portofolio tidak valid atau sama dengan nol.",
            observations=observation_count,
        )

    marginal_risk = covariance_values @ weight_vector

    component_risk = weight_vector * marginal_risk

    risk_contribution = (
        component_risk / portfolio_variance_daily
    )

    risk_contribution_df = pd.DataFrame({
        "Ticker": tickers,
        "Weight_Pct": weight_vector * 100,
        "Annualized_Volatility_Pct": (
            individual_volatility.reindex(tickers).to_numpy() * 100
        ),
        "Risk_Contribution_Pct": risk_contribution * 100,
    })

    risk_contribution_df = (
        risk_contribution_df.sort_values(
            "Risk_Contribution_Pct",
            ascending=False,
        ).reset_index(drop=True)
    )

    # ---------------------------------------------------------
    # 8. Hasil
    # ---------------------------------------------------------

    return {
        "status": "success",
        "message": "Perhitungan risiko portofolio berhasil.",
        "observations": observation_count,
        "first_date": daily_returns.index.min().date().isoformat(),
        "last_date": daily_returns.index.max().date().isoformat(),
        "annualized_return_pct": annualized_return * 100,
        "annualized_volatility_pct": annualized_volatility * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "portfolio_daily_returns": portfolio_daily_returns,
        "correlation_matrix": correlation_matrix,
        "covariance_matrix": covariance_matrix,
        "individual_volatility": (
            individual_volatility.rename(
                "Annualized_Volatility"
            )
        ),
        "risk_contribution": risk_contribution_df,
        "weights": weights,
        "daily_returns": daily_returns,
        "portfolio_growth_index": cumulative_returns,
    }
