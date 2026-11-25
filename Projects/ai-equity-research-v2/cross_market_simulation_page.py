"""Cross-market FX portfolio backtest, Monte Carlo and stress UI."""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from daily_signal_engine import load_daily_history
from fx_portfolio_engine import combine_mixed_currency_returns
from portfolio_simulation import (
    run_historical_stress_scenarios, run_portfolio_monte_carlo,
    run_factor_stress_scenario, run_regime_switching_monte_carlo,
    run_block_bootstrap_monte_carlo,
)
from market_data_provider import YahooFinanceProvider
from transaction_aware_portfolio import run_transaction_aware_portfolio


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
        max_price_gap = st.number_input("Maksimum umur harga penutupan (hari kalender)", 0, 14, 7)
        if st.button("Bangun cross-market portfolio", type="primary", key="fx_run"):
            for stale_key in (
                "cross_market_fx_result", "cross_market_price_closes",
                "cross_market_asset_currencies", "cross_market_usdidr_close",
                "cross_market_monte_carlo_result", "cross_market_regime_monte_carlo_result",
                "cross_market_transaction_replay_result", "cross_market_block_bootstrap_result", "cross_market_stress_result",
                "cross_market_factor_stress_result",
            ):
                st.session_state.pop(stale_key, None)
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
                        st.session_state["cross_market_price_closes"] = closes
                        st.session_state["cross_market_asset_currencies"] = currencies
                        st.session_state["cross_market_usdidr_close"] = fx
                        st.session_state["cross_market_fx_errors"] = errors
                        for result_key in ("cross_market_monte_carlo_result", "cross_market_regime_monte_carlo_result", "cross_market_transaction_replay_result", "cross_market_stress_result", "cross_market_factor_stress_result"):
                            st.session_state.pop(result_key, None)
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
            st.markdown("**Base-currency asset returns**")
            st.dataframe(result["asset_returns"].tail(10), use_container_width=True)
            st.markdown("**FX contribution by asset (percentage points)**")
            st.dataframe(result["asset_fx_contribution_pct"].tail(10), use_container_width=True)
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

    with st.expander("Historical block bootstrap Monte Carlo", expanded=False):
        st.caption(
            "Resample blok return historis gabungan seluruh aset untuk mempertahankan korelasi antar-aset "
            "dan pola serial pendek. Pilih panjang blok sesuai karakter data."
        )
        block_size = st.slider(
            "Panjang blok historis (sesi)", min_value=1, max_value=20,
            value=5, key="fx_bootstrap_block_size",
        )
        if st.button("Jalankan block bootstrap Monte Carlo", key="fx_block_bootstrap_run"):
            try:
                bootstrap_result = run_block_bootstrap_monte_carlo(
                    result["asset_returns"], result["weights"],
                    simulations=int(simulations), horizon_days=int(horizon),
                    block_size=int(block_size), seed=int(seed),
                )
                st.session_state["cross_market_block_bootstrap_result"] = bootstrap_result
            except Exception as exc:
                st.error(f"Block bootstrap gagal: {type(exc).__name__}: {exc}")
        bootstrap_result = st.session_state.get("cross_market_block_bootstrap_result")
        if bootstrap_result:
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Median return", f"{bootstrap_result['median_return_pct']:.2f}%")
            b2.metric("VaR loss", f"{bootstrap_result['var_loss_pct']:.2f}%")
            b3.metric("CVaR loss", f"{bootstrap_result['cvar_loss_pct']:.2f}%")
            b4.metric("Probability of loss", f"{bootstrap_result['probability_of_loss_pct']:.1f}%")
            st.dataframe(pd.DataFrame([
                {"Percentile": key, "Return (%)": value}
                for key, value in bootstrap_result["return_percentiles_pct"].items()
            ]), use_container_width=True, hide_index=True)
            st.caption(bootstrap_result["assumptions"])

    with st.expander("Regime-switching Monte Carlo (calm / stress)", expanded=False):
        st.caption(
            "Label historis dibentuk dari volatilitas rolling 20 sesi portfolio. "
            "Probabilitas transisi Markov diisi pengguna; model bukan prediksi regime."
        )
        c1, c2, c3 = st.columns(3)
        vol_threshold = c1.number_input(
            "Ambang volatilitas tahunan (%)", min_value=5.0, max_value=150.0,
            value=30.0, step=5.0, key="fx_regime_vol_threshold",
        ) / 100.0
        calm_to_stress = c2.slider(
            "Probabilitas calm → stress", min_value=0.0, max_value=1.0,
            value=0.05, step=0.01, key="fx_regime_calm_to_stress",
        )
        stress_to_calm = c3.slider(
            "Probabilitas stress → calm", min_value=0.0, max_value=1.0,
            value=0.20, step=0.01, key="fx_regime_stress_to_calm",
        )
        weighted_history = result["asset_returns"].mul(pd.Series(result["weights"]), axis=1).sum(axis=1)
        rolling_volatility = weighted_history.rolling(20, min_periods=20).std() * (252 ** 0.5)
        regime_labels = rolling_volatility.dropna().apply(
            lambda value: "stress" if value >= vol_threshold else "calm"
        )
        regime_counts = regime_labels.value_counts().reindex(["calm", "stress"], fill_value=0)
        st.write({
            "Calm observations": int(regime_counts["calm"]),
            "Stress observations": int(regime_counts["stress"]),
            "Initial regime": str(regime_labels.iloc[-1]) if not regime_labels.empty else "Unavailable",
        })
        use_empirical_transitions = st.checkbox(
            "Gunakan probabilitas transisi historis (Laplace smoothing)",
            value=True, key="fx_regime_empirical_transitions",
            help="Estimasi frekuensi transisi dari label historis yang terlihat. Ini deskriptif/in-sample, bukan probabilitas prediksi.",
        )
        if use_empirical_transitions:
            empirical_transition = estimate_regime_transition_matrix(regime_labels)
            transition_matrix = empirical_transition["transition_matrix"]
            st.write("Transisi historis (baris = regime saat ini, kolom = regime berikutnya):")
            st.dataframe(pd.DataFrame(
                transition_matrix, index=["calm", "stress"], columns=["calm", "stress"],
            ), use_container_width=True)
            st.caption(empirical_transition["method"])
        else:
            transition_matrix = [
                [1.0 - calm_to_stress, calm_to_stress],
                [stress_to_calm, 1.0 - stress_to_calm],
            ]
        if (regime_counts < 20).any():
            st.warning("Setiap regime memerlukan minimal 20 observasi. Ubah ambang volatilitas atau periode historis.")
        if st.button("Jalankan regime-switching Monte Carlo", key="fx_regime_monte_carlo"):
            try:
                aligned_returns = result["asset_returns"].loc[regime_labels.index]
                regime_result = run_regime_switching_monte_carlo(
                    aligned_returns, result["weights"], regime_labels,
                    transition_matrix,
                    initial_regime=str(regime_labels.iloc[-1]),
                    simulations=int(simulations), horizon_days=int(horizon), seed=int(seed),
                )
                regime_result["transition_estimation"] = (
                    empirical_transition["method"] if use_empirical_transitions else "User-supplied transition probabilities."
                )
                regime_result["volatility_threshold_pct"] = vol_threshold * 100.0
                st.session_state["cross_market_regime_monte_carlo_result"] = regime_result
            except Exception as exc:
                st.error(f"Regime-switching Monte Carlo gagal: {type(exc).__name__}: {exc}")
        regime_result = st.session_state.get("cross_market_regime_monte_carlo_result")
        if regime_result:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Median return", f"{regime_result['median_return_pct']:.2f}%")
            r2.metric("VaR loss", f"{regime_result['var_loss_pct']:.2f}%")
            r3.metric("CVaR loss", f"{regime_result['cvar_loss_pct']:.2f}%")
            r4.metric("Probability of loss", f"{regime_result['probability_of_loss_pct']:.1f}%")
            st.write("Final regime counts:", regime_result["final_regime_counts"])
            st.caption(regime_result["assumptions"])

    with st.expander("Transaction-aware portfolio replay (CSV event ledger)", expanded=False):
        st.caption(
            "Replay BUY/SELL/dividend/fee/tax/deposit/withdrawal events against downloaded daily prices. "
            "This uses explicit fill data; it does not place orders or infer broker fills."
        )
        st.caption(
            "CSV columns: date,event_type,amount,ticker,quantity,price,amount_currency,settlement_date,notes. "
            f"All amount values must use base currency ({result['base_currency']}); for foreign-asset trades/dividends, explicitly convert cash amounts before entry. "
            "The price field remains in the asset's local quote currency; amount_currency, if supplied, must equal base currency. "
            "settlement_date is optional; blank means same-day settlement."
        )
        template = pd.DataFrame(columns=[
            "date", "event_type", "amount", "ticker", "quantity", "price",
            "amount_currency", "settlement_date", "notes",
        ])
        st.download_button(
            "Unduh template transaction ledger CSV",
            template.to_csv(index=False).encode("utf-8-sig"),
            file_name="transaction_aware_ledger_template.csv", mime="text/csv",
            key="transaction_ledger_template_download",
        )
        uploaded_ledger = st.file_uploader(
            "Unggah event ledger CSV", type=["csv"], key="transaction_aware_ledger_upload",
        )
        initial_cash = st.number_input(
            f"Saldo kas awal ({result['base_currency']})", min_value=0.0,
            value=0.0, key="transaction_aware_initial_cash",
        )
        initial_positions_raw = st.text_input(
            "Posisi saham awal (TICKER:jumlah, pisahkan koma)",
            value="", key="transaction_aware_initial_positions",
        )
        if st.button("Jalankan transaction-aware replay", key="transaction_aware_replay_run"):
            try:
                if uploaded_ledger is None:
                    raise ValueError("Unggah CSV event ledger terlebih dahulu.")
                event_frame = pd.read_csv(uploaded_ledger)
                opening_positions = {}
                if initial_positions_raw.strip():
                    for item in initial_positions_raw.split(","):
                        parts = item.strip().split(":")
                        if len(parts) != 2 or not parts[0].strip():
                            raise ValueError("Format posisi awal harus TICKER:jumlah.")
                        ticker, shares = parts[0].strip().upper(), float(parts[1].strip())
                        if ticker in opening_positions or not math.isfinite(shares) or shares <= 0:
                            raise ValueError("Posisi awal harus unik dan jumlahnya positif.")
                        opening_positions[ticker] = shares
                replay = run_transaction_aware_portfolio(
                    st.session_state.get("cross_market_price_closes") or {},
                    st.session_state.get("cross_market_asset_currencies") or {},
                    event_frame,
                    base_currency=result["base_currency"],
                    usd_idr_close=st.session_state.get("cross_market_usdidr_close"),
                    initial_cash=float(initial_cash),
                    initial_positions=opening_positions,
                    max_fx_gap_days=int(max_gap),
                    max_price_gap_days=int(max_price_gap),
                )
                st.session_state["cross_market_transaction_replay_result"] = replay
            except Exception as exc:
                st.error(f"Transaction-aware replay gagal: {type(exc).__name__}: {exc}")
        replay = st.session_state.get("cross_market_transaction_replay_result")
        if replay:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Ending portfolio value", f"{replay['ending_portfolio_value']:,.2f} {replay['base_currency']}")
            r2.metric("Total TWR", f"{replay['total_twr_pct']:.2f}%")
            r3.metric("Available cash", f"{replay['ending_available_cash']:,.2f}")
            r4.metric("Pending settlements", len(replay["pending_settlements"]))
            st.line_chart(replay["curve"]["twr_equity_index"])
            st.dataframe(replay["curve"].drop(columns=["position_values"]).tail(20), use_container_width=True)
            st.download_button(
                "Unduh transaction-aware equity curve CSV",
                replay["curve"].drop(columns=["position_values"]).to_csv().encode("utf-8-sig"),
                file_name="transaction_aware_equity_curve.csv", mime="text/csv",
                key="transaction_aware_curve_download",
            )
            st.caption(
                f"Settled cash: {replay['ending_cash']:,.2f} · "
                f"Unsettled receivables: {replay['ending_unsettled_receivables']:,.2f} · "
                f"Unsettled payables: {replay['ending_unsettled_payables']:,.2f}"
            )
            if not replay["pending_settlements"].empty:
                st.dataframe(replay["pending_settlements"], use_container_width=True, hide_index=True)
            st.caption(replay["method"])
            st.caption(replay["limitations"])

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


    st.divider()
    st.markdown("**Factor stress: FX, interest rates & sector**")
    st.caption(
        "FX beta dibuat dari mata uang aset dan base currency. Beta suku bunga dan sektor "
        "harus diisi pengguna; ini pendekatan linear, bukan sensitivitas issuer yang terverifikasi."
    )
    factor_rows = []
    for symbol, currency in result["asset_currencies"].items():
        fx_beta = 1.0 if currency == "USD" and result["base_currency"] == "IDR" else (
            -1.0 if currency == "IDR" and result["base_currency"] == "USD" else 0.0
        )
        factor_rows.append({
            "ticker": symbol, "fx_usdidr_beta": fx_beta,
            "interest_rate_beta": 0.0, "sector_beta": 0.0,
        })
    factor_frame = pd.DataFrame(factor_rows)
    factor_key = "cross_market_factor_exposures_" + "_".join(sorted(result["weights"]))
    if factor_key not in st.session_state:
        st.session_state[factor_key] = factor_frame
    exposures_frame = st.data_editor(
        st.session_state[factor_key], use_container_width=True, hide_index=True,
        key="cross_market_factor_exposure_editor_" + "_".join(sorted(result["weights"])),
    )
    with st.form("cross_market_factor_shock_form"):
        c1, c2, c3 = st.columns(3)
        fx_shock = c1.number_input("USD/IDR shock (%)", value=-10.0) / 100.0
        rate_shock = c2.number_input("Interest-rate shock (percentage points)", value=1.0, help="Beta di tabel berarti estimasi perubahan return aset (%) untuk setiap kenaikan suku bunga 1 percentage point.") / 100.0
        sector_shock = c3.number_input("Sector shock (%)", value=-15.0) / 100.0
        factor_submit = st.form_submit_button("Hitung factor stress")
    if factor_submit:
        try:
            exposures = {
                row["ticker"]: {
                    "fx_usdidr": float(row["fx_usdidr_beta"]),
                    "interest_rate": float(row["interest_rate_beta"]),
                    "sector": float(row["sector_beta"]),
                }
                for row in exposures_frame.to_dict("records")
            }
            factor_result = run_factor_stress_scenario(
                result["weights"], exposures,
                {"fx_usdidr": fx_shock, "interest_rate": rate_shock, "sector": sector_shock},
            )
            st.session_state["cross_market_factor_stress_result"] = factor_result
        except Exception as exc:
            st.error(f"Factor stress gagal: {type(exc).__name__}: {exc}")
    factor_result = st.session_state.get("cross_market_factor_stress_result")
    if factor_result:
        st.metric("Factor stress portfolio return", f"{factor_result['portfolio_return_pct']:.2f}%")
        st.dataframe(pd.DataFrame([
            {"Ticker": ticker, "Estimated impact (%)": value}
            for ticker, value in factor_result["asset_impacts_pct"].items()
        ]), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame([
            {"Factor": factor, "Contribution (%)": value}
            for factor, value in factor_result["factor_contributions_pct"].items()
        ]), use_container_width=True, hide_index=True)
        st.caption(factor_result["method"])
