"""Portfolio-level exposure checks and indicative position sizing."""
from __future__ import annotations

import math

from daily_signal_risk import build_trade_plan


def allocate_candidates(
    candidates: list[dict], portfolio_value: float,
    risk_pct: float = 1.0, max_total_exposure_pct: float = 60.0,
    max_single_position_pct: float = 15.0, max_positions: int = 8,
) -> dict:
    try:
        capital, risk, total_cap, single_cap = map(
            float, (portfolio_value, risk_pct, max_total_exposure_pct, max_single_position_pct)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Parameter portofolio harus numerik dan finite.") from exc
    if not all(math.isfinite(value) for value in (capital, risk, total_cap, single_cap)):
        raise ValueError("Parameter portofolio harus numerik dan finite.")
    if capital <= 0 or not 0 < risk <= 5 or not 0 < total_cap <= 100:
        raise ValueError("Parameter portofolio tidak valid.")
    if not 0 < single_cap <= 100:
        raise ValueError("Batas posisi individual harus di atas 0% dan maksimal 100%.")
    if isinstance(max_positions, bool) or not isinstance(max_positions, int) or max_positions < 1:
        raise ValueError("Batas jumlah posisi harus integer positif.")
    if not isinstance(candidates, list):
        raise ValueError("Candidates harus berupa list.")

    selected, skipped = [], []
    used = 0.0
    seen = set()
    for item in sorted(candidates, key=lambda x: x.get("score", 0), reverse=True):
        if not isinstance(item, dict):
            skipped.append({"ticker": None, "reason": "Format kandidat tidak valid."})
            continue
        if item.get("signal") != "BUY_CANDIDATE":
            continue
        market = str(item.get("market", "IDX")).upper().strip()
        ticker = str(item.get("ticker", "")).upper().strip()
        if market not in {"IDX", "US"} or not ticker:
            skipped.append({"ticker": ticker or None, "reason": "Market atau ticker tidak valid."})
            continue
        key = (market, ticker)
        if key in seen:
            skipped.append({"ticker": ticker, "reason": "Kandidat duplikat dilewati."})
            continue
        seen.add(key)
        if len(selected) >= max_positions:
            skipped.append({"ticker": ticker, "reason": "Batas jumlah posisi tercapai."})
            continue
        try:
            close = float(item["close"])
            atr = float(item["atr14"])
            if not math.isfinite(close) or not math.isfinite(atr) or close <= 0 or atr <= 0:
                raise ValueError("Harga dan ATR harus finite dan positif.")
            plan = build_trade_plan(
                close, atr, capital, risk_pct=risk,
                max_position_pct=single_cap,
            )
            remaining = capital * total_cap / 100 - used
            allowed = int(max(0, remaining) / close)
            lot_size = 100 if market == "IDX" else 1
            raw_shares = min(plan["shares"], allowed)
            plan["shares"] = (raw_shares // lot_size) * lot_size
            plan["lots"] = plan["shares"] // lot_size if market == "IDX" else None
            plan["lot_size"] = lot_size
            plan["position_value"] = plan["shares"] * close
            plan["planned_loss"] = plan["shares"] * plan["risk_per_share"]
            plan["portfolio_weight_pct"] = plan["position_value"] / capital * 100
            if not all(math.isfinite(float(plan[key])) for key in (
                "position_value", "planned_loss", "portfolio_weight_pct"
            )):
                raise ValueError("Hasil alokasi melampaui rentang numerik.")
            if plan["shares"] <= 0:
                skipped.append({"ticker": ticker, "reason": "Tidak ada kapasitas exposure tersisa atau tidak cukup untuk satu lot."})
                continue
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            skipped.append({"ticker": ticker, "reason": f"Input sizing tidak valid: {exc}"})
            continue
        selected.append({
            "market": market, "ticker": ticker,
            "score": item.get("score"), "plan": plan,
        })
        used += plan["position_value"]
    return {
        "portfolio_value": capital, "allocated_value": used,
        "exposure_pct": used / capital * 100,
        "positions": selected, "skipped": skipped,
        "disclaimer": "Sizing indikatif. Perhitungkan lot size IDX, biaya, likuiditas, korelasi dan posisi aktual sebelum keputusan.",
    }
