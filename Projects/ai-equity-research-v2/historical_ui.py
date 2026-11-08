import streamlit as st
from idx_fundamentals import fetch_idx_fundamentals, get_fundamentals_summary
from idx_analysis import analyze_idx_fundamentals


def _trillion_currency(value, currency):
    if value is None:
        return "N/A"
    try:
        if value != value:
            return "N/A"
        amount = float(value) / 1_000_000_000_000
        code = str(currency or "").strip().upper()
        prefix = f"{code} " if code else ""
        return f"{prefix}{amount:,.2f} T"
    except (TypeError, ValueError, OverflowError):
        return "N/A"


def render_historical_analysis(symbol: str, market: str) -> None:
    st.subheader("Historical Fundamental Analysis")

    if market != "IDX":
        st.info("Historical Fundamental Analysis saat ini tersedia untuk saham IDX.")
        return

    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        st.warning("Masukkan ticker IDX terlebih dahulu.")
        return

    cached_symbol = st.session_state.get("historical_fundamentals_symbol")
    if cached_symbol != normalized_symbol:
        for key in (
            "historical_fundamentals_data",
            "historical_fundamentals_analysis",
            "historical_fundamentals_summary",
        ):
            st.session_state.pop(key, None)
        st.session_state["historical_fundamentals_symbol"] = normalized_symbol

    if st.button("Muat / Perbarui Data Historis", key="load_historical_fundamentals"):
        try:
            with st.spinner("Mengambil laporan keuangan historis dari Yahoo Finance..."):
                raw_data = fetch_idx_fundamentals(normalized_symbol)
                analysis = analyze_idx_fundamentals(raw_data)
                summary = get_fundamentals_summary(raw_data)
                st.session_state["historical_fundamentals_data"] = raw_data
                st.session_state["historical_fundamentals_analysis"] = analysis
                st.session_state["historical_fundamentals_summary"] = summary
        except Exception as exc:
            st.error(f"Gagal mengambil data historis: {exc}")
            return

    raw_data = st.session_state.get("historical_fundamentals_data")
    analysis = st.session_state.get("historical_fundamentals_analysis")
    summary = st.session_state.get("historical_fundamentals_summary")

    if not raw_data or not analysis or not summary:
        st.info("Klik Muat / Perbarui Data Historis untuk mengambil laporan tahunan.")
        return

    st.markdown(f"**{analysis.get('company_name') or normalized_symbol}**")
    st.caption(
        f"Ticker: {analysis.get('ticker')} · Sektor: {analysis.get('sector') or 'N/A'} · "
        f"Industri: {analysis.get('industry') or 'N/A'} · Mata uang laporan: {analysis.get('reported_currency') or 'N/A'}"
    )
    st.caption(f"Sumber data: {analysis.get('source') or 'Tidak tersedia'}")

    metrics = analysis.get("annual_metrics")
    if metrics is None or metrics.empty:
        st.warning("Tidak ada metrik historis yang dapat ditampilkan.")
    else:
        latest = metrics.iloc[0]
        currency = analysis.get("reported_currency")
        st.markdown("#### Ringkasan periode terbaru")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue", _trillion_currency(latest.get("revenue"), currency))
        c2.metric("Net Income", _trillion_currency(latest.get("net_income"), currency))
        c3.metric("EBITDA", _trillion_currency(latest.get("ebitda"), currency))
        c4.metric("Free Cash Flow", _trillion_currency(latest.get("free_cash_flow"), currency))

        st.markdown("#### Tren keuangan tahunan")
        chart_columns = [
            name for name in ("revenue", "net_income", "ebitda", "free_cash_flow")
            if name in metrics.columns and metrics[name].notna().any()
        ]
        if chart_columns:
            chart_data = metrics[["year"] + chart_columns].sort_values("year").set_index("year")
            st.line_chart(chart_data)
            st.caption("Nilai grafik dalam mata uang pelaporan asli; tidak dikonversi.")
        else:
            st.info("Data belum cukup untuk membuat grafik tren.")

        st.markdown("#### Rasio dan metrik historis")
        st.dataframe(metrics, use_container_width=True, hide_index=True)

    st.markdown("#### Kelengkapan laporan keuangan")
    statement_labels = {
        "income_statement": "Income Statement",
        "balance_sheet": "Balance Sheet",
        "cash_flow": "Cash Flow",
    }
    coverage_rows = []
    for key, label in statement_labels.items():
        item = summary.get("statements", {}).get(key, {})
        coverage_rows.append({
            "Laporan": label,
            "Jumlah baris": item.get("rows", 0),
            "Periode": item.get("period_count", 0),
            "Data terisi": item.get("non_null_cells", 0),
            "Data kosong": item.get("missing_cells", 0),
        })
    st.dataframe(coverage_rows, use_container_width=True, hide_index=True)

    warnings = analysis.get("warnings", [])
    if warnings:
        st.markdown("#### Peringatan kualitas data")
        for warning in warnings:
            st.warning(warning)
    else:
        st.success("Tidak ada peringatan kualitas data dari pemeriksaan awal.")

    st.caption(analysis.get("methodology", ""))
