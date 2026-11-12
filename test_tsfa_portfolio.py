
import sys
from pathlib import Path
from io import BytesIO
from datetime import date

import pytest
from openpyxl import Workbook, load_workbook

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "time-series"))

from tsfa_portfolio_engine import (
    calculate_portfolio,
    validate_portfolio_workbook,
    PortfolioValidationError,
)


def make_workbook():
    wb = Workbook()

    ws = wb.active
    ws.title = "PORTFOLIO"

    ws.append([
        "Record_Type", "Market", "Ticker",
        "Opening_Quantity_Shares", "Opening_Average_Cost",
        "Opening_Market_Price", "Opening_Cash",
        "Currency", "As_Of_Date"
    ])

    ws.append([
        "HOLDING", "Indonesia", "BBRI",
        100, 10, 11, None, "IDR", date(2026, 1, 1)
    ])

    ws.append([
        "CASH", "Indonesia", "CASH",
        None, None, None, 10000, "IDR", date(2026, 1, 1)
    ])

    ws = wb.create_sheet("TRANSACTIONS")
    ws.append([
        "Transaction_ID", "Date", "Market", "Ticker",
        "Side", "Quantity_Shares", "Price_Per_Share",
        "Fees", "Tax", "Currency"
    ])

    ws.append([
        "T001", date(2026, 1, 2), "Indonesia",
        "BBRI", "BUY", 100, 12, 10, 0, "IDR"
    ])

    ws.append([
        "T002", date(2026, 1, 3), "Indonesia",
        "BBRI", "SELL", 50, 14, 10, 0, "IDR"
    ])

    ws = wb.create_sheet("CASH_FLOW")
    ws.append([
        "Flow_ID", "Date", "Flow_Type",
        "Amount", "Currency", "Ticker", "Tax"
    ])

    ws.append([
        "F001", date(2026, 1, 4),
        "DEPOSIT", 1000, "IDR", None, 0
    ])

    ws.append([
        "F002", date(2026, 1, 4),
        "WITHDRAWAL", 100, "IDR", None, 0
    ])

    ws.append([
        "F003", date(2026, 1, 4),
        "DIVIDEND", 50, "IDR", "BBRI", 5
    ])

    ws = wb.create_sheet("PRICE_HISTORY")
    ws.append([
        "Date", "Market", "Ticker", "Close", "Currency"
    ])

    ws.append([
        date(2026, 1, 5), "Indonesia",
        "BBRI", 13, "IDR"
    ])

    ws = wb.create_sheet("ANALYSIS_RESULTS")
    ws.append(["Ticker", "Quantity_Shares"])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return output.getvalue()


def test_workbook_validation():
    result = validate_portfolio_workbook(make_workbook())

    assert result["status"] == "VALID"
    assert result["holding_count"] == 1
    assert result["total_quantity_shares"] == 100


def test_buy_sell_average_cost_and_cash():
    result = calculate_portfolio(make_workbook())

    position = result.positions.iloc[0]

    # Opening: 100 shares x Rp10
    # BUY: 100 shares x Rp12 + Rp10 fee
    # Average cost = Rp11.05
    assert position["Quantity_Shares"] == 150
    assert position["Average_Cost"] == pytest.approx(11.05)

    # SELL: 50 shares x Rp14 - Rp10 fee
    # Realized P/L = Rp137.50
    assert position["Realized_PnL"] == pytest.approx(137.50)

    # Cash = 10000 - 1210 + 690 + 1000 - 100 + 45
    assert result.cash_balance == pytest.approx(10425)

    # Market value = 150 x Rp13
    assert position["Market_Value"] == pytest.approx(1950)

    # Cost basis = 150 x Rp11.05
    assert position["Cost_Basis"] == pytest.approx(1657.50)

    assert position["Unrealized_PnL"] == pytest.approx(292.50)

    assert result.priced_positions == 1



def test_sell_exceeding_available_shares():
    data = make_workbook()

    wb = load_workbook(BytesIO(data))
    ws = wb["TRANSACTIONS"]

    ws.append([
        "T003", date(2026, 1, 6), "Indonesia",
        "BBRI", "SELL", 1000, 14, 0, 0, "IDR"
    ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    with pytest.raises(
        PortfolioValidationError,
        match="melebihi jumlah saham tersedia"
    ):
        calculate_portfolio(output.getvalue())


    # This test will be added separately after baseline verification.
    assert isinstance(data, bytes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

def test_negative_opening_cash_rejected():
    data = make_workbook()

    wb = load_workbook(BytesIO(data))
    ws = wb["PORTFOLIO"]

    ws["G3"] = -1000

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    with pytest.raises(PortfolioValidationError):
        validate_portfolio_workbook(output.getvalue())


def test_buy_exceeding_cash_rejected():
    data = make_workbook()

    wb = load_workbook(BytesIO(data))
    ws = wb["TRANSACTIONS"]

    # BUY 100 saham x Rp200 = Rp20.000,
    # sedangkan saldo kas awal hanya Rp10.000.
    ws["G2"] = 200
    ws["H2"] = 0
    ws["I2"] = 0

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    with pytest.raises(PortfolioValidationError):
        calculate_portfolio(output.getvalue())