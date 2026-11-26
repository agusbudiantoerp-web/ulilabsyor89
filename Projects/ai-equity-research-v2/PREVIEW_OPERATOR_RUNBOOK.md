# Preview Operator Runbook — AI Equity Research V2

This runbook is for a disposable Preview environment only. It does not authorize a production migration, merge, or deployment.

## Safety rules

- Use a new Preview Streamlit app and a new disposable PostgreSQL database. Never point these steps at production.
- Keep the administrator/migration URL, runtime URL, OAuth client secret, cookie secret and database passwords in a private password manager or local secret store. Never paste them into chat, GitHub issues, source files or screenshots.
- The PostgreSQL migration identity and application runtime identity must be different.
- Do not put the administrator URL in Streamlit Secrets. The hosted app receives only the restricted runtime connection.
- Stop if any migration or diagnostic reports an error. Do not bypass a failed RLS check to make the app appear healthy.

## 1. Create the Preview app

In Streamlit Community Cloud, create a separate app with:

- Repository: `agusbudiantoerp-web/ulilabsyor89`
- Branch: `feature/advanced-equity-intelligence`
- Main file: `Projects/ai-equity-research-v2/app.py`

Record the assigned Preview hostname. Do not change the production app.

## 2. Configure the Preview OIDC callback

In the Google OAuth Web client, add the Preview callback while retaining any existing production callback:

```text
https://YOUR-PREVIEW-APP.streamlit.app/oauth2callback
```

If Google Console displays Authorized JavaScript origins, use only the origin (no path):

```text
https://YOUR-PREVIEW-APP.streamlit.app
```

Keep the consent screen in Testing and allow only approved test accounts during acceptance. Configure the Preview app's private Streamlit Secrets using the exact format in `OIDC_SETUP.md`; change `redirect_uri` to the Preview callback. Configure one OIDC provider only. Never copy client secrets into this repository.

## 3. Provision Preview PostgreSQL

Create a dedicated disposable PostgreSQL database with TLS enabled and a dedicated migration/admin identity. The migration identity must be able to create/alter the application's schema objects and must be SUPERUSER or BYPASSRLS for the RLS rollout/maintenance checks. On managed PostgreSQL, confirm the provider supports the required privileges before proceeding.

Connect as the migration identity and create a new runtime role. Use a unique role name for this Preview database:

```sql
CREATE ROLE ai_equity_preview_runtime
  LOGIN
  NOSUPERUSER
  NOBYPASSRLS
  NOINHERIT;
```

Set the role password interactively in `psql` so it is not embedded in shell history:

```text
\password ai_equity_preview_runtime
```

Do not grant this role membership in any other role. Do not make it the owner of the database, schema or application tables. The migration script grants schema/table/required sequence privileges. If the role inherits another role or owns any tenant table, the migration must stop.

## 4. Run schema migration from a trusted workstation

On a trusted workstation, check out the same development branch and enter the project directory:

```powershell
cd Projects/ai-equity-research-v2
python -m pip install -r requirements.txt
```

Set the administrator connection only in the current private PowerShell session. Do not commit it or share it:

```powershell
$env:DATABASE_URL = "YOUR_PRIVATE_PREVIEW_ADMIN_POSTGRES_URL"
$env:AI_EQUITY_RESEARCH_CONFIRM_SCHEMA_MIGRATION = "YES"
python postgres_schema_migration.py
Remove-Item Env:DATABASE_URL
Remove-Item Env:AI_EQUITY_RESEARCH_CONFIRM_SCHEMA_MIGRATION
```

Expected result: eight initializer groups complete, including audit log/hash-chain lock. The script does not install RLS.

If this fails, stop and inspect the database and migration output before retrying. Do not switch to production credentials.

## 5. Apply RLS and least-privilege grants

Use the same private administrator connection. Set the runtime role name to the role created in Step 3:

```powershell
$env:DATABASE_URL = "YOUR_PRIVATE_PREVIEW_ADMIN_POSTGRES_URL"
$env:AI_EQUITY_RESEARCH_RUNTIME_ROLE = "ai_equity_preview_runtime"
$env:AI_EQUITY_RESEARCH_CONFIRM_RLS_MIGRATION = "YES"
python postgres_rls_migration.py
Remove-Item Env:DATABASE_URL
Remove-Item Env:AI_EQUITY_RESEARCH_RUNTIME_ROLE
Remove-Item Env:AI_EQUITY_RESEARCH_CONFIRM_RLS_MIGRATION
```

Expected result: RLS is enabled and forced on all 12 registered owner-scoped tables. The migration grants only required table privileges and backing-sequence access for insertable tables. It also installs the assigned-reviewer read policies.

The migration must reject a runtime role that is SUPERUSER, BYPASSRLS, inherits another role, owns a tenant table, or is the same identity as the migration connection. Resolve any rejection at the database privilege level; never weaken the migration checks.

## 6. Configure Preview Streamlit Secrets

In the Preview app's Settings → Secrets:

- Configure the single OIDC provider and `[auth_roles]` mapping as documented in `OIDC_SETUP.md`.
- Configure `DATABASE_URL` with the Preview runtime role connection only (not the administrator URL).
- Keep all other required API credentials private and Preview-specific.
- Do not copy a production database URL or migration/admin credential into Preview.

Restart/redeploy the Preview app after saving Secrets.

## 7. Verify using the application runtime identity

Sign in as the approved Preview admin account and open Security & Audit. Confirm database diagnostics show:

- PostgreSQL connection succeeds using the runtime identity.
- All 12 registered tenant tables have RLS enabled and FORCE RLS.
- Tenant and assigned-reviewer policy coverage is present and applicable to the runtime role.
- Runtime role is not SUPERUSER or BYPASSRLS and does not own tenant tables.
- Required CRUD grants are present; unrelated administrator-owned sequences are not exposed.
- No broad unexpected permissive policy or privilege warning is reported.

The diagnostics are read-only. They do not repair a database. If any check fails, stop and correct the Preview database configuration with the administrator identity, then re-check.

## 8. Two-identity acceptance checklist

Use two separate Google test accounts, A and B, plus an assigned reviewer where appropriate. Do not use real customer or production data.

- [ ] Unknown/unmapped OIDC principal is denied.
- [ ] Account A creates a portfolio book, position, cash-flow event and valuation; account B cannot read, modify, delete or export A's records.
- [ ] Account A and B cannot see each other's saved research runs, daily signals/outcomes or investment theses.
- [ ] Reviewer can access only the explicitly assigned thesis/version and can submit only the permitted review decision.
- [ ] Reviewer cannot access unrelated tenant records or perform owner-only writes.
- [ ] Role-gated pages and direct operation paths reject unauthorized roles.
- [ ] Audit console and audit export are admin-only; audit chain verification succeeds.
- [ ] Logout/account switching does not retain the prior principal's session data.
- [ ] Backup is created and restored into a separate disposable database; restored data passes integrity checks.

Record the test date, app commit, test account labels (not emails), expected result and observed result in the release acceptance record. Do not record credentials or tokens.

## 9. Stop/go decision

Preview is not accepted until all checks above pass and an independent security review is complete. A green GitHub Actions run is evidence of automated test behavior, not evidence that the live Preview identity, database, network, backups or browser UI are secure.

Do not merge PR #4, change `main`, or deploy production until the release owner explicitly approves the completed acceptance evidence.
