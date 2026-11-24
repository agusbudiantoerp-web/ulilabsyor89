"""Streamlit-native OIDC authentication and fail-closed role resolution.

Identity claims are supplied by Streamlit's verified OIDC session. Roles are
mapped only by immutable provider subject IDs stored in server-side secrets.
"""
from __future__ import annotations

from typing import Any

from security_controls import record_audit_event, resolve_role_for_subject


def oidc_provider_name(secrets: Any) -> str | None:
    """Return the single configured provider name, or None for Streamlit's default provider."""
    auth_settings = secrets.get("auth", {})
    if not isinstance(auth_settings, dict) and not hasattr(auth_settings, "get"):
        raise ValueError("Konfigurasi [auth] tidak valid.")
    if not auth_settings.get("redirect_uri") or not auth_settings.get("cookie_secret"):
        raise ValueError("redirect_uri dan cookie_secret wajib dikonfigurasi.")
    root_configured = all(auth_settings.get(key) for key in (
        "client_id", "client_secret", "server_metadata_url"
    ))
    named = [
        str(key) for key, value in auth_settings.items()
        if (isinstance(value, dict) or hasattr(value, "get"))
        and value.get("client_id") and value.get("client_secret")
        and value.get("server_metadata_url")
    ]
    if root_configured and not named:
        return None
    if not root_configured and len(named) == 1:
        return named[0]
    raise ValueError("Harus ada tepat satu konfigurasi OIDC: default [auth] atau satu provider bernama.")


def oidc_is_configured(secrets: Any) -> bool:
    """Accept one default provider or exactly one named provider."""
    try:
        oidc_provider_name(secrets)
        return True
    except Exception:
        return False


def get_claim(user: Any, key: str, default: Any = "") -> Any:
    """Read a Streamlit OIDC claim without assuming a concrete User implementation."""
    try:
        return user.get(key, default)
    except (AttributeError, TypeError):
        try:
            return user[key]
        except (KeyError, TypeError, AttributeError):
            return getattr(user, key, default)


def resolve_streamlit_identity(user: Any, secrets: Any) -> dict:
    """Resolve a logged-in Streamlit user; never derive role from email/name."""
    if not bool(getattr(user, "is_logged_in", False)):
        raise PermissionError("Sesi login belum terverifikasi.")
    subject = str(get_claim(user, "sub", "") or "").strip()
    issuer = str(get_claim(user, "iss", "") or "").strip().rstrip("/")
    if not subject or not issuer:
        raise PermissionError("Provider tidak memberikan immutable subject (sub) dan issuer (iss).")
    # Subject identifiers are unique only within an issuer. Bind both to avoid
    # accidental role reuse if the configured identity provider is changed.
    principal_id = f"{issuer}|{subject}"
    role_mapping = secrets.get("auth_roles", {})
    role = resolve_role_for_subject(principal_id, role_mapping)
    return {
        "subject_id": principal_id,
        "provider_subject": subject,
        "issuer": issuer,
        "role": role,
        "email": str(get_claim(user, "email", "") or ""),
        "name": str(get_claim(user, "name", "") or ""),
    }


def audit_login_once(st_module: Any, identity: dict) -> None:
    """Write one login audit event per Streamlit session; fail closed on audit errors."""
    key = "_security_login_audited"
    if st_module.session_state.get(key):
        return
    audit_path = st_module.secrets.get("audit_db_path")
    record_audit_event(
        identity["subject_id"],
        identity["role"],
        "LOGIN",
        "streamlit_session",
        details={"authentication": "OIDC"},
        path=str(audit_path) if audit_path else None,
    )
    st_module.session_state[key] = True


def logout(st_module: Any, identity: dict) -> bool:
    """Always terminate the OIDC session; report whether the audit append succeeded."""
    audited = True
    try:
        audit_path = st_module.secrets.get("audit_db_path", "data/audit_log.sqlite3")
        record_audit_event(
            identity["subject_id"],
            identity["role"],
            "LOGOUT",
            "streamlit_session",
            details={"authentication": "OIDC"},
            path=str(audit_path),
        )
    except Exception:
        audited = False
    finally:
        st_module.logout()
    return audited
