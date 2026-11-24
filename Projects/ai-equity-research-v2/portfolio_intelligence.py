"""Portfolio concentration, correlation and scenario analytics."""
from __future__ import annotations

import math
import pandas as pd


def analyze_portfolio(positions: pd.DataFrame, returns: dict[str, pd.Series]) -> dict:
    required = {"Ticker", "Market", "Currency", "Market Value"}
    if not required.issubset(positions.columns):
        raise ValueError(f"Kolom posisi wajib: {sorted(required)}")
    frame = positions.copy()
    frame["Ticker"] = frame["Ticker"].astype(str).str.upper().str.strip()
    frame["Currency"] = frame["Currency"].astype(str).str.upper().str.strip()
    frame["Market Value"] = pd.to_numeric(frame["Market Value"], errors="coerce")
    if frame["Market Value"].isna().any() or not frame["Market Value"].map(math.isfinite).all():
        raise ValueError("Market Value harus berupa angka finite.")
    if (frame["Market Value"] < 0).any():
        raise ValueError("Market Value tidak boleh negatif.")
    if (frame["Ticker"] == "").any() or (frame["Currency"] == "").any():
        raise ValueError("Ticker dan Currency wajib diisi.")
    frame["Market"] = frame["Market"].astype(str).str.upper().str.strip()
    if (frame["Market"] == "").any():
        raise ValueError("Market wajib diisi.")
    if "Sector" in frame.columns:
        frame["Sector"] = frame["Sector"].fillna("Unknown").astype(str).str.strip()
        frame.loc[frame["Sector"] == "", "Sector"] = "Unknown"
    frame = frame[frame["Market Value"] > 0].copy()
    if frame.empty:
        raise ValueError("Tidak ada posisi dengan nilai pasar positif.")

    currency_totals = frame.groupby("Currency")["Market Value"].sum()
    market_totals = frame.groupby("Market")["Market Value"].sum()
    if not currency_totals.map(math.isfinite).all() or not market_totals.map(math.isfinite).all():
        raise ValueError("Agregasi exposure melampaui rentang numerik yang didukung.")
    currency_exposure = currency_totals.to_dict()
    market_exposure = market_totals.to_dict()
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
        available_tickers = [
            ticker for ticker in ticker_values.index
            if ticker in returns and isinstance(returns[ticker], pd.Series)
            and not returns[ticker].dropna().empty
        ]
        covered_value = float(ticker_values.reindex(available_tickers).sum()) if available_tickers else 0.0
        coverage_pct = covered_value / total_value * 100 if total_value > 0 else 0.0
        if not available_tickers:
            risk_rows.append({
                "Currency": currency, "Annualized volatility %": None,
                "Historical VaR 95% 1d %": None, "Historical ES 95% 1d %": None, "Max drawdown %": None,
                "Observations": 0, "Market value coverage %": 0.0,
                "Positions with data": 0, "Total positions": int(len(ticker_values)),
                "Coverage status": "No price-return data",
            })
            continue
        daily = pd.concat(
            [returns[ticker].rename(ticker) for ticker in available_tickers],
            axis=1,
        ).sort_index()
        daily = daily.replace([float("inf"), -float("inf")], float("nan")).dropna(how="any")
        if (daily <= -1).any().any():
            raise ValueError("Daily return tidak boleh <= -100%.")
        columns = [column for column in daily.columns if column in ticker_values.index]
        if daily.empty or not columns:
            risk_rows.append({
                "Currency": currency, "Annualized volatility %": None,
                "Historical VaR 95% 1d %": None, "Historical ES 95% 1d %": None,
                "Max drawdown %": None, "Observations": 0,
                "Market value coverage %": round(coverage_pct, 1),
                "Positions with data": len(available_tickers),
                "Total positions": int(len(ticker_values)),
                "Coverage status": "No overlapping complete return dates",
            })
            continue
        weights = ticker_values.reindex(columns).fillna(0)
        weights = weights / weights.sum() if weights.sum() else weights
        aligned = daily[columns]
        portfolio_returns = aligned.mul(weights, axis=1).sum(axis=1)
        vol = float(portfolio_returns.std(ddof=1) * math.sqrt(252) * 100) if len(portfolio_returns) > 1 else None
        var95 = max(0.0, float(-portfolio_returns.quantile(0.05) * 100)) if len(portfolio_returns) > 1 else None
        tail = portfolio_returns[portfolio_returns <= portfolio_returns.quantile(0.05)] if len(portfolio_returns) > 1 else pd.Series(dtype=float)
        es95 = max(0.0, float(-tail.mean() * 100)) if not tail.empty else None
        compounded = (1 + portfolio_returns).cumprod()
        running_peak = compounded.cummax().clip(lower=1.0)
        drawdown = float((compounded / running_peak - 1).min() * 100) if len(portfolio_returns) else None
        currency_groups[currency] = portfolio_returns
        correlations[currency] = aligned.corr().round(3)
        risk_rows.append({
            "Currency": currency, "Annualized volatility %": vol,
            "Historical VaR 95% 1d %": var95, "Historical ES 95% 1d %": es95, "Max drawdown %": drawdown,
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
        if not math.isfinite(market_value) or market_value < 0:
            raise ValueError("Market Value skenario harus finite dan tidak negatif.")
        if not math.isfinite(shock) or shock < -100:
            raise ValueError("Shock saham harus finite dan tidak boleh di bawah -100%.")
        pnl = market_value * shock / 100
        scenario_value = market_value + pnl
        if not math.isfinite(pnl) or not math.isfinite(scenario_value):
            raise ValueError("Hasil skenario saham melampaui rentang numerik yang didukung.")
        rows.append({
            "Ticker": ticker,
            "Currency": item.get("Currency"),
            "Market Value": market_value,
            "Shock %": shock,
            "Estimated P/L": pnl,
            "Scenario Value": scenario_value,
        })
    return pd.DataFrame(rows)


def fx_scenario_analysis(positions: pd.DataFrame, usd_idr: float, fx_shock_pct: float = 0.0) -> dict:
    """Isolate USD/IDR translation risk using a user-supplied spot rate."""
    if (
        not math.isfinite(float(usd_idr))
        or not math.isfinite(float(fx_shock_pct))
        or usd_idr <= 0 or fx_shock_pct <= -100
    ):
        raise ValueError("Kurs USD/IDR harus finite dan positif; shock FX harus finite dan lebih besar dari -100%.")
    if not {"Currency", "Market Value"}.issubset(positions.columns):
        raise ValueError("Kolom Currency dan Market Value wajib tersedia.")
    values = pd.to_numeric(positions["Market Value"], errors="coerce")
    if values.isna().any() or not values.map(math.isfinite).all() or (values < 0).any():
        raise ValueError("Market Value FX harus finite dan tidak negatif.")
    fx_positions = positions.copy()
    fx_positions["Currency"] = fx_positions["Currency"].astype(str).str.upper().str.strip()
    fx_positions["Market Value"] = values
    grouped = fx_positions.groupby("Currency")["Market Value"].sum().to_dict()
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
    if not all(math.isfinite(value) for value in (
        current_usd_idr, scenario_rate, scenario_usd_idr, current_total, scenario_total
    )):
        raise ValueError("Hasil translasi FX melampaui rentang numerik yang didukung.")
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
