import sys
from types import ModuleType

from database_health import OWNER_SCOPED_TABLES, REQUIRED_TABLES, check_postgres_health


def _install_fake_postgres(monkeypatch, *, rls_enabled=False, force_rls=False,
                           superuser=False, bypass_rls=False, table_owner="db_owner",
                           tenant_policies=True, broad_policy=False,
                           policy_role_mismatch=False):
    class FakeCursor:
        def __init__(self):
            self.one = None
            self.many = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            if "SELECT 1, current_database()" in query:
                self.one = (1, "research_test", "public", "17.0")
            elif "information_schema.tables" in query:
                self.many = [(name,) for name in params[0]]
            elif "has_table_privilege" in query:
                self.one = (True,)
            elif "SELECT current_user, r.rolsuper" in query:
                self.one = ("app_role", superuser, bypass_rls)
            elif "pg_class c JOIN pg_namespace" in query:
                self.many = [
                    (name, rls_enabled, force_rls, table_owner, "app_role")
                    for name in params[0]
                ]
            elif "FROM pg_policies" in query:
                self.many = []
                if tenant_policies:
                    for table in params[0]:
                        for command in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                            using = "owner_id = current_setting('app.current_owner_id', true)" if command != "INSERT" else None
                            check = "owner_id = current_setting('app.current_owner_id', true)" if command in {"INSERT", "UPDATE"} else None
                            if broad_policy and table == sorted(params[0])[0] and command == "SELECT":
                                using = "true"
                            applies = not (policy_role_mismatch and table == sorted(params[0])[0])
                            roles = ["other_role"] if not applies else ["app_role"]
                            self.many.append((table, f"{table}_{command.lower()}_tenant", "PERMISSIVE", roles, command, using, check, applies))

        def fetchone(self):
            return self.one

        def fetchall(self):
            return self.many

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

    fake_psycopg = ModuleType("psycopg")
    fake_psycopg.connect = lambda url, connect_timeout: FakeConnection()
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)


def test_database_health_fails_closed_when_url_is_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CLOUD_DATABASE_URL", raising=False)
    result = check_postgres_health({})
    assert result["configured"] is False
    assert result["connected"] is False
    assert result["ok"] is False
    assert set(result["missing_tables"]) == set(REQUIRED_TABLES)
    assert result["rls_issues"] == []


def test_database_health_requires_rls_and_restricted_application_role(monkeypatch):
    _install_fake_postgres(monkeypatch, rls_enabled=False, force_rls=False)
    result = check_postgres_health({"DATABASE_URL": "postgresql://private"})
    assert result["configured"] is True
    assert result["connected"] is True
    assert result["ok"] is False
    assert result["database"] == "research_test"
    assert result["missing_tables"] == []
    assert result["privilege_issues"] == []
    assert result["application_role"] == {
        "name": "app_role", "superuser": False, "bypass_rls": False,
    }
    assert {item["scope"] for item in result["rls_issues"]} == OWNER_SCOPED_TABLES
    assert result["latency_ms"] >= 0


def test_database_health_passes_when_rls_is_forced_and_role_is_restricted(monkeypatch):
    _install_fake_postgres(monkeypatch, rls_enabled=True, force_rls=True)
    result = check_postgres_health({"DATABASE_URL": "postgresql://private"})
    assert result["connected"] is True
    assert result["ok"] is True
    assert result["rls_issues"] == []


def test_database_health_rejects_rls_enabled_without_tenant_policies(monkeypatch):
    _install_fake_postgres(
        monkeypatch, rls_enabled=True, force_rls=True, tenant_policies=False,
    )
    result = check_postgres_health({"DATABASE_URL": "postgresql://private"})
    assert result["ok"] is False
    assert any("belum ada policy tenant" in item["reason"] for item in result["rls_issues"])


def test_database_health_rejects_broad_permissive_tenant_policy(monkeypatch):
    _install_fake_postgres(
        monkeypatch, rls_enabled=True, force_rls=True, broad_policy=True,
    )
    result = check_postgres_health({"DATABASE_URL": "postgresql://private"})
    assert result["ok"] is False
    assert any("tanpa pembatas owner_id" in item["reason"] for item in result["rls_issues"])


def test_database_health_rejects_superuser_or_bypassrls_application_role(monkeypatch):
    _install_fake_postgres(
        monkeypatch, rls_enabled=True, force_rls=True, bypass_rls=True,
    )
    result = check_postgres_health({"DATABASE_URL": "postgresql://private"})
    assert result["ok"] is False
    assert any(item["scope"] == "application_role" for item in result["rls_issues"])


def test_database_health_rejects_application_role_that_owns_rls_tables(monkeypatch):
    _install_fake_postgres(
        monkeypatch, rls_enabled=True, force_rls=True, table_owner="app_role",
    )
    result = check_postgres_health({"DATABASE_URL": "postgresql://private"})
    assert result["ok"] is False
    assert any("pemilik tabel" in item["reason"] for item in result["rls_issues"])


def test_database_health_rejects_policies_not_applicable_to_application_role(monkeypatch):
    _install_fake_postgres(
        monkeypatch, rls_enabled=True, force_rls=True,
        policy_role_mismatch=True,
    )
    result = check_postgres_health({"DATABASE_URL": "postgresql://private"})
    assert result["ok"] is False
    assert any(
        "belum ada policy tenant" in item["reason"]
        for item in result["rls_issues"]
    )
