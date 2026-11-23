
"""Validated Performance Metrics and NAV Reconciliation for TSFA V1.4."""

from __future__ import annotations

import numpy as np
import pandas as pd


MIN_VOLATILITY_PERIODS = 30
MIN_SHARPE_PERIODS = 30
MIN_CAGR_DAYS = 365
DEFAULT_PERIODS_PER_YEAR = 252
RECONCILIATION_TOLERANCE = 1.0


def _validate_positive_integer(name, value):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ValueError(f"{name} harus integer positif.")


def _validate_numeric_series(
    series,
    name,
    *,
    strictly_positive=False,
):
    result = pd.to_numeric(series, errors="coerce")

    if result.empty:
        raise ValueError(f"{name} tidak boleh kosong.")

    values = result.to_numpy(dtype=float)

    if not np.isfinite(values).all():
        raise ValueError(f"{name} mengandung nilai tidak valid.")

    if strictly_positive and (result <= 0).any():
        raise ValueError(f"{name} harus lebih besar dari nol.")

    return result.astype(float)


def calculate_summary(
    daily: pd.DataFrame,
    twr_result: dict,
    *,
    min_volatility_periods: int = MIN_VOLATILITY_PERIODS,
    min_sharpe_periods: int = MIN_SHARPE_PERIODS,
    min_cagr_days: int = MIN_CAGR_DAYS,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> dict:
    """Calculate validated portfolio performance metrics.

    Cash flows are assumed to occur at the beginning of each day.
    The first daily return is intentionally NaN and is excluded.
    """

    # -----------------------------------------------------
    # 1. INPUT VALIDATION
    # -----------------------------------------------------

    if (
        not isinstance(daily, pd.DataFrame)
        or daily.empty
        or "NAV" not in daily.columns
    ):
        raise ValueError(
            "daily harus berupa DataFrame non-kosong "
            "dengan kolom NAV."
        )

    if not isinstance(twr_result, dict):
        raise TypeError("twr_result harus berupa dictionary.")

    if not {
        "twr_index",
        "daily_returns",
    }.issubset(twr_result):
        raise ValueError(
            "twr_result harus memiliki twr_index "
            "dan daily_returns."
        )

    for name, value in {
        "min_volatility_periods": min_volatility_periods,
        "min_sharpe_periods": min_sharpe_periods,
        "min_cagr_days": min_cagr_days,
        "periods_per_year": periods_per_year,
    }.items():
        _validate_positive_integer(name, value)

    if not isinstance(twr_result["twr_index"], pd.Series):
        raise TypeError("twr_index harus berupa pandas Series.")

    if not isinstance(twr_result["daily_returns"], pd.Series):
        raise TypeError("daily_returns harus berupa pandas Series.")

    # -----------------------------------------------------
    # 2. DATE INDEX VALIDATION
    # -----------------------------------------------------

    if not isinstance(daily.index, pd.DatetimeIndex):
        raise TypeError("daily harus menggunakan DatetimeIndex.")

    if daily.index.has_duplicates:
        raise ValueError("Tanggal daily NAV tidak boleh duplikat.")

    if not daily.index.is_monotonic_increasing:
        raise ValueError("Tanggal daily NAV harus berurutan.")

    if not daily.index.equals(twr_result["twr_index"].index):
        raise ValueError(
            "Indeks tanggal NAV dan TWR index harus sama."
        )

    if not daily.index.equals(twr_result["daily_returns"].index):
        raise ValueError(
            "Indeks tanggal NAV dan daily returns harus sama."
        )

    # -----------------------------------------------------
    # 3. NUMERIC VALIDATION
    # -----------------------------------------------------

    nav = _validate_numeric_series(
        daily["NAV"],
        "NAV",
        strictly_positive=True,
    )

    twr_index = _validate_numeric_series(
        twr_result["twr_index"],
        "TWR index",
        strictly_positive=True,
    )

    returns_raw = pd.to_numeric(
        twr_result["daily_returns"],
        errors="coerce",
    )

    # First observation must be NaN by design.
    if not pd.isna(returns_raw.iloc[0]):
        raise ValueError(
            "Daily return observasi pertama harus NaN."
        )

    returns = returns_raw.iloc[1:]

    if returns.isna().any():
        raise ValueError(
            "Daily return setelah observasi pertama "
            "tidak boleh mengandung nilai kosong."
        )

    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        raise ValueError(
            "Daily return mengandung nilai tidak valid."
        )

    returns = returns.astype(float)

    if len(nav) < 2:
        raise ValueError(
            "Minimal diperlukan dua observasi NAV."
        )

    # -----------------------------------------------------
    # 4. TWR VALIDATION
    # -----------------------------------------------------

    expected_index = 100.0 * (
        1.0 + returns
    ).cumprod()

    expected_index = pd.concat(
        [
            pd.Series(
                [100.0],
                index=twr_index.index[:1],
            ),
            expected_index,
        ]
    )

    if not np.allclose(
        twr_index.to_numpy(dtype=float),
        expected_index.to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-9,
    ):
        raise ValueError(
            "TWR index tidak konsisten dengan daily returns."
        )

    # -----------------------------------------------------
    # 5. PERFORMANCE METRICS
    # -----------------------------------------------------

    total_return = float(
        twr_index.iloc[-1] / twr_index.iloc[0] - 1.0
    )

    elapsed_days = int(
        (
            daily.index[-1] - daily.index[0]
        ).days
    )

    elapsed_years = elapsed_days / 365.25

    # CAGR
    cagr_available = (
        elapsed_days >= min_cagr_days
        and elapsed_years > 0
    )

    cagr = (
        float(
            (
                twr_index.iloc[-1]
                / twr_index.iloc[0]
            ) ** (1.0 / elapsed_years) - 1.0
        )
        if cagr_available
        else np.nan
    )

    # Annualized volatility
    volatility_available = (
        len(returns) >= min_volatility_periods
    )

    volatility = (
        float(
            returns.std(ddof=1)
            * np.sqrt(periods_per_year)
        )
        if volatility_available
        else np.nan
    )

    # Sharpe ratio (zero risk-free rate assumption)
    sharpe_available = (
        len(returns) >= min_sharpe_periods
    )

    sharpe = np.nan

    if sharpe_available:
        daily_std = float(
            returns.std(ddof=1)
        )

        if daily_std > 0:
            sharpe = float(
                returns.mean()
                / daily_std
                * np.sqrt(periods_per_year)
            )

        sharpe_available = bool(
            np.isfinite(sharpe)
        )

    # Maximum drawdown
    drawdown = (
        twr_index / twr_index.cummax()
    ) - 1.0

    max_drawdown = float(
        drawdown.min()
    )

    # -----------------------------------------------------
    # 6. OUTPUT
    # -----------------------------------------------------

    return {
        "Ending NAV": float(nav.iloc[-1]),
        "Total TWR": total_return,
        "CAGR": cagr,
        "Annualized Volatility": volatility,
        "Sharpe Ratio": sharpe,
        "Maximum Drawdown": max_drawdown,
        "Trading Observations": int(len(nav)),
        "Return Periods": int(len(returns)),
        "Elapsed Calendar Days": elapsed_days,
        "CAGR Available": bool(cagr_available),
        "Volatility Available": bool(volatility_available),
        "Sharpe Available": bool(sharpe_available),
        "TWR Cash Flow Assumption": (
            "External cash flows are treated as "
            "beginning-of-day flows."
        ),
    }


def build_nav_reconciliation(
    daily: pd.DataFrame,
    ending_positions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build opening-to-ending NAV reconciliation."""

    required = {
        "NAV",
        "Cash",
        "Market_Value",
        "External_Cash_Flow",
    }

    if (
        not isinstance(daily, pd.DataFrame)
        or daily.empty
        or not required.issubset(daily.columns)
    ):
        raise ValueError(
            "daily tidak memiliki kolom yang diperlukan "
            "untuk rekonsiliasi NAV."
        )

    # -----------------------------------------------------
    # 1. VALIDATE DAILY VALUES
    # -----------------------------------------------------

    nav = _validate_numeric_series(
        daily["NAV"],
        "NAV",
    )

    cash = _validate_numeric_series(
        daily["Cash"],
        "Cash",
    )

    market_value = _validate_numeric_series(
        daily["Market_Value"],
        "Market_Value",
    )

    external_flows = pd.to_numeric(
        daily["External_Cash_Flow"],
        errors="coerce",
    ).fillna(0.0)

    if not np.isfinite(
        external_flows.to_numpy(dtype=float)
    ).all():
        raise ValueError(
            "External cash flow mengandung nilai tidak valid."
        )

    # -----------------------------------------------------
    # 2. NAV RECONCILIATION
    # -----------------------------------------------------

    opening_nav = float(nav.iloc[0])
    ending_nav = float(nav.iloc[-1])

    opening_cash = float(cash.iloc[0])
    ending_cash = float(cash.iloc[-1])

    opening_market_value = float(
        market_value.iloc[0]
    )

    ending_market_value = float(
        market_value.iloc[-1]
    )

    net_external_flows = float(
        external_flows.sum()
    )

    investment_pnl = (
        ending_nav
        - opening_nav
        - net_external_flows
    )

    opening_difference = (
        opening_nav
        - opening_cash
        - opening_market_value
    )

    ending_difference = (
        ending_nav
        - ending_cash
        - ending_market_value
    )

    # -----------------------------------------------------
    # 3. ENDING POSITION VALIDATION
    # -----------------------------------------------------

    positions_market_value = np.nan
    holdings_difference = np.nan

    if ending_positions is not None:

        if not isinstance(
            ending_positions,
            pd.DataFrame,
        ):
            raise TypeError(
                "ending_positions harus berupa DataFrame."
            )

        if not ending_positions.empty:

            if "Market_Value" not in ending_positions.columns:
                raise ValueError(
                    "ending_positions tidak memiliki "
                    "kolom Market_Value."
                )

            position_values = pd.to_numeric(
                ending_positions["Market_Value"],
                errors="coerce",
            ).fillna(0.0)

            if not np.isfinite(
                position_values.to_numpy(dtype=float)
            ).all():
                raise ValueError(
                    "Market_Value ending positions tidak valid."
                )

            positions_market_value = float(
                position_values.sum()
            )

            holdings_difference = (
                ending_market_value
                - positions_market_value
            )

    # -----------------------------------------------------
    # 4. RECONCILIATION REPORT
    # -----------------------------------------------------

    rows = [
        (
            "Opening NAV",
            opening_nav,
            "Opening portfolio value",
            "INFO",
        ),
        (
            "Opening Cash",
            opening_cash,
            "Opening cash balance",
            "INFO",
        ),
        (
            "Opening Equity Market Value",
            opening_market_value,
            "Opening market value of holdings",
            "INFO",
        ),
        (
            "Opening NAV Component Difference",
            opening_difference,
            "Should be zero",
            "CHECK",
        ),
        (
            "Net External Cash Flows",
            net_external_flows,
            "Deposits minus withdrawals",
            "INFO",
        ),
        (
            "Net Investment P&L (Residual)",
            investment_pnl,
            "Ending NAV minus opening NAV minus external flows",
            "INFO",
        ),
        (
            "Ending NAV",
            ending_nav,
            "Ending portfolio value",
            "INFO",
        ),
        (
            "Ending Cash",
            ending_cash,
            "Ending cash balance",
            "INFO",
        ),
        (
            "Ending Equity Market Value",
            ending_market_value,
            "Ending market value of holdings",
            "INFO",
        ),
        (
            "Ending NAV Component Difference",
            ending_difference,
            "Should be zero",
            "CHECK",
        ),
        (
            "Ending Positions Market Value",
            positions_market_value,
            "Sum of ending positions market value",
            "INFO",
        ),
        (
            "Daily NAV vs Positions Difference",
            holdings_difference,
            "Should be zero",
            "CHECK",
        ),
    ]

    result = pd.DataFrame(
        rows,
        columns=[
            "Metric",
            "Value_IDR",
            "Explanation",
            "Check_Status",
        ],
    )

    tolerance = RECONCILIATION_TOLERANCE

    checks = {
        "Opening NAV components": (
            abs(opening_difference) <= tolerance
        ),
        "Ending NAV components": (
            abs(ending_difference) <= tolerance
        ),
        "Ending positions": (
            True
            if pd.isna(holdings_difference)
            else abs(holdings_difference) <= tolerance
        ),
    }

    status_mapping = {
        "Opening NAV Component Difference": (
            checks["Opening NAV components"]
        ),
        "Ending NAV Component Difference": (
            checks["Ending NAV components"]
        ),
        "Daily NAV vs Positions Difference": (
            checks["Ending positions"]
        ),
    }

    for metric, passed in status_mapping.items():
        result.loc[
            result["Metric"] == metric,
            "Check_Status",
        ] = "PASS" if passed else "WARNING"

    result.attrs["checks"] = checks

    result.attrs["status"] = (
        "PASS"
        if all(checks.values())
        else "WARNING"
    )

    return result
