from engine import calculate_dcf


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
