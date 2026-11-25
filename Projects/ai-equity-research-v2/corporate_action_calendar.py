"""Corporate-action and issuer-event calendar with explicit provenance."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import numbers
import pandas as pd

EVENT_TYPES = {"EARNINGS", "DIVIDEND_DECLARATION", "EX_DIVIDEND", "PAY_DATE", "STOCK_SPLIT", "RIGHTS_ISSUE", "OTHER"}
EVENT_STATUSES = {"CONFIRMED", "ESTIMATED", "CANCELLED"}


def _parse_event_calendar_dates(series: pd.Series) -> pd.Series:
    """Keep the issuer/exchange calendar date; do not shift it through UTC."""
    parsed = []
    for value in series:
        if isinstance(value, numbers.Number) or isinstance(value, bool) or type(value).__name__ in {"bool_", "bool"}:
            raise ValueError("Tanggal event dan retrieved_at harus berupa tanggal yang valid.")
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Tanggal event dan retrieved_at harus berupa tanggal yang valid.") from None
        if pd.isna(timestamp):
            raise ValueError("Tanggal event dan retrieved_at harus berupa tanggal yang valid.")
        parsed.append(pd.Timestamp(timestamp.date()))
    return pd.Series(parsed, index=series.index, dtype="datetime64[ns]")


def normalize_corporate_events(events, *, as_of=None, stale_after_days=30) -> dict:
    frame = events.copy() if isinstance(events, pd.DataFrame) else pd.DataFrame(list(events))
    required = {"ticker", "event_type", "event_date", "status", "source", "retrieved_at"}
    if not required.issubset(frame.columns):
        raise ValueError("Kolom event wajib: " + ", ".join(sorted(required - set(frame.columns))))
    if frame.empty:
        return {"events": frame, "event_count": 0, "warnings": []}
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["event_type"] = frame["event_type"].astype(str).str.upper().str.strip()
    frame["status"] = frame["status"].astype(str).str.upper().str.strip()
    if frame["ticker"].eq("").any() or frame["source"].astype(str).str.strip().eq("").any():
        raise ValueError("Ticker dan sumber event wajib diisi.")
    if (
        isinstance(stale_after_days, bool)
        or type(stale_after_days).__name__ in {"bool_", "bool"}
        or not isinstance(stale_after_days, numbers.Integral)
        or stale_after_days < 0
    ):
        raise ValueError("stale_after_days harus berupa bilangan bulat non-negatif.")
    stale_threshold = int(stale_after_days)
    unknown_types = sorted(set(frame["event_type"]) - EVENT_TYPES)
    unknown_status = sorted(set(frame["status"]) - EVENT_STATUSES)
    if unknown_types or unknown_status:
        raise ValueError("Event type/status tidak dikenal.")
    def _is_boolean(value):
        return isinstance(value, bool) or type(value).__name__ in {"bool_", "bool"}

    frame["event_date"] = _parse_event_calendar_dates(frame["event_date"])
    if frame["retrieved_at"].map(
        lambda value: isinstance(value, numbers.Number) or _is_boolean(value)
    ).any():
        raise ValueError("Tanggal event dan retrieved_at harus berupa tanggal yang valid.")
    frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], errors="coerce", utc=True)
    if frame[["event_date", "retrieved_at"]].isna().any().any():
        raise ValueError("Tanggal event dan retrieved_at harus valid.")
    if "timezone" not in frame:
        frame["timezone"] = "UTC"
    if "source_url" not in frame:
        frame["source_url"] = ""
    frame["source_url"] = frame["source_url"].fillna("").astype(str).str.strip()
    invalid_urls = frame["source_url"].ne("") & ~frame["source_url"].str.match(r"^https?://", case=False)
    if invalid_urls.any():
        raise ValueError("source_url harus berupa URL http/https jika diisi.")
    if "details" not in frame:
        frame["details"] = ""
    if "amount" not in frame:
        frame["amount"] = None
    if "currency" not in frame:
        frame["currency"] = ""
    if "split_ratio" not in frame:
        frame["split_ratio"] = None
    for column in ("amount", "split_ratio"):
        raw_values = frame[column]
        if raw_values.map(_is_boolean).any():
            raise ValueError(f"{column} harus berupa angka, bukan boolean.")
        converted = pd.to_numeric(raw_values, errors="coerce")
        supplied_invalid = raw_values.notna() & raw_values.astype(str).str.strip().ne("") & converted.isna()
        if supplied_invalid.any():
            raise ValueError(f"{column} harus berupa angka valid jika diisi.")
        frame[column] = converted
    for column in ("amount", "split_ratio"):
        supplied = frame[column].notna()
        if supplied.any() and not all(math.isfinite(float(value)) for value in frame.loc[supplied, column]):
            raise ValueError(f"{column} harus berupa angka finite.")
    if (frame["amount"].dropna() < 0).any() or (frame["split_ratio"].dropna() <= 0).any():
        raise ValueError("Amount tidak boleh negatif dan split ratio harus positif.")
    if frame.loc[frame["event_type"].eq("STOCK_SPLIT"), "split_ratio"].isna().any():
        raise ValueError("Split ratio wajib untuk event STOCK_SPLIT.")
    reference = pd.Timestamp(as_of or datetime.now(timezone.utc))
    if reference.tzinfo is None:
        reference = reference.tz_localize("UTC")
    else:
        reference = reference.tz_convert("UTC")
    frame["event_age_days"] = (reference - frame["retrieved_at"]).dt.total_seconds() / 86400
    frame["future_retrieval_timestamp"] = frame["event_age_days"] < 0
    frame["stale"] = frame["event_age_days"] > stale_threshold
    duplicate_keys = ["ticker", "event_type", "event_date"]
    frame["duplicate_event"] = frame.duplicated(duplicate_keys, keep=False)
    # Expose status semantics explicitly to downstream screens and exports.
    frame["status_is_confirmed"] = frame["status"].eq("CONFIRMED")
    frame["status_is_cancelled"] = frame["status"].eq("CANCELLED")
    frame["conflicting_duplicate"] = False
    for field in ("amount", "currency", "split_ratio"):
        if field not in frame.columns:
            continue
        conflict = frame.groupby(duplicate_keys, dropna=False)[field].transform(
            lambda values: values.nunique(dropna=True) > 1
        )
        frame["conflicting_duplicate"] |= frame["duplicate_event"] & conflict
    frame = frame.sort_values(["event_date", "ticker"], kind="stable").reset_index(drop=True)
    warnings = []
    if frame["stale"].any():
        warnings.append(f"{int(frame['stale'].sum())} event memiliki metadata sumber kedaluwarsa.")
    if frame["future_retrieval_timestamp"].any():
        warnings.append("Ada retrieved_at yang berada di masa depan; metadata perlu diperiksa.")
    if frame["duplicate_event"].any():
        warnings.append(f"{int(frame['duplicate_event'].sum())} baris event duplikat perlu ditinjau.")
    if frame["conflicting_duplicate"].any():
        warnings.append(f"{int(frame['conflicting_duplicate'].sum())} baris event duplikat memiliki detail yang saling bertentangan.")
    if (frame["status"] == "ESTIMATED").any():
        warnings.append("Sebagian tanggal merupakan estimasi provider, bukan konfirmasi issuer/exchange.")
    return {
        "events": frame,
        "event_count": int(len(frame)),
        "warnings": warnings,
        "coverage_note": (
            "Kalender hanya berisi event yang dimasukkan/tersedia dari sumber yang dicatat; "
            "ini bukan feed komprehensif seluruh issuer."
        ),
    }
