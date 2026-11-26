# AI Equity Research V2 — Final Multi User Release Test Plan

This plan is intentionally separate from feature development. Run it only after the development branch is declared feature complete. Do not merge PR #4 or deploy the development branch to the production Streamlit app until all required gates pass.

## 1. Preview OIDC setup

- Keep the production Google OAuth callback URI registered.
- Add the exact Preview app callback URI ending in `/oauth2callback` as a second **Authorized redirect URI**. Do not enter the Preview app's origin in the redirect-URI list.
- In Preview app Settings → Secrets, copy the OIDC configuration privately and change only `redirect_uri` to the Preview app callback.
- Keep Google OAuth in Testing mode while validating and add only the approved test identities as test users.
- Never paste client secrets, cookie secrets or database credentials into chat, issue comments, screenshots or Git.

## 2. PostgreSQL setup and direct verification

- Configure `DATABASE_URL` only in the Preview app's private Streamlit Secrets.
- Provision the Preview database using a dedicated migration/DDL principal from a trusted administrator workstation. Set `DATABASE_URL` privately to that migration connection and set `AI_EQUITY_RESEARCH_CONFIRM_SCHEMA_MIGRATION=YES`; run `python postgres_schema_migration.py` from this project folder. The script refuses to run without both settings and never prints the connection string.
- Create a separate runtime role that is not SUPERUSER, not BYPASSRLS, not a table owner and does not inherit any other PostgreSQL role. Give it no broad role memberships. Keep its password separate from the migration identity.
- With the administrator migration connection still in the private local environment, set `AI_EQUITY_RESEARCH_RUNTIME_ROLE` to the exact runtime role name and `AI_EQUITY_RESEARCH_CONFIRM_RLS_MIGRATION=YES`; run `python postgres_rls_migration.py`. The migration enables and forces RLS on 12 owner-scoped tables, installs tenant and assigned-reviewer policies, grants required table privileges and only the backing sequences needed for inserts. The migration identity must be SUPERUSER or BYPASSRLS and own the application tables (unless it is a database superuser).
- Remove the administrator `DATABASE_URL` and migration confirmation variables from the shell after the migration. Never configure the migration identity in Streamlit Secrets.
- Configure the Preview Streamlit app's `DATABASE_URL` with the runtime role only, plus the Preview-specific OIDC settings described in `OIDC_SETUP.md`.
- Sign in as the designated administrator and open **Security & Audit (Admin)**.
- Run **Uji koneksi, skema & hak akses PostgreSQL**. Confirm the connection, required tables, table grants, RLS/FORCE RLS, tenant/reviewer policy coverage, runtime-role attributes, ownership and inherited-role checks pass. A failure is a release blocker; the diagnostic is read-only. Sequence grants are verified by the PostgreSQL integration test, which checks required application inserts and denies access to an unrelated administrator-owned sequence.
- Confirm the console identifies PostgreSQL for cloud-backed signals, portfolio books, research runs and audit events. Local SQLite history is not automatically migrated to Preview.
- Do not use production database credentials for Preview validation.
- CI runs the PostgreSQL integration suite against an ephemeral PostgreSQL 16 service. It provisions a restricted runtime role and verifies tenant isolation, reviewer access, no-context read/write behavior, transaction-local context reset, audit-chain append/read and denied access to unrelated administrator-owned sequences. This CI test does not replace the Preview migration and acceptance checks.

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
- Confirm LOGIN, LOGOUT, scan, screener, backtest, portfolio lifecycle, report export, audit export and database health events are recorded. Record schema/RLS migration execution separately in the administrator's change log; migrations are intentionally not run through the app.
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
