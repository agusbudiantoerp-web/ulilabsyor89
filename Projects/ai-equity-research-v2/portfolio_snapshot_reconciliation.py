"""Read-only comparison of a reconstructed portfolio ledger with a broker snapshot."""
from __future__ import annotations

from datetime import date, datetime
import math
import numbers

import pandas as pd


def _finite_nonnegative(value, label: str) -> float:
    if isinstance(value, bool) or type(value).__name__ in {"bool_", "bool"}:
        raise ValueError(f"{label} harus berupa angka finite dan tidak negatif.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} harus berupa angka finite dan tidak negatif.") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} harus berupa angka finite dan tidak negatif.")
    return number


def _calendar_date(value, label: str) -> date:
    if isinstance(value, (numbers.Number, bool)) or type(value).__name__ in {"bool_", "bool"}:
        raise ValueError(f"{label} tidak valid.")
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} tidak valid.") from exc
    if pd.isna(parsed):
        raise ValueError(f"{label} tidak valid.")
    return parsed.date()


def _positions_frame(positions) -> dict[str, float]:
    if isinstance(positions, pd.DataFrame):
        if not {"ticker", "shares"}.issubset(positions.columns):
            raise ValueError("Snapshot holdings wajib memiliki kolom ticker dan shares.")
        records = positions[["ticker", "shares"]].to_dict("records")
    elif isinstance(positions, dict):
        records = [{"ticker": ticker, "shares": shares} for ticker, shares in positions.items()]
    else:
        records = list(positions or [])
    normalized = {}
    for row in records:
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            raise ValueError("Ticker snapshot tidak boleh kosong.")
        if ticker in normalized:
            raise ValueError(f"Ticker snapshot duplikat: {ticker}.")
        normalized[ticker] = _finite_nonnegative(row.get("shares"), f"Shares {ticker}")
    return normalized


def reconcile_broker_snapshot(
    *,
    ledger_cash,
    ledger_positions,
    broker_cash,
    broker_positions,
    ledger_currency: str,
    broker_currency: str,
    ledger_as_of_date,
    broker_as_of_date,
    cash_tolerance: float = 0.0,
    shares_tolerance: float = 1e-8,
    date_tolerance_days: int = 0,
) -> dict:
    """Compare balances without mutating the ledger; never compare unlike currencies/dates."""
    cash_left = _finite_nonnegative(ledger_cash, "Ledger cash")
    cash_right = _finite_nonnegative(broker_cash, "Broker cash")
    cash_tol = _finite_nonnegative(cash_tolerance, "Cash tolerance")
    share_tol = _finite_nonnegative(shares_tolerance, "Shares tolerance")
    if isinstance(date_tolerance_days, bool) or not isinstance(date_tolerance_days, numbers.Integral) or not 0 <= date_tolerance_days <= 30:
        raise ValueError("Date tolerance harus integer 0–30.")
    ledger_ccy = str(ledger_currency or "").strip().upper()
    broker_ccy = str(broker_currency or "").strip().upper()
    if not ledger_ccy or not broker_ccy:
        raise ValueError("Mata uang ledger dan broker wajib diisi.")
    ledger_date = _calendar_date(ledger_as_of_date, "Tanggal ledger")
    broker_date = _calendar_date(broker_as_of_date, "Tanggal snapshot broker")
    date_gap = abs((ledger_date - broker_date).days)
    internal = _positions_frame(ledger_positions)
    broker = _positions_frame(broker_positions)
    comparable = ledger_ccy == broker_ccy and date_gap <= int(date_tolerance_days)
    warnings = []
    if ledger_ccy != broker_ccy:
        warnings.append(f"Mata uang berbeda ({ledger_ccy} vs {broker_ccy}); saldo kas dan nilai nominal tidak dibandingkan.")
    if date_gap > date_tolerance_days:
        warnings.append(f"Tanggal saldo berbeda {date_gap} hari; toleransi yang diizinkan {date_tolerance_days} hari.")
    warnings.extend([
        "Perbedaan dapat berasal dari transaksi belum settlement, corporate action, fractional shares/cash-in-lieu, biaya/pajak, atau FX.",
        "Snapshot harus memakai cut-off waktu dan definisi saldo kas yang sama dengan ledger.",
    ])
    rows = []
    if comparable:
        cash_diff = cash_right - cash_left
        rows.append({
            "item_type": "CASH", "ticker": "", "ledger_balance": cash_left,
            "broker_balance": cash_right, "difference": cash_diff,
            "status": "MATCH" if abs(cash_diff) <= cash_tol else "CASH_MISMATCH",
            "currency": ledger_ccy,
        })
        for ticker in sorted(set(internal) | set(broker)):
            left, right = internal.get(ticker, 0.0), broker.get(ticker, 0.0)
            diff = right - left
            if abs(diff) <= share_tol:
                status = "MATCH"
            elif ticker not in internal:
                status = "MISSING_IN_LEDGER"
            elif ticker not in broker:
                status = "MISSING_IN_BROKER"
            else:
                status = "QUANTITY_MISMATCH"
            rows.append({
                "item_type": "HOLDING", "ticker": ticker, "ledger_balance": left,
                "broker_balance": right, "difference": diff, "status": status,
                "currency": "",
            })
    else:
        cash_diff = None
        rows.append({
            "item_type": "CASH", "ticker": "", "ledger_balance": cash_left,
            "broker_balance": cash_right, "difference": None,
            "status": "NOT_COMPARABLE", "currency": "",
        })
        for ticker in sorted(set(internal) | set(broker)):
            rows.append({
                "item_type": "HOLDING", "ticker": ticker,
                "ledger_balance": internal.get(ticker, 0.0),
                "broker_balance": broker.get(ticker, 0.0),
                "difference": None, "status": "NOT_COMPARABLE", "currency": "",
            })
    details = pd.DataFrame(rows, columns=[
        "item_type", "ticker", "ledger_balance", "broker_balance",
        "difference", "status", "currency",
    ])
    counts = details["status"].value_counts().to_dict() if not details.empty else {}
    return {
        "comparable": comparable,
        "status": "COMPARABLE" if comparable else "NOT_COMPARABLE",
        "ledger_currency": ledger_ccy,
        "broker_currency": broker_ccy,
        "ledger_as_of_date": ledger_date.isoformat(),
        "broker_as_of_date": broker_date.isoformat(),
        "date_difference_days": date_gap,
        "cash_difference": cash_diff,
        "matched_count": int(counts.get("MATCH", 0)),
        "exception_count": int(sum(v for k, v in counts.items() if k != "MATCH")),
        "status_counts": counts,
        "details": details,
        "warnings": warnings,
        "read_only": True,
        "method": "Exact-date/currency-gated snapshot comparison; broker minus ledger; no ledger writes or automatic adjustments.",
    }


def classify_snapshot_exceptions(details: pd.DataFrame) -> dict:
    """Add deterministic priority and next-step guidance to snapshot comparison rows."""
    if not isinstance(details, pd.DataFrame):
        raise ValueError("Detail rekonsiliasi harus berupa DataFrame.")
    required = {"item_type", "ticker", "status", "difference"}
    if not required.issubset(details.columns):
        raise ValueError("Kolom detail rekonsiliasi tidak lengkap.")
    guidance = {
        "NOT_COMPARABLE": (
            "BLOCKER", 0, "Perbandingan terblokir",
            "Samakan mata uang, tanggal cut-off, dan definisi saldo sebelum menilai selisih."
        ),
        "MISSING_IN_LEDGER": (
            "CRITICAL", 1, "Holding broker tidak ada di ledger",
            "Periksa trade confirmation, transfer saham, corporate action, lalu catat melalui alur ledger yang sah."
        ),
        "MISSING_IN_BROKER": (
            "CRITICAL", 1, "Holding ledger tidak ada di broker",
            "Periksa penjualan, transfer keluar, corporate action, dan posisi settled broker."
        ),
        "QUANTITY_MISMATCH": (
            "WARNING", 2, "Jumlah saham berbeda",
            "Telusuri partial fill, settlement, split, rights, bonus, dan fractional shares."
        ),
        "CASH_MISMATCH": (
            "WARNING", 2, "Saldo kas berbeda",
            "Rekonsiliasi deposit/withdrawal, proceeds, biaya, pajak, dividen, FX, dan unsettled cash."
        ),
        "MATCH": (
            "MATCHED", 3, "Saldo cocok",
            "Tidak perlu tindakan; simpan snapshot dan bukti cut-off untuk audit."
        ),
    }
    result = details.copy()
    priorities, ranks, categories, actions = [], [], [], []
    for status in result["status"].astype(str):
        priority, rank, category, action = guidance.get(
            status, ("REVIEW", 2, "Status belum dikenali", "Tinjau detail secara manual sebelum mengambil tindakan.")
        )
        priorities.append(priority)
        ranks.append(rank)
        categories.append(category)
        actions.append(action)
    result["priority"] = priorities
    result["priority_rank"] = ranks
    result["exception_category"] = categories
    result["recommended_action"] = actions
    result = result.sort_values(
        ["priority_rank", "item_type", "ticker"], kind="stable"
    ).drop(columns=["priority_rank"]).reset_index(drop=True)
    counts = result["priority"].value_counts().to_dict()
    return {
        "details": result,
        "priority_counts": {key: int(counts.get(key, 0)) for key in ("BLOCKER", "CRITICAL", "WARNING", "REVIEW", "MATCHED")},
        "action_required_count": int(result["priority"].isin(["BLOCKER", "CRITICAL", "WARNING", "REVIEW"]).sum()),
        "read_only": True,
    }
