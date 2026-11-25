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


@pytest.mark.parametrize(
    ("module_name", "render_name", "role"),
    [
        ("corporate_action_calendar_page", "render_corporate_action_calendar", "viewer"),
        ("cross_market_simulation_page", "render_cross_market_simulation", "viewer"),
        ("cross_market_simulation_page", "render_cross_market_simulation", "analyst"),
        ("valuation_intelligence_page", "render_valuation_intelligence", "viewer"),
    ],
)
def test_sensitive_research_pages_enforce_permission_inside_render(
    monkeypatch, module_name, render_name, role
):
    import importlib

    module = importlib.import_module(module_name)
    monkeypatch.setattr(
        module.st,
        "session_state",
        {"_auth_subject_id": "issuer|test-user", "_auth_role": role},
    )

    with pytest.raises(PermissionError):
        getattr(module, render_name)()
