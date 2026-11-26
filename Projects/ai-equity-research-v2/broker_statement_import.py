"""Conservative CSV normalization for broker statements; never writes to the portfolio ledger."""
from __future__ import annotations

import csv
import io
import math
import re

import pandas as pd

from portfolio_cashflow import normalize_events


ALIASES = {
    "date": {"date", "trade date", "transaction date", "tanggal", "tgl", "tanggal transaksi", "trade_date"},
    "event_type": {"event type", "type", "transaction type", "side", "action", "jenis", "jenis transaksi", "tipe", "buy sell"},
    "amount": {"amount", "gross amount", "net amount", "total", "nilai", "nominal", "nilai transaksi", "jumlah", "transaction value"},
    "ticker": {"ticker", "symbol", "code", "stock", "kode saham", "saham", "emiten", "kode"},
    "quantity": {"quantity", "qty", "shares", "volume", "lot saham", "jumlah saham", "lembar", "lot"},
    "price": {"price", "unit price", "trade price", "harga", "harga transaksi", "harga per saham"},
    "notes": {"notes", "description", "remark", "remarks", "keterangan", "catatan"},
}
EVENT_ALIASES = {
    "BUY": "BUY", "B": "BUY", "BELI": "BUY", "PURCHASE": "BUY",
    "SELL": "SELL", "S": "SELL", "JUAL": "SELL", "SALE": "SELL",
    "DIVIDEND": "DIVIDEND", "DIV": "DIVIDEND", "DIVIDEN": "DIVIDEND",
    "FEE": "FEE", "COMMISSION": "FEE", "KOMISI": "FEE", "BIAYA": "FEE",
    "TAX": "TAX", "PAJAK": "TAX", "WITHHOLDING TAX": "TAX",
    "DEPOSIT": "DEPOSIT", "SETOR": "DEPOSIT", "SETORAN": "DEPOSIT",
    "WITHDRAWAL": "WITHDRAWAL", "TARIK": "WITHDRAWAL", "PENARIKAN": "WITHDRAWAL",
}


def _header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def _number(value: object, locale: str) -> float:
    if isinstance(value, bool):
        raise ValueError("Nilai numerik tidak boleh boolean.")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        raw = str(value).strip().replace(" ", "").replace("Rp", "").replace("IDR", "")
        raw = raw.replace("(", "-").replace(")", "")
        raw = re.sub(r"[^0-9,.-]", "", raw)
        if not raw or raw in {"-", ".", ","}:
            raise ValueError(f"Nilai numerik tidak valid: {value!r}")
        if locale == "id":
            raw = raw.replace(".", "").replace(",", ".")
        elif locale == "en":
            raw = raw.replace(",", "")
        elif locale == "auto":
            if "," in raw and "." in raw:
                decimal_sep = "," if raw.rfind(",") > raw.rfind(".") else "."
                thousands_sep = "." if decimal_sep == "," else ","
                raw = raw.replace(thousands_sep, "").replace(decimal_sep, ".")
            elif "," in raw:
                tail = raw.rsplit(",", 1)[1]
                raw = raw.replace(",", "") if len(tail) == 3 else raw.replace(",", ".")
            elif "." in raw:
                parts = raw.split(".")
                if len(parts) > 2 or len(parts[-1]) == 3:
                    raw = "".join(parts)
        else:
            raise ValueError("locale harus auto, id, atau en.")
        result = float(raw)
    if not math.isfinite(result):
        raise ValueError("Nilai numerik harus finite.")
    return result


def normalize_broker_statement(source, *, locale: str = "auto") -> dict:
    """Read CSV bytes/file-like/DataFrame and return canonical events plus import diagnostics.

    The function intentionally requires an explicit event amount. It does not
    infer net/gross amounts, fees, taxes, settlement dates, or missing trade fields.
    """
    if locale not in {"auto", "id", "en"}:
        raise ValueError("locale harus auto, id, atau en.")
    if isinstance(source, pd.DataFrame):
        frame = source.copy()
    else:
        if hasattr(source, "getvalue"):
            payload = source.getvalue()
        elif isinstance(source, (bytes, bytearray)):
            payload = bytes(source)
        elif isinstance(source, str):
            payload = source.encode("utf-8-sig")
        else:
            raise ValueError("Sumber harus berupa CSV, bytes, file upload, atau DataFrame.")
        try:
            sample = payload[:8192].decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            try:
                sample = payload[:8192].decode("cp1252")
            except UnicodeDecodeError as exc:
                raise ValueError("Encoding CSV tidak didukung; simpan sebagai UTF-8.") from exc
        # Detect from the header row only: decimal commas in data rows can
        # otherwise trick Sniffer into treating a semicolon CSV as one column.
        header_line = next((line for line in sample.splitlines() if line.strip()), "")
        delimiter_counts = {candidate: header_line.count(candidate) for candidate in (",", ";", "\\t", "|")}
        delimiter = max(delimiter_counts, key=delimiter_counts.get)
        if delimiter_counts[delimiter] == 0:
            delimiter = ","
        try:
            frame = pd.read_csv(io.BytesIO(payload), sep=delimiter, dtype=object, encoding="utf-8-sig")
        except UnicodeDecodeError:
            frame = pd.read_csv(io.BytesIO(payload), sep=delimiter, dtype=object, encoding="cp1252")
    if frame.empty:
        raise ValueError("CSV broker kosong.")
    mapping = {}
    normalized_headers = {_header(column): column for column in frame.columns}
    for target, aliases in ALIASES.items():
        matches = [original for normalized, original in normalized_headers.items()
                   if normalized in {_header(alias) for alias in aliases}]
        if len(matches) > 1:
            raise ValueError(f"Kolom {target} ambigu: {matches}. Sisakan satu kolom yang sesuai.")
        if matches:
            mapping[target] = matches[0]
    missing = [name for name in ("date", "event_type", "amount", "ticker") if name not in mapping]
    if missing:
        raise ValueError("Kolom wajib tidak terdeteksi: " + ", ".join(missing)
                         + ". Kolom yang didukung: date/tanggal, type/side/jenis, amount/nominal, ticker/symbol.")
    rows = []
    for row_number, row in frame.iterrows():
        raw_type = str(row[mapping["event_type"]]).strip().upper()
        event_type = EVENT_ALIASES.get(raw_type)
        if event_type is None:
            raise ValueError(f"Jenis transaksi baris {row_number + 2} tidak dikenali: {raw_type!r}.")
        date_value = str(row[mapping["date"]]).strip()
        if re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", date_value):
            parsed_date = pd.to_datetime(date_value, format="%Y-%m-%d", errors="coerce")
        else:
            parsed_date = pd.to_datetime(date_value, errors="coerce", dayfirst=True)
        if pd.isna(parsed_date):
            raise ValueError(f"Tanggal baris {row_number + 2} tidak valid: {date_value!r}.")
        amount = abs(_number(row[mapping["amount"]], locale))
        ticker = str(row[mapping["ticker"]]).strip().upper()
        if ticker.lower() in {"nan", "none"}:
            ticker = ""
        item = {"date": parsed_date.date().isoformat(), "event_type": event_type,
                "amount": amount, "ticker": ticker}
        for field in ("quantity", "price"):
            if field in mapping and pd.notna(row[mapping[field]]) and str(row[mapping[field]]).strip():
                item[field] = abs(_number(row[mapping[field]], locale))
        if "notes" in mapping and pd.notna(row[mapping["notes"]]):
            item["notes"] = str(row[mapping["notes"]])
        rows.append(item)
    canonical = normalize_events(rows)
    return {
        "events": canonical,
        "row_count": int(len(canonical)),
        "detected_columns": mapping,
        "delimiter": delimiter if not isinstance(source, pd.DataFrame) else "dataframe",
        "locale": locale,
        "warnings": [
            "Nominal dibaca sebagai nilai absolut; parser tidak menentukan apakah kolom amount merupakan gross atau net.",
            "Biaya, pajak, settlement date, corporate action, dan konversi mata uang tidak ditebak.",
            "Periksa preview sebelum membandingkan; hasil import tidak menulis ke ledger.",
        ],
    }
