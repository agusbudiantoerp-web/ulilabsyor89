import pandas as pd
import pytest

from fx_portfolio_engine import (
    combine_mixed_currency_returns,
    convert_asset_returns_to_base_currency,
)


def test_usd_asset_in_idr_base_separates_local_and_fx_return():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    local = pd.Series([100.0, 110.0], index=dates)
    fx = pd.Series([15000.0, 16500.0], index=dates)
    result = convert_asset_returns_to_base_currency(local, "USD", fx, "IDR")
    assert result["local_return"].iloc[1] == pytest.approx(0.10)
    assert result["fx_return"].iloc[1] == pytest.approx(0.10)
    assert result["base_return"].iloc[1] == pytest.approx(0.21)
    assert result["fx_contribution_pct"].iloc[1] == pytest.approx(11.0)


def test_idr_asset_in_usd_base_uses_inverse_fx():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    local = pd.Series([15000.0, 16500.0], index=dates)
    fx = pd.Series([15000.0, 16500.0], index=dates)
    result = convert_asset_returns_to_base_currency(local, "IDR", fx, "USD")
    assert result["local_return"].iloc[1] == pytest.approx(0.10)
    assert result["fx_return"].iloc[1] == pytest.approx(-1 / 11, rel=1e-5)
    assert result["base_return"].iloc[1] == pytest.approx(0.0)


def test_same_currency_has_no_fx_contribution():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    local = pd.Series([100.0, 105.0], index=dates)
    fx = pd.Series([15000.0, 16000.0], index=dates)
    result = convert_asset_returns_to_base_currency(local, "IDR", None, "IDR")
    assert result["base_return"].iloc[1] == pytest.approx(0.05)
    assert result["fx_return"].iloc[1] == pytest.approx(0.0)


def test_missing_fx_beyond_tolerance_is_rejected():
    local = pd.Series([100.0], index=pd.to_datetime(["2026-01-20"]))
    fx = pd.Series([15000.0], index=pd.to_datetime(["2026-01-01"]))
    with pytest.raises(ValueError, match="Cakupan FX"):
        convert_asset_returns_to_base_currency(local, "USD", fx, "IDR", max_fx_gap_days=3)


def test_mixed_currency_portfolio_combines_returns_without_reweighting_closed_market():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    fx = pd.Series([15000.0, 15000.0, 15000.0], index=dates)
    idx_close = pd.Series([100.0, 110.0], index=dates[[0, 2]])
    us_close = pd.Series([100.0, 100.0, 110.0], index=dates)
    result = combine_mixed_currency_returns(
        {"IDX": idx_close, "US": us_close},
        {"IDX": "IDR", "US": "USD"},
        {"IDX": 0.5, "US": 0.5}, fx, "IDR",
    )
    assert result["asset_returns"].loc[dates[1], "IDX"] == 0
    assert result["asset_returns"].loc[dates[1], "US"] == 0
    assert result["curve"].iloc[-1]["equity_index"] > 1.0


def test_weights_and_currencies_must_be_explicit_and_valid():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    closes = pd.Series([100.0, 101.0], index=dates)
    fx = pd.Series([15000.0, 15000.0], index=dates)
    with pytest.raises(ValueError, match="Total bobot"):
        combine_mixed_currency_returns(
            {"A": closes}, {"A": "IDR"}, {"A": 1.1}, fx, "IDR"
        )
