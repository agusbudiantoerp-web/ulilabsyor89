from engine import calculate_dcf, dcf_sensitivity


def _data(fcf=100.0, debt=20.0, cash=30.0, shares=10.0):
    return {
        "currency": "IDR",
        "financial_currency": "IDR",
        "ratios": {
            "Free cash flow": fcf,
            "Total debt": debt,
            "Cash and equivalents": cash,
            "Shares outstanding": shares,
        },
    }


def test_standard_dcf_rejects_non_positive_equity_value():
    result = calculate_dcf(_data(debt=100_000, cash=0))
    assert result["available"] is False
    assert "Equity value tidak positif" in result["reason"]
    assert result["equity_value"] <= 0


def test_standard_dcf_rejects_boolean_forecast_years():
    result = calculate_dcf(_data(), years=True)
    assert result["available"] is False
    assert "bilangan bulat" in result["reason"]


def test_standard_dcf_rejects_extreme_growth_assumption():
    result = calculate_dcf(_data(), growth=1.25)
    assert result["available"] is False
    assert "growth" in result["reason"].lower()


def test_standard_dcf_rejects_wacc_above_100_percent():
    result = calculate_dcf(_data(), wacc=1.2)
    assert result["available"] is False
    assert "WACC" in result["reason"]


def test_standard_dcf_rejects_intrinsic_value_fx_overflow():
    result = calculate_dcf(
        {**_data(fcf=1e307, debt=0, cash=0, shares=1),
         "financial_currency": "USD", "currency": "IDR"},
        growth=0.0, fx_rate=100.0,
    )
    assert result["available"] is False
    assert "rentang numerik" in result["reason"]


def test_standard_dcf_sensitivity_rejects_boolean_years_and_extreme_assumptions():
    data = _data()
    assert not dcf_sensitivity(data, years=True)["available"]
    assert not dcf_sensitivity(data, growth_rates=[1.5])["available"]
    assert not dcf_sensitivity(data, wacc_rates=[1.2])["available"]


def test_standard_dcf_sensitivity_fails_closed_on_overflow():
    result = dcf_sensitivity(
        _data(fcf=1e308, debt=0, cash=0, shares=1),
        growth_rates=[0.5], wacc_rates=[0.12], years=20,
    )
    assert result["available"] is False
    assert "overflow" in result["reason"].lower()
