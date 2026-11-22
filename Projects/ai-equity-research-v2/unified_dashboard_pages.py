"""Unified dashboard pages for AI Equity Research."""

from __future__ import annotations

import math
import pandas as pd
import streamlit as st

from daily_signal_service import (
    run_daily_scan, get_dashboard_data, format_report, refresh_forward_outcomes,
)
from daily_signal_engine import load_daily_history
from daily_signal_storage import backend_name
from daily_signal_backtest import backtest


def _show_scan(scan: dict) -> None:
    counts = scan.get("counts", {})
    cols = st.columns(5)
    cols[0].metric("Dipindai", counts.get("scanned", 0))
    cols[1].metric("Berhasil", counts.get("success", 0))
    cols[2].metric("Gagal", counts.get("failed", 0))
    cols[3].metric("BUY candidate", counts.get("buy_candidate", 0))
    cols[4].metric("WATCH", counts.get("watch", 0))
    results = scan.get("results", [])
    if results:
        frame = pd.DataFrame(results)
        preferred = [
            "market", "ticker", "bar_date", "signal", "score", "close",
            "currency", "rsi14", "relative_volume", "entry_low",
            "entry_high", "stop_loss", "target", "reward_risk"
        ]
        frame = frame[[c for c in preferred if c in frame.columns]]
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Unduh hasil scan CSV", frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="daily_stock_signal.csv", mime="text/csv",
        )
    if scan.get("errors"):
        with st.expander(f"Detail data gagal ({len(scan['errors'])})"):
            st.dataframe(pd.DataFrame(scan["errors"]), use_container_width=True, hide_index=True)
    with st.expander("Laporan ringkas"):
        st.code(format_report(scan), language="text")


def render_daily_signal() -> None:
    st.header("Daily Stock Signal")
    st.caption("Pemindaian teknikal IDX dan US berdasarkan watchlist sistem. Data harga harian Yahoo Finance, bukan harga live.")
    st.info("Pemindaian dashboard menyimpan hasil ke database aktif. Telegram dan Ollama hanya dijalankan oleh otomasi lokal.")
    left, right = st.columns([1, 3])
    with left:
        run = st.button("Jalankan pemindaian sekarang", type="primary", use_container_width=True)
    with right:
        st.caption("Universe awal: 15 saham IDX dan 10 instrumen US. Ini watchlist terpilih, bukan seluruh bursa.")
    if run:
        try:
            with st.spinner("Memindai watchlist IDX dan US..."):
                scan = run_daily_scan(max_workers=3)
            st.session_state["unified_latest_scan"] = scan
            st.success(f"Scan tersimpan. Scan ID: {scan.get('scan_id', 'N/A')}")
        except Exception as exc:
            st.error(f"Pemindaian gagal: {type(exc).__name__}: {exc}")
    scan = st.session_state.get("unified_latest_scan")
    if scan is None:
        try:
            scan = get_dashboard_data().get("latest")
        except Exception as exc:
            st.warning(f"Riwayat scan belum dapat dibaca: {exc}")
    if scan:
        _show_scan(scan)
    else:
        st.info("Belum ada hasil pemindaian tersimpan. Klik tombol pemindaian untuk memulai.")


def render_portfolio_risk() -> None:
    st.header("Portfolio & Risk Management")
    st.caption("Masukkan posisi yang dimiliki untuk menghitung nilai pasar, P/L, bobot, volatilitas, dan Value at Risk historis.")
    if "portfolio_input" not in st.session_state:
        st.session_state["portfolio_input"] = pd.DataFrame([
            {"Market": "IDX", "Ticker": "TPIA", "Shares": 0.0, "Average Cost": 0.0}
        ])
    edited = st.data_editor(
        st.session_state["portfolio_input"], num_rows="dynamic",
        use_container_width=True, hide_index=True,
        column_config={
            "Market": st.column_config.SelectboxColumn("Market", options=["IDX", "US"], required=True),
            "Ticker": st.column_config.TextColumn("Ticker", help="Contoh IDX: TPIA, BBCA. US: NVDA, AAPL."),
            "Shares": st.column_config.NumberColumn("Shares", min_value=0.0, step=1.0),
            "Average Cost": st.column_config.NumberColumn("Average Cost", min_value=0.0, step=1.0),
        }, key="portfolio_editor",
    )
    st.session_state["portfolio_input"] = edited
    if st.button("Hitung portofolio & risiko", type="primary"):
        try:
            positions, return_series = [], {}
            for _, row in edited.iterrows():
                raw_ticker = row.get("Ticker", "")
                if pd.isna(raw_ticker) or not str(raw_ticker).strip():
                    continue
                ticker = str(raw_ticker).strip().upper()
                raw_market = row.get("Market", "IDX")
                market = "IDX" if pd.isna(raw_market) else str(raw_market).upper()
                shares = 0.0 if pd.isna(row.get("Shares", 0)) else float(row.get("Shares", 0))
                avg_cost = 0.0 if pd.isna(row.get("Average Cost", 0)) else float(row.get("Average Cost", 0))
                if shares <= 0:
                    continue
                bars, meta = load_daily_history(ticker, market, "1y")
                close = float(bars["Close"].iloc[-1])
                currency = meta.get("currency", "IDR" if market == "IDX" else "USD")
                value, cost = shares * close, shares * avg_cost
                resolved = meta.get("ticker", ticker)
                positions.append({
                    "Market": market, "Ticker": resolved, "Shares": shares,
                    "Average Cost": avg_cost, "Latest Close": close, "Currency": currency,
                    "Market Value": value, "Cost Basis": cost, "Unrealized P/L": value-cost,
                    "Return %": ((close / avg_cost)-1)*100 if avg_cost > 0 else None,
                })
                return_series[resolved] = bars["Close"].pct_change().dropna().rename(resolved)
            if not positions:
                st.warning("Isi minimal satu posisi dengan jumlah saham lebih dari nol.")
                return
            st.session_state["portfolio_result"] = {"positions": pd.DataFrame(positions), "returns": return_series}
        except Exception as exc:
            st.error(f"Gagal menghitung portofolio: {type(exc).__name__}: {exc}")
    result = st.session_state.get("portfolio_result")
    if not result:
        st.info("Data posisi hanya disimpan dalam sesi browser ini. Belum ada order broker atau transaksi yang dilakukan.")
        return
    frame = result["positions"].copy()
    total_value_by_currency = frame.groupby("Currency")["Market Value"].sum().to_dict()
    total_cost_by_currency = frame.groupby("Currency")["Cost Basis"].sum().to_dict()
    frame["Weight within currency"] = frame.apply(
        lambda r: r["Market Value"] / total_value_by_currency.get(r["Currency"], 1) * 100
        if total_value_by_currency.get(r["Currency"], 0) else 0, axis=1
    )
    st.subheader("Posisi & valuasi")
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.caption("Nilai agregat dipisahkan menurut mata uang; IDR dan USD tidak dijumlahkan tanpa konversi FX.")
    summary = [{"Currency": c, "Market Value": v, "Cost Basis": total_cost_by_currency.get(c, 0),
                "Unrealized P/L": v-total_cost_by_currency.get(c, 0)} for c, v in total_value_by_currency.items()]
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)
    st.subheader("Risk indicators by currency")
    for currency, currency_positions in frame.groupby("Currency"):
        tickers = currency_positions["Ticker"].tolist()
        available = [result["returns"][t] for t in tickers if t in result["returns"]]
        if not available:
            continue
        daily = pd.concat(available, axis=1).sort_index().dropna(how="all")
        weights = currency_positions.set_index("Ticker")["Market Value"]
        tickers = [t for t in daily.columns if t in weights.index]
        if not tickers:
            continue
        w = weights.reindex(tickers).fillna(0)
        w = w/w.sum() if w.sum() else w
        portfolio_returns = daily[tickers].fillna(0).mul(w, axis=1).sum(axis=1)
        if len(portfolio_returns) >= 20:
            annual_vol = float(portfolio_returns.std(ddof=1)*math.sqrt(252)*100)
            hist_var = float(-portfolio_returns.quantile(0.05)*100)
            st.markdown(f"**{currency} portfolio**")
            a,b,c = st.columns(3)
            a.metric("Annualized volatility", f"{annual_vol:.2f}%")
            b.metric("Historical VaR 95% (1 day)", f"{hist_var:.2f}%")
            c.metric("Observasi harian", f"{len(portfolio_returns):,}")
            st.line_chart((1+portfolio_returns).cumprod().rename(f"{currency} growth of 1 unit"))
        else:
            st.info(f"Belum cukup observasi return bersama untuk {currency} (minimal 20 hari).")
    st.caption("Risiko dihitung terpisah per mata uang agar return IDR dan USD tidak tercampur tanpa konversi FX.")


def render_backtesting() -> None:
    st.header("Backtesting")
    st.caption("Uji historis strategi Daily Stock Signal dengan biaya dan slippage yang dapat diubah.")
    with st.form("backtest_form"):
        c1,c2,c3 = st.columns(3)
        market = c1.selectbox("Pasar", ["IDX","US"], key="bt_market")
        ticker = c2.text_input("Ticker", "TPIA" if market=="IDX" else "NVDA", key="bt_ticker")
        period = c3.selectbox("Periode data", ["2y","5y","10y"], index=1, key="bt_period")
        c4,c5,c6 = st.columns(3)
        fee = c4.number_input("Fee (bps per sisi)",0.0,500.0,10.0,1.0)
        slippage = c5.number_input("Slippage (bps per sisi)",0.0,500.0,10.0,1.0)
        risk = c6.number_input("Risk budget per trade (%)",0.1,5.0,1.0,0.1)
        c7,c8 = st.columns(2)
        allocation = c7.slider("Maksimum alokasi posisi (%)",1,100,100)/100
        holding = c8.slider("Holding maksimum (sesi)",1,5,5)
        submitted = st.form_submit_button("Jalankan backtest", type="primary")
    if submitted:
        try:
            with st.spinner(f"Mengunduh data historis {ticker.upper()}..."):
                bars,meta = load_daily_history(ticker,market,period)
                result = backtest(bars,fee_bps=fee,slippage_bps=slippage,risk_fraction=risk/100,
                                  max_allocation=allocation,max_holding_sessions=holding)
            st.session_state["backtest_result"]={"ticker":meta.get("ticker",ticker.upper()),"market":market,"result":result}
        except Exception as exc:
            st.error(f"Backtest gagal: {type(exc).__name__}: {exc}")
    saved = st.session_state.get("backtest_result")
    if saved:
        r = saved["result"]
        st.subheader(f"{saved['ticker']} · {saved['market']}")
        cols=st.columns(5)
        cols[0].metric("Total return",f"{r['total_return_pct']:.2f}%")
        cols[1].metric("CAGR",f"{r['cagr_pct']:.2f}%")
        cols[2].metric("Max drawdown",f"{r['max_drawdown_pct']:.2f}%")
        cols[3].metric("Win rate",f"{r['win_rate_pct']:.1f}%")
        cols[4].metric("Trades",r["trades"])
        cols2=st.columns(4)
        cols2[0].metric("Profit factor",f"{r['profit_factor']:.2f}" if math.isfinite(r["profit_factor"]) else "∞")
        cols2[1].metric("Sharpe ratio",f"{r['sharpe_ratio']:.2f}")
        cols2[2].metric("Benchmark buy & hold",f"{r['benchmark_buy_hold_pct']:.2f}%")
        cols2[3].metric("Round-trip cost",f"{r['cost_bps_round_trip']:.0f} bps")
        curve=pd.DataFrame(r["equity_curve"])
        if not curve.empty:
            curve["date"]=pd.to_datetime(curve["date"])
            st.line_chart(curve.set_index("date")["equity"])
        trades=pd.DataFrame(r["trades_detail"])
        if not trades.empty:
            st.subheader("Detail transaksi")
            st.dataframe(trades,use_container_width=True,hide_index=True)
            st.download_button("Unduh transaksi CSV",trades.to_csv(index=False).encode("utf-8-sig"),"backtest_trades.csv","text/csv")
        else:
            st.info("Tidak ada transaksi yang memenuhi seluruh aturan strategi pada periode ini.")
        st.warning(r["limitations"])


def render_performance_dashboard() -> None:
    st.header("Performance Dashboard")
    st.caption("Kinerja scan, histori sinyal, dan outcome forward 1/3/5 sesi dari harga penutupan yang benar-benar tersedia.")
    backend = backend_name()
    if backend == "PostgreSQL":
        st.success("Database cloud PostgreSQL aktif. Histori scan disimpan secara persisten.")
    else:
        st.warning("Database aktif masih SQLite. Pada Streamlit Cloud, penyimpanan lokal dapat hilang saat instance dibuat ulang. Konfigurasikan DATABASE_URL untuk histori cloud persisten.")
    if st.button("Perbarui outcome 1/3/5 sesi", type="primary"):
        try:
            with st.spinner("Memeriksa harga penutupan harian setelah tanggal sinyal..."):
                refresh = refresh_forward_outcomes(limit=500)
            st.success(f"{refresh['updated_outcomes']} outcome baru tercatat dari {refresh['pending_signals']} sinyal tertunda.")
            if refresh["errors"]:
                with st.expander(f"Ticker yang belum berhasil diperbarui ({len(refresh['errors'])})"):
                    st.dataframe(pd.DataFrame(refresh["errors"]), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Pembaruan outcome gagal: {type(exc).__name__}: {exc}")
    try:
        data = get_dashboard_data(limit=500)
        latest, history, outcomes = data.get("latest"), data.get("history") or [], data.get("outcomes") or []
    except Exception as exc:
        st.error(f"Database performa tidak dapat dibaca: {type(exc).__name__}: {exc}")
        return
    if latest:
        counts=latest.get("counts",{})
        cols=st.columns(4)
        cols[0].metric("Saham dipindai terakhir",counts.get("scanned",0))
        cols[1].metric("BUY candidate",counts.get("buy_candidate",0))
        cols[2].metric("WATCH",counts.get("watch",0))
        cols[3].metric("Gagal ambil data",counts.get("failed",0))
        st.caption(f"Scan ID: {latest.get('scan_id','N/A')} · Data tiap ticker menggunakan tanggal bar masing-masing.")
    else:
        st.info("Belum ada scan tersimpan pada database aktif. Jalankan Daily Stock Signal untuk membuat data.")
    if history:
        frame=pd.DataFrame(history)
        cols=[c for c in ["bar_date","market","ticker","signal","score","close","outcome_1d_return_pct","outcome_3d_return_pct","outcome_5d_return_pct"] if c in frame.columns]
        st.subheader("Riwayat sinyal dan forward outcome")
        st.dataframe(frame[cols],use_container_width=True,hide_index=True)
        st.download_button("Unduh histori sinyal CSV",frame[cols].to_csv(index=False).encode("utf-8-sig"),"signal_history.csv","text/csv")
        counts=frame["signal"].value_counts().rename_axis("Signal").reset_index(name="Count")
        st.bar_chart(counts.set_index("Signal"))
    else:
        st.info("Histori sinyal belum tersedia.")
    if outcomes:
        st.subheader("Forward outcome (observasi aktual)")
        outcome_frame=pd.DataFrame(outcomes)
        outcome_frame["Horizon"] = outcome_frame["horizon"].astype(str) + " sesi"
        outcome_frame=outcome_frame.rename(columns={"observations":"Observasi","avg_forward_return_pct":"Rata-rata return (%)","positive_rate_pct":"Outcome positif (%)"})
        st.dataframe(outcome_frame[["Horizon","Observasi","Rata-rata return (%)","Outcome positif (%)"]],use_container_width=True,hide_index=True)
    else:
        st.info("Outcome 1/3/5 sesi belum tercatat. Sistem hanya mencatat return setelah harga penutupan untuk horizon tersebut tersedia.")
