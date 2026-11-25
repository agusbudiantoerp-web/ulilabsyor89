"""Owner-scoped portfolio valuation snapshots for persistent TWR history."""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _url():
    value=os.getenv("DATABASE_URL") or os.getenv("CLOUD_DATABASE_URL")
    if value:
        return value.strip()
    try:
        import streamlit as st
        value=st.secrets.get("DATABASE_URL") or st.secrets.get("CLOUD_DATABASE_URL")
        if not value:
            database=st.secrets.get("database",{})
            value=database.get("url") if hasattr(database,"get") else None
        return str(value).strip() if value else None
    except Exception:
        return None


def _sqlite(path=None):
    target=path or os.getenv("PORTFOLIO_VALUATIONS_DB_PATH","data/portfolio_valuations.sqlite3")
    Path(target).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(target,timeout=30)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def _pg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Driver PostgreSQL belum terpasang.") from exc
    if not _url():
        raise RuntimeError("DATABASE_URL belum dikonfigurasi.")
    return psycopg.connect(_url(),row_factory=dict_row,connect_timeout=15)


def initialize(path=None):
    if path is None and _url():
        with _pg() as db:
            with db.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS portfolio_valuations(
                    owner_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
                    valuation_date TEXT NOT NULL, portfolio_value DOUBLE PRECISION NOT NULL,
                    external_flow DOUBLE PRECISION NOT NULL, currency TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(owner_id,portfolio_id,valuation_date))""")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_valuations_owner ON portfolio_valuations(owner_id,portfolio_id,valuation_date)")
        return
    with _sqlite(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS portfolio_valuations(
            owner_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
            valuation_date TEXT NOT NULL, portfolio_value REAL NOT NULL,
            external_flow REAL NOT NULL, currency TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(owner_id,portfolio_id,valuation_date))""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_valuations_owner ON portfolio_valuations(owner_id,portfolio_id,valuation_date)")


def save_valuations(owner_id, portfolio_id, valuations, *, currency="IDR", path=None):
    owner=str(owner_id or "").strip()
    portfolio=str(portfolio_id or "").strip()
    unit=str(currency or "").strip().upper()
    if not owner or not portfolio:
        raise ValueError("Owner dan portfolio ID wajib diisi.")
    if unit not in {"IDR","USD"}:
        raise ValueError("Currency hanya mendukung IDR atau USD.")
    frame=valuations.copy() if isinstance(valuations,pd.DataFrame) else pd.DataFrame(list(valuations))
    required={"date","portfolio_value","external_flow"}
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError("Valuations wajib berisi date, portfolio_value dan external_flow.")
    frame["date"]=pd.to_datetime(frame["date"],errors="coerce")
    frame["portfolio_value"]=pd.to_numeric(frame["portfolio_value"],errors="coerce")
    frame["external_flow"]=pd.to_numeric(frame["external_flow"],errors="coerce")
    if frame[["date","portfolio_value","external_flow"]].isna().any().any():
        raise ValueError("Tanggal, nilai portfolio dan external flow harus valid.")
    if frame["date"].duplicated().any():
        raise ValueError("Tanggal valuasi untuk portfolio ini harus unik.")
    for col in ("portfolio_value","external_flow"):
        if not all(math.isfinite(float(x)) for x in frame[col]):
            raise ValueError("Valuasi harus finite.")
    if (frame["portfolio_value"]<=0).any():
        raise ValueError("Portfolio value harus positif.")
    now=datetime.now(timezone.utc).isoformat()
    initialize(path)
    rows=[(owner,portfolio,pd.Timestamp(row["date"]).date().isoformat(),float(row["portfolio_value"]),float(row["external_flow"]),unit,now) for row in frame.to_dict("records")]
    if path is None and _url():
        with _pg() as db:
            with db.cursor() as cur:
                cur.executemany("""INSERT INTO portfolio_valuations
                    (owner_id,portfolio_id,valuation_date,portfolio_value,external_flow,currency,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(owner_id,portfolio_id,valuation_date) DO UPDATE SET
                    portfolio_value=EXCLUDED.portfolio_value,external_flow=EXCLUDED.external_flow,
                    currency=EXCLUDED.currency,created_at=EXCLUDED.created_at""",rows)
    else:
        with _sqlite(path) as db:
            db.executemany("""INSERT INTO portfolio_valuations
                (owner_id,portfolio_id,valuation_date,portfolio_value,external_flow,currency,created_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(owner_id,portfolio_id,valuation_date) DO UPDATE SET
                portfolio_value=excluded.portfolio_value,external_flow=excluded.external_flow,
                currency=excluded.currency,created_at=excluded.created_at""",rows)
    return len(rows)


def list_valuations(owner_id, portfolio_id, *, path=None):
    owner=str(owner_id or "").strip()
    portfolio=str(portfolio_id or "").strip()
    if not owner or not portfolio:
        raise ValueError("Owner dan portfolio ID wajib diisi.")
    initialize(path)
    query="SELECT valuation_date AS date,portfolio_value,external_flow,currency FROM portfolio_valuations WHERE owner_id={owner} AND portfolio_id={portfolio} ORDER BY valuation_date"
    if path is None and _url():
        with _pg() as db:
            rows=db.execute(query.format(owner="%s",portfolio="%s"),(owner,portfolio)).fetchall()
    else:
        with _sqlite(path) as db:
            rows=db.execute(query.format(owner="?",portfolio="?"),(owner,portfolio)).fetchall()
    return pd.DataFrame([dict(row) for row in rows],columns=["date","portfolio_value","external_flow","currency"])


def delete_valuations(owner_id, portfolio_id, *, path=None):
    owner=str(owner_id or "").strip()
    portfolio=str(portfolio_id or "").strip()
    if not owner or not portfolio:
        raise ValueError("Owner dan portfolio ID wajib diisi.")
    initialize(path)
    if path is None and _url():
        with _pg() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM portfolio_valuations WHERE owner_id=%s AND portfolio_id=%s",(owner,portfolio))
                return cur.rowcount
    with _sqlite(path) as db:
        cur=db.execute("DELETE FROM portfolio_valuations WHERE owner_id=? AND portfolio_id=?",(owner,portfolio))
        return cur.rowcount
