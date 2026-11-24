import pandas as pd

from research_reporting import build_excel_report, build_pdf_report


def test_excel_and_pdf_reports_are_generated():
    portfolio = pd.DataFrame([{"Ticker": "BBCA", "Market Value": 1000}])
    excel = build_excel_report(portfolio=portfolio, metrics={"Return": 12.5})
    pdf = build_pdf_report("Test report", {"Return": 12.5}, ["Research only"])
    assert excel[:2] == b"PK"
    assert pdf.startswith(b"%PDF")
