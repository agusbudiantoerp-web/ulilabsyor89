"""Manual/source-attributed corporate action calendar UI."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from corporate_action_calendar import normalize_corporate_events
from corporate_event_store import create_event, delete_event, list_events


def render_corporate_action_calendar() -> None:
    owner = str(st.session_state.get("_auth_subject_id") or "").strip()
    if not owner:
        st.error("Identitas pengguna terverifikasi tidak tersedia.")
        return
    st.subheader("Corporate Actions & Event Calendar")
    st.caption("Catat event earnings, dividen, ex-date, pay-date, stock split dan rights issue dengan sumber dan status yang jelas.")
    st.warning("Event tidak diambil dari feed exchange/issuer secara otomatis. Masukkan data yang telah diverifikasi; kalender ini bukan daftar komprehensif.")
    st.markdown("**Impor event secara massal dari CSV**")
    uploaded = st.file_uploader(
        "CSV event (wajib: ticker,event_type,event_date,status,source,retrieved_at)",
        type=["csv"], key="corporate_event_csv_upload",
    )
    if uploaded is not None and st.button("Validasi dan simpan CSV", key="corporate_event_csv_import"):
        try:
            imported = pd.read_csv(uploaded)
            normalized_import = normalize_corporate_events(imported)
            records = normalized_import["events"].to_dict("records")
            saved_count = 0
            for record in records:
                create_event(owner, record)
                saved_count += 1
            st.success(f"{saved_count} event berhasil diimpor.")
            st.rerun()
        except Exception as exc:
            st.error(f"Impor CSV dibatalkan: {type(exc).__name__}: {exc}")

    try:
        stored_events = list_events(owner)
    except Exception as exc:
        st.error(f"Corporate event store tidak dapat dibaca ({type(exc).__name__}).")
        return
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
        try:
            normalized = normalize_corporate_events([row])
            event_id = create_event(owner, normalized["events"].iloc[0].to_dict())
            st.success(f"Event tersimpan permanen. ID: {event_id[:8]}")
            st.rerun()
        except Exception as exc:
            st.error(f"Event tidak valid: {type(exc).__name__}: {exc}")
    if stored_events:
        result = normalize_corporate_events(stored_events)
        st.dataframe(result["events"], use_container_width=True, hide_index=True)
        for warning in result["warnings"]:
            st.warning(warning)
        st.caption(result["coverage_note"])
        st.download_button(
            "Unduh corporate actions CSV",
            result["events"].to_csv(index=False).encode("utf-8-sig"),
            file_name="corporate_action_calendar.csv", mime="text/csv",
        )
        choices = {
            f"{item['ticker']} · {item['event_type']} · {item['event_date']} · {item['id'][:8]}": item["id"]
            for item in stored_events
        }
        selected = st.selectbox("Pilih event untuk dihapus", list(choices), key="corporate_event_delete_select")
        if st.button("Hapus event terpilih", key="corporate_event_delete"):
            try:
                if delete_event(owner, choices[selected]):
                    st.success("Event dihapus.")
                    st.rerun()
                else:
                    st.info("Event sudah tidak tersedia.")
            except Exception as exc:
                st.error(f"Event tidak dapat dihapus ({type(exc).__name__}).")
    else:
        st.info("Belum ada event.")
