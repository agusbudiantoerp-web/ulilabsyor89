"""Administrator-only security and audit console."""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from ui_theme import render_page_hero

from daily_signal_storage import backend_name as signal_backend_name
from portfolio_store import backend_name as portfolio_backend_name
from research_run_store import backend_name as research_backend_name
from database_health import check_postgres_health, initialize_required_postgres_schema
from report_export_utils import safe_csv_bytes
from security_controls import (
    ROLE_PERMISSIONS,
    list_audit_events,
    normalize_role,
    record_audit_event,
    require_permission,
    verify_audit_chain,
)


def _record_admin_audit_safely(
    actor_id: str, actor_role: str, action: str, resource_type: str,
    details: dict, path: str | None = None,
) -> None:
    try:
        record_audit_event(
            actor_id, actor_role, action, resource_type,
            details=details, path=path,
        )
    except Exception as exc:
        st.warning(
            f"Event audit tidak berhasil dicatat ({type(exc).__name__}). "
            "Detail error disembunyikan."
        )


def render_security_audit(identity: dict, secrets) -> None:
    """Render audit visibility and role-map review for administrators only."""
    actor_id = str(identity.get("subject_id") or "").strip()
    actor_role = str(identity.get("role") or "").strip()
    require_permission(actor_role, "view_audit")
    if not actor_id:
        raise PermissionError("Identitas administrator tidak tersedia.")

    render_page_hero("INVESTMENT GOVERNANCE CENTER", "Security & Audit Console", "Administrator controls for role mapping, access visibility, audit integrity and operational diagnostics.", "ACCESS CONTROL  ·  AUDIT INTEGRITY  ·  ADMIN")
    st.caption("Konsol administrator untuk meninjau pemetaan role dan jejak audit sistem.")
    audit_path = secrets.get("audit_db_path")
    audit_path_value = str(audit_path) if audit_path else None
    try:
        record_audit_event(
            actor_id,
            actor_role,
            "AUDIT_VIEW",
            "audit_log",
            details={"view": "security_audit_console"},
            path=audit_path_value,
        )
        events = list_audit_events(limit=500, path=audit_path_value)
    except Exception as exc:
        st.error(
            "Audit console dikunci karena penyimpanan audit tidak dapat diakses "
            f"({type(exc).__name__}). Detail koneksi dan error disembunyikan."
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

    st.subheader("Matriks izin per role")
    st.dataframe(pd.DataFrame([
        {"Role": role, "Permissions": ", ".join(sorted(permissions))}
        for role, permissions in ROLE_PERMISSIONS.items()
    ]), use_container_width=True, hide_index=True)

    st.subheader("Konfigurasi penyimpanan")
    database_settings = secrets.get("database", {})
    database_url_configured = bool(
        os.getenv("DATABASE_URL")
        or os.getenv("CLOUD_DATABASE_URL")
        or secrets.get("DATABASE_URL")
        or secrets.get("CLOUD_DATABASE_URL")
        or (database_settings.get("url") if hasattr(database_settings, "get") else None)
    )
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
        "Indikator backend di atas membaca konfigurasi. Gunakan pemeriksaan berikut untuk "
        "menguji koneksi PostgreSQL, tabel wajib, dan hak akses tanpa menulis data."
    )
    st.caption("Jika database baru dibuat, administrator dapat menjalankan migrasi skema idempoten terlebih dahulu.")
    confirm_schema = st.checkbox(
        "Saya menyetujui pembuatan/migrasi tabel aplikasi pada PostgreSQL yang dikonfigurasi.",
        key="confirm_postgres_schema_initialize",
    )
    if st.button(
        "Siapkan skema PostgreSQL",
        key="initialize_postgres_schema",
        disabled=not confirm_schema,
    ):
        try:
            prepared = initialize_required_postgres_schema(
                secrets, actor_id=actor_id, actor_role=actor_role,
                audit_path=audit_path_value,
            )
            if prepared.get("ok"):
                st.success("Skema PostgreSQL berhasil disiapkan dan pemeriksaan dasar lulus.")
            else:
                st.warning("Skema telah diproses, tetapi masih ada tabel, hak akses, atau kebijakan RLS yang perlu diperiksa.")
                if prepared.get("missing_tables"):
                    st.write("Tabel belum tersedia:", ", ".join(prepared["missing_tables"]))
                if prepared.get("privilege_issues"):
                    st.dataframe(pd.DataFrame(prepared["privilege_issues"]), use_container_width=True, hide_index=True)
                if prepared.get("rls_issues"):
                    st.error("Isolasi database belum memenuhi syarat produksi. Aktifkan RLS + FORCE RLS dan gunakan role aplikasi non-owner tanpa SUPERUSER/BYPASSRLS.")
                    st.dataframe(pd.DataFrame(prepared["rls_issues"]), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Inisialisasi skema gagal: {type(exc).__name__}. Detail koneksi disembunyikan.")
    if st.button("Uji koneksi, skema & hak akses PostgreSQL", key="database_health_check"):
        health = check_postgres_health(secrets)
        if health.get("connected") and health.get("ok"):
            st.success(health["message"])
        elif health.get("connected"):
            st.warning(health["message"])
        else:
            st.error(health["message"])
        if health.get("connected"):
            health_cols = st.columns(3)
            health_cols[0].metric("Database", health.get("database", "N/A"))
            health_cols[1].metric("Schema", health.get("schema", "N/A"))
            health_cols[2].metric("Latency", f"{health.get('latency_ms', 0)} ms")
            if health.get("missing_tables"):
                st.warning("Tabel belum tersedia: " + ", ".join(health["missing_tables"]))
            if health.get("privilege_issues"):
                st.dataframe(pd.DataFrame(health["privilege_issues"]), use_container_width=True, hide_index=True)
            if health.get("application_role"):
                st.json(health["application_role"])
            if health.get("rls_issues"):
                st.error("RLS belum aman untuk produksi. Semua tabel tenant harus mengaktifkan dan memaksa RLS; role aplikasi tidak boleh menjadi pemilik tabel, SUPERUSER, atau BYPASSRLS.")
                st.dataframe(pd.DataFrame(health["rls_issues"]), use_container_width=True, hide_index=True)
            if not health.get("missing_tables") and not health.get("privilege_issues") and not health.get("rls_issues"):
                st.caption(f"Versi PostgreSQL: {health.get('server_version', 'N/A')}")
        _audit_event = {
            "connected": bool(health.get("connected")),
            "schema_ok": bool(health.get("ok")),
            "missing_table_count": len(health.get("missing_tables", [])),
            "privilege_issue_count": len(health.get("privilege_issues", [])),
            "rls_issue_count": len(health.get("rls_issues", [])),
            "application_role_restricted": bool(
                health.get("application_role")
                and not health["application_role"].get("superuser")
                and not health["application_role"].get("bypass_rls")
            ),
        }
        try:
            record_audit_event(
                actor_id, actor_role, "DATABASE_HEALTH_CHECK", "database",
                details=_audit_event, path=audit_path_value,
            )
        except Exception as exc:
            st.warning(f"Hasil pemeriksaan tidak tercatat ke audit log: {type(exc).__name__}.")

    st.subheader("Integritas audit log")
    if st.button("Verifikasi hash chain audit", type="primary", key="audit_verify_chain"):
        try:
            result = verify_audit_chain(path=audit_path_value)
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
            st.error(f"Verifikasi gagal ({type(exc).__name__}). Detail koneksi dan error disembunyikan.")
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
        filter_col1, filter_col2 = st.columns(2)
        actor_values = ["Semua pengguna"] + sorted(frame["actor_id"].astype(str).unique().tolist())
        action_values = ["Semua aksi"] + sorted(frame["action"].astype(str).unique().tolist())
        selected_actor = filter_col1.selectbox("Filter pengguna", actor_values, key="audit_actor_filter")
        selected_action = filter_col2.selectbox("Filter aksi", action_values, key="audit_action_filter")
        search_text = st.text_input("Cari resource atau detail", key="audit_search_text").strip().lower()
        filtered = frame.copy()
        if selected_actor != "Semua pengguna":
            filtered = filtered[filtered["actor_id"].astype(str) == selected_actor]
        if selected_action != "Semua aksi":
            filtered = filtered[filtered["action"].astype(str) == selected_action]
        if search_text:
            searchable = (
                filtered["resource_type"].astype(str) + " "
                + filtered["resource_id"].astype(str) + " "
                + filtered["details_json"].astype(str)
            ).str.lower()
            filtered = filtered[searchable.str.contains(search_text, regex=False, na=False)]
        st.caption(f"Menampilkan {len(filtered)} dari {len(frame)} event terbaru.")
        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.download_button(
            "Unduh audit log CSV",
            safe_csv_bytes(filtered),
            file_name="ai_equity_research_audit_log.csv",
            mime="text/csv",
            on_click=lambda: _record_admin_audit_safely(
                actor_id, actor_role, "AUDIT_EXPORT", "audit_log",
                {"format": "csv", "event_count": len(filtered)},
                path=audit_path_value,
            ),
        )
    else:
        st.info("Belum ada event audit tersimpan.")
