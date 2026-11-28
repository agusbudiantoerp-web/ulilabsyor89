from daily_signal_scheduler import run_once


def test_dry_run_bypasses_already_sent_guard_and_never_sends(monkeypatch, capsys):
    sample = {"counts": {"scanned": 1, "success": 1, "failed": 0}, "results": [], "errors": []}
    monkeypatch.setattr("daily_signal_scheduler._setup_logging", lambda: None)
    monkeypatch.setattr("daily_signal_scheduler._already_sent", lambda day: True)
    captured = {}
    monkeypatch.setattr(
        "daily_signal_scheduler.run_daily_scan",
        lambda db_path=None, owner_id=None: captured.update(
            db_path=db_path, owner_id=owner_id
        ) or sample,
    )
    monkeypatch.setattr("daily_signal_scheduler.format_report", lambda result: "source report")
    monkeypatch.setattr("daily_signal_scheduler.enrich_report", lambda report: report + " + Gemma")
    monkeypatch.setattr("daily_signal_scheduler.send_report", lambda report: (_ for _ in ()).throw(AssertionError("must not send")))
    monkeypatch.setattr("daily_signal_scheduler._mark_sent", lambda day: (_ for _ in ()).throw(AssertionError("must not mark sent")))

    result = run_once(dry_run=True)

    assert result is sample
    assert captured["owner_id"] == "local-automation"
    assert "source report + Gemma" in capsys.readouterr().out
