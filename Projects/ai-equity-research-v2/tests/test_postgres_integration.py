"""Opt-in PostgreSQL integration tests. Use only a disposable staging/test database."""
import os
import uuid

import pandas as pd
import pytest

from daily_signal_storage import record_outcome, save_scan, signal_history
from portfolio_store import delete_book, list_books, load_book, save_book
from research_run_store import delete_run, get_run, list_runs, save_run


@pytest.fixture
def postgres_test_database(monkeypatch):
    url = os.getenv("AI_EQUITY_RESEARCH_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set AI_EQUITY_RESEARCH_TEST_DATABASE_URL to a disposable PostgreSQL database.")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("CLOUD_DATABASE_URL", raising=False)
    return url


def test_postgres_portfolio_owner_isolation(postgres_test_database):
    book_id = "test-" + uuid.uuid4().hex
    positions = pd.DataFrame([{
        "Market": "IDX", "Ticker": "BBCA", "Shares": 100, "Average Cost": 9000,
    }])
    save_book(book_id, "Isolation test", positions, owner_id="issuer|alice")
    try:
        assert len(list_books(owner_id="issuer|alice")) >= 1
        assert all(item["id"] != book_id for item in list_books(owner_id="issuer|bob"))
        with pytest.raises(PermissionError):
            load_book(book_id, owner_id="issuer|bob")
        assert delete_book(book_id, owner_id="issuer|bob") is False
        assert load_book(book_id, owner_id="issuer|alice").iloc[0]["Ticker"] == "BBCA"
    finally:
        delete_book(book_id, owner_id="issuer|alice")


def test_postgres_research_run_owner_isolation(postgres_test_database):
    run_id = save_run(
        owner_id="issuer|alice", run_type="single_ticker", market="IDX",
        symbols=["BBCA"], parameters={"period": "1y"},
        result={"total_return_pct": 1.5},
    )
    try:
        assert any(item["id"] == run_id for item in list_runs("issuer|alice"))
        assert all(item["id"] != run_id for item in list_runs("issuer|bob"))
        with pytest.raises(KeyError):
            get_run("issuer|bob", run_id)
        assert delete_run("issuer|bob", run_id) is False
        assert get_run("issuer|alice", run_id)["result"]["total_return_pct"] == 1.5
    finally:
        delete_run("issuer|alice", run_id)


def test_postgres_learning_records_are_owner_scoped(postgres_test_database):
    suffix = uuid.uuid4().hex[:8].upper()
    owner_a = f"issuer|test-alice-{suffix}"
    owner_b = f"issuer|test-bob-{suffix}"
    ticker = f"TST{suffix[:5]}"
    scan = {
        "counts": {"scanned": 1, "failed": 0, "success": 1},
        "results": [{
            "market": "IDX", "ticker": ticker, "bar_date": "2026-01-02",
            "signal": "WATCH", "score": 50, "close": 9000,
        }],
        "errors": [],
    }
    try:
        save_scan(scan, owner_id=owner_a)
        save_scan(scan, owner_id=owner_b)
        alice_rows = signal_history(owner_id=owner_a)
        bob_rows = signal_history(owner_id=owner_b)
        assert any(row["ticker"] == ticker and row["bar_date"] == "2026-01-02" for row in alice_rows)
        assert any(row["ticker"] == ticker and row["bar_date"] == "2026-01-02" for row in bob_rows)
        alice_signal = next(
            row for row in alice_rows
            if row["ticker"] == ticker and row["bar_date"] == "2026-01-02"
        )
        with pytest.raises(ValueError, match="Signal tidak ditemukan"):
            record_outcome(
                alice_signal["id"], 1, "2026-01-05", 9100,
                owner_id=owner_b,
            )
    finally:
        import psycopg
        with psycopg.connect(postgres_test_database) as db:
            db.execute("DELETE FROM scans WHERE owner_id = ANY(%s)", ([owner_a, owner_b],))
