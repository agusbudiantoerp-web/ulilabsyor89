import pytest

import portfolio_cashflow_page


@pytest.mark.parametrize("role", ["viewer", "analyst"])
def test_cashflow_page_rejects_roles_without_portfolio_permission(monkeypatch, role):
    monkeypatch.setattr(
        portfolio_cashflow_page.st,
        "session_state",
        {"_auth_subject_id": "issuer|test-user", "_auth_role": role},
    )

    with pytest.raises(PermissionError, match="manage_portfolio"):
        portfolio_cashflow_page.render_portfolio_cashflow()
