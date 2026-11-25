"""Owner-scoped persistence for manually curated corporate events."""
from __future__ import annotations

import json
import os
import numbers
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from corporate_action_calendar import normalize_corporate_events


def _url():
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


def _sqlite(path=None):
    target = path or os.getenv("CORPORATE_EVENTS_DB_PATH", "data/corporate_events.sqlite3")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
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
    return psycopg.connect(_url(), row_factory=dict_row, connect_timeout=15)


def initialize(path=None):
    if path is None and _url():
        with _pg() as db:
            with db.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS corporate_events(
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, ticker TEXT NOT NULL,
                    event_type TEXT NOT NULL, event_date TEXT NOT NULL, status TEXT NOT NULL,
                    source TEXT NOT NULL, retrieved_at TEXT NOT NULL, payload_json JSONB NOT NULL,
                    created_at TEXT NOT NULL)""")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_corporate_events_owner_date ON corporate_events(owner_id,event_date)")
        return
    with _sqlite(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS corporate_events(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, ticker TEXT NOT NULL,
            event_type TEXT NOT NULL, event_date TEXT NOT NULL, status TEXT NOT NULL,
            source TEXT NOT NULL, retrieved_at TEXT NOT NULL, payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_corporate_events_owner_date ON corporate_events(owner_id,event_date)")


def create_events(owner_id, events, *, path=None):
    owner = str(owner_id or "").strip()
    if not owner or not isinstance(events, (list, tuple)) or not events:
        raise ValueError("Owner dan daftar event wajib diisi.")
    if any(not isinstance(event, dict) for event in events):
        raise ValueError("Setiap event harus berupa dictionary.")
    # Enforce the same event taxonomy, date, provenance URL and numeric rules
    # at the persistence boundary, not only in the Streamlit form/import path.
    validated = normalize_corporate_events(events)["events"]
    now = datetime.now(timezone.utc).isoformat()
    rows, event_ids = [], []
    for event in validated.to_dict("records"):
        normalized = {}
        for key, value in event.items():
            try:
                missing = pd.isna(value)
                if bool(missing) if not hasattr(missing, "__len__") else False:
                    normalized[key] = None
                    continue
            except (TypeError, ValueError):
                pass
            if hasattr(value, "isoformat"):
                normalized[key] = value.isoformat()
            elif hasattr(value, "item"):
                normalized[key] = value.item()
            else:
                normalized[key] = value
        event_id = uuid.uuid4().hex
        payload = json.dumps(normalized, ensure_ascii=False, default=str, allow_nan=False)
        json_payload = json.loads(payload)
        rows.append((
            event_id, owner, str(normalized["ticker"]).upper(), str(normalized["event_type"]).upper(),
            str(normalized["event_date"]), str(normalized["status"]).upper(), str(normalized["source"]),
            str(normalized["retrieved_at"]), payload, json_payload, now,
        ))
        event_ids.append(event_id)
    initialize(path)
    if path is None and _url():
        from psycopg.types.json import Jsonb
        with _pg() as db:
            with db.cursor() as cur:
                cur.executemany("""INSERT INTO corporate_events
                    (id,owner_id,ticker,event_type,event_date,status,source,retrieved_at,payload_json,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
                    (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], Jsonb(row[9]), row[10])
                    for row in rows
                ])
    else:
        with _sqlite(path) as db:
            db.executemany("""INSERT INTO corporate_events
                (id,owner_id,ticker,event_type,event_date,status,source,retrieved_at,payload_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", [
                (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[10])
                for row in rows
            ])
    return event_ids


def create_event(owner_id, event, *, path=None):
    return create_events(owner_id, [event], path=path)[0]

def list_events(owner_id, *, path=None, limit=1000):
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    if isinstance(limit, bool) or not isinstance(limit, numbers.Integral) or int(limit) < 1:
        raise ValueError("Limit harus berupa bilangan bulat positif.")
    bounded = min(int(limit), 5000)
    initialize(path)
    if path is None and _url():
        with _pg() as db:
            rows = db.execute("SELECT id,payload_json,created_at FROM corporate_events WHERE owner_id=%s ORDER BY event_date DESC LIMIT %s",(owner,bounded)).fetchall()
    else:
        with _sqlite(path) as db:
            rows = db.execute("SELECT id,payload_json,created_at FROM corporate_events WHERE owner_id=? ORDER BY event_date DESC LIMIT ?",(owner,bounded)).fetchall()
    result=[]
    for row in rows:
        payload=row["payload_json"]
        if isinstance(payload,str):
            payload=json.loads(payload)
        result.append({"id":row["id"],"created_at":row["created_at"],**payload})
    return result


def delete_event(owner_id, event_id, *, path=None):
    owner=str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    initialize(path)
    if path is None and _url():
        with _pg() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM corporate_events WHERE id=%s AND owner_id=%s RETURNING id",(event_id,owner))
                return cur.fetchone() is not None
    with _sqlite(path) as db:
        cur=db.execute("DELETE FROM corporate_events WHERE id=? AND owner_id=?",(event_id,owner))
        return cur.rowcount > 0
