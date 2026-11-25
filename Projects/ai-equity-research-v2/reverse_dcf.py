"""Reverse DCF: solve the forecast FCF growth implied by a market price."""
from __future__ import annotations

import math


def reverse_dcf_implied_growth(
    *,
    current_fcf: float,
    market_price: float,
    diluted_shares: float,
    net_debt: float,
    wacc: float,
    terminal_growth: float,
    forecast_years: int = 5,
    lower_growth: float = -0.50,
    upper_growth: float = 1.00,
    tolerance: float = 1e-8,
) -> dict:
    values = {
        "current_fcf": current_fcf, "market_price": market_price,
        "diluted_shares": diluted_shares, "net_debt": net_debt,
        "wacc": wacc, "terminal_growth": terminal_growth,
        "lower_growth": lower_growth, "upper_growth": upper_growth,
        "tolerance": tolerance,
    }
    for name, value in values.items():
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} harus finite.")
    if current_fcf <= 0:
        raise ValueError("Current FCF harus positif untuk reverse DCF ini.")
    if market_price <= 0 or diluted_shares <= 0:
        raise ValueError("Market price dan diluted shares harus positif.")
    if wacc <= terminal_growth or wacc <= -1:
        raise ValueError("WACC harus lebih besar daripada terminal growth dan di atas -100%.")
    if forecast_years < 1 or forecast_years > 30:
        raise ValueError("Forecast years harus antara 1 dan 30.")
    if lower_growth <= -1 or upper_growth <= lower_growth:
        raise ValueError("Rentang growth tidak valid.")
    if tolerance <= 0:
        raise ValueError("Tolerance harus positif.")

    target_equity = market_price * diluted_shares
    target_enterprise = target_equity + net_debt

    def value_at_growth(growth: float) -> dict:
        projected = [current_fcf * ((1.0 + growth) ** year)
                     for year in range(1, forecast_years + 1)]
        if any(not math.isfinite(x) or x <= 0 for x in projected):
            raise ValueError("Proyeksi FCF tidak valid pada batas growth ini.")
        pv_explicit = sum(
            fcf / ((1.0 + wacc) ** year)
            for year, fcf in enumerate(projected, start=1)
        )
        terminal_fcf = projected[-1] * (1.0 + terminal_growth)
        terminal_value = terminal_fcf / (wacc - terminal_growth)
        pv_terminal = terminal_value / ((1.0 + wacc) ** forecast_years)
        enterprise = pv_explicit + pv_terminal
        equity = enterprise - net_debt
        return {
            "growth": growth, "enterprise_value": enterprise,
            "equity_value": equity, "implied_price": equity / diluted_shares,
            "pv_explicit_fcf": pv_explicit, "terminal_value": terminal_value,
            "pv_terminal_value": pv_terminal,
        }

    low_result = value_at_growth(lower_growth)
    high_result = value_at_growth(upper_growth)
    low_gap = low_result["enterprise_value"] - target_enterprise
    high_gap = high_result["enterprise_value"] - target_enterprise
    if low_gap == 0:
        solved = low_result
    elif high_gap == 0:
        solved = high_result
    elif low_gap * high_gap > 0:
        raise ValueError(
            "Market price berada di luar rentang valuasi growth yang diizinkan; "
            "perluas rentang asumsi secara eksplisit."
        )
    else:
        low, high = lower_growth, upper_growth
        solved = None
        for _ in range(300):
            mid = (low + high) / 2.0
            current = value_at_growth(mid)
            gap = current["enterprise_value"] - target_enterprise
            solved = current
            if abs(gap) <= max(1.0, abs(target_enterprise)) * tolerance or abs(high - low) <= tolerance:
                break
            if low_gap * gap <= 0:
                high = mid
            else:
                low, low_gap = mid, gap
        if solved is None:
            raise ValueError("Reverse DCF tidak konvergen.")
    return {
        "implied_fcf_growth_pct": solved["growth"] * 100.0,
        "market_price": market_price,
        "implied_price": solved["implied_price"],
        "target_equity_value": target_equity,
        "target_enterprise_value": target_enterprise,
        "enterprise_value": solved["enterprise_value"],
        "pv_explicit_fcf": solved["pv_explicit_fcf"],
        "terminal_value": solved["terminal_value"],
        "pv_terminal_value": solved["pv_terminal_value"],
        "terminal_value_share_pct": (
            solved["pv_terminal_value"] / solved["enterprise_value"] * 100.0
            if solved["enterprise_value"] else None
        ),
        "net_debt": net_debt,
        "diluted_shares": diluted_shares,
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "forecast_years": forecast_years,
        "method": "Constant explicit-period FCF growth solved by bisection; Gordon Growth terminal value.",
        "limitations": (
            "Reverse DCF is conditional on normalized current FCF, WACC, terminal growth, "
            "net debt and diluted shares. It does not establish that market expectations are correct."
        ),
    }
