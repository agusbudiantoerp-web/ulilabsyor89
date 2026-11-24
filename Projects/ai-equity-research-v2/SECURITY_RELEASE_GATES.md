# Security, Audit and Multi-User Release Gates

## Implemented foundations

- Telegram chat access remains fail-closed: an empty allowlist authorizes nobody.
- `security_controls.py` provides role names and permission checks for viewer, analyst, portfolio_manager and admin.
- A fail-closed helper maps an immutable, verified identity-provider subject to a server-managed role; it does not authenticate a user by itself.
- `security_controls.py` provides a SQLite hash-linked audit event log, serialized append operations, and a chain-verification routine.
- Audit payloads reject credential-like keys recursively, including common nested and naming variants.
- Portfolio books remain local SQLite by design; no shared cloud portfolio store is enabled.
- Performance/learning history can use PostgreSQL, but this database is not a substitute for tenant authorization.

## Important release status

**This application is not yet certified or configured for production multi-user deployment.** The RBAC and audit module is a control foundation, not a complete authentication/authorization deployment.

The current application does not establish a verified identity provider for every Streamlit session, does not enforce tenant ownership on every portfolio/database query, and does not yet route every privileged UI action through `require_permission` and `record_audit_event`. Therefore, role labels must never be inferred from a username, query parameter, browser state, or user-editable form.

## Required before enabling multiple users

1. Select and configure a trusted identity provider (OIDC/SAML or an equivalent verified provider).
2. Map immutable provider subject IDs to server-managed roles; deny access if identity or role is missing.
3. Enforce authorization server-side on every portfolio read/write/delete, report export, model configuration change, user administration action, and audit-log access.
4. Add tenant/user ownership keys to portfolio and private data tables; migrate existing local books with an explicit owner.
5. Use managed PostgreSQL with least-privilege credentials, TLS, connection limits, backups, and tested point-in-time recovery.
6. Export audit events to access-controlled append-only or WORM storage. The local hash chain is tamper-evident, not immutable against an administrator who can rewrite the database.
7. Redact secrets and personal data from logs; rotate credentials and document incident response.
8. Perform dependency, vulnerability, access-control, backup-restore, and penetration testing before release.

## Operational controls

- Keep API keys and database credentials in Streamlit secrets or environment variables, never in source files or audit payloads.
- Do not expose local SQLite files or database connection strings through downloads.
- Do not merge the development branch or deploy it to the public Streamlit app until the complete test suite and release gates pass.
- The system is research support only; it does not place broker orders or replace human review.
