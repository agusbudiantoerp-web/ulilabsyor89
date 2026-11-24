"""Safe CSV export helpers for untrusted market/provider text."""
from __future__ import annotations

import pandas as pd


def safe_csv_bytes(frame: pd.DataFrame, encoding: str = "utf-8-sig") -> bytes:
    """Serialize a dataframe while neutralizing spreadsheet formula-like text cells."""
    safe = frame.copy()
    for column in safe.columns:
        safe[column] = safe[column].map(
            lambda value: "'" + value
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
            else value
        )
    return safe.to_csv(index=False).encode(encoding)
