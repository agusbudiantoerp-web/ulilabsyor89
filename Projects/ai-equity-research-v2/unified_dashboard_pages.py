"""Unified dashboard pages for AI Equity Research."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from daily_signal_service import run_daily_scan, get_dashboard_data, format_report
from daily_signal_engine import load_daily_history
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
            "Unduh hasil scan CSV",
            frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="daily_stock_signal.csv",
            mime="text/csv",
        )
    if scan.get("errors"):
        with st.expander(f"Detail data gagal ({len(scan['errors'])})"):
            st.dataframe(pd.DataFrame(scan["errors"]), use_container_width=True, hide_index=True)
    with st.expander("Laporan ringkas"):
        st.code(format_report(scan), language="text")


def render_daily_signal() -> None:
    st.header("Daily Stock Signal")
    st.caption("Pemindaian teknikal IDX dan US berdasarkan watchlist sistem. Data harga harian Yahoo Finance, bukan harga live.")
    st.info("Pemindaian dari dashboard tidak mengirim Telegram dan tidak menjalankan Ollama. Otomasi Ollama + Telegram lokal tetap berjalan terpisah sesuai Task Scheduler.")
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
        st.session_state["portfolio_input"],
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Market": st.column_config.SelectboxColumn("Market", options=["IDX", "US"], required=True),
            "Ticker": st.column_config.TextColumn("Ticker", help="Contoh IDX: TPIA, BBCA. US: NVDA, AAPL."),
            "Shares": st.column_config.NumberColumn("Shares", min_value=0.0, step=1.0),
            "Average Cost": st.column_config.NumberColumn("Average Cost", min_value=0.0, step=1.0),
        },
        key="portfolio_editor",
    )
    st.session_state["portfolio_input"] = edited
    if st.button("Hitung portofolio & risiko", type="primary"):
        try:
            import yfinance as yf
            positions = []
            return_series = {}
            for _, row in edited.iterrows():
                ticker = str(row.get("Ticker", "")).strip().upper()
                market = str(row.get("Market", "IDX")).upper()
                shares = float(row.get("Shares", 0) or 0)
                avg_cost = float(row.get("Average Cost", 0) or 0)
                if not ticker or shares <= 0:
                    continue
                bars, meta = load_daily_history(ticker, market, "1y")
                close = float(bars["Close"].iloc[-1])
                currency = meta.get("currency", "IDR" if market == "IDX" else "USD")
                value = shares * close
                cost = shares * avg_cost
                positions.append({
                    "Market": market, "Ticker": meta.get("ticker", ticker),
                    "Shares": shares, "Average Cost": avg_cost,
                    "Latest Close": close, "Currency": currency,
                    "Market Value": value, "Cost Basis": cost,
                    "Unrealized P/L": value - cost,
                    "Return %": ((close / avg_cost) - 1) * 100 if avg_cost > 0 else None,
                })
                series = bars["Close"].pct_change().dropna().rename(meta.get("ticker", ticker))
                return_series[meta.get("ticker", ticker)] = series
            if not positions:
                st.warning("Isi minimal satu posisi dengan jumlah saham lebih dari nol.")
                return
            frame = pd.DataFrame(positions)
            st.session_state["portfolio_result"] = {"positions": frame, "returns": return_series}
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
    summary = []
    for currency, value in total_value_by_currency.items():
        cost = total_cost_by_currency.get(currency, 0)
        summary.append({"Currency": currency, "Market Value": value, "Cost Basis": cost, "Unrealized P/L": value-cost})
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)
    returns = result["returns"]
    if len(returns) >= 1:
        daily = pd.concat(returns.values(), axis=1).sort_index().dropna(how="all")
        weights = frame.set_index("Ticker")["Market Value"]
        # Normalize each position's weight within its currency group for a currency-consistent proxy.
        tickers = [c for c in daily.columns if c in weights.index]
        if tickers:
            w = weights.reindex(tickers).fillna(0)
            w = w / w.sum() if w.sum() else w
            portfolio_returns = daily[tickers].fillna(0).mul(w, axis=1).sum(axis=1)
            if len(portfolio_returns) >= 20:
                annual_vol = float(portfolio_returns.std(ddof=1) * math.sqrt(252) * 100)
                hist_var = float(-portfolio_returns.quantile(0.05) * 100)
                st.subheader("Risk indicators (portfolio proxy)")
                a, b, c = st.columns(3)
                a.metric("Annualized volatility", f"{annual_vol:.2f}%")
                b.metric("Historical VaR 95% (1 day)", f"{hist_var:.2f}%")
                c.metric("Observasi harian", f"{len(portfolio_returns):,}")
                st.line_chart((1 + portfolio_returns).cumprod().rename("Growth of 1 unit"))
                st.caption("Risiko dihitung dari irisan return harian yang tersedia. Jika portofolio multi-mata-uang, bobot risiko adalah proxy berbasis nilai nominal dan belum dikonversi ke satu mata uang.")
            else:
                st.info("Belum cukup observasi return bersama untuk estimasi risiko (minimal 20 hari).")


def render_backtesting() -> None:
    st.header("Backtesting")
    st.caption("Uji historis strategi Daily Stock Signal dengan biaya dan slippage yang dapat diubah.")
    with st.form("backtest_form"):
        c1, c2, c3 = st.columns(3)
        market = c1.selectbox("Pasar", ["IDX", "US"], key="bt_market")
        ticker = c2.text_input("Ticker", "TPIA" if market == "IDX" else "NVDA", key="bt_ticker")
        period = c3.selectbox("Periode data", ["2y", "5y", "10y"], index=1, key="bt_period")
        c4, c5, c6 = st.columns(3)
        fee = c4.number_input("Fee (bps per sisi)", 0.0, 500.0, 10.0, 1.0)
        slippage = c5.number_input("Slippage (bps per sisi)", 0.0, 500.0, 10.0, 1.0)
        risk = c6.number_input("Risk budget per trade (%)", 0.1, 5.0, 1.0, 0.1)
        c7, c8 = st.columns(2)
        allocation = c7.slider("Maksimum alokasi posisi (%)", 1, 100, 100) / 100
        holding = c8.slider("Holding maksimum (sesi)", 1, 5, 5)
        submitted = st.form_submit_button("Jalankan backtest", type="primary")
    if submitted:
        try:
            with st.spinner(f"Mengunduh data historis {ticker.upper()}..."):
                bars, meta = load_daily_history(ticker, market, period)
                result = backtest(
                    bars, fee_bps=fee, slippage_bps=slippage,
                    risk_fraction=risk/100, max_allocation=allocation,
                    max_holding_sessions=holding,
                )
            st.session_state["backtest_result"] = {"ticker": meta.get("ticker", ticker.upper()), "market": market, "result": result}
        except Exception as exc:
            st.error(f"Backtest gagal: {type(exc).__name__}: {exc}")
    saved = st.session_state.get("backtest_result")
    if saved:
        r = saved["result"]
        st.subheader(f"{saved['ticker']} · {saved['market']}")
        cols = st.columns(5)
        cols[0].metric("Total return", f"{r['total_return_pct']:.2f}%")
        cols[1].metric("CAGR", f"{r['cagr_pct']:.2f}%")
        cols[2].metric("Max drawdown", f"{r['max_drawdown_pct']:.2f}%")
        cols[3].metric("Win rate", f"{r['win_rate_pct']:.1f}%")
        cols[4].metric("Trades", r["trades"])
        cols2 = st.columns(4)
        cols2[0].metric("Profit factor", f"{r['profit_factor']:.2f}" if math.isfinite(r["profit_factor"]) else "∞")
        cols2[1].metric("Sharpe ratio", f"{r['sharpe_ratio']:.2f}")
        cols2[2].metric("Benchmark buy & hold", f"{r['benchmark_buy_hold_pct']:.2f}%")
        cols2[3].metric("Round-trip cost", f"{r['cost_bps_round_trip']:.0f} bps")
        curve = pd.DataFrame(r["equity_curve"])
        if not curve.empty:
            curve["date"] = pd.to_datetime(curve["date"])
            st.line_chart(curve.set_index("date")["equity"])
        trades = pd.DataFrame(r["trades_detail"])
        if not trades.empty:
            st.subheader("Detail transaksi")
            st.dataframe(trades, use_container_width=True, hide_index=True)
            st.download_button("Unduh transaksi CSV", trades.to_csv(index=False).encode("utf-8-sig"), "backtest_trades.csv", "text/csv")
        else:
            st.info("Tidak ada transaksi yang memenuhi seluruh aturan strategi pada periode ini.")
        st.warning(r["limitations"])


def render_performance_dashboard() -> None:
    st.header("Performance Dashboard")
    st.caption("Kinerja scan, histori sinyal, dan outcome yang tercatat di database aplikasi.")
    try:
        data = get_dashboard_data(limit=500)
        latest = data.get("latest")
        history = data.get("history") or []
    except Exception as exc:
        st.error(f"Database performa tidak dapat dibaca: {exc}")
        return
    if latest:
        counts = latest.get("counts", {})
        cols = st.columns(4)
        cols[0].metric("Saham dipindai terakhir", counts.get("scanned", 0))
        cols[1].metric("BUY candidate", counts.get("buy_candidate", 0))
        cols[2].metric("WATCH", counts.get("watch", 0))
        cols[3].metric("Gagal ambil data", counts.get("failed", 0))
        st.caption(f"Scan ID: {latest.get('scan_id', 'N/A')} · Tanggal data tiap ticker ditampilkan pada tabel.")
    else:
        st.info("Belum ada scan tersimpan di database instance ini. Jalankan Daily Stock Signal untuk membuat data awal.")
    if history:
        frame = pd.DataFrame(history)
        cols = [c for c in ["bar_date", "market", "ticker", "signal", "score", "close", "entry_low", "stop_loss", "target"] if c in frame.columns]
        st.subheader("Riwayat sinyal")
        st.dataframe(frame[cols], use_container_width=True, hide_index=True)
        st.download_button("Unduh histori sinyal CSV", frame[cols].to_csv(index=False).encode("utf-8-sig"), "signal_history.csv", "text/csv")
        counts = frame["signal"].value_counts().rename_axis("Signal").reset_index(name="Count")
        st.bar_chart(counts.set_index("Signal"))
    else:
        st.info("Histori sinyal belum tersedia.")
    db_path = Path("data/daily_signals.sqlite3")
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as db:
                outcomes = pd.read_sql_query(
                    "SELECT horizon, COUNT(*) AS observations, AVG(return_pct) AS avg_forward_return_pct, SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS positive_rate_pct FROM outcomes GROUP BY horizon ORDER BY horizon",
                    db,
                )
            if not outcomes.empty:
                st.subheader("Forward outcome (data yang sudah tercatat)")
                st.dataframe(outcomes, use_container_width=True, hide_index=True)
            else:
                st.info("Outcome 1/3/5 sesi belum tercatat. Dashboard tidak mengarang return yang belum diamati.")
        except Exception:
            st.caption("Tabel outcome belum tersedia pada database ini.")
    st.warning("Database lokal komputer tidak otomatis tersinkron ke Streamlit Cloud. Dashboard cloud hanya menampilkan data yang tersimpan pada instance cloud; hasil scan lokal dan Telegram tetap terpisah.")
