"""Evaluate stored signals after 1, 3, 5, 10 and 20 completed sessions."""
from __future__ import annotations

import pandas as pd

from daily_signal_engine import load_daily_history
from daily_signal_storage import OUTCOME_HORIZONS, signal_history, record_outcome


def update_forward_outcomes(db_path=None, limit=500, owner_id=None):
    rows = signal_history(limit=limit, db_path=db_path, owner_id=owner_id)
    updated, errors = [], []
    grouped = {}
    for row in rows:
        grouped.setdefault((row["market"], row["ticker"]), []).append(row)
    for (market, ticker), signals in grouped.items():
        try:
            bars, _ = load_daily_history(ticker, market, "2y")
            dates = pd.DatetimeIndex(bars.index)
            if dates.tz is not None:
                dates = dates.tz_localize(None)
            bars = bars.copy()
            bars.index = dates.normalize()
            for row in signals:
                signal_date = pd.Timestamp(row["bar_date"]).normalize()
                future = bars.loc[bars.index > signal_date]
                for horizon in OUTCOME_HORIZONS:
                    if len(future) < horizon:
                        continue
                    dt = future.index[horizon - 1]
                    close = float(future.iloc[horizon - 1]["Close"])
                    value = record_outcome(row["id"], horizon, dt.date().isoformat(), close, db_path=db_path, owner_id=owner_id)
                    updated.append({"signal_id": row["id"], "horizon": horizon, "return_pct": value})
        except Exception as exc:
            errors.append({"market": market, "ticker": ticker, "error": str(exc)})
    return {"updated": updated, "errors": errors}
