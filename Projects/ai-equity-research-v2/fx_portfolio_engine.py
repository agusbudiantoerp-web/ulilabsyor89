"""FX-aware daily return conversion for mixed IDX / US portfolios.

The module works from close series and never forward-fills FX beyond a small,
explicit calendar-day tolerance. It does not model intraday execution.
"""
from __future__ import annotations

import math
import numbers
from typing import Mapping

import pandas as pd


def _clean_close(series: pd.Series, label: str) -> pd.Series:
    if not isinstance(series, pd.Series) or series.empty:
        raise ValueError(f"Close {label} kosong.")
    values = pd.to_numeric(series, errors="coerce")
    try:
        parsed_index = pd.to_datetime(values.index, errors="coerce")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Tanggal close {label} tidak valid.") from exc
    if parsed_index.isna().any():
        raise ValueError(f"Tanggal close {label} tidak valid.")
    values.index = parsed_index
    if values.index.tz is not None:
        values.index = values.index.tz_localize(None)
    if values.index.has_duplicates:
        raise ValueError(f"Tanggal close {label} duplikat; agregasi harus dilakukan secara eksplisit.")
    values = values.sort_index()
    if values.isna().any() or not all(math.isfinite(float(x)) for x in values):
        raise ValueError(f"Close {label} mengandung nilai kosong/non-finite.")
    if (values <= 0).any():
        raise ValueError(f"Close {label} harus positif.")
    return values.astype(float)


def portfolio_requires_fx(asset_currencies: Mapping[str, str], base_currency: str) -> bool:
    """Return whether any portfolio asset needs IDR/USD conversion."""
    if not isinstance(asset_currencies, Mapping):
        raise ValueError("asset_currencies harus berupa mapping.")
    base = str(base_currency).upper().strip()
    if base not in {"IDR", "USD"}:
        raise ValueError("Base currency hanya mendukung IDR atau USD.")
    return any(
        str(currency).upper().strip() != base
        for currency in asset_currencies.values()
    )


def convert_asset_returns_to_base_currency(
    local_close: pd.Series,
    asset_currency: str,
    usd_idr_close: pd.Series | None = None,
    base_currency: str = "IDR",
    *,
    max_fx_gap_days: int = 3,
) -> pd.DataFrame:
    """Return local, FX and base-currency daily returns on asset trading dates.

    USDIDR is IDR per USD. For an IDR asset in a USD base portfolio, FX
    conversion uses the reciprocal USDIDR rate.
    """
    currency = str(asset_currency).upper().strip()
    base = str(base_currency).upper().strip()
    if currency not in {"IDR", "USD"} or base not in {"IDR", "USD"}:
        raise ValueError("Mata uang aset dan base hanya mendukung IDR atau USD.")
    if (
        isinstance(max_fx_gap_days, bool)
        or not isinstance(max_fx_gap_days, numbers.Integral)
        or not 0 <= max_fx_gap_days <= 30
    ):
        raise ValueError("max_fx_gap_days harus integer 0–30.")
    asset = _clean_close(local_close, "asset")
    asset_frame = pd.DataFrame({"date": asset.index, "local_close": asset.values})
    if currency == base:
        merged = asset_frame.copy()
        merged["usd_idr"] = float("nan")
        fx_factor = pd.Series(1.0, index=merged.index)
    else:
        if usd_idr_close is None:
            raise ValueError("Data USD/IDR wajib untuk konversi lintas mata uang.")
        fx = _clean_close(usd_idr_close, "USD/IDR")
        fx_frame = pd.DataFrame({"date": fx.index, "usd_idr": fx.values})
        merged = pd.merge_asof(
            asset_frame.sort_values("date"), fx_frame.sort_values("date"),
            on="date", direction="backward",
            tolerance=pd.Timedelta(days=int(max_fx_gap_days)),
        )
        if merged["usd_idr"].isna().any():
            missing_dates = merged.loc[merged["usd_idr"].isna(), "date"].dt.date.astype(str).tolist()
            raise ValueError(
                "Cakupan FX tidak tersedia dalam toleransi "
                f"{max_fx_gap_days} hari untuk tanggal: {', '.join(missing_dates[:5])}"
            )
        if currency == "USD" and base == "IDR":
            fx_factor = merged["usd_idr"]
        else:
            fx_factor = 1.0 / merged["usd_idr"]
    merged["fx_factor"] = fx_factor
    merged["base_value"] = merged["local_close"] * merged["fx_factor"]
    merged["local_return"] = merged["local_close"].pct_change()
    merged["fx_return"] = merged["fx_factor"].pct_change()
    merged["base_return"] = merged["base_value"].pct_change()
    merged["fx_contribution_pct"] = (
        (1.0 + merged["local_return"]) * (1.0 + merged["fx_return"]) - 1.0
        - merged["local_return"]
    ) * 100.0
    merged = merged.set_index("date")
    merged.index.name = "date"
    return merged[[
        "local_close", "usd_idr", "fx_factor", "base_value",
        "local_return", "fx_return", "base_return", "fx_contribution_pct",
    ]]


def combine_mixed_currency_returns(
    asset_closes: Mapping[str, pd.Series],
    asset_currencies: Mapping[str, str],
    weights: Mapping[str, float],
    usd_idr_close: pd.Series | None = None,
    base_currency: str = "IDR",
    *,
    max_fx_gap_days: int = 3,
) -> dict:
    """Combine fixed target weights on union dates; closed markets earn zero that day."""
    if not all(isinstance(value, Mapping) for value in (asset_closes, asset_currencies, weights)):
        raise ValueError("Close, currencies dan weights harus berupa mapping.")
    raw_maps = (asset_closes, asset_currencies, weights)
    normalized_maps = []
    for mapping in raw_maps:
        keys = [str(key).strip().upper() for key in mapping]
        if any(not key for key in keys):
            raise ValueError("Ticker portfolio tidak boleh kosong.")
        if len(set(keys)) != len(keys):
            raise ValueError("Ticker portfolio duplikat setelah normalisasi.")
        normalized_maps.append(dict(zip(keys, mapping.values())))
    close_map, currency_map, weight_map = normalized_maps
    symbols = list(close_map)
    if not symbols:
        raise ValueError("Minimal satu aset diperlukan.")
    if set(symbols) != set(currency_map) or set(symbols) != set(weight_map):
        raise ValueError("Set ticker pada close, currency dan weights harus sama setelah normalisasi.")
    clean_weights = {}
    for symbol in symbols:
        raw_weight = weight_map[symbol]
        if isinstance(raw_weight, bool) or type(raw_weight).__name__ in {"bool_", "bool"}:
            raise ValueError("Bobot harus berupa angka, bukan boolean.")
        try:
            clean_weights[symbol] = float(raw_weight)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Bobot harus berupa angka finite dan tidak negatif.") from None
    if any(not math.isfinite(x) or x < 0 for x in clean_weights.values()):
        raise ValueError("Bobot harus finite dan tidak negatif.")
    total_weight = sum(clean_weights.values())
    if total_weight <= 0 or total_weight > 1.0000001:
        raise ValueError("Total bobot harus lebih besar dari 0 dan maksimal 100%.")
    requires_fx = any(str(currency_map[symbol]).upper().strip() != str(base_currency).upper().strip() for symbol in symbols)
    if requires_fx and usd_idr_close is None:
        raise ValueError("Data USD/IDR wajib untuk portfolio lintas mata uang.")
    converted = {
        symbol: convert_asset_returns_to_base_currency(
            close_map[symbol], currency_map[symbol], usd_idr_close,
            base_currency, max_fx_gap_days=max_fx_gap_days,
        )
        for symbol in symbols
    }
    dates = sorted(set().union(*(set(frame.index) for frame in converted.values())))
    returns = pd.DataFrame(index=pd.DatetimeIndex(dates, name="date"))
    fx_contribution = pd.DataFrame(index=returns.index)
    for symbol, frame in converted.items():
        returns[symbol] = frame["base_return"].reindex(returns.index).fillna(0.0)
        fx_contribution[symbol] = frame["fx_contribution_pct"].reindex(returns.index).fillna(0.0)
    weighted = returns.mul(pd.Series(clean_weights), axis=1)
    portfolio_return = weighted.sum(axis=1)
    equity = (1.0 + portfolio_return).cumprod()
    curve = pd.DataFrame({
        "portfolio_return": portfolio_return,
        "equity_index": equity,
        "weighted_fx_contribution_pct": fx_contribution.mul(
            pd.Series(clean_weights), axis=1
        ).sum(axis=1),
    }, index=returns.index)
    return {
        "base_currency": str(base_currency).upper(),
        "weights": clean_weights,
        "asset_currencies": {symbol: str(currency_map[symbol]).upper() for symbol in symbols},
        "asset_returns": returns,
        "asset_fx_contribution_pct": fx_contribution,
        "curve": curve,
        "total_return_pct": (float(equity.iloc[-1]) - 1.0) * 100.0,
        "method": (
            "Fixed target weights; local-market closed dates contribute zero return; "
            "FX uses backward as-of alignment with explicit maximum calendar-day tolerance. "
            "No cross-market same-day look-ahead."
        ),
    }
