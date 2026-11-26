# AI Equity Research V2 — Unified Workspace

Integrated Streamlit research platform for Indonesian (IDX) and US equities. The workspace is research support only: it does not connect to a broker, submit orders, or provide personalized investment advice.

Yahoo Finance is a third-party source. Prices and fundamentals may be delayed, incomplete, revised, rate-limited, or unavailable. Verify material data against issuer filings and exchange disclosures.

## Interface and visual system

The workspace uses a responsive dark-fintech visual system with layered navy surfaces, subtle technical grid, cyan/blue/violet accents, high-contrast metric panels, consistent controls, selected-state navigation, and reusable page-specific hero headers. The shared styling and escaped hero renderer live in `ui_theme.py` and are applied by the authenticated app shell; page logic, access controls, audit behavior and financial calculations remain separate from presentation. Equity Research, Daily Signals, Portfolio & Risk, Backtesting, Performance & Learning, Cash Flow, Valuation, Cross-Market Simulation, Corporate Actions, Investment Thesis, Review Inbox and Security & Audit use a consistent visual hierarchy. The design adapts to narrow screens, respects reduced-motion preferences, and adds visible keyboard-focus indicators plus clear disabled-control states.

## Main workspace menus

1. **Equity Research** — company financials, valuation, DCF, Multi-Stage DCF, sensitivity and scenarios.
2. **Daily Stock Signal** — IDX/US daily technical signals, entry/stop/target levels and candidate/watch/no-trade states. Includes a nested **Advanced Screener + AI Stock Scoring** tab.
3. **Portfolio & Risk Management** — position weights, sector/market/currency exposure, correlations, volatility, historical VaR, drawdown, price/FX scenarios and indicative candidate allocation.
4. **Backtesting** — fee/slippage-aware single-ticker backtest, chronological walk-forward evaluation, multi-asset simulation and owner-scoped saved run history.
5. **Performance & Learning** — owner-scoped PostgreSQL cloud persistence and observed 1/3/5/10/20-session forward outcomes grouped by signal and ruleset.
6. **Cash Flow & Return Ledger** — owner-scoped dividend/transaction events, cash/share reconciliation, TWR and XIRR.
7. **Valuation Intelligence** — peer-relative multiples, currency/fiscal provenance, outlier flags and reverse DCF sensitivity.
8. **Cross-Market & Monte Carlo** — IDR/USD FX-adjusted portfolio returns, Monte Carlo, historical and factor stress.
9. **Corporate Actions Calendar** — source-attributed earnings/dividend/split events with status and stale/duplicate checks, including confirmed dividend declaration, ex-date, record date and pay date.
10. **Investment Thesis** — owner-scoped, versioned bull/base/bear research theses linked to saved runs.
11. **Thesis Review Inbox** — assigned version-specific reviewer decisions for portfolio managers/admins.
12. **Security & Audit (admin only)** — server-managed OIDC role-map review, recent audit-event history, CSV export, on-demand hash-chain integrity verification and read-only PostgreSQL connectivity/schema/privilege diagnostics.

## Advanced screener and scoring

- Editable preset universe of 40 IDX and 40 US symbols. This is a curated starter universe, not the complete exchange listings.
- Fundamentals when supplied by Yahoo Finance: trailing/forward P/E, P/B, ROE, ROA, debt/equity, revenue/earnings growth, market capitalization and average turnover.
- Technicals: RSI(14), MACD/signal, EMA20/50/200, relative volume, ATR percentage and 20-session breakout.
- Filters: market, sector, score, native-currency market-cap range, RSI range, relative-volume minimum, breakout and price above EMA200.
- Explainable 0–100 weighted scoring: fundamentals 30%, valuation 20%, momentum 25%, liquidity 10%, risk 15%.
- Field-level data coverage is shown; scores are withheld below 35% weighted coverage. Missing data is not fabricated.
- This is a deterministic scoring model, not a trained predictive ML model or a return guarantee.

See [ADVANCED_EQUITY_INTELLIGENCE.md](ADVANCED_EQUITY_INTELLIGENCE.md) for methodology and limitations.

## Additional intelligence tools

The original research, signal, portfolio and backtest menus also include these extensions:

- **Daily Stock Signal:** market-regime classification for the IDX Composite (^JKSE) or SPY, relative strength of a selected stock versus its market benchmark over matched sessions, and OHLCV/fundamental data-quality checks. Regime/relative-strength calculations reject missing, non-numeric, non-finite, non-positive or duplicate close observations instead of silently dropping or overwriting them. Negative valuation multiples are flagged for interpretation rather than automatically treated as invalid; quote/reporting-currency mismatches are surfaced.
- **Portfolio & Risk Management:** named portfolio books can be saved, loaded and deleted with owner-scoped PostgreSQL storage when `DATABASE_URL` is configured; local SQLite is the fallback. Duplicate ticker rows are consolidated using share-weighted average cost. Legacy local books are quarantined as `legacy-unassigned` and are not automatically uploaded to PostgreSQL.
- **Backtesting:** multi-asset long-only portfolio simulation with maximum concurrent positions, per-position weight caps, fee/slippage costs, and a lagged signal design: completed day-t signals can only earn returns beginning on day t+1. A price-only benchmark comparison is included when benchmark data overlaps. Single-ticker, walk-forward and multi-asset runs can be saved, reloaded and deleted within the authenticated owner account.
- **Performance & Learning:** export a research pack to Excel and a concise PDF summary.
- **Data provenance:** provider/source ticker, currency, adjustment basis, retrieval/cache age, latest bar and OHLCV quality checks. Yahoo Finance requests use bounded retries, TTL caching and immediate rate-limit handling.
- **Cash-flow ledger:** persistent owner-scoped deposits, withdrawals, dividends, buys/sells, fees, taxes and split ratios; TWR valuation snapshots can be saved by portfolio ID. Dividend events represent cash actually received and should be entered on payment date, not declaration or ex-date.
- **Portfolio performance attribution:** combines realized P&L from FIFO/average-cost tax lots with unrealized P&L from explicitly supplied market marks, dividends, fees and taxes through a selected as-of date. Requires prices for every open ticker, validates open-lot cost-basis consistency, logs aggregate calculation/export metadata, and exports per-holding attribution. This is not TWR/XIRR, statutory tax, or an FX-adjusted return; all values must use one currency and the same cut-off.
- **Broker reconciliation auditability:** broker-statement and broker-snapshot comparisons plus their CSV exports append owner-attributed audit events with counts, cut-off dates, currencies and active export filters. Raw uploaded statements, cash balances, holdings quantities and credentials are not copied into audit metadata. Snapshot exception CSV export uses the same priority filter as the on-screen table.
- **Dividend entitlement estimate:** pairs confirmed declaration/ex/record/pay dates and estimates gross entitlement from the trade-date portfolio ledger and confirmed gross dividend per share. It does not post cash automatically and excludes broker settlement corrections, withholding tax, fractional cash-in-lieu and FX. Opening positions must be present in the ledger or supplied as an initial-position snapshot; otherwise the estimate is withheld.
- **Rights issue / HMETD estimate:** records the confirmed record date, rights-per-existing-share ratio, subscription price and currency. Estimates theoretical rights entitlement and cash required for full exercise from the trade-date portfolio ledger; fractional rights are not silently rounded. It does not subscribe, sell rights, add shares or deduct cash. Broker lot/fraction rules, trading/subscription windows, fees, taxes, oversubscription and FX must be verified from the prospectus and broker. Opening positions must be present in the ledger or supplied as an initial-position snapshot.
- **Broker statement reconciliation:** accepts canonical CSV columns and common English/Indonesian aliases (tanggal, jenis transaksi, kode saham, jumlah saham, harga, nominal). Number formats can be set to automatic, Indonesian (1.234,56) or international (1,234.56). The parser shows a normalized preview and warnings before matching; it does not infer gross/net semantics, fees, taxes, settlement, FX or write imported rows to the ledger. Review broker column definitions and currency before reconciliation.
- **Cross-market portfolio:** explicit IDR/USD base currency and FX alignment with stale-FX rejection. Daily close model only; no intraday synchronization.
- **Valuation tools:** peer median/coverage and reverse DCF implied FCF growth with sensitivity.
- **Research governance:** owner-scoped thesis version history, assigned PM/admin review, and thesis/review history plus market-data provenance included in the Excel research pack.

The multi-asset backtest is a separate fixed-rule trend simulation, not a broker execution model. Missing price bars are not forward-filled; uninvested cash earns zero. Benchmark comparisons are price-only and do not include dividends. Local SQLite files may be ephemeral on hosted instances; PostgreSQL is preferred for persistent cloud storage.


## Windows PowerShell setup

Run these commands from the repository root:

~~~powershell
cd Projects/ai-equity-research-v2
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
~~~

If PowerShell blocks virtual-environment activation, use the project's interpreter directly:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
~~~

## Automated tests

After dependencies are installed, run:

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider .\tests
~~~

A GitHub Actions workflow also runs compile checks and the complete test suite on updates to `feature/advanced-equity-intelligence`. The default test suite validates deterministic logic and local SQLite storage. Opt-in PostgreSQL tenant-isolation integration tests run only when `AI_EQUITY_RESEARCH_TEST_DATABASE_URL` points to a disposable staging/test database. Neither suite proves live Yahoo Finance availability or Streamlit Cloud deployment.

## Authentication and access control

The workspace entry point is protected by Streamlit-native OIDC login. It requires exactly one OIDC provider configuration and a server-side `[auth_roles]` mapping from immutable provider `sub` values to `viewer`, `analyst`, `portfolio_manager`, or `admin`. Analysts/portfolio managers/admins can manage their own thesis; only portfolio managers/admins can decide explicitly assigned thesis reviews. Missing login or role mapping is denied by default. Page access and portfolio/learning databases are owner-scoped and permission-gated. PostgreSQL tenant isolation currently relies on application-level owner filters and authorization checks; database-native Row-Level Security (RLS) is not enabled. Treat RLS review and enforcement as a separate production multi-user release gate. The admin-only Security & Audit console provides role-map visibility and audit-chain review. The audit hash chain is stored in PostgreSQL when configured, but it is not WORM/immutable. Report exports and administrator audit-log CSV downloads are audit-logged; Excel and CSV exports escape formula-like untrusted text. Remaining private data sources, managed database operations, operation-level reviews, and deployment configuration must still pass the release gates before production multi-user use.

See [OIDC_SETUP.md](OIDC_SETUP.md) for Google and Microsoft Entra ID configuration. The final two-user, PostgreSQL, audit, backtest, backup/restore and Preview-login validation sequence is documented in [MULTI_USER_RELEASE_TEST_PLAN.md](MULTI_USER_RELEASE_TEST_PLAN.md). Keep provider client secrets and the cookie secret only in Streamlit Secrets.

## Cloud performance database

Streamlit Cloud uses PostgreSQL when `DATABASE_URL` is configured in App settings → Secrets. The app creates/migrates owner-scoped scan, signal, outcome, portfolio, cash-flow event, valuation snapshot, corporate event, research-run, thesis/version/review and audit tables. Legacy learning/portfolio records are quarantined as `legacy-unassigned`; local SQLite books are not automatically uploaded. Never commit database URLs, passwords, Telegram tokens, chat IDs or local database files.

See [CLOUD_PERFORMANCE_DATABASE.md](CLOUD_PERFORMANCE_DATABASE.md) for configuration and storage details.

## PostgreSQL schema migration (administrator workstation)

Schema creation is deliberately separated from the Streamlit runtime. Use a dedicated, private migration/DDL connection only from a trusted administrator workstation:

~~~powershell
$env:DATABASE_URL = "YOUR_PRIVATE_MIGRATION_CONNECTION"
$env:AI_EQUITY_RESEARCH_CONFIRM_SCHEMA_MIGRATION = "YES"
python .\postgres_schema_migration.py
Remove-Item Env:DATABASE_URL
Remove-Item Env:AI_EQUITY_RESEARCH_CONFIRM_SCHEMA_MIGRATION
~~~

The script refuses to run unless both the connection and explicit confirmation are present. It never prints the connection string. After migration, configure Streamlit Secrets with a separate restricted runtime role that does not own tables and has no SUPERUSER/BYPASSRLS. Never place the migration connection in Streamlit Secrets. This schema script does not install tenant RLS policies or certify tenant isolation; RLS remains a separate reviewed release gate.

## Database backup utility

`database_backup.py` creates integrity-checked local SQLite backups and custom-format PostgreSQL logical backups. It writes SHA-256 manifests and never prints or stores the database URL in the manifest. See [CLOUD_PERFORMANCE_DATABASE.md](CLOUD_PERFORMANCE_DATABASE.md) for commands and staging-first recovery guidance. Keep generated `backups/` artifacts private; the directory is excluded from Git.

## Local Telegram and Ollama automation

The local Telegram/Ollama scheduler is separate from the Streamlit Cloud app. It continues using SQLite through its explicit local database path. Keep bot tokens and allowed chat IDs in local environment variables or a private `.env` file; never upload them to GitHub.

Ollama settings can be supplied privately in `.env`:

~~~env
OLLAMA_URL=http://127.0.0.1:11434/api/generate
OLLAMA_MODEL=gemma4:latest
OLLAMA_TIMEOUT_SECONDS=300
OLLAMA_NUM_PREDICT=650
~~~

## Broker statement and balance reconciliation

Broker CSV transactions are normalized into a preview and matched one-to-one against the internal cash-flow ledger. A separate read-only broker snapshot comparison checks cash balances and ticker quantities, reports missing/extra holdings and quantity/cash differences, and exports an exception CSV. Snapshot comparisons are blocked when currencies differ or the as-of dates exceed the configured tolerance. No broker snapshot or statement is automatically written into the portfolio ledger.

The snapshot comparison requires the user to provide the broker cash balance, currency, as-of date, and holdings as `TICKER,SHARES` rows. It also requires the ledger opening balances and its as-of date. Use matching cut-off definitions; unsettled cash, settlement timing, corporate actions, fractional entitlements/cash-in-lieu, fees/taxes and FX can explain differences. The tool is an exception report, not broker confirmation, custody evidence, or an automatic adjustment facility.

## Research and model limitations

- Backtests are historical simulations, not forecasts. Results depend on the data window, fees, slippage, liquidity and assumptions.
- Walk-forward uses fixed documented rules and does not optimize parameters on test folds.
- Portfolio risk metrics show data coverage; incomplete price history means partial risk estimates.
- Forward outcomes are close-to-close observations and exclude dividends, fees and slippage.
- Yahoo Finance financials can have reporting-currency, fiscal-period and unit differences.
- Corporate actions, taxes, spreads, market impact, suspensions, survivorship bias and actual execution are not fully modeled.
- No module places trades or connects to a broker.
