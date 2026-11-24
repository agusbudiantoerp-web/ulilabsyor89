"""Private local SQLite persistence for user-entered portfolio books."""
from __future__ import annotations

import os
import sqlite3
import math
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


def backend_name(path: str | None = None) -> str:
    """Holdings stay local until per-user cloud authentication and isolation exist."""
    return "SQLite"


def _connect(path: str | None = None):
    target = path or os.getenv("PORTFOLIO_DB_PATH", "data/portfolio_books.sqlite3")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def initialize(path: str | None = None) -> None:
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
    frame["Market"] = frame["Market"].astype(str).str.upper().str.strip()
    frame["Ticker"] = frame["Ticker"].astype(str).str.upper().str.strip()
    frame["Shares"] = pd.to_numeric(frame["Shares"], errors="coerce")
    frame["Average Cost"] = pd.to_numeric(frame["Average Cost"], errors="coerce")
    frame = frame.dropna(subset=["Shares", "Average Cost"])
    if not all(math.isfinite(float(value)) for value in frame[["Shares", "Average Cost"]].to_numpy().ravel()):
        raise ValueError("Jumlah saham dan harga rata-rata harus finite.")
    frame = frame[
        (frame["Ticker"] != "") & (frame["Ticker"].str.lower() != "nan")
        & frame["Market"].isin(["IDX", "US"])
    ]
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
    with _connect(path) as db:
        book = db.execute(
            "SELECT owner_id FROM portfolio_books WHERE id=?", (book_id,)
        ).fetchone()
        if book and book["owner_id"] != owner:
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
    with _connect(path) as db:
        book = db.execute(
            "SELECT owner_id FROM portfolio_books WHERE id=?", (book_id,)
        ).fetchone()
        if book and book["owner_id"] != owner:
            raise PermissionError("Portfolio ini dimiliki pengguna lain; akses ditolak.")
        db.execute("DELETE FROM portfolio_positions WHERE book_id=?", (book_id,))
        result = db.execute(
            "DELETE FROM portfolio_books WHERE id=? AND owner_id=?", (book_id, owner)
        )
        return result.rowcount > 0
