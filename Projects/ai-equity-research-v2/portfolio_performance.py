"""Portfolio performance attribution from tax lots, market marks and ledger cash events.
The output is indicative, not a tax calculation or broker statement.
"""
from __future__ import annotations
import math
import pandas as pd

def _finite(value, label: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or type(value).__name__ in {"bool_", "bool"}:
        raise ValueError(f"{label} harus berupa angka, bukan boolean.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} harus berupa angka finite.") from exc
    if not math.isfinite(number) or (not allow_zero and number <= 0):
        raise ValueError(f"{label} harus berupa angka finite" + (" positif." if not allow_zero else "."))
    return number

def calculate_portfolio_performance_snapshot(tax_lot_result: dict, events, market_prices: dict[str, float], *, as_of_date=None) -> dict:
    """Calculate realized/unrealized P&L and attribution using supplied marks."""
    if not isinstance(tax_lot_result, dict):
        raise ValueError("Tax lot result harus berupa dictionary.")
    required = {"open_lots", "realized_pnl", "open_cost_basis", "realized_sale_proceeds"}
    missing = required - set(tax_lot_result)
    if missing:
        raise ValueError("Tax lot result tidak lengkap: " + ", ".join(sorted(missing)))
    lots = tax_lot_result["open_lots"]
    if not isinstance(lots, pd.DataFrame) or not {"ticker", "quantity", "cost_basis"}.issubset(lots.columns):
        raise ValueError("Open lots wajib berupa DataFrame dengan ticker, quantity dan cost_basis.")
    if not isinstance(market_prices, dict):
        raise ValueError("Market prices harus berupa dictionary TICKER:PRICE.")
    normalized_prices = {}
    for raw_ticker, raw_price in market_prices.items():
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker or ticker in normalized_prices:
            raise ValueError("Ticker harga kosong atau duplikat.")
        normalized_prices[ticker] = _finite(raw_price, f"Harga {ticker}", allow_zero=False)
    positions = {}
    for row in lots.to_dict("records"):
        ticker = str(row["ticker"] or "").strip().upper()
        if not ticker:
            raise ValueError("Ticker open lot tidak boleh kosong.")
        quantity = _finite(row["quantity"], f"Quantity {ticker}", allow_zero=False)
        basis = _finite(row["cost_basis"], f"Cost basis {ticker}")
        current = positions.setdefault(ticker, {"quantity": 0.0, "cost_basis": 0.0})
        current["quantity"] += quantity
        current["cost_basis"] += basis
    missing_prices = sorted(set(positions) - set(normalized_prices))
    if missing_prices:
        raise ValueError("Harga pasar belum tersedia untuk: " + ", ".join(missing_prices))
    unused_prices = sorted(set(normalized_prices) - set(positions))
    holdings, market_value, open_basis = [], 0.0, 0.0
    for ticker, position in sorted(positions.items()):
        mark = normalized_prices[ticker]
        value = position["quantity"] * mark
        unrealized = value - position["cost_basis"]
        market_value += value
        open_basis += position["cost_basis"]
        holdings.append({"ticker": ticker, "quantity": position["quantity"], "market_price": mark,
            "market_value": value, "cost_basis": position["cost_basis"], "unrealized_pnl": unrealized,
            "unrealized_return_pct": unrealized / position["cost_basis"] * 100.0 if position["cost_basis"] > 0 else None})
    frame = events.copy() if isinstance(events, pd.DataFrame) else pd.DataFrame(list(events or []))
    if frame.empty:
        frame = pd.DataFrame(columns=["event_type", "amount"])
    if not {"event_type", "amount"}.issubset(frame.columns):
        raise ValueError("Events wajib memiliki event_type dan amount.")
    frame["event_type"] = frame["event_type"].astype(str).str.upper().str.strip()
    if "date" in frame.columns and as_of_date is not None:
        cutoff = pd.Timestamp(as_of_date)
        if pd.isna(cutoff):
            raise ValueError("As-of date tidak valid.")
        dates = pd.to_datetime(frame["date"], errors="coerce")
        if dates.isna().any():
            raise ValueError("Tanggal event tidak valid.")
        frame = frame.loc[dates.dt.date <= cutoff.date()].copy()
    totals = {}
    for kind in ("DIVIDEND", "FEE", "TAX"):
        amounts = [_finite(v, f"Nominal {kind}") for v in frame.loc[frame["event_type"].eq(kind), "amount"]]
        totals[kind.lower()] = float(sum(amounts))
    realized = _finite(tax_lot_result["realized_pnl"], "Realized P&L")
    reported_basis = _finite(tax_lot_result["open_cost_basis"], "Open cost basis")
    if not math.isclose(reported_basis, open_basis, rel_tol=1e-7, abs_tol=1e-7):
        raise ValueError("Open cost basis tidak konsisten dengan rincian open lots.")
    realized_proceeds = _finite(tax_lot_result["realized_sale_proceeds"], "Realized sale proceeds")
    realized_basis = _finite(tax_lot_result.get("realized_cost_basis", 0), "Realized cost basis")
    unrealized = market_value - open_basis
    dividends, fees, taxes = totals["dividend"], totals["fee"], totals["tax"]
    total_profit = realized + unrealized + dividends - fees - taxes
    invested_basis = open_basis + realized_basis
    return {
        "as_of_date": str(pd.Timestamp(as_of_date).date()) if as_of_date is not None else None,
        "holdings": pd.DataFrame(holdings, columns=["ticker", "quantity", "market_price", "market_value", "cost_basis", "unrealized_pnl", "unrealized_return_pct"]),
        "market_value": market_value, "open_cost_basis": open_basis, "unrealized_pnl": unrealized,
        "realized_pnl": realized, "realized_sale_proceeds": realized_proceeds,
        "dividend_income": dividends, "fees": fees, "taxes": taxes, "fees_and_taxes": fees + taxes,
        "total_profit_including_dividends": total_profit,
        "total_return_on_recorded_cost_basis_pct": total_profit / invested_basis * 100.0 if invested_basis > 0 else None,
        "missing_prices": [], "unused_price_tickers": unused_prices,
        "limitations": ("Snapshot memakai harga pasar yang dimasukkan pengguna dan tax-lot method terpilih. "
            "Semua nominal wajib satu mata uang; tidak memasukkan FX, pajak legal, biaya yang belum dicatat, "
            "corporate actions yang belum masuk ledger, atau cash balance. Total return adalah attribution "
            "atas cost basis transaksi tercatat, bukan TWR/XIRR.")
    }
