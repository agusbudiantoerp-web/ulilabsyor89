import pandas as pd
import pytest

from portfolio_cashflow import calculate_twr, calculate_xirr, cash_flow_ledger, normalize_events, reconcile_portfolio_ledger


def test_cash_flow_ledger_separates_external_flows_dividends_and_costs():
    result = cash_flow_ledger([
        {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 1000},
        {"date": "2026-02-01", "event_type": "DIVIDEND", "amount": 25, "ticker": "BBCA"},
        {"date": "2026-02-02", "event_type": "FEE", "amount": 5},
        {"date": "2026-03-01", "event_type": "WITHDRAWAL", "amount": 100},
    ])
    assert result["net_external_contributions"] == 900
    assert result["dividend_income"] == 25
    assert result["transaction_costs"] == 5
    assert result["event_count"] == 4


def test_normalize_events_rejects_missing_ticker_for_dividend():
    with pytest.raises(ValueError, match="Ticker wajib"):
        normalize_events([{"date": "2026-01-01", "event_type": "DIVIDEND", "amount": 10}])


def test_normalize_events_rejects_unknown_event_and_negative_amount():
    with pytest.raises(ValueError, match="tidak dikenal"):
        normalize_events([{"date": "2026-01-01", "event_type": "MAGIC", "amount": 1}])
    with pytest.raises(ValueError, match="nilai absolut positif"):
        normalize_events([{"date": "2026-01-01", "event_type": "DEPOSIT", "amount": -1}])


def test_twr_removes_external_deposit_before_linking_returns():
    # 100 -> 110 after 10% gain; then 110 + 100 deposit -> 231 = another 10% gain.
    frame = pd.DataFrame([
        {"date": "2026-01-01", "portfolio_value": 100, "external_flow": 0},
        {"date": "2026-02-01", "portfolio_value": 110, "external_flow": 0},
        {"date": "2026-03-01", "portfolio_value": 231, "external_flow": 100},
    ])
    result = calculate_twr(frame)
    assert result["twr_pct"] == pytest.approx(21.0)
    assert result["period_returns_pct"] == pytest.approx([10.0, 10.0])


def test_twr_rejects_non_positive_valuation():
    frame = pd.DataFrame([
        {"date": "2026-01-01", "portfolio_value": 100, "external_flow": 0},
        {"date": "2026-02-01", "portfolio_value": 0, "external_flow": 0},
    ])
    with pytest.raises(ValueError, match="positif"):
        calculate_twr(frame)


def test_xirr_solves_one_year_double_return():
    result = calculate_xirr([
        {"date": "2025-01-01", "amount": -1000},
        {"date": "2026-01-01", "amount": 1100},
    ])
    assert result["xirr_pct"] == pytest.approx(10.0, abs=0.02)


def test_xirr_includes_ending_portfolio_valuation():
    result = calculate_xirr(
        [{"date": "2025-01-01", "amount": -1000}],
        ending_value=1100, ending_date="2026-01-01",
    )
    assert result["xirr_pct"] == pytest.approx(10.0, abs=0.02)


def test_xirr_rejects_flows_without_both_signs():
    with pytest.raises(ValueError, match="arus negatif"):
        calculate_xirr([{"date": "2025-01-01", "amount": 100}])


def test_twr_rejects_duplicate_valuation_dates():
    frame = pd.DataFrame([
        {"date": "2026-01-01", "portfolio_value": 100, "external_flow": 0},
        {"date": "2026-01-01", "portfolio_value": 101, "external_flow": 0},
    ])
    with pytest.raises(ValueError, match="harus unik"):
        calculate_twr(frame)


def test_xirr_rejects_ambiguous_multiple_sign_changes():
    flows = [
        {"date": "2025-01-01", "amount": -1000},
        {"date": "2025-06-01", "amount": 1200},
        {"date": "2025-09-01", "amount": -300},
        {"date": "2026-01-01", "amount": 200},
    ]
    with pytest.raises(ValueError, match="lebih dari satu akar"):
        calculate_xirr(flows)


def test_portfolio_reconciliation_handles_partial_sell_dividend_fee_and_split():
    events = [
        {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 10000},
        {"date": "2026-01-02", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
        {"date": "2026-01-03", "event_type": "DIVIDEND", "amount": 50, "ticker": "BBCA"},
        {"date": "2026-01-04", "event_type": "FEE", "amount": 10},
        {"date": "2026-01-05", "event_type": "SELL", "amount": 480, "ticker": "BBCA", "quantity": 4, "price": 120},
        {"date": "2026-01-06", "event_type": "SPLIT", "amount": 0, "ticker": "BBCA", "quantity": 2},
    ]
    result = reconcile_portfolio_ledger(events)
    assert result["cash_balance"] == pytest.approx(9520)
    assert result["positions"]["BBCA"] == pytest.approx(12)


def test_portfolio_reconciliation_rejects_oversell_and_negative_cash():
    with pytest.raises(ValueError, match="melebihi"):
        reconcile_portfolio_ledger([
            {"date": "2026-01-01", "event_type": "SELL", "amount": 100, "ticker": "BBCA", "quantity": 1, "price": 100}
        ], initial_positions={"BBCA": 0})
    with pytest.raises(ValueError, match="Cash tidak cukup untuk WITHDRAWAL"):
        reconcile_portfolio_ledger([
            {"date": "2026-01-01", "event_type": "WITHDRAWAL", "amount": 100}
        ], initial_cash=10)


def test_portfolio_reconciliation_flags_transaction_amount_mismatch():
    result = reconcile_portfolio_ledger([
        {"date": "2026-01-01", "event_type": "BUY", "amount": 1200, "ticker": "BBCA", "quantity": 10, "price": 100}
    ], initial_cash=2000)
    assert result["cash_balance"] == pytest.approx(800)
    assert len(result["warnings"]) == 1


def test_portfolio_reconciliation_rejects_temporary_cash_deficit_even_if_later_deposit_exists():
    events = [
        {"date": "2026-01-01", "event_type": "BUY", "amount": 100, "ticker": "BBCA", "quantity": 1, "price": 100},
        {"date": "2026-01-02", "event_type": "DEPOSIT", "amount": 100},
    ]
    with pytest.raises(ValueError, match="Cash tidak cukup untuk BUY"):
        reconcile_portfolio_ledger(events)


def test_portfolio_reconciliation_rejects_zero_trade_quantity_or_price():
    with pytest.raises(ValueError, match="Quantity BUY/SELL"):
        normalize_events([
            {"date": "2026-01-01", "event_type": "BUY", "amount": 100, "ticker": "BBCA", "quantity": 0, "price": 100}
        ])
    with pytest.raises(ValueError, match="Price BUY/SELL"):
        normalize_events([
            {"date": "2026-01-01", "event_type": "BUY", "amount": 100, "ticker": "BBCA", "quantity": 1, "price": 0}
        ])


def test_portfolio_reconciliation_rejects_zero_split_ratio():
    with pytest.raises(ValueError, match="Rasio split"):
        normalize_events([
            {"date": "2026-01-01", "event_type": "SPLIT", "amount": 0, "ticker": "BBCA", "quantity": 0}
        ])


def test_portfolio_reconciliation_supports_preexisting_opening_positions():
    result = reconcile_portfolio_ledger(
        [{
            "date": "2026-01-01", "event_type": "SELL", "amount": 1200,
            "ticker": "BBCA", "quantity": 10, "price": 120,
        }],
        initial_cash=100,
        initial_positions={"BBCA": 25},
    )
    assert result["cash_balance"] == pytest.approx(1300)
    assert result["positions"]["BBCA"] == pytest.approx(15)



def test_normalize_events_rejects_non_finite_trade_quantity_and_price():
    with pytest.raises(ValueError, match="quantity harus berupa angka finite"):
        normalize_events([{
            "date": "2026-01-01", "event_type": "BUY", "amount": 100,
            "ticker": "BBCA", "quantity": float("inf"), "price": 100,
        }])
    with pytest.raises(ValueError, match="price harus berupa angka finite"):
        normalize_events([{
            "date": "2026-01-01", "event_type": "BUY", "amount": 100,
            "ticker": "BBCA", "quantity": 1, "price": float("inf"),
        }])


def test_normalize_events_validates_explicit_settlement_date():
    base = {
        "date": "2026-01-02", "event_type": "BUY", "amount": 100,
        "ticker": "BBCA", "quantity": 1, "price": 100,
    }
    with pytest.raises(ValueError, match="Settlement date transaksi tidak valid"):
        normalize_events([{**base, "settlement_date": "not-a-date"}])
    with pytest.raises(ValueError, match="tidak boleh lebih awal"):
        normalize_events([{**base, "settlement_date": "2026-01-01"}])
    normalized = normalize_events([{**base, "settlement_date": "2026-01-03"}])
    assert pd.Timestamp(normalized.iloc[0]["settlement_date"]) == pd.Timestamp("2026-01-03")


@pytest.mark.parametrize("field,value", [
    ("date", True),
    ("date", 1767225600000000000),
    ("amount", True),
    ("quantity", False),
    ("price", True),
])
def test_normalize_events_rejects_boolean_or_numeric_date_and_boolean_numbers(field, value):
    event = {
        "date": "2026-01-01", "event_type": "BUY", "amount": 100,
        "ticker": "BBCA", "quantity": 1, "price": 100,
    }
    event[field] = value
    with pytest.raises(ValueError):
        normalize_events([event])


@pytest.mark.parametrize("field,value", [
    ("date", True),
    ("date", 1767225600000000000),
    ("portfolio_value", True),
    ("external_flow", False),
])
def test_twr_rejects_boolean_and_numeric_dates(field, value):
    frame = pd.DataFrame([
        {"date": "2026-01-01", "portfolio_value": 100, "external_flow": 0},
        {"date": "2026-02-01", "portfolio_value": 110, "external_flow": 0},
    ]).astype({field: "object"})
    frame.loc[0, field] = value
    with pytest.raises(ValueError):
        calculate_twr(frame)


@pytest.mark.parametrize("field,value", [
    ("date", True),
    ("date", 1767225600000000000),
    ("amount", True),
])
def test_xirr_rejects_boolean_and_numeric_dates(field, value):
    flows = pd.DataFrame([
        {"date": "2025-01-01", "amount": -1000},
        {"date": "2026-01-01", "amount": 1100},
    ]).astype({field: "object"})
    flows.loc[0, field] = value
    with pytest.raises(ValueError):
        calculate_xirr(flows)


def test_xirr_rejects_boolean_ending_value_and_numeric_ending_date():
    flows = [
        {"date": "2025-01-01", "amount": -1000},
        {"date": "2026-01-01", "amount": 500},
    ]
    with pytest.raises(ValueError, match="boolean"):
        calculate_xirr(flows, ending_value=True, ending_date="2026-12-31")
    with pytest.raises(ValueError, match="Ending date"):
        calculate_xirr(flows, ending_value=500, ending_date=1767225600000000000)


def test_twr_and_xirr_accept_mixed_timezone_aware_dates():
    twr = calculate_twr(pd.DataFrame([
        {"date": "2026-01-01T00:00:00Z", "portfolio_value": 100, "external_flow": 0},
        {"date": "2026-02-01T07:00:00+07:00", "portfolio_value": 110, "external_flow": 0},
    ]))
    xirr = calculate_xirr([
        {"date": "2025-01-01T00:00:00Z", "amount": -1000},
        {"date": "2026-01-01T07:00:00+07:00", "amount": 1100},
    ])
    assert twr["twr_pct"] == pytest.approx(10.0)
    assert xirr["xirr_pct"] == pytest.approx(10.0, abs=0.02)


@pytest.mark.parametrize("value", [True, 1767225600000000000])
def test_normalize_events_rejects_boolean_or_numeric_settlement_date(value):
    event = {
        "date": "2026-01-02", "event_type": "BUY", "amount": 100,
        "ticker": "BBCA", "quantity": 1, "price": 100,
        "settlement_date": value,
    }
    with pytest.raises(ValueError, match="Settlement date"):
        normalize_events([event])


@pytest.mark.parametrize("kwargs", [
    {"initial_cash": True},
    {"amount_tolerance_pct": True},
    {"initial_positions": {"BBCA": True}},
])
def test_reconcile_portfolio_ledger_rejects_boolean_opening_inputs(kwargs):
    with pytest.raises(ValueError, match="boolean"):
        reconcile_portfolio_ledger([], **kwargs)


def test_normalize_events_preserves_local_calendar_day_for_timezone_aware_dates():
    normalized = normalize_events([{
        "date": "2026-01-02T00:30:00+07:00",
        "event_type": "BUY",
        "amount": 100,
        "ticker": "BBCA",
        "quantity": 1,
        "price": 100,
        "settlement_date": "2026-01-03T00:30:00+07:00",
    }])
    assert normalized.iloc[0]["date"] == pd.Timestamp("2026-01-02")
    assert normalized.iloc[0]["settlement_date"] == pd.Timestamp("2026-01-03")
    assert normalized.iloc[0]["date"].tzinfo is None
    assert normalized.iloc[0]["settlement_date"].tzinfo is None
