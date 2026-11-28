"""Streamlit entry-point smoke tests for fail-closed startup behavior."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_app_entrypoint_renders_and_fails_closed_without_oidc_secrets():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not app.exception
    assert any(
        "autentikasi OIDC belum dikonfigurasi" in str(element.value)
        for element in app.error
    )
    assert any(
        "AI Equity Research Workspace" in str(element.value)
        for element in app.markdown
    )
