"""Institutional-style portfolio risk diagnostics; research support, not advice."""
from __future__ import annotations

import math
from statistics import NormalDist
import pandas as pd


DEFAULT_RISK_LIMITS = {
    "max_position_weight_pct": 20.0,
    "max_sector_weight_pct": 35.0,
    "max_historical_var_pct": 5.0,
    "max_drawdown_pct": 20.0,
}


def analyze_institutional_risk(
    positions: pd.DataFrame,
    returns: dict[str, pd.Series],
    confidence_level: float = 0.95,
    stress_scenarios: dict[str, dict[str, float]] | None = None,
    risk_limits: dict[str, float] | None = None,
) -> dict:
    """Calculate concentration, historical/parametric VaR, ES and stress losses.

    Risk is calculated separately by native currency. Missing return observations
    are not silently replaced with zero; complete-case dates are used and
    coverage is reported so partial histories remain visible.
    """
    required = {"Ticker", "Currency", "Market Value"}
    if not required.issubset(positions.columns):
        raise ValueError(f"Kolom posisi wajib: {sorted(required)}")
    if not 0.90 <= float(confidence_level) <= 0.999:
        raise ValueError("confidence_level harus antara 0.90 dan 0.999.")

    frame = positions.copy()
    frame["Ticker"] = frame["Ticker"].astype(str).str.strip()
    frame["Currency"] = frame["Currency"].astype(str).str.upper().str.strip()
    frame["Market Value"] = pd.to_numeric(frame["Market Value"], errors="coerce")
    if frame["Market Value"].isna().any() or not frame["Market Value"].map(math.isfinite).all():
        raise ValueError("Market Value harus berupa angka finite.")
    frame = frame[(frame["Ticker"] != "") & (frame["Market Value"] > 0)].copy()
    if frame.empty:
        raise ValueError("Tidak ada posisi dengan market value positif.")

    limits = {**DEFAULT_RISK_LIMITS, **(risk_limits or {})}
    for key, value in limits.items():
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"Risk limit {key} harus finite dan tidak negatif.")

    frame = frame.groupby(["Ticker", "Currency"], as_index=False).agg(
        {"Market Value": "sum", **({"Sector": "first"} if "Sector" in frame.columns else {})}
    )
    frame["Weight %"] = (
        frame["Market Value"]
        / frame.groupby("Currency")["Market Value"].transform("sum") * 100
    )

    concentration = []
    for currency, group in frame.groupby("Currency"):
        weights = group["Weight %"] / 100
        hhi = float((weights ** 2).sum())
        row = {
            "Currency": currency,
            "Positions": int(len(group)),
            "Largest position %": float(group["Weight %"].max()),
            "Top 5 positions %": float(group.nlargest(5, "Market Value")["Weight %"].sum()),
            "Position HHI": hhi,
            "Effective positions": 1 / hhi if hhi > 0 else None,
        }
        if "Sector" in group.columns:
            sector_weights = group.groupby("Sector")["Market Value"].sum()
            total = float(group["Market Value"].sum())
            row["Largest sector"] = str(sector_weights.idxmax()) if not sector_weights.empty else None
            row["Largest sector %"] = float(sector_weights.max() / total * 100) if total else None
        concentration.append(row)

    risk_rows = []
    portfolio_returns = {}
    for currency, group in frame.groupby("Currency"):
        values = group.groupby("Ticker")["Market Value"].sum()
        available = [
            ticker for ticker in values.index
            if ticker in returns and isinstance(returns[ticker], pd.Series)
        ]
        covered_value = float(values.reindex(available).sum()) if available else 0.0
        total_value = float(values.sum())
        coverage = covered_value / total_value * 100 if total_value else 0.0
        if not available:
            risk_rows.append({
                "Currency": currency, "Coverage %": coverage, "Observations": 0,
                "Historical VaR %": None, "Historical ES %": None,
                "Parametric VaR %": None, "Annualized volatility %": None,
                "Max drawdown %": None, "Status": "NO DATA",
            })
            continue

        daily = pd.concat(
            [pd.to_numeric(returns[ticker], errors="coerce").rename(ticker) for ticker in available],
            axis=1,
        ).sort_index()
        daily = daily.replace([float("inf"), -float("inf")], float("nan")).dropna(how="any")
        if (daily <= -1).any().any():
            raise ValueError("Daily return tidak boleh <= -100%.")
        weights = values.reindex(available).astype(float)
        weights = weights / weights.sum()
        series = daily.mul(weights, axis=1).sum(axis=1)
        portfolio_returns[currency] = series
        if len(series) < 2:
            risk_rows.append({
                "Currency": currency, "Coverage %": coverage, "Observations": len(series),
                "Historical VaR %": None, "Historical ES %": None,
                "Parametric VaR %": None, "Annualized volatility %": None,
                "Max drawdown %": None, "Status": "INSUFFICIENT HISTORY",
            })
            continue

        tail_q = float(series.quantile(1 - confidence_level))
        tail = series[series <= tail_q]
        mean = float(series.mean())
        std = float(series.std(ddof=1))
        z_score = NormalDist().inv_cdf(float(confidence_level))
        parametric_var = max(0.0, -(mean - z_score * std)) * 100
        growth = (1 + series).cumprod()
        running_peak = growth.cummax().clip(lower=1.0)
        drawdown = (growth / running_peak - 1).min() * 100
        hist_var = max(0.0, -tail_q * 100)
        hist_es = max(0.0, -float(tail.mean()) * 100) if not tail.empty else hist_var
        risk_rows.append({
            "Currency": currency, "Coverage %": coverage, "Observations": len(series),
            "Historical VaR %": hist_var, "Historical ES %": hist_es,
            "Parametric VaR %": parametric_var,
            "Annualized volatility %": std * math.sqrt(252) * 100,
            "Max drawdown %": float(drawdown),
            "Status": "COMPLETE" if coverage >= 99.99 else "PARTIAL COVERAGE",
        })

    breaches = []
    for row in concentration:
        if row["Largest position %"] > float(limits["max_position_weight_pct"]):
            breaches.append({"Currency": row["Currency"], "Metric": "Largest position",
                             "Observed": row["Largest position %"], "Limit": limits["max_position_weight_pct"]})
        if row.get("Largest sector %") is not None and row["Largest sector %"] > float(limits["max_sector_weight_pct"]):
            breaches.append({"Currency": row["Currency"], "Metric": "Largest sector",
                             "Observed": row["Largest sector %"], "Limit": limits["max_sector_weight_pct"]})
    for row in risk_rows:
        if row.get("Historical VaR %") is not None and row["Historical VaR %"] > float(limits["max_historical_var_pct"]):
            breaches.append({"Currency": row["Currency"], "Metric": "Historical VaR",
                             "Observed": row["Historical VaR %"], "Limit": limits["max_historical_var_pct"]})
        if row.get("Max drawdown %") is not None and abs(row["Max drawdown %"]) > float(limits["max_drawdown_pct"]):
            breaches.append({"Currency": row["Currency"], "Metric": "Maximum drawdown",
                             "Observed": abs(row["Max drawdown %"]), "Limit": limits["max_drawdown_pct"]})

    stress_rows = []
    for scenario_name, shocks in (stress_scenarios or {}).items():
        for currency, group in frame.groupby("Currency"):
            pnl = 0.0
            for item in group.to_dict("records"):
                shock = float((shocks or {}).get(item["Ticker"], 0.0))
                if not math.isfinite(shock) or shock < -100:
                    raise ValueError("Shock saham harus finite dan tidak boleh di bawah -100%.")
                pnl += float(item["Market Value"]) * shock / 100
            base = float(group["Market Value"].sum())
            stress_rows.append({
                "Scenario": scenario_name, "Currency": currency,
                "Estimated P/L": pnl, "Scenario Value": base + pnl,
                "Return %": pnl / base * 100 if base else 0.0,
            })

    return {
        "confidence_level": float(confidence_level),
        "concentration": pd.DataFrame(concentration),
        "risk": pd.DataFrame(risk_rows),
        "limit_breaches": pd.DataFrame(breaches, columns=["Currency", "Metric", "Observed", "Limit"]),
        "stress": pd.DataFrame(stress_rows),
        "returns": portfolio_returns,
        "risk_limits": limits,
        "methodology": (
            "Historical VaR is the empirical loss quantile; Expected Shortfall is "
            "the mean loss in observations at or beyond that tail quantile. "
            "Parametric VaR assumes an approximately normal return distribution. "
            "Metrics are separated by native currency and use complete-case dates."
        ),
        "limitations": (
            "Historical and parametric risk estimates are sensitive to sample length, "
            "regime changes, missing data and non-normal returns. Stress shocks are "
            "user-defined and do not represent forecasts or guaranteed worst cases."
        ),
    }
