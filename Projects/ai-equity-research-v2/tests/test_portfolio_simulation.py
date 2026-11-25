import numpy as np
import pandas as pd
import pytest

from portfolio_simulation import run_historical_stress_scenarios, run_portfolio_monte_carlo


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
