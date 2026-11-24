import unittest
from unittest.mock import patch

from multistage_adapter import calculate_multistage_dcf


class MultiStageAdapterFXTests(unittest.TestCase):

    def sample_data(self, financial_currency="IDR"):
        return {
            "price": 1500.0,
            "financial_currency": financial_currency,
            "quote_currency": "IDR",
            "ratios": {
                "Revenue": 1000.0,
                "EBITDA": 200.0,
                "Normalized EBITDA": 180.0,
                "Depreciation and amortization": 50.0,
                "Total debt": 100.0,
                "Cash and equivalents": 20.0,
                "Shares outstanding": 10.0,
                "Capital expenditure": -60.0,
                "Accounts receivable": 100.0,
                "Inventory": 50.0,
                "Accounts payable": 40.0,
                "Tax Rate For Calcs": 0.22,
            },
        }

    @patch("multistage_adapter.project_multistage_dcf")
    def test_same_currency_uses_fx_rate_one_and_no_date(self, mock_dcf):
        mock_dcf.return_value = {"available": True}

        result = calculate_multistage_dcf(
            self.sample_data("IDR"),
            {},
            fx_rate=None,
            fx_source_date="2026-11-06",
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["fx_rate_applied"], 1.0)
        self.assertIsNone(result["fx_source_date"])
        mock_dcf.assert_called_once()

    @patch("multistage_adapter.project_multistage_dcf")
    def test_different_currency_preserves_fx_rate_and_date(self, mock_dcf):
        mock_dcf.return_value = {"available": True}

        result = calculate_multistage_dcf(
            self.sample_data("USD"),
            {},
            fx_rate=16500.0,
            fx_source_date="2026-11-06",
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["fx_rate_applied"], 16500.0)
        self.assertEqual(result["fx_source_date"], "2026-11-06")
        mock_dcf.assert_called_once()

    @patch("multistage_adapter.project_multistage_dcf")
    def test_different_currency_rejects_missing_fx_rate(self, mock_dcf):
        result = calculate_multistage_dcf(
            self.sample_data("USD"),
            {},
            fx_rate=None,
            fx_source_date="2026-11-06",
        )

        self.assertFalse(result["available"])
        self.assertIn("FX rate wajib diisi", result["reason"])
        mock_dcf.assert_not_called()

    @patch("multistage_adapter.project_multistage_dcf")
    def test_material_normalized_ebitda_difference_requires_review(self, mock_dcf):
        data = self.sample_data()
        data["ratios"]["Normalized EBITDA"] = 150.0

        result = calculate_multistage_dcf(data, {})

        self.assertFalse(result["available"])
        self.assertIn("Requires Manual Review", result["reason"])
        self.assertTrue(result["warnings"])
        mock_dcf.assert_not_called()

    @patch("multistage_adapter.project_multistage_dcf")
    def test_engine_warning_is_informational_not_blocking(self, mock_dcf):
        mock_dcf.return_value = {"available": True}
        data = self.sample_data()
        data["data_quality_warnings"] = [
            "EBITDA berasal dari klasifikasi Yahoo Finance."
        ]

        result = calculate_multistage_dcf(data, {})

        self.assertTrue(result["available"])
        self.assertEqual(
            result["data_quality_warnings"],
            data["data_quality_warnings"]
        )
        self.assertFalse(result["warnings"])
        mock_dcf.assert_called_once()

if __name__ == "__main__":
    unittest.main()


    @patch("multistage_adapter.project_multistage_dcf")
    def test_critical_statement_period_mismatch_requires_manual_review(self, mock_dcf):
        mock_dcf.return_value = {"available": True}
        data = self.sample_data()
        data["data_quality_warnings"] = [
            "Periode laporan laba rugi dan neraca berbeda."
        ]
        result = calculate_multistage_dcf(data, {})
        self.assertFalse(result["available"])
        self.assertIn("Requires Manual Review", result["reason"])
        self.assertTrue(result["critical_data_quality_warnings"])
        mock_dcf.assert_not_called()

    @patch("multistage_adapter.project_multistage_dcf")
    def test_critical_warning_can_only_proceed_with_explicit_override(self, mock_dcf):
        mock_dcf.return_value = {"available": True}
        data = self.sample_data()
        data["data_quality_warnings"] = [
            "Periode laporan laba rugi dan neraca berbeda."
        ]
        result = calculate_multistage_dcf(
            data, {}, allow_data_quality_override=True
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["critical_data_quality_warnings"])
        self.assertTrue(result["data_quality_override"])
        mock_dcf.assert_called_once()
