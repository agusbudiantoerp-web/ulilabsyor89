"""Opt-in PostgreSQL integration tests. Use only a disposable staging/test database."""
import os
import uuid

import pandas as pd
import pytest

from daily_signal_storage import record_outcome, save_scan, signal_history
from portfolio_store import delete_book, list_books, load_book, save_book
from research_run_store import delete_run, get_run, list_runs, save_run
from thesis_store import (create_thesis, delete_thesis, get_thesis, list_theses,
                          request_review, list_reviews_for_reviewer, decide_review, update_thesis)
from corporate_event_store import create_event as create_corporate_event, delete_event as delete_corporate_event, list_events as list_corporate_events
from portfolio_event_store import create_event as create_cashflow_event, delete_event as delete_cashflow_event, list_events as list_cashflow_events
from portfolio_valuation_store import save_valuations, list_valuations, delete_valuations


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
        assert any(item["id"] == book_id for item in list_books(owner_id="issuer|alice"))
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



def test_postgres_thesis_and_event_stores_are_owner_scoped(postgres_test_database):
    suffix = uuid.uuid4().hex
    alice = f"issuer|alice-{suffix}"
    bob = f"issuer|bob-{suffix}"
    thesis_id = create_thesis(
        alice, "BBCA", "IDX", "Postgres isolation thesis",
        {"bull_case": "growth", "target_price": 12000},
    )
    reviewer = f"issuer|reviewer-{suffix}"
    review_id = request_review(alice, thesis_id, reviewer, actor_id=alice)
    corporate_id = create_corporate_event(alice, {
        "ticker": "BBCA", "event_type": "EX_DIVIDEND",
        "event_date": "2027-01-01", "status": "CONFIRMED",
        "source": "issuer filing", "retrieved_at": "2026-11-25T00:00:00+00:00",
    })
    cashflow_id = create_cashflow_event(alice, {
        "date": "2026-11-25", "event_type": "DEPOSIT",
        "amount": 1000000, "ticker": "", "notes": "test",
    })
    try:
        assert any(item["id"] == thesis_id for item in list_theses(alice))
        assert list_theses(bob) == []
        assert len(list_reviews_for_reviewer(reviewer)) == 1
        assert list_reviews_for_reviewer(bob) == []
        assert decide_review(reviewer, review_id, "APPROVED", "PG integration approval") == "APPROVED"
        with pytest.raises(KeyError):
            get_thesis(bob, thesis_id)
        with pytest.raises(KeyError):
            update_thesis(
                bob, thesis_id, title="Unauthorized update",
                content={"bull_case": "tampered", "target_price": 1},
                status="CLOSED",
            )
        assert get_thesis(alice, thesis_id)["title"] == "Postgres isolation thesis"
        assert any(item["id"] == corporate_id for item in list_corporate_events(alice))
        assert list_corporate_events(bob) == []
        assert any(item["id"] == cashflow_id for item in list_cashflow_events(alice))
        assert list_cashflow_events(bob) == []
        assert delete_corporate_event(bob, corporate_id) is False
        assert delete_cashflow_event(bob, cashflow_id) is False
    finally:
        delete_thesis(alice, thesis_id)
        delete_corporate_event(alice, corporate_id)
        delete_cashflow_event(alice, cashflow_id)


def test_postgres_portfolio_valuation_snapshots_are_owner_scoped(postgres_test_database):
    owner = "issuer|valuation-" + uuid.uuid4().hex
    other = "issuer|other-" + uuid.uuid4().hex
    frame = pd.DataFrame([
        {"date": "2026-01-01", "portfolio_value": 1000, "external_flow": 0},
        {"date": "2026-02-01", "portfolio_value": 1100, "external_flow": 100},
    ])
    save_valuations(owner, "main", frame, currency="IDR")
    try:
        assert len(list_valuations(owner, "main")) == 2
        assert list_valuations(other, "main").empty
        assert delete_valuations(other, "main") == 0
    finally:
        delete_valuations(owner, "main")
