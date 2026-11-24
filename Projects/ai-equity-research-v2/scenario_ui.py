import pandas as pd
import streamlit as st

from scenario_engine import run_scenarios, scenario_sensitivity


def render_scenario_analysis(data: dict, fx_rate: float, years: int = 5):
    st.subheader("Scenario Analysis")
    st.caption("Bear, Base, and Bull valuation based on explicit operating assumptions.")

    st.caption("Catatan katalis dan risiko diisi analis; sistem tidak mengarang peristiwa korporasi.")
    catalyst_notes = st.text_area(
        "Katalis utama (opsional, sertakan tanggal/sumber bila tersedia)",
        value="", key=f"scenario_catalysts_{data.get('ticker', 'unknown')}",
        help="Contoh: ekspansi kapasitas, kontrak baru, perubahan regulasi. Cantumkan sumber dan tanggal."
    )
    risk_notes = st.text_area(
        "Risiko utama (opsional, sertakan tanggal/sumber bila tersedia)",
        value="", key=f"scenario_risks_{data.get('ticker', 'unknown')}",
        help="Contoh: leverage, volatilitas bahan baku, risiko proyek, likuiditas."
    )

    ratios = data.get("ratios", {})

    revenue = ratios.get("Revenue")
    total_debt = ratios.get("Total debt")
    cash = ratios.get("Cash and equivalents")
    shares = ratios.get("Shares outstanding")
    current_price = data.get("price")

    required_values = {
        "Revenue": revenue,
        "Total debt": total_debt,
        "Cash and equivalents": cash,
        "Shares outstanding": shares,
        "Current price": current_price,
    }

    missing = [name for name, value in required_values.items() if value is None]

    if missing:
        reason = "Data belum lengkap: " + ", ".join(missing)
        st.warning("Scenario Analysis tidak tersedia. " + reason)
        return {"available": False, "reason": reason}

    financial_currency = data.get("financial_currency") or data.get("currency")
    quote_currency = data.get("quote_currency") or data.get("currency")

    effective_fx = (
        float(fx_rate)
        if financial_currency != quote_currency
        else 1.0
    )

    net_debt = float(total_debt) - float(cash)

    financials = {
        "ticker": data.get("ticker", "Unknown"),
        "revenue_base": float(revenue),
        "net_debt": net_debt,
        "shares_outstanding": float(shares),
        "current_price": float(current_price),
        "fx_rate": effective_fx,
        "financial_currency": financial_currency,
        "quote_currency": quote_currency,
    }

    st.caption(
        f"Financial currency: {financial_currency} | "
        f"Share currency: {quote_currency} | "
        f"FX conversion: {effective_fx:,.2f}"
    )

    st.write("**Financial inputs used by the scenario model**")

    input_table = pd.DataFrame([
        {"Input": "Revenue", "Value": revenue, "Currency": financial_currency},
        {"Input": "Total debt", "Value": total_debt, "Currency": financial_currency},
        {"Input": "Cash", "Value": cash, "Currency": financial_currency},
        {"Input": "Net debt", "Value": net_debt, "Currency": financial_currency},
        {"Input": "Shares outstanding", "Value": shares, "Currency": "Shares"},
        {"Input": "Current share price", "Value": current_price, "Currency": quote_currency},
    ])

    st.dataframe(input_table, use_container_width=True, hide_index=True)

    scenarios = {
        "Bear": {
            "revenue_growth": 0.02,
            "ebitda_margin": 0.08,
            "da_pct_revenue": 0.0305,
            "capex_pct_revenue": 0.10,
            "nwc_pct_revenue": 0.00,
            "tax_rate": 0.22,
            "wacc": 0.15,
            "terminal_growth": 0.02,
        },
        "Base": {
            "revenue_growth": 0.06,
            "ebitda_margin": 0.12,
            "da_pct_revenue": 0.0305,
            "capex_pct_revenue": 0.094,
            "nwc_pct_revenue": 0.00,
            "tax_rate": 0.22,
            "wacc": 0.12,
            "terminal_growth": 0.025,
        },
        "Bull": {
            "revenue_growth": 0.10,
            "ebitda_margin": 0.15,
            "da_pct_revenue": 0.0305,
            "capex_pct_revenue": 0.07,
            "nwc_pct_revenue": 0.00,
            "tax_rate": 0.22,
            "wacc": 0.10,
            "terminal_growth": 0.03,
        },
    }

    results = run_scenarios(financials, scenarios, years=years)
    rows = []

    for name, result in results["scenarios"].items():
        if result.get("available"):
            rows.append({
                "Scenario": name,
                "Status": "Available",
                "Intrinsic value / share": result["intrinsic_value_per_share"],
                "Upside / Downside (%)": result["upside_downside_pct"],
                "Enterprise value": result["enterprise_value"],
                "Equity value": result["equity_value"],
                "Reason": "",
            })
        else:
            rows.append({
                "Scenario": name,
                "Status": "Not available",
                "Intrinsic value / share": None,
                "Upside / Downside (%)": None,
                "Enterprise value": result.get("enterprise_value"),
                "Equity value": result.get("equity_value"),
                "Reason": result.get("reason", "Not available"),
            })

    st.subheader("Bear / Base / Bull comparison")
    st.caption("Valuation figures use the share's quote currency: " + str(quote_currency))
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    for name, result in results["scenarios"].items():
        with st.expander(f"{name} scenario assumptions and forecast"):
            st.json(scenarios[name])

            if result.get("forecast"):
                st.dataframe(
                    pd.DataFrame(result["forecast"]),
                    use_container_width=True,
                    hide_index=True,
                )

            if not result.get("available"):
                st.warning(result.get("reason", "Scenario valuation unavailable."))
            for warning in result.get("model_warnings") or []:
                st.warning(warning)

    st.subheader("DCF Sensitivity Analysis")

    selected_scenario = st.selectbox(
        "Sensitivity assumptions",
        ["Base", "Bull", "Bear"],
        index=1,
        key="scenario_sensitivity_case",
    )

    sensitivity = scenario_sensitivity(
        financials,
        scenarios[selected_scenario],
        years=years,
    )

    if sensitivity.get("available"):
        growth_values = sensitivity["terminal_growth_values"]
        table_rows = []

        for row in sensitivity["sensitivity"]:
            item = {"WACC": f"{row['wacc']:.1%}"}

            for index, growth in enumerate(growth_values):
                cell = row["values"][index]

                if cell.get("available"):
                    display_value = (
                        f"{cell['value_per_share']:,.2f} {quote_currency}"
                    )
                else:
                    equity = cell.get("equity_value")
                    if equity is not None:
                        display_value = (
                            f"N/M | Equity: {equity:,.0f} "
                            f"{financial_currency}"
                        )
                    else:
                        display_value = "N/M"

                item[f"Terminal growth {growth:.1%}"] = display_value

            table_rows.append(item)

        st.dataframe(
            pd.DataFrame(table_rows),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(sensitivity["note"])
    else:
        st.info("Sensitivity analysis is not available.")

    st.warning(
        "Scenario results depend on assumptions, not guaranteed future prices. "
        "Review financial data and assumptions before using these results."
    )
    return {
        "available": True,
        "ticker": financials.get("ticker"),
        "financials": financials,
        "assumptions": scenarios,
        "results": results.get("scenarios", {}),
        "sensitivity": sensitivity,
        "selected_scenario": selected_scenario,
        "research_context": {
            "catalysts": catalyst_notes.strip(),
            "risks": risk_notes.strip(),
            "analyst_note": "Katalis dan risiko merupakan catatan analis yang dimasukkan manual; bukan hasil verifikasi otomatis.",
        },
        "source_metadata": {
            "provider": data.get("data_source", "Yahoo Finance"),
            "generated_at_utc": data.get("as_of"),
            "latest_price_date": data.get("latest_price_date"),
            "income_statement_period": data.get("latest_financial_period"),
            "balance_sheet_period": data.get("latest_balance_period"),
            "cash_flow_period": data.get("latest_cashflow_period"),
            "financial_currency": financial_currency,
            "quote_currency": quote_currency,
            "fx_rate": effective_fx,
        },
    }
