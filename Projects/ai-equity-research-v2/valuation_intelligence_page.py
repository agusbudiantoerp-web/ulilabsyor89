"""Peer valuation and reverse DCF Streamlit page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from market_engine import resolve_market_ticker
from peer_valuation import build_peer_comparison, compare_company_to_peers
from reverse_dcf import reverse_dcf_implied_growth, reverse_dcf_sensitivity
from market_data_provider import YahooFinanceProvider


def _peer_record(symbol: str, market: str) -> dict:
    resolved = resolve_market_ticker(symbol, market)
    ticker = resolved["ticker"]
    info = YahooFinanceProvider().fetch_info(ticker)
    return {
        "ticker": symbol.upper(),
        "provider_ticker": ticker,
        "industry": info.get("industry") or info.get("sector") or "Unknown",
        "currency": str(info.get("financialCurrency") or info.get("currency") or resolved.get("currency") or "unknown").upper(),
        "quote_currency": str(info.get("currency") or resolved.get("currency") or "unknown").upper(),
        "pe_ttm": info.get("trailingPE"),
        "pb": info.get("priceToBook"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "ev_sales": info.get("enterpriseToRevenue"),
        "roe": info.get("returnOnEquity"),
        "roic": info.get("returnOnCapitalEmployed"),
        "revenue_growth": info.get("revenueGrowth"),
        "operating_margin": info.get("operatingMargins"),
        "fiscal_year_end": (
            pd.to_datetime(info.get("lastFiscalYearEnd"), unit="s", utc=True).date().isoformat()
            if isinstance(info.get("lastFiscalYearEnd"), (int, float)) and info.get("lastFiscalYearEnd")
            else str(info.get("lastFiscalYearEnd") or "unknown")
        ),
        "source": "Yahoo Finance",
    }


def render_valuation_intelligence() -> None:
    st.subheader("Relative Valuation & Reverse DCF")
    st.caption("Peer multiples dan market-implied FCF growth. Periksa mata uang, periode fiskal, dan definisi metrik sebelum membandingkan.")
    with st.expander("Peer valuation comparison", expanded=True):
        c1, c2 = st.columns(2)
        market = c1.selectbox("Market peer", ["IDX", "US"], key="peer_market")
        symbols_raw = c2.text_input(
            "Daftar ticker peer (pisahkan koma)",
            "BBCA, BBRI, BMRI, BBNI" if market == "IDX" else "JPM, BAC, WFC, C",
            key="peer_symbols",
        )
        if st.button("Ambil data peer", key="peer_fetch", type="primary"):
            symbols = list(dict.fromkeys(
                item.strip().upper() for item in symbols_raw.replace("\n", ",").split(",") if item.strip()
            ))
            if len(symbols) < 2:
                st.warning("Masukkan minimal dua ticker.")
            else:
                records, errors = [], []
                with st.spinner("Mengambil metrik fundamental peer..."):
                    for symbol in symbols[:20]:
                        try:
                            records.append(_peer_record(symbol, market))
                        except Exception as exc:
                            errors.append({"ticker": symbol, "error": type(exc).__name__})
                st.session_state["peer_valuation_records"] = records
                st.session_state["peer_valuation_errors"] = errors
        records = st.session_state.get("peer_valuation_records", [])
        errors = st.session_state.get("peer_valuation_errors", [])
        if records:
            frame = pd.DataFrame(records)
            industries = sorted(frame["industry"].dropna().astype(str).unique())
            currencies = sorted(frame["currency"].dropna().astype(str).unique())
            c1, c2 = st.columns(2)
            industry = c1.selectbox("Industri peer", industries, key="peer_industry")
            currency = c2.selectbox("Mata uang laporan", currencies, key="peer_currency")
            try:
                comparison = build_peer_comparison(records, industry=industry, currency=currency)
                st.dataframe(pd.DataFrame(comparison["records"]), use_container_width=True, hide_index=True)
                if any(bool(row.get("currency_mismatch")) for row in comparison["records"]):
                    st.warning("Sebagian peer memiliki quote currency berbeda dari financial reporting currency. Periksa sumber dan satuan laporan sebelum membandingkan.")
                summary_rows = [
                    {"Metric": metric, **values}
                    for metric, values in comparison["metrics"].items()
                ]
                st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
                st.caption("Outlier ditandai dengan aturan IQR 1,5×; periksa manual sebelum mengecualikan perusahaan dari peer set.")
                selected = st.selectbox("Ticker untuk dibandingkan dengan median", comparison["tickers"])
                compared = compare_company_to_peers(comparison, selected)
                st.dataframe(pd.DataFrame([
                    {"Metric": metric, **values}
                    for metric, values in compared["metrics"].items()
                ]), use_container_width=True, hide_index=True)
                st.caption(comparison["limitations"])
                st.download_button(
                    "Unduh peer comparison CSV",
                    pd.DataFrame(comparison["records"]).to_csv(index=False).encode("utf-8-sig"),
                    file_name="peer_valuation_comparison.csv", mime="text/csv",
                )
            except Exception as exc:
                st.error(f"Peer comparison tidak dapat dihitung: {type(exc).__name__}: {exc}")
        if errors:
            with st.expander(f"Ticker gagal diambil ({len(errors)})"):
                st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)

    st.divider()
    with st.expander("Reverse DCF — implied FCF growth", expanded=True):
        st.caption(
            "Masukkan angka dalam satu mata uang dan satuan yang konsisten. Reverse DCF "
            "ini menggunakan constant FCF growth selama periode eksplisit."
        )
        with st.form("reverse_dcf_form"):
            c1, c2, c3 = st.columns(3)
            fcf = c1.number_input("Normalized current FCF", min_value=0.01, value=1000000000.0)
            price = c2.number_input("Harga pasar per saham", min_value=0.01, value=1000.0)
            shares = c3.number_input("Diluted shares", min_value=0.01, value=1000000000.0)
            c4, c5, c6 = st.columns(3)
            net_debt = c4.number_input("Net debt (+) / net cash (-)", value=0.0)
            wacc_pct = c5.number_input("WACC (%)", min_value=0.1, max_value=50.0, value=12.0)
            terminal_pct = c6.number_input("Terminal growth (%)", min_value=-5.0, max_value=15.0, value=3.0)
            fx_rate = st.number_input("FX rate: quote currency per 1 model currency", min_value=0.000001, value=1.0, help="Contoh: harga pasar dalam IDR, FCF/net debt dalam USD → masukkan jumlah IDR untuk 1 USD. Jika mata uang sama, gunakan 1.")
            c10, c11 = st.columns(2)
            model_currency = c10.text_input("Mata uang FCF / net debt", "USD").strip().upper()
            quote_currency = c11.text_input("Mata uang harga pasar", "IDR").strip().upper()
            c7, c8, c9 = st.columns(3)
            years = c7.number_input("Forecast years", min_value=1, max_value=30, value=5)
            lower_pct = c8.number_input("Batas growth bawah (%)", min_value=-90.0, max_value=99.0, value=-20.0)
            upper_pct = c9.number_input("Batas growth atas (%)", min_value=-89.0, max_value=300.0, value=100.0)
            calculate = st.form_submit_button("Hitung implied FCF growth", type="primary")
        if calculate:
            try:
                result = reverse_dcf_implied_growth(
                    current_fcf=fcf, market_price=price, diluted_shares=shares,
                    net_debt=net_debt, wacc=wacc_pct / 100.0,
                    terminal_growth=terminal_pct / 100.0,
                    fx_rate_quote_per_model=fx_rate,
                    forecast_years=int(years), lower_growth=lower_pct / 100.0,
                    upper_growth=upper_pct / 100.0,
                )
                st.session_state["reverse_dcf_result"] = {**result, "model_currency": model_currency, "quote_currency": quote_currency}
            except Exception as exc:
                st.error(f"Reverse DCF tidak dapat dihitung: {type(exc).__name__}: {exc}")
        result = st.session_state.get("reverse_dcf_result")
        if result:
            c1, c2, c3 = st.columns(3)
            c1.metric("Implied FCF growth", f"{result['implied_fcf_growth_pct']:.2f}%")
            c2.metric("Market price", f"{result['market_price']:,.2f}")
            c3.metric("Reconciled price", f"{result['implied_price']:,.2f}")
            st.caption("Komponen enterprise/equity valuation di bawah ditampilkan dalam mata uang model (FCF dan net debt). Harga pasar dan implied price ditampilkan dalam mata uang quote.")
            st.dataframe(pd.DataFrame([
                {"Komponen": "PV explicit FCF", "Nilai": result["pv_explicit_fcf"]},
                {"Komponen": "Terminal value (undiscounted)", "Nilai": result["terminal_value"]},
                {"Komponen": "PV terminal value", "Nilai": result["pv_terminal_value"]},
                {"Komponen": "Enterprise value", "Nilai": result["enterprise_value"]},
                {"Komponen": "Net debt", "Nilai": result["net_debt"]},
                {"Komponen": "Equity value target", "Nilai": result["target_equity_value"]},
                {"Komponen": "Terminal value share (%)", "Nilai": result["terminal_value_share_pct"]},
            ]), use_container_width=True, hide_index=True)
            sensitivity_rows = reverse_dcf_sensitivity(
                current_fcf=result["current_fcf"],
                market_price=result["market_price"],
                diluted_shares=result["diluted_shares"],
                net_debt=result["net_debt"],
                fx_rate_quote_per_model=result["fx_rate_quote_per_model"],
                forecast_years=result["forecast_years"],
                lower_growth=result["lower_growth"],
                upper_growth=result["upper_growth"],
                wacc_values=[
                    max(-0.9, result["wacc"] - 0.01),
                    result["wacc"],
                    result["wacc"] + 0.01,
                ],
                terminal_growth_values=[
                    result["terminal_growth"] - 0.005,
                    result["terminal_growth"],
                    result["terminal_growth"] + 0.005,
                ],
            )
            st.markdown("**Sensitivitas implied growth: WACC × terminal growth**")
            st.dataframe(pd.DataFrame(sensitivity_rows), use_container_width=True, hide_index=True)
            st.caption(f"Model currency: {result.get('model_currency', 'model')} · Quote currency: {result.get('quote_currency', 'quote')} · FX bridge: {result['fx_rate_quote_per_model']:,.6f} quote per model · market price in model currency: {result['market_price_model_currency']:,.4f}")
            st.warning(result["limitations"])
