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


def test_fifo_orders_opening_and_ledger_lots_by_acquisition_date():
    result = calculate_tax_lots(
        [
            {"date": "2026-02-01", "event_type": "BUY", "amount": 1200, "ticker": "BBCA", "quantity": 10, "price": 120},
            {"date": "2026-04-01", "event_type": "SELL", "amount": 700, "ticker": "BBCA", "quantity": 5, "price": 140},
        ],
        opening_lots=[
            {"ticker": "BBCA", "quantity": 10, "unit_cost": 90, "acquisition_date": "2026-03-01"},
        ],
    )
    # The February ledger purchase predates the March opening lot and is consumed first.
    assert result["realized_cost_basis"] == pytest.approx(600)
    assert result["open_quantity_by_ticker"]["BBCA"] == pytest.approx(15)
    assert result["open_cost_basis"] == pytest.approx(1500)


def test_fifo_cannot_sell_an_opening_lot_before_its_acquisition_date():
    with pytest.raises(ValueError, match="tax lot tersedia pada 2026-02-01"):
        calculate_tax_lots(
            [{"date": "2026-02-01", "event_type": "SELL", "amount": 100, "ticker": "BBCA", "quantity": 1, "price": 100}],
            opening_lots=[
                {"ticker": "BBCA", "quantity": 5, "unit_cost": 80, "acquisition_date": "2026-03-01"},
            ],
        )


def test_opening_lot_rejects_invalid_acquisition_date():
    with pytest.raises(ValueError, match="acquisition_date"):
        calculate_tax_lots([], opening_lots=[
            {"ticker": "BBCA", "quantity": 5, "unit_cost": 80, "acquisition_date": "not-a-date"},
        ])

def test_average_cost_sale_preserves_lots_acquired_after_sale_date():
    result = calculate_tax_lots(
        [{
            "date": "2026-02-01", "event_type": "SELL", "amount": 600,
            "ticker": "BBCA", "quantity": 5, "price": 120,
        }],
        method="AVERAGE_COST",
        opening_lots=[
            {"ticker": "BBCA", "quantity": 10, "unit_cost": 100, "acquisition_date": "2026-01-01"},
            {"ticker": "BBCA", "quantity": 5, "unit_cost": 200, "acquisition_date": "2026-03-01"},
        ],
    )
    assert result["realized_cost_basis"] == pytest.approx(500)
    assert result["realized_pnl"] == pytest.approx(100)
    assert result["open_quantity_by_ticker"]["BBCA"] == pytest.approx(10)
    assert result["open_cost_basis"] == pytest.approx(1500)
    future_lot = result["open_lots"].loc[
        result["open_lots"]["acquisition_date"].eq("2026-03-01")
    ].iloc[0]
    assert future_lot["quantity"] == pytest.approx(5)
    assert future_lot["unit_cost"] == pytest.approx(200)

def test_fifo_sorts_opening_lots_even_when_input_order_is_not_chronological():
    result = calculate_tax_lots(
        [{
            "date": "2026-04-01", "event_type": "SELL", "amount": 500,
            "ticker": "BBCA", "quantity": 5, "price": 100,
        }],
        opening_lots=[
            {"ticker": "BBCA", "quantity": 5, "unit_cost": 200, "acquisition_date": "2026-03-01"},
            {"ticker": "BBCA", "quantity": 5, "unit_cost": 80, "acquisition_date": "2026-01-01"},
        ],
    )
    assert result["realized_cost_basis"] == pytest.approx(400)
    assert result["realized_pnl"] == pytest.approx(100)
    remaining = result["open_lots"].iloc[0]
    assert remaining["acquisition_date"] == "2026-03-01"
    assert remaining["quantity"] == pytest.approx(5)

def test_average_cost_supports_multiple_sales_from_remaining_pooled_lot():
    result = calculate_tax_lots(
        [
            {"date": "2026-02-01", "event_type": "SELL", "amount": 600, "ticker": "BBCA", "quantity": 5, "price": 120},
            {"date": "2026-02-15", "event_type": "SELL", "amount": 240, "ticker": "BBCA", "quantity": 2, "price": 120},
        ],
        method="AVERAGE_COST",
        opening_lots=[
            {"ticker": "BBCA", "quantity": 10, "unit_cost": 100, "acquisition_date": "2026-01-01"},
        ],
    )
    assert result["realized_cost_basis"] == pytest.approx(700)
    assert result["realized_pnl"] == pytest.approx(140)
    assert result["open_quantity_by_ticker"]["BBCA"] == pytest.approx(3)
    assert result["open_cost_basis"] == pytest.approx(300)
