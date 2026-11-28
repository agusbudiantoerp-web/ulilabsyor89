import pytest

from postgres_rls import connect_with_owner_context


def test_postgres_context_rejects_missing_owner_and_actor():
    with pytest.raises(ValueError, match="authenticated owner or actor"):
        connect_with_owner_context("postgresql://unused", None)


def test_postgres_context_sets_transaction_local_owner_and_actor(monkeypatch):
    import sys
    from types import ModuleType
    calls = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params): calls.append((sql, params))

    class Connection:
        closed = False
        def cursor(self): return Cursor()
        def close(self): self.closed = True

    connection = Connection()
    fake = ModuleType("psycopg")
    fake.connect = lambda *args, **kwargs: connection
    rows = ModuleType("psycopg.rows")
    rows.dict_row = object()
    fake.rows = rows
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.setitem(sys.modules, "psycopg.rows", rows)
    assert connect_with_owner_context("postgresql://private", "issuer|owner", "issuer|actor") is connection
    assert calls == [(
        "SELECT set_config('app.current_owner_id', %s, true), "
        "set_config('app.current_actor_id', %s, true)",
        ("issuer|owner", "issuer|actor"),
    )]


def test_postgres_context_closes_connection_when_binding_fails(monkeypatch):
    import sys
    from types import ModuleType

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params): raise RuntimeError("binding failed")

    class Connection:
        closed = False
        def cursor(self): return Cursor()
        def close(self): self.closed = True

    connection = Connection()
    fake = ModuleType("psycopg")
    fake.connect = lambda *args, **kwargs: connection
    rows = ModuleType("psycopg.rows")
    rows.dict_row = object()
    fake.rows = rows
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.setitem(sys.modules, "psycopg.rows", rows)
    with pytest.raises(RuntimeError, match="binding failed"):
        connect_with_owner_context("postgresql://private", "owner")
    assert connection.closed
