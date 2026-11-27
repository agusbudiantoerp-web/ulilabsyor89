import unittest
import pandas as pd

from bank_valuation import calculate_bank_valuation


def sample_bank():
    return {
        "ticker": "BBCA.JK",
        "company": "PT Bank Central Asia Tbk",
        "sector": "Financial Services",
        "industry": "Banks - Regional",
        "price": 6000.0,
        "currency": "IDR",
        "quote_currency": "IDR",
        "financial_currency": "IDR",
        "ratios": {
            "Total stockholders equity": 250_000_000_000_000,
            "Shares outstanding": 123_000_000_000,
            "Net income attributable to parent": 50_000_000_000_000,
            "ROE (%)": 20.0,
        },
    }


class BankValuationTests(unittest.TestCase):
    def test_rim_returns_intrinsic_value_and_outputs(self):
        result = calculate_bank_valuation(
            sample_bank(), expected_roe=0.18, cost_of_equity=0.12,
            stable_growth=0.04, years=5
        )
        self.assertTrue(result["available"])
        self.assertGreater(result["intrinsic_value_per_share"], 0)
        self.assertIsInstance(result["forecast"], pd.DataFrame)
        self.assertEqual(len(result["forecast"]), 5)
        self.assertEqual(len(result["scenarios"]), 3)
        self.assertEqual(result["sensitivity"].shape[0], 3)

    def test_rejects_missing_book_equity(self):
        data = sample_bank()
        data["ratios"]["Total stockholders equity"] = None
        result = calculate_bank_valuation(data, expected_roe=0.18)
        self.assertFalse(result["available"])
        self.assertIn("equity", result["reason"].lower())

    def test_rejects_cost_of_equity_not_above_growth(self):
        result = calculate_bank_valuation(
            sample_bank(), expected_roe=0.18,
            cost_of_equity=0.04, stable_growth=0.04
        )
        self.assertFalse(result["available"])
        self.assertIn("lebih tinggi", result["reason"])

    def test_requires_fx_when_financial_currency_differs(self):
        data = sample_bank()
        data["financial_currency"] = "USD"
        result = calculate_bank_valuation(data, expected_roe=0.18)
        self.assertFalse(result["available"])
        self.assertIn("kurs FX", result["reason"])

    def test_applies_fx_to_per_share_value(self):
        data = sample_bank()
        data["financial_currency"] = "USD"
        result = calculate_bank_valuation(
            data, expected_roe=0.18, cost_of_equity=0.12,
            stable_growth=0.04, fx_rate=16000
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["fx_rate_applied"], 16000)
        self.assertEqual(result["currency"], "IDR")

    def test_rejects_invalid_years(self):
        result = calculate_bank_valuation(sample_bank(), expected_roe=0.18, years=0)
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
