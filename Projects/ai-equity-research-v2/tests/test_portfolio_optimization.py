import numpy as np
import pandas as pd
import pytest

from portfolio_optimization import optimize_portfolio


def fixtures(currency="IDR", n=120):
    dates = pd.bdate_range("2025-01-01", periods=n)
    rng = np.random.default_rng(17)
    common = rng.normal(0.0004, 0.008, n)
    returns = {
        "AAA": pd.Series(common + rng.normal(0.0002, 0.006, n), index=dates),
        "BBB": pd.Series(common * 0.5 + rng.normal(0.0005, 0.012, n), index=dates),
        "CCC": pd.Series(common * 0.8 + rng.normal(0.0003, 0.009, n), index=dates),
    }
    positions = pd.DataFrame([
        {"Ticker": ticker, "Currency": currency, "Market Value": value}
        for ticker, value in zip(returns, [500, 300, 200])
    ])
    return positions, returns


def test_optimizer_returns_valid_risk_parity_and_max_sharpe_weights():
    positions, returns = fixtures()
    result = optimize_portfolio(positions, returns, simulations=2000)
    for key in ("risk_parity", "max_sharpe"):
        table = result[key]
        assert table["Weight %"].sum() == pytest.approx(100, abs=1e-6)
        assert (table["Weight %"] >= 0).all()
        assert (table["Weight %"] <= 40.000001).all()
    assert result["observations"] == 120
    assert result["max_sharpe_metrics"]["method"].startswith("Deterministic")
    assert result["risk_parity"]["Risk Contribution %"].sum() == pytest.approx(100, abs=1e-5)


def test_optimizer_rejects_mixed_currencies_and_short_history():
    positions, returns = fixtures()
    positions.loc[1, "Currency"] = "USD"
    with pytest.raises(ValueError, match="satu mata uang"):
        optimize_portfolio(positions, returns)
    positions, returns = fixtures(n=30)
    with pytest.raises(ValueError, match="minimal 60"):
        optimize_portfolio(positions, returns)


def test_optimizer_rejects_missing_asset_returns_and_invalid_cap():
    positions, returns = fixtures()
    returns.pop("BBB")
    with pytest.raises(ValueError, match="Histori return"):
        optimize_portfolio(positions, returns)
    positions, returns = fixtures()
    with pytest.raises(ValueError, match="maksimum"):
        optimize_portfolio(positions, returns, max_weight=0.2)


def test_optimizer_rejects_negative_value_and_missing_currency():
    import pytest
    idx = pd.bdate_range("2025-01-01", periods=80)
    returns = {
        "AAA": pd.Series(np.linspace(-0.01, 0.01, 80), index=idx),
        "BBB": pd.Series(np.linspace(0.01, -0.01, 80), index=idx),
    }
    negative = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": 100},
        {"Ticker": "BBB", "Currency": "IDR", "Market Value": -10},
    ])
    with pytest.raises(ValueError, match="tidak boleh negatif"):
        optimize_portfolio(negative, returns)
    blank = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": 100},
        {"Ticker": "BBB", "Currency": "", "Market Value": 100},
    ])
    with pytest.raises(ValueError, match="wajib diisi"):
        optimize_portfolio(blank, returns)
