import pandas as pd

from portfolio_store import backend_name, delete_book, list_books, load_book, save_book


def test_portfolio_book_round_trip_and_weighted_average_cost(tmp_path):
    db_path = str(tmp_path / "portfolio.sqlite3")
    positions = pd.DataFrame([
        {"Market": "IDX", "Ticker": "BBCA", "Shares": 100, "Average Cost": 9000},
        {"Market": "IDX", "Ticker": "BBCA", "Shares": 300, "Average Cost": 10000},
        {"Market": "US", "Ticker": "NVDA", "Shares": 2, "Average Cost": 100},
    ])
    assert save_book("book-1", "Core", positions, path=db_path, owner_id="local") == 2
    books = list_books(path=db_path, owner_id="local")
    assert len(books) == 1 and books[0]["name"] == "Core"
    loaded = load_book("book-1", path=db_path, owner_id="local")
    bbca = loaded[loaded["Ticker"] == "BBCA"].iloc[0]
    assert bbca["Shares"] == 400
    assert bbca["Average Cost"] == 9750
    assert delete_book("book-1", path=db_path, owner_id="local")
    assert list_books(path=db_path, owner_id="local") == []



def test_portfolio_store_rejects_infinite_holdings(tmp_path):
    import pytest

    db_path = str(tmp_path / "portfolio.sqlite3")
    positions = pd.DataFrame([
        {"Market": "IDX", "Ticker": "BBCA", "Shares": float("inf"), "Average Cost": 9000}
    ])
    with pytest.raises(ValueError, match="finite"):
        save_book("book-invalid", "Invalid", positions, path=db_path, owner_id="local")


def test_portfolio_store_rejects_overflowing_position_cost(tmp_path):
    import pytest

    positions = pd.DataFrame([
        {"Market": "US", "Ticker": "BIG", "Shares": 1e308, "Average Cost": 1e308}
    ])
    with pytest.raises(ValueError, match="melampaui"):
        save_book(
            "book-overflow", "Overflow", positions,
            path=str(tmp_path / "portfolio.sqlite3"), owner_id="local",
        )


def test_portfolio_books_are_isolated_by_oidc_owner(tmp_path):
    import pytest

    db_path = str(tmp_path / "portfolio.sqlite3")
    positions = pd.DataFrame([
        {"Market": "IDX", "Ticker": "BBCA", "Shares": 100, "Average Cost": 9000}
    ])
    save_book("shared-id", "Alice book", positions, path=db_path, owner_id="issuer|alice")
    assert len(list_books(path=db_path, owner_id="issuer|alice")) == 1
    assert list_books(path=db_path, owner_id="issuer|bob") == []
    with pytest.raises(PermissionError, match="pengguna lain"):
        load_book("shared-id", path=db_path, owner_id="issuer|bob")
    with pytest.raises(PermissionError, match="pengguna lain"):
        save_book("shared-id", "Hijack", positions, path=db_path, owner_id="issuer|bob")
    with pytest.raises(PermissionError, match="pengguna lain"):
        delete_book("shared-id", path=db_path, owner_id="issuer|bob")
    assert len(list_books(path=db_path, owner_id="issuer|alice")) == 1


def test_legacy_portfolio_books_are_quarantined_from_authenticated_owners(tmp_path):
    import sqlite3
    from portfolio_store import initialize

    db_path = str(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE portfolio_books(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE portfolio_positions(
                book_id TEXT NOT NULL, market TEXT NOT NULL, ticker TEXT NOT NULL,
                shares REAL NOT NULL, average_cost REAL NOT NULL,
                PRIMARY KEY(book_id, market, ticker)
            );
            INSERT INTO portfolio_books VALUES('old-book', 'Legacy', '2025-01-01');
        """)
    initialize(db_path)
    assert list_books(path=db_path, owner_id="issuer|new-user") == []
    assert list_books(path=db_path, owner_id="legacy-unassigned") == [
        {"id": "old-book", "name": "Legacy", "updated_at": "2025-01-01"}
    ]


def test_portfolio_store_requires_explicit_owner_identity(tmp_path):
    import pytest
    positions = pd.DataFrame([
        {"Market": "IDX", "Ticker": "BBCA", "Shares": 100, "Average Cost": 9000}
    ])
    path = str(tmp_path / "portfolio.sqlite3")
    with pytest.raises(ValueError, match="Owner portfolio"):
        save_book("no-owner", "No owner", positions, path=path)
    with pytest.raises(ValueError, match="Owner portfolio"):
        list_books(path=path)


def test_portfolio_load_and_delete_fail_closed_for_unknown_book(tmp_path):
    import pytest
    path = str(tmp_path / "portfolio.sqlite3")
    with pytest.raises(KeyError, match="tidak ditemukan"):
        load_book("missing", path=path, owner_id="issuer|alice")
    assert delete_book("missing", path=path, owner_id="issuer|alice") is False


def test_portfolio_backend_uses_postgres_when_cloud_url_is_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@example.invalid/db")
    assert backend_name() == "PostgreSQL"
    assert backend_name(path=str(tmp_path / "explicit-local.sqlite3")) == "SQLite"
