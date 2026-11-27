"""Bank fundamental validation and provenance controls.

Officially sourced inputs remain analyst-entered until a filing connector exists.
No provider field is promoted to VERIFIED merely because it is populated.
"""
from __future__ import annotations

import math
from datetime import date
from urllib.parse import urlsplit


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

    official_roe = _num((manual_metrics or {}).get("Official reported ROE (%)"))
    entered["Official reported ROE (%)"] = None
    if official_roe is not None:
        if 0 <= official_roe <= 200:
            entered["Official reported ROE (%)"] = official_roe
        else:
            checks.append({
                "Check": "Official reported ROE (%)",
                "Value": official_roe,
                "Status": "INVALID",
                "Detail": "Expected a value between 0 and 200 percent.",
            })

    source_url_value = str(source_url or "").strip()
    parsed_url = urlsplit(source_url_value)
    source_url_ok = bool(
        parsed_url.scheme.lower() == "https"
        and parsed_url.hostname
        and not parsed_url.username
        and not parsed_url.password
    )

    # The filing period must be a real ISO date and must match the periods
    # from which the app obtained the bank's balance sheet and income statement.
    source_period_value = str(source_period or "").strip()
    try:
        source_period_date = date.fromisoformat(source_period_value)
    except (TypeError, ValueError):
        source_period_date = None

    def _period_date(value):
        if value is None:
            return None
        try:
            return date.fromisoformat(str(value).strip()[:10])
        except (TypeError, ValueError):
            return None

    balance_period = _period_date(data.get("latest_balance_period"))
    financial_period = _period_date(data.get("latest_financial_period"))
    period_matches = bool(
        source_period_date
        and balance_period
        and financial_period
        and source_period_date == balance_period == financial_period
    )
    price_period = _period_date(data.get("latest_price_date"))
    fundamental_period = max(
        (period for period in (balance_period, financial_period) if period),
        default=None,
    )
    price_fundamental_gap_days = (
        abs((price_period - fundamental_period).days)
        if price_period and fundamental_period else None
    )
    if price_fundamental_gap_days is not None:
        checks.append({
            "Check": "Market price vs fundamental reporting-period gap",
            "Value": price_fundamental_gap_days,
            "Status": "REVIEW REQUIRED" if price_fundamental_gap_days > 150 else "PASS",
            "Detail": (
                f"Price date={price_period.isoformat()}; "
                f"latest balance/income period={fundamental_period.isoformat()}; "
                "gap is measured in calendar days. More than 150 days requires review."
            ),
        })

    if source_period_value:
        checks.append({
            "Check": "Official filing period vs financial statement periods",
            "Value": source_period_value,
            "Status": "PASS" if period_matches else "REVIEW REQUIRED",
            "Detail": (
                f"Source={source_period_value}; "
                f"balance={balance_period.isoformat() if balance_period else 'unavailable'}; "
                f"income={financial_period.isoformat() if financial_period else 'unavailable'}."
            ),
        })

    source_ok = bool(
        str(source_name or "").strip()
        and source_period_date
        and period_matches
        and source_url_ok
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
        notes.append("To mark VERIFIED, provide a valid HTTPS filing URL, source name, an ISO reporting date matching both app financial statement periods, and confirm that you personally checked the filing.")
    if source_period_value and not period_matches:
        notes.append("The analyst filing period does not match both the balance-sheet and income-statement periods used by the model; VERIFIED is blocked.")
    if price_fundamental_gap_days is not None and price_fundamental_gap_days > 150:
        notes.append(
            f"Fundamental data is stale relative to market price: "
            f"{price_fundamental_gap_days} calendar days between price date and "
            "latest balance-sheet/income-statement period. Refresh financial statements before relying on valuation."
        )
    if source_url_value and not source_url_ok:
        notes.append("The filing URL must be a valid HTTPS URL without embedded credentials.")
    if failed_checks:
        notes.append("At least one consistency check requires review; VERIFIED status is blocked.")
    if not all_ratios:
        notes.append("NPL gross, CAR, LDR and NIM must all be supplied from the same official reporting period.")
    if average_equity is None:
        notes.append("Average equity unavailable; closing-equity ROE is only a proxy.")
    if source_ok:
        notes.append("Source/period entered by analyst; verify the cited filing before treating inputs as authoritative.")

    freshness_status = (
        "STALE" if price_fundamental_gap_days is not None and price_fundamental_gap_days > 150
        else "CURRENT" if price_fundamental_gap_days is not None
        else "UNKNOWN"
    )

    return {
        "status": status,
        "checks": checks,
        "fundamental_freshness_status": freshness_status,
        "price_fundamental_gap_days": price_fundamental_gap_days,
        "metrics": entered,
        "source_name": str(source_name or "").strip() or None,
        "source_period": str(source_period or "").strip() or None,
        "source_url": source_url_value or None,
        "source_confirmed": bool(source_confirmed),
        "source_period_matches_financials": period_matches,
        "source_url_valid_https": source_url_ok,
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
