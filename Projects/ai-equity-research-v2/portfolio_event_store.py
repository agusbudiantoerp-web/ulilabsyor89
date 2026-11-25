"""Owner-scoped persistence for portfolio cash-flow and dividend events."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


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
    target=path or os.getenv("PORTFOLIO_EVENTS_DB_PATH","data/portfolio_cashflow_events.sqlite3")
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
                cur.execute("""CREATE TABLE IF NOT EXISTS portfolio_cashflow_events(
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, event_date TEXT NOT NULL,
                    event_type TEXT NOT NULL, ticker TEXT NOT NULL, amount DOUBLE PRECISION NOT NULL,
                    quantity DOUBLE PRECISION, price DOUBLE PRECISION, payload_json JSONB NOT NULL,
                    created_at TEXT NOT NULL)""")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_cashflow_owner_date ON portfolio_cashflow_events(owner_id,event_date)")
        return
    with _sqlite(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS portfolio_cashflow_events(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, event_date TEXT NOT NULL,
            event_type TEXT NOT NULL, ticker TEXT NOT NULL, amount REAL NOT NULL,
            quantity REAL, price REAL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cashflow_owner_date ON portfolio_cashflow_events(owner_id,event_date)")


def create_event(owner_id,event,*,path=None):
    owner=str(owner_id or "").strip()
    if not owner or not isinstance(event,dict):
        raise ValueError("Owner dan event wajib diisi.")
    required=("date","event_type","amount")
    if any(event.get(key) is None or str(event.get(key)).strip()=="" for key in required):
        raise ValueError("Date, event_type dan amount wajib diisi.")
    event_id=uuid.uuid4().hex
    now=datetime.now(timezone.utc).isoformat()
    payload=json.dumps(event,ensure_ascii=False,default=str,allow_nan=False)
    normalized=json.loads(payload)
    ticker=str(normalized.get("ticker") or "").upper().strip()
    initialize(path)
    if path is None and _url():
        from psycopg.types.json import Jsonb
        with _pg() as db:
            db.execute("""INSERT INTO portfolio_cashflow_events
                (id,owner_id,event_date,event_type,ticker,amount,quantity,price,payload_json,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (event_id,owner,str(normalized["date"]),str(normalized["event_type"]).upper(),
                 ticker,float(normalized["amount"]),normalized.get("quantity"),normalized.get("price"),
                 Jsonb(normalized),now))
    else:
        with _sqlite(path) as db:
            db.execute("""INSERT INTO portfolio_cashflow_events
                (id,owner_id,event_date,event_type,ticker,amount,quantity,price,payload_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (event_id,owner,str(normalized["date"]),str(normalized["event_type"]).upper(),
                 ticker,float(normalized["amount"]),normalized.get("quantity"),normalized.get("price"),
                 payload,now))
    return event_id


def list_events(owner_id,*,path=None,limit=5000):
    owner=str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    bounded=max(1,min(int(limit),10000))
    initialize(path)
    if path is None and _url():
        with _pg() as db:
            rows=db.execute("SELECT id,payload_json,created_at FROM portfolio_cashflow_events WHERE owner_id=%s ORDER BY event_date,id LIMIT %s",(owner,bounded)).fetchall()
    else:
        with _sqlite(path) as db:
            rows=db.execute("SELECT id,payload_json,created_at FROM portfolio_cashflow_events WHERE owner_id=? ORDER BY event_date,id LIMIT ?",(owner,bounded)).fetchall()
    result=[]
    for row in rows:
        payload=row["payload_json"]
        if isinstance(payload,str):
            payload=json.loads(payload)
        result.append({"id":row["id"],"created_at":row["created_at"],**payload})
    return result


def delete_event(owner_id,event_id,*,path=None):
    owner=str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    initialize(path)
    if path is None and _url():
        with _pg() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM portfolio_cashflow_events WHERE id=%s AND owner_id=%s RETURNING id",(event_id,owner))
                return cur.fetchone() is not None
    with _sqlite(path) as db:
        cur=db.execute("DELETE FROM portfolio_cashflow_events WHERE id=? AND owner_id=?",(event_id,owner))
        return cur.rowcount>0
