"""Shared futuristic visual system for the AI Equity Research workspace."""
from __future__ import annotations

import streamlit as st


def apply_workspace_theme() -> None:
    """Inject a responsive dark-fintech theme without changing page logic."""
    st.markdown(
        """
        <style>
        :root {
          --aer-bg: #070d18;
          --aer-panel: rgba(15, 27, 45, .82);
          --aer-panel-strong: #101d30;
          --aer-line: rgba(91, 170, 220, .20);
          --aer-cyan: #43d9ff;
          --aer-blue: #668cff;
          --aer-violet: #a78bfa;
          --aer-text: #e8f3ff;
          --aer-muted: #91a7c1;
          --aer-green: #37d6a0;
          --aer-orange: #ffad66;
        }
        .stApp {
          color: var(--aer-text);
          background:
            radial-gradient(ellipse at 8% 0%, rgba(35, 116, 180, .20), transparent 34%),
            radial-gradient(ellipse at 92% 4%, rgba(112, 75, 190, .16), transparent 30%),
            linear-gradient(145deg, #070d18 0%, #091321 48%, #0a1020 100%);
        }
        .stApp:before {
          content: "";
          position: fixed; inset: 0; pointer-events: none; z-index: 0;
          opacity: .16;
          background-image: linear-gradient(rgba(99, 173, 220, .10) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(99, 173, 220, .10) 1px, transparent 1px);
          background-size: 42px 42px;
          mask-image: linear-gradient(to bottom, black, transparent 78%);
        }
        [data-testid="stHeader"] { background: rgba(7, 13, 24, .72); backdrop-filter: blur(18px); }
        [data-testid="stToolbar"] { right: 1rem; }
        [data-testid="stAppViewContainer"] > .main { position: relative; z-index: 1; }
        .block-container { max-width: 1580px; padding-top: 2.0rem; padding-bottom: 3rem; }
        h1, h2, h3 { color: #eff8ff !important; letter-spacing: -.035em; }
        h1 { font-weight: 780 !important; }
        h2, h3 { font-weight: 700 !important; }
        p, label, [data-testid="stMarkdownContainer"] { color: inherit; }
        [data-testid="stCaptionContainer"] { color: var(--aer-muted); }
        [data-testid="stSidebar"] {
          background: linear-gradient(180deg, rgba(12, 25, 43, .98), rgba(8, 16, 29, .98));
          border-right: 1px solid var(--aer-line);
        }
        [data-testid="stSidebar"] > div:first-child { border-right: 0; }
        [data-testid="stSidebar"] h1 { color: var(--aer-cyan) !important; }
        [data-testid="stSidebar"] [role="radiogroup"] { gap: 5px; }
        [data-testid="stSidebar"] [role="radiogroup"] label {
          border: 1px solid transparent; border-radius: 10px; padding: 7px 10px;
          transition: background .16s ease, border-color .16s ease;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {
          background: rgba(67, 217, 255, .07); border-color: var(--aer-line);
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
          background: linear-gradient(100deg, rgba(67, 217, 255, .14), rgba(102, 140, 255, .10));
          border-color: rgba(67, 217, 255, .30);
        }
        [data-testid="stMetric"] {
          background: linear-gradient(145deg, rgba(19, 39, 62, .92), rgba(12, 25, 43, .88));
          border: 1px solid var(--aer-line); border-radius: 16px;
          padding: 16px 18px; box-shadow: 0 12px 30px rgba(0,0,0,.16);
        }
        [data-testid="stMetricLabel"] { color: #9eb5cf !important; font-size: .82rem; }
        [data-testid="stMetricValue"] { color: #f2f9ff !important; font-weight: 760; }
        [data-testid="stMetricDelta"] { font-weight: 650; }
        [data-testid="stVerticalBlockBorderWrapper"] {
          border-color: var(--aer-line) !important; border-radius: 18px !important;
          background: rgba(13, 27, 46, .52);
        }
        [data-testid="stExpander"] {
          border: 1px solid var(--aer-line); border-radius: 16px;
          background: rgba(13, 27, 46, .62); overflow: hidden;
        }
        [data-testid="stExpander"] summary { font-weight: 650; }
        div[data-baseweb="tab-list"] {
          gap: 7px; border-bottom: 1px solid var(--aer-line);
        }
        button[data-baseweb="tab"] {
          border-radius: 10px 10px 0 0; padding: 10px 16px;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
          color: var(--aer-cyan) !important;
          border-bottom: 2px solid var(--aer-cyan);
          background: rgba(67, 217, 255, .07);
        }
        .stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] button {
          border: 1px solid rgba(67, 217, 255, .38);
          border-radius: 11px; color: #eafaff;
          background: linear-gradient(115deg, rgba(27, 113, 151, .92), rgba(69, 88, 170, .92));
          font-weight: 680; transition: all .18s ease;
          box-shadow: 0 5px 18px rgba(24, 125, 170, .13);
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
          border-color: var(--aer-cyan); color: white;
          transform: translateY(-1px); box-shadow: 0 8px 24px rgba(67, 217, 255, .19);
        }
        .stButton > button:focus-visible, .stDownloadButton > button:focus-visible,
        [data-testid="stFormSubmitButton"] button:focus-visible,
        button[data-baseweb="tab"]:focus-visible,
        [data-testid="stSidebar"] input:focus-visible {
          outline: 2px solid var(--aer-cyan) !important;
          outline-offset: 3px !important;
          box-shadow: 0 0 0 5px rgba(67, 217, 255, .14) !important;
        }
        .stButton > button:disabled, .stDownloadButton > button:disabled {
          opacity: .48; cursor: not-allowed; transform: none; box-shadow: none;
        }
        ::selection { background: rgba(67, 217, 255, .28); color: #fff; }
        [data-testid="stBaseButton-secondary"] {
          background: rgba(17, 34, 56, .88) !important;
          border-color: var(--aer-line) !important;
        }
        input, textarea, [data-baseweb="select"] > div {
          background: rgba(7, 17, 31, .86) !important;
          border-color: rgba(104, 157, 198, .30) !important;
          border-radius: 10px !important;
        }
        input:focus, textarea:focus { border-color: var(--aer-cyan) !important; }
        [data-testid="stDataFrame"], [data-testid="stTable"] {
          border: 1px solid var(--aer-line); border-radius: 13px; overflow: hidden;
        }
        [data-testid="stAlert"] { border-radius: 13px; }
        [data-testid="stProgressBar"] > div > div { background: linear-gradient(90deg, var(--aer-cyan), var(--aer-violet)); }
        [data-testid="stStatusWidget"] { border-color: var(--aer-line); }
        [data-testid="stPlotlyChart"], [data-testid="stVegaLiteChart"] {
          border: 1px solid rgba(91, 170, 220, .14); border-radius: 15px;
          background: rgba(10, 21, 37, .45); padding: 5px;
        }
        hr { border-color: var(--aer-line) !important; }
        .aer-hero {
          position: relative; overflow: hidden; padding: 25px 28px;
          border: 1px solid rgba(67, 217, 255, .25); border-radius: 20px;
          background: linear-gradient(112deg, rgba(18, 54, 83, .88), rgba(23, 31, 67, .82) 58%, rgba(40, 29, 75, .72));
          box-shadow: 0 18px 46px rgba(0,0,0,.20), inset 0 1px rgba(255,255,255,.04);
          margin: 0 0 20px 0;
        }
        .aer-page-hero { margin-bottom: 16px; }
        .aer-page-hero .aer-title { font-size: clamp(1.35rem, 2.25vw, 1.9rem); }
        .aer-page-hero .aer-subtitle { max-width: 980px; }
        .aer-hero:after {
          content: ""; position: absolute; width: 250px; height: 250px; right: -65px; top: -120px;
          border: 1px solid rgba(67,217,255,.22); border-radius: 50%;
          box-shadow: 0 0 0 24px rgba(67,217,255,.035), 0 0 0 50px rgba(167,139,250,.025);
        }
        .aer-eyebrow {
          color: var(--aer-cyan); font-size: .72rem; font-weight: 800;
          letter-spacing: .18em; text-transform: uppercase; margin-bottom: 8px;
        }
        .aer-title { color: #f2f9ff; font-size: clamp(1.45rem, 2.6vw, 2.15rem);
          font-weight: 780; letter-spacing: -.045em; line-height: 1.12; }
        .aer-subtitle { color: #afc4dc; margin-top: 9px; max-width: 900px; font-size: .94rem; }
        .aer-chip {
          display: inline-block; border: 1px solid rgba(67,217,255,.30);
          border-radius: 999px; padding: 5px 10px; margin-top: 14px;
          color: #a9edff; background: rgba(67,217,255,.08);
          font-size: .72rem; font-weight: 700; letter-spacing: .04em;
        }
        @media (max-width: 700px) {
          .block-container { padding: 1.2rem .8rem 2rem; }
          .aer-hero { padding: 20px; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *:before, *:after { transition: none !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )



def render_page_hero(eyebrow: str, title: str, subtitle: str, chips: str) -> None:
    """Render a consistent, escaped hero header for a workspace page."""
    from html import escape

    safe_eyebrow = escape(str(eyebrow))
    safe_title = escape(str(title))
    safe_subtitle = escape(str(subtitle))
    safe_chips = escape(str(chips))
    st.markdown(
        f"""<section class="aer-hero aer-page-hero">
        <div class="aer-eyebrow">{safe_eyebrow}</div>
        <div class="aer-title">{safe_title}</div>
        <div class="aer-subtitle">{safe_subtitle}</div>
        <span class="aer-chip">{safe_chips}</span>
        </section>""",
        unsafe_allow_html=True,
    )
