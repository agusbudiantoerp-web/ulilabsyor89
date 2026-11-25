from io import BytesIO

import pandas as pd

from report_export_utils import safe_csv_bytes


def test_csv_export_escapes_formula_like_text_but_preserves_numeric_values():
    frame = pd.DataFrame({
        "=Ticker": ["=HYPERLINK(\"https://evil.example\",\"click\")", "  @SUM(1,1)", "BBCA"],
        "PnL": [-125.5, 25.0, 0.0],
        "Provider": ["+cmd|' /C calc'!A0", "-malicious-text", "Yahoo Finance"],
    })
    output = safe_csv_bytes(frame).decode("utf-8-sig")
    assert output.startswith("'=Ticker,")
    rows = list(pd.read_csv(BytesIO(safe_csv_bytes(frame))).itertuples(index=False, name=None))
    assert rows[0][0].startswith("'=")
    assert rows[1][0].startswith("'  @")
    assert rows[2][0] == "BBCA"
    assert rows[0][1] == -125.5
    assert rows[0][2].startswith("'+")
    assert rows[1][2].startswith("'-")


def test_csv_export_neutralizes_formula_after_utf8_bom_prefix():
    frame = pd.DataFrame({"Ticker": ["chr(0xFEFF) + "=HYPERLINK(\"https://evil.example\",\"x\")"]})
    rows = list(pd.read_csv(BytesIO(safe_csv_bytes(frame))).itertuples(index=False, name=None))
    assert rows[0][0].startswith("'" + chr(0xFEFF) + "=")
