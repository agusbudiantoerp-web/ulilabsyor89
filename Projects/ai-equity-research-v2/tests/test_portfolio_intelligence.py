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
