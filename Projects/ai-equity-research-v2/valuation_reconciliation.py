"""Cross-check enterprise/equity bridges and assumptions across DCF models."""
from __future__ import annotations

import math


def reconcile_dcf_models(multistage: dict, reverse_dcf: dict) -> dict:
    if not isinstance(multistage, dict) or not multistage.get("available"):
        raise ValueError("Multi-Stage DCF harus tersedia.")
    if not isinstance(reverse_dcf, dict) or not reverse_dcf:
        raise ValueError("Reverse DCF harus tersedia.")
    ms_financial = str(multistage.get("financial_currency") or "").upper()
    ms_quote = str(multistage.get("quote_currency") or "").upper()
    reverse_model = str(reverse_dcf.get("model_currency") or "").upper()
    reverse_quote = str(reverse_dcf.get("quote_currency") or "").upper()
    if not ms_financial or not ms_quote or not reverse_model or not reverse_quote:
        raise ValueError("Metadata mata uang kedua model belum lengkap.")
    if ms_financial != reverse_model or ms_quote != reverse_quote:
        raise ValueError(
            "Mata uang model/quote tidak sama. Samakan mata uang FCF/net debt dan harga quote sebelum rekonsiliasi."
        )
    required = {
        "multistage enterprise_value": multistage.get("enterprise_value"),
        "multistage equity_value": multistage.get("equity_value"),
        "multistage net_debt": multistage.get("net_debt"),
        "reverse target_enterprise_value": reverse_dcf.get("target_enterprise_value"),
        "reverse target_equity_value": reverse_dcf.get("target_equity_value"),
        "reverse net_debt": reverse_dcf.get("net_debt"),
        "multistage intrinsic_value_per_share": multistage.get("intrinsic_value_per_share"),
        "reverse market_price": reverse_dcf.get("market_price"),
    }
    for name, value in required.items():
        if value is None or not math.isfinite(float(value)):
            raise ValueError(f"Nilai {name} tidak valid.")
    ms_assumptions = multistage.get("assumptions") or {}
    try:
        reverse_wacc = float(reverse_dcf.get("wacc"))
        reverse_terminal = float(reverse_dcf.get("terminal_growth"))
        ms_wacc = float(ms_assumptions.get("wacc"))
        ms_terminal = float(ms_assumptions.get("terminal_growth"))
    except (TypeError, ValueError) as exc:
        raise ValueError("WACC/terminal growth kedua model wajib tersedia.") from exc
    if not all(math.isfinite(value) for value in (ms_wacc, ms_terminal, reverse_wacc, reverse_terminal)):
        raise ValueError("WACC/terminal growth kedua model tidak valid.")
    ms_ev = float(multistage["enterprise_value"])
    ms_equity = float(multistage["equity_value"])
    ms_debt = float(multistage["net_debt"])
    reverse_ev = float(reverse_dcf["target_enterprise_value"])
    reverse_equity = float(reverse_dcf["target_equity_value"])
    reverse_debt = float(reverse_dcf["net_debt"])
    ms_price = float(multistage["intrinsic_value_per_share"])
    market_price = float(reverse_dcf["market_price"])
    ev_gap = ms_ev - reverse_ev
    equity_gap = ms_equity - reverse_equity
    price_gap_pct = (ms_price / market_price - 1.0) * 100.0
    assumptions = {
        "net_debt_gap": ms_debt - reverse_debt,
        "wacc_gap_pct_points": (ms_wacc - reverse_wacc) * 100.0,
        "terminal_growth_gap_pct_points": (ms_terminal - reverse_terminal) * 100.0,
    }
    warnings = [
        "Multi-Stage DCF memakai FCFF berbasis revenue/margin/reinvestment; Reverse DCF memakai current FCF dan constant growth. Nilai tidak diharapkan identik.",
        "Perbedaan net debt, WACC dan terminal growth harus disamakan atau dijustifikasi sebelum membandingkan output.",
    ]
    return {
        "financial_currency": ms_financial,
        "quote_currency": ms_quote,
        "multistage_enterprise_value": ms_ev,
        "reverse_market_implied_enterprise_value": reverse_ev,
        "enterprise_value_gap": ev_gap,
        "enterprise_value_gap_pct": (ev_gap / reverse_ev * 100.0) if reverse_ev else None,
        "multistage_equity_value": ms_equity,
        "reverse_market_implied_equity_value": reverse_equity,
        "equity_value_gap": equity_gap,
        "multistage_intrinsic_price": ms_price,
        "reverse_market_price": market_price,
        "intrinsic_price_gap_pct": price_gap_pct,
        "multistage_ev_bridge_residual": ms_ev - ms_debt - ms_equity,
        "reverse_ev_bridge_residual": reverse_ev - reverse_debt - reverse_equity,
        "assumption_gaps": assumptions,
        "warnings": warnings,
        "method": (
            "Cross-model bridge comparison in matched currencies. Reverse DCF enterprise/equity values "
            "represent the market-implied target; Multi-Stage DCF values are the intrinsic model output."
        ),
    }
