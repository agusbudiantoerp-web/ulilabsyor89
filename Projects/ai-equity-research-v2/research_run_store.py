"""Owner-scoped persistence for single, walk-forward and multi-asset research runs."""
from __future__ import annotations

import json
import math
import numbers
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_TYPES = {"single_ticker", "walk_forward", "multi_asset"}


def _database_url() -> str | None:
    value = os.getenv("DATABASE_URL") or os.getenv("CLOUD_DATABASE_URL")
    if value:
        return value.strip()
    try:
        import streamlit as st
        value = st.secrets.get("DATABASE_URL") or st.secrets.get("CLOUD_DATABASE_URL")
        if not value:
            database = st.secrets.get("database", {})
            value = database.get("url") if hasattr(database, "get") else None
        return str(value).strip() if value else None
    except Exception:
        return None


def backend_name(path: str | None = None) -> str:
    return "SQLite" if path is not None or not _database_url() else "PostgreSQL"


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _safe_json(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _json_text(value: Any) -> str:
    return json.dumps(_safe_json(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _connect_sqlite(path: str | None = None):
    target = path or os.getenv("RESEARCH_RUNS_DB_PATH", "data/research_runs.sqlite3")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def _connect_postgres():
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL belum dikonfigurasi.")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Driver PostgreSQL belum terpasang. Instal psycopg[binary].") from exc
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=15)


def initialize(path: str | None = None) -> None:
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS research_runs (
                        id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        run_type TEXT NOT NULL,
                        market TEXT NOT NULL,
                        symbols_json JSONB NOT NULL,
                        parameters_json JSONB NOT NULL,
                        result_json JSONB NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_research_runs_owner_created
                    ON research_runs(owner_id, created_at DESC)
                """)
        return
    with _connect_sqlite(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS research_runs (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                run_type TEXT NOT NULL,
                market TEXT NOT NULL,
                symbols_json TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_research_runs_owner_created
            ON research_runs(owner_id, created_at DESC)
        """)


def save_run(
    owner_id: str,
    run_type: str,
    market: str,
    symbols: list[str],
    parameters: dict,
    result: dict,
    path: str | None = None,
) -> str:
    owner = str(owner_id or "").strip()
    kind = str(run_type or "").strip().lower()
    market_value = str(market or "").strip().upper()
    if not owner:
        raise ValueError("Owner identity wajib diisi untuk menyimpan research run.")
    if kind not in RUN_TYPES:
        raise ValueError("Jenis research run tidak dikenal.")
    if market_value not in {"IDX", "US"}:
        raise ValueError("Market harus IDX atau US.")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("Minimal satu ticker wajib disimpan.")
    if not isinstance(parameters, dict) or not isinstance(result, dict):
        raise ValueError("Parameters dan result harus berupa dictionary.")
    normalized_symbols = list(dict.fromkeys(
        str(item).strip().upper() for item in symbols if str(item).strip()
    ))
    if not normalized_symbols:
        raise ValueError("Minimal satu ticker valid wajib disimpan.")
    run_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    symbols_json = _safe_json(normalized_symbols)
    parameters_json = _safe_json(parameters)
    result_json = _safe_json(result)
    # Ensure the schema exists before the first INSERT on both SQLite and PostgreSQL.
    initialize(path)
    if backend_name(path) == "PostgreSQL":
        from psycopg.types.json import Jsonb
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute("""
                    INSERT INTO research_runs(
                        id,owner_id,run_type,market,symbols_json,parameters_json,result_json,created_at
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    run_id, owner, kind, market_value, Jsonb(symbols_json),
                    Jsonb(parameters_json), Jsonb(result_json), created_at,
                ))
    else:
        with _connect_sqlite(path) as db:
            db.execute("""
                INSERT INTO research_runs(
                    id,owner_id,run_type,market,symbols_json,parameters_json,result_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
            """, (
                run_id, owner, kind, market_value, _json_text(symbols_json),
                _json_text(parameters_json), _json_text(result_json), created_at,
            ))
    return run_id


def _decode(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def list_runs(owner_id: str, limit: int = 100, path: str | None = None) -> list[dict]:
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    if isinstance(limit, bool) or not isinstance(limit, numbers.Integral) or int(limit) < 1:
        raise ValueError("Limit harus berupa bilangan bulat positif.")
    bounded = min(int(limit), 500)
    initialize(path)
    query = """
        SELECT id,run_type,market,symbols_json,parameters_json,created_at
        FROM research_runs WHERE owner_id={owner}
        ORDER BY created_at DESC LIMIT {limit}
    """
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres() as db:
            rows = db.execute(query.format(owner="%s", limit="%s"), (owner, bounded)).fetchall()
    else:
        with _connect_sqlite(path) as db:
            rows = db.execute(query.format(owner="?", limit="?"), (owner, bounded)).fetchall()
    return [{
        "id": row["id"],
        "run_type": row["run_type"],
        "market": row["market"],
        "symbols": _decode(row["symbols_json"]),
        "parameters": _decode(row["parameters_json"]),
        "created_at": row["created_at"],
    } for row in rows]


def get_run(owner_id: str, run_id: str, path: str | None = None) -> dict:
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    initialize(path)
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres() as db:
            row = db.execute(
                "SELECT * FROM research_runs WHERE id=%s AND owner_id=%s",
                (str(run_id), owner),
            ).fetchone()
    else:
        with _connect_sqlite(path) as db:
            row = db.execute(
                "SELECT * FROM research_runs WHERE id=? AND owner_id=?",
                (str(run_id), owner),
            ).fetchone()
    if not row:
        raise KeyError("Research run tidak ditemukan untuk pengguna ini.")
    return {
        "id": row["id"],
        "owner_id": row["owner_id"],
        "run_type": row["run_type"],
        "market": row["market"],
        "symbols": _decode(row["symbols_json"]),
        "parameters": _decode(row["parameters_json"]),
        "result": _decode(row["result_json"]),
        "created_at": row["created_at"],
    }


def delete_run(owner_id: str, run_id: str, path: str | None = None) -> bool:
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    initialize(path)
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(
                    "DELETE FROM research_runs WHERE id=%s AND owner_id=%s RETURNING id",
                    (str(run_id), owner),
                )
                return cur.fetchone() is not None
    with _connect_sqlite(path) as db:
        cur = db.execute(
            "DELETE FROM research_runs WHERE id=? AND owner_id=?",
            (str(run_id), owner),
        )
        return cur.rowcount > 0
