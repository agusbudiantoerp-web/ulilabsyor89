import numpy as np
import pandas as pd
import pytest

from multi_asset_backtest import run_multi_asset_backtest


def sample_bars(seed=1, n=420):
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0008, 0.006, n)
    close = 100 * np.cumprod(1 + returns)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": 100_000,
    }, index=idx)


def test_multi_asset_backtest_returns_metrics_and_lagged_curve():
    bars = {"AAA": sample_bars(1), "BBB": sample_bars(2)}
    result = run_multi_asset_backtest(bars, initial_capital=1_000_000)
    assert result["final_equity"] > 0
    assert result["max_drawdown_pct"] <= 0
    assert result["active_symbols"] == ["AAA", "BBB"]
    assert result["method"].find("t+1") >= 0
    assert len(result["curve"]) > 100


def test_multi_asset_backtest_rejects_empty_universe():
    with pytest.raises(ValueError, match="minimal satu"):
        run_multi_asset_backtest({})
