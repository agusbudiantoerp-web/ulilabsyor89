import pandas as pd
import pytest

from institutional_risk import analyze_institutional_risk


def test_institutional_risk_calculates_var_es_concentration_and_stress():
    dates = pd.bdate_range("2025-01-01", periods=100)
    a = pd.Series([0.01] * 90 + [-0.05, -0.06, -0.07, -0.08, -0.09, -0.10, -0.11, -0.12, -0.13, -0.14], index=dates)
    b = pd.Series([0.005] * 90 + [-0.03, -0.04, -0.05, -0.06, -0.07, -0.08, -0.09, -0.10, -0.11, -0.12], index=dates)
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


def test_drawdown_includes_loss_from_initial_capital_baseline():
    dates = pd.bdate_range("2025-01-01", periods=30)
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": 100}
    ])
    result = analyze_institutional_risk(
        positions, {"AAA": pd.Series([-0.01] * 30, index=dates)}
    )
    assert result["risk"].iloc[0]["Max drawdown %"] < 0


def test_institutional_risk_rejects_negative_market_value_and_blank_currency():
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": -1}
    ])
    with pytest.raises(ValueError, match="tidak boleh negatif"):
        analyze_institutional_risk(positions, {})
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "", "Market Value": 100}
    ])
    with pytest.raises(ValueError, match="wajib diisi"):
        analyze_institutional_risk(positions, {})


def test_institutional_risk_rejects_nan_confidence_and_unknown_limits():
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": 100}
    ])
    with pytest.raises(ValueError, match="confidence_level"):
        analyze_institutional_risk(positions, {}, confidence_level=float("nan"))
    with pytest.raises(ValueError, match="tidak dikenal"):
        analyze_institutional_risk(positions, {}, risk_limits={"unknown_limit": 5})
    with pytest.raises(ValueError, match="0–100"):
        analyze_institutional_risk(positions, {}, risk_limits={"max_position_weight_pct": 101})


def test_institutional_risk_normalizes_ticker_and_counts_unknown_sector():
    dates = pd.bdate_range("2025-01-01", periods=30)
    positions = pd.DataFrame([
        {"Ticker": "aaa", "Currency": "idr", "Market Value": 100, "Sector": None},
        {"Ticker": "bbb", "Currency": "IDR", "Market Value": 100, "Sector": ""},
    ])
    returns = {
        "AAA": pd.Series([0.01] * 30, index=dates),
        "BBB": pd.Series([0.02] * 30, index=dates),
    }
    result = analyze_institutional_risk(positions, returns)
    concentration = result["concentration"].iloc[0]
    assert concentration["Largest sector"] == "Unknown"
    assert concentration["Largest sector %"] == pytest.approx(100)
    assert result["risk"].iloc[0]["Coverage %"] == pytest.approx(100)


def test_institutional_risk_rejects_market_value_aggregation_overflow():
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": 1e308},
        {"Ticker": "BBB", "Currency": "IDR", "Market Value": 1e308},
    ])
    with pytest.raises(ValueError, match="market value per mata uang"):
        analyze_institutional_risk(positions, {})
