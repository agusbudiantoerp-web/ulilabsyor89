import streamlit as st

from auth import audit_login_once, get_claim, logout, oidc_is_configured, resolve_streamlit_identity
from equity_research_page import render_equity_research
from security_controls import require_permission
from unified_dashboard_pages import (
    render_daily_signal,
    render_portfolio_risk,
    render_backtesting,
    render_performance_dashboard,
)

st.set_page_config(
    page_title="AI Equity Research Workspace",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("AI Equity Research Workspace")
st.caption("Integrated research, daily signals, market regime, relative strength, portfolio risk, multi-asset backtesting, and performance reporting.")
st.warning("Platform riset dan pengambilan keputusan. Bukan nasihat investasi atau sistem eksekusi order.")

if not oidc_is_configured(st.secrets):
    st.error("Akses dashboard dikunci: autentikasi OIDC belum dikonfigurasi.")
    st.markdown(
        "Administrator harus mengatur Streamlit Secrets sesuai panduan "
        "[OIDC_SETUP.md](https://github.com/agusbudiantoerp-web/ulilabsyor89/blob/"
        "feature/advanced-equity-intelligence/Projects/ai-equity-research-v2/OIDC_SETUP.md)."
    )
    st.stop()

if not st.user.is_logged_in:
    st.info("Silakan masuk menggunakan akun organisasi yang telah didaftarkan.")
    if st.button("Login dengan OIDC", type="primary"):
        st.login()
    st.stop()

try:
    identity = resolve_streamlit_identity(st.user, st.secrets)
except PermissionError as exc:
    st.error("Akses ditolak: " + str(exc))
    subject = str(get_claim(st.user, "sub", "") or "").strip()
    if subject:
        st.caption("Principal identifier (issuer|sub) untuk administrator:")
        st.code(subject)
        st.caption(
            "Administrator harus memasukkan principal identifier ini ke tabel [auth_roles] "
            "di Streamlit Secrets dengan role yang disetujui."
        )
    if st.button("Logout"):
        st.logout()
    st.stop()

# Clear prior user's widget and cached portfolio/research state when the
# authenticated OIDC principal changes within a reused Streamlit session.
previous_principal = st.session_state.get("_auth_subject_id")
if previous_principal != identity["subject_id"]:
    for state_key in list(st.session_state.keys()):
        del st.session_state[state_key]
    st.session_state["_auth_subject_id"] = identity["subject_id"]
st.session_state["_auth_role"] = identity["role"]

try:
    audit_login_once(st, identity)
except Exception:
    st.error("Akses ditolak: pencatatan audit login gagal. Hubungi administrator.")
    st.stop()

PAGES = {
    "1. Equity Research": (render_equity_research, "run_analysis"),
    "2. Daily Stock Signal": (render_daily_signal, "run_analysis"),
    "3. Portfolio & Risk Management": (render_portfolio_risk, "manage_portfolio"),
    "4. Backtesting": (render_backtesting, "run_analysis"),
    "5. Performance Dashboard": (render_performance_dashboard, "view_dashboard"),
}

with st.sidebar:
    st.title("📊 AI Research")
    st.caption(f"Signed in: {identity['email'] or identity['subject_id']}")
    st.caption(f"Role: {identity['role']}")
    if st.button("Logout", use_container_width=True):
        try:
            logout(st, identity)
        except Exception:
            st.error("Logout audit gagal. Silakan hubungi administrator.")
            st.stop()
    st.divider()
    allowed_pages = []
    for label, (_, permission) in PAGES.items():
        try:
            require_permission(identity["role"], permission)
            allowed_pages.append(label)
        except PermissionError:
            continue
    if not allowed_pages:
        st.error("Role Anda belum memiliki izin untuk membuka halaman.")
        st.stop()
    selected = st.radio("Menu utama", allowed_pages, index=0)
    st.divider()
    st.caption("Market data: Yahoo Finance")
    st.caption("AI lokal & Telegram: komputer pribadi")
    st.caption("Versi: AI Equity Research V2 · Advanced Intelligence")

render_function, required_permission = PAGES[selected]
require_permission(identity["role"], required_permission)
render_function()
