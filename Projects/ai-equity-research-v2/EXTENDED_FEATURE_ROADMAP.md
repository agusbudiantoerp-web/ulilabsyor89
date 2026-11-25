# AI Equity Research V2 — Extended Feature Roadmap

This roadmap extends the current feature-complete baseline on `feature/advanced-equity-intelligence`. It is a development backlog, not a deployment checklist. No item authorizes a merge to `main`, Preview deployment, or production release.

## Existing baseline (do not rebuild)

The current workspace already includes DCF and Multi-Stage DCF, scenario analysis, IDX/US screening and explainable scoring, market regime and relative strength, portfolio risk/optimization, single-ticker/walk-forward/multi-asset backtests, forward-outcome learning, research exports, OIDC roles, owner-scoped storage, audit, and backup utilities.

## Extended development backlog

### E1 — Portfolio cash-flow and dividend ledger
- Record deposits, withdrawals, buy/sell fills, fees, taxes, cash balances, dividends and corporate-action adjustments as dated events.
- Calculate time-weighted return (TWR) and money-weighted return (XIRR) separately; never mix them with price-only return.
- Reconcile event totals to holdings and cash; show missing or unreconciled events as warnings.
- Keep manual input supported; do not imply broker synchronization.

Acceptance: deterministic tests for deposits, withdrawals, dividends, partial sells, fees, split adjustments, TWR, XIRR and invalid event sequences.

### E2 — Cross-market portfolio and FX-aware backtest
- Support a combined IDX and US universe with an explicit base currency (IDR or USD).
- Convert daily US asset returns using a supplied or downloaded USD/IDR series aligned by available dates; expose FX contribution separately from local asset return.
- Reject missing FX coverage rather than silently forward-filling long gaps.
- Keep market calendars and non-overlapping sessions explicit; no cross-market same-day look-ahead.

Acceptance: synthetic tests for asset-only return, FX-only return, combined return, missing FX, calendar alignment and currency translation.

### E3 — Relative valuation and peer comparison
- Compare companies only within a selected peer group/industry and display source, currency, fiscal period and field coverage.
- Include EV/EBITDA, P/E, P/B, EV/Sales, margins, ROIC/ROE and growth where source data exists.
- Show median/dispersion and outlier flags; do not manufacture missing peer metrics.
- Clearly distinguish trailing, forward and reported-period metrics.

Acceptance: tests for mixed currencies, missing denominators, negative earnings/equity, outliers and small peer groups.

### E4 — Reverse DCF and valuation bridge
- Add reverse DCF to solve for the growth assumptions implied by the current market price.
- Show explicit forecast, terminal value, net debt/cash, diluted shares, FX and enterprise-to-equity bridge.
- Surface non-convergence, invalid WACC/terminal-growth combinations and sensitivity ranges.

Acceptance: numerical tests with known synthetic cash flows, boundary tests and reconciliation against the existing DCF engine.

### E5 — Event and corporate-action awareness
- Provide an earnings/dividend/split calendar when reliable event data is available.
- Flag stale event data and distinguish confirmed issuer/exchange dates from provider estimates.
- Add explicit split/dividend adjustment provenance to historical price metadata and reports.
- Never represent an incomplete event feed as comprehensive.

Acceptance: timezone, duplicate event, stale event, split-ratio and adjusted-price consistency tests.

### E6 — Portfolio stress testing and Monte Carlo
- Add historical and user-defined shock scenarios across price, FX, rates and sector exposures where inputs exist.
- Add reproducible Monte Carlo paths with a fixed seed option, clearly stated return/volatility assumptions and confidence intervals.
- Keep simulation outputs separate from forecasts and historical backtest results.

Acceptance: deterministic seed tests, covariance validation, positive-semidefinite safeguards, tail-loss metrics and zero-volatility edge cases.

### E7 — Data provenance, freshness and provider abstraction
- Standardize source, retrieval timestamp, bar date, currency, adjustment mode, missing fields and cache age in a shared market-data contract.
- Add provider interfaces so alternate licensed sources can be integrated without rewriting valuation/screener logic.
- Add cache and rate-limit handling with bounded retries; never bypass provider terms or scrape restricted endpoints.

Acceptance: provider contract tests, stale-cache tests, malformed payload tests and rate-limit/backoff tests.

### E8 — Research workflow and governance
- Add thesis records with bull/base/bear assumptions, catalysts, risks, invalidation levels, owner, status and review date.
- Link thesis versions to saved research runs and reports.
- Add reviewer approval history and immutable version identifiers; audit hash chaining remains tamper-evident, not WORM.

Acceptance: owner-isolation, version-history, role-permission and audit-event tests.

## Development order

1. E7 data provenance contract (foundation for all other additions).
2. E1 portfolio cash-flow/dividend ledger.
3. E2 cross-market FX-aware backtest.
4. E3 peer-relative valuation.
5. E4 reverse DCF.
6. E5 event/corporate-action awareness.
7. E6 stress and Monte Carlo.
8. E8 research thesis workflow.

Each feature must include implementation, UI integration, documentation, deterministic unit tests and CI. Do not start Preview or production deployment until the user explicitly requests it after feature development is complete.

## Non-goals

- No broker order placement or automated trade execution.
- No claim of guaranteed returns or predictive certainty.
- No use of production secrets or production databases in development tests.
- No silent FX conversion, price forward-fill across material gaps, fabricated fundamentals, or invented event dates.
