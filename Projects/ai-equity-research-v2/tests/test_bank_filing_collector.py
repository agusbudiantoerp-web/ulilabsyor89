import unittest
from bank_filing_collector import FilingRetrievalError, _validate_official_url, extract_metrics_from_pdf_text

class BankFilingCollectorTests(unittest.TestCase):
    def test_rejects_non_allowlisted_or_non_https_urls(self):
        for url in ("http://bri.co.id/report.pdf", "https://evil.example/report.pdf", "https://user:pass@bri.co.id/report.pdf"):
            with self.subTest(url=url), self.assertRaises(FilingRetrievalError):
                _validate_official_url(url)

    def test_extracts_values_with_period_and_provenance(self):
        text = "Kewajiban Penyediaan Modal Minimum (KPMM) | 20,62 | 23,01\n5. NPL gross | 3,07 | 3,29\n10. Return on Equity (ROE) 3) | 22,11 | 20,44\n11. Return on Equity (ROE) 4) | 18,13 | 16,48\n12. Net Interest Margin (NIM) | 6,16 | 6,53\n15. Loan to Deposit Ratio (LDR) | 88,22 | 87,05"
        result = extract_metrics_from_pdf_text(text, source_url="https://bri.co.id/report.pdf",
            source_name="BRI Q3 report", period="2026-09-30", document_sha256="abc123", roe_definition_mode="bri_q3_2026")
        metrics = result["metrics"]
        self.assertEqual(metrics["NPL gross (%)"]["value"], 3.07)
        self.assertEqual(metrics["CAR (%)"]["value"], 20.62)
        self.assertEqual(metrics["Official reported ROE (%)"]["value"], 18.13)
        self.assertEqual(metrics["NIM (%)"]["value"], 6.16)
        self.assertEqual(metrics["LDR (%)"]["value"], 88.22)
        self.assertEqual(metrics["LDR (%)"]["page"], 1)
        self.assertEqual(metrics["NPL gross (%)"]["period"], "2026-09-30")
        self.assertEqual(metrics["NPL gross (%)"]["source_url"], "https://bri.co.id/report.pdf")
        self.assertNotIn("LDR (%)", result["missing_metrics"])
        self.assertEqual(result["status"], "REVIEW REQUIRED")


    def test_extracts_values_when_pdf_splits_table_cells_across_lines(self):
        text = "5. NPL gross\n3,07\n3,29\n6. NPL net\n1,00\n1,04"
        result = extract_metrics_from_pdf_text(text, source_url="https://bri.co.id/report.pdf",
            source_name="BRI Q3 report", period="2026-09-30")
        self.assertEqual(result["metrics"]["NPL gross (%)"]["value"], 3.07)

    def test_extracts_values_when_split_cells_include_spaces(self):
        text = "5. NPL gross\n   3,07    3,29   \n6. NPL net\n1,00 1,04"
        result = extract_metrics_from_pdf_text(text, source_url="https://bri.co.id/report.pdf",
            source_name="BRI Q3 report", period="2026-09-30")
        self.assertEqual(result["metrics"]["NPL gross (%)"]["value"], 3.07)

    def test_generic_upload_does_not_assume_bri_roe_footnote_definition(self):
        result = extract_metrics_from_pdf_text(
            "Return on Equity (ROE) 4) | 18,13",
            source_url="https://bank.example/report.pdf", source_name="Other bank report",
            period="2026-09-30")
        self.assertNotIn("Official reported ROE (%)", result["metrics"])

    def test_uploaded_pdf_parser_requires_iso_period_and_valid_pdf(self):
        from bank_filing_collector import extract_uploaded_bank_filing
        with self.assertRaises(FilingRetrievalError):
            extract_uploaded_bank_filing(b"not a pdf", ticker="BBCA", source_name="test",
                period="2026-09-30")
        with self.assertRaises(FilingRetrievalError):
            extract_uploaded_bank_filing(b"%PDF-fake", ticker="BBCA", source_name="test",
                period="30-09-2026")

    def test_ignores_kpmm_heading_and_date_before_ratio_row(self):
        text = "LAPORAN PERHITUNGAN KPMM BANK UMUM KONVENSIONAL\nPT BANK RAKYAT INDONESIA\nTanggal 30 September 2026\nRasio KPMM (%) | 20,62 | 22,99"
        result = extract_metrics_from_pdf_text(text, source_url="https://bri.co.id/report.pdf",
            source_name="BRI Q3 report", period="2026-09-30")
        self.assertEqual(result["metrics"]["CAR (%)"]["value"], 20.62)

    def test_does_not_promote_tier_one_roe(self):
        result = extract_metrics_from_pdf_text("Return on Equity (ROE) 3) 22,11",
            source_url="https://bri.co.id/report.pdf", source_name="BRI report", period="2026-09-30")
        self.assertNotIn("Official reported ROE (%)", result["metrics"])

if __name__ == "__main__":
    unittest.main()
