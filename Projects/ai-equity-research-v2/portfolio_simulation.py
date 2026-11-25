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


def run_factor_stress_scenario(
    weights: dict[str, float],
    factor_exposures: dict[str, dict[str, float]],
    factor_shocks: dict[str, float],
) -> dict:
    """Apply user-supplied factor betas and shocks; no exposure is inferred."""
    if not weights or set(weights) != set(factor_exposures):
        raise ValueError("Ticker pada weights dan factor exposures harus sama dan tidak kosong.")
    clean_weights = {ticker: float(value) for ticker, value in weights.items()}
    if any(not math.isfinite(value) or value < 0 for value in clean_weights.values()):
        raise ValueError("Bobot harus finite dan tidak negatif.")
    if sum(clean_weights.values()) > 1.000001 or sum(clean_weights.values()) <= 0:
        raise ValueError("Total bobot harus di atas 0 dan maksimal 100%.")
    if not factor_shocks:
        raise ValueError("Minimal satu factor shock diperlukan.")
    shocks = {str(key): float(value) for key, value in factor_shocks.items()}
    if any(not math.isfinite(value) or value < -1 or value > 5 for value in shocks.values()):
        raise ValueError("Factor shock harus berada antara -100% dan +500% dalam satuan desimal.")
    asset_impacts = {}
    factor_contributions = {factor: 0.0 for factor in shocks}
    for ticker, exposures in factor_exposures.items():
        if not isinstance(exposures, dict):
            raise ValueError(f"Exposure {ticker} harus berupa dictionary.")
        impact = 0.0
        for factor, shock in shocks.items():
            beta = float(exposures.get(factor, 0.0))
            if not math.isfinite(beta):
                raise ValueError(f"Beta {factor} untuk {ticker} harus finite.")
            component = beta * shock
            impact += component
            factor_contributions[factor] += clean_weights[ticker] * component
        asset_impacts[ticker] = impact * 100.0
    portfolio_impact = sum(clean_weights[ticker] * asset_impacts[ticker] / 100.0 for ticker in clean_weights)
    return {
        "portfolio_return_pct": portfolio_impact * 100.0,
        "asset_impacts_pct": asset_impacts,
        "factor_contributions_pct": {key: value * 100.0 for key, value in factor_contributions.items()},
        "factor_shocks": shocks,
        "method": (
            "Linear factor approximation from user-supplied betas and shocks. "
            "No exposure is inferred; nonlinear interactions, convexity and hedges are excluded."
        ),
    }



def run_regime_switching_monte_carlo(
    historical_returns: pd.DataFrame,
    weights: dict[str, float],
    regime_labels: pd.Series,
    transition_matrix,
    *,
    regimes: tuple[str, str] = ("calm", "stress"),
    initial_regime: str | None = None,
    simulations: int = 5000,
    horizon_days: int = 252,
    seed: int = 42,
    confidence: float = 0.95,
) -> dict:
    """Simulate returns from two explicitly labeled regimes and a Markov transition matrix.

    Regime labels must be supplied by the caller; this function does not infer
    or backdate regimes. Each regime needs at least 20 complete observations.
    """
    if not isinstance(historical_returns, pd.DataFrame) or historical_returns.empty:
        raise ValueError("Historical returns kosong.")
    if set(weights) != set(historical_returns.columns):
        raise ValueError("Ticker weights harus sama dengan kolom historical returns.")
    if not isinstance(regime_labels, pd.Series):
        raise ValueError("Regime labels harus berupa pandas Series.")
    frame = historical_returns.apply(pd.to_numeric, errors="coerce")
    labels = regime_labels.copy()
    if not frame.index.equals(labels.index):
        raise ValueError("Index regime labels harus sama persis dengan index historical returns.")
    frame = frame.dropna(how="any")
    labels = labels.reindex(frame.index)
    if labels.isna().any() or not set(labels.astype(str).unique()).issubset(set(regimes)):
        raise ValueError("Setiap observasi harus memiliki salah satu label regime yang valid.")
    if len(regimes) != 2 or regimes[0] == regimes[1]:
        raise ValueError("Model hanya mendukung dua regime yang berbeda.")
    try:
        transition = np.asarray(transition_matrix, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Transition matrix harus berupa matriks 2x2.") from exc
    if transition.shape != (2, 2) or not np.isfinite(transition).all():
        raise ValueError("Transition matrix harus finite dan berukuran 2x2.")
    if (transition < 0).any() or not np.allclose(transition.sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("Setiap baris transition matrix harus non-negatif dan berjumlah 1.")
    weight = np.asarray([float(weights[column]) for column in frame.columns], dtype=float)
    if not np.isfinite(weight).all() or (weight < 0).any() or weight.sum() <= 0 or weight.sum() > 1.000001:
        raise ValueError("Bobot harus finite, non-negatif, total positif dan maksimal 100%.")
    if not isinstance(simulations, int) or not 100 <= simulations <= 100000:
        raise ValueError("Simulations harus antara 100 dan 100000.")
    if not isinstance(horizon_days, int) or not 1 <= horizon_days <= 2520:
        raise ValueError("Horizon harus antara 1 dan 2520 sesi.")
    if not 0.5 < confidence < 1:
        raise ValueError("Confidence harus antara 50% dan 100%.")
    if len(frame) < 40 or not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("Minimal 40 observasi return finite diperlukan.")
    stats = {}
    for regime in regimes:
        subset = frame.loc[labels.astype(str).eq(regime)]
        if len(subset) < 20:
            raise ValueError(f"Regime {regime} memerlukan minimal 20 observasi.")
        values = subset.to_numpy(dtype=float)
        mean = values.mean(axis=0)
        covariance = np.atleast_2d(np.cov(values, rowvar=False, ddof=1))
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        covariance_psd = (eigenvectors * np.clip(eigenvalues, 0.0, None)) @ eigenvectors.T
        stats[regime] = (mean, covariance_psd, bool(np.any(eigenvalues < -1e-12)))
    if initial_regime is None:
        initial_regime = str(labels.iloc[-1])
    if initial_regime not in regimes:
        raise ValueError("Initial regime tidak dikenal.")
    rng = np.random.default_rng(seed)
    regime_index = {regime: index for index, regime in enumerate(regimes)}
    states = np.full(simulations, regime_index[initial_regime], dtype=int)
    equity = np.ones(simulations, dtype=float)
    peaks = np.ones(simulations, dtype=float)
    max_drawdowns = np.zeros(simulations, dtype=float)
    final_regimes = np.zeros(2, dtype=int)
    for _ in range(horizon_days):
        uniforms = rng.random(simulations)
        probabilities = transition[states]
        next_states = (uniforms >= probabilities[:, 0]).astype(int)
        simulated_assets = np.empty((simulations, len(frame.columns)), dtype=float)
        for state, regime in enumerate(regimes):
            selected = np.flatnonzero(next_states == state)
            if not len(selected):
                continue
            mean, covariance, _ = stats[regime]
            simulated_assets[selected] = rng.multivariate_normal(
                mean, covariance, size=len(selected), check_valid="raise"
            )
        portfolio_returns = simulated_assets @ weight
        portfolio_returns = np.clip(portfolio_returns, -0.999999, None)
        equity *= 1.0 + portfolio_returns
        peaks = np.maximum(peaks, equity)
        max_drawdowns = np.minimum(max_drawdowns, equity / peaks - 1.0)
        states = next_states
    final_returns = equity - 1.0
    final_regimes = np.bincount(states, minlength=2)
    loss_quantile = float(np.quantile(final_returns, 1.0 - confidence))
    tail = final_returns[final_returns <= loss_quantile]
    return {
        "simulations": simulations,
        "horizon_days": horizon_days,
        "seed": seed,
        "confidence": confidence,
        "regimes": list(regimes),
        "transition_matrix": transition.tolist(),
        "initial_regime": initial_regime,
        "final_regime_counts": {regime: int(final_regimes[index]) for index, regime in enumerate(regimes)},
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
        "covariance_psd_adjusted": any(value[2] for value in stats.values()),
        "assumptions": (
            "Two-state Markov regime process with caller-supplied historical labels and transition probabilities; "
            "within-regime returns are multivariate normal using regime-specific sample mean/covariance. "
            "No automatic regime detection, parameter uncertainty, liquidity, taxes or corporate actions. "
            "Scenario distribution is not a forecast."
        ),
    }


def run_block_bootstrap_monte_carlo(
    historical_returns: pd.DataFrame,
    weights: dict[str, float],
    *,
    simulations: int = 5000,
    horizon_days: int = 252,
    block_size: int = 5,
    seed: int = 42,
    confidence: float = 0.95,
) -> dict:
    """Non-parametric circular moving-block bootstrap of joint asset returns."""
    if not isinstance(historical_returns, pd.DataFrame) or historical_returns.empty:
        raise ValueError("Historical returns kosong.")
    if set(weights) != set(historical_returns.columns):
        raise ValueError("Ticker weights harus sama dengan kolom historical returns.")
    frame = historical_returns.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if len(frame) < 20 or not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("Minimal 20 observasi return finite diperlukan.")
    if not isinstance(block_size, int) or not 1 <= block_size <= min(60, len(frame)):
        raise ValueError("Block size harus integer 1–60 dan tidak melebihi histori.")
    if not isinstance(simulations, int) or not 100 <= simulations <= 100000:
        raise ValueError("Simulations harus antara 100 dan 100000.")
    if not isinstance(horizon_days, int) or not 1 <= horizon_days <= 2520:
        raise ValueError("Horizon harus antara 1 dan 2520 sesi.")
    if not 0.5 < confidence < 1:
        raise ValueError("Confidence harus antara 50% dan 100%.")
    weight = np.asarray([float(weights[column]) for column in frame.columns], dtype=float)
    if not np.isfinite(weight).all() or (weight < 0).any() or weight.sum() <= 0 or weight.sum() > 1.000001:
        raise ValueError("Bobot harus finite, non-negatif, total positif dan maksimal 100%.")
    values = frame.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    blocks_per_path = int(np.ceil(horizon_days / block_size))
    offsets = np.arange(block_size)
    final_returns = np.empty(simulations, dtype=float)
    max_drawdowns = np.empty(simulations, dtype=float)
    batch_size = max(100, min(1000, simulations))
    for start in range(0, simulations, batch_size):
        stop = min(simulations, start + batch_size)
        count = stop - start
        block_starts = rng.integers(0, len(values), size=(count, blocks_per_path))
        indices = (block_starts[:, :, None] + offsets[None, None, :]) % len(values)
        sampled = values[indices].reshape(count, blocks_per_path * block_size, values.shape[1])[:, :horizon_days, :]
        asset_returns = np.clip(sampled, -0.999999, None)
        portfolio_returns = np.einsum("shn,n->sh", asset_returns, weight)
        equity = np.cumprod(1.0 + portfolio_returns, axis=1)
        peaks = np.maximum.accumulate(np.column_stack([np.ones(count), equity]), axis=1)[:, 1:]
        final_returns[start:stop] = equity[:, -1] - 1.0
        max_drawdowns[start:stop] = (equity / peaks - 1.0).min(axis=1)
    loss_quantile = float(np.quantile(final_returns, 1.0 - confidence))
    tail = final_returns[final_returns <= loss_quantile]
    return {
        "simulations": simulations,
        "horizon_days": horizon_days,
        "block_size": block_size,
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
            "Circular moving-block bootstrap resamples joint historical asset-return vectors, "
            "preserving cross-asset dependence and within-block serial patterns. "
            "It assumes historical blocks are representative and does not model structural breaks, "
            "parameter uncertainty beyond empirical resampling, liquidity, taxes or corporate actions. "
            "Scenario distribution is not a forecast."
        ),
    }
