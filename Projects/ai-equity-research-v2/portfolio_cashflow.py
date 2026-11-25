"""Portfolio cash-flow ledger and return metrics (TWR / XIRR).

External contributions/withdrawals are separated from investment P&L. Positive TWR flows are deposits; negative flows are withdrawals.
This module does not infer broker fills or corporate actions.
"""
from __future__ import annotations

from datetime import date, datetime
import math
import numbers
from typing import Iterable

import pandas as pd

EVENT_TYPES = {"DEPOSIT", "WITHDRAWAL", "DIVIDEND", "BUY", "SELL", "FEE", "TAX", "SPLIT"}
EXTERNAL_FLOW_TYPES = {"DEPOSIT", "WITHDRAWAL"}
CASH_EVENT_TYPES = {"DEPOSIT", "WITHDRAWAL", "DIVIDEND", "BUY", "SELL", "FEE", "TAX"}


def _reject_boolean_values(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    for column in columns:
        if column in frame and frame[column].map(
            lambda value: isinstance(value, bool) or type(value).__name__ == "bool_"
        ).any():
            raise ValueError(f"{column} tidak boleh berupa boolean.")


def _parse_date_series(series: pd.Series, label: str) -> pd.Series:
    if series.map(lambda value: isinstance(value, numbers.Number)).any():
        raise ValueError(f"{label} tidak valid.")
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError(f"{label} tidak valid.")
    return parsed.dt.tz_localize(None)


def normalize_events(events: pd.DataFrame | Iterable[dict]) -> pd.DataFrame:
    frame = events.copy() if isinstance(events, pd.DataFrame) else pd.DataFrame(list(events))
    required = {"date", "event_type", "amount"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("Kolom event wajib: " + ", ".join(sorted(missing)))
    if frame.empty:
        return pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price", "notes"])
    def _is_boolean(value):
        return isinstance(value, bool) or type(value).__name__ == "bool_"

    # Do not let pandas interpret integer/boolean values as nanoseconds from
    # the Unix epoch when a human-readable event date is required.
    if frame["date"].map(lambda value: isinstance(value, numbers.Number) or _is_boolean(value)).any():
        raise ValueError("Tanggal event tidak valid.")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True).dt.tz_localize(None)
    if frame["date"].isna().any():
        raise ValueError("Tanggal event tidak valid.")
    frame["event_type"] = frame["event_type"].astype(str).str.upper().str.strip()
    unknown = sorted(set(frame["event_type"]) - EVENT_TYPES)
    if unknown:
        raise ValueError("Jenis event tidak dikenal: " + ", ".join(unknown))
    for column in ("amount", "quantity", "price"):
        if column in frame and frame[column].map(_is_boolean).any():
            raise ValueError(f"{column} harus berupa angka, bukan boolean.")
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
        present = frame[column].notna()
        if present.any() and not all(math.isfinite(float(value)) for value in frame.loc[present, column]):
            raise ValueError(f"{column} harus berupa angka finite.")
        if (frame[column].dropna() < 0).any():
            raise ValueError(f"{column} tidak boleh negatif.")
    if "settlement_date" in frame.columns:
        trade_rows = frame["event_type"].isin({"BUY", "SELL"})
        supplied = frame["settlement_date"].notna() & frame["settlement_date"].astype(str).str.strip().ne("")
        validate_rows = trade_rows & supplied
        settlement_values = frame.loc[validate_rows, "settlement_date"]
        if settlement_values.map(
            lambda value: isinstance(value, numbers.Number) or _is_boolean(value)
        ).any():
            raise ValueError("Settlement date transaksi tidak valid.")
        parsed = pd.to_datetime(settlement_values, errors="coerce", utc=True).dt.tz_localize(None)
        trade_dates = frame.loc[validate_rows, "date"]
        if parsed.isna().any():
            raise ValueError("Settlement date transaksi tidak valid.")
        try:
            earlier = parsed.reset_index(drop=True) < trade_dates.reset_index(drop=True)
        except TypeError as exc:
            raise ValueError("Timezone settlement date harus konsisten dengan trade date.") from exc
        if earlier.any():
            raise ValueError("Settlement date tidak boleh lebih awal dari trade date.")
        frame.loc[validate_rows, "settlement_date"] = parsed
    frame["ticker"] = frame["ticker"].fillna("").astype(str).str.upper().str.strip()
    frame["notes"] = frame["notes"].fillna("").astype(str)
    if frame.loc[frame["event_type"].isin({"BUY", "SELL", "DIVIDEND", "SPLIT"}), "ticker"].eq("").any():
        raise ValueError("Ticker wajib untuk BUY, SELL, DIVIDEND dan SPLIT.")
    if frame.loc[frame["event_type"].isin({"BUY", "SELL", "SPLIT"}), "quantity"].isna().any():
        raise ValueError("Quantity wajib untuk BUY, SELL dan SPLIT.")
    if frame.loc[frame["event_type"].isin({"BUY", "SELL"}), "price"].isna().any():
        raise ValueError("Price wajib untuk BUY dan SELL.")
    trade_rows = frame["event_type"].isin({"BUY", "SELL"})
    if frame.loc[trade_rows, "amount"].le(0).any():
        raise ValueError("Nominal transaksi BUY/SELL harus lebih besar dari 0.")
    if frame.loc[trade_rows, "quantity"].isna().any() or frame.loc[trade_rows, "quantity"].le(0).any():
        raise ValueError("Quantity BUY/SELL harus lebih besar dari 0.")
    if frame.loc[trade_rows, "price"].isna().any() or frame.loc[trade_rows, "price"].le(0).any():
        raise ValueError("Price BUY/SELL harus lebih besar dari 0.")
    split_rows = frame["event_type"].eq("SPLIT")
    if frame.loc[split_rows, "quantity"].isna().any() or frame.loc[split_rows, "quantity"].le(0).any():
        raise ValueError("Rasio split harus lebih besar dari 0.")
    if frame.loc[split_rows, "amount"].ne(0).any():
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
    _reject_boolean_values(frame, ("date", "portfolio_value", "external_flow"))
    frame["date"] = _parse_date_series(frame["date"], "Tanggal valuasi")
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
    _reject_boolean_values(frame, ("date", "amount"))
    frame["date"] = _parse_date_series(frame["date"], "Tanggal cash flow")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    if frame.empty or frame[["date", "amount"]].isna().any().any():
        raise ValueError("Cash flow kosong atau tidak valid.")
    if not all(math.isfinite(float(x)) for x in frame["amount"]):
        raise ValueError("Cash flow harus finite.")
    if isinstance(ending_value, bool) or type(ending_value).__name__ == "bool_":
        raise ValueError("Ending value harus berupa angka, bukan boolean.")
    end_value = float(ending_value)
    if not math.isfinite(end_value) or end_value < 0:
        raise ValueError("Ending value harus finite dan tidak negatif.")
    if ending_date is not None:
        if isinstance(ending_date, numbers.Number) or isinstance(ending_date, bool):
            raise ValueError("Ending date tidak valid.")
        end = pd.to_datetime(ending_date, errors="coerce", utc=True)
        if pd.isna(end):
            raise ValueError("Ending date tidak valid.")
        end = end.tz_localize(None)
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


def reconcile_portfolio_ledger(
    events: pd.DataFrame | Iterable[dict],
    *,
    initial_cash: float = 0.0,
    initial_positions: dict[str, float] | None = None,
    amount_tolerance_pct: float = 1.0,
) -> dict:
    """Reconstruct cash and share quantities from dated events on trade date.

    This simple ledger does not defer cash to settlement_date; use the
    transaction-aware portfolio replay for unsettled cash/payables/receivables.
    BUY amount is total cash paid; SELL amount is gross proceeds. Fees/taxes
    are separate cash outflows. SPLIT quantity is the new-shares-per-old-share
    ratio. Same-day ordering follows the stable order supplied by the caller.
    """
    if isinstance(initial_cash, bool) or type(initial_cash).__name__ == "bool_":
        raise ValueError("Initial cash harus berupa angka, bukan boolean.")
    if isinstance(amount_tolerance_pct, bool) or type(amount_tolerance_pct).__name__ == "bool_":
        raise ValueError("Amount tolerance harus berupa angka, bukan boolean.")
    cash = float(initial_cash)
    if not math.isfinite(cash) or cash < 0:
        raise ValueError("Initial cash harus finite dan tidak negatif.")
    tolerance = float(amount_tolerance_pct)
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Amount tolerance harus finite dan tidak negatif.")
    positions = {}
    for ticker, shares in (initial_positions or {}).items():
        if isinstance(shares, bool) or type(shares).__name__ == "bool_":
            raise ValueError("Initial positions harus berupa angka, bukan boolean.")
        positions[str(ticker).upper().strip()] = float(shares)
    if any(not math.isfinite(value) or value < 0 for value in positions.values()):
        raise ValueError("Initial positions harus finite dan tidak negatif.")
    frame = normalize_events(events)
    warnings = []
    for row in frame.to_dict("records"):
        kind = row["event_type"]
        ticker = str(row["ticker"] or "").upper()
        amount = float(row["amount"])
        quantity = float(row["quantity"]) if pd.notna(row["quantity"]) else 0.0
        price = float(row["price"]) if pd.notna(row["price"]) else 0.0
        if kind == "DEPOSIT":
            cash += amount
        elif kind == "WITHDRAWAL":
            cash -= amount
            if cash < -1e-8:
                raise ValueError(f"Cash tidak cukup untuk WITHDRAWAL pada {pd.Timestamp(row['date']).date()}.")
        elif kind == "DIVIDEND":
            cash += amount
        elif kind == "BUY":
            cash -= amount
            if cash < -1e-8:
                raise ValueError(f"Cash tidak cukup untuk BUY {ticker} pada {pd.Timestamp(row['date']).date()}.")
            positions[ticker] = positions.get(ticker, 0.0) + quantity
            expected = quantity * price
            if expected > 0 and abs(amount / expected - 1.0) * 100.0 > tolerance:
                warnings.append(
                    f"{ticker}: BUY nominal differs from quantity × price by more than {tolerance:.2f}%."
                )
        elif kind == "SELL":
            if quantity > positions.get(ticker, 0.0) + 1e-9:
                raise ValueError(f"SELL {ticker} melebihi jumlah saham yang tersedia.")
            cash += amount
            positions[ticker] = max(0.0, positions.get(ticker, 0.0) - quantity)
            expected = quantity * price
            if expected > 0 and abs(amount / expected - 1.0) * 100.0 > tolerance:
                warnings.append(
                    f"{ticker}: SELL proceeds differ from quantity × price by more than {tolerance:.2f}%."
                )
        elif kind in {"FEE", "TAX"}:
            cash -= amount
            if cash < -1e-8:
                raise ValueError(f"Cash tidak cukup untuk {kind} pada {pd.Timestamp(row['date']).date()}.")
        elif kind == "SPLIT":
            if ticker not in positions:
                warnings.append(f"{ticker}: split tercatat tanpa posisi awal; periksa histori transaksi.")
            positions[ticker] = positions.get(ticker, 0.0) * quantity
    if cash < -1e-8:
        raise ValueError("Cash balance negatif; periksa urutan dan nominal transaksi.")
    if any(value < -1e-8 for value in positions.values()):
        raise ValueError("Saldo saham negatif.")
    return {
        "cash_balance": max(0.0, cash),
        "positions": {ticker: shares for ticker, shares in positions.items() if shares > 1e-9},
        "event_count": int(len(frame)),
        "warnings": warnings,
        "currency_note": "Rekonsiliasi hanya valid jika seluruh nominal event menggunakan mata uang dasar yang sama.",
        "limitations": (
            "Rekonsiliasi ini menghitung saldo kas dan jumlah saham berdasarkan trade date; "
            "settlement cash tertunda dihitung oleh transaction-aware replay. FIFO/average-cost "
            "tax lots dan realized P&L tersedia pada modul tax-lot terpisah. Pajak legal, bunga, "
            "FX conversion dan validasi broker tidak dihitung oleh fungsi ini."
        ),
    }
