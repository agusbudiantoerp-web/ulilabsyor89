import numpy as np
import pandas as pd

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
