from stock_scoring import score_stock


def test_score_stock_returns_weighted_score_and_coverage():
    row = {
        "market": "US", "returnOnEquity": 0.20, "returnOnAssets": 0.08,
        "revenueGrowth": 0.12, "earningsGrowth": 0.15, "debtToEquity": 45,
        "trailingPE": 18, "priceToBook": 3, "close": 100,
        "ema20": 98, "ema50": 95, "ema200": 90, "macd": 2,
        "macd_signal": 1, "rsi14": 60, "relative_volume": 1.4,
        "marketCap": 1_000_000_000_000, "average_turnover": 100_000_000,
        "atr_pct": 2.5,
    }
    result = score_stock(row)
    assert 0 <= result["ai_score"] <= 100
    assert result["score_coverage_pct"] == 100
    assert result["score_label"] in {"Strong", "Positive", "Neutral", "Weak"}
    assert set(result["factor_scores"]) == {"fundamental", "valuation", "momentum", "liquidity", "risk"}


def test_score_stock_does_not_invent_missing_fundamentals():
    result = score_stock({"market": "IDX", "close": 100, "ema20": 99, "rsi14": 55})
    assert result["ai_score"] is None
    assert result["score_coverage_pct"] < 35
    assert result["factor_scores"]["fundamental"] is None
