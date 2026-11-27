# Security, Audit and Multi User Release Gates

## Implemented application controls

  Streamlit-native OIDC login is integrated in the application entry point. The app requires exactly one complete configured provider, rejects partially populated or mixed default/named provider blocks, derives the principal from the verified issuer-bound immutable `iss|sub`, and denies access when login or role mapping is missing.
- Server-managed roles are `viewer`, `analyst`, `portfolio_manager` and `admin`. `portfolio_manager` and `admin` can review assigned investment thesis versions; `analyst`, `portfolio_manager` and `admin` can author their own theses. Role mapping is maintained in private Streamlit Secrets; the browser console is read-only.
- Server-side page gates protect research, daily signals, portfolio/risk, backtesting, performance and the admin-only Security & Audit console. Selected portfolio-management, report-export and other sensitive operations also enforce permissions at their execution points.
- Session state is cleared when the authenticated principal changes in a reused Streamlit session.
- Portfolio books, cash-flow event ledgers and dated portfolio valuations, corporate event records, versioned investment theses/review requests, daily scans/signals/forward outcomes and saved single-ticker, walk-forward and multi-asset research runs are owner-scoped using the immutable OIDC principal. Thesis review decisions are restricted to the explicitly assigned reviewer and the specific saved thesis version. Existing legacy records are quarantined as `legacy-unassigned`; they are not silently assigned to the first user or uploaded from local SQLite.
- PostgreSQL RLS rollout is implemented in `postgres_rls_migration.py`: it enables and forces RLS on 12 owner-scoped tables, installs tenant and assigned-reviewer policies, and grants a restricted non-owner runtime role only the table privileges and backing sequences needed by the application. Runtime storage connections set transaction-local owner/actor context. The migration is separate from normal Streamlit startup and must be executed explicitly by an administrator. The automated PostgreSQL 16 integration test provisions a restricted role and verifies tenant isolation, reviewer access, context reset, and denied context-free writes. Live Preview deployment and independent security review remain mandatory release gates.
- The Security & Audit console's read-only PostgreSQL diagnostics now inspect every registered owner-scoped table for RLS enablement and FORCE RLS, flag missing catalog results, reject SUPERUSER/BYPASSRLS application roles, and flag an application role that owns a tenant table. A healthy TCP connection or sufficient SQL grants alone no longer count as a passing database security check. These diagnostics do not create policies or change database grants.
- Performance/learning records use PostgreSQL when configured and local SQLite otherwise. Local SQLite history is not automatically merged into cloud PostgreSQL.
- Login/logout and application activity are audit-logged. The audit console is admin-only; audit history is intentionally system-wide rather than tenant-private.
- Audit writes are serialized in PostgreSQL and SQLite. A SHA-256 hash chain can detect accidental or partial tampering, but it is not WORM storage and cannot resist a privileged database administrator rewriting the entire chain.
- Audit payloads reject common credential-like keys recursively. Excel/CSV exports escape formula-like untrusted text; dynamic PDF text is escaped.
- The admin console exposes the server-managed role map, permission matrix, audit history/export, hash-chain verification, storage routing and read-only database/table/privilege diagnostics. It does not execute schema or RLS migrations through the runtime connection.
- SQLite backup integrity checks and PostgreSQL custom-format logical backup support are provided by `database_backup.py`, with SHA-256 manifests.

## Explicit boundaries (not represented as completed application features)

- User provisioning and role changes are performed by an administrator in Streamlit Secrets; there is no self-service registration or in-app role editor.
- Audit history is shared across the installation and visible only to administrators. External append-only/WORM retention is not included in the application.
- PostgreSQL managed-service configuration, credential rotation, point-in-time recovery, network policy and backup retention remain infrastructure/administrator responsibilities.
- Local SQLite files are not a multi-instance shared database and may be ephemeral on hosted infrastructure. Configure PostgreSQL for persistent cloud multi-user operation.
- The app does not place broker orders. Research and backtest outputs remain decision support, not execution instructions.

## Required before production release

1. Configure one trusted OIDC provider in Preview Streamlit Secrets and register the exact callback URL; see `OIDC_SETUP.md`.
2. Map each approved immutable `issuer|sub` principal to the least-privilege role. Unknown principals must remain denied.
3. Configure a dedicated Preview PostgreSQL database with TLS and least-privilege grants. Never use production credentials for Preview.
4. Review and exercise every privileged page and operation against each role, including direct invocation paths, exports, portfolio CRUD, thesis authoring/reviewer assignment, reviewer approval decisions, saved-run CRUD, and admin actions.
5. Verify two-user isolation for portfolio books, learning/performance records and research/backtest history. Confirm audit records remain admin-only.
6. Verify PostgreSQL schema, grants, connection limits, backups and recovery procedures on Preview/staging.
7. Export audit events to an access-controlled append-only/WORM system if regulatory or operational retention requires immutability.
8. Perform dependency/vulnerability review, access-control testing, backup-restore rehearsal and an independent security review before inviting production users.

## Operational controls

- Keep API keys, OAuth client secrets, cookie secrets and database credentials only in Streamlit Secrets or private environment variables, never in source files or audit payloads.
- Do not expose local SQLite files or database connection strings through downloads.
- Do not merge the development branch or deploy it to the public Streamlit app until the complete test suite and release gates pass.
- The system is research support only; it does not place broker orders or replace human review.


## PostgreSQL RLS policy diagnostics

The read-only database health check verifies RLS enablement and FORCE RLS, tenant/reviewer policy coverage, runtime-role attributes and ownership, and required CRUD grants. The separate `postgres_rls_migration.py` migration installs these policies and restricted grants; CI exercises the migration against PostgreSQL 16 using a restricted non-owner role, including context-free reads/writes and transaction-local context reset. The diagnostic is read-only and does not repair a misconfigured live database. Preview must be migrated and checked independently before release.


## Forward-outcome tenant ownership migration

The daily-learning `outcomes` table stores its own non-null `owner_id`, backfilled from its parent signal. Outcome writes verify the signal under the requesting owner and persist that owner; summary/history joins constrain matching owner IDs. Automated coverage verifies cross-owner rejection. The RLS migration additionally forces tenant policies on this table; Preview acceptance remains required.


## Separate schema migration and runtime identities

The Streamlit runtime does not execute PostgreSQL DDL. Run `postgres_schema_migration.py` from a trusted administrator workstation with a private migration connection and explicit confirmation to create/migrate application and audit tables. Then run `postgres_rls_migration.py` with the administrator connection, `AI_EQUITY_RESEARCH_RUNTIME_ROLE` naming a dedicated restricted non-owner role, and `AI_EQUITY_RESEARCH_CONFIRM_RLS_MIGRATION=YES`. Configure Streamlit with only the restricted runtime connection. Never store the migration/admin connection in Streamlit Secrets. CI validates both migrations, but live Preview rollout, two-identity OIDC acceptance, backup/restore and independent security review remain outstanding.
