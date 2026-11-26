import pandas as pd
import pytest

from portfolio_snapshot_reconciliation import reconcile_broker_snapshot


def run(**overrides):
    args = dict(
        ledger_cash=1000, ledger_positions={"BBCA": 10, "TLKM": 5},
        broker_cash=1000, broker_positions={"BBCA": 10, "TLKM": 5},
        ledger_currency="IDR", broker_currency="IDR",
        ledger_as_of_date="2026-11-25", broker_as_of_date="2026-11-25",
    )
    args.update(overrides)
    return reconcile_broker_snapshot(**args)


def test_exact_snapshot_match_is_read_only():
    result = run()
    assert result["comparable"] is True
    assert result["exception_count"] == 0
    assert result["matched_count"] == 3
    assert result["read_only"] is True


def test_cash_difference_is_reported_broker_minus_ledger():
    result = run(broker_cash=950, cash_tolerance=10)
    cash = result["details"].query("item_type == 'CASH'").iloc[0]
    assert cash["status"] == "CASH_MISMATCH"
    assert cash["difference"] == -50


def test_missing_and_extra_holdings_are_reported():
    result = run(ledger_positions={"BBCA": 10}, broker_positions={"TLKM": 5})
    holdings = result["details"].query("item_type == 'HOLDING'")
    statuses = dict(zip(holdings["ticker"], holdings["status"]))
    assert statuses == {"BBCA": "MISSING_IN_BROKER", "TLKM": "MISSING_IN_LEDGER"}


def test_quantity_mismatch_is_reported():
    result = run(broker_positions={"BBCA": 9, "TLKM": 5})
    bbca = result["details"].query("ticker == 'BBCA'").iloc[0]
    assert bbca["status"] == "QUANTITY_MISMATCH"
    assert bbca["difference"] == -1


def test_currency_mismatch_blocks_all_balance_comparisons():
    result = run(broker_currency="USD")
    assert result["status"] == "NOT_COMPARABLE"
    assert result["cash_difference"] is None
    assert set(result["details"]["status"]) == {"NOT_COMPARABLE"}


def test_date_mismatch_blocks_comparison_unless_within_explicit_tolerance():
    blocked = run(broker_as_of_date="2026-11-23")
    allowed = run(broker_as_of_date="2026-11-24", date_tolerance_days=1)
    assert blocked["comparable"] is False
    assert allowed["comparable"] is True


def test_duplicate_ticker_rows_are_rejected():
    duplicate = pd.DataFrame([{"ticker": "BBCA", "shares": 10}, {"ticker": "bbca", "shares": 2}])
    with pytest.raises(ValueError, match="duplikat"):
        run(broker_positions=duplicate)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "x"])
def test_invalid_cash_and_tolerances_are_rejected(value):
    with pytest.raises(ValueError):
        run(broker_cash=value)
    with pytest.raises(ValueError):
        run(cash_tolerance=value)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_invalid_share_balances_are_rejected(value):
    with pytest.raises(ValueError):
        run(broker_positions={"BBCA": value})


def test_empty_holdings_and_zero_cash_are_valid():
    result = run(ledger_cash=0, broker_cash=0, ledger_positions={}, broker_positions={})
    assert result["matched_count"] == 1
    assert result["exception_count"] == 0


def test_invalid_date_tolerance_is_rejected():
    with pytest.raises(ValueError, match="Date tolerance"):
        run(date_tolerance_days=1.5)
