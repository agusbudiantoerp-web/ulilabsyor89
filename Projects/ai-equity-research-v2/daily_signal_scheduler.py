"""Scheduled daily employee runner for Windows Task Scheduler / cron."""
from __future__ import annotations
import argparse, asyncio, logging, os, sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from daily_signal_service import run_daily_scan, format_report
from daily_signal_telegram import send_report
from ollama_analyst import enrich_report

TZ=ZoneInfo("Asia/Singapore")
DB_PATH=os.getenv("DAILY_SIGNAL_DB", "data/daily_signals.sqlite3")
LOG_PATH=Path("logs/daily_employee.log")


def _setup_logging():
    LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=str(LOG_PATH),level=logging.INFO,
      format="%(asctime)s %(levelname)s %(message)s",encoding="utf-8")


def _already_sent(day: str) -> bool:
    Path(DB_PATH).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB_PATH,timeout=30) as db:
        db.execute("CREATE TABLE IF NOT EXISTS daily_employee_delivery (report_date TEXT PRIMARY KEY, delivered_at TEXT NOT NULL)")
        row=db.execute("SELECT report_date FROM daily_employee_delivery WHERE report_date=?",(day,)).fetchone()
        return row is not None


def _mark_sent(day: str):
    with sqlite3.connect(DB_PATH,timeout=30) as db:
        db.execute("CREATE TABLE IF NOT EXISTS daily_employee_delivery (report_date TEXT PRIMARY KEY, delivered_at TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO daily_employee_delivery(report_date,delivered_at) VALUES(?,?)",
          (day,datetime.now(TZ).isoformat()))


def run_once(force: bool=False, dry_run: bool=False):
    _setup_logging()
    day=datetime.now(TZ).date().isoformat()
    if not force and not dry_run and _already_sent(day):
        msg=f"Laporan {day} sudah berhasil dikirim; duplikasi dilewati."
        print(msg,flush=True); logging.info(msg)
        return {"skipped":True,"date":day}
    try:
        # Keep Windows Task Scheduler / Telegram / Ollama history isolated in local SQLite.
        result=run_daily_scan(db_path=DB_PATH)
        report=format_report(result)
    except Exception as exc:
        logging.exception("Daily scan failed")
        report=("⚠️ AI EQUITY RESEARCH — LAPORAN GAGAL\n"
                f"Tanggal: {day} SGT\nKesalahan: {type(exc).__name__}: {str(exc)[:1000]}\n"
                "Tidak ada sinyal yang diterbitkan. Periksa koneksi dan sumber data.")
        result={"counts":{"success":0,"failed":1},"error":str(exc)}
    report=enrich_report(report)
    print(report,flush=True)
    if dry_run:
        return result
    asyncio.run(send_report(report))
    _mark_sent(day)
    logging.info("Daily report delivered for %s",day)
    return result


def main():
    p=argparse.ArgumentParser(description="AI Equity Research daily employee")
    p.add_argument("--force",action="store_true",help="Kirim ulang meski laporan hari ini sudah terkirim")
    p.add_argument("--dry-run",action="store_true",help="Scan dan tampilkan laporan tanpa Telegram")
    p.add_argument("--test-telegram",action="store_true",help="Kirim pesan tes Telegram tanpa scan saham")
    p.add_argument("--test-ollama-telegram",action="store_true",help="Uji Ollama lalu kirim hasilnya ke Telegram")
    args=p.parse_args()
    if args.test_telegram:
        asyncio.run(send_report("✅ Koneksi AI Equity Research berhasil. Laporan harian Telegram siap diuji."))
        print("Pesan tes berhasil dikirim.")
        return
    if args.test_ollama_telegram:
        sample=("Contoh data uji (BUKAN data pasar aktual): IDX BBCA skor 72/100, sinyal WATCH, "
                "harga penutupan contoh 9.000 IDR, RSI 55. Risiko: data contoh dan perlu diverifikasi.")
        report="🧪 TES INTEGRASI OLLAMA + TELEGRAM\n"+enrich_report(sample)
        asyncio.run(send_report(report))
        print("Tes Ollama + Telegram selesai. Periksa Telegram dan bagian ANALISIS AI LOKAL.")
        return
    run_once(force=args.force,dry_run=args.dry_run)

if __name__=="__main__":
    main()
