"""TSFA V1.4 Portfolio Lifecycle Engine.

Integrated accounting/audit layer over the validated historical NAV engine.
All uploaded workbook data remains in-memory; this module never writes to DataHub.
Scope: Indonesia equities / IDR, integer share units.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

from tsfa_historical_portfolio_engine import reconstruct_daily_portfolio


def _date(v: Any) -> pd.Timestamp:
    d = pd.Timestamp(v)
    if pd.isna(d):
        raise ValueError(f"Tanggal tidak valid: {v!r}")
    if d.tzinfo is not None:
        d = d.tz_localize(None)
    return d.normalize()


def _num(v: Any, field: str, *, default: float | None = None, minimum: float | None = None) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip()):
        if default is not None:
            return float(default)
        raise ValueError(f"{field} wajib diisi.")
    try:
        n = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} harus berupa angka.") from exc
    if not np.isfinite(n):
        raise ValueError(f"{field} harus berupa angka finite.")
    if minimum is not None and n < minimum:
        raise ValueError(f"{field} minimal {minimum}.")
    return n


def _clean_inputs(portfolio: pd.DataFrame, transactions: pd.DataFrame, cash_flows: pd.DataFrame):
    p = portfolio.copy().fillna({})
    tx = transactions.copy()
    cf = cash_flows.copy()
    if p.empty:
        raise ValueError("PORTFOLIO tidak boleh kosong.")
    dates = {_date(x) for x in p["As_Of_Date"].dropna().tolist()}
    if len(dates) != 1:
        raise ValueError("Semua As_Of_Date harus sama.")
    asof = next(iter(dates))
    positions: dict[str, int] = {}
    avg_cost: dict[str, float] = {}
    opening_cash = 0.0
    opening_rows = []
    for i, r in p.iterrows():
        kind = str(r.get("Record_Type", "")).strip().upper()
        if not kind or kind == "NAN":
            continue
        ticker = str(r.get("Ticker", "")).strip().upper()
        if kind == "CASH":
            if ticker != "CASH":
                raise ValueError(f"PORTFOLIO baris {i+2}: CASH harus memakai ticker CASH.")
            opening_cash += _num(r.get("Opening_Cash"), "Opening_Cash", minimum=0)
        elif kind == "HOLDING":
            q = _num(r.get("Opening_Quantity_Shares"), "Opening_Quantity_Shares", minimum=0)
            c = _num(r.get("Opening_Average_Cost"), "Opening_Average_Cost", minimum=0)
            if not ticker or ticker == "CASH" or q <= 0 or not q.is_integer() or c <= 0:
                raise ValueError(f"PORTFOLIO baris {i+2}: holding tidak valid.")
            if ticker in positions:
                raise ValueError(f"Ticker opening duplikat: {ticker}.")
            positions[ticker], avg_cost[ticker] = int(q), c
            opening_rows.append({"Ticker": ticker, "Quantity_Shares": int(q), "Average_Cost": c})
        else:
            raise ValueError(f"Record_Type tidak dikenal: {kind}.")
    if not positions:
        raise ValueError("Minimal satu HOLDING diperlukan pada PORTFOLIO.")

    if not tx.empty:
        tx["_row_order"] = np.arange(len(tx))
        tx["Date"] = tx["Date"].map(_date)
        tx["Ticker"] = tx["Ticker"].astype(str).str.strip().str.upper()
        tx["Side"] = tx["Side"].astype(str).str.strip().str.upper()
        if (tx["Date"] <= asof).any():
            raise ValueError("Transaksi harus setelah As_Of_Date.")
        if not tx["Side"].isin(["BUY", "SELL"]).all():
            raise ValueError("Side transaksi hanya boleh BUY atau SELL.")
    if not cf.empty:
        cf["_row_order"] = np.arange(len(cf))
        cf["Date"] = cf["Date"].map(_date)
        cf["Flow_Type"] = cf["Flow_Type"].astype(str).str.strip().str.upper()
        if (cf["Date"] <= asof).any():
            raise ValueError("Cash flow harus setelah As_Of_Date.")
        allowed = {"DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE", "TAX"}
        bad = sorted(set(cf["Flow_Type"]) - allowed)
        if bad:
            raise ValueError("Flow_Type tidak didukung: " + ", ".join(bad))
    return asof, positions, avg_cost, opening_cash, tx, cf, pd.DataFrame(opening_rows)


def run_portfolio_lifecycle(
    portfolio: pd.DataFrame,
    transactions: pd.DataFrame,
    cash_flows: pd.DataFrame,
    price_history: pd.DataFrame,
    *,
    max_price_staleness_days: int = 5,
) -> dict[str, pd.DataFrame]:
    """Run daily NAV, moving-average accounting, transaction/cash ledgers and reconciliation."""
    asof, positions, avg_cost, opening_cash, tx, cf, opening_positions = _clean_inputs(
        portfolio, transactions, cash_flows
    )

    # Reuse the established historical price/staleness/NAV engine as the NAV control total.
    daily = reconstruct_daily_portfolio(
        portfolio=portfolio,
        transactions=transactions,
        cash_flows=cash_flows,
        price_history=price_history,
        max_price_staleness_days=max_price_staleness_days,
    ).copy()

    prices = price_history.copy()
    prices["Date"] = prices["Date"].map(_date)
    prices["Ticker"] = prices["Ticker"].astype(str).str.strip().str.upper()
    prices["Close"] = pd.to_numeric(prices["Close"], errors="coerce")
    prices = prices.sort_values(["Date", "Ticker"])
    tickers = set(positions)
    if not tx.empty:
        tickers.update(tx["Ticker"].tolist())
    px = prices[prices["Ticker"].isin(tickers)].pivot(index="Date", columns="Ticker", values="Close")
    px = px.reindex(daily.index).ffill()

    cash = opening_cash
    realized_cum = 0.0
    cash_flow_rows, tx_rows, position_rows, daily_rows = [], [], [], []
    for date in daily.index:
        external_flow = 0.0
        income_net = 0.0
        cash_before = cash
        # Beginning-of-day cash events, in workbook order.
        if not cf.empty:
            for _, r in cf[cf["Date"] == date].sort_values("_row_order").iterrows():
                typ = r["Flow_Type"]
                amount = _num(r.get("Amount"), "Amount", minimum=0)
                tax = _num(r.get("Tax"), "Tax", default=0, minimum=0)
                if typ == "DEPOSIT": delta, ext, detail = amount, amount, "External capital contribution"
                elif typ == "WITHDRAWAL": delta, ext, detail = -amount, -amount, "External capital withdrawal"
                elif typ in {"DIVIDEND", "INTEREST"}:
                    delta, ext, detail = amount-tax, 0.0, "Investment income net of withholding tax"
                    income_net += delta
                elif typ in {"FEE", "TAX"}:
                    delta, ext, detail = -(amount+tax), 0.0, "Portfolio expense / tax"
                    income_net += delta
                else:
                    raise ValueError(f"Unsupported cash flow type {typ}.")
                cash += delta
                external_flow += ext
                if cash < -1e-6:
                    raise ValueError(f"Kas tidak cukup setelah {typ} pada {date.date()}.")
                cash_flow_rows.append({
                    "Date": date, "Flow_ID": r.get("Flow_ID"), "Flow_Type": typ,
                    "Amount": amount, "Tax": tax, "Cash_Delta": delta,
                    "External_Cash_Flow": ext, "Cash_Balance_After": cash,
                    "Description": detail,
                })

        realized_day = 0.0
        trade_cash_delta = 0.0
        if not tx.empty:
            for _, r in tx[tx["Date"] == date].sort_values("_row_order").iterrows():
                ticker, side = r["Ticker"], r["Side"]
                qty = _num(r.get("Quantity_Shares"), "Quantity_Shares", minimum=0)
                price = _num(r.get("Price_Per_Share"), "Price_Per_Share", minimum=0)
                fees = _num(r.get("Fees"), "Fees", default=0, minimum=0)
                tax = _num(r.get("Tax"), "Tax", default=0, minimum=0)
                if qty <= 0 or not qty.is_integer() or price <= 0:
                    raise ValueError(f"Transaksi {ticker} pada {date.date()} tidak valid.")
                qty = int(qty)
                q0 = positions.get(ticker, 0)
                ac0 = avg_cost.get(ticker, 0.0)
                if side == "BUY":
                    gross = qty * price
                    cash_delta = -(gross + fees + tax)
                    if cash + cash_delta < -1e-6:
                        raise ValueError(f"Kas tidak cukup untuk BUY {ticker} pada {date.date()}.")
                    q1 = q0 + qty
                    ac1 = (q0 * ac0 + gross + fees + tax) / q1
                    realized = 0.0
                else:
                    if qty > q0:
                        raise ValueError(f"SELL {ticker} {qty:,} saham melebihi kepemilikan {q0:,} pada {date.date()}.")
                    gross = qty * price
                    cash_delta = gross - fees - tax
                    realized = cash_delta - qty * ac0
                    q1 = q0 - qty
                    ac1 = ac0 if q1 else 0.0
                cash += cash_delta
                trade_cash_delta += cash_delta
                realized_day += realized
                realized_cum += realized
                positions[ticker], avg_cost[ticker] = q1, ac1
                tx_rows.append({
                    "Date": date, "Transaction_ID": r.get("Transaction_ID"), "Ticker": ticker,
                    "Side": side, "Quantity_Shares": qty, "Price_Per_Share": price,
                    "Gross_Amount": gross, "Fees": fees, "Tax": tax,
                    "Cash_Delta": cash_delta, "Quantity_Before": q0,
                    "Average_Cost_Before": ac0, "Quantity_After": q1,
                    "Average_Cost_After": ac1, "Cost_Basis_After": q1*ac1,
                    "Realized_PnL": realized, "Realized_PnL_Cumulative": realized_cum,
                })

        market_value = cost_basis = 0.0
        for ticker, qty in positions.items():
            if qty <= 0:
                continue
            if ticker not in px.columns or pd.isna(px.loc[date, ticker]):
                raise ValueError(f"Harga tidak tersedia untuk {ticker} pada {date.date()}.")
            close = float(px.loc[date, ticker])
            basis = qty * avg_cost[ticker]
            mv = qty * close
            cost_basis += basis
            market_value += mv
            position_rows.append({
                "Date": date, "Ticker": ticker, "Quantity_Shares": qty,
                "Average_Cost": avg_cost[ticker], "Cost_Basis": basis,
                "Close": close, "Market_Value": mv, "Unrealized_PnL": mv-basis,
                "Unrealized_Return": (mv/basis-1) if basis else np.nan,
            })
        nav = cash + market_value
        nav_control = float(daily.loc[date, "NAV"])
        if abs(nav-nav_control) > 1.0:
            raise ValueError(f"Rekonsiliasi NAV gagal pada {date.date()}: ledger {nav:,.2f} vs NAV engine {nav_control:,.2f}.")
        daily_rows.append({
            "Date": date, "Opening_Cash": cash_before, "Cash": cash,
            "Cash_Flow_Delta": cash-cash_before-trade_cash_delta,
            "Trade_Cash_Delta": trade_cash_delta, "Market_Value": market_value,
            "Cost_Basis": cost_basis, "Unrealized_PnL": market_value-cost_basis,
            "Realized_PnL_Daily": realized_day, "Realized_PnL_Cumulative": realized_cum,
            "Investment_Income_Net": income_net, "NAV": nav,
            "External_Cash_Flow": external_flow,
            "NAV_Control_Difference": nav-nav_control,
        })

    daily_accounting = pd.DataFrame(daily_rows).set_index("Date")
    # Preserve legacy output columns and add explicit accounting fields.
    daily = daily.join(daily_accounting.drop(columns=["Cash", "Market_Value", "NAV", "External_Cash_Flow"], errors="ignore"), rsuffix="_Accounting")
    transaction_ledger = pd.DataFrame(tx_rows, columns=[
        "Date", "Transaction_ID", "Ticker", "Side", "Quantity_Shares", "Price_Per_Share",
        "Gross_Amount", "Fees", "Tax", "Cash_Delta", "Quantity_Before", "Average_Cost_Before",
        "Quantity_After", "Average_Cost_After", "Cost_Basis_After", "Realized_PnL", "Realized_PnL_Cumulative"
    ])
    cash_ledger = pd.DataFrame(cash_flow_rows, columns=[
        "Date", "Flow_ID", "Flow_Type", "Amount", "Tax", "Cash_Delta",
        "External_Cash_Flow", "Cash_Balance_After", "Description"
    ])
    position_history = pd.DataFrame(position_rows, columns=[
        "Date", "Ticker", "Quantity_Shares", "Average_Cost", "Cost_Basis", "Close",
        "Market_Value", "Unrealized_PnL", "Unrealized_Return"
    ])
    ending = position_history[position_history["Date"] == daily.index[-1]].copy() if not position_history.empty else position_history.copy()

    opening_market = 0.0
    for _, r in opening_positions.iterrows():
        prior = prices[(prices["Ticker"] == r["Ticker"]) & (prices["Date"] <= asof)]
        if prior.empty:
            raise ValueError(f"Harga pembukaan tidak ditemukan untuk {r['Ticker']}.")
        opening_market += int(r["Quantity_Shares"]) * float(prior.iloc[-1]["Close"])
    opening_nav = opening_cash + opening_market
    net_external = float(daily["External_Cash_Flow"].sum())
    ending_nav = float(daily["NAV"].iloc[-1])
    expected_ending_cash = opening_cash + (float(cash_ledger["Cash_Delta"].sum()) if not cash_ledger.empty else 0.0) + (float(transaction_ledger["Cash_Delta"].sum()) if not transaction_ledger.empty else 0.0)
    actual_ending_cash = float(daily["Cash"].iloc[-1])
    cash_recon_difference = actual_ending_cash - expected_ending_cash
    reconciliation = pd.DataFrame([
        ("Opening Cash", opening_cash, "Saldo kas awal", "INFO"),
        ("Opening Equity Market Value", opening_market, "Nilai pasar saham pada As_Of_Date", "INFO"),
        ("Opening NAV", opening_nav, "Opening cash + opening equity market value", "INFO"),
        ("Net External Cash Flow", net_external, "Deposit dikurangi withdrawal", "INFO"),
        ("Ending Cash", actual_ending_cash, "Kas akhir dari ledger", "INFO"),
        ("Expected Ending Cash", expected_ending_cash, "Opening cash + seluruh cash-flow delta + seluruh transaction cash delta", "INFO"),
        ("Ending Cash Reconciliation Difference", cash_recon_difference, "Harus mendekati nol", "CHECK"),
        ("Ending Equity Market Value", float(daily["Market_Value"].iloc[-1]), "Nilai pasar saham akhir", "INFO"),
        ("Ending NAV", ending_nav, "Kas akhir + nilai pasar saham akhir", "INFO"),
        ("Ending NAV Difference", ending_nav-float(daily["Cash"].iloc[-1])-float(daily["Market_Value"].iloc[-1]), "Harus mendekati nol", "CHECK"),
        ("Ledger NAV Control Max Abs Difference", float(daily_accounting["NAV_Control_Difference"].abs().max()), "Maksimum selisih ledger vs historical NAV engine; harus <= Rp1", "CHECK"),
        ("Investment P&L Residual", ending_nav-opening_nav-net_external, "Residual perubahan NAV setelah arus kas eksternal", "INFO"),
        ("Realized P&L Cumulative", float(daily_accounting["Realized_PnL_Cumulative"].iloc[-1]), "Laba/rugi terealisasi dari penjualan bersih biaya dan pajak", "INFO"),
        ("Ending Unrealized P&L", float(daily_accounting["Unrealized_PnL"].iloc[-1]), "Nilai pasar akhir dikurangi cost basis akhir", "INFO"),
    ], columns=["Metric", "Value_IDR", "Explanation", "Check_Status"])
    reconciliation.loc[reconciliation["Metric"] == "Ending NAV Difference", "Check_Status"] = "PASS" if abs(float(reconciliation.loc[reconciliation["Metric"] == "Ending NAV Difference", "Value_IDR"].iloc[0])) <= 1 else "WARNING"
    reconciliation.loc[reconciliation["Metric"] == "Ending Cash Reconciliation Difference", "Check_Status"] = "PASS" if abs(cash_recon_difference) <= 1 else "WARNING"
    maxdiff = float(daily_accounting["NAV_Control_Difference"].abs().max())
    reconciliation.loc[reconciliation["Metric"] == "Ledger NAV Control Max Abs Difference", "Check_Status"] = "PASS" if maxdiff <= 1 else "WARNING"

    return {
        "daily": daily,
        "daily_accounting": daily_accounting.reset_index(),
        "transaction_ledger": transaction_ledger,
        "cash_flow_ledger": cash_ledger,
        "position_history": position_history,
        "ending_positions_accounting": ending,
        "reconciliation": reconciliation,
        "opening_positions": opening_positions,
    }
