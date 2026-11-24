# OIDC Authentication Setup

The Streamlit application now uses Streamlit's native OIDC login. It supports a single configured OIDC provider at a time (for example, Google or Microsoft Entra ID). The application does not contain provider credentials.

## 1. Configure the identity provider

Create an OIDC web application in the provider's administration console. Register this exact redirect URI:

```text
https://YOUR-APP-NAME.streamlit.app/oauth2callback
```

For local development, register the local callback separately:

```text
http://localhost:8501/oauth2callback
```

Use the issuer's discovery metadata URL:

- Google: `https://accounts.google.com/.well-known/openid-configuration`
- Microsoft Entra ID: `https://login.microsoftonline.com/YOUR-TENANT-ID/v2.0/.well-known/openid-configuration`

Use the client ID and client secret supplied by the identity provider. Never commit these values to Git.

## 2. Configure Streamlit Secrets

Open the app's Streamlit Cloud settings → Secrets. Add the shared authentication settings and exactly one provider block. Replace every placeholder privately.

### Google example

```toml
[auth]
redirect_uri = "https://YOUR-APP-NAME.streamlit.app/oauth2callback"
cookie_secret = "REPLACE_WITH_A_LONG_RANDOM_PRIVATE_VALUE"

[auth.google]
client_id = "YOUR_GOOGLE_CLIENT_ID"
client_secret = "YOUR_GOOGLE_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[auth_roles]
"IMMUTABLE_SUBJECT_FROM_LOGIN" = "admin"
```

### Microsoft Entra ID example

Use this provider block instead of the Google block:

```toml
[auth]
redirect_uri = "https://YOUR-APP-NAME.streamlit.app/oauth2callback"
cookie_secret = "REPLACE_WITH_A_LONG_RANDOM_PRIVATE_VALUE"

[auth.microsoft]
client_id = "YOUR_ENTRA_APPLICATION_CLIENT_ID"
client_secret = "YOUR_ENTRA_CLIENT_SECRET"
server_metadata_url = "https://login.microsoftonline.com/YOUR-TENANT-ID/v2.0/.well-known/openid-configuration"

[auth_roles]
"IMMUTABLE_SUBJECT_FROM_LOGIN" = "admin"
```

Do not configure both provider blocks at the same time in this release: the login flow intentionally requires exactly one provider.

## 3. Assign roles

1. Save the provider settings and restart/reload the Streamlit app.
2. Sign in with the intended account.
3. If the account has no role yet, the app denies dashboard access and displays that account's immutable `sub` claim.
4. As the administrator, copy that exact `sub` value into `[auth_roles]` in Streamlit Secrets and assign an approved role.
5. Repeat for each authorized user. Never assign a role based only on a display name or email address.

Supported roles:

| Role | Access |
|---|---|
| `viewer` | Performance dashboard |
| `analyst` | Equity research, daily signals, backtesting, performance dashboard |
| `portfolio_manager` | Analyst access plus portfolio and risk management |
| `admin` | All application pages and administrative permission primitives |

The current UI page gate is enforced server-side. Sensitive operations inside individual pages still require a separate complete authorization review before production multi-user use.

## 4. Important release limitations

- OIDC login and subject-to-role mapping do not by themselves provide tenant isolation.
- Audit events currently use a local SQLite file unless `audit_db_path` is configured. Hosted local storage may be ephemeral.
- Portfolio books and other private records are not yet tenant-scoped.
- Every export, write, delete, model-configuration action, and audit viewer must be individually permission-checked before production release.
- Use managed PostgreSQL, immutable/append-only central audit storage, backup restoration tests, and security testing before inviting multiple users.
- Keep `client_secret`, `cookie_secret`, database URLs and API tokens only in Streamlit Secrets or a private local secrets file.
- This authentication change must be reviewed and tested before merging or deploying. It does not certify the application as production-ready.
