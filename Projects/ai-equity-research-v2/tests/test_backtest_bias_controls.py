import numpy as np
import pandas as pd
import pytest
import pytest

from daily_signal_backtest import backtest
from daily_signal_engine import calculate_indicators


def sample_bars(n=320):
    rng = np.random.default_rng(2026)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    open_price = close * (1 + rng.normal(0, 0.002, n))
    return pd.DataFrame({
        "Open": open_price,
        "High": np.maximum(open_price, close) * 1.01,
        "Low": np.minimum(open_price, close) * 0.99,
        "Close": close,
        "Volume": rng.integers(100_000, 500_000, n),
    }, index=pd.bdate_range("2024-01-01", periods=n))


def test_trailing_indicators_are_invariant_to_future_bars():
    bars = sample_bars()
    cutoff = 250
    full = calculate_indicators(bars)
    prefix = calculate_indicators(bars.iloc[:cutoff])
    columns = ["SMA50", "EMA9", "EMA21", "RSI14", "MACD", "MACD_SIGNAL", "ATR14"]
    pd.testing.assert_series_equal(
        full.iloc[cutoff - 1][columns],
        prefix.iloc[-1][columns],
        check_names=False,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_backtest_rejects_unsorted_or_duplicate_dates():
    bars = sample_bars()
    with pytest.raises(ValueError, match="berurutan"):
        backtest(bars.iloc[::-1])
    duplicate = pd.concat([bars, bars.iloc[[-1]]]).sort_index()
    with pytest.raises(ValueError, match="duplikat"):
        backtest(duplicate)


def test_backtest_rejects_invalid_ohlc_relationship():
    bars = sample_bars()
    bars.iloc[100, bars.columns.get_loc("High")] = 1.0
    with pytest.raises(ValueError, match="Relasi OHLC"):
        backtest(bars)


def test_backtest_exposes_bias_control_status():
    result = backtest(sample_bars())
    controls = result["bias_controls"]
    assert "next session open" in controls["signal_execution_timing"]
    assert controls["point_in_time_universe"] is False
    assert controls["survivorship_bias_control"] is False



def test_backtest_applies_sell_side_tax_as_separate_exit_cost():
    bars = sample_bars()
    result = backtest(bars, fee_bps=10, slippage_bps=5, sell_tax_bps=10)
    costs = result["transaction_costs"]
    assert costs["entry_cost_pct"] == pytest.approx(0.15)
    assert costs["exit_cost_pct"] == pytest.approx(0.25)
    assert result["cost_bps_round_trip"] == pytest.approx(40)


def test_backtest_rejects_invalid_sell_side_tax():
    with pytest.raises(ValueError, match="sell tax"):
        backtest(sample_bars(), sell_tax_bps=-1)
