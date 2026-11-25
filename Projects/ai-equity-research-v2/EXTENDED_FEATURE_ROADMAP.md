# AI Equity Research V2 — Extended Feature Roadmap

This roadmap extends the current feature-complete baseline on `feature/advanced-equity-intelligence`. It is a development backlog, not a deployment checklist. No item authorizes a merge to `main`, Preview deployment, or production release.

## Existing baseline (do not rebuild)

The current workspace already includes DCF and Multi-Stage DCF, scenario analysis, IDX/US screening and explainable scoring, market regime and relative strength, portfolio risk/optimization, single-ticker/walk-forward/multi-asset backtests, forward-outcome learning, research exports, OIDC roles, owner-scoped storage, audit, and backup utilities.

## Implementation status (2026-11-25)

- E7: canonical market-data provenance/freshness contract is integrated into daily history, screener and Market Intelligence. Yahoo provider adapter, bounded retries, explicit rate-limit handling, TTL cache and cache-age metadata are implemented. An additional licensed provider adapter and end-to-end alternate-provider parity remain.
- E1: event ledger, dividend/cost classification, TWR and XIRR engines, Streamlit page, owner-scoped SQLite/PostgreSQL transaction-event storage and persisted valuation snapshots are implemented. Cash sequencing, positive trade quantity/price, split-ratio validation and opening-position reconciliation are enforced. FIFO and weighted-average tax lots, realized P&L, opening-lot entry and split-adjusted cost basis are implemented with a dedicated UI. A one-to-one CSV broker statement matcher now flags matched, missing, unexpected and date/amount/quantity/price-mismatched events; results are visible in the UI and Research Pack. Trade-date positions and settlement-date cash payables/receivables are now supported when the CSV supplies an explicit settlement_date; cash is reserved for pending buys and pending sells are not treated as settled cash. Inferred exchange settlement calendars and direct broker integration remain.
- E2: FX-aware IDR/USD daily return conversion, FX attribution, strict stale-FX tolerance and cross-market UI are implemented. A transaction-aware replay engine and CSV UI now replay dated BUY/SELL/dividend/fee/tax/deposit/withdrawal/split events, mark holdings to historical closes, convert currencies with explicit FX/staleness limits, and calculate daily TWR excluding external flows. Broker settlement-calendar inference, intraday fills and multi-currency cash sub-ledgers remain.
- E3: industry/currency-filtered peer metrics, coverage, medians, IQR outlier flags and company-vs-peer comparison are implemented with Yahoo Finance UI. Metric period basis is now explicit (TTM, point-in-time, provider-defined YoY/trailing), and fiscal year-end differences greater than 90 days from the peer median are flagged in results/UI; no unsupported period normalization is fabricated. Independent filing verification remains.
- E4: bounded reverse DCF solver, explicit quote/model currency FX bridge, enterprise-to-equity bridge, WACC/terminal-growth sensitivity and UI are implemented. Independent reconciliation against the existing multi-stage DCF and scenario sensitivity integration remain.
- E5: source-attributed event calendar, individual entry and atomic validated CSV import, stale/duplicate/estimated flags and owner-scoped SQLite/PostgreSQL persistence are implemented. Automated exchange/issuer feed and adjusted-price corporate-action reconciliation remain.
- E6: seeded multivariate Monte Carlo, PSD covariance safeguard, VaR/CVaR, drawdown, user-defined price shocks and explicit FX/rate/sector factor stress are implemented. A two-state Markov regime-switching Monte Carlo is now available with rolling-volatility historical labels, user-supplied transition probabilities, per-regime return/covariance estimates, and reproducible simulation. Parameter uncertainty and calibrated regime validation remain.
- E8: owner-scoped versioned thesis records, role permission, PostgreSQL schema/health grants, UI, saved-run links and assigned reviewer approval workflow are implemented. Research Pack now exports the authenticated owner's thesis summaries, version history and reviewer decisions, with thesis/review metrics. Richer governance analytics and release-stage multi-user validation remain.

These are implementation milestones, not completion claims for the full acceptance criteria below. All remaining items are still part of feature development before deployment.

## Extended development backlog

### E1 — Portfolio cash-flow and dividend ledger
- Record deposits, withdrawals, buy/sell fills, fees, taxes, cash balances, dividends and corporate-action adjustments as dated events.
- Calculate time-weighted return (TWR) and money-weighted return (XIRR) separately; never mix them with price-only return.
- Reconcile event totals to holdings and cash; show missing or unreconciled events as warnings.
- Calculate FIFO and weighted-average cost basis, realized P&L on partial/full sells, and preserve basis through stock splits; accept opening lots for pre-ledger holdings.
- Reconcile internal events against a normalized broker statement CSV with explicit tolerance settings and export exception reports; never silently alter the ledger.
- Keep manual input supported; do not imply broker synchronization.
- Support explicitly supplied settlement dates for BUY/SELL, reserve cash for unsettled buys, hold sale proceeds as receivables until settlement, and show unsettled balances.

Acceptance: deterministic tests for deposits, withdrawals, dividends, partial sells, fees, split adjustments, FIFO/average-cost tax lots, realized P&L, opening lots, TWR, XIRR and invalid event sequences. Automatic settlement-calendar inference and direct broker API integration remain out of scope; explicit settlement dates and manual CSV broker statement reconciliation are implemented.

### E2 — Cross-market portfolio and FX-aware backtest
- Support a combined IDX and US universe with an explicit base currency (IDR or USD).
- Replay explicit transaction events against historical close series, with dated fill prices/amounts, holdings/cash reconstruction, external-flow-adjusted TWR and CSV import.
- Convert daily US asset returns using a supplied or downloaded USD/IDR series aligned by available dates; expose FX contribution separately from local asset return.
- Reject missing FX coverage rather than silently forward-filling long gaps.
- Keep market calendars and non-overlapping sessions explicit; no cross-market same-day look-ahead.

Acceptance: synthetic tests for asset-only return, FX-only return, combined return, missing FX, calendar alignment, currency translation, event replay, deposits/withdrawals, partial sales, insufficient cash, stale marks and no-lookahead. Settlement-cycle and broker integration remain out of scope.

### E3 — Relative valuation and peer comparison
- Compare companies only within a selected peer group/industry and display source, currency, fiscal period and field coverage.
- Include EV/EBITDA, P/E, P/B, EV/Sales, margins, ROIC/ROE and growth where source data exists.
- Show median/dispersion and outlier flags; do not manufacture missing peer metrics.
- Clearly distinguish trailing, point-in-time, provider-defined YoY and reported-period metrics; flag fiscal year-end comparability gaps rather than silently treating periods as equivalent.

Acceptance: tests for mixed currencies, missing denominators, negative earnings/equity, outliers, small peer groups, metric-period labels and fiscal year-end mismatch warnings. Independent filing verification remains a release limitation.

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
- Add an optional two-regime Markov simulation with explicit historical regime labels, per-regime return/covariance estimates and user-controlled transition probabilities; expose the regime classifier and limitations.
- Keep simulation outputs separate from forecasts and historical backtest results.

Acceptance: deterministic seed tests, covariance validation, positive-semidefinite safeguards, tail-loss metrics, zero-volatility edge cases, transition-matrix validation, regime sample minimums and UI disclosure. Parameter uncertainty and out-of-sample regime calibration remain open.

### E7 — Data provenance, freshness and provider abstraction
- Standardize source, retrieval timestamp, bar date, currency, adjustment mode, missing fields and cache age in a shared market-data contract.
- Add provider interfaces so alternate licensed sources can be integrated without rewriting valuation/screener logic.
- Add cache and rate-limit handling with bounded retries; never bypass provider terms or scrape restricted endpoints.

Acceptance: provider contract tests, stale-cache tests, malformed payload tests and rate-limit/backoff tests.

### E8 — Research workflow and governance
- Add thesis records with bull/base/bear assumptions, catalysts, risks, invalidation levels, owner, status and review date.
- Link thesis versions to saved research runs and reports; include owner-scoped thesis, version and review history in Research Pack exports.
- Add reviewer approval history and immutable version identifiers; audit hash chaining remains tamper-evident, not WORM.

Acceptance: owner-isolation, version-history, role-permission and audit-event tests, plus owner-scoped thesis/version/review export. Richer governance analytics and release-stage multi-user validation remain.

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
