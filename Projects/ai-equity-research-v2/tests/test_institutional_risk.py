import pandas as pd
import pytest

from institutional_risk import analyze_institutional_risk


def test_institutional_risk_calculates_var_es_concentration_and_stress():
    dates = pd.bdate_range("2025-01-01", periods=100)
    a = pd.Series([0.01] * 95 + [-0.05, -0.06, -0.07, -0.08, -0.09], index=dates)
    b = pd.Series([0.005] * 95 + [-0.03, -0.04, -0.05, -0.06, -0.07], index=dates)
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": 800, "Sector": "Bank"},
        {"Ticker": "BBB", "Currency": "IDR", "Market Value": 200, "Sector": "Energy"},
    ])
    result = analyze_institutional_risk(
        positions,
        {"AAA": a, "BBB": b},
        stress_scenarios={"Market shock": {"AAA": -20, "BBB": -10}},
        risk_limits={"max_position_weight_pct": 70},
    )

    risk = result["risk"].iloc[0]
    assert risk["Historical VaR %"] > 0
    assert risk["Historical ES %"] >= risk["Historical VaR %"]
    assert risk["Parametric VaR %"] > 0
    assert result["concentration"].iloc[0]["Largest position %"] == pytest.approx(80)
    assert len(result["limit_breaches"]) >= 1
    assert result["stress"].iloc[0]["Estimated P/L"] == pytest.approx(-180)


def test_institutional_risk_reports_partial_return_coverage():
    dates = pd.bdate_range("2025-01-01", periods=30)
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "USD", "Market Value": 50},
        {"Ticker": "BBB", "Currency": "USD", "Market Value": 50},
    ])
    result = analyze_institutional_risk(
        positions, {"AAA": pd.Series([0.01] * 30, index=dates)}
    )
    row = result["risk"].iloc[0]
    assert row["Coverage %"] == pytest.approx(50)
    assert row["Status"] == "PARTIAL COVERAGE"


def test_institutional_risk_rejects_invalid_confidence_and_shock():
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": 100}
    ])
    with pytest.raises(ValueError, match="confidence_level"):
        analyze_institutional_risk(positions, {}, confidence_level=0.8)
    with pytest.raises(ValueError, match="Shock saham"):
        analyze_institutional_risk(
            positions, {}, stress_scenarios={"bad": {"AAA": -101}}
        )
