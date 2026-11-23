"""SQLite for local automation and PostgreSQL for cloud performance history."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


OUTCOME_HORIZONS = (1, 3, 5, 10, 20)


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


def backend_name(db_path: str | None = None) -> str:
    return "SQLite" if db_path is not None or not _database_url() else "PostgreSQL"


def _connect_sqlite(db_path: str | None = None):
    path = db_path or os.getenv("DAILY_SIGNAL_DB", "data/daily_signals.sqlite3")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
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


def connect(db_path: str | None = None):
    """Backward-compatible SQLite connection for local tools and tests."""
    return _connect_sqlite(db_path)


def initialize(db_path: str | None = None):
    if backend_name(db_path) == "PostgreSQL":
        statements = [
            """CREATE TABLE IF NOT EXISTS scans (
                id BIGSERIAL PRIMARY KEY, created_at TEXT NOT NULL,
                scanned INTEGER, failed INTEGER, payload JSONB NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS signals (
                id BIGSERIAL PRIMARY KEY,
                scan_id BIGINT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
                market TEXT, ticker TEXT, bar_date TEXT, signal TEXT, score INTEGER,
                close DOUBLE PRECISION, entry_low DOUBLE PRECISION, entry_high DOUBLE PRECISION,
                stop_loss DOUBLE PRECISION, target DOUBLE PRECISION, reward_risk DOUBLE PRECISION,
                payload JSONB NOT NULL, UNIQUE(market,ticker,bar_date)
            )""",
            """CREATE TABLE IF NOT EXISTS outcomes (
                id BIGSERIAL PRIMARY KEY,
                signal_id BIGINT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
                horizon INTEGER NOT NULL, observed_date TEXT, close DOUBLE PRECISION,
                return_pct DOUBLE PRECISION, UNIQUE(signal_id,horizon)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(bar_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_outcomes_horizon ON outcomes(horizon)",
        ]
        with _connect_postgres() as db:
            with db.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
                # Idempotent migration from the original 1/3/5-session constraint.
                cur.execute("ALTER TABLE outcomes DROP CONSTRAINT IF EXISTS outcomes_horizon_check")
                cur.execute(
                    "ALTER TABLE outcomes ADD CONSTRAINT outcomes_horizon_check "
                    "CHECK (horizon IN (1,3,5,10,20))"
                )
        return

    with _connect_sqlite(db_path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS scans(
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
            scanned INTEGER, failed INTEGER, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signals(
            id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL,
            market TEXT, ticker TEXT, bar_date TEXT, signal TEXT, score INTEGER,
            close REAL, entry_low REAL, entry_high REAL, stop_loss REAL,
            target REAL, reward_risk REAL, payload TEXT NOT NULL,
            UNIQUE(market,ticker,bar_date)
        );
        CREATE TABLE IF NOT EXISTS outcomes(
            id INTEGER PRIMARY KEY, signal_id INTEGER NOT NULL, horizon INTEGER NOT NULL,
            observed_date TEXT, close REAL, return_pct REAL, UNIQUE(signal_id,horizon)
        );
        CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(bar_date DESC);
        CREATE INDEX IF NOT EXISTS idx_outcomes_horizon ON outcomes(horizon);
        """)


def save_scan(scan: dict, db_path: str | None = None) -> int:
    initialize(db_path)
    created_at = datetime.now(timezone.utc).isoformat()
    counts = scan.get("counts", {})
    payload = dict(scan)

    if backend_name(db_path) == "PostgreSQL":
        from psycopg.types.json import Jsonb
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO scans(created_at,scanned,failed,payload) VALUES(%s,%s,%s,%s) RETURNING id",
                    (created_at, counts.get("scanned", 0), counts.get("failed", 0), Jsonb(payload)),
                )
                scan_id = int(cur.fetchone()["id"])
                payload["scan_id"] = scan_id
                cur.execute("UPDATE scans SET payload=%s WHERE id=%s", (Jsonb(payload), scan_id))
                for item in scan.get("results", []):
                    cur.execute("""
                        INSERT INTO signals(scan_id,market,ticker,bar_date,signal,score,close,
                            entry_low,entry_high,stop_loss,target,reward_risk,payload)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(market,ticker,bar_date) DO NOTHING
                    """, (
                        scan_id, item.get("market"), item.get("ticker"), item.get("bar_date"),
                        item.get("signal"), item.get("score"), item.get("close"),
                        item.get("entry_low"), item.get("entry_high"), item.get("stop_loss"),
                        item.get("target"), item.get("reward_risk"), Jsonb(item),
                    ))
                return scan_id

    with _connect_sqlite(db_path) as db:
        cur = db.execute(
            "INSERT INTO scans(created_at,scanned,failed,payload) VALUES(?,?,?,?)",
            (created_at, counts.get("scanned", 0), counts.get("failed", 0), json.dumps(payload, default=str)),
        )
        scan_id = int(cur.lastrowid)
        payload["scan_id"] = scan_id
        db.execute("UPDATE scans SET payload=? WHERE id=?", (json.dumps(payload, default=str), scan_id))
        for item in scan.get("results", []):
            db.execute("""
                INSERT OR IGNORE INTO signals(scan_id,market,ticker,bar_date,signal,score,close,
                    entry_low,entry_high,stop_loss,target,reward_risk,payload)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                scan_id, item.get("market"), item.get("ticker"), item.get("bar_date"),
                item.get("signal"), item.get("score"), item.get("close"),
                item.get("entry_low"), item.get("entry_high"), item.get("stop_loss"),
                item.get("target"), item.get("reward_risk"), json.dumps(item, default=str),
            ))
        return scan_id


def _decode_payload(value):
    return json.loads(value) if isinstance(value, str) else value


def latest_scan(db_path: str | None = None):
    initialize(db_path)
    if backend_name(db_path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute("SELECT payload FROM scans ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                return _decode_payload(row["payload"]) if row else None
    with _connect_sqlite(db_path) as db:
        row = db.execute("SELECT payload FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        return _decode_payload(row["payload"]) if row else None


def signal_history(limit: int = 100, db_path: str | None = None):
    initialize(db_path)
    limit = max(1, min(int(limit), 1000))
    query = """
        SELECT s.*,
          o1.return_pct AS outcome_1d_return_pct,
          o3.return_pct AS outcome_3d_return_pct,
          o5.return_pct AS outcome_5d_return_pct,
          o10.return_pct AS outcome_10d_return_pct,
          o20.return_pct AS outcome_20d_return_pct
        FROM signals s
        LEFT JOIN outcomes o1 ON o1.signal_id=s.id AND o1.horizon=1
        LEFT JOIN outcomes o3 ON o3.signal_id=s.id AND o3.horizon=3
        LEFT JOIN outcomes o5 ON o5.signal_id=s.id AND o5.horizon=5
        LEFT JOIN outcomes o10 ON o10.signal_id=s.id AND o10.horizon=10
        LEFT JOIN outcomes o20 ON o20.signal_id=s.id AND o20.horizon=20
        ORDER BY s.bar_date DESC,s.id DESC LIMIT {"%s" if backend_name(db_path) == "PostgreSQL" else "?"}
    """
    if backend_name(db_path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(query, (limit,))
                rows = cur.fetchall()
    else:
        with _connect_sqlite(db_path) as db:
            rows = db.execute(query, (limit,)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["payload"] = _decode_payload(item.get("payload"))
        output.append(item)
    return output


def get_pending_outcomes(limit: int = 500, db_path: str | None = None):
    initialize(db_path)
    limit = max(1, min(int(limit), 2000))
    if backend_name(db_path) == "PostgreSQL":
        sql = """
            SELECT s.id,s.market,s.ticker,s.bar_date,s.close,
                   ARRAY(SELECT o.horizon FROM outcomes o WHERE o.signal_id=s.id) AS recorded
            FROM signals s ORDER BY s.bar_date DESC LIMIT %s
        """
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
    else:
        with _connect_sqlite(db_path) as db:
            rows = db.execute("""
                SELECT s.id,s.market,s.ticker,s.bar_date,s.close,GROUP_CONCAT(o.horizon) AS recorded
                FROM signals s LEFT JOIN outcomes o ON o.signal_id=s.id
                GROUP BY s.id ORDER BY s.bar_date DESC LIMIT ?
            """, (limit,)).fetchall()
    pending = []
    for row in rows:
        item = dict(row)
        recorded = item.get("recorded")
        if isinstance(recorded, str):
            recorded = [int(x) for x in recorded.split(",") if x]
        missing = [h for h in OUTCOME_HORIZONS if h not in set(recorded or [])]
        if missing and item.get("bar_date") and item.get("close"):
            item["missing_horizons"] = missing
            pending.append(item)
    return pending


def record_outcome(signal_id: int, horizon: int, observed_date: str, close: float, db_path: str | None = None):
    if horizon not in OUTCOME_HORIZONS:
        raise ValueError("Horizon hanya 1, 3, 5, 10, atau 20 sesi.")
    initialize(db_path)
    if backend_name(db_path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute("SELECT close FROM signals WHERE id=%s", (signal_id,))
                row = cur.fetchone()
                if not row or not row["close"]:
                    raise ValueError("Signal tidak ditemukan atau harga awal tidak valid.")
                ret = (float(close) / float(row["close"]) - 1) * 100
                cur.execute("""
                    INSERT INTO outcomes(signal_id,horizon,observed_date,close,return_pct)
                    VALUES(%s,%s,%s,%s,%s)
                    ON CONFLICT(signal_id,horizon) DO UPDATE SET
                    observed_date=EXCLUDED.observed_date,close=EXCLUDED.close,return_pct=EXCLUDED.return_pct
                """, (signal_id, horizon, observed_date, float(close), ret))
        return ret
    with _connect_sqlite(db_path) as db:
        row = db.execute("SELECT close FROM signals WHERE id=?", (signal_id,)).fetchone()
        if not row or not row["close"]:
            raise ValueError("Signal tidak ditemukan atau harga awal tidak valid.")
        ret = (float(close) / float(row["close"]) - 1) * 100
        db.execute("""
            INSERT OR REPLACE INTO outcomes(signal_id,horizon,observed_date,close,return_pct)
            VALUES(?,?,?,?,?)
        """, (signal_id, horizon, observed_date, float(close), ret))
        return ret


def outcome_summary(db_path: str | None = None):
    initialize(db_path)
    query = """
        SELECT horizon,COUNT(*) AS observations,AVG(return_pct) AS avg_forward_return_pct,
               SUM(CASE WHEN return_pct>0 THEN 1 ELSE 0 END)*100.0/COUNT(*) AS positive_rate_pct
        FROM outcomes GROUP BY horizon ORDER BY horizon
    """
    if backend_name(db_path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]
    with _connect_sqlite(db_path) as db:
        return [dict(row) for row in db.execute(query).fetchall()]
