"""Local/cloud persistence for user-entered portfolio books and positions."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd


def _url() -> str | None:
    value = os.getenv("DATABASE_URL") or os.getenv("CLOUD_DATABASE_URL")
    if value:
        return value.strip()
    try:
        import streamlit as st
        value = st.secrets.get("DATABASE_URL") or st.secrets.get("CLOUD_DATABASE_URL")
        if not value:
            db = st.secrets.get("database", {})
            value = db.get("url") if hasattr(db, "get") else None
        return str(value).strip() if value else None
    except Exception:
        return None


def backend_name() -> str:
    return "PostgreSQL" if _url() else "SQLite"


def _connect(path: str | None = None):
    target = path or os.getenv("PORTFOLIO_DB_PATH", "data/portfolio_books.sqlite3")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def _pg_connect():
    import psycopg
    from psycopg.rows import dict_row
    url = _url()
    if not url:
        raise RuntimeError("DATABASE_URL belum dikonfigurasi.")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=15)


def initialize(path: str | None = None):
    statements = [
        """CREATE TABLE IF NOT EXISTS portfolio_books(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS portfolio_positions(
            book_id TEXT NOT NULL, market TEXT NOT NULL, ticker TEXT NOT NULL,
            shares DOUBLE PRECISION NOT NULL, average_cost DOUBLE PRECISION NOT NULL,
            PRIMARY KEY(book_id, market, ticker)
        )""",
    ]
    if backend_name() == "PostgreSQL":
        with _pg_connect() as db:
            with db.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
    else:
        with _connect(path) as db:
            db.executescript(";".join(statements).replace("DOUBLE PRECISION", "REAL"))



def save_book(book_id: str, name: str, positions: pd.DataFrame, path: str | None = None) -> int:
    if not book_id.strip() or not name.strip():
        raise ValueError("ID dan nama portfolio wajib diisi.")
    required = {"Market", "Ticker", "Shares", "Average Cost"}
    if not required.issubset(positions.columns):
        raise ValueError(f"Kolom wajib: {sorted(required)}")
    frame = positions.copy()
    frame["Market"] = frame["Market"].astype(str).str.upper().str.strip()
    frame["Ticker"] = frame["Ticker"].astype(str).str.upper().str.strip()
    frame["Shares"] = pd.to_numeric(frame["Shares"], errors="coerce")
    frame["Average Cost"] = pd.to_numeric(frame["Average Cost"], errors="coerce")
    frame = frame.dropna(subset=["Shares", "Average Cost"])
    frame = frame[(frame["Ticker"] != "") & frame["Market"].isin(["IDX", "US"])]
    if (frame[["Shares", "Average Cost"]] < 0).any().any():
        raise ValueError("Jumlah saham dan harga rata-rata tidak boleh negatif.")
    frame["Cost Value"] = frame["Shares"] * frame["Average Cost"]
    frame = frame.groupby(["Market", "Ticker"], as_index=False).agg(
        {"Shares": "sum", "Cost Value": "sum"}
    )
    frame["Average Cost"] = frame.apply(
        lambda row: row["Cost Value"] / row["Shares"] if row["Shares"] > 0 else 0.0, axis=1
    )
    frame = frame.drop(columns=["Cost Value"])
    now = datetime.now(timezone.utc).isoformat()
    initialize(path)
    if backend_name() == "PostgreSQL":
        with _pg_connect() as db:
            with db.cursor() as cur:
                cur.execute("""INSERT INTO portfolio_books(id,name,updated_at) VALUES(%s,%s,%s)
                    ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,updated_at=EXCLUDED.updated_at""",
                    (book_id, name, now))
                cur.execute("DELETE FROM portfolio_positions WHERE book_id=%s", (book_id,))
                for row in frame.to_dict("records"):
                    cur.execute("""INSERT INTO portfolio_positions(book_id,market,ticker,shares,average_cost)
                        VALUES(%s,%s,%s,%s,%s)""",
                        (book_id, row["Market"], row["Ticker"], float(row["Shares"]), float(row["Average Cost"])))
    else:
        with _connect(path) as db:
            db.execute("INSERT INTO portfolio_books(id,name,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at",
                       (book_id, name, now))
            db.execute("DELETE FROM portfolio_positions WHERE book_id=?", (book_id,))
            db.executemany("INSERT INTO portfolio_positions(book_id,market,ticker,shares,average_cost) VALUES(?,?,?,?,?)",
                           [(book_id, r["Market"], r["Ticker"], float(r["Shares"]), float(r["Average Cost"])) for r in frame.to_dict("records")])
    return len(frame)


def list_books(path: str | None = None) -> list[dict]:
    initialize(path)
    if backend_name() == "PostgreSQL":
        with _pg_connect() as db:
            with db.cursor() as cur:
                cur.execute("SELECT id,name,updated_at FROM portfolio_books ORDER BY name")
                return [dict(r) for r in cur.fetchall()]
    with _connect(path) as db:
        return [dict(r) for r in db.execute("SELECT id,name,updated_at FROM portfolio_books ORDER BY name").fetchall()]


def load_book(book_id: str, path: str | None = None) -> pd.DataFrame:
    initialize(path)
    if backend_name() == "PostgreSQL":
        with _pg_connect() as db:
            with db.cursor() as cur:
                cur.execute("SELECT market,ticker,shares,average_cost FROM portfolio_positions WHERE book_id=%s ORDER BY market,ticker", (book_id,))
                rows = cur.fetchall()
    else:
        with _connect(path) as db:
            rows = db.execute("SELECT market,ticker,shares,average_cost FROM portfolio_positions WHERE book_id=? ORDER BY market,ticker", (book_id,)).fetchall()
    return pd.DataFrame([{"Market":r["market"],"Ticker":r["ticker"],"Shares":r["shares"],"Average Cost":r["average_cost"]} for r in rows],
                        columns=["Market","Ticker","Shares","Average Cost"])


def delete_book(book_id: str, path: str | None = None) -> bool:
    initialize(path)
    if backend_name() == "PostgreSQL":
        with _pg_connect() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM portfolio_positions WHERE book_id=%s", (book_id,))
                cur.execute("DELETE FROM portfolio_books WHERE id=%s", (book_id,))
                return cur.rowcount > 0
    with _connect(path) as db:
        db.execute("DELETE FROM portfolio_positions WHERE book_id=?", (book_id,))
        cur = db.execute("DELETE FROM portfolio_books WHERE id=?", (book_id,))
        return cur.rowcount > 0
