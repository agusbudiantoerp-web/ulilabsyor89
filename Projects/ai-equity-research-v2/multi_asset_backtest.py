"""Long-only multi-asset daily portfolio simulation with lagged signals and costs."""
from __future__ import annotations

import math
import numbers
import pandas as pd


def _validated_close(bars: pd.DataFrame, label: str) -> pd.Series:
    if not isinstance(bars, pd.DataFrame) or bars.empty:
        raise ValueError(f"{label}: data Close tidak tersedia.")
    close_column = "Close" if "Close" in bars.columns else None
    if close_column is None and isinstance(bars.columns, pd.MultiIndex):
        matches = [
            column for column in bars.columns
            if any(str(part).strip().lower() == "close" for part in (column if isinstance(column, tuple) else (column,)))
        ]
        if len(matches) == 1:
            close_column = matches[0]
        elif len(matches) > 1:
            raise ValueError(f"{label}: kolom Close benchmark ambigu; pilih satu instrumen terlebih dahulu.")
    if close_column is None:
        raise ValueError(f"{label}: data Close tidak tersedia.")
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError(f"{label}: index harus berupa DatetimeIndex.")
    if bars.index.has_duplicates:
        raise ValueError(f"{label}: tanggal historis duplikat.")
    if not bars.index.is_monotonic_increasing:
        raise ValueError(f"{label}: tanggal historis harus berurutan.")
    index = bars.index
    if index.tz is not None:
        index = index.tz_localize(None)
    if index.has_duplicates:
        raise ValueError(f"{label}: tanggal duplikat setelah normalisasi timezone.")
    close = pd.to_numeric(bars[close_column], errors="coerce")
    if close.isna().any() or not all(math.isfinite(float(value)) for value in close):
        raise ValueError(f"{label}: Close mengandung nilai kosong, non-numeric atau non-finite.")
    if (close <= 0).any():
        raise ValueError(f"{label}: Close harus positif.")
    close.index = index
    return close


def _finite_parameter(name: str, value, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or type(value).__name__ in {"bool_", "bool"}:
        raise ValueError(f"{name} harus berupa angka finite.")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} harus berupa angka finite.") from None
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{name} harus finite dan >= {minimum}.")
    return result


def run_multi_asset_backtest(
    bars_by_symbol: dict[str, pd.DataFrame],
    benchmark_bars: pd.DataFrame | None = None,
    initial_capital: float = 100_000_000.0,
    fee_bps: float = 10.0,
    slippage_bps: float = 10.0,
    max_positions: int = 8,
    max_weight_pct: float = 20.0,
    min_history: int = 220,
) -> dict:
    """Equal-weight active trend candidates; signals are lagged one full session."""
    if not isinstance(bars_by_symbol, dict) or not bars_by_symbol:
        raise ValueError("Masukkan minimal satu instrumen.")
    initial_capital = _finite_parameter("initial_capital", initial_capital, minimum=0)
    if initial_capital <= 0:
        raise ValueError("Modal harus lebih besar dari 0.")
    fee_bps = _finite_parameter("fee_bps", fee_bps, minimum=0)
    slippage_bps = _finite_parameter("slippage_bps", slippage_bps, minimum=0)
    max_weight_pct = _finite_parameter("max_weight_pct", max_weight_pct, minimum=0)
    for name, value, minimum in (("max_positions", max_positions, 1), ("min_history", min_history, 1)):
        if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < minimum:
            raise ValueError(f"{name} harus bilangan bulat >= {minimum}.")
    if max_weight_pct > 100:
        raise ValueError("max_weight_pct tidak boleh melebihi 100%.")
    if fee_bps + slippage_bps >= 10_000:
        raise ValueError("Biaya transaksi gabungan harus di bawah 100%.")

    closes, signals, strengths = {}, {}, {}
    rejected = []
    for symbol, bars in bars_by_symbol.items():
        close = _validated_close(bars, str(symbol))
        if len(close) < min_history:
            rejected.append({"ticker": symbol, "reason": f"Histori kurang dari {min_history} sesi."})
            continue
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema200 = close.ewm(span=200, adjust=False).mean()
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi = 100 - 100 / (1 + rs)
        rsi.loc[(loss == 0) & (gain > 0)] = 100
        signal = ((close > ema20) & (ema20 > ema50) & (close > ema200) & (rsi >= 50) & (rsi <= 75)).astype(float)
        strength = (((close / ema200) - 1) + ((ema20 / ema50) - 1)) * 100
        closes[str(symbol)] = close.rename(str(symbol))
        signals[str(symbol)] = signal.rename(str(symbol))
        strengths[str(symbol)] = strength.where(signal > 0).rename(str(symbol))
    if not closes:
        raise ValueError("Tidak ada instrumen dengan histori memadai.")

    close_frame = pd.concat(closes.values(), axis=1).sort_index()
    # Returns are calculated on each instrument's own exchange calendar.
    return_series = [series.pct_change(fill_method=None).rename(symbol) for symbol, series in closes.items()]
    daily_returns = pd.concat(return_series, axis=1).reindex(close_frame.index)
    daily_returns = daily_returns.replace([float("inf"), -float("inf")], float("nan")).fillna(0.0)
    signal_frame = pd.concat(signals.values(), axis=1).reindex(close_frame.index).fillna(0.0)
    strength_frame = pd.concat(strengths.values(), axis=1).reindex(close_frame.index)
    active = signal_frame.shift(1).fillna(0.0)
    active_strength = strength_frame.shift(1)
    weights = pd.DataFrame(0.0, index=active.index, columns=active.columns)
    for date, row in active.iterrows():
        candidates = row[row > 0].index
        if len(candidates):
            ranking = active_strength.loc[date, candidates].dropna().sort_values(ascending=False)
            chosen = ranking.index[:int(max_positions)]
            if len(chosen):
                weight = min(1.0 / len(chosen), max_weight_pct / 100.0)
                weights.loc[date, chosen] = weight
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = weights.iloc[0].abs().sum()
    cost_rate = (fee_bps + slippage_bps) / 10_000.0
    gross = (weights * daily_returns.reindex_like(weights).fillna(0.0)).sum(axis=1)
    net = gross - turnover * cost_rate
    equity = (1 + net).cumprod() * initial_capital
    peak = equity.cummax()
    drawdown = (equity / peak - 1) * 100
    elapsed_days = max(1, (equity.index[-1] - equity.index[0]).days)
    years = elapsed_days / 365.25
    total_return = (float(equity.iloc[-1]) / initial_capital - 1) * 100
    cagr = ((float(equity.iloc[-1]) / initial_capital) ** (1 / years) - 1) * 100 if years > 0 and equity.iloc[-1] > 0 else -100.0
    daily_std = float(net.std(ddof=1)) if len(net) > 1 else 0.0
    vol = daily_std * math.sqrt(252)
    sharpe = float(net.mean() / daily_std * math.sqrt(252)) if daily_std > 0 else 0.0

    benchmark_return = None
    if benchmark_bars is not None:
        benchmark_close = _validated_close(benchmark_bars, "Benchmark")
        aligned_benchmark = benchmark_close.reindex(net.index).dropna()
        if len(aligned_benchmark) > 1:
            benchmark_return = float((aligned_benchmark.iloc[-1] / aligned_benchmark.iloc[0] - 1) * 100)
    curve = pd.DataFrame({
        "equity": equity, "daily_return_pct": net * 100,
        "drawdown_pct": drawdown, "gross_return_pct": gross * 100,
        "turnover": turnover,
    })
    curve.index.name = "date"
    return {
        "initial_capital": initial_capital, "final_equity": float(equity.iloc[-1]),
        "total_return_pct": float(total_return), "cagr_pct": float(cagr),
        "max_drawdown_pct": float(drawdown.min()), "annualized_volatility_pct": vol * 100,
        "sharpe_ratio": sharpe, "benchmark_return_pct": benchmark_return,
        "active_symbols": list(closes), "rejected_symbols": rejected,
        "average_active_positions": float((weights > 0).sum(axis=1).mean()),
        "average_exposure_pct": float(weights.sum(axis=1).mean() * 100),
        "estimated_cost_paid": float((turnover * cost_rate * equity.shift(1).fillna(initial_capital)).sum()),
        "curve": curve.reset_index().to_dict("records"),
        "method": "Long-only equal-weight trend portfolio; signals use completed bar t and returns start at t+1; turnover costs applied on weight changes.",
        "price_adjustment_policy": (
            "Close is used exactly as supplied; this engine does not apply stock-split adjustments. "
            "Input histories must use a consistent split-adjusted basis. If the provider already "
            "adjusts historical prices for splits, do not apply the same split again to this price "
            "series. Unadjusted raw prices spanning a split must be normalized before backtesting."
        ),
        "limitations": "Simulation only. No dividends/total-return adjustment, taxes, borrow costs, intraday execution, market impact, corporate-action reconciliation or survivorship correction. Missing asset prices on non-trading dates contribute zero return; uninvested cash earns zero. Benchmark is price-only and must use a consistent split-adjusted price basis.",
    }
