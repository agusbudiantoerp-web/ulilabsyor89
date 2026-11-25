"""Tax-lot accounting for portfolio trades (FIFO and average cost).

BUY amount is total acquisition cash cost; SELL amount is net sale proceeds
before separately recorded portfolio-level fees/taxes. This module does not
calculate statutory tax liabilities or infer broker fills.
"""
from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd

from portfolio_cashflow import normalize_events


def calculate_tax_lots(events, *, method: str = "FIFO", opening_lots=None) -> dict:
    """Match sales to acquisition cost and return realized/unrealized lot balances.

    opening_lots accepts rows with ticker, quantity, unit_cost, and optional
    acquisition_date. Splits multiply remaining quantity and divide unit cost.
    """
    method = str(method).strip().upper()
    if method not in {"FIFO", "AVERAGE_COST"}:
        raise ValueError("Metode tax lot harus FIFO atau AVERAGE_COST.")
    lots = defaultdict(list)
    for raw in (opening_lots or []):
        ticker = str(raw.get("ticker") or "").strip().upper()
        quantity = float(raw.get("quantity", 0))
        unit_cost = float(raw.get("unit_cost", 0))
        if not ticker or not math.isfinite(quantity) or not math.isfinite(unit_cost) or quantity <= 0 or unit_cost < 0:
            raise ValueError("Opening lot harus memiliki ticker, quantity positif dan unit_cost non-negatif.")
        raw_date = str(raw.get("acquisition_date") or "").strip()
        if raw_date:
            parsed_date = pd.to_datetime(raw_date, errors="coerce")
            if pd.isna(parsed_date):
                raise ValueError("Tanggal acquisition_date opening lot tidak valid.")
            acquisition_date = parsed_date.date().isoformat()
        else:
            # Legacy opening positions without a known date are treated as the
            # oldest available lots, and remain explicitly undated in output.
            acquisition_date = ""
        lots[ticker].append({
            "ticker": ticker, "acquisition_date": acquisition_date,
            "quantity": quantity, "unit_cost": unit_cost,
        })
    if method == "FIFO":
        for ticker_lots in lots.values():
            ticker_lots.sort(
                key=lambda lot: (lot["acquisition_date"] or "0000-01-01")
            )

    raw_events = events.copy() if isinstance(events, pd.DataFrame) else list(events or [])
    if isinstance(raw_events, pd.DataFrame) and raw_events.empty:
        raw_events = pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price", "notes"])
    elif isinstance(raw_events, list) and not raw_events:
        raw_events = pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price", "notes"])
    frame = normalize_events(raw_events)
    realized = []
    warnings = []
    for row in frame.to_dict("records"):
        kind = row["event_type"]
        ticker = str(row["ticker"] or "").upper()
        quantity = float(row["quantity"]) if pd.notna(row["quantity"]) else 0.0
        amount = float(row["amount"])
        price = float(row["price"]) if pd.notna(row["price"]) else 0.0
        event_date = pd.Timestamp(row["date"]).date().isoformat()
        if kind == "BUY":
            lots[ticker].append({
                "ticker": ticker, "acquisition_date": event_date,
                "quantity": quantity, "unit_cost": amount / quantity,
            })
            if method == "FIFO":
                lots[ticker].sort(
                    key=lambda lot: (lot["acquisition_date"] or "0000-01-01")
                )
        elif kind == "SPLIT":
            if ticker not in lots or not lots[ticker]:
                warnings.append(f"{ticker}: split tanpa tax lot; basis biaya historis belum tersedia.")
                continue
            for lot in lots[ticker]:
                lot["quantity"] *= quantity
                lot["unit_cost"] /= quantity
        elif kind == "SELL":
            eligible_lots = [
                lot for lot in lots[ticker]
                if not lot["acquisition_date"] or lot["acquisition_date"] <= event_date
            ]
            available = sum(lot["quantity"] for lot in eligible_lots)
            if quantity > available + 1e-9:
                raise ValueError(
                    f"SELL {ticker} melebihi tax lot tersedia pada {event_date} ({available:.8g})."
                )
            if method == "AVERAGE_COST":
                # Only lots acquired by the sale date are eligible. Keep later
                # dated lots untouched instead of consuming future holdings.
                ineligible_lots = [
                    lot for lot in lots[ticker]
                    if lot["acquisition_date"] and lot["acquisition_date"] > event_date
                ]
                total_basis = sum(
                    lot["quantity"] * lot["unit_cost"] for lot in eligible_lots
                )
                average = total_basis / available if available else 0.0
                basis = quantity * average
                remaining_quantity = max(0.0, available - quantity)
                remaining_lots = ([
                    {
                        "ticker": ticker, "acquisition_date": event_date,
                        "quantity": remaining_quantity, "unit_cost": average,
                    }
                ] if remaining_quantity > 1e-9 else [])
                lots[ticker] = remaining_lots + ineligible_lots
            else:
                remaining = quantity
                basis = 0.0
                for lot in eligible_lots:
                    take = min(lot["quantity"], remaining)
                    basis += take * lot["unit_cost"]
                    lot["quantity"] -= take
                    remaining -= take
                    if remaining <= 1e-9:
                        break
            lots[ticker] = [lot for lot in lots[ticker] if lot["quantity"] > 1e-9]
            proceeds_per_share = amount / quantity
            realized.append({
                "date": event_date, "ticker": ticker, "quantity": quantity,
                "sale_proceeds": amount, "cost_basis": basis,
                "realized_pnl": amount - basis,
                "realized_return_pct": ((amount / basis - 1.0) * 100.0) if basis > 0 else None,
                "matched_unit_sale_proceeds": proceeds_per_share,
                "method": method,
            })

    open_rows = []
    for ticker, ticker_lots in sorted(lots.items()):
        for lot in ticker_lots:
            if lot["quantity"] > 1e-9:
                open_rows.append({**lot, "cost_basis": lot["quantity"] * lot["unit_cost"]})
    realized_frame = pd.DataFrame(realized, columns=[
        "date", "ticker", "quantity", "sale_proceeds", "cost_basis",
        "realized_pnl", "realized_return_pct", "matched_unit_sale_proceeds", "method",
    ])
    open_frame = pd.DataFrame(open_rows, columns=[
        "ticker", "acquisition_date", "quantity", "unit_cost", "cost_basis",
    ])
    realized_total = float(realized_frame["realized_pnl"].sum()) if not realized_frame.empty else 0.0
    open_basis = float(open_frame["cost_basis"].sum()) if not open_frame.empty else 0.0
    return {
        "method": method,
        "realized_trades": realized_frame,
        "open_lots": open_frame,
        "realized_pnl": realized_total,
        "realized_sale_proceeds": float(realized_frame["sale_proceeds"].sum()) if not realized_frame.empty else 0.0,
        "realized_cost_basis": float(realized_frame["cost_basis"].sum()) if not realized_frame.empty else 0.0,
        "open_cost_basis": open_basis,
        "open_quantity_by_ticker": {
            ticker: float(sum(lot["quantity"] for lot in ticker_lots))
            for ticker, ticker_lots in sorted(lots.items())
            if sum(lot["quantity"] for lot in ticker_lots) > 1e-9
        },
        "warnings": warnings,
        "limitations": (
            "Tidak menghitung pajak legal, wash-sale, corporate action selain split, "
            "biaya broker yang dicatat terpisah, FX, atau rekonsiliasi statement broker. "
            "SELL amount dianggap hasil bersih sebelum event FEE/TAX terpisah."
        ),
    }
