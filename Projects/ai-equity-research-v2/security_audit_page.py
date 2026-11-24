"""Administrator-only security and audit console."""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from daily_signal_storage import backend_name as signal_backend_name
from portfolio_store import backend_name as portfolio_backend_name
from research_run_store import backend_name as research_backend_name
from security_controls import (
    list_audit_events,
    normalize_role,
    record_audit_event,
    require_permission,
    verify_audit_chain,
)


def render_security_audit(identity: dict, secrets) -> None:
    """Render audit visibility and role-map review for administrators only."""
    actor_id = str(identity.get("subject_id") or "").strip()
    actor_role = str(identity.get("role") or "").strip()
    require_permission(actor_role, "view_audit")
    if not actor_id:
        raise PermissionError("Identitas administrator tidak tersedia.")

    st.header("Security & Audit Console")
    st.caption("Konsol administrator untuk meninjau pemetaan role dan jejak audit sistem.")
    try:
        record_audit_event(
            actor_id,
            actor_role,
            "AUDIT_VIEW",
            "audit_log",
            details={"view": "security_audit_console"},
        )
        events = list_audit_events(limit=500)
    except Exception as exc:
        st.error(
            "Audit console dikunci karena penyimpanan audit tidak dapat diakses: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    roles = secrets.get("auth_roles", {})
    role_rows = []
    if hasattr(roles, "items"):
        for principal, configured_role in roles.items():
            try:
                normalized = normalize_role(str(configured_role))
                status = "Aktif"
            except ValueError:
                normalized = str(configured_role)
                status = "Role tidak valid"
            role_rows.append({
                "OIDC principal (issuer|sub)": str(principal),
                "Role": normalized,
                "Status": status,
            })

    st.subheader("Pemetaan akses pengguna")
    st.caption(
        "Role bersumber dari Streamlit Secrets [auth_roles]. Perubahan role dilakukan "
        "oleh administrator pada Secrets, bukan melalui browser."
    )
    if role_rows:
        st.dataframe(pd.DataFrame(role_rows), use_container_width=True, hide_index=True)
    else:
        st.warning("Belum ada pemetaan role yang dapat ditampilkan.")

    st.subheader("Konfigurasi penyimpanan")
    database_settings = secrets.get("database", {})
    database_url_configured = bool(
        os.getenv("DATABASE_URL")
        or os.getenv("CLOUD_DATABASE_URL")
        or secrets.get("DATABASE_URL")
        or secrets.get("CLOUD_DATABASE_URL")
        or (database_settings.get("url") if hasattr(database_settings, "get") else None)
    )
    audit_path = secrets.get("audit_db_path")
    storage_cols = st.columns(4)
    storage_cols[0].metric("Daily signals", signal_backend_name())
    storage_cols[1].metric("Portfolio books", portfolio_backend_name())
    storage_cols[2].metric("Research runs", research_backend_name())
    storage_cols[3].metric(
        "Audit events",
        "SQLite" if audit_path else ("PostgreSQL" if database_url_configured else "SQLite"),
    )
    if not database_url_configured:
        st.warning("DATABASE_URL belum dikonfigurasi. Penyimpanan cloud menggunakan fallback SQLite dan dapat bersifat sementara.")
    st.caption(
        "Panel ini hanya membaca jalur backend berdasarkan konfigurasi; belum menguji koneksi, "
        "hak akses database, migrasi, backup, atau pemulihan."
    )

    st.subheader("Integritas audit log")
    if st.button("Verifikasi hash chain audit", type="primary", key="audit_verify_chain"):
        try:
            result = verify_audit_chain()
            if result.get("valid"):
                st.success(
                    f"Hash chain valid. {result.get('checked_events', 0)} event diperiksa."
                )
            else:
                st.error(
                    "Integritas hash chain gagal pada event "
                    f"{result.get('failed_event_id')}."
                )
        except Exception as exc:
            st.error(f"Verifikasi gagal: {type(exc).__name__}: {exc}")
    st.warning(
        "Hash chain bersifat tamper-evident, bukan penyimpanan WORM. Administrator "
        "database dengan hak tulis masih dapat mengubah seluruh rantai; gunakan "
        "penyimpanan append-only eksternal untuk retensi audit tingkat produksi."
    )

    st.subheader("Riwayat audit terbaru")
    st.caption("Maksimal 500 event terbaru. Kredensial tidak ditampilkan.")
    if events:
        frame = pd.DataFrame(events)
        visible = [
            "id", "occurred_at", "actor_id", "actor_role", "action",
            "resource_type", "resource_id", "details_json", "event_hash",
        ]
        frame = frame[[column for column in visible if column in frame.columns]]
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Unduh audit log CSV",
            frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="ai_equity_research_audit_log.csv",
            mime="text/csv",
        )
    else:
        st.info("Belum ada event audit tersimpan.")
