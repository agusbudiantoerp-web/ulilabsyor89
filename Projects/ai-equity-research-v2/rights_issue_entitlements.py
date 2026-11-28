"""Conservative rights-issue (HMETD) entitlement estimates.

The event_date is interpreted as the issuer-confirmed recording date. This
module estimates theoretical rights and full-exercise cash requirement only;
it never modifies shares, cash, or the portfolio ledger.
"""
from __future__ import annotations

import math
import pandas as pd

from corporate_action_calendar import normalize_corporate_events
from dividend_entitlements import estimate_shares_at_date


def estimate_rights_issue_entitlements(portfolio_events, corporate_events, *, initial_positions=None) -> dict:
    """Estimate HMETD from confirmed RIGHTS_ISSUE events.

    rights_ratio means rights offered per one existing share (e.g. 0.5
    means one right for every two shares). subscription_price is the
    cash price per right subscribed, in currency. The event date is the
    confirmed record date. Fractional rights are left unrounded and
    explicitly flagged for broker/issuer confirmation.
    """
    calendar = normalize_corporate_events(corporate_events)
    events = calendar["events"]
    warnings = list(calendar["warnings"])
    if events.empty:
        return {"entitlements": pd.DataFrame(), "warnings": ["Corporate action calendar belum memiliki event."], "method": "No estimate."}

    rows = []
    processed = set()
    rights_events = events.loc[events["event_type"].eq("RIGHTS_ISSUE")]
    for _, event in rights_events.iterrows():
        ticker = str(event["ticker"]).upper()
        record_date = pd.Timestamp(event["event_date"])
        if event["status"] != "CONFIRMED":
            warnings.append(f"{ticker}: event HMETD {record_date.date()} bukan CONFIRMED; estimasi dilewati.")
            continue
        if bool(event.get("conflicting_duplicate", False)):
            warnings.append(f"{ticker}: detail event HMETD {record_date.date()} bertentangan; estimasi dilewati.")
            continue
        ratio, price = event.get("rights_ratio"), event.get("subscription_price")
        raw_currency = event.get("currency")
        currency = "" if pd.isna(raw_currency) else str(raw_currency).strip().upper()
        if pd.isna(ratio) or pd.isna(price) or float(ratio) <= 0 or float(price) <= 0 or not currency:
            warnings.append(f"{ticker}: HMETD memerlukan rasio hak, harga pelaksanaan, dan mata uang yang valid.")
            continue
        duplicate_key = (ticker, record_date, float(ratio), float(price), currency)
        if duplicate_key in processed:
            continue
        processed.add(duplicate_key)
        shares = estimate_shares_at_date(portfolio_events, ticker, record_date, initial_positions)
        if shares is None:
            warnings.append(f"{ticker}: posisi pada record date tidak dapat dihitung karena tidak ada posisi awal atau histori BUY/SELL/SPLIT.")
            continue
        rights = shares * float(ratio)
        cost = rights * float(price)
        if not math.isfinite(rights) or not math.isfinite(cost):
            warnings.append(f"{ticker}: hasil estimasi HMETD tidak finite; estimasi dilewati.")
            continue
        fractional = not math.isclose(rights, round(rights), rel_tol=0.0, abs_tol=1e-9)
        rows.append({
            "ticker": ticker, "record_date": record_date,
            "shares_at_record_date_estimate": shares,
            "rights_per_existing_share": float(ratio),
            "estimated_rights_entitlement": rights,
            "subscription_price_per_right": float(price),
            "currency": currency,
            "cash_required_if_fully_exercised_estimate": cost,
            "fractional_rights_need_broker_confirmation": fractional,
            "status": "ESTIMATE_ONLY", "source": str(event["source"]),
        })
    result = pd.DataFrame(rows)
    if not result.empty:
        warnings.append("Estimasi HMETD tidak membulatkan hak pecahan dan tidak memperhitungkan aturan lot, rasio efektif, biaya, pajak, jadwal perdagangan/penebusan, penjualan hak, oversubscription, atau FX. Konfirmasi prospektus dan broker.")
    return {
        "entitlements": result, "warnings": warnings,
        "method": "Estimated rights = estimated shares at confirmed record date × rights ratio. Estimated full-exercise cash = estimated rights × subscription price. No portfolio cash or share balance is changed.",
    }
