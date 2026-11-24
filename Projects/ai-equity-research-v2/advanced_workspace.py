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
from portfolio_store import delete_book, list_books, load_book, save_book
from research_reporting import build_excel_report, build_pdf_report
from security_controls import has_permission, require_permission, record_audit_event
from research_run_store import delete_run, get_run, list_runs, save_run


def _audit_event_safely(
    owner_id: str, action: str, resource_type: str, resource_id: str = "",
    details: dict | None = None,
) -> None:
    try:
        record_audit_event(
            owner_id, st.session_state.get("_auth_role"), action,
            resource_type, resource_id, details=details or {},
        )
    except Exception as exc:
        st.warning(f"Data berhasil diproses, tetapi audit event gagal dicatat: {type(exc).__name__}: {exc}")


def _download_benchmark(market: str, period: str) -> pd.DataFrame:
    import yfinance as yf
    ticker = BENCHMARKS[market]
    frame = yf.download(ticker, period=period, interval="1d", auto_adjust=True,
                        progress=False, threads=False)
    if frame is None or frame.empty:
        raise ValueError(f"Benchmark {ticker} tidak tersedia dari Yahoo Finance.")
    return frame


def render_market_intelligence() -> None:
    require_permission(st.session_state.get("_auth_role"), "run_analysis")
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


def render_portfolio_persistence(positions: pd.DataFrame, owner_id: str) -> None:
    st.subheader("Simpan & Muat Portfolio")
    st.caption("Portfolio disimpan dengan owner ID OIDC. PostgreSQL digunakan bila DATABASE_URL tersedia; jika tidak, sistem memakai SQLite lokal yang tidak dienkripsi dan dapat bersifat sementara di hosting.")
    if not str(owner_id or "").strip():
        st.error("Owner identity tidak tersedia; penyimpanan portfolio dikunci.")
        return
    try:
        require_permission(st.session_state.get("_auth_role"), "manage_portfolio")
    except PermissionError:
        st.error("Role Anda tidak memiliki izin mengelola portfolio.")
        return
    with st.expander("Kelola portfolio tersimpan", expanded=False):
        try:
            books = list_books(owner_id=owner_id)
        except Exception as exc:
            st.error(f"Daftar portfolio tidak dapat dibaca: {type(exc).__name__}: {exc}")
            return
        names = {f"{b['name']} · {b['id']}": b["id"] for b in books}
        c1, c2 = st.columns([2, 1])
        selected_label = c1.selectbox("Portfolio tersimpan", ["— pilih —"] + list(names), key="saved_portfolio_select")
        if c2.button("Muat portfolio", key="load_saved_portfolio"):
            if selected_label in names:
                try:
                    loaded = load_book(names[selected_label], owner_id=owner_id)
                    record_audit_event(
                        owner_id, st.session_state.get("_auth_role"), "PORTFOLIO_LOAD",
                        "portfolio_book", names[selected_label],
                        details={"position_count": len(loaded)},
                    )
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
                count = save_book(book_id, name.strip(), positions, owner_id=owner_id)
                try:
                    record_audit_event(
                        owner_id, st.session_state.get("_auth_role"), "PORTFOLIO_SAVE",
                        "portfolio_book", book_id,
                        details={"position_count": count},
                    )
                except Exception as audit_exc:
                    st.warning(f"Portfolio tersimpan, tetapi audit event gagal dicatat: {type(audit_exc).__name__}. Hubungi administrator.")
                st.success(f"{count} posisi disimpan. ID: {book_id}")
                st.rerun()
            except Exception as exc:
                st.error(f"Gagal menyimpan portfolio: {type(exc).__name__}: {exc}")
        if selected_label in names:
            confirm_delete = st.checkbox(
                "Saya memahami portfolio terpilih akan dihapus permanen.",
                key="confirm_delete_saved_portfolio",
            )
            if st.button(
                "Hapus portfolio tersimpan",
                key="delete_saved_portfolio",
                disabled=not confirm_delete,
            ):
                try:
                    deleted = delete_book(names[selected_label], owner_id=owner_id)
                    if deleted:
                        _audit_event_safely(
                            owner_id, "PORTFOLIO_DELETE", "portfolio_book",
                            names[selected_label], details={"scope": "owner"},
                        )
                        st.success("Portfolio tersimpan berhasil dihapus.")
                        st.session_state.pop("saved_portfolio_select", None)
                        st.session_state.pop("confirm_delete_saved_portfolio", None)
                        st.rerun()
                    else:
                        st.info("Portfolio tidak ditemukan atau sudah dihapus.")
                except Exception as exc:
                    st.error(f"Gagal menghapus portfolio: {type(exc).__name__}: {exc}")
        if books:
            st.dataframe(pd.DataFrame(books), use_container_width=True, hide_index=True)
        else:
            st.info("Belum ada portfolio tersimpan.")


def render_multi_asset_backtest(owner_id: str) -> None:
    require_permission(st.session_state.get("_auth_role"), "run_analysis")
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
        st.caption("Semua nominal mengikuti mata uang pasar yang dipilih: IDR untuk IDX atau USD untuk US.")
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
                    try:
                        run_id = save_run(
                            owner_id=owner_id,
                            run_type="multi_asset",
                            market=market,
                            symbols=symbols,
                            parameters={
                                "period": period, "initial_capital": capital,
                                "fee_bps": fee, "slippage_bps": slippage,
                                "max_positions": max_positions, "max_weight_pct": cap_weight,
                            },
                            result=result,
                        )
                        st.session_state["multi_asset_backtest_run_id"] = run_id
                        _audit_event_safely(
                            owner_id, "BACKTEST_RUN", "research_run", run_id,
                            details={"run_type": "multi_asset", "market": market, "symbols": symbols},
                        )
                    except Exception as persist_exc:
                        st.warning(
                            "Hasil backtest tersedia pada sesi ini, tetapi belum tersimpan permanen: "
                            f"{type(persist_exc).__name__}: {persist_exc}"
                        )
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
            st.caption(
                f"Average exposure {result['average_exposure_pct']:.1f}% · "
                f"Average positions {result['average_active_positions']:.1f} · "
                f"Estimated costs {result['estimated_cost_paid']:,.2f}"
            )
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


def render_research_run_history(owner_id: str) -> None:
    """Owner-scoped history for single, walk-forward and multi-asset backtests."""
    require_permission(st.session_state.get("_auth_role"), "run_analysis")
    st.subheader("Riwayat Research & Backtest Tersimpan")
    if not str(owner_id or "").strip():
        st.info("Riwayat tersimpan memerlukan identitas pengguna yang terverifikasi.")
        return
    try:
        runs = list_runs(owner_id=owner_id, limit=100)
    except Exception as exc:
        st.error(f"Riwayat research tidak dapat dibaca: {type(exc).__name__}: {exc}")
        return
    if not runs:
        st.info("Belum ada hasil backtest yang tersimpan.")
        return
    labels = {
        f"{item['created_at']} · {item['run_type']} · {item['market']} · "
        f"{', '.join(item['symbols'])} · {item['id'][:8]}": item["id"]
        for item in runs
    }
    st.dataframe(pd.DataFrame([{
        "Tanggal UTC": item["created_at"],
        "Jenis": item["run_type"],
        "Market": item["market"],
        "Ticker": ", ".join(item["symbols"]),
        "Run ID": item["id"],
    } for item in runs]), use_container_width=True, hide_index=True)
    selected = st.selectbox(
        "Pilih hasil backtest tersimpan",
        ["— pilih —"] + list(labels),
        key="research_run_history_select",
    )
    if selected == "— pilih —":
        return
    run_id = labels[selected]
    load_col, delete_col = st.columns(2)
    if load_col.button("Muat hasil ke dashboard", key="load_research_run"):
        try:
            saved = get_run(owner_id=owner_id, run_id=run_id)
            if saved["run_type"] == "single_ticker":
                st.session_state["backtest_result"] = {
                    "ticker": saved["symbols"][0],
                    "market": saved["market"],
                    "result": saved["result"],
                }
            elif saved["run_type"] == "walk_forward":
                st.session_state["walk_forward_result"] = {
                    "ticker": saved["symbols"][0],
                    "market": saved["market"],
                    "result": saved["result"],
                }
            elif saved["run_type"] == "multi_asset":
                st.session_state["multi_asset_backtest_result"] = saved["result"]
            _audit_event_safely(
                owner_id, "RESEARCH_RUN_LOAD", "research_run", run_id,
                details={"run_type": saved["run_type"], "market": saved["market"]},
            )
            st.success("Hasil backtest berhasil dimuat.")
            st.rerun()
        except Exception as exc:
            st.error(f"Hasil backtest tidak dapat dimuat: {type(exc).__name__}: {exc}")
    if delete_col.button("Hapus hasil tersimpan", key="delete_research_run"):
        try:
            deleted = delete_run(owner_id=owner_id, run_id=run_id)
            if deleted:
                _audit_event_safely(
                    owner_id, "RESEARCH_RUN_DELETE", "research_run", run_id,
                    details={"scope": "owner"},
                )
                st.success("Hasil backtest dihapus dari penyimpanan pengguna ini.")
                st.session_state.pop("research_run_history_select", None)
                st.rerun()
            else:
                st.info("Hasil sudah tidak tersedia.")
        except Exception as exc:
            st.error(f"Hasil backtest tidak dapat dihapus: {type(exc).__name__}: {exc}")


def render_research_exports(latest: dict | None, history: list | None, owner_id: str) -> None:
    st.subheader("Research Pack & Export")
    st.caption("Ekspor ringkasan performa dan histori sinyal ke Excel atau PDF.")
    frame = pd.DataFrame(history or [])
    metrics = {}
    extra_sheets: dict[str, pd.DataFrame] = {}
    if latest:
        counts = latest.get("counts", {})
        metrics = {"Scan ID": latest.get("scan_id"), "Scanned": counts.get("scanned"),
                   "Success": counts.get("success"), "Failed": counts.get("failed"),
                   "BUY candidate": counts.get("buy_candidate"), "WATCH": counts.get("watch"),
                   "NO TRADE": counts.get("no_trade")}
    latest_scan_rows = (latest or {}).get("results", [])
    if latest_scan_rows:
        extra_sheets["Latest Daily Scan"] = pd.DataFrame(latest_scan_rows)
    screener_result = st.session_state.get("advanced_screener_result") or {}
    if screener_result.get("results"):
        extra_sheets["Advanced Screener"] = pd.DataFrame(screener_result["results"])

    for state_key, sheet_name in [
        ("portfolio_exposure_report_frame", "Portfolio Exposure"),
        ("portfolio_risk_report_frame", "Portfolio Risk"),
        ("portfolio_sector_report_frame", "Sector Exposure"),
        ("portfolio_risk_parity_report_frame", "Risk Parity Weights"),
        ("portfolio_max_sharpe_report_frame", "Max Sharpe Weights"),
        ("portfolio_institutional_risk_frame", "Institutional Risk"),
        ("portfolio_concentration_frame", "Concentration Limits"),
        ("portfolio_stress_frame", "Stress Scenarios"),
        ("portfolio_limit_breaches_frame", "Risk Limit Breaches"),
        ("portfolio_price_scenario_frame", "Price Scenarios"),
    ]:
        saved_frame = st.session_state.get(state_key)
        if isinstance(saved_frame, pd.DataFrame) and not saved_frame.empty:
            extra_sheets[sheet_name] = saved_frame.copy()
    fx_metrics = st.session_state.get("portfolio_fx_scenario_metrics") or {}
    if fx_metrics:
        metrics.update({
            "Portfolio FX base currency": fx_metrics.get("base_currency"),
            "USD/IDR spot input": fx_metrics.get("usd_idr_spot"),
            "FX shock %": fx_metrics.get("fx_shock_pct"),
            "FX translation P/L IDR": fx_metrics.get("fx_translation_pnl_idr"),
            "Portfolio scenario value IDR": fx_metrics.get("scenario_portfolio_idr"),
        })
    optimization_metrics = st.session_state.get("portfolio_optimization_metrics") or {}
    if optimization_metrics:
        for key, value in optimization_metrics.items():
            metrics[f"Portfolio optimization — {key}"] = value

    market_result = st.session_state.get("market_intelligence_result")
    if market_result:
        regime = market_result.get("regime", {})
        strength = market_result.get("strength", {})
        strength_rows = [
            {"Horizon": horizon, **values}
            for horizon, values in strength.get("periods", {}).items()
        ]
        extra_sheets["Market Relative Strength"] = pd.DataFrame(strength_rows)
        extra_sheets["Price Data Quality"] = pd.DataFrame(market_result.get("quality", {}).get("checks", []))
        extra_sheets["Fundamental Data Quality"] = pd.DataFrame(
            market_result.get("fundamental_quality", {}).get("checks", [])
        )
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
        extra_sheets["Multi Asset Equity Curve"] = pd.DataFrame(multi_result.get("curve", []))
        extra_sheets["Multi Asset Universe"] = pd.DataFrame({
            "Ticker": multi_result.get("active_symbols", [])
        })
        extra_sheets["Rejected Assets"] = pd.DataFrame(multi_result.get("rejected_symbols", []))

    single_saved = st.session_state.get("backtest_result") or {}
    single_result = single_saved.get("result") or {}
    if single_result:
        metrics.update({
            "Single-ticker": single_saved.get("ticker"),
            "Single backtest return %": single_result.get("total_return_pct"),
            "Single backtest CAGR %": single_result.get("cagr_pct"),
            "Single backtest max drawdown %": single_result.get("max_drawdown_pct"),
            "Single backtest trades": single_result.get("trades"),
        })
        extra_sheets["Single Equity Curve"] = pd.DataFrame(single_result.get("equity_curve", []))
        extra_sheets["Single Trade Detail"] = pd.DataFrame(single_result.get("trades_detail", []))

    walk_saved = st.session_state.get("walk_forward_result") or {}
    walk_result = walk_saved.get("result") or {}
    if walk_result:
        metrics.update({
            "Walk-forward ticker": walk_saved.get("ticker"),
            "Walk-forward OOS return %": walk_result.get("combined_oos_return_pct"),
            "Walk-forward weighted win rate %": walk_result.get("weighted_win_rate_pct"),
            "Walk-forward total trades": walk_result.get("total_trades"),
            "Walk-forward profitable folds %": walk_result.get("profitable_folds_pct"),
        })
        extra_sheets["Walk Forward Folds"] = pd.DataFrame(walk_result.get("folds", []))

    try:
        saved_runs = list_runs(owner_id=owner_id, limit=100)
        metrics["Saved research runs"] = len(saved_runs)
        extra_sheets["Saved Research Runs"] = pd.DataFrame([{
            "Created UTC": item["created_at"], "Run Type": item["run_type"],
            "Market": item["market"], "Symbols": ", ".join(item["symbols"]),
            "Run ID": item["id"], "Parameters": item["parameters"],
        } for item in saved_runs])
    except Exception as exc:
        st.warning(f"Riwayat backtest tidak ditambahkan ke Excel: {type(exc).__name__}: {exc}")
    if has_permission(st.session_state.get("_auth_role"), "export_reports"):
        c1, c2 = st.columns(2)
        c1.download_button("Unduh Research Pack Excel", build_excel_report(
            portfolio=st.session_state.get("portfolio_report_frame"),
            metrics=metrics, history=frame, extra_sheets=extra_sheets,
        ), file_name="ai_equity_research_pack.xlsx",
           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        c2.download_button("Unduh Ringkasan PDF", build_pdf_report(
            "AI Equity Research — Performance Summary", metrics,
            notes=["Forward outcomes are observations, not forecasts.",
                   "Yahoo Finance data may be incomplete or revised.",
                   "No broker execution is performed."],
        ), file_name="ai_equity_research_summary.pdf", mime="application/pdf")
    else:
        st.info("Ekspor laporan memerlukan role analyst atau lebih tinggi.")
