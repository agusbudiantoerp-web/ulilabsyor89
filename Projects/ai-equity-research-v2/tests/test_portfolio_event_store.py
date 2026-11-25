import pytest

from portfolio_event_store import create_event, delete_event, list_events


def event():
    return {"date":"2026-01-01","event_type":"DEPOSIT","amount":1000,"ticker":"","notes":"opening"}


def test_portfolio_cashflow_events_persist_and_isolate_by_owner(tmp_path):
    db=str(tmp_path/"cashflows.sqlite")
    event_id=create_event("issuer|one",event(),path=db)
    assert len(list_events("issuer|one",path=db))==1
    assert list_events("issuer|two",path=db)==[]
    assert not delete_event("issuer|two",event_id,path=db)
    assert delete_event("issuer|one",event_id,path=db)
    assert list_events("issuer|one",path=db)==[]


def test_portfolio_cashflow_events_require_owner_and_fields(tmp_path):
    db=str(tmp_path/"cashflows.sqlite")
    with pytest.raises(ValueError,match="Owner dan event"):
        create_event("",event(),path=db)
    with pytest.raises(ValueError,match="wajib"):
        create_event("owner",{"date":"2026-01-01"},path=db)



@pytest.mark.parametrize("invalid", [
    {"date": "not-a-date", "event_type": "DEPOSIT", "amount": 1000},
    {"date": "2026-01-01", "event_type": "UNKNOWN", "amount": 1000},
    {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": "inf"},
    {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": -1},
    {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "BBCA", "quantity": 0, "price": 100},
    {"date": "2026-01-01", "event_type": "SELL", "amount": 1000, "ticker": "BBCA", "quantity": 1, "price": "nan"},
])
def test_portfolio_event_store_rejects_invalid_ledger_events(tmp_path, invalid):
    db = str(tmp_path / "cashflows.sqlite")
    with pytest.raises(ValueError):
        create_event("owner", invalid, path=db)
    assert list_events("owner", path=db) == []


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, "10", None])
def test_portfolio_event_store_requires_positive_integer_limit(tmp_path, limit):
    db = str(tmp_path / "cashflows.sqlite")
    with pytest.raises(ValueError, match="Limit"):
        list_events("owner", path=db, limit=limit)


def test_portfolio_event_store_normalizes_event_fields(tmp_path):
    db = str(tmp_path / "cashflows.sqlite")
    event_id = create_event("owner", {
        "date": "2026-01-01", "event_type": "deposit", "amount": "1000",
        "ticker": None, "notes": None,
    }, path=db)
    stored = list_events("owner", path=db)[0]
    assert stored["id"] == event_id
    assert stored["event_type"] == "DEPOSIT"
    assert stored["amount"] == 1000.0
    assert stored["date"].startswith("2026-01-01")
