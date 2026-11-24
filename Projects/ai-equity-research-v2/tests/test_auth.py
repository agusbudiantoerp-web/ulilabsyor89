from types import SimpleNamespace

import pytest

from auth import (
    audit_login_once,
    get_claim,
    oidc_is_configured,
    oidc_provider_name,
    logout,
    resolve_streamlit_identity,
)
from security_controls import list_audit_events


class FakeUser(dict):
    is_logged_in = True


def test_oidc_configuration_requires_shared_settings_and_one_provider():
    assert oidc_is_configured({
        "auth": {
            "redirect_uri": "https://example.streamlit.app/oauth2callback",
            "cookie_secret": "private",
            "google": {
                "client_id": "id",
                "client_secret": "secret",
                "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            },
        }
    })
    assert not oidc_is_configured({})
    assert not oidc_is_configured({
        "auth": {
            "redirect_uri": "https://example.streamlit.app/oauth2callback",
            "cookie_secret": "private",
            "google": {"client_id": "id", "client_secret": "secret", "server_metadata_url": "https://example.com"},
            "microsoft": {"client_id": "id", "client_secret": "secret", "server_metadata_url": "https://example.org"},
        }
    })


def test_oidc_configuration_accepts_default_google_auth_block():
    secrets = {
        "auth": {
            "redirect_uri": "https://example.streamlit.app/oauth2callback",
            "cookie_secret": "private",
            "client_id": "id",
            "client_secret": "secret",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        }
    }
    assert oidc_is_configured(secrets)
    assert oidc_provider_name(secrets) is None


def test_oidc_provider_name_selects_one_named_provider_and_rejects_ambiguous_config():
    base = {
        "redirect_uri": "https://example.streamlit.app/oauth2callback",
        "cookie_secret": "private",
    }
    named = {
        "auth": {
            **base,
            "google": {
                "client_id": "id",
                "client_secret": "secret",
                "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            },
        }
    }
    assert oidc_is_configured(named)
    assert oidc_provider_name(named) == "google"
    ambiguous = {
        "auth": {
            **base,
            "client_id": "id",
            "client_secret": "secret",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            "google": named["auth"]["google"],
        }
    }
    assert not oidc_is_configured(ambiguous)


def test_identity_uses_subject_not_email_for_role_resolution():
    user = FakeUser(iss="https://accounts.google.com", sub="immutable-sub-001", email="person@example.com", name="Person")
    identity = resolve_streamlit_identity(
        user, {"auth_roles": {"https://accounts.google.com|immutable-sub-001": "portfolio_manager"}}
    )
    assert identity["subject_id"] == "https://accounts.google.com|immutable-sub-001"
    assert identity["role"] == "portfolio_manager"
    assert identity["email"] == "person@example.com"


def test_identity_requires_login_subject_and_server_role():
    with pytest.raises(PermissionError, match="belum terverifikasi"):
        resolve_streamlit_identity({"sub": "subject"}, {"auth_roles": {"subject": "admin"}})
    with pytest.raises(PermissionError, match="immutable subject"):
        resolve_streamlit_identity(FakeUser(iss="https://accounts.google.com", email="person@example.com"), {"auth_roles": {}})
    with pytest.raises(PermissionError, match="belum diberi role"):
        resolve_streamlit_identity(FakeUser(iss="https://accounts.google.com", sub="new-user"), {"auth_roles": {}})


def test_audit_login_is_written_once_per_session(tmp_path):
    audit_path = str(tmp_path / "audit.sqlite3")
    fake_st = SimpleNamespace(
        session_state={},
        secrets={"audit_db_path": audit_path},
    )
    identity = {"subject_id": "subject-001", "role": "analyst"}
    audit_login_once(fake_st, identity)
    audit_login_once(fake_st, identity)
    events = list_audit_events(10, audit_path)
    assert len(events) == 1
    assert events[0]["action"] == "LOGIN"
    assert events[0]["actor_id"] == "subject-001"


def test_claim_reader_supports_mapping_and_attribute_only_user():
    assert get_claim({"sub": "subject"}, "sub") == "subject"
    assert get_claim(SimpleNamespace(sub="subject"), "sub") == "subject"
    assert get_claim(SimpleNamespace(), "missing", "fallback") == "fallback"


def test_identity_requires_issuer_to_prevent_cross_provider_subject_collision():
    user = FakeUser(sub="same-subject")
    with pytest.raises(PermissionError, match="issuer"):
        resolve_streamlit_identity(user, {"auth_roles": {"same-subject": "admin"}})


def test_logout_is_not_blocked_by_audit_storage_failure(monkeypatch):
    import auth

    def fail_audit(*args, **kwargs):
        raise OSError("audit store unavailable")

    monkeypatch.setattr(auth, "record_audit_event", fail_audit)
    fake_st = SimpleNamespace(
        secrets={},
        logout=lambda: setattr(fake_st, "logged_out", True),
        logged_out=False,
    )
    audited = logout(fake_st, {"subject_id": "issuer|subject", "role": "analyst"})
    assert audited is False
    assert fake_st.logged_out is True
