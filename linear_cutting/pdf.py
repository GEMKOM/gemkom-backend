"""
PDF generator for linear cutting lists using ReportLab.

Produces an A4 page with:
  - Header: session info (key, title, material, stock length, date)
  - Per-bar section: bar number, waste, efficiency
    - Table of cuts: offset | label | nominal length | effective length | job no
  - Footer: totals summary
"""

import io
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


# ─── Color palette ────────────────────────────────────────────────────────────
DARK_BLUE = colors.HexColor('#1E3A5F')
MID_BLUE  = colors.HexColor('#2E6DA4')
LIGHT_BLUE = colors.HexColor('#D6E4F0')
LIGHT_GREY = colors.HexColor('#F5F5F5')
BAR_ACCENT = colors.HexColor('#E8F4FD')


def build_cutting_list_pdf(session) -> bytes:
    """
    Build and return a PDF cutting list for the given LinearCuttingSession.

    Parameters
    ----------
    session : LinearCuttingSession
        Must have optimization_result populated.

    Returns
    -------
    bytes — raw PDF content
    """
    result = session.optimization_result or {}
    bars = result.get('bars', [])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        title=f"Cutting List – {session.key}",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'title', parent=styles['Normal'],
        fontSize=16, textColor=DARK_BLUE, fontName='Helvetica-Bold',
        spaceAfter=2 * mm,
    )
    subtitle_style = ParagraphStyle(
        'subtitle', parent=styles['Normal'],
        fontSize=9, textColor=colors.grey,
        spaceAfter=1 * mm,
    )
    bar_header_style = ParagraphStyle(
        'bar_header', parent=styles['Normal'],
        fontSize=11, textColor=DARK_BLUE, fontName='Helvetica-Bold',
        spaceBefore=4 * mm, spaceAfter=2 * mm,
    )
    small_style = ParagraphStyle(
        'small', parent=styles['Normal'],
        fontSize=8, textColor=colors.grey,
    )

    page_width = A4[0] - 30 * mm  # usable width after margins

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph(f"Cutting List – {session.key}", title_style))
    story.append(Paragraph(session.title, subtitle_style))

    # Info table (2 columns)
    info_data = [
        ['Material', session.material or '—', 'Stock length', f"{session.stock_length_mm} mm"],
        ['Kerf', f"{session.kerf_mm} mm", 'Bars needed', str(result.get('bars_needed', '—'))],
        ['Efficiency', f"{result.get('efficiency_pct', '—')} %", 'Total waste', f"{result.get('total_waste_mm', '—')} mm"],
        ['Date', str(date.today()), 'Prepared by', session.created_by.get_full_name() if session.created_by else '—'],
    ]
    info_table = Table(info_data, colWidths=[30 * mm, 55 * mm, 35 * mm, 55 * mm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (0, -1), DARK_BLUE),
        ('TEXTCOLOR', (2, 0), (2, -1), DARK_BLUE),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GREY),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [LIGHT_GREY, colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width='100%', thickness=1.5, color=DARK_BLUE))
    story.append(Spacer(1, 3 * mm))

    # ── Per-bar sections ───────────────────────────────────────────────────────
    cut_col_widths = [20 * mm, 20 * mm, 65 * mm, 22 * mm, 22 * mm, 26 * mm]

    for bar in bars:
        bar_idx = bar['bar_index']
        waste = bar['waste_mm']
        bar_stock = bar['stock_length_mm']
        efficiency = round((1 - waste / bar_stock) * 100, 1) if bar_stock else 0

        story.append(Paragraph(
            f"Bar #{bar_idx}  –  {bar_stock} mm  |  Waste: {waste} mm  |  Efficiency: {efficiency} %",
            bar_header_style,
        ))

        # Cut table header
        header_row = ['#', 'Offset (mm)', 'Part label', 'Nominal (mm)', 'Effective (mm)', 'Job No']
        table_data = [header_row]

        for i, cut in enumerate(bar['cuts'], start=1):
            table_data.append([
                str(i),
                str(round(cut.get('offset_mm', 0), 1)),
                cut.get('label', ''),
                str(cut.get('nominal_mm', '')),
                str(round(cut.get('effective_mm', cut.get('nominal_mm', 0)), 1)),
                cut.get('job_no', '') or '—',
            ])

        # Waste row
        table_data.append(['', '', '⟶ WASTE', str(waste) + ' mm', '', ''])

        cut_table = Table(table_data, colWidths=cut_col_widths, repeatRows=1)
        cut_table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), DARK_BLUE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            # Body
            ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -2), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, BAR_ACCENT]),
            # Waste row (last)
            ('BACKGROUND', (0, -1), (-1, -1), LIGHT_GREY),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Oblique'),
            ('FONTSIZE', (0, -1), (-1, -1), 8),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.grey),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('LINEBELOW', (0, 0), (-1, 0), 1, DARK_BLUE),
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            # Alignment for numeric columns
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
        ]))
        story.append(cut_table)
        story.append(Spacer(1, 3 * mm))

    # ── Footer summary ─────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        f"Total: {result.get('bars_needed', 0)} bars × {session.stock_length_mm} mm = "
        f"{(result.get('bars_needed', 0) or 0) * session.stock_length_mm} mm used  |  "
        f"Total waste: {result.get('total_waste_mm', 0)} mm  |  "
        f"Overall efficiency: {result.get('efficiency_pct', 0)} %",
        small_style,
    ))

    doc.build(story)
    return buffer.getvalue()
