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
        ticker_values = group.groupby("Ticker")["Market Value"].sum()
        total_value = float(ticker_values.sum())
        available_tickers = [ticker for ticker in ticker_values.index if ticker in returns]
        covered_value = float(ticker_values.reindex(available_tickers).sum()) if available_tickers else 0.0
        coverage_pct = covered_value / total_value * 100 if total_value > 0 else 0.0
        if not available_tickers:
            risk_rows.append({
                "Currency": currency, "Annualized volatility %": None,
                "Historical VaR 95% 1d %": None, "Max drawdown %": None,
                "Observations": 0, "Market value coverage %": 0.0,
                "Positions with data": 0, "Total positions": int(len(ticker_values)),
                "Coverage status": "No price-return data",
            })
            continue
        daily = pd.concat(
            [returns[ticker].rename(ticker) for ticker in available_tickers],
            axis=1,
        ).sort_index().dropna(how="all")
        columns = [column for column in daily.columns if column in ticker_values.index]
        weights = ticker_values.reindex(columns).fillna(0)
        weights = weights / weights.sum() if weights.sum() else weights
        aligned = daily[columns].fillna(0)
        portfolio_returns = aligned.mul(weights, axis=1).sum(axis=1)
        vol = float(portfolio_returns.std(ddof=1) * math.sqrt(252) * 100) if len(portfolio_returns) > 1 else None
        var95 = float(-portfolio_returns.quantile(0.05) * 100) if len(portfolio_returns) > 1 else None
        compounded = (1 + portfolio_returns).cumprod()
        drawdown = float((compounded / compounded.cummax() - 1).min() * 100) if len(portfolio_returns) else None
        currency_groups[currency] = portfolio_returns
        correlations[currency] = aligned.corr().round(3)
        risk_rows.append({
            "Currency": currency, "Annualized volatility %": vol,
            "Historical VaR 95% 1d %": var95, "Max drawdown %": drawdown,
            "Observations": len(portfolio_returns),
            "Market value coverage %": round(coverage_pct, 1),
            "Positions with data": len(available_tickers),
            "Total positions": int(len(ticker_values)),
            "Coverage status": "Complete" if coverage_pct >= 99.99 else "Partial — interpret cautiously",
        })

    return {
        "currency_exposure": currency_exposure,
        "market_exposure": market_exposure,
        "position_exposure": position_exposure,
        "sector_exposure": sector_exposure,
        "risk": pd.DataFrame(risk_rows),
        "correlations": correlations,
        "returns": currency_groups,
        "limitations": "IDR dan USD tidak dijumlahkan tanpa kurs FX. Korelasi dihitung hanya antarposisi dalam mata uang yang sama. Risk metrics memakai posisi yang memiliki histori return; periksa kolom coverage karena data parsial tidak mewakili seluruh portfolio.",
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


def fx_scenario_analysis(positions: pd.DataFrame, usd_idr: float, fx_shock_pct: float = 0.0) -> dict:
    """Isolate USD/IDR translation risk using a user-supplied spot rate."""
    if usd_idr <= 0 or fx_shock_pct <= -100:
        raise ValueError("Kurs USD/IDR harus positif dan shock FX harus lebih besar dari -100%.")
    grouped = positions.groupby("Currency")["Market Value"].sum().to_dict()
    idr_value = float(grouped.get("IDR", 0.0))
    usd_value = float(grouped.get("USD", 0.0))
    unsupported = set(grouped) - {"IDR", "USD"}
    if unsupported:
        raise ValueError(f"Mata uang belum didukung untuk konversi IDR: {sorted(unsupported)}")
    current_usd_idr = usd_value * float(usd_idr)
    scenario_rate = float(usd_idr) * (1 + float(fx_shock_pct) / 100)
    scenario_usd_idr = usd_value * scenario_rate
    current_total = idr_value + current_usd_idr
    scenario_total = idr_value + scenario_usd_idr
    return {
        "base_currency": "IDR",
        "usd_idr_spot": float(usd_idr),
        "fx_shock_pct": float(fx_shock_pct),
        "scenario_usd_idr": scenario_rate,
        "current_portfolio_idr": current_total,
        "scenario_portfolio_idr": scenario_total,
        "fx_translation_pnl_idr": scenario_total - current_total,
        "note": "Simulasi translasi kurs saja; harga saham diasumsikan tetap. Kurs spot dimasukkan pengguna dan bukan kuotasi live.",
    }
