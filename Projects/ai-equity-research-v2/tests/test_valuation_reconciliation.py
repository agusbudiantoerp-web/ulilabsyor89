import pytest

from reverse_dcf import reverse_dcf_implied_growth
from valuation_reconciliation import reconcile_dcf_models


def reverse_result():
    return reverse_dcf_implied_growth(
        current_fcf=100, market_price=100, diluted_shares=10,
        net_debt=100, wacc=0.10, terminal_growth=0.03,
        forecast_years=5, lower_growth=-0.2, upper_growth=0.5,
    ) | {"model_currency": "USD", "quote_currency": "IDR"}


def multistage_result():
    return {
        "available": True,
        "enterprise_value": 1100,
        "equity_value": 1000,
        "net_debt": 100,
        "intrinsic_value_per_share": 110,
        "financial_currency": "USD",
        "quote_currency": "IDR",
        "assumptions": {"wacc": 0.11, "terminal_growth": 0.025},
    }


def test_reconcile_dcf_models_checks_ev_and_equity_bridges():
    result = reconcile_dcf_models(multistage_result(), reverse_result())
    assert result["multistage_ev_bridge_residual"] == pytest.approx(0)
    assert result["reverse_ev_bridge_residual"] == pytest.approx(0)
    assert result["enterprise_value_gap"] == pytest.approx(
        result["multistage_enterprise_value"] - result["reverse_market_implied_enterprise_value"]
    )
    assert result["assumption_gaps"]["wacc_gap_pct_points"] == pytest.approx(1.0)
    assert result["financial_currency"] == "USD"
    assert result["quote_currency"] == "IDR"


def test_reconcile_dcf_models_rejects_currency_mismatch():
    reverse = reverse_result()
    reverse["model_currency"] = "IDR"
    with pytest.raises(ValueError, match="Mata uang model/quote tidak sama"):
        reconcile_dcf_models(multistage_result(), reverse)


def test_reconcile_dcf_models_requires_both_models_available():
    with pytest.raises(ValueError, match="Multi-Stage DCF harus tersedia"):
        reconcile_dcf_models({"available": False}, reverse_result())
