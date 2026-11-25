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
from urllib.parse import parse_qs, unquote, urlsplit


LOCAL_DATABASES = {
    "daily_signals": ("DAILY_SIGNAL_DB", "data/daily_signals.sqlite3"),
    "portfolio_books": ("PORTFOLIO_DB_PATH", "data/portfolio_books.sqlite3"),
    "audit_log": ("AUDIT_DB_PATH", "data/audit_log.sqlite3"),
    "research_runs": ("RESEARCH_RUNS_DB_PATH", "data/research_runs.sqlite3"),
    "research_theses": ("RESEARCH_THESIS_DB_PATH", "data/research_theses.sqlite3"),
    "corporate_events": ("CORPORATE_EVENTS_DB_PATH", "data/corporate_events.sqlite3"),
    "portfolio_cashflow_events": ("PORTFOLIO_EVENTS_DB_PATH", "data/portfolio_cashflow_events.sqlite3"),
    "portfolio_valuations": ("PORTFOLIO_VALUATIONS_DB_PATH", "data/portfolio_valuations.sqlite3"),
}

_LIBPQ_QUERY_ENV = {
    "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcrl": "PGSSLCRL",
    "application_name": "PGAPPNAME",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
    "gssencmode": "PGGSSENCMODE",
    "channel_binding": "PGCHANNELBINDING",
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


def _postgres_environment(database_url: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Translate a PostgreSQL URL into libpq environment variables, not process arguments."""
    parsed = urlsplit(str(database_url).strip())
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("DATABASE_URL harus berupa URL PostgreSQL yang valid.")
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError("DATABASE_URL harus menyertakan nama database.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Port PostgreSQL pada DATABASE_URL tidak valid.") from exc

    env = dict(os.environ if base_env is None else base_env)
    # Do not let unrelated inherited PG* settings silently override this URL.
    for key in (
        "PGHOST", "PGHOSTADDR", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE",
        "PGSERVICE", "PGSERVICEFILE", "PGSSLMODE", "PGSSLCERT", "PGSSLKEY",
        "PGSSLROOTCERT", "PGSSLCRL", "PGAPPNAME", "PGCONNECT_TIMEOUT",
        "PGTARGETSESSIONATTRS", "PGGSSENCMODE", "PGCHANNELBINDING",
    ):
        env.pop(key, None)
    env["PGHOST"] = unquote(parsed.hostname)
    env["PGDATABASE"] = database
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    if port is not None:
        env["PGPORT"] = str(port)

    query = parse_qs(parsed.query, keep_blank_values=False)
    for parameter, environment_key in _LIBPQ_QUERY_ENV.items():
        values = query.get(parameter)
        if values:
            env[environment_key] = values[-1]
    env.setdefault("PGCONNECT_TIMEOUT", "15")
    env.pop("DATABASE_URL", None)
    env.pop("CLOUD_DATABASE_URL", None)
    return env


def verify_backup_manifest(manifest_path: str | Path) -> dict:
    """Verify backup artifact identity, size and SHA-256 against its manifest."""
    manifest_file = Path(manifest_path)
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Manifest backup tidak ditemukan: {manifest_file}")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest backup tidak valid atau tidak dapat dibaca.") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Struktur manifest backup harus berupa object.")
    backup_name = manifest.get("backup_file")
    if (not isinstance(backup_name, str) or not backup_name
            or Path(backup_name).name != backup_name or "/" in backup_name or "\\" in backup_name
            or backup_name in {".", ".."}):
        raise ValueError("Nama file backup pada manifest tidak valid.")
    backup_path = manifest_file.parent / backup_name
    if not backup_path.is_file():
        raise FileNotFoundError(f"File backup tidak ditemukan: {backup_path}")
    expected_size = manifest.get("size_bytes")
    expected_hash = manifest.get("sha256")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        raise ValueError("Ukuran file pada manifest tidak valid.")
    if (not isinstance(expected_hash, str) or len(expected_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_hash.lower())):
        raise ValueError("SHA-256 pada manifest tidak valid.")
    actual_size = backup_path.stat().st_size
    actual_hash = _sha256(backup_path)
    if actual_size != expected_size:
        raise ValueError("Ukuran file backup tidak cocok dengan manifest.")
    if actual_hash.lower() != expected_hash.lower():
        raise ValueError("SHA-256 file backup tidak cocok dengan manifest.")
    return {
        "backup": str(backup_path),
        "backend": manifest.get("backend"),
        "size_bytes": actual_size,
        "sha256": actual_hash,
        "validation": "manifest integrity: ok",
    }



def restore_sqlite_backup(
    manifest_path: str | Path,
    target_path: str | Path,
    *,
    overwrite: bool = False,
) -> dict:
    """Restore a verified SQLite backup atomically without overwriting by default."""
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite harus berupa boolean.")
    verified = verify_backup_manifest(manifest_path)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if verified.get("backend") != "SQLite":
        raise ValueError("Restore SQLite hanya menerima backup dengan backend SQLite.")
    if manifest.get("validation") != "PRAGMA integrity_check: ok":
        raise ValueError("Manifest tidak menyatakan bahwa backup lolos integrity_check.")

    source = Path(verified["backup"])
    target = Path(target_path)
    if source.resolve() == target.resolve():
        raise ValueError("Target restore tidak boleh sama dengan file backup sumber.")
    # A stale WAL/SHM file can be replayed against the restored main database.
    # Refuse to replace a target with sidecars rather than risk mixing old state
    # into the newly restored database or deleting files used by a live process.
    sidecars = [Path(f"{target}-wal"), Path(f"{target}-shm")]
    if any(sidecar.exists() for sidecar in sidecars):
        raise RuntimeError(
            "Target memiliki file SQLite WAL/SHM. Hentikan semua koneksi database "
            "dan bersihkan sidecar melalui prosedur SQLite sebelum restore."
        )
    if target.exists() and not overwrite:
        raise FileExistsError(f"Target sudah ada; gunakan overwrite=True secara eksplisit: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(source), timeout=30)) as source_db:
        source_check = source_db.execute("PRAGMA integrity_check").fetchone()[0]
    if source_check != "ok":
        raise ValueError(f"Backup sumber gagal integrity_check: {source_check}")

    import tempfile

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".restore.tmp", dir=str(target.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        with closing(sqlite3.connect(str(temporary), timeout=30)) as restored_db:
            restored_check = restored_db.execute("PRAGMA integrity_check").fetchone()[0]
        if restored_check != "ok":
            raise ValueError(f"Salinan restore gagal integrity_check: {restored_check}")

        if overwrite:
            os.replace(temporary, target)
        else:
            # Publish atomically without clobbering a target created concurrently.
            os.link(temporary, target)
            temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "restored_to": str(target),
        "source_backup": str(source),
        "validation": "PRAGMA integrity_check: ok",
        "overwritten": overwrite,
    }


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
    """Create a custom-format pg_dump using libpq environment variables."""
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
    env = _postgres_environment(database_url)

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
            env=env, check=True, capture_output=True, text=True, timeout=120,
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
    parser.add_argument("backend", choices=("local", "sqlite", "postgres", "verify", "restore-sqlite"))
    parser.add_argument("--source", help="SQLite database path; required for backend=sqlite.")
    parser.add_argument("--manifest", help="Backup manifest path; required for verify/restore-sqlite.")
    parser.add_argument("--target", help="SQLite restore target path; required for backend=restore-sqlite.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing SQLite restore target.")
    parser.add_argument("--output-dir", default="backups")
    args = parser.parse_args()

    if args.backend == "restore-sqlite":
        if not args.manifest or not args.target:
            parser.error("--manifest and --target are required when backend=restore-sqlite")
        result = restore_sqlite_backup(args.manifest, args.target, overwrite=args.overwrite)
        print(f"Restored to: {result['restored_to']}")
        print(f"Source backup: {result['source_backup']}")
        print(f"Validation: {result['validation']}")
        return 0
    if args.backend == "verify":
        if not args.manifest:
            parser.error("--manifest is required when backend=verify")
        result = verify_backup_manifest(args.manifest)
        print(f"Backup: {result['backup']}")
        print(f"Backend: {result['backend']}")
        print(f"SHA-256: {result['sha256']}")
        print(f"Validation: {result['validation']}")
        return 0
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
