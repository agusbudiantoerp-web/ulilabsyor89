"""Downloadable Excel/PDF research packs for portfolio and strategy results."""
from __future__ import annotations

from io import BytesIO
from datetime import datetime, timezone
import pandas as pd


def build_excel_report(
    portfolio: pd.DataFrame | None = None,
    metrics: dict | None = None,
    history: pd.DataFrame | None = None,
) -> bytes:
    output = BytesIO()

    def excel_safe(frame: pd.DataFrame) -> pd.DataFrame:
        safe = frame.copy()
        for column in safe.columns:
            safe[column] = safe[column].map(
                lambda value: str(value) if isinstance(value, (dict, list, tuple, set)) else value
            )
        return safe

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if portfolio is not None and not portfolio.empty:
            excel_safe(portfolio).to_excel(writer, sheet_name="Portfolio", index=False)
        if history is not None and not history.empty:
            excel_safe(history).to_excel(writer, sheet_name="Signal History", index=False)
        metric_rows = [{"Metric": key, "Value": value} for key, value in (metrics or {}).items()
                       if isinstance(value, (str, int, float, bool)) or value is None]
        pd.DataFrame(metric_rows or [{"Metric": "Status", "Value": "No summary metrics supplied"}]).to_excel(
            writer, sheet_name="Summary", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                letter = column[0].column_letter
                width = min(42, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
                sheet.column_dimensions[letter].width = width
    return output.getvalue()


def build_pdf_report(title: str, metrics: dict, notes: list[str] | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]),
             Paragraph("Generated " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), styles["Normal"]),
             Spacer(1, 8*mm)]
    rows = [["Metric", "Value"]]
    for key, value in metrics.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            rows.append([str(key), str(value)])
    table = Table(rows, repeatRows=1, colWidths=[65*mm, 105*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#243746")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), 0.35, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
    ]))
    story.append(table)
    if notes:
        story.extend([Spacer(1, 8*mm), Paragraph("Method and limitations", styles["Heading2"])])
        story.extend(Paragraph(str(note), styles["BodyText"]) for note in notes)
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("Research support only. Not investment advice. No broker orders are placed.", styles["Italic"]))
    doc.build(story)
    return output.getvalue()
