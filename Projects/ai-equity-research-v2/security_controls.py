"""Role checks and tamper-evident local audit events.

This module is a control foundation, not a complete multi-user identity system.
The caller must supply actor_id from a verified authentication provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROLE_PERMISSIONS = {
    "viewer": {"view_dashboard", "view_reports"},
    "analyst": {"view_dashboard", "view_reports", "run_analysis", "export_reports"},
    "portfolio_manager": {
        "view_dashboard", "view_reports", "run_analysis", "export_reports",
        "manage_portfolio",
    },
    "admin": {
        "view_dashboard", "view_reports", "run_analysis", "export_reports",
        "manage_portfolio", "manage_users", "manage_model_config", "view_audit",
    },
}


def normalize_role(role: str | None) -> str:
    value = str(role or "").strip().lower()
    if value not in ROLE_PERMISSIONS:
        raise ValueError("Role tidak dikenal; akses ditolak.")
    return value


def has_permission(role: str | None, permission: str) -> bool:
    normalized = normalize_role(role)
    return permission in ROLE_PERMISSIONS[normalized]


def require_permission(role: str | None, permission: str) -> None:
    if not has_permission(role, permission):
        raise PermissionError(f"Akses ditolak: role tidak memiliki izin {permission}.")


def _connect(path: str | None = None) -> sqlite3.Connection:
    target = path or os.getenv("AUDIT_DB_PATH", "data/audit_log.sqlite3")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            details_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE
        )
    """)
    return db


def _canonical_event(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _contains_secret_key(value: Any) -> bool:
    """Reject credential-like keys recursively, including common naming variants."""
    forbidden_fragments = (
        "password", "token", "secret", "apikey", "databaseurl",
        "authorization", "privatekey", "clientsecret",
    )
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(ch for ch in str(key).lower() if ch.isalnum())
            if any(fragment in normalized for fragment in forbidden_fragments):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_secret_key(item) for item in value)
    return False


def record_audit_event(
    actor_id: str,
    actor_role: str,
    action: str,
    resource_type: str,
    resource_id: str = "",
    details: dict | None = None,
    path: str | None = None,
) -> int:
    """Append an event; actor identity must come from trusted authentication."""
    actor = str(actor_id or "").strip()
    action_value = str(action or "").strip()
    resource = str(resource_type or "").strip()
    if not actor or not action_value or not resource:
        raise ValueError("Actor, action, dan resource_type wajib diisi.")
    role = normalize_role(actor_role)
    payload = details or {}
    if not isinstance(payload, dict):
        raise ValueError("details harus berupa dictionary.")
    # Do not store likely credentials/secrets in audit payloads, including nested values.
    if _contains_secret_key(payload):
        raise ValueError("Audit details tidak boleh memuat kredensial atau secret.")

    with _connect(path) as db:
        # Serialize append operations so concurrent writers cannot fork the hash chain.
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            "SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = str(previous["event_hash"]) if previous else "GENESIS"
        event = {
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "actor_id": actor,
            "actor_role": role,
            "action": action_value,
            "resource_type": resource,
            "resource_id": str(resource_id or ""),
            "details_json": _canonical_event(payload),
            "previous_hash": previous_hash,
        }
        event_hash = hashlib.sha256(_canonical_event(event).encode("utf-8")).hexdigest()
        cur = db.execute("""
            INSERT INTO audit_events(
                occurred_at, actor_id, actor_role, action, resource_type,
                resource_id, details_json, previous_hash, event_hash
            ) VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            event["occurred_at"], actor, role, action_value, resource,
            event["resource_id"], event["details_json"], previous_hash, event_hash,
        ))
        return int(cur.lastrowid)


def verify_audit_chain(path: str | None = None) -> dict:
    with _connect(path) as db:
        rows = db.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
    previous_hash = "GENESIS"
    for row in rows:
        event = {
            "occurred_at": row["occurred_at"],
            "actor_id": row["actor_id"],
            "actor_role": row["actor_role"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "details_json": row["details_json"],
            "previous_hash": row["previous_hash"],
        }
        expected = hashlib.sha256(_canonical_event(event).encode("utf-8")).hexdigest()
        if row["previous_hash"] != previous_hash or row["event_hash"] != expected:
            return {"valid": False, "checked_events": int(row["id"]), "failed_event_id": int(row["id"])}
        previous_hash = row["event_hash"]
    return {"valid": True, "checked_events": len(rows), "failed_event_id": None}


def list_audit_events(limit: int = 100, path: str | None = None) -> list[dict]:
    bounded = max(1, min(int(limit), 1000))
    with _connect(path) as db:
        rows = db.execute(
            "SELECT id, occurred_at, actor_id, actor_role, action, resource_type, "
            "resource_id, details_json, previous_hash, event_hash "
            "FROM audit_events ORDER BY id DESC LIMIT ?", (bounded,)
        ).fetchall()
    return [dict(row) for row in rows]
