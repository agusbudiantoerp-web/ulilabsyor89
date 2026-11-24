"""Create verified local SQLite or PostgreSQL logical backups without logging credentials."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path


LOCAL_DATABASES = {
    "daily_signals": ("DAILY_SIGNAL_DB", "data/daily_signals.sqlite3"),
    "portfolio_books": ("PORTFOLIO_DB_PATH", "data/portfolio_books.sqlite3"),
    "audit_log": ("AUDIT_DB_PATH", "data/audit_log.sqlite3"),
    "research_runs": ("RESEARCH_RUNS_DB_PATH", "data/research_runs.sqlite3"),
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(backup_path: Path, backend: str, source_name: str, validation: str) -> Path:
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "source": source_name,
        "backup_file": backup_path.name,
        "size_bytes": backup_path.stat().st_size,
        "sha256": _sha256(backup_path),
        "validation": validation,
    }
    manifest_path = backup_path.with_suffix(backup_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def backup_sqlite(source: str | Path, output_dir: str | Path = "backups") -> dict:
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"Database SQLite tidak ditemukan: {source_path}")
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_path = target_dir / f"{source_path.stem}-{_timestamp()}.sqlite3"

    try:
        with closing(sqlite3.connect(str(source_path), timeout=30)) as src:
            with closing(sqlite3.connect(str(backup_path), timeout=30)) as dst:
                src.backup(dst)
                result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"SQLite integrity_check gagal: {result}")
        manifest_path = _write_manifest(
            backup_path, "SQLite", source_path.name, "PRAGMA integrity_check: ok"
        )
        return {"backup": str(backup_path), "manifest": str(manifest_path), "validation": result}
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise


def backup_local_databases(output_dir: str | Path = "backups") -> list[dict]:
    """Back up each known local database that currently exists."""
    results = []
    for label, (environment_key, default_path) in LOCAL_DATABASES.items():
        source = os.getenv(environment_key, default_path)
        if Path(source).is_file():
            result = backup_sqlite(source, output_dir)
            result["database"] = label
            results.append(result)
    return results


def backup_postgres(output_dir: str | Path = "backups") -> dict:
    """Create a custom-format pg_dump using PGDATABASE, not a command-line URI."""
    database_url = os.getenv("DATABASE_URL") or os.getenv("CLOUD_DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set DATABASE_URL privately in the process environment first.")
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        raise RuntimeError("pg_dump and pg_restore must be installed and available on PATH.")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_path = target_dir / f"ai-equity-research-{_timestamp()}.dump"
    env = os.environ.copy()
    env["PGDATABASE"] = database_url
    env.setdefault("PGCONNECT_TIMEOUT", "15")
    env.pop("DATABASE_URL", None)
    env.pop("CLOUD_DATABASE_URL", None)

    try:
        subprocess.run(
            [
                pg_dump, "--format=custom", "--no-owner", "--no-privileges",
                "--file", str(backup_path),
            ],
            env=env, check=True, capture_output=True, text=True, timeout=900,
        )
        subprocess.run(
            [pg_restore, "--list", str(backup_path)],
            check=True, capture_output=True, text=True, timeout=120,
        )
        manifest_path = _write_manifest(
            backup_path, "PostgreSQL", "DATABASE_URL (value redacted)",
            "pg_restore --list: ok",
        )
        return {"backup": str(backup_path), "manifest": str(manifest_path), "validation": "ok"}
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Create verified AI Equity Research database backups.")
    parser.add_argument("backend", choices=("local", "sqlite", "postgres"))
    parser.add_argument("--source", help="SQLite database path; required for backend=sqlite.")
    parser.add_argument("--output-dir", default="backups")
    args = parser.parse_args()

    if args.backend == "sqlite":
        if not args.source:
            parser.error("--source is required when backend=sqlite")
        results = [backup_sqlite(args.source, args.output_dir)]
    elif args.backend == "local":
        results = backup_local_databases(args.output_dir)
        if not results:
            print("No local SQLite databases found; nothing was backed up.")
            return 0
    else:
        results = [backup_postgres(args.output_dir)]

    for item in results:
        print(f"Backup: {item['backup']}")
        print(f"Manifest: {item['manifest']}")
        print(f"Validation: {item['validation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
