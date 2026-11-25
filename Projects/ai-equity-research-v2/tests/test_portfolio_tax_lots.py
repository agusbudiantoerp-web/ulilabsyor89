import pytest

from portfolio_tax_lots import calculate_tax_lots


def test_fifo_matches_oldest_lot_and_reports_realized_pnl():
    result = calculate_tax_lots([
        {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
        {"date": "2026-02-01", "event_type": "BUY", "amount": 600, "ticker": "BBCA", "quantity": 5, "price": 120},
        {"date": "2026-03-01", "event_type": "SELL", "amount": 720, "ticker": "BBCA", "quantity": 6, "price": 120},
    ])
    assert result["realized_cost_basis"] == pytest.approx(600)
    assert result["realized_sale_proceeds"] == pytest.approx(720)
    assert result["realized_pnl"] == pytest.approx(120)
    assert result["open_quantity_by_ticker"]["BBCA"] == pytest.approx(9)
    assert result["open_cost_basis"] == pytest.approx(1000)


def test_average_cost_uses_weighted_average_basis():
    result = calculate_tax_lots([
        {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
        {"date": "2026-02-01", "event_type": "BUY", "amount": 600, "ticker": "BBCA", "quantity": 5, "price": 120},
        {"date": "2026-03-01", "event_type": "SELL", "amount": 720, "ticker": "BBCA", "quantity": 6, "price": 120},
    ], method="AVERAGE_COST")
    assert result["realized_cost_basis"] == pytest.approx(640)
    assert result["realized_pnl"] == pytest.approx(80)
    assert result["open_cost_basis"] == pytest.approx(960)


def test_split_preserves_total_cost_basis_and_adjusts_unit_cost():
    result = calculate_tax_lots([
        {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
        {"date": "2026-02-01", "event_type": "SPLIT", "amount": 0, "ticker": "BBCA", "quantity": 2},
    ])
    assert result["open_quantity_by_ticker"]["BBCA"] == pytest.approx(20)
    assert result["open_cost_basis"] == pytest.approx(1000)
    assert result["open_lots"].iloc[0]["unit_cost"] == pytest.approx(50)


def test_opening_lots_can_be_used_for_partial_sale():
    result = calculate_tax_lots([
        {"date": "2026-03-01", "event_type": "SELL", "amount": 250, "ticker": "TLKM", "quantity": 5, "price": 50},
    ], opening_lots=[{
        "ticker": "TLKM", "quantity": 10, "unit_cost": 40, "acquisition_date": "2025-01-01",
    }])
    assert result["realized_pnl"] == pytest.approx(50)
    assert result["open_quantity_by_ticker"]["TLKM"] == pytest.approx(5)
    assert result["open_cost_basis"] == pytest.approx(200)


def test_tax_lots_reject_short_sale_and_unknown_method():
    events = [{"date": "2026-03-01", "event_type": "SELL", "amount": 250, "ticker": "TLKM", "quantity": 5, "price": 50}]
    with pytest.raises(ValueError, match="melebihi tax lot"):
        calculate_tax_lots(events)
    with pytest.raises(ValueError, match="Metode tax lot"):
        calculate_tax_lots([], method="LIFO")


def test_opening_lots_reject_invalid_values():
    with pytest.raises(ValueError, match="Opening lot"):
        calculate_tax_lots([], opening_lots=[{"ticker": "BBCA", "quantity": -1, "unit_cost": 10}])



def test_opening_tax_lots_work_without_any_ledger_events():
    result = calculate_tax_lots(
        [],
        opening_lots=[{
            "ticker": "BBCA", "quantity": 100,
            "unit_cost": 8500, "acquisition_date": "2025-01-01",
        }],
    )
    assert result["realized_pnl"] == pytest.approx(0)
    assert result["open_quantity_by_ticker"]["BBCA"] == pytest.approx(100)
    assert result["open_cost_basis"] == pytest.approx(850000)
