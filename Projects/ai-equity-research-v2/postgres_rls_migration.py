"""Explicit PostgreSQL RLS rollout for a restricted application role.

Run from a trusted administrator workstation only after the application
transaction-context release has been reviewed and staging-tested. This script
never enables RLS implicitly from the Streamlit runtime.
"""
from __future__ import annotations

import os

CONFIRMATION_VARIABLE = "AI_EQUITY_RESEARCH_CONFIRM_RLS_MIGRATION"
RUNTIME_ROLE_VARIABLE = "AI_EQUITY_RESEARCH_RUNTIME_ROLE"

OWNER_SCOPED_TABLES = (
    "scans", "signals", "outcomes", "portfolio_books", "portfolio_positions",
    "research_runs", "research_theses", "research_thesis_versions",
    "research_thesis_reviews", "corporate_events", "portfolio_cashflow_events",
    "portfolio_valuations",
)

REQUIRED_GRANTS = {
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


def apply_rls_policies() -> tuple[str, ...]:
    database_url = os.getenv("DATABASE_URL")
    runtime_role = str(os.getenv(RUNTIME_ROLE_VARIABLE) or "").strip()
    if not database_url:
        raise RuntimeError("Set a private administrator DATABASE_URL before applying RLS.")
    if os.getenv(CONFIRMATION_VARIABLE) != "YES":
        raise RuntimeError(f"Set {CONFIRMATION_VARIABLE}=YES to explicitly confirm RLS migration.")
    if not runtime_role:
        raise RuntimeError(f"Set {RUNTIME_ROLE_VARIABLE} to the restricted runtime role name.")

    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise RuntimeError("Install psycopg[binary] before applying RLS policies.") from exc

    with psycopg.connect(database_url, connect_timeout=15) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=%s",
                (runtime_role,),
            )
            role = cursor.fetchone()
            if not role:
                raise RuntimeError("The configured runtime role does not exist.")
            if bool(role[1]) or bool(role[2]):
                raise RuntimeError("The runtime role must not have SUPERUSER or BYPASSRLS.")
            if runtime_role == connection.info.user:
                raise RuntimeError("The migration identity and runtime identity must be different.")

            cursor.execute(
                "SELECT r.rolname FROM pg_roles r WHERE r.rolname <> %s "
                "AND pg_has_role(%s::name, r.oid, 'MEMBER') ORDER BY r.rolname LIMIT 1",
                (runtime_role, runtime_role),
            )
            inherited = cursor.fetchone()
            if inherited:
                raise RuntimeError(
                    "The runtime role inherits another PostgreSQL role; remove role memberships first."
                )

            cursor.execute("SELECT current_schema()")
            schema = cursor.fetchone()[0]
            cursor.execute(
                "SELECT c.relname, pg_get_userbyid(c.relowner) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relkind='r' AND c.relname=ANY(%s)",
                (schema, list(OWNER_SCOPED_TABLES)),
            )
            owners = dict(cursor.fetchall())
            missing = sorted(set(OWNER_SCOPED_TABLES) - set(owners))
            if missing:
                raise RuntimeError("Required owner-scoped tables are missing: " + ", ".join(missing))
            cursor.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
            migration_role = cursor.fetchone()
            migration_is_superuser = bool(migration_role[0])
            migration_has_bypassrls = bool(migration_role[1])
            # Neon does not expose a PostgreSQL SUPERUSER login. Its managed
            # administrator role inherits elevated privileges through membership
            # in the NOLOGIN neon_superuser role (including BYPASSRLS).
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='neon_superuser')"
            )
            neon_role_exists = bool(cursor.fetchone()[0])
            migration_is_neon_admin = False
            if neon_role_exists:
                cursor.execute(
                    "SELECT pg_has_role(current_user, 'neon_superuser', 'MEMBER')"
                )
                migration_is_neon_admin = bool(cursor.fetchone()[0])
            migration_can_bypass_rls = (
                migration_is_superuser or migration_has_bypassrls or migration_is_neon_admin
            )
            if not migration_can_bypass_rls:
                raise RuntimeError(
                    "The RLS migration identity must be SUPERUSER, BYPASSRLS, or a managed "
                    "Neon administrator member of neon_superuser so maintenance migrations "
                    "can safely run after FORCE ROW LEVEL SECURITY."
                )
            for table, table_owner in owners.items():
                if table_owner == runtime_role:
                    raise RuntimeError(f"Runtime role owns table {table}.")
                cursor.execute(
                    "SELECT pg_has_role(%s::name, %s::name, 'MEMBER')",
                    (runtime_role, table_owner),
                )
                if cursor.fetchone()[0]:
                    raise RuntimeError(f"Runtime role inherits ownership privileges for table {table}.")
                if not migration_is_superuser and not migration_is_neon_admin and table_owner != connection.info.user:
                    raise RuntimeError(
                        f"Migration identity must own table {table} or be a database superuser."
                    )

            schema_ident = sql.Identifier(schema)
            role_ident = sql.Identifier(runtime_role)
            owner_expr = "owner_id = NULLIF(current_setting('app.current_owner_id', true), '')"
            actor_expr = "reviewer_id = NULLIF(current_setting('app.current_actor_id', true), '')"
            review_table = sql.Identifier(schema, "research_thesis_reviews").as_string(connection)
            reviewer_thesis_expr = (
                owner_expr + " OR EXISTS (SELECT 1 FROM " + review_table +
                " AS reviewer_assignment WHERE reviewer_assignment.owner_id = research_theses.owner_id "
                "AND reviewer_assignment.thesis_id = research_theses.id "
                "AND reviewer_assignment.reviewer_id = NULLIF(current_setting('app.current_actor_id', true), ''))"
            )
            reviewer_version_expr = (
                owner_expr + " OR EXISTS (SELECT 1 FROM " + review_table +
                " AS reviewer_assignment WHERE reviewer_assignment.owner_id = research_thesis_versions.owner_id "
                "AND reviewer_assignment.thesis_id = research_thesis_versions.thesis_id "
                "AND reviewer_assignment.version = research_thesis_versions.version "
                "AND reviewer_assignment.reviewer_id = NULLIF(current_setting('app.current_actor_id', true), ''))"
            )
            reviewer_review_expr = owner_expr + " OR " + actor_expr

            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema_ident, role_ident)
            )
            for table, privileges in REQUIRED_GRANTS.items():
                if table not in owners and table not in {"audit_events", "audit_chain_lock"}:
                    continue
                cursor.execute(
                    "SELECT to_regclass(%s)",
                    (f"{schema}.{table}",),
                )
                if cursor.fetchone()[0] is None:
                    continue
                table_ident = sql.Identifier(schema, table)
                grants = sql.SQL(", ").join(sql.SQL(item) for item in privileges)
                cursor.execute(
                    sql.SQL("GRANT {} ON TABLE {} TO {}").format(grants, table_ident, role_ident)
                )

            # Grant sequence access only for serial/identity columns on tables
            # that the runtime role may insert into. Never expose unrelated
            # administrator or extension sequences in the same schema.
            for table, privileges in REQUIRED_GRANTS.items():
                if "INSERT" not in privileges:
                    continue
                cursor.execute(
                    """
                    SELECT sequence_namespace.nspname, sequence_class.relname
                    FROM pg_class AS table_class
                    JOIN pg_namespace AS table_namespace
                      ON table_namespace.oid = table_class.relnamespace
                    JOIN pg_attribute AS id_attribute
                      ON id_attribute.attrelid = table_class.oid
                     AND id_attribute.attname = 'id'
                     AND NOT id_attribute.attisdropped
                    JOIN pg_depend AS dependency
                      ON dependency.refobjid = table_class.oid
                     AND dependency.refobjsubid = id_attribute.attnum
                     AND dependency.deptype IN ('a', 'i')
                    JOIN pg_class AS sequence_class
                      ON sequence_class.oid = dependency.objid
                     AND sequence_class.relkind = 'S'
                    JOIN pg_namespace AS sequence_namespace
                      ON sequence_namespace.oid = sequence_class.relnamespace
                    WHERE table_namespace.nspname = %s
                      AND table_class.relname = %s
                    """,
                    (schema, table),
                )
                sequence = cursor.fetchone()
                if sequence:
                    sequence_ident = sql.Identifier(sequence[0], sequence[1])
                    cursor.execute(
                        sql.SQL("GRANT USAGE, SELECT ON SEQUENCE {} TO {}").format(
                            sequence_ident, role_ident
                        )
                    )

            for table in OWNER_SCOPED_TABLES:
                table_ident = sql.Identifier(schema, table)
                cursor.execute(
                    sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(table_ident)
                )
                cursor.execute(
                    sql.SQL("ALTER TABLE {} FORCE ROW LEVEL SECURITY").format(table_ident)
                )
                cursor.execute(
                    sql.SQL("DROP POLICY IF EXISTS ai_equity_research_owner ON {}").format(table_ident)
                )
                cursor.execute(
                    sql.SQL("DROP POLICY IF EXISTS ai_equity_research_reviewer_read ON {}").format(table_ident)
                )
                cursor.execute(
                    sql.SQL(
                        "CREATE POLICY ai_equity_research_owner ON {} FOR ALL TO {} "
                        "USING ({}) WITH CHECK ({})"
                    ).format(table_ident, role_ident, sql.SQL(owner_expr), sql.SQL(owner_expr))
                )
                if table == "research_theses":
                    expression = reviewer_thesis_expr
                elif table == "research_thesis_versions":
                    expression = reviewer_version_expr
                elif table == "research_thesis_reviews":
                    expression = reviewer_review_expr
                else:
                    expression = None
                if expression:
                    cursor.execute(
                        sql.SQL(
                            "CREATE POLICY ai_equity_research_reviewer_read ON {} "
                            "FOR SELECT TO {} USING ({})"
                        ).format(table_ident, role_ident, sql.SQL(expression))
                    )

        return OWNER_SCOPED_TABLES


def main() -> int:
    tables = apply_rls_policies()
    print(f"RLS enabled and forced on {len(tables)} owner-scoped tables.")
    print("Tenant policies and least-privilege runtime grants were applied.")
    print("Run the read-only Security & Audit database check using the runtime role.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
