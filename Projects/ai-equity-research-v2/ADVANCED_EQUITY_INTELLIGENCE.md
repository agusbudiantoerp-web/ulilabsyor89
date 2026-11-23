# Advanced Equity Intelligence — V2 Workspace

This upgrade extends the existing unified Streamlit application. It does not replace the original Equity Research, DCF, Multi-Stage DCF, scenario, Telegram, Ollama, or local SQLite automation modules.

## 1. Advanced Stock Screener

- Two explicit markets: IDX and US.
- Editable preset universe: 40 IDX symbols and 40 US symbols. It is a curated, liquid starter universe, not a claim to cover every listed issuer.
- Users may replace the preset with their own ticker list.
- Fundamental fields from Yahoo Finance when available: trailing/forward P/E, P/B, ROE, ROA, debt/equity, revenue growth, earnings growth, market capitalization, average volume and average daily turnover.
- Technical fields from daily bars: RSI(14), MACD and signal, EMA20/50/200, relative volume, ATR percentage and 20-session breakout.
- Filters for market, sector, score and market capitalization. IDX market-cap thresholds are in IDR; US thresholds are in USD.
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

The displayed coverage percentage indicates how much of the weighted factor model has usable input data. A score is withheld when coverage is below 35%. Valuation thresholds are broad screening heuristics; compare companies within similar industries and verify reported currencies/periods before making a decision.

## 3. Advanced Backtesting

- Single-ticker historical simulation retains fee, slippage, risk budget and maximum allocation controls.
- Reports total return, CAGR, win rate, profit factor, maximum drawdown, Sharpe ratio, trade details and buy-and-hold benchmark.
- Chronological expanding-history walk-forward evaluation produces sequential out-of-sample test folds.
- The walk-forward test uses the fixed, documented signal rules. It does not optimize parameters on the test fold.
- IDX/US historical data availability, corporate actions, taxes, spreads, market impact, suspensions, liquidity and survivorship bias remain important limitations.

## 4. Portfolio Intelligence

- Position weights within each currency.
- Market, currency and sector exposure.
- Correlation matrices and historical volatility, 95% one-day VaR and drawdown calculated separately by currency.
- User-defined price-shock scenario analysis.
- Indicative allocation from the latest BUY candidates, with separate IDR and USD capital budgets. IDX allocations are rounded down to 100-share board lots; US quantities use whole shares.

IDR and USD are never summed without an explicit FX conversion. The allocation planner is not connected to a broker and does not place orders.

## 5. Performance & Learning Engine

- Stores and evaluates forward returns after 1, 3, 5, 10 and 20 completed trading sessions.
- Outcomes are recorded only when the corresponding future daily close exists.
- Dashboard groups observed outcomes by signal and ruleset version, reporting observation count, mean/median return and win rate.
- PostgreSQL migration expands the allowed horizon values while retaining existing scan/signal/outcome records.
- Scan IDs are now persisted in new scan payloads and backfilled from the database row ID when older scans are read.

This is a measurement and evaluation loop, not automatic model retraining. Strategy changes should receive a new ruleset version before comparing performance.

## Data and safety notes

- Price/fundamental data is retrieved from Yahoo Finance via yfinance and may be delayed, incomplete, revised or rate-limited.
- Daily closing bars are not live quotes.
- IDX and US financial data can use different reporting currencies and fiscal periods. Verify company filings for material decisions.
- The score, signal, valuation and portfolio scenario outputs are research tools, not personalized investment advice.
- No broker connection or automated order execution is included.
- Local Telegram/Ollama scheduling continues to use SQLite unless a database URL is deliberately configured in that local environment.
