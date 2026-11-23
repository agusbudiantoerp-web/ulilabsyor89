"""Explainable portfolio intelligence report builder for TSFA V1.4."""
from __future__ import annotations

from typing import Any
import math
import pandas as pd


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: Any) -> str:
    number = _number(value)
    return "Unavailable" if number is None else f"{number:.2%}"


def _date_text(value: Any) -> str:
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return "Unavailable"


def build_investment_report(
    summary: dict[str, Any],
    benchmark_result: dict[str, Any] | None = None,
    risk_result: dict[str, Any] | None = None,
    ending_positions: pd.DataFrame | None = None,
    investor_profile: dict[str, Any] | None = None,
    price_report: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Return factual findings; missing or statistically insufficient metrics are unavailable."""
    rows: list[dict[str, str]] = []

    def add(category: str, finding: str, status: str, detail: Any) -> None:
        rows.append({"Category": category, "Finding": finding, "Status": status, "Detail": str(detail)})

    nav = _number(summary.get("Ending NAV"))
    total_return = _number(summary.get("Total TWR"))
    cagr = _number(summary.get("CAGR"))
    volatility = _number(summary.get("Annualized Volatility"))
    sharpe = _number(summary.get("Sharpe Ratio"))
    max_dd = _number(summary.get("Maximum Drawdown"))
    return_periods = summary.get("Return Periods", "Unavailable")
    elapsed_days = summary.get("Elapsed Calendar Days", "Unavailable")

    add("Executive Summary", "Ending NAV", "Available" if nav is not None else "Unavailable", f"Rp {nav:,.0f}" if nav is not None else "Ending NAV was not supplied.")
    add("Performance", "Total time-weighted return", "Available" if total_return is not None else "Unavailable", _fmt_pct(total_return))
    cagr_detail = _fmt_pct(cagr) if cagr is not None else (f"Unavailable – requires at least 365 calendar days; observed {elapsed_days} days." if elapsed_days != "Unavailable" else "Unavailable")
    add("Performance", "Annualized return (CAGR)", "Available" if cagr is not None else "Unavailable", cagr_detail)
    vol_detail = _fmt_pct(volatility) if volatility is not None else (f"Unavailable – requires at least 30 daily return periods; observed {return_periods}." if return_periods != "Unavailable" else "Unavailable")
    sharpe_detail = f"{sharpe:.3f}" if sharpe is not None else (f"Unavailable – requires at least 30 daily return periods; observed {return_periods}." if return_periods != "Unavailable" else "Unavailable")
    add("Risk", "Annualized volatility", "Available" if volatility is not None else "Unavailable", vol_detail)
    add("Risk", "Sharpe ratio", "Available" if sharpe is not None else "Unavailable", sharpe_detail)
    add("Risk", "Maximum drawdown", "Available" if max_dd is not None else "Unavailable", _fmt_pct(max_dd))

    if benchmark_result and isinstance(benchmark_result.get("summary"), dict):
        bm = benchmark_result["summary"]
        p_ret = _number(bm.get("portfolio_total_return"))
        b_ret = _number(bm.get("benchmark_total_return"))
        active = _number(bm.get("annualized_active_return"))
        tracking_error = _number(bm.get("tracking_error"))
        information_ratio = _number(bm.get("information_ratio"))
        add("Benchmark", "Portfolio total return", "Available" if p_ret is not None else "Unavailable", _fmt_pct(p_ret))
        add("Benchmark", "Benchmark total return", "Available" if b_ret is not None else "Unavailable", _fmt_pct(b_ret))
        add("Benchmark", "Annualized active return", "Available" if active is not None else "Unavailable", _fmt_pct(active) if active is not None else "Unavailable – requires at least 365 calendar days for both series.")
        min_periods = bm.get("active_risk_minimum_periods", 30)
        actual_periods = bm.get("return_periods", 0)
        te_detail = _fmt_pct(tracking_error) if tracking_error is not None else f"Unavailable – requires at least {min_periods} matched adjacent daily return periods; observed {actual_periods}."
        ir_detail = f"{information_ratio:.3f}" if information_ratio is not None else f"Unavailable – requires at least {min_periods} matched adjacent daily return periods and non-zero active-return dispersion; observed {actual_periods}."
        add("Benchmark", "Annualized tracking error", "Available" if tracking_error is not None else "Unavailable", te_detail)
        add("Benchmark", "Information ratio", "Available" if information_ratio is not None else "Unavailable", ir_detail)
        coverage = bm.get("coverage", {})
        p_last = coverage.get("portfolio_last_date", bm.get("portfolio_last_date"))
        b_last = coverage.get("benchmark_last_date", bm.get("benchmark_last_date"))
        c_end = coverage.get("comparison_end_date", bm.get("end_date"))
        coverage_mismatch = p_last is not None and b_last is not None and pd.Timestamp(p_last) != pd.Timestamp(b_last)
        coverage_detail = f"Comparison ends {_date_text(c_end)}; portfolio last date {_date_text(p_last)}; benchmark last date {_date_text(b_last)}."
        if coverage_mismatch:
            coverage_detail += " Different last available dates; total returns are compared only through the last common date."
        add("Data Quality", "Benchmark date coverage", "Attention" if coverage_mismatch else "Available", coverage_detail)
    else:
        add("Benchmark", "Benchmark comparison", "Unavailable", "Benchmark series or valid overlapping observations were not available.")

    if risk_result and risk_result.get("status") == "success":
        add("Risk", "Risk model", "Available", "Risk analytics calculated using ending-period weights applied to historical asset returns; this is not a daily historical-weight reconstruction.")
    else:
        reason = (risk_result or {}).get("message", "Risk model result was not supplied.")
        add("Risk", "Risk model", "Unavailable", reason)

    if ending_positions is not None and not ending_positions.empty and {"Ticker", "Market_Value"}.issubset(ending_positions.columns):
        vals = pd.to_numeric(ending_positions["Market_Value"], errors="coerce").fillna(0).clip(lower=0)
        total = float(vals.sum())
        if total > 0:
            weights = vals / total
            top_idx = weights.idxmax()
            top_ticker = str(ending_positions.loc[top_idx, "Ticker"])
            top_weight = float(weights.loc[top_idx])
            hhi = float((weights ** 2).sum())
            add("Concentration", "Largest holding", "Available", f"{top_ticker}: {top_weight:.2%} of listed equity market value.")
            add("Concentration", "Top 3 holdings", "Available", f"{weights.nlargest(3).sum():.2%} of listed equity market value.")
            add("Concentration", "Equity concentration (HHI)", "Available", f"{hhi:.4f}; calculated from ending listed equity positions only, excluding cash.")
        else:
            add("Concentration", "Holdings concentration", "Unavailable", "Ending equity market value is zero or unavailable.")
    else:
        add("Concentration", "Holdings concentration", "Unavailable", "Ending positions with Ticker and Market_Value were not supplied.")

    if investor_profile:
        add("Investor Profile", "Screened investor profile", "Available", investor_profile.get("profile", "Unavailable"))
        for flag in investor_profile.get("guardrails", []):
            add("Investor Profile", "Guardrail", "Attention", flag)
        for warning in investor_profile.get("warnings", []):
            add("Investor Profile", "Profile conflict", "Attention", warning)
        if not investor_profile.get("guardrails") and not investor_profile.get("warnings"):
            add("Investor Profile", "Profile flags", "Clear", "No questionnaire guardrail or conflict flag was triggered.")
        add("Investor Profile", "Scope", "Information", investor_profile.get("disclaimer", "Educational screening only; not personalized investment advice."))
    else:
        add("Investor Profile", "Investor profile", "Unavailable", "Questionnaire has not been completed.")

    if price_report:
        failed = price_report.get("failed_tickers", {})
        quality = price_report.get("quality", {}) or {}
        warnings = list(quality.get("coverage_warnings", []) or [])
        if quality.get("invalid_dates"):
            warnings.append(f"Invalid dates: {quality['invalid_dates']}")
        if quality.get("invalid_prices"):
            warnings.append(f"Invalid prices: {quality['invalid_prices']}")
        if quality.get("duplicate_rows"):
            warnings.append(f"Duplicate rows: {quality['duplicate_rows']}")
        if quality.get("missing_tickers"):
            warnings.append("Missing tickers: " + ", ".join(quality["missing_tickers"]))
        if failed:
            warnings.append("Failed tickers: " + str(failed))
        quality_status = str(price_report.get("status", "Unknown")).upper()
        has_download_failures = bool(failed)
        has_integrity_issues = bool(
            quality.get("invalid_dates") or quality.get("invalid_prices")
            or quality.get("duplicate_rows") or quality.get("missing_tickers")
        )
        has_coverage_gap = bool(quality.get("coverage_warnings"))
        status = "Attention" if quality_status != "PASS" or warnings else "Available"
        if has_download_failures:
            download_state = "Download failure: one or more tickers could not be downloaded."
        else:
            download_state = "No ticker download failures were reported."
        if has_integrity_issues:
            integrity_state = "Data integrity issue detected; inspect invalid rows, duplicates, or missing tickers."
        else:
            integrity_state = "No invalid dates/prices, duplicate rows, or missing expected tickers were reported."
        if has_coverage_gap:
            coverage_state = "Requested-period coverage gap: the latest available trading date is earlier than the requested end date. This may reflect market holidays, feed publication timing, or incomplete coverage; it is not by itself proof of a failed download."
        else:
            coverage_state = "No requested-period end-date coverage gap was reported."
        detail = (
            f"Status: {quality_status}; downloaded tickers: {price_report.get('downloaded_tickers', [])}; "
            f"failed tickers: {failed or 'None'}. {download_state} {integrity_state} {coverage_state}"
        )
        if warnings:
            detail += " Findings: " + " | ".join(warnings)
        add("Data Quality", "Historical price download", status, detail)
    else:
        add("Data Quality", "Historical price download", "Unavailable", "Price download quality report was not supplied.")

    add("Methodology", "Interpretation limits", "Information", "TWR treats external cash flows as beginning-of-day flows. CAGR requires at least 365 calendar days; annualized volatility, Sharpe, tracking error and information ratio require at least 30 valid daily return periods. Findings are descriptive, not forecasts, OJK suitability assessments, or personalized buy/sell recommendations.")
    return pd.DataFrame(rows, columns=["Category", "Finding", "Status", "Detail"])


def build_investment_report_summary(report: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create deterministic status and category/status counts for audit export."""
    required = {"Category", "Status", "Finding", "Detail"}
    if not isinstance(report, pd.DataFrame):
        raise TypeError("report harus berupa pandas DataFrame.")
    missing = required - set(report.columns)
    if missing:
        raise ValueError(f"Kolom investment report tidak lengkap: {sorted(missing)}")

    status_order = ["Attention", "Unavailable", "Available", "Information", "Clear"]
    status_counts = (
        report.groupby("Status", dropna=False).size()
        .reindex(status_order, fill_value=0)
        .rename("Items").rename_axis("Status").reset_index()
    )
    category_counts = (
        report.groupby(["Category", "Status"], dropna=False)
        .size().rename("Items").reset_index()
        .sort_values(["Category", "Status"], kind="stable")
        .reset_index(drop=True)
    )
    return status_counts, category_counts
