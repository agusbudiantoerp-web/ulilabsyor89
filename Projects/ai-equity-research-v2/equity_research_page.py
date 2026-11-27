
import streamlit as st

from ui_theme import render_page_hero
from engine import analyze_equity, calculate_dcf, dcf_sensitivity, build_research_summary
from engine import is_bank
from bank_valuation import calculate_bank_valuation
from multistage_adapter import calculate_multistage_dcf
from reports import make_excel_report, make_pdf_report
from scenario_ui import render_scenario_analysis
from dcf_sensitivity import run_dcf_sensitivity
from historical_ui import render_historical_analysis
from security_controls import require_permission, record_audit_event


def _audit_equity_action(action: str, ticker: str, details: dict | None = None) -> None:
    try:
        record_audit_event(
            st.session_state.get("_auth_subject_id", ""),
            st.session_state.get("_auth_role", ""),
            action,
            "equity_research",
            ticker,
            details=details or {},
        )
    except Exception as exc:
        st.warning(f"Aksi selesai, tetapi audit event gagal dicatat: {type(exc).__name__}.")


def _audit_equity_export(fmt: str, ticker: str) -> None:
    _audit_equity_action("REPORT_EXPORT", ticker, {"format": fmt})


def _apply_bank_filing_preview() -> None:
    """Apply reviewed PDF candidates before Streamlit recreates the input widgets."""
    preview = st.session_state.get("bank_filing_preview") or {}
    metrics = preview.get("metrics") or {}
    for metric_key, state_key in (
        ("NPL gross (%)", "bank_npl_pct"),
        ("CAR (%)", "bank_car_pct"),
        ("NIM (%)", "bank_nim_pct"),
        ("LDR (%)", "bank_ldr_pct"),
        ("Official reported ROE (%)", "bank_official_roe_pct"),
    ):
        candidate = metrics.get(metric_key)
        if candidate is not None:
            st.session_state[state_key] = str(candidate.get("value", ""))
    st.session_state["bank_source_name"] = preview.get("source_name", "")
    st.session_state["bank_source_period"] = preview.get("source_period", "")
    st.session_state["bank_source_url"] = preview.get("source_url", "")
    st.session_state["bank_source_confirmed"] = False


def render_equity_research():
    require_permission(st.session_state.get("_auth_role"), "run_analysis")
    render_page_hero("RESEARCH TERMINAL", "Equity Research & Valuation", "Fundamental analysis, DCF, Multi-Stage DCF, scenario valuation and sensitivity tools for IDX and US equities.", "FUNDAMENTALS  ·  DCF  ·  SCENARIOS")
    
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

        with st.expander("Bank valuation assumptions"):
            use_manual_bank_roe = st.checkbox(
                "Override reported ROE with manual assumption", value=False
            )
            bank_roe_pct = st.number_input(
                "Expected ROE (%)", min_value=-100.0, max_value=200.0,
                value=12.0, step=0.5, disabled=not use_manual_bank_roe,
                help="Secara default model memakai reported ROE dari sumber data; aktifkan untuk menggantinya."
            )
            bank_cost_of_equity_pct = st.number_input(
                "Cost of equity (%)", min_value=0.5, max_value=100.0,
                value=12.0, step=0.5
            )
            bank_growth_pct = st.number_input(
                "Stable book-value growth (%)", min_value=-10.0, max_value=20.0,
                value=4.0, step=0.5
            )
            bank_forecast_years = st.number_input(
                "Bank forecast years", min_value=1, max_value=20,
                value=5, step=1
            )
            st.caption("Digunakan khusus untuk emiten perbankan. Cost of equity harus lebih tinggi daripada stable growth.")

            st.markdown("**Official filing collector · issuer source retrieval**")
            if symbol.strip().upper().replace(".JK", "") == "BBRI":
                if st.button("Ambil data resmi BBRI · Q3 2026", key="fetch_official_bbri_filing"):
                    try:
                        from bank_filing_collector import extract_official_bank_filing
                        with st.spinner("Mengunduh dan membaca laporan resmi BRI..."):
                            st.session_state["bank_filing_preview"] = extract_official_bank_filing("BBRI")
                        st.success("Dokumen terbaca. Kandidat angka ditampilkan untuk pemeriksaan analis.")
                    except Exception as filing_error:
                        st.error(f"Pengambilan dokumen resmi gagal: {filing_error}")
            else:
                st.caption("Konektor otomatis saat ini baru tersedia untuk BBRI; ticker bank lain tetap memakai input manual.")
            filing_preview = st.session_state.get("bank_filing_preview")
            if (filing_preview and filing_preview.get("ticker") == symbol.strip().upper().replace(".JK", "")):
                st.warning("Hasil ekstraksi PDF adalah kandidat, bukan data VERIFIED. Cocokkan setiap angka dengan halaman dan definisi laporan.")
                st.dataframe([
                    {"Metric": key, "Candidate value": item.get("value"),
                     "PDF page": item.get("page"), "Confidence": item.get("confidence")}
                    for key, item in filing_preview.get("metrics", {}).items()
                ], use_container_width=True, hide_index=True)
                st.caption(
                    f"Source: {filing_preview.get('source_url')} · Period: {filing_preview.get('source_period')} · "
                    f"SHA-256: {filing_preview.get('document_sha256')}"
                )
                st.button(
                    "Terapkan kandidat ke input (perlu konfirmasi)",
                    key="apply_bbri_candidates",
                    on_click=_apply_bank_filing_preview,
                )
            st.markdown("**Bank regulatory / operating ratios · official filing review**")
            bank_official_roe_pct = st.text_input(
                "Official reported ROE (%)", value=st.session_state.get("bank_official_roe_pct", ""),
                help="Masukkan ROE dari laporan resmi. Pastikan definisinya (mis. laba setelah pajak / rata-rata ekuitas) dan periodenya sama dengan sumber yang dicatat."
            )
            bank_npl_pct = st.text_input("NPL gross (%)", value=st.session_state.get("bank_npl_pct", ""), help="Masukkan angka dari laporan publikasi bank; kosongkan jika belum diverifikasi.")
            bank_car_pct = st.text_input("CAR / KPMM (%)", value=st.session_state.get("bank_car_pct", ""))
            bank_ldr_pct = st.text_input("LDR (%)", value=st.session_state.get("bank_ldr_pct", ""))
            bank_nim_pct = st.text_input("NIM (%)", value=st.session_state.get("bank_nim_pct", ""))
            bank_source_name = st.text_input("Official source / filing name", value=st.session_state.get("bank_source_name", ""), help="Contoh: Laporan Publikasi Triwulan III 2026 — nama dokumen yang Anda periksa.")
            bank_source_period = st.text_input(
                "Official reporting period (YYYY-MM-DD)", value=st.session_state.get("bank_source_period", ""),
                help="Gunakan tanggal periode laporan, bukan tanggal harga saham. Agar VERIFIED, tanggal ini harus sama dengan periode neraca dan laba rugi yang dipakai aplikasi."
            )
            bank_source_url = st.text_input(
                "Official filing URL (HTTPS)", value=st.session_state.get("bank_source_url", ""),
                help="Masukkan tautan laporan dari situs resmi emiten, BEI, atau regulator. Tautan harus HTTPS tanpa username/password."
            )
            uploaded_bank_pdf = st.file_uploader(
                "Upload official bank ratio report (PDF)", type=["pdf"],
                key="bank_ratio_pdf_upload",
                help="Untuk bank yang belum memiliki konektor otomatis. PDF hasil scan memerlukan OCR dan belum didukung."
            )
            if st.button("Baca PDF yang diunggah", key="parse_uploaded_bank_pdf", disabled=uploaded_bank_pdf is None):
                try:
                    from bank_filing_collector import extract_uploaded_bank_filing
                    st.session_state["bank_filing_preview"] = extract_uploaded_bank_filing(
                        uploaded_bank_pdf.getvalue(), ticker=symbol,
                        source_name=bank_source_name or uploaded_bank_pdf.name,
                        period=bank_source_period, source_url=bank_source_url,
                    )
                    st.session_state["bank_source_confirmed"] = False
                    st.success("PDF berhasil diproses sebagai kandidat. Periksa angka, halaman, periode dan sumber sebelum menerapkan.")
                except Exception as upload_error:
                    st.error(f"Ekstraksi PDF gagal: {upload_error}")

            upload_preview = st.session_state.get("bank_filing_preview") or {}
            if (
                upload_preview.get("ticker") == symbol.strip().upper().replace(".JK", "")
                and upload_preview.get("extraction_method") == "Uploaded PDF text extraction"
            ):
                st.warning("Hasil ekstraksi PDF unggahan adalah kandidat, bukan data VERIFIED. Cocokkan setiap angka dengan halaman dan definisi laporan.")
                st.dataframe([
                    {"Metric": key, "Candidate value": item.get("value"),
                     "PDF page": item.get("page"), "Confidence": item.get("confidence")}
                    for key, item in upload_preview.get("metrics", {}).items()
                ], use_container_width=True, hide_index=True)
                st.caption(
                    f"Source: {upload_preview.get('source_url') or 'URL not supplied'} · "
                    f"Period: {upload_preview.get('source_period')} · "
                    f"SHA-256: {upload_preview.get('document_sha256')}"
                )
                st.button(
                    "Terapkan kandidat PDF unggahan ke input",
                    key="apply_uploaded_bank_pdf_candidates",
                    on_click=_apply_bank_filing_preview,
                )
            bank_source_confirmed = st.checkbox(
                "I personally checked this official filing and its figures",
                value=st.session_state.get("bank_source_confirmed", False),
                help="Status VERIFIED adalah konfirmasi analis, bukan verifikasi otomatis oleh aplikasi."
            )

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
                    allow_data_quality_override=allow_data_quality_override,
                    fx_source_date=fx_source_date
                )

                bank_valuation = (
                    calculate_bank_valuation(
                        result,
                        expected_roe=(
                            bank_roe_pct / 100 if use_manual_bank_roe else None
                        ),
                        cost_of_equity=bank_cost_of_equity_pct / 100,
                        stable_growth=bank_growth_pct / 100,
                        years=int(bank_forecast_years),
                        fx_rate=fx_rate,
                        fx_source_date=fx_source_date,
                        manual_metrics={
                            "Official reported ROE (%)": bank_official_roe_pct,
                            "NPL gross (%)": bank_npl_pct,
                            "CAR (%)": bank_car_pct,
                            "LDR (%)": bank_ldr_pct,
                            "NIM (%)": bank_nim_pct,
                        },
                        source_name=bank_source_name,
                        source_period=bank_source_period,
                        source_url=bank_source_url,
                        source_confirmed=bank_source_confirmed,
                    )
                    if is_bank(result)
                    else {"available": False, "reason": "Model khusus bank; tidak diterapkan pada emiten non-bank."}
                )
    
            st.session_state["equity_result"] = result
            st.session_state["equity_dcf"] = dcf
            st.session_state["equity_multistage_dcf"] = multistage_dcf
            st.session_state["equity_bank_valuation"] = bank_valuation
            st.session_state.pop("equity_scenario_result", None)
            st.session_state.pop("valuation_reconciliation_result", None)
            st.session_state.pop("reverse_dcf_result", None)
            _audit_equity_action(
                "EQUITY_ANALYSIS_RUN",
                result.get("ticker", symbol.strip().upper()),
                {"market": market, "period": period},
            )
    
        except Exception as exc:
            st.error(str(exc))
    
    data = st.session_state.get("equity_result")
    dcf = st.session_state.get("equity_dcf")
    multistage_dcf = st.session_state.get("equity_multistage_dcf")
    bank_valuation = st.session_state.get("equity_bank_valuation")
    scenario_result = st.session_state.get("equity_scenario_result")
    
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
    
        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            ["Overview", "Fundamentals", "Technical", "Valuation", "Historical Analysis"]
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
            if is_bank(data):
                st.subheader("Bank Valuation Model · Residual Income")
                st.caption(
                    "Valuasi ekuitas bank berbasis book value dan residual income. "
                    "FCFF DCF dan Multi-Stage DCF tidak digunakan untuk bank."
                )
                if bank_valuation and bank_valuation.get("available"):
                    b1, b2, b3, b4 = st.columns(4)
                    b1.metric(
                        "Intrinsic Value / Share",
                        f"{bank_valuation['intrinsic_value_per_share']:,.2f} {bank_valuation['currency']}"
                    )
                    b2.metric(
                        "Current Price",
                        f"{bank_valuation['current_price']:,.2f} {bank_valuation['currency']}"
                    )
                    b3.metric(
                        "Upside / Downside",
                        f"{bank_valuation['upside_downside_pct']:+.2f}%"
                    )
                    b4.metric(
                        "Current P/B",
                        f"{bank_valuation['current_pb']:.2f}x"
                        if bank_valuation.get("current_pb") is not None else "N/A"
                    )
                    status = bank_valuation.get("data_quality_status", "REVIEW REQUIRED")
                    st.markdown(f"**Bank data quality: {status}**")
                    quality = bank_valuation.get("data_quality") or {}
                    freshness = quality.get("fundamental_freshness_status", "UNKNOWN")
                    gap_days = quality.get("price_fundamental_gap_days")
                    if freshness == "STALE":
                        st.error(f"Fundamental data freshness: STALE · {gap_days} calendar days between market price and latest financial statements. Refresh financials before relying on this valuation.")
                    elif freshness == "CURRENT":
                        st.caption(f"Fundamental data freshness: CURRENT · {gap_days} calendar-day gap.")
                    else:
                        st.warning("Fundamental data freshness: UNKNOWN · reporting dates are incomplete.")
                    metric_rows = [
                        {"Indicator": name, "Value (%)": value if value is not None else "Not supplied"}
                        for name, value in (quality.get("metrics") or {}).items()
                    ]
                    st.markdown("#### Bank operating and regulatory indicators")
                    st.dataframe(metric_rows, use_container_width=True, hide_index=True)
                    if quality.get("source_name") or quality.get("source_period"):
                        st.caption(
                            f"Source: {quality.get('source_name') or 'Not supplied'} · "
                            f"Reporting period: {quality.get('source_period') or 'Not supplied'} · "
                            f"Filing URL: {quality.get('source_url') or 'Not supplied'}"
                        )
                    if quality.get("checks"):
                        st.markdown("#### Fundamental consistency checks")
                        st.dataframe(quality["checks"], use_container_width=True, hide_index=True)
                    for note in quality.get("notes", []):
                        st.info(note)
                    st.caption(
                        f"Book value/share: {bank_valuation['book_value_per_share']:,.2f} "
                        f"{bank_valuation['currency']} · Implied P/B: "
                        f"{bank_valuation['implied_pb']:.2f}x · "
                        f"ROE source: {bank_valuation['roe_source']}"
                    )
                    if bank_valuation.get("fx_conversion_applied"):
                        st.caption(
                            f"FX conversion: {bank_valuation['financial_currency']} to "
                            f"{bank_valuation['currency']} · Rate: "
                            f"{bank_valuation['fx_rate_applied']:,.4f} · Reference date: "
                            f"{bank_valuation.get('fx_source_date') or 'Not specified'}"
                        )
                    st.markdown("#### Residual Income Forecast")
                    st.dataframe(
                        bank_valuation["forecast"].style.format({
                            "Opening book value / share": "{:,.2f}",
                            "Forecast ROE": "{:.2%}",
                            "Cost of equity": "{:.2%}",
                            "Residual income / share": "{:,.2f}",
                            "Present value of residual income": "{:,.2f}",
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
                    st.markdown("#### Bear / Base / Bull Scenarios")
                    st.dataframe(
                        bank_valuation["scenarios"].style.format({
                            "Expected ROE": "{:.2%}",
                            "Cost of equity": "{:.2%}",
                            "Stable growth": "{:.2%}",
                            "Intrinsic value / share": "{:,.2f}",
                            "Upside / downside (%)": "{:+.2f}%",
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
                    st.markdown("#### Sensitivity · ROE vs Cost of Equity")
                    st.caption(
                        "Nilai intrinsik per saham; asumsi stable growth dan periode forecast mengikuti Base Case."
                    )
                    sensitivity_display = bank_valuation["sensitivity"].copy()
                    sensitivity_display["Cost of equity"] = sensitivity_display["Cost of equity"].map(
                        lambda value: f"{value:.2%}"
                    )
                    st.dataframe(
                        sensitivity_display.style.format(
                            {column: "{:,.2f}" for column in sensitivity_display.columns if column != "Cost of equity"}
                        ),
                        use_container_width=True,
                        hide_index=True
                    )
                    with st.expander("Bank valuation assumptions and methodology"):
                        st.json(bank_valuation["assumptions"])
                        st.write(
                            f"Present value of forecast residual income: "
                            f"{bank_valuation['pv_residual_income']:,.2f} {bank_valuation['currency']}"
                        )
                        st.write(
                            f"Present value of terminal residual income: "
                            f"{bank_valuation['pv_terminal_residual_income']:,.2f} {bank_valuation['currency']}"
                        )
                    for warning in bank_valuation.get("warnings", []):
                        st.warning(warning)
                    if status == "VERIFIED":
                        st.success("STATUS: VERIFIED — source, reporting period, core data and all four bank ratios have been supplied. Independently inspect the linked official filing.")
                    elif status == "INSUFFICIENT DATA":
                        st.error("STATUS: INSUFFICIENT DATA — data inti bank belum cukup untuk analisis yang dapat ditinjau.")
                    else:
                        st.warning("STATUS: REVIEW REQUIRED — verifikasi laporan resmi dan lengkapi rasio yang belum tersedia. Nilai intrinsik belum boleh diperlakukan sebagai hasil tervalidasi.")
                else:
                    if bank_valuation:
                        status = bank_valuation.get("data_quality_status", "INSUFFICIENT DATA")
                        if status == "INSUFFICIENT DATA":
                            st.error(f"Bank data quality: {status}")
                        else:
                            st.warning(f"Bank data quality: {status}")
                        quality = bank_valuation.get("data_quality") or {}
                        for missing_field in quality.get("missing_fields", []):
                            st.write(f"Missing: {missing_field}")
                        for note in quality.get("notes", []):
                            st.info(note)
                        st.warning(bank_valuation.get("reason", "Bank valuation belum tersedia."))
                    else:
                        st.warning("Jalankan analisis saham terlebih dahulu.")

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
    
            if not is_bank(data):
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
        
                    ms_financial_currency = multistage_dcf.get('financial_currency', ms_currency)
                    ms_fx_rate = multistage_dcf.get('fx_rate_applied')
                    ms_fx_date = multistage_dcf.get('fx_source_date')
                    if ms_financial_currency != ms_currency:
                        st.caption('Currency conversion: {} to {} - Applied FX rate: {:,.2f} - Reference date: {}'.format(ms_financial_currency, ms_currency, ms_fx_rate, ms_fx_date or 'Not specified'))
                    else:
                        st.caption('Valuation currency: {}. No currency conversion applied.'.format(ms_currency))
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
        
                    if multistage_dcf.get("warnings"):
                        st.warning("Valuasi memiliki peringatan yang memerlukan review manual.")
                    elif multistage_dcf.get("data_quality_warnings"):
                        st.info("Terdapat catatan kualitas data dari sumber Yahoo Finance.")
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
                        st.info(warning)
        
                    for warning in multistage_dcf.get("warnings", []):
                        st.warning(warning)
        
                    if multistage_dcf.get("data_quality_override"):
                        st.warning(
                            "Perhitungan dilanjutkan dengan persetujuan manual "
                            "meskipun terdapat peringatan yang memerlukan review."
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
                scenario_result = render_scenario_analysis(data, fx_rate=fx_rate, years=years)
                st.session_state["equity_scenario_result"] = scenario_result
        

            else:
                st.info(
                    "Multi-Stage DCF dan FCFF scenario valuation dilewati untuk bank. "
                    "Gunakan Bank Valuation Model berbasis Residual Income di atas."
                )

        with tab5:
            render_historical_analysis(symbol, market)
    
        col1, col2 = st.columns(2)
    
        col1.download_button(
            "Download Excel report",
            make_excel_report(data, dcf, multistage_dcf=multistage_dcf, scenario_result=scenario_result, bank_valuation=bank_valuation),
            file_name=f"{data['ticker'].replace('.', '_')}_research.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            on_click=lambda: _audit_equity_export("xlsx", data["ticker"]),
        )
    
        col2.download_button(
            "Download PDF report",
            make_pdf_report(data, dcf, multistage_dcf=multistage_dcf, scenario_result=scenario_result, bank_valuation=bank_valuation),
            file_name=f"{data['ticker'].replace('.', '_')}_research.pdf",
            mime="application/pdf",
            use_container_width=True,
            on_click=lambda: _audit_equity_export("pdf", data["ticker"]),
        )
    
    else:
        st.info("Masukkan ticker saham, atur asumsi, lalu klik Analyze stock.")
