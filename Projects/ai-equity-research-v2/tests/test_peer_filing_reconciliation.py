import pandas as pd
import pytest

from peer_filing_reconciliation import reconcile_peer_filing_records


def provider_record():
    return {
        "ticker": "BBCA", "currency": "IDR", "fiscal_year_end": "2025-12-31",
        "totalRevenue": 1000, "ebitda": 300, "totalDebt": 200,
        "totalCash": 100, "sharesOutstanding": 1000, "bookValue": 900,
    }


def filing_record(**overrides):
    row = {
        "ticker": "BBCA", "period_end": "2025-12-31", "currency": "IDR",
        "source_name": "Issuer annual report", "source_url": "https://example.com/report.pdf",
        "total_revenue": 1000, "ebitda": 300, "total_debt": 200,
        "cash": 100, "shares_outstanding": 1000, "book_value_per_share": 900,
    }
    row.update(overrides)
    return row


def test_peer_filing_reconciliation_matches_source_values_and_period():
    result = reconcile_peer_filing_records([provider_record()], [filing_record()])
    assert result["metric_count"] == 6
    assert result["matched_count"] == 6
    assert result["mismatch_count"] == 0
    assert set(result["details"]["status"]) == {"MATCH"}
    assert result["details"].iloc[0]["source_url"].startswith("https://")


def test_peer_filing_reconciliation_flags_value_mismatch():
    result = reconcile_peer_filing_records(
        [provider_record()], [filing_record(total_revenue=700)], tolerance_pct=5,
    )
    row = result["details"].loc[result["details"]["metric"].eq("total_revenue")].iloc[0]
    assert row["status"] == "MISMATCH"
    assert row["variance_pct"] > 5


def test_peer_filing_reconciliation_flags_period_and_currency_mismatch():
    result = reconcile_peer_filing_records(
        [provider_record()],
        [filing_record(period_end="2024-12-31", currency="USD")],
    )
    assert set(result["details"]["status"]) == {"PERIOD_MISMATCH"}


def test_peer_filing_reconciliation_reports_missing_ticker_and_provider_values():
    result = reconcile_peer_filing_records(
        [{**provider_record(), "totalRevenue": None}, {**provider_record(), "ticker": "BBRI", "totalRevenue": None}],
        [filing_record()],
    )
    assert (result["details"].loc[result["details"]["ticker"].eq("BBRI"), "status"] == "FILING_MISSING").all()
    assert (result["details"].loc[result["details"]["metric"].eq("total_revenue") & result["details"]["ticker"].eq("BBCA"), "status"] == "PROVIDER_MISSING").all()


def test_peer_filing_reconciliation_validates_source_and_columns():
    with pytest.raises(ValueError, match="source_url"):
        reconcile_peer_filing_records([provider_record()], [filing_record(source_url="not-a-url")])
    with pytest.raises(ValueError, match="Kolom filing wajib"):
        reconcile_peer_filing_records([provider_record()], [{"ticker": "BBCA"}])



def test_peer_filing_reconciliation_flags_currency_mismatch_separately():
    result = reconcile_peer_filing_records(
        [provider_record()],
        [filing_record(currency="USD")],
    )
    assert set(result["details"]["status"]) == {"CURRENCY_MISMATCH"}
