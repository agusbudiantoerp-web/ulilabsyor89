# OIDC Authentication Setup

The Streamlit application uses Streamlit's native OpenID Connect (OIDC) login. This release supports one OIDC provider per app. Google is the configured provider for the current deployment.

## 1. Register redirect URIs with Google

For each Streamlit app (production and preview), register its exact callback URL in the Google OAuth Web client:

```text
https://YOUR-APP-NAME.streamlit.app/oauth2callback
```

Keep the production callback registered when adding a preview callback. Do not replace it.

Google discovery metadata URL:

```text
https://accounts.google.com/.well-known/openid-configuration
```

Never commit the Google client secret or Streamlit cookie secret to Git.

## 2. Configure Streamlit Secrets

In Streamlit Community Cloud, open the specific app's Settings → Secrets. For the current single-provider Google setup, use the default `[auth]` section:

```toml
[auth]
redirect_uri = "https://YOUR-APP-NAME.streamlit.app/oauth2callback"
cookie_secret = "REPLACE_WITH_A_LONG_RANDOM_PRIVATE_VALUE"
client_id = "YOUR_GOOGLE_CLIENT_ID"
client_secret = "YOUR_GOOGLE_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[auth_roles]
"ISSUER_URL|IMMUTABLE_SUBJECT_FROM_LOGIN" = "admin"
```

Replace all placeholders privately in Streamlit Secrets. The `[auth]` values above are the default provider configuration; the application calls Streamlit's default OIDC provider. Do not paste secrets into chat, GitHub files, screenshots, or issue reports.

A named provider section such as `[auth.google]` is also supported by the application, but do not configure both the default provider keys and a named provider at the same time.

## 3. Assign roles safely

1. Save the provider settings and restart/reload the Streamlit app.
2. Sign in with the intended Google account.
3. If the account has no role yet, the app denies dashboard access and displays its exact `iss|sub` principal identifier.
4. As administrator, copy that exact identifier into `[auth_roles]` in the app's Streamlit Secrets and assign the approved role.
5. Repeat for each authorized user. Never assign roles using display name or email alone. The mapping key combines OIDC issuer (`iss`) and immutable subject (`sub`).

Supported roles:

| Role | Access |
|---|---|
| `viewer` | Read-only, owner-scoped Performance Dashboard |
| `analyst` | Equity research, daily signals, backtesting |
| `portfolio_manager` | Analyst access plus portfolio and risk management |
| `admin` | All application pages and administrative permission primitives |

## 4. Preview-first rollout

Create a separate Streamlit Community Cloud app using the development branch and this project entry point:

```text
Repository: agusbudiantoerp-web/ulilabsyor89
Branch: feature/advanced-equity-intelligence
Main file: Projects/ai-equity-research-v2/app.py
```

After Streamlit assigns the preview app URL:

- Add the preview callback URL to the same Google OAuth Web client, retaining the production callback.
- Copy the existing secrets privately into the preview app's Secrets.
- Change only the preview app's `redirect_uri` to its own preview callback URL.
- Do not alter production app settings while testing.

Initially keep the Google OAuth consent screen in Testing and add only approved test accounts.

## 5. Administrator console

The admin-only **Security & Audit** menu displays the configured OIDC principal-to-role mapping, recent audit events, CSV export, hash-chain verification and the selected storage backend for signals, portfolio books, research runs and audit events. Role assignments are still changed in Streamlit Secrets under `[auth_roles]`; the browser console is read-only. Storage indicators report configuration routing only and do not prove database connectivity or backup health.

## 6. Security and release limitations

- OIDC login and subject-to-role mapping do not by themselves prove complete tenant isolation.
- Audit events use shared PostgreSQL when `DATABASE_URL` is configured; otherwise they use local SQLite. The hash chain is tamper-evident, not WORM/immutable.
- Portfolio books, learning/performance records and saved research/backtest runs have owner scoping. Audit events are system-wide and visible only through the admin-only console; they still need protected external retention.
- Page entry points and selected write/delete/export operations have server-side permission checks. Complete review of every privileged operation and any future API endpoint is still required before production release.
- Use managed PostgreSQL, immutable/append-only central audit storage, backup restoration tests, and security testing before inviting multiple users.
- Keep client secrets, cookie secrets, database URLs, and API tokens only in Streamlit Secrets or a private local secrets file.
- This authentication change must be reviewed and tested before merging or deploying. It does not certify the application as production-ready.
