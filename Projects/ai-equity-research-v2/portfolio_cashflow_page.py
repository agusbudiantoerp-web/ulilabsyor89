"""Streamlit interface for portfolio cash-flow and return analysis."""
from __future__ import annotations

import math
import pandas as pd
import streamlit as st

from portfolio_cashflow import calculate_twr, calculate_xirr, cash_flow_ledger, reconcile_portfolio_ledger
from portfolio_tax_lots import calculate_tax_lots
from portfolio_reconciliation import reconcile_broker_statement
from portfolio_event_store import create_event, delete_event, list_events
from portfolio_valuation_store import save_valuations, list_valuations, delete_valuations
from security_controls import record_audit_event
from report_export_utils import safe_csv_bytes


def _audit_cashflow(owner, role, action, resource_type, resource_id, details):
    try:
        record_audit_event(owner, role, action, resource_type, resource_id, details=details)
    except Exception as exc:
        st.warning(f"Data tersimpan, tetapi audit event gagal dicatat ({type(exc).__name__}).")


def render_portfolio_cashflow() -> None:
    owner = str(st.session_state.get("_auth_subject_id") or "").strip()
    role = st.session_state.get("_auth_role")
    if not owner:
        st.error("Identitas pengguna terverifikasi tidak tersedia.")
        return
    st.subheader("Portfolio Cash Flow, Dividend Ledger & Returns")
    st.caption(
        "Catat arus kas investor dan aktivitas investasi. Perhitungan TWR mengeluarkan "
        "setoran/penarikan eksternal; XIRR mengukur return berbobot arus kas."
    )
    st.caption("Event transaksi disimpan permanen dan dibatasi berdasarkan identitas pengguna. Valuasi TWR masih dimasukkan pada sesi aktif.")
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
            cash_flow_ledger([row])
            event_id = create_event(owner, row)
            _audit_cashflow(owner, role, "PORTFOLIO_CASHFLOW_EVENT_CREATE", "portfolio_cashflow_event", event_id, {"event_type": event_type, "ticker": ticker.upper()})
            st.success(f"Event tersimpan permanen. ID: {event_id[:8]}")
            st.rerun()
        except Exception as exc:
            st.error(f"Event tidak valid: {type(exc).__name__}: {exc}")

    try:
        stored_events = list_events(owner)
        events = pd.DataFrame(stored_events)
    except Exception as exc:
        st.error(f"Portfolio event store tidak dapat dibaca ({type(exc).__name__}).")
        return
    st.markdown("**Event ledger**")
    if not events.empty:
        st.dataframe(events, use_container_width=True, hide_index=True)
        st.download_button(
            "Unduh event ledger CSV", safe_csv_bytes(events),
            file_name="portfolio_cashflow_ledger.csv", mime="text/csv",
        )
        delete_options = {
            f"{row['date']} · {row['event_type']} · {row.get('ticker') or 'CASH'} · {row['id'][:8]}": row["id"]
            for row in stored_events
        }
        selected_event = st.selectbox("Pilih event untuk dihapus", list(delete_options), key="cashflow_delete_select")
        if st.button("Hapus event terpilih", type="secondary"):
            try:
                if delete_event(owner, delete_options[selected_event]):
                    _audit_cashflow(owner, role, "PORTFOLIO_CASHFLOW_EVENT_DELETE", "portfolio_cashflow_event", delete_options[selected_event], {})
                    st.success("Event dihapus.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Event tidak dapat dihapus ({type(exc).__name__}).")
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

    with st.expander("Rekonsiliasi event dengan broker statement CSV", expanded=False):
        st.caption(
            "Unggah statement broker dengan kolom date,event_type,amount,ticker,quantity,price. "
            "Pastikan semua nominal menggunakan mata uang dasar yang sama dengan internal ledger. "
            "Hasil hanya menandai selisih; tidak mengubah event tersimpan."
        )
        broker_file = st.file_uploader(
            "Broker statement CSV", type=["csv"], key="portfolio_broker_statement_upload",
        )
        date_tolerance = st.number_input(
            "Toleransi perbedaan tanggal (hari)", min_value=0, max_value=30,
            value=1, key="portfolio_broker_date_tolerance",
        )
        if st.button("Bandingkan dengan internal ledger", key="portfolio_broker_reconcile"):
            try:
                if broker_file is None:
                    raise ValueError("Unggah broker statement CSV terlebih dahulu.")
                broker_frame = pd.read_csv(broker_file)
                broker_result = reconcile_broker_statement(
                    events, broker_frame, date_tolerance_days=int(date_tolerance),
                )
                st.session_state["portfolio_broker_reconciliation_details"] = broker_result["details"].copy()
                st.session_state["portfolio_broker_reconciliation_metrics"] = {
                    key: broker_result[key] for key in (
                        "internal_event_count", "broker_event_count", "matched_count",
                        "mismatch_count", "missing_in_broker_count",
                        "unexpected_in_broker_count", "status_counts",
                    )
                }
            except Exception as exc:
                st.error(f"Rekonsiliasi broker gagal: {type(exc).__name__}: {exc}")
        broker_details = st.session_state.get("portfolio_broker_reconciliation_details")
        broker_metrics = st.session_state.get("portfolio_broker_reconciliation_metrics") or {}
        if broker_metrics:
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Matched", broker_metrics["matched_count"])
            b2.metric("Mismatches", broker_metrics["mismatch_count"])
            b3.metric("Missing in broker", broker_metrics["missing_in_broker_count"])
            b4.metric("Unexpected in broker", broker_metrics["unexpected_in_broker_count"])
            if isinstance(broker_details, pd.DataFrame):
                st.dataframe(broker_details, use_container_width=True, hide_index=True)
                st.download_button(
                    "Unduh broker reconciliation CSV",
                    safe_csv_bytes(broker_details),
                    file_name="broker_statement_reconciliation.csv", mime="text/csv",
                    key="portfolio_broker_reconciliation_download",
                )

    if not events.empty:
        st.markdown("**Rekonsiliasi saldo kas & saham**")
        opening_cash = st.number_input(
            "Saldo kas awal sebelum event pertama", min_value=0.0, value=0.0,
            key="portfolio_cashflow_opening_cash",
        )
        opening_positions_raw = st.text_input(
            "Saldo saham awal (format TICKER:jumlah, pisahkan koma)",
            value="", key="portfolio_cashflow_opening_positions",
            help="Contoh: BBCA:100, TLKM:50. Isi bila histori event dimulai setelah Anda sudah memiliki saham.",
        )
        if st.button("Rekonsiliasi cash & holdings", key="portfolio_cashflow_reconcile"):
            try:
                opening_positions = {}
                if opening_positions_raw.strip():
                    for item in opening_positions_raw.split(","):
                        parts = item.strip().split(":")
                        if len(parts) != 2 or not parts[0].strip():
                            raise ValueError("Format saldo saham awal harus TICKER:jumlah.")
                        symbol, shares = parts[0].strip().upper(), float(parts[1].strip())
                        if symbol in opening_positions:
                            raise ValueError(f"Ticker saldo awal duplikat: {symbol}.")
                        if not math.isfinite(shares) or shares <= 0:
                            raise ValueError(f"Jumlah saham awal {symbol} harus positif.")
                        opening_positions[symbol] = shares
                reconciliation = reconcile_portfolio_ledger(
                    events, initial_cash=opening_cash, initial_positions=opening_positions
                )
                st.metric("Saldo kas hasil rekonsiliasi", f"{reconciliation['cash_balance']:,.2f}")
                holdings = pd.DataFrame([
                    {"Ticker": ticker, "Shares": shares}
                    for ticker, shares in reconciliation["positions"].items()
                ])
                st.dataframe(holdings, use_container_width=True, hide_index=True)
                for warning in reconciliation["warnings"]:
                    st.warning(warning)
                st.caption(reconciliation["limitations"])

                st.markdown("**Tax lot & realized profit/loss**")
                tax_method = st.selectbox(
                    "Metode cost basis", ["FIFO", "AVERAGE_COST"],
                    key="portfolio_tax_lot_method",
                    help="FIFO memakai lot pembelian tertua; Average Cost memakai biaya rata-rata tertimbang.",
                )
                opening_lots_raw = st.text_input(
                    "Tax lot awal (format TICKER:jumlah:biaya_per_saham; pisahkan dengan koma)",
                    value="", key="portfolio_tax_lot_opening",
                    help="Contoh: BBCA:100:8500, TLKM:50:3000. Isi hanya untuk saham yang dibeli sebelum histori ledger.",
                )
                if st.button("Hitung realized P&L & tax lots", key="portfolio_tax_lot_calculate"):
                    try:
                        opening_lots = []
                        if opening_lots_raw.strip():
                            for item in opening_lots_raw.split(","):
                                parts = [part.strip() for part in item.split(":")]
                                if len(parts) != 3 or not parts[0]:
                                    raise ValueError("Format tax lot awal harus TICKER:jumlah:biaya_per_saham.")
                                symbol, shares, unit_cost = parts[0].upper(), float(parts[1]), float(parts[2])
                                opening_lots.append({
                                    "ticker": symbol, "quantity": shares,
                                    "unit_cost": unit_cost, "acquisition_date": "opening",
                                })
                        tax_result = calculate_tax_lots(
                            events, method=tax_method, opening_lots=opening_lots,
                        )
                        st.session_state["portfolio_tax_lot_realized_frame"] = tax_result["realized_trades"].copy()
                        st.session_state["portfolio_tax_lot_open_lots_frame"] = tax_result["open_lots"].copy()
                        st.session_state["portfolio_tax_lot_metrics"] = {
                            "method": tax_result["method"],
                            "realized_pnl": tax_result["realized_pnl"],
                            "realized_cost_basis": tax_result["realized_cost_basis"],
                            "realized_sale_proceeds": tax_result["realized_sale_proceeds"],
                            "open_cost_basis": tax_result["open_cost_basis"],
                        }
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Realized P&L", f"{tax_result['realized_pnl']:,.2f}")
                        m2.metric("Cost basis terjual", f"{tax_result['realized_cost_basis']:,.2f}")
                        m3.metric("Cost basis tersisa", f"{tax_result['open_cost_basis']:,.2f}")
                        st.caption(
                            f"Metode {tax_result['method']} · Proceeds penjualan "
                            f"{tax_result['realized_sale_proceeds']:,.2f}"
                        )
                        st.markdown("**Rincian realized trades**")
                        st.dataframe(tax_result["realized_trades"], use_container_width=True, hide_index=True)
                        st.markdown("**Tax lots tersisa**")
                        st.dataframe(tax_result["open_lots"], use_container_width=True, hide_index=True)
                        for warning in tax_result["warnings"]:
                            st.warning(warning)
                        st.caption(tax_result["limitations"])
                    except Exception as exc:
                        st.error(f"Tax lot tidak dapat dihitung: {type(exc).__name__}: {exc}")
            except Exception as exc:
                st.error(f"Rekonsiliasi gagal: {type(exc).__name__}: {exc}")

    st.divider()
    st.markdown("**Time-Weighted Return (TWR)**")
    st.caption(
        "Masukkan valuasi akhir setiap periode. External flow positif untuk setoran "
        "dan negatif untuk penarikan yang terjadi tepat sebelum valuasi periode tersebut."
    )
    c1, c2 = st.columns(2)
    valuation_portfolio_id = c1.text_input("Portfolio ID untuk histori valuasi", value="main", key="portfolio_valuation_portfolio_id")
    valuation_currency = c2.selectbox("Mata uang valuasi", ["IDR", "USD"], key="portfolio_valuation_currency")
    try:
        saved_valuations = list_valuations(owner, valuation_portfolio_id)
    except Exception as exc:
        st.error(f"Histori valuasi tidak dapat dibaca ({type(exc).__name__}).")
        saved_valuations = pd.DataFrame()
    default_values = pd.DataFrame([
        {"date": pd.Timestamp("2026-01-01"), "portfolio_value": 100000000, "external_flow": 0},
        {"date": pd.Timestamp("2026-02-01"), "portfolio_value": 105000000, "external_flow": 0},
    ])
    valuation_key = "portfolio_cashflow_valuations_" + valuation_portfolio_id
    if valuation_key not in st.session_state:
        if not saved_valuations.empty:
            st.session_state[valuation_key] = saved_valuations[["date", "portfolio_value", "external_flow"]].copy()
            st.session_state[valuation_key]["date"] = pd.to_datetime(st.session_state[valuation_key]["date"])
        else:
            st.session_state[valuation_key] = default_values
    valuations = st.data_editor(
        st.session_state[valuation_key], num_rows="dynamic", use_container_width=True,
        key="portfolio_cashflow_valuation_editor_" + valuation_portfolio_id,
        column_config={
            "date": st.column_config.DateColumn("Tanggal"),
            "portfolio_value": st.column_config.NumberColumn("Nilai portfolio", min_value=0.01),
            "external_flow": st.column_config.NumberColumn("External flow (+ setoran / - penarikan)"),
        },
    )
    save_col, delete_col = st.columns(2)
    if save_col.button("Simpan histori valuasi permanen", key="portfolio_cashflow_save_valuations"):
        try:
            count = save_valuations(owner, valuation_portfolio_id, valuations, currency=valuation_currency)
            _audit_cashflow(owner, role, "PORTFOLIO_VALUATIONS_SAVE", "portfolio_valuations", valuation_portfolio_id, {"row_count": count, "currency": valuation_currency})
            st.success(f"{count} titik valuasi tersimpan untuk portfolio {valuation_portfolio_id}.")
            st.rerun()
        except Exception as exc:
            st.error(f"Histori valuasi tidak dapat disimpan: {type(exc).__name__}: {exc}")
    if delete_col.button("Hapus histori valuasi portfolio ini", key="portfolio_cashflow_delete_valuations"):
        try:
            removed = delete_valuations(owner, valuation_portfolio_id)
            _audit_cashflow(owner, role, "PORTFOLIO_VALUATIONS_DELETE", "portfolio_valuations", valuation_portfolio_id, {"row_count": removed})
            st.session_state.pop(valuation_key, None)
            st.success(f"{removed} titik valuasi dihapus.")
            st.rerun()
        except Exception as exc:
            st.error(f"Histori valuasi tidak dapat dihapus: {type(exc).__name__}.")
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
