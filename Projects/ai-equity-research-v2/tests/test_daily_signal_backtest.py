
import numpy as np
import pandas as pd
import pytest

from daily_signal_backtest import backtest


def sample_bars(n=300):
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0008, 0.018, n)
    close = 100 * np.cumprod(1 + returns)
    open_price = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_price, close) * 1.012
    low = np.minimum(open_price, close) * 0.988
    volume = rng.integers(1_000_000, 3_000_000, n)

    return pd.DataFrame({
        "Open": open_price,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=pd.bdate_range("2024-01-01", periods=n))


def test_backtest_returns_expected_metrics():
    result = backtest(sample_bars())
    expected = {
        "trades", "win_rate_pct", "avg_return_pct",
        "profit_factor", "max_drawdown_pct",
        "total_return_pct", "cagr_pct", "sharpe_ratio",
        "benchmark_buy_hold_pct", "equity_curve",
    }
    assert expected.issubset(result.keys())
    assert result["trades"] >= 0
    assert result["equity_curve"]
    assert result["max_drawdown_pct"] <= 0


def test_backtest_rejects_missing_columns():
    with pytest.raises(ValueError, match="Kolom wajib"):
        backtest(pd.DataFrame({"Close": [10, 11, 12]}))


def test_backtest_rejects_invalid_risk():
    with pytest.raises(ValueError, match="risk_fraction"):
        backtest(sample_bars(), risk_fraction=0)


def test_backtest_rejects_invalid_holding_period():
    with pytest.raises(ValueError, match="Holding"):
        backtest(sample_bars(), max_holding_sessions=6)


def test_backtest_report_is_readable_and_includes_limitations():
    from daily_signal_cli import format_backtest_report

    report = format_backtest_report("BBCA.JK", "IDX", {
        "trades": 12,
        "win_rate_pct": 58.3,
        "avg_return_pct": 1.25,
        "profit_factor": 1.6,
        "max_drawdown_pct": -4.2,
        "total_return_pct": 8.1,
        "cagr_pct": 3.9,
        "sharpe_ratio": 0.8,
        "benchmark_buy_hold_pct": 7.2,
        "risk_per_trade_pct": 1.0,
        "max_allocation_pct": 100.0,
        "max_holding_sessions": 5,
        "cost_bps_round_trip": 40,
        "limitations": "Simulasi sederhana.",
    })
    assert "HISTORICAL BACKTEST" in report
    assert "Win rate" in report
    assert "Maximum drawdown" in report
    assert "Buy-and-hold benchmark" in report
    assert "Simulasi sederhana" in report


def test_benchmark_uses_entry_exit_costs_including_sell_tax():
    from daily_signal_engine import calculate_indicators, DEFAULT_CONFIG

    bars = sample_bars()
    result = backtest(bars, fee_bps=10, slippage_bps=20, sell_tax_bps=15)
    evaluated = calculate_indicators(bars).dropna(subset=[
        "SMA50", "EMA9", "EMA21", "RSI14", "MACD", "MACD_SIGNAL", "ATR14", "REL_VOLUME"
    ])
    first_close = float(evaluated.Close.iloc[0])
    last_close = float(evaluated.Close.iloc[-1])
    entry_cost = 30 / 10000
    exit_cost = 45 / 10000
    expected = (
        last_close * (1 - exit_cost) / (first_close * (1 + entry_cost)) - 1
    ) * 100
    assert result["benchmark_buy_hold_pct"] == pytest.approx(expected)
    assert result["cost_bps_round_trip"] == pytest.approx(75)
    assert result["transaction_costs"]["sell_tax_bps_on_exit"] == pytest.approx(15)


def test_backtest_rejects_non_finite_transaction_costs():
    with pytest.raises(ValueError, match="finite"):
        backtest(sample_bars(), sell_tax_bps=float("nan"))
