import pytest

from daily_signal_storage import outcome_summary, record_outcome, save_scan


def _seed(tmp_path):
    db_path = str(tmp_path / "learning.sqlite3")
    scan = {
        "counts": {"scanned": 2, "failed": 0},
        "results": [
            {
                "market": "IDX", "ticker": "AAA.JK", "bar_date": "2026-01-05",
                "signal": "BUY_CANDIDATE", "score": 80, "close": 100.0,
                "ruleset_version": "v1",
            },
            {
                "market": "IDX", "ticker": "BBB.JK", "bar_date": "2026-01-05",
                "signal": "WATCH", "score": 60, "close": 200.0,
                "ruleset_version": "v2",
            },
        ],
    }
    scan_id = save_scan(scan, db_path=db_path, owner_id='test-owner')
    return db_path, scan_id


def test_outcome_summary_includes_median_and_segments(tmp_path):
    db_path, _ = _seed(tmp_path)

    # Three completed outcomes for the same ruleset/signal segment.
    from daily_signal_storage import signal_history
    rows = signal_history(limit=10, db_path=db_path, owner_id='test-owner')
    ids = {row["ticker"]: row["id"] for row in rows}
    record_outcome(ids["AAA.JK"], 1, "2026-01-06", 110.0, db_path=db_path, owner_id='test-owner')
    record_outcome(ids["AAA.JK"], 3, "2026-01-08", 90.0, db_path=db_path, owner_id='test-owner')
    record_outcome(ids["BBB.JK"], 1, "2026-01-06", 220.0, db_path=db_path, owner_id='test-owner')

    summary = outcome_summary(db_path=db_path, owner_id='test-owner')
    overall_1d = next(
        row for row in summary
        if row["horizon"] == 1 and row["ruleset_version"] == "ALL"
        and row["signal_type"] == "ALL"
    )
    assert overall_1d["observations"] == 2
    assert overall_1d["avg_forward_return_pct"] == pytest.approx(10.0)
    assert overall_1d["median_forward_return_pct"] == pytest.approx(10.0)
    assert overall_1d["positive_rate_pct"] == pytest.approx(100.0)

    buy_v1 = next(
        row for row in summary
        if row["horizon"] == 1 and row["ruleset_version"] == "v1"
        and row["signal_type"] == "BUY_CANDIDATE"
    )
    assert buy_v1["observations"] == 1
    assert buy_v1["median_forward_return_pct"] == pytest.approx(10.0)


def test_outcomes_persist_owner_identity_and_reject_cross_owner_access(tmp_path):
    from daily_signal_storage import signal_history
    db_path, _ = _seed(tmp_path)
    rows = signal_history(limit=10, db_path=db_path, owner_id="test-owner")
    signal_id = next(row["id"] for row in rows if row["ticker"] == "AAA.JK")

    with pytest.raises(ValueError, match="Signal tidak ditemukan"):
        record_outcome(
            signal_id, 1, "2026-01-06", 110.0,
            db_path=db_path, owner_id="another-owner",
        )

    record_outcome(
        signal_id, 1, "2026-01-06", 110.0,
        db_path=db_path, owner_id="test-owner",
    )
    import sqlite3
    with sqlite3.connect(db_path) as db:
        stored_owner = db.execute(
            "SELECT owner_id FROM outcomes WHERE signal_id=? AND horizon=1",
            (signal_id,),
        ).fetchone()[0]
    assert stored_owner == "test-owner"
    assert outcome_summary(db_path=db_path, owner_id="another-owner") == []


def test_outcome_summary_does_not_count_unavailable_horizons(tmp_path):
    db_path, _ = _seed(tmp_path)
    summary = outcome_summary(db_path=db_path, owner_id='test-owner')
    assert summary == []


def test_record_outcome_rejects_invalid_price_and_non_forward_date(tmp_path):
    db_path, _ = _seed(tmp_path)
    from daily_signal_storage import signal_history
    rows = signal_history(limit=10, db_path=db_path, owner_id='test-owner')
    signal_id = next(row["id"] for row in rows if row["ticker"] == "AAA.JK")
    with pytest.raises(ValueError, match="finite dan positif"):
        record_outcome(signal_id, 1, "2026-01-06", float("inf"), db_path=db_path, owner_id='test-owner')
    with pytest.raises(ValueError, match="setelah tanggal signal"):
        record_outcome(signal_id, 1, "2026-01-05", 101.0, db_path=db_path, owner_id='test-owner')
    with pytest.raises(ValueError, match="ISO"):
        record_outcome(signal_id, 1, "not-a-date", 101.0, db_path=db_path, owner_id='test-owner')
