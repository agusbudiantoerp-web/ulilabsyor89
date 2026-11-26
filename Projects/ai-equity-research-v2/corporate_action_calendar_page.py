"""Manual/source-attributed corporate action calendar UI."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from corporate_action_calendar import normalize_corporate_events
from corporate_event_store import create_event, create_events, delete_event, list_events
from security_controls import record_audit_event, require_permission
from report_export_utils import safe_csv_bytes
from portfolio_event_store import list_events as list_portfolio_events
from dividend_entitlements import estimate_dividend_entitlements
from rights_issue_entitlements import estimate_rights_issue_entitlements


def _audit_corporate_event(owner, role, action, event_id, details):
    try:
        record_audit_event(owner, role, action, "corporate_event", event_id, details=details)
    except Exception as exc:
        st.warning(f"Event tersimpan, tetapi audit event gagal dicatat ({type(exc).__name__}).")


def render_corporate_action_calendar() -> None:
    owner = str(st.session_state.get("_auth_subject_id") or "").strip()
    role = st.session_state.get("_auth_role")
    require_permission(role, "run_analysis")
    if not owner:
        st.error("Identitas pengguna terverifikasi tidak tersedia.")
        return
    st.subheader("Corporate Actions & Event Calendar")
    st.caption("Catat event earnings, deklarasi dividen, ex-date, record date, pay date, stock split dan rights issue dengan sumber dan status yang jelas.")
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
            created_ids = create_events(owner, records)
            saved_count = len(created_ids)
            _audit_corporate_event(owner, role, "CORPORATE_EVENT_BULK_IMPORT", "bulk:" + str(len(created_ids)), {"count": saved_count})
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
            "Event type", ["EARNINGS", "DIVIDEND_DECLARATION", "EX_DIVIDEND", "RECORD_DATE",
                           "PAY_DATE", "STOCK_SPLIT", "RIGHTS_ISSUE", "OTHER"]
        )
        event_date = c3.date_input("Tanggal event / record date HMETD")
        c4, c5, c6 = st.columns(3)
        status = c4.selectbox("Status", ["CONFIRMED", "ESTIMATED", "CANCELLED"])
        source = c5.text_input("Sumber (issuer / BEI / provider)")
        retrieved = c6.date_input("Tanggal data diperoleh")
        c7, c8, c9 = st.columns(3)
        amount = c7.number_input("Nominal dividen bruto per saham (opsional)", min_value=0.0, value=0.0, help="Untuk DIVIDEND_DECLARATION isi DPS bruto; untuk event lain gunakan nominal yang relevan atau kosongkan.")
        currency = c8.text_input("Mata uang")
        split_ratio = c9.number_input("Rasio split (opsional)", min_value=0.0, value=0.0)
        c10, c11 = st.columns(2)
        rights_ratio = c10.number_input("Rasio HMETD per saham lama", min_value=0.0, value=0.0, help="Contoh 0,5 berarti 1 hak untuk setiap 2 saham lama.")
        subscription_price = c11.number_input("Harga pelaksanaan per hak", min_value=0.0, value=0.0, help="Harga tebus per hak; mata uang mengikuti kolom Mata uang.")
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
            "split_ratio": split_ratio if split_ratio > 0 else None,
            "rights_ratio": rights_ratio if rights_ratio > 0 else None,
            "subscription_price": subscription_price if subscription_price > 0 else None,
            "details": details,
        }
        try:
            normalized = normalize_corporate_events([row])
            event_id = create_event(owner, normalized["events"].iloc[0].to_dict())
            _audit_corporate_event(owner, role, "CORPORATE_EVENT_CREATE", event_id, {"ticker": ticker.upper(), "event_type": event_type})
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
        st.markdown("**Estimasi hak dividen (tidak membuat arus kas)**")
        try:
            portfolio_rows = list_portfolio_events(owner)
            entitlement_result = estimate_dividend_entitlements(
                portfolio_rows, stored_events
            )
            entitlements = entitlement_result["entitlements"]
            if entitlements.empty:
                st.caption("Belum ada siklus dividen lengkap dengan deklarasi, ex-date, record date, dan pay date yang seluruhnya CONFIRMED.")
            else:
                st.dataframe(entitlements, use_container_width=True, hide_index=True)
                st.caption(entitlement_result["method"])
            for warning in entitlement_result["warnings"]:
                st.warning(warning)
            st.markdown("**Estimasi HMETD / rights issue (tidak mengubah saldo portofolio)**")
            rights_result = estimate_rights_issue_entitlements(portfolio_rows, stored_events)
            rights_table = rights_result["entitlements"]
            if rights_table.empty:
                st.caption("Belum ada event RIGHTS_ISSUE CONFIRMED dengan rasio, harga pelaksanaan, mata uang, dan posisi record date yang valid.")
            else:
                st.dataframe(rights_table, use_container_width=True, hide_index=True)
                st.caption(rights_result["method"])
            for warning in rights_result["warnings"]:
                st.warning(warning)
        except Exception as exc:
            st.error(f"Estimasi hak dividen tidak dapat dihitung ({type(exc).__name__}): {exc}")
        st.download_button(
            "Unduh corporate actions CSV",
            safe_csv_bytes(result["events"]),
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
                    _audit_corporate_event(owner, role, "CORPORATE_EVENT_DELETE", choices[selected], {})
                    st.success("Event dihapus.")
                    st.rerun()
                else:
                    st.info("Event sudah tidak tersedia.")
            except Exception as exc:
                st.error(f"Event tidak dapat dihapus ({type(exc).__name__}).")
    else:
        st.info("Belum ada event.")
