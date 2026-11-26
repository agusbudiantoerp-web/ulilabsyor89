"""Read-only PostgreSQL connectivity, schema and privilege diagnostics."""
from __future__ import annotations

import os
import time
from typing import Any


OWNER_SCOPED_TABLES = {
    "scans", "signals", "outcomes", "portfolio_books", "portfolio_positions",
    "research_runs", "research_theses", "research_thesis_versions",
    "research_thesis_reviews", "corporate_events", "portfolio_cashflow_events",
    "portfolio_valuations",
}


REQUIRED_TABLES = {
    "scans": ("SELECT", "INSERT", "UPDATE"),
    "signals": ("SELECT", "INSERT"),
    "outcomes": ("SELECT", "INSERT", "UPDATE"),
    "portfolio_books": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "portfolio_positions": ("SELECT", "INSERT", "DELETE"),
    "research_runs": ("SELECT", "INSERT", "DELETE"),
    "research_theses": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "research_thesis_versions": ("SELECT", "INSERT"),
    "research_thesis_reviews": ("SELECT", "INSERT", "UPDATE"),
    "corporate_events": ("SELECT", "INSERT", "DELETE"),
    "portfolio_cashflow_events": ("SELECT", "INSERT", "DELETE"),
    "portfolio_valuations": ("SELECT", "INSERT", "UPDATE", "DELETE"),
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


def _required_tables(secrets: Any = None) -> dict[str, tuple[str, ...]]:
    tables = dict(REQUIRED_TABLES)
    try:
        if secrets is not None and secrets.get("audit_db_path"):
            tables.pop("audit_events", None)
            tables.pop("audit_chain_lock", None)
    except Exception:
        pass
    return tables


def check_postgres_health(secrets: Any = None) -> dict:
    """Check connectivity, required tables and privileges without mutating data."""
    required_tables = _required_tables(secrets)
    url = _resolve_database_url(secrets)
    if not url:
        return {
            "configured": False,
            "connected": False,
            "ok": False,
            "message": "DATABASE_URL belum dikonfigurasi.",
            "missing_tables": sorted(required_tables),
            "privilege_issues": [],
            "rls_issues": [],
            "application_role": None,
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
                    (list(required_tables),),
                )
                existing = {row[0] for row in cursor.fetchall()}

                privilege_issues = []
                for table, privileges in required_tables.items():
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

                cursor.execute(
                    "SELECT current_user, r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                )
                role_row = cursor.fetchone()
                application_role = {
                    "name": role_row[0],
                    "superuser": bool(role_row[1]),
                    "bypass_rls": bool(role_row[2]),
                } if role_row else {"name": None, "superuser": True, "bypass_rls": True}

                cursor.execute(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "pg_get_userbyid(c.relowner), current_user "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=current_schema() AND c.relkind='r' "
                    "AND c.relname = ANY(%s)",
                    (sorted(OWNER_SCOPED_TABLES & existing),),
                )
                rls_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT tablename, policyname, permissive, roles, cmd, qual, with_check "
                    "FROM pg_policies WHERE schemaname=current_schema() "
                    "AND tablename = ANY(%s)",
                    (sorted(OWNER_SCOPED_TABLES & existing),),
                )
                policy_rows = cursor.fetchall()

        missing = sorted(set(required_tables) - existing)
        rls_issues = []
        if application_role["superuser"] or application_role["bypass_rls"]:
            rls_issues.append({
                "scope": "application_role",
                "reason": "Role aplikasi memiliki SUPERUSER atau BYPASSRLS.",
            })
        rls_found = {row[0] for row in rls_rows}
        for table in sorted(OWNER_SCOPED_TABLES & existing):
            if table not in rls_found:
                rls_issues.append({"scope": table, "reason": "Status RLS tidak dapat diverifikasi."})
                continue
            _, enabled, forced, table_owner, current_user = next(
                row for row in rls_rows if row[0] == table
            )
            if not enabled:
                rls_issues.append({"scope": table, "reason": "ROW LEVEL SECURITY belum aktif."})
            elif not forced:
                rls_issues.append({"scope": table, "reason": "FORCE ROW LEVEL SECURITY belum aktif."})
            if table_owner == current_user:
                rls_issues.append({
                    "scope": table,
                    "reason": "Role aplikasi adalah pemilik tabel dan dapat mengubah kebijakan RLS.",
                })

        # RLS being enabled is not sufficient: permissive policies are OR-combined.
        # Require CRUD coverage and owner predicates on every permissive policy so
        # an accidentally broad policy cannot silently bypass tenant isolation.
        policies_by_table = {}
        for row in policy_rows:
            table, policy_name, permissive, roles, command, using_expr, check_expr = row
            policies_by_table.setdefault(table, []).append({
                "name": policy_name,
                "permissive": str(permissive).upper(),
                "command": str(command).upper(),
                "using": str(using_expr or "").lower(),
                "check": str(check_expr or "").lower(),
            })
        required_commands = {"SELECT", "INSERT", "UPDATE", "DELETE"}
        owner_tokens = ("owner_id", "current_setting", "app.current_owner_id")
        for table in sorted(OWNER_SCOPED_TABLES & existing):
            policies = policies_by_table.get(table, [])
            if not policies:
                rls_issues.append({
                    "scope": table,
                    "reason": "RLS aktif tetapi belum ada policy tenant.",
                })
                continue
            covered = set()
            for policy in policies:
                if policy["permissive"] != "PERMISSIVE":
                    continue
                command = policy["command"]
                using_expr = policy["using"]
                check_expr = policy["check"]
                using_scoped = all(token in using_expr for token in owner_tokens)
                check_scoped = all(token in check_expr for token in owner_tokens)
                if command in {"ALL", "SELECT", "UPDATE", "DELETE"} and using_scoped:
                    covered.update(required_commands if command == "ALL" else {command})
                if command in {"ALL", "INSERT", "UPDATE"} and check_scoped:
                    if command == "ALL":
                        covered.update(required_commands)
                    elif command == "INSERT":
                        covered.add("INSERT")
                    elif command == "UPDATE" and using_scoped:
                        covered.add("UPDATE")
                if command in {"ALL", "SELECT", "UPDATE", "DELETE"} and not using_scoped:
                    rls_issues.append({
                        "scope": table,
                        "reason": f"Policy {policy['name']} memiliki USING tanpa pembatas owner_id/current_setting.",
                    })
                if command in {"ALL", "INSERT", "UPDATE"} and not check_scoped:
                    rls_issues.append({
                        "scope": table,
                        "reason": f"Policy {policy['name']} memiliki WITH CHECK tanpa pembatas owner_id/current_setting.",
                    })
            missing_commands = sorted(required_commands - covered)
            if missing_commands:
                rls_issues.append({
                    "scope": table,
                    "reason": "Policy tenant belum mencakup operasi: " + ", ".join(missing_commands),
                })

        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return {
            "configured": True,
            "connected": True,
            "ok": not missing and not privilege_issues and not rls_issues,
            "database": database,
            "schema": schema,
            "server_version": version,
            "missing_tables": missing,
            "privilege_issues": privilege_issues,
            "rls_issues": rls_issues,
            "application_role": application_role,
            "latency_ms": elapsed,
            "message": (
                "Koneksi, tabel, hak akses dan isolasi RLS terverifikasi."
                if not missing and not privilege_issues and not rls_issues
                else "Koneksi berhasil, tetapi skema, hak akses, atau isolasi RLS belum memenuhi syarat."
            ),
        }
    except Exception as exc:
        return {
            "configured": True,
            "connected": False,
            "ok": False,
            "message": f"Koneksi PostgreSQL gagal: {type(exc).__name__}. Detail koneksi disembunyikan.",
            "missing_tables": sorted(required_tables),
            "privilege_issues": [],
            "rls_issues": [],
            "application_role": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }



def initialize_required_postgres_schema(
    secrets: Any = None, actor_id: str = "", actor_role: str = "",
    audit_path: str | None = None,
) -> dict:
    """Run the application's idempotent PostgreSQL schema initializers, then verify."""
    if not _resolve_database_url(secrets):
        raise RuntimeError("DATABASE_URL belum dikonfigurasi; skema PostgreSQL tidak diubah.")

    from daily_signal_storage import initialize as initialize_daily_signals
    from portfolio_store import initialize as initialize_portfolios
    from research_run_store import initialize as initialize_research_runs
    from thesis_store import initialize as initialize_theses
    from corporate_event_store import initialize as initialize_corporate_events
    from portfolio_event_store import initialize as initialize_portfolio_events
    from portfolio_valuation_store import initialize as initialize_portfolio_valuations
    from security_controls import record_audit_event

    initialize_daily_signals()
    initialize_portfolios()
    initialize_research_runs()
    initialize_theses()
    initialize_corporate_events()
    initialize_portfolio_events()
    initialize_portfolio_valuations()
    record_audit_event(
        actor_id,
        actor_role,
        "DATABASE_SCHEMA_INITIALIZE",
        "database_schema",
        details={"tables": sorted(_required_tables(secrets))},
        path=audit_path,
    )
    return check_postgres_health(secrets)
