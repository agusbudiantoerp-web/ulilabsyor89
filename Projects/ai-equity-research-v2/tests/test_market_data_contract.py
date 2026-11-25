from datetime import datetime, timezone

import pandas as pd

from market_data_contract import build_market_data_metadata


def sample_bars():
    idx = pd.bdate_range("2026-11-02", periods=5)
    return pd.DataFrame({
        "Open": [10, 11, 12, 13, 14],
        "High": [11, 12, 13, 14, 15],
        "Low": [9, 10, 11, 12, 13],
        "Close": [10.5, 11.5, 12.5, 13.5, 14.5],
        "Volume": [100, 110, 120, 130, 140],
    }, index=idx)


def test_market_data_contract_records_provenance_and_adjustment_mode():
    stamp = datetime(2026, 11, 9, tzinfo=timezone.utc)
    result = build_market_data_metadata(
        sample_bars(),
        {"source": "Yahoo Finance", "ticker": "BBCA.JK", "market": "IDX",
         "exchange": "Indonesia Stock Exchange", "currency": "IDR"},
        adjustment_mode="auto_adjusted", retrieved_at=stamp, as_of=stamp,
    )
    assert result["source"] == "Yahoo Finance"
    assert result["source_ticker"] == "BBCA.JK"
    assert result["currency"] == "IDR"
    assert result["price_basis"] == "adjusted_ohlc"
    assert result["quality_status"] == "PASS"
    assert result["bar_count"] == 5


def test_market_data_contract_flags_stale_data():
    result = build_market_data_metadata(
        sample_bars(), retrieved_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
        as_of=datetime(2026, 11, 20, tzinfo=timezone.utc), max_age_calendar_days=5,
    )
    assert result["quality_status"] == "WARNING"
    assert any(item["code"] == "STALE_DATA" for item in result["quality_checks"])


def test_market_data_contract_flags_invalid_ohlc_and_negative_volume():
    bars = sample_bars()
    bars.iloc[0, bars.columns.get_loc("High")] = 1
    bars.iloc[1, bars.columns.get_loc("Volume")] = -1
    stamp = datetime(2026, 11, 9, tzinfo=timezone.utc)
    result = build_market_data_metadata(bars, retrieved_at=stamp, as_of=stamp)
    codes = {item["code"] for item in result["quality_checks"]}
    assert result["quality_status"] == "FAIL"
    assert "INVALID_OHLC_RELATION" in codes
    assert "NEGATIVE_VOLUME" in codes


def test_market_data_contract_flags_missing_columns():
    stamp = datetime(2026, 11, 9, tzinfo=timezone.utc)
    result = build_market_data_metadata(
        pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2026-11-09"])),
        retrieved_at=stamp, as_of=stamp,
    )
    assert result["quality_status"] == "FAIL"
    assert result["quality_checks"][0]["code"] == "MISSING_COLUMNS"
