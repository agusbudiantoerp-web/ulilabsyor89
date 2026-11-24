"""Streamlit UI extensions kept inside the existing five-menu workspace."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from daily_signal_engine import load_daily_history
from market_intelligence import (
    BENCHMARKS, audit_fundamental_record, audit_price_history,
    classify_market_regime, relative_strength,
)
from multi_asset_backtest import run_multi_asset_backtest
from portfolio_store import list_books, load_book, save_book
from research_reporting import build_excel_report, build_pdf_report


def _download_benchmark(market: str, period: str) -> pd.DataFrame:
    import yfinance as yf
    ticker = BENCHMARKS[market]
    frame = yf.download(ticker, period=period, interval="1d", auto_adjust=True,
                        progress=False, threads=False)
    if frame is None or frame.empty:
        raise ValueError(f"Benchmark {ticker} tidak tersedia dari Yahoo Finance.")
    return frame


def render_market_intelligence() -> None:
    st.subheader("Market Regime, Relative Strength & Data Quality")
    st.caption("Analisis kondisi indeks acuan dan kekuatan relatif saham. Menggunakan daily close yang telah tersedia.")
    with st.expander("Buka Market Intelligence", expanded=False):
        c1, c2, c3 = st.columns(3)
        market = c1.selectbox("Market acuan", ["IDX", "US"], key="mi_market")
        ticker = c2.text_input("Ticker saham", "BBCA" if market == "IDX" else "MSFT", key="mi_ticker")
        period = c3.selectbox("Histori", ["1y", "2y", "5y"], index=1, key="mi_period")
        if st.button("Analisis market regime & relative strength", key="mi_run", type="primary"):
            try:
                with st.spinner("Mengambil harga saham dan indeks acuan..."):
                    asset, meta = load_daily_history(ticker.strip(), market, period)
                    benchmark = _download_benchmark(market, period)
                    regime = classify_market_regime(benchmark)
                    strength = relative_strength(asset, benchmark)
                    quality = audit_price_history(asset)
                    fundamentals = {}
                    try:
                        import yfinance as yf
                        info = yf.Ticker(meta["ticker"]).get_info()
                        if isinstance(info, dict):
                            fundamentals = {
                                "trailingPE": info.get("trailingPE"), "forwardPE": info.get("forwardPE"),
                                "priceToBook": info.get("priceToBook"), "returnOnEquity": info.get("returnOnEquity"),
                                "returnOnAssets": info.get("returnOnAssets"), "debtToEquity": info.get("debtToEquity"),
                                "revenueGrowth": info.get("revenueGrowth"), "earningsGrowth": info.get("earningsGrowth"),
                                "marketCap": info.get("marketCap"), "currency": info.get("currency"),
                                "financialCurrency": info.get("financialCurrency"),
                            }
                    except Exception as exc:
                        fundamentals = {"provider_error": f"{type(exc).__name__}: {exc}"}
                    fundamental_quality = audit_fundamental_record(fundamentals)
                st.session_state["market_intelligence_result"] = {
                    "ticker": meta.get("ticker", ticker.upper()), "market": market,
                    "benchmark": BENCHMARKS[market], "regime": regime, "strength": strength,
                    "quality": quality, "fundamental_quality": fundamental_quality,
                }
            except Exception as exc:
                st.error(f"Market Intelligence gagal: {type(exc).__name__}: {exc}")
        result = st.session_state.get("market_intelligence_result")
        if result:
            regime = result["regime"]
            st.markdown(f"**{result['market']} · {result['benchmark']} · {regime['bar_date']}**")
            st.metric("Market regime", regime["regime"])
            r1, r2, r3 = st.columns(3)
            r1.metric("Return indeks 20 sesi", f"{regime['return_20d_pct']:.2f}%")
            r2.metric("Return indeks 60 sesi", f"{regime['return_60d_pct']:.2f}%" if regime["return_60d_pct"] is not None else "N/A")
            r3.metric("Harga vs EMA200", "Di atas" if regime["benchmark_close"] > regime["ema200"] else "Di bawah")
            st.info(regime["risk_note"])
            st.markdown(f"**Relative strength: {result['ticker']} vs {result['benchmark']}**")
            strength_rows = []
            for horizon, values in result["strength"]["periods"].items():
                strength_rows.append({"Horizon": horizon, "Return saham %": values["asset_return_pct"],
                                      "Return benchmark %": values["benchmark_return_pct"],
                                      "Outperformance %": values["relative_strength_pct"]})
            if strength_rows:
                st.dataframe(pd.DataFrame(strength_rows), use_container_width=True, hide_index=True)
            st.caption(result["strength"]["note"])
            quality = result["quality"]
            st.markdown(f"**Price data quality: {quality['status']}** · {quality.get('rows', 0)} bars · latest {quality.get('last_bar', 'N/A')}")
            st.dataframe(pd.DataFrame(quality["checks"]), use_container_width=True, hide_index=True)
            fquality = result["fundamental_quality"]
            st.markdown(f"**Fundamental data quality: {fquality['status']}**")
            if fquality["checks"]:
                st.dataframe(pd.DataFrame(fquality["checks"]), use_container_width=True, hide_index=True)
            st.caption("Regime dan relative strength adalah indikator historis berbasis aturan, bukan prediksi. Benchmark IDX menggunakan ^JKSE dan US menggunakan SPY; perbandingan price-only tidak memasukkan dividen.")


def render_portfolio_persistence(positions: pd.DataFrame) -> None:
    st.subheader("Simpan & Muat Portfolio")
    st.caption("Penyimpanan portfolio: SQLite lokal (file tidak dienkripsi). Lindungi komputer dan file database; penyimpanan cloud belum diaktifkan karena belum ada isolasi akun per pengguna.")
    with st.expander("Kelola portfolio tersimpan", expanded=False):
        try:
            books = list_books()
        except Exception as exc:
            st.error(f"Daftar portfolio tidak dapat dibaca: {type(exc).__name__}: {exc}")
            return
        names = {f"{b['name']} · {b['id']}": b["id"] for b in books}
        c1, c2 = st.columns([2, 1])
        selected_label = c1.selectbox("Portfolio tersimpan", ["— pilih —"] + list(names), key="saved_portfolio_select")
        if c2.button("Muat portfolio", key="load_saved_portfolio"):
            if selected_label in names:
                try:
                    loaded = load_book(names[selected_label])
                    st.session_state["portfolio_input"] = loaded
                    st.session_state.pop("portfolio_result", None)
                    st.success("Portfolio dimuat. Jalankan kembali Hitung portfolio intelligence.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Gagal memuat portfolio: {type(exc).__name__}: {exc}")
        name = st.text_input("Nama portfolio", value="Portfolio utama", key="save_portfolio_name")
        if st.button("Simpan posisi saat ini", key="save_portfolio_button", type="primary"):
            try:
                import uuid
                existing_id = names.get(selected_label)
                book_id = existing_id or uuid.uuid4().hex
                count = save_book(book_id, name.strip(), positions)
                st.success(f"{count} posisi disimpan. ID: {book_id}")
                st.rerun()
            except Exception as exc:
                st.error(f"Gagal menyimpan portfolio: {type(exc).__name__}: {exc}")
        if books:
            st.dataframe(pd.DataFrame(books), use_container_width=True, hide_index=True)
        else:
            st.info("Belum ada portfolio tersimpan.")


def render_multi_asset_backtest() -> None:
    st.subheader("Multi-Asset Portfolio Backtest")
    st.caption("Uji strategi pada beberapa saham sekaligus dengan sinyal yang digeser satu sesi untuk mencegah look-ahead.")
    with st.expander("Buka Multi-Asset Backtest", expanded=False):
        c1, c2, c3 = st.columns(3)
        market = c1.selectbox("Market portfolio", ["IDX", "US"], key="mab_market")
        period = c2.selectbox("Periode histori", ["2y", "5y", "10y"], index=1, key="mab_period")
        max_positions = c3.slider("Maksimum posisi bersamaan", 1, 20, 8, key="mab_max_positions")
        raw = st.text_area("Ticker dipisahkan koma", "BBCA, BBRI, BMRI, TLKM, ASII" if market == "IDX" else "AAPL, MSFT, NVDA, AMZN, GOOGL",
                           key="mab_tickers")
        c4, c5, c6 = st.columns(3)
        capital = c4.number_input("Modal awal", min_value=1.0, value=100_000_000.0 if market == "IDX" else 100_000.0, step=1_000_000.0, key="mab_capital")
        fee = c5.number_input("Fee per sisi (bps)", min_value=0.0, max_value=500.0, value=10.0, key="mab_fee")
        slippage = c6.number_input("Slippage per sisi (bps)", min_value=0.0, max_value=500.0, value=10.0, key="mab_slippage")
        cap_weight = st.slider("Batas bobot per saham (%)", 5, 100, 20, key="mab_weight")
        if st.button("Jalankan multi-asset backtest", key="mab_run", type="primary"):
            symbols = list(dict.fromkeys(x.strip().upper() for x in raw.replace("\n", ",").split(",") if x.strip()))
            if not symbols:
                st.warning("Masukkan minimal satu ticker.")
            else:
                bars_by_symbol, errors = {}, []
                with st.spinner(f"Mengunduh histori {len(symbols)} ticker..."):
                    for symbol in symbols:
                        try:
                            bars, _ = load_daily_history(symbol, market, period)
                            bars_by_symbol[symbol] = bars
                        except Exception as exc:
                            errors.append({"ticker": symbol, "error": f"{type(exc).__name__}: {exc}"})
                    benchmark = None
                    try:
                        benchmark = _download_benchmark(market, period)
                    except Exception as exc:
                        errors.append({"ticker": BENCHMARKS[market], "error": f"{type(exc).__name__}: {exc}"})
                try:
                    result = run_multi_asset_backtest(
                        bars_by_symbol, benchmark_bars=benchmark, initial_capital=capital,
                        fee_bps=fee, slippage_bps=slippage, max_positions=max_positions,
                        max_weight_pct=cap_weight,
                    )
                    st.session_state["multi_asset_backtest_result"] = result
                    st.session_state["multi_asset_backtest_errors"] = errors
                except Exception as exc:
                    st.error(f"Multi-asset backtest gagal: {type(exc).__name__}: {exc}")
        result = st.session_state.get("multi_asset_backtest_result")
        if result:
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Total return", f"{result['total_return_pct']:.2f}%")
            m2.metric("CAGR", f"{result['cagr_pct']:.2f}%")
            m3.metric("Max drawdown", f"{result['max_drawdown_pct']:.2f}%")
            m4.metric("Sharpe", f"{result['sharpe_ratio']:.2f}")
            m5.metric("Final equity", f"{result['final_equity']:,.2f}")
            st.caption(f"Benchmark price return: {result['benchmark_return_pct']:.2f}%" if result["benchmark_return_pct"] is not None else "Benchmark tidak tersedia.")
            curve = pd.DataFrame(result["curve"])
            if not curve.empty:
                curve["date"] = pd.to_datetime(curve["date"])
                st.line_chart(curve.set_index("date")["equity"])
            st.dataframe(pd.DataFrame([{"Ticker": x} for x in result["active_symbols"]]), use_container_width=True, hide_index=True)
            st.caption(result["method"])
            st.warning(result["limitations"])
            errors = st.session_state.get("multi_asset_backtest_errors", [])
            if errors:
                with st.expander(f"Data gagal ({len(errors)})"):
                    st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)


def render_research_exports(latest: dict | None, history: list | None) -> None:
    st.subheader("Research Pack & Export")
    st.caption("Ekspor ringkasan performa dan histori sinyal ke Excel atau PDF.")
    frame = pd.DataFrame(history or [])
    metrics = {}
    if latest:
        counts = latest.get("counts", {})
        metrics = {"Scan ID": latest.get("scan_id"), "Scanned": counts.get("scanned"),
                   "Success": counts.get("success"), "Failed": counts.get("failed"),
                   "BUY candidate": counts.get("buy_candidate"), "WATCH": counts.get("watch"),
                   "NO TRADE": counts.get("no_trade")}
    market_result = st.session_state.get("market_intelligence_result")
    if market_result:
        regime = market_result.get("regime", {})
        metrics.update({
            "Market regime": regime.get("regime"),
            "Market index date": regime.get("bar_date"),
            "Index return 20 sessions %": regime.get("return_20d_pct"),
        })
    multi_result = st.session_state.get("multi_asset_backtest_result")
    if multi_result:
        metrics.update({
            "Multi-asset return %": multi_result.get("total_return_pct"),
            "Multi-asset CAGR %": multi_result.get("cagr_pct"),
            "Multi-asset max drawdown %": multi_result.get("max_drawdown_pct"),
            "Multi-asset Sharpe": multi_result.get("sharpe_ratio"),
            "Multi-asset benchmark return %": multi_result.get("benchmark_return_pct"),
        })
    c1, c2 = st.columns(2)
    c1.download_button("Unduh Research Pack Excel", build_excel_report(
        portfolio=st.session_state.get("portfolio_report_frame"),
        metrics=metrics, history=frame,
    ), file_name="ai_equity_research_pack.xlsx",
       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c2.download_button("Unduh Ringkasan PDF", build_pdf_report(
        "AI Equity Research — Performance Summary", metrics,
        notes=["Forward outcomes are observations, not forecasts.",
               "Yahoo Finance data may be incomplete or revised.",
               "No broker execution is performed."],
    ), file_name="ai_equity_research_summary.pdf", mime="application/pdf")
