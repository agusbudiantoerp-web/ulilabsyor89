"""Private local SQLite persistence for user-entered portfolio books."""
from __future__ import annotations

import os
import sqlite3
import math
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


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
    """Use owner-scoped PostgreSQL in cloud; explicit paths remain isolated SQLite."""
    return "SQLite" if path is not None or not _database_url() else "PostgreSQL"


def _connect_postgres(owner_id=None, actor_id=None):
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL belum dikonfigurasi.")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Driver PostgreSQL belum terpasang. Instal psycopg[binary].") from exc
    if owner_id is not None or actor_id is not None:
        from postgres_rls import connect_with_owner_context
        return connect_with_owner_context(url, owner_id, actor_id)
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=15)


def _connect(path: str | None = None):
    target = path or os.getenv("PORTFOLIO_DB_PATH", "data/portfolio_books.sqlite3")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def initialize(path: str | None = None) -> None:
    if backend_name(path) == "PostgreSQL" and os.getenv("AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT") != "YES":
        return
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres() as db:
            with db.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio_books(
                        owner_id TEXT NOT NULL,
                        id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(owner_id,id)
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio_positions(
                        owner_id TEXT NOT NULL,
                        book_id TEXT NOT NULL,
                        market TEXT NOT NULL,
                        ticker TEXT NOT NULL,
                        shares DOUBLE PRECISION NOT NULL,
                        average_cost DOUBLE PRECISION NOT NULL,
                        PRIMARY KEY(owner_id,book_id,market,ticker),
                        FOREIGN KEY(owner_id,book_id)
                            REFERENCES portfolio_books(owner_id,id) ON DELETE CASCADE
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_portfolio_books_owner
                    ON portfolio_books(owner_id,updated_at DESC)
                """)
        return
    with _connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS portfolio_books(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned'
        );
        CREATE TABLE IF NOT EXISTS portfolio_positions(
            book_id TEXT NOT NULL,
            market TEXT NOT NULL,
            ticker TEXT NOT NULL,
            shares REAL NOT NULL,
            average_cost REAL NOT NULL,
            PRIMARY KEY(book_id, market, ticker)
        );
        CREATE INDEX IF NOT EXISTS idx_portfolio_positions_book
            ON portfolio_positions(book_id);
        """)
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(portfolio_books)").fetchall()
        }
        if "owner_id" not in columns:
            # Existing books are quarantined until an administrator explicitly reassigns them.
            db.execute(
                "ALTER TABLE portfolio_books ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'legacy-unassigned'"
            )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_portfolio_books_owner ON portfolio_books(owner_id)"
        )


def save_book(book_id: str, name: str, positions: pd.DataFrame,
              path: str | None = None, owner_id: str | None = None) -> int:
    if not isinstance(book_id, str) or not book_id.strip() or not isinstance(name, str) or not name.strip():
        raise ValueError("ID dan nama portfolio wajib diisi.")
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner portfolio wajib diisi.")
    required = {"Market", "Ticker", "Shares", "Average Cost"}
    if not required.issubset(positions.columns):
        raise ValueError(f"Kolom wajib: {sorted(required)}")
    frame = positions.copy()
    frame["Market"] = frame["Market"].fillna("").astype(str).str.upper().str.strip()
    frame["Ticker"] = frame["Ticker"].fillna("").astype(str).str.upper().str.strip()
    # Ignore intentionally blank editor rows, but never silently discard a
    # populated holding because its market or numeric fields are malformed.
    populated = frame["Ticker"].ne("") & ~frame["Ticker"].str.lower().isin(["nan", "none"])
    frame = frame.loc[populated].copy()
    if frame.empty:
        raise ValueError("Tidak ada posisi valid untuk disimpan.")
    if not frame["Market"].isin(["IDX", "US"]).all():
        raise ValueError("Market setiap posisi harus IDX atau US.")
    frame["Shares"] = pd.to_numeric(frame["Shares"], errors="coerce")
    frame["Average Cost"] = pd.to_numeric(frame["Average Cost"], errors="coerce")
    if frame[["Shares", "Average Cost"]].isna().any().any():
        raise ValueError("Jumlah saham dan harga rata-rata harus berupa angka valid.")
    if not all(math.isfinite(float(value)) for value in frame[["Shares", "Average Cost"]].to_numpy().ravel()):
        raise ValueError("Jumlah saham dan harga rata-rata harus finite.")
    if (frame[["Shares", "Average Cost"]] < 0).any().any():
        raise ValueError("Jumlah saham dan harga rata-rata tidak boleh negatif.")
    frame["Cost Value"] = frame["Shares"] * frame["Average Cost"]
    if not all(math.isfinite(float(value)) for value in frame["Cost Value"].to_numpy()):
        raise ValueError("Nilai modal posisi melampaui rentang numerik yang didukung.")
    frame = frame.groupby(["Market", "Ticker"], as_index=False).agg(
        {"Shares": "sum", "Cost Value": "sum"}
    )
    if not all(math.isfinite(float(value)) for value in frame[["Shares", "Cost Value"]].to_numpy().ravel()):
        raise ValueError("Agregasi posisi menghasilkan nilai non-finite.")
    frame["Average Cost"] = frame.apply(
        lambda row: row["Cost Value"] / row["Shares"] if row["Shares"] > 0 else 0.0,
        axis=1,
    )
    frame = frame.drop(columns=["Cost Value"])
    if frame.empty:
        raise ValueError("Tidak ada posisi valid untuk disimpan.")

    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres(owner) as db:
            with db.cursor() as cur:
                cur.execute("""
                    INSERT INTO portfolio_books(owner_id,id,name,updated_at)
                    VALUES(%s,%s,%s,%s)
                    ON CONFLICT(owner_id,id) DO UPDATE SET
                        name=EXCLUDED.name, updated_at=EXCLUDED.updated_at
                """, (owner, book_id, name, now))
                cur.execute(
                    "DELETE FROM portfolio_positions WHERE owner_id=%s AND book_id=%s",
                    (owner, book_id),
                )
                cur.executemany("""
                    INSERT INTO portfolio_positions(
                        owner_id,book_id,market,ticker,shares,average_cost
                    ) VALUES(%s,%s,%s,%s,%s,%s)
                """, [
                    (owner, book_id, row["Market"], row["Ticker"],
                     float(row["Shares"]), float(row["Average Cost"]))
                    for row in frame.to_dict("records")
                ])
        return len(frame)
    with _connect(path) as db:
        # Serialize ownership check and write so concurrent users cannot race
        # a book-ID collision and overwrite another owner's positions.
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT owner_id FROM portfolio_books WHERE id=?", (book_id,)
        ).fetchone()
        if existing and existing["owner_id"] != owner:
            raise PermissionError("Portfolio ini dimiliki pengguna lain; akses ditolak.")
        db.execute("""
            INSERT INTO portfolio_books(id, name, updated_at, owner_id) VALUES(?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, updated_at=excluded.updated_at
            WHERE portfolio_books.owner_id=excluded.owner_id
        """, (book_id, name, now, owner))
        db.execute("DELETE FROM portfolio_positions WHERE book_id=?", (book_id,))
        db.executemany("""
            INSERT INTO portfolio_positions(book_id, market, ticker, shares, average_cost)
            VALUES(?,?,?,?,?)
        """, [
            (book_id, row["Market"], row["Ticker"], float(row["Shares"]),
             float(row["Average Cost"]))
            for row in frame.to_dict("records")
        ])
    return len(frame)


def list_books(path: str | None = None, owner_id: str | None = None) -> list[dict]:
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner portfolio wajib diisi.")
    initialize(path)
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres(owner) as db:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT id,name,updated_at FROM portfolio_books WHERE owner_id=%s ORDER BY name",
                    (owner,),
                )
                return [dict(row) for row in cur.fetchall()]
    with _connect(path) as db:
        rows = db.execute(
            "SELECT id, name, updated_at FROM portfolio_books WHERE owner_id=? ORDER BY name",
            (owner,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_book(book_id: str, path: str | None = None, owner_id: str | None = None) -> pd.DataFrame:
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner portfolio wajib diisi.")
    initialize(path)
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres(owner) as db:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT owner_id FROM portfolio_books WHERE id=%s AND owner_id=%s",
                    (book_id, owner),
                )
                book = cur.fetchone()
                if not book:
                    cur.execute(
                        "SELECT 1 FROM portfolio_books WHERE id=%s", (book_id,)
                    )
                    if cur.fetchone():
                        raise PermissionError("Portfolio ini dimiliki pengguna lain; akses ditolak.")
                    raise KeyError("Portfolio tidak ditemukan.")
                cur.execute("""
                    SELECT market,ticker,shares,average_cost
                    FROM portfolio_positions
                    WHERE owner_id=%s AND book_id=%s ORDER BY market,ticker
                """, (owner, book_id))
                rows = cur.fetchall()
        return pd.DataFrame([
            {"Market": row["market"], "Ticker": row["ticker"],
             "Shares": row["shares"], "Average Cost": row["average_cost"]}
            for row in rows
        ], columns=["Market", "Ticker", "Shares", "Average Cost"])
    with _connect(path) as db:
        book = db.execute(
            "SELECT owner_id FROM portfolio_books WHERE id=?", (book_id,)
        ).fetchone()
        if not book:
            raise KeyError("Portfolio tidak ditemukan.")
        if book["owner_id"] != owner:
            raise PermissionError("Portfolio ini dimiliki pengguna lain; akses ditolak.")
        rows = db.execute("""
            SELECT market, ticker, shares, average_cost
            FROM portfolio_positions WHERE book_id=? ORDER BY market, ticker
        """, (book_id,)).fetchall()
    return pd.DataFrame([
        {"Market": row["market"], "Ticker": row["ticker"],
         "Shares": row["shares"], "Average Cost": row["average_cost"]}
        for row in rows
    ], columns=["Market", "Ticker", "Shares", "Average Cost"])


def delete_book(book_id: str, path: str | None = None, owner_id: str | None = None) -> bool:
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("Owner portfolio wajib diisi.")
    initialize(path)
    if backend_name(path) == "PostgreSQL":
        with _connect_postgres(owner) as db:
            with db.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_books WHERE id=%s AND owner_id=%s RETURNING id",
                    (book_id, owner),
                )
                return cur.fetchone() is not None
    with _connect(path) as db:
        book = db.execute(
            "SELECT owner_id FROM portfolio_books WHERE id=?", (book_id,)
        ).fetchone()
        if not book:
            return False
        if book["owner_id"] != owner:
            raise PermissionError("Portfolio ini dimiliki pengguna lain; akses ditolak.")
        db.execute("DELETE FROM portfolio_positions WHERE book_id=?", (book_id,))
        result = db.execute(
            "DELETE FROM portfolio_books WHERE id=? AND owner_id=?", (book_id, owner)
        )
        return result.rowcount > 0
