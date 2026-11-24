# Security, Audit and Multi-User Release Gates

## Implemented foundations

- Telegram chat access remains fail-closed: an empty allowlist authorizes nobody.
- `security_controls.py` provides role names and permission checks for viewer, analyst, portfolio_manager and admin.
- Streamlit-native OIDC login is integrated in the application entry point. The app requires exactly one configured provider, uses the verified issuer-bound immutable `iss|sub` principal, and fails closed when login or role mapping is missing.
- Server-side page-level permission checks restrict research, signal, portfolio/risk, backtest, performance and the administrator-only Security & Audit console by role. The console displays the server-managed OIDC role map, recent audit events and an on-demand hash-chain integrity check. This is not yet a substitute for checks on every sensitive operation inside the other pages.
- Login/logout audit events use PostgreSQL when `DATABASE_URL` is configured and SQLite as a local fallback, unless an explicit local `audit_db_path` is supplied. Login audit failure blocks dashboard access; logout always terminates the OIDC session and reports audit failure.
- `security_controls.py` provides a hash-linked audit event log with serialized append operations in PostgreSQL (cross-instance lock) and SQLite (immediate transaction), plus a chain-verification routine.
- Audit payloads reject credential-like keys recursively, including common nested and naming variants.
- Portfolio books are scoped by the authenticated issuer-bound OIDC principal in PostgreSQL when `DATABASE_URL` is configured, with local SQLite fallback. Existing pre-migration local books are assigned `legacy-unassigned` and are hidden from authenticated users; they are not automatically uploaded to PostgreSQL.
- Daily scans, signals, forward outcomes and learning analytics are scoped to the authenticated issuer-bound OIDC principal in both SQLite and PostgreSQL. Existing records are migrated to `legacy-unassigned` and hidden from authenticated principals.
- Performance history can use PostgreSQL, but production use still requires managed database operations, tenant-aware backups and operational security.

## Important release status

**OIDC login and page-level role gates are implemented, but the application is not yet certified or configured for production multi-user deployment.** The identity provider and role mapping still need to be configured in Streamlit Secrets, and tenant isolation and operation-level authorization remain incomplete.

Portfolio books and learning/performance records are scoped by issuer-bound owner ID. Other private data sources, audit storage and model configuration still require separate tenant/role controls. Page-level gates and selected action-level checks are present; every privileged operation still needs a complete authorization and audit review. Role labels must never be inferred from a username, email address, query parameter, browser state, or user-editable form.

## Required before enabling multiple users

1. Configure exactly one trusted OIDC provider in Streamlit Secrets and register the exact callback URL; see `OIDC_SETUP.md`.
2. Map issuer-bound immutable provider subject IDs to server-managed roles; deny access if identity or role is missing.
3. Enforce authorization server-side on every portfolio read/write/delete, report export, model configuration change, and user administration action. The audit console is admin-only, but its page-level gate must be complemented by endpoint-level checks if new audit APIs are added.
4. Extend tenant/user ownership keys to any remaining private data tables and migrate legacy records with an explicit owner. Portfolio and learning records are owner-scoped; audit storage and other private records remain to be reviewed.
5. Use managed PostgreSQL with least-privilege credentials, TLS, connection limits, backups, and tested point-in-time recovery.
6. Export audit events to access-controlled append-only or WORM storage. The PostgreSQL/SQLite hash chain is tamper-evident, not immutable against an administrator who can rewrite the database.
7. Redact secrets and personal data from logs; rotate credentials and document incident response.
8. Perform dependency, vulnerability, access-control, backup-restore, and penetration testing before release.

## Operational controls

- Keep API keys and database credentials in Streamlit secrets or environment variables, never in source files or audit payloads.
- Do not expose local SQLite files or database connection strings through downloads.
- Do not merge the development branch or deploy it to the public Streamlit app until the complete test suite and release gates pass.
- The system is research support only; it does not place broker orders or replace human review.
