import math

import pytest

from daily_signal_portfolio import allocate_candidates
from daily_signal_risk import build_trade_plan, validate_entry


def test_trade_plan_rejects_non_finite_and_invalid_entry_buffer():
    with pytest.raises(ValueError, match="finite"):
        build_trade_plan(float("nan"), 10, 1_000_000)
    with pytest.raises(ValueError, match="buffer"):
        build_trade_plan(100, 10, 1_000_000, entry_buffer_pct=100)
    with pytest.raises(ValueError, match="finite"):
        validate_entry(float("inf"), 90, 110)


def test_trade_plan_rejects_share_count_overflow():
    with pytest.raises(ValueError, match="Jumlah saham"):
        build_trade_plan(0.02, 1e-15, 1e300, risk_pct=1)


def test_idx_candidate_allocation_rounds_down_to_board_lots():
    candidates = [
        {"market": "IDX", "ticker": "AAA", "signal": "BUY_CANDIDATE",
         "score": 90, "close": 1000, "atr14": 10},
        {"market": "US", "ticker": "BBB", "signal": "BUY_CANDIDATE",
         "score": 80, "close": 10, "atr14": 1},
    ]
    result = allocate_candidates(candidates, 100_000_000)
    idx = next(item for item in result["positions"] if item["market"] == "IDX")
    us = next(item for item in result["positions"] if item["market"] == "US")
    assert idx["plan"]["shares"] % 100 == 0
    assert idx["plan"]["lots"] == idx["plan"]["shares"] // 100
    assert idx["plan"]["lot_size"] == 100
    assert us["plan"]["lot_size"] == 1
    assert result["exposure_pct"] <= 60


def test_candidate_allocation_rejects_duplicate_and_skips_bad_inputs():
    candidates = [
        {"market": "IDX", "ticker": "AAA", "signal": "BUY_CANDIDATE",
         "score": 90, "close": 1000, "atr14": 10},
        {"market": "IDX", "ticker": "AAA", "signal": "BUY_CANDIDATE",
         "score": 80, "close": 1000, "atr14": 10},
        {"market": "IDX", "ticker": "BAD", "signal": "BUY_CANDIDATE",
         "score": 70, "close": float("nan"), "atr14": 10},
        None,
    ]
    result = allocate_candidates(candidates, 100_000_000)
    assert len(result["positions"]) == 1
    assert len(result["skipped"]) == 3


def test_candidate_allocation_rejects_invalid_limits():
    with pytest.raises(ValueError, match="finite"):
        allocate_candidates([], float("inf"))
    with pytest.raises(ValueError, match="jumlah posisi"):
        allocate_candidates([], 1_000_000, max_positions=0)
