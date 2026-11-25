"""Streamlit interface for portfolio cash-flow and return analysis."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from portfolio_cashflow import calculate_twr, calculate_xirr, cash_flow_ledger


def render_portfolio_cashflow() -> None:
    st.subheader("Portfolio Cash Flow, Dividend Ledger & Returns")
    st.caption(
        "Catat arus kas investor dan aktivitas investasi. Perhitungan TWR mengeluarkan "
        "setoran/penarikan eksternal; XIRR mengukur return berbobot arus kas."
    )
    st.info(
        "Ledger ini saat ini disimpan dalam sesi dashboard aktif. Unduh CSV untuk arsip; "
        "penyimpanan permanen multi-user belum diaktifkan pada halaman ini."
    )
    state_key = "portfolio_cashflow_events"
    if state_key not in st.session_state:
        st.session_state[state_key] = pd.DataFrame(columns=[
            "date", "event_type", "amount", "ticker", "quantity", "price", "notes"
        ])
    with st.form("portfolio_cashflow_add_event", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        event_date = c1.date_input("Tanggal event")
        event_type = c2.selectbox(
            "Jenis event",
            ["DEPOSIT", "WITHDRAWAL", "DIVIDEND", "BUY", "SELL", "FEE", "TAX", "SPLIT"],
        )
        amount = c3.number_input(
            "Nominal (mata uang dasar)", min_value=0.0, value=0.0,
            help="Nominal absolut. Untuk SPLIT isi 0; rasio split dimasukkan di quantity.",
        )
        c4, c5, c6 = st.columns(3)
        ticker = c4.text_input("Ticker (wajib untuk saham/dividen/split)")
        quantity = c5.number_input("Quantity / rasio split", min_value=0.0, value=0.0)
        price = c6.number_input("Harga per unit", min_value=0.0, value=0.0)
        notes = st.text_input("Catatan")
        submitted = st.form_submit_button("Tambahkan event")
    if submitted:
        row = {
            "date": str(event_date), "event_type": event_type, "amount": amount,
            "ticker": ticker, "quantity": quantity if quantity > 0 else None,
            "price": price if price > 0 else None, "notes": notes,
        }
        try:
            candidate = pd.concat([st.session_state[state_key], pd.DataFrame([row])], ignore_index=True)
            ledger = cash_flow_ledger(candidate)
            st.session_state[state_key] = ledger["events"]
            st.success("Event berhasil ditambahkan.")
        except Exception as exc:
            st.error(f"Event tidak valid: {type(exc).__name__}: {exc}")

    events = st.session_state[state_key]
    st.markdown("**Event ledger**")
    if not events.empty:
        st.dataframe(events, use_container_width=True, hide_index=True)
        st.download_button(
            "Unduh event ledger CSV", events.to_csv(index=False).encode("utf-8-sig"),
            file_name="portfolio_cashflow_ledger.csv", mime="text/csv",
        )
        if st.button("Hapus seluruh ledger sesi", type="secondary"):
            st.session_state[state_key] = pd.DataFrame(columns=events.columns)
            st.rerun()
        try:
            summary = cash_flow_ledger(events)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Net setoran", f"{summary['net_external_contributions']:,.2f}")
            c2.metric("Pendapatan dividen", f"{summary['dividend_income']:,.2f}")
            c3.metric("Biaya & pajak", f"{summary['transaction_costs']:,.2f}")
            c4.metric("Jumlah event", summary["event_count"])
            st.caption(summary["currency_note"])
        except Exception as exc:
            st.error(f"Ledger tidak dapat dihitung: {type(exc).__name__}: {exc}")
    else:
        st.caption("Belum ada event yang dicatat.")

    st.divider()
    st.markdown("**Time-Weighted Return (TWR)**")
    st.caption(
        "Masukkan valuasi akhir setiap periode. External flow positif untuk setoran "
        "dan negatif untuk penarikan yang terjadi tepat sebelum valuasi periode tersebut."
    )
    default_values = pd.DataFrame([
        {"date": pd.Timestamp("2026-01-01"), "portfolio_value": 100000000, "external_flow": 0},
        {"date": pd.Timestamp("2026-02-01"), "portfolio_value": 105000000, "external_flow": 0},
    ])
    valuation_key = "portfolio_cashflow_valuations"
    if valuation_key not in st.session_state:
        st.session_state[valuation_key] = default_values
    valuations = st.data_editor(
        st.session_state[valuation_key], num_rows="dynamic", use_container_width=True,
        key="portfolio_cashflow_valuation_editor",
        column_config={
            "date": st.column_config.DateColumn("Tanggal"),
            "portfolio_value": st.column_config.NumberColumn("Nilai portfolio", min_value=0.01),
            "external_flow": st.column_config.NumberColumn("External flow (+ setoran / - penarikan)"),
        },
    )
    if st.button("Hitung TWR", key="portfolio_cashflow_calc_twr"):
        try:
            result = calculate_twr(valuations)
            st.metric("TWR kumulatif", f"{result['twr_pct']:.2f}%")
            st.caption(result["method"])
            st.dataframe(pd.DataFrame({
                "Sub-periode": range(1, result["period_count"] + 1),
                "Return (%)": result["period_returns_pct"],
            }), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"TWR tidak dapat dihitung: {type(exc).__name__}: {exc}")

    st.divider()
    st.markdown("**Money-Weighted Return (XIRR)**")
    st.caption(
        "XIRR memakai setoran sebagai arus kas negatif, penarikan sebagai positif, "
        "serta nilai akhir portfolio sebagai arus kas positif pada tanggal valuasi."
    )
    c1, c2 = st.columns(2)
    ending_value = c1.number_input(
        "Nilai akhir portfolio", min_value=0.0, value=0.0, key="portfolio_cashflow_ending_value"
    )
    ending_date = c2.date_input("Tanggal valuasi akhir", key="portfolio_cashflow_ending_date")
    include_dividends = st.checkbox(
        "Dividen merupakan kas yang dibayarkan keluar kepada investor",
        value=False, help="Centang hanya jika dividen diterima di luar portfolio dan belum tercermin dalam nilai akhir.",
    )
    if st.button("Hitung XIRR", key="portfolio_cashflow_calc_xirr"):
        try:
            cash_flows = []
            for row in events.to_dict("records"):
                if row["event_type"] == "DEPOSIT":
                    cash_flows.append({"date": row["date"], "amount": -float(row["amount"])})
                elif row["event_type"] == "WITHDRAWAL":
                    cash_flows.append({"date": row["date"], "amount": float(row["amount"])})
                elif include_dividends and row["event_type"] == "DIVIDEND":
                    cash_flows.append({"date": row["date"], "amount": float(row["amount"])})
            result = calculate_xirr(
                cash_flows, ending_value=ending_value,
                ending_date=ending_date if ending_value > 0 else None,
            )
            st.metric("XIRR tahunan", f"{result['xirr_pct']:.2f}%")
            st.caption(result["method"])
        except Exception as exc:
            st.error(f"XIRR tidak dapat dihitung: {type(exc).__name__}: {exc}")
