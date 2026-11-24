import json
import sqlite3
from pathlib import Path

from database_backup import _postgres_environment, backup_sqlite


def test_sqlite_backup_is_integrity_checked_and_has_sha256_manifest(tmp_path):
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO sample(value) VALUES('private-row')")

    result = backup_sqlite(source, tmp_path / "backups")
    backup_path = Path(result["backup"])
    manifest_path = Path(result["manifest"])

    assert result["validation"] == "ok"
    with sqlite3.connect(backup_path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT value FROM sample").fetchone()[0] == "private-row"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backend"] == "SQLite"
    assert len(manifest["sha256"]) == 64
    assert "private-row" not in manifest_path.read_text(encoding="utf-8")


def test_postgres_url_is_translated_to_libpq_environment_without_url_leak():
    url = (
        "postgresql://research_user:p%40ss%3Aword@db.example.net:6543/research_db"
        "?sslmode=require&connect_timeout=22&application_name=equity-backup"
    )
    env = _postgres_environment(url, {"PATH": "/usr/bin", "DATABASE_URL": url})

    assert env["PGHOST"] == "db.example.net"
    assert env["PGPORT"] == "6543"
    assert env["PGUSER"] == "research_user"
    assert env["PGPASSWORD"] == "p@ss:word"
    assert env["PGDATABASE"] == "research_db"
    assert env["PGSSLMODE"] == "require"
    assert env["PGCONNECT_TIMEOUT"] == "22"
    assert env["PGAPPNAME"] == "equity-backup"
    assert "DATABASE_URL" not in env
    assert url not in env.values()


def test_postgres_url_requires_database_name():
    import pytest

    with pytest.raises(ValueError, match="nama database"):
        _postgres_environment("postgresql://user:pass@db.example.net/")
