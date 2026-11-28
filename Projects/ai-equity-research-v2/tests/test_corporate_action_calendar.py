from datetime import datetime, timezone

import pandas as pd
import pytest

from corporate_action_calendar import normalize_corporate_events


def base_event(**overrides):
    item = {
        "ticker": "BBCA", "event_type": "DIVIDEND_DECLARATION",
        "event_date": "2026-12-01T00:00:00Z", "status": "CONFIRMED",
        "source": "Issuer filing", "retrieved_at": "2026-11-25T00:00:00Z",
        "source_url": "https://example.invalid/filing", "currency": "IDR", "amount": 200,
    }
    item.update(overrides)
    return item


def test_calendar_preserves_provenance_and_confirmed_status():
    result = normalize_corporate_events(
        [base_event()], as_of=datetime(2026, 11, 25, tzinfo=timezone.utc)
    )
    row = result["events"].iloc[0]
    assert row["ticker"] == "BBCA"
    assert row["status"] == "CONFIRMED"
    assert row["source"] == "Issuer filing"
    assert not row["stale"]


def test_calendar_flags_estimates_stale_and_duplicates():
    old = base_event(status="ESTIMATED", retrieved_at="2026-01-01T00:00:00Z")
    result = normalize_corporate_events(
        [old, old], as_of=datetime(2026, 11, 25, tzinfo=timezone.utc), stale_after_days=30
    )
    assert result["events"]["stale"].all()
    assert result["events"]["duplicate_event"].all()
    assert len(result["warnings"]) == 3


def test_calendar_rejects_unknown_status_and_invalid_date():
    with pytest.raises(ValueError, match="Event type/status"):
        normalize_corporate_events([base_event(status="MAYBE")])
    with pytest.raises(ValueError, match="Tanggal event"):
        normalize_corporate_events([base_event(event_date="not-a-date")])


def test_calendar_rejects_invalid_split_ratio():
    with pytest.raises(ValueError, match="split ratio"):
        normalize_corporate_events([base_event(event_type="STOCK_SPLIT", split_ratio=0)])


def test_calendar_requires_source_and_stock_split_ratio():
    with pytest.raises(ValueError, match="sumber event"):
        normalize_corporate_events([base_event(source=" ")])
    with pytest.raises(ValueError, match="Split ratio wajib"):
        normalize_corporate_events([base_event(event_type="STOCK_SPLIT")])



def test_calendar_rejects_non_finite_amount_and_split_ratio():
    with pytest.raises(ValueError, match="amount harus berupa angka finite"):
        normalize_corporate_events([base_event(amount=float("inf"))])
    with pytest.raises(ValueError, match="split_ratio harus berupa angka finite"):
        normalize_corporate_events([base_event(event_type="STOCK_SPLIT", split_ratio=float("inf"))])


def test_calendar_rejects_malformed_source_url_when_provided():
    with pytest.raises(ValueError, match="source_url harus berupa URL"):
        normalize_corporate_events([base_event(source_url="issuer-portal/report.pdf")])


@pytest.mark.parametrize("threshold", [-1, 1.5, float("inf"), "invalid"])
def test_calendar_rejects_invalid_staleness_threshold(threshold):
    with pytest.raises(ValueError, match="stale_after_days"):
        normalize_corporate_events([base_event()], stale_after_days=threshold)


def test_calendar_rejects_malformed_numeric_fields_instead_of_silently_dropping_them():
    with pytest.raises(ValueError, match="amount harus berupa angka valid"):
        normalize_corporate_events([base_event(amount="not-a-number")])
    with pytest.raises(ValueError, match="split_ratio harus berupa angka valid"):
        normalize_corporate_events([
            base_event(event_type="STOCK_SPLIT", split_ratio="two-for-one")
        ])


def test_calendar_rejects_numpy_boolean_amount():
    import numpy as np
    with pytest.raises(ValueError, match="amount"):
        normalize_corporate_events([base_event(amount=np.bool_(True))])


def test_calendar_preserves_local_exchange_date_for_timezone_aware_event():
    event = base_event(event_date="2026-12-01T00:15:00+07:00")
    result = normalize_corporate_events([event])
    assert result["events"].iloc[0]["event_date"] == pd.Timestamp("2026-12-01")


def test_calendar_marks_same_local_day_as_duplicate_across_offsets():
    first = base_event(event_date="2026-12-01T00:15:00+07:00")
    second = base_event(event_date="2026-12-01T08:00:00+07:00")
    result = normalize_corporate_events([first, second])
    assert result["events"]["duplicate_event"].all()


@pytest.mark.parametrize("threshold", [True, 1.0])
def test_calendar_rejects_boolean_or_float_staleness_threshold(threshold):
    with pytest.raises(ValueError, match="stale_after_days"):
        normalize_corporate_events([base_event()], stale_after_days=threshold)



def test_calendar_exposes_confirmed_and_cancelled_status_flags():
    result = normalize_corporate_events([
        base_event(status="CONFIRMED"),
        base_event(event_type="EX_DIVIDEND", status="CANCELLED"),
    ])
    rows = result["events"].set_index("event_type")
    assert bool(rows.loc["DIVIDEND_DECLARATION", "status_is_confirmed"])
    assert not bool(rows.loc["DIVIDEND_DECLARATION", "status_is_cancelled"])
    assert not bool(rows.loc["EX_DIVIDEND", "status_is_confirmed"])
    assert bool(rows.loc["EX_DIVIDEND", "status_is_cancelled"])


def test_calendar_flags_conflicting_duplicate_corporate_action_details():
    first = base_event(event_type="STOCK_SPLIT", split_ratio=2)
    second = base_event(event_type="STOCK_SPLIT", split_ratio=3)
    result = normalize_corporate_events([first, second])
    assert result["events"]["duplicate_event"].all()
    assert result["events"]["conflicting_duplicate"].all()
    assert any("saling bertentangan" in warning for warning in result["warnings"])


def test_calendar_does_not_flag_identical_duplicate_details_as_conflicting():
    event = base_event(event_type="STOCK_SPLIT", split_ratio=2)
    result = normalize_corporate_events([event, event])
    assert result["events"]["duplicate_event"].all()
    assert not result["events"]["conflicting_duplicate"].any()


def test_calendar_validates_and_preserves_rights_issue_terms():
    event = base_event(
        event_type="RIGHTS_ISSUE", rights_ratio=0.5,
        subscription_price=1250, currency="IDR",
    )
    row = normalize_corporate_events([event])["events"].iloc[0]
    assert row["rights_ratio"] == pytest.approx(0.5)
    assert row["subscription_price"] == pytest.approx(1250)


@pytest.mark.parametrize("changes", [
    {"rights_ratio": 0}, {"rights_ratio": -0.5},
    {"subscription_price": 0}, {"subscription_price": -1},
    {"currency": ""},
])
def test_calendar_rejects_incomplete_or_invalid_rights_issue_terms(changes):
    event = base_event(event_type="RIGHTS_ISSUE", rights_ratio=0.5, subscription_price=100, currency="IDR")
    event.update(changes)
    with pytest.raises(ValueError):
        normalize_corporate_events([event])


def test_calendar_flags_conflicting_rights_issue_ratio_or_subscription_price():
    first = base_event(event_type="RIGHTS_ISSUE", rights_ratio=0.5, subscription_price=100, currency="IDR")
    second = dict(first, rights_ratio=0.25)
    result = normalize_corporate_events([first, second])
    assert result["events"]["conflicting_duplicate"].all()

def test_calendar_normalizes_currency_codes_before_duplicate_comparison():
    first = base_event(event_type="RIGHTS_ISSUE", rights_ratio=0.5, subscription_price=100, currency="idr")
    second = dict(first, currency="IDR")
    result = normalize_corporate_events([first, second])
    assert result["events"]["currency"].eq("IDR").all()
    assert not result["events"]["conflicting_duplicate"].any()