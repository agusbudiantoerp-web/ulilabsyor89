# Security, Audit and Multi-User Release Gates

## Implemented foundations

- Telegram chat access remains fail-closed: an empty allowlist authorizes nobody.
- `security_controls.py` provides role names and permission checks for viewer, analyst, portfolio_manager and admin.
- Streamlit-native OIDC login is integrated in the application entry point. The app requires exactly one configured provider, uses the verified issuer-bound immutable `iss|sub` principal, and fails closed when login or role mapping is missing.
- Server-side page-level permission checks restrict research, signal, portfolio/risk, backtest and performance pages by role. This is not yet a substitute for checks on every sensitive operation inside those pages.
- Login/logout audit events are recorded when the local audit store is available. Login audit failure blocks dashboard access; logout remains available even if the audit store fails.
- `security_controls.py` provides a SQLite hash-linked audit event log, serialized append operations, and a chain-verification routine.
- Audit payloads reject credential-like keys recursively, including common nested and naming variants.
- Portfolio books are scoped by the authenticated issuer-bound OIDC principal in SQLite. Existing pre-migration books are assigned `legacy-unassigned` and are hidden from authenticated users until an administrator explicitly migrates ownership.
- The portfolio database remains local SQLite and is not encrypted or suitable for shared multi-instance deployment.
- Performance/learning history can use PostgreSQL, but this database is not a substitute for tenant authorization.

## Important release status

**OIDC login and page-level role gates are implemented, but the application is not yet certified or configured for production multi-user deployment.** The identity provider and role mapping still need to be configured in Streamlit Secrets, and tenant isolation and operation-level authorization remain incomplete.

Portfolio-book queries are scoped by issuer-bound owner ID, but shared learning/performance history and other private database records are not yet fully tenant-scoped. Page-level gates and selected action-level checks are present; every privileged operation still needs a complete authorization and audit review. Role labels must never be inferred from a username, email address, query parameter, browser state, or user-editable form.

## Required before enabling multiple users

1. Configure exactly one trusted OIDC provider in Streamlit Secrets and register the exact callback URL; see `OIDC_SETUP.md`.
2. Map issuer-bound immutable provider subject IDs to server-managed roles; deny access if identity or role is missing.
3. Enforce authorization server-side on every portfolio read/write/delete, report export, model configuration change, user administration action, and audit-log access; current page-level checks are not sufficient.
4. Extend tenant/user ownership keys to all private data tables and migrate legacy portfolio books with an explicit owner. Current portfolio-book owner scoping is only a first step.
5. Use managed PostgreSQL with least-privilege credentials, TLS, connection limits, backups, and tested point-in-time recovery.
6. Export audit events to access-controlled append-only or WORM storage. The local hash chain is tamper-evident, not immutable against an administrator who can rewrite the database.
7. Redact secrets and personal data from logs; rotate credentials and document incident response.
8. Perform dependency, vulnerability, access-control, backup-restore, and penetration testing before release.

## Operational controls

- Keep API keys and database credentials in Streamlit secrets or environment variables, never in source files or audit payloads.
- Do not expose local SQLite files or database connection strings through downloads.
- Do not merge the development branch or deploy it to the public Streamlit app until the complete test suite and release gates pass.
- The system is research support only; it does not place broker orders or replace human review.
