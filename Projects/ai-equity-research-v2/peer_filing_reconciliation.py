"""Compare provider fundamentals with manually transcribed issuer-filing data."""
from __future__ import annotations

import math
from urllib.parse import urlsplit

import pandas as pd


FILING_METRICS = {
    "total_revenue": "totalRevenue",
    "ebitda": "ebitda",
    "total_debt": "totalDebt",
    "cash": "totalCash",
    "shares_outstanding": "sharesOutstanding",
    "book_value_per_share": "bookValue",
}


def reconcile_peer_filing_records(provider_records, filing_records, *, tolerance_pct: float = 5.0,
                                  period_tolerance_days: int = 90) -> dict:
    if not math.isfinite(float(tolerance_pct)) or tolerance_pct < 0:
        raise ValueError("Tolerance persentase harus finite dan tidak negatif.")
    if not isinstance(period_tolerance_days, int) or not 0 <= period_tolerance_days <= 366:
        raise ValueError("Period tolerance harus integer 0–366 hari.")
    provider = provider_records.copy() if isinstance(provider_records, pd.DataFrame) else pd.DataFrame(list(provider_records or []))
    filings = pd.DataFrame(filing_records.copy() if isinstance(filing_records, pd.DataFrame) else list(filing_records or []))
    required = {"ticker", "period_end", "currency", "source_name", "source_url", *FILING_METRICS.keys()}
    missing = sorted(required - set(filings.columns))
    if missing:
        raise ValueError("Kolom filing wajib: " + ", ".join(missing))
    if filings["ticker"].isna().any() or filings["ticker"].astype(str).str.strip().eq("").any():
        raise ValueError("Ticker filing wajib diisi.")
    filings["ticker"] = filings["ticker"].astype(str).str.strip().str.upper()
    if filings["ticker"].duplicated().any():
        raise ValueError("CSV filing harus memiliki satu baris terbaru per ticker.")
    if provider.empty is False:
        if "ticker" not in provider:
            raise ValueError("Provider records wajib memiliki kolom ticker.")
        provider["ticker"] = provider["ticker"].fillna("").astype(str).str.strip().str.upper()
        if provider["ticker"].eq("").any():
            raise ValueError("Ticker provider wajib diisi.")
        if provider["ticker"].duplicated().any():
            raise ValueError("Provider records tidak boleh memiliki ticker duplikat.")
    if filings["source_name"].isna().any() or filings["source_name"].astype(str).str.strip().eq("").any():
        raise ValueError("source_name wajib diisi.")
    if filings["currency"].isna().any():
        raise ValueError("Currency filing wajib diisi.")
    filings["currency"] = filings["currency"].astype(str).str.strip().str.upper()
    if not filings["currency"].str.fullmatch(r"[A-Z]{3}").all():
        raise ValueError("Currency filing harus berupa kode tiga huruf.")
    filings["source_url"] = filings["source_url"].fillna("").astype(str).str.strip()
    def valid_source_url(value):
        try:
            parsed = urlsplit(value)
            return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc) and "." in parsed.netloc
        except ValueError:
            return False
    if not filings["source_url"].map(valid_source_url).all():
        raise ValueError("source_url harus berupa URL http/https yang valid.")
    for metric in FILING_METRICS:
        original = filings[metric]
        numeric = pd.to_numeric(original, errors="coerce")
        invalid_text = original.notna() & original.astype(str).str.strip().ne("") & numeric.isna()
        if invalid_text.any():
            raise ValueError(f"Nilai filing {metric} harus numerik.")
        finite = numeric.dropna().map(lambda value: math.isfinite(float(value)))
        if not finite.all():
            raise ValueError(f"Nilai filing {metric} harus finite.")
        filings[metric] = numeric
    filings["period_end_parsed"] = pd.to_datetime(filings["period_end"], errors="coerce", format="mixed")
    if filings["period_end_parsed"].isna().any():
        raise ValueError("period_end filing harus berupa tanggal yang valid.")
    rows = []
    for record in provider.to_dict("records"):
        ticker = str(record.get("ticker") or "").strip().upper()
        match = filings.loc[filings["ticker"].eq(ticker)]
        if match.empty:
            for metric, provider_key in FILING_METRICS.items():
                rows.append({
                    "ticker": ticker, "metric": metric,
                    "provider_value": record.get(provider_key), "filing_value": None,
                    "variance_pct": None, "status": "FILING_MISSING",
                    "provider_period_end": record.get("fiscal_year_end"),
                    "filing_period_end": None, "provider_currency": record.get("currency"),
                    "filing_currency": None, "source_name": None, "source_url": None,
                })
            continue
        filing = match.iloc[0]
        provider_period = pd.to_datetime(record.get("fiscal_year_end"), errors="coerce", format="mixed")
        filing_period = filing["period_end_parsed"]
        period_gap = abs((provider_period - filing_period).days) if pd.notna(provider_period) else None
        provider_currency = str(record.get("currency") or "").upper()
        filing_currency = str(filing["currency"] or "").upper()
        period_ok = period_gap is not None and period_gap <= period_tolerance_days
        currency_ok = bool(provider_currency and provider_currency == filing_currency)
        for metric, provider_key in FILING_METRICS.items():
            provider_value = record.get(provider_key)
            filing_value = filing.get(metric)
            try:
                provider_number = float(provider_value) if provider_value is not None and pd.notna(provider_value) else None
                filing_number = float(filing_value) if filing_value is not None and pd.notna(filing_value) else None
            except (TypeError, ValueError):
                provider_number = filing_number = None
            variance = None
            if not period_ok and not currency_ok:
                status = "PERIOD_AND_CURRENCY_MISMATCH"
            elif not period_ok:
                status = "PERIOD_MISMATCH"
            elif not currency_ok:
                status = "CURRENCY_MISMATCH"
            elif provider_number is None:
                status = "PROVIDER_MISSING"
            elif filing_number is None:
                status = "FILING_MISSING"
            elif not math.isfinite(provider_number) or not math.isfinite(filing_number):
                status = "INVALID_VALUE"
            else:
                denominator = max(abs(provider_number), abs(filing_number), 1e-12)
                variance = abs(provider_number - filing_number) / denominator * 100.0
                status = "MATCH" if variance <= tolerance_pct else "MISMATCH"
            rows.append({
                "ticker": ticker, "metric": metric,
                "provider_value": provider_number, "filing_value": filing_number,
                "variance_pct": variance, "status": status,
                "provider_period_end": record.get("fiscal_year_end"),
                "filing_period_end": str(filing["period_end"]),
                "period_gap_days": period_gap,
                "provider_currency": provider_currency, "filing_currency": filing_currency,
                "source_name": str(filing["source_name"]),
                "source_url": str(filing["source_url"]),
            })
    details = pd.DataFrame(rows)
    counts = details["status"].value_counts().to_dict() if not details.empty else {}
    return {
        "metric_count": int(len(details)),
        "matched_count": int(counts.get("MATCH", 0)),
        "mismatch_count": int(counts.get("MISMATCH", 0)),
        "period_mismatch_count": int(counts.get("PERIOD_MISMATCH", 0) + counts.get("PERIOD_AND_CURRENCY_MISMATCH", 0)),
        "currency_mismatch_count": int(counts.get("CURRENCY_MISMATCH", 0) + counts.get("PERIOD_AND_CURRENCY_MISMATCH", 0)),
        "missing_count": int(counts.get("FILING_MISSING", 0) + counts.get("PROVIDER_MISSING", 0)),
        "status_counts": counts,
        "details": details,
        "limitations": (
            "Filing values are manually transcribed from the source URL supplied by the user; "
            "the application does not authenticate the document, audit accounting policies, normalize "
            "units, or certify the filing. Confirm units, consolidation scope, fiscal period and currency."
        ),
    }
