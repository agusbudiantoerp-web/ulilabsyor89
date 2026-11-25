import json
import sqlite3
from pathlib import Path

import pytest

from database_backup import (LOCAL_DATABASES, _postgres_environment, backup_sqlite, restore_sqlite_backup, verify_backup_manifest)


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
    env = _postgres_environment(url, {"PATH": "/usr/bin", "DATABASE_URL": url, "PGHOST": "stale-host", "PGPASSWORD": "stale-password"})

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



def test_postgres_url_does_not_inherit_stale_credentials():
    env = _postgres_environment(
        "postgresql://backup_user@db.example.net/research_db",
        {"PATH": "/usr/bin", "PGUSER": "old-user", "PGPASSWORD": "old-password"},
    )

    assert env["PGUSER"] == "backup_user"
    assert "PGPASSWORD" not in env


def test_local_backup_inventory_includes_new_owner_scoped_stores():
    assert "research_theses" in LOCAL_DATABASES
    assert "corporate_events" in LOCAL_DATABASES
    assert "portfolio_cashflow_events" in LOCAL_DATABASES
    assert "portfolio_valuations" in LOCAL_DATABASES



def test_backup_manifest_verifier_checks_artifact_hash_and_size(tmp_path):
    import pytest

    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample VALUES('verified')")
    result = backup_sqlite(source, tmp_path / "backups")
    verified = verify_backup_manifest(result["manifest"])
    assert verified["validation"] == "manifest integrity: ok"
    assert verified["backend"] == "SQLite"

    backup_path = Path(result["backup"])
    backup_path.write_bytes(backup_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="Ukuran file backup"):
        verify_backup_manifest(result["manifest"])


@pytest.mark.parametrize("unsafe_name", ["../outside.dump", "..\\\\outside.dump"])
def test_backup_manifest_verifier_rejects_path_traversal(tmp_path, unsafe_name):
    import json
    import pytest

    manifest = tmp_path / "backup.manifest.json"
    manifest.write_text(json.dumps({
        "backup_file": unsafe_name,
        "size_bytes": 0,
        "sha256": "0" * 64,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Nama file backup"):
        verify_backup_manifest(manifest)


def test_backup_manifest_verifier_rejects_hash_mismatch(tmp_path):
    import json
    import pytest

    backup = tmp_path / "artifact.dump"
    backup.write_bytes(b"safe backup")
    manifest = tmp_path / "artifact.dump.manifest.json"
    manifest.write_text(json.dumps({
        "backup_file": backup.name,
        "size_bytes": backup.stat().st_size,
        "sha256": "0" * 64,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_backup_manifest(manifest)



def test_backup_cli_can_verify_manifest_without_database_credentials(tmp_path, monkeypatch, capsys):
    import sys
    from database_backup import main

    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE sample(value TEXT)")
    result = backup_sqlite(source, tmp_path / "backups")
    monkeypatch.setattr(sys, "argv", ["database_backup.py", "verify", "--manifest", result["manifest"]])
    assert main() == 0
    output = capsys.readouterr().out
    assert "manifest integrity: ok" in output
    assert "SHA-256:" in output



def test_sqlite_restore_requires_explicit_overwrite_and_restores_integrity_checked_database(tmp_path):
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample VALUES('restored-value')")
    backup = backup_sqlite(source, tmp_path / "backups")
    target = tmp_path / "restored" / "production-copy.sqlite3"

    restored = restore_sqlite_backup(backup["manifest"], target)
    assert restored["validation"] == "PRAGMA integrity_check: ok"
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT value FROM sample").fetchone()[0] == "restored-value"

    target.write_bytes(b"existing target")
    with pytest.raises(FileExistsError, match="Target sudah ada"):
        restore_sqlite_backup(backup["manifest"], target)
    overwritten = restore_sqlite_backup(backup["manifest"], target, overwrite=True)
    assert overwritten["overwritten"] is True
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT value FROM sample").fetchone()[0] == "restored-value"


def test_sqlite_restore_rejects_non_sqlite_backup_manifest(tmp_path):
    import hashlib

    artifact = tmp_path / "postgres.dump"
    artifact.write_bytes(b"not a sqlite database")
    manifest = tmp_path / "postgres.dump.manifest.json"
    manifest.write_text(json.dumps({
        "backend": "PostgreSQL",
        "backup_file": artifact.name,
        "size_bytes": artifact.stat().st_size,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "validation": "pg_restore --list: ok",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="backend SQLite"):
        restore_sqlite_backup(manifest, tmp_path / "restore.sqlite3")


def test_sqlite_restore_cli_requires_target_and_restores(tmp_path, monkeypatch, capsys):
    import sys
    from database_backup import main

    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample VALUES('cli-restore')")
    backup = backup_sqlite(source, tmp_path / "backups")
    target = tmp_path / "restore.sqlite3"
    monkeypatch.setattr(sys, "argv", [
        "database_backup.py", "restore-sqlite",
        "--manifest", backup["manifest"], "--target", str(target),
    ])
    assert main() == 0
    output = capsys.readouterr().out
    assert "PRAGMA integrity_check: ok" in output
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT value FROM sample").fetchone()[0] == "cli-restore"


def test_sqlite_restore_refuses_target_with_wal_or_shm_sidecars(tmp_path):
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample VALUES('backup-value')")
    backup = backup_sqlite(source, tmp_path / "backups")
    target = tmp_path / "restore.sqlite3"
    with sqlite3.connect(target) as db:
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample VALUES('existing-value')")

    Path(f"{target}-wal").write_bytes(b"stale-wal-marker")
    with pytest.raises(RuntimeError, match="WAL/SHM"):
        restore_sqlite_backup(backup["manifest"], target, overwrite=True)

    with sqlite3.connect(target) as db:
        assert db.execute("SELECT value FROM sample").fetchone()[0] == "existing-value"
