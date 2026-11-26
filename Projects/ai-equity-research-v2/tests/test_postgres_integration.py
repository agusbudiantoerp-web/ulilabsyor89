"""Opt-in PostgreSQL integration tests. Use only a disposable staging/test database."""
import os
import uuid

import pandas as pd
import pytest

from daily_signal_storage import outcome_summary, record_outcome, save_scan, signal_history
from portfolio_store import delete_book, list_books, load_book, save_book
from research_run_store import delete_run, get_run, list_runs, save_run
from thesis_store import (create_thesis, delete_thesis, get_thesis, list_theses,
                          request_review, list_reviews_for_reviewer, decide_review, update_thesis)
from corporate_event_store import create_event as create_corporate_event, delete_event as delete_corporate_event, list_events as list_corporate_events
from portfolio_event_store import create_event as create_cashflow_event, delete_event as delete_cashflow_event, list_events as list_cashflow_events
from portfolio_valuation_store import save_valuations, list_valuations, delete_valuations
from security_controls import record_audit_event, verify_audit_chain, list_audit_events


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


def test_postgres_portfolio_replacement_rolls_back_on_position_failure(postgres_test_database):
    import psycopg

    suffix = uuid.uuid4().hex
    book_id = "atomic-" + suffix
    trigger_name = "reject_portfolio_position_" + suffix
    function_name = "reject_portfolio_position_fn_" + suffix
    original = pd.DataFrame([
        {"Market": "IDX", "Ticker": "BBCA", "Shares": 100, "Average Cost": 9000},
    ])
    replacement = pd.DataFrame([
        {"Market": "IDX", "Ticker": "BBCA", "Shares": 200, "Average Cost": 9500},
        {"Market": "IDX", "Ticker": "BBRI", "Shares": 50, "Average Cost": 4000},
    ])
    save_book(book_id, "Original", original, owner_id="issuer|atomic-test")
    try:
        with psycopg.connect(postgres_test_database) as db:
            db.execute(
                f"""CREATE FUNCTION {function_name}() RETURNS trigger
                LANGUAGE plpgsql AS $func$
                BEGIN
                    IF NEW.ticker = 'BBRI' THEN
                        RAISE EXCEPTION 'injected portfolio position failure';
                    END IF;
                    RETURN NEW;
                END;
                $func$"""
            )
            db.execute(
                f"""CREATE TRIGGER {trigger_name} BEFORE INSERT ON portfolio_positions
                FOR EACH ROW EXECUTE FUNCTION {function_name}()"""
            )
        with pytest.raises(psycopg.errors.RaiseException, match="injected portfolio position failure"):
            save_book(book_id, "Replacement", replacement, owner_id="issuer|atomic-test")
        assert list_books(owner_id="issuer|atomic-test")[0]["name"] == "Original"
        assert load_book(book_id, owner_id="issuer|atomic-test").to_dict("records") == [
            {"Market": "IDX", "Ticker": "BBCA", "Shares": 100.0, "Average Cost": 9000.0}
        ]
    finally:
        with psycopg.connect(postgres_test_database) as db:
            db.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON portfolio_positions")
            db.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
        delete_book(book_id, owner_id="issuer|atomic-test")


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

        # Persisted outcomes carry their own owner key and cannot leak through
        # owner-scoped summaries, even when the same symbol/date exists twice.
        record_outcome(
            alice_signal["id"], 1, "2026-01-05", 9100,
            owner_id=owner_a,
        )
        alice_summary = outcome_summary(owner_id=owner_a)
        assert len(alice_summary) == 3
        assert all(item["observations"] == 1 for item in alice_summary)
        assert outcome_summary(owner_id=owner_b) == []
        import psycopg
        with psycopg.connect(postgres_test_database) as db:
            persisted_owner = db.execute(
                "SELECT owner_id FROM outcomes WHERE signal_id=%s AND horizon=1",
                (alice_signal["id"],),
            ).fetchone()[0]
        assert persisted_owner == owner_a
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



def test_postgres_valuation_replacement_rolls_back_when_insert_fails(postgres_test_database):
    import psycopg

    owner = "issuer|valuation-rollback-" + uuid.uuid4().hex
    baseline = pd.DataFrame([
        {"date": "2026-01-01", "portfolio_value": 1000, "external_flow": 0},
        {"date": "2026-02-01", "portfolio_value": 1100, "external_flow": 0},
    ])
    trigger_name = "reject_valuation_" + uuid.uuid4().hex
    function_name = "reject_valuation_fn_" + uuid.uuid4().hex
    save_valuations(owner, "main", baseline, currency="IDR")
    try:
        with psycopg.connect(postgres_test_database) as db:
            db.execute(f"""
                CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.portfolio_value = 9999 THEN
                        RAISE EXCEPTION 'injected valuation insert failure';
                    END IF;
                    RETURN NEW;
                END;
                $$
            """)
            db.execute(f"""
                CREATE TRIGGER {trigger_name} BEFORE INSERT ON portfolio_valuations
                FOR EACH ROW EXECUTE FUNCTION {function_name}()
            """)

        replacement = pd.DataFrame([
            {"date": "2026-03-01", "portfolio_value": 9999, "external_flow": 0},
        ])
        with pytest.raises(psycopg.errors.RaiseException, match="injected valuation insert failure"):
            save_valuations(owner, "main", replacement, currency="IDR")

        # Duplicate intraday timestamps must be rejected before DELETE/INSERT,
        # because the persistent primary key is a calendar date.
        duplicate_intraday = pd.DataFrame([
            {"date": "2026-01-01T09:00:00", "portfolio_value": 1200, "external_flow": 0},
            {"date": "2026-01-01T16:30:00", "portfolio_value": 1300, "external_flow": 0},
        ])
        with pytest.raises(ValueError, match="unik"):
            save_valuations(owner, "main", duplicate_intraday, currency="IDR")

        preserved = list_valuations(owner, "main")
        assert preserved["date"].tolist() == ["2026-01-01", "2026-02-01"]
        assert preserved["portfolio_value"].tolist() == [1000.0, 1100.0]
    finally:
        with psycopg.connect(postgres_test_database) as db:
            db.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON portfolio_valuations")
            db.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
        delete_valuations(owner, "main")


def test_postgres_thesis_update_rolls_back_if_version_insert_fails(postgres_test_database):
    import psycopg

    suffix = uuid.uuid4().hex
    owner = "issuer|thesis-rollback-" + suffix
    reviewer = "issuer|reviewer-rollback-" + suffix
    trigger_name = "reject_thesis_version_" + suffix
    function_name = "reject_thesis_version_fn_" + suffix
    thesis_id = create_thesis(
        owner, "BBCA", "IDX", "Original PostgreSQL thesis",
        {"bull_case": "original", "target_price": 12000},
    )
    review_id = request_review(owner, thesis_id, reviewer, actor_id=owner)
    try:
        with psycopg.connect(postgres_test_database) as db:
            db.execute(f"""
                CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version = 2 THEN
                        RAISE EXCEPTION 'injected thesis version failure';
                    END IF;
                    RETURN NEW;
                END;
                $$
            """)
            db.execute(f"""
                CREATE TRIGGER {trigger_name} BEFORE INSERT ON research_thesis_versions
                FOR EACH ROW EXECUTE FUNCTION {function_name}()
            """)

        with pytest.raises(psycopg.errors.RaiseException, match="injected thesis version failure"):
            update_thesis(
                owner, thesis_id, title="Should roll back",
                content={"bull_case": "changed", "target_price": 1},
                status="CLOSED",
            )

        saved = get_thesis(owner, thesis_id)
        assert saved["title"] == "Original PostgreSQL thesis"
        assert saved["content"]["target_price"] == 12000
        assert [item["version"] for item in saved["versions"]] == [1]
        reviews = list_reviews_for_reviewer(reviewer)
        assert len(reviews) == 1
        assert reviews[0]["id"] == review_id
        assert reviews[0]["status"] == "PENDING"
    finally:
        with psycopg.connect(postgres_test_database) as db:
            db.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON research_thesis_versions")
            db.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
        delete_thesis(owner, thesis_id)



def test_postgres_audit_hash_chain_serializes_concurrent_appends(postgres_test_database):
    from concurrent.futures import ThreadPoolExecutor

    # Initialize the shared lock row before concurrent writers race to append.
    record_audit_event(
        "issuer|audit-bootstrap-" + uuid.uuid4().hex,
        "admin", "TEST_BOOTSTRAP", "integration_test",
        details={"scope": "postgres-concurrency"},
    )
    suffix = uuid.uuid4().hex
    actors = [f"issuer|audit-{suffix}-{index}" for index in range(24)]

    def append_event(actor):
        return record_audit_event(
            actor, "analyst", "TEST_CONCURRENT_APPEND", "integration_test",
            resource_id=actor,
            details={"batch": suffix, "source": "postgres-integration"},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        event_ids = list(executor.map(append_event, actors))

    assert len(set(event_ids)) == len(actors)
    assert verify_audit_chain()["valid"] is True
    recent = list_audit_events(limit=100)
    batch_rows = [
        row for row in recent
        if row["action"] == "TEST_CONCURRENT_APPEND"
        and row["actor_id"] in set(actors)
    ]
    assert len(batch_rows) == len(actors)
