import pandas as pd
import pytest

from dividend_entitlements import estimate_dividend_entitlements


def corporate_cycle(**overrides):
    rows = [
        {
            "ticker": "BBCA", "event_type": "DIVIDEND_DECLARATION",
            "event_date": "2026-12-01", "status": "CONFIRMED",
            "source": "Issuer filing", "retrieved_at": "2026-11-25T00:00:00Z",
            "amount": 100, "currency": "IDR",
        },
        {
            "ticker": "BBCA", "event_type": "EX_DIVIDEND",
            "event_date": "2026-12-10", "status": "CONFIRMED",
            "source": "Issuer filing", "retrieved_at": "2026-11-25T00:00:00Z",
        },
        {
            "ticker": "BBCA", "event_type": "RECORD_DATE",
            "event_date": "2026-12-12", "status": "CONFIRMED",
            "source": "Issuer filing", "retrieved_at": "2026-11-25T00:00:00Z",
        },
        {
            "ticker": "BBCA", "event_type": "PAY_DATE",
            "event_date": "2026-12-20", "status": "CONFIRMED",
            "source": "Issuer filing", "retrieved_at": "2026-11-25T00:00:00Z",
        },
    ]
    for index, changes in overrides.items():
        rows[int(index)].update(changes)
    return rows


def test_dividend_entitlement_uses_record_date_position_after_split_and_sell():
    portfolio = [
        {"date": "2026-12-01", "event_type": "BUY", "amount": 1000,
         "ticker": "BBCA", "quantity": 10, "price": 100},
        {"date": "2026-12-05", "event_type": "SPLIT", "amount": 0,
         "ticker": "BBCA", "quantity": 2},
        {"date": "2026-12-11", "event_type": "SELL", "amount": 500,
         "ticker": "BBCA", "quantity": 5, "price": 100},
    ]
    result = estimate_dividend_entitlements(portfolio, corporate_cycle())
    row = result["entitlements"].iloc[0]
    assert row["shares_at_record_date_estimate"] == pytest.approx(15)
    assert row["gross_dividend_per_share"] == pytest.approx(100)
    assert row["gross_entitlement_estimate"] == pytest.approx(1500)
    assert row["currency"] == "IDR"
    assert row["status"] == "ESTIMATE_ONLY"
    assert any("settlement" in warning.lower() for warning in result["warnings"])


def test_dividend_entitlement_requires_confirmed_record_date_and_pay_date():
    events = corporate_cycle()
    events[2]["status"] = "ESTIMATED"
    result = estimate_dividend_entitlements(
        [{"date": "2026-12-01", "event_type": "BUY", "amount": 1000,
          "ticker": "BBCA", "quantity": 10, "price": 100}],
        events,
    )
    assert result["entitlements"].empty
    assert any("RECORD_DATE CONFIRMED" in warning for warning in result["warnings"])


def test_dividend_entitlement_skips_conflicting_ex_date_duplicates():
    events = corporate_cycle()
    conflicting = dict(events[1])
    conflicting["currency"] = "USD"
    events.append(conflicting)
    result = estimate_dividend_entitlements([], events)
    assert result["entitlements"].empty
    assert any("EX_DIVIDEND CONFIRMED" in warning for warning in result["warnings"])


def test_dividend_entitlement_rejects_negative_position_from_ledger():
    portfolio = [
        {"date": "2026-12-01", "event_type": "SELL", "amount": 100,
         "ticker": "BBCA", "quantity": 1, "price": 100},
    ]
    with pytest.raises(ValueError, match="posisi negatif"):
        estimate_dividend_entitlements(portfolio, corporate_cycle())


def test_dividend_entitlement_does_not_create_cash_ledger_events():
    portfolio = [
        {"date": "2026-12-01", "event_type": "BUY", "amount": 1000,
         "ticker": "BBCA", "quantity": 10, "price": 100},
    ]
    result = estimate_dividend_entitlements(portfolio, corporate_cycle())
    assert "DIVIDEND" not in set(
        pd.DataFrame(portfolio)["event_type"]
    )
    assert result["entitlements"].iloc[0]["status"] == "ESTIMATE_ONLY"


def test_dividend_entitlement_does_not_assume_zero_without_position_history():
    result = estimate_dividend_entitlements([], corporate_cycle())
    assert result["entitlements"].empty
    assert any("tidak ada posisi awal" in warning for warning in result["warnings"])
