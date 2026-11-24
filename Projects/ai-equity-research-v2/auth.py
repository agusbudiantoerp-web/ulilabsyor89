"""Streamlit-native OIDC authentication and fail-closed role resolution.

Identity claims are supplied by Streamlit's verified OIDC session. Roles are
mapped only by immutable provider subject IDs stored in server-side secrets.
"""
from __future__ import annotations

from typing import Any

from security_controls import record_audit_event, resolve_role_for_subject


def oidc_is_configured(secrets: Any) -> bool:
    """Require Streamlit auth settings and at least one configured OIDC provider."""
    try:
        auth_settings = secrets.get("auth", {})
        if not isinstance(auth_settings, dict) and not hasattr(auth_settings, "get"):
            return False
        if not auth_settings.get("redirect_uri") or not auth_settings.get("cookie_secret"):
            return False
        providers = [
            value for key, value in auth_settings.items()
            if isinstance(value, dict) or hasattr(value, "get")
            if value.get("client_id") and value.get("client_secret")
            and value.get("server_metadata_url")
        ]
        return bool(providers)
    except Exception:
        return False


def resolve_streamlit_identity(user: Any, secrets: Any) -> dict:
    """Resolve a logged-in Streamlit user; never derive role from email/name."""
    if not bool(getattr(user, "is_logged_in", False)):
        raise PermissionError("Sesi login belum terverifikasi.")
    subject = str(user.get("sub", "") or "").strip()
    if not subject:
        raise PermissionError("Provider tidak memberikan immutable subject (sub).")
    role_mapping = secrets.get("auth_roles", {})
    role = resolve_role_for_subject(subject, role_mapping)
    return {
        "subject_id": subject,
        "role": role,
        "email": str(user.get("email", "") or ""),
        "name": str(user.get("name", "") or ""),
    }


def audit_login_once(st_module: Any, identity: dict) -> None:
    """Write one login audit event per Streamlit session; fail closed on audit errors."""
    key = "_security_login_audited"
    if st_module.session_state.get(key):
        return
    audit_path = st_module.secrets.get("audit_db_path", "data/audit_log.sqlite3")
    record_audit_event(
        identity["subject_id"],
        identity["role"],
        "LOGIN",
        "streamlit_session",
        details={"authentication": "OIDC"},
        path=str(audit_path),
    )
    st_module.session_state[key] = True


def logout(st_module: Any, identity: dict) -> None:
    """Audit logout before invoking Streamlit's OIDC logout."""
    audit_path = st_module.secrets.get("audit_db_path", "data/audit_log.sqlite3")
    record_audit_event(
        identity["subject_id"],
        identity["role"],
        "LOGOUT",
        "streamlit_session",
        details={"authentication": "OIDC"},
        path=str(audit_path),
    )
    st_module.logout()
