
"""
TSFA V1.4 - Portfolio Rebalancing Engine

Features:
- First trading day monthly rebalancing
- Last trading day monthly rebalancing
- Daily portfolio valuation
- Portfolio weight drift
- Transaction cost
- Slippage
- Turnover tracking
- Performance metrics integration
"""

import numpy as np
import pandas as pd

from tsfa_backtest_engine import calculate_performance_metrics


VALID_SCHEDULES = (
    "first_trading_day",
    "last_trading_day",
)


def run_rebalanced_backtest(
    price_data,
    target_weights,
    initial_capital=100_000_000,
    rebalancing="first_trading_day",
    transaction_cost=0.0015,
    slippage=0.0005,
    risk_free_rate=0.0,
    periods_per_year=252,
):
    """
    Run a long-only portfolio backtest with monthly rebalancing.

    Rebalancing:
        first_trading_day:
            First available trading day of each month.

        last_trading_day:
            Last available trading day of each month.

    Costs:
        Transaction cost and slippage are deducted from equity.

    Accounting:
        Equity curve starts with gross initial capital at a
        synthetic pre-investment date (one calendar day before
        the first available trading date).

        Initial investment costs are reflected on the first
        trading date, so investor returns include these costs.

    Execution assumption:
        Rebalancing takes place at closing prices.
    """

    # --------------------------------------------------
    # 1. Validate input
    # --------------------------------------------------

    if not isinstance(price_data, pd.DataFrame):
        raise TypeError("price_data harus berupa pandas DataFrame.")

    if price_data.empty:
        raise ValueError("price_data tidak boleh kosong.")

    if not isinstance(price_data.index, pd.DatetimeIndex):
        raise TypeError("Index harga harus berupa DatetimeIndex.")

    if price_data.index.has_duplicates:
        raise ValueError("Tanggal harga tidak boleh duplikat.")

    if len(price_data) < 2:
        raise ValueError("Minimal diperlukan dua tanggal harga.")

    if price_data.columns.has_duplicates:
        raise ValueError("Nama aset tidak boleh duplikat.")

    if not np.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial_capital harus lebih besar dari nol.")

    if rebalancing not in VALID_SCHEDULES:
        raise ValueError(
            "rebalancing harus first_trading_day "
            "atau last_trading_day."
        )

    for name, value in [
        ("transaction_cost", transaction_cost),
        ("slippage", slippage),
    ]:
        if (
            not np.isfinite(value)
            or value < 0
            or value >= 1
        ):
            raise ValueError(
                f"{name} harus berada di antara 0 dan 1."
            )

    total_cost_rate = transaction_cost + slippage

    if total_cost_rate >= 1:
        raise ValueError("Total biaya harus lebih kecil dari 100%.")

    # --------------------------------------------------
    # 2. Validate and prepare prices
    # --------------------------------------------------

    prices = price_data.copy().sort_index()

    prices = prices.apply(pd.to_numeric, errors="coerce")
    prices = prices.replace([np.inf, -np.inf], np.nan)

    if prices.isna().any().any():
        raise ValueError("Harga mengandung nilai kosong atau invalid.")

    if (prices <= 0).any().any():
        raise ValueError("Semua harga harus lebih besar dari nol.")

    # --------------------------------------------------
    # 3. Validate target weights
    # --------------------------------------------------

    weights = pd.Series(target_weights, dtype=float)

    if weights.empty:
        raise ValueError("target_weights tidak boleh kosong.")

    if weights.index.has_duplicates:
        raise ValueError("Nama aset pada weights tidak boleh duplikat.")

    if set(weights.index) != set(prices.columns):
        raise ValueError(
            "Aset pada weights harus sama dengan kolom harga."
        )

    weights = weights.reindex(prices.columns)

    if not np.isfinite(weights.to_numpy()).all():
        raise ValueError("Bobot harus berupa angka finite.")

    if (weights < 0).any():
        raise ValueError("Short selling belum didukung.")

    if not np.isclose(weights.sum(), 1.0, atol=1e-8):
        raise ValueError("Total bobot harus sama dengan 1.")

    target = weights.to_numpy(dtype=float)

    # --------------------------------------------------
    # 4. Determine monthly rebalancing dates
    # --------------------------------------------------

    monthly_groups = prices.groupby(
        prices.index.to_period("M")
    )

    if rebalancing == "first_trading_day":
        rebalance_dates = set(
            monthly_groups.head(1).index
        )
    else:
        rebalance_dates = set(
            monthly_groups.tail(1).index
        )

    # Initial allocation already uses target weights.
    rebalance_dates.discard(prices.index[0])

    # --------------------------------------------------
    # 5. Initialize portfolio
    # --------------------------------------------------

    initial_cost = initial_capital * transaction_cost
    initial_slippage = initial_capital * slippage

    initial_total_cost = initial_cost + initial_slippage

    equity = initial_capital - initial_total_cost

    if equity <= 0:
        raise ValueError(
            "Modal awal setelah biaya investasi harus positif."
        )

    current_weights = target.copy()

    # Gross capital baseline before initial investment.
    baseline_date = prices.index[0] - pd.Timedelta(days=1)

    equity_records = [
        float(initial_capital),
        float(equity),
    ]

    equity_dates = prices.index.insert(
        0,
        baseline_date,
    )

    # Weight history remains aligned with actual trading dates.
    weight_records = [
        current_weights.copy()
    ]

    transaction_records = [{
        "Date": prices.index[0],
        "Event": "Initial Investment",
        "Turnover": 1.0,
        "Transaction_Cost": float(initial_cost),
        "Slippage_Cost": float(initial_slippage),
        "Total_Cost": float(initial_total_cost),
    }]

    # --------------------------------------------------
    # 6. Daily simulation
    # --------------------------------------------------

    daily_returns = prices.pct_change(
        fill_method=None
    )

    for i in range(1, len(prices)):

        date = prices.index[i]

        asset_returns = daily_returns.iloc[i].to_numpy(
            dtype=float
        )

        previous_equity = equity

        # Portfolio return before rebalancing costs.
        portfolio_return = float(
            np.dot(current_weights, asset_returns)
        )

        if (
            not np.isfinite(portfolio_return)
            or portfolio_return <= -1
        ):
            raise ValueError(
                f"Return portofolio tidak valid pada {date}."
            )

        pre_trade_equity = previous_equity * (
            1 + portfolio_return
        )

        # Calculate natural weight drift.
        drifted_weights = (
            current_weights * (1 + asset_returns)
        ) / (1 + portfolio_return)

        # --------------------------------------------------
        # 7. Monthly rebalancing
        # --------------------------------------------------

        if date in rebalance_dates:

            turnover = 0.5 * np.abs(
                target - drifted_weights
            ).sum()

            traded_value = pre_trade_equity * turnover

            transaction_fee = (
                traded_value * transaction_cost
            )

            slippage_fee = (
                traded_value * slippage
            )

            total_fee = transaction_fee + slippage_fee

            equity = pre_trade_equity - total_fee

            current_weights = target.copy()

            transaction_records.append({
                "Date": date,
                "Event": "Monthly Rebalancing",
                "Turnover": float(turnover),
                "Transaction_Cost": float(transaction_fee),
                "Slippage_Cost": float(slippage_fee),
                "Total_Cost": float(total_fee),
            })

        else:
            equity = pre_trade_equity
            current_weights = drifted_weights

        if not np.isfinite(equity) or equity <= 0:
            raise ValueError(
                f"Nilai portofolio tidak valid pada {date}."
            )

        equity_records.append(float(equity))
        weight_records.append(current_weights.copy())

    # --------------------------------------------------
    # 8. Build output
    # --------------------------------------------------

    equity_curve = pd.Series(
        equity_records,
        index=equity_dates,
        name="Portfolio_Value",
    )

    weights_history = pd.DataFrame(
        weight_records,
        index=prices.index,
        columns=prices.columns,
    )

    transactions = pd.DataFrame(transaction_records)

    portfolio_returns = equity_curve.pct_change(
        fill_method=None
    ).rename("Portfolio_Return")

    metrics = calculate_performance_metrics(
        equity_curve,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
    )

    total_transaction_cost = float(
        transactions["Transaction_Cost"].sum()
    )

    total_slippage_cost = float(
        transactions["Slippage_Cost"].sum()
    )

    total_cost = (
        total_transaction_cost + total_slippage_cost
    )

    return {
        "equity_curve": equity_curve,
        "portfolio_returns": portfolio_returns,
        "weights_history": weights_history,
        "transactions": transactions,
        "metrics": metrics,
        "summary": {
            "rebalancing": rebalancing,
            "initial_capital": float(initial_capital),
            "final_value": float(equity_curve.iloc[-1]),
            "total_transaction_cost": total_transaction_cost,
            "total_slippage_cost": total_slippage_cost,
            "total_cost": total_cost,
            "rebalancing_count": int(
                (
                    transactions["Event"]
                    == "Monthly Rebalancing"
                ).sum()
            ),
            "transaction_count": int(len(transactions)),
            "baseline_date": baseline_date,
            "first_trading_date": prices.index[0],
        },
    }
