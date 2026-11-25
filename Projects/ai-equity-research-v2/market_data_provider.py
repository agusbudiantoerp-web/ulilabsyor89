"""Provider abstraction with bounded retries and explicit rate-limit handling."""
from __future__ import annotations

import time
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

    def __init__(self, *, max_attempts: int = 3, base_delay_seconds: float = 0.5,
                 sleep=time.sleep):
        if not 1 <= int(max_attempts) <= 5 or base_delay_seconds < 0:
            raise ValueError("Retry policy harus 1–5 attempts dan delay non-negatif.")
        self.max_attempts = int(max_attempts)
        self.base_delay_seconds = float(base_delay_seconds)
        self.sleep = sleep

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
                return frame
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
        return info
