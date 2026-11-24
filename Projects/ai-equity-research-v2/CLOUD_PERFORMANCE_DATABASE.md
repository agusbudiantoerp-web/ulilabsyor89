# Cloud Performance Database

The dashboard supports two isolated storage backends:

- Local automation: SQLite at `DAILY_SIGNAL_DB` (default `data/daily_signals.sqlite3`). The local Telegram/Ollama scheduler continues using this database.
- Streamlit Cloud: PostgreSQL when `DATABASE_URL` is present in Streamlit secrets or the process environment. Cloud scans, signals, forward outcomes, saved portfolio books, research/backtest runs and audit events use the same PostgreSQL connection. Private records are keyed by the authenticated OIDC issuer and subject; reads and writes are filtered by that owner. Audit events are append-serialized through a database lock and linked by SHA-256 hashes.
- Research run history stores single-ticker, walk-forward and multi-asset backtest inputs/results under the authenticated owner. Local mode uses `RESEARCH_RUNS_DB_PATH` (default `data/research_runs.sqlite3`); cloud mode uses the owner-scoped `research_runs` PostgreSQL table. No local run history is uploaded automatically.

## Streamlit Cloud configuration

1. Create a managed PostgreSQL database (for example, a Supabase project).
2. Copy its PostgreSQL connection URI. Use the provider's connection-pooler URI if direct IPv6 connectivity is unavailable.
3. In Streamlit Community Cloud, open the app settings and add this secret:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"
```

4. Reboot the Streamlit app. On first use, the application creates or migrates the `scans`, `signals`, `outcomes`, `portfolio_books`, `portfolio_positions`, `research_runs`, and `audit_events` tables and indexes automatically. Existing learning rows are assigned `legacy-unassigned` and are not visible to authenticated users. Local SQLite portfolio books and research runs are not automatically uploaded.

Never commit the real connection URI, database password, or service credentials. Keep `.streamlit/secrets.toml` out of Git.

## Backup and recovery operations

The administrator console reports which backend is selected from configuration; it does not prove that the database is reachable or that a backup is restorable. Before multi-user production use:

1. Enable the database provider's automated backups and point-in-time recovery where available. Confirm retention, recovery-point objective and recovery-time objective with the provider; availability may depend on the selected service plan.
2. Keep a separate encrypted backup copy under administrator-controlled access. Never commit backup files or connection strings to Git.
3. For a manual PostgreSQL logical backup from a trusted administrator workstation, configure `DATABASE_URL` privately in the PowerShell process environment, then run:

~~~powershell
New-Item -ItemType Directory -Force .\backups | Out-Null
$backupFile = ".\backups\ai-equity-research-$(Get-Date -Format 'yyyyMMdd-HHmmss').dump"
pg_dump --dbname="$env:DATABASE_URL" --format=custom --no-owner --file="$backupFile"
~~~

4. A restore must be rehearsed against a separate staging database first. The following command can replace objects in the target database; do not run it against production without a verified backup and an approved maintenance window:

~~~powershell
pg_restore --clean --if-exists --no-owner --dbname="$env:DATABASE_URL" ".\backups\ai-equity-research-YYYYMMDD-HHMMSS.dump"
~~~

5. Back up role mappings and OIDC configuration separately through the provider's secure secret-management process. Do not include client secrets or database credentials in the database dump procedure or in support messages.

The application does not currently automate provider-level snapshots, PITR configuration, off-site backup replication or restore orchestration. Those remain administrator/provider operations and must be included in release validation.

## Forward outcome recording

The Performance Dashboard's **Perbarui outcome 1/3/5/10/20 sesi** action checks Yahoo Finance daily closes after each stored signal's bar date. It records a missing horizon only when the corresponding future trading-session close exists. Existing outcome rows are retained and not re-counted; unavailable future observations remain blank.

Returns are close-to-close percentage changes from the signal bar close. They do not include dividends, fees, or slippage and are not a simulated trading P/L.

## Local/cloud separation

No local SQLite file is uploaded or synchronized automatically. The Windows scheduler uses the separate `local-automation` owner in its local SQLite database; Streamlit users see only rows written under their own OIDC principal. Local Telegram and Ollama jobs remain independent. To populate cloud history, run scans from the Streamlit Cloud app while the PostgreSQL secret is configured.
