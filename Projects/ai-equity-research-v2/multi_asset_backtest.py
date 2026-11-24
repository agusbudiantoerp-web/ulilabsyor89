"""Long-only multi-asset daily portfolio simulation with lagged signals and costs."""
from __future__ import annotations

import math
import pandas as pd


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
    """Equal-weight active trend candidates; signals are lagged one session before returns."""
    if not bars_by_symbol:
        raise ValueError("Masukkan minimal satu instrumen.")
    if initial_capital <= 0 or fee_bps < 0 or slippage_bps < 0:
        raise ValueError("Modal dan biaya harus valid.")
    if max_positions < 1 or not 0 < max_weight_pct <= 100:
        raise ValueError("Batas posisi/bobot tidak valid.")
    closes, signals, strengths = {}, {}, {}
    rejected = []
    for symbol, bars in bars_by_symbol.items():
        if bars is None or bars.empty or "Close" not in bars:
            rejected.append({"ticker": symbol, "reason": "Data close tidak tersedia."})
            continue
        frame = bars.copy().sort_index()
        close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
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
    # Calculate returns on each asset's own trading calendar before aligning markets.
    return_series = [series.pct_change(fill_method=None).rename(symbol) for symbol, series in closes.items()]
    daily_returns = pd.concat(return_series, axis=1).reindex(close_frame.index)
    daily_returns = daily_returns.replace([float("inf"), -float("inf")], float("nan")).fillna(0.0)
    signal_frame = pd.concat(signals.values(), axis=1).reindex(close_frame.index).fillna(0.0)
    strength_frame = pd.concat(strengths.values(), axis=1).reindex(close_frame.index)
    # Shift signal and ranking score by one full bar to prevent look-ahead.
    active = signal_frame.shift(1).fillna(0.0)
    active_strength = strength_frame.shift(1)
    weights = pd.DataFrame(0.0, index=active.index, columns=active.columns)
    for date, row in active.iterrows():
        candidates = row[row > 0].index
        if len(candidates):
            ranking = active_strength.loc[date, candidates].dropna().sort_values(ascending=False)
            chosen = ranking.index[:max_positions]
            if len(chosen):
                weight = min(1.0 / len(chosen), max_weight_pct / 100.0)
                weights.loc[date, chosen] = weight
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = weights.iloc[0].abs().sum()
    cost_rate = (fee_bps + slippage_bps) / 10_000.0
    gross = (weights * daily_returns.reindex_like(weights).fillna(0.0)).sum(axis=1)
    net = gross - turnover * cost_rate
    equity = (1 + net).cumprod() * float(initial_capital)
    peak = equity.cummax()
    drawdown = (equity / peak - 1) * 100
    elapsed_days = max(1, (equity.index[-1] - equity.index[0]).days)
    years = elapsed_days / 365.25
    total_return = (float(equity.iloc[-1]) / initial_capital - 1) * 100
    cagr = ((float(equity.iloc[-1]) / initial_capital) ** (1 / years) - 1) * 100 if years > 0 and equity.iloc[-1] > 0 else -100.0
    vol = float(net.std(ddof=1) * math.sqrt(252)) if len(net) > 1 else 0.0
    sharpe = float(net.mean() / net.std(ddof=1) * math.sqrt(252)) if len(net) > 1 and net.std(ddof=1) > 0 else 0.0
    benchmark_return = None
    if benchmark_bars is not None and not benchmark_bars.empty:
        if isinstance(benchmark_bars.columns, pd.MultiIndex):
            matches = [i for i, col in enumerate(benchmark_bars.columns)
                       if "Close" in {str(part).title() for part in (col if isinstance(col, tuple) else (col,))}]
            benchmark_close = benchmark_bars.iloc[:, matches[0]] if matches else pd.Series(dtype=float)
        else:
            matches = [col for col in benchmark_bars.columns if str(col).strip().lower() == "close"]
            benchmark_close = benchmark_bars[matches[0]] if matches else pd.Series(dtype=float)
        if isinstance(benchmark_close, pd.DataFrame):
            benchmark_close = benchmark_close.iloc[:, 0]
        benchmark_close = pd.to_numeric(benchmark_close, errors="coerce").dropna()
        benchmark_close.index = pd.to_datetime(benchmark_close.index)
        if getattr(benchmark_close.index, "tz", None) is not None:
            benchmark_close.index = benchmark_close.index.tz_localize(None)
        aligned_benchmark = benchmark_close.reindex(net.index).dropna()
        if len(aligned_benchmark) > 1:
            benchmark_return = float((aligned_benchmark.iloc[-1] / aligned_benchmark.iloc[0] - 1) * 100)
    curve = pd.DataFrame({"equity": equity, "daily_return_pct": net * 100, "drawdown_pct": drawdown,
                          "gross_return_pct": gross * 100, "turnover": turnover})
    curve.index.name = "date"
    return {
        "initial_capital": float(initial_capital), "final_equity": float(equity.iloc[-1]),
        "total_return_pct": float(total_return), "cagr_pct": float(cagr),
        "max_drawdown_pct": float(drawdown.min()), "annualized_volatility_pct": vol * 100,
        "sharpe_ratio": sharpe, "benchmark_return_pct": benchmark_return,
        "active_symbols": list(closes), "rejected_symbols": rejected,
        "average_active_positions": float((weights > 0).sum(axis=1).mean()),
        "average_exposure_pct": float(weights.sum(axis=1).mean() * 100),
        "estimated_cost_paid": float((turnover * cost_rate * equity.shift(1).fillna(initial_capital)).sum()),
        "curve": curve.reset_index().to_dict("records"),
        "method": "Long-only equal-weight trend portfolio; signals use completed bar t and returns start at t+1; turnover costs applied on weight changes.",
        "limitations": "Simulation only. No dividends, taxes, borrow costs, intraday execution, market impact, corporate-action reconciliation or survivorship correction. Missing prices are not forward-filled; uninvested cash earns zero. Benchmark is price-only.",
    }
