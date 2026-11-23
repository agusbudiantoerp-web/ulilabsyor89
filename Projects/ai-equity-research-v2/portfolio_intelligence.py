"""Portfolio concentration, correlation and scenario analytics."""
from __future__ import annotations

import math
import pandas as pd


def analyze_portfolio(positions: pd.DataFrame, returns: dict[str, pd.Series]) -> dict:
    required = {"Ticker", "Market", "Currency", "Market Value"}
    if not required.issubset(positions.columns):
        raise ValueError(f"Kolom posisi wajib: {sorted(required)}")
    frame = positions.copy()
    frame["Market Value"] = pd.to_numeric(frame["Market Value"], errors="coerce").fillna(0)
    frame = frame[frame["Market Value"] > 0].copy()
    if frame.empty:
        raise ValueError("Tidak ada posisi dengan nilai pasar positif.")

    currency_exposure = frame.groupby("Currency")["Market Value"].sum().to_dict()
    market_exposure = frame.groupby("Market")["Market Value"].sum().to_dict()
    frame["Weight within currency %"] = (
        frame["Market Value"] / frame.groupby("Currency")["Market Value"].transform("sum") * 100
    )
    exposure_columns = ["Ticker", "Market", "Sector", "Currency", "Market Value", "Weight within currency %"]
    position_exposure = frame[[column for column in exposure_columns if column in frame.columns]].copy()
    sector_exposure = (
        frame.groupby(["Currency", "Sector"])["Market Value"].sum().reset_index()
        if "Sector" in frame.columns else pd.DataFrame()
    )
    currency_groups = {}
    correlations = {}
    risk_rows = []
    for currency, group in frame.groupby("Currency"):
        series = [returns[t] for t in group["Ticker"] if t in returns]
        if not series:
            continue
        daily = pd.concat(series, axis=1).sort_index().dropna(how="all")
        weights = group.drop_duplicates("Ticker").set_index("Ticker")["Market Value"]
        columns = [c for c in daily.columns if c in weights.index]
        if not columns:
            continue
        w = weights.reindex(columns).fillna(0)
        w = w / w.sum() if w.sum() else w
        aligned = daily[columns].fillna(0)
        portfolio_returns = aligned.mul(w, axis=1).sum(axis=1)
        vol = float(portfolio_returns.std(ddof=1) * math.sqrt(252) * 100) if len(portfolio_returns) > 1 else None
        var95 = float(-portfolio_returns.quantile(0.05) * 100) if len(portfolio_returns) > 1 else None
        drawdown = float(((1 + portfolio_returns).cumprod() / (1 + portfolio_returns).cumprod().cummax() - 1).min() * 100) if len(portfolio_returns) else None
        currency_groups[currency] = portfolio_returns
        correlations[currency] = aligned.corr().round(3)
        risk_rows.append({"Currency": currency, "Annualized volatility %": vol, "Historical VaR 95% 1d %": var95, "Max drawdown %": drawdown, "Observations": len(portfolio_returns)})

    return {
        "currency_exposure": currency_exposure,
        "market_exposure": market_exposure,
        "position_exposure": position_exposure,
        "sector_exposure": sector_exposure,
        "risk": pd.DataFrame(risk_rows),
        "correlations": correlations,
        "returns": currency_groups,
        "limitations": "IDR dan USD tidak dijumlahkan tanpa kurs FX. Korelasi dihitung hanya antarposisi dalam mata uang yang sama; histori harga dan Yahoo Finance dapat tidak lengkap.",
    }


def scenario_analysis(positions: pd.DataFrame, shocks: dict[str, float]) -> pd.DataFrame:
    """Apply user-entered price shocks per ticker; values are percentage points."""
    rows = []
    for _, item in positions.iterrows():
        ticker = str(item.get("Ticker", ""))
        market_value = float(item.get("Market Value", 0) or 0)
        shock = float(shocks.get(ticker, 0))
        rows.append({
            "Ticker": ticker,
            "Currency": item.get("Currency"),
            "Market Value": market_value,
            "Shock %": shock,
            "Estimated P/L": market_value * shock / 100,
            "Scenario Value": market_value * (1 + shock / 100),
        })
    return pd.DataFrame(rows)
