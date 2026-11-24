# Cloud Performance Database

The dashboard supports two isolated storage backends:

- Local automation: SQLite at `DAILY_SIGNAL_DB` (default `data/daily_signals.sqlite3`). The local Telegram/Ollama scheduler continues using this database.
- Streamlit Cloud: PostgreSQL when `DATABASE_URL` is present in Streamlit secrets or the process environment. Cloud scans, signals, forward outcomes, saved portfolio books and audit events use the same PostgreSQL connection. Private scan/portfolio records are keyed by the authenticated OIDC issuer and subject; reads and writes are filtered by that owner. Audit events are append-serialized through a database lock and linked by SHA-256 hashes.

## Streamlit Cloud configuration

1. Create a managed PostgreSQL database (for example, a Supabase project).
2. Copy its PostgreSQL connection URI. Use the provider's connection-pooler URI if direct IPv6 connectivity is unavailable.
3. In Streamlit Community Cloud, open the app settings and add this secret:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"
```

4. Reboot the Streamlit app. On first use, the application creates or migrates the `scans`, `signals`, `outcomes`, `portfolio_books`, `portfolio_positions`, and `audit_events` tables and indexes automatically. Existing learning rows are assigned `legacy-unassigned` and are not visible to authenticated users. Local SQLite portfolio books are not automatically uploaded.

Never commit the real connection URI, database password, or service credentials. Keep `.streamlit/secrets.toml` out of Git.

## Forward outcome recording

The Performance Dashboard's **Perbarui outcome 1/3/5/10/20 sesi** action checks Yahoo Finance daily closes after each stored signal's bar date. It records a missing horizon only when the corresponding future trading-session close exists. Existing outcome rows are retained and not re-counted; unavailable future observations remain blank.

Returns are close-to-close percentage changes from the signal bar close. They do not include dividends, fees, or slippage and are not a simulated trading P/L.

## Local/cloud separation

No local SQLite file is uploaded or synchronized automatically. The Windows scheduler uses the separate `local-automation` owner in its local SQLite database; Streamlit users see only rows written under their own OIDC principal. Local Telegram and Ollama jobs remain independent. To populate cloud history, run scans from the Streamlit Cloud app while the PostgreSQL secret is configured.
