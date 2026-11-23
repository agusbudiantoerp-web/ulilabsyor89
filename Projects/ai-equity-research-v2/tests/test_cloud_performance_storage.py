from daily_signal_storage import (
    backend_name, get_pending_outcomes, latest_scan, outcome_summary,
    record_outcome, save_scan, signal_history,
)


def _scan():
    return {
        "counts": {"scanned": 1, "failed": 0, "success": 1, "buy_candidate": 1, "watch": 0},
        "results": [{
            "market": "IDX", "ticker": "TPIA.JK", "bar_date": "2026-11-20",
            "signal": "BUY_CANDIDATE", "score": 80, "ruleset_version": "1.0.0", "close": 1155.0,
            "entry_low": 1143.45, "entry_high": 1166.55, "stop_loss": 1100.0,
            "target": 1254.0, "reward_risk": 1.8,
        }],
        "errors": [],
    }


def test_sqlite_scan_and_outcome_lifecycle(tmp_path):
    db_path = str(tmp_path / "performance.sqlite3")
    scan = _scan()
    scan_id = save_scan(scan, db_path=db_path)

    assert backend_name(db_path) == "SQLite"
    assert latest_scan(db_path=db_path)["counts"]["scanned"] == 1
    assert latest_scan(db_path=db_path)["scan_id"] == scan_id

    history = signal_history(db_path=db_path)
    assert len(history) == 1
    assert history[0]["ruleset_version"] == "1.0.0"
    signal_id = history[0]["id"]

    pending = get_pending_outcomes(db_path=db_path)
    assert pending[0]["missing_horizons"] == [1, 3, 5, 10, 20]

    record_outcome(signal_id, 1, "2026-11-23", 1178.1, db_path=db_path)
    record_outcome(signal_id, 3, "2026-11-25", 1190.0, db_path=db_path)

    history = signal_history(db_path=db_path)
    assert round(history[0]["outcome_1d_return_pct"], 2) == 2.0
    assert history[0]["outcome_3d_return_pct"] is not None
    assert history[0]["outcome_5d_return_pct"] is None

    pending = get_pending_outcomes(db_path=db_path)
    assert pending[0]["missing_horizons"] == [5, 10, 20]

    record_outcome(signal_id, 5, "2026-11-27", 1200.0, db_path=db_path)
    record_outcome(signal_id, 10, "2026-12-04", 1210.0, db_path=db_path)
    record_outcome(signal_id, 20, "2026-12-18", 1230.0, db_path=db_path)
    pending = get_pending_outcomes(db_path=db_path)
    assert pending == []

    summary = outcome_summary(db_path=db_path)
    assert [row["horizon"] for row in summary] == [1, 3, 5, 10, 20]


def test_record_outcome_rejects_unsupported_horizon(tmp_path):
    db_path = str(tmp_path / "performance.sqlite3")
    scan_id = save_scan(_scan(), db_path=db_path)
    signal_id = signal_history(db_path=db_path)[0]["id"]
    try:
        record_outcome(signal_id, 2, "2026-11-24", 1160.0, db_path=db_path)
    except ValueError as exc:
        assert "1, 3, 5, 10, atau 20" in str(exc)
    else:
        raise AssertionError("Horizon selain 1, 3, 5, 10, atau 20 seharusnya ditolak.")
