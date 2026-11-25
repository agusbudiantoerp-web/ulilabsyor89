"""Deterministic technical signal engine. Research candidates only; never places orders."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import math
import pandas as pd
from market_engine import resolve_market_ticker
from market_data_contract import build_market_data_metadata
from market_data_provider import YahooFinanceProvider

RULESET_VERSION = "1.0.0"

DEFAULT_CONFIG = {
    "min_score": 65, "rsi_min": 50.0, "rsi_max": 72.0,
    "min_relative_volume": 1.10, "atr_stop_multiple": 1.5,
    "reward_risk_min": 1.8, "entry_buffer_pct": 0.01,
    "max_bar_age_days": 5,
}

def calculate_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(bars.columns):
        raise ValueError("Data wajib memiliki Open, High, Low, Close, Volume.")
    x = bars.copy().sort_index()
    for col in required:
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.dropna(subset=["Open", "High", "Low", "Close"])
    if (x[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise ValueError("Harga OHLC harus positif.")
    c, v = x["Close"], x["Volume"].fillna(0)
    x["SMA20"], x["SMA50"], x["SMA200"] = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    x["EMA9"], x["EMA21"] = c.ewm(span=9, adjust=False).mean(), c.ewm(span=21, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    x["RSI14"] = 100 - 100 / (1 + rs)
    x.loc[(loss == 0) & (gain > 0), "RSI14"] = 100
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    x["MACD"] = e12 - e26
    x["MACD_SIGNAL"] = x["MACD"].ewm(span=9, adjust=False).mean()
    prev = c.shift(1)
    tr = pd.concat([x["High"]-x["Low"], (x["High"]-prev).abs(), (x["Low"]-prev).abs()], axis=1).max(axis=1)
    x["ATR14"] = tr.ewm(alpha=1/14, adjust=False).mean()
    x["AVG_VOLUME20"] = v.rolling(20).mean()
    x["REL_VOLUME"] = v / x["AVG_VOLUME20"].replace(0, float("nan"))
    x["HIGH20"] = x["High"].rolling(20).max().shift(1)
    x["LOW20"] = x["Low"].rolling(20).min().shift(1)
    x["RETURN5"] = c.pct_change(5) * 100
    return x

def load_daily_history(symbol: str, market: str, period: str = "1y") -> tuple[pd.DataFrame, dict]:
    meta = resolve_market_ticker(symbol, market)
    bars = YahooFinanceProvider().fetch_history(
        meta["ticker"], period=period, interval="1d", auto_adjust=True
    )
    provider_retrieved_at = bars.attrs.get("provider_retrieved_at")
    provider_cache_hit = bool(bars.attrs.get("provider_cache_hit", False))
    provider_cache_age = float(bars.attrs.get("provider_cache_age_seconds", 0.0))
    required = ["Open", "High", "Low", "Close", "Volume"]

    if isinstance(bars.columns, pd.MultiIndex):
        selected = {}
        for field in required:
            matches = [
                i for i, column in enumerate(bars.columns)
                if field in {
                    str(part).strip().title()
                    for part in (column if isinstance(column, tuple) else (column,))
                }
            ]
            if not matches:
                raise ValueError(f"Kolom {field} tidak ditemukan dari Yahoo Finance.")
            selected[field] = bars.iloc[:, matches[0]]

        bars = pd.DataFrame(selected, index=bars.index)

    else:
        bars.columns = [str(c).strip().title() for c in bars.columns]
        bars = bars.loc[:, ~bars.columns.duplicated(keep="first")]

        missing = set(required) - set(bars.columns)
        if missing:
            raise ValueError(f"Kolom harga tidak tersedia: {sorted(missing)}")

        bars = bars.loc[:, required]
    bars.index = pd.to_datetime(bars.index)
    if getattr(bars.index, "tz", None) is not None:
        bars.index = bars.index.tz_localize(None)
    bars = bars[~bars.index.duplicated(keep="last")].sort_index()
    bars = bars.dropna(subset=["Open", "High", "Low", "Close"])
    if len(bars) < 60:
        raise ValueError("Minimal 60 sesi perdagangan diperlukan.")
    retrieved_at = datetime.fromisoformat(provider_retrieved_at) if provider_retrieved_at else datetime.now(timezone.utc)
    meta.update({
        "source": YahooFinanceProvider.name,
        "retrieved_at": retrieved_at.isoformat(),
        "cache_hit": provider_cache_hit,
        "cache_age_seconds": provider_cache_age,
    })
    meta["data_provenance"] = build_market_data_metadata(
        bars, meta, adjustment_mode="auto_adjusted", retrieved_at=retrieved_at
    )
    return bars, meta

def evaluate_signal(bars: pd.DataFrame, market_meta: dict | None = None,
                    config: dict | None = None, as_of: datetime | None = None) -> dict[str, Any]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    x = calculate_indicators(bars)
    valid = x.dropna(subset=["EMA21", "RSI14", "MACD", "MACD_SIGNAL", "ATR14", "REL_VOLUME", "SMA50"])
    if len(valid) < 2:
        raise ValueError("Riwayat belum cukup untuk menghitung indikator.")
    r, p = valid.iloc[-1], valid.iloc[-2]
    close, atr = float(r.Close), float(r.ATR14)
    if not all(math.isfinite(z) for z in (close, atr)) or close <= 0 or atr <= 0:
        raise ValueError("Harga penutupan atau ATR tidak valid.")
    bar_date = pd.Timestamp(valid.index[-1]).date()
    today = (as_of or datetime.now(timezone.utc)).date()
    age = max(0, (today - bar_date).days)
    checks = {
        "price_above_ema21": close > float(r.EMA21),
        "ema9_above_ema21": float(r.EMA9) > float(r.EMA21),
        "macd_bullish": float(r.MACD) > float(r.MACD_SIGNAL),
        "macd_improving": float(r.MACD) > float(p.MACD),
        "rsi_momentum": float(cfg["rsi_min"]) <= float(r.RSI14) <= float(cfg["rsi_max"]),
        "relative_volume": float(r.REL_VOLUME) >= float(cfg["min_relative_volume"]),
        "price_above_sma50": close > float(r.SMA50),
    }
    weights = {"price_above_ema21":20, "ema9_above_ema21":20, "macd_bullish":15,
               "macd_improving":10, "rsi_momentum":15, "relative_volume":10, "price_above_sma50":10}
    score = sum(weights[k] for k, passed in checks.items() if passed)
    warnings = []
    if age > int(cfg["max_bar_age_days"]):
        warnings.append(f"Data terakhir berumur {age} hari kalender; sinyal dibatalkan.")
    if float(r.Volume) <= 0:
        warnings.append("Volume sesi terakhir nol atau tidak tersedia.")
    stop = max(0.01, close - float(cfg["atr_stop_multiple"]) * atr)
    risk = close - stop
    target = close + float(cfg["reward_risk_min"]) * risk
    rr = (target - close) / risk if risk > 0 else 0.0
    if warnings:
        state = "NO_TRADE"
    elif score >= int(cfg["min_score"]) and rr >= float(cfg["reward_risk_min"]):
        state = "BUY_CANDIDATE"
    elif score >= 40:
        state = "WATCH"
    else:
        state = "NO_TRADE"
    meta = market_meta or {}
    return {
        "ruleset_version": RULESET_VERSION, "market": meta.get("market"), "exchange": meta.get("exchange"),
        "ticker": meta.get("ticker"), "currency": meta.get("currency"), "source": meta.get("source", "provided"),
        "retrieved_at": meta.get("retrieved_at"), "bar_date": bar_date.isoformat(), "bar_age_days": age,
        "close": close, "signal": state, "score": int(score), "checks": checks, "warnings": warnings,
        "rsi14": float(r.RSI14), "ema9": float(r.EMA9), "ema21": float(r.EMA21),
        "macd": float(r.MACD), "macd_signal": float(r.MACD_SIGNAL), "atr14": atr,
        "relative_volume": float(r.REL_VOLUME), "return5_pct": float(r.RETURN5) if pd.notna(r.RETURN5) else None,
        "entry_low": close * (1-float(cfg["entry_buffer_pct"])),
        "entry_high": close * (1+float(cfg["entry_buffer_pct"])),
        "stop_loss": stop, "target": target, "reward_risk": rr,
        "evaluated_at": datetime.now(timezone.utc).isoformat()
    }

def scan_symbol(symbol: str, market: str, period: str = "1y", config: dict | None = None) -> dict:
    bars, meta = load_daily_history(symbol, market, period)
    return evaluate_signal(bars, meta, config)
