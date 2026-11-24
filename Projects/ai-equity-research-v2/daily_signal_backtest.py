"""Single-position and walk-forward daily mark-to-market backtests. Research only."""
from __future__ import annotations

import math
import pandas as pd

from daily_signal_engine import calculate_indicators, DEFAULT_CONFIG


def backtest(
    bars: pd.DataFrame,
    config: dict | None = None,
    fee_bps: float = 10,
    slippage_bps: float = 10,
    risk_fraction: float = 0.01,
    max_allocation: float = 1.0,
    max_holding_sessions: int = 5,
    evaluation_start=None,
) -> dict:
    if fee_bps < 0 or slippage_bps < 0:
        raise ValueError("Fee dan slippage tidak boleh negatif.")
    if not 0 < risk_fraction <= 0.05:
        raise ValueError("risk_fraction harus >0 dan <=5%.")
    if not 0 < max_allocation <= 1:
        raise ValueError("max_allocation harus >0 dan <=100%.")
    if not 1 <= max_holding_sessions <= 5:
        raise ValueError("Holding harus antara 1 dan 5 sesi.")
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(bars.columns):
        raise ValueError(f"Kolom wajib tidak lengkap: {sorted(required - set(bars.columns))}")
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("Index backtest harus berupa DatetimeIndex.")
    if bars.index.has_duplicates:
        raise ValueError("Tanggal historis duplikat harus dibersihkan sebelum backtest.")
    if not bars.index.is_monotonic_increasing:
        raise ValueError("Data historis harus berurutan dari tanggal paling lama.")

    numeric = bars[list(required)].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not numeric.map(math.isfinite).all().all():
        raise ValueError("Data OHLCV mengandung nilai kosong atau non-finite.")
    if (numeric[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise ValueError("Harga OHLC harus positif.")
    if (numeric["Volume"] < 0).any():
        raise ValueError("Volume tidak boleh negatif.")
    invalid_ohlc = (
        (numeric["High"] < numeric[["Open", "Close", "Low"]].max(axis=1))
        | (numeric["Low"] > numeric[["Open", "Close", "High"]].min(axis=1))
    )
    if invalid_ohlc.any():
        raise ValueError("Relasi OHLC tidak valid pada data backtest.")

    cfg = {**DEFAULT_CONFIG, **(config or {})}
    x = calculate_indicators(bars).dropna(subset=[
        "SMA50", "EMA9", "EMA21", "RSI14", "MACD", "MACD_SIGNAL", "ATR14", "REL_VOLUME"
    ]).copy()
    if len(x) < 3:
        raise ValueError("Data historis tidak cukup untuk backtest.")
    start_ts = pd.Timestamp(evaluation_start) if evaluation_start is not None else None
    if start_ts is not None and start_ts.tzinfo is not None:
        start_ts = start_ts.tz_localize(None)

    cost = (fee_bps + slippage_bps) / 10000
    equity = 1.0
    trades = []
    curve_updates = {}
    i = 1
    while i < len(x) - 1:
        if start_ts is not None and x.index[i] < start_ts:
            i += 1
            continue
        r, p = x.iloc[i], x.iloc[i - 1]
        conditions = [
            r.Close > r.EMA21, r.EMA9 > r.EMA21, r.MACD > r.MACD_SIGNAL,
            r.MACD > p.MACD, cfg["rsi_min"] <= r.RSI14 <= cfg["rsi_max"],
            r.REL_VOLUME >= cfg["min_relative_volume"], r.Close > r.SMA50,
        ]
        score = sum(w for ok, w in zip(conditions, [20,20,15,10,15,10,10]) if ok)
        if score < cfg["min_score"]:
            i += 1
            continue
        entry_index = i + 1
        entry_bar = x.iloc[entry_index]
        raw_entry = float(entry_bar.Open)
        if not math.isfinite(raw_entry) or raw_entry <= 0:
            i += 1
            continue
        entry = raw_entry * (1 + cost)
        stop = max(0.01, float(r.Close) - cfg["atr_stop_multiple"] * float(r.ATR14))
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            i += 1
            continue
        position_fraction = min(risk_fraction / (risk_per_share / entry), max_allocation)
        target = entry + cfg["reward_risk_min"] * risk_per_share
        exit_price, exit_reason, exit_index = None, "time_exit", entry_index
        last_index = min(entry_index + max_holding_sessions, len(x))
        for j in range(entry_index, last_index):
            day = x.iloc[j]
            day_open, day_low, day_high = float(day.Open), float(day.Low), float(day.High)
            if day_low <= stop:
                exit_price, exit_reason, exit_index = min(day_open, stop), "stop", j
                break
            if day_high >= target:
                exit_price, exit_reason, exit_index = target, "target", j
                break
            if j == last_index - 1:
                exit_price, exit_reason, exit_index = float(day.Close), "time_exit", j
        if exit_price is None:
            i += 1
            continue
        exit_net = exit_price * (1 - cost)
        net_return = exit_net / entry - 1
        equity_before = equity
        for j in range(entry_index, exit_index):
            mark = float(x.iloc[j].Close) * (1 - cost)
            curve_updates[x.index[j]] = equity_before * (1 + position_fraction * (mark / entry - 1))
        equity_after = equity_before * (1 + position_fraction * net_return)
        curve_updates[x.index[exit_index]] = equity_after
        equity = equity_after
        trades.append({
            "signal_date": str(x.index[i].date()), "entry_date": str(x.index[entry_index].date()),
            "exit_date": str(x.index[exit_index].date()), "entry": entry, "exit": exit_net,
            "reason": exit_reason, "return_pct": net_return * 100, "score": int(score),
            "position_pct": position_fraction * 100, "equity_before": equity_before,
            "equity_after": equity_after,
        })
        i = exit_index + 1

    curve = []
    current = 1.0
    for date in x.index:
        if date in curve_updates:
            current = curve_updates[date]
        curve.append({"date": str(date.date()), "equity": current})
    equity_series = pd.Series(
        [item["equity"] for item in curve],
        index=pd.to_datetime([item["date"] for item in curve]), dtype=float,
    )
    if start_ts is not None:
        evaluation_series = equity_series.loc[equity_series.index >= start_ts]
        evaluation_bars = x.loc[x.index >= start_ts]
    else:
        evaluation_series, evaluation_bars = equity_series, x
    if evaluation_series.empty:
        evaluation_series = equity_series.iloc[-1:]
        evaluation_bars = x.iloc[-1:]
    daily_returns = evaluation_series.pct_change().dropna()
    running_peak = evaluation_series.cummax()
    drawdowns = evaluation_series / running_peak - 1
    max_dd = float(drawdowns.min()) if len(drawdowns) else 0.0
    n = len(trades)
    returns = [item["return_pct"] for item in trades]
    wins = sum(value > 0 for value in returns)
    gross_wins = sum(value for value in returns if value > 0)
    gross_losses = abs(sum(value for value in returns if value < 0))
    days = max((evaluation_bars.index[-1] - evaluation_bars.index[0]).days, 1)
    total_return = equity - 1
    cagr = (equity ** (365.25 / days) - 1) * 100 if equity > 0 else -100
    daily_std = float(daily_returns.std(ddof=1)) if len(daily_returns) > 1 else 0.0
    sharpe = float(daily_returns.mean() / daily_std * math.sqrt(252)) if daily_std > 0 else 0.0
    first_close, last_close = float(evaluation_bars.Close.iloc[0]), float(evaluation_bars.Close.iloc[-1])
    benchmark_return = (last_close * (1-cost) / (first_close * (1+cost)) - 1) * 100
    return {
        "trades": n, "win_rate_pct": wins / n * 100 if n else 0.0,
        "avg_return_pct": sum(returns) / n if n else 0.0,
        "profit_factor": gross_wins / gross_losses if gross_losses > 0 else (float("inf") if gross_wins > 0 else 0.0),
        "max_drawdown_pct": max_dd * 100, "ending_equity_index": equity,
        "total_return_pct": total_return * 100, "cagr_pct": cagr, "sharpe_ratio": sharpe,
        "benchmark_buy_hold_pct": benchmark_return, "risk_per_trade_pct": risk_fraction * 100,
        "max_allocation_pct": max_allocation * 100, "max_holding_sessions": max_holding_sessions,
        "cost_bps_round_trip": 2 * (fee_bps + slippage_bps), "trades_detail": trades,
        "equity_curve": [
            item for item in curve
            if start_ts is None or pd.Timestamp(item["date"]) >= start_ts
        ],
        "bias_controls": {
            "signal_execution_timing": "Signal is evaluated on completed bar i; entry is at next session open i+1.",
            "indicator_calculation": "Indicators use trailing/causal rolling and exponential calculations.",
            "same_bar_stop_target": "Stop is prioritized when stop and target are both touched in one daily bar.",
            "point_in_time_universe": False,
            "survivorship_bias_control": False,
            "corporate_action_history_complete": False,
        },
        "limitations": (
            "Simulasi harian konservatif dengan sinyal pada bar selesai dan entry sesi berikutnya. "
            "Data historis Yahoo saat ini bukan point-in-time universe; survivorship bias belum dapat dihilangkan. "
            "Pajak, spread aktual, market impact, suspensi, corporate actions historis lengkap, "
            "dan antrean/likuiditas eksekusi belum dimodelkan."
        ),
    }


def walk_forward_backtest(
    bars: pd.DataFrame,
    train_months: int = 24,
    test_months: int = 6,
    **kwargs,
) -> dict:
    """Expanding-history, sequential out-of-sample folds using the fixed documented rule set."""
    if train_months < 6 or test_months < 1:
        raise ValueError("Training minimal 6 bulan dan test minimal 1 bulan.")
    if bars is None or bars.empty:
        raise ValueError("Data historis kosong.")
    data = bars.sort_index().copy()
    dates = pd.DatetimeIndex(data.index)
    if dates.tz is not None:
        data.index = dates.tz_localize(None)
    first, last = data.index[0], data.index[-1]
    test_start = first + pd.DateOffset(months=int(train_months))
    folds = []
    while test_start <= last:
        test_end = min(test_start + pd.DateOffset(months=int(test_months)) - pd.Timedelta(days=1), last)
        subset = data.loc[:test_end]
        result = backtest(subset, evaluation_start=test_start, **kwargs)
        folds.append({
            "test_start": test_start.date().isoformat(),
            "test_end": test_end.date().isoformat(),
            "trades": result["trades"],
            "total_return_pct": result["total_return_pct"],
            "cagr_pct": result["cagr_pct"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "win_rate_pct": result["win_rate_pct"],
            "profit_factor": result["profit_factor"] if math.isfinite(result["profit_factor"]) else None,
            "sharpe_ratio": result["sharpe_ratio"],
            "benchmark_buy_hold_pct": result["benchmark_buy_hold_pct"],
        })
        test_start = test_end + pd.offsets.BDay(1)
    if not folds:
        raise ValueError(
            f"Data tidak cukup untuk walk-forward: perlu sekurangnya {train_months + test_months} bulan."
        )
    combined_equity = 1.0
    total_trades = sum(item["trades"] for item in folds)
    weighted_wins = sum(item["win_rate_pct"] * item["trades"] for item in folds)
    finite_pf = [item["profit_factor"] for item in folds if item["profit_factor"] is not None]
    for item in folds:
        combined_equity *= 1 + item["total_return_pct"] / 100
    return {
        "folds": folds,
        "fold_count": len(folds),
        "total_trades": total_trades,
        "combined_oos_return_pct": (combined_equity - 1) * 100,
        "weighted_win_rate_pct": weighted_wins / total_trades if total_trades else 0.0,
        "mean_profit_factor": sum(finite_pf) / len(finite_pf) if finite_pf else None,
        "worst_fold_drawdown_pct": min(item["max_drawdown_pct"] for item in folds),
        "profitable_folds_pct": sum(item["total_return_pct"] > 0 for item in folds) / len(folds) * 100,
        "method": "Expanding-history chronological walk-forward; fixed rules, no parameter tuning on test folds.",
        "limitations": "Out-of-sample historical simulation, not a forecast. Small samples, data revisions, survivorship, costs, taxes, corporate actions and liquidity can materially change results.",
    }
