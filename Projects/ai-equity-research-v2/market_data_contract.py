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
    try:
        max_age = int(max_age_calendar_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("Batas umur data harus berupa bilangan bulat non-negatif.") from exc
    if max_age < 0:
        raise ValueError("Batas umur data harus berupa bilangan bulat non-negatif.")

    meta = dict(source_meta or {})
    retrieved = retrieved_at or datetime.now(timezone.utc)
    reference = as_of or datetime.now(timezone.utc)
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference_date = reference.astimezone(timezone.utc).date()

    missing = [name for name in REQUIRED_OHLCV if name not in bars.columns]
    checks: list[dict[str, str]] = []
    last_bar = None
    age_days = None

    # Validate the index independently from OHLCV so malformed timestamps are
    # visible rather than causing an opaque .date() / max() failure downstream.
    parsed_dates = pd.DatetimeIndex([
        pd.to_datetime(value, errors="coerce", utc=True) for value in bars.index
    ])
    invalid_dates = int(parsed_dates.isna().sum())
    valid_dates = parsed_dates[~parsed_dates.isna()]
    if invalid_dates:
        checks.append({
            "severity": "ERROR", "code": "INVALID_BAR_DATES",
            "message": f"{invalid_dates} bar memiliki indeks tanggal yang tidak valid.",
        })
    if len(valid_dates):
        last_date = valid_dates.max().date()
        last_bar = last_date.isoformat()
        age_days = max(0, (reference_date - last_date).days)
        if int(valid_dates.duplicated().sum()):
            checks.append({
                "severity": "WARNING", "code": "DUPLICATE_DATES",
                "message": f"{int(valid_dates.duplicated().sum())} tanggal duplikat.",
            })
        if not valid_dates.is_monotonic_increasing:
            checks.append({
                "severity": "WARNING", "code": "UNSORTED_DATES",
                "message": "Urutan bar tidak kronologis; urutkan berdasarkan tanggal sebelum analisis.",
            })
        if age_days > max_age:
            checks.append({
                "severity": "WARNING", "code": "STALE_DATA",
                "message": f"Bar terakhir berumur {age_days} hari kalender.",
            })
        if last_date > reference_date:
            checks.append({
                "severity": "ERROR", "code": "FUTURE_BAR",
                "message": "Tanggal bar terakhir berada di masa depan.",
            })
    else:
        checks.append({
            "severity": "ERROR", "code": "NO_VALID_BAR_DATES",
            "message": "Tidak ada tanggal bar yang dapat dibaca.",
        })

    if missing:
        checks.append({
            "severity": "ERROR", "code": "MISSING_COLUMNS",
            "message": "Kolom OHLCV hilang: " + ", ".join(missing),
        })
    else:
        frame = bars.loc[:, list(REQUIRED_OHLCV)].apply(pd.to_numeric, errors="coerce")
        invalid_rows = int(frame.isna().any(axis=1).sum())
        if invalid_rows:
            checks.append({
                "severity": "ERROR", "code": "NON_NUMERIC_OHLCV",
                "message": f"{invalid_rows} bar memiliki nilai OHLCV kosong/non-numerik.",
            })
        nonfinite = sum(
            1 for row in frame.to_numpy() for value in row
            if pd.notna(value) and not math.isfinite(float(value))
        )
        if nonfinite:
            checks.append({
                "severity": "ERROR", "code": "NON_FINITE_OHLCV",
                "message": f"{nonfinite} bar memiliki nilai non-finite.",
            })
        invalid_price = int((frame[["Open", "High", "Low", "Close"]] <= 0).any(axis=1).sum())
        if invalid_price:
            checks.append({
                "severity": "ERROR", "code": "NON_POSITIVE_PRICE",
                "message": f"{invalid_price} bar memiliki harga nol/negatif.",
            })
        negative_volume = int((frame["Volume"] < 0).sum())
        if negative_volume:
            checks.append({
                "severity": "ERROR", "code": "NEGATIVE_VOLUME",
                "message": f"{negative_volume} bar memiliki volume negatif.",
            })
        bad_ohlc = (
            (frame["High"] < frame[["Open", "Close", "Low"]].max(axis=1))
            | (frame["Low"] > frame[["Open", "Close", "High"]].min(axis=1))
        ).fillna(False)
        if int(bad_ohlc.sum()):
            checks.append({
                "severity": "ERROR", "code": "INVALID_OHLC_RELATION",
                "message": f"{int(bad_ohlc.sum())} bar memiliki relasi OHLC tidak valid.",
            })

    if not checks:
        checks.append({
            "severity": "INFO", "code": "BASIC_CHECKS_PASSED",
            "message": "Pemeriksaan dasar OHLCV lolos; verifikasi sumber tetap diperlukan.",
        })
    status = "FAIL" if any(item["severity"] == "ERROR" for item in checks) else (
        "WARNING" if any(item["severity"] == "WARNING" for item in checks) else "PASS"
    )
    try:
        cache_age = float(meta.get("cache_age_seconds", 0.0))
    except (TypeError, ValueError):
        cache_age = float("nan")
    if not math.isfinite(cache_age) or cache_age < 0:
        cache_age = 0.0
        checks.append({
            "severity": "WARNING", "code": "INVALID_CACHE_AGE",
            "message": "Umur cache tidak valid; metadata cache dinormalisasi menjadi nol.",
        })
        if status == "PASS":
            status = "WARNING"

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
        "cache_hit": bool(meta.get("cache_hit", False)),
        "cache_age_seconds": cache_age,
        "quality_status": status,
        "quality_checks": checks,
        "corporate_action_note": (
            "Harga disesuaikan oleh provider sesuai adjustment_mode; kelengkapan historis corporate actions "
            "dan point-in-time universe tidak diverifikasi secara independen."
        ),
    }
