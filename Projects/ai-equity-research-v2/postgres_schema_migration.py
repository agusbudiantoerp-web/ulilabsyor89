"""Run idempotent PostgreSQL schema initializers with a dedicated DDL identity.

Run only from a trusted administrator workstation. Never configure this URL in
the deployed Streamlit app. This script creates/migrates schema objects; it
does not install tenant RLS policies or prove tenant isolation.
"""
from __future__ import annotations

import os


CONFIRMATION_VARIABLE = "AI_EQUITY_RESEARCH_CONFIRM_SCHEMA_MIGRATION"


def run_schema_migrations() -> tuple[str, ...]:
    # Deliberately accept only the explicit migration URL. Do not fall back
    # to a runtime/cloud URL that may have been inherited from the environment.
    database_url = os.getenv("DATABASE_URL")
    if not database_url or not database_url.strip():
        raise RuntimeError("Set a private migration DATABASE_URL before running schema migrations.")
    if os.getenv(CONFIRMATION_VARIABLE) != "YES":
        raise RuntimeError(
            f"Set {CONFIRMATION_VARIABLE}=YES to explicitly confirm schema migration."
        )

    # Only this explicit administrator command enables PostgreSQL DDL initializers.
    # Restore the process environment even on failure so a long-lived caller
    # cannot accidentally leave runtime schema initialization enabled.
    previous_schema_flag = os.environ.get("AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT")
    os.environ["AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT"] = "YES"
    try:
        from daily_signal_storage import initialize as initialize_daily_signals
        from portfolio_store import initialize as initialize_portfolios
        from research_run_store import initialize as initialize_research_runs
        from thesis_store import initialize as initialize_theses
        from corporate_event_store import initialize as initialize_corporate_events
        from portfolio_event_store import initialize as initialize_portfolio_events
        from portfolio_valuation_store import initialize as initialize_portfolio_valuations

        migrations = (
            ("daily signals and learning outcomes", initialize_daily_signals),
            ("portfolio books", initialize_portfolios),
            ("research runs", initialize_research_runs),
            ("investment theses", initialize_theses),
            ("corporate events", initialize_corporate_events),
            ("portfolio cash-flow events", initialize_portfolio_events),
            ("portfolio valuation snapshots", initialize_portfolio_valuations),
        )
        completed = []
        for label, initialize in migrations:
            initialize()
            completed.append(label)
        return tuple(completed)
    finally:
        if previous_schema_flag is None:
            os.environ.pop("AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT", None)
        else:
            os.environ["AI_EQUITY_RESEARCH_ALLOW_SCHEMA_INIT"] = previous_schema_flag


def main() -> int:
    completed = run_schema_migrations()
    print(f"PostgreSQL schema migration completed: {len(completed)} initializer groups.")
    for label in completed:
        print(f"- {label}")
    print("RLS policies were not installed. Configure a separate restricted runtime role.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
