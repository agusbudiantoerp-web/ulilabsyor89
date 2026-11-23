# Cloud Performance Database

The dashboard supports two isolated storage backends:

- Local automation: SQLite at `DAILY_SIGNAL_DB` (default `data/daily_signals.sqlite3`). The local Telegram/Ollama scheduler continues using this database.
- Streamlit Cloud: PostgreSQL when `DATABASE_URL` is present in Streamlit secrets or the process environment. Cloud scans and forward outcomes are stored there.

## Streamlit Cloud configuration

1. Create a managed PostgreSQL database (for example, a Supabase project).
2. Copy its PostgreSQL connection URI. Use the provider's connection-pooler URI if direct IPv6 connectivity is unavailable.
3. In Streamlit Community Cloud, open the app settings and add this secret:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"
```

4. Reboot the Streamlit app. On first use, the application creates the `scans`, `signals`, and `outcomes` tables and indexes automatically.

Never commit the real connection URI, database password, or service credentials. Keep `.streamlit/secrets.toml` out of Git.

## Forward outcome recording

The Performance Dashboard's **Perbarui outcome 1/3/5 sesi** action checks Yahoo Finance daily closes after each stored signal's bar date. It records a horizon only when the corresponding future trading-session close exists. Existing outcomes are refreshed idempotently; unavailable future observations remain blank.

Returns are close-to-close percentage changes from the signal bar close. They do not include dividends, fees, or slippage and are not a simulated trading P/L.

## Local/cloud separation

No local SQLite file is uploaded or synchronized automatically. Local Telegram and Ollama jobs remain independent. To populate cloud history, run scans from the Streamlit Cloud app while the PostgreSQL secret is configured.
