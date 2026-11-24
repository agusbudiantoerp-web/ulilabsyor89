from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from research_reporting import build_excel_report, build_pdf_report


def test_excel_and_pdf_reports_are_generated_with_nested_history_payload():
    portfolio = pd.DataFrame([{"Ticker": "BBCA", "Market Value": 1000}])
    history = pd.DataFrame([{
        "ticker": "BBCA",
        "payload": {"signal": "BUY", "checks": ["trend", "volume"]},
    }])
    excel = build_excel_report(
        portfolio=portfolio, metrics={"Return": 12.5}, history=history,
        extra_sheets={"Backtest Trades": pd.DataFrame([{"ticker": "BBCA", "pnl": 25}])},
    )
    pdf = build_pdf_report("Test report", {"Return": 12.5}, ["Research only"])
    assert excel[:2] == b"PK"
    workbook = load_workbook(BytesIO(excel), read_only=True)
    assert {"Portfolio", "Signal History", "Summary", "Backtest Trades"}.issubset(
        set(workbook.sheetnames)
    )
    assert pdf.startswith(b"%PDF")



def test_excel_report_escapes_formula_like_untrusted_text():
    excel = build_excel_report(
        portfolio=pd.DataFrame([{"Ticker": "=HYPERLINK(\"https://evil.example\",\"click\")"}]),
        metrics={"Provider note": "+cmd|' /C calc'!A0"},
        extra_sheets={"External Data": pd.DataFrame([{"Company": "  @SUM(1,1)"}])},
    )
    workbook = load_workbook(BytesIO(excel), read_only=True, data_only=False)
    assert workbook["Portfolio"]["A2"].value.startswith("'=")
    summary = {row[0]: row[1] for row in workbook["Summary"].iter_rows(values_only=True) if row[0]}
    assert str(summary["Provider note"]).startswith("'+")
    assert workbook["External Data"]["A2"].value.startswith("'  @")
