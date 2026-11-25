"""Reviewer inbox for assigned investment thesis versions."""
from __future__ import annotations

import streamlit as st

from security_controls import record_audit_event, require_permission
from thesis_store import decide_review, get_review_for_reviewer, list_reviews_for_reviewer


def render_thesis_reviews() -> None:
    reviewer = str(st.session_state.get("_auth_subject_id") or "").strip()
    role = st.session_state.get("_auth_role")
    require_permission(role, "approve_thesis")
    if not reviewer:
        st.error("Identitas reviewer terverifikasi tidak tersedia.")
        return
    st.subheader("Investment Thesis Review Inbox")
    st.caption("Hanya permintaan review yang secara eksplisit ditugaskan kepada akun ini yang dapat dibuka.")
    try:
        reviews = list_reviews_for_reviewer(reviewer)
    except Exception as exc:
        st.error(f"Review inbox tidak dapat dibaca ({type(exc).__name__}).")
        return
    if not reviews:
        st.info("Tidak ada permintaan review yang ditugaskan.")
        return
    labels = {
        "{} · {} · {} · v{} · {}".format(
            item["ticker"], item["title"], item["status"], item["version"], item["created_at"]
        ): item["id"]
        for item in reviews
    }
    selected = st.selectbox("Pilih permintaan review", list(labels), key="thesis_review_inbox")
    review_id = labels[selected]
    try:
        review = get_review_for_reviewer(reviewer, review_id)
    except Exception as exc:
        st.error(f"Review tidak dapat dibuka ({type(exc).__name__}).")
        return
    st.markdown("**Tesis yang ditinjau**")
    st.write({
        "Ticker": review["ticker"], "Market": review["market"],
        "Judul": review["title"], "Versi": review["version"],
        "Pemilik": review["owner_id"], "Status": review["status"],
    })
    st.json(review["content"])
    if review["status"] != "PENDING":
        st.info("Review ini sudah diputuskan. Keputusan dan komentar bersifat read-only.")
        st.write(review.get("comments", ""))
        return
    with st.form("thesis_review_decision_form"):
        decision = st.selectbox(
            "Keputusan", ["APPROVED", "CHANGES_REQUESTED", "REJECTED"],
            format_func=lambda value: {
                "APPROVED": "Approve",
                "CHANGES_REQUESTED": "Minta revisi",
                "REJECTED": "Reject",
            }[value],
        )
        comments = st.text_area("Catatan reviewer")
        submitted = st.form_submit_button("Kirim keputusan review", type="primary")
    if submitted:
        try:
            outcome = decide_review(reviewer, review_id, decision, comments)
            st.success("Keputusan review berhasil disimpan.")
            try:
                record_audit_event(
                    reviewer, role, "THESIS_REVIEW_DECISION", "research_thesis_review",
                    review_id, details={
                        "thesis_id": review["thesis_id"], "version": review["version"],
                        "decision": outcome,
                    },
                )
            except Exception as audit_exc:
                st.warning(f"Keputusan tersimpan, tetapi audit event gagal dicatat ({type(audit_exc).__name__}).")
            st.rerun()
        except Exception as exc:
            st.error(f"Keputusan review gagal disimpan ({type(exc).__name__}).")
