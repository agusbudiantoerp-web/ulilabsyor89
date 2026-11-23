"""Supporting analytics for TSFA Dual Market V1.4 dashboard."""
from __future__ import annotations

import pandas as pd


def build_ending_positions(portfolio: pd.DataFrame,
                           transactions: pd.DataFrame,
                           price_history: pd.DataFrame) -> pd.DataFrame:
    """Derive end-of-period stock weights from opening holdings and trades."""
    positions: dict[str, int] = {}
    for _, row in portfolio.iterrows():
        if str(row.get("Record_Type", "")).strip().upper() == "HOLDING":
            ticker = str(row["Ticker"]).strip().upper()
            positions[ticker] = int(float(row["Opening_Quantity_Shares"]))

    if transactions is not None and not transactions.empty:
        tx = transactions.copy()
        tx["_order"] = range(len(tx))
        tx = tx.sort_values(["Date", "_order"])
        for _, row in tx.iterrows():
            ticker = str(row["Ticker"]).strip().upper()
            qty = int(float(row["Quantity_Shares"]))
            side = str(row["Side"]).strip().upper()
            if side == "BUY":
                positions[ticker] = positions.get(ticker, 0) + qty
            elif side == "SELL":
                positions[ticker] = positions.get(ticker, 0) - qty

    prices = price_history.copy()
    prices["Date"] = pd.to_datetime(prices["Date"], errors="coerce")
    prices["Ticker"] = prices["Ticker"].astype(str).str.strip().str.upper()
    prices["Close"] = pd.to_numeric(prices["Close"], errors="coerce")
    prices = prices.dropna(subset=["Date", "Close"])
    prices = prices.sort_values("Date").drop_duplicates("Ticker", keep="last")
    latest = prices.set_index("Ticker")["Close"].to_dict()

    rows = []
    for ticker, quantity in sorted(positions.items()):
        if quantity <= 0:
            continue
        if ticker not in latest:
            continue
        rows.append({
            "Ticker": ticker,
            "Quantity_Shares": quantity,
            "Latest_Price": float(latest[ticker]),
            "Market_Value": quantity * float(latest[ticker]),
        })
    return pd.DataFrame(rows, columns=[
        "Ticker", "Quantity_Shares", "Latest_Price", "Market_Value"
    ])


def extract_benchmark_series(price_history: pd.DataFrame,
                             benchmark_ticker: str) -> pd.Series:
    """Return a clean date-indexed close-price series for a benchmark."""
    data = price_history.loc[
        price_history["Ticker"].astype(str).str.upper() == benchmark_ticker.upper(),
        ["Date", "Close"],
    ].copy()
    if data.empty:
        raise ValueError(f"Data benchmark {benchmark_ticker} tidak tersedia.")
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data["Close"] = pd.to_numeric(data["Close"], errors="coerce")
    data = data.dropna().sort_values("Date").drop_duplicates("Date", keep="last")
    result = data.set_index("Date")["Close"].astype(float)
    result.index = pd.DatetimeIndex(result.index)
    result.name = benchmark_ticker
    return result


def calculate_rebalance_plan(positions: pd.DataFrame, total_nav: float,
                             target_weights: pd.DataFrame) -> pd.DataFrame:
    """Create a cash-neutral target allocation plan; quantities are estimates."""
    required = {"Ticker", "Market_Value", "Latest_Price"}
    if not required.issubset(positions.columns):
        raise ValueError(f"Positions harus memiliki kolom {sorted(required)}")
    if not {"Ticker", "Target_Weight_Pct"}.issubset(target_weights.columns):
        raise ValueError("Target weights harus memiliki Ticker dan Target_Weight_Pct.")
    nav = float(total_nav)
    if not pd.notna(nav) or nav <= 0:
        raise ValueError("Total NAV harus lebih besar dari nol.")
    p = positions.copy()
    t = target_weights[["Ticker", "Target_Weight_Pct"]].copy()
    p["Ticker"] = p["Ticker"].astype(str).str.upper().str.strip()
    t["Ticker"] = t["Ticker"].astype(str).str.upper().str.strip()
    if p["Ticker"].duplicated().any() or t["Ticker"].duplicated().any():
        raise ValueError("Ticker tidak boleh duplikat.")
    t["Target_Weight_Pct"] = pd.to_numeric(t["Target_Weight_Pct"], errors="coerce")
    if t["Target_Weight_Pct"].isna().any() or (t["Target_Weight_Pct"] < 0).any():
        raise ValueError("Target weight harus berupa angka tidak negatif.")
    if not abs(float(t["Target_Weight_Pct"].sum()) - 100.0) <= 0.05:
        raise ValueError("Total target weight harus 100% (toleransi 0,05%).")
    p = p.merge(t, on="Ticker", how="outer", validate="one_to_one")
    p[["Market_Value", "Latest_Price"]] = p[["Market_Value", "Latest_Price"]].fillna(0.0)
    p["Target_Weight_Pct"] = p["Target_Weight_Pct"].fillna(0.0)
    if (p["Latest_Price"] < 0).any() or (p["Market_Value"] < 0).any():
        raise ValueError("Harga dan market value tidak boleh negatif.")
    p["Current_Weight_Pct"] = p["Market_Value"] / nav * 100.0
    p["Target_Value"] = nav * p["Target_Weight_Pct"] / 100.0
    p["Trade_Value"] = p["Target_Value"] - p["Market_Value"]
    p["Estimated_Quantity_Change"] = p.apply(
        lambda r: r["Trade_Value"] / r["Latest_Price"] if r["Latest_Price"] > 0 else float("nan"), axis=1
    )
    p["Action"] = p["Trade_Value"].map(lambda x: "BUY" if x > 0.5 else ("SELL" if x < -0.5 else "HOLD"))
    return p.sort_values("Trade_Value", ascending=False).reset_index(drop=True)


def build_price_matrix(price_history: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Build aligned close-price matrix for selected equity tickers."""
    data = price_history.copy()
    required = {"Date", "Ticker", "Close"}
    if not required.issubset(data.columns):
        raise ValueError("Price history harus memiliki Date, Ticker, Close.")
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data["Ticker"] = data["Ticker"].astype(str).str.upper().str.strip()
    data["Close"] = pd.to_numeric(data["Close"], errors="coerce")
    data = data[data["Ticker"].isin([x.upper() for x in tickers])]
    matrix = data.pivot_table(index="Date", columns="Ticker", values="Close", aggfunc="last").sort_index()
    matrix = matrix.dropna(axis=1, how="all").ffill().dropna()
    if matrix.shape[0] < 2 or matrix.shape[1] == 0:
        raise ValueError("Data harga tidak cukup untuk backtest rebalancing.")
    return matrix
