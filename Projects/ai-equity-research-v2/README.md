# AI Equity Research V2 — Unified Workspace

Integrated Streamlit research platform for Indonesian (IDX) and US equities. The workspace is research support only: it does not connect to a broker, submit orders, or provide personalized investment advice.

Yahoo Finance is a third-party source. Prices and fundamentals may be delayed, incomplete, revised, rate-limited, or unavailable. Verify material data against issuer filings and exchange disclosures.

## Five main menus

1. **Equity Research** — company financials, valuation, DCF, Multi-Stage DCF, sensitivity and scenarios.
2. **Daily Stock Signal** — IDX/US daily technical signals, entry/stop/target levels and candidate/watch/no-trade states. Includes a nested **Advanced Screener + AI Stock Scoring** tab.
3. **Portfolio & Risk Management** — position weights, sector/market/currency exposure, correlations, volatility, historical VaR, drawdown, price/FX scenarios and indicative candidate allocation.
4. **Backtesting** — fee/slippage-aware single-ticker backtest and chronological walk-forward evaluation.
5. **Performance & Learning** — owner-scoped PostgreSQL cloud persistence and observed 1/3/5/10/20-session forward outcomes grouped by signal and ruleset.

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

The existing five menus also include these extensions:

- **Daily Stock Signal:** market-regime classification for the IDX Composite (^JKSE) or SPY, relative strength of a selected stock versus its market benchmark over matched sessions, and OHLCV/fundamental data-quality checks. Negative valuation multiples are flagged for interpretation rather than automatically treated as invalid; quote/reporting-currency mismatches are surfaced.
- **Portfolio & Risk Management:** named portfolio books are scoped to the authenticated OIDC issuer/subject and use PostgreSQL when `DATABASE_URL` is configured; local SQLite is the fallback. Duplicate ticker rows are consolidated using share-weighted average cost. Legacy local books are quarantined as `legacy-unassigned` and are not automatically uploaded to PostgreSQL.
- **Backtesting:** multi-asset long-only portfolio simulation with maximum concurrent positions, per-position weight caps, fee/slippage costs, and a lagged signal design: completed day-t signals can only earn returns beginning on day t+1. A price-only benchmark comparison is included when benchmark data overlaps.
- **Performance & Learning:** export a research pack to Excel and a concise PDF summary.

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

A GitHub Actions workflow also runs compile checks and the complete test suite on updates to `feature/advanced-equity-intelligence`. The test suite validates deterministic logic and local SQLite storage. It does not prove live Yahoo Finance availability, Streamlit Cloud deployment, PostgreSQL credentials/network access, or broker execution behavior.

## Authentication and access control

The workspace entry point is protected by Streamlit-native OIDC login. It requires exactly one OIDC provider configuration and a server-side `[auth_roles]` mapping from immutable provider `sub` values to `viewer`, `analyst`, `portfolio_manager`, or `admin`. Missing login or role mapping is denied by default. Page access and portfolio/learning databases are owner-scoped and permission-gated. The audit hash chain is stored in PostgreSQL when configured, but it is not WORM/immutable. Remaining private data sources, managed database operations, operation-level reviews, and deployment configuration must still pass the release gates before production multi-user use.

See [OIDC_SETUP.md](OIDC_SETUP.md) for Google and Microsoft Entra ID configuration. Keep provider client secrets and the cookie secret only in Streamlit Secrets.

## Cloud performance database

Streamlit Cloud uses PostgreSQL when `DATABASE_URL` is configured in App settings → Secrets. The app creates/migrates owner-scoped scan, signal, outcome, portfolio and audit tables. Legacy learning/portfolio records are quarantined as `legacy-unassigned`; local SQLite books are not automatically uploaded. Never commit database URLs, passwords, Telegram tokens, chat IDs or local database files.

See [CLOUD_PERFORMANCE_DATABASE.md](CLOUD_PERFORMANCE_DATABASE.md) for configuration and storage details.

## Local Telegram and Ollama automation

The local Telegram/Ollama scheduler is separate from the Streamlit Cloud app. It continues using SQLite through its explicit local database path. Keep bot tokens and allowed chat IDs in local environment variables or a private `.env` file; never upload them to GitHub.

Ollama settings can be supplied privately in `.env`:

~~~env
OLLAMA_URL=http://127.0.0.1:11434/api/generate
OLLAMA_MODEL=gemma4:latest
OLLAMA_TIMEOUT_SECONDS=300
OLLAMA_NUM_PREDICT=650
~~~

## Research and model limitations

- Backtests are historical simulations, not forecasts. Results depend on the data window, fees, slippage, liquidity and assumptions.
- Walk-forward uses fixed documented rules and does not optimize parameters on test folds.
- Portfolio risk metrics show data coverage; incomplete price history means partial risk estimates.
- Forward outcomes are close-to-close observations and exclude dividends, fees and slippage.
- Yahoo Finance financials can have reporting-currency, fiscal-period and unit differences.
- Corporate actions, taxes, spreads, market impact, suspensions, survivorship bias and actual execution are not fully modeled.
- No module places trades or connects to a broker.
