import pytest

import postgres_rls_migration as migration


def test_rls_migration_requires_private_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(migration.CONFIRMATION_VARIABLE, "YES")
    monkeypatch.setenv(migration.RUNTIME_ROLE_VARIABLE, "equity_runtime")
    with pytest.raises(RuntimeError, match="administrator DATABASE_URL"):
        migration.apply_rls_policies()


def test_rls_migration_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.delenv(migration.CONFIRMATION_VARIABLE, raising=False)
    monkeypatch.setenv(migration.RUNTIME_ROLE_VARIABLE, "equity_runtime")
    with pytest.raises(RuntimeError, match="explicitly confirm RLS migration"):
        migration.apply_rls_policies()


def test_rls_migration_requires_restricted_runtime_role_name(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv(migration.CONFIRMATION_VARIABLE, "YES")
    monkeypatch.delenv(migration.RUNTIME_ROLE_VARIABLE, raising=False)
    with pytest.raises(RuntimeError, match="restricted runtime role name"):
        migration.apply_rls_policies()


def test_rls_migration_rejects_blank_runtime_role_name(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv(migration.CONFIRMATION_VARIABLE, "YES")
    monkeypatch.setenv(migration.RUNTIME_ROLE_VARIABLE, "   ")
    with pytest.raises(RuntimeError, match="restricted runtime role name"):
        migration.apply_rls_policies()
