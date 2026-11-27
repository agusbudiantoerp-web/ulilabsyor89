import unittest
from bank_filing_collector import FilingRetrievalError, _validate_official_url, extract_metrics_from_pdf_text

class BankFilingCollectorTests(unittest.TestCase):
    def test_rejects_non_allowlisted_or_non_https_urls(self):
        for url in ("http://bri.co.id/report.pdf", "https://evil.example/report.pdf", "https://user:pass@bri.co.id/report.pdf"):
            with self.subTest(url=url), self.assertRaises(FilingRetrievalError):
                _validate_official_url(url)

    def test_extracts_values_with_period_and_provenance(self):
        text = "KPMM 20,62\nNPL gross 3,07\nReturn on Equity (ROE) 3) 22,11\nReturn on Equity (ROE) 4) 18,13\nNet Interest Margin (NIM) 6,16"
        result = extract_metrics_from_pdf_text(text, source_url="https://bri.co.id/report.pdf",
            source_name="BRI Q3 report", period="2026-09-30", document_sha256="abc123")
        metrics = result["metrics"]
        self.assertEqual(metrics["NPL gross (%)"]["value"], 3.07)
        self.assertEqual(metrics["CAR (%)"]["value"], 20.62)
        self.assertEqual(metrics["Official reported ROE (%)"]["value"], 18.13)
        self.assertEqual(metrics["NIM (%)"]["value"], 6.16)
        self.assertEqual(metrics["NPL gross (%)"]["period"], "2026-09-30")
        self.assertEqual(metrics["NPL gross (%)"]["source_url"], "https://bri.co.id/report.pdf")
        self.assertIn("LDR (%)", result["missing_metrics"])
        self.assertEqual(result["status"], "REVIEW REQUIRED")

    def test_does_not_promote_tier_one_roe(self):
        result = extract_metrics_from_pdf_text("Return on Equity (ROE) 3) 22,11",
            source_url="https://bri.co.id/report.pdf", source_name="BRI report", period="2026-09-30")
        self.assertNotIn("Official reported ROE (%)", result["metrics"])

if __name__ == "__main__":
    unittest.main()
