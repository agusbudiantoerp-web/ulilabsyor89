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
