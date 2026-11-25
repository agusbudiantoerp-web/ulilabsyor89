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
