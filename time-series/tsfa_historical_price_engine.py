
"""
TSFA Historical Price Engine - V1.4

Mengambil dan memvalidasi harga historis saham untuk portfolio backtesting.

Initial scope:
- Indonesia / IDR.
- Yahoo Finance sebagai sumber data.
- Daily Close prices.
- Harga Close, bukan Adj Close.
- Tidak menyimpan data ke DataHub atau file eksternal.
- Output berupa DataFrame yang dapat diproses engine berikutnya.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd


PRICE_COLUMNS = [
    "Date",
    "Market",
    "Ticker",
    "Close",
    "Currency",
]


def _to_timestamp(value: Any, field_name: str) -> pd.Timestamp:
    """Convert input to a normalized, timezone-naive timestamp."""
    result = pd.to_datetime(value, errors="coerce")

    if pd.isna(result):
        raise ValueError(f"{field_name} bukan tanggal yang valid: {value}")

    result = pd.Timestamp(result)

    if result.tzinfo is not None:
        result = result.tz_localize(None)

    return result.normalize()


def normalize_ticker(ticker: Any, market: str = "Indonesia") -> str:
    """Normalize ticker symbols for Yahoo Finance."""
    value = str(ticker).strip().upper()

    if not value:
        raise ValueError("Ticker tidak boleh kosong.")

    if market == "Indonesia":
        if value.endswith(".JK"):
            value = value[:-3]

        return value

    if market == "USA":
        return value

    raise ValueError(
        f"Market tidak didukung: {market}. "
        "Pilihan yang tersedia: Indonesia atau USA."
    )


def yahoo_ticker_symbol(
    ticker: Any,
    market: str = "Indonesia",
) -> str:
    """Convert portfolio ticker to Yahoo Finance ticker."""
    normalized = normalize_ticker(ticker, market)

    if market == "Indonesia":
        # Yahoo Finance index symbols (e.g. ^JKSE) are already
        # complete symbols and must not receive the .JK suffix.
        if normalized.startswith("^"):
            return normalized
        return f"{normalized}.JK"

    return normalized


def collect_required_tickers(
    portfolio: pd.DataFrame,
    transactions: pd.DataFrame | None = None,
    market: str = "Indonesia",
) -> list[str]:
    """
    Collect unique tickers from opening holdings and all transactions.

    This includes tickers that were subsequently sold completely.
    """
    tickers: set[str] = set()

    if portfolio is not None and not portfolio.empty:
        required = {"Record_Type", "Ticker"}
        missing = required.difference(portfolio.columns)

        if missing:
            raise ValueError(
                "Kolom PORTFOLIO tidak lengkap: "
                + ", ".join(sorted(missing))
            )

        for _, row in portfolio.iterrows():
            record_type = str(row.get("Record_Type", "")).strip().upper()

            if record_type != "HOLDING":
                continue

            raw_ticker = row.get("Ticker")

            if pd.isna(raw_ticker):
                continue

            tickers.add(normalize_ticker(raw_ticker, market))

    if transactions is not None and not transactions.empty:
        if "Ticker" not in transactions.columns:
            raise ValueError(
                "Kolom Ticker tidak ditemukan pada TRANSACTIONS."
            )

        for raw_ticker in transactions["Ticker"]:
            if pd.isna(raw_ticker):
                continue

            value = str(raw_ticker).strip()

            if not value:
                continue

            tickers.add(normalize_ticker(value, market))

    if not tickers:
        raise ValueError(
            "Tidak ditemukan ticker dari PORTFOLIO atau TRANSACTIONS."
        )

    return sorted(tickers)


def normalize_price_data(
    raw_data: pd.DataFrame,
    ticker: str,
    market: str = "Indonesia",
    currency: str = "IDR",
) -> pd.DataFrame:
    """
    Normalize Yahoo Finance output into standard price-history format.
    """
    if raw_data is None or raw_data.empty:
        raise ValueError(f"Data harga {ticker} kosong.")

    data = raw_data.copy()

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    if "Close" not in data.columns:
        raise ValueError(
            f"Kolom Close tidak ditemukan untuk ticker {ticker}."
        )

    close = data["Close"]

    if isinstance(close, pd.DataFrame):
        if close.shape[1] != 1:
            raise ValueError(
                f"Kolom Close untuk {ticker} memiliki lebih dari satu seri."
            )
        close = close.iloc[:, 0]

    close = pd.to_numeric(close, errors="coerce")

    result = pd.DataFrame({
        "Date": pd.to_datetime(close.index),
        "Close": close.to_numpy(),
    })

    result["Date"] = pd.to_datetime(result["Date"])

    if result["Date"].dt.tz is not None:
        result["Date"] = result["Date"].dt.tz_localize(None)

    result["Date"] = result["Date"].dt.normalize()
    result["Ticker"] = normalize_ticker(ticker, market)
    result["Market"] = market
    result["Currency"] = currency

    result = result[PRICE_COLUMNS]

    result = result.dropna(subset=["Date", "Close"])
    result = result[np.isfinite(result["Close"])]
    result = result[result["Close"] > 0]

    result = (
        result.sort_values("Date")
        .drop_duplicates(subset=["Date", "Ticker"], keep="last")
        .reset_index(drop=True)
    )

    if result.empty:
        raise ValueError(
            f"Tidak ada harga Close valid untuk ticker {ticker}."
        )

    return result


def validate_historical_prices(
    price_history: pd.DataFrame,
    expected_tickers: Iterable[str] | None = None,
    start_date: Any | None = None,
    end_date: Any | None = None,
) -> dict[str, Any]:
    """
    Validate historical price data and return a quality report.

    Coverage is evaluated separately for each ticker.
    Requested start/end dates are coverage boundaries, not
    requirements for an exact trading-day price on those dates.
    """
    required = set(PRICE_COLUMNS)

    if price_history is None or price_history.empty:
        raise ValueError("Historical price data kosong.")

    missing = required.difference(price_history.columns)

    if missing:
        raise ValueError(
            "Kolom harga historis tidak lengkap: "
            + ", ".join(sorted(missing))
        )

    data = price_history.copy()

    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")

    # Normalize timezone-aware dates to timezone-naive dates.
    if isinstance(data["Date"].dtype, pd.DatetimeTZDtype):
        data["Date"] = data["Date"].dt.tz_localize(None)

    data["Date"] = data["Date"].dt.normalize()
    data["Close"] = pd.to_numeric(data["Close"], errors="coerce")

    invalid_dates = int(data["Date"].isna().sum())

    invalid_prices = int(
        (
            data["Close"].isna()
            | ~np.isfinite(data["Close"].fillna(0))
            | (data["Close"] <= 0)
        ).sum()
    )

    duplicate_count = int(
        data.duplicated(subset=["Date", "Ticker"]).sum()
    )

    data["Ticker"] = data["Ticker"].astype("string").str.strip().str.upper()

    actual_tickers = sorted(
        data["Ticker"].dropna().astype(str).unique().tolist()
    )

    missing_tickers: list[str] = []

    if expected_tickers is not None:
        expected = {
            normalize_ticker(ticker)
            for ticker in expected_tickers
        }
        missing_tickers = sorted(expected.difference(actual_tickers))

    first_date = (
        data["Date"].min().date()
        if data["Date"].notna().any()
        else None
    )

    last_date = (
        data["Date"].max().date()
        if data["Date"].notna().any()
        else None
    )

    start = (
        _to_timestamp(start_date, "start_date").date()
        if start_date is not None else None
    )

    end = (
        _to_timestamp(end_date, "end_date").date()
        if end_date is not None else None
    )

    ticker_coverage: dict[str, dict[str, Any]] = {}
    coverage_warnings: list[str] = []

    for ticker in actual_tickers:
        ticker_data = data[
            (data["Ticker"] == ticker)
            & data["Date"].notna()
        ]

        dates = ticker_data["Date"]

        ticker_first = dates.min().date() if not dates.empty else None
        ticker_last = dates.max().date() if not dates.empty else None

        ticker_coverage[ticker] = {
            "rows": int(len(ticker_data)),
            "first_date": ticker_first,
            "last_date": ticker_last,
        }

        if start is not None and ticker_first is not None:
            if ticker_first > start:
                coverage_warnings.append(
                    f"{ticker}: histori dimulai {ticker_first}, "
                    f"setelah tanggal awal yang diminta {start}."
                )

        if end is not None and ticker_last is not None:
            if ticker_last < end:
                coverage_warnings.append(
                    f"{ticker}: histori berakhir {ticker_last}, "
                    f"sebelum tanggal akhir yang diminta {end}."
                )

    has_warnings = (
        invalid_dates > 0
        or invalid_prices > 0
        or duplicate_count > 0
        or bool(missing_tickers)
        or bool(coverage_warnings)
    )

    return {
        "status": "WARNING" if has_warnings else "PASS",
        "rows": len(data),
        "ticker_count": len(actual_tickers),
        "tickers": actual_tickers,
        "missing_tickers": missing_tickers,
        "first_date": first_date,
        "last_date": last_date,
        "requested_start_date": start,
        "requested_end_date": end,
        "ticker_coverage": ticker_coverage,
        "coverage_warnings": coverage_warnings,
        "invalid_dates": invalid_dates,
        "invalid_prices": invalid_prices,
        "duplicate_rows": duplicate_count,
    }


def download_historical_prices(
    tickers: Iterable[str],
    start_date: Any,
    end_date: Any,
    market: str = "Indonesia",
    currency: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Download daily Close prices from Yahoo Finance.

    end_date is inclusive for the user. Yahoo Finance uses an
    exclusive end date, so one calendar day is added internally.

    Returns:
        price_history: standardized DataFrame
        report: download and validation summary
    """
    import yfinance as yf

    start = _to_timestamp(start_date, "start_date")
    end = _to_timestamp(end_date, "end_date")

    if start > end:
        raise ValueError("start_date tidak boleh setelah end_date.")

    if end > pd.Timestamp.today().normalize():
        raise ValueError("end_date tidak boleh berada di masa depan.")

    if market not in {"Indonesia", "USA"}:
        raise ValueError("Market harus Indonesia atau USA.")

    if currency is None:
        currency = "IDR" if market == "Indonesia" else "USD"

    normalized_tickers = sorted({
        normalize_ticker(ticker, market)
        for ticker in tickers
    })

    if not normalized_tickers:
        raise ValueError("Daftar ticker kosong.")

    frames: list[pd.DataFrame] = []
    errors: dict[str, str] = {}

    yahoo_end = end + pd.Timedelta(days=1)

    for ticker in normalized_tickers:
        symbol = yahoo_ticker_symbol(ticker, market)

        try:
            raw = yf.download(
                symbol,
                start=start.strftime("%Y-%m-%d"),
                end=yahoo_end.strftime("%Y-%m-%d"),
                interval="1d",
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=False,
            )

            normalized = normalize_price_data(
                raw_data=raw,
                ticker=ticker,
                market=market,
                currency=currency,
            )

            normalized = normalized[
                (normalized["Date"] >= start)
                & (normalized["Date"] <= end)
            ].copy()

            if normalized.empty:
                raise ValueError(
                    "Tidak ada data harga dalam periode yang diminta."
                )

            frames.append(normalized)

        except Exception as exc:
            errors[ticker] = f"{type(exc).__name__}: {exc}"

    if frames:
        price_history = pd.concat(frames, ignore_index=True)
        price_history = (
            price_history.sort_values(["Date", "Ticker"])
            .reset_index(drop=True)
        )
    else:
        price_history = pd.DataFrame(columns=PRICE_COLUMNS)

    quality_report = (
        validate_historical_prices(
            price_history=price_history,
            expected_tickers=normalized_tickers,
            start_date=start,
            end_date=end,
        )
        if not price_history.empty
        else {
            "status": "FAILED",
            "rows": 0,
            "ticker_count": 0,
            "tickers": [],
            "missing_tickers": normalized_tickers,
            "ticker_coverage": {},
            "coverage_warnings": [],
        }
    )

    report = {
        "status": (
            "PASS"
            if quality_report["status"] == "PASS" and not errors
            else "WARNING"
        ),
        "market": market,
        "currency": currency,
        "requested_tickers": normalized_tickers,
        "downloaded_tickers": sorted(
            price_history["Ticker"].unique().tolist()
        ) if not price_history.empty else [],
        "failed_tickers": errors,
        "quality": quality_report,
    }

    return price_history, report
