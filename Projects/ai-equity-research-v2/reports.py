
"""Excel and PDF report builders for AI Equity Research."""

from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd

from report_export_utils import safe_spreadsheet_text
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)


def _unique_excel_sheet_name(workbook, proposed: str) -> str:
    """Return a valid, case-insensitively unique Excel worksheet title."""
    invalid = set('[]:*?/\\\\')
    cleaned = "".join("_" if char in invalid else char for char in str(proposed))
    cleaned = "".join(char for char in cleaned if ord(char) >= 32)
    cleaned = cleaned.strip().strip("'") or "Scenario"
    base = cleaned[:31]
    existing = {name.casefold() for name in workbook.sheetnames}
    candidate = base
    suffix = 2
    while candidate.casefold() in existing:
        ending = f" ({suffix})"
        candidate = base[:31 - len(ending)] + ending
        suffix += 1
    return candidate

def make_excel_report(data: dict, dcf: dict | None = None, multistage_dcf: dict | None = None, scenario_result: dict | None = None) -> bytes:
    out = BytesIO()

    ratios = pd.DataFrame([
        {"Metric": key, "Value": value}
        for key, value in data["ratios"].items()
    ])

    snapshot = pd.DataFrame([{
        "Ticker": data["ticker"],
        "Company": data["company"],
        "Sector": data["sector"],
        "Industry": data["industry"],
        "Quote currency": data["currency"],
        "Financial currency": data.get("financial_currency"),
        "As of UTC": data["as_of"],
        "Latest price date": data.get("latest_price_date"),
        "Income statement period": data.get("latest_financial_period"),
        "Balance sheet period": data.get("latest_balance_period"),
        "Cash flow period": data.get("latest_cashflow_period"),
        "Latest price": data["price"],
        "Daily change %": data["change_pct"],
        "Period return %": data["period_return_pct"],
        "Trend": data["trend"],
        "RSI 14": data["rsi14"],
        "Annualized volatility %": data["annualized_volatility_pct"],
        "Data source": data["data_source"],
        "Data quality note": data.get("data_quality_note")
    }])

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        snapshot.to_excel(writer, sheet_name="Summary", index=False)
        ratios.to_excel(writer, sheet_name="Fundamentals", index=False)
        data["history"].to_excel(writer, sheet_name="Price History", index=False)

        warnings = data.get("data_quality_warnings", [])
        pd.DataFrame({
            "Data quality warnings": warnings or [
                "No automatic warning; manual source verification still required."
            ]
        }).to_excel(writer, sheet_name="Data Quality", index=False)

        if dcf and dcf.get("available"):
            dcf["forecast"].to_excel(
                writer,
                sheet_name="DCF Forecast",
                index=False
            )

            dcf_rows = [
                {"Metric": "Enterprise value", "Value": dcf["enterprise_value"]},
                {"Metric": "PV forecast", "Value": dcf["pv_forecast"]},
                {"Metric": "Terminal value", "Value": dcf["terminal_value"]},
                {"Metric": "PV terminal value", "Value": dcf["pv_terminal_value"]},
                {"Metric": "Total debt", "Value": dcf["total_debt"]},
                {"Metric": "Cash and equivalents", "Value": dcf["cash"]},
                {"Metric": "Net debt", "Value": dcf["net_debt"]},
                {"Metric": "Equity value", "Value": dcf["equity_value"]},
                {"Metric": "Shares outstanding", "Value": dcf["shares_outstanding"]},
                {
                    "Metric": "Intrinsic value per share",
                    "Value": dcf["intrinsic_value_per_share"]
                },
                {"Metric": "Financial currency", "Value": dcf["currency"]},
                {"Metric": "Display currency", "Value": dcf["display_currency"]},
                {"Metric": "FX conversion applied", "Value": dcf["fx_conversion_applied"]},
                {"Metric": "FX rate", "Value": dcf["fx_rate"]},
                {"Metric": "FX reference date", "Value": dcf["fx_source_date"]}
            ]

            dcf_rows += [
                {"Metric": key, "Value": value}
                for key, value in dcf["assumptions"].items()
            ]

            pd.DataFrame(dcf_rows).to_excel(
                writer,
                sheet_name="DCF Valuation",
                index=False
            )

            dcf_notes = [dcf["warning"]] + list(dcf.get("model_warnings") or [])
            pd.DataFrame({"DCF notes": dcf_notes}).to_excel(
                writer, sheet_name="DCF Notes", index=False
            )

        else:
            reason = dcf.get("reason", "DCF not run") if dcf else "DCF not run"
            pd.DataFrame({
                "DCF status": [reason]
            }).to_excel(writer, sheet_name="DCF Valuation", index=False)

        if multistage_dcf and multistage_dcf.get("available"):
            pd.DataFrame(multistage_dcf.get("forecast", [])).to_excel(
                writer, sheet_name="MultiStage Forecast", index=False
            )
            ms_rows = [
                {"Metric": "Enterprise value", "Value": multistage_dcf.get("enterprise_value")},
                {"Metric": "Equity value", "Value": multistage_dcf.get("equity_value")},
                {"Metric": "Net debt", "Value": multistage_dcf.get("net_debt")},
                {"Metric": "PV forecast FCFF", "Value": multistage_dcf.get("pv_fcff")},
                {"Metric": "PV terminal value", "Value": multistage_dcf.get("pv_terminal")},
                {"Metric": "Terminal value", "Value": multistage_dcf.get("terminal_value")},
                {"Metric": "Intrinsic value per share", "Value": multistage_dcf.get("intrinsic_value_per_share")},
                {"Metric": "Quote currency", "Value": multistage_dcf.get("quote_currency")},
                {"Metric": "Financial currency", "Value": multistage_dcf.get("financial_currency")},
                {"Metric": "FX rate applied", "Value": multistage_dcf.get("fx_rate_applied")},
                {"Metric": "FX reference date", "Value": multistage_dcf.get("fx_source_date")},
                {"Metric": "EBITDA source", "Value": multistage_dcf.get("ebitda_source")},
                {"Metric": "EBITDA used", "Value": multistage_dcf.get("ebitda_used")},
            ]
            ms_rows.extend(
                {"Metric": "Assumption: " + str(key), "Value": value}
                for key, value in (multistage_dcf.get("assumptions") or {}).items()
            )
            pd.DataFrame(ms_rows).to_excel(writer, sheet_name="MultiStage Valuation", index=False)
            ms_warnings = list(multistage_dcf.get("warnings") or []) + list(multistage_dcf.get("data_quality_warnings") or []) + list(multistage_dcf.get("model_warnings") or [])
            pd.DataFrame({"Review notes": ms_warnings or ["No model warning returned; independent source verification is still required."]}).to_excel(
                writer, sheet_name="Valuation Review", index=False
            )

        if scenario_result and scenario_result.get("available"):
            scenario_rows = []
            for name, result in (scenario_result.get("results") or {}).items():
                scenario_rows.append({
                    "Scenario": name,
                    "Status": "Available" if result.get("available") else "Not available",
                    "Intrinsic value per share": result.get("intrinsic_value_per_share"),
                    "Upside / Downside %": result.get("upside_downside_pct"),
                    "Enterprise value": result.get("enterprise_value"),
                    "Equity value": result.get("equity_value"),
                    "PV terminal / EV %": result.get("terminal_value_share_pct"),
                    "Model warnings": " | ".join(result.get("model_warnings") or []),
                    "Reason": result.get("reason"),
                })
                if result.get("forecast"):
                    sheet_name = _unique_excel_sheet_name(writer.book, str(name)[:20] + " Forecast")
                    pd.DataFrame(result["forecast"]).to_excel(
                        writer, sheet_name=sheet_name, index=False
                    )
            if scenario_rows:
                pd.DataFrame(scenario_rows).to_excel(writer, sheet_name="Bear Base Bull", index=False)
            sensitivity = scenario_result.get("sensitivity") or {}
            sensitivity_rows = []
            for row in sensitivity.get("sensitivity", []):
                for index, cell in enumerate(row.get("values", [])):
                    growth_values = sensitivity.get("terminal_growth_values", [])
                    sensitivity_rows.append({
                        "WACC": row.get("wacc"),
                        "Terminal growth": growth_values[index] if index < len(growth_values) else None,
                        "Available": cell.get("available"),
                        "Value per share": cell.get("value_per_share"),
                        "Equity value": cell.get("equity_value"),
                        "Reason": cell.get("reason"),
                    })
            if sensitivity_rows:
                pd.DataFrame(sensitivity_rows).to_excel(writer, sheet_name="Scenario Sensitivity", index=False)

            operating = scenario_result.get("operating_sensitivity") or {}
            operating_rows = []
            for matrix_row in operating.get("sensitivity", []):
                growth_values = operating.get("revenue_growth_values", [])
                for index, cell in enumerate(matrix_row.get("values", [])):
                    operating_rows.append({
                        "EBITDA margin": matrix_row.get("ebitda_margin"),
                        "Revenue growth": growth_values[index] if index < len(growth_values) else cell.get("revenue_growth"),
                        "Available": cell.get("available"),
                        "Value per share": cell.get("value_per_share"),
                        "Equity value": cell.get("equity_value"),
                        "Upside / Downside %": cell.get("upside_downside_pct"),
                        "Reason": cell.get("reason"),
                    })
            if operating_rows:
                pd.DataFrame(operating_rows).to_excel(
                    writer, sheet_name="Operating Sensitivity", index=False
                )

            assumptions_rows = []
            for scenario_name, scenario_data in (scenario_result.get("assumptions") or {}).items():
                for key, value in scenario_data.items():
                    assumptions_rows.append({
                        "Scenario": scenario_name,
                        "Assumption": key,
                        "Value": value,
                    })
            if assumptions_rows:
                pd.DataFrame(assumptions_rows).to_excel(
                    writer, sheet_name="Scenario Assumptions", index=False
                )

            context = scenario_result.get("research_context") or {}
            pd.DataFrame([
                {"Section": "Catalysts", "Analyst notes": context.get("catalysts") or "Not supplied"},
                {"Section": "Risks", "Analyst notes": context.get("risks") or "Not supplied"},
                {"Section": "Disclosure", "Analyst notes": context.get("analyst_note") or "Manual analyst input"},
            ]).to_excel(writer, sheet_name="Catalysts & Risks", index=False)

            source = scenario_result.get("source_metadata") or {}
            pd.DataFrame(
                [{"Field": key, "Value": value} for key, value in source.items()]
            ).to_excel(writer, sheet_name="Sources & Dates", index=False)

        for ws in writer.book.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        # Treat untrusted provider/analyst text as text, never as an Excel formula.
                        cell.value = safe_spreadsheet_text(cell.value)
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions

            for col in ws.columns:
                letter = col[0].column_letter
                max_len = max(
                    (len(str(cell.value)) if cell.value is not None else 0)
                    for cell in col
                )
                ws.column_dimensions[letter].width = min(
                    max(max_len + 2, 12),
                    42
                )

    return out.getvalue()


def make_pdf_report(data: dict, dcf: dict | None = None, multistage_dcf: dict | None = None, scenario_result: dict | None = None) -> bytes:
    out = BytesIO()

    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        rightMargin=38,
        leftMargin=38,
        topMargin=38,
        bottomMargin=38
    )

    styles = getSampleStyleSheet()

    company = escape(str(data["company"]))
    ticker = escape(str(data["ticker"]))

    story = [
        Paragraph("AI Equity Research Report", styles["Title"]),
        Spacer(1, 8),
        Paragraph(f"{company} ({ticker})", styles["Heading2"]),
        Paragraph(
            f"Sector: {escape(str(data['sector']))} | "
            f"Industry: {escape(str(data['industry']))} | "
            f"Quote currency: {escape(str(data['currency']))} | "
            f"Financial currency: {escape(str(data.get('financial_currency', 'N/A')))}",
            styles["Normal"]
        ),
        Paragraph(
            f"Generated (UTC): {escape(str(data['as_of']))}",
            styles["Normal"]
        ),
        Paragraph(
            f"Price date: {escape(str(data.get('latest_price_date', 'N/A')))} | "
            f"Income statement: {escape(str(data.get('latest_financial_period', 'N/A')))} | "
            f"Balance sheet: {escape(str(data.get('latest_balance_period', 'N/A')))} | "
            f"Cash flow: {escape(str(data.get('latest_cashflow_period', 'N/A')))}",
            styles["Normal"]
        ),
        Spacer(1, 14)
    ]

    rows = [
        ["Metric", "Value"],
        ["Latest price", str(data.get("price")) + " " + str(data.get("currency"))],
        ["Daily change (%)", str(data.get("change_pct"))],
        ["Period return (%)", str(data.get("period_return_pct"))],
        ["Trend", str(data.get("trend"))],
        ["RSI 14", str(data.get("rsi14"))],
        ["Annualized volatility (%)", str(data.get("annualized_volatility_pct"))]
    ]

    table = Table(rows, colWidths=[210, 250])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163447")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .4, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 6)
    ]))

    story += [
        table,
        Spacer(1, 14),
        Paragraph("Fundamental data", styles["Heading2"])
    ]

    fundamental_rows = [["Metric", "Value"]] + [
        [str(key), "N/A" if value is None else str(value)]
        for key, value in data["ratios"].items()
    ]

    fundamental_table = Table(
        fundamental_rows,
        colWidths=[210, 250],
        repeatRows=1
    )

    fundamental_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163447")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .3, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 4)
    ]))

    story += [
        fundamental_table,
        Spacer(1, 14),
        Paragraph("Data quality checks", styles["Heading2"])
    ]

    warnings = data.get("data_quality_warnings", []) or [
        "No automatic warning; manual source verification is still required."
    ]

    for warning in warnings:
        story.append(
            Paragraph("• " + escape(str(warning)), styles["BodyText"])
        )

    story.append(Spacer(1, 10))

    if dcf and dcf.get("available"):
        dcf_rows = [
            ["DCF metric", "Value"],
            ["Enterprise value", f"{dcf['enterprise_value']:,.2f} {dcf['currency']}"],
            ["PV forecast", f"{dcf['pv_forecast']:,.2f} {dcf['currency']}"],
            ["PV terminal value", f"{dcf['pv_terminal_value']:,.2f} {dcf['currency']}"],
            ["Total debt", f"{dcf['total_debt']:,.2f} {dcf['currency']}"],
            ["Cash and equivalents", f"{dcf['cash']:,.2f} {dcf['currency']}"],
            ["Net debt", f"{dcf['net_debt']:,.2f} {dcf['currency']}"],
            ["Equity value", f"{dcf['equity_value']:,.2f} {dcf['currency']}"],
            ["Shares outstanding", f"{dcf['shares_outstanding']:,.0f}"],
            [
                "Intrinsic value per share",
                f"{dcf['intrinsic_value_per_share']:,.2f} {dcf['display_currency']}"
            ]
        ]

        dcf_table = Table(dcf_rows, colWidths=[210, 250], repeatRows=1)
        dcf_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163447")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), .4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("PADDING", (0, 0), (-1, -1), 5)
        ]))

        story += [
            Paragraph("DCF Valuation", styles["Heading2"]),
            dcf_table,
            Spacer(1, 8)
        ]

        if dcf.get("fx_conversion_applied"):
            fx_note = (
                f"FX conversion: {dcf['currency']} to {dcf['display_currency']} | "
                f"Rate: {dcf['fx_rate']:,.2f} | "
                f"Reference date: {dcf.get('fx_source_date') or 'Not specified'}"
            )
            story.append(Paragraph(escape(fx_note), styles["BodyText"]))

        story += [
            Spacer(1, 6),
            Paragraph(escape(dcf["warning"]), styles["BodyText"]),
            *[Paragraph("Review: " + escape(str(item)), styles["BodyText"]) for item in (dcf.get("model_warnings") or [])],
            Spacer(1, 10)
        ]

    else:
        reason = dcf.get("reason", "DCF not run") if dcf else "DCF not run"

        story += [
            Paragraph("DCF not presented", styles["Heading2"]),
            Paragraph(escape(reason), styles["BodyText"]),
            Spacer(1, 10)
        ]

    if multistage_dcf and multistage_dcf.get("available"):
        story += [
            Paragraph("Multi-Stage DCF Valuation", styles["Heading2"]),
        ]
        ms_rows = [["Metric", "Value"]]
        for key in ("enterprise_value", "equity_value", "net_debt", "pv_fcff",
                    "pv_terminal", "intrinsic_value_per_share", "financial_currency",
                    "quote_currency", "fx_rate_applied", "fx_source_date", "ebitda_source"):
            ms_rows.append([key.replace("_", " ").title(), str(multistage_dcf.get(key))])
        ms_table = Table(ms_rows, colWidths=[210, 250], repeatRows=1)
        ms_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163447")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), .3, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story += [ms_table, Spacer(1, 8)]
        for warning in list(multistage_dcf.get("warnings") or []) + list(multistage_dcf.get("data_quality_warnings") or []) + list(multistage_dcf.get("model_warnings") or []):
            story.append(Paragraph("Review: " + escape(str(warning)), styles["BodyText"]))

    if scenario_result and scenario_result.get("available"):
        story.append(Paragraph("Bear / Base / Bull Scenario Analysis", styles["Heading2"]))
        scenario_rows = [["Scenario", "Status", "Value / Share", "Upside / Downside"]]
        for name, result in (scenario_result.get("results") or {}).items():
            scenario_rows.append([
                str(name),
                "Available" if result.get("available") else "N/M",
                str(result.get("intrinsic_value_per_share")),
                str(result.get("upside_downside_pct")),
            ])
            for warning in result.get("model_warnings") or []:
                story.append(Paragraph(
                    f"Review ({escape(str(name))}): {escape(str(warning))}",
                    styles["BodyText"],
                ))
        scenario_table = Table(scenario_rows, colWidths=[90, 65, 145, 160], repeatRows=1)
        scenario_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163447")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), .3, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story += [scenario_table, Spacer(1, 8)]

        operating = scenario_result.get("operating_sensitivity") or {}
        operating_growth = operating.get("revenue_growth_values", [])
        operating_rows = [["EBITDA margin"] + [f"Revenue growth {float(value):.1%}" for value in operating_growth]]
        for matrix_row in operating.get("sensitivity", []):
            cells = [f"{float(matrix_row.get('ebitda_margin')):.1%}"]
            for cell in matrix_row.get("values", []):
                value = cell.get("value_per_share")
                cells.append(
                    f"{float(value):,.2f}" if cell.get("available") and value is not None else "N/M"
                )
            operating_rows.append(cells)
        if len(operating_rows) > 1:
            growth_count = max(1, len(operating_growth))
            column_width = 390.0 / growth_count
            operating_table = Table(
                operating_rows,
                colWidths=[70.0] + [column_width] * growth_count,
                repeatRows=1,
            )
            operating_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163447")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), .3, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 6),
                ("PADDING", (0, 0), (-1, -1), 3),
            ]))
            quote_currency = (scenario_result.get("financials") or {}).get("quote_currency", "quote currency")
            story += [
                Paragraph(
                    f"Operating assumption sensitivity (value per share, {escape(str(quote_currency))})",
                    styles["Heading3"],
                ),
                operating_table,
                Spacer(1, 8),
            ]

        assumption_rows = [["Scenario", "Assumption", "Value"]]
        for scenario_name, scenario_data in (scenario_result.get("assumptions") or {}).items():
            for key, value in scenario_data.items():
                assumption_rows.append([str(scenario_name), str(key), str(value)])
        if len(assumption_rows) > 1:
            assumption_table = Table(assumption_rows, colWidths=[90, 190, 180], repeatRows=1)
            assumption_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163447")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), .3, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("PADDING", (0, 0), (-1, -1), 3),
            ]))
            story += [Paragraph("Scenario assumptions", styles["Heading3"]), assumption_table, Spacer(1, 8)]

        context = scenario_result.get("research_context") or {}
        source = scenario_result.get("source_metadata") or {}
        story.append(Paragraph("Analyst catalysts and risks", styles["Heading3"]))
        for label, value in (
            ("Catalysts", context.get("catalysts") or "Not supplied by analyst."),
            ("Risks", context.get("risks") or "Not supplied by analyst."),
            ("Disclosure", context.get("analyst_note") or "Manual analyst input."),
        ):
            story.append(Paragraph(f"<b>{escape(label)}:</b> {escape(str(value))}", styles["BodyText"]))
        story.append(Paragraph("Source and reporting dates", styles["Heading3"]))
        for key, value in source.items():
            story.append(Paragraph(f"<b>{escape(str(key))}:</b> {escape(str(value))}", styles["BodyText"]))
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "Scenario assumptions and sensitivity are assumption-driven. "
            "Review the accompanying Excel workbook for detailed assumptions and forecasts.",
            styles["BodyText"],
        ))

    story += [
        Paragraph("Important limitations", styles["Heading2"]),
        Paragraph(escape(str(data["disclaimer"])), styles["BodyText"]),
        Paragraph(
            "This report is generated from third-party market data and automated "
            "calculations. Verify source data, accounting periods, units, corporate "
            "actions and assumptions independently. It is not a recommendation "
            "to buy or sell securities.",
            styles["BodyText"]
        )
    ]

    doc.build(story)
    return out.getvalue()
