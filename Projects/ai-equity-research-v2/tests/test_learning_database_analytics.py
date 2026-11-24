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
    scan_id = save_scan(scan, db_path=db_path)
    return db_path, scan_id


def test_outcome_summary_includes_median_and_segments(tmp_path):
    db_path, _ = _seed(tmp_path)

    # Three completed outcomes for the same ruleset/signal segment.
    from daily_signal_storage import signal_history
    rows = signal_history(limit=10, db_path=db_path)
    ids = {row["ticker"]: row["id"] for row in rows}
    record_outcome(ids["AAA.JK"], 1, "2026-01-06", 110.0, db_path=db_path)
    record_outcome(ids["AAA.JK"], 3, "2026-01-08", 90.0, db_path=db_path)
    record_outcome(ids["BBB.JK"], 1, "2026-01-06", 220.0, db_path=db_path)

    summary = outcome_summary(db_path=db_path)
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


def test_outcome_summary_does_not_count_unavailable_horizons(tmp_path):
    db_path, _ = _seed(tmp_path)
    summary = outcome_summary(db_path=db_path)
    assert summary == []
