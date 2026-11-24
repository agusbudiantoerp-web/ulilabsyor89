"""Market regime, relative-strength and source-quality diagnostics."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


BENCHMARKS = {"IDX": "^JKSE", "US": "SPY"}


def _clean_close(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        raise ValueError("Data harga kosong.")
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        close_cols = [i for i, col in enumerate(data.columns) if "Close" in {str(x).title() for x in (col if isinstance(col, tuple) else (col,))}]
        if not close_cols:
            raise ValueError("Kolom Close tidak ditemukan.")
        close = data.iloc[:, close_cols[0]]
    else:
        matches = [c for c in data.columns if str(c).strip().lower() == "close"]
        if not matches:
            raise ValueError("Kolom Close tidak ditemukan.")
        close = data[matches[0]]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    close.index = pd.to_datetime(close.index)
    if getattr(close.index, "tz", None) is not None:
        close.index = close.index.tz_localize(None)
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close = close[close > 0]
    if len(close) < 60:
        raise ValueError("Minimal 60 sesi data penutupan diperlukan.")
    return close.astype(float).rename("Close")


def classify_market_regime(index_bars: pd.DataFrame) -> dict[str, Any]:
    """Classify broad trend using only completed daily closes."""
    close = _clean_close(index_bars)
    if len(close) < 200:
        raise ValueError("Klasifikasi EMA200 memerlukan minimal 200 sesi penutupan.")
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    last = float(close.iloc[-1])
    e50, e200 = float(ema50.iloc[-1]), float(ema200.iloc[-1])
    ret20 = float(close.pct_change(20).iloc[-1] * 100)
    ret60 = float(close.pct_change(60).iloc[-1] * 100) if len(close) > 60 else None
    if last > e50 > e200 and ret20 > 0:
        regime, risk = "BULLISH", "Normal; tetap gunakan stop-loss dan position sizing."
    elif last < e50 < e200 and ret20 < 0:
        regime, risk = "BEARISH", "Defensif; kurangi risiko dan hindari mengejar rebound."
    elif last > e200 and ret20 >= 0:
        regime, risk = "RECOVERY / TRANSITION", "Tren membaik tetapi konfirmasi menengah belum lengkap."
    elif last < e200 and ret20 < 0:
        regime, risk = "WEAK / TRANSITION", "Tekanan masih dominan; tunggu konfirmasi tren."
    else:
        regime, risk = "SIDEWAYS / MIXED", "Arah belum konsisten; seleksi saham dan batas risiko penting."
    return {
        "regime": regime, "benchmark_close": last, "ema50": e50, "ema200": e200,
        "return_20d_pct": ret20, "return_60d_pct": ret60,
        "bar_date": close.index[-1].date().isoformat(),
        "method": "Rule-based regime from completed close, EMA50/EMA200 and 20-session return; not a forecast.",
        "risk_note": risk,
    }


def relative_strength(asset_bars: pd.DataFrame, benchmark_bars: pd.DataFrame) -> dict[str, Any]:
    """Compare asset and benchmark returns over matched dates; positive spread means outperformance."""
    asset = _clean_close(asset_bars).rename("asset")
    benchmark = _clean_close(benchmark_bars).rename("benchmark")
    joined = pd.concat([asset, benchmark], axis=1, join="inner").dropna()
    if len(joined) < 22:
        raise ValueError("Tanggal bersama minimal 22 sesi diperlukan untuk relative strength.")
    rows = {}
    for label, n in (("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252)):
        if len(joined) > n:
            ar = (joined["asset"].iloc[-1] / joined["asset"].iloc[-n-1] - 1) * 100
            br = (joined["benchmark"].iloc[-1] / joined["benchmark"].iloc[-n-1] - 1) * 100
            rows[label] = {
                "asset_return_pct": float(ar), "benchmark_return_pct": float(br),
                "relative_strength_pct": float(ar - br),
            }
    return {
        "periods": rows, "matched_sessions": int(len(joined)),
        "start_date": joined.index[0].date().isoformat(),
        "end_date": joined.index[-1].date().isoformat(),
        "note": "Return price-only pada tanggal perdagangan yang cocok; bukan total return dan tidak memasukkan dividen.",
    }


def audit_price_history(bars: pd.DataFrame, max_age_calendar_days: int = 5) -> dict[str, Any]:
    """Return actionable data-quality flags without silently repairing source values."""
    if bars is None or bars.empty:
        return {"status": "FAIL", "checks": [{"severity": "ERROR", "message": "Data harga kosong."}]}
    frame = bars.copy()
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in frame.columns]
    checks = []
    if missing:
        checks.append({"severity": "ERROR", "message": f"Kolom wajib hilang: {', '.join(missing)}."})
        return {"status": "FAIL", "checks": checks, "rows": int(len(frame))}
    numeric = frame[required].apply(pd.to_numeric, errors="coerce")
    invalid = int(numeric[["Open", "High", "Low", "Close"]].isna().any(axis=1).sum())
    if invalid:
        checks.append({"severity": "WARNING", "message": f"{invalid} bar memiliki OHLC kosong/non-numerik."})
    bad_ohlc = int(((numeric["High"] < numeric[["Open", "Close", "Low"]].max(axis=1)) |
                    (numeric["Low"] > numeric[["Open", "Close", "High"]].min(axis=1))).fillna(False).sum())
    if bad_ohlc:
        checks.append({"severity": "ERROR", "message": f"{bad_ohlc} bar memiliki relasi OHLC tidak valid."})
    nonpositive = int((numeric[["Open", "High", "Low", "Close"]] <= 0).any(axis=1).sum())
    if nonpositive:
        checks.append({"severity": "ERROR", "message": f"{nonpositive} bar memiliki harga nol/negatif."})
    negative_volume = int((numeric["Volume"] < 0).sum())
    if negative_volume:
        checks.append({"severity": "ERROR", "message": f"{negative_volume} bar memiliki volume negatif."})
    duplicate_dates = int(frame.index.duplicated().sum())
    if duplicate_dates:
        checks.append({"severity": "WARNING", "message": f"{duplicate_dates} tanggal duplikat."})
    dates = pd.to_datetime(frame.index)
    age = max(0, (pd.Timestamp.now().date() - dates.max().date()).days)
    if age > max_age_calendar_days:
        checks.append({"severity": "WARNING", "message": f"Bar terakhir berumur {age} hari kalender."})
    if len(frame) < 200:
        checks.append({"severity": "WARNING", "message": f"Histori hanya {len(frame)} bar; indikator jangka panjang/backtest dapat terbatas."})
    if not checks:
        checks.append({"severity": "INFO", "message": "Pemeriksaan dasar OHLCV lolos; tetap verifikasi sumber dan corporate actions."})
    status = "FAIL" if any(x["severity"] == "ERROR" for x in checks) else ("WARNING" if any(x["severity"] == "WARNING" for x in checks) else "PASS")
    return {"status": status, "rows": int(len(frame)), "last_bar": dates.max().date().isoformat(),
            "age_calendar_days": age, "checks": checks}


def _finite_negative(value: Any) -> bool:
    try:
        number = float(value)
        return math.isfinite(number) and number < 0
    except (TypeError, ValueError):
        return False


def audit_fundamental_record(record: dict[str, Any]) -> dict[str, Any]:
    """Flag missing and implausible fundamentals while retaining original source values."""
    numeric_fields = ("trailingPE", "forwardPE", "priceToBook", "returnOnEquity",
                      "returnOnAssets", "debtToEquity", "revenueGrowth", "earningsGrowth", "marketCap")
    missing = [key for key in numeric_fields if record.get(key) is None]
    invalid = []
    for key in numeric_fields:
        value = record.get(key)
        if value is None:
            continue
        try:
            number = float(value)
            if not math.isfinite(number) or (key == "marketCap" and number < 0):
                invalid.append(key)
        except (TypeError, ValueError):
            invalid.append(key)
    flags = []
    if missing:
        flags.append({"severity": "WARNING", "message": "Fundamental tidak tersedia: " + ", ".join(missing)})
    if invalid:
        flags.append({"severity": "ERROR", "message": "Nilai fundamental tidak valid: " + ", ".join(invalid)})
    negative_multiples = [key for key in ("trailingPE", "forwardPE", "priceToBook")
                          if record.get(key) is not None and _finite_negative(record.get(key))]
    if negative_multiples:
        flags.append({"severity": "WARNING", "message": "Multiple negatif perlu interpretasi khusus (misalnya perusahaan rugi atau ekuitas negatif): " + ", ".join(negative_multiples)})
    if record.get("currency") is None:
        flags.append({"severity": "WARNING", "message": "Mata uang pelaporan/kuotasi tidak diketahui."})
    if record.get("financialCurrency") and record.get("currency") and record["financialCurrency"] != record["currency"]:
        flags.append({"severity": "WARNING", "message": "Mata uang laporan keuangan berbeda dari mata uang kuotasi; jangan bandingkan nominal tanpa konversi."})
    return {"status": "FAIL" if invalid else ("WARNING" if flags else "PASS"),
            "missing_fields": missing, "invalid_fields": invalid, "checks": flags}
