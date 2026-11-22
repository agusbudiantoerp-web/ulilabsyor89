import streamlit as st

from equity_research_page import render_equity_research
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
st.caption("Integrated research, daily signals, portfolio risk, backtesting, and performance monitoring.")
st.warning("Platform riset dan pengambilan keputusan. Bukan nasihat investasi atau sistem eksekusi order.")

PAGES = {
    "1. Equity Research": render_equity_research,
    "2. Daily Stock Signal": render_daily_signal,
    "3. Portfolio & Risk Management": render_portfolio_risk,
    "4. Backtesting": render_backtesting,
    "5. Performance Dashboard": render_performance_dashboard,
}

with st.sidebar:
    st.title("📊 AI Research")
    selected = st.radio("Menu utama", list(PAGES.keys()), index=0)
    st.divider()
    st.caption("Market data: Yahoo Finance")
    st.caption("AI lokal & Telegram: komputer pribadi")
    st.caption("Versi: Unified Workspace 1.0")

PAGES[selected]()
