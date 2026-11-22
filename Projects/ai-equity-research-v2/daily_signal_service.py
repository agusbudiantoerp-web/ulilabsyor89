"""Shared service used by CLI, dashboard and messaging adapters."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from daily_signal_scanner import scan_universe
from daily_signal_storage import (
    save_scan, latest_scan, signal_history, get_pending_outcomes,
    record_outcome, outcome_summary,
)
from daily_signal_engine import load_daily_history

REPORT_TZ = ZoneInfo("Asia/Singapore")


def run_daily_scan(universe=None, config=None, db_path=None, max_workers=4):
    result = scan_universe(universe=universe, config=config, max_workers=max_workers)
    result["scan_id"] = save_scan(result, db_path=db_path)
    return result


def get_dashboard_data(limit=100, db_path=None):
    return {
        "latest": latest_scan(db_path=db_path),
        "history": signal_history(limit=limit, db_path=db_path),
        "outcomes": outcome_summary(db_path=db_path),
    }


def refresh_forward_outcomes(db_path=None, limit=500):
    """Record observed 1/3/5-session forward returns once future daily closes exist."""
    pending = get_pending_outcomes(limit=limit, db_path=db_path)
    grouped = {}
    for item in pending:
        key = (item.get("market"), item.get("ticker"))
        grouped.setdefault(key, []).append(item)

    updated = 0
    errors = []
    for (market, ticker), signals in grouped.items():
        try:
            bars, _ = load_daily_history(ticker, market, "1y")
            index = pd.to_datetime(bars.index).tz_localize(None) if getattr(bars.index, "tz", None) is not None else pd.to_datetime(bars.index)
            bars = bars.copy()
            bars.index = index.normalize()
            for signal in signals:
                signal_date = pd.Timestamp(signal["bar_date"]).normalize()
                future = bars.loc[bars.index > signal_date]
                missing = signal.get("missing_horizons", [])
                for horizon in missing:
                    if len(future) >= horizon:
                        observed = future.iloc[horizon - 1]
                        observed_date = future.index[horizon - 1].date().isoformat()
                        record_outcome(
                            int(signal["id"]), int(horizon), observed_date,
                            float(observed["Close"]), db_path=db_path,
                        )
                        updated += 1
        except Exception as exc:
            errors.append({"market": market, "ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})
    return {"pending_signals": len(pending), "updated_outcomes": updated, "errors": errors}


def _price(value, currency=""):
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.2f} {currency or ''}".strip()
    except (TypeError, ValueError):
        return "N/A"


def _number(value, digits=2):
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def _find_tpia(results):
    return next(
        (item for item in results if str(item.get("ticker", "")).upper() in {"TPIA", "TPIA.JK"}),
        None,
    )


def format_report(scan: dict) -> str:
    """Format deterministic scan results; always expose the dedicated TPIA row."""
    now = datetime.now(REPORT_TZ)
    counts = scan.get("counts", {})
    results = scan.get("results", [])
    errors = scan.get("errors", [])

    lines = [
        "📊 AI EQUITY RESEARCH — DAILY MARKET BRIEF",
        f"Waktu laporan: {now:%A, %d %B %Y | %H:%M SGT}",
        "Universe: watchlist IDX + US (bukan seluruh pasar)",
        "",
        f"Dipindai: {counts.get('scanned', 0)} | Data berhasil: {counts.get('success', 0)} | Gagal: {counts.get('failed', 0)}",
        f"BUY CANDIDATE: {counts.get('buy_candidate', 0)} | WATCH: {counts.get('watch', 0)} | NO TRADE: {counts.get('no_trade', 0)}",
        "",
    ]

    buys = [item for item in results if item.get("signal") == "BUY_CANDIDATE"]
    watches = [item for item in results if item.get("signal") == "WATCH"]
    if buys:
        lines.append("🟢 KANDIDAT PRIORITAS (bukan instruksi beli)")
        for item in buys[:5]:
            currency = item.get("currency")
            lines.extend([
                f"• {item.get('market')} {item.get('ticker')} | skor {item.get('score')}/100 | penutupan {_price(item.get('close'), currency)}",
                f"  Entry indikatif {_price(item.get('entry_low'), currency)} – {_price(item.get('entry_high'), currency)}",
                f"  Stop {_price(item.get('stop_loss'), currency)} | Target {_price(item.get('target'), currency)} | R/R {_number(item.get('reward_risk'))}",
                f"  Bar {item.get('bar_date', 'N/A')} | RSI {_number(item.get('rsi14'), 1)} | RelVol {_number(item.get('relative_volume'))}x",
            ])
            if item.get("warnings"):
                lines.append("  Peringatan: " + "; ".join(map(str, item["warnings"])))
    else:
        lines.append("🟢 KANDIDAT PRIORITAS: Tidak ada saham yang lolos seluruh kriteria.")

    if watches:
        lines.extend(["", "🟡 WATCHLIST (perlu konfirmasi; bukan sinyal beli)"])
        for item in watches[:5]:
            lines.append(
                f"• {item.get('market')} {item.get('ticker')} | skor {item.get('score')}/100 | "
                f"close {_price(item.get('close'), item.get('currency'))} | RSI {_number(item.get('rsi14'), 1)} | "
                f"RelVol {_number(item.get('relative_volume'))}x | bar {item.get('bar_date', 'N/A')}"
            )

    tpia = _find_tpia(results)
    if tpia:
        currency = tpia.get("currency") or "IDR"
        lines.extend([
            "",
            "🔎 PANTAUAN KHUSUS TPIA",
            f"Status: {tpia.get('signal', 'N/A')} | Skor: {tpia.get('score', 'N/A')}/100",
            f"Harga penutupan: {_price(tpia.get('close'), currency)} | Tanggal data: {tpia.get('bar_date', 'N/A')}",
            f"RSI14: {_number(tpia.get('rsi14'), 2)} | Relative Volume: {_number(tpia.get('relative_volume'))}x | Return 5 sesi: {_number(tpia.get('return5_pct'))}%",
            f"Entry indikatif: {_price(tpia.get('entry_low'), currency)} – {_price(tpia.get('entry_high'), currency)}",
            f"Stop: {_price(tpia.get('stop_loss'), currency)} | Target: {_price(tpia.get('target'), currency)} | R/R: {_number(tpia.get('reward_risk'))}",
        ])
        if tpia.get("warnings"):
            lines.append("Peringatan TPIA: " + "; ".join(map(str, tpia["warnings"])))
        if tpia.get("signal") == "NO_TRADE":
            lines.append("Interpretasi: belum memenuhi aturan sinyal; level harga bersifat indikatif, bukan instruksi transaksi.")
    else:
        lines.extend(["", "🔎 PANTAUAN KHUSUS TPIA", "TPIA tidak tersedia pada hasil pemindaian ini."])

    if errors:
        lines.extend(["", "⚠️ DATA TIDAK BERHASIL DIAMBIL"])
        for error in errors[:8]:
            lines.append(
                f"• {error.get('market')} {error.get('symbol')}: "
                f"{str(error.get('error', 'Unknown error'))[:180]}"
            )
        if len(errors) > 8:
            lines.append(f"• Dan {len(errors) - 8} error lainnya.")

    if not results and errors:
        lines.extend(["", "Tidak ada kesimpulan pasar yang dapat dibuat karena data gagal diambil."])

    lines.extend([
        "",
        "SUMBER & BATASAN",
        "• Data harga: Yahoo Finance; memakai bar harian terakhir yang tersedia, bukan harga live.",
        "• Watchlist awal terbatas; cakupan pasar tidak menyeluruh.",
        "• Sinyal teknikal dan level risiko adalah hipotesis riset; bukan rekomendasi atau instruksi transaksi.",
        "• Backtest historis harus memperhitungkan biaya, slippage, likuiditas, aksi korporasi, dan bias survivorship.",
        "• Sistem tidak terhubung ke broker dan tidak mengirim order.",
    ])
    return "\n".join(lines)
