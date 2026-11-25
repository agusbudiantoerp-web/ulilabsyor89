"""Investment thesis authoring and version history UI."""
from __future__ import annotations

import streamlit as st

from security_controls import record_audit_event, require_permission
from thesis_store import (create_thesis, get_thesis, list_theses, update_thesis,
                          request_review, list_reviews_for_thesis)
from research_run_store import get_run, list_runs


def _audit(owner, action, thesis_id, details):
    try:
        record_audit_event(
            owner, st.session_state.get("_auth_role"), action,
            "research_thesis", thesis_id, details=details,
        )
    except Exception as exc:
        st.warning(f"Audit event tidak berhasil dicatat ({type(exc).__name__}).")


def render_investment_thesis() -> None:
    owner = str(st.session_state.get("_auth_subject_id") or "").strip()
    role = st.session_state.get("_auth_role")
    require_permission(role, "manage_thesis")
    if not owner:
        st.error("Identitas pengguna terverifikasi tidak tersedia.")
        return
    st.subheader("Investment Thesis & Review Workflow")
    st.caption("Simpan tesis bull/base/bear, katalis, risiko, invalidation, target dan riwayat versi.")
    try:
        theses = list_theses(owner)
    except Exception as exc:
        st.error(f"Thesis store tidak dapat dibaca ({type(exc).__name__}). Detail koneksi disembunyikan.")
        return
    labels = {"— buat tesis baru —": None}
    labels.update({
        f"{item['ticker']} · {item['title']} · v{item['current_version']} · {item['status']}": item["id"]
        for item in theses
    })
    selected = st.selectbox("Pilih tesis", list(labels), key="thesis_select")
    thesis_id = labels[selected]
    existing = None
    if thesis_id:
        try:
            existing = get_thesis(owner, thesis_id)
        except Exception as exc:
            st.error(f"Tesis tidak dapat dimuat ({type(exc).__name__}).")
            return
    data = existing["content"] if existing else {}
    try:
        saved_runs = list_runs(owner, limit=100)
    except Exception:
        saved_runs = []
    run_labels = {"— tidak ditautkan —": ""}
    run_labels.update({
        "{} · {} · {} · {} · {}".format(item["created_at"], item["run_type"], item["market"], ", ".join(item["symbols"]), item["id"][:8]): item["id"]
        for item in saved_runs
    })
    existing_run_id = str(data.get("linked_research_run_id") or "")
    default_run_label = next((label for label, run_id in run_labels.items() if run_id == existing_run_id), "— tidak ditautkan —")
    with st.form("investment_thesis_editor"):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("Ticker", value=existing["ticker"] if existing else "")
        market = c2.selectbox("Market", ["IDX", "US"], index=0 if not existing or existing["market"] == "IDX" else 1)
        status_options = ["DRAFT", "ACTIVE", "WATCH", "CLOSED"]
        status = c3.selectbox(
            "Status", status_options,
            index=status_options.index(existing["status"]) if existing else 0,
        )
        title = st.text_input("Judul tesis", value=existing["title"] if existing else "")
        bull = st.text_area("Bull case", value=data.get("bull_case", ""))
        base = st.text_area("Base case", value=data.get("base_case", ""))
        bear = st.text_area("Bear case", value=data.get("bear_case", ""))
        c4, c5 = st.columns(2)
        catalysts = c4.text_area("Katalis (satu per baris)", value="\n".join(data.get("catalysts", [])))
        risks = c5.text_area("Risiko (satu per baris)", value="\n".join(data.get("risks", [])))
        invalidation = st.text_area("Thesis invalidation criteria", value=data.get("invalidation", ""))
        c6, c7, c8 = st.columns(3)
        target = c6.number_input("Target price", min_value=0.0, value=float(data.get("target_price") or 0.0))
        currency = c7.text_input("Mata uang target", value=data.get("currency", "IDR" if market == "IDX" else "USD"))
        review_date = c8.text_input("Review date (YYYY-MM-DD)", value=existing.get("review_date", "") if existing else "")
        linked_run_label = st.selectbox("Tautkan research/backtest run", list(run_labels), index=list(run_labels).index(default_run_label))
        submitted = st.form_submit_button("Simpan versi tesis", type="primary")
    if submitted:
        payload = {
            "bull_case": bull, "base_case": base, "bear_case": bear,
            "catalysts": [x.strip() for x in catalysts.splitlines() if x.strip()],
            "risks": [x.strip() for x in risks.splitlines() if x.strip()],
            "invalidation": invalidation, "target_price": target,
            "currency": currency.strip().upper(),
            "linked_research_run_id": run_labels[linked_run_label],
        }
        try:
            if existing:
                version = update_thesis(
                    owner, thesis_id, title=title, content=payload,
                    status=status, review_date=review_date, actor_id=owner,
                )
                _audit(owner, "THESIS_VERSION_UPDATE", thesis_id, {"version": version, "status": status})
                st.success(f"Versi tesis {version} berhasil disimpan.")
            else:
                new_id = create_thesis(
                    owner, ticker, market, title, payload, status=status,
                    review_date=review_date, actor_id=owner,
                )
                _audit(owner, "THESIS_CREATE", new_id, {"ticker": ticker.upper(), "status": status})
                st.success("Investment thesis berhasil dibuat.")
            st.rerun()
        except Exception as exc:
            st.error(f"Tesis tidak dapat disimpan: {type(exc).__name__}: {exc}")
    if existing:
        st.divider()
        st.markdown("**Riwayat versi dan review**")
        st.caption(f"Versi aktif: {existing['current_version']} · Dibuat: {existing['created_at']} · Diperbarui: {existing['updated_at']}")
        for version in reversed(existing["versions"]):
            with st.expander(f"Versi {version['version']} · {version['created_at']} · {version['actor_id']}"):
                st.json(version["content"])
        if existing.get("review_date"):
            st.info(f"Review berikutnya dijadwalkan: {existing['review_date']}")
        try:
            reviews = list_reviews_for_thesis(owner, thesis_id)
            if reviews:
                st.markdown("**Status review reviewer**")
                st.dataframe(reviews, use_container_width=True, hide_index=True)
            role_map = st.secrets.get("auth_roles", {})
            reviewer_choices = {
                str(principal): str(configured_role).lower()
                for principal, configured_role in role_map.items()
                if str(configured_role).lower() in {"portfolio_manager", "admin"}
                and str(principal) != owner
            } if hasattr(role_map, "items") else {}
            if reviewer_choices:
                reviewer = st.selectbox("Pilih reviewer (portfolio manager/admin)", list(reviewer_choices), key="thesis_reviewer_select")
                if st.button("Minta review versi tesis saat ini", key="thesis_request_review"):
                    review_id = request_review(owner, thesis_id, reviewer, actor_id=owner)
                    _audit(owner, "THESIS_REVIEW_REQUEST", review_id, {"thesis_id": thesis_id, "reviewer_id": reviewer})
                    st.success("Permintaan review berhasil dikirim.")
                    st.rerun()
            else:
                st.caption("Belum ada portfolio manager/admin lain pada auth_roles yang dapat dipilih sebagai reviewer.")
        except Exception as exc:
            st.warning(f"Workflow review belum dapat ditampilkan ({type(exc).__name__}).")
        linked_id = existing["content"].get("linked_research_run_id")
        if linked_id:
            try:
                linked_run = get_run(owner, linked_id)
                st.markdown("**Research run tertaut**")
                st.json({"run_id": linked_run["id"], "run_type": linked_run["run_type"], "market": linked_run["market"], "symbols": linked_run["symbols"], "created_at": linked_run["created_at"]})
            except Exception:
                st.warning("Research run tertaut sudah tidak tersedia atau tidak dapat diakses.")
