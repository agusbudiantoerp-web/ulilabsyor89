"""Conservative dividend entitlement estimates from confirmed corporate events.

The result is an estimate from the user's trade-date ledger, not a broker
entitlement statement. It never posts a dividend cash-flow event.
"""
from __future__ import annotations

import math
import pandas as pd

from corporate_action_calendar import normalize_corporate_events
from portfolio_cashflow import normalize_events


def _positions_at_record_date(portfolio_events, ticker, record_date, initial_positions):
    if isinstance(portfolio_events, pd.DataFrame):
        raw = portfolio_events.copy()
    else:
        raw = list(portfolio_events or [])
    if isinstance(raw, list) and not raw:
        raw = pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price"])
    ledger = normalize_events(raw)
    positions = {}
    for key, value in (initial_positions or {}).items():
        symbol = str(key).strip().upper()
        if not symbol:
            raise ValueError("Ticker initial_positions tidak boleh kosong.")
        if isinstance(value, bool) or type(value).__name__ in {"bool_", "bool"}:
            raise ValueError("Initial positions harus berupa angka finite dan non-negatif.")
        try:
            shares = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Initial positions harus berupa angka finite dan non-negatif.") from None
        if not math.isfinite(shares) or shares < 0:
            raise ValueError("Initial positions harus berupa angka finite dan non-negatif.")
        positions[symbol] = shares
    ledger = ledger.loc[
        ledger["ticker"].eq(ticker) & ledger["date"].le(pd.Timestamp(record_date))
    ].copy()
    if ticker not in positions and ledger.empty:
        return None
    ledger["_priority"] = ledger["event_type"].map({"SPLIT": 0}).fillna(1)
    ledger = ledger.sort_values(["date", "_priority"], kind="stable")
    for row in ledger.to_dict("records"):
        kind = row["event_type"]
        quantity = float(row["quantity"]) if pd.notna(row["quantity"]) else 0.0
        current = positions.get(ticker, 0.0)
        if kind == "BUY":
            positions[ticker] = current + quantity
        elif kind == "SELL":
            if quantity > current + 1e-9:
                raise ValueError(
                    f"Ledger {ticker} menghasilkan posisi negatif sebelum record date."
                )
            positions[ticker] = max(0.0, current - quantity)
        elif kind == "SPLIT":
            positions[ticker] = current * quantity
    return float(positions.get(ticker, 0.0))


def estimate_dividend_entitlements(
    portfolio_events,
    corporate_events,
    *,
    initial_positions=None,
) -> dict:
    """Estimate gross dividend entitlement from confirmed declaration/ex/record/pay dates.

    Declaration amount is interpreted as gross dividend per share. Milestone
    dates are paired chronologically per ticker. Only CONFIRMED milestones are
    used; ambiguous duplicate details and incomplete cycles are not estimated.
    """
    calendar = normalize_corporate_events(corporate_events)
    events = calendar["events"].copy()
    if events.empty:
        return {
            "entitlements": pd.DataFrame(),
            "warnings": ["Corporate action calendar belum memiliki event."],
            "method": "No estimate.",
        }
    warnings = list(calendar["warnings"])
    output = []
    for ticker, group in events.groupby("ticker", sort=True):
        declarations = group.loc[group["event_type"].eq("DIVIDEND_DECLARATION")].sort_values(
            "event_date", kind="stable"
        )
        milestones = {
            kind: group.loc[group["event_type"].eq(kind)].sort_values("event_date", kind="stable")
            for kind in ("EX_DIVIDEND", "RECORD_DATE", "PAY_DATE")
        }
        used = {kind: set() for kind in milestones}
        for declaration_index, declaration in declarations.iterrows():
            if declaration["status"] != "CONFIRMED":
                warnings.append(
                    f"{ticker}: deklarasi dividen {declaration['event_date'].date()} tidak CONFIRMED; estimasi dilewati."
                )
                continue
            if bool(declaration.get("conflicting_duplicate", False)):
                warnings.append(f"{ticker}: deklarasi dividen memiliki detail duplikat yang konflik; estimasi dilewati.")
                continue
            amount = declaration.get("amount")
            raw_currency = declaration.get("currency")
            currency = "" if pd.isna(raw_currency) else str(raw_currency).strip().upper()
            if pd.isna(amount) or float(amount) <= 0 or not currency:
                warnings.append(
                    f"{ticker}: deklarasi dividen harus memiliki nominal bruto per saham dan mata uang."
                )
                continue
            selected = {}
            previous_date = pd.Timestamp(declaration["event_date"])
            incomplete = False
            for kind in ("EX_DIVIDEND", "RECORD_DATE", "PAY_DATE"):
                candidates = milestones[kind]
                candidates = candidates.loc[
                    (~candidates.index.isin(used[kind]))
                    & candidates["event_date"].gt(previous_date)
                    & candidates["status"].eq("CONFIRMED")
                ]
                candidates = candidates.loc[~candidates["conflicting_duplicate"]]
                if candidates.empty:
                    warnings.append(
                        f"{ticker}: siklus dividen {declaration['event_date'].date()} belum memiliki {kind} CONFIRMED."
                    )
                    incomplete = True
                    break
                chosen = candidates.iloc[0]
                selected[kind] = chosen
                used[kind].add(chosen.name)
                previous_date = pd.Timestamp(chosen["event_date"])
            if incomplete:
                continue
            record_date = pd.Timestamp(selected["RECORD_DATE"]["event_date"])
            shares = _positions_at_record_date(
                portfolio_events, ticker, record_date, initial_positions
            )
            if shares is None:
                warnings.append(
                    f"{ticker}: tidak ada posisi awal atau histori BUY/SELL/SPLIT sampai record date; estimasi dilewati."
                )
                continue
            gross = shares * float(amount)
            output.append({
                "ticker": ticker,
                "declaration_date": pd.Timestamp(declaration["event_date"]),
                "ex_date": pd.Timestamp(selected["EX_DIVIDEND"]["event_date"]),
                "record_date": record_date,
                "pay_date": pd.Timestamp(selected["PAY_DATE"]["event_date"]),
                "shares_at_record_date_estimate": shares,
                "gross_dividend_per_share": float(amount),
                "currency": currency,
                "gross_entitlement_estimate": gross,
                "status": "ESTIMATE_ONLY",
                "source": str(declaration["source"]),
            })
    result = pd.DataFrame(output)
    if not result.empty:
        warnings.append(
            "Estimasi memakai posisi ledger berdasarkan trade date sampai record date. "
            "Aturan settlement, koreksi broker, pajak/pemotongan, fractional entitlement, "
            "dan FX tidak dihitung; verifikasi dengan broker/issuer."
        )
    return {
        "entitlements": result,
        "warnings": warnings,
        "method": (
            "Gross entitlement estimate = estimated shares held at the confirmed record date "
            "multiplied by confirmed gross dividend per share. No dividend cash event is created."
        ),
    }
