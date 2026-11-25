"""Cross-market FX portfolio backtest, Monte Carlo and stress UI."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from daily_signal_engine import load_daily_history
from fx_portfolio_engine import combine_mixed_currency_returns
from portfolio_simulation import run_historical_stress_scenarios, run_portfolio_monte_carlo
from market_data_provider import YahooFinanceProvider


def _download_usdidr(period: str) -> pd.Series:
    frame = YahooFinanceProvider().fetch_history(
        "USDIDR=X", period=period, interval="1d", auto_adjust=True
    )
    close = frame["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna()


def render_cross_market_simulation() -> None:
    st.subheader("Cross-Market Portfolio · FX · Monte Carlo")
    st.caption("Gabungkan saham IDX dan US dalam satu mata uang dasar, lalu jalankan simulasi dan stress test.")
    with st.expander("Cross-market portfolio return", expanded=True):
        c1, c2 = st.columns(2)
        idx_raw = c1.text_input("Ticker IDX", "BBCA, BMRI", key="fx_idx_symbols")
        us_raw = c2.text_input("Ticker US", "MSFT, NVDA", key="fx_us_symbols")
        c3, c4 = st.columns(2)
        base = c3.selectbox("Base currency", ["IDR", "USD"], key="fx_base_currency")
        period = c4.selectbox("Historical period", ["1y", "2y", "5y"], index=1, key="fx_period")
        max_gap = st.number_input("Maksimum umur data FX (hari kalender)", 0, 7, 3)
        if st.button("Bangun cross-market portfolio", type="primary", key="fx_run"):
            idx_symbols = list(dict.fromkeys(x.strip().upper() for x in idx_raw.split(",") if x.strip()))
            us_symbols = list(dict.fromkeys(x.strip().upper() for x in us_raw.split(",") if x.strip()))
            overlap = set(idx_symbols) & set(us_symbols)
            if overlap:
                st.error("Ticker tidak boleh muncul sekaligus di IDX dan US: " + ", ".join(sorted(overlap)))
            elif not idx_symbols and not us_symbols:
                st.warning("Masukkan minimal satu ticker.")
            else:
                closes, currencies, errors = {}, {}, []
                with st.spinner("Mengunduh harga saham dan kurs USD/IDR..."):
                    for market, symbols, currency in [("IDX", idx_symbols, "IDR"), ("US", us_symbols, "USD")]:
                        for symbol in symbols:
                            try:
                                bars, _ = load_daily_history(symbol, market, period)
                                close = bars["Close"]
                                if isinstance(close, pd.DataFrame):
                                    close = close.iloc[:, 0]
                                closes[symbol] = close.dropna()
                                currencies[symbol] = currency
                            except Exception as exc:
                                errors.append({"ticker": symbol, "market": market, "error": type(exc).__name__})
                    needs_fx = any(currency != base for currency in currencies.values())
                    if needs_fx:
                        try:
                            fx = _download_usdidr(period)
                        except Exception as exc:
                            fx = None
                            errors.append({"ticker": "USDIDR=X", "market": "FX", "error": type(exc).__name__})
                    else:
                        fx = None
                if closes and fx is not None:
                    weights = {symbol: 1.0 / len(closes) for symbol in closes}
                    try:
                        result = combine_mixed_currency_returns(
                            closes, currencies, weights, fx, base,
                            max_fx_gap_days=int(max_gap),
                        )
                        st.session_state["cross_market_fx_result"] = result
                        st.session_state["cross_market_fx_errors"] = errors
                    except Exception as exc:
                        st.error(f"Cross-market conversion gagal: {type(exc).__name__}: {exc}")
                else:
                    st.error("Data harga saham atau kurs FX tidak cukup untuk menghitung portfolio.")
                    st.session_state["cross_market_fx_errors"] = errors
        result = st.session_state.get("cross_market_fx_result")
        if result:
            curve = result["curve"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Total return", f"{result['total_return_pct']:.2f}%")
            c2.metric("Base currency", result["base_currency"])
            c3.metric("Jumlah aset", len(result["weights"]))
            st.line_chart(curve["equity_index"])
            st.dataframe(result["asset_returns"].tail(10), use_container_width=True)
            st.caption(result["method"])
            st.download_button(
                "Unduh FX-adjusted equity curve CSV",
                curve.to_csv().encode("utf-8-sig"),
                file_name="cross_market_fx_equity_curve.csv", mime="text/csv",
            )
        errors = st.session_state.get("cross_market_fx_errors", [])
        if errors:
            with st.expander(f"Data gagal ({len(errors)})"):
                st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("**Monte Carlo portfolio simulation**")
    result = st.session_state.get("cross_market_fx_result")
    if not result:
        st.info("Bangun cross-market portfolio terlebih dahulu untuk mengaktifkan simulasi.")
        return
    c1, c2, c3 = st.columns(3)
    simulations = c1.number_input("Jumlah simulasi", min_value=100, max_value=100000, value=5000, step=500)
    horizon = c2.number_input("Horizon (sesi)", min_value=1, max_value=2520, value=252)
    seed = c3.number_input("Random seed", min_value=0, max_value=2147483647, value=42)
    if st.button("Jalankan Monte Carlo", key="fx_monte_carlo"):
        try:
            mc = run_portfolio_monte_carlo(
                result["asset_returns"], result["weights"],
                simulations=int(simulations), horizon_days=int(horizon), seed=int(seed),
            )
            st.session_state["cross_market_monte_carlo_result"] = mc
        except Exception as exc:
            st.error(f"Monte Carlo gagal: {type(exc).__name__}: {exc}")
    mc = st.session_state.get("cross_market_monte_carlo_result")
    if mc:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Median return", f"{mc['median_return_pct']:.2f}%")
        c2.metric("VaR loss (95%)", f"{mc['var_loss_pct']:.2f}%")
        c3.metric("CVaR loss (95%)", f"{mc['cvar_loss_pct']:.2f}%")
        c4.metric("Probability of loss", f"{mc['probability_of_loss_pct']:.1f}%")
        st.dataframe(pd.DataFrame([
            {"Percentile": key, "Return (%)": value}
            for key, value in mc["return_percentiles_pct"].items()
        ]), use_container_width=True, hide_index=True)
        st.caption(mc["assumptions"])

    st.markdown("**User-defined stress scenario**")
    with st.form("cross_market_stress_form"):
        shock_inputs = {}
        columns = st.columns(min(4, len(result["weights"])))
        for index, symbol in enumerate(result["weights"]):
            shock_inputs[symbol] = columns[index % len(columns)].number_input(
                f"{symbol} shock (%)", min_value=-100.0, max_value=500.0,
                value=-20.0, key=f"fx_stress_{symbol}",
            ) / 100.0
        run_stress = st.form_submit_button("Hitung stress test")
    if run_stress:
        try:
            stress = run_historical_stress_scenarios(
                result["asset_returns"], result["weights"], shock_inputs,
            )
            st.session_state["cross_market_stress_result"] = stress
        except Exception as exc:
            st.error(f"Stress test gagal: {type(exc).__name__}: {exc}")
    stress = st.session_state.get("cross_market_stress_result")
    if stress:
        st.metric("Stress portfolio return", f"{stress['portfolio_return_pct']:.2f}%")
        st.dataframe(pd.DataFrame([
            {"Ticker": ticker, "Contribution (%)": value}
            for ticker, value in stress["asset_contributions_pct"].items()
        ]), use_container_width=True, hide_index=True)
        st.caption(stress["method"])
