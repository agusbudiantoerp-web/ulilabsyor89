from advanced_stock_screener import ADVANCED_UNIVERSE, run_advanced_screener


def test_advanced_universe_has_both_markets():
    assert len(ADVANCED_UNIVERSE["IDX"]) >= 30
    assert len(ADVANCED_UNIVERSE["US"]) >= 30


def test_screener_applies_market_specific_native_currency_caps(monkeypatch):
    import advanced_stock_screener as screener

    def fake_screen(symbol, market, period):
        cap = 2_000_000_000_000 if market == "IDX" else 2_000_000_000
        return {
            "market": market, "ticker": symbol, "marketCap": cap,
            "ai_score": 80, "score_coverage_pct": 80, "sector": "Technology",
        }

    monkeypatch.setattr(screener, "screen_symbol", fake_screen)
    result = run_advanced_screener(
        markets=["IDX", "US"],
        symbols_by_market={"IDX": ["BBCA"], "US": ["AAPL"]},
        min_score=60,
        min_market_cap={"IDX": 1_000_000_000_000, "US": 3_000_000_000},
    )
    assert result["raw_success"] == 2
    assert [item["market"] for item in result["results"]] == ["IDX"]


def test_screener_applies_technical_filters(monkeypatch):
    import advanced_stock_screener as screener

    def fake_screen(symbol, market, period):
        return {
            "market":market, "ticker":symbol, "marketCap":1_000_000,
            "ai_score":80, "score_coverage_pct":90, "sector":"Technology",
            "rsi14":62 if symbol == "AAA" else 42,
            "relative_volume":1.6 if symbol == "AAA" else 0.7,
            "breakout_20d":symbol == "AAA",
            "close":110 if symbol == "AAA" else 90,
            "ema200":100,
        }

    monkeypatch.setattr(screener, "screen_symbol", fake_screen)
    result = run_advanced_screener(
        markets=["US"], symbols_by_market={"US":["AAA","BBB"]},
        min_rsi=50, max_rsi=70, min_relative_volume=1.0,
        require_breakout=True, require_above_ema200=True,
    )
    assert [item["ticker"] for item in result["results"]] == ["AAA"]
