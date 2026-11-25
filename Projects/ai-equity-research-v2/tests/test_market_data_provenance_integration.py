from types import SimpleNamespace

import pandas as pd

import daily_signal_engine


def test_load_daily_history_attaches_provider_provenance(monkeypatch):
    index = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=70)
    close = pd.Series(range(100, 170), index=index, dtype=float)
    bars = pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1,
        "Low": close - 1,
        "Close": close,
        "Volume": 100_000,
    }, index=index)
    calls = {}

    def fake_download(ticker, **kwargs):
        calls["ticker"] = ticker
        calls.update(kwargs)
        return bars

    monkeypatch.setitem(__import__("sys").modules, "yfinance", SimpleNamespace(download=fake_download))
    monkeypatch.setattr(daily_signal_engine, "resolve_market_ticker", lambda symbol, market: {
        "market": "IDX", "exchange": "Indonesia Stock Exchange",
        "ticker": "BBCA.JK", "currency": "IDR",
    })

    loaded, meta = daily_signal_engine.load_daily_history("BBCA", "IDX", "1y")

    provenance = meta["data_provenance"]
    assert calls["auto_adjust"] is True
    assert provenance["source"] == "Yahoo Finance"
    assert provenance["source_ticker"] == "BBCA.JK"
    assert provenance["currency"] == "IDR"
    assert provenance["adjustment_mode"] == "auto_adjusted"
    assert provenance["price_basis"] == "adjusted_ohlc"
    assert provenance["bar_count"] == len(loaded)
    assert provenance["quality_status"] == "PASS"
