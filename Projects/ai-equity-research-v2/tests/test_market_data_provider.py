from types import SimpleNamespace

import pandas as pd
import pytest

from market_data_provider import (
    MarketDataRateLimited, MarketDataUnavailable, YahooFinanceProvider,
)


def test_provider_returns_history_with_explicit_adjustment(monkeypatch):
    calls = {}
    frame = pd.DataFrame({"Close": [1.0]})

    def download(ticker, **kwargs):
        calls["ticker"] = ticker
        calls.update(kwargs)
        return frame

    monkeypatch.setitem(__import__("sys").modules, "yfinance", SimpleNamespace(download=download))
    provider = YahooFinanceProvider(max_attempts=1)
    result = provider.fetch_history("BBCA.JK", period="1y", auto_adjust=True)
    assert result.equals(frame)
    assert calls["auto_adjust"] is True
    assert calls["threads"] is False


def test_provider_retries_transient_errors_with_bounded_backoff(monkeypatch):
    attempts = {"count": 0}
    delays = []

    def download(ticker, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise TimeoutError("temporary network timeout")
        return pd.DataFrame({"Close": [1.0]})

    monkeypatch.setitem(__import__("sys").modules, "yfinance", SimpleNamespace(download=download))
    provider = YahooFinanceProvider(max_attempts=3, base_delay_seconds=0.25, sleep=delays.append)
    provider.fetch_history("BBCA.JK", period="1y")
    assert attempts["count"] == 2
    assert delays == [0.25]


def test_provider_does_not_retry_rate_limit(monkeypatch):
    attempts = {"count": 0}

    def download(ticker, **kwargs):
        attempts["count"] += 1
        raise RuntimeError("Too Many Requests HTTP 429")

    monkeypatch.setitem(__import__("sys").modules, "yfinance", SimpleNamespace(download=download))
    provider = YahooFinanceProvider(max_attempts=5, sleep=lambda _: None)
    with pytest.raises(MarketDataRateLimited):
        provider.fetch_history("BBCA.JK", period="1y")
    assert attempts["count"] == 1


def test_provider_rejects_empty_and_blank_ticker(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "yfinance", SimpleNamespace(
        download=lambda *args, **kwargs: pd.DataFrame()
    ))
    provider = YahooFinanceProvider(max_attempts=2, sleep=lambda _: None)
    with pytest.raises(ValueError, match="Ticker"):
        provider.fetch_history("", period="1y")
    with pytest.raises(MarketDataUnavailable, match="tidak tersedia"):
        provider.fetch_history("MISSING", period="1y")


def test_provider_validates_retry_policy():
    with pytest.raises(ValueError):
        YahooFinanceProvider(max_attempts=8)
