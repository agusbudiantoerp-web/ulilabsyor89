
import streamlit as st
from engine import analyze_equity, calculate_dcf, dcf_sensitivity, build_research_summary
from multistage_adapter import calculate_multistage_dcf
from reports import make_excel_report, make_pdf_report
from scenario_ui import render_scenario_analysis
from dcf_sensitivity import run_dcf_sensitivity

st.set_page_config(page_title="AI Equity Research", page_icon="📊", layout="wide")
st.title("AI Equity Research")
st.caption("Indonesian equities first · shared engine for web and Telegram · Yahoo Finance data")
st.warning("Research support only. Not investment advice. Verify data and assumptions independently.")

with st.sidebar:
    st.header("Research settings")

    market = st.selectbox(
        "Pilih pasar saham",
        ["IDX", "US"],
        index=0,
        format_func=lambda x: "Indonesia (IDX)" if x == "IDX" else "United States (US)"
    )

    if market == "IDX":
        symbol = st.text_input(
            "Ticker saham",
            "ANTM",
            help="Masukkan kode saham BEI, contoh: ANTM, BBCA, TPIA."
        )
    else:
        symbol = st.text_input(
            "Ticker saham",
            "NVDA",
            help="Masukkan ticker saham Amerika, contoh: NVDA, AAPL, MSFT, BRK.B."
        )

    period = st.selectbox("Periode harga", ["1y", "2y", "5y", "10y"], index=2)

    st.subheader("DCF assumptions")
    years = st.slider("Forecast years", 3, 10, 5)
    growth_pct = st.number_input("Annual FCF growth (%)", -50.0, 100.0, 5.0, 1.0)
    wacc_pct = st.number_input("WACC (%)", 1.0, 100.0, 12.0, 0.5)
    terminal_pct = st.number_input("Terminal growth (%)", -10.0, 20.0, 2.5, 0.5)

    st.subheader("Multi-Stage DCF assumptions")
    high_growth_pct = st.number_input(
        "High growth (%)", -50.0, 100.0, 15.0, 1.0
    )
    transition_growth_pct = st.number_input(
        "Transition growth (%)", -50.0, 100.0, 8.0, 1.0
    )
    stable_growth_pct = st.number_input(
        "Stable growth (%)", -10.0, 20.0, 3.0, 0.5
    )

    high_growth_years = st.number_input(
        "High growth years",
        min_value=1,
        max_value=max(1, years - 1),
        value=min(2, max(1, years - 1)),
        step=1
    )
    transition_growth_years = st.number_input(
        "Transition growth years",
        min_value=1,
        max_value=max(1, years - high_growth_years),
        value=min(2, max(1, years - high_growth_years)),
        step=1
    )

    terminal_capex_pct = st.number_input(
        "Terminal CAPEX (% revenue)",
        min_value=0.0,
        max_value=200.0,
        value=5.0,
        step=0.5
    )

    use_manual_tax_rate = st.checkbox("Use manual tax rate", value=False)
    manual_tax_pct = st.number_input(
        "Manual tax rate (%)",
        min_value=0.0,
        max_value=100.0,
        value=22.0,
        step=0.5,
        disabled=not use_manual_tax_rate
    )

    allow_data_quality_override = st.checkbox(
        "Allow calculation with data-quality warnings",
        value=False,
        help="Aktifkan hanya jika Anda sudah memeriksa dan menerima risiko peringatan kualitas data."
    )

    st.subheader("DCF sensitivity settings")

    sensitivity_growth = st.multiselect(
        "FCF Growth scenarios (%)",
        options=[0, 5, 10, 15, 20],
        default=[0, 5, 10, 15, 20]
    )

    sensitivity_wacc = st.multiselect(
        "WACC scenarios (%)",
        options=[8, 10, 12, 14, 16],
        default=[8, 10, 12, 14, 16]
    )

    st.subheader("Currency conversion")
    fx_rate = st.number_input(
        "Reference USD/IDR rate",
        min_value=1.0,
        max_value=100000.0,
        value=18094.0,
        step=10.0,
        help="Digunakan hanya jika mata uang laporan berbeda dari mata uang saham."
    )
    fx_source_date = st.text_input("FX reference date", "2026-11-06")
    st.caption("Masukkan kurs referensi dan tanggalnya secara manual. Perbarui sebelum analisis berikutnya.")

    run = st.button("Analyze stock", type="primary", use_container_width=True)

if run:
    try:
        with st.spinner("Mengambil data pasar dan menghitung indikator..."):
            result = analyze_equity(symbol, period, market=market)
            dcf = calculate_dcf(
                result,
                years=years,
                growth=growth_pct / 100,
                wacc=wacc_pct / 100,
                terminal_growth=terminal_pct / 100,
                fx_rate=fx_rate,
                fx_source_date=fx_source_date
            )

            multistage_assumptions = {
                "high_growth": high_growth_pct / 100,
                "transition_growth": transition_growth_pct / 100,
                "stable_growth": stable_growth_pct / 100,
                "high_growth_years": int(high_growth_years),
                "transition_growth_years": int(transition_growth_years),
                "wacc": wacc_pct / 100,
                "terminal_growth": terminal_pct / 100,
                "terminal_capex_pct_revenue": terminal_capex_pct / 100
            }

            if use_manual_tax_rate:
                multistage_assumptions["tax_rate"] = manual_tax_pct / 100

            multistage_dcf = calculate_multistage_dcf(
                result,
                multistage_assumptions,
                fx_rate=fx_rate,
                years=years,
                allow_data_quality_override=allow_data_quality_override
            )

        st.session_state["equity_result"] = result
        st.session_state["equity_dcf"] = dcf
        st.session_state["equity_multistage_dcf"] = multistage_dcf

    except Exception as exc:
        st.error(str(exc))

data = st.session_state.get("equity_result")
dcf = st.session_state.get("equity_dcf")
multistage_dcf = st.session_state.get("equity_multistage_dcf")

if data:
    st.subheader(f"{data['company']} · {data['ticker']}")

    c = st.columns(4)
    c[0].metric("Latest price", f"{data['price']:,.2f} {data['currency']}")
    c[1].metric(
        "Daily change",
        f"{data['change_pct']:.2f}%" if data.get("change_pct") is not None else "N/A"
    )
    c[2].metric(
        "Period return",
        f"{data['period_return_pct']:.2f}%" if data.get("period_return_pct") is not None else "N/A"
    )
    c[3].metric(
        "Annualized volatility",
        f"{data['annualized_volatility_pct']:.2f}%"
        if data.get("annualized_volatility_pct") is not None else "N/A"
    )

    st.caption(
        f"Harga terakhir: {data.get('latest_price_date', 'N/A')} · "
        f"Laporan laba rugi: {data.get('latest_financial_period', 'N/A')} · "
        f"Neraca: {data.get('latest_balance_period', 'N/A')} · "
        f"Arus kas: {data.get('latest_cashflow_period', 'N/A')}"
    )

    for warning in data.get("data_quality_warnings", []):
        st.warning(warning)

    st.info(data["data_quality_note"])

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Overview", "Fundamentals", "Technical", "Valuation"]
    )

    with tab1:
        st.write(f"**Sector:** {data['sector']} · **Industry:** {data['industry']}")
        st.write(f"**Data source:** {data['data_source']} · **Generated:** {data['as_of']}")

        for item in build_research_summary(data):
            st.write("• " + item)

        st.line_chart(data["history"].set_index("Date")["Close"])

    with tab2:
        st.dataframe(
            [
                {"Metric": k, "Value": v if v is not None else "N/A"}
                for k, v in data["ratios"].items()
            ],
            use_container_width=True,
            hide_index=True
        )

    with tab3:
        metrics = {
            "SMA 20": data["sma20"],
            "SMA 50": data["sma50"],
            "SMA 200": data["sma200"],
            "RSI 14": data["rsi14"]
        }

        st.dataframe(
            [
                {"Indicator": k, "Value": v if v is not None else "N/A"}
                for k, v in metrics.items()
            ],
            use_container_width=True,
            hide_index=True
        )
        st.write("Trend:", data["trend"], "· RSI:", data["rsi_signal"])

    with tab4:
        if dcf and dcf.get("available"):
            st.subheader("DCF valuation")

            st.metric(
                "Enterprise Value",
                f"{dcf['enterprise_value']:,.2f} {dcf['currency']}"
            )
            st.metric(
                "Equity Value",
                f"{dcf['equity_value']:,.2f} {dcf['currency']}"
            )
            st.metric(
                "Intrinsic Value per Share",
                f"{dcf['intrinsic_value_per_share']:,.2f} {dcf['display_currency']}"
            )

            if dcf.get("fx_conversion_applied"):
                st.caption(
                    f"Per-share conversion: {dcf['currency']} to "
                    f"{dcf['display_currency']} · "
                    f"Rate: {dcf['fx_rate']:,.2f} · "
                    f"Reference date: {dcf.get('fx_source_date') or 'Not specified'}"
                )
            else:
                st.caption(
                    f"Valuation currency: {dcf['currency']}. "
                    "No currency conversion applied."
                )

            if dcf["display_currency"] == data["currency"]:
                upside = (
                    dcf["intrinsic_value_per_share"] / data["price"] - 1
                ) * 100 if data["price"] else None

                if upside is not None:
                    st.metric("Implied upside / downside", f"{upside:+.2f}%")

            st.subheader("FCF forecast")
            st.dataframe(dcf["forecast"], use_container_width=True, hide_index=True)
            st.caption(dcf["warning"])

            sensitivity = dcf_sensitivity(
                data,
                growth_rates=[x / 100 for x in sensitivity_growth],
                wacc_rates=[x / 100 for x in sensitivity_wacc],
                years=years,
                terminal_growth=terminal_pct / 100,
                fx_rate=fx_rate
            )

            if sensitivity.get("available"):
                st.subheader("Sensitivity · intrinsic value per share")
                st.caption(sensitivity["warning"])
                st.dataframe(
                    sensitivity["matrix"],
                    use_container_width=True,
                    hide_index=True
                )

                with st.expander("Show enterprise value sensitivity"):
                    st.dataframe(
                        sensitivity["enterprise_value_matrix"],
                        use_container_width=True,
                        hide_index=True
                    )
            else:
                st.info(sensitivity.get("reason", "Sensitivity not available."))

        else:
            reason = dcf.get("reason", "Run analysis first.") if dcf else "Run analysis first."
            st.info(reason)

            if "bank" in reason.lower() or "asuransi" in reason.lower():
                st.write(
                    "Untuk bank, evaluasi P/B, ROE, pertumbuhan laba, kualitas aset, "
                    "NPL, CAR, dan pendekatan residual income atau dividend discount."
                )

        st.divider()
        st.subheader("Multi-Stage DCF Valuation")
        st.caption(
            "Valuasi menggunakan tiga fase pertumbuhan: High Growth, "
            "Transition Growth, dan Stable Growth."
        )

        if multistage_dcf and multistage_dcf.get("available"):
            ms_currency = multistage_dcf.get("quote_currency", data["currency"])

            m1, m2, m3, m4 = st.columns(4)
            m1.metric(
                "Intrinsic Value / Share",
                f"{multistage_dcf['intrinsic_value_per_share']:,.2f} {ms_currency}"
            )
            m2.metric(
                "Current Price",
                f"{multistage_dcf['current_price']:,.2f} {ms_currency}"
            )
            m3.metric(
                "Upside / Downside",
                f"{multistage_dcf['upside_downside_pct']:+.2f}%"
            )
            m4.metric(
                "Equity Value",
                f"{multistage_dcf['equity_value']:,.2f} "
                f"{multistage_dcf.get('financial_currency', ms_currency)}"
            )

            # Transparansi sumber EBITDA yang digunakan model.
            ebitda_used = multistage_dcf.get("ebitda_used")
            ebitda_source = multistage_dcf.get("ebitda_source")
            financial_currency = multistage_dcf.get(
                "financial_currency", ms_currency
            )

            st.markdown("#### EBITDA Data Source")

            if ebitda_used is not None:
                e1, e2 = st.columns(2)
                e1.metric(
                    "EBITDA Used",
                    f"{ebitda_used:,.2f} {financial_currency}"
                )
                e2.metric(
                    "EBITDA Source",
                    ebitda_source or "Not specified"
                )

            if multistage_dcf.get("data_quality_warnings"):
                st.warning("Data memerlukan pemeriksaan manual.")
            else:
                st.success("Pemeriksaan konsistensi data: tidak ada warning.")

            st.write(
                "**Enterprise Value:** "
                f"{multistage_dcf['enterprise_value']:,.2f} "
                f"{multistage_dcf.get('financial_currency', ms_currency)}"
            )
            st.write(
                "**Net Debt:** "
                f"{multistage_dcf['net_debt']:,.2f} "
                f"{multistage_dcf.get('financial_currency', ms_currency)}"
            )

            st.subheader("Multi-Stage DCF Forecast")
            st.dataframe(
                multistage_dcf["forecast"],
                use_container_width=True,
                hide_index=True
            )

            # Multi-Stage DCF Sensitivity Analysis
            st.subheader("Multi-Stage DCF Sensitivity Analysis")
            st.caption(
                "Nilai intrinsik per saham berdasarkan kombinasi "
                "WACC dan Terminal Growth."
            )

            sensitivity_financials = multistage_dcf.get(
                "sensitivity_financials"
            )
            sensitivity_assumptions = multistage_dcf.get(
                "sensitivity_assumptions"
            )

            if sensitivity_financials and sensitivity_assumptions:
                base_wacc = float(sensitivity_assumptions["wacc"])
                base_growth = float(
                    sensitivity_assumptions["terminal_growth"]
                )

                # Rentang otomatis di sekitar Base Case.
                wacc_values = sorted(set([
                    round(base_wacc - 0.04, 4),
                    round(base_wacc - 0.02, 4),
                    round(base_wacc, 4),
                    round(base_wacc + 0.02, 4),
                    round(base_wacc + 0.04, 4),
                ]))

                growth_values = sorted(set([
                    round(max(0.0, base_growth - 0.01), 4),
                    round(max(0.0, base_growth - 0.005), 4),
                    round(base_growth, 4),
                    round(base_growth + 0.005, 4),
                    round(base_growth + 0.01, 4),
                ]))

                ms_sensitivity = run_dcf_sensitivity(
                    fundamentals=sensitivity_financials,
                    assumptions=sensitivity_assumptions,
                    years=years,
                    wacc_values=wacc_values,
                    terminal_growth_values=growth_values,
                )

                if ms_sensitivity.get("available"):
                    matrix_table = []

                    for row in ms_sensitivity["matrix"]:
                        table_row = {
                            "WACC": f"{row['wacc']:.2%}"
                        }

                        for growth, value in row["values"].items():
                            column = f"TG {growth:.2%}"
                            table_row[column] = (
                                f"{value:,.2f} {ms_currency}"
                                if value is not None
                                else "N/A"
                            )

                        matrix_table.append(table_row)

                    st.dataframe(
                        matrix_table,
                        use_container_width=True,
                        hide_index=True
                    )

                    base_case = ms_sensitivity.get("base_case")

                    if base_case and base_case.get(
                        "intrinsic_value_per_share"
                    ) is not None:
                        base_sensitivity_value = base_case[
                            "intrinsic_value_per_share"
                        ]
                        main_value = multistage_dcf[
                            "intrinsic_value_per_share"
                        ]
                        difference = abs(
                            base_sensitivity_value - main_value
                        )

                        st.metric(
                            "Base Case · Sensitivity",
                            f"{base_sensitivity_value:,.2f} {ms_currency}",
                            help=(
                                "Seharusnya sama dengan Intrinsic Value "
                                "utama jika asumsi dan input identik."
                            )
                        )

                        if difference < max(0.01, abs(main_value) * 1e-8):
                            st.success(
                                "Base Case cocok dengan valuasi utama."
                            )
                        else:
                            st.error(
                                "Base Case berbeda dari valuasi utama. "
                                "Perlu pemeriksaan input atau asumsi."
                            )
                    else:
                        st.warning(
                            "Base Case tidak ditemukan dalam matriks."
                        )
                else:
                    st.warning(
                        ms_sensitivity.get(
                            "reason",
                            "Multi-Stage sensitivity tidak tersedia."
                        )
                    )
            else:
                st.warning(
                    "Input sensitivitas belum tersedia. "
                    "Jalankan ulang analisis saham."
                )

            assumptions = multistage_dcf.get("assumptions", {})
            if assumptions:
                with st.expander("Show Multi-Stage DCF assumptions"):
                    st.dataframe(
                        [
                            {"Assumption": key, "Value": value}
                            for key, value in assumptions.items()
                        ],
                        use_container_width=True,
                        hide_index=True
                    )

            for warning in multistage_dcf.get("data_quality_warnings", []):
                st.warning(warning)

            if multistage_dcf.get("data_quality_override"):
                st.warning(
                    "Perhitungan dilanjutkan dengan persetujuan manual "
                    "meskipun terdapat peringatan kualitas data."
                )

            st.caption(multistage_dcf.get("warning", ""))

        else:
            reason = (
                multistage_dcf.get("reason", "Run analysis first.")
                if multistage_dcf else "Run analysis first."
            )
            st.info(f"Multi-Stage DCF belum tersedia: {reason}")

            if multistage_dcf:
                for warning in multistage_dcf.get("data_quality_warnings", []):
                    st.warning(warning)

        st.divider()
        render_scenario_analysis(data, fx_rate=fx_rate, years=years)

    col1, col2 = st.columns(2)

    col1.download_button(
        "Download Excel report",
        make_excel_report(data, dcf),
        file_name=f"{data['ticker'].replace('.', '_')}_research.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    col2.download_button(
        "Download PDF report",
        make_pdf_report(data, dcf),
        file_name=f"{data['ticker'].replace('.', '_')}_research.pdf",
        mime="application/pdf",
        use_container_width=True
    )

else:
    st.info("Masukkan ticker saham, atur asumsi, lalu klik Analyze stock.")
