import numpy as np
import pandas as pd
import pytest

from portfolio_simulation import (
    run_historical_stress_scenarios, run_portfolio_monte_carlo,
    run_factor_stress_scenario, run_regime_switching_monte_carlo,
    run_block_bootstrap_monte_carlo, estimate_regime_transition_matrix,
    detect_portfolio_structural_break,
)


def returns_frame():
    rng = np.random.default_rng(7)
    return pd.DataFrame({
        "A": rng.normal(0.0005, 0.01, 80),
        "B": rng.normal(0.0003, 0.015, 80),
    })


def test_monte_carlo_is_reproducible_with_fixed_seed():
    frame = returns_frame()
    a = run_portfolio_monte_carlo(frame, {"A": 0.6, "B": 0.4}, simulations=500, horizon_days=60, seed=9)
    b = run_portfolio_monte_carlo(frame, {"A": 0.6, "B": 0.4}, simulations=500, horizon_days=60, seed=9)
    assert a["median_return_pct"] == b["median_return_pct"]
    assert a["var_loss_pct"] == b["var_loss_pct"]
    assert a["simulations"] == 500


def test_monte_carlo_zero_volatility_produces_deterministic_path():
    frame = pd.DataFrame({"A": [0.001] * 30})
    result = run_portfolio_monte_carlo(frame, {"A": 1.0}, simulations=200, horizon_days=20)
    assert result["return_percentiles_pct"]["p05"] == pytest.approx(
        result["return_percentiles_pct"]["p95"]
    )
    assert result["probability_of_loss_pct"] == 0


def test_monte_carlo_rejects_invalid_weights_and_short_history():
    with pytest.raises(ValueError, match="melebihi"):
        run_portfolio_monte_carlo(returns_frame(), {"A": 0.8, "B": 0.4})
    with pytest.raises(ValueError, match="20 observasi"):
        run_portfolio_monte_carlo(returns_frame().head(10), {"A": 0.5, "B": 0.5})


def test_stress_scenarios_calculate_weighted_portfolio_shock():
    result = run_historical_stress_scenarios(
        returns_frame(), {"A": 0.6, "B": 0.4}, {"A": -0.2, "B": -0.1}
    )
    assert result["portfolio_return_pct"] == pytest.approx(-16.0)
    assert result["unallocated_cash_weight"] == pytest.approx(0.0)


def test_stress_scenarios_reject_shock_below_total_loss():
    with pytest.raises(ValueError, match="Shock"):
        run_historical_stress_scenarios(
            returns_frame(), {"A": 1.0, "B": 0.0}, {"A": -1.1, "B": 0}
        )


def test_factor_stress_combines_fx_rate_and_sector_exposures():
    result = run_factor_stress_scenario(
        {"US": 0.6, "IDX": 0.4},
        {
            "US": {"fx_usdidr": 1.0, "interest_rate": -2.0, "sector": 0.5},
            "IDX": {"fx_usdidr": 0.0, "interest_rate": -1.0, "sector": 1.0},
        },
        {"fx_usdidr": 0.05, "interest_rate": 0.01, "sector": -0.10},
    )
    # US: +5% FX -2% rate + -5% sector = -2%; IDX: -1% rate -10% sector = -11%.
    assert result["asset_impacts_pct"]["US"] == pytest.approx(-2.0)
    assert result["asset_impacts_pct"]["IDX"] == pytest.approx(-11.0)
    assert result["portfolio_return_pct"] == pytest.approx(-5.6)


def test_factor_stress_rejects_missing_exposures_and_invalid_shocks():
    with pytest.raises(ValueError, match="harus sama"):
        run_factor_stress_scenario({"A": 1.0}, {}, {"fx": 0.1})
    with pytest.raises(ValueError, match="Factor shock"):
        run_factor_stress_scenario(
            {"A": 1.0}, {"A": {"fx": 1.0}}, {"fx": -1.5}
        )



def regime_frame():
    rng = np.random.default_rng(123)
    calm = pd.DataFrame({
        "A": rng.normal(0.0008, 0.008, 60),
        "B": rng.normal(0.0005, 0.010, 60),
    })
    stress = pd.DataFrame({
        "A": rng.normal(-0.002, 0.025, 40),
        "B": rng.normal(-0.001, 0.030, 40),
    })
    frame = pd.concat([calm, stress], ignore_index=True)
    labels = pd.Series(["calm"] * 60 + ["stress"] * 40, index=frame.index)
    return frame, labels


def test_regime_switching_monte_carlo_is_reproducible_and_reports_regimes():
    frame, labels = regime_frame()
    kwargs = dict(
        historical_returns=frame, weights={"A": 0.6, "B": 0.4},
        regime_labels=labels, transition_matrix=[[0.95, 0.05], [0.20, 0.80]],
        simulations=300, horizon_days=30, seed=17,
    )
    first = run_regime_switching_monte_carlo(**kwargs)
    second = run_regime_switching_monte_carlo(**kwargs)
    assert first["median_return_pct"] == second["median_return_pct"]
    assert first["var_loss_pct"] == second["var_loss_pct"]
    assert first["regimes"] == ["calm", "stress"]
    assert sum(first["final_regime_counts"].values()) == 300
    assert "Markov" in first["assumptions"]


def test_regime_switching_monte_carlo_rejects_bad_transition_and_alignment():
    frame, labels = regime_frame()
    args = dict(
        historical_returns=frame, weights={"A": 0.5, "B": 0.5},
        regime_labels=labels, transition_matrix=[[0.8, 0.3], [0.2, 0.8]],
        simulations=100, horizon_days=10,
    )
    with pytest.raises(ValueError, match="berjumlah 1"):
        run_regime_switching_monte_carlo(**args)
    with pytest.raises(ValueError, match="Index regime labels"):
        run_regime_switching_monte_carlo(
            **{**args, "transition_matrix": [[0.8, 0.2], [0.2, 0.8]],
               "regime_labels": labels.iloc[::-1]}
        )


def test_regime_switching_monte_carlo_requires_minimum_observations_per_regime():
    frame, labels = regime_frame()
    labels.iloc[-25:] = "calm"
    with pytest.raises(ValueError, match="minimal 20 observasi"):
        run_regime_switching_monte_carlo(
            frame, {"A": 0.5, "B": 0.5}, labels,
            [[0.9, 0.1], [0.2, 0.8]], simulations=100, horizon_days=10,
        )



def test_block_bootstrap_monte_carlo_is_reproducible_and_reports_method():
    frame = returns_frame()
    kwargs = dict(
        historical_returns=frame, weights={"A": 0.6, "B": 0.4},
        simulations=300, horizon_days=40, block_size=5, seed=19,
    )
    first = run_block_bootstrap_monte_carlo(**kwargs)
    second = run_block_bootstrap_monte_carlo(**kwargs)
    assert first["median_return_pct"] == second["median_return_pct"]
    assert first["var_loss_pct"] == second["var_loss_pct"]
    assert first["block_size"] == 5
    assert "moving-block bootstrap" in first["assumptions"]


def test_block_bootstrap_monte_carlo_validates_block_size_and_weights():
    frame = returns_frame()
    with pytest.raises(ValueError, match="Block size"):
        run_block_bootstrap_monte_carlo(
            frame, {"A": 0.5, "B": 0.5}, block_size=100,
            simulations=100, horizon_days=10,
        )
    with pytest.raises(ValueError, match="Bobot"):
        run_block_bootstrap_monte_carlo(
            frame, {"A": 0.8, "B": 0.4}, simulations=100, horizon_days=10,
        )


def test_estimate_regime_transition_matrix_uses_ordered_counts_and_smoothing():
    labels = pd.Series(["calm", "calm", "stress", "stress", "calm", "stress"])
    result = estimate_regime_transition_matrix(labels, smoothing=1.0)
    assert result["transition_counts"] == [[1, 2], [1, 1]]
    assert result["transition_matrix"] == [[0.4, 0.6], [0.5, 0.5]]
    assert result["transition_observation_count"] == 5
    assert "not out-of-sample calibrated" in result["method"]


def test_estimate_regime_transition_matrix_validates_labels_and_smoothing():
    with pytest.raises(ValueError, match="Minimal dua label"):
        estimate_regime_transition_matrix(pd.Series(["calm"]))
    with pytest.raises(ValueError, match="tidak dikenal"):
        estimate_regime_transition_matrix(pd.Series(["calm", "unknown"]))
    with pytest.raises(ValueError, match="Smoothing"):
        estimate_regime_transition_matrix(pd.Series(["calm", "stress"]), smoothing=0)


def test_detect_portfolio_structural_break_flags_recent_volatility_shift():
    rng = np.random.default_rng(123)
    values = np.concatenate([
        rng.normal(0.0005, 0.004, 60),
        rng.normal(-0.001, 0.035, 60),
    ])
    series = pd.Series(values, index=pd.date_range("2025-01-01", periods=120))
    result = detect_portfolio_structural_break(series, window=60)
    assert result["detected"] is True
    assert result["volatility_break"] is True
    assert result["status"] == "POTENTIAL_BREAK"
    assert result["recent_window_start"] == str(series.index[60].date())


def test_detect_portfolio_structural_break_does_not_flag_stable_constant_returns():
    series = pd.Series([0.001] * 80, index=pd.date_range("2026-01-01", periods=80))
    result = detect_portfolio_structural_break(series, window=40)
    assert result["detected"] is False
    assert result["volatility_ratio"] == pytest.approx(1.0)


def test_detect_portfolio_structural_break_validates_history_and_thresholds():
    with pytest.raises(ValueError, match="Minimal 40 observasi"):
        detect_portfolio_structural_break(pd.Series([0.01] * 39), window=20)
    with pytest.raises(ValueError, match="Volatility ratio threshold"):
        detect_portfolio_structural_break(pd.Series([0.01] * 80), window=40, volatility_ratio_threshold=1.0)

@pytest.mark.parametrize("runner,extra", [
    (run_portfolio_monte_carlo, {}),
    (run_regime_switching_monte_carlo, {
        "regime_labels": pd.Series(["calm"] * 40 + ["stress"] * 40),
        "transition_matrix": [[0.9, 0.1], [0.2, 0.8]],
    }),
    (run_block_bootstrap_monte_carlo, {}),
])
@pytest.mark.parametrize("parameter,value", [
    ("confidence", float("nan")),
    ("confidence", float("inf")),
    ("confidence", "invalid"),
    ("simulations", True),
    ("horizon_days", 1.5),
    ("seed", -1),
    ("seed", True),
])
def test_simulation_runners_reject_invalid_controls(runner, extra, parameter, value):
    frame = returns_frame()
    if runner is run_regime_switching_monte_carlo:
        kwargs = {
            "historical_returns": frame,
            "weights": {"A": 0.6, "B": 0.4},
            **extra,
            "simulations": 100,
            "horizon_days": 10,
        }
    else:
        kwargs = {
            "historical_returns": frame,
            "weights": {"A": 0.6, "B": 0.4},
            "simulations": 100,
            "horizon_days": 10,
        }
    kwargs[parameter] = value
    with pytest.raises(ValueError):
        runner(**kwargs)


def test_block_bootstrap_rejects_boolean_block_size():
    with pytest.raises(ValueError, match="Block size"):
        run_block_bootstrap_monte_carlo(
            returns_frame(), {"A": 0.5, "B": 0.5},
            block_size=True, simulations=100, horizon_days=10,
        )

@pytest.mark.parametrize("runner,extra", [
    (run_portfolio_monte_carlo, {}),
    (run_regime_switching_monte_carlo, {
        "regime_labels": pd.Series(["calm"] * 40 + ["stress"] * 40),
        "transition_matrix": [[0.9, 0.1], [0.2, 0.8]],
    }),
    (run_block_bootstrap_monte_carlo, {}),
])
def test_simulation_runners_reject_daily_return_at_or_below_total_loss(runner, extra):
    frame = returns_frame()
    frame.iloc[0, 0] = -1.0
    kwargs = {
        "historical_returns": frame,
        "weights": {"A": 0.6, "B": 0.4},
        "simulations": 100,
        "horizon_days": 10,
        **extra,
    }
    with pytest.raises(ValueError, match="-100%"):
        runner(**kwargs)
