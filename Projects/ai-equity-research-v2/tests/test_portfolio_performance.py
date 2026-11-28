import pandas as pd
import pytest
from portfolio_performance import calculate_portfolio_performance_snapshot

def _tax_result():
    return {"open_lots": pd.DataFrame([
        {"ticker": "BBCA", "quantity": 5.0, "cost_basis": 500.0},
        {"ticker": "TLKM", "quantity": 2.0, "cost_basis": 200.0},
    ]), "realized_pnl": 80.0, "realized_sale_proceeds": 300.0,
        "realized_cost_basis": 220.0, "open_cost_basis": 700.0}

def test_snapshot_attributes_realized_unrealized_dividend_and_costs():
    result = calculate_portfolio_performance_snapshot(_tax_result(), [
        {"date": "2026-01-01", "event_type": "DIVIDEND", "amount": 20},
        {"date": "2026-01-02", "event_type": "FEE", "amount": 5},
        {"date": "2026-01-03", "event_type": "TAX", "amount": 2},
    ], {"BBCA": 120, "TLKM": 90}, as_of_date="2026-01-03")
    assert result["market_value"] == pytest.approx(780)
    assert result["unrealized_pnl"] == pytest.approx(80)
    assert result["realized_pnl"] == pytest.approx(80)
    assert result["dividend_income"] == pytest.approx(20)
    assert result["fees_and_taxes"] == pytest.approx(7)
    assert result["total_profit_including_dividends"] == pytest.approx(173)
    assert result["total_return_on_recorded_cost_basis_pct"] == pytest.approx(18.8043478261)
    assert list(result["holdings"]["ticker"]) == ["BBCA", "TLKM"]

def test_snapshot_requires_complete_prices_and_reports_unused_prices():
    with pytest.raises(ValueError, match="Harga pasar belum tersedia"):
        calculate_portfolio_performance_snapshot(_tax_result(), [], {"BBCA": 100})
    result = calculate_portfolio_performance_snapshot(_tax_result(), [], {"BBCA": 100, "TLKM": 100, "ASII": 500})
    assert result["unused_price_tickers"] == ["ASII"]

def test_snapshot_filters_cash_events_to_as_of_date():
    result = calculate_portfolio_performance_snapshot(_tax_result(), [
        {"date": "2026-01-01", "event_type": "DIVIDEND", "amount": 10},
        {"date": "2026-02-01", "event_type": "DIVIDEND", "amount": 90},
    ], {"BBCA": 100, "TLKM": 100}, as_of_date="2026-01-31")
    assert result["dividend_income"] == pytest.approx(10)

def test_snapshot_rejects_inconsistent_open_lot_basis_and_invalid_market_price():
    bad = _tax_result()
    bad["open_cost_basis"] = 701
    with pytest.raises(ValueError, match="tidak konsisten"):
        calculate_portfolio_performance_snapshot(bad, [], {"BBCA": 100, "TLKM": 100})
    with pytest.raises(ValueError, match="Harga BBCA"):
        calculate_portfolio_performance_snapshot(_tax_result(), [], {"BBCA": float("nan"), "TLKM": 100})

def test_snapshot_rejects_missing_schema_and_duplicate_normalized_price_tickers():
    with pytest.raises(ValueError, match="tidak lengkap"):
        calculate_portfolio_performance_snapshot({}, [], {})
    with pytest.raises(ValueError, match="duplikat"):
        calculate_portfolio_performance_snapshot(_tax_result(), [], {"bbca": 100, "BBCA": 101})
