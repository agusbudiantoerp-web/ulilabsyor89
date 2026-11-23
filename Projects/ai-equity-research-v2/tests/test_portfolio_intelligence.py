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
