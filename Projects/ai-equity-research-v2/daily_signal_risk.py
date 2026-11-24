"""Trade planning and position sizing. Outputs are indicative, not broker instructions."""
from __future__ import annotations

import math


def build_trade_plan(
    close: float, atr: float, equity: float, risk_pct: float = 1.0,
    atr_multiple: float = 1.5, reward_risk: float = 2.0,
    entry_buffer_pct: float = 1.0, max_position_pct: float = 20.0,
) -> dict:
    names = (
        "close", "atr", "equity", "risk_pct", "atr_multiple",
        "reward_risk", "entry_buffer_pct", "max_position_pct",
    )
    try:
        values = {name: float(value) for name, value in zip(
            names, (close, atr, equity, risk_pct, atr_multiple, reward_risk,
                    entry_buffer_pct, max_position_pct)
        )}
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Semua input sizing harus numerik dan finite.") from exc
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("Semua input sizing harus numerik dan finite.")
    close, atr, equity = values["close"], values["atr"], values["equity"]
    risk_pct, atr_multiple = values["risk_pct"], values["atr_multiple"]
    reward_risk, entry_buffer_pct = values["reward_risk"], values["entry_buffer_pct"]
    max_position_pct = values["max_position_pct"]
    if min(close, atr, equity, risk_pct, atr_multiple, reward_risk, max_position_pct) <= 0:
        raise ValueError("Harga, ATR, modal, risk, multiplier, reward-risk dan batas posisi harus positif.")
    if not 0 <= entry_buffer_pct < 100:
        raise ValueError("Entry buffer harus berada pada rentang 0% sampai kurang dari 100%.")
    if risk_pct > 5 or max_position_pct > 100:
        raise ValueError("Batas risiko/posisi tidak wajar.")
    stop = max(0.01, close - atr * atr_multiple)
    per_share = close - stop
    if not math.isfinite(stop) or not math.isfinite(per_share):
        raise ValueError("Hasil stop-loss melampaui rentang numerik.")
    if per_share <= 0:
        raise ValueError("ATR stop tidak menghasilkan risiko per saham yang positif.")
    risk_budget = equity * risk_pct / 100
    cap_value = equity * (max_position_pct / 100)
    if not math.isfinite(risk_budget) or not math.isfinite(cap_value):
        raise ValueError("Modal atau risk budget melampaui rentang numerik.")
    shares_by_risk = int(risk_budget / per_share)
    shares_by_cap = int(cap_value / close)
    shares = max(0, min(shares_by_risk, shares_by_cap))
    entry_low = close * (1 - entry_buffer_pct / 100)
    entry_high = close * (1 + entry_buffer_pct / 100)
    target = close + reward_risk * per_share
    position_value = shares * close
    planned_loss = shares * per_share
    outputs = (entry_low, entry_high, target, position_value, planned_loss)
    if not all(math.isfinite(value) for value in outputs):
        raise ValueError("Hasil sizing melampaui rentang numerik.")
    return {
        "entry_low": entry_low, "entry_high": entry_high,
        "stop_loss": stop, "target": target,
        "risk_per_share": per_share, "risk_budget": risk_budget,
        "shares": shares, "position_value": position_value,
        "portfolio_weight_pct": position_value / equity * 100,
        "planned_loss": planned_loss,
        "reward_risk": (target - close) / per_share,
    }


def validate_entry(current_price: float, entry_low: float, entry_high: float) -> dict:
    try:
        current_price, entry_low, entry_high = map(float, (current_price, entry_low, entry_high))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Rentang harga harus numerik dan finite.") from exc
    if not all(math.isfinite(value) for value in (current_price, entry_low, entry_high)):
        raise ValueError("Rentang harga harus numerik dan finite.")
    if min(current_price, entry_low, entry_high) <= 0 or entry_low > entry_high:
        raise ValueError("Rentang harga tidak valid.")
    valid = entry_low <= current_price <= entry_high
    return {
        "valid": valid,
        "status": "ENTRY_WITHIN_ZONE" if valid else "GAP_OR_OUTSIDE_ZONE",
        "message": "Harga masih dalam zona indikatif." if valid else "Jangan mengejar harga; kandidat dibatalkan di luar zona entry.",
    }
