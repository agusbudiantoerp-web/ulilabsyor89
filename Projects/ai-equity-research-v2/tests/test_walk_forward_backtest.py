import numpy as np
import pandas as pd
import pytest

from daily_signal_backtest import walk_forward_backtest


def sample_bars(n=1500):
    rng = np.random.default_rng(123)
    returns = rng.normal(0.0004, 0.012, n)
    close = 100 * np.cumprod(1 + returns)
    open_price = close * (1 + rng.normal(0, 0.002, n))
    return pd.DataFrame({
        "Open":open_price,
        "High":np.maximum(open_price,close)*1.01,
        "Low":np.minimum(open_price,close)*0.99,
        "Close":close,
        "Volume":rng.integers(100000,500000,n),
    }, index=pd.bdate_range("2020-01-01", periods=n))


def test_walk_forward_returns_out_of_sample_folds():
    result = walk_forward_backtest(sample_bars(), train_months=24, test_months=6)
    assert result["fold_count"] >= 3
    assert result["total_trades"] >= 0
    assert 0 <= result["profitable_folds_pct"] <= 100
    assert result["method"].startswith("Expanding-history")


def test_walk_forward_rejects_insufficient_history():
    with pytest.raises(ValueError, match="tidak cukup"):
        walk_forward_backtest(sample_bars(300), train_months=36, test_months=12)
