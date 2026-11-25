"""Safe CSV export helpers for untrusted market/provider text."""
from __future__ import annotations

import pandas as pd


def safe_spreadsheet_text(value):
    """Prefix formula-like text after whitespace or a leading Unicode BOM."""
    if not isinstance(value, str):
        return value
    probe = value.lstrip()
    if probe.startswith(chr(0xFEFF)):
        probe = probe[1:].lstrip()
    if probe.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value

def safe_csv_bytes(frame: pd.DataFrame, encoding: str = "utf-8-sig") -> bytes:
    """Serialize a dataframe while neutralizing spreadsheet formula-like text cells."""
    safe = frame.copy()
    safe.columns = [safe_spreadsheet_text(column) for column in safe.columns]
    for column in safe.columns:
        safe[column] = safe[column].map(safe_spreadsheet_text)
    return safe.to_csv(index=False).encode(encoding)
