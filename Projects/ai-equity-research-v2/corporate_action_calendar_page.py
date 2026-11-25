"""Manual/source-attributed corporate action calendar UI."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from corporate_action_calendar import normalize_corporate_events


def render_corporate_action_calendar() -> None:
    st.subheader("Corporate Actions & Event Calendar")
    st.caption("Catat event earnings, dividen, ex-date, pay-date, stock split dan rights issue dengan sumber dan status yang jelas.")
    st.warning("Event tidak diambil dari feed exchange/issuer secara otomatis. Masukkan data yang telah diverifikasi; kalender ini bukan daftar komprehensif.")
    key = "corporate_action_events"
    if key not in st.session_state:
        st.session_state[key] = pd.DataFrame(columns=[
            "ticker", "event_type", "event_date", "status", "source",
            "retrieved_at", "source_url", "timezone", "amount", "currency",
            "split_ratio", "details",
        ])
    with st.form("corporate_action_add_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("Ticker")
        event_type = c2.selectbox(
            "Event type", ["EARNINGS", "DIVIDEND_DECLARATION", "EX_DIVIDEND",
                           "PAY_DATE", "STOCK_SPLIT", "RIGHTS_ISSUE", "OTHER"]
        )
        event_date = c3.date_input("Tanggal event")
        c4, c5, c6 = st.columns(3)
        status = c4.selectbox("Status", ["CONFIRMED", "ESTIMATED", "CANCELLED"])
        source = c5.text_input("Sumber (issuer / BEI / provider)")
        retrieved = c6.date_input("Tanggal data diperoleh")
        c7, c8, c9 = st.columns(3)
        amount = c7.number_input("Nominal dividen (opsional)", min_value=0.0, value=0.0)
        currency = c8.text_input("Mata uang")
        split_ratio = c9.number_input("Rasio split (opsional)", min_value=0.0, value=0.0)
        source_url = st.text_input("URL dokumen sumber")
        timezone_name = st.text_input("Timezone event", "Asia/Jakarta")
        details = st.text_input("Catatan")
        submitted = st.form_submit_button("Tambahkan event")
    if submitted:
        row = {
            "ticker": ticker, "event_type": event_type, "event_date": str(event_date),
            "status": status, "source": source,
            "retrieved_at": pd.Timestamp(retrieved).tz_localize("UTC").isoformat(),
            "source_url": source_url, "timezone": timezone_name,
            "amount": amount if amount > 0 else None, "currency": currency,
            "split_ratio": split_ratio if split_ratio > 0 else None, "details": details,
        }
        candidate = pd.concat([st.session_state[key], pd.DataFrame([row])], ignore_index=True)
        try:
            normalized = normalize_corporate_events(candidate)
            st.session_state[key] = normalized["events"]
            st.success("Event ditambahkan.")
        except Exception as exc:
            st.error(f"Event tidak valid: {type(exc).__name__}: {exc}")
    events = st.session_state[key]
    if not events.empty:
        result = normalize_corporate_events(events)
        st.dataframe(result["events"], use_container_width=True, hide_index=True)
        for warning in result["warnings"]:
            st.warning(warning)
        st.caption(result["coverage_note"])
        st.download_button(
            "Unduh corporate actions CSV",
            result["events"].to_csv(index=False).encode("utf-8-sig"),
            file_name="corporate_action_calendar.csv", mime="text/csv",
        )
        if st.button("Hapus seluruh event sesi"):
            st.session_state[key] = pd.DataFrame(columns=events.columns)
            st.rerun()
    else:
        st.info("Belum ada event.")
