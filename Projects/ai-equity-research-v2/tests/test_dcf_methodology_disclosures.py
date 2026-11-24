from engine import calculate_dcf


def test_standard_dcf_exposes_fcf_classification_and_terminal_concentration():
    result = calculate_dcf({
        "currency": "IDR",
        "financial_currency": "IDR",
        "ratios": {
            "Free cash flow": 100.0,
            "Total debt": 20.0,
            "Cash and equivalents": 30.0,
            "Shares outstanding": 10.0,
        },
    })
    assert result["available"] is True
    assert 0 <= result["terminal_value_share_pct"] <= 100
    assert any("FCFF versus FCFE" in item for item in result["model_warnings"])
