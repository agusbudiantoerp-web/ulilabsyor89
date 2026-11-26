# AI Equity Research V2 — Release Readiness

Last updated: 2026-11-26

## Current engineering state

- Development branch: `feature/advanced-equity-intelligence`
- Pull request: [#4](https://github.com/agusbudiantoerp-web/ulilabsyor89/pull/4) — Draft, not merged.
- Latest branch head at the time of this update: `a154413ba4194b71d4853cddf9dbb5f82e54b944` (Preview operator runbook and release documentation; documentation-only).
- Latest branch-head CI verification: **success** on commit `a154413ba4194b71d4853cddf9dbb5f82e54b944`; Python 3.10 module compilation and the complete automated/PostgreSQL integration job both completed successfully: [GitHub Actions run](https://github.com/agusbudiantoerp-web/ulilabsyor89/actions/runs/45827459261).
- Latest code-bearing full-suite baseline: **772 passed, 0 failed** on commit `e67a54530ea8ff0813afc3152408f4a23215223f`, including PostgreSQL 16 integration: [GitHub Actions run](https://github.com/agusbudiantoerp-web/ulilabsyor89/actions/runs/45823801298). Subsequent changes through `a154413` are documentation-only.
- The PostgreSQL integration suite also verifies that the runtime role is not granted access to unrelated administrator-owned sequences in the application schema.
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

1. Configure Preview Google OIDC and register the exact callback URL; keep client secrets outside chat and source control.
2. Provision a disposable Preview PostgreSQL database, separate from production, with TLS and a dedicated administrator/migration identity.
3. Run `postgres_schema_migration.py` from a trusted administrator workstation with explicit confirmation.
4. Create a dedicated non-owner, non-superuser, non-BYPASSRLS runtime role; run `postgres_rls_migration.py` with explicit confirmation and verify the read-only Security & Audit diagnostics report no RLS, policy, ownership or privilege issues.
5. Configure Preview Streamlit with only the restricted runtime database connection and the server-side OIDC role map.
6. Test two distinct Google identities across all owner-scoped stores, reviewer assignment/decisions, role-gated pages and direct operation paths; verify unknown identities are denied.
7. Verify audit-chain behavior, admin-only audit UI, denied-operation logging and audit export controls.
8. Exercise PostgreSQL backup and restore against staging data, including integrity verification.
9. Complete dependency/vulnerability, security and data-retention review, plus an independent security review.
10. Review the final release candidate and obtain explicit approval before merging PR #4 or deploying.

## Release decision

**Not production-ready yet.** The latest CI is green, including PostgreSQL-backed tests, but passing automated tests does not prove the multi-user deployment, security controls, external data integrations or operational recovery. Complete the staging and acceptance gates above before merging or deploying.


## PostgreSQL RLS policy diagnostics

The read-only database health check verifies RLS enablement and FORCE RLS, tenant/reviewer policy coverage, runtime-role attributes and ownership, and required CRUD grants. The separate `postgres_rls_migration.py` migration installs these policies and restricted grants. CI validates the migration against PostgreSQL 16 with a restricted non-owner runtime role, including no-context reads/writes and transaction-local context reset. These checks validate the migration mechanics in an ephemeral test database; the actual Preview database still requires explicit administrator rollout and read-only diagnostics before release.


## Forward-outcome ownership hardening

The `outcomes` table now has a persisted, non-null `owner_id`, backfilled from its parent signal during PostgreSQL/SQLite initialization. Outcome writes validate ownership and persist the owner; reads and aggregates constrain joins by owner. A regression test covers cross-owner write rejection, persisted owner identity and cross-owner summary isolation. This is reinforced by the separate PostgreSQL RLS migration, which forces row-level policies on the registered owner-scoped tables. Live Preview execution and two-identity acceptance remain release gates.


## Migration/runtime credential separation

The Streamlit runtime does not execute PostgreSQL DDL. Run `postgres_schema_migration.py` out-of-band using a dedicated administrator connection and explicit confirmation. Then run `postgres_rls_migration.py` using the administrator connection, a dedicated restricted runtime role name, and explicit confirmation. The application receives only the restricted non-owner runtime connection. Both migration steps are covered by PostgreSQL 16 CI integration tests, but still must be executed and verified in the actual Preview environment.



## Preview operator runbook

A step-by-step Preview-only operator guide is available in `PREVIEW_OPERATOR_RUNBOOK.md`. It covers Google callback setup, disposable PostgreSQL provisioning, separation of migration/runtime identities, schema and RLS migration commands, read-only diagnostics, two-identity acceptance and explicit stop/go criteria. It does not authorize production changes.
