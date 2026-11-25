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

    DEPOSIT/WITHDRAWAL and FEE/TAX amounts use base currency. BUY/SELL amounts
    and DIVIDEND amounts use the relevant asset's local currency. FEE/TAX may
    optionally specify amount_currency (IDR or USD) on the event.
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
    dates.update(pd.Timestamp(value) for value in frame["date"])
    timeline = pd.DatetimeIndex(sorted(dates), name="date")
    if len(timeline) < 2:
        raise ValueError("Minimal dua tanggal valuasi diperlukan.")
    if not frame.empty and (frame["date"].min() < timeline.min() or frame["date"].max() > timeline.max()):
        raise ValueError("Tanggal event berada di luar cakupan data harga.")

    events_by_date = {
        pd.Timestamp(day): group.to_dict("records")
        for day, group in frame.groupby("date", sort=True)
    }
    rows = []
    previous_value = None
    for when in timeline:
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
                factor = _fx_factor(currencies[ticker], base, when, fx, max_fx_gap_days)
                amount_base = amount * factor
                if kind == "BUY":
                    cash -= amount_base
                    if cash < -1e-8:
                        raise ValueError(f"Cash tidak cukup untuk BUY {ticker} pada {when.date()}.")
                    positions[ticker] = positions.get(ticker, 0.0) + quantity
                else:
                    if quantity > positions.get(ticker, 0.0) + 1e-9:
                        raise ValueError(f"SELL {ticker} melebihi jumlah saham tersedia.")
                    cash += amount_base
                    positions[ticker] = max(0.0, positions.get(ticker, 0.0) - quantity)
            elif kind == "DIVIDEND":
                factor = _fx_factor(currencies[ticker], base, when, fx, max_fx_gap_days)
                cash += amount * factor
            elif kind in {"FEE", "TAX"}:
                event_currency = str(row.get("amount_currency") or base).upper()
                if event_currency not in {"IDR", "USD"}:
                    raise ValueError("amount_currency untuk FEE/TAX harus IDR atau USD.")
                factor = _fx_factor(event_currency, base, when, fx, max_fx_gap_days)
                cash -= amount * factor
            elif kind == "SPLIT":
                positions[ticker] = positions.get(ticker, 0.0) * quantity
            if cash < -1e-8:
                raise ValueError(f"Cash tidak cukup setelah event {kind} pada {when.date()}.")

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
        portfolio_value = max(0.0, cash) + market_value
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
        "ending_market_value": float(curve["market_value"].iloc[-1]),
        "ending_portfolio_value": float(curve["portfolio_value"].iloc[-1]),
        "ending_positions": dict(positions),
        "total_twr_pct": total_twr,
        "event_count": int(len(frame)),
        "method": (
            "Event replay at supplied fill dates/prices; daily mark-to-market uses backward as-of closes "
            "and explicit stale-price/FX limits. Deposits/withdrawals are external flows removed from daily TWR. "
            "Internal trades, dividends, fees and taxes remain in portfolio performance."
        ),
        "limitations": (
            "No intraday execution, broker fills, settlement cycle, tax-lot realization, market impact, "
            "dividend entitlement inference or automatic currency cash sub-ledgers. Fees/taxes default to base currency "
            "unless amount_currency is supplied."
        ),
    }
