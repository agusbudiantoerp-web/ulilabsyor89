"""Owner-scoped, versioned investment thesis persistence (SQLite/PostgreSQL)."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = {"DRAFT", "ACTIVE", "WATCH", "CLOSED"}


def _database_url():
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


def _connect(path=None):
    target = path or os.getenv("RESEARCH_THESIS_DB_PATH", "data/research_theses.sqlite3")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def _pg(owner_id=None, actor_id=None):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Driver PostgreSQL belum terpasang.") from exc
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL belum dikonfigurasi.")
    if owner_id is not None or actor_id is not None:
        from postgres_rls import connect_with_owner_context
        return connect_with_owner_context(url, owner_id, actor_id)
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=15)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str)


def _validate(owner_id, ticker, market, title, content, status, review_date):
    owner = str(owner_id or "").strip()
    symbol = str(ticker or "").strip().upper()
    market_value = str(market or "").strip().upper()
    title_value = str(title or "").strip()
    state = str(status or "DRAFT").strip().upper()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    if not symbol or market_value not in {"IDX", "US"} or not title_value:
        raise ValueError("Ticker, market IDX/US dan judul tesis wajib diisi.")
    if state not in STATUSES:
        raise ValueError("Status tesis tidak dikenal.")
    if not isinstance(content, dict):
        raise ValueError("Konten tesis harus berupa dictionary.")
    review = str(review_date or "").strip()
    if review:
        try:
            datetime.fromisoformat(review)
        except ValueError as exc:
            raise ValueError("Review date harus ISO date/datetime.") from exc
    return owner, symbol, market_value, title_value, state, review


def initialize(path=None):
    if path is None and _database_url() and os.getenv("AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT") != "YES":
        return
    if path is None and _database_url():
        with _pg() as db:
            with db.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS research_theses(
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, ticker TEXT NOT NULL,
                    market TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
                    review_date TEXT NOT NULL, current_version INTEGER NOT NULL,
                    content_json JSONB NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                cur.execute("""CREATE TABLE IF NOT EXISTS research_thesis_versions(
                    owner_id TEXT NOT NULL, thesis_id TEXT NOT NULL, version INTEGER NOT NULL,
                    actor_id TEXT NOT NULL, content_json JSONB NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(owner_id,thesis_id,version),
                    FOREIGN KEY(thesis_id) REFERENCES research_theses(id) ON DELETE CASCADE)""")
                cur.execute("""CREATE TABLE IF NOT EXISTS research_thesis_reviews(
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, thesis_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL, requested_by TEXT NOT NULL, version INTEGER NOT NULL,
                    status TEXT NOT NULL, comments TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(thesis_id) REFERENCES research_theses(id) ON DELETE CASCADE)""")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_thesis_reviews_reviewer ON research_thesis_reviews(reviewer_id,status,created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_thesis_reviews_owner ON research_thesis_reviews(owner_id,thesis_id,created_at DESC)")
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_thesis_review ON research_thesis_reviews(thesis_id,owner_id,reviewer_id,version) WHERE status='PENDING'")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_theses_owner_updated ON research_theses(owner_id,updated_at DESC)")
        return
    with _connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS research_theses(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, ticker TEXT NOT NULL,
            market TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
            review_date TEXT NOT NULL, current_version INTEGER NOT NULL,
            content_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS research_thesis_versions(
            owner_id TEXT NOT NULL, thesis_id TEXT NOT NULL, version INTEGER NOT NULL,
            actor_id TEXT NOT NULL, content_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(owner_id,thesis_id,version),
            FOREIGN KEY(thesis_id) REFERENCES research_theses(id) ON DELETE CASCADE)""")
        db.execute("""CREATE TABLE IF NOT EXISTS research_thesis_reviews(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, thesis_id TEXT NOT NULL,
            reviewer_id TEXT NOT NULL, requested_by TEXT NOT NULL, version INTEGER NOT NULL,
            status TEXT NOT NULL, comments TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(thesis_id) REFERENCES research_theses(id) ON DELETE CASCADE)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_thesis_reviews_reviewer ON research_thesis_reviews(reviewer_id,status,created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_thesis_reviews_owner ON research_thesis_reviews(owner_id,thesis_id,created_at DESC)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_thesis_review ON research_thesis_reviews(thesis_id,owner_id,reviewer_id,version) WHERE status='PENDING'")
        db.execute("CREATE INDEX IF NOT EXISTS idx_theses_owner_updated ON research_theses(owner_id,updated_at DESC)")


def create_thesis(owner_id, ticker, market, title, content, *, status="DRAFT", review_date="", actor_id="", path=None):
    owner, symbol, market_value, title_value, state, review = _validate(
        owner_id, ticker, market, title, content, status, review_date
    )
    thesis_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    payload = dict(content)
    initialize(path)
    if path is None and _database_url():
        from psycopg.types.json import Jsonb
        with _pg(owner) as db:
            with db.cursor() as cur:
                cur.execute("""INSERT INTO research_theses
                    (id,owner_id,ticker,market,title,status,review_date,current_version,content_json,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)""",
                    (thesis_id,owner,symbol,market_value,title_value,state,review,Jsonb(payload),now,now))
                cur.execute("""INSERT INTO research_thesis_versions
                    (owner_id,thesis_id,version,actor_id,content_json,created_at)
                    VALUES(%s,%s,1,%s,%s,%s)""", (owner,thesis_id,str(actor_id or owner),Jsonb(payload),now))
    else:
        with _connect(path) as db:
            db.execute("""INSERT INTO research_theses
                (id,owner_id,ticker,market,title,status,review_date,current_version,content_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,1,?,?,?)""",
                (thesis_id,owner,symbol,market_value,title_value,state,review,_json(payload),now,now))
            db.execute("""INSERT INTO research_thesis_versions
                (owner_id,thesis_id,version,actor_id,content_json,created_at)
                VALUES(?,?,1,?,?,?)""", (owner,thesis_id,str(actor_id or owner),_json(payload),now))
    return thesis_id


def list_theses(owner_id, *, path=None):
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    initialize(path)
    query = "SELECT id,ticker,market,title,status,review_date,current_version,created_at,updated_at FROM research_theses WHERE owner_id={owner} ORDER BY updated_at DESC"
    if path is None and _database_url():
        with _pg(owner) as db:
            rows = db.execute(query.format(owner="%s"), (owner,)).fetchall()
    else:
        with _connect(path) as db:
            rows = db.execute(query.format(owner="?"), (owner,)).fetchall()
    return [dict(row) for row in rows]


def get_thesis(owner_id, thesis_id, *, path=None):
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    initialize(path)
    if path is None and _database_url():
        with _pg(owner) as db:
            row = db.execute("SELECT * FROM research_theses WHERE id=%s AND owner_id=%s", (thesis_id,owner)).fetchone()
            versions = db.execute("SELECT version,actor_id,content_json,created_at FROM research_thesis_versions WHERE thesis_id=%s AND owner_id=%s ORDER BY version", (thesis_id,owner)).fetchall()
    else:
        with _connect(path) as db:
            row = db.execute("SELECT * FROM research_theses WHERE id=? AND owner_id=?", (thesis_id,owner)).fetchone()
            versions = db.execute("SELECT version,actor_id,content_json,created_at FROM research_thesis_versions WHERE thesis_id=? AND owner_id=? ORDER BY version", (thesis_id,owner)).fetchall()
    if not row:
        raise KeyError("Investment thesis tidak ditemukan untuk pengguna ini.")
    result = dict(row)
    result["content"] = result.pop("content_json")
    if isinstance(result["content"], str):
        result["content"] = json.loads(result["content"])
    result["versions"] = [{
        "version": item["version"], "actor_id": item["actor_id"],
        "content": json.loads(item["content_json"]) if isinstance(item["content_json"], str) else item["content_json"],
        "created_at": item["created_at"],
    } for item in versions]
    return result


def update_thesis(owner_id, thesis_id, *, title, content, status, review_date="", actor_id="", path=None):
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    if not isinstance(content, dict) or str(status).upper() not in STATUSES or not str(title).strip():
        raise ValueError("Title, content dan status tesis tidak valid.")
    review = str(review_date or "").strip()
    if review:
        try:
            datetime.fromisoformat(review)
        except ValueError as exc:
            raise ValueError("Review date harus ISO date/datetime.") from exc
    now = datetime.now(timezone.utc).isoformat()
    initialize(path)
    if path is None and _database_url():
        from psycopg.types.json import Jsonb
        with _pg(owner) as db:
            with db.cursor() as cur:
                cur.execute("SELECT current_version FROM research_theses WHERE id=%s AND owner_id=%s FOR UPDATE", (thesis_id,owner))
                row = cur.fetchone()
                if not row:
                    raise KeyError("Investment thesis tidak ditemukan untuk pengguna ini.")
                version = int(row["current_version"]) + 1
                cur.execute("""UPDATE research_thesis_reviews SET status='SUPERSEDED',comments='Thesis updated before reviewer decision.',updated_at=%s
                    WHERE thesis_id=%s AND owner_id=%s AND status='PENDING'""", (now, thesis_id, owner))
                cur.execute("""UPDATE research_theses SET title=%s,status=%s,review_date=%s,
                    current_version=%s,content_json=%s,updated_at=%s WHERE id=%s AND owner_id=%s""",
                    (str(title).strip(),str(status).upper(),review,version,Jsonb(content),now,thesis_id,owner))
                cur.execute("""INSERT INTO research_thesis_versions
                    (owner_id,thesis_id,version,actor_id,content_json,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    (owner,thesis_id,version,str(actor_id or owner),Jsonb(content),now))
                return version
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT current_version FROM research_theses WHERE id=? AND owner_id=?", (thesis_id,owner)).fetchone()
        if not row:
            raise KeyError("Investment thesis tidak ditemukan untuk pengguna ini.")
        version = int(row["current_version"]) + 1
        db.execute("""UPDATE research_thesis_reviews SET status='SUPERSEDED',comments='Thesis updated before reviewer decision.',updated_at=?
            WHERE thesis_id=? AND owner_id=? AND status='PENDING'""", (now, thesis_id, owner))
        db.execute("""UPDATE research_theses SET title=?,status=?,review_date=?,
            current_version=?,content_json=?,updated_at=? WHERE id=? AND owner_id=?""",
            (str(title).strip(),str(status).upper(),review,version,_json(content),now,thesis_id,owner))
        db.execute("""INSERT INTO research_thesis_versions
            (owner_id,thesis_id,version,actor_id,content_json,created_at)
            VALUES(?,?,?,?,?,?)""", (owner,thesis_id,version,str(actor_id or owner),_json(content),now))
    return version


def delete_thesis(owner_id, thesis_id, *, path=None):
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    initialize(path)
    if path is None and _database_url():
        with _pg(owner) as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM research_theses WHERE id=%s AND owner_id=%s RETURNING id", (thesis_id,owner))
                return cur.fetchone() is not None
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id FROM research_theses WHERE id=? AND owner_id=?", (thesis_id,owner)).fetchone()
        if not row:
            return False
        db.execute("DELETE FROM research_thesis_reviews WHERE thesis_id=? AND owner_id=?", (thesis_id,owner))
        db.execute("DELETE FROM research_thesis_versions WHERE thesis_id=? AND owner_id=?", (thesis_id,owner))
        return db.execute("DELETE FROM research_theses WHERE id=? AND owner_id=?", (thesis_id,owner)).rowcount > 0


def request_review(owner_id, thesis_id, reviewer_id, *, actor_id="", path=None):
    owner = str(owner_id or "").strip()
    reviewer = str(reviewer_id or "").strip()
    actor = str(actor_id or owner).strip()
    if not owner or not reviewer:
        raise ValueError("Owner dan reviewer wajib diisi.")
    if reviewer == owner:
        raise ValueError("Pemilik tesis tidak dapat menjadi reviewer untuk tesisnya sendiri.")
    initialize(path)
    review_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    if path is None and _database_url():
        with _pg(owner) as db:
            with db.cursor() as cur:
                cur.execute("SELECT current_version FROM research_theses WHERE id=%s AND owner_id=%s", (thesis_id, owner))
                thesis = cur.fetchone()
                if not thesis:
                    raise KeyError("Investment thesis tidak ditemukan untuk pengguna ini.")
                version = int(thesis["current_version"])
                cur.execute("""SELECT id FROM research_thesis_reviews
                    WHERE thesis_id=%s AND owner_id=%s AND reviewer_id=%s AND version=%s AND status='PENDING'""",
                    (thesis_id, owner, reviewer, version))
                if cur.fetchone():
                    raise ValueError("Review untuk versi tesis ini masih menunggu reviewer.")
                cur.execute("""INSERT INTO research_thesis_reviews
                    (id,owner_id,thesis_id,reviewer_id,requested_by,version,status,comments,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,'PENDING','',%s,%s)""",
                    (review_id, owner, thesis_id, reviewer, actor, version, now, now))
    else:
        with _connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            thesis = db.execute("SELECT current_version FROM research_theses WHERE id=? AND owner_id=?", (thesis_id, owner)).fetchone()
            if not thesis:
                raise KeyError("Investment thesis tidak ditemukan untuk pengguna ini.")
            version = int(thesis["current_version"])
            pending = db.execute("""SELECT id FROM research_thesis_reviews
                WHERE thesis_id=? AND owner_id=? AND reviewer_id=? AND version=? AND status='PENDING'""",
                (thesis_id, owner, reviewer, version)).fetchone()
            if pending:
                raise ValueError("Review untuk versi tesis ini masih menunggu reviewer.")
            db.execute("""INSERT INTO research_thesis_reviews
                (id,owner_id,thesis_id,reviewer_id,requested_by,version,status,comments,created_at,updated_at)
                VALUES(?,?,?,?,?,?,'PENDING','',?,?)""",
                (review_id, owner, thesis_id, reviewer, actor, version, now, now))
    return review_id


def list_reviews_for_thesis(owner_id, thesis_id, *, path=None):
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner identity wajib diisi.")
    initialize(path)
    query = """SELECT id,reviewer_id,requested_by,version,status,comments,created_at,updated_at
        FROM research_thesis_reviews WHERE owner_id={owner} AND thesis_id={thesis} ORDER BY created_at DESC"""
    if path is None and _database_url():
        with _pg(owner) as db:
            rows = db.execute(query.format(owner="%s", thesis="%s"), (owner, thesis_id)).fetchall()
    else:
        with _connect(path) as db:
            rows = db.execute(query.format(owner="?", thesis="?"), (owner, thesis_id)).fetchall()
    return [dict(row) for row in rows]


def list_reviews_for_reviewer(reviewer_id, *, path=None):
    reviewer = str(reviewer_id or "").strip()
    if not reviewer:
        raise ValueError("Reviewer identity wajib diisi.")
    initialize(path)
    query = """SELECT r.id,r.owner_id,r.thesis_id,r.version,r.status,r.comments,r.created_at,
        t.ticker,t.market,t.title FROM research_thesis_reviews r
        JOIN research_theses t ON t.id=r.thesis_id AND t.owner_id=r.owner_id
        WHERE r.reviewer_id={reviewer} ORDER BY r.created_at DESC"""
    if path is None and _database_url():
        with _pg(actor_id=reviewer_id) as db:
            rows = db.execute(query.format(reviewer="%s"), (reviewer,)).fetchall()
    else:
        with _connect(path) as db:
            rows = db.execute(query.format(reviewer="?"), (reviewer,)).fetchall()
    return [dict(row) for row in rows]


def get_review_for_reviewer(reviewer_id, review_id, *, path=None):
    reviewer = str(reviewer_id or "").strip()
    if not reviewer:
        raise ValueError("Reviewer identity wajib diisi.")
    initialize(path)
    query = """SELECT r.*,t.ticker,t.market,t.title,v.content_json
        FROM research_thesis_reviews r
        JOIN research_theses t ON t.id=r.thesis_id AND t.owner_id=r.owner_id
        JOIN research_thesis_versions v ON v.owner_id=r.owner_id AND v.thesis_id=r.thesis_id AND v.version=r.version
        WHERE r.id={id} AND r.reviewer_id={reviewer}"""
    if path is None and _database_url():
        with _pg(actor_id=reviewer_id) as db:
            row = db.execute(query.format(id="%s", reviewer="%s"), (review_id, reviewer)).fetchone()
    else:
        with _connect(path) as db:
            row = db.execute(query.format(id="?", reviewer="?"), (review_id, reviewer)).fetchone()
    if not row:
        raise KeyError("Review tidak ditemukan untuk reviewer ini.")
    result = dict(row)
    result["content"] = result.pop("content_json")
    if isinstance(result["content"], str):
        result["content"] = json.loads(result["content"])
    return result


def decide_review(reviewer_id, review_id, decision, comments="", *, path=None):
    reviewer = str(reviewer_id or "").strip()
    outcome = str(decision or "").strip().upper()
    if not reviewer:
        raise ValueError("Reviewer identity wajib diisi.")
    if outcome not in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}:
        raise ValueError("Keputusan review tidak dikenal.")
    now = datetime.now(timezone.utc).isoformat()
    initialize(path)
    if path is None and _database_url():
        with _pg(actor_id=reviewer) as db:
            with db.cursor() as cur:
                # Reviewer access is read-only at the RLS layer. Resolve the
                # assigned tenant first, then switch this transaction to that
                # owner context before applying the narrowly scoped decision.
                cur.execute(
                    "SELECT owner_id FROM research_thesis_reviews "
                    "WHERE id=%s AND reviewer_id=%s AND status='PENDING'",
                    (review_id, reviewer),
                )
                assigned = cur.fetchone()
                if not assigned:
                    raise KeyError("Review tidak ditemukan, bukan milik reviewer ini, atau sudah diputuskan.")
                tenant_owner = str(assigned["owner_id"])
                cur.execute(
                    "SELECT set_config('app.current_owner_id', %s, true)",
                    (tenant_owner,),
                )
                cur.execute("""UPDATE research_thesis_reviews SET status=%s,comments=%s,updated_at=%s
                    WHERE id=%s AND owner_id=%s AND reviewer_id=%s AND status='PENDING' RETURNING id""",
                    (outcome, str(comments or ""), now, review_id, tenant_owner, reviewer))
                if not cur.fetchone():
                    raise KeyError("Review tidak ditemukan, bukan milik reviewer ini, atau sudah diputuskan.")
    else:
        with _connect(path) as db:
            cur = db.execute("""UPDATE research_thesis_reviews SET status=?,comments=?,updated_at=?
                WHERE id=? AND reviewer_id=? AND status='PENDING'""",
                (outcome, str(comments or ""), now, review_id, reviewer))
            if cur.rowcount == 0:
                raise KeyError("Review tidak ditemukan, bukan milik reviewer ini, atau sudah diputuskan.")
    return outcome
