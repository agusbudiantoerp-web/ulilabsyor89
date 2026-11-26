# AI Equity Research V2 — Final Multi-User Release Test Plan

This plan is intentionally separate from feature development. Run it only after the development branch is declared feature-complete. Do not merge PR #4 or deploy the development branch to the production Streamlit app until all required gates pass.

## 1. Preview OIDC setup

- Keep the production Google OAuth callback URI registered.
- Add the exact Preview app callback URI ending in `/oauth2callback` as a second **Authorized redirect URI**. Do not enter the Preview app's origin in the redirect-URI list.
- In Preview app Settings → Secrets, copy the OIDC configuration privately and change only `redirect_uri` to the Preview app callback.
- Keep Google OAuth in Testing mode while validating and add only the approved test identities as test users.
- Never paste client secrets, cookie secrets or database credentials into chat, issue comments, screenshots or Git.

## 2. PostgreSQL setup and direct verification

- Configure `DATABASE_URL` only in the Preview app's private Streamlit Secrets.
- Provision the Preview database using a dedicated migration/DDL principal from a trusted administrator workstation. Set `DATABASE_URL` privately to that migration connection and set `AI_EQUITY_RESEARCH_CONFIRM_SCHEMA_MIGRATION=YES`; run `python postgres_schema_migration.py` from this project folder. The script refuses to run without both settings and never prints the connection string.
- After schema creation, provision a separate runtime role that is not a table owner, is not SUPERUSER/BYPASSRLS, and has only the required table privileges. Apply reviewed grants and (once the transaction owner-context implementation is complete) tenant RLS policies. Do not use the migration principal as the app runtime identity.
- Configure the Preview Streamlit app's `DATABASE_URL` with the runtime role only.
- Sign in as the designated administrator and open **Security & Audit (Admin)**.
- Run **Uji koneksi, skema & hak akses PostgreSQL**. Confirm the connection, required tables, least-privilege grants, and actual RLS policy coverage pass. A failure is a release blocker; the diagnostic is read-only.
- Confirm the console identifies PostgreSQL for cloud-backed signals, portfolio books and research runs. Audit storage may intentionally use SQLite only when an explicit `audit_db_path` override is configured.
- Do not use production database credentials for Preview validation.
- Optional automated PostgreSQL storage integration tests are available in `tests/test_postgres_integration.py`. Set `AI_EQUITY_RESEARCH_TEST_DATABASE_URL` only to a disposable test database; the tests create and delete uniquely identified test records and must never target production.

## 3. Multi-user isolation

Use two distinct Google test accounts and map each verified `issuer|sub` to an approved role in Preview Secrets.

- User A creates a uniquely named portfolio book and saves a research/backtest run.
- User B must see neither record in portfolio or research-run history.
- User B must not be able to load, overwrite or delete User A's records, even if a record identifier is known.
- User A must still be able to read, reload and delete their own records.
- User A and B each create learning scans/signals. Each account must see only its own scan history and forward outcomes.
- Switch identities in a reused browser session and confirm the previous user's Streamlit session state is cleared.
- Confirm unknown principals and unmapped roles are denied by default.

## 4. Role and audit validation

- Viewer: may view permitted dashboards but cannot run analysis, manage portfolios or export reports.
- Analyst: may run research and export reports but cannot manage portfolio books or access the admin console.
- Portfolio manager: may run research, manage portfolio books and export reports, but cannot access admin-only controls.
- Admin: may access all approved pages and the Security & Audit console.
- Confirm LOGIN, LOGOUT, scan, screener, backtest, portfolio lifecycle, report export, audit export, database health and schema initialization events are recorded.
- Run audit hash-chain verification and inspect the first failing event if the chain is invalid.
- Treat the hash chain as tamper-evident, not WORM/immutable.

## 5. Backtest and report validation

- Single ticker: verify fee/slippage assumptions, trade details, equity curve, benchmark and drawdown.
- Walk-forward: verify chronological folds and out-of-sample-only aggregation.
- Multi-asset: verify signal lag, position caps, turnover costs, benchmark overlap and rejected symbols.
- Confirm IDX calculations use IDR and US calculations use USD; do not combine currencies without an explicit FX conversion.
- Export Excel and verify Summary, signal history, portfolio/risk sheets, market diagnostics and available backtest detail sheets.
- Export PDF and confirm timestamp, metrics and method/limitation notes.
- Confirm formula-like untrusted text is stored as text, not executable spreadsheet formulas.

## 6. Backup and recovery

- Create a PostgreSQL custom-format logical backup using `database_backup.py postgres` from a trusted administrator workstation.
- Verify the generated SHA-256 manifest and `pg_restore --list`.
- Restore to a separate staging database and repeat the health check and owner-isolation smoke tests.
- Never rehearse destructive restore commands against production.

## 7. Release decision

All of the following must be true before release:

- CI compile and full test suite pass.
- PostgreSQL direct verification passes on Preview.
- Two-user isolation and role tests pass.
- Audit events and chain verification pass.
- Backtest and Excel/PDF report checks pass.
- Backup restore rehearsal passes.
- Google Login Preview works with the exact callback URI.
- Administrator signs off on remaining operational risks and data-source limitations.

The application remains research support only. No broker order execution is provided.
