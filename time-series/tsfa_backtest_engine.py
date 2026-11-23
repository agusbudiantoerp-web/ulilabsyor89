
"""
TSFA V1.4 - Portfolio Backtesting Engine

Initial version:
- Simple daily returns
- Buy-and-hold portfolio valuation
- Basic performance metrics
- Minimum observation safeguards
"""

import numpy as np
import pandas as pd


# Minimum data requirements
MIN_VOLATILITY_PERIODS = 30
MIN_SHARPE_PERIODS = 30
MIN_CAGR_DAYS = 365
DEFAULT_PERIODS_PER_YEAR = 252


def calculate_returns(price_data, price_column="Adj Close"):
    """
    Calculate simple daily returns from historical prices.

    For single-asset Yahoo Finance data, price_column is used.
    For multi-asset data, each column represents one asset.
    """
    if not isinstance(price_data, pd.DataFrame):
        raise TypeError("price_data harus berupa pandas DataFrame.")

    if price_data.empty:
        raise ValueError("price_data kosong.")

    if not isinstance(price_data.index, pd.DatetimeIndex):
        raise TypeError("Index price_data harus berupa DatetimeIndex.")

    if price_data.index.has_duplicates:
        raise ValueError("Tanggal pada price_data tidak boleh duplikat.")

    prices = price_data.copy().sort_index()

    if price_column in prices.columns and len(prices.columns) > 1:
        prices = prices[[price_column]].rename(
            columns={price_column: "Asset"}
        )

    if prices.columns.has_duplicates:
        raise ValueError("Nama kolom aset tidak boleh duplikat.")

    prices = prices.apply(pd.to_numeric, errors="coerce")
    prices = prices.replace([np.inf, -np.inf], np.nan)

    if prices.isna().any().any():
        raise ValueError(
            "Harga mengandung nilai kosong atau non-numerik."
        )

    if (prices <= 0).any().any():
        raise ValueError("Semua harga harus lebih besar dari nol.")

    returns = prices.pct_change(fill_method=None).dropna(how="any")
    returns.index.name = prices.index.name

    if returns.empty:
        raise ValueError("Data tidak cukup untuk menghitung return.")

    return returns


def calculate_portfolio_value(
    price_data,
    weights,
    initial_capital=100_000_000,
):
    """
    Calculate buy-and-hold portfolio value.

    Initial allocation is based on the first available price.
    Asset quantities remain unchanged during the simulation.
    """
    if not isinstance(price_data, pd.DataFrame):
        raise TypeError("price_data harus berupa pandas DataFrame.")

    if price_data.empty:
        raise ValueError("price_data kosong.")

    if not isinstance(price_data.index, pd.DatetimeIndex):
        raise TypeError("Index price_data harus berupa DatetimeIndex.")

    if price_data.index.has_duplicates:
        raise ValueError("Tanggal pada price_data tidak boleh duplikat.")

    if not np.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial_capital harus lebih besar dari nol.")

    prices = price_data.copy().sort_index()
    prices = prices.apply(pd.to_numeric, errors="coerce")
    prices = prices.replace([np.inf, -np.inf], np.nan)

    if prices.isna().any().any():
        raise ValueError("Harga mengandung nilai kosong atau non-finite.")

    if (prices <= 0).any().any():
        raise ValueError("Semua harga harus lebih besar dari nol.")

    if prices.columns.has_duplicates:
        raise ValueError("Nama kolom aset tidak boleh duplikat.")

    weights = pd.Series(weights, dtype=float)

    if weights.empty:
        raise ValueError("Bobot portofolio tidak boleh kosong.")

    if weights.index.has_duplicates:
        raise ValueError("Nama aset pada bobot tidak boleh duplikat.")

    if set(weights.index) != set(prices.columns):
        raise ValueError(
            "Nama aset pada weights harus sama dengan kolom price_data."
        )

    weights = weights.reindex(prices.columns)

    if not np.isfinite(weights.to_numpy()).all():
        raise ValueError("Bobot harus berupa angka finite.")

    if (weights < 0).any():
        raise ValueError("Bobot negatif belum didukung pada versi awal.")

    if not np.isclose(weights.sum(), 1.0, atol=1e-8):
        raise ValueError("Total bobot portofolio harus sama dengan 1.")

    initial_prices = prices.iloc[0]
    initial_allocation = initial_capital * weights
    asset_units = initial_allocation / initial_prices

    portfolio_value = prices.mul(asset_units, axis="columns").sum(axis=1)
    portfolio_value.name = "Portfolio_Value"

    return portfolio_value


def calculate_performance_metrics(
    portfolio_value,
    risk_free_rate=0.0,
    periods_per_year=DEFAULT_PERIODS_PER_YEAR,
):
    """
    Calculate portfolio performance metrics.

    risk_free_rate:
        Annual risk-free rate expressed as a decimal.
        Example: 0.05 means 5% per year.

    Minimum data requirements:
        Total return: at least 2 observations.
        Maximum drawdown: at least 2 observations.
        Annualized volatility: 30 return periods.
        Sharpe ratio: 30 return periods.
        CAGR: at least 365 calendar days.
    """
    if not isinstance(portfolio_value, pd.Series):
        raise TypeError("portfolio_value harus berupa pandas Series.")

    if len(portfolio_value) < 2:
        raise ValueError(
            "Minimal diperlukan dua observasi nilai portofolio."
        )

    if not isinstance(portfolio_value.index, pd.DatetimeIndex):
        raise TypeError(
            "Index portfolio_value harus berupa DatetimeIndex."
        )

    if portfolio_value.index.has_duplicates:
        raise ValueError(
            "Tanggal portfolio_value tidak boleh duplikat."
        )

    if not np.isfinite(risk_free_rate) or risk_free_rate <= -1:
        raise ValueError("risk_free_rate harus lebih besar dari -1.")

    if not isinstance(periods_per_year, (int, np.integer)):
        raise TypeError("periods_per_year harus berupa bilangan bulat.")

    if periods_per_year <= 0:
        raise ValueError("periods_per_year harus lebih besar dari nol.")

    equity = pd.to_numeric(
        portfolio_value, errors="coerce"
    ).sort_index()

    if equity.isna().any() or not np.isfinite(equity.to_numpy()).all():
        raise ValueError(
            "Nilai portofolio mengandung data tidak valid."
        )

    if (equity <= 0).any():
        raise ValueError(
            "Nilai portofolio harus lebih besar dari nol."
        )

    daily_returns = equity.pct_change(fill_method=None).dropna()

    if daily_returns.empty:
        raise ValueError(
            "Return portofolio tidak dapat dihitung."
        )

    # Metrics available with short data
    total_return = equity.iloc[-1] / equity.iloc[0] - 1

    drawdown = equity / equity.cummax() - 1
    max_drawdown = drawdown.min()

    # Actual calendar duration
    elapsed_days = (
        equity.index[-1] - equity.index[0]
    ).days

    elapsed_years = elapsed_days / 365.25

    # CAGR: do not annualize short observation periods
    if elapsed_days >= MIN_CAGR_DAYS:
        cagr = (
            equity.iloc[-1] / equity.iloc[0]
        ) ** (1 / elapsed_years) - 1
    else:
        cagr = np.nan

    # Annualized volatility: minimum 30 return observations
    if len(daily_returns) >= MIN_VOLATILITY_PERIODS:
        annualized_volatility = (
            daily_returns.std(ddof=1)
            * np.sqrt(periods_per_year)
        )
    else:
        annualized_volatility = np.nan

    # Sharpe ratio: minimum 30 return observations
    if len(daily_returns) >= MIN_SHARPE_PERIODS:
        daily_risk_free = (
            (1 + risk_free_rate) ** (1 / periods_per_year) - 1
        )

        excess_returns = daily_returns - daily_risk_free
        daily_std = daily_returns.std(ddof=1)

        if daily_std > 0:
            sharpe_ratio = (
                excess_returns.mean()
                / daily_std
                * np.sqrt(periods_per_year)
            )
        else:
            sharpe_ratio = np.nan
    else:
        sharpe_ratio = np.nan

    return {
        "initial_value": float(equity.iloc[0]),
        "final_value": float(equity.iloc[-1]),
        "total_return": float(total_return),
        "cagr": float(cagr),
        "annualized_volatility": float(annualized_volatility),
        "sharpe_ratio": float(sharpe_ratio),
        "max_drawdown": float(max_drawdown),
        "observations": int(len(equity)),
        "return_periods": int(len(daily_returns)),
        "elapsed_days": int(elapsed_days),
        "cagr_available": bool(elapsed_days >= MIN_CAGR_DAYS),
        "volatility_available": bool(
            len(daily_returns) >= MIN_VOLATILITY_PERIODS
        ),
        "sharpe_available": bool(
            len(daily_returns) >= MIN_SHARPE_PERIODS
        ),
    }
