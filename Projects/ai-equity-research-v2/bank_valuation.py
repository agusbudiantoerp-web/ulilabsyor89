"""Bank-specific equity valuation using the residual income method.

This model is intentionally separate from FCFF/FCFE DCF. It uses reported
common book equity per share and an explicit forecast ROE, cost of equity,
and long-run book-value growth assumption. It is decision support, not advice.
"""
from __future__ import annotations

import math
import pandas as pd

from bank_data_quality import assess_bank_data


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _rim_value(book_value_per_share, expected_roe, cost_of_equity, growth, years):
    book_value = book_value_per_share
    present_value_residual_income = 0.0
    forecast = []

    for year in range(1, years + 1):
        opening_book_value = book_value
        residual_income = (expected_roe - cost_of_equity) * opening_book_value
        present_value = residual_income / ((1 + cost_of_equity) ** year)
        present_value_residual_income += present_value
        forecast.append({
            "Year": year,
            "Opening book value / share": opening_book_value,
            "Forecast ROE": expected_roe,
            "Cost of equity": cost_of_equity,
            "Residual income / share": residual_income,
            "Present value of residual income": present_value,
        })
        book_value *= (1 + growth)

    terminal_residual_income = (
        forecast[-1]["Residual income / share"] * (1 + growth)
    )
    terminal_value = terminal_residual_income / (cost_of_equity - growth)
    terminal_present_value = terminal_value / ((1 + cost_of_equity) ** years)
    intrinsic_value = (
        book_value_per_share
        + present_value_residual_income
        + terminal_present_value
    )
    return {
        "intrinsic_value_per_share": intrinsic_value,
        "pv_residual_income": present_value_residual_income,
        "terminal_residual_income_value": terminal_value,
        "pv_terminal_residual_income": terminal_present_value,
        "forecast": pd.DataFrame(forecast),
    }


def calculate_bank_valuation(
    data: dict,
    expected_roe: float | None = None,
    cost_of_equity: float = 0.12,
    stable_growth: float = 0.04,
    years: int = 5,
    fx_rate: float | None = None,
    fx_source_date: str | None = None,
    manual_metrics: dict | None = None,
    source_name: str | None = None,
    source_period: str | None = None,
) -> dict:
    """Calculate residual-income fair value and scenario/sensitivity outputs."""
    if not isinstance(data, dict):
        return {"available": False, "reason": "Data saham tidak valid."}

    ratios = data.get("ratios") or {}
    book_equity = _finite(ratios.get("Total stockholders equity"))
    shares = _finite(ratios.get("Shares outstanding"))
    price = _finite(data.get("price"))

    if book_equity is None or book_equity <= 0:
        return {
            "available": False,
            "reason": "Total stockholders equity tidak tersedia atau tidak positif. Periksa neraca resmi bank.",
        }
    if shares is None or shares <= 0:
        return {
            "available": False,
            "reason": "Shares outstanding tidak tersedia atau tidak valid.",
        }
    if price is None or price <= 0:
        return {"available": False, "reason": "Harga saham tidak tersedia atau tidak valid."}

    book_value_per_share = book_equity / shares
    if not math.isfinite(book_value_per_share) or book_value_per_share <= 0:
        return {"available": False, "reason": "Book value per share tidak valid."}

    financial_currency = data.get("financial_currency") or data.get("currency") or "Unknown"
    quote_currency = data.get("quote_currency") or data.get("currency") or "Unknown"
    conversion_applied = financial_currency != quote_currency
    applied_fx = 1.0

    if conversion_applied:
        applied_fx = _finite(fx_rate)
        if applied_fx is None or applied_fx <= 0:
            return {
                "available": False,
                "reason": (
                    f"Mata uang laporan ({financial_currency}) berbeda dari mata uang saham "
                    f"({quote_currency}). Isi kurs FX referensi yang valid."
                ),
            }

    quality = assess_bank_data(
        data,
        manual_metrics=manual_metrics,
        source_name=source_name,
        source_period=source_period,
    )
    if expected_roe is None:
        calculated_roe = _finite(ratios.get("Calculated ROE (%)"))
        reported_roe = _finite(ratios.get("ROE (%)"))
        net_income = _finite(ratios.get("Net income attributable to parent"))
        if calculated_roe is not None:
            expected_roe = calculated_roe / 100.0
            roe_source = "Calculated net income / average reported equity"
        elif reported_roe is not None:
            expected_roe = reported_roe / 100.0
            roe_source = "Yahoo Finance reported ROE (unverified provider field)"
        elif net_income is not None:
            expected_roe = net_income / book_equity
            roe_source = "Net income / closing book equity proxy"
        else:
            return {
                "available": False,
                "reason": "Expected ROE tidak tersedia. Lengkapi laba bersih dan ekuitas atau masukkan asumsi ROE.",
                "data_quality": quality,
                "data_quality_status": quality["status"],
            }
    else:
        expected_roe = _finite(expected_roe)
        roe_source = "User assumption"

    cost_of_equity = _finite(cost_of_equity)
    stable_growth = _finite(stable_growth)

    if expected_roe is None or not -1.0 < expected_roe <= 2.0:
        return {"available": False, "reason": "Expected ROE harus di antara -100% dan 200%."}
    if cost_of_equity is None or not 0 < cost_of_equity <= 1:
        return {"available": False, "reason": "Cost of equity harus lebih besar dari 0% dan maksimal 100%."}
    if stable_growth is None or not -0.5 < stable_growth < 1:
        return {"available": False, "reason": "Stable growth harus di antara -50% dan 100%."}
    if cost_of_equity <= stable_growth:
        return {
            "available": False,
            "reason": "Cost of equity harus lebih tinggi daripada stable growth.",
        }
    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 20:
        return {"available": False, "reason": "Forecast years harus bilangan bulat 1 sampai 20."}

    book_value_display = book_value_per_share * applied_fx
    base = _rim_value(
        book_value_per_share, expected_roe, cost_of_equity, stable_growth, years
    )
    intrinsic_value = base["intrinsic_value_per_share"] * applied_fx
    if not math.isfinite(intrinsic_value) or intrinsic_value <= 0:
        return {
            "available": False,
            "reason": "Residual Income menghasilkan nilai intrinsik nol/negatif atau tidak valid; periksa ROE, cost of equity, dan pertumbuhan.",
        }
    upside = (intrinsic_value / price - 1) * 100

    sensitivity_rows = []
    roe_shocks = [-0.02, 0.0, 0.02]
    coe_shocks = [-0.02, 0.0, 0.02]
    for coe_delta in coe_shocks:
        coe = cost_of_equity + coe_delta
        row = {"Cost of equity": coe}
        for roe_delta in roe_shocks:
            roe = expected_roe + roe_delta
            if coe <= stable_growth or not -1 < roe <= 2:
                value = None
            else:
                value = _rim_value(
                    book_value_per_share, roe, coe, stable_growth, years
                )["intrinsic_value_per_share"] * applied_fx
            row[f"ROE {roe:.1%}"] = value
        sensitivity_rows.append(row)

    scenarios = []
    scenario_inputs = [
        ("Bear", expected_roe - 0.03, cost_of_equity + 0.01, max(-0.10, stable_growth - 0.01)),
        ("Base", expected_roe, cost_of_equity, stable_growth),
        ("Bull", expected_roe + 0.03, max(0.01, cost_of_equity - 0.01), stable_growth + 0.01),
    ]
    for label, roe, coe, growth in scenario_inputs:
        if coe <= growth or not -1 < roe <= 2:
            value = None
        else:
            value = _rim_value(book_value_per_share, roe, coe, growth, years)[
                "intrinsic_value_per_share"
            ] * applied_fx
        scenarios.append({
            "Scenario": label,
            "Expected ROE": roe,
            "Cost of equity": coe,
            "Stable growth": growth,
            "Intrinsic value / share": value,
            "Upside / downside (%)": (value / price - 1) * 100 if value is not None else None,
        })

    current_pb = price / book_value_display if book_value_display > 0 else None
    implied_pb = intrinsic_value / book_value_display if book_value_display > 0 else None
    warnings = [
        "Residual Income Model (RIM) adalah pendekatan valuasi ekuitas bank; bukan FCFF DCF.",
        "Book equity dan shares berasal dari data agregator. Cocokkan dengan ekuitas yang dapat diatribusikan kepada pemilik induk dan jumlah saham terdilusi pada laporan resmi.",
        "ROE, cost of equity, dan stable growth adalah asumsi sensitif. Uji beberapa skenario dan jangan anggap nilai intrinsik sebagai target harga pasti.",
        "NPL gross, CAR, LDR, dan NIM hanya berasal dari input analis dengan sumber/periode yang dicatat; bukan otomatis diverifikasi oleh sistem.",
        "Model sederhana ini mengasumsikan ROE dan pertumbuhan book value stabil; perubahan kualitas kredit, kebutuhan modal, dan regulasi dapat mengubah hasil.",
    ]
    if roe_source != "User assumption":
        warnings.append(f"Expected ROE menggunakan sumber: {roe_source}. Verifikasi periode dan definisinya.")
    warnings.extend(quality.get("notes") or [])
    if quality.get("status") != "VERIFIED":
        warnings.append("Data bank belum berstatus VERIFIED; intrinsic value hanya untuk review internal.")
    if conversion_applied:
        warnings.append(
            f"Nilai per saham dikonversi dari {financial_currency} ke {quote_currency} "
            f"dengan kurs manual {applied_fx:,.4f}; tanggal referensi: {fx_source_date or 'Not specified'}."
        )

    return {
        "available": True,
        "method": "Residual Income Model (RIM)",
        "currency": quote_currency,
        "financial_currency": financial_currency,
        "book_equity": book_equity,
        "shares_outstanding": shares,
        "book_value_per_share": book_value_display,
        "current_price": price,
        "intrinsic_value_per_share": intrinsic_value,
        "upside_downside_pct": upside,
        "current_pb": current_pb,
        "implied_pb": implied_pb,
        "pv_residual_income": base["pv_residual_income"] * applied_fx,
        "terminal_residual_income_value": base["terminal_residual_income_value"] * applied_fx,
        "pv_terminal_residual_income": base["pv_terminal_residual_income"] * applied_fx,
        "forecast": base["forecast"],
        "sensitivity": pd.DataFrame(sensitivity_rows),
        "scenarios": pd.DataFrame(scenarios),
        "roe_source": roe_source,
        "fx_conversion_applied": conversion_applied,
        "fx_rate_applied": applied_fx if conversion_applied else None,
        "fx_source_date": fx_source_date if conversion_applied else None,
        "assumptions": {
            "expected_roe": expected_roe,
            "cost_of_equity": cost_of_equity,
            "stable_growth": stable_growth,
            "years": years,
        },
        "warnings": warnings,
        "data_quality_status": quality["status"],
        "data_quality": quality,
    }
