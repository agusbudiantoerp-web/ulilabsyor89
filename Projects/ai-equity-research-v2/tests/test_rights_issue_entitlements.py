import pandas as pd
import pytest

from rights_issue_entitlements import estimate_rights_issue_entitlements


def rights_event(**overrides):
    event = {
        "ticker": "BBCA", "event_type": "RIGHTS_ISSUE",
        "event_date": "2026-12-12", "status": "CONFIRMED",
        "source": "Issuer prospectus", "retrieved_at": "2026-11-25T00:00:00Z",
        "rights_ratio": 0.25, "subscription_price": 500, "currency": "IDR",
    }
    event.update(overrides)
    return event


def test_rights_issue_estimates_entitlement_and_full_exercise_cash_after_split_and_sale():
    portfolio = [
        {"date": "2026-12-01", "event_type": "BUY", "amount": 100000, "ticker": "BBCA", "quantity": 1000, "price": 100},
        {"date": "2026-12-05", "event_type": "SPLIT", "amount": 0, "ticker": "BBCA", "quantity": 2},
        {"date": "2026-12-10", "event_type": "SELL", "amount": 100000, "ticker": "BBCA", "quantity": 200, "price": 500},
    ]
    result = estimate_rights_issue_entitlements(portfolio, [rights_event()])
    row = result["entitlements"].iloc[0]
    assert row["shares_at_record_date_estimate"] == pytest.approx(1800)
    assert row["estimated_rights_entitlement"] == pytest.approx(450)
    assert row["cash_required_if_fully_exercised_estimate"] == pytest.approx(225000)
    assert row["currency"] == "IDR"
    assert row["status"] == "ESTIMATE_ONLY"
    assert not bool(row["fractional_rights_need_broker_confirmation"])


def test_rights_issue_preserves_fractional_rights_without_silent_rounding():
    portfolio = [{"date": "2026-12-01", "event_type": "BUY", "amount": 100100, "ticker": "BBCA", "quantity": 1001, "price": 100}]
    result = estimate_rights_issue_entitlements(portfolio, [rights_event()])
    row = result["entitlements"].iloc[0]
    assert row["estimated_rights_entitlement"] == pytest.approx(250.25)
    assert bool(row["fractional_rights_need_broker_confirmation"])


def test_rights_issue_skips_unconfirmed_event():
    portfolio = [{"date": "2026-12-01", "event_type": "BUY", "amount": 100000, "ticker": "BBCA", "quantity": 1000, "price": 100}]
    result = estimate_rights_issue_entitlements(portfolio, [rights_event(status="ESTIMATED")])
    assert result["entitlements"].empty
    assert any("bukan CONFIRMED" in warning for warning in result["warnings"])


def test_rights_issue_skips_conflicting_duplicate_terms():
    portfolio = [{"date": "2026-12-01", "event_type": "BUY", "amount": 100000, "ticker": "BBCA", "quantity": 1000, "price": 100}]
    result = estimate_rights_issue_entitlements(portfolio, [rights_event(), rights_event(rights_ratio=0.5)])
    assert result["entitlements"].empty
    assert any("bertentangan" in warning for warning in result["warnings"])


def test_rights_issue_does_not_assume_zero_position_without_history():
    result = estimate_rights_issue_entitlements([], [rights_event()])
    assert result["entitlements"].empty
    assert any("tidak ada posisi awal" in warning for warning in result["warnings"])


def test_rights_issue_uses_initial_position_snapshot_when_ledger_has_no_trades():
    result = estimate_rights_issue_entitlements([], [rights_event()], initial_positions={"BBCA": 2000})
    row = result["entitlements"].iloc[0]
    assert row["shares_at_record_date_estimate"] == pytest.approx(2000)
    assert row["estimated_rights_entitlement"] == pytest.approx(500)


def test_rights_issue_rejects_negative_portfolio_position():
    portfolio = [{"date": "2026-12-01", "event_type": "SELL", "amount": 100, "ticker": "BBCA", "quantity": 1, "price": 100}]
    with pytest.raises(ValueError, match="posisi negatif"):
        estimate_rights_issue_entitlements(portfolio, [rights_event()])


def test_rights_issue_estimate_does_not_create_cash_or_share_ledger_events():
    portfolio = [{"date": "2026-12-01", "event_type": "BUY", "amount": 100000, "ticker": "BBCA", "quantity": 1000, "price": 100}]
    before = pd.DataFrame(portfolio).copy(deep=True)
    estimate_rights_issue_entitlements(portfolio, [rights_event()])
    pd.testing.assert_frame_equal(pd.DataFrame(portfolio), before)
    assert "RIGHTS_SUBSCRIPTION" not in set(pd.DataFrame(portfolio)["event_type"])


def test_rights_issue_collapses_identical_duplicate_event_rows():
    portfolio = [{"date": "2026-12-01", "event_type": "BUY", "amount": 100000, "ticker": "BBCA", "quantity": 1000, "price": 100}]
    result = estimate_rights_issue_entitlements(portfolio, [rights_event(), rights_event()])
    assert len(result["entitlements"]) == 1