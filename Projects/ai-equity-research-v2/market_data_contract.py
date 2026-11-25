"""Canonical provenance and freshness metadata for market-data frames.

The contract describes the data received; it does not certify provider accuracy.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

import pandas as pd

REQUIRED_OHLCV = ("Open", "High", "Low", "Close", "Volume")


def build_market_data_metadata(
    bars: pd.DataFrame,
    source_meta: dict[str, Any] | None = None,
    *,
    adjustment_mode: str = "provider_adjusted",
    retrieved_at: datetime | None = None,
    as_of: datetime | None = None,
    max_age_calendar_days: int = 5,
) -> dict[str, Any]:
    """Build a serializable provenance record and explicit quality flags."""
    if bars is None or bars.empty:
        raise ValueError("Data harga kosong; provenance tidak dapat dibuat.")
    meta = dict(source_meta or {})
    retrieved = retrieved_at or datetime.now(timezone.utc)
    reference = as_of or retrieved
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    missing = [name for name in REQUIRED_OHLCV if name not in bars.columns]
    checks: list[dict[str, str]] = []
    if missing:
        checks.append({"severity": "ERROR", "code": "MISSING_COLUMNS",
                       "message": "Kolom OHLCV hilang: " + ", ".join(missing)})
        last_bar = None
        age_days = None
    else:
        frame = bars.loc[:, list(REQUIRED_OHLCV)].apply(pd.to_numeric, errors="coerce")
        invalid_rows = int(frame.isna().any(axis=1).sum())
        if invalid_rows:
            checks.append({"severity": "ERROR", "code": "NON_NUMERIC_OHLCV",
                           "message": f"{invalid_rows} bar memiliki nilai OHLCV kosong/non-numerik."})
        nonfinite = int((~frame.map(lambda value: math.isfinite(float(value)) if pd.notna(value) else False)).any(axis=1).sum())
        if nonfinite:
            checks.append({"severity": "ERROR", "code": "NON_FINITE_OHLCV",
                           "message": f"{nonfinite} bar memiliki nilai non-finite."})
        invalid_price = int((frame[["Open", "High", "Low", "Close"]] <= 0).any(axis=1).sum())
        if invalid_price:
            checks.append({"severity": "ERROR", "code": "NON_POSITIVE_PRICE",
                           "message": f"{invalid_price} bar memiliki harga nol/negatif."})
        negative_volume = int((frame["Volume"] < 0).sum())
        if negative_volume:
            checks.append({"severity": "ERROR", "code": "NEGATIVE_VOLUME",
                           "message": f"{negative_volume} bar memiliki volume negatif."})
        bad_ohlc = (
            (frame["High"] < frame[["Open", "Close", "Low"]].max(axis=1))
            | (frame["Low"] > frame[["Open", "Close", "High"]].min(axis=1))
        ).fillna(False)
        if int(bad_ohlc.sum()):
            checks.append({"severity": "ERROR", "code": "INVALID_OHLC_RELATION",
                           "message": f"{int(bad_ohlc.sum())} bar memiliki relasi OHLC tidak valid."})
        duplicate_dates = int(pd.Index(bars.index).duplicated().sum())
        if duplicate_dates:
            checks.append({"severity": "WARNING", "code": "DUPLICATE_DATES",
                           "message": f"{duplicate_dates} tanggal duplikat."})
        dates = pd.to_datetime(bars.index)
        if getattr(dates, "tz", None) is not None:
            dates = dates.tz_localize(None)
        last_bar = dates.max().date().isoformat()
        age_days = max(0, (reference.date() - dates.max().date()).days)
        if age_days > int(max_age_calendar_days):
            checks.append({"severity": "WARNING", "code": "STALE_DATA",
                           "message": f"Bar terakhir berumur {age_days} hari kalender."})
        if dates.max().date() > reference.date():
            checks.append({"severity": "ERROR", "code": "FUTURE_BAR",
                           "message": "Tanggal bar terakhir berada di masa depan."})
    if not checks:
        checks.append({"severity": "INFO", "code": "BASIC_CHECKS_PASSED",
                       "message": "Pemeriksaan dasar OHLCV lolos; verifikasi sumber tetap diperlukan."})
    status = "FAIL" if any(item["severity"] == "ERROR" for item in checks) else (
        "WARNING" if any(item["severity"] == "WARNING" for item in checks) else "PASS"
    )
    return {
        "source": str(meta.get("source") or "unknown"),
        "source_ticker": str(meta.get("ticker") or ""),
        "market": str(meta.get("market") or ""),
        "exchange": str(meta.get("exchange") or ""),
        "currency": str(meta.get("currency") or "unknown"),
        "adjustment_mode": str(adjustment_mode),
        "price_basis": "adjusted_ohlc" if adjustment_mode == "auto_adjusted" else "provider_reported",
        "retrieved_at": retrieved.astimezone(timezone.utc).isoformat(),
        "bar_date": last_bar,
        "bar_count": int(len(bars)),
        "age_calendar_days": age_days,
        "quality_status": status,
        "quality_checks": checks,
        "corporate_action_note": (
            "Harga disesuaikan oleh provider sesuai adjustment_mode; kelengkapan historis corporate actions "
            "dan point-in-time universe tidak diverifikasi secara independen."
        ),
    }
