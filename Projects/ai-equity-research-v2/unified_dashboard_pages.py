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
from daily_signal_backtest import backtest, walk_forward_backtest
from advanced_stock_screener import ADVANCED_UNIVERSE, run_advanced_screener
from portfolio_intelligence import analyze_portfolio, scenario_analysis, fx_scenario_analysis
from daily_signal_portfolio import allocate_candidates


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
    st.header("Daily Stock Signal & Advanced Screener")
    st.caption("Data harian Yahoo Finance; hasil adalah kandidat riset, bukan harga live atau instruksi transaksi.")
    daily_tab, advanced_tab = st.tabs(["Daily Signal", "Advanced Screener + AI Stock Scoring"])
    with daily_tab:
        st.caption("Pemindaian watchlist operasional: 15 saham IDX dan 10 instrumen US.")
        st.info("Hasil pemindaian dashboard disimpan ke database aktif. Telegram dan Ollama tetap berjalan melalui otomasi lokal.")
        left, right = st.columns([1, 3])
        with left:
            run = st.button("Jalankan pemindaian sekarang", type="primary", use_container_width=True)
        with right:
            st.caption("Untuk universe lebih luas, gunakan tab Advanced Screener.")
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
    with advanced_tab:
        st.subheader("Screening fundamental, teknikal, dan ranking kuantitatif")
        st.caption("Preset berisi 40 ticker IDX dan 40 ticker US yang dipilih untuk likuiditas/coverage. Ini bukan seluruh emiten bursa.")
        markets = st.multiselect("Market", ["IDX", "US"], default=["IDX", "US"], key="adv_markets")
        use_preset = st.checkbox("Gunakan universe preset (40 IDX + 40 US)", value=True, key="adv_preset")
        symbols_by_market = {m: list(ADVANCED_UNIVERSE[m]) for m in markets}
        if not use_preset:
            st.caption("Ticker dipisahkan koma atau baris baru. IDX tanpa .JK; US gunakan simbol Yahoo Finance seperti BRK.B.")
            col_idx, col_us = st.columns(2)
            with col_idx:
                idx_text = st.text_area("Ticker IDX", value=", ".join(ADVANCED_UNIVERSE["IDX"][:15]), height=110, key="adv_idx_tickers")
            with col_us:
                us_text = st.text_area("Ticker US", value=", ".join(ADVANCED_UNIVERSE["US"][:15]), height=110, key="adv_us_tickers")
            import re
            symbols_by_market = {
                "IDX": [x.strip().upper() for x in re.split(r"[,\n; ]+", idx_text) if x.strip()],
                "US": [x.strip().upper() for x in re.split(r"[,\n; ]+", us_text) if x.strip()],
            }
        f1, f2, f3 = st.columns(3)
        min_score = f1.slider("Skor AI minimum", 0, 100, 0, 5, key="adv_min_score")
        period = f2.selectbox("Riwayat teknikal", ["1y", "2y", "5y"], index=0, key="adv_period")
        workers = f3.selectbox("Parallel workers", [2, 3, 4, 5, 6], index=2, key="adv_workers")
        st.caption("Market cap menggunakan mata uang asli: IDR untuk IDX dan USD untuk US.")
        cap_idx, cap_us = st.columns(2)
        min_cap = {
            "IDX": cap_idx.number_input("Market cap minimum IDX (IDR)", min_value=0.0, value=0.0, step=100000000000.0, key="adv_cap_idx"),
            "US": cap_us.number_input("Market cap minimum US (USD)", min_value=0.0, value=0.0, step=1000000000.0, key="adv_cap_us"),
        }
        max_idx, max_us = st.columns(2)
        max_cap_values = {
            "IDX": max_idx.number_input("Market cap maximum IDX (IDR; 0 = no limit)", min_value=0.0, value=0.0, step=100000000000.0, key="adv_max_cap_idx"),
            "US": max_us.number_input("Market cap maximum US (USD; 0 = no limit)", min_value=0.0, value=0.0, step=1000000000.0, key="adv_max_cap_us"),
        }
        max_cap = {market: (value if value > 0 else None) for market, value in max_cap_values.items()}
        sector_text = st.text_input("Filter sektor (opsional, pisahkan koma)", key="adv_sectors")
        sectors = [x.strip() for x in sector_text.split(",") if x.strip()]
        if st.button("Jalankan Advanced Screener", type="primary", key="run_advanced_screener"):
            if not markets:
                st.warning("Pilih minimal satu market.")
            elif not any(symbols_by_market.get(m) for m in markets):
                st.warning("Masukkan minimal satu ticker.")
            else:
                try:
                    with st.spinner("Mengambil data harga dan fundamental; proses dapat memerlukan beberapa menit..."):
                        result = run_advanced_screener(
                            markets=markets, symbols_by_market=symbols_by_market,
                            min_score=min_score, sectors=sectors,
                            min_market_cap=min_cap, max_market_cap=max_cap,
                            period=period, max_workers=workers,
                        )
                    st.session_state["advanced_screener_result"] = result
                except Exception as exc:
                    st.error(f"Advanced Screener gagal: {type(exc).__name__}: {exc}")
        result = st.session_state.get("advanced_screener_result")
        if result:
            a, b, d = st.columns(3)
            a.metric("Berhasil dianalisis", result.get("raw_success", 0))
            b.metric("Lolos filter", len(result.get("results", [])))
            d.metric("Gagal mengambil data", result.get("failed", 0))
            st.info(result.get("coverage_note", ""))
            rows = result.get("results", [])
            if rows:
                frame = pd.DataFrame(rows)
                columns = [
                    "market", "ticker", "company", "sector", "close", "currency",
                    "ai_score", "score_coverage_pct", "score_label", "trailingPE", "forwardPE",
                    "priceToBook", "returnOnEquity", "returnOnAssets", "debtToEquity",
                    "revenueGrowth", "earningsGrowth", "marketCap", "rsi14",
                    "macd", "macd_signal", "ema20", "ema50", "ema200",
                    "average_turnover", "relative_volume", "atr_pct", "breakout_20d", "bar_date",
                ]
                visible = frame[[name for name in columns if name in frame.columns]]
                st.dataframe(visible, use_container_width=True, hide_index=True)
                st.download_button("Unduh ranking screener CSV", visible.to_csv(index=False).encode("utf-8-sig"), "advanced_stock_screener.csv", "text/csv")
                with st.expander("Penjelasan skor AI dan coverage data"):
                    for item in rows[:10]:
                        st.markdown(f"**{item['ticker']} — {item.get('ai_score')} / 100 ({item.get('score_label')})**")
                        st.json({
                            "factor_scores": item.get("factor_scores", {}),
                            "factor_coverage_pct": item.get("factor_coverage_pct", {}),
                        })
                        st.caption(f"Coverage faktor: {item.get('score_coverage_pct')}%. {item.get('score_method')}")
            else:
                st.warning("Tidak ada saham yang memenuhi filter. Turunkan skor minimum atau periksa coverage data.")
            if result.get("errors"):
                with st.expander(f"Ticker gagal ({len(result['errors'])})"):
                    st.dataframe(pd.DataFrame(result["errors"]), use_container_width=True, hide_index=True)
        st.caption("Skor 0–100 adalah model kuantitatif berbasis aturan yang transparan, bukan model machine learning terlatih atau jaminan return. Data fundamental Yahoo Finance dapat kosong/berbeda mata uang; nilai kosong tidak diisi dengan perkiraan.")

def render_portfolio_risk() -> None:
    st.header("Portfolio & Risk Management")
    st.caption("Analisis posisi, konsentrasi, korelasi, risiko per mata uang, dan skenario harga. Tidak mengirim order.")
    if "portfolio_input" not in st.session_state:
        st.session_state["portfolio_input"] = pd.DataFrame([{"Market":"IDX","Ticker":"TPIA","Shares":0.0,"Average Cost":0.0}])
    edited = st.data_editor(
        st.session_state["portfolio_input"], num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "Market": st.column_config.SelectboxColumn("Market", options=["IDX","US"], required=True),
            "Ticker": st.column_config.TextColumn("Ticker", help="IDX: TPIA, BBCA. US: NVDA, AAPL."),
            "Shares": st.column_config.NumberColumn("Shares", min_value=0.0, step=1.0),
            "Average Cost": st.column_config.NumberColumn("Average Cost", min_value=0.0, step=1.0),
        }, key="portfolio_editor",
    )
    st.session_state["portfolio_input"] = edited
    if st.button("Hitung portfolio intelligence", type="primary"):
        positions, return_series, errors = [], {}, []
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
            try:
                bars, meta = load_daily_history(ticker, market, "1y")
                close = float(bars["Close"].iloc[-1])
                currency = meta.get("currency", "IDR" if market == "IDX" else "USD")
                resolved = meta.get("ticker", ticker)
                try:
                    import yfinance as yf
                    info = yf.Ticker(resolved).get_info()
                    sector = info.get("sector", "Unknown") if isinstance(info, dict) else "Unknown"
                except Exception:
                    sector = "Unknown"
                value, cost = shares * close, shares * avg_cost
                positions.append({
                    "Market":market,"Ticker":resolved,"Sector":sector or "Unknown","Shares":shares,
                    "Average Cost":avg_cost,"Latest Close":close,"Currency":currency,
                    "Market Value":value,"Cost Basis":cost,"Unrealized P/L":value-cost,
                    "Return %":((close/avg_cost)-1)*100 if avg_cost>0 else None,
                })
                return_series[resolved] = bars["Close"].pct_change().dropna().rename(resolved)
            except Exception as exc:
                errors.append({"market":market,"ticker":ticker,"error":f"{type(exc).__name__}: {exc}"})
        if not positions:
            st.warning("Isi minimal satu posisi valid dengan jumlah saham lebih dari nol.")
            if errors:
                st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)
        else:
            st.session_state["portfolio_result"] = {"positions":pd.DataFrame(positions),"returns":return_series,"errors":errors}
    result = st.session_state.get("portfolio_result")
    if not result:
        st.info("Posisi disimpan dalam sesi browser. Masukkan saham dan jumlah kepemilikan untuk memulai.")
        return
    frame = result["positions"].copy()
    st.subheader("Posisi & valuasi")
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if result.get("errors"):
        with st.expander(f"Posisi yang gagal dimuat ({len(result['errors'])})"):
            st.dataframe(pd.DataFrame(result["errors"]), use_container_width=True, hide_index=True)
    st.caption("Nilai IDR dan USD tidak dijumlahkan tanpa kurs FX. Bobot dan risiko dihitung per mata uang.")
    analysis = analyze_portfolio(frame, result["returns"])
    st.subheader("Bobot setiap posisi")
    st.dataframe(analysis["position_exposure"], use_container_width=True, hide_index=True)
    ccy = pd.DataFrame([{"Currency":k,"Market Value":v} for k,v in analysis["currency_exposure"].items()])
    market = pd.DataFrame([{"Market":k,"Market Value":v} for k,v in analysis["market_exposure"].items()])
    col_a,col_b = st.columns(2)
    with col_a:
        st.subheader("Eksposur per mata uang")
        st.dataframe(ccy,use_container_width=True,hide_index=True)
    with col_b:
        st.subheader("Eksposur per pasar")
        st.dataframe(market,use_container_width=True,hide_index=True)
    if not analysis["sector_exposure"].empty:
        sector = analysis["sector_exposure"].copy()
        sector["Weight within currency %"] = sector["Market Value"] / sector.groupby("Currency")["Market Value"].transform("sum") * 100
        st.subheader("Konsentrasi sektor")
        st.dataframe(sector,use_container_width=True,hide_index=True)
    if not analysis["risk"].empty:
        st.subheader("Risk metrics per mata uang")
        st.caption("Coverage di bawah 100% berarti risk metrics hanya mewakili posisi yang memiliki histori return.")
        st.dataframe(analysis["risk"],use_container_width=True,hide_index=True)
        for currency, series in analysis["returns"].items():
            st.line_chart((1+series).cumprod().rename(f"{currency} portfolio growth"))
    if analysis["correlations"]:
        st.subheader("Matriks korelasi")
        for currency,matrix in analysis["correlations"].items():
            with st.expander(f"Korelasi {currency}"):
                st.dataframe(matrix,use_container_width=True)
    st.subheader("Simulasi alokasi dari BUY candidate terbaru")
    st.caption("Alokasi ini simulasi berdasarkan modal terpisah per mata uang. IDX dibulatkan ke lot 100 saham; US menggunakan satuan saham. Bukan instruksi order.")
    try:
        latest_scan = get_dashboard_data(limit=500).get("latest") or {}
        candidates = [item for item in latest_scan.get("results", []) if item.get("signal") == "BUY_CANDIDATE"]
    except Exception:
        candidates = []
    alloc1, alloc2, alloc3 = st.columns(3)
    idx_capital = alloc1.number_input("Modal simulasi IDX (IDR)", min_value=0.0, value=0.0, step=10000000.0, key="alloc_idx_capital")
    us_capital = alloc2.number_input("Modal simulasi US (USD)", min_value=0.0, value=0.0, step=1000.0, key="alloc_us_capital")
    alloc_risk = alloc3.number_input("Risk budget per posisi (%)", min_value=0.1, max_value=5.0, value=1.0, step=0.1, key="alloc_risk")
    if candidates and (idx_capital > 0 or us_capital > 0):
        allocation_rows = []
        for market_name, capital in [("IDX", idx_capital), ("US", us_capital)]:
            if capital <= 0:
                continue
            market_candidates = [item for item in candidates if item.get("market") == market_name and item.get("atr14")]
            if not market_candidates:
                continue
            allocation = allocate_candidates(
                market_candidates, capital, risk_pct=alloc_risk,
                max_total_exposure_pct=60, max_single_position_pct=15, max_positions=8,
            )
            for item in allocation["positions"]:
                plan = item["plan"]
                allocation_rows.append({
                    "Market":market_name,"Ticker":item["ticker"],"Score":item["score"],
                    "Shares":plan["shares"],"Lots":plan.get("lots"),
                    "Lot size":plan.get("lot_size"),"Position value":plan["position_value"],
                    "Weight %":plan["portfolio_weight_pct"],"Planned loss":plan["planned_loss"],
                })
        if allocation_rows:
            st.dataframe(pd.DataFrame(allocation_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Belum ada BUY candidate dengan ATR valid yang dapat dialokasikan.")
    elif not candidates:
        st.info("Belum ada BUY candidate tersimpan dari Daily Stock Signal. Jalankan pemindaian terlebih dahulu.")
    st.subheader("Simulasi skenario harga")
    st.caption("Masukkan perubahan harga hipotetis per saham. Ini analisis sensitivitas, bukan prediksi.")
    scenario_input = frame[["Ticker","Currency","Market Value"]].copy()
    scenario_input["Shock %"] = 0.0
    scenario_edited = st.data_editor(
        scenario_input,use_container_width=True,hide_index=True,
        column_config={"Shock %":st.column_config.NumberColumn("Shock %",min_value=-100.0,max_value=300.0,step=1.0)},
        key="portfolio_scenario_editor",
    )
    scenario = scenario_analysis(frame,dict(zip(scenario_edited["Ticker"],scenario_edited["Shock %"])))
    st.dataframe(scenario,use_container_width=True,hide_index=True)
    st.dataframe(scenario.groupby("Currency")[["Estimated P/L","Scenario Value"]].sum().reset_index(),use_container_width=True,hide_index=True)
    with st.expander("Simulasi risiko kurs USD/IDR"):
        st.caption("Simulasi translasi kurs secara terpisah; harga saham diasumsikan tetap.")
        fx_col1, fx_col2 = st.columns(2)
        usd_idr_spot = fx_col1.number_input("Kurs USD/IDR spot (input manual)", min_value=0.0, value=0.0, step=100.0, key="portfolio_usd_idr")
        fx_shock = fx_col2.slider("Perubahan kurs USD/IDR (%)", -30, 30, 0, key="portfolio_fx_shock")
        if usd_idr_spot > 0:
            fx_result = fx_scenario_analysis(frame, usd_idr_spot, fx_shock)
            fx_a, fx_b, fx_c = st.columns(3)
            fx_a.metric("Nilai portfolio IDR", f"Rp {fx_result['current_portfolio_idr']:,.0f}")
            fx_b.metric("Nilai skenario IDR", f"Rp {fx_result['scenario_portfolio_idr']:,.0f}")
            fx_c.metric("Dampak translasi FX", f"Rp {fx_result['fx_translation_pnl_idr']:,.0f}")
            st.caption(f"Kurs skenario: {fx_result['scenario_usd_idr']:,.2f} · {fx_result['note']}")
        else:
            st.info("Masukkan kurs USD/IDR yang ingin digunakan untuk mengaktifkan simulasi FX.")
    st.caption(analysis["limitations"])

def render_backtesting() -> None:
    st.header("Advanced Backtesting")
    st.caption("Simulasi historis dengan fee, slippage, risk sizing, dan evaluasi walk-forward kronologis.")
    single_tab,wf_tab = st.tabs(["Single ticker backtest","Walk-forward out-of-sample"])
    with single_tab:
        with st.form("backtest_form"):
            c1,c2,c3=st.columns(3)
            market=c1.selectbox("Pasar",["IDX","US"],key="bt_market")
            ticker=c2.text_input("Ticker","TPIA" if market=="IDX" else "NVDA",key="bt_ticker")
            period=c3.selectbox("Periode data",["2y","5y","10y"],index=1,key="bt_period")
            c4,c5,c6=st.columns(3)
            fee=c4.number_input("Fee (bps per sisi)",0.0,500.0,10.0,1.0,key="bt_fee")
            slippage=c5.number_input("Slippage (bps per sisi)",0.0,500.0,10.0,1.0,key="bt_slippage")
            risk=c6.number_input("Risk budget per trade (%)",0.1,5.0,1.0,0.1,key="bt_risk")
            c7,c8=st.columns(2)
            allocation=c7.slider("Maksimum alokasi posisi (%)",1,100,100,key="bt_alloc")/100
            holding=c8.slider("Holding maksimum (sesi)",1,5,5,key="bt_holding")
            submitted=st.form_submit_button("Jalankan backtest",type="primary")
        if submitted:
            try:
                with st.spinner(f"Mengunduh data historis {ticker.upper()}..."):
                    bars,meta=load_daily_history(ticker,market,period)
                    result=backtest(bars,fee_bps=fee,slippage_bps=slippage,risk_fraction=risk/100,max_allocation=allocation,max_holding_sessions=holding)
                st.session_state["backtest_result"]={"ticker":meta.get("ticker",ticker.upper()),"market":market,"result":result}
            except Exception as exc:
                st.error(f"Backtest gagal: {type(exc).__name__}: {exc}")
        saved=st.session_state.get("backtest_result")
        if saved:
            r=saved["result"]
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
                st.info("Tidak ada transaksi yang memenuhi aturan strategi pada periode ini.")
            st.warning(r["limitations"])
    with wf_tab:
        st.caption("Expanding-history chronological walk-forward. Histori sebelum periode test menjadi warm-up indikator; aturan tetap dan tidak dioptimalkan pada test.")
        with st.form("walk_forward_form"):
            w1,w2,w3=st.columns(3)
            wf_market=w1.selectbox("Pasar",["IDX","US"],key="wf_market")
            wf_ticker=w2.text_input("Ticker","BBCA" if wf_market=="IDX" else "MSFT",key="wf_ticker")
            wf_period=w3.selectbox("Riwayat",["5y","10y"],index=0,key="wf_period")
            w4,w5=st.columns(2)
            train_months=w4.selectbox("Warm-up history (bulan)",[12,18,24,36],index=2,key="wf_train")
            test_months=w5.selectbox("Test window (bulan)",[3,6,12],index=1,key="wf_test")
            w6,w7,w8=st.columns(3)
            wf_fee=w6.number_input("Fee per sisi (bps)",0.0,500.0,10.0,key="wf_fee")
            wf_slippage=w7.number_input("Slippage per sisi (bps)",0.0,500.0,10.0,key="wf_slippage")
            wf_risk=w8.number_input("Risk per trade (%)",0.1,5.0,1.0,key="wf_risk")
            wf_submit=st.form_submit_button("Jalankan walk-forward",type="primary")
        if wf_submit:
            try:
                with st.spinner("Menjalankan evaluasi out-of-sample per fold..."):
                    bars,meta=load_daily_history(wf_ticker,wf_market,wf_period)
                    result=walk_forward_backtest(bars,train_months=train_months,test_months=test_months,fee_bps=wf_fee,slippage_bps=wf_slippage,risk_fraction=wf_risk/100)
                st.session_state["walk_forward_result"]={"ticker":meta.get("ticker",wf_ticker),"market":wf_market,"result":result}
            except Exception as exc:
                st.error(f"Walk-forward gagal: {type(exc).__name__}: {exc}")
        saved=st.session_state.get("walk_forward_result")
        if saved:
            r=saved["result"]
            st.subheader(f"{saved['ticker']} · {saved['market']}")
            m1,m2,m3,m4,m5=st.columns(5)
            m1.metric("OOS return gabungan",f"{r['combined_oos_return_pct']:.2f}%")
            m2.metric("Win rate tertimbang",f"{r['weighted_win_rate_pct']:.1f}%")
            m3.metric("Total trade",r["total_trades"])
            m4.metric("Fold positif",f"{r['profitable_folds_pct']:.1f}%")
            m5.metric("Worst fold DD",f"{r['worst_fold_drawdown_pct']:.2f}%")
            st.dataframe(pd.DataFrame(r["folds"]),use_container_width=True,hide_index=True)
            st.caption(r["method"])
            st.warning(r["limitations"])

def render_performance_dashboard() -> None:
    st.header("Performance & Learning Dashboard")
    st.caption("Histori scan, kualitas sinyal, dan forward return aktual setelah 1/3/5/10/20 sesi perdagangan.")
    backend=backend_name()
    if backend=="PostgreSQL":
        st.success("Database cloud PostgreSQL aktif. Histori scan disimpan secara persisten.")
    else:
        st.warning("Database aktif masih SQLite. Konfigurasikan DATABASE_URL untuk histori cloud persisten.")
    if st.button("Perbarui outcome 1/3/5/10/20 sesi",type="primary"):
        try:
            with st.spinner("Memeriksa harga penutupan setelah tanggal sinyal..."):
                refresh=refresh_forward_outcomes(limit=1000)
            st.success(f"{refresh['updated_outcomes']} outcome baru tercatat dari {refresh['pending_signals']} sinyal tertunda.")
            if refresh["errors"]:
                with st.expander(f"Ticker belum berhasil diperbarui ({len(refresh['errors'])})"):
                    st.dataframe(pd.DataFrame(refresh["errors"]),use_container_width=True,hide_index=True)
        except Exception as exc:
            st.error(f"Pembaruan outcome gagal: {type(exc).__name__}: {exc}")
    try:
        data=get_dashboard_data(limit=1000)
        latest,history,outcomes=data.get("latest"),data.get("history") or [],data.get("outcomes") or []
    except Exception as exc:
        st.error(f"Database performa tidak dapat dibaca: {type(exc).__name__}: {exc}")
        return
    if latest:
        counts=latest.get("counts",{})
        cols=st.columns(5)
        cols[0].metric("Saham dipindai terakhir",counts.get("scanned",0))
        cols[1].metric("BUY candidate",counts.get("buy_candidate",0))
        cols[2].metric("WATCH",counts.get("watch",0))
        cols[3].metric("NO TRADE",counts.get("no_trade",0))
        cols[4].metric("Gagal ambil data",counts.get("failed",0))
        st.caption(f"Scan ID: {latest.get('scan_id','N/A')} · Data tiap ticker memakai tanggal bar masing-masing.")
    else:
        st.info("Belum ada scan tersimpan. Jalankan Daily Stock Signal.")
    if history:
        frame=pd.DataFrame(history)
        cols=[c for c in ["bar_date","market","ticker","signal","score","close","outcome_1d_return_pct","outcome_3d_return_pct","outcome_5d_return_pct","outcome_10d_return_pct","outcome_20d_return_pct"] if c in frame.columns]
        st.subheader("Riwayat sinyal dan forward outcome")
        st.dataframe(frame[cols],use_container_width=True,hide_index=True)
        st.download_button("Unduh histori sinyal CSV",frame[cols].to_csv(index=False).encode("utf-8-sig"),"signal_history.csv","text/csv")
        st.bar_chart(frame["signal"].value_counts().rename_axis("Signal").reset_index(name="Count").set_index("Signal"))
        st.subheader("Evaluasi hasil berdasarkan sinyal")
        for horizon,column in [(1,"outcome_1d_return_pct"),(3,"outcome_3d_return_pct"),(5,"outcome_5d_return_pct"),(10,"outcome_10d_return_pct"),(20,"outcome_20d_return_pct")]:
            if column in frame:
                valid=frame[frame[column].notna()]
                if not valid.empty:
                    group_keys=[key for key in ["ruleset_version","signal"] if key in valid.columns]
                    grouped=valid.groupby(group_keys, dropna=False)[column].agg(["count","mean","median",lambda values: (values > 0).mean()*100])
                    grouped.columns=["Observasi","Rata-rata return %","Median return %","Win rate %"]
                    st.markdown(f"**Forward {horizon} sesi — kualitas strategi/sinyal**")
                    st.dataframe(grouped,use_container_width=True)
    else:
        st.info("Histori sinyal belum tersedia.")
    if outcomes:
        st.subheader("Forward outcome (observasi aktual)")
        outcome_frame=pd.DataFrame(outcomes)
        outcome_frame["Horizon"]=outcome_frame["horizon"].astype(str)+" sesi"
        outcome_frame=outcome_frame.rename(columns={"observations":"Observasi","avg_forward_return_pct":"Rata-rata return (%)","positive_rate_pct":"Outcome positif (%)"})
        st.dataframe(outcome_frame[["Horizon","Observasi","Rata-rata return (%)","Outcome positif (%)"]],use_container_width=True,hide_index=True)
    else:
        st.info("Outcome forward belum tercatat. Sistem menunggu harga penutupan untuk setiap horizon tersedia.")
    st.caption("Return historis adalah hasil observasi setelah tanggal sinyal, bukan prediksi. Evaluasi per sinyal belum menghilangkan seluruh bias survivorship dan data vendor.")
