"""Transaction-aware mixed-currency portfolio valuation and TWR backtest.

Trades use explicit ledger fill price/amount; daily marks use historical close
series. All cash and portfolio values are converted into one explicit base
currency. This is not a broker execution simulator.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping

import pandas as pd

from portfolio_cashflow import normalize_events


def _clean_series(series: pd.Series, label: str) -> pd.Series:
    if not isinstance(series, pd.Series) or series.empty:
        raise ValueError(f"Data {label} kosong.")
    result = pd.to_numeric(series, errors="coerce").copy()
    result.index = pd.to_datetime(result.index)
    if result.index.tz is not None:
        result.index = result.index.tz_localize(None)
    result = result.sort_index()
    if result.index.has_duplicates:
        result = result.groupby(level=0).last()
    if result.isna().any() or not all(math.isfinite(float(x)) for x in result):
        raise ValueError(f"Data {label} mengandung nilai non-finite.")
    if (result <= 0).any():
        raise ValueError(f"Data {label} harus positif.")
    return result.astype(float)


def _asof_value(series: pd.Series, when: pd.Timestamp, max_gap_days: int, label: str) -> float:
    index = series.index
    position = int(index.searchsorted(when, side="right")) - 1
    if position < 0:
        raise ValueError(f"{label} belum tersedia pada {when.date()}; look-ahead dilarang.")
    observed = index[position]
    age = (when.normalize() - observed.normalize()).days
    if age > max_gap_days:
        raise ValueError(f"{label} stale {age} hari pada {when.date()} (maksimum {max_gap_days}).")
    return float(series.iloc[position])


def _event_currency(row: dict, default: str) -> str:
    value = row.get("amount_currency")
    if value is None or pd.isna(value) or not str(value).strip():
        return str(default).upper()
    return str(value).strip().upper()


def _fx_factor(currency: str, base: str, when: pd.Timestamp,
               fx: pd.Series | None, max_gap_days: int) -> float:
    currency, base = currency.upper(), base.upper()
    if currency == base:
        return 1.0
    if {currency, base} != {"IDR", "USD"}:
        raise ValueError(f"Konversi mata uang {currency}/{base} tidak didukung.")
    if fx is None:
        raise ValueError("Data USD/IDR wajib untuk portfolio lintas mata uang.")
    rate = _asof_value(fx, when, max_gap_days, "USD/IDR")
    return rate if currency == "USD" and base == "IDR" else 1.0 / rate


def run_transaction_aware_portfolio(
    price_closes: Mapping[str, pd.Series],
    asset_currencies: Mapping[str, str],
    events,
    *,
    base_currency: str = "IDR",
    usd_idr_close: pd.Series | None = None,
    initial_cash: float = 0.0,
    initial_positions: Mapping[str, float] | None = None,
    max_price_gap_days: int = 7,
    max_fx_gap_days: int = 3,
) -> dict:
    """Replay dated cash/trade events and calculate base-currency equity/TWR.

    All event cash amounts use the portfolio base currency. For foreign-asset
    BUY/SELL/DIVIDEND events, the user must explicitly convert the cash amount
    into base currency before entry; the engine never silently converts trade
    cash. The price field remains in the asset's local quote currency.
    BUY/SELL may specify settlement_date; positions change on trade date while
    base-currency cash settles on the supplied date.
    """

    if not isinstance(price_closes, Mapping) or not price_closes:
        raise ValueError("Minimal satu seri harga aset diperlukan.")
    symbols = list(price_closes)
    if set(symbols) != set(asset_currencies):
        raise ValueError("Ticker harga dan asset currencies harus sama.")
    base = str(base_currency).upper().strip()
    if base not in {"IDR", "USD"}:
        raise ValueError("Base currency hanya mendukung IDR atau USD.")
    if max_price_gap_days < 0 or max_fx_gap_days < 0:
        raise ValueError("Toleransi umur harga/FX tidak boleh negatif.")
    cash = float(initial_cash)
    if not math.isfinite(cash) or cash < 0:
        raise ValueError("Initial cash harus finite dan tidak negatif.")
    positions = {str(k).upper(): float(v) for k, v in (initial_positions or {}).items()}
    if set(positions) - set(symbols):
        raise ValueError("Initial position memiliki ticker tanpa data harga.")
    if any(not math.isfinite(v) or v < 0 for v in positions.values()):
        raise ValueError("Initial positions harus finite dan tidak negatif.")
    currencies = {str(k).upper(): str(v).upper().strip() for k, v in asset_currencies.items()}
    if any(value not in {"IDR", "USD"} for value in currencies.values()):
        raise ValueError("Mata uang aset hanya mendukung IDR atau USD.")
    prices = {str(k).upper(): _clean_series(v, f"close {k}") for k, v in price_closes.items()}
    if len(prices) != len(symbols):
        raise ValueError("Ticker harga duplikat setelah normalisasi.")
    fx = _clean_series(usd_idr_close, "USD/IDR") if usd_idr_close is not None else None
    raw_events = events.copy() if isinstance(events, pd.DataFrame) else list(events or [])
    if isinstance(raw_events, pd.DataFrame) and raw_events.empty:
        raw_events = pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price", "notes"])
    elif isinstance(raw_events, list) and not raw_events:
        raw_events = pd.DataFrame(columns=["date", "event_type", "amount", "ticker", "quantity", "price", "notes"])
    frame = normalize_events(raw_events)
    unknown = sorted(set(frame.loc[frame["ticker"].ne(""), "ticker"]) - set(prices))
    if unknown:
        raise ValueError("Ticker event tidak memiliki data harga: " + ", ".join(unknown))
    dates = set()
    for series in prices.values():
        dates.update(series.index)
    market_end = max(series.index.max() for series in prices.values())
    dates.update(pd.Timestamp(value) for value in frame["date"])
    for row in frame.to_dict("records"):
        if row["event_type"] in {"BUY", "SELL"}:
            raw_settlement = row.get("settlement_date")
            if raw_settlement is not None and not pd.isna(raw_settlement) and str(raw_settlement).strip():
                settlement = pd.to_datetime(raw_settlement, errors="coerce")
                if pd.isna(settlement):
                    raise ValueError("Settlement date transaksi tidak valid.")
                if settlement < pd.Timestamp(row["date"]):
                    raise ValueError("Settlement date tidak boleh lebih awal dari trade date.")
                if pd.Timestamp(settlement) <= market_end:
                    dates.add(pd.Timestamp(settlement))
    timeline = pd.DatetimeIndex(sorted(dates), name="date")
    if len(timeline) < 2:
        raise ValueError("Minimal dua tanggal valuasi diperlukan.")
    if not frame.empty and (frame["date"].min() < timeline.min() or frame["date"].max() > timeline.max()):
        raise ValueError("Tanggal event berada di luar cakupan data harga.")

    events_by_date = {
        pd.Timestamp(day): group.to_dict("records")
        for day, group in frame.groupby("date", sort=True)
    }
    settlements_by_date = defaultdict(list)
    unsettled_payables = 0.0
    unsettled_receivables = 0.0
    pending_settlements = []
    rows = []
    previous_value = None
    for when in timeline:
        for settlement in settlements_by_date.pop(when, []):
            cash += float(settlement["cash_delta"])
            if settlement["kind"] == "BUY":
                unsettled_payables = max(0.0, unsettled_payables - settlement["amount"])
            else:
                unsettled_receivables = max(0.0, unsettled_receivables - settlement["amount"])
            pending_settlements.remove(settlement)

        external_flow = 0.0
        for row in events_by_date.get(when, []):
            kind = str(row["event_type"])
            ticker = str(row["ticker"] or "").upper()
            amount = float(row["amount"])
            quantity = float(row["quantity"]) if pd.notna(row["quantity"]) else 0.0
            if kind in {"DEPOSIT", "WITHDRAWAL"}:
                if kind == "DEPOSIT":
                    cash += amount
                    external_flow += amount
                else:
                    cash -= amount
                    external_flow -= amount
            elif kind in {"BUY", "SELL"}:
                if ticker not in prices:
                    raise ValueError(f"Ticker {ticker} tidak memiliki seri harga.")
                event_currency = _event_currency(row, base)
                if event_currency != base:
                    raise ValueError(
                        f"Nominal BUY/SELL harus dalam base currency {base}; "
                        "konversi kas lintas mata uang tidak dilakukan otomatis."
                    )
                amount_base = amount
                raw_settlement = row.get("settlement_date")
                settlement_date = (
                    pd.Timestamp(pd.to_datetime(raw_settlement, errors="coerce"))
                    if raw_settlement is not None and not pd.isna(raw_settlement) and str(raw_settlement).strip()
                    else when
                )
                if pd.isna(settlement_date) or settlement_date < when:
                    raise ValueError("Settlement date transaksi tidak valid atau lebih awal dari trade date.")
                deferred = settlement_date > when
                if kind == "BUY":
                    available_cash = cash - unsettled_payables
                    if available_cash + 1e-8 < amount_base:
                        raise ValueError(f"Cash tersedia tidak cukup untuk BUY {ticker} pada {when.date()}.")
                    positions[ticker] = positions.get(ticker, 0.0) + quantity
                    if deferred:
                        settlement = {
                            "kind": "BUY", "amount": amount_base,
                            "cash_delta": -amount_base, "settlement_date": settlement_date,
                            "ticker": ticker,
                        }
                        unsettled_payables += amount_base
                        settlements_by_date[settlement_date].append(settlement)
                        pending_settlements.append(settlement)
                    else:
                        cash -= amount_base
                else:
                    if quantity > positions.get(ticker, 0.0) + 1e-9:
                        raise ValueError(f"SELL {ticker} melebihi jumlah saham tersedia.")
                    positions[ticker] = max(0.0, positions.get(ticker, 0.0) - quantity)
                    if deferred:
                        settlement = {
                            "kind": "SELL", "amount": amount_base,
                            "cash_delta": amount_base, "settlement_date": settlement_date,
                            "ticker": ticker,
                        }
                        unsettled_receivables += amount_base
                        settlements_by_date[settlement_date].append(settlement)
                        pending_settlements.append(settlement)
                    else:
                        cash += amount_base
            elif kind == "DIVIDEND":
                event_currency = _event_currency(row, base)
                if event_currency != base:
                    raise ValueError(
                        f"Nominal DIVIDEND harus dalam base currency {base}; "
                        "konversi kas lintas mata uang tidak dilakukan otomatis."
                    )
                cash += amount
            elif kind in {"FEE", "TAX"}:
                event_currency = _event_currency(row, base)
                if event_currency != base:
                    raise ValueError(
                        f"Nominal FEE/TAX harus dalam base currency {base}; "
                        "konversi kas lintas mata uang tidak dilakukan otomatis."
                    )
                cash -= amount
            elif kind == "SPLIT":
                positions[ticker] = positions.get(ticker, 0.0) * quantity
            if cash - unsettled_payables < -1e-8:
                raise ValueError(f"Cash tersedia tidak cukup setelah event {kind} pada {when.date()}.")

        market_value = 0.0
        position_values = {}
        for ticker, quantity in positions.items():
            if quantity <= 1e-9:
                continue
            local_close = _asof_value(prices[ticker], when, max_price_gap_days, f"Close {ticker}")
            factor = _fx_factor(currencies[ticker], base, when, fx, max_fx_gap_days)
            value = quantity * local_close * factor
            position_values[ticker] = value
            market_value += value
        available_cash = max(0.0, cash - unsettled_payables)
        portfolio_value = max(0.0, cash) + market_value + unsettled_receivables - unsettled_payables
        if portfolio_value <= 0:
            raise ValueError(f"Portfolio value tidak positif pada {when.date()}.")
        daily_return = None
        if previous_value is not None:
            capital_at_risk = previous_value + external_flow
            if capital_at_risk <= 0:
                raise ValueError(f"Modal awal setelah external flow tidak positif pada {when.date()}.")
            daily_return = portfolio_value / capital_at_risk - 1.0
            if daily_return <= -1.0:
                raise ValueError("Return harian tidak boleh -100% atau lebih rendah.")
        rows.append({
            "date": when, "cash_balance": max(0.0, cash),
            "available_cash": available_cash,
            "unsettled_receivables": unsettled_receivables,
            "unsettled_payables": unsettled_payables,
            "market_value": market_value, "portfolio_value": portfolio_value,
            "external_flow": external_flow, "daily_twr_return": daily_return,
            "position_values": dict(position_values),
        })
        previous_value = portfolio_value

    curve = pd.DataFrame(rows).set_index("date")
    valid_returns = curve["daily_twr_return"].dropna()
    total_twr = (float((1.0 + valid_returns).prod()) - 1.0) * 100.0
    curve["twr_equity_index"] = (1.0 + curve["daily_twr_return"].fillna(0.0)).cumprod()
    return {
        "base_currency": base,
        "curve": curve,
        "ending_cash": float(curve["cash_balance"].iloc[-1]),
        "ending_available_cash": float(curve["available_cash"].iloc[-1]),
        "ending_unsettled_receivables": float(curve["unsettled_receivables"].iloc[-1]),
        "ending_unsettled_payables": float(curve["unsettled_payables"].iloc[-1]),
        "pending_settlements": pd.DataFrame(pending_settlements),
        "ending_market_value": float(curve["market_value"].iloc[-1]),
        "ending_portfolio_value": float(curve["portfolio_value"].iloc[-1]),
        "ending_positions": dict(positions),
        "total_twr_pct": total_twr,
        "event_count": int(len(frame)),
        "method": (
            "Event replay at supplied fill dates/prices; daily mark-to-market uses backward as-of closes "
            "and explicit stale-price/FX limits. Deposits/withdrawals are external flows removed from daily TWR. "
            "Internal trades, dividends, fees and taxes remain in portfolio performance. Supplied settlement dates separate trade-date holdings from settlement-date cash."
        ),
        "limitations": (
            "No intraday execution, broker fills, inferred settlement calendars, tax-lot realization, market impact, "
            "dividend entitlement inference or automatic currency cash sub-ledgers. Fees/taxes default to base currency "
            "unless amount_currency is supplied."
        ),
    }
