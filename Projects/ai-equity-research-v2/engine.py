
"""Shared market research engine. Yahoo Finance data; not investment advice."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import math
import re

import numpy as np
import pandas as pd
import yfinance as yf
from market_engine import resolve_market_ticker
from multistage_adapter import calculate_multistage_dcf

def normalize_ticker(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace(" ", "")
    if not s:
        raise ValueError("Masukkan kode saham.")
    if s.endswith(".JK"):
        code = s[:-3]
    elif "." in s:
        raise ValueError("V1 saat ini hanya mendukung ticker BEI dengan akhiran .JK.")
    else:
        code = s
    if not re.fullmatch(r"[A-Z0-9]{3,6}", code):
        raise ValueError("Format ticker BEI tidak valid. Contoh: ANTM atau ANTM.JK.")
    return f"{code}.JK"


def _number(value: Any):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _to_percent(value: Any):
    """Normalize Yahoo fractional ratios to percentage without double scaling."""
    n = _number(value)
    if n is None:
        return None
    return n * 100 if abs(n) <= 1 else n


def is_financial_institution(data: dict) -> bool:
    identity = " ".join(
        str(data.get(k) or "")
        for k in ("sector", "industry", "company", "ticker")
    ).lower()
    terms = (
        "bank", "financial services", "financials", "insurance",
        "insurer", "capital markets", "credit services"
    )
    return any(term in identity for term in terms)


def _ordered_columns(frame: pd.DataFrame):
    if frame is None or frame.empty:
        return []
    columns = list(frame.columns)
    try:
        columns = sorted(
            columns,
            key=lambda c: pd.Timestamp(c),
            reverse=True
        )
    except (TypeError, ValueError):
        pass
    return columns


def _statement_value(frame: pd.DataFrame, candidates: list[str]):
    """Read matching statement rows from the newest period only."""
    if frame is None or frame.empty:
        return None

    columns = _ordered_columns(frame)
    if not columns:
        return None

    latest_column = columns[0]

    for candidate in candidates:
        matches = [
            label for label in frame.index
            if str(label).strip().lower() == candidate.strip().lower()
        ]
        if not matches:
            continue

        row = frame.loc[matches[0]]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        if latest_column in row.index:
            value = _number(row[latest_column])
            if value is not None:
                return value

    return None


def _latest_period(frame: pd.DataFrame):
    columns = _ordered_columns(frame)
    return str(columns[0]) if columns else None


def _safe_info(ticker):
    try:
        return ticker.get_info() or {}
    except Exception:
        try:
            return ticker.info or {}
        except Exception:
            return {}


def _safe_statement(ticker, name):
    try:
        value = getattr(ticker, name)
        return value if isinstance(value, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def analyze_equity(symbol: str, period: str = "5y", market: str = "IDX") -> dict:
    market_info = resolve_market_ticker(symbol, market)
    ticker_symbol = market_info["ticker"]
    ticker = yf.Ticker(ticker_symbol)
    info = _safe_info(ticker)

    hist = ticker.history(period=period, auto_adjust=True)
    if hist is None or hist.empty or "Close" not in hist:
        raise ValueError(
            f"Tidak ada data harga untuk {ticker_symbol}. "
            "Periksa ticker atau coba lagi nanti."
        )

    financials = _safe_statement(ticker, "financials")
    balance = _safe_statement(ticker, "balance_sheet")
    cashflow = _safe_statement(ticker, "cashflow")

    close = hist["Close"].dropna()
    if close.empty:
        raise ValueError(f"Data harga penutupan {ticker_symbol} tidak tersedia.")

    returns = close.pct_change().dropna()
    latest = float(close.iloc[-1])
    previous = float(close.iloc[-2]) if len(close) > 1 else latest

    change_pct = ((latest / previous) - 1) * 100 if previous else None
    sma20 = float(close.tail(20).mean()) if len(close) >= 20 else None
    sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    sma200 = float(close.tail(200).mean()) if len(close) >= 200 else None

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()
    loss = -delta.clip(upper=0).ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()

    rsi_series = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    rsi_series = rsi_series.mask((loss == 0) & (gain > 0), 100)
    rsi_series = rsi_series.mask((loss == 0) & (gain == 0), 50)
    rsi = _number(rsi_series.iloc[-1]) if not rsi_series.empty else None

    volatility = (
        _number(returns.std() * np.sqrt(252) * 100)
        if len(returns) > 1 else None
    )
    total_return = (
        ((latest / float(close.iloc[0])) - 1) * 100
        if len(close) > 1 and close.iloc[0] else None
    )

    # Income statement
    revenue = _statement_value(
        financials, ["Total Revenue", "Operating Revenue"]
    )
    net_income_parent = _statement_value(
        financials,
        [
            "Net Income Common Stockholders",
            "Net Income",
            "Net Income From Continuing Operation Net Minority Interest"
        ]
    )
    net_income_consolidated = _statement_value(
        financials,
        [
            "Net Income Including Noncontrolling Interests",
            "Net Income Continuous Operations"
        ]
    )
    operating_income = _statement_value(
        financials,
        ["Operating Income", "Total Operating Income As Reported"]
    )
    ebit = _statement_value(financials, ["EBIT"])
    ebitda = _statement_value(financials, ["EBITDA"])
    normalized_ebitda = _statement_value(
        financials, ["Normalized EBITDA"]
    )
    tax_provision = _statement_value(
        financials,
        ["Tax Provision", "Income Tax Expense"]
    )
    pretax_income = _statement_value(
        financials,
        ["Pretax Income", "Income Before Tax"]
    )
    tax_rate_for_calcs = _statement_value(
        financials,
        ["Tax Rate For Calcs"]
    )
    # Balance sheet
    total_debt = _statement_value(
        balance,
        ["Total Debt", "Long Term Debt And Capital Lease Obligation"]
    )
    cash = _statement_value(
        balance,
        [
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Short Term Investments"
        ]
    )
    accounts_receivable = _statement_value(
        balance,
        ["Accounts Receivable", "Receivables"]
    )
    inventory = _statement_value(
        balance,
        ["Inventory", "Inventories"]
    )
    accounts_payable = _statement_value(
        balance,
        ["Accounts Payable", "Payables"]
    )
    # Cash flow statement
    operating_cash_flow = _statement_value(
        cashflow,
        [
            "Operating Cash Flow",
            "Cash Flow From Continuing Operating Activities",
            "Cash Flowsfromusedin Operating Activities Direct"
        ]
    )
    capex = _statement_value(
        cashflow, ["Capital Expenditure", "Capital Expenditures"]
    )
    depreciation_amortization = _statement_value(
        financials,
        [
            "Depreciation And Amortization In Income Statement",
            "Reconciled Depreciation",
            "Depreciation Income Statement"
        ]
    )
    free_cash_flow = _statement_value(cashflow, ["Free Cash Flow"])

    if (
        free_cash_flow is None
        and operating_cash_flow is not None
        and capex is not None
    ):
        free_cash_flow = operating_cash_flow - abs(capex)

    # Quote currency and financial-statement currency are not always identical.
    quote_currency = info.get("currency") or "Unknown"
    financial_currency = (
        info.get("financialCurrency") or quote_currency
    )

    raw_pe = _number(info.get("trailingPE"))
    raw_pb = _number(info.get("priceToBook"))

    warnings = []

    if quote_currency == "Unknown":
        warnings.append("Mata uang harga saham tidak tersedia dari metadata.")

    if financial_currency == "Unknown":
        warnings.append("Mata uang laporan keuangan tidak dapat dipastikan.")

    if quote_currency != financial_currency:
        warnings.append(
            "Mata uang harga saham berbeda dari mata uang laporan keuangan. "
            "P/E dan P/B dari metadata Yahoo tidak ditampilkan sebagai rasio "
            "terverifikasi. DCF menggunakan mata uang laporan keuangan."
        )
        raw_pe = None
        raw_pb = None

    if raw_pb is not None and raw_pb > 100:
        warnings.append(
            "Price to book sangat tinggi atau tidak wajar; "
            "nilai P/B disembunyikan sampai diverifikasi."
        )
        raw_pb = None

    dividend_yield = _number(info.get("dividendYield"))
    if dividend_yield is not None and (
        dividend_yield < 0 or dividend_yield > 100
    ):
        warnings.append(
            "Dividend yield di luar rentang kewajaran; "
            "nilai tidak ditampilkan."
        )
        dividend_yield = None

    debt_to_equity = _to_percent(info.get("debtToEquity"))
    roe = _to_percent(info.get("returnOnEquity"))

    if financials.empty:
        warnings.append("Laporan laba rugi tidak tersedia.")
    if balance.empty:
        warnings.append("Neraca tidak tersedia.")
    if cashflow.empty:
        warnings.append("Laporan arus kas tidak tersedia.")

    if operating_cash_flow is None and not cashflow.empty:
        warnings.append(
            "Operating cash flow tidak ditemukan pada periode terbaru."
        )

    if capex is None and not cashflow.empty:
        warnings.append("Capital expenditure tidak ditemukan.")

    if net_income_parent is None and not financials.empty:
        warnings.append("Net income attributable to parent tidak ditemukan.")

    if (
        not financials.empty
        and not balance.empty
        and _latest_period(financials) != _latest_period(balance)
    ):
        warnings.append(
            "Periode laporan laba rugi dan neraca berbeda."
        )

    if (
        not cashflow.empty
        and _latest_period(cashflow) != _latest_period(financials)
    ):
        warnings.append(
            "Periode arus kas dan laba rugi berbeda."
        )

    if ebitda is not None:
        warnings.append(
            "EBITDA berasal dari klasifikasi Yahoo Finance; "
            "verifikasi definisinya terhadap laporan resmi emiten."
        )

    trend = (
        "Bullish (SMA20 > SMA50)"
        if sma20 > sma50 else "Bearish (SMA20 < SMA50)"
    ) if sma20 is not None and sma50 is not None else "Insufficient history"

    rsi_signal = (
        "Unavailable" if rsi is None
        else "Potentially overbought" if rsi >= 70
        else "Potentially oversold" if rsi <= 30
        else "Neutral range"
    )

    history = hist.reset_index()
    date_column = "Date" if "Date" in history.columns else history.columns[0]
    history["Date"] = history[date_column].astype(str)

    ratios = {
        "Revenue": revenue,
        "Net income": net_income_parent,
        "Net income attributable to parent": net_income_parent,
        "Net income including noncontrolling interests": net_income_consolidated,
        "Operating income": operating_income,
        "EBIT": ebit,
        "EBITDA": ebitda,
        "Normalized EBITDA": normalized_ebitda,
        "Tax provision": tax_provision,
        "Pretax income": pretax_income,
        "Tax Rate For Calcs": tax_rate_for_calcs,
        "Depreciation and amortization": depreciation_amortization,
        "Accounts receivable": accounts_receivable,
        "Inventory": inventory,
        "Accounts payable": accounts_payable,
        "Market capitalization": _number(info.get("marketCap")),
	"Shares outstanding": _number(info.get("sharesOutstanding")),
        "Trailing P/E": raw_pe,
        "Price to book": raw_pb,
        "ROE (%)": roe,
        "Debt to equity": debt_to_equity,
        "Dividend yield (%)": dividend_yield,
        "Operating cash flow": operating_cash_flow,
        "Capital expenditure": capex,
        "Free cash flow": free_cash_flow,
        "Total debt": total_debt,
        "Cash and equivalents": cash,
    }

    return {
        "ticker": ticker_symbol,
        "market": market_info["market"],
        "exchange": market_info["exchange"],
        "company": info.get("longName") or info.get("shortName") or ticker_symbol,
        "sector": info.get("sector") or "Not disclosed",
        "industry": info.get("industry") or "Not disclosed",
        "currency": quote_currency,
        "quote_currency": quote_currency,
        "financial_currency": financial_currency,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "latest_price_date": str(history["Date"].iloc[-1]),
        "latest_financial_period": _latest_period(financials),
        "latest_balance_period": _latest_period(balance),
        "latest_cashflow_period": _latest_period(cashflow),
        "price": latest,
        "previous_close": previous,
        "change_pct": change_pct,
        "period_return_pct": total_return,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "rsi14": rsi,
        "annualized_volatility_pct": volatility,
        "trend": trend,
        "rsi_signal": rsi_signal,
        "ratios": ratios,
        "history": history[
            ["Date", "Open", "High", "Low", "Close", "Volume"]
        ],
        "data_source": "Yahoo Finance via yfinance",
        "data_quality_warnings": warnings,
        "data_quality_note": (
            "Harga dan kapitalisasi pasar menggunakan mata uang kuotasi. "
            "Fundamental dan DCF menggunakan mata uang laporan keuangan. "
            "ROE, DER, dan dividend yield dinyatakan dalam persen. "
            "Periksa kembali satuan, periode, dan definisi terhadap laporan resmi."
        ),
        "disclaimer": (
            "Data may be delayed, incomplete, restated, or unavailable. "
            "Not investment advice."
        )
    }



def calculate_dcf(
    data: dict,
    years: int = 5,
    growth: float = 0.05,
    wacc: float = 0.12,
    terminal_growth: float = 0.025,
    fx_rate: float | None = None,
    fx_source_date: str | None = None
) -> dict:
    """Calculate DCF enterprise value, equity value and intrinsic value per share."""

    if not isinstance(data, dict):
        return {"available": False, "reason": "Data saham tidak valid."}

    if is_financial_institution(data):
        return {
            "available": False,
            "reason": (
                "DCF berbasis FCF perusahaan non-keuangan tidak digunakan "
                "untuk bank/asuransi. Gunakan pendekatan valuasi khusus sektor."
            )
        }

    ratios = data.get("ratios", {})
    fcf = _number(ratios.get("Free cash flow"))
    debt = _number(ratios.get("Total debt"))
    cash = _number(ratios.get("Cash and equivalents"))
    shares = _number(ratios.get("Shares outstanding"))

    if fcf is None or fcf <= 0:
        return {
            "available": False,
            "reason": "DCF memerlukan free cash flow positif."
        }

    if debt is None or cash is None:
        return {
            "available": False,
            "reason": "Total debt atau cash tidak tersedia. Equity Value tidak dapat dihitung."
        }

    if shares is None or shares <= 0:
        return {
            "available": False,
            "reason": "Shares outstanding tidak tersedia atau tidak valid."
        }

    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 20:
        return {"available": False, "reason": "Periode proyeksi harus bilangan bulat 1 sampai 20 tahun."}

    growth = _number(growth)
    wacc = _number(wacc)
    terminal_growth = _number(terminal_growth)

    if any(x is None for x in (growth, wacc, terminal_growth)):
        return {"available": False, "reason": "Asumsi DCF harus berupa angka valid."}

    if growth <= -1 or growth > 1:
        return {"available": False, "reason": "FCF growth harus lebih besar dari -100% dan tidak boleh melebihi 100%."}

    if not 0 < wacc <= 1:
        return {"available": False, "reason": "WACC harus lebih besar dari 0% dan maksimal 100%."}

    if not -1 < terminal_growth < 1:
        return {"available": False, "reason": "Terminal growth harus di antara -100% dan 100%."}

    if wacc <= terminal_growth:
        return {
            "available": False,
            "reason": "WACC harus lebih tinggi daripada terminal growth."
        }

    forecast = []
    pv_sum = 0.0

    for year in range(1, years + 1):
        cash_flow = fcf * ((1 + growth) ** year)
        pv = cash_flow / ((1 + wacc) ** year)
        pv_sum += pv

        forecast.append({
            "Year": year,
            "FCF": cash_flow,
            "Present value": pv
        })

    terminal_value = (
        forecast[-1]["FCF"] * (1 + terminal_growth)
        / (wacc - terminal_growth)
    )
    terminal_pv = terminal_value / ((1 + wacc) ** years)

    enterprise_value = pv_sum + terminal_pv
    net_debt = debt - cash
    equity_value = enterprise_value - net_debt
    if not all(math.isfinite(value) for value in (
        pv_sum, terminal_value, terminal_pv, enterprise_value, net_debt, equity_value
    )):
        return {"available": False, "reason": "Hasil DCF mengandung nilai non-finite."}
    if equity_value <= 0:
        return {
            "available": False,
            "reason": "Equity value tidak positif setelah dikurangi net debt; intrinsic value per saham tidak layak ditampilkan.",
            "enterprise_value": enterprise_value,
            "net_debt": net_debt,
            "equity_value": equity_value,
        }
    intrinsic_value = equity_value / shares
    terminal_value_share_pct = terminal_pv / enterprise_value * 100 if enterprise_value > 0 else None
    model_warnings = [
        "Yahoo Finance Free Cash Flow is an OCF-minus-CAPEX proxy and may reflect financing/interest cash flows; confirm FCFF versus FCFE before interpreting EV less net debt."
    ]
    if terminal_value_share_pct is not None and terminal_value_share_pct > 75:
        model_warnings.append("PV terminal value exceeds 75% of enterprise value; valuation is highly sensitive to terminal assumptions.")

    financial_currency = (
        data.get("financial_currency") or data.get("currency", "Unknown")
    )
    quote_currency = data.get("currency", "Unknown")

    display_currency = financial_currency
    conversion_applied = False

    if financial_currency != quote_currency:
        if fx_rate is not None:
            fx_rate = _number(fx_rate)

            if fx_rate is None or fx_rate <= 0:
                return {
                    "available": False,
                    "reason": "Kurs konversi harus berupa angka positif."
                }

            intrinsic_value *= fx_rate
            display_currency = quote_currency
            conversion_applied = True
    if not math.isfinite(intrinsic_value):
        return {"available": False, "reason": "Intrinsic value per share melampaui rentang numerik yang didukung."}

    return {
        "available": True,
        "base_fcf": fcf,
        "forecast": pd.DataFrame(forecast),
        "pv_forecast": pv_sum,
        "terminal_value": terminal_value,
        "pv_terminal_value": terminal_pv,
        "enterprise_value": enterprise_value,
        "terminal_value_share_pct": terminal_value_share_pct,
        "model_warnings": model_warnings,
        "total_debt": debt,
        "cash": cash,
        "net_debt": net_debt,
        "equity_value": equity_value,
        "shares_outstanding": shares,
        "intrinsic_value_per_share": intrinsic_value,
        "currency": financial_currency,
        "display_currency": display_currency,
        "quote_currency": quote_currency,
        "fx_rate": fx_rate if conversion_applied else None,
        "fx_source_date": fx_source_date if conversion_applied else None,
        "fx_conversion_applied": conversion_applied,
        "assumptions": {
            "years": years,
            "growth": growth,
            "wacc": wacc,
            "terminal_growth": terminal_growth
        },
        "warning": (
            "DCF ini merupakan estimasi sederhana. Equity Value dihitung "
            "dari EV dikurangi total debt dan ditambah cash. Nilai per saham "
            "bergantung pada kualitas FCF, neraca, jumlah saham, asumsi, "
            "dan kurs konversi jika digunakan. FCF Yahoo adalah proxy OCF dikurangi CAPEX; "
            "klasifikasi FCFF/FCFE wajib diverifikasi sebelum EV dikurangi net debt. "
            "Bukan rekomendasi investasi."
        )
    }


def dcf_sensitivity(
    data: dict,
    growth_rates=None,
    wacc_rates=None,
    years: int = 5,
    terminal_growth: float = 0.025,
    fx_rate: float | None = None
) -> dict:
    """Return sensitivity matrices for enterprise value and intrinsic value per share."""

    ratios = data.get("ratios", {})
    base = _number(ratios.get("Free cash flow"))
    debt = _number(ratios.get("Total debt"))
    cash = _number(ratios.get("Cash and equivalents"))
    shares = _number(ratios.get("Shares outstanding"))

    if is_financial_institution(data):
        return {"available": False, "reason": "Sensitivity DCF tidak digunakan untuk bank/asuransi."}

    if base is None or base <= 0:
        return {"available": False, "reason": "Sensitivity DCF memerlukan FCF positif."}

    if debt is None or cash is None or shares is None or shares <= 0:
        return {
            "available": False,
            "reason": "Debt, cash, atau shares outstanding tidak tersedia."
        }

    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 20:
        return {"available": False, "reason": "Periode proyeksi harus 1 sampai 20 tahun."}

    growth_rates = list(growth_rates if growth_rates is not None else [0.00, 0.05, 0.10])
    wacc_rates = list(wacc_rates if wacc_rates is not None else [0.10, 0.12, 0.14])

    if not growth_rates or not wacc_rates:
        return {"available": False, "reason": "Skenario growth dan WACC tidak boleh kosong."}

    terminal_growth = _number(terminal_growth)
    if terminal_growth is None or not -1 < terminal_growth < 1:
        return {"available": False, "reason": "Terminal growth harus di antara -100% dan 100%."}

    financial_currency = data.get("financial_currency") or data.get("currency", "Unknown")
    quote_currency = data.get("currency", "Unknown")
    display_currency = financial_currency
    conversion_applied = False

    if financial_currency != quote_currency and fx_rate is not None:
        fx_rate = _number(fx_rate)
        if fx_rate is None or fx_rate <= 0:
            return {"available": False, "reason": "Kurs konversi harus positif."}
        display_currency = quote_currency
        conversion_applied = True

    share_rows = []
    ev_rows = []

    for growth_rate in growth_rates:
        g = _number(growth_rate)

        if g is None or not -1 < g <= 1:
            return {"available": False, "reason": "Growth scenario harus lebih besar dari -100% dan maksimal 100%."}

        share_row = {"FCF growth": g}
        ev_row = {"FCF growth": g}

        for discount_rate in wacc_rates:
            w = _number(discount_rate)

            if w is None or not terminal_growth < w <= 1:
                return {
                    "available": False,
                    "reason": "Setiap WACC harus lebih tinggi daripada terminal growth."
                }

            pv = sum(
                base * ((1 + g) ** year) / ((1 + w) ** year)
                for year in range(1, years + 1)
            )

            terminal_fcf = base * ((1 + g) ** years)
            terminal_value = (
                terminal_fcf * (1 + terminal_growth)
                / (w - terminal_growth)
            )
            pv_terminal = terminal_value / ((1 + w) ** years)

            ev = pv + pv_terminal
            equity = ev - debt + cash
            per_share = equity / shares

            if conversion_applied:
                per_share *= fx_rate
            if not all(math.isfinite(value) for value in (
                pv, terminal_fcf, terminal_value, pv_terminal, ev, equity, per_share
            )):
                return {
                    "available": False,
                    "reason": "Sensitivity menghasilkan numerical overflow; periksa growth, WACC, dan kurs.",
                }

            column = f"WACC {w:.1%}"
            ev_row[column] = ev
            share_row[column] = per_share

        ev_rows.append(ev_row)
        share_rows.append(share_row)

    return {
        "available": True,
        "matrix": pd.DataFrame(share_rows),
        "enterprise_value_matrix": pd.DataFrame(ev_rows),
        "currency": display_currency,
        "financial_currency": financial_currency,
        "warning": (
            f"Nilai dalam {display_currency} per saham. "
            "Setiap sel menggunakan asumsi growth dan WACC pada baris/kolom."
        )
    }


def build_research_summary(data: dict) -> list[str]:
    return [
        f"Perubahan harga harian: {data['change_pct']:.2f}%."
        if data.get("change_pct") is not None
        else "Perubahan harga harian tidak tersedia.",

        f"Return periode data: {data['period_return_pct']:.2f}%."
        if data.get("period_return_pct") is not None
        else "Return periode tidak tersedia.",

        f"Tren moving average: {data['trend']}.",

        f"RSI 14: {data['rsi14']:.1f} ({data['rsi_signal']})."
        if data.get("rsi14") is not None
        else "RSI tidak tersedia.",

        f"Volatilitas tahunan historis: {data['annualized_volatility_pct']:.2f}%."
        if data.get("annualized_volatility_pct") is not None
        else "Volatilitas tidak tersedia."
    ]
