"""Scenario-based DCF engine for AI Equity Research V2.

Financial inputs use the same financial currency.
Per-share values are converted to quote currency using fx_rate.
"""

import math


def _to_float(value, field_name):
    """Convert a value to a finite float or raise a clear error."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")

    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite.")

    return number


def project_scenario(financials: dict, assumptions: dict, years: int = 5) -> dict:
    # revenue_base is preferred; revenue_ttm remains supported for old UI code.
    revenue_input = financials.get("revenue_base")
    if revenue_input is None:
        revenue_input = financials.get("revenue_ttm")

    required = {
        "revenue_base": revenue_input,
        "net_debt": financials.get("net_debt"),
        "shares_outstanding": financials.get("shares_outstanding"),
        "current_price": financials.get("current_price"),
        "fx_rate": financials.get("fx_rate"),
    }

    missing = [key for key, value in required.items() if value is None]
    if missing:
        return {
            "available": False,
            "reason": f"Financial data missing: {', '.join(missing)}",
        }

    required_assumptions = [
        "revenue_growth",
        "ebitda_margin",
        "da_pct_revenue",
        "capex_pct_revenue",
        "nwc_pct_revenue",
        "tax_rate",
        "wacc",
        "terminal_growth",
    ]

    missing = [
        key for key in required_assumptions
        if assumptions.get(key) is None
    ]
    if missing:
        return {
            "available": False,
            "reason": f"Assumptions missing: {', '.join(missing)}",
        }

    try:
        revenue = _to_float(revenue_input, "revenue_base")
        net_debt = _to_float(required["net_debt"], "net_debt")
        shares = _to_float(required["shares_outstanding"], "shares_outstanding")
        current_price = _to_float(required["current_price"], "current_price")
        fx_rate = _to_float(required["fx_rate"], "fx_rate")

        growth = _to_float(assumptions["revenue_growth"], "revenue_growth")
        margin = _to_float(assumptions["ebitda_margin"], "ebitda_margin")
        da_pct = _to_float(assumptions["da_pct_revenue"], "da_pct_revenue")
        capex_pct = _to_float(assumptions["capex_pct_revenue"], "capex_pct_revenue")
        nwc_pct = _to_float(assumptions["nwc_pct_revenue"], "nwc_pct_revenue")
        tax_rate = _to_float(assumptions["tax_rate"], "tax_rate")
        wacc = _to_float(assumptions["wacc"], "wacc")
        terminal_growth = _to_float(
            assumptions["terminal_growth"], "terminal_growth"
        )
    except ValueError as exc:
        return {"available": False, "reason": str(exc)}

    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 20:
        return {"available": False, "reason": "Years must be an integer from 1 to 20."}

    if revenue <= 0 or shares <= 0 or current_price <= 0 or fx_rate <= 0:
        return {"available": False, "reason": "Revenue, shares, price and FX rate must be positive."}

    if growth < -1:
        return {"available": False, "reason": "Revenue growth cannot be below -100%."}

    if not -1 <= margin <= 1:
        return {"available": False, "reason": "EBITDA margin must be between -100% and 100%."}

    if not 0 <= da_pct <= 1:
        return {"available": False, "reason": "D&A percentage must be between 0% and 100%."}

    if not 0 <= capex_pct <= 2:
        return {"available": False, "reason": "CAPEX percentage must be between 0% and 200%."}

    if not -1 <= nwc_pct <= 1:
        return {"available": False, "reason": "NWC percentage must be between -100% and 100%."}

    if not 0 <= tax_rate <= 1:
        return {"available": False, "reason": "Tax rate must be between 0% and 100%."}

    if not 0 < wacc <= 1:
        return {"available": False, "reason": "WACC must be greater than 0% and no more than 100%."}

    if not -1 < terminal_growth < 1:
        return {"available": False, "reason": "Terminal growth must be between -100% and 100%."}

    if wacc <= terminal_growth:
        return {
            "available": False,
            "reason": "WACC must be higher than terminal growth.",
        }

    forecast = []
    previous_revenue = revenue
    pv_fcff = 0.0

    for year in range(1, years + 1):
        revenue *= 1 + growth
        ebitda = revenue * margin
        depreciation = revenue * da_pct
        ebit = ebitda - depreciation
        tax = max(ebit, 0) * tax_rate
        capex = revenue * capex_pct
        change_nwc = (revenue - previous_revenue) * nwc_pct

        fcff = ebit - tax + depreciation - capex - change_nwc
        pv = fcff / ((1 + wacc) ** year)
        pv_fcff += pv

        year_values = (
            revenue, ebitda, depreciation, ebit, tax, capex,
            change_nwc, fcff, pv, pv_fcff,
        )
        if not all(math.isfinite(value) for value in year_values):
            return {
                "available": False,
                "reason": f"Numerical overflow detected in forecast year {year}; review revenue and scenario assumptions.",
                "forecast": forecast,
            }

        forecast.append({
            "year": year,
            "revenue": revenue,
            "ebitda": ebitda,
            "depreciation": depreciation,
            "ebit": ebit,
            "tax": tax,
            "capex": capex,
            "change_nwc": change_nwc,
            "fcff": fcff,
            "present_value": pv,
        })

        previous_revenue = revenue

    terminal_fcff = forecast[-1]["fcff"]

    if terminal_fcff <= 0:
        return {
            "available": False,
            "reason": (
                f"Year {years} FCFF is not positive; "
                "terminal DCF is not reliable under these assumptions."
            ),
            "forecast": forecast,
            "pv_fcff": pv_fcff,
            "terminal_fcff": terminal_fcff,
        }

    terminal_value = (
        terminal_fcff * (1 + terminal_growth)
        / (wacc - terminal_growth)
    )
    pv_terminal = terminal_value / ((1 + wacc) ** years)

    enterprise_value = pv_fcff + pv_terminal
    equity_value = enterprise_value - net_debt
    if not all(math.isfinite(value) for value in (
        terminal_value, pv_terminal, enterprise_value, equity_value
    )):
        return {
            "available": False,
            "reason": "Numerical overflow detected in terminal or equity valuation.",
            "forecast": forecast,
        }
    terminal_value_share_pct = (
        pv_terminal / enterprise_value * 100 if enterprise_value > 0 else None
    )
    model_warnings = []
    if terminal_value_share_pct is not None and terminal_value_share_pct > 75:
        model_warnings.append(
            f"PV terminal value represents {terminal_value_share_pct:.1f}% of Enterprise Value; "
            "valuation is highly sensitive to terminal assumptions."
        )
    if any(item["fcff"] < 0 for item in forecast):
        model_warnings.append(
            "One or more forecast years have negative FCFF; review operating margin, CAPEX and working-capital assumptions."
        )

    if equity_value <= 0:
        return {
            "available": False,
            "reason": (
                "Enterprise Value belum cukup menutup net debt. "
                "Equity Value tidak positif."
            ),
            "forecast": forecast,
            "pv_fcff": pv_fcff,
            "terminal_value": terminal_value,
            "pv_terminal": pv_terminal,
            "enterprise_value": enterprise_value,
            "net_debt": net_debt,
            "equity_value": equity_value,
        }

    intrinsic_financial = equity_value / shares
    intrinsic_quote = intrinsic_financial * fx_rate
    upside_pct = ((intrinsic_quote / current_price) - 1) * 100

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
        "upside_downside_pct": upside_pct,
        "currency": financials.get("quote_currency", "IDR"),
        "financial_currency": financials.get("financial_currency", "Unknown"),
        "assumptions": assumptions,
        "warning": (
            "Scenario valuation is assumption-driven, not a guaranteed "
            "share price forecast. Verify financial data and assumptions "
            "against official company reports."
        ),
    }


def run_scenarios(financials: dict, scenarios: dict, years: int = 5) -> dict:
    results = {}

    for name, assumptions in scenarios.items():
        results[name] = project_scenario(
            financials=financials,
            assumptions=assumptions,
            years=years,
        )

    return {
        "ticker": financials.get("ticker", "Unknown"),
        "years": years,
        "scenarios": results,
    }


def scenario_sensitivity(
    financials: dict,
    assumptions: dict,
    wacc_values=None,
    terminal_growth_values=None,
    years: int = 5,
) -> dict:
    """Calculate DCF sensitivity across WACC and terminal growth."""

    if wacc_values is None:
        wacc_values = [0.09, 0.10, 0.11, 0.12, 0.13]

    if terminal_growth_values is None:
        terminal_growth_values = [0.02, 0.025, 0.03]

    results = []

    for wacc in wacc_values:
        row = {
            "wacc": wacc,
            "values": [],
        }

        for terminal_growth in terminal_growth_values:
            test_assumptions = assumptions.copy()
            test_assumptions["wacc"] = wacc
            test_assumptions["terminal_growth"] = terminal_growth

            result = project_scenario(
                financials=financials,
                assumptions=test_assumptions,
                years=years,
            )

            if result.get("available"):
                cell = {
                    "available": True,
                    "value_per_share": result["intrinsic_value_per_share"],
                    "equity_value": result["equity_value"],
                    "reason": None,
                }
            else:
                cell = {
                    "available": False,
                    "value_per_share": None,
                    "equity_value": result.get("equity_value"),
                    "reason": result.get("reason"),
                }

            row["values"].append(cell)

        results.append(row)

    return {
        "available": True,
        "ticker": financials.get("ticker", "Unknown"),
        "currency": financials.get("quote_currency", "IDR"),
        "terminal_growth_values": terminal_growth_values,
        "sensitivity": results,
        "note": (
            "N/M berarti valuasi per saham tidak tersedia, "
            "misalnya karena FCFF terminal tidak positif atau "
            "Equity Value tidak positif."
        ),
    }

def operating_scenario_sensitivity(
    financials: dict,
    assumptions: dict,
    revenue_growth_values=None,
    ebitda_margin_values=None,
    years: int = 5,
    *,
    max_cells: int = 100,
) -> dict:
    """Stress intrinsic value across revenue growth and EBITDA margin.

    Every cell re-runs the full scenario DCF. Invalid or unavailable cells are
    retained with a reason instead of being silently dropped.
    """
    base_growth = _to_float(assumptions.get("revenue_growth"), "revenue_growth")
    base_margin = _to_float(assumptions.get("ebitda_margin"), "ebitda_margin")
    if revenue_growth_values is None:
        revenue_growth_values = [base_growth + delta for delta in (-0.05, -0.025, 0.0, 0.025, 0.05)]
    if ebitda_margin_values is None:
        ebitda_margin_values = [base_margin + delta for delta in (-0.05, -0.025, 0.0, 0.025, 0.05)]

    def _validated_axis(values, field):
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{field} must be a non-empty numeric sequence.")
        try:
            axis = [_to_float(value, field) for value in values]
        except TypeError as exc:
            raise ValueError(f"{field} must be a non-empty numeric sequence.") from exc
        if not axis:
            raise ValueError(f"{field} must not be empty.")
        if len(axis) != len(set(axis)):
            raise ValueError(f"{field} must not contain duplicate values.")
        return axis

    growth_axis = _validated_axis(revenue_growth_values, "revenue_growth_values")
    margin_axis = _validated_axis(ebitda_margin_values, "ebitda_margin_values")
    if len(growth_axis) * len(margin_axis) > int(max_cells):
        raise ValueError(f"Sensitivity grid exceeds the {int(max_cells)}-cell safety limit.")
    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 20:
        raise ValueError("Years must be an integer from 1 to 20.")

    rows = []
    for margin in margin_axis:
        cells = []
        for growth in growth_axis:
            test_assumptions = dict(assumptions)
            test_assumptions["revenue_growth"] = growth
            test_assumptions["ebitda_margin"] = margin
            result = project_scenario(financials, test_assumptions, years=years)
            cells.append({
                "available": bool(result.get("available")),
                "revenue_growth": growth,
                "ebitda_margin": margin,
                "value_per_share": result.get("intrinsic_value_per_share"),
                "equity_value": result.get("equity_value"),
                "upside_downside_pct": result.get("upside_downside_pct"),
                "reason": result.get("reason"),
            })
        rows.append({"ebitda_margin": margin, "values": cells})

    return {
        "available": True,
        "ticker": financials.get("ticker", "Unknown"),
        "currency": financials.get("quote_currency", "IDR"),
        "revenue_growth_values": growth_axis,
        "ebitda_margin_values": margin_axis,
        "sensitivity": rows,
        "base_revenue_growth": base_growth,
        "base_ebitda_margin": base_margin,
        "years": years,
        "note": (
            "Each cell recalculates the full FCFF scenario DCF. N/M means the "
            "assumptions did not produce a valid positive terminal FCFF and equity value."
        ),
    }
