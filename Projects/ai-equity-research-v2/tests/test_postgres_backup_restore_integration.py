from __future__ import annotations

import os
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest


def test_postgres_backup_restore_round_trip_against_real_postgres(tmp_path, monkeypatch):
    """Exercise pg_dump/pg_restore against the ephemeral PostgreSQL CI service."""
    database_url = os.getenv("AI_EQUITY_RESEARCH_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Dedicated PostgreSQL integration URL is not configured.")
    if any(shutil.which(command) is None for command in ("pg_dump", "pg_restore", "psql")):
        pytest.skip("PostgreSQL client utilities are not installed.")

    import psycopg
    from psycopg import sql

    import database_backup

    parsed = urlsplit(database_url)
    source_database = parsed.path.lstrip("/")
    if not source_database:
        pytest.skip("PostgreSQL test URL has no database name.")

    target_database = "restore_test_" + uuid4().hex[:12]
    probe_table = "backup_restore_probe_" + uuid4().hex[:12]
    target_url = urlunsplit(parsed._replace(path="/" + target_database))
    maintenance_url = urlunsplit(parsed._replace(path="/postgres"))

    target_created = False
    probe_created = False
    try:
        with psycopg.connect(database_url, autocommit=True) as source:
            with source.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE TABLE {} (id integer PRIMARY KEY, marker text NOT NULL)").format(
                        sql.Identifier("public", probe_table)
                    )
                )
                cursor.execute(
                    sql.SQL("INSERT INTO {} (id, marker) VALUES (1, %s)").format(
                        sql.Identifier("public", probe_table)
                    ),
                    ("backup-restore-round-trip",),
                )
        probe_created = True

        with psycopg.connect(maintenance_url, autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_database)))
        target_created = True

        monkeypatch.setenv("DATABASE_URL", database_url)
        backup = database_backup.backup_postgres(tmp_path / "backups")
        verified = database_backup.verify_backup_manifest(backup["manifest"])
        assert verified["backend"] == "PostgreSQL"

        monkeypatch.setenv("DATABASE_URL", target_url)
        monkeypatch.setenv(database_backup.POSTGRES_RESTORE_CONFIRMATION, "YES")
        try:
            restored = database_backup.restore_postgres_backup(backup["manifest"])
        except subprocess.CalledProcessError as exc:
            pytest.fail("pg_restore failed during real integration restore: " + str(exc.stderr))
        assert restored["restored_relations"] > 0

        with psycopg.connect(target_url) as recovered:
            with recovered.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT marker FROM {} WHERE id=1").format(
                        sql.Identifier("public", probe_table)
                    )
                )
                assert cursor.fetchone() == ("backup-restore-round-trip",)
    finally:
        if target_created:
            with psycopg.connect(maintenance_url, autocommit=True) as admin:
                with admin.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {}").format(sql.Identifier(target_database))
                    )
        if probe_created:
            with psycopg.connect(database_url, autocommit=True) as source:
                with source.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP TABLE IF EXISTS {}").format(
                            sql.Identifier("public", probe_table)
                        )
                    )
