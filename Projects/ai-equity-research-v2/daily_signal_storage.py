"""SQLite for local automation and PostgreSQL for cloud performance history."""
from __future__ import annotations

import json
import os
import sqlite3
import math
from pathlib import Path
from datetime import date, datetime, timezone


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
                scanned INTEGER, failed INTEGER, owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned', payload JSONB NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS signals (
                id BIGSERIAL PRIMARY KEY,
                scan_id BIGINT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
                market TEXT, ticker TEXT, bar_date TEXT, signal TEXT, score INTEGER,
                close DOUBLE PRECISION, entry_low DOUBLE PRECISION, entry_high DOUBLE PRECISION,
                stop_loss DOUBLE PRECISION, target DOUBLE PRECISION, reward_risk DOUBLE PRECISION,
                owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned', payload JSONB NOT NULL
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
                cur.execute("ALTER TABLE scans ADD COLUMN IF NOT EXISTS owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned'")
                cur.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned'")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_scans_owner_id ON scans(owner_id,id DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_owner_date ON signals(owner_id,bar_date DESC)")
                cur.execute("ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_market_ticker_bar_date_key")
                cur.execute("""
                    DO $
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conrelid='signals'::regclass
                          AND conname='signals_owner_market_ticker_bar_date_key'
                      ) THEN
                        ALTER TABLE signals ADD CONSTRAINT signals_owner_market_ticker_bar_date_key
                          UNIQUE(owner_id,market,ticker,bar_date);
                      END IF;
                    END $;
                """)
                # Migrate the old constraint once; avoid DDL on every dashboard read.
                cur.execute("""
                    SELECT pg_get_constraintdef(oid) AS definition
                    FROM pg_constraint
                    WHERE conrelid='outcomes'::regclass
                      AND contype='c' AND conname='outcomes_horizon_check'
                """)
                constraint = cur.fetchone()
                if constraint is None:
                    cur.execute(
                        "ALTER TABLE outcomes ADD CONSTRAINT outcomes_horizon_check "
                        "CHECK (horizon IN (1,3,5,10,20))"
                    )
                elif "20" not in str(constraint["definition"]):
                    cur.execute("ALTER TABLE outcomes DROP CONSTRAINT outcomes_horizon_check")
                    cur.execute(
                        "ALTER TABLE outcomes ADD CONSTRAINT outcomes_horizon_check "
                        "CHECK (horizon IN (1,3,5,10,20))"
                    )
        return

    with _connect_sqlite(db_path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS scans(
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
            scanned INTEGER, failed INTEGER, owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned', payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signals(
            id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL,
            market TEXT, ticker TEXT, bar_date TEXT, signal TEXT, score INTEGER,
            close REAL, entry_low REAL, entry_high REAL, stop_loss REAL,
            target REAL, reward_risk REAL, owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned', payload TEXT NOT NULL,
            UNIQUE(owner_id,market,ticker,bar_date)
        );
        CREATE TABLE IF NOT EXISTS outcomes(
            id INTEGER PRIMARY KEY, signal_id INTEGER NOT NULL, horizon INTEGER NOT NULL,
            observed_date TEXT, close REAL, return_pct REAL, UNIQUE(signal_id,horizon)
        );
        CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(bar_date DESC);
        CREATE INDEX IF NOT EXISTS idx_outcomes_horizon ON outcomes(horizon);
        """)
        scan_columns = {row["name"] for row in db.execute("PRAGMA table_info(scans)").fetchall()}
        if "owner_id" not in scan_columns:
            db.execute("ALTER TABLE scans ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned'")
        signal_columns = {row["name"] for row in db.execute("PRAGMA table_info(signals)").fetchall()}
        if "owner_id" not in signal_columns:
            db.execute("ALTER TABLE signals RENAME TO signals_legacy")
            db.execute("""
                CREATE TABLE signals(
                    id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL,
                    market TEXT, ticker TEXT, bar_date TEXT, signal TEXT, score INTEGER,
                    close REAL, entry_low REAL, entry_high REAL, stop_loss REAL,
                    target REAL, reward_risk REAL,
                    owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned', payload TEXT NOT NULL,
                    UNIQUE(owner_id,market,ticker,bar_date)
                )
            """)
            db.execute("""
                INSERT INTO signals(id,scan_id,market,ticker,bar_date,signal,score,close,
                    entry_low,entry_high,stop_loss,target,reward_risk,owner_id,payload)
                SELECT id,scan_id,market,ticker,bar_date,signal,score,close,
                    entry_low,entry_high,stop_loss,target,reward_risk,'legacy-unassigned',payload
                FROM signals_legacy
            """)
            db.execute("DROP TABLE signals_legacy")
        db.execute("CREATE INDEX IF NOT EXISTS idx_scans_owner_id ON scans(owner_id,id DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_signals_owner_date ON signals(owner_id,bar_date DESC)")


def save_scan(scan: dict, db_path: str | None = None, owner_id: str | None = None) -> int:
    owner = str(owner_id or '').strip()
    if not owner: raise ValueError('Owner identity wajib diisi untuk menyimpan scan.')
    initialize(db_path)
    created_at = datetime.now(timezone.utc).isoformat()
    counts = scan.get("counts", {})
    payload = dict(scan)

    if backend_name(db_path) == "PostgreSQL":
        from psycopg.types.json import Jsonb
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO scans(created_at,scanned,failed,owner_id,payload) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                    (created_at, counts.get("scanned", 0), counts.get("failed", 0), owner, Jsonb(payload)),
                )
                scan_id = int(cur.fetchone()["id"])
                payload["scan_id"] = scan_id
                cur.execute("UPDATE scans SET payload=%s WHERE id=%s", (Jsonb(payload), scan_id))
                for item in scan.get("results", []):
                    cur.execute("""
                        INSERT INTO signals(scan_id,market,ticker,bar_date,signal,score,close,
                            entry_low,entry_high,stop_loss,target,reward_risk,owner_id,payload)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(owner_id,market,ticker,bar_date) DO NOTHING
                    """, (
                        scan_id, item.get("market"), item.get("ticker"), item.get("bar_date"),
                        item.get("signal"), item.get("score"), item.get("close"),
                        item.get("entry_low"), item.get("entry_high"), item.get("stop_loss"),
                        item.get("target"), item.get("reward_risk"), owner, Jsonb(item),
                    ))
                return scan_id

    with _connect_sqlite(db_path) as db:
        cur = db.execute(
            "INSERT INTO scans(created_at,scanned,failed,owner_id,payload) VALUES(?,?,?,?,?)",
            (created_at, counts.get("scanned", 0), counts.get("failed", 0), owner, json.dumps(payload, default=str)),
        )
        scan_id = int(cur.lastrowid)
        payload["scan_id"] = scan_id
        db.execute("UPDATE scans SET payload=? WHERE id=?", (json.dumps(payload, default=str), scan_id))
        for item in scan.get("results", []):
            db.execute("""
                INSERT OR IGNORE INTO signals(scan_id,market,ticker,bar_date,signal,score,close,
                    entry_low,entry_high,stop_loss,target,reward_risk,owner_id,payload)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                scan_id, item.get("market"), item.get("ticker"), item.get("bar_date"),
                item.get("signal"), item.get("score"), item.get("close"),
                item.get("entry_low"), item.get("entry_high"), item.get("stop_loss"),
                item.get("target"), item.get("reward_risk"), owner, json.dumps(item, default=str),
            ))
        return scan_id


def _decode_payload(value):
    return json.loads(value) if isinstance(value, str) else value


def latest_scan(db_path: str | None = None, owner_id: str | None = None):
    owner = str(owner_id or '').strip()
    if not owner: raise ValueError('Owner identity wajib diisi.')
    initialize(db_path)
    if backend_name(db_path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute("SELECT id,payload FROM scans WHERE owner_id=%s ORDER BY id DESC LIMIT 1", (owner,))
                row = cur.fetchone()
                if not row:
                    return None
                payload = _decode_payload(row["payload"])
                if isinstance(payload, dict):
                    payload.setdefault("scan_id", int(row["id"]))
                return payload
    with _connect_sqlite(db_path) as db:
        row = db.execute("SELECT id,payload FROM scans WHERE owner_id=? ORDER BY id DESC LIMIT 1", (owner,)).fetchone()
        if not row:
            return None
        payload = _decode_payload(row["payload"])
        if isinstance(payload, dict):
            payload.setdefault("scan_id", int(row["id"]))
        return payload


def signal_history(limit: int = 100, db_path: str | None = None, owner_id: str | None = None):
    owner = str(owner_id or '').strip()
    if not owner: raise ValueError('Owner identity wajib diisi.')
    initialize(db_path)
    limit = max(1, min(int(limit), 1000))
    placeholder = "%s" if backend_name(db_path) == "PostgreSQL" else "?"
    query = f"""
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
        WHERE s.owner_id={placeholder} ORDER BY s.bar_date DESC,s.id DESC LIMIT {placeholder}
    """
    if backend_name(db_path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(query, (owner, limit))
                rows = cur.fetchall()
    else:
        with _connect_sqlite(db_path) as db:
            rows = db.execute(query, (owner, limit)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["payload"] = _decode_payload(item.get("payload"))
        payload = item.get("payload")
        item["ruleset_version"] = payload.get("ruleset_version") if isinstance(payload, dict) else None
        output.append(item)
    return output


def get_pending_outcomes(limit: int = 500, db_path: str | None = None, owner_id: str | None = None):
    owner = str(owner_id or '').strip()
    if not owner: raise ValueError('Owner identity wajib diisi.')
    initialize(db_path)
    limit = max(1, min(int(limit), 2000))
    if backend_name(db_path) == "PostgreSQL":
        sql = """
            SELECT s.id,s.market,s.ticker,s.bar_date,s.close,
                   ARRAY(SELECT o.horizon FROM outcomes o WHERE o.signal_id=s.id) AS recorded
            FROM signals s WHERE s.owner_id=%s ORDER BY s.bar_date DESC LIMIT %s
        """
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(sql, (owner, limit))
                rows = cur.fetchall()
    else:
        with _connect_sqlite(db_path) as db:
            rows = db.execute("""
                SELECT s.id,s.market,s.ticker,s.bar_date,s.close,GROUP_CONCAT(o.horizon) AS recorded
                FROM signals s LEFT JOIN outcomes o ON o.signal_id=s.id
                WHERE s.owner_id=? GROUP BY s.id ORDER BY s.bar_date DESC LIMIT ?
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
    if isinstance(horizon, bool) or horizon not in OUTCOME_HORIZONS:
        raise ValueError("Horizon hanya 1, 3, 5, 10, atau 20 sesi.")
    try:
        observed = date.fromisoformat(str(observed_date))
        observed_close = float(close)
    except (TypeError, ValueError) as exc:
        raise ValueError("Tanggal observasi harus ISO YYYY-MM-DD dan harga harus numerik.") from exc
    if not math.isfinite(observed_close) or observed_close <= 0:
        raise ValueError("Harga observasi harus finite dan positif.")
    initialize(db_path)
    if backend_name(db_path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute("SELECT close,bar_date FROM signals WHERE id=%s", (signal_id,))
                row = cur.fetchone()
                if not row or row["close"] is None:
                    raise ValueError("Signal tidak ditemukan atau harga awal tidak valid.")
                initial_close = float(row["close"])
                if not math.isfinite(initial_close) or initial_close <= 0:
                    raise ValueError("Harga awal signal harus finite dan positif.")
                if observed <= date.fromisoformat(str(row["bar_date"])[:10]):
                    raise ValueError("Tanggal observasi harus setelah tanggal signal.")
                ret = (observed_close / initial_close - 1) * 100
                cur.execute("""
                    INSERT INTO outcomes(signal_id,horizon,observed_date,close,return_pct)
                    VALUES(%s,%s,%s,%s,%s)
                    ON CONFLICT(signal_id,horizon) DO UPDATE SET
                    observed_date=EXCLUDED.observed_date,close=EXCLUDED.close,return_pct=EXCLUDED.return_pct
                """, (signal_id, horizon, observed.isoformat(), observed_close, ret))
        return ret
    with _connect_sqlite(db_path) as db:
        row = db.execute("SELECT close,bar_date FROM signals WHERE id=?", (signal_id,)).fetchone()
        if not row or row["close"] is None:
            raise ValueError("Signal tidak ditemukan atau harga awal tidak valid.")
        initial_close = float(row["close"])
        if not math.isfinite(initial_close) or initial_close <= 0:
            raise ValueError("Harga awal signal harus finite dan positif.")
        if observed <= date.fromisoformat(str(row["bar_date"])[:10]):
            raise ValueError("Tanggal observasi harus setelah tanggal signal.")
        ret = (observed_close / initial_close - 1) * 100
        db.execute("""
            INSERT OR REPLACE INTO outcomes(signal_id,horizon,observed_date,close,return_pct)
            VALUES(?,?,?,?,?)
        """, (signal_id, horizon, observed.isoformat(), observed_close, ret))
        return ret


def outcome_summary(db_path: str | None = None):
    """Summarize realized forward returns overall and by ruleset/signal type.

    Only rows already present in outcomes are included, so incomplete forward
    horizons are never treated as zero-return observations.
    """
    initialize(db_path)
    query = """
        SELECT o.horizon, o.return_pct, s.signal, s.score, s.payload
        FROM outcomes o
        JOIN signals s ON s.id=o.signal_id
        WHERE o.return_pct IS NOT NULL
        ORDER BY o.horizon
    """
    if backend_name(db_path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute(query)
                records = [dict(row) for row in cur.fetchall()]
    else:
        with _connect_sqlite(db_path) as db:
            records = [dict(row) for row in db.execute(query).fetchall()]

    groups = {}
    for record in records:
        payload = _decode_payload(record.get("payload"))
        payload = payload if isinstance(payload, dict) else {}
        ruleset = payload.get("ruleset_version") or "unknown"
        signal_type = record.get("signal") or payload.get("signal") or "unknown"
        value = float(record["return_pct"])
        if not math.isfinite(value):
            continue
        horizon = int(record["horizon"])
        keys = [
            (horizon, "ALL", "ALL"),
            (horizon, str(ruleset), "ALL"),
            (horizon, str(ruleset), str(signal_type)),
        ]
        for key in keys:
            groups.setdefault(key, []).append(value)

    output = []
    for (horizon, ruleset, signal_type), values in sorted(groups.items()):
        count = len(values)
        output.append({
            "horizon": horizon,
            "ruleset_version": ruleset,
            "signal_type": signal_type,
            "observations": count,
            "avg_forward_return_pct": sum(values) / count,
            "median_forward_return_pct": float(__import__("statistics").median(values)),
            "positive_rate_pct": sum(value > 0 for value in values) / count * 100,
            "negative_rate_pct": sum(value < 0 for value in values) / count * 100,
            "zero_rate_pct": sum(value == 0 for value in values) / count * 100,
            "best_return_pct": max(values),
            "worst_return_pct": min(values),
        })
    return output
