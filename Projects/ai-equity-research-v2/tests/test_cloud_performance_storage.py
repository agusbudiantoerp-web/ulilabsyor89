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
    scan_id = save_scan(scan, db_path=db_path, owner_id='test-owner')

    assert backend_name(db_path) == "SQLite"
    assert latest_scan(db_path=db_path, owner_id='test-owner')["counts"]["scanned"] == 1
    assert latest_scan(db_path=db_path, owner_id='test-owner')["scan_id"] == scan_id

    history = signal_history(db_path=db_path, owner_id='test-owner')
    assert len(history) == 1
    assert history[0]["ruleset_version"] == "1.0.0"
    signal_id = history[0]["id"]

    pending = get_pending_outcomes(db_path=db_path, owner_id='test-owner')
    assert pending[0]["missing_horizons"] == [1, 3, 5, 10, 20]

    record_outcome(signal_id, 1, "2026-11-23", 1178.1, db_path=db_path, owner_id='test-owner')
    record_outcome(signal_id, 3, "2026-11-25", 1190.0, db_path=db_path, owner_id='test-owner')

    history = signal_history(db_path=db_path, owner_id='test-owner')
    assert round(history[0]["outcome_1d_return_pct"], 2) == 2.0
    assert history[0]["outcome_3d_return_pct"] is not None
    assert history[0]["outcome_5d_return_pct"] is None

    pending = get_pending_outcomes(db_path=db_path, owner_id='test-owner')
    assert pending[0]["missing_horizons"] == [5, 10, 20]

    record_outcome(signal_id, 5, "2026-11-27", 1200.0, db_path=db_path, owner_id='test-owner')
    record_outcome(signal_id, 10, "2026-12-04", 1210.0, db_path=db_path, owner_id='test-owner')
    record_outcome(signal_id, 20, "2026-12-18", 1230.0, db_path=db_path, owner_id='test-owner')
    pending = get_pending_outcomes(db_path=db_path, owner_id='test-owner')
    assert pending == []

    summary = outcome_summary(db_path=db_path, owner_id='test-owner')
    overall = [row for row in summary if row["ruleset_version"] == "ALL" and row["signal_type"] == "ALL"]
    assert [row["horizon"] for row in overall] == [1, 3, 5, 10, 20]


def test_record_outcome_rejects_unsupported_horizon(tmp_path):
    db_path = str(tmp_path / "performance.sqlite3")
    scan_id = save_scan(_scan(), db_path=db_path, owner_id='test-owner')
    signal_id = signal_history(db_path=db_path, owner_id='test-owner')[0]["id"]
    try:
        record_outcome(signal_id, 2, "2026-11-24", 1160.0, db_path=db_path, owner_id='test-owner')
    except ValueError as exc:
        assert "1, 3, 5, 10, atau 20" in str(exc)
    else:
        raise AssertionError("Horizon selain 1, 3, 5, 10, atau 20 seharusnya ditolak.")


def test_learning_history_isolated_between_users_and_same_day_tickers(tmp_path):
    db_path = str(tmp_path / "tenant-learning.sqlite3")
    first = save_scan(_scan(), db_path=db_path, owner_id="issuer|alice")
    second = save_scan(_scan(), db_path=db_path, owner_id="issuer|bob")
    assert first != second
    assert len(signal_history(db_path=db_path, owner_id="issuer|alice")) == 1
    assert len(signal_history(db_path=db_path, owner_id="issuer|bob")) == 1
    assert latest_scan(db_path=db_path, owner_id="issuer|alice")["scan_id"] == first
    assert latest_scan(db_path=db_path, owner_id="issuer|bob")["scan_id"] == second
    alice_signal = signal_history(db_path=db_path, owner_id="issuer|alice")[0]
    with __import__("pytest").raises(ValueError, match="Signal tidak ditemukan"):
        record_outcome(
            alice_signal["id"], 1, "2026-11-23", 1178.1,
            db_path=db_path, owner_id="issuer|bob",
        )
    record_outcome(
        alice_signal["id"], 1, "2026-11-23", 1178.1,
        db_path=db_path, owner_id="issuer|alice",
    )
    assert outcome_summary(db_path=db_path, owner_id="issuer|bob") == []
    assert outcome_summary(db_path=db_path, owner_id="issuer|alice")


def test_learning_storage_requires_explicit_owner(tmp_path):
    import pytest
    db_path = str(tmp_path / "owner-required.sqlite3")
    with pytest.raises(ValueError, match="Owner identity"):
        save_scan(_scan(), db_path=db_path)
    with pytest.raises(ValueError, match="Owner identity"):
        signal_history(db_path=db_path)
    with pytest.raises(ValueError, match="Owner identity"):
        latest_scan(db_path=db_path)


def test_legacy_learning_records_are_quarantined_on_owner_migration(tmp_path):
    import sqlite3
    from daily_signal_storage import initialize

    db_path = str(tmp_path / "legacy-learning.sqlite3")
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE scans(
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                scanned INTEGER, failed INTEGER, payload TEXT NOT NULL
            );
            CREATE TABLE signals(
                id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL,
                market TEXT, ticker TEXT, bar_date TEXT, signal TEXT, score INTEGER,
                close REAL, entry_low REAL, entry_high REAL, stop_loss REAL,
                target REAL, reward_risk REAL, payload TEXT NOT NULL,
                UNIQUE(market,ticker,bar_date)
            );
            CREATE TABLE outcomes(
                id INTEGER PRIMARY KEY, signal_id INTEGER NOT NULL, horizon INTEGER NOT NULL,
                observed_date TEXT, close REAL, return_pct REAL, UNIQUE(signal_id,horizon)
            );
            INSERT INTO scans VALUES(1,'2026-01-01',1,0,'{"results":[]}');
            INSERT INTO signals VALUES(1,1,'IDX','AAA.JK','2026-01-01','WATCH',60,100,NULL,NULL,NULL,NULL,NULL,'{"ruleset_version":"legacy"}');
            INSERT INTO outcomes VALUES(1,1,1,'2026-01-02',101,1);
        """)
    initialize(db_path)
    assert latest_scan(db_path=db_path, owner_id="issuer|new-user") is None
    assert signal_history(db_path=db_path, owner_id="issuer|new-user") == []
    legacy = signal_history(db_path=db_path, owner_id="legacy-unassigned")
    assert len(legacy) == 1
    assert legacy[0]["outcome_1d_return_pct"] == 1
