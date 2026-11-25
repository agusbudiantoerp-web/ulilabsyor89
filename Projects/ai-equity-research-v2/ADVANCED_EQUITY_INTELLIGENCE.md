# Advanced Equity Intelligence — V2 Workspace

This upgrade extends the existing unified Streamlit application. It does not replace the original Equity Research, DCF, Multi-Stage DCF, scenario, Telegram, Ollama, or local SQLite automation modules.

## 1. Advanced Stock Screener

- Two explicit markets: IDX and US.
- Editable preset universe: 40 IDX symbols and 40 US symbols. It is a curated, liquid starter universe, not a claim to cover every listed issuer.
- Users may replace the preset with their own ticker list.
- Fundamental fields from Yahoo Finance when available: trailing/forward P/E, P/B, ROE, ROA, debt/equity, revenue growth, earnings growth, market capitalization, average volume and average daily turnover.
- Technical fields from daily bars: RSI(14), MACD and signal, EMA20/50/200, relative volume, ATR percentage and 20-session breakout.
- Filters for market, sector, score, native-currency market-cap range, RSI range, relative volume, 20-session breakout and price above EMA200. IDX market-cap thresholds are in IDR; US thresholds are in USD.
- Missing fundamental data stays missing. The screener never invents financial values.

## 2. Explainable AI Stock Scoring

The 0–100 score is a deterministic, explainable multi-factor model, not a trained machine-learning model and not a prediction guarantee.

| Factor | Weight |
|---|---:|
| Fundamental quality | 30% |
| Valuation | 20% |
| Momentum | 25% |
| Liquidity | 10% |
| Risk | 15% |

The displayed coverage percentage is calculated from the availability of individual inputs within each factor (not merely whether one field exists for a whole factor). A score is withheld when coverage is below 35%. Liquidity uses average daily turnover, or average volume as a fallback; market capitalization is a separate filter and is not treated as tradability. Valuation thresholds are broad screening heuristics; compare companies within similar industries and verify reported currencies/periods before making a decision.

## 3. Advanced Backtesting

- Single-ticker historical simulation retains fee, slippage, risk budget and maximum allocation controls.
- Reports total return, CAGR, win rate, profit factor, maximum drawdown, Sharpe ratio, trade details and buy-and-hold benchmark.
- Chronological expanding-history walk-forward evaluation produces sequential out-of-sample test folds.
- The walk-forward test uses the fixed, documented signal rules. It does not optimize parameters on the test fold.
- IDX/US historical data availability, corporate actions, taxes, spreads, market impact, suspensions, liquidity and survivorship bias remain important limitations.

## 4. Portfolio Intelligence

- Position weights within each currency.
- Market, currency and sector exposure.
- Correlation matrices and historical volatility, 95% one-day VaR and drawdown calculated separately by currency. Risk tables show market-value coverage and explicitly flag partial price-history coverage; duplicate rows for the same ticker are aggregated for risk weighting.
- User-defined price-shock scenario analysis.
- Optional USD/IDR translation-risk scenario using a manually supplied spot rate and FX shock; this isolates currency translation while holding share prices constant.
- Indicative allocation from the latest BUY candidates, with separate IDR and USD capital budgets. IDX allocations are rounded down to 100-share board lots; US quantities use whole shares.

IDR and USD are never summed without an explicit FX conversion. The allocation planner is not connected to a broker and does not place orders.

## 5. Performance & Learning Engine

- Stores and evaluates forward returns after 1, 3, 5, 10 and 20 completed trading sessions.
- Outcomes are recorded only when the corresponding future daily close exists.
- Dashboard groups observed outcomes by signal and ruleset version, reporting observation count, mean/median return and win rate.
- PostgreSQL migration expands the allowed horizon values while retaining existing scan/signal/outcome records.
- Scan IDs are now persisted in new scan payloads and backfilled from the database row ID when older scans are read.

This is a measurement and evaluation loop, not automatic model retraining. Strategy changes should receive a new ruleset version before comparing performance.

## Data provenance and freshness contract

- Every history download records provider/source ticker, market, exchange, quote currency, retrieval timestamp, latest bar date, bar count and adjustment mode.
- A provider protocol and Yahoo Finance adapter now centralize daily-history and fundamental requests; transient history failures use bounded exponential retries, explicit rate-limit responses fail immediately without retry loops, and a thread-safe TTL cache avoids duplicate downloads while exposing cache age.
- Daily signal history, advanced screener fundamentals, Market Intelligence, peer valuation and benchmark/FX history use the shared adapter.
- The current Yahoo Finance history loader explicitly requests `auto_adjust=True`; the contract labels the resulting OHLC as provider-adjusted rather than raw/unadjusted.
- Basic OHLCV validation reports missing/non-numeric/non-finite values, invalid OHLC relationships, non-positive prices, negative volume, duplicate dates and stale bars.
- Screener results carry the provenance record, and Market Intelligence displays its source, currency, adjustment basis, latest bar and quality status.
- A passing basic quality check is not independent proof of Yahoo Finance accuracy, complete corporate-action history, point-in-time data or survivorship-bias-free coverage.

## 11. Portfolio Cash-Flow Ledger, Dividends, TWR and XIRR

- Event types: deposits, withdrawals, dividends, buys, sells, fees, taxes and stock splits.
- Event validation checks dates, event types, non-negative absolute amounts, ticker requirements and quantity/price requirements.
- The ledger separates external investor flows, dividend income and transaction costs, and reconstructs cash/share balances from deposits, withdrawals, buys, partial sells, fees, taxes and split ratios.
- TWR geometrically links sub-period returns after adding/subtracting external flows from opening capital at risk.
- XIRR solves dated investor cash flows with an ACT/365 bisection solver and optional terminal portfolio value.
- Transaction events and TWR valuation snapshots are persisted per authenticated owner in SQLite/PostgreSQL. The Research Pack includes the owner's event ledger; the ledger page also provides CSV export. Opening cash and pre-existing share positions can be supplied for reconciliation. FIFO and weighted-average tax-lot engines calculate realized P&L for partial/full sales, accept opening tax lots for pre-ledger positions, and preserve aggregate cost basis through stock splits; the page displays realized trades and remaining lots, and Research Pack Excel includes both realized P&L and open tax-lot sheets when calculated in the active session. BUY amount is treated as total acquisition cost and SELL amount as sale proceeds before separately recorded fees/taxes. Statutory tax and automatic settlement-calendar inference are not implemented. Transaction-aware replay accepts explicit BUY/SELL settlement_date values, reserves cash for unsettled purchases, holds sale proceeds as receivables until settlement, and reports pending payables/receivables. A manual normalized CSV broker-statement matcher reports matched, missing, unexpected and date/amount/quantity/price mismatches without changing the stored ledger; its exception report is included in Research Pack Excel when available.
- All amounts must use one base currency. Split events record ratio metadata; they do not independently rewrite historical prices or existing saved positions.

## 12. Cross-Market FX-Aware Portfolio Returns

- Combines IDX (IDR) and US (USD) daily close returns in an explicit IDR or USD base currency.
- USD/IDR is aligned backward as-of to each asset trading date with an explicit maximum calendar-day tolerance; missing FX coverage fails closed.
- Local asset return and FX contribution are reported separately per asset; inverse USD/IDR conversion is used for IDR assets in a USD base portfolio.
- Static target weights are preserved across market holidays; a closed market contributes zero daily return rather than being reweighted into another market.
- The cross-market page also supports transaction-aware replay from a CSV event ledger. It reconstructs cash and holdings from dated deposits, withdrawals, BUY/SELL fills, dividends, fees, taxes and splits; marks positions to backward-as-of closes; requires all event cash amounts (including foreign-asset trades and dividends) to be explicitly expressed in the portfolio base currency; fill `price` remains in the asset's local quote currency and no FX cash conversion is inferred; and calculates daily TWR after removing external deposits/withdrawals. The UI includes a CSV template and displays/export the resulting equity curve.
- This is a daily close valuation model, not an intraday synchronized execution model. It does not infer broker settlement calendars, maintain separate local-currency cash sub-ledgers, infer FX cash conversions, execute automatic fills or model market impact. Broker statement CSV reconciliation is available as a manual exception report. FX provider, timezone, market holidays and stale-data tolerance should be reviewed.

## 13. Peer-Relative Valuation

- Peer sets are explicitly filtered by industry and reporting currency.
- Summary metrics include P/E, P/B, EV/EBITDA, EV/Sales, ROE, ROIC, revenue growth and operating margin when provider data exists. Source, provider ticker, fiscal year end, quote/reporting currencies, coverage and IQR outlier flags are displayed.
- Negative/non-positive valuation multiples are excluded from peer medians; missing values remain missing and coverage is displayed.
- Metric period basis is explicitly labeled (TTM, point-in-time, or provider-defined YoY/trailing). Fiscal year-end dates more than 90 days from the peer-set median are flagged in the comparison table and UI; no automatic normalization is inferred.
- Yahoo Finance provider fields may still have inconsistent definitions and source periods. Independent issuer-filing verification and user review of the peer set remain necessary.

## 14. Reverse DCF

- Solves constant explicit-period FCF growth implied by current market price using a bounded bisection solver and shows an implied-growth sensitivity grid across WACC and terminal-growth assumptions.
- Shows present value of explicit FCF, terminal value, present value of terminal value and enterprise-to-equity bridge, with an explicit quote-currency/model-currency FX conversion factor.
- Requires normalized positive current FCF, market price, diluted shares, net debt/cash, WACC, terminal growth and explicit forecast horizon.
- Rejects WACC/terminal-growth combinations that do not converge and target prices outside the selected growth bounds.
- This is a conditional expectation analysis, not a forecast of actual future growth.

## 15. Monte Carlo and Stress Testing

- Reproducible multivariate-normal daily return simulations with a user-selectable seed, horizon and simulation count.
- Reports return percentiles, probability of loss, VaR, CVaR and median maximum drawdown.
- Covariance eigenvalues are clipped at zero when numerical estimation yields a non-positive-semidefinite covariance matrix.
- Optional two-state Markov regime-switching simulation uses rolling 20-session portfolio volatility to label calm/stress history, estimates separate means/covariances, and accepts user-supplied transition probabilities. The UI shows regime sample counts and requires at least 20 observations in each state.
- Optional circular moving-block bootstrap resamples joint historical asset-return vectors, preserving cross-asset dependence and short serial patterns; block length is user-selectable. Percentile, VaR/CVaR and loss-probability outputs are included in Research Pack.
- User-defined instantaneous price shocks calculate weighted asset contributions and unallocated cash. Factor stress combines FX, interest-rate and sector shocks using explicit user-supplied betas; FX beta is initialized from the asset/base currency relationship.
- The basic simulation assumes IID multivariate-normal returns. The optional regime model assumes a two-state Markov process and regime-conditional multivariate-normal returns; historical regime labels are based on a user-selected rolling-volatility threshold, not an independently validated classifier. The block bootstrap assumes historical joint return blocks are representative. These are scenarios, not forecasts, and exclude structural breaks, taxes, liquidity and corporate actions unless already embedded in returns. They are scenarios, not forecasts.

## 16. Corporate Actions & Event Calendar

- Tracks earnings, dividend declarations, ex-dates, pay dates, stock splits and rights issues.
- Every record carries source, source URL, retrieval date, timezone, and CONFIRMED / ESTIMATED / CANCELLED status. Events can be entered individually or imported from a validated CSV in one atomic database transaction.
- Duplicate records and stale source metadata are flagged; estimated dates are never presented as confirmed.
- The calendar is manually curated and persisted per authenticated owner in SQLite/PostgreSQL; it is not a comprehensive automated BEI/issuer event feed.

## 17. Versioned Investment Thesis Workflow

- Analysts, portfolio managers and administrators can create owner-scoped thesis records for IDX and US securities.
- Each thesis captures bull/base/bear cases, catalysts, risks, invalidation criteria, target price, currency, status and review date.
- Every edit creates a new version with actor and timestamp; prior versions remain reviewable. Owners can assign a specific portfolio manager/admin from the configured OIDC role map to review a specific thesis version; only the assigned reviewer can read and decide that review. Decisions are APPROVED, REJECTED or CHANGES_REQUESTED and are audited.
- SQLite is used for explicit local paths and PostgreSQL for configured cloud deployments. PostgreSQL schema and least-privilege grants include thesis and version tables.
- Thesis data is isolated by immutable authenticated owner principal. Cloud database connectivity and two-user isolation still require staging validation.

## Data and safety notes

- Price/fundamental data is retrieved from Yahoo Finance via yfinance and may be delayed, incomplete, revised or rate-limited.
- Daily closing bars are not live quotes.
- IDX and US financial data can use different reporting currencies and fiscal periods. Verify company filings for material decisions.
- The score, signal, valuation and portfolio scenario outputs are research tools, not personalized investment advice.
- No broker connection or automated order execution is included.
- Local Telegram/Ollama scheduling continues to use SQLite unless a database URL is deliberately configured in that local environment.


## 6. Market Regime, Relative Strength and Data Quality

- IDX market regime uses the Jakarta Composite Index (^JKSE); US market regime uses SPY as a broad-market proxy.
- Regime labels are rule-based from the latest available close, EMA50, EMA200 and 20-session price return: bullish, bearish, recovery/transition, weak/transition, or sideways/mixed.
- Relative strength compares the selected stock and benchmark over matched dates for 1-month, 3-month, 6-month and 1-year windows when enough observations exist.
- OHLCV checks flag missing/non-numeric bars, invalid OHLC relationships, non-positive prices, negative volume, duplicate dates, stale latest bars and short history.
- Fundamental checks surface missing values, non-finite/invalid market capitalization, negative valuation multiples requiring context, unknown currency, and a difference between quote currency and financial reporting currency.
- These are diagnostic flags, not independent verification of issuer filings or exchange data.

## 7. Saved Portfolio Books

- Named portfolio books and their positions can be saved, loaded and deleted through the storage layer.
- When `DATABASE_URL` is configured, cloud portfolio books use PostgreSQL and are scoped by the authenticated OIDC issuer-bound subject. Without it, local SQLite is used; hosted local SQLite may be ephemeral.
- Portfolio operations require the `portfolio_manager` or `admin` role. Existing local records without a verified owner are quarantined as `legacy-unassigned`; they are not automatically uploaded or assigned to a user.
- Repeated rows for the same market/ticker are consolidated. Average cost is share-weighted, not a simple arithmetic average.
- Portfolio book persistence stores market, ticker, shares and average cost; market prices, sector classifications and risk analytics are refreshed when the user recalculates the portfolio.
- Owner-scoped read, write and delete operations are implemented, but live PostgreSQL connectivity, multi-user tenant isolation and backup/restore still require release validation.

## 8. Multi-Asset Portfolio Backtest

- Fixed long-only trend rule using price/EMA20/EMA50/EMA200 alignment and RSI bounds.
- Signals are shifted by one complete session: information from close t can only earn the return beginning at t+1.
- Active names are selected deterministically up to the configured maximum number of positions, with an equal-weight target capped per position.
- Turnover-based transaction costs include user-supplied fee and slippage assumptions.
- Reports total return, CAGR, maximum drawdown, annualized volatility, Sharpe ratio, average exposure, estimated cost and benchmark price return over overlapping dates.
- No implicit forward-fill is applied to missing close values. Uninvested cash earns zero.

Limitations: this is a simplified daily close simulation. It excludes dividends, taxes, borrow costs, market impact, intraday execution, corporate-action reconciliation and survivorship correction. The benchmark is price-only.

## 9. Research Pack Exports

- Excel output can include portfolio positions, signal history, scalar summary metrics, daily scan results, advanced screener output, portfolio exposure/risk/optimization/stress scenarios, realized P&L and open tax lots, broker statement reconciliation exceptions, transaction-aware mixed-currency equity curve and replay metrics, owner-scoped investment thesis summaries, thesis version history and reviewer decisions, market intelligence diagnostics, single-ticker and multi-asset equity curves, trade details, walk-forward folds and saved research-run metadata when those results are available in the current session/account.
- PDF output contains a timestamped summary and method/limitation notes.
- Export controls require the `analyst`, `portfolio_manager` or `admin` role; successful Excel/PDF downloads generate audit events.
- Excel/CSV exports neutralize formula-like untrusted text; PDF text fields are escaped before rendering.
- Exports are analytical summaries, not official broker statements, tax reports or investment recommendations.

## 10. Multi-User Security, Audit and Operations

- Streamlit-native OIDC login resolves the immutable issuer-bound principal (`iss|sub`) and maps it to a server-managed role. Missing or invalid identity/role fails closed.
- Roles: `viewer`, `analyst`, `portfolio_manager`, `admin`. Analysts/portfolio managers/admins can manage their own thesis workflow; only portfolio managers/admins can decide explicitly assigned thesis reviews. Page and selected operation-level checks restrict portfolio management, research execution, report exports and administrator audit access.
- Portfolio books, learning/performance records and saved research/backtest runs are owner-scoped when PostgreSQL is configured. Audit history is system-wide and administrator-only.
- The Security & Audit console provides role-map visibility, audit filtering/CSV export and on-demand hash-chain verification. Hash chaining is tamper-evident, not immutable/WORM.
- `database_backup.py` supports integrity-checked SQLite backups and PostgreSQL custom-format logical dumps with SHA-256 manifests. Restore must be rehearsed on staging.
- These controls are implementation foundations, not production certification. See `SECURITY_RELEASE_GATES.md` and `OIDC_SETUP.md` for outstanding configuration and validation requirements.
