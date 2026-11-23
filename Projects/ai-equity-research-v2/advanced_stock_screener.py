"""Advanced IDX/US screener using reported Yahoo Finance data and daily bars."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from daily_signal_engine import load_daily_history, calculate_indicators
from market_engine import resolve_market_ticker
from stock_scoring import score_stock

ADVANCED_UNIVERSE = {
    "IDX": [
        "BBCA","BBRI","BMRI","BBNI","BBTN","BRIS","ARTO","BBYB","BTPN","BNGA",
        "ASII","UNTR","ADRO","PTBA","ITMG","MEDC","PGAS","ANTM","INCO","MDKA",
        "TPIA","BRPT","AMMN","INKP","TKIM","SMGR","INTP","TLKM","ISAT","EXCL",
        "ICBP","INDF","MYOR","KLBF","SIDO","GOTO","BUKA","ACES","MAPI","CPIN"
    ],
    "US": [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","AVGO","TSLA","BRK.B","JPM",
        "V","MA","LLY","UNH","XOM","COST","WMT","HD","PG","JNJ",
        "ABBV","KO","PEP","MRK","BAC","NFLX","CRM","ORCL","AMD","QCOM",
        "ADBE","CSCO","INTC","TMO","CAT","GE","SPY","QQQ","IWM","DIA"
    ],
}


def _safe_info(info: dict, key: str):
    value = info.get(key)
    try:
        number = float(value)
        return number if pd.notna(number) else None
    except (TypeError, ValueError):
        return None


def screen_symbol(symbol: str, market: str, period: str = "1y") -> dict[str, Any]:
    resolved = resolve_market_ticker(symbol, market)
    bars, meta = load_daily_history(symbol, market, period)
    indicators = calculate_indicators(bars)
    row = indicators.iloc[-1]
    import yfinance as yf
    info = yf.Ticker(resolved["ticker"]).get_info()
    info = info if isinstance(info, dict) else {}

    close = float(row["Close"])
    atr = float(row["ATR14"]) if pd.notna(row["ATR14"]) else None
    result = {
        "market": market.upper(),
        "ticker": resolved["ticker"],
        "company": info.get("longName") or info.get("shortName") or resolved["ticker"],
        "sector": info.get("sector") or "Unknown",
        "industry": info.get("industry") or "Unknown",
        "currency": info.get("currency") or meta.get("currency"),
        "close": close,
        "bar_date": pd.Timestamp(bars.index[-1]).date().isoformat(),
        "trailingPE": _safe_info(info, "trailingPE"),
        "forwardPE": _safe_info(info, "forwardPE"),
        "priceToBook": _safe_info(info, "priceToBook"),
        "returnOnEquity": _safe_info(info, "returnOnEquity"),
        "returnOnAssets": _safe_info(info, "returnOnAssets"),
        "debtToEquity": _safe_info(info, "debtToEquity"),
        "revenueGrowth": _safe_info(info, "revenueGrowth"),
        "earningsGrowth": _safe_info(info, "earningsGrowth"),
        "marketCap": _safe_info(info, "marketCap"),
        "averageVolume": _safe_info(info, "averageVolume"),
        "rsi14": _safe_info({"v": row.get("RSI14")}, "v"),
        "macd": _safe_info({"v": row.get("MACD")}, "v"),
        "macd_signal": _safe_info({"v": row.get("MACD_SIGNAL")}, "v"),
        "ema20": float(bars["Close"].ewm(span=20, adjust=False).mean().iloc[-1]),
        "ema50": float(bars["Close"].ewm(span=50, adjust=False).mean().iloc[-1]),
        "ema200": float(bars["Close"].ewm(span=200, adjust=False).mean().iloc[-1]),
        "relative_volume": _safe_info({"v": row.get("REL_VOLUME")}, "v"),
        "atr_pct": atr / close * 100 if atr and close else None,
        "breakout_20d": bool(close > float(row["HIGH20"])) if pd.notna(row.get("HIGH20")) else False,
        "source": "Yahoo Finance",
    }
    result.update(score_stock(result))
    return result


def run_advanced_screener(
    markets: list[str] | None = None,
    symbols_by_market: dict[str, list[str]] | None = None,
    min_score: float = 0,
    sectors: list[str] | None = None,
    min_market_cap: float = 0,
    max_market_cap: float | None = None,
    period: str = "1y",
    max_workers: int = 4,
) -> dict[str, Any]:
    selected_markets = [m.upper() for m in (markets or ["IDX", "US"]) if m.upper() in ADVANCED_UNIVERSE]
    universe = symbols_by_market or {m: ADVANCED_UNIVERSE[m] for m in selected_markets}
    jobs = {}
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 6))) as pool:
        for market in selected_markets:
            for symbol in dict.fromkeys(universe.get(market, [])):
                if not str(symbol).strip():
                    continue
                future = pool.submit(screen_symbol, str(symbol).strip(), market, period)
                jobs[future] = (market, symbol)
        for future in as_completed(jobs):
            market, symbol = jobs[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append({"market": market, "ticker": symbol, "error": f"{type(exc).__name__}: {exc}"})

    sector_set = {s.strip().lower() for s in sectors or [] if s.strip()}
    filtered = []
    for item in results:
        cap = item.get("marketCap")
        score = item.get("ai_score")
        if score is None or score < float(min_score):
            continue
        if sector_set and str(item.get("sector", "")).lower() not in sector_set:
            continue
        if cap is not None and cap < float(min_market_cap):
            continue
        if max_market_cap is not None and cap is not None and cap > float(max_market_cap):
            continue
        filtered.append(item)
    filtered.sort(key=lambda item: (item.get("ai_score") or -1, item.get("score_coverage_pct") or 0), reverse=True)
    return {
        "results": filtered,
        "raw_success": len(results),
        "failed": len(errors),
        "errors": errors,
        "universe_size": sum(len(universe.get(m, [])) for m in selected_markets),
        "coverage_note": "Universe adalah daftar saham likuid pilihan yang dapat diedit, bukan seluruh emiten IDX/US. Fundamental yang tidak tersedia dibiarkan kosong dan menurunkan coverage.",
    }
