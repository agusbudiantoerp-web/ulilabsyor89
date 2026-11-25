"""Reproducible portfolio Monte Carlo and stress scenario analytics."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd


def run_portfolio_monte_carlo(
    historical_returns: pd.DataFrame,
    weights: dict[str, float],
    *,
    simulations: int = 5000,
    horizon_days: int = 252,
    seed: int = 42,
    confidence: float = 0.95,
) -> dict:
    if not isinstance(historical_returns, pd.DataFrame) or historical_returns.empty:
        raise ValueError("Historical returns kosong.")
    if set(weights) != set(historical_returns.columns):
        raise ValueError("Ticker weights harus sama dengan kolom historical returns.")
    frame = historical_returns.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if len(frame) < 20:
        raise ValueError("Minimal 20 observasi return lengkap diperlukan.")
    values = frame.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Historical returns harus finite.")
    weight = np.asarray([float(weights[column]) for column in frame.columns], dtype=float)
    if not np.isfinite(weight).all() or (weight < 0).any() or weight.sum() <= 0:
        raise ValueError("Bobot harus finite, non-negatif dan memiliki total positif.")
    if weight.sum() > 1.000001:
        raise ValueError("Total bobot tidak boleh melebihi 100%.")
    if not isinstance(simulations, int) or not 100 <= simulations <= 100000:
        raise ValueError("Simulations harus antara 100 dan 100000.")
    if not isinstance(horizon_days, int) or not 1 <= horizon_days <= 2520:
        raise ValueError("Horizon harus antara 1 dan 2520 sesi.")
    if not 0.5 < confidence < 1:
        raise ValueError("Confidence harus antara 50% dan 100%.")
    mean = values.mean(axis=0)
    covariance = np.cov(values, rowvar=False, ddof=1)
    covariance = np.atleast_2d(covariance)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    clipped = np.clip(eigenvalues, 0.0, None)
    covariance_psd = (eigenvectors * clipped) @ eigenvectors.T
    rng = np.random.default_rng(seed)
    paths = rng.multivariate_normal(mean, covariance_psd, size=(simulations, horizon_days), check_valid="raise")
    paths = np.clip(paths, -0.999999, None)
    portfolio_returns = np.einsum("shn,n->sh", paths, weight)
    equity = np.cumprod(1.0 + portfolio_returns, axis=1)
    final_returns = equity[:, -1] - 1.0
    peaks = np.maximum.accumulate(np.column_stack([np.ones(simulations), equity]), axis=1)[:, 1:]
    drawdowns = equity / peaks - 1.0
    max_drawdowns = drawdowns.min(axis=1)
    loss_quantile = float(np.quantile(final_returns, 1.0 - confidence))
    tail = final_returns[final_returns <= loss_quantile]
    return {
        "simulations": simulations,
        "horizon_days": horizon_days,
        "seed": seed,
        "confidence": confidence,
        "expected_return_pct": float(np.mean(final_returns) * 100.0),
        "median_return_pct": float(np.median(final_returns) * 100.0),
        "return_percentiles_pct": {
            "p05": float(np.quantile(final_returns, 0.05) * 100.0),
            "p25": float(np.quantile(final_returns, 0.25) * 100.0),
            "p75": float(np.quantile(final_returns, 0.75) * 100.0),
            "p95": float(np.quantile(final_returns, 0.95) * 100.0),
        },
        "var_loss_pct": float(-loss_quantile * 100.0),
        "cvar_loss_pct": float(-np.mean(tail) * 100.0) if len(tail) else float(-loss_quantile * 100.0),
        "median_max_drawdown_pct": float(np.median(max_drawdowns) * 100.0),
        "probability_of_loss_pct": float(np.mean(final_returns < 0) * 100.0),
        "weights": dict(weights),
        "assumptions": (
            "IID multivariate-normal daily returns using sample mean/covariance; "
            "no parameter uncertainty, regime switching, liquidity, taxes, costs or corporate actions. "
            "Simulation is a scenario distribution, not a forecast."
        ),
        "covariance_psd_adjusted": bool(np.any(eigenvalues < -1e-12)),
    }


def run_historical_stress_scenarios(
    returns: pd.DataFrame,
    weights: dict[str, float],
    shocks: dict[str, float],
) -> dict:
    if not isinstance(returns, pd.DataFrame) or returns.empty:
        raise ValueError("Return historis kosong.")
    if set(weights) != set(returns.columns) or set(shocks) != set(returns.columns):
        raise ValueError("Kolom return, weights dan shocks harus sama.")
    weight = {key: float(value) for key, value in weights.items()}
    shock = {key: float(value) for key, value in shocks.items()}
    if any(not math.isfinite(v) or v < 0 for v in weight.values()) or sum(weight.values()) > 1.000001:
        raise ValueError("Bobot harus valid dan total maksimal 100%.")
    if any(not math.isfinite(v) or v < -1 or v > 5 for v in shock.values()):
        raise ValueError("Shock harus berada antara -100% dan +500%.")
    contributions = {key: weight[key] * shock[key] for key in weights}
    return {
        "portfolio_return_pct": sum(contributions.values()) * 100.0,
        "asset_contributions_pct": {key: value * 100.0 for key, value in contributions.items()},
        "unallocated_cash_weight": 1.0 - sum(weight.values()),
        "method": "User-defined instantaneous price shocks; excludes path, FX and interaction effects.",
    }
