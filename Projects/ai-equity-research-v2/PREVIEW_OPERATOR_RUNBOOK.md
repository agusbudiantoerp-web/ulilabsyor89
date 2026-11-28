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

Create a dedicated Neon project for Preview only (do not reuse a production project or production branch). Use its default branch as the disposable Preview database, and retain TLS (`sslmode=require`). Use the Neon project owner/admin login as the migration identity: Neon does not provide a PostgreSQL SUPERUSER login; its managed administrator login is a member of the `neon_superuser` role. The RLS migration recognizes that managed membership. Do not create the migration identity as an ordinary SQL role. Keep the migration connection direct/unpooled (hostname has no `-pooler` suffix).

From the Neon SQL Editor (or `psql`) connected as the Neon project owner/admin on the Preview branch, create a restricted runtime role using SQL. SQL-created roles are not automatically members of `neon_superuser`; this is intentional. Use a unique role name for this Preview database:

```sql
CREATE ROLE ai_equity_preview_runtime
  LOGIN
  NOSUPERUSER
  NOBYPASSRLS
  NOINHERIT;
```

Set the role password interactively in `psql` so it is not embedded in shell history. If using the Neon SQL Editor, use its secure role/password management workflow rather than pasting a password into a saved query:

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

From Neon Console → Connect, select the Preview branch, database, and Neon project owner/admin role. Turn Connection pooling OFF and use the direct (unpooled) connection for migrations. Set that administrator connection only in the current private PowerShell session. Do not commit it or share it:

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
- Configure `DATABASE_URL` with the Preview runtime role's pooled connection only (hostname includes `-pooler`; not the administrator URL). Keep the direct/unpooled administrator URL only in the trusted workstation session for migrations. Neon recommends pooled connections for application traffic and direct connections for migrations.
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
- [ ] Backup is created, its SHA-256 manifest is verified, and the PostgreSQL archive is restored into a separate empty disposable database; the restore command completes and the post-restore relation check passes.

### PostgreSQL backup and restore drill

Run these commands from the repository root in PowerShell. First change into the project directory. The backup connection may use the approved Preview backup identity. The restore target must be a separate, empty disposable database; use a migration/admin identity with sufficient CREATE privileges. Never point either command at production.

Create and verify the archive:

```powershell
Set-Location .\Projects\ai-equity-research-v2
$env:DATABASE_URL = "YOUR_PRIVATE_PREVIEW_BACKUP_POSTGRES_URL"
python database_backup.py postgres --output-dir backups
# Copy the printed manifest path, then:
python database_backup.py verify --manifest "backups\YOUR_BACKUP.dump.manifest.json"
Remove-Item Env:DATABASE_URL
```

Restore to a separate empty Preview recovery database (the tool refuses a destination that already contains user relations and never drops existing objects):

```powershell
$env:DATABASE_URL = "YOUR_PRIVATE_EMPTY_PREVIEW_RESTORE_DATABASE_URL"
$env:AI_EQUITY_RESEARCH_CONFIRM_POSTGRES_RESTORE = "YES"
python database_backup.py restore-postgres --manifest "backups\YOUR_BACKUP.dump.manifest.json"
Remove-Item Env:DATABASE_URL
Remove-Item Env:AI_EQUITY_RESEARCH_CONFIRM_POSTGRES_RESTORE
```

Expected result: archive SHA-256/size validation succeeds, the manifest includes a non-secret source-database fingerprint, `pg_restore` completes in a single transaction with owner/ACL restoration disabled, and a post-restore query confirms application relations exist. The restore tool refuses a target whose host/port/database fingerprint matches the backup source, and it refuses a target containing user relations. Preserve the backup and manifest together. This verifies a logical restore into a separate disposable database; it is not a point-in-time recovery test or proof of provider-level disaster recovery.

After the archive restore, treat the recovery database as not yet application-ready. PostgreSQL roles are cluster-level objects and are not included in a normal database archive. On a different PostgreSQL cluster, recreate or verify the restricted runtime role before rerunning the RLS migration. For example, using the migration administrator in `psql`:

```sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_equity_preview_runtime') THEN
    CREATE ROLE ai_equity_preview_runtime LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;
  END IF;
END
$$;
```

Set the role password interactively in `psql` (outside the SQL block):

```text
\password ai_equity_preview_runtime
```

Then rerun `postgres_rls_migration.py` against the recovery database using its migration/admin identity, with `AI_EQUITY_RESEARCH_RUNTIME_ROLE=ai_equity_preview_runtime` and explicit confirmation. Because the archive is produced with `--no-owner --no-privileges`, verify table ownership and grants are repaired by the migration. Connect with the restricted runtime role and repeat the read-only Security & Audit checks, including RLS/FORCE RLS, grants, owner isolation and reviewer policies. Do not point the Preview app at the recovery database until those checks pass.

Record the test date, app commit, test account labels (not emails), expected result and observed result in the release acceptance record. Do not record credentials or tokens.

## 9. Stop/go decision

Preview is not accepted until all checks above pass and an independent security review is complete. A green GitHub Actions run is evidence of automated test behavior, not evidence that the live Preview identity, database, network, backups or browser UI are secure.

Do not merge PR #4, change `main`, or deploy production until the release owner explicitly approves the completed acceptance evidence.
