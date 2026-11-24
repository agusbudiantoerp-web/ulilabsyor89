"""Long-only portfolio optimization with explicit data and currency limits."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd


def _project_capped_simplex(weights: np.ndarray, cap: float) -> np.ndarray:
    """Project a vector onto sum(weights)=1 and 0<=weight<=cap."""
    if cap * len(weights) < 1 - 1e-12:
        raise ValueError("Batas bobot maksimum terlalu kecil untuk jumlah aset.")
    low, high = float(np.min(weights - cap)), float(np.max(weights))
    for _ in range(100):
        mid = (low + high) / 2
        projected = np.clip(weights - mid, 0, cap)
        if projected.sum() > 1:
            low = mid
        else:
            high = mid
    result = np.clip(weights - (low + high) / 2, 0, cap)
    return result / result.sum()


def optimize_portfolio(
    positions: pd.DataFrame,
    returns: dict[str, pd.Series],
    risk_free_rate: float = 0.0,
    max_weight: float = 0.40,
    min_observations: int = 60,
    simulations: int = 20000,
    seed: int = 42,
) -> dict:
    """Return risk-parity and approximate maximum-Sharpe long-only weights.

    Optimization is restricted to a single native currency. Cross-currency
    portfolios require synchronized FX-adjusted return series and are rejected
    rather than mixing local-currency returns.
    """
    required = {"Ticker", "Currency", "Market Value"}
    if not required.issubset(positions.columns):
        raise ValueError(f"Kolom wajib: {sorted(required)}")
    frame = positions.copy()
    frame["Ticker"] = frame["Ticker"].astype(str).str.strip()
    frame["Currency"] = frame["Currency"].astype(str).str.upper().str.strip()
    frame["Market Value"] = pd.to_numeric(frame["Market Value"], errors="coerce")
    if frame["Market Value"].isna().any() or not np.isfinite(frame["Market Value"]).all():
        raise ValueError("Market Value harus finite.")
    if (frame["Market Value"] < 0).any():
        raise ValueError("Market Value tidak boleh negatif.")
    if (frame["Ticker"] == "").any() or (frame["Currency"] == "").any():
        raise ValueError("Ticker dan Currency wajib diisi.")
    frame = frame[frame["Market Value"] > 0].copy()
    if frame.empty:
        raise ValueError("Tidak ada posisi bernilai positif.")
    currencies = frame["Currency"].unique().tolist()
    if len(currencies) != 1:
        raise ValueError("Optimizer hanya mendukung satu mata uang per perhitungan. Konversi return dengan FX terlebih dahulu.")
    if not 0 < float(max_weight) <= 1 or not math.isfinite(float(max_weight)):
        raise ValueError("max_weight harus lebih besar dari 0 dan maksimal 1.")
    if not math.isfinite(float(risk_free_rate)) or risk_free_rate < -1 or risk_free_rate > 1:
        raise ValueError("risk_free_rate harus berupa angka antara -1 dan 1.")
    if not isinstance(min_observations, int) or min_observations < 20:
        raise ValueError("min_observations minimal 20.")
    if not isinstance(simulations, int) or not 1000 <= simulations <= 200000:
        raise ValueError("simulations harus antara 1.000 dan 200.000.")

    values = frame.groupby("Ticker")["Market Value"].sum()
    tickers = values.index.tolist()
    if len(tickers) < 2:
        raise ValueError("Optimizer memerlukan minimal dua aset.")
    if max_weight * len(tickers) < 1 - 1e-12:
        raise ValueError("Batas bobot maksimum terlalu kecil untuk jumlah aset.")

    missing = [ticker for ticker in tickers if ticker not in returns or not isinstance(returns[ticker], pd.Series)]
    if missing:
        raise ValueError("Histori return belum tersedia untuk: " + ", ".join(missing))
    daily = pd.concat([
        pd.to_numeric(returns[ticker], errors="coerce").rename(ticker)
        for ticker in tickers
    ], axis=1).sort_index()
    daily = daily.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    if len(daily) < min_observations:
        raise ValueError(f"Observasi lengkap hanya {len(daily)}; minimal {min_observations} diperlukan.")
    if (daily <= -1).any().any():
        raise ValueError("Return harian tidak boleh <= -100%.")

    mu = daily.mean().to_numpy(dtype=float) * 252
    covariance = daily.cov().to_numpy(dtype=float) * 252
    covariance = (covariance + covariance.T) / 2
    covariance += np.eye(len(tickers)) * 1e-10
    if not np.isfinite(mu).all() or not np.isfinite(covariance).all():
        raise ValueError("Estimasi return/covariance tidak finite.")

    n = len(tickers)
    budget = np.full(n, 1 / n)
    weights = np.full(n, 1 / n)
    # Equal risk contribution fixed-point iteration. Do not silently label
    # equal-weight fallback as risk parity when negative covariance blocks convergence.
    converged = False
    for _ in range(10000):
        marginal = covariance @ weights
        if np.any(marginal <= 1e-14):
            raise ValueError(
                "Risk parity tidak stabil: ada marginal risk contribution non-positif. "
                "Periksa histori return, korelasi dan aset yang dipilih."
            )
        updated = budget / marginal
        updated = _project_capped_simplex(updated, float(max_weight))
        if np.max(np.abs(updated - weights)) < 1e-10:
            weights = updated
            converged = True
            break
        weights = updated
    if not converged:
        raise ValueError(
            "Risk parity tidak mencapai konvergensi dalam 10.000 iterasi; "
            "hasil tidak ditampilkan agar tidak memberi label optimasi yang keliru."
        )

    risk = math.sqrt(max(float(weights @ covariance @ weights), 0.0))
    marginal = covariance @ weights
    contributions = weights * marginal / risk if risk > 0 else np.zeros(n)
    if np.any(contributions < -1e-10) or contributions.sum() <= 0:
        raise ValueError("Risk contribution tidak valid untuk solusi long-only ini.")
    contribution_pct = contributions / contributions.sum() * 100

    rng = np.random.default_rng(seed)
    candidates = rng.dirichlet(np.ones(n), size=simulations)
    candidates = np.vstack([candidates, np.full(n, 1 / n), weights])
    # Enforce max-weight cap for each candidate.
    candidates = np.vstack([_project_capped_simplex(row, float(max_weight)) for row in candidates])
    expected = candidates @ mu
    variance = np.einsum("ij,jk,ik->i", candidates, covariance, candidates)
    volatility = np.sqrt(np.maximum(variance, 1e-16))
    sharpe = (expected - float(risk_free_rate)) / volatility
    best = candidates[int(np.nanargmax(sharpe))]
    best_return = float(best @ mu)
    best_vol = math.sqrt(max(float(best @ covariance @ best), 0.0))

    def table_for(weights_array: np.ndarray, label: str) -> pd.DataFrame:
        return pd.DataFrame({
            "Ticker": tickers,
            "Currency": currencies[0],
            "Weight %": weights_array * 100,
            "Current Weight %": values.to_numpy() / values.sum() * 100,
            "Expected Annual Return %": mu * 100,
            "Annualized Volatility %": np.sqrt(np.maximum(np.diag(covariance), 0)) * 100,
            "Strategy": label,
        })

    risk_parity = table_for(weights, "Risk parity")
    risk_parity["Risk Contribution %"] = contribution_pct * 100 / 100
    max_sharpe = table_for(best, "Approximate max Sharpe")
    return {
        "currency": currencies[0],
        "observations": len(daily),
        "risk_parity": risk_parity,
        "max_sharpe": max_sharpe,
        "risk_parity_metrics": {
            "expected_annual_return_pct": float(weights @ mu * 100),
            "annualized_volatility_pct": risk * 100,
        },
        "max_sharpe_metrics": {
            "expected_annual_return_pct": best_return * 100,
            "annualized_volatility_pct": best_vol * 100,
            "sharpe_ratio": float((best_return - risk_free_rate) / best_vol) if best_vol > 0 else None,
            "method": "Deterministic seeded random-simplex search; approximate, not a global optimality guarantee.",
        },
        "methodology": (
            "Risk parity uses iterative equal-risk-contribution weights. Max Sharpe is "
            "an approximate long-only search over a seeded random simplex. Annualized "
            "expected returns use arithmetic daily means times 252; covariance uses "
            "sample daily covariance times 252. No FX translation, taxes, transaction "
            "costs, liquidity constraints or forward-looking forecasts are included."
        ),
        "limitations": (
            "Historical returns are not forecasts. Estimates are sensitive to lookback "
            "window, outliers and regime changes. Review turnover, liquidity, fees, "
            "taxes, concentration and actual holdings before implementation."
        ),
    }
