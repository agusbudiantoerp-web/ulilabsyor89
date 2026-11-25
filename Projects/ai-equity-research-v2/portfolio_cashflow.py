"""Portfolio cash-flow ledger and return metrics (TWR / XIRR).

External contributions/withdrawals are separated from investment P&L. Positive TWR flows are deposits; negative flows are withdrawals.
This module does not infer broker fills or corporate actions.
"""
from __future__ import annotations

from datetime import date, datetime
import math
from typing import Iterable

import pandas as pd

EVENT_TYPES = {"DEPOSIT", "WITHDRAWAL", "DIVIDEND", "BUY", "SELL", "FEE", "TAX", "SPLIT"}
EXTERNAL_FLOW_TYPES = {"DEPOSIT", "WITHDRAWAL"}
CASH_EVENT_TYPES = {"DEPOSIT", "WITHDRAWAL", "DIVIDEND", "BUY", "SELL", "FEE", "TAX"}


def normalize_events(events: pd.DataFrame | Iterable[dict]) -> pd.DataFrame:
    frame = events.copy() if isinstance(events, pd.DataFrame) else pd.DataFrame(list(events))
    required = {"date", "event_type", "amount"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("Kolom event wajib: " + ", ".join(sorted(missing)))
    if frame.empty:
        return pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price", "notes"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any():
        raise ValueError("Tanggal event tidak valid.")
    frame["event_type"] = frame["event_type"].astype(str).str.upper().str.strip()
    unknown = sorted(set(frame["event_type"]) - EVENT_TYPES)
    if unknown:
        raise ValueError("Jenis event tidak dikenal: " + ", ".join(unknown))
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    if frame["amount"].isna().any() or not all(math.isfinite(float(x)) for x in frame["amount"]):
        raise ValueError("Nominal event harus berupa angka finite.")
    if (frame["amount"] < 0).any():
        raise ValueError("Nominal event dicatat sebagai nilai absolut positif.")
    if "ticker" not in frame:
        frame["ticker"] = ""
    if "quantity" not in frame:
        frame["quantity"] = None
    if "price" not in frame:
        frame["price"] = None
    if "notes" not in frame:
        frame["notes"] = ""
    for column in ("quantity", "price"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if (frame[column].dropna() < 0).any():
            raise ValueError(f"{column} tidak boleh negatif.")
    frame["ticker"] = frame["ticker"].fillna("").astype(str).str.upper().str.strip()
    frame["notes"] = frame["notes"].fillna("").astype(str)
    if frame.loc[frame["event_type"].isin({"BUY", "SELL", "DIVIDEND", "SPLIT"}), "ticker"].eq("").any():
        raise ValueError("Ticker wajib untuk BUY, SELL, DIVIDEND dan SPLIT.")
    if frame.loc[frame["event_type"].isin({"BUY", "SELL", "SPLIT"}), "quantity"].isna().any():
        raise ValueError("Quantity wajib untuk BUY, SELL dan SPLIT.")
    if frame.loc[frame["event_type"].isin({"BUY", "SELL"}), "price"].isna().any():
        raise ValueError("Price wajib untuk BUY dan SELL.")
    if frame.loc[frame["event_type"].eq("SPLIT"), "amount"].ne(0).any():
        raise ValueError("Amount untuk event SPLIT harus 0; gunakan quantity sebagai rasio split.")
    return frame.sort_values(["date"], kind="stable").reset_index(drop=True)


def cash_flow_ledger(events: pd.DataFrame | Iterable[dict]) -> dict:
    """Return normalized events and categorized cash totals; no guessed balance."""
    frame = normalize_events(events)
    totals = {
        event_type.lower(): float(frame.loc[frame["event_type"].eq(event_type), "amount"].sum())
        for event_type in sorted(CASH_EVENT_TYPES)
    }
    external_net = totals["deposit"] - totals["withdrawal"]
    investment_income = totals["dividend"]
    transaction_costs = totals["fee"] + totals["tax"]
    return {
        "events": frame,
        "event_count": int(len(frame)),
        "totals": totals,
        "net_external_contributions": external_net,
        "dividend_income": investment_income,
        "transaction_costs": transaction_costs,
        "currency_note": "Semua nominal harus menggunakan satu mata uang dasar yang sama.",
    }


def calculate_twr(valuations: pd.DataFrame) -> dict:
    """Calculate linked sub-period TWR; external_flow is signed into the portfolio.

    Each row is an end-of-period valuation. external_flow is the net external
    contribution made immediately before that valuation (positive deposit,
    negative withdrawal). First row's flow is ignored because no prior value
    exists; caller should supply an opening valuation before the first period.
    """
    required = {"date", "portfolio_value", "external_flow"}
    if not required.issubset(valuations.columns):
        raise ValueError("Valuations wajib memiliki date, portfolio_value, external_flow.")
    frame = valuations.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["portfolio_value"] = pd.to_numeric(frame["portfolio_value"], errors="coerce")
    frame["external_flow"] = pd.to_numeric(frame["external_flow"], errors="coerce")
    if frame[["date", "portfolio_value", "external_flow"]].isna().any().any():
        raise ValueError("Tanggal, nilai portfolio dan external flow harus valid.")
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise ValueError("Tanggal valuasi TWR harus unik; agregasikan transaksi dalam satu titik valuasi.")
    if len(frame) < 2:
        raise ValueError("Minimal dua titik valuasi diperlukan.")
    values = frame["portfolio_value"].tolist()
    flows = frame["external_flow"].tolist()
    if any(not math.isfinite(float(x)) for x in values + flows):
        raise ValueError("Nilai valuasi dan flow harus finite.")
    if any(x <= 0 for x in values):
        raise ValueError("Nilai portfolio harus positif pada setiap titik valuasi.")
    returns = []
    for index in range(1, len(frame)):
        denominator = values[index - 1]
        capital_at_risk = denominator + flows[index]
        if capital_at_risk <= 0:
            raise ValueError("Modal awal sub-periode setelah external flow harus positif.")
        period_return = values[index] / capital_at_risk - 1.0
        if period_return <= -1:
            raise ValueError("Return sub-periode tidak boleh -100% atau lebih rendah.")
        returns.append(period_return)
    linked = math.prod(1.0 + value for value in returns) - 1.0
    return {
        "twr_pct": linked * 100.0,
        "period_returns_pct": [value * 100.0 for value in returns],
        "period_count": len(returns),
        "method": "Geometrically linked sub-period returns; external flows are added to opening capital at the start of each sub-period.",
    }


def calculate_xirr(cash_flows: pd.DataFrame | Iterable[dict], *, ending_value: float = 0.0,
                   ending_date: date | datetime | str | None = None) -> dict:
    """Solve annualized money-weighted return using dated investor cash flows."""
    frame = cash_flows.copy() if isinstance(cash_flows, pd.DataFrame) else pd.DataFrame(list(cash_flows))
    if not {"date", "amount"}.issubset(frame.columns):
        raise ValueError("Cash flows wajib memiliki date dan amount.")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    if frame.empty or frame[["date", "amount"]].isna().any().any():
        raise ValueError("Cash flow kosong atau tidak valid.")
    if not all(math.isfinite(float(x)) for x in frame["amount"]):
        raise ValueError("Cash flow harus finite.")
    end_value = float(ending_value)
    if not math.isfinite(end_value) or end_value < 0:
        raise ValueError("Ending value harus finite dan tidak negatif.")
    if ending_date is not None:
        end = pd.Timestamp(ending_date)
    elif end_value > 0:
        end = frame["date"].max()
    else:
        end = None
    if end_value > 0:
        if end is None or end < frame["date"].max():
            raise ValueError("Ending date tidak boleh lebih awal dari cash flow terakhir.")
        frame = pd.concat([frame, pd.DataFrame([{"date": end, "amount": end_value}])], ignore_index=True)
    frame = frame.groupby("date", as_index=False)["amount"].sum().sort_values("date")
    if frame["amount"].min() >= 0 or frame["amount"].max() <= 0:
        raise ValueError("XIRR memerlukan setidaknya satu arus negatif dan satu arus positif.")
    signs = [1 if value > 0 else -1 for value in frame["amount"] if value != 0]
    sign_changes = sum(signs[i] != signs[i - 1] for i in range(1, len(signs)))
    if sign_changes > 1:
        raise ValueError("Arus kas berganti tanda beberapa kali; XIRR dapat memiliki lebih dari satu akar.")
    origin = frame["date"].min()
    days = (frame["date"] - origin).dt.days.to_numpy(dtype=float)
    amounts = frame["amount"].to_numpy(dtype=float)

    def npv(rate: float) -> float:
        if rate <= -1:
            return math.inf
        return sum(float(amount) / ((1.0 + rate) ** (day / 365.0))
                   for amount, day in zip(amounts, days))

    low, high = -0.9999, 1.0
    f_low, f_high = npv(low), npv(high)
    expansions = 0
    while f_low * f_high > 0 and expansions < 60:
        high = high * 2.0 + 1.0
        f_high = npv(high)
        expansions += 1
    if not math.isfinite(f_low) or not math.isfinite(f_high) or f_low * f_high > 0:
        raise ValueError("XIRR tidak dapat dipecahkan untuk arus kas ini.")
    for _ in range(250):
        mid = (low + high) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9 or abs(high - low) < 1e-12:
            return {
                "xirr_pct": mid * 100.0,
                "cash_flow_count": int(len(frame)),
                "method": "Annualized dated cash-flow IRR, ACT/365, bisection solver.",
            }
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    raise ValueError("XIRR solver tidak konvergen.")
