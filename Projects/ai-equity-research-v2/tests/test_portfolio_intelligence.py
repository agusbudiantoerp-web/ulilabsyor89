import pandas as pd

from portfolio_intelligence import analyze_portfolio, scenario_analysis


def test_portfolio_intelligence_separates_currency_and_sector_exposure():
    positions = pd.DataFrame([
        {"Ticker":"A.JK","Market":"IDX","Currency":"IDR","Market Value":1000,"Sector":"Bank"},
        {"Ticker":"B.JK","Market":"IDX","Currency":"IDR","Market Value":500,"Sector":"Energy"},
        {"Ticker":"AAPL","Market":"US","Currency":"USD","Market Value":200,"Sector":"Technology"},
    ])
    idx = pd.bdate_range("2025-01-01", periods=40)
    returns = {
        "A.JK": pd.Series([0.01] * 40, index=idx, name="A.JK"),
        "B.JK": pd.Series([0.005] * 40, index=idx, name="B.JK"),
        "AAPL": pd.Series([0.002] * 40, index=idx, name="AAPL"),
    }
    result = analyze_portfolio(positions, returns)
    assert result["currency_exposure"] == {"IDR":1500,"USD":200}
    assert set(result["correlations"]) == {"IDR","USD"}
    assert not result["sector_exposure"].empty
    assert set(result["risk"]["Currency"]) == {"IDR","USD"}


def test_scenario_analysis_calculates_shock_pl_by_currency():
    positions = pd.DataFrame([
        {"Ticker":"BBCA.JK","Currency":"IDR","Market Value":1_000_000},
        {"Ticker":"NVDA","Currency":"USD","Market Value":500},
    ])
    result = scenario_analysis(positions, {"BBCA.JK":-10,"NVDA":20})
    assert result.loc[0,"Estimated P/L"] == -100_000
    assert result.loc[1,"Estimated P/L"] == 100


def test_idx_candidate_allocation_rounds_down_to_board_lot():
    from daily_signal_portfolio import allocate_candidates

    candidates = [{
        "market":"IDX", "ticker":"BBCA.JK", "signal":"BUY_CANDIDATE",
        "score":85, "close":100.0, "atr14":10.0,
    }]
    result = allocate_candidates(candidates, 1_000_000, risk_pct=1.0)
    plan = result["positions"][0]["plan"]
    assert plan["lot_size"] == 100
    assert plan["shares"] % 100 == 0
    assert plan["lots"] == plan["shares"] // 100


def test_fx_scenario_is_separate_and_uses_manual_rate():
    from portfolio_intelligence import fx_scenario_analysis

    positions = pd.DataFrame([
        {"Currency":"IDR","Market Value":1_000_000},
        {"Currency":"USD","Market Value":100},
    ])
    result = fx_scenario_analysis(positions, usd_idr=16000, fx_shock_pct=10)
    assert result["current_portfolio_idr"] == 2_600_000
    assert result["scenario_portfolio_idr"] == 2_760_000
    assert result["fx_translation_pnl_idr"] == 160_000


def test_portfolio_risk_reports_partial_data_coverage_and_aggregates_duplicates():
    positions = pd.DataFrame([
        {"Ticker":"AAA","Market":"IDX","Currency":"IDR","Market Value":100},
        {"Ticker":"AAA","Market":"IDX","Currency":"IDR","Market Value":100},
        {"Ticker":"BBB","Market":"IDX","Currency":"IDR","Market Value":200},
    ])
    idx = pd.bdate_range("2025-01-01", periods=30)
    returns = {"AAA":pd.Series([0.01] * 30,index=idx,name="AAA")}
    result = analyze_portfolio(positions, returns)
    risk = result["risk"].iloc[0]
    assert risk["Positions with data"] == 1
    assert risk["Total positions"] == 2
    assert risk["Market value coverage %"] == 50.0
    assert risk["Coverage status"].startswith("Partial")



def test_portfolio_risk_uses_complete_dates_and_reports_expected_shortfall():
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Market": "IDX", "Currency": "IDR", "Market Value": 100},
        {"Ticker": "BBB", "Market": "IDX", "Currency": "IDR", "Market Value": 100},
    ])
    idx = pd.bdate_range("2025-01-01", periods=5)
    returns = {
        "AAA": pd.Series([0.10, 0.10, 0.10, -0.10, -0.20], index=idx, name="AAA"),
        "BBB": pd.Series([None, None, 0.00, -0.10, -0.20], index=idx, name="BBB"),
    }
    result = analyze_portfolio(positions, returns)
    risk = result["risk"].iloc[0]
    assert risk["Observations"] == 3
    assert "Historical ES 95% 1d %" in result["risk"].columns
    assert risk["Historical ES 95% 1d %"] >= risk["Historical VaR 95% 1d %"]


def test_portfolio_risk_does_not_report_negative_var_in_all_up_period():
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Market": "IDX", "Currency": "IDR", "Market Value": 100},
    ])
    idx = pd.bdate_range("2025-01-01", periods=5)
    returns = {"AAA": pd.Series([0.01] * 5, index=idx, name="AAA")}
    result = analyze_portfolio(positions, returns)
    assert result["risk"].iloc[0]["Historical VaR 95% 1d %"] == 0


def test_portfolio_rejects_non_finite_market_value():
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Market": "IDX", "Currency": "IDR", "Market Value": float("inf")},
    ])
    import pytest
    with pytest.raises(ValueError, match="finite"):
        analyze_portfolio(positions, {})


def test_stock_scenario_rejects_loss_beyond_total_capital():
    import pytest
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Currency": "IDR", "Market Value": 100},
    ])
    with pytest.raises(ValueError, match="-100"):
        scenario_analysis(positions, {"AAA": -101})


def test_fx_scenario_rejects_non_finite_rate_or_shock():
    import pytest
    from portfolio_intelligence import fx_scenario_analysis
    positions = pd.DataFrame([{"Currency": "IDR", "Market Value": 100}])
    with pytest.raises(ValueError, match="finite"):
        fx_scenario_analysis(positions, usd_idr=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        fx_scenario_analysis(positions, usd_idr=16000, fx_shock_pct=float("inf"))


def test_portfolio_exposure_includes_missing_sector_and_normalizes_ticker():
    positions = pd.DataFrame([
        {"Ticker": "aaa", "Market": "idx", "Currency": "idr", "Market Value": 100, "Sector": None},
        {"Ticker": "BBB", "Market": "IDX", "Currency": "IDR", "Market Value": 100, "Sector": ""},
    ])
    idx = pd.bdate_range("2025-01-01", periods=30)
    returns = {
        "AAA": pd.Series([0.01] * 30, index=idx, name="AAA"),
        "BBB": pd.Series([0.02] * 30, index=idx, name="BBB"),
    }
    result = analyze_portfolio(positions, returns)
    assert set(result["position_exposure"]["Ticker"]) == {"AAA", "BBB"}
    assert result["sector_exposure"]["Market Value"].sum() == 200
    assert set(result["sector_exposure"]["Sector"]) == {"Unknown"}
    assert result["market_exposure"] == {"IDX": 200}


def test_portfolio_intelligence_rejects_exposure_aggregation_overflow():
    import pytest
    positions = pd.DataFrame([
        {"Ticker": "AAA", "Market": "IDX", "Currency": "IDR", "Market Value": 1e308},
        {"Ticker": "BBB", "Market": "IDX", "Currency": "IDR", "Market Value": 1e308},
    ])
    with pytest.raises(ValueError, match="Agregasi exposure"):
        analyze_portfolio(positions, {})
