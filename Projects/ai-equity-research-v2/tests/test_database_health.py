import sys
from types import ModuleType

from database_health import REQUIRED_TABLES, check_postgres_health


def test_database_health_fails_closed_when_url_is_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CLOUD_DATABASE_URL", raising=False)
    result = check_postgres_health({})
    assert result["configured"] is False
    assert result["connected"] is False
    assert result["ok"] is False
    assert set(result["missing_tables"]) == set(REQUIRED_TABLES)


def test_database_health_checks_connection_tables_and_privileges(monkeypatch):
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

    result = check_postgres_health({"DATABASE_URL": "postgresql://private"})
    assert result["configured"] is True
    assert result["connected"] is True
    assert result["ok"] is True
    assert result["database"] == "research_test"
    assert result["missing_tables"] == []
    assert result["privilege_issues"] == []
    assert result["latency_ms"] >= 0
