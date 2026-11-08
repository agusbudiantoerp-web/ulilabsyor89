
from multistage_dcf import project_multistage_dcf


def calculate_multistage_dcf(
    data,
    assumptions,
    fx_rate=None,
    years=5,
    allow_data_quality_override=False
):
    """
    Adapter Multi-Stage DCF untuk output analyze_equity().

    fx_rate = jumlah mata uang kuotasi untuk 1 unit
              mata uang laporan keuangan.
    """

    def number(value):
        try:
            result = float(value)
            return result if result == result and abs(result) != float("inf") else None
        except (TypeError, ValueError):
            return None

    if not isinstance(data, dict):
        return {"available": False, "reason": "Data saham tidak valid."}

    if not isinstance(assumptions, dict):
        return {"available": False, "reason": "Asumsi DCF harus berupa dictionary."}

    ratios = data.get("ratios") or {}
    warnings = []

    sector = str(data.get("sector", "")).lower()
    industry = str(data.get("industry", "")).lower()

    # Bank dan lembaga keuangan tidak memakai FCFF DCF standar.
    if (
        "bank" in industry
        or "bank" in sector
        or "financial services" in sector
    ):
        return {
            "available": False,
            "reason": (
                "Perusahaan keuangan/bank tidak cocok menggunakan "
                "FCFF DCF standar. Gunakan model valuasi khusus."
            )
        }

    revenue = number(ratios.get("Revenue"))
    reported_ebitda = number(ratios.get("EBITDA"))
    normalized_ebitda = number(ratios.get("Normalized EBITDA"))

    if normalized_ebitda is not None and normalized_ebitda > 0:
        ebitda = normalized_ebitda
        ebitda_source = "Normalized EBITDA (Yahoo Finance)"
    else:
        ebitda = reported_ebitda
        ebitda_source = "EBITDA (Yahoo Finance)"
    if (
        normalized_ebitda is not None
        and normalized_ebitda <= 0
        and reported_ebitda is not None
        and reported_ebitda > 0
    ):
        warnings.append(
            "Normalized EBITDA tidak positif, tetapi EBITDA biasa positif. "
            "Model menggunakan EBITDA biasa; periksa unusual items "
            "dan lakukan review manual sebelum memakai valuasi."
        )

    da = number(ratios.get("Depreciation and amortization"))
    operating_income = number(ratios.get("Operating income"))
    ebit = number(ratios.get("EBIT"))
    pretax_income = number(ratios.get("Pretax income"))
    tax_provision = number(ratios.get("Tax provision"))
    yahoo_tax_rate = number(ratios.get("Tax Rate For Calcs"))

    total_debt = number(ratios.get("Total debt"))
    cash = number(ratios.get("Cash and equivalents"))
    shares = number(ratios.get("Shares outstanding"))
    current_price = number(data.get("price"))

    required = {
        "Revenue": revenue,
        "EBITDA": ebitda,
        "Depreciation and amortization": da,
        "Total debt": total_debt,
        "Cash and equivalents": cash,
        "Shares outstanding": shares,
        "Current price": current_price,
    }

    missing = [name for name, value in required.items() if value is None]

    if missing:
        return {
            "available": False,
            "reason": "Data fundamental belum lengkap: " + ", ".join(missing)
        }

    if revenue <= 0 or ebitda <= 0 or da < 0:
        return {
            "available": False,
            "reason": "Revenue/EBITDA harus positif dan D&A tidak boleh negatif."
        }

    if shares <= 0 or current_price <= 0:
        return {
            "available": False,
            "reason": "Shares outstanding dan harga saham harus positif."
        }

    # Validasi EBITDA - D&A menggunakan EBIT jika tersedia.
    validation_ebit = ebit if ebit is not None else operating_income
    if validation_ebit is not None:
        calculated_ebit = ebitda - da
        discrepancy = abs(calculated_ebit - validation_ebit) / revenue

        if discrepancy > 0.03:
            comparison_label = "EBIT" if ebit is not None else "Operating Income"
            warnings.append(
                f"EBITDA - D&A berbeda material dari {comparison_label} "
                f"({discrepancy:.2%} dari Revenue). Periksa sumber laporan."
            )

    # Prioritaskan Tax Rate For Calcs dari Yahoo jika valid.
    tax_rate = None

    if yahoo_tax_rate is not None and 0 <= yahoo_tax_rate <= 1:
        tax_rate = yahoo_tax_rate

    # Fallback: hitung dari Tax Provision jika data Yahoo tidak valid.
    if (
        tax_rate is None
        and pretax_income is not None
        and tax_provision is not None
        and pretax_income > 0
        and tax_provision >= 0
    ):
        calculated_tax_rate = tax_provision / pretax_income

        if 0 <= calculated_tax_rate <= 1:
            tax_rate = calculated_tax_rate

    if warnings and not allow_data_quality_override:
        return {
            "available": False,
            "reason": "Requires Manual Review: " + " ".join(warnings),
            "warnings": warnings
        }

    model_assumptions = dict(assumptions)

    # Data operasional diturunkan dari laporan keuangan.
    model_assumptions.setdefault("ebitda_margin", ebitda / revenue)
    model_assumptions.setdefault("da_pct_revenue", da / revenue)

    capex = number(ratios.get("Capital expenditure"))

    if capex is None:
        return {
            "available": False,
            "reason": "Data Capital Expenditure tidak tersedia."
        }

    model_assumptions.setdefault("capex_pct_revenue", abs(capex) / revenue)

    ar = number(ratios.get("Accounts receivable"))
    inventory = number(ratios.get("Inventory"))
    ap = number(ratios.get("Accounts payable"))

    if ar is None or inventory is None or ap is None:
        return {
            "available": False,
            "reason": (
                "Data AR, Inventory, atau AP tidak lengkap. "
                "Operating NWC belum dapat dihitung."
            )
        }

    operating_nwc = ar + inventory - ap
    model_assumptions.setdefault("nwc_pct_revenue", operating_nwc / revenue)

    if "tax_rate" not in model_assumptions:
        if tax_rate is None:
            return {
                "available": False,
                "reason": (
                    "Tax rate tidak dapat dihitung secara andal. "
                    "Periksa data pajak atau berikan asumsi tax_rate manual."
                )
            }

        model_assumptions["tax_rate"] = tax_rate

    # Validasi mata uang.
    financial_currency = str(data.get("financial_currency") or "").upper()
    quote_currency = str(
        data.get("quote_currency") or data.get("currency") or ""
    ).upper()

    if not financial_currency or not quote_currency:
        return {
            "available": False,
            "reason": "Mata uang laporan atau mata uang kuotasi tidak tersedia."
        }

    if financial_currency == quote_currency:
        applied_fx_rate = 1.0
    else:
        applied_fx_rate = number(fx_rate)

        if applied_fx_rate is None or applied_fx_rate <= 0:
            return {
                "available": False,
                "reason": (
                    f"FX rate wajib diisi untuk konversi "
                    f"{financial_currency} ke {quote_currency}. "
                    "Gunakan quote currency per 1 financial currency."
                )
            }

    financials = {
        "revenue_base": revenue,
        "net_debt": total_debt - cash,
        "shares_outstanding": shares,
        "current_price": current_price,
        "fx_rate": applied_fx_rate,
        "financial_currency": financial_currency,
        "quote_currency": quote_currency,
    }

    try:
        result = project_multistage_dcf(
            financials,
            model_assumptions,
            years=years
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": f"Perhitungan Multi-Stage DCF gagal: {exc}"
        }

    if isinstance(result, dict):
        result["ebitda_source"] = ebitda_source
        result["ebitda_used"] = ebitda
        result["sensitivity_financials"] = dict(financials)
        result["sensitivity_assumptions"] = dict(model_assumptions)
        result["data_quality_warnings"] = warnings
        result["data_quality_override"] = bool(
            warnings and allow_data_quality_override
        )

    return result
