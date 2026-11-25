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


@pytest.mark.parametrize("bad_close", [float("nan"), float("inf"), 0.0, -1.0, "bad"])
def test_multi_asset_rejects_invalid_close_values(bad_close):
    bars = sample_bars()
    bars.iloc[10, bars.columns.get_loc("Close")] = bad_close
    with pytest.raises(ValueError, match="Close"):
        run_multi_asset_backtest({"AAA": bars})


def test_multi_asset_rejects_duplicate_dates_instead_of_silently_sorting():
    bars = sample_bars()
    bars.index = list(bars.index[:-1]) + [bars.index[-2]]
    with pytest.raises(ValueError, match="duplikat"):
        run_multi_asset_backtest({"AAA": bars})


def test_multi_asset_rejects_unsorted_dates():
    bars = sample_bars()
    bars = bars.iloc[::-1]
    with pytest.raises(ValueError, match="berurutan"):
        run_multi_asset_backtest({"AAA": bars})


def test_multi_asset_rejects_duplicate_sessions_after_timezone_normalization():
    bars = sample_bars()
    duplicate_instants = pd.DatetimeIndex([
        "2024-11-03T01:30:00-04:00",
        "2024-11-03T01:30:00-05:00",
    ]).tz_convert("America/New_York")
    remaining = pd.date_range(
        "2024-11-04", periods=len(bars) - 2, freq="B", tz="America/New_York"
    )
    bars.index = duplicate_instants.append(remaining)
    with pytest.raises(ValueError, match="duplikat"):
        run_multi_asset_backtest({"AAA": bars})


@pytest.mark.parametrize("kwargs", [
    {"initial_capital": True},
    {"initial_capital": float("inf")},
    {"fee_bps": float("nan")},
    {"slippage_bps": -1},
    {"max_positions": True},
    {"min_history": 1.5},
    {"max_weight_pct": 101},
])
def test_multi_asset_rejects_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        run_multi_asset_backtest({"AAA": sample_bars()}, **kwargs)


def test_multi_asset_rejects_invalid_benchmark_close():
    benchmark = sample_bars()
    benchmark.iloc[0, benchmark.columns.get_loc("Close")] = float("inf")
    with pytest.raises(ValueError, match="Benchmark.*Close"):
        run_multi_asset_backtest({"AAA": sample_bars()}, benchmark_bars=benchmark)


def test_multi_asset_rejects_non_datetime_index():
    bars = sample_bars()
    bars.index = range(len(bars))
    with pytest.raises(ValueError, match="DatetimeIndex"):
        run_multi_asset_backtest({"AAA": bars})


def test_multi_asset_result_documents_split_adjustment_policy():
    result = run_multi_asset_backtest({"AAA": sample_bars()})
    policy = result["price_adjustment_policy"].lower()
    assert "does not apply stock-split adjustments" in policy
    assert "do not apply the same split again" in policy


def test_multi_asset_keeps_last_known_signal_across_other_market_holiday():
    bars = sample_bars(seed=42)
    missing_date = bars.index[300]
    complete = run_multi_asset_backtest(
        {"AAA": bars, "BBB": bars.copy()},
        max_positions=2,
        max_weight_pct=50,
    )
    holiday_bars = bars.drop(index=missing_date)
    holiday = run_multi_asset_backtest(
        {"AAA": bars, "BBB": holiday_bars},
        max_positions=2,
        max_weight_pct=50,
    )
    complete_turnover = {
        row["date"]: row["turnover"] for row in complete["curve"]
    }
    holiday_turnover = {
        row["date"]: row["turnover"] for row in holiday["curve"]
    }
    key = missing_date.date().isoformat()
    assert holiday_turnover[key] == pytest.approx(complete_turnover[key])
