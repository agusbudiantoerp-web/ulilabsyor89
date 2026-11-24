import json
import sqlite3
from pathlib import Path

from database_backup import backup_sqlite


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
