import unittest
from multistage_dcf import project_multistage_dcf

class TestMultiStageDCF(unittest.TestCase):
    def setUp(self):
        self.f = {"revenue_base": 1000.0, "net_debt": 80.0, "shares_outstanding": 10.0, "current_price": 1500.0, "fx_rate": 1.0}
        self.a = {"high_growth": 0.12, "transition_growth": 0.08, "stable_growth": 0.04, "high_growth_years": 2, "transition_growth_years": 2, "ebitda_margin": 0.20, "da_pct_revenue": 0.05, "capex_pct_revenue": 0.06, "nwc_pct_revenue": 0.11, "tax_rate": 0.22, "wacc": 0.12, "terminal_growth": 0.025}
    def test_base_case_returns_positive_valuation(self):
        result = project_multistage_dcf(self.f, self.a, years=5)
        self.assertTrue(result["available"], result.get("reason"))
        self.assertGreater(result["intrinsic_value_per_share"], 0)
    def test_higher_wacc_lowers_intrinsic_value(self):
        low = dict(self.a)
        high = dict(self.a)
        low["wacc"] = 0.10
        high["wacc"] = 0.14
        result_low = project_multistage_dcf(self.f, low, years=5)
        result_high = project_multistage_dcf(self.f, high, years=5)
        self.assertTrue(result_low["available"])
        self.assertTrue(result_high["available"])
        self.assertGreater(result_low["intrinsic_value_per_share"], result_high["intrinsic_value_per_share"])
    def test_higher_terminal_capex_lowers_intrinsic_value(self):
        low = dict(self.a)
        high = dict(self.a)
        low["terminal_capex_pct_revenue"] = 0.05
        high["terminal_capex_pct_revenue"] = 0.10
        result_low = project_multistage_dcf(self.f, low, years=5)
        result_high = project_multistage_dcf(self.f, high, years=5)
        self.assertTrue(result_low["available"])
        self.assertTrue(result_high["available"])
        self.assertGreater(result_low["intrinsic_value_per_share"], result_high["intrinsic_value_per_share"])
    def test_wacc_must_exceed_terminal_growth(self):
        invalid = dict(self.a)
        invalid["wacc"] = invalid["terminal_growth"]
        result = project_multistage_dcf(self.f, invalid, years=5)
        self.assertFalse(result["available"])
        self.assertIn("WACC must be positive and higher than terminal growth", result["reason"])
    def test_fractional_stage_duration_returns_unavailable(self):
        invalid = dict(self.a)
        invalid["high_growth_years"] = 1.5
        result = project_multistage_dcf(self.f, invalid, years=5)
        self.assertFalse(result["available"])
        self.assertIn("Growth stage durations must be whole numbers", result["reason"])

    def test_zero_stage_duration_returns_unavailable(self):
        invalid = dict(self.a)
        invalid["high_growth_years"] = 0
        result = project_multistage_dcf(self.f, invalid, years=5)
        self.assertFalse(result["available"])
        self.assertIn("at least one year", result["reason"])

    def test_stage_durations_exceeding_forecast_returns_unavailable(self):
        invalid = dict(self.a)
        invalid["high_growth_years"] = 3
        invalid["transition_growth_years"] = 3
        result = project_multistage_dcf(self.f, invalid, years=5)
        self.assertFalse(result["available"])
        self.assertIn("exceed forecast years", result["reason"])

    def test_negative_terminal_fcff_returns_unavailable(self):
        invalid = dict(self.a)
        invalid["terminal_capex_pct_revenue"] = 2.0
        result = project_multistage_dcf(self.f, invalid, years=5)
        self.assertFalse(result["available"])
        self.assertIn("Terminal FCFF is not positive", result["reason"])

if __name__ == "__main__":
    unittest.main()


    def test_model_discloses_terminal_value_share_and_low_terminal_capex(self):
        assumptions = dict(self.a)
        assumptions["capex_pct_revenue"] = 0.10
        assumptions["terminal_capex_pct_revenue"] = 0.01
        result = project_multistage_dcf(self.f, assumptions, years=5)
        self.assertTrue(result["available"], result.get("reason"))
        self.assertGreaterEqual(result["terminal_value_share_pct"], 0)
        self.assertLessEqual(result["terminal_value_share_pct"], 100)
        self.assertTrue(any("Terminal CAPEX intensity" in item for item in result["model_warnings"]))


    def test_extreme_finite_revenue_is_rejected_on_numerical_overflow(self):
        financials = dict(self.f)
        financials["revenue_base"] = 1e308
        result = project_multistage_dcf(financials, self.a, years=5)
        self.assertFalse(result["available"])
        self.assertIn("Numerical overflow", result["reason"])

    def test_terminal_overflow_is_reported_as_unavailable(self):
        financials = dict(self.f)
        financials["revenue_base"] = 1e307
        assumptions = dict(self.a)
        assumptions["high_growth"] = 1.5
        assumptions["transition_growth"] = 1.0
        assumptions["stable_growth"] = 0.5
        result = project_multistage_dcf(financials, assumptions, years=5)
        self.assertFalse(result["available"])
        self.assertIn("Numerical overflow", result["reason"])
