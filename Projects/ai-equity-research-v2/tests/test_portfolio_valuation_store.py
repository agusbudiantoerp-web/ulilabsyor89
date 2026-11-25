import pandas as pd
import pytest

from portfolio_valuation_store import delete_valuations, list_valuations, save_valuations


def sample():
    return pd.DataFrame([
        {"date":"2026-01-01","portfolio_value":1000,"external_flow":0},
        {"date":"2026-02-01","portfolio_value":1100,"external_flow":0},
    ])


def test_valuation_snapshots_persist_and_are_owner_scoped(tmp_path):
    db=str(tmp_path/"valuations.sqlite")
    assert save_valuations("issuer|alice","main",sample(),currency="IDR",path=db)==2
    assert len(list_valuations("issuer|alice","main",path=db))==2
    assert list_valuations("issuer|bob","main",path=db).empty
    assert delete_valuations("issuer|bob","main",path=db)==0
    assert delete_valuations("issuer|alice","main",path=db)==2


def test_valuation_snapshots_upsert_by_date(tmp_path):
    db=str(tmp_path/"valuations.sqlite")
    save_valuations("owner","main",sample(),path=db)
    changed=sample()
    changed.loc[1,"portfolio_value"]=1200
    save_valuations("owner","main",changed,path=db)
    result=list_valuations("owner","main",path=db)
    assert len(result)==2
    assert result.iloc[1]["portfolio_value"]==1200


def test_valuation_snapshots_reject_duplicate_dates_and_invalid_values(tmp_path):
    db=str(tmp_path/"valuations.sqlite")
    duplicate=pd.DataFrame([
        {"date":"2026-01-01","portfolio_value":100,"external_flow":0},
        {"date":"2026-01-01","portfolio_value":101,"external_flow":0},
    ])
    with pytest.raises(ValueError,match="unik"):
        save_valuations("owner","main",duplicate,path=db)
    invalid=sample()
    invalid.loc[0,"portfolio_value"]=0
    with pytest.raises(ValueError,match="positif"):
        save_valuations("owner","main",invalid,path=db)
