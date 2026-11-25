from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from reports import make_excel_report, make_pdf_report


def sample_data():
    return {
        "ticker": "TEST.JK",
        "company": "Test Company Tbk",
        "sector": "Industrials",
        "industry": "Industrial Products",
        "currency": "IDR",
        "financial_currency": "IDR",
        "as_of": "2026-11-24T00:00:00+00:00",
        "latest_price_date": "2026-11-24",
        "latest_financial_period": "2025-12-31",
        "latest_balance_period": "2025-12-31",
        "latest_cashflow_period": "2025-12-31",
        "price": 1000,
        "change_pct": 1.0,
        "period_return_pct": 10.0,
        "trend": "Bullish",
        "rsi14": 55,
        "annualized_volatility_pct": 25,
        "data_source": "Test fixture",
        "data_quality_note": "Synthetic test data",
        "data_quality_warnings": [],
        "disclaimer": "Synthetic report test only.",
        "ratios": {"Revenue": 1000000},
        "history": pd.DataFrame([{"Date": "2026-11-24", "Close": 1000}]),
    }


def valuation_payloads():
    multistage = {
        "available": True,
        "forecast": [{"Year": 1, "Revenue": 1000, "FCFF": 100}],
        "enterprise_value": 1000,
        "equity_value": 900,
        "net_debt": 100,
        "pv_fcff": 300,
        "pv_terminal": 700,
        "terminal_value": 900,
        "intrinsic_value_per_share": 900,
        "financial_currency": "IDR",
        "quote_currency": "IDR",
        "fx_rate_applied": 1.0,
        "fx_source_date": None,
        "ebitda_source": "Normalized EBITDA",
        "ebitda_used": 200,
        "assumptions": {"wacc": 0.12, "terminal_growth": 0.025},
        "warnings": [],
        "data_quality_warnings": [],
    }
    scenarios = {
        "available": True,
        "results": {
            "Bear": {"available": True, "intrinsic_value_per_share": 700, "upside_downside_pct": -30, "forecast": [{"year": 1, "fcff": 80}]},
            "Base": {"available": True, "intrinsic_value_per_share": 1000, "upside_downside_pct": 0, "forecast": [{"year": 1, "fcff": 100}]},
            "Bull": {"available": True, "intrinsic_value_per_share": 1300, "upside_downside_pct": 30, "forecast": [{"year": 1, "fcff": 120}]},
        },
        "sensitivity": {"sensitivity": [], "terminal_growth_values": []},
    }
    return multistage, scenarios


def test_excel_research_pack_contains_multistage_and_scenario_sheets():
    multistage, scenarios = valuation_payloads()
    payload = make_excel_report(
        sample_data(), multistage_dcf=multistage, scenario_result=scenarios
    )
    workbook = load_workbook(BytesIO(payload), read_only=True)
    assert "MultiStage Forecast" in workbook.sheetnames
    assert "MultiStage Valuation" in workbook.sheetnames
    assert "Bear Base Bull" in workbook.sheetnames
    assert "Bear Forecast" in workbook.sheetnames
    workbook.close()


def test_pdf_research_pack_contains_valuation_sections():
    multistage, scenarios = valuation_payloads()
    payload = make_pdf_report(
        sample_data(), multistage_dcf=multistage, scenario_result=scenarios
    )
    assert payload.startswith(b"%PDF")
    assert len(payload) > 1000



def test_equity_excel_report_escapes_formula_like_ticker_text():
    data = sample_data()
    data["ticker"] = "=HYPERLINK(\"https://evil.example\",\"click\")"
    payload = make_excel_report(data)
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=False)
    assert workbook["Summary"]["A2"].value.startswith("'=")
    workbook.close()


def test_excel_scenario_forecast_sheet_names_are_sanitized_and_unique():
    data = sample_data()
    scenarios = {
        "available": True,
        "results": {
            "bad/name": {"available": True, "forecast": [{"year": 1, "fcff": 1}]},
            "bad:name": {"available": True, "forecast": [{"year": 1, "fcff": 2}]},
        },
    }
    payload = make_excel_report(data, scenario_result=scenarios)
    workbook = load_workbook(BytesIO(payload), read_only=True)
    forecast_sheets = [name for name in workbook.sheetnames if "Forecast" in name]
    assert "bad_name Forecast" in forecast_sheets
    assert "bad_name Forecast (2)" in forecast_sheets
    assert len(forecast_sheets) == len(set(forecast_sheets))
    workbook.close()


def test_excel_export_neutralizes_formula_after_utf8_bom_prefix():
    data = sample_data()
    data["ticker"] = "\\ufeff=HYPERLINK(\"https://evil.example\",\"click\")"
    workbook = load_workbook(BytesIO(make_excel_report(data)), read_only=True, data_only=False)
    assert workbook["Summary"]["A2"].value.startswith("'\\ufeff=")
    workbook.close()
