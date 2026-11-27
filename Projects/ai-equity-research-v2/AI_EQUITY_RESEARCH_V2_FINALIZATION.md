# AI Equity Research V2 — Finalization Notes

## Existing V2 capabilities retained

  Research Engine, DCF, Multi Stage DCF, sensitivity and scenario analysis.
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
- Shared market-data provider adapter with Yahoo Finance, bounded retries, immediate rate-limit handling, thread-safe TTL cache and OHLCV provenance/freshness checks, including invalid/future/duplicate/unsorted bar dates and invalid cache-age guardrails.
- Scenario analysis now includes a full operating-assumption sensitivity matrix across revenue growth and EBITDA margin; unavailable cells remain visible with reasons, the UI shows the matrix, and the Excel and PDF Research Packs export the sensitivity results.
- Peer-relative valuation with currency/fiscal/source metadata, coverage and outlier flags; manual issuer-filing CSV verification with metric/period/currency exception reporting; reverse DCF with enterprise-to-equity bridge, sensitivity and cross-check against Multi-Stage DCF.
- FX-aware IDX/US portfolio returns and transaction-aware replay with historical close marks, FX-only returns on local-market holidays, explicit stale-price/FX freshness limits, base-currency cash events, external-flow-adjusted TWR and settlement payables/receivables. Monte Carlo includes seeded parametric, two-state regime-switching and circular moving-block bootstrap methods, plus validated historical price shocks and user-supplied FX/rate/sector factor stress.
- Persistent owner-scoped cash-flow/dividend ledger, cash/share reconciliation, TWR/XIRR and saved valuation snapshots. FIFO/weighted-average tax lots, realized P&L, opening lots, one-to-one broker CSV exception matching and explicit unsettled BUY/SELL settlement dates are supported; this is not a broker integration or statutory tax engine.
- Source-attributed corporate event calendar with confirmed/estimated/cancelled status, stale/duplicate/future-retrieval flags, URL validation and owner-scoped storage. Calendar coverage is explicitly non-comprehensive and official feed automation is not included.
- Versioned owner-scoped investment theses, saved research-run links, assigned reviewer inbox and version-specific review decisions.

The scoring engine is deterministic and explainable; it is not a trained ML predictor. Walk-forward evaluation uses fixed rules and does not tune on test folds. Backtests are simplified historical simulations and do not fully model taxes, actual spread, market impact, suspensions, corporate actions, survivorship bias or intrabar execution ambiguity.

## Multi-user and operational capabilities

- Streamlit-native OIDC login uses immutable issuer-bound `iss|sub` identity and server-managed roles: `viewer`, `analyst`, `portfolio_manager` and `admin`. Unknown principals fail closed.
- Owner-scoped PostgreSQL/SQLite persistence is implemented for portfolio books, cash-flow events, valuation snapshots, corporate events, thesis/version/review records, daily learning/signals/outcomes and saved single-ticker, walk-forward and multi-asset research runs.
- Session state is cleared when the authenticated principal changes.
- Admin-only Security & Audit console includes role-map visibility, permission matrix, audit-chain verification, storage routing, read-only PostgreSQL connectivity/schema/privilege/RLS diagnostics; schema migrations run out-of-band with a separate DDL identity.
- Audit events cover authentication, research and portfolio operations, cash-flow/valuation lifecycle actions, thesis/reviewer decisions, backtests, forward-outcome refreshes, report exports, audit exports and database diagnostics.
- Excel/CSV formula-injection protections include leading whitespace and Unicode BOM handling; dynamic scenario worksheet names are sanitized/de-duplicated. PDF dynamic-text escaping is implemented.
- `database_backup.py` supports integrity-checked SQLite backups and PostgreSQL custom-format logical dumps with SHA-256 manifests. `verify --manifest` validates artifact size/hash and rejects POSIX/Windows path traversal. `restore-sqlite --manifest ... --target ...` restores a verified SQLite backup through a temporary file and integrity checks; existing targets are protected unless `--overwrite` is explicitly supplied. PostgreSQL custom-format restore is implemented with SHA-256/size manifest validation, source-endpoint mismatch protection, empty-destination enforcement, transactional `pg_restore` with owner/ACL restoration disabled, and post-restore relation checks. A separate disposable-database restore drill remains an operational acceptance gate. PostgreSQL URLs are translated to libpq environment variables rather than exposed as command-line arguments.
- CI compiles Python modules and runs the complete automated suite against an ephemeral PostgreSQL 16 service. The workflow uses maintained Node 24-compatible GitHub Actions releases and cancels superseded runs on the same ref.

## Remaining release gates (not feature-development tasks)

The application code and release documentation are prepared for validation, but this does not certify a production multi-user deployment. The following require the Preview environment, administrator credentials, or operational infrastructure and are intentionally deferred to the test phase:

1. Preview Google OIDC callback and private Streamlit Secrets configuration.
2. Dedicated Preview PostgreSQL setup, schema/grant verification and two-user isolation checks.
3. Role-by-role verification of all page and operation permissions.
4. End-to-end backtest/report/export review and backup/restore rehearsal.
5. Latest feature branch CI is green (PR and push workflows); complete an independent security review before release.
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

- Latest feature-branch code head at the time of this note: `3a97ee4dbbd16d6508dfcc691d4370026a1709ed`.
- Latest push and PR workflows both passed: **809 tests and 3 subtests passed**, Python module compilation passed, dependency audit found no known vulnerabilities, and PostgreSQL 16 integration tests passed. [Push CI](https://github.com/agusbudiantoerp-web/ulilabsyor89/actions/runs/46011006248) · [PR CI](https://github.com/agusbudiantoerp-web/ulilabsyor89/actions/runs/46011015584).
- The admin Security & Audit console now reports RLS enablement, FORCE RLS, table ownership and application-role SUPERUSER/BYPASSRLS status. This is a release diagnostic, not automatic RLS policy provisioning; PostgreSQL RLS remains a required staging/production setup task.
- Bank filing extraction includes bounded Tesseract OCR fallback (English + Indonesian) for scanned PDF pages, with BMRI's Q3 2026 ratio table targeted at page 23. OCR candidates are not verified data; unavailable OCR returns `OCR REQUIRED` without inventing metrics.
- CI validates automated code paths only. It does not certify Preview OIDC, live provider credentials, two-user isolation, role permissions, live backup/restore, browser rendering or production readiness; those still require the release-gate exercise.

## Research limitations

Yahoo Finance data may be delayed, incomplete, revised, rate-limited or unavailable. IDX/US reporting currencies and fiscal periods can differ. Signals and valuation outputs are research hypotheses, not executable quotes or personalized investment advice. No module places broker orders.


## PostgreSQL RLS policy diagnostics

The read-only database health check verifies more than `relrowsecurity` and `relforcerowsecurity`: it also inspects `pg_policies` for each registered owner-scoped table. A release-ready table must have tenant-scoped permissive policy coverage for SELECT, INSERT, UPDATE, and DELETE, with both `USING` and `WITH CHECK` expressions (where applicable) binding `owner_id` to `current_setting('app.current_owner_id', true)`. Broad permissive policies and missing CRUD coverage are reported as release blockers. This remains diagnostic only: it does not create policies, set per-transaction owner context, or change database privileges. Actual RLS rollout still requires a separately reviewed migration and integration tests using the restricted non-owner application role.

- Forward-learning outcomes now persist their own tenant owner ID in SQLite and PostgreSQL; migrations backfill from parent signals, writes verify ownership, and history/summary joins enforce owner matching. Cross-owner regression coverage is included.


- PostgreSQL schema DDL has been separated from the deployed runtime identity. The new out-of-band migration command requires a dedicated private `DATABASE_URL` plus explicit confirmation; the Streamlit admin console is now read-only for database diagnostics. RLS policy provisioning and transaction owner context are still not implemented.
