"""Bank fundamental validation and provenance controls.

Officially sourced inputs remain analyst-entered until a filing connector exists.
No provider field is promoted to VERIFIED merely because it is populated.
"""
from __future__ import annotations

import math


BANK_RATIO_FIELDS = ("NPL gross (%)", "CAR (%)", "LDR (%)", "NIM (%)")


def _num(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def assess_bank_data(data: dict, manual_metrics: dict | None = None,
                     source_name: str | None = None,
                     source_period: str | None = None,
                     source_url: str | None = None,
                     source_confirmed: bool = False) -> dict:
    ratios = data.get("ratios") or {}
    equity = _num(ratios.get("Total stockholders equity"))
    net_income = _num(ratios.get("Net income attributable to parent"))
    shares = _num(ratios.get("Shares outstanding"))
    price = _num(data.get("price"))
    average_equity = _num(ratios.get("Average stockholders equity"))
    reported_roe = _num(ratios.get("ROE (%)"))

    checks = []
    missing = []
    if equity is None or equity <= 0:
        missing.append("Total stockholders equity")
    if net_income is None:
        missing.append("Net income attributable to parent")
    if shares is None or shares <= 0:
        missing.append("Shares outstanding")
    if price is None or price <= 0:
        missing.append("Latest market price")

    if equity is not None and equity > 0 and net_income is not None:
        if average_equity is not None and average_equity > 0:
            calculated_roe = net_income / average_equity * 100
            roe_basis = "Net income attributable to parent / average equity"
        else:
            calculated_roe = net_income / equity * 100
            roe_basis = "Net income attributable to parent / closing equity proxy"
        checks.append({
            "Check": "ROE cross-check",
            "Value": calculated_roe,
            "Status": "REVIEW REQUIRED" if average_equity is None else "CALCULATED",
            "Detail": roe_basis,
        })
        if reported_roe is not None:
            difference = abs(calculated_roe - reported_roe)
            checks.append({
                "Check": "Provider ROE vs calculated ROE",
                "Value": difference,
                "Status": "PASS" if difference <= 2.0 else "REVIEW REQUIRED",
                "Detail": "Difference in percentage points; investigate period and equity basis.",
            })

    if equity is not None and shares is not None and shares > 0:
        bvps = equity / shares
        checks.append({
            "Check": "Book value per share",
            "Value": bvps,
            "Status": "CALCULATED",
            "Detail": "Provider-reported total equity divided by shares; verify parent-attributable equity and diluted shares.",
        })

    if price is not None and shares is not None and shares > 0:
        market_cap_proxy = price * shares
        provider_market_cap = _num(ratios.get("Market capitalization"))
        if provider_market_cap and provider_market_cap > 0:
            delta_pct = abs(market_cap_proxy / provider_market_cap - 1) * 100
            checks.append({
                "Check": "Price × shares vs market capitalization",
                "Value": delta_pct,
                "Status": "PASS" if delta_pct <= 5 else "REVIEW REQUIRED",
                "Detail": "Relative difference in percent; corporate actions and share classes may explain variance.",
            })

    entered = {}
    for field in BANK_RATIO_FIELDS:
        raw = (manual_metrics or {}).get(field)
        value = _num(raw)
        entered[field] = None
        if value is not None:
            upper = 1000 if field == "LDR (%)" else 100
            if 0 <= value <= upper:
                entered[field] = value
            else:
                checks.append({
                    "Check": field, "Value": value,
                    "Status": "INVALID",
                    "Detail": f"Expected a value between 0 and {upper}.",
                })

    source_url_value = str(source_url or "").strip()
    source_ok = bool(
        str(source_name or "").strip()
        and str(source_period or "").strip()
        and source_url_value.startswith("https://")
        and source_confirmed is True
    )
    all_ratios = all(entered.get(field) is not None for field in BANK_RATIO_FIELDS)
    core_ok = not missing and equity is not None and equity > 0
    failed_checks = any(
        row.get("Status") in {"REVIEW REQUIRED", "INVALID"}
        for row in checks
    )
    if not core_ok:
        status = "INSUFFICIENT DATA"
    elif source_ok and all_ratios and average_equity is not None and average_equity > 0 and not failed_checks:
        status = "VERIFIED"
    else:
        status = "REVIEW REQUIRED"

    notes = []
    if missing:
        notes.append("Missing required fields: " + ", ".join(missing))
    if not source_ok:
        notes.append("To mark VERIFIED, provide an HTTPS official filing URL, source name, reporting period and confirm that you personally checked the filing.")
    if failed_checks:
        notes.append("At least one consistency check requires review; VERIFIED status is blocked.")
    if not all_ratios:
        notes.append("NPL gross, CAR, LDR and NIM must all be supplied from the same official reporting period.")
    if average_equity is None:
        notes.append("Average equity unavailable; closing-equity ROE is only a proxy.")
    if source_ok:
        notes.append("Source/period entered by analyst; verify the cited filing before treating inputs as authoritative.")

    return {
        "status": status,
        "checks": checks,
        "metrics": entered,
        "source_name": str(source_name or "").strip() or None,
        "source_period": str(source_period or "").strip() or None,
        "source_url": source_url_value or None,
        "source_confirmed": bool(source_confirmed),
        "notes": notes,
        "missing_fields": missing,
        "calculated_roe_pct": (
            net_income / average_equity * 100
            if net_income is not None and average_equity is not None and average_equity > 0
            else net_income / equity * 100
            if net_income is not None and equity is not None and equity > 0
            else None
        ),
        "roe_basis": (
            "Average equity"
            if average_equity is not None and average_equity > 0
            else "Closing equity proxy"
        ),
    }
