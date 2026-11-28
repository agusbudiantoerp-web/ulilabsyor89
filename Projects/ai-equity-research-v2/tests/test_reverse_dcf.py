import pytest

from reverse_dcf import reverse_dcf_implied_growth, reverse_dcf_sensitivity


def model_at_growth(growth):
    fcf, shares, debt, wacc, terminal, years = 100.0, 10.0, 50.0, 0.10, 0.03, 5
    projected = [fcf * (1 + growth) ** year for year in range(1, years + 1)]
    pv = sum(value / (1 + wacc) ** year for year, value in enumerate(projected, 1))
    tv = projected[-1] * (1 + terminal) / (wacc - terminal)
    ev = pv + tv / (1 + wacc) ** years
    return (ev - debt) / shares


def test_reverse_dcf_recovers_known_implied_growth():
    price = model_at_growth(0.12)
    result = reverse_dcf_implied_growth(
        current_fcf=100, market_price=price, diluted_shares=10,
        net_debt=50, wacc=0.10, terminal_growth=0.03,
        forecast_years=5, lower_growth=-0.2, upper_growth=0.5,
    )
    assert result["implied_fcf_growth_pct"] == pytest.approx(12.0, abs=1e-5)
    assert result["implied_price"] == pytest.approx(price, rel=1e-6)


def test_reverse_dcf_reconciles_enterprise_to_equity_bridge():
    result = reverse_dcf_implied_growth(
        current_fcf=100, market_price=model_at_growth(0.08), diluted_shares=10,
        net_debt=50, wacc=0.10, terminal_growth=0.03,
        forecast_years=5, lower_growth=-0.2, upper_growth=0.5,
    )
    assert result["enterprise_value"] - result["net_debt"] == pytest.approx(
        result["target_equity_value"], rel=1e-6
    )
    assert result["terminal_value_share_pct"] > 0


@pytest.mark.parametrize("kwargs", [
    {"current_fcf": 0}, {"market_price": 0}, {"diluted_shares": 0},
    {"wacc": 0.03}, {"terminal_growth": 0.10}, {"forecast_years": 0},
])
def test_reverse_dcf_rejects_invalid_inputs(kwargs):
    params = dict(current_fcf=100, market_price=10, diluted_shares=10,
                  net_debt=0, wacc=0.10, terminal_growth=0.03, forecast_years=5)
    params.update(kwargs)
    with pytest.raises(ValueError):
        reverse_dcf_implied_growth(**params)


def test_reverse_dcf_flags_price_outside_growth_range():
    with pytest.raises(ValueError, match="di luar rentang"):
        reverse_dcf_implied_growth(
            current_fcf=100, market_price=1000, diluted_shares=10,
            net_debt=0, wacc=0.10, terminal_growth=0.03,
            forecast_years=5, lower_growth=-0.1, upper_growth=0.1,
        )


def test_reverse_dcf_rejects_terminal_growth_at_or_below_minus_100_percent():
    with pytest.raises(ValueError, match="WACC"):
        reverse_dcf_implied_growth(
            current_fcf=100, market_price=10, diluted_shares=10,
            net_debt=0, wacc=0.10, terminal_growth=-1.1,
        )


def test_reverse_dcf_sensitivity_reports_valid_and_invalid_cells():
    rows = reverse_dcf_sensitivity(
        current_fcf=100, market_price=model_at_growth(0.12), diluted_shares=10,
        net_debt=50, forecast_years=5, lower_growth=-0.2, upper_growth=0.5,
        wacc_values=[0.10, 0.12], terminal_growth_values=[0.03, 0.12],
    )
    assert len(rows) == 4
    assert any(row["status"] == "OK" for row in rows)
    assert any(row["status"] == "INVALID" for row in rows)


def test_reverse_dcf_explicit_fx_bridge_reconciles_quote_and_model_currency():
    model_price = model_at_growth(0.12)
    fx = 15000.0
    result = reverse_dcf_implied_growth(
        current_fcf=100, market_price=model_price * fx, diluted_shares=10,
        net_debt=50, wacc=0.10, terminal_growth=0.03,
        forecast_years=5, lower_growth=-0.2, upper_growth=0.5,
        fx_rate_quote_per_model=fx,
    )
    assert result["market_price_model_currency"] == pytest.approx(model_price)
    assert result["implied_price"] == pytest.approx(model_price * fx)
    assert result["implied_fcf_growth_pct"] == pytest.approx(12.0, abs=1e-5)


def test_reverse_dcf_rejects_non_positive_fx_rate():
    with pytest.raises(ValueError, match="positif"):
        reverse_dcf_implied_growth(
            current_fcf=100, market_price=10, diluted_shares=10,
            net_debt=0, wacc=0.10, terminal_growth=0.03,
            fx_rate_quote_per_model=0,
        )
