
import sys
import hashlib
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

# ---------------------------------------------------------
# PATH AND ENGINE IMPORTS
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tsfa_portfolio_engine import (
    _read_workbook,
    validate_portfolio_workbook,
)

from tsfa_historical_price_engine import (
    collect_required_tickers,
    download_historical_prices,
)

from tsfa_historical_portfolio_engine import calculate_time_weighted_returns
from tsfa_portfolio_lifecycle_engine import run_portfolio_lifecycle
from tsfa_benchmark_engine import calculate_benchmark_comparison
from tsfa_multi_benchmark_engine import (
    BENCHMARKS, compare_all_benchmarks, parse_benchmark_csv,
)
from tsfa_portfolio_risk import calculate_portfolio_risk
from tsfa_v14_intelligence import (
    build_ending_positions,
    extract_benchmark_series,
    calculate_rebalance_plan,
    build_price_matrix,
)
from tsfa_portfolio_stress import calculate_market_stress, calculate_sector_stress
from tsfa_sector_analysis import calculate_sector_exposure, DEFAULT_SECTOR_MAP
from tsfa_rebalancing_engine import run_rebalanced_backtest
from tsfa_investor_profile import evaluate_investor_profile
from tsfa_investment_report import build_investment_report, build_investment_report_summary
from tsfa_v14_performance import calculate_summary, build_nav_reconciliation


# ---------------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="TSFA V1.4 - Portfolio Intelligence",
    page_icon="📊",
    layout="wide",
)

st.title("TSFA Dual Market V1.4")
st.subheader("Portfolio Backtesting & Performance Intelligence")

st.caption(
    "Historical portfolio analysis based on actual holdings, "
    "transactions, cash flows, and historical market prices."
)

st.info(
    "V1.4 Prototype | Indonesia Stock Market | IDR | "
    "Uploaded portfolio data is processed in the current session."
)


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def build_excel_export(
    daily,
    twr_result,
    price_history,
    summary,
    benchmark_result=None,
    benchmark_results=None,
    benchmark_table=None,
    risk_result=None,
    ending_positions=None,
    investor_profile=None,
    investment_report=None,
    portfolio_input=None,
    transactions_input=None,
    cash_flows_input=None,
    price_report=None,
    lifecycle_result=None,
):

    output = BytesIO()

    daily_export = daily.copy()
    daily_export.index.name = "Date"
    daily_export = daily_export.reset_index()

    twr_export = pd.DataFrame({
        "Date": twr_result["twr_index"].index,
        "TWR_Index": twr_result["twr_index"].values,
        "Daily_Return": twr_result["daily_returns"].values,
    })

    summary_export = pd.DataFrame(
        list(summary.items()),
        columns=["Metric", "Value"],
    )

    with pd.ExcelWriter(
        output,
        engine="openpyxl",
    ) as writer:

        summary_export.to_excel(
            writer,
            sheet_name="SUMMARY",
            index=False,
        )

        daily_export.to_excel(
            writer,
            sheet_name="DAILY_NAV",
            index=False,
        )

        twr_export.to_excel(
            writer,
            sheet_name="TWR",
            index=False,
        )

        price_history.to_excel(
            writer,
            sheet_name="PRICE_HISTORY",
            index=False,
        )

        if price_report is not None:
            quality_rows = []
            for section, report in (("Portfolio prices", price_report), ("Benchmark prices", price_report.get("benchmark_quality", {}))):
                if not isinstance(report, dict) or not report:
                    continue
                for key in ("status", "market", "currency", "requested_tickers", "downloaded_tickers", "failed_tickers"):
                    if key in report:
                        quality_rows.append({"Section": section, "Metric": key, "Value": str(report.get(key))})
                quality = report.get("quality", {}) or {}
                for key in ("first_date", "last_date", "requested_start_date", "requested_end_date", "missing_tickers", "invalid_dates", "invalid_prices", "duplicate_rows"):
                    if key in quality:
                        quality_rows.append({"Section": section, "Metric": key, "Value": str(quality.get(key))})
                for warning in quality.get("coverage_warnings", []) or []:
                    quality_rows.append({"Section": section, "Metric": "coverage_warning", "Value": str(warning)})
                for ticker, coverage in (quality.get("ticker_coverage", {}) or {}).items():
                    quality_rows.append({"Section": section, "Metric": f"ticker_coverage:{ticker}", "Value": str(coverage)})
            if quality_rows:
                pd.DataFrame(quality_rows).to_excel(writer, sheet_name="PRICE_QUALITY", index=False)

        # Full accounting, transaction, cash-flow and position audit ledgers.
        if lifecycle_result is not None:
            lifecycle_result["daily_accounting"].to_excel(writer, sheet_name="DAILY_ACCOUNTING", index=False)
            lifecycle_result["transaction_ledger"].to_excel(writer, sheet_name="TRANSACTION_LEDGER", index=False)
            lifecycle_result["cash_flow_ledger"].to_excel(writer, sheet_name="CASH_FLOW_LEDGER", index=False)
            lifecycle_result["position_history"].to_excel(writer, sheet_name="POSITION_HISTORY", index=False)
            lifecycle_result["reconciliation"].to_excel(writer, sheet_name="ACCOUNTING_RECON", index=False)

        # Preserve source inputs in the export so portfolio movements can be audited.
        if portfolio_input is not None:
            portfolio_input.to_excel(writer, sheet_name="OPENING_PORTFOLIO", index=False)
        if transactions_input is not None:
            transactions_input.to_excel(writer, sheet_name="TRANSACTIONS", index=False)
        if cash_flows_input is not None:
            cash_flows_input.to_excel(writer, sheet_name="CASH_FLOWS", index=False)

        if ending_positions is not None:
            reconciliation = build_nav_reconciliation(daily, ending_positions)
            reconciliation.to_excel(writer, sheet_name="NAV_RECONCILIATION", index=False)

        if benchmark_table is not None and not benchmark_table.empty:
            benchmark_table.to_excel(writer, sheet_name="BENCHMARK_SUMMARY", index=False)
        if benchmark_results:
            for benchmark_key, result in benchmark_results.items():
                safe_name = ("BM_" + benchmark_key)[:31]
                result["cumulative_returns"].to_excel(writer, sheet_name=safe_name)
                coverage = result["summary"].get("coverage", {})
                pd.DataFrame([{"Metric": k, "Value": str(v)} for k, v in coverage.items()]).to_excel(
                    writer, sheet_name=(safe_name + "_COV")[:31], index=False
                )
        elif benchmark_result is not None:
            benchmark_result["cumulative_returns"].to_excel(writer, sheet_name="BENCHMARK")

        if ending_positions is not None and not ending_positions.empty:
            ending_positions.to_excel(
                writer, sheet_name="ENDING_POSITIONS", index=False
            )

        if investor_profile is not None:
            profile_rows = [
                {"Field": "Profile", "Value": investor_profile.get("profile")},
                {"Field": "Raw Score", "Value": investor_profile.get("raw_score")},
                {"Field": "Adjusted Score", "Value": investor_profile.get("adjusted_score")},
                {"Field": "Methodology", "Value": investor_profile.get("methodology")},
                {"Field": "Disclaimer", "Value": investor_profile.get("disclaimer")},
            ]
            pd.DataFrame(profile_rows).to_excel(
                writer, sheet_name="INVESTOR_PROFILE", index=False
            )
            pd.DataFrame(
                [{"Dimension": k, "Answer": v, "Score": investor_profile.get("dimension_scores", {}).get(k),
                  "Weight": investor_profile.get("weights", {}).get(k)}
                 for k, v in investor_profile.get("answers", {}).items()]
            ).to_excel(writer, sheet_name="PROFILE_DETAILS", index=False)
            pd.DataFrame(
                [{"Type": kind, "Message": message}
                 for kind in ("guardrails", "warnings")
                 for message in investor_profile.get(kind, [])]
            ).to_excel(writer, sheet_name="PROFILE_FLAGS", index=False)

        if investment_report is not None and not investment_report.empty:
            # Keep the complete finding-level report and a compact audit summary.
            investment_report.to_excel(
                writer, sheet_name="INVESTMENT_REPORT", index=False
            )
            report_summary, category_summary = build_investment_report_summary(investment_report)
            report_summary.to_excel(writer, sheet_name="REPORT_SUMMARY", index=False, startrow=0)
            category_summary.to_excel(writer, sheet_name="REPORT_SUMMARY", index=False, startrow=len(report_summary) + 3)

        if risk_result is not None and risk_result.get("status") == "success":
            pd.DataFrame(
                [{k: v for k, v in risk_result.items()
                  if k not in {"portfolio_daily_returns", "correlation_matrix",
                               "covariance_matrix", "individual_volatility",
                               "risk_contribution", "weights", "daily_returns",
                               "portfolio_growth_index"}}]
            ).to_excel(writer, sheet_name="RISK_SUMMARY", index=False)
            risk_result["correlation_matrix"].to_excel(
                writer, sheet_name="RISK_CORRELATION"
            )
            risk_result["risk_contribution"].to_excel(
                writer, sheet_name="RISK_CONTRIBUTION", index=False
            )

    output.seek(0)
    return output


# ---------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------

st.sidebar.header("Analysis Settings")

max_staleness = st.sidebar.number_input(
    "Maximum stale price (calendar days)",
    min_value=0,
    max_value=30,
    value=5,
    step=1,
)

st.sidebar.markdown("**Benchmark standar**")
st.sidebar.caption("IHSG (^JKSE) dan LQ45 (^JKLQ45) diunduh otomatis dari Yahoo Finance. Untuk IDX30 dan Kompas100, gunakan CSV historis dari sumber tepercaya karena simbol feed publik otomatisnya belum terverifikasi pada paket ini.")
benchmark_csv_upload = st.sidebar.file_uploader(
    "CSV historis IDX30 / Kompas100 (opsional)", type=["csv"], key="tsfa_benchmark_csv_upload"
)
st.sidebar.caption("Format CSV: Date,Index,Close. Index: IDX30 atau KOMPAS100. Tanggal YYYY-MM-DD.")
st.sidebar.download_button("Download CSV Template Benchmark", data="Date,Index,Close\n2026-01-02,IDX30,300\n2026-01-02,KOMPAS100,900\n", file_name="TSFA_Benchmark_Template.csv", mime="text/csv")
benchmark_csv_series = {}
if benchmark_csv_upload is not None:
    try:
        benchmark_csv_series = parse_benchmark_csv(benchmark_csv_upload.getvalue())
    except Exception as exc:
        st.sidebar.error(f"CSV benchmark tidak valid: {exc}")

st.sidebar.caption(
    "A price older than this threshold will trigger "
    "a valuation error for an active holding."
)


# ---------------------------------------------------------
# WORKBOOK UPLOAD
# ---------------------------------------------------------

st.header("1. Upload Portfolio Workbook")

uploaded_file = st.file_uploader(
    "Upload Excel workbook from TSFA V1.3",
    type=["xlsx"],
)

if uploaded_file is None:

    st.warning(
        "Upload your portfolio workbook to begin historical analysis."
    )

    st.markdown(
        """
        **Required workbook sheets:**

        - PORTFOLIO
        - TRANSACTIONS
        - CASH_FLOW
        - PRICE_HISTORY
        - ANALYSIS_RESULTS
        """
    )

    st.stop()


# ---------------------------------------------------------
# VALIDATE WORKBOOK
# ---------------------------------------------------------

try:

    workbook_bytes = uploaded_file.getvalue()
    workbook_fingerprint = hashlib.sha256(workbook_bytes).hexdigest()

    # Prevent results from a previously uploaded workbook being shown
    # after the user selects a different portfolio file.
    previous_fingerprint = st.session_state.get("tsfa_workbook_fingerprint")
    if previous_fingerprint != workbook_fingerprint:
        for key in (
            "tsfa_daily",
            "tsfa_twr",
            "tsfa_prices",
            "tsfa_summary",
            "tsfa_price_report",
            "tsfa_benchmark",
            "tsfa_benchmark_warning",
            "tsfa_benchmark_results",
            "tsfa_benchmark_table",
            "tsfa_benchmark_warnings",
            "tsfa_risk",
            "tsfa_ending_positions",
            "tsfa_rebalance_backtest",
        ):
            st.session_state.pop(key, None)

    validation = validate_portfolio_workbook(
        workbook_bytes
    )

    frames, _ = _read_workbook(workbook_bytes)

    portfolio = frames["PORTFOLIO"].copy()
    transactions = frames["TRANSACTIONS"].copy()
    cash_flows = frames["CASH_FLOW"].copy()

    as_of_date = pd.Timestamp(
        validation["as_of_date"]
    ).normalize()

except Exception as exc:

    st.error(f"Workbook validation failed: {exc}")
    st.stop()


st.success("Portfolio workbook successfully validated.")

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Number of Holdings",
    validation["holding_count"],
)

col2.metric(
    "Total Shares",
    f"{validation['total_quantity_shares']:,}",
)

col3.metric(
    "Total Cost Basis",
    f"Rp {validation['total_cost_basis']:,.0f}",
)

col4.metric(
    "Opening Cash",
    f"Rp {validation['opening_cash']:,.0f}",
)

st.write("**Portfolio Tickers:**", ", ".join(validation["tickers"]))
st.write("**Opening Date:**", str(as_of_date.date()))


# ---------------------------------------------------------
# ANALYSIS PERIOD
# ---------------------------------------------------------

st.header("2. Historical Analysis Period")

today = pd.Timestamp.today().normalize()

if as_of_date > today:

    st.error("Opening date tidak boleh berada di masa depan.")
    st.stop()

selected_end_date = st.date_input(
    "Analysis End Date",
    value=today.date(),
    min_value=as_of_date.date(),
    max_value=today.date(),
)

selected_end = pd.Timestamp(
    selected_end_date
).normalize()

analysis_fingerprint = hashlib.sha256(
    f"{workbook_fingerprint}|{selected_end.date()}|{int(max_staleness)}|{hashlib.sha256(benchmark_csv_upload.getvalue()).hexdigest() if benchmark_csv_upload else 'NO_BENCHMARK_CSV'}".encode("utf-8")
).hexdigest()
previous_analysis_fingerprint = st.session_state.get("tsfa_analysis_fingerprint")
if previous_analysis_fingerprint and previous_analysis_fingerprint != analysis_fingerprint:
    for key in (
        "tsfa_daily", "tsfa_twr", "tsfa_prices", "tsfa_summary",
        "tsfa_price_report", "tsfa_benchmark", "tsfa_benchmark_warning",
        "tsfa_benchmark_results", "tsfa_benchmark_table", "tsfa_benchmark_warnings",
        "tsfa_risk", "tsfa_ending_positions",
    ):
        st.session_state.pop(key, None)

if selected_end <= as_of_date:

    st.warning(
        "Tanggal akhir harus setelah Opening Date "
        "agar tersedia minimal dua observasi NAV."
    )

    st.stop()


# ---------------------------------------------------------
# COLLECT TICKERS
# ---------------------------------------------------------

try:

    tickers = collect_required_tickers(
        portfolio=portfolio,
        transactions=transactions,
        market="Indonesia",
    )

except Exception as exc:

    st.error(f"Unable to collect tickers: {exc}")
    st.stop()


st.write("**Tickers to download:**", ", ".join(tickers))


# ---------------------------------------------------------
# RUN HISTORICAL ANALYSIS
# ---------------------------------------------------------

st.header("3. Run Historical Backtesting")

if st.button(
    "Download Prices & Run Portfolio Analysis",
    type="primary",
    use_container_width=True,
):

    with st.spinner(
        "Downloading historical prices and reconstructing portfolio..."
    ):

        try:

            # Download a few calendar days before opening date
            # to obtain a previous closing price when opening
            # date falls on a market holiday.

            download_start = (
                as_of_date - pd.Timedelta(days=7)
            )

            price_history, price_report = (
                download_historical_prices(
                    tickers=tickers,
                    start_date=download_start,
                    end_date=selected_end,
                    market="Indonesia",
                    currency="IDR",
                )
            )

            if price_history.empty:

                raise ValueError(
                    "Yahoo Finance did not return historical prices."
                )

            if price_report["failed_tickers"]:

                raise ValueError(
                    "Some tickers failed to download: "
                    + str(price_report["failed_tickers"])
                )

            # Reconstruct actual daily portfolio.

            lifecycle_result = run_portfolio_lifecycle(
                portfolio=portfolio,
                transactions=transactions,
                cash_flows=cash_flows,
                price_history=price_history,
                max_price_staleness_days=int(max_staleness),
            )
            daily = lifecycle_result["daily"]

            # Calculate daily time-weighted returns.

            twr_result = calculate_time_weighted_returns(
                nav=daily["NAV"],
                external_cash_flows=daily["External_Cash_Flow"],
            )

            summary = calculate_summary(
                daily,
                twr_result,
            )

            # Download provider-backed benchmark series and merge optional CSV series.
            benchmark_series_map = dict(benchmark_csv_series)
            benchmark_quality = {}
            benchmark_warnings = {}
            provider_tickers = [BENCHMARKS[k]["ticker"] for k in ("IHSG", "LQ45")]
            try:
                benchmark_history, benchmark_report = download_historical_prices(
                    tickers=provider_tickers,
                    start_date=download_start,
                    end_date=selected_end,
                    market="Indonesia",
                    currency="IDR",
                )
                benchmark_quality = benchmark_report
                for benchmark_key in ("IHSG", "LQ45"):
                    ticker_symbol = BENCHMARKS[benchmark_key]["ticker"]
                    if ticker_symbol in benchmark_report.get("failed_tickers", {}):
                        benchmark_warnings[benchmark_key] = str(benchmark_report["failed_tickers"][ticker_symbol])
                        continue
                    try:
                        benchmark_series_map[benchmark_key] = extract_benchmark_series(
                            benchmark_history, ticker_symbol
                        )
                    except Exception as exc:
                        benchmark_warnings[benchmark_key] = str(exc)
                if benchmark_history is not None and not benchmark_history.empty:
                    price_history = pd.concat([price_history, benchmark_history], ignore_index=True)
            except Exception as benchmark_exc:
                benchmark_warnings["Yahoo Finance"] = str(benchmark_exc)

            benchmark_results, benchmark_table = compare_all_benchmarks(
                portfolio_twr_index=twr_result["twr_index"],
                benchmark_series=benchmark_series_map,
            )
            benchmark_result = benchmark_results.get("IHSG")
            benchmark_warning = None if benchmark_result is not None else benchmark_warnings.get("IHSG", "Data IHSG tidak tersedia atau tidak memiliki tanggal overlap yang cukup.")
            price_report["benchmark_quality"] = benchmark_quality
            price_report["benchmark_warnings"] = benchmark_warnings

            ending_positions = build_ending_positions(
                portfolio, transactions, price_history
            )
            risk_result = calculate_portfolio_risk(
                price_history=price_history[
                    price_history["Ticker"].isin(tickers)
                ],
                positions=ending_positions[["Ticker", "Market_Value"]],
                min_observations=60,
            ) if not ending_positions.empty else {
                "status": "insufficient_data",
                "message": "Tidak ada posisi saham akhir periode yang dapat dihitung.",
            }

            # Save results in current Streamlit session only.

            st.session_state["tsfa_workbook_fingerprint"] = workbook_fingerprint
            st.session_state["tsfa_analysis_fingerprint"] = analysis_fingerprint
            st.session_state["tsfa_daily"] = daily
            st.session_state["tsfa_lifecycle"] = lifecycle_result
            st.session_state["tsfa_twr"] = twr_result
            st.session_state["tsfa_prices"] = price_history
            st.session_state["tsfa_summary"] = summary
            st.session_state["tsfa_price_report"] = price_report
            st.session_state["tsfa_benchmark"] = benchmark_result
            st.session_state["tsfa_benchmark_results"] = benchmark_results
            st.session_state["tsfa_benchmark_table"] = benchmark_table
            st.session_state["tsfa_benchmark_warning"] = benchmark_warning
            st.session_state["tsfa_benchmark_warnings"] = benchmark_warnings
            st.session_state["tsfa_risk"] = risk_result
            st.session_state["tsfa_ending_positions"] = ending_positions

            st.success("Historical portfolio analysis completed.")

        except Exception as exc:

            st.error(
                f"Historical analysis could not be completed: {exc}"
            )


# ---------------------------------------------------------
# DISPLAY RESULTS
# ---------------------------------------------------------

if "tsfa_daily" in st.session_state:

    daily = st.session_state["tsfa_daily"]
    twr_result = st.session_state["tsfa_twr"]
    price_history = st.session_state["tsfa_prices"]
    summary = st.session_state["tsfa_summary"]
    price_report = st.session_state["tsfa_price_report"]

    st.divider()

    st.header("4. Portfolio Performance")
    st.caption(
        f"Portfolio NAV menghasilkan {summary.get('Return Periods', 0)} return periods selama "
        f"{summary.get('Elapsed Calendar Days', 0)} hari kalender. "
        "Angka ini berbeda dari observasi return harga saham pada bagian Risk Analytics. "
        "CAGR memerlukan minimal 365 hari kalender; volatility dan Sharpe memerlukan minimal 30 return periods portofolio."
    )

    m1, m2, m3 = st.columns(3)

    m1.metric(
        "Ending NAV",
        f"Rp {summary['Ending NAV']:,.0f}",
    )

    m2.metric(
        "Total TWR",
        f"{summary['Total TWR']:.2%}",
    )

    m3.metric(
        "CAGR",
        (
            f"{summary['CAGR']:.2%}"
            if np.isfinite(summary["CAGR"])
            else "N/A"
        ),
    )

    m4, m5, m6 = st.columns(3)

    m4.metric(
        "Annualized Volatility",
        (
            f"{summary['Annualized Volatility']:.2%}"
            if np.isfinite(summary["Annualized Volatility"])
            else "N/A"
        ),
    )

    m5.metric(
        "Sharpe Ratio",
        (
            f"{summary['Sharpe Ratio']:.3f}"
            if np.isfinite(summary["Sharpe Ratio"])
            else "N/A"
        ),
    )

    m6.metric(
        "Maximum Drawdown",
        f"{summary['Maximum Drawdown']:.2%}",
    )

    # NAV chart

    st.subheader("Historical Net Asset Value")

    nav_chart = px.line(
        daily.reset_index(),
        x="Date",
        y="NAV",
        title="Daily Portfolio NAV",
    )

    st.plotly_chart(
        nav_chart,
        use_container_width=True,
    )

    # TWR chart

    st.subheader("Time-Weighted Return Index")

    twr_chart_data = pd.DataFrame({
        "Date": twr_result["twr_index"].index,
        "TWR Index": twr_result["twr_index"].values,
    })

    twr_chart = px.line(
        twr_chart_data,
        x="Date",
        y="TWR Index",
        title="TWR Index (Base = 100)",
    )

    st.plotly_chart(
        twr_chart,
        use_container_width=True,
    )

    # Daily table

    st.subheader("Daily Portfolio Data")

    st.dataframe(
        daily,
        use_container_width=True,
    )

    # Price report

    with st.expander("Historical Price Data Quality"):

        st.write(
            "Download status:",
            price_report["status"],
        )

        st.write(
            "Downloaded tickers:",
            price_report["downloaded_tickers"],
        )

        st.write(
            "Failed tickers (unduhan benar-benar gagal):",
            price_report["failed_tickers"],
        )

        quality = price_report.get("quality", {})
        coverage_warnings = quality.get("coverage_warnings", []) or []
        if coverage_warnings:
            st.warning("Cakupan tanggal belum mencapai batas periode yang diminta. Ini tidak otomatis berarti unduhan gagal; periksa tanggal terakhir tiap ticker.")
            for warning in coverage_warnings:
                st.write("•", warning)
        if price_report.get("failed_tickers"):
            st.error("Sebagian ticker gagal diunduh. Lihat detail error di bawah.")
        st.json(quality)

    # Benchmark comparison
    benchmark_result = st.session_state.get("tsfa_benchmark")
    benchmark_warning = st.session_state.get("tsfa_benchmark_warning")
    # Adaptive investor profile (educational suitability screen)
    st.header("5. Adaptive Investor Profile")
    st.caption("Profil menggabungkan toleransi risiko, kapasitas finansial, tujuan, horizon, likuiditas, dan pengalaman. Isi berdasarkan kondisi investor yang sedang dianalisis.")
    with st.expander("Investor Profile Questionnaire", expanded=False):
        profile_col1, profile_col2 = st.columns(2)
        with profile_col1:
            profile_risk_tolerance = st.selectbox("Risk tolerance", ["Low", "Moderate", "High"], index=1, key="tsfa_profile_tolerance")
            profile_risk_capacity = st.selectbox("Financial risk capacity", ["Low", "Medium", "High"], index=1, key="tsfa_profile_capacity")
            profile_objective = st.selectbox("Primary investment objective", ["Capital Preservation", "Income", "Balanced", "Growth", "Aggressive Growth"], index=2, key="tsfa_profile_objective")
        with profile_col2:
            profile_horizon = st.selectbox("Investment horizon", ["Short (under 3 years)", "Medium (3–7 years)", "Long (over 7 years)"], index=1, key="tsfa_profile_horizon")
            profile_liquidity = st.selectbox("Liquidity needs", ["High (funds may be needed within 1 year)", "Medium (1–3 years)", "Low (not expected within 3 years)"], index=1, key="tsfa_profile_liquidity")
            profile_experience = st.selectbox("Investment experience", ["Beginner", "Intermediate", "Advanced"], index=1, key="tsfa_profile_experience")
        profile_answers = {
            "risk_tolerance": profile_risk_tolerance, "risk_capacity": profile_risk_capacity,
            "objective": profile_objective, "horizon": profile_horizon,
            "liquidity_need": profile_liquidity, "experience": profile_experience,
        }
        profile_result = evaluate_investor_profile(profile_answers)
        st.session_state["tsfa_investor_profile"] = profile_result
        p1, p2 = st.columns(2)
        p1.metric("Investor Profile", profile_result["profile"])
        p2.metric("Adjusted Suitability Score", f"{profile_result['adjusted_score']:.2f} / 3.00")
        if profile_result["guardrails"]:
            st.warning("\n".join(profile_result["guardrails"]))
        if profile_result["warnings"]:
            for profile_warning in profile_result["warnings"]:
                st.warning(profile_warning)
        st.dataframe(pd.DataFrame([{"Dimension": k.replace("_", " ").title(), "Score": v, "Weight": profile_result["weights"][k]} for k, v in profile_result["dimension_scores"].items()]), use_container_width=True, hide_index=True)
        st.caption(profile_result["disclaimer"])

    st.header("6. Benchmark Comparison")
    benchmark_results = st.session_state.get("tsfa_benchmark_results", {})
    benchmark_table = st.session_state.get("tsfa_benchmark_table")
    if benchmark_table is not None:
        st.caption("Setiap indeks dibandingkan dengan TWR portofolio pada tanggal observasi bersama. Data yang tidak tersedia tidak diisi atau diperkirakan.")
        st.dataframe(benchmark_table, use_container_width=True, hide_index=True)
        if benchmark_results:
            chart_data = []
            for key, result in benchmark_results.items():
                curve = result["cumulative_returns"]
                label = BENCHMARKS[key]["name"]
                for date, row in curve.iterrows():
                    chart_data.append({"Date": date, "Series": f"Portfolio vs {label}", "Return": float(row["Portfolio"])})
                    chart_data.append({"Date": date, "Series": label, "Return": float(row["Benchmark"])})
            chart_frame = pd.DataFrame(chart_data)
            st.plotly_chart(px.line(chart_frame, x="Date", y="Return", color="Series", title="Portfolio vs IHSG, LQ45, IDX30 & Kompas100 — Cumulative Return"), use_container_width=True)
        unavailable = benchmark_table.loc[benchmark_table["Status"] != "Available", ["Benchmark", "Status", "Source"]]
        if not unavailable.empty:
            st.warning("Benchmark berstatus Unavailable tidak dihitung sampai data historis valid tersedia.")
            st.dataframe(unavailable, use_container_width=True, hide_index=True)
    else:
        st.warning("Benchmark belum dihitung. Jalankan historical backtesting terlebih dahulu.")

    # Portfolio risk analytics
    st.header("7. Portfolio Risk Analytics")
    st.caption(
        "Risk profile dihitung dari bobot kepemilikan akhir periode yang diterapkan "
        "pada riwayat return saham. Ini bukan rekonstruksi bobot historis harian."
    )
    risk_result = st.session_state.get("tsfa_risk", {})
    ending_positions = st.session_state.get("tsfa_ending_positions")
    if risk_result.get("status") == "success":
        r1, r2, r3 = st.columns(3)
        r1.metric("Annualized Return", f"{risk_result['annualized_return_pct']:.2f}%")
        r2.metric("Annualized Volatility", f"{risk_result['annualized_volatility_pct']:.2f}%")
        r3.metric("Historical Max Drawdown", f"{risk_result['max_drawdown_pct']:.2f}%")
        st.subheader("Risk Contribution by Holding")
        st.dataframe(risk_result["risk_contribution"], use_container_width=True)
        st.subheader("Return Correlation Matrix")
        st.dataframe(risk_result["correlation_matrix"], use_container_width=True)
    else:
        observed = risk_result.get("observations")
        minimum = risk_result.get("minimum_required", 60)
        if observed is not None:
            risk_message = (
                f"Risk analytics belum dapat dihitung: tersedia {int(observed)} "
                f"observasi return harian saham yang lengkap dari harga historis; "
                f"minimal diperlukan {int(minimum)} observasi. "
                "Angka ini berbeda dari return periods portofolio berbasis NAV "
                "pada bagian 4. Perhitungan menggunakan bobot kepemilikan akhir "
                "periode, bukan bobot historis harian."
            )
        else:
            risk_message = (
                str(risk_result.get("message", "Data belum mencukupi."))
                + " Risk Analytics memakai return harga saham harian yang lengkap. "
                "Jumlah observasinya dapat berbeda dari return periods NAV pada bagian 4."
            )
        st.info(risk_message)
    if ending_positions is not None and not ending_positions.empty:
        with st.expander("Ending Holdings Used for Risk Calculation"):
            st.dataframe(ending_positions, use_container_width=True)

    # Stress testing and sector exposure
    st.header("8. Stress Testing & Sector Exposure")
    if ending_positions is not None and not ending_positions.empty:
        cash_balance = float(daily["Cash"].iloc[-1]) if "Cash" in daily.columns else 0.0
        stress_col, sector_col = st.columns(2)
        with stress_col:
            st.subheader("Market-wide Stress Scenarios")
            try:
                stress = calculate_market_stress(
                    ending_positions[["Ticker", "Market_Value"]],
                    cash_balance=cash_balance,
                    market_shocks=[-5, -10, -15, -20, -30],
                )
                st.dataframe(stress["scenario_results"], use_container_width=True)
                st.caption("Simulasi shock seragam; bukan prediksi atau estimasi probabilitas.")
            except Exception as exc:
                st.warning(f"Stress test belum tersedia: {exc}")
        with sector_col:
            st.subheader("Sector Exposure")
            try:
                sector_result = calculate_sector_exposure(
                    ending_positions[["Ticker", "Market_Value"]]
                )
                st.dataframe(sector_result["sector_exposure"], use_container_width=True)
                if sector_result["unclassified_tickers"]:
                    st.warning("Ticker belum memiliki klasifikasi sektor: " + ", ".join(sector_result["unclassified_tickers"]))
            except Exception as exc:
                st.warning(f"Sector exposure belum tersedia: {exc}")

        st.subheader("Sector-specific Stress")
        try:
            sector_result = calculate_sector_exposure(ending_positions[["Ticker", "Market_Value"]])
            sector_names = sector_result["sector_exposure"]["Sector"].tolist()
            sector_shocks = {name: -15.0 for name in sector_names}
            sector_stress = calculate_sector_stress(
                ending_positions[["Ticker", "Market_Value"]],
                sector_shocks=sector_shocks,
                cash_balance=cash_balance,
            )
            st.dataframe(sector_stress["sector_stress"], use_container_width=True)
            st.caption("Shock default -15% per sektor; ubah asumsi di kode atau tahap konfigurasi berikutnya.")
        except Exception as exc:
            st.info(f"Sector stress belum dapat dihitung: {exc}")

        # Rebalancing plan
        st.header("9. Portfolio Rebalancing Planner")
        st.caption("Target bobot awal dibagi rata. Anda dapat mengubah bobot; total harus 100%. Estimasi jumlah saham belum dibulatkan ke lot dan belum memasukkan biaya transaksi/pajak.")
        try:
            rebalance_base = ending_positions[["Ticker", "Market_Value", "Latest_Price"]].copy()
            n_assets = len(rebalance_base)
            target_df = pd.DataFrame({
                "Ticker": rebalance_base["Ticker"],
                "Target_Weight_Pct": [100.0 / n_assets] * n_assets,
            })
            edited_targets = st.data_editor(
                target_df, use_container_width=True, hide_index=True,
                column_config={"Target_Weight_Pct": st.column_config.NumberColumn("Target Weight (%)", min_value=0.0, max_value=100.0, step=0.5)},
                key=f"tsfa_v14_target_weights_{st.session_state.get('tsfa_workbook_fingerprint', 'new')[:8]}",
            )
            rebalance_plan = calculate_rebalance_plan(
                rebalance_base, float(daily["NAV"].iloc[-1]), edited_targets
            )
            st.dataframe(rebalance_plan, use_container_width=True)
            buy_value = float(rebalance_plan.loc[rebalance_plan["Action"] == "BUY", "Trade_Value"].sum())
            sell_value = float(-rebalance_plan.loc[rebalance_plan["Action"] == "SELL", "Trade_Value"].sum())
            q1, q2 = st.columns(2)
            q1.metric("Estimated BUY", f"Rp {buy_value:,.0f}")
            q2.metric("Estimated SELL", f"Rp {sell_value:,.0f}")
            if st.button("Run Historical Rebalancing Backtest", key="tsfa_run_rebalance"):
                price_matrix = build_price_matrix(price_history, rebalance_base["Ticker"].tolist())
                target_weights = dict(zip(edited_targets["Ticker"], edited_targets["Target_Weight_Pct"] / 100.0))
                bt = run_rebalanced_backtest(
                    price_data=price_matrix, target_weights=target_weights,
                    initial_capital=float(daily["NAV"].iloc[0]),
                    rebalancing="first_trading_day",
                )
                st.session_state["tsfa_rebalance_backtest"] = bt
            bt = st.session_state.get("tsfa_rebalance_backtest")
            if bt:
                st.json(bt["summary"])
                st.dataframe(bt["transactions"], use_container_width=True)
        except Exception as exc:
            st.warning(f"Rebalancing planner belum tersedia: {exc}")
    else:
        st.info("Stress testing, sector exposure, dan rebalancing membutuhkan ending holdings yang valid.")

    st.header("10. Performance Attribution — Data Requirement")
    st.info("Engine Brinson-Fachler tersedia di proyek, tetapi attribution belum ditampilkan karena workbook dan feed harga saat ini belum menyediakan bobot serta return benchmark per sektor. Menggunakan IHSG saja tidak cukup untuk menghasilkan attribution sektoral yang valid.")

    # Investment Intelligence Report
    st.header("11. Investment Intelligence Report")
    investor_profile_for_report = st.session_state.get("tsfa_investor_profile")
    investment_report = build_investment_report(
        summary=summary,
        benchmark_result=benchmark_result,
        risk_result=risk_result,
        ending_positions=ending_positions,
        investor_profile=investor_profile_for_report,
        price_report=price_report,
    )
    multi_benchmark_table = st.session_state.get("tsfa_benchmark_table")
    if multi_benchmark_table is not None and not multi_benchmark_table.empty:
        extra_rows = []
        for _, bm_row in multi_benchmark_table.iterrows():
            bm_name = str(bm_row.get("Benchmark", "Benchmark"))
            bm_status = str(bm_row.get("Status", "Unavailable"))
            if bm_status == "Available":
                extra_rows.append({"Category": "Benchmark", "Finding": f"{bm_name} total return", "Status": "Available", "Detail": f"{float(bm_row['Total Return']):.2%}"})
                active_value = bm_row.get("Active Return")
                active_ok = pd.notna(active_value) and np.isfinite(float(active_value))
                extra_rows.append({"Category": "Benchmark", "Finding": f"Active return vs {bm_name}", "Status": "Available" if active_ok else "Unavailable", "Detail": f"{float(active_value):.2%}" if active_ok else "Requires at least 365 calendar days for both series."})
            else:
                extra_rows.append({"Category": "Benchmark", "Finding": f"{bm_name} data availability", "Status": "Unavailable", "Detail": bm_status})
        if extra_rows:
            investment_report = pd.concat([investment_report, pd.DataFrame(extra_rows)], ignore_index=True)
    status_counts = investment_report["Status"].value_counts()
    attention_count = int(status_counts.get("Attention", 0))
    unavailable_count = int(status_counts.get("Unavailable", 0))
    available_count = int(status_counts.get("Available", 0))
    information_count = int(status_counts.get("Information", 0) + status_counts.get("Clear", 0))
    report_cols = st.columns(4)
    report_cols[0].metric("Items requiring attention", attention_count)
    report_cols[1].metric("Unavailable metrics", unavailable_count)
    report_cols[2].metric("Available findings", available_count)
    report_cols[3].metric("Information / clear", information_count)
    st.caption(
        "Unavailable berarti data atau panjang periode belum memenuhi syarat perhitungan; "
        "bukan otomatis kesalahan portofolio. Attention menunjukkan hal yang perlu ditinjau, "
        "misalnya perbedaan tanggal cakupan harga."
    )
    with st.expander("Lihat rincian lengkap Investment Intelligence Report", expanded=True):
        report_filter = st.multiselect(
            "Filter status temuan",
            options=["Attention", "Unavailable", "Available", "Information", "Clear"],
            default=["Attention", "Unavailable", "Available", "Information", "Clear"],
            key="tsfa_v14_report_status_filter",
        )
        visible_report = investment_report[investment_report["Status"].isin(report_filter)].copy()
        st.dataframe(visible_report, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Investment Report (CSV)",
            data=investment_report.to_csv(index=False).encode("utf-8-sig"),
            file_name="TSFA_V1_4_Investment_Report.csv",
            mime="text/csv",
            key="tsfa_v14_report_csv",
        )
    st.caption("Laporan bersifat deskriptif berdasarkan data yang diproses; bukan rekomendasi beli/jual atau penilaian kesesuaian OJK.")

    # Portfolio lifecycle audit trail
    lifecycle = st.session_state.get("tsfa_lifecycle")
    if lifecycle is not None:
        st.header("12. Portfolio Accounting & Audit Trail")
        recon = lifecycle["reconciliation"]
        st.dataframe(recon, use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Transaction ledger — moving weighted-average cost")
            st.dataframe(lifecycle["transaction_ledger"], use_container_width=True, hide_index=True)
        with c2:
            st.caption("Cash-flow ledger — external and internal cash movements")
            st.dataframe(lifecycle["cash_flow_ledger"], use_container_width=True, hide_index=True)
        st.caption("Daily position history: quantity, average cost, market value, and unrealized P&L")
        st.dataframe(lifecycle["position_history"], use_container_width=True, hide_index=True)

    # Excel export

    st.header("13. Export Analysis")

    excel_file = build_excel_export(
        daily=daily,
        twr_result=twr_result,
        price_history=price_history,
        summary=summary,
        benchmark_result=benchmark_result,
        benchmark_results=st.session_state.get("tsfa_benchmark_results"),
        benchmark_table=st.session_state.get("tsfa_benchmark_table"),
        risk_result=risk_result,
        ending_positions=ending_positions,
        investor_profile=st.session_state.get("tsfa_investor_profile"),
        investment_report=investment_report,
        portfolio_input=portfolio,
        transactions_input=transactions,
        cash_flows_input=cash_flows,
        price_report=st.session_state.get("tsfa_price_report"),
        lifecycle_result=st.session_state.get("tsfa_lifecycle"),
    )

    st.download_button(
        label="Download Historical Analysis (Excel)",
        data=excel_file,
        file_name="TSFA_V1_4_Historical_Analysis.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        use_container_width=True,
    )

st.divider()

st.caption(
    "TSFA V1.4 Prototype | Historical portfolio reconstruction "
    "| Indonesia / IDR"
)
