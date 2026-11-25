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
        if isinstance(value, bool) or type(value).__name__ in {"bool_", "bool"} or not math.isfinite(numeric_value) or numeric_value < 0:
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

    # Build all plausible pairs first, then allocate the closest pairs globally.
    # Matching each internal row greedily in input order can consume an exact
    # broker match for an earlier event that only has a nearby-date alternative.
    candidate_pairs = []
    for internal_index, item in internal.iterrows():
        candidates = broker.loc[
            broker["event_type"].eq(item["event_type"])
            & broker["ticker"].eq(item["ticker"])
        ]
        for broker_index, candidate in candidates.iterrows():
            date_gap = abs((pd.Timestamp(item["date"]) - pd.Timestamp(candidate["date"])).days)
            amount_gap = relative_gap(item["amount"], candidate["amount"])
            candidate_pairs.append(
                (date_gap, amount_gap, int(internal_index), int(broker_index))
            )

    candidates_by_internal = {}
    for date_gap, amount_gap, internal_index, broker_index in sorted(candidate_pairs):
        candidates_by_internal.setdefault(internal_index, []).append(
            (date_gap, amount_gap, broker_index)
        )

    # Use augmenting paths so an early flexible internal row cannot consume
    # the only broker candidate available to a later constrained row.
    broker_to_internal = {}

    def assign(internal_index, visited_broker):
        for _, _, broker_index in candidates_by_internal.get(internal_index, []):
            if broker_index in visited_broker:
                continue
            visited_broker.add(broker_index)
            previous_internal = broker_to_internal.get(broker_index)
            if previous_internal is None or assign(previous_internal, visited_broker):
                broker_to_internal[broker_index] = internal_index
                return True
        return False

    internal_order = sorted(
        candidates_by_internal,
        key=lambda index: (len(candidates_by_internal[index]), index),
    )
    for internal_index in internal_order:
        assign(internal_index, set())

    matched_pairs = {}
    for broker_index, internal_index in broker_to_internal.items():
        candidate = next(
            item for item in candidates_by_internal[internal_index]
            if item[2] == broker_index
        )
        matched_pairs[internal_index] = (broker_index, candidate[0], candidate[1])
        unmatched.discard(broker_index)

    for internal_index, item in internal.iterrows():
        if internal_index not in matched_pairs:
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
        broker_index, date_gap, amount_gap = matched_pairs[internal_index]
        matched = broker.loc[broker_index]
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
            "One-to-one global greedy allocation of event type/ticker pairs, prioritizing nearest date then amount difference. "
            "This is an exception report, not a broker-confirmed reconciliation or tax statement."
        ),
    }
