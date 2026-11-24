
"""Multi-Stage FCFF DCF Engine - AI Equity Research V2."""

import math


def _number(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a valid number.")

    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite.")

    return result


def project_multistage_dcf(
    financials: dict,
    assumptions: dict,
    years: int = 5,
) -> dict:
    """
    Three-stage FCFF valuation:
    1. High growth
    2. Transition growth
    3. Stable growth
    """

    required_financials = [
        "revenue_base",
        "net_debt",
        "shares_outstanding",
        "current_price",
        "fx_rate",
    ]

    required_assumptions = [
        "high_growth",
        "transition_growth",
        "stable_growth",
        "high_growth_years",
        "transition_growth_years",
        "ebitda_margin",
        "da_pct_revenue",
        "capex_pct_revenue",
        "nwc_pct_revenue",
        "tax_rate",
        "wacc",
        "terminal_growth",
    ]

    missing = [
        key for key in required_financials
        if financials.get(key) is None
    ]

    missing += [
        key for key in required_assumptions
        if assumptions.get(key) is None
    ]

    if missing:
        return {
            "available": False,
            "reason": f"Missing inputs: {', '.join(missing)}",
        }

    try:
        revenue = _number(financials["revenue_base"], "revenue_base")
        net_debt = _number(financials["net_debt"], "net_debt")
        shares = _number(
            financials["shares_outstanding"], "shares_outstanding"
        )
        current_price = _number(
            financials["current_price"], "current_price"
        )
        fx_rate = _number(financials["fx_rate"], "fx_rate")

        high_growth = _number(
            assumptions["high_growth"], "high_growth"
        )
        transition_growth = _number(
            assumptions["transition_growth"], "transition_growth"
        )
        stable_growth = _number(
            assumptions["stable_growth"], "stable_growth"
        )
        high_years = _number(
            assumptions["high_growth_years"], "high_growth_years"
        )
        transition_years = _number(
            assumptions["transition_growth_years"],
            "transition_growth_years",
        )

        margin = _number(assumptions["ebitda_margin"], "ebitda_margin")
        da_pct = _number(assumptions["da_pct_revenue"], "da_pct_revenue")
        capex_pct = _number(
            assumptions["capex_pct_revenue"], "capex_pct_revenue"
        )
        terminal_capex_pct = capex_pct

        if assumptions.get("terminal_capex_pct_revenue") is not None:
            terminal_capex_pct = _number(
                assumptions["terminal_capex_pct_revenue"],
                "terminal_capex_pct_revenue"
            )
        nwc_pct = _number(
            assumptions["nwc_pct_revenue"], "nwc_pct_revenue"
        )
        tax_rate = _number(assumptions["tax_rate"], "tax_rate")
        wacc = _number(assumptions["wacc"], "wacc")
        terminal_growth = _number(
            assumptions["terminal_growth"], "terminal_growth"
        )

    except ValueError as exc:
        return {"available": False, "reason": str(exc)}

    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 20:
        return {
            "available": False,
            "reason": "Years must be an integer from 1 to 20.",
        }

    if high_years != int(high_years) or transition_years != int(transition_years):
        return {
            "available": False,
            "reason": "Growth stage durations must be whole numbers.",
        }

    high_years = int(high_years)
    transition_years = int(transition_years)

    if high_years < 1 or transition_years < 1:
        return {
            "available": False,
            "reason": "High and transition stages must each have at least one year.",
        }

    if high_years + transition_years > years:
        return {
            "available": False,
            "reason": "High and transition stage durations exceed forecast years.",
        }

    if revenue <= 0 or shares <= 0 or current_price <= 0 or fx_rate <= 0:
        return {
            "available": False,
            "reason": "Revenue, shares, price and FX rate must be positive.",
        }

    if not -1 < high_growth < 2:
        return {"available": False, "reason": "Invalid high growth assumption."}

    if not -1 < transition_growth < 2:
        return {"available": False, "reason": "Invalid transition growth assumption."}

    if not -1 < stable_growth < 2:
        return {"available": False, "reason": "Invalid stable growth assumption."}

    if not -1 < terminal_growth < 1:
        return {"available": False, "reason": "Invalid terminal growth assumption."}

    if not 0 < wacc <= 1 or wacc <= terminal_growth:
        return {
            "available": False,
            "reason": "WACC must be positive and higher than terminal growth.",
        }

    if not 0 <= margin <= 1 or not 0 <= da_pct <= 1:
        return {
            "available": False,
            "reason": "EBITDA margin and D&A percentage must be between 0% and 100%.",
        }

    if not 0 <= capex_pct <= 2:
        return {
            "available": False,
            "reason": "CAPEX percentage must be between 0% and 200%.",
        }
    if not 0 <= terminal_capex_pct <= 2:
        return {
            "available": False,
            "reason": "Terminal CAPEX percentage must be between 0% and 200%.",
        }

    if not -1 <= nwc_pct <= 1 or not 0 <= tax_rate <= 1:
        return {
            "available": False,
            "reason": "Invalid NWC percentage or tax rate.",
        }
    forecast = []
    pv_fcff = 0.0
    previous_revenue = revenue

    for year in range(1, years + 1):


        if year <= high_years:
            growth = high_growth
            stage = "High Growth"

        elif year <= high_years + transition_years:
            growth = transition_growth
            stage = "Transition Growth"

        else:
            growth = stable_growth
            stage = "Stable Growth"


        revenue *= 1 + growth

        ebitda = revenue * margin
        depreciation = revenue * da_pct
        ebit = ebitda - depreciation
        tax = max(ebit, 0) * tax_rate
        capex = revenue * capex_pct
        change_nwc = (revenue - previous_revenue) * nwc_pct

        fcff = ebit - tax + depreciation - capex - change_nwc

        present_value = fcff / ((1 + wacc) ** year)
        pv_fcff += present_value

        forecast.append({
            "Year": year,
            "Stage": stage,
            "Revenue Growth": growth,
            "Revenue": revenue,
            "EBITDA": ebitda,
            "EBIT": ebit,
            "Tax": tax,
            "CAPEX": capex,
            "Change NWC": change_nwc,
            "FCFF": fcff,
            "Present Value FCFF": present_value,
        })

        previous_revenue = revenue


    last_revenue = forecast[-1]["Revenue"]

    terminal_revenue = last_revenue * (1 + terminal_growth)

    terminal_ebitda = terminal_revenue * margin
    terminal_da = terminal_revenue * da_pct

    terminal_ebit = terminal_ebitda - terminal_da
    terminal_tax = max(terminal_ebit, 0) * tax_rate

    terminal_capex = terminal_revenue * terminal_capex_pct

    terminal_change_nwc = (
        terminal_revenue - last_revenue
    ) * nwc_pct

    terminal_fcff = (
        terminal_ebit
        - terminal_tax
        + terminal_da
        - terminal_capex
        - terminal_change_nwc
    )

    if terminal_fcff <= 0:
        return {
            "available": False,
            "reason": "Terminal FCFF is not positive.",
            "forecast": forecast,
            "pv_fcff": pv_fcff,
        }

    terminal_value = (
        terminal_fcff / (wacc - terminal_growth)
    )


    pv_terminal = terminal_value / ((1 + wacc) ** years)

    enterprise_value = pv_fcff + pv_terminal
    equity_value = enterprise_value - net_debt

    if equity_value <= 0:
        return {
            "available": False,
            "reason": "Equity value is not positive.",
            "forecast": forecast,
            "pv_fcff": pv_fcff,
            "terminal_value": terminal_value,
            "enterprise_value": enterprise_value,
            "equity_value": equity_value,
        }

    intrinsic_financial = equity_value / shares
    intrinsic_quote = intrinsic_financial * fx_rate

    upside = ((intrinsic_quote / current_price) - 1) * 100
    terminal_value_share_pct = (
        pv_terminal / enterprise_value * 100 if enterprise_value > 0 else None
    )
    model_warnings = []
    if terminal_value_share_pct is not None and terminal_value_share_pct > 75:
        model_warnings.append(
            "PV terminal value exceeds 75% of enterprise value; valuation is highly sensitive to terminal assumptions."
        )
    if terminal_capex_pct < capex_pct * 0.5:
        model_warnings.append(
            "Terminal CAPEX intensity is less than half of forecast CAPEX intensity; justify the long-run reinvestment assumption."
        )

    return {
        "available": True,
        "forecast": forecast,
        "pv_fcff": pv_fcff,
        "terminal_fcff": terminal_fcff,
        "terminal_value": terminal_value,
        "pv_terminal": pv_terminal,
        "terminal_value_share_pct": terminal_value_share_pct,
        "model_warnings": model_warnings,
        "enterprise_value": enterprise_value,
        "net_debt": net_debt,
        "equity_value": equity_value,
        "intrinsic_value_financial_currency": intrinsic_financial,
        "intrinsic_value_per_share": intrinsic_quote,
        "current_price": current_price,
        "upside_downside_pct": upside,
        "financial_currency": financials.get("financial_currency", "Unknown"),
        "quote_currency": financials.get("quote_currency", "Unknown"),
        "assumptions": assumptions,
        "warning": (
            "Multi-Stage DCF is assumption-driven. Verify financial data, "
            "capital structure, and growth assumptions independently. "
            "Not investment advice."
        ),
    }
