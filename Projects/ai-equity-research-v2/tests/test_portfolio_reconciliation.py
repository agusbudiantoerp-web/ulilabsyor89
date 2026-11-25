import pandas as pd
import pytest

from portfolio_reconciliation import reconcile_broker_statement


def internal_rows():
    return [
        {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
        {"date": "2026-01-03", "event_type": "DIVIDEND", "amount": 50, "ticker": "BBCA"},
        {"date": "2026-01-04", "event_type": "FEE", "amount": 5},
    ]


def test_broker_reconciliation_matches_events_within_date_tolerance():
    result = reconcile_broker_statement(
        internal_rows(),
        [
            {"date": "2026-01-02", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
            {"date": "2026-01-03", "event_type": "DIVIDEND", "amount": 50, "ticker": "BBCA"},
            {"date": "2026-01-04", "event_type": "FEE", "amount": 5},
        ],
        date_tolerance_days=1,
    )
    assert result["matched_count"] == 3
    assert result["mismatch_count"] == 0
    assert result["missing_in_broker_count"] == 0
    assert result["unexpected_in_broker_count"] == 0


def test_broker_reconciliation_reports_amount_quantity_and_price_mismatches():
    result = reconcile_broker_statement(
        [internal_rows()[0]],
        [{"date": "2026-01-01", "event_type": "BUY", "amount": 900, "ticker": "BBCA", "quantity": 9, "price": 100}],
    )
    assert result["mismatch_count"] == 1
    assert result["details"].iloc[0]["status"] == "AMOUNT_MISMATCH"


def test_broker_reconciliation_reports_missing_and_unexpected_events():
    result = reconcile_broker_statement(
        [internal_rows()[0]],
        [
            {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
            {"date": "2026-01-02", "event_type": "SELL", "amount": 200, "ticker": "BBCA", "quantity": 2, "price": 100},
        ],
    )
    assert result["matched_count"] == 1
    assert result["missing_in_broker_count"] == 0
    assert result["unexpected_in_broker_count"] == 1
    assert "UNEXPECTED_IN_BROKER" in result["status_counts"]


def test_broker_reconciliation_flags_large_date_difference():
    result = reconcile_broker_statement(
        [internal_rows()[0]],
        [{"date": "2026-01-10", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100}],
        date_tolerance_days=1,
    )
    assert result["details"].iloc[0]["status"] == "DATE_MISMATCH"


def test_broker_reconciliation_validates_tolerances_and_supports_empty_ledgers():
    with pytest.raises(ValueError, match="date_tolerance_days"):
        reconcile_broker_statement([], [], date_tolerance_days=31)
    result = reconcile_broker_statement([], [])
    assert result["internal_event_count"] == 0
    assert result["broker_event_count"] == 0
    assert result["details"].empty

@pytest.mark.parametrize("parameter", [
    "amount_tolerance_pct", "price_tolerance_pct", "quantity_tolerance",
])
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "not-a-number", True])
def test_broker_reconciliation_rejects_invalid_numeric_tolerances(parameter, value):
    with pytest.raises(ValueError, match=parameter):
        reconcile_broker_statement([], [], **{parameter: value})


@pytest.mark.parametrize("value", [True, -1, 1.5, 31, "1"])
def test_broker_reconciliation_requires_integer_date_tolerance(value):
    with pytest.raises(ValueError, match="date_tolerance_days"):
        reconcile_broker_statement([], [], date_tolerance_days=value)


@pytest.mark.parametrize("value", [pd.NA, 1.0, float("inf"), "1"])
def test_broker_reconciliation_rejects_non_integral_date_tolerance(value):
    with pytest.raises(ValueError, match="date_tolerance_days"):
        reconcile_broker_statement([], [], date_tolerance_days=value)


@pytest.mark.parametrize("parameter", ["amount_tolerance_pct", "price_tolerance_pct", "quantity_tolerance"])
def test_broker_reconciliation_rejects_numpy_boolean_tolerances(parameter):
    import numpy as np
    with pytest.raises(ValueError, match=parameter):
        reconcile_broker_statement([], [], **{parameter: np.bool_(True)})


def test_broker_reconciliation_accepts_numpy_integer_date_tolerance():
    import numpy as np
    result = reconcile_broker_statement([], [], date_tolerance_days=np.int64(1))
    assert result["internal_event_count"] == 0


def test_broker_reconciliation_preserves_exact_match_when_earlier_row_has_only_nearby_candidate():
    internal = [
        {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
        {"date": "2026-01-02", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
    ]
    broker = [
        {"date": "2026-01-02", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 10, "price": 100},
    ]
    result = reconcile_broker_statement(internal, broker, date_tolerance_days=1)
    assert result["matched_count"] == 1
    assert result["missing_in_broker_count"] == 1
    matched = result["details"].loc[result["details"]["status"] == "MATCH"].iloc[0]
    missing = result["details"].loc[result["details"]["status"] == "MISSING_IN_BROKER"].iloc[0]
    assert pd.Timestamp(matched["internal_date"]) == pd.Timestamp("2026-01-02")
    assert pd.Timestamp(missing["internal_date"]) == pd.Timestamp("2026-01-01")
