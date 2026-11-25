"""Corporate-action and issuer-event calendar with explicit provenance."""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd

EVENT_TYPES = {"EARNINGS", "DIVIDEND_DECLARATION", "EX_DIVIDEND", "PAY_DATE", "STOCK_SPLIT", "RIGHTS_ISSUE", "OTHER"}
EVENT_STATUSES = {"CONFIRMED", "ESTIMATED", "CANCELLED"}


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
    if int(stale_after_days) < 0:
        raise ValueError("stale_after_days tidak boleh negatif.")
    unknown_types = sorted(set(frame["event_type"]) - EVENT_TYPES)
    unknown_status = sorted(set(frame["status"]) - EVENT_STATUSES)
    if unknown_types or unknown_status:
        raise ValueError("Event type/status tidak dikenal.")
    frame["event_date"] = pd.to_datetime(frame["event_date"], errors="coerce", utc=True)
    frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], errors="coerce", utc=True)
    if frame[["event_date", "retrieved_at"]].isna().any().any():
        raise ValueError("Tanggal event dan retrieved_at harus valid.")
    if "timezone" not in frame:
        frame["timezone"] = "UTC"
    if "source_url" not in frame:
        frame["source_url"] = ""
    if "details" not in frame:
        frame["details"] = ""
    if "amount" not in frame:
        frame["amount"] = None
    if "currency" not in frame:
        frame["currency"] = ""
    if "split_ratio" not in frame:
        frame["split_ratio"] = None
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame["split_ratio"] = pd.to_numeric(frame["split_ratio"], errors="coerce")
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
    frame["stale"] = frame["event_age_days"] > int(stale_after_days)
    duplicate_keys = ["ticker", "event_type", "event_date"]
    frame["duplicate_event"] = frame.duplicated(duplicate_keys, keep=False)
    frame = frame.sort_values(["event_date", "ticker"], kind="stable").reset_index(drop=True)
    warnings = []
    if frame["stale"].any():
        warnings.append(f"{int(frame['stale'].sum())} event memiliki metadata sumber kedaluwarsa.")
    if frame["future_retrieval_timestamp"].any():
        warnings.append("Ada retrieved_at yang berada di masa depan; metadata perlu diperiksa.")
    if frame["duplicate_event"].any():
        warnings.append(f"{int(frame['duplicate_event'].sum())} baris event duplikat perlu ditinjau.")
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
