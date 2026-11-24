"""Read-only PostgreSQL connectivity, schema and privilege diagnostics."""
from __future__ import annotations

import os
import time
from typing import Any


REQUIRED_TABLES = {
    "scans": ("SELECT", "INSERT", "UPDATE"),
    "signals": ("SELECT", "INSERT"),
    "outcomes": ("SELECT", "INSERT", "UPDATE"),
    "portfolio_books": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "portfolio_positions": ("SELECT", "INSERT", "DELETE"),
    "research_runs": ("SELECT", "INSERT", "DELETE"),
    "audit_events": ("SELECT", "INSERT"),
    "audit_chain_lock": ("SELECT", "INSERT", "UPDATE"),
}


def _resolve_database_url(secrets: Any = None) -> str | None:
    value = os.getenv("DATABASE_URL") or os.getenv("CLOUD_DATABASE_URL")
    if value:
        return value.strip()
    try:
        source = secrets
        if source is None:
            import streamlit as st
            source = st.secrets
        value = source.get("DATABASE_URL") or source.get("CLOUD_DATABASE_URL")
        if not value:
            database = source.get("database", {})
            value = database.get("url") if hasattr(database, "get") else None
        return str(value).strip() if value else None
    except Exception:
        return None


def check_postgres_health(secrets: Any = None) -> dict:
    """Check connectivity, required tables and privileges without mutating data."""
    url = _resolve_database_url(secrets)
    if not url:
        return {
            "configured": False,
            "connected": False,
            "ok": False,
            "message": "DATABASE_URL belum dikonfigurasi.",
            "missing_tables": sorted(REQUIRED_TABLES),
            "privilege_issues": [],
            "latency_ms": None,
        }

    started = time.perf_counter()
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1, current_database(), current_schema(), "
                    "current_setting('server_version')"
                )
                _, database, schema, version = cursor.fetchone()
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
                    (list(REQUIRED_TABLES),),
                )
                existing = {row[0] for row in cursor.fetchall()}

                privilege_issues = []
                for table, privileges in REQUIRED_TABLES.items():
                    if table not in existing:
                        continue
                    qualified = f"{schema}.{table}"
                    for privilege in privileges:
                        cursor.execute(
                            "SELECT has_table_privilege(current_user, %s, %s)",
                            (qualified, privilege),
                        )
                        if not cursor.fetchone()[0]:
                            privilege_issues.append({
                                "table": table,
                                "privilege": privilege,
                            })

        missing = sorted(set(REQUIRED_TABLES) - existing)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return {
            "configured": True,
            "connected": True,
            "ok": not missing and not privilege_issues,
            "database": database,
            "schema": schema,
            "server_version": version,
            "missing_tables": missing,
            "privilege_issues": privilege_issues,
            "latency_ms": elapsed,
            "message": (
                "Koneksi, tabel dan hak akses dasar terverifikasi."
                if not missing and not privilege_issues
                else "Koneksi berhasil, tetapi skema atau hak akses belum lengkap."
            ),
        }
    except Exception as exc:
        return {
            "configured": True,
            "connected": False,
            "ok": False,
            "message": f"Koneksi PostgreSQL gagal: {type(exc).__name__}. Detail koneksi disembunyikan.",
            "missing_tables": sorted(REQUIRED_TABLES),
            "privilege_issues": [],
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }



def initialize_required_postgres_schema(
    secrets: Any = None, actor_id: str = "", actor_role: str = ""
) -> dict:
    """Run the application's idempotent PostgreSQL schema initializers, then verify."""
    if not _resolve_database_url(secrets):
        raise RuntimeError("DATABASE_URL belum dikonfigurasi; skema PostgreSQL tidak diubah.")

    from daily_signal_storage import initialize as initialize_daily_signals
    from portfolio_store import initialize as initialize_portfolios
    from research_run_store import initialize as initialize_research_runs
    from security_controls import record_audit_event

    initialize_daily_signals()
    initialize_portfolios()
    initialize_research_runs()
    record_audit_event(
        actor_id,
        actor_role,
        "DATABASE_SCHEMA_INITIALIZE",
        "database_schema",
        details={"tables": sorted(REQUIRED_TABLES)},
    )
    return check_postgres_health(secrets)
