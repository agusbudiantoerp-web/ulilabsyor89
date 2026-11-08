import unittest
import pandas as pd

from idx_analysis import analyze_idx_fundamentals


class IdxAnalysisTests(unittest.TestCase):
    def setUp(self):
        periods = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
        self.data = {
            "ticker": "ANTM.JK",
            "company_name": "Example Mining Tbk",
            "sector": "Basic Materials",
            "industry": "Mining",
            "reported_currency": "IDR",
            "source": "Test data",
            "periods": {
                "income_statement": ["2025-12-31", "2024-12-31"],
                "balance_sheet": ["2025-12-31", "2024-12-31"],
                "cash_flow": ["2025-12-31", "2024-12-31"],
            },
            "statements": {
                "income_statement": pd.DataFrame(
                    [[1200, 1000], [240, 150], [180, 120], [200, 160], [120, 100]],
                    index=["Total Revenue", "Gross Profit", "Operating Income", "EBITDA", "Net Income"],
                    columns=periods,
                ),
                "balance_sheet": pd.DataFrame(
                    [[1100, 900], [550, 450], [200, 180], [100, 80]],
                    index=["Total Assets", "Stockholders Equity", "Total Debt", "Cash And Cash Equivalents"],
                    columns=periods,
                ),
                "cash_flow": pd.DataFrame(
                    [[140, 100]], index=["Free Cash Flow"], columns=periods
                ),
            },
            "warnings": [],
        }

    def test_revenue_growth_is_calculated(self):
        result = analyze_idx_fundamentals(self.data)["annual_metrics"]
        self.assertAlmostEqual(result.iloc[0]["revenue_growth_pct"], 20.0)

    def test_profitability_margins_are_calculated(self):
        result = analyze_idx_fundamentals(self.data)["annual_metrics"]
        self.assertAlmostEqual(result.iloc[0]["net_margin_pct"], 10.0)
        self.assertAlmostEqual(result.iloc[0]["gross_margin_pct"], 20.0)

    def test_roe_and_roa_use_average_balances(self):
        result = analyze_idx_fundamentals(self.data)["annual_metrics"]
        self.assertAlmostEqual(result.iloc[0]["roe_pct"], 120 / 500 * 100)
        self.assertAlmostEqual(result.iloc[0]["roa_pct"], 120 / 1000 * 100)

    def test_net_debt_is_calculated(self):
        result = analyze_idx_fundamentals(self.data)["annual_metrics"]
        self.assertAlmostEqual(result.iloc[0]["net_debt"], 100)

    def test_missing_previous_period_keeps_growth_unavailable(self):
        data = self.data.copy()
        data["periods"] = {name: ["2025-12-31"] for name in data["periods"]}
        data["statements"] = {name: frame.iloc[:, :1].copy() for name, frame in self.data["statements"].items()}
        result = analyze_idx_fundamentals(data)["annual_metrics"]
        self.assertTrue(pd.isna(result.iloc[0]["revenue_growth_pct"]))


if __name__ == "__main__":
    unittest.main()
