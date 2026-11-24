import sqlite3

import pytest

from security_controls import (
    has_permission,
    list_audit_events,
    record_audit_event,
    require_permission,
    verify_audit_chain,
)


def test_role_permissions_fail_closed():
    assert has_permission("analyst", "run_analysis")
    assert not has_permission("viewer", "manage_portfolio")
    with pytest.raises(PermissionError):
        require_permission("viewer", "manage_portfolio")
    with pytest.raises(ValueError):
        has_permission("unknown-role", "view_dashboard")


def test_audit_chain_verifies_and_detects_tampering(tmp_path):
    path = str(tmp_path / "audit.sqlite3")
    first = record_audit_event(
        "user-123", "analyst", "EXPORT_REPORT", "research_report",
        "TLKM", {"format": "pdf"}, path,
    )
    second = record_audit_event(
        "admin-456", "admin", "CHANGE_MODEL", "model_config",
        "dcf-v2", {"wacc": 0.12}, path,
    )
    assert first == 1
    assert second == 2
    assert verify_audit_chain(path)["valid"] is True
    assert len(list_audit_events(10, path)) == 2

    with sqlite3.connect(path) as db:
        db.execute("UPDATE audit_events SET action='ALTERED' WHERE id=1")
    result = verify_audit_chain(path)
    assert result["valid"] is False
    assert result["failed_event_id"] == 1


def test_audit_rejects_missing_actor_and_secrets(tmp_path):
    path = str(tmp_path / "audit.sqlite3")
    with pytest.raises(ValueError, match="Actor"):
        record_audit_event("", "admin", "LOGIN", "session", path=path)
    with pytest.raises(ValueError, match="kredensial"):
        record_audit_event(
            "admin", "admin", "CONFIG", "settings",
            details={"api_key": "do-not-store"}, path=path,
        )
