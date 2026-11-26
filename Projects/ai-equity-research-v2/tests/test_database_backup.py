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


def test_postgres_backup_uses_private_libpq_environment_and_redacted_manifest(tmp_path, monkeypatch):
    import hashlib
    import subprocess
    import database_backup

    database_url = "postgresql://backup_user:s3cr%40t@db.example.net:5432/research_db?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(database_backup.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(command, *, env, check, capture_output, text, timeout):
        calls.append((command, env.copy(), timeout))
        if command[0].endswith("pg_dump"):
            output = Path(command[command.index("--file") + 1])
            output.write_bytes(b"postgres-custom-dump")
        return subprocess.CompletedProcess(command, 0, stdout="validated", stderr="")

    monkeypatch.setattr(database_backup.subprocess, "run", fake_run)
    result = database_backup.backup_postgres(tmp_path / "backups")

    assert len(calls) == 2
    dump_command, dump_env, dump_timeout = calls[0]
    restore_command, restore_env, restore_timeout = calls[1]
    assert "--dbname" not in dump_command
    assert database_url not in " ".join(dump_command + restore_command)
    assert "s3cr@t" not in " ".join(dump_command + restore_command)
    assert dump_env["PGPASSWORD"] == "s3cr@t"
    assert dump_env["PGSSLMODE"] == "require"
    assert "DATABASE_URL" not in dump_env
    assert dump_timeout == 900
    assert restore_command[1:3] == ["--list", result["backup"]]
    assert restore_timeout == 120

    manifest_text = Path(result["manifest"]).read_text(encoding="utf-8")
    assert "DATABASE_URL (value redacted)" in manifest_text
    assert "s3cr@t" not in manifest_text
    assert database_backup.verify_backup_manifest(result["manifest"])["sha256"] == hashlib.sha256(
        Path(result["backup"]).read_bytes()
    ).hexdigest()


def test_postgres_backup_removes_partial_dump_when_validation_fails(tmp_path, monkeypatch):
    import subprocess
    import database_backup

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example.net/research_db")
    monkeypatch.setattr(database_backup.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        if command[0].endswith("pg_dump"):
            Path(command[command.index("--file") + 1]).write_bytes(b"partial-dump")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise subprocess.CalledProcessError(1, command, stderr="invalid archive")

    monkeypatch.setattr(database_backup.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        database_backup.backup_postgres(tmp_path / "backups")
    assert list((tmp_path / "backups").glob("*.dump")) == []
    assert list((tmp_path / "backups").glob("*.manifest.json")) == []

def test_postgres_restore_requires_explicit_confirmation_and_empty_target(tmp_path, monkeypatch):
    import hashlib
    import subprocess
    import database_backup

    archive = tmp_path / "preview.dump"
    archive.write_bytes(b"verified-postgres-archive")
    manifest = tmp_path / "preview.dump.manifest.json"
    manifest.write_text(json.dumps({
        "backend": "PostgreSQL",
        "backup_file": archive.name,
        "size_bytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "validation": "pg_restore --list: ok",
    }), encoding="utf-8")

    monkeypatch.setenv("DATABASE_URL", "postgresql://restore_user:secret@preview-db.example/restore_target?sslmode=require")
    monkeypatch.delenv(database_backup.POSTGRES_RESTORE_CONFIRMATION, raising=False)
    with pytest.raises(RuntimeError, match="mengonfirmasi restore"):
        database_backup.restore_postgres_backup(manifest)

    monkeypatch.setenv(database_backup.POSTGRES_RESTORE_CONFIRMATION, "YES")
    monkeypatch.setattr(database_backup.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(command, *, env, check, capture_output, text, timeout):
        calls.append((command, env.copy(), timeout))
        if command[0].endswith("psql"):
            # Preflight sees an empty DB; postflight sees restored relations.
            stdout = "0\n" if len([x for x in calls if x[0][0].endswith("psql")]) == 1 else "14\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(database_backup.subprocess, "run", fake_run)
    result = database_backup.restore_postgres_backup(manifest)
    assert result["restored_relations"] == 14
    assert "post-restore relation check: ok" in result["validation"]
    restore_call = next(call for call in calls if call[0][0].endswith("pg_restore"))
    command, env, _ = restore_call
    assert "--single-transaction" in command
    assert "--no-owner" in command and "--no-privileges" in command
    assert "secret" not in " ".join(command)
    assert "DATABASE_URL" not in env
    assert env["PGDATABASE"] == "restore_target"


def test_postgres_restore_refuses_nonempty_target_before_running_pg_restore(tmp_path, monkeypatch):
    import hashlib
    import subprocess
    import database_backup

    archive = tmp_path / "preview.dump"
    archive.write_bytes(b"verified-postgres-archive")
    manifest = tmp_path / "preview.dump.manifest.json"
    manifest.write_text(json.dumps({
        "backend": "PostgreSQL",
        "backup_file": archive.name,
        "size_bytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "validation": "pg_restore --list: ok",
    }), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://restore_user:secret@preview-db.example/restore_target")
    monkeypatch.setenv(database_backup.POSTGRES_RESTORE_CONFIRMATION, "YES")
    monkeypatch.setattr(database_backup.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="3\n", stderr="")

    monkeypatch.setattr(database_backup.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="(?i)tidak kosong"):
        database_backup.restore_postgres_backup(manifest)
    assert len(calls) == 1
    assert calls[0][0].endswith("psql")


def test_postgres_restore_rejects_sqlite_manifest(tmp_path):
    import pytest
    from database_backup import restore_postgres_backup

    artifact = tmp_path / "sqlite.sqlite3"
    artifact.write_bytes(b"not postgres")
    manifest = tmp_path / "sqlite.sqlite3.manifest.json"
    manifest.write_text(json.dumps({
        "backend": "SQLite",
        "backup_file": artifact.name,
        "size_bytes": artifact.stat().st_size,
        "sha256": "0" * 64,
        "validation": "PRAGMA integrity_check: ok",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="backend PostgreSQL"):
        restore_postgres_backup(manifest)

