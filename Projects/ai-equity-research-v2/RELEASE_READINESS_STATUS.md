# AI Equity Research V2 — Release Readiness

Last updated: 2026-11-25

## Current engineering state

- Development branch: `feature/advanced-equity-intelligence`
- Pull request: [#4](https://github.com/agusbudiantoerp-web/ulilabsyor89/pull/4) — Draft, not merged.
- Latest development commit: `73bcf1de5524177eb35f5c0c01ecbeca132c6e40`.
- Production branch `main` remains unchanged.
- Latest PR CI run: **332 passed, 0 failed, 0 skipped**; Python compilation passed and PostgreSQL 16 service initialized successfully. Run: [GitHub Actions #857](https://github.com/agusbudiantoerp-web/ulilabsyor89/actions/runs/45552889590).
- CI now provisions an isolated PostgreSQL 16 service for the complete automated and PostgreSQL integration test suite; database credentials are ephemeral test-only values, not production secrets.
- No production deployment, secret rotation, production database mutation or live broker connection was performed.

## Implemented in the development branch

- IDX/US research, DCF, Multi-Stage DCF, Reverse DCF and cross-model EV/equity/price bridge checks.
- Peer valuation with metric-period labels, fiscal year-end comparability warnings and a source-attributed issuer-filing CSV verification workflow with strict currency/URL/ticker/numeric validation and separate invalid-value reporting. Filing validation checks three-letter currency codes, structurally valid HTTP(S) source URLs, duplicate provider/issuer tickers, finite numeric fields, distinguishes invalid provider values from genuinely missing data, and exposes invalid-value counts separately in the valuation UI. Multi-Stage DCF now returns explicit unavailable results for non-finite forecast/terminal calculations rather than leaking numerical overflow.
- Portfolio cash-flow ledger, TWR/XIRR, FIFO/weighted-average tax lots, realized P&L, opening lots and split basis adjustments.
- Manual broker-statement CSV reconciliation with matched/missing/unexpected and amount/quantity/price/date exceptions.
- Transaction-aware historical portfolio replay with explicit trade fills, optional settlement dates, reserved unsettled buy payables, unsettled sell receivables, stale-price/FX checks and external-flow-adjusted TWR.
- Cross-market daily return analysis, IID Monte Carlo, two-state Markov regime simulation with optional smoothed empirical transitions, moving-block bootstrap, and a two-window structural-break diagnostic warning.
- Owner-scoped thesis/version/reviewer export and review-aging dashboard.
- Research Pack exports for applicable portfolio, reconciliation, filing, thesis and simulation outputs.

## Remaining engineering and external dependencies

| Area | Remaining work | Dependency / release constraint |
|---|---|---|
| Portfolio ledger | Direct broker API integration, statutory tax treatment, inferred settlement calendars and multi-currency cash sub-ledgers | Broker API access, tax/accounting rules and explicit FX-conversion design |
| Cross-market | Full local-currency cash balances and explicit FX conversion ledger | Product/accounting decision and additional integration tests |
| Peer verification | Automated official filing retrieval/OCR, unit and consolidation-scope normalization | Official issuer/BEI source formats and validation rules |
| Valuation | Integrate scenario sensitivity and model-to-model assumption scenario sweeps | Additional UI/model acceptance criteria |
| Corporate actions | Automated official BEI/issuer event feeds and adjusted-price reconciliation | Confirmed official feed endpoints, schemas and permitted access |
| Market data | Secondary licensed provider adapter and provider-parity validation | Provider selection, subscription and secrets configured outside chat |
| Risk simulation | Formal breakpoint tests and out-of-sample regime calibration | Defined validation sample and methodology |
| Governance | Additional role-specific governance dashboards | Final role/workflow requirements |

## Mandatory release gates — not yet signed off

1. Configure Preview Google OIDC without sharing client secrets in chat.
2. Configure a disposable staging PostgreSQL database, separate from production.
3. Run two-user owner-isolation and role-permission tests.
4. Verify audit-chain behavior, admin controls and denied-operation logging.
5. Exercise backup and restore against staging data.
6. Complete security and data-retention review.
7. Review the final release candidate and obtain explicit approval before merging PR #4 or deploying.

## Release decision

**Not production-ready yet.** The latest CI is green, including PostgreSQL-backed tests, but passing automated tests does not prove the multi-user deployment, security controls, external data integrations or operational recovery. Complete the staging and acceptance gates above before merging or deploying.
