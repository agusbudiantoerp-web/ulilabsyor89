
import sys
import tempfile

import pandas as pd
import yfinance as yf

# Mengakses storage engine di folder time-series
sys.path.insert(0, "time-series")

from tsfa_storage_engine import TSFAStorageEngine


def main():
    temp = tempfile.TemporaryDirectory()
    engine = TSFAStorageEngine(base_dir=temp.name)

    tickers = [
        ("AAPL", "USA"),
        ("^JKSE", "Indonesia"),
    ]

    try:
        for ticker, market in tickers:
            print("\n" + "=" * 50)
            print("TICKER:", ticker)
            print("=" * 50)

            data = yf.download(
                ticker,
                period="max",
                auto_adjust=False,
                progress=False
            )

            if data is None or data.empty:
                print("DOWNLOAD: GAGAL - Data kosong")
                continue

            print("DOWNLOAD ROWS:", len(data))

            # Merapikan MultiIndex dari Yahoo Finance
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            required = [
                "Open",
                "High",
                "Low",
                "Close",
                "Adj Close",
                "Volume"
            ]

            missing = [
                col for col in required
                if col not in data.columns
            ]

            if missing:
                print("KOLOM HILANG:", missing)
                continue

            data = data[required].copy()
            data.index = pd.to_datetime(data.index)

            # Menyimpan melalui storage engine
            result = engine.save_dataset(
                ticker,
                market,
                data,
                provider="Yahoo Finance"
            )

            print("SAVE STATUS:", result.get("status"))
            print("VALIDATION:", result.get("validation"))
            print("ERROR:", result.get("errors", []))

            # Memeriksa hasil Clean CSV
            if result.get("status") not in ("PASS", "UNCHANGED"):
                print("PENYIMPANAN GAGAL")
                continue

            clean = pd.read_csv(
                result["clean_path"],
                index_col=0,
                parse_dates=True
            )

            print("CLEAN ROWS:", len(clean))
            print(
                "ADJ CLOSE NULL:",
                clean["Adj Close"].isna().sum()
            )
            print(
                "CLOSE NULL:",
                clean["Close"].isna().sum()
            )
            print("LAST DATE:", clean.index[-1])

    finally:
        temp.cleanup()


if __name__ == "__main__":
    main()
