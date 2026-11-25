"""Deterministic matching of an internal portfolio ledger to a broker CSV export."""
from __future__ import annotations

import math
import numbers

import pandas as pd

from portfolio_cashflow import normalize_events


def _normalized_or_empty(events) -> pd.DataFrame:
    raw = events.copy() if isinstance(events, pd.DataFrame) else list(events or [])
    if isinstance(raw, pd.DataFrame) and raw.empty:
        raw = pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price"])
    elif isinstance(raw, list) and not raw:
        raw = pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price"])
    return normalize_events(raw)


def reconcile_broker_statement(
    internal_events,
    broker_events,
    *,
    amount_tolerance_pct: float = 1.0,
    price_tolerance_pct: float = 1.0,
    quantity_tolerance: float = 1e-8,
    date_tolerance_days: int = 1,
) -> dict:
    """Match events one-to-one and report missing, unexpected and mismatched rows."""
    for name, value in {
        "amount_tolerance_pct": amount_tolerance_pct,
        "price_tolerance_pct": price_tolerance_pct,
        "quantity_tolerance": quantity_tolerance,
    }.items():
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} harus berupa angka finite dan tidak negatif.") from exc
        if isinstance(value, bool) or type(value).__name__ == "bool_" or not math.isfinite(numeric_value) or numeric_value < 0:
            raise ValueError(f"{name} harus finite dan tidak negatif.")
    if (
        isinstance(date_tolerance_days, bool)
        or not isinstance(date_tolerance_days, numbers.Integral)
        or not 0 <= date_tolerance_days <= 30
    ):
        raise ValueError("date_tolerance_days harus integer 0–30.")
    internal = _normalized_or_empty(internal_events)
    broker = _normalized_or_empty(broker_events)
    unmatched = set(broker.index.tolist())
    rows = []

    def relative_gap(left, right):
        if pd.isna(left) and pd.isna(right):
            return 0.0
        if pd.isna(left) or pd.isna(right):
            return float("inf")
        denominator = max(abs(float(left)), abs(float(right)), 1e-12)
        return abs(float(left) - float(right)) / denominator * 100.0

    for internal_index, item in internal.iterrows():
        candidates = broker.loc[
            broker.index.isin(unmatched)
            & broker["event_type"].eq(item["event_type"])
            & broker["ticker"].eq(item["ticker"])
        ]
        if candidates.empty:
            rows.append({
                "status": "MISSING_IN_BROKER", "internal_date": item["date"],
                "broker_date": None, "event_type": item["event_type"],
                "ticker": item["ticker"], "internal_amount": item["amount"],
                "broker_amount": None, "amount_diff_pct": None,
                "internal_quantity": item["quantity"], "broker_quantity": None,
                "internal_price": item["price"], "broker_price": None,
                "date_diff_days": None,
            })
            continue
        ranked = []
        for broker_index, candidate in candidates.iterrows():
            date_gap = abs((pd.Timestamp(item["date"]) - pd.Timestamp(candidate["date"])).days)
            amount_gap = relative_gap(item["amount"], candidate["amount"])
            ranked.append((date_gap, amount_gap, broker_index, candidate))
        date_gap, amount_gap, broker_index, matched = min(ranked, key=lambda value: (value[0], value[1], value[2]))
        unmatched.remove(broker_index)
        quantity_gap = (
            abs(float(item["quantity"]) - float(matched["quantity"]))
            if pd.notna(item["quantity"]) and pd.notna(matched["quantity"])
            else (0.0 if pd.isna(item["quantity"]) and pd.isna(matched["quantity"]) else float("inf"))
        )
        price_gap = relative_gap(item["price"], matched["price"])
        if date_gap > date_tolerance_days:
            status = "DATE_MISMATCH"
        elif amount_gap > amount_tolerance_pct:
            status = "AMOUNT_MISMATCH"
        elif quantity_gap > quantity_tolerance:
            status = "QUANTITY_MISMATCH"
        elif price_gap > price_tolerance_pct:
            status = "PRICE_MISMATCH"
        else:
            status = "MATCH"
        rows.append({
            "status": status, "internal_date": item["date"],
            "broker_date": matched["date"], "event_type": item["event_type"],
            "ticker": item["ticker"], "internal_amount": float(item["amount"]),
            "broker_amount": float(matched["amount"]),
            "amount_diff_pct": amount_gap,
            "internal_quantity": item["quantity"], "broker_quantity": matched["quantity"],
            "quantity_diff": quantity_gap,
            "internal_price": item["price"], "broker_price": matched["price"],
            "price_diff_pct": price_gap, "date_diff_days": date_gap,
        })

    for broker_index in sorted(unmatched):
        item = broker.loc[broker_index]
        rows.append({
            "status": "UNEXPECTED_IN_BROKER", "internal_date": None,
            "broker_date": item["date"], "event_type": item["event_type"],
            "ticker": item["ticker"], "internal_amount": None,
            "broker_amount": float(item["amount"]), "amount_diff_pct": None,
            "internal_quantity": None, "broker_quantity": item["quantity"],
            "internal_price": None, "broker_price": item["price"],
            "date_diff_days": None,
        })
    details = pd.DataFrame(rows)
    counts = details["status"].value_counts().to_dict() if not details.empty else {}
    return {
        "internal_event_count": int(len(internal)),
        "broker_event_count": int(len(broker)),
        "matched_count": int(counts.get("MATCH", 0)),
        "mismatch_count": int(sum(value for key, value in counts.items() if key not in {"MATCH", "MISSING_IN_BROKER", "UNEXPECTED_IN_BROKER"})),
        "missing_in_broker_count": int(counts.get("MISSING_IN_BROKER", 0)),
        "unexpected_in_broker_count": int(counts.get("UNEXPECTED_IN_BROKER", 0)),
        "status_counts": counts,
        "details": details,
        "method": (
            "One-to-one greedy matching by event type/ticker, nearest date, then amount difference. "
            "This is an exception report, not a broker-confirmed reconciliation or tax statement."
        ),
    }
