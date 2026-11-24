"""Downloadable Excel/PDF research packs for portfolio and strategy results."""
from __future__ import annotations

from io import BytesIO
from datetime import datetime, timezone
import pandas as pd


def build_excel_report(
    portfolio: pd.DataFrame | None = None,
    metrics: dict | None = None,
    history: pd.DataFrame | None = None,
    extra_sheets: dict[str, pd.DataFrame] | None = None,
) -> bytes:
    output = BytesIO()

    def safe_excel_cell(value):
        if isinstance(value, (dict, list, tuple, set)):
            value = str(value)
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            # Prevent untrusted ticker/provider text from being interpreted as a formula.
            return "'" + value
        return value

    def excel_safe(frame: pd.DataFrame) -> pd.DataFrame:
        safe = frame.copy()
        safe.columns = [safe_excel_cell(column) for column in safe.columns]
        for column in safe.columns:
            safe[column] = safe[column].map(safe_excel_cell)
        return safe

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if portfolio is not None and not portfolio.empty:
            excel_safe(portfolio).to_excel(writer, sheet_name="Portfolio", index=False)
        if history is not None and not history.empty:
            excel_safe(history).to_excel(writer, sheet_name="Signal History", index=False)
        metric_rows = [{"Metric": key, "Value": value} for key, value in (metrics or {}).items()
                       if isinstance(value, (str, int, float, bool)) or value is None]
        excel_safe(pd.DataFrame(
            metric_rows or [{"Metric": "Status", "Value": "No summary metrics supplied"}]
        )).to_excel(writer, sheet_name="Summary", index=False)
        used_names = {sheet.title for sheet in writer.book.worksheets}
        for requested_name, extra_frame in (extra_sheets or {}).items():
            if extra_frame is None or extra_frame.empty:
                continue
            base_name = str(requested_name).strip()[:31] or "Details"
            sheet_name = base_name
            suffix = 2
            while sheet_name in used_names:
                ending = f" {suffix}"
                sheet_name = base_name[:31 - len(ending)] + ending
                suffix += 1
            excel_safe(extra_frame).to_excel(writer, sheet_name=sheet_name, index=False)
            used_names.add(sheet_name)
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
    from xml.sax.saxutils import escape

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(str(title)), styles["Title"]),
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
        story.extend(Paragraph(escape(str(note)), styles["BodyText"]) for note in notes)
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("Research support only. Not investment advice. No broker orders are placed.", styles["Italic"]))
    doc.build(story)
    return output.getvalue()
