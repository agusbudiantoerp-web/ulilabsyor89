"""Explainable quantitative stock scoring. No opaque model or fabricated fundamentals."""
from __future__ import annotations

import math
from typing import Any


def _number(row: dict, key: str) -> float | None:
    value = row.get(key)
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _band(value: float | None, bands: list[tuple[float, float]]) -> float | None:
    if value is None:
        return None
    for upper, score in bands:
        if value <= upper:
            return score
    return bands[-1][1]


def score_stock(row: dict[str, Any]) -> dict[str, Any]:
    """Return 0-100 score, factor scores and explicit data coverage."""
    components: dict[str, float | None] = {}

    roe = _number(row, "returnOnEquity")
    roa = _number(row, "returnOnAssets")
    revenue_growth = _number(row, "revenueGrowth")
    earnings_growth = _number(row, "earningsGrowth")
    debt_equity = _number(row, "debtToEquity")
    pe = _number(row, "trailingPE")
    pb = _number(row, "priceToBook")
    rsi = _number(row, "rsi14")
    rel_volume = _number(row, "relative_volume")
    close = _number(row, "close")
    ema20 = _number(row, "ema20")
    ema50 = _number(row, "ema50")
    ema200 = _number(row, "ema200")
    macd = _number(row, "macd")
    macd_signal = _number(row, "macd_signal")
    market_cap = _number(row, "marketCap")
    avg_volume = _number(row, "averageVolume")
    atr_pct = _number(row, "atr_pct")

    fundamental = []
    if roe is not None:
        fundamental.append(max(0.0, min(100.0, 50 + roe * 125)))
    if roa is not None:
        fundamental.append(max(0.0, min(100.0, 50 + roa * 250)))
    if revenue_growth is not None:
        fundamental.append(max(0.0, min(100.0, 50 + revenue_growth * 100)))
    if earnings_growth is not None:
        fundamental.append(max(0.0, min(100.0, 50 + earnings_growth * 100)))
    if debt_equity is not None:
        fundamental.append(_band(debt_equity, [(30,100),(60,90),(100,75),(150,55),(250,30),(500,10),(float("inf"),0)]))
    components["fundamental"] = sum(fundamental) / len(fundamental) if fundamental else None

    valuation = []
    if pe is not None:
        valuation.append(_band(pe, [(0,0),(8,95),(12,85),(18,70),(25,55),(35,35),(50,15),(float("inf"),0)]))
    if pb is not None:
        valuation.append(_band(pb, [(0,0),(1,95),(2,80),(3,65),(5,40),(8,15),(float("inf"),0)]))
    components["valuation"] = sum(valuation) / len(valuation) if valuation else None

    momentum = []
    if close is not None and ema20 is not None:
        momentum.append(100 if close > ema20 else 20)
    if close is not None and ema50 is not None:
        momentum.append(100 if close > ema50 else 20)
    if close is not None and ema200 is not None:
        momentum.append(100 if close > ema200 else 20)
    if macd is not None and macd_signal is not None:
        momentum.append(100 if macd > macd_signal else 20)
    if rsi is not None:
        momentum.append(100 if 52 <= rsi <= 68 else 70 if 45 <= rsi < 52 or 68 < rsi <= 72 else 25 if rsi < 45 else 10)
    if rel_volume is not None:
        momentum.append(100 if rel_volume >= 1.5 else 80 if rel_volume >= 1.1 else 50 if rel_volume >= 0.8 else 20)
    components["momentum"] = sum(momentum) / len(momentum) if momentum else None

    liquidity = []
    if market_cap is not None and market_cap > 0:
        liquidity.append(_band(market_cap, [(1e9,10),(1e10,25),(1e11,45),(1e12,65),(1e13,85),(float("inf"),100)]))
    if avg_volume is not None:
        liquidity.append(_band(avg_volume, [(1e4,10),(1e5,25),(5e5,45),(1e6,65),(5e6,85),(float("inf"),100)]))
    components["liquidity"] = sum(liquidity) / len(liquidity) if liquidity else None

    risk = []
    if atr_pct is not None:
        risk.append(_band(atr_pct, [(1,100),(2,90),(3,75),(5,55),(8,30),(12,10),(float("inf"),0)]))
    components["risk"] = sum(risk) / len(risk) if risk else None

    weights = {"fundamental": 0.30, "valuation": 0.20, "momentum": 0.25, "liquidity": 0.10, "risk": 0.15}
    available = [(name, value) for name, value in components.items() if value is not None]
    coverage = sum(weights[name] for name, _ in available)
    score = (
        sum(float(value) * weights[name] for name, value in available) / coverage
        if coverage >= 0.35 else None
    )
    return {
        "ai_score": round(score, 1) if score is not None else None,
        "score_coverage_pct": round(coverage * 100, 1),
        "factor_scores": {k: round(v, 1) if v is not None else None for k, v in components.items()},
        "score_label": (
            "Strong" if score is not None and score >= 80 else
            "Positive" if score is not None and score >= 65 else
            "Neutral" if score is not None and score >= 50 else
            "Weak" if score is not None else "Insufficient data"
        ),
        "score_method": "Explainable weighted rules; not a trained predictive ML model",
    }
