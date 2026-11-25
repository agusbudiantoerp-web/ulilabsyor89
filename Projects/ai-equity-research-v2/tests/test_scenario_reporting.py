import pandas as pd
from openpyxl import load_workbook
from io import BytesIO

from scenario_engine import project_scenario, operating_scenario_sensitivity
from reports import make_excel_report, make_pdf_report


def _financials():
    return {
        "ticker": "TEST.JK",
        "revenue_base": 100.0,
        "net_debt": 0.0,
        "shares_outstanding": 10.0,
        "current_price": 10.0,
        "fx_rate": 1.0,
        "financial_currency": "IDR",
        "quote_currency": "IDR",
    }


def _assumptions():
    return {
        "revenue_growth": 0.0,
        "ebitda_margin": 0.20,
        "da_pct_revenue": 0.05,
        "capex_pct_revenue": 0.05,
        "nwc_pct_revenue": 0.0,
        "tax_rate": 0.20,
        "wacc": 0.10,
        "terminal_growth": 0.03,
    }


def test_scenario_dcf_discloses_terminal_value_concentration():
    result = project_scenario(_financials(), _assumptions(), years=1)
    assert result["available"]
    assert result["terminal_value_share_pct"] > 75
    assert any("terminal value" in item.lower() for item in result["model_warnings"])


def test_research_exports_include_scenario_assumptions_catalysts_risks_and_sources():
    data = {
        "ticker": "TEST.JK",
        "company": "Test Company",
        "sector": "Industrials",
        "industry": "Services",
        "currency": "IDR",
        "financial_currency": "IDR",
        "as_of": "2026-11-24T00:00:00+00:00",
        "latest_price_date": "2026-11-23",
        "latest_financial_period": "2025-12-31",
        "latest_balance_period": "2025-12-31",
        "latest_cashflow_period": "2025-12-31",
        "price": 100.0,
        "change_pct": 1.0,
        "period_return_pct": 5.0,
        "trend": "Bullish",
        "rsi14": 55.0,
        "annualized_volatility_pct": 20.0,
        "data_source": "Yahoo Finance",
        "data_quality_note": "Third-party data; verify official reports.",
        "data_quality_warnings": [],
        "disclaimer": "Research support only.",
        "ratios": {"Revenue": 100.0},
        "history": pd.DataFrame([{"Date": "2026-11-23", "Close": 100.0}]),
    }
    scenario = {
        "available": True,
        "assumptions": {"Base": _assumptions()},
        "results": {
            "Base": {
                "available": True,
                "intrinsic_value_per_share": 12.0,
                "upside_downside_pct": 20.0,
                "enterprise_value": 120.0,
                "equity_value": 120.0,
                "terminal_value_share_pct": 80.0,
                "model_warnings": ["Terminal value dominates the valuation."],
            }
        },
        "research_context": {
            "catalysts": "New capacity expected in 2027 (analyst note).",
            "risks": "Commodity price volatility.",
            "analyst_note": "Manually entered; not independently verified.",
        },
        "source_metadata": {
            "provider": "Yahoo Finance",
            "latest_price_date": "2026-11-23",
            "income_statement_period": "2025-12-31",
        },
    }
    excel = make_excel_report(data, scenario_result=scenario)
    workbook = load_workbook(BytesIO(excel), read_only=True)
    assert "Scenario Assumptions" in workbook.sheetnames
    assert "Catalysts & Risks" in workbook.sheetnames
    assert "Sources & Dates" in workbook.sheetnames
    pdf = make_pdf_report(data, scenario_result=scenario)
    assert pdf.startswith(b"%PDF")


def test_scenario_dcf_fails_closed_on_forecast_overflow():
    financials = _financials()
    financials["revenue_base"] = 1e308
    assumptions = _assumptions()
    assumptions["revenue_growth"] = 0.5
    result = project_scenario(financials, assumptions, years=5)
    assert not result["available"]
    assert "overflow" in result["reason"].lower()


def test_operating_sensitivity_recalculates_growth_and_margin_grid():
    result = operating_scenario_sensitivity(
        _financials(), _assumptions(),
        revenue_growth_values=[-0.02, 0.0, 0.02],
        ebitda_margin_values=[0.18, 0.20, 0.22],
        years=3,
    )
    assert result["available"]
    assert len(result["sensitivity"]) == 3
    assert all(len(row["values"]) == 3 for row in result["sensitivity"])
    center = result["sensitivity"][1]["values"][1]
    baseline = project_scenario(_financials(), _assumptions(), years=3)
    assert center["available"] is True
    assert center["value_per_share"] == baseline["intrinsic_value_per_share"]
    assert result["currency"] == "IDR"


def test_operating_sensitivity_rejects_duplicate_axis_and_oversized_grid():
    import pytest

    with pytest.raises(ValueError, match="duplicate"):
        operating_scenario_sensitivity(
            _financials(), _assumptions(),
            revenue_growth_values=[0.0, 0.0],
            ebitda_margin_values=[0.2],
        )
    with pytest.raises(ValueError, match="safety limit"):
        operating_scenario_sensitivity(
            _financials(), _assumptions(),
            revenue_growth_values=[i / 100 for i in range(11)],
            ebitda_margin_values=[i / 100 for i in range(10)],
        )
