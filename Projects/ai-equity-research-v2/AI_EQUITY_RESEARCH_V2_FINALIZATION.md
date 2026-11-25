# AI Equity Research V2 — Finalization Notes

## Existing V2 capabilities retained

- Research Engine, DCF, Multi-Stage DCF, sensitivity and scenario analysis.
- Daily Stock Signal, local Telegram adapter, Ollama commentary and Windows scheduler.
- Excel/PDF research reports and local SQLite storage.
- Telegram allowlist remains fail-closed: an empty allowlist authorizes nobody.
- `--dry-run` bypasses the same-day delivery guard and never sends Telegram or marks a report as delivered.
- Backtest CLI prints a readable summary by default; `--json` retains machine-readable output and trade detail.

## Advanced Equity Intelligence

- Editable starter universe of 40 IDX and 40 US symbols, advanced fundamental/technical screening and transparent 0–100 factor scoring with field-level coverage.
- Market regime, relative strength and price/fundamental data-quality diagnostics.
- Portfolio exposure, sector/market/currency concentration, correlations, historical risk, price/FX scenarios, risk-parity and approximate max-Sharpe allocation.
- Single-ticker, chronological walk-forward and multi-asset backtesting with fees/slippage, risk sizing, lagged signals and benchmark comparisons.
- Forward outcome tracking at 1/3/5/10/20 completed sessions.
- Expanded Excel/PDF research packs with portfolio, market, screener, backtest, market-data provenance, cash-flow ledger, tax-lot results, broker and issuer-filing reconciliation, transaction replay, Monte Carlo outputs, DCF reconciliation, investment theses and thesis-review history.
- Shared market-data provider adapter with Yahoo Finance, bounded retries, immediate rate-limit handling, thread-safe TTL cache and OHLCV provenance/freshness checks.
- Peer-relative valuation with currency/fiscal/source metadata, coverage and outlier flags; manual issuer-filing CSV verification with metric/period/currency exception reporting; reverse DCF with enterprise-to-equity bridge, sensitivity and cross-check against Multi-Stage DCF.
- FX-aware IDX/US portfolio returns and transaction-aware replay with historical close marks, base-currency cash events, external-flow-adjusted TWR, explicit FX freshness limits and settlement payables/receivables. Monte Carlo includes seeded parametric, two-state regime-switching and circular moving-block bootstrap methods, plus historical price shocks and user-supplied FX/rate/sector factor stress.
- Persistent owner-scoped cash-flow/dividend ledger, cash/share reconciliation, TWR/XIRR and saved valuation snapshots. FIFO/weighted-average tax lots, realized P&L, opening lots, one-to-one broker CSV exception matching and explicit unsettled BUY/SELL settlement dates are supported; this is not a broker integration or statutory tax engine.
- Source-attributed corporate event calendar with confirmed/estimated/cancelled status, stale/duplicate/future-retrieval flags, URL validation and owner-scoped storage. Calendar coverage is explicitly non-comprehensive and official feed automation is not included.
- Versioned owner-scoped investment theses, saved research-run links, assigned reviewer inbox and version-specific review decisions.

The scoring engine is deterministic and explainable; it is not a trained ML predictor. Walk-forward evaluation uses fixed rules and does not tune on test folds. Backtests are simplified historical simulations and do not fully model taxes, actual spread, market impact, suspensions, corporate actions, survivorship bias or intrabar execution ambiguity.

## Multi-user and operational capabilities

- Streamlit-native OIDC login uses immutable issuer-bound `iss|sub` identity and server-managed roles: `viewer`, `analyst`, `portfolio_manager` and `admin`. Unknown principals fail closed.
- Owner-scoped PostgreSQL/SQLite persistence is implemented for portfolio books, cash-flow events, valuation snapshots, corporate events, thesis/version/review records, daily learning/signals/outcomes and saved single-ticker, walk-forward and multi-asset research runs.
- Session state is cleared when the authenticated principal changes.
- Admin-only Security & Audit console includes role-map visibility, permission matrix, audit-chain verification, storage routing, confirmed PostgreSQL schema initialization and read-only connectivity/schema/privilege diagnostics.
- Audit events cover authentication, research and portfolio operations, cash-flow/valuation lifecycle actions, thesis/reviewer decisions, backtests, forward-outcome refreshes, report exports, audit exports and database diagnostics.
- Excel/CSV formula-injection protections and PDF dynamic-text escaping are implemented.
- `database_backup.py` supports integrity-checked SQLite backups and PostgreSQL custom-format logical dumps with SHA-256 manifests. PostgreSQL URLs are translated to libpq environment variables rather than exposed as command-line arguments.
- CI compiles Python modules and runs the complete automated suite against an ephemeral PostgreSQL 16 service.

## Remaining release gates (not feature-development tasks)

The application code and release documentation are prepared for validation, but this does not certify a production multi-user deployment. The following require the Preview environment, administrator credentials, or operational infrastructure and are intentionally deferred to the test phase:

1. Preview Google OIDC callback and private Streamlit Secrets configuration.
2. Dedicated Preview PostgreSQL setup, schema/grant verification and two-user isolation checks.
3. Role-by-role verification of all page and operation permissions.
4. End-to-end backtest/report/export review and backup/restore rehearsal.
5. Final CI run on the final development commit and independent security review.
6. Administrator approval before any merge or production deployment.

Never use production database credentials for Preview or disposable integration tests. Never paste OAuth client secrets, cookie secrets, database URLs, Telegram tokens or chat IDs into chat or GitHub.

## Commands and local automation

Run a daily report dry-run with:

```powershell
python daily_signal_scheduler.py --dry-run
```

Run a single-ticker backtest with:

```powershell
python daily_signal_cli.py backtest BBCA IDX
```

The local scheduler remains separate from Streamlit Cloud. Keep its `.env`, Telegram credentials and local database files private.

## Current automated CI baseline

- Latest completed full CI run: **332 passed, 0 failed, 0 skipped** on the PR merge test ref; PostgreSQL 16 service health check passed.
- Python compile step passed in the same run.
- All PostgreSQL integration tests were included in the full suite using an ephemeral disposable database; this does not replace a separate Preview/staging verification.
- [GitHub Actions run #857](https://github.com/agusbudiantoerp-web/ulilabsyor89/actions/runs/45552889590).
- A subsequent run is triggered for the documentation-only release-readiness update; verify it before declaring the final development head green.
- Do not treat CI as proof of Preview or production readiness.

## Research limitations

Yahoo Finance data may be delayed, incomplete, revised, rate-limited or unavailable. IDX/US reporting currencies and fiscal periods can differ. Signals and valuation outputs are research hypotheses, not executable quotes or personalized investment advice. No module places broker orders.
