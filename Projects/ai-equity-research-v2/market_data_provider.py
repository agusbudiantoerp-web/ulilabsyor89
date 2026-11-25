"""Provider abstraction with bounded retries and explicit rate-limit handling."""
from __future__ import annotations

import time
import threading
from datetime import datetime, timezone
from typing import Protocol, Any

import pandas as pd


class MarketDataError(RuntimeError):
    pass


class MarketDataUnavailable(MarketDataError):
    pass


class MarketDataRateLimited(MarketDataError):
    pass


class MarketDataProvider(Protocol):
    name: str

    def fetch_history(self, ticker: str, *, period: str, interval: str = "1d",
                      auto_adjust: bool = True) -> pd.DataFrame: ...

    def fetch_info(self, ticker: str) -> dict[str, Any]: ...


def _is_rate_limit_error(exc: Exception) -> bool:
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(token in message for token in ("rate limit", "too many requests", "http 429", "status code 429"))


class YahooFinanceProvider:
    name = "Yahoo Finance"

    _history_cache = {}
    _info_cache = {}
    _cache_lock = threading.RLock()

    def __init__(self, *, max_attempts: int = 3, base_delay_seconds: float = 0.5,
                 cache_ttl_seconds: float = 300.0, sleep=time.sleep):
        if not 1 <= int(max_attempts) <= 5 or base_delay_seconds < 0 or cache_ttl_seconds < 0:
            raise ValueError("Retry/cache policy harus valid; attempts 1–5 dan TTL/delay non-negatif.")
        self.max_attempts = int(max_attempts)
        self.base_delay_seconds = float(base_delay_seconds)
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.sleep = sleep

    @classmethod
    def clear_cache(cls):
        with cls._cache_lock:
            cls._history_cache.clear()
            cls._info_cache.clear()

    def _cached(self, cache, key):
        if self.cache_ttl_seconds <= 0:
            return None
        with self._cache_lock:
            item = cache.get(key)
            if not item:
                return None
            fetched_monotonic, value, retrieved_at = item
            age = time.monotonic() - fetched_monotonic
            if age > self.cache_ttl_seconds:
                cache.pop(key, None)
                return None
            return value, retrieved_at, age

    @staticmethod
    def _yf():
        try:
            import yfinance as yf
            return yf
        except ImportError as exc:
            raise MarketDataUnavailable("Paket yfinance belum terpasang.") from exc

    def fetch_history(self, ticker: str, *, period: str, interval: str = "1d",
                      auto_adjust: bool = True) -> pd.DataFrame:
        symbol = str(ticker or "").strip()
        if not symbol:
            raise ValueError("Ticker provider wajib diisi.")
        cache_key = (symbol, str(period), str(interval), bool(auto_adjust))
        cached = self._cached(self._history_cache, cache_key)
        if cached is not None:
            frame, retrieved_at, age = cached
            result = frame.copy()
            result.attrs.update(frame.attrs)
            result.attrs.update({
                "provider_retrieved_at": retrieved_at,
                "provider_cache_hit": True,
                "provider_cache_age_seconds": age,
            })
            return result
        yf = self._yf()
        last_error = None
        for attempt in range(self.max_attempts):
            try:
                frame = yf.download(
                    symbol, period=period, interval=interval,
                    auto_adjust=auto_adjust, progress=False, threads=False,
                )
                if frame is None or frame.empty:
                    raise MarketDataUnavailable(f"Data harian {symbol} tidak tersedia.")
                retrieved_at = datetime.now(timezone.utc).isoformat()
                stored = frame.copy()
                stored.attrs.update(frame.attrs)
                with self._cache_lock:
                    self._history_cache[cache_key] = (time.monotonic(), stored, retrieved_at)
                result = frame.copy()
                result.attrs.update(frame.attrs)
                result.attrs.update({
                    "provider_retrieved_at": retrieved_at,
                    "provider_cache_hit": False,
                    "provider_cache_age_seconds": 0.0,
                })
                return result
            except Exception as exc:
                if isinstance(exc, MarketDataUnavailable):
                    raise
                if _is_rate_limit_error(exc):
                    raise MarketDataRateLimited(
                        "Provider membatasi permintaan. Tunggu sesuai kebijakan provider sebelum mencoba lagi."
                    ) from exc
                last_error = exc
                if attempt + 1 >= self.max_attempts:
                    break
                self.sleep(self.base_delay_seconds * (2 ** attempt))
        raise MarketDataUnavailable(
            f"Pengambilan histori gagal setelah {self.max_attempts} percobaan ({type(last_error).__name__})."
        ) from last_error

    def fetch_info(self, ticker: str) -> dict[str, Any]:
        symbol = str(ticker or "").strip()
        if not symbol:
            raise ValueError("Ticker provider wajib diisi.")
        cached = self._cached(self._info_cache, symbol)
        if cached is not None:
            info, _, _ = cached
            return dict(info)
        yf = self._yf()
        try:
            info = yf.Ticker(symbol).get_info()
        except Exception as exc:
            if _is_rate_limit_error(exc):
                raise MarketDataRateLimited(
                    "Provider membatasi permintaan. Tunggu sesuai kebijakan provider sebelum mencoba lagi."
                ) from exc
            raise MarketDataUnavailable(f"Fundamental tidak tersedia ({type(exc).__name__}).") from exc
        if not isinstance(info, dict) or not info:
            raise MarketDataUnavailable("Fundamental provider kosong.")
        with self._cache_lock:
            self._info_cache[symbol] = (time.monotonic(), dict(info), datetime.now(timezone.utc).isoformat())
        return dict(info)
