"""TSFA V1.4 benchmark comparison with strict common-session safeguards."""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_ACTIVE_RISK_PERIODS = 30


def calculate_benchmark_comparison(
    portfolio_value: pd.Series,
    benchmark_prices: pd.Series,
    benchmark_name: str = "Benchmark",
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
    min_active_risk_periods: int = MIN_ACTIVE_RISK_PERIODS,
) -> dict:
    """Compare portfolio TWR index with benchmark price/index series.

    Total returns use the first/last common observations. Tracking error and
    information ratio use only adjacent portfolio-session returns for which
    both benchmark endpoints exist; missing benchmark dates are never silently
    bridged and annualized as if they were one-day observations.
    """
    if not isinstance(portfolio_value, pd.Series) or not isinstance(benchmark_prices, pd.Series):
        raise TypeError("portfolio_value dan benchmark_prices harus berupa pandas Series.")
    if portfolio_value.empty or benchmark_prices.empty:
        raise ValueError("Input series cannot be empty.")
    for name, series in (("Portfolio", portfolio_value), ("Benchmark", benchmark_prices)):
        if not isinstance(series.index, pd.DatetimeIndex):
            raise TypeError(f"{name} index must be DatetimeIndex.")
        if series.index.has_duplicates:
            raise ValueError(f"{name} dates contain duplicates.")
    if not isinstance(periods_per_year, int) or isinstance(periods_per_year, bool) or periods_per_year <= 0:
        raise ValueError("periods_per_year must be a positive integer.")
    if not isinstance(min_active_risk_periods, int) or min_active_risk_periods < 2:
        raise ValueError("min_active_risk_periods must be an integer >= 2.")
    if not np.isfinite(risk_free_rate) or risk_free_rate <= -1:
        raise ValueError("risk_free_rate must be finite and greater than -1.")

    portfolio = pd.to_numeric(portfolio_value.copy(), errors="coerce").sort_index()
    benchmark = pd.to_numeric(benchmark_prices.copy(), errors="coerce").sort_index()
    if not np.isfinite(portfolio.to_numpy(dtype=float)).all() or not np.isfinite(benchmark.to_numpy(dtype=float)).all():
        raise ValueError("Input series contain invalid numbers.")
    if (portfolio <= 0).any() or (benchmark <= 0).any():
        raise ValueError("Portfolio values and benchmark prices must be positive.")

    synthetic_baseline_added = False
    if (len(portfolio) >= 2 and portfolio.index[0] < benchmark.index[0]
            and portfolio.index[1] in benchmark.index and portfolio.index[0] not in benchmark.index):
        benchmark.loc[portfolio.index[0]] = benchmark.loc[portfolio.index[1]]
        benchmark = benchmark.sort_index()
        synthetic_baseline_added = True

    # Keep the portfolio session calendar. Do not forward-fill benchmark prices.
    benchmark_on_portfolio_calendar = benchmark.reindex(portfolio.index)
    full = pd.DataFrame({"Portfolio": portfolio, "Benchmark": benchmark_on_portfolio_calendar})
    common = full.dropna(subset=["Portfolio", "Benchmark"])
    if len(common) < 2:
        raise ValueError("At least two common dates are required.")

    # Endpoint cumulative returns are valid over the common coverage window.
    cumulative_returns = pd.DataFrame(index=common.index)
    cumulative_returns["Portfolio"] = common["Portfolio"] / common["Portfolio"].iloc[0] - 1.0
    cumulative_returns["Benchmark"] = common["Benchmark"] / common["Benchmark"].iloc[0] - 1.0

    # Daily active risk only uses truly adjacent portfolio sessions.
    full_returns = full.pct_change(fill_method=None)
    valid_adjacent = full["Benchmark"].notna() & full["Benchmark"].shift(1).notna()
    valid_adjacent &= full["Portfolio"].notna() & full["Portfolio"].shift(1).notna()
    returns = full_returns.loc[valid_adjacent, ["Portfolio", "Benchmark"]].dropna()
    active_returns = returns["Portfolio"] - returns["Benchmark"]

    elapsed_days = int((common.index[-1] - common.index[0]).days)

    def aligned_metrics(series_name: str) -> dict:
        values = common[series_name]
        series_returns = returns[series_name]
        total = float(values.iloc[-1] / values.iloc[0] - 1.0)
        cagr_available = elapsed_days >= 365 and elapsed_days > 0
        cagr = float((values.iloc[-1] / values.iloc[0]) ** (365.25 / elapsed_days) - 1.0) if cagr_available else np.nan
        volatility_available = len(series_returns) >= min_active_risk_periods
        volatility = float(series_returns.std(ddof=1) * np.sqrt(periods_per_year)) if volatility_available else np.nan
        sharpe_available = volatility_available
        if sharpe_available and series_returns.std(ddof=1) > 0:
            daily_rf = (1.0 + risk_free_rate) ** (1.0 / periods_per_year) - 1.0
            sharpe = float((series_returns - daily_rf).mean() / series_returns.std(ddof=1) * np.sqrt(periods_per_year))
        else:
            sharpe = np.nan
            sharpe_available = False
        dd = values / values.cummax() - 1.0
        return {
            "total_return": total, "cagr": cagr, "cagr_available": bool(cagr_available),
            "annualized_volatility": volatility, "volatility_available": bool(volatility_available),
            "sharpe_ratio": sharpe, "sharpe_available": bool(sharpe_available),
            "max_drawdown": float(dd.min()), "observations": int(len(values)),
            "return_periods": int(len(series_returns)),
        }

    portfolio_metrics = aligned_metrics("Portfolio")
    benchmark_metrics = aligned_metrics("Benchmark")

    annualized_active_return = (
        portfolio_metrics["cagr"] - benchmark_metrics["cagr"]
        if portfolio_metrics["cagr_available"] and benchmark_metrics["cagr_available"] else np.nan
    )
    active_risk_available = len(active_returns) >= min_active_risk_periods
    tracking_error = float(active_returns.std(ddof=1) * np.sqrt(periods_per_year)) if active_risk_available else np.nan
    information_ratio = (
        float(active_returns.mean() / active_returns.std(ddof=1) * np.sqrt(periods_per_year))
        if active_risk_available and active_returns.std(ddof=1) > 0 else np.nan
    )

    portfolio_last_date = portfolio.index[-1]
    benchmark_last_date = benchmark.index[-1]
    comparison_end_date = common.index[-1]
    coverage = {
        "portfolio_last_date": portfolio_last_date,
        "benchmark_last_date": benchmark_last_date,
        "comparison_end_date": comparison_end_date,
        "portfolio_end_after_benchmark_days": int((portfolio_last_date - benchmark_last_date).days),
        "portfolio_dates_without_benchmark": [d for d in portfolio.index if d not in benchmark.index],
        "benchmark_dates_without_portfolio": [d for d in benchmark.index if d not in portfolio.index],
    }

    summary = {
        "benchmark_name": benchmark_name,
        "observations": int(len(common)),
        "return_periods": int(len(returns)),
        "start_date": common.index[0],
        "end_date": comparison_end_date,
        "portfolio_last_date": portfolio_last_date,
        "benchmark_last_date": benchmark_last_date,
        "portfolio_total_return": float(cumulative_returns["Portfolio"].iloc[-1]),
        "benchmark_total_return": float(cumulative_returns["Benchmark"].iloc[-1]),
        "annualized_active_return": float(annualized_active_return),
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "tracking_error_available": bool(active_risk_available),
        "information_ratio_available": bool(active_risk_available and np.isfinite(information_ratio)),
        "portfolio_cagr": portfolio_metrics["cagr"],
        "benchmark_cagr": benchmark_metrics["cagr"],
        "portfolio_volatility": portfolio_metrics["annualized_volatility"],
        "benchmark_volatility": benchmark_metrics["annualized_volatility"],
        "portfolio_sharpe": portfolio_metrics["sharpe_ratio"],
        "benchmark_sharpe": benchmark_metrics["sharpe_ratio"],
        "portfolio_max_drawdown": portfolio_metrics["max_drawdown"],
        "benchmark_max_drawdown": benchmark_metrics["max_drawdown"],
        "synthetic_baseline_added": synthetic_baseline_added,
        "active_risk_minimum_periods": min_active_risk_periods,
        "coverage": coverage,
    }
    return {
        "aligned_data": common,
        "daily_returns": returns,
        "cumulative_returns": cumulative_returns,
        "active_returns": active_returns,
        "portfolio_metrics": portfolio_metrics,
        "benchmark_metrics": benchmark_metrics,
        "summary": summary,
    }
