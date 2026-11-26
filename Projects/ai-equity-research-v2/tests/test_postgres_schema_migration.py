import pytest

import postgres_schema_migration as migration


def test_schema_migration_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CLOUD_DATABASE_URL", raising=False)
    monkeypatch.setenv(migration.CONFIRMATION_VARIABLE, "YES")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        migration.run_schema_migrations()


def test_schema_migration_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.delenv(migration.CONFIRMATION_VARIABLE, raising=False)
    with pytest.raises(RuntimeError, match="explicitly confirm"):
        migration.run_schema_migrations()


def test_schema_migration_runs_each_initializer_only_after_confirmation(monkeypatch):
    from types import ModuleType

    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv(migration.CONFIRMATION_VARIABLE, "YES")
    names = (
        "daily_signal_storage", "portfolio_store", "research_run_store",
        "thesis_store", "corporate_event_store", "portfolio_event_store",
        "portfolio_valuation_store",
    )
    called = []
    for name in names:
        module = ModuleType(name)
        module.initialize = lambda name=name: called.append(name)
        monkeypatch.setitem(__import__("sys").modules, name, module)

    completed = migration.run_schema_migrations()
    assert len(completed) == 7
    assert called == list(names)



def test_schema_init_permission_is_restored_after_success(monkeypatch):
    from types import ModuleType

    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv(migration.CONFIRMATION_VARIABLE, "YES")
    monkeypatch.setenv("AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT", "NO")
    for name in (
        "daily_signal_storage", "portfolio_store", "research_run_store",
        "thesis_store", "corporate_event_store", "portfolio_event_store",
        "portfolio_valuation_store",
    ):
        module = ModuleType(name)
        module.initialize = lambda: None
        monkeypatch.setitem(__import__("sys").modules, name, module)

    migration.run_schema_migrations()
    assert __import__("os").environ["AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT"] == "NO"


def test_schema_init_permission_is_restored_after_failure(monkeypatch):
    from types import ModuleType

    import os

    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv(migration.CONFIRMATION_VARIABLE, "YES")
    monkeypatch.delenv("AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT", raising=False)
    for name in (
        "daily_signal_storage", "portfolio_store", "research_run_store",
        "thesis_store", "corporate_event_store", "portfolio_event_store",
        "portfolio_valuation_store",
    ):
        module = ModuleType(name)
        module.initialize = lambda: None
        monkeypatch.setitem(__import__("sys").modules, name, module)

    import sys
    sys.modules["portfolio_store"].initialize = lambda: (_ for _ in ()).throw(
        RuntimeError("simulated migration failure")
    )
    with pytest.raises(RuntimeError, match="simulated migration failure"):
        migration.run_schema_migrations()
    assert "AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT" not in os.environ
