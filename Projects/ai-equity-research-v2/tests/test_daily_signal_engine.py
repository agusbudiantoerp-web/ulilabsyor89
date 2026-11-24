import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import pytest
from daily_signal_engine import calculate_indicators,evaluate_signal
from daily_signal_risk import build_trade_plan,validate_entry
from daily_signal_storage import initialize,save_scan,latest_scan,signal_history

def sample_bars(n=260):
    idx=pd.bdate_range("2025-01-01",periods=n)
    close=np.linspace(100,180,n)+np.sin(np.arange(n)/5)*2
    return pd.DataFrame({"Open":close*.995,"High":close*1.02,"Low":close*.98,
      "Close":close,"Volume":np.full(n,100000)},index=idx)

def test_indicators_created():
    x=calculate_indicators(sample_bars())
    for col in ["EMA9","EMA21","RSI14","MACD","MACD_SIGNAL","ATR14","REL_VOLUME","SMA50"]:
        assert col in x and x[col].notna().any()

def test_signal_schema_and_score():
    x=sample_bars()
    result=evaluate_signal(x,{"market":"IDX","ticker":"TEST.JK","currency":"IDR"},
      config={"min_relative_volume":0.5,"max_bar_age_days":1000},
      as_of=pd.Timestamp(x.index[-1]).to_pydatetime())
    assert result["signal"] in {"BUY_CANDIDATE","WATCH","NO_TRADE"}
    assert 0<=result["score"]<=100
    assert result["stop_loss"]<result["close"]<result["target"]

def test_risk_plan_and_entry_validation():
    plan=build_trade_plan(100,4,100000,1)
    assert plan["shares"]>0 and plan["stop_loss"]<100<plan["target"]
    assert validate_entry(100,99,101)["valid"]
    assert not validate_entry(105,99,101)["valid"]

def test_sqlite_persistence(tmp_path):
    path=str(tmp_path/"signals.db")
    scan={"counts":{"scanned":1,"failed":0},"results":[{"market":"US","ticker":"AAPL","bar_date":"2026-01-01","signal":"WATCH","score":55,"close":100}]}
    save_scan(scan,path,owner_id='test-owner')
    assert latest_scan(path,owner_id='test-owner')["counts"]["scanned"]==1
    assert len(signal_history(db_path=path,owner_id='test-owner'))==1

def test_invalid_ohlc_raises():
    with pytest.raises(ValueError):
        calculate_indicators(pd.DataFrame({"Close":[1,2]}))
