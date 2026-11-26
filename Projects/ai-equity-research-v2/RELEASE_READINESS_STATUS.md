# AI Equity Research V2 — Release Readiness

Last updated: 2026-11-26

## Current engineering state

- Development branch: `feature/advanced-equity-intelligence`
- Pull request: [#4](https://github.com/agusbudiantoerp-web/ulilabsyor89/pull/4) — Draft, not merged.
- Latest branch head: `2a38a201a3d73b2c0c2cf8fd04a250aea5dfdda3`.
- Earlier automated baseline: **720 passed, 0 failed, 0 skipped** on commit `05454ef5bbecd78a6d69c824f763cf60b7bbc7a2` (historical run; superseded).
- Previous full baseline: **751 passed, 0 failed** on `87b9e2424255360c7929c89d85ba5feef8cb85e5`.
- Latest code head `2a38a201a3d73b2c0c2cf8fd04a250aea5dfdda3`: **757 passed, 0 failed; fresh SQLite and PostgreSQL schemas enforce non-null outcome ownership**; Python 3.10 module compilation and the complete suite against an ephemeral PostgreSQL 16 service passed: [GitHub Actions run](https://github.com/agusbudiantoerp-web/ulilabsyor89/actions/runs/45773101971).
- Production branch `main` remains unchanged.
- CI provisions an isolated PostgreSQL 16 service for automated and PostgreSQL integration tests. Database credentials are ephemeral test-only values, not production secrets.
- GitHub Actions now uses `actions/checkout@v7.0.1` and `actions/setup-python@v7.1.0`; the prior Node.js 20 deprecation warning no longer appears in the completed run. Concurrency cancels superseded runs on the same branch/ref.
- Backup manifests can be independently verified against artifact size and SHA-256, with POSIX/Windows path-traversal checks. SQLite restore now verifies the manifest and database integrity before and after copying, publishes atomically, and refuses to overwrite an existing target unless `--overwrite` is explicitly supplied. PostgreSQL restore is not automated; its custom-format dump is structurally checked with `pg_restore --list`.
- Excel/CSV exports neutralize formula-like text after whitespace and Unicode BOM prefixes; scenario worksheet names are sanitized and de-duplicated.
- No production deployment, secret rotation, production database mutation or live broker connection was performed.

## Implemented in the development branch

- IDX/US research, DCF, Multi-Stage DCF, Reverse DCF, cross-model EV/equity/price bridge checks, and operating sensitivity across revenue-growth × EBITDA-margin assumptions with Excel/PDF Research Pack export.
- Peer valuation with metric-period labels, fiscal year-end comparability warnings and a source-attributed issuer-filing CSV verification workflow with strict currency/URL/ticker/numeric validation and separate invalid-value reporting. Filing validation checks three-letter currency codes, structurally valid HTTP(S) source URLs, duplicate provider/issuer tickers, finite numeric fields, distinguishes invalid provider values from genuinely missing data, and exposes invalid-value counts separately in the valuation UI. Multi-Stage DCF returns explicit unavailable results for non-finite forecast/terminal calculations rather than leaking numerical overflow.
- Portfolio cash-flow ledger, TWR/XIRR, FIFO/weighted-average tax lots, realized P&L, opening lots and split basis adjustments.
- Manual broker-statement CSV reconciliation with matched/missing/unexpected and amount/quantity/price/date exceptions.
- Transaction-aware historical portfolio replay with explicit trade fills, optional settlement dates, reserved unsettled buy payables, unsettled sell receivables, stale-price/FX checks and external-flow-adjusted TWR.
- Cross-market daily return analysis with FX-only return marking on local-market holidays, explicit stale-price/FX limits, IID Monte Carlo, two-state Markov regime simulation with optional smoothed empirical transitions, moving-block bootstrap, and a two-window structural-break diagnostic warning. The structural-break diagnostic is heuristic, not a formal breakpoint test or out-of-sample calibration.
- Owner-scoped thesis/version/reviewer export and review-aging dashboard.
- Research Pack exports for applicable portfolio, reconciliation, filing, thesis and simulation outputs.
- OIDC identity resolution using immutable issuer-bound `iss|sub`, server-managed fail-closed roles, owner-scoped stores, admin-only security/audit controls, database diagnostics and backup/restore tooling.

## Remaining engineering and external dependencies

| Area | Remaining work | Dependency / release constraint |
|---|---|---|
| Portfolio ledger | Direct broker API integration, statutory tax treatment, inferred settlement calendars and multi-currency cash sub-ledgers | Broker API access, tax/accounting rules and explicit FX-conversion design |
| Cross-market | Full local-currency cash balances and explicit FX conversion ledger | Product/accounting decision and additional integration tests |
| Peer verification | Automated official filing retrieval/OCR, unit and consolidation-scope normalization | Official issuer/BEI source formats and validation rules |
| Valuation | Model-to-model assumption scenario sweeps beyond the new revenue-growth × EBITDA-margin sensitivity matrix | Additional UI/model acceptance criteria |
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


## PostgreSQL RLS policy diagnostics

The read-only database health check verifies more than `relrowsecurity` and `relforcerowsecurity`: it also inspects `pg_policies` for each registered owner-scoped table. A release-ready table must have tenant-scoped permissive policy coverage for SELECT, INSERT, UPDATE, and DELETE, with both `USING` and `WITH CHECK` expressions (where applicable) binding `owner_id` to `current_setting('app.current_owner_id', true)`. Broad permissive policies and missing CRUD coverage are reported as release blockers. This remains diagnostic only: it does not create policies, set per-transaction owner context, or change database privileges. Actual RLS rollout still requires a separately reviewed migration and integration tests using the restricted non-owner application role.


## Forward-outcome ownership hardening

The `outcomes` table now has a persisted, non-null `owner_id`, backfilled from its parent signal during PostgreSQL/SQLite initialization. Outcome writes validate ownership and persist the owner; reads and aggregates constrain joins by owner. A regression test covers cross-owner write rejection, persisted owner identity and cross-owner summary isolation. This is application-level ownership enforcement; PostgreSQL RLS remains unconfigured and is still a release gate.


## Migration/runtime credential separation

The Streamlit admin console no longer executes schema DDL using the application's runtime database URL. Schema migrations must be run out-of-band using `postgres_schema_migration.py` and a dedicated migration principal from a trusted administrator workstation. The app receives only a restricted non-owner runtime connection. This avoids creating tables owned by the runtime role and preserves least-privilege separation. The script does not install RLS policies; database-native tenant isolation remains unconfigured until the owner-context lifecycle is implemented and verified in staging.
