
"""
TSFA Historical Portfolio Engine
================================

Reconstructs daily portfolio NAV from:
- Opening portfolio balances
- BUY and SELL transactions
- Deposits, withdrawals, dividends and interest
- Historical closing prices

Initial scope: Indonesia / IDR.

Historical price staleness is checked using calendar days.
External cash flows are applied at the beginning of their date.
Transactions on the same date retain workbook row order.
"""

import numpy as np
import pandas as pd


def calculate_time_weighted_returns(nav, external_cash_flows):
    """Calculate daily TWR, assuming external flows occur at start of day."""

    if not isinstance(nav, pd.Series):
        raise TypeError("nav must be a pandas Series.")

    if not isinstance(external_cash_flows, pd.Series):
        raise TypeError("external_cash_flows must be a pandas Series.")

    if len(nav) < 2:
        raise ValueError("At least two NAV observations are required.")

    if not isinstance(nav.index, pd.DatetimeIndex):
        raise TypeError("NAV index must be a DatetimeIndex.")

    if not isinstance(external_cash_flows.index, pd.DatetimeIndex):
        raise TypeError("Cash flow index must be a DatetimeIndex.")

    if nav.index.has_duplicates:
        raise ValueError("NAV dates must be unique.")

    if external_cash_flows.index.has_duplicates:
        raise ValueError("Cash flow dates must be unique.")

    nav = nav.sort_index().astype(float)
    external_cash_flows = external_cash_flows.sort_index().astype(float)

    if not nav.index.equals(external_cash_flows.index):
        raise ValueError("NAV and cash flow dates must match exactly.")

    if not np.isfinite(nav.to_numpy()).all():
        raise ValueError("NAV contains non-finite values.")

    if not np.isfinite(external_cash_flows.to_numpy()).all():
        raise ValueError("External cash flows contain non-finite values.")

    if (nav <= 0).any():
        raise ValueError("NAV must be positive.")

    adjusted_capital = nav.shift(1) + external_cash_flows
    adjusted_capital.iloc[0] = np.nan

    if (adjusted_capital.iloc[1:] <= 0).any():
        raise ValueError("Adjusted capital must be positive.")

    daily_returns = nav / adjusted_capital - 1.0
    daily_returns.iloc[0] = np.nan

    if not np.isfinite(daily_returns.iloc[1:].to_numpy()).all():
        raise ValueError("Calculated returns contain non-finite values.")

    twr_index = pd.Series(index=nav.index, dtype=float, name="TWR_Index")
    twr_index.iloc[0] = 100.0

    for i in range(1, len(twr_index)):
        twr_index.iloc[i] = (
            twr_index.iloc[i - 1] * (1.0 + daily_returns.iloc[i])
        )

    daily_returns.name = "Daily_Return"

    return {
        "daily_returns": daily_returns,
        "twr_index": twr_index,
    }


def _to_date(value, field_name):
    """Convert a value to a normalized pandas Timestamp."""
    try:
        result = pd.Timestamp(value)
    except Exception as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc

    if pd.isna(result):
        raise ValueError(f"Invalid {field_name}: {value}")

    if result.tzinfo is not None:
        result = result.tz_localize(None)

    return result.normalize()


def _number(value, field_name, minimum=None):
    """Convert a value to a finite float and optionally enforce a minimum."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric.")

    if not np.isfinite(result):
        raise ValueError(f"{field_name} must be finite.")

    if minimum is not None and result < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}.")

    return result


def reconstruct_daily_portfolio(
    portfolio,
    transactions,
    cash_flows,
    price_history,
    max_price_staleness_days=5,
):
    """
    Reconstruct daily portfolio holdings, cash and NAV.

    max_price_staleness_days:
        Maximum calendar-day age allowed for a held ticker's latest
        available closing price.

    Returns a DataFrame indexed by date with:
    Cash, Market_Value, NAV, External_Cash_Flow, Realized_PnL.
    """

    if (
        isinstance(max_price_staleness_days, bool)
        or not isinstance(max_price_staleness_days, (int, np.integer))
        or max_price_staleness_days < 0
    ):
        raise ValueError(
            "max_price_staleness_days must be a non-negative integer."
        )

    required_portfolio = {
        "Record_Type",
        "Ticker",
        "Opening_Quantity_Shares",
        "Opening_Average_Cost",
        "Opening_Cash",
        "As_Of_Date",
    }

    required_transactions = {
        "Date",
        "Ticker",
        "Side",
        "Quantity_Shares",
        "Price_Per_Share",
        "Fees",
        "Tax",
    }

    required_cash_flows = {
        "Date",
        "Flow_Type",
        "Amount",
        "Tax",
    }

    required_prices = {
        "Date",
        "Ticker",
        "Close",
    }

    for name, frame, required in [
        ("portfolio", portfolio, required_portfolio),
        ("transactions", transactions, required_transactions),
        ("cash_flows", cash_flows, required_cash_flows),
        ("price_history", price_history, required_prices),
    ]:
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{name} must be a pandas DataFrame.")

        missing = required - set(frame.columns)
        if missing:
            raise ValueError(
                f"{name} is missing columns: {sorted(missing)}"
            )

    if portfolio.empty:
        raise ValueError("Portfolio opening balances cannot be empty.")

    # Opening balances.
    as_of_dates = {
        _to_date(value, "As_Of_Date")
        for value in portfolio["As_Of_Date"]
    }

    if len(as_of_dates) != 1:
        raise ValueError("All portfolio rows must share one As_Of_Date.")

    as_of = next(iter(as_of_dates))

    positions = {}
    average_costs = {}
    opening_cash = 0.0

    for _, row in portfolio.iterrows():
        record_type = str(row["Record_Type"]).strip().upper()
        ticker = str(row["Ticker"]).strip().upper()

        if record_type == "CASH":
            if ticker != "CASH":
                raise ValueError("CASH record must use ticker CASH.")

            opening_cash += _number(
                row["Opening_Cash"], "Opening_Cash", minimum=0
            )
            continue

        if record_type != "HOLDING":
            raise ValueError(f"Unsupported Record_Type: {record_type}")

        if not ticker or ticker == "CASH":
            raise ValueError("Invalid holding ticker.")

        if ticker in positions:
            raise ValueError(f"Duplicate opening holding: {ticker}")

        quantity = _number(
            row["Opening_Quantity_Shares"],
            "Opening_Quantity_Shares",
            minimum=0,
        )

        average_cost = _number(
            row["Opening_Average_Cost"],
            "Opening_Average_Cost",
            minimum=0,
        )

        if quantity <= 0 or not quantity.is_integer():
            raise ValueError("Opening quantity must be a positive integer.")

        if average_cost <= 0:
            raise ValueError("Opening average cost must be positive.")

        positions[ticker] = int(quantity)
        average_costs[ticker] = average_cost

    if not positions:
        raise ValueError("At least one opening holding is required.")

    # Historical prices.
    prices = price_history.copy()

    prices["Date"] = prices["Date"].map(
        lambda value: _to_date(value, "price Date")
    )
    prices["Ticker"] = (
        prices["Ticker"].astype(str).str.strip().str.upper()
    )
    prices["Close"] = pd.to_numeric(prices["Close"], errors="coerce")

    if prices["Close"].isna().any():
        raise ValueError("Price history contains invalid Close values.")

    if not np.isfinite(prices["Close"].to_numpy()).all():
        raise ValueError("Price history contains non-finite Close values.")

    if (prices["Close"] <= 0).any():
        raise ValueError("Historical Close prices must be positive.")

    if prices.duplicated(["Date", "Ticker"]).any():
        raise ValueError("Duplicate historical price dates and tickers.")

    prices = prices.sort_values(["Date", "Ticker"]).reset_index(drop=True)

    # Transactions.
    tx = transactions.copy()
    tx["_row_order"] = np.arange(len(tx))

    if not tx.empty:
        tx["Date"] = tx["Date"].map(
            lambda value: _to_date(value, "transaction Date")
        )
        tx["Ticker"] = tx["Ticker"].astype(str).str.strip().str.upper()
        tx["Side"] = tx["Side"].astype(str).str.strip().str.upper()

        if (tx["Date"] <= as_of).any():
            raise ValueError("Transactions must occur after As_Of_Date.")

    # Cash flows.
    cf = cash_flows.copy()

    if not cf.empty:
        cf["Date"] = cf["Date"].map(
            lambda value: _to_date(value, "cash flow Date")
        )
        cf["Flow_Type"] = (
            cf["Flow_Type"].astype(str).str.strip().str.upper()
        )

        if (cf["Date"] <= as_of).any():
            raise ValueError("Cash flows must occur after As_Of_Date.")

    required_tickers = set(positions)

    if not tx.empty:
        required_tickers.update(tx["Ticker"].tolist())

    if "CASH" in required_tickers or "" in required_tickers:
        raise ValueError("Invalid transaction ticker.")

    prices = prices[prices["Ticker"].isin(required_tickers)].copy()

    # Include opening date, price dates and event dates.
    event_dates = []

    if not tx.empty:
        event_dates.extend(tx["Date"].tolist())

    if not cf.empty:
        event_dates.extend(cf["Date"].tolist())

    future_price_dates = prices.loc[
        prices["Date"] >= as_of, "Date"
    ].tolist()

    if not future_price_dates and not event_dates:
        raise ValueError("No historical dates after the opening date.")

    end_date = max(future_price_dates + event_dates)

    dates = sorted(
        {as_of}
        | {
            date for date in prices["Date"]
            if as_of <= date <= end_date
        }
        | {
            date for date in event_dates
            if as_of <= date <= end_date
        }
    )

    # Keep both price values and the original observation dates.
    price_matrix = (
        prices.pivot(index="Date", columns="Ticker", values="Close")
        .sort_index()
        .reindex(dates)
        .ffill()
    )

    price_date_matrix = (
        prices.pivot(index="Date", columns="Ticker", values="Date")
        .sort_index()
        .reindex(dates)
        .ffill()
    )

    # Opening valuation: use last available price on or before As_Of_Date.
    for ticker, quantity in positions.items():
        opening_rows = prices.loc[
            (prices["Ticker"] == ticker)
            & (prices["Date"] <= as_of)
        ]

        if quantity > 0 and opening_rows.empty:
            raise ValueError(
                f"No opening price on or before As_Of_Date for {ticker}."
            )

        if not opening_rows.empty:
            opening_row = opening_rows.iloc[-1]
            price_matrix.loc[as_of, ticker] = float(opening_row["Close"])
            price_date_matrix.loc[as_of, ticker] = opening_row["Date"]

    # Reapply forward fill after inserting opening observations.
    price_matrix = price_matrix.ffill()
    price_date_matrix = price_date_matrix.ffill()

    cash = opening_cash
    realized_pnl = 0.0
    records = []

    for date in dates:
        external_flow = 0.0

        # Beginning-of-day deposits and withdrawals.
        if not cf.empty:
            todays_flows = cf[cf["Date"] == date]

            for _, row in todays_flows.iterrows():
                flow_type = row["Flow_Type"]
                amount = _number(row["Amount"], "cash flow Amount", 0)
                tax = _number(row["Tax"], "cash flow Tax", 0)

                if flow_type == "DEPOSIT":
                    cash += amount
                    external_flow += amount

                elif flow_type == "WITHDRAWAL":
                    cash -= amount
                    external_flow -= amount

                elif flow_type in {"DIVIDEND", "INTEREST"}:
                    cash += amount - tax

                elif flow_type in {"FEE", "TAX"}:
                    cash -= amount + tax

                elif flow_type == "OTHER":
                    raise ValueError(
                        "Flow_Type OTHER tidak memiliki arah arus kas. "
                        "Gunakan DEPOSIT, WITHDRAWAL, DIVIDEND, INTEREST, FEE, atau TAX."
                    )

                else:
                    raise ValueError(
                        f"Unsupported cash flow type: {flow_type}"
                    )

                if cash < -0.000001:
                    raise ValueError(
                        f"Insufficient cash after cash flow on {date.date()}."
                    )

        # Transactions in original workbook row order.
        if not tx.empty:
            todays_transactions = tx[tx["Date"] == date].sort_values(
                "_row_order"
            )

            for _, row in todays_transactions.iterrows():
                ticker = row["Ticker"]
                side = row["Side"]

                quantity = _number(
                    row["Quantity_Shares"], "Quantity_Shares", 0
                )
                price = _number(
                    row["Price_Per_Share"], "Price_Per_Share", 0
                )
                fees = _number(row["Fees"], "Fees", 0)
                tax = _number(row["Tax"], "Tax", 0)

                if not quantity.is_integer() or quantity <= 0:
                    raise ValueError(
                        "Transaction quantity must be a positive integer."
                    )

                if price <= 0:
                    raise ValueError("Transaction price must be positive.")

                quantity = int(quantity)
                total_cost = quantity * price + fees + tax

                if side == "BUY":
                    if cash + 0.000001 < total_cost:
                        raise ValueError(
                            f"Insufficient cash for BUY {ticker} "
                            f"on {date.date()}."
                        )

                    old_quantity = positions.get(ticker, 0)
                    old_cost = average_costs.get(ticker, 0.0)
                    new_quantity = old_quantity + quantity

                    average_costs[ticker] = (
                        old_quantity * old_cost + total_cost
                    ) / new_quantity

                    positions[ticker] = new_quantity
                    cash -= total_cost

                elif side == "SELL":
                    old_quantity = positions.get(ticker, 0)

                    if quantity > old_quantity:
                        raise ValueError(
                            f"SELL quantity exceeds holdings for {ticker} "
                            f"on {date.date()}."
                        )

                    average_cost = average_costs[ticker]
                    net_proceeds = quantity * price - fees - tax

                    realized_pnl += (
                        net_proceeds - quantity * average_cost
                    )

                    positions[ticker] = old_quantity - quantity
                    cash += net_proceeds

                    if positions[ticker] == 0:
                        average_costs[ticker] = 0.0

                else:
                    raise ValueError(f"Unsupported transaction side: {side}")

        # End-of-day valuation with stale-price protection.
        market_value = 0.0

        for ticker, quantity in positions.items():
            if quantity == 0:
                continue

            if ticker not in price_matrix.columns:
                raise ValueError(f"Missing price history for {ticker}.")

            close = price_matrix.loc[date, ticker]
            price_date = price_date_matrix.loc[date, ticker]

            if pd.isna(close) or close <= 0 or pd.isna(price_date):
                raise ValueError(
                    f"Missing valid price for held ticker {ticker} "
                    f"on {date.date()}."
                )

            age_days = (date - price_date).days

            if age_days > max_price_staleness_days:
                raise ValueError(
                    f"Stale price for {ticker} on {date.date()}: "
                    f"last available price was {price_date.date()} "
                    f"({age_days} calendar days old; maximum allowed "
                    f"{max_price_staleness_days})."
                )

            market_value += quantity * float(close)

        nav = cash + market_value

        if not np.isfinite(nav) or nav <= 0:
            raise ValueError(
                f"Portfolio NAV must be positive on {date.date()}."
            )

        records.append({
            "Date": date,
            "Cash": cash,
            "Market_Value": market_value,
            "NAV": nav,
            "External_Cash_Flow": external_flow,
            "Realized_PnL": realized_pnl,
        })

    result = pd.DataFrame(records).set_index("Date")
    result.index.name = "Date"

    return result
