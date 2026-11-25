import numpy as np
import pandas as pd
import pytest

from market_intelligence import (
    audit_fundamental_record, audit_price_history,
    classify_market_regime, relative_strength,
)


def bars(close):
    close = pd.Series(close, index=pd.bdate_range("2024-01-01", periods=len(close)))
    return pd.DataFrame({
        "Open": close * 0.999, "High": close * 1.01,
        "Low": close * 0.99, "Close": close, "Volume": 100_000,
    }, index=close.index)


def test_classifies_persistent_uptrend_as_bullish():
    values = np.linspace(100, 220, 320)
    result = classify_market_regime(bars(values))
    assert result["regime"] == "BULLISH"
    assert result["benchmark_close"] > result["ema200"]


def test_relative_strength_uses_matched_dates_and_reports_spread():
    asset = bars(np.linspace(100, 180, 300))
    benchmark = bars(np.linspace(100, 130, 300))
    result = relative_strength(asset, benchmark)
    assert result["matched_sessions"] == 300
    assert result["periods"]["1m"]["relative_strength_pct"] > 0


def test_price_quality_flags_invalid_ohlc():
    frame = bars(np.linspace(100, 150, 220))
    frame.iloc[-1, frame.columns.get_loc("High")] = 1
    result = audit_price_history(frame)
    assert result["status"] == "FAIL"
    assert any(item["severity"] == "ERROR" for item in result["checks"])


def test_negative_pe_is_warning_not_invalid_fundamental():
    result = audit_fundamental_record({"trailingPE": -4.0, "marketCap": 1000, "currency": "IDR"})
    assert result["status"] == "WARNING"
    assert result["invalid_fields"] == []



@pytest.mark.parametrize(
    "mutate, message",
    [
        ("missing", "nilai kosong atau non-numerik"),
        ("infinite", "non-finite"),
        ("zero", "harus positif"),
        ("duplicate", "tanggal harga mengandung tanggal duplikat"),
        ("invalid_date", "tanggal tidak valid"),
    ],
)
def test_market_regime_rejects_invalid_close_history(mutate, message):
    frame = bars(np.linspace(100, 220, 240))
    if mutate == "missing":
        frame.iloc[-1, frame.columns.get_loc("Close")] = np.nan
    elif mutate == "infinite":
        frame.iloc[-1, frame.columns.get_loc("Close")] = np.inf
    elif mutate == "zero":
        frame.iloc[-1, frame.columns.get_loc("Close")] = 0
    elif mutate == "duplicate":
        frame.index = list(frame.index[:-1]) + [frame.index[-2]]
    elif mutate == "invalid_date":
        frame.index = list(frame.index[:-1]) + ["not-a-date"]
    with pytest.raises(ValueError, match=message):
        classify_market_regime(frame)



def test_market_regime_sorts_valid_unsorted_close_dates_before_calculation():
    frame = bars(np.linspace(100, 220, 240)).iloc[::-1]
    result = classify_market_regime(frame)
    assert result["regime"] == "BULLISH"
    assert result["bar_date"] == "2024-11-29"



@pytest.mark.parametrize("age", [True, False, -1, 366, 1.5, "5", None])
def test_price_history_audit_rejects_invalid_staleness_threshold(age):
    with pytest.raises(ValueError, match="max_age_calendar_days"):
        audit_price_history(bars(np.linspace(100, 150, 220)), max_age_calendar_days=age)


def test_price_history_audit_fails_on_invalid_date_index():
    frame = bars(np.linspace(100, 150, 220))
    frame.index = list(frame.index[:-1]) + ["invalid-date"]
    result = audit_price_history(frame)
    assert result["status"] == "FAIL"
    assert any("tanggal tidak valid" in item["message"] for item in result["checks"])


def test_price_history_audit_flags_duplicate_dates():
    frame = bars(np.linspace(100, 150, 220))
    frame.index = list(frame.index[:-1]) + [frame.index[-2]]
    result = audit_price_history(frame)
    assert result["status"] == "WARNING"
    assert any("tanggal duplikat" in item["message"] for item in result["checks"])


def test_price_history_audit_accepts_timezone_aware_dates():
    frame = bars(np.linspace(100, 150, 220))
    frame.index = frame.index.tz_localize("Asia/Jakarta")
    result = audit_price_history(frame)
    assert result["status"] in {"PASS", "WARNING"}
    assert result["last_bar"] == "2024-11-01"
