def test_local_daily_scheduler_passes_explicit_sqlite_path(monkeypatch):
    import daily_signal_scheduler as scheduler

    captured = {}

    def fake_scan(db_path=None):
        captured["db_path"] = db_path
        return {"counts": {"scanned": 0}, "results": [], "errors": []}

    monkeypatch.setattr(scheduler, "_setup_logging", lambda: None)
    monkeypatch.setattr(scheduler, "run_daily_scan", fake_scan)
    monkeypatch.setattr(scheduler, "format_report", lambda scan: "dry run report")
    monkeypatch.setattr(scheduler, "enrich_report", lambda report: report)

    scheduler.run_once(dry_run=True)

    assert captured["db_path"] == scheduler.DB_PATH
