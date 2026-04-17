"""
PDF generator for linear cutting lists using ReportLab.

Uses Bitstream Vera Sans (bundled with ReportLab) for full Unicode support —
covers all Turkish characters (Ğ ğ İ ı Ş ş Ö ö Ü ü Ç ç) and the degree symbol (°).

optimization_result is now {"groups": [...]} where each group is one catalog
item. Each group is rendered as its own section with a page break between them.
"""

import io
import os
from datetime import date

import reportlab
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, Flowable, PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ─── Register Unicode-capable fonts once at module load ──────────────────────
_FONT_DIR = os.path.join(os.path.dirname(reportlab.__file__), 'fonts')

pdfmetrics.registerFont(TTFont('Vera',   os.path.join(_FONT_DIR, 'Vera.ttf')))
pdfmetrics.registerFont(TTFont('VeraBd', os.path.join(_FONT_DIR, 'VeraBd.ttf')))
pdfmetrics.registerFont(TTFont('VeraIt', os.path.join(_FONT_DIR, 'VeraIt.ttf')))
pdfmetrics.registerFont(TTFont('VeraBI', os.path.join(_FONT_DIR, 'VeraBI.ttf')))

pdfmetrics.registerFontFamily(
    'Vera',
    normal='Vera', bold='VeraBd', italic='VeraIt', boldItalic='VeraBI',
)

# ─── Color palette ────────────────────────────────────────────────────────────
DARK_BLUE   = colors.HexColor('#1E3A5F')
LIGHT_GREY  = colors.HexColor('#F5F5F5')
BAR_ACCENT  = colors.HexColor('#E8F4FD')
WASTE_COLOR = colors.HexColor('#D0D0D0')

# Distinct segment colors for cut pieces (cycles if more than 8 cuts)
_CUT_COLORS = [
    colors.HexColor('#2E86C1'),
    colors.HexColor('#1ABC9C'),
    colors.HexColor('#E67E22'),
    colors.HexColor('#8E44AD'),
    colors.HexColor('#27AE60'),
    colors.HexColor('#E74C3C'),
    colors.HexColor('#F39C12'),
    colors.HexColor('#16A085'),
]


def _fmt_angle(val) -> str:
    """Format an angle value: always show degree symbol. '0°' for square cuts."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return '\u2014'
    return f"{f:g}\u00b0"   # \u00b0 = °


# ─── Custom Flowable: bar diagram ─────────────────────────────────────────────

class BarDiagram(Flowable):
    """
    Draws a horizontal bar diagram for one stock bar.

    The bar is drawn as a rectangle split into colored segments (cuts) and a
    grey waste segment at the end.  Each segment is labelled with its index
    number.  A ruler with mm ticks is drawn below the bar.
    """

    BAR_H    = 14 * mm   # bar rectangle height
    RULER_H  =  5 * mm   # ruler height below bar
    LABEL_H  =  5 * mm   # space for offset labels below ruler
    TOTAL_H  = BAR_H + RULER_H + LABEL_H + 2 * mm

    def __init__(self, bar: dict, cut_colors: list, width: float):
        super().__init__()
        self.bar        = bar
        self.cut_colors = cut_colors
        self.width      = width
        self.height     = self.TOTAL_H

    def draw(self):
        c           = self.canv
        bar         = self.bar
        stock_mm    = bar['stock_length_mm']
        cuts        = bar['cuts']
        waste_mm    = bar['waste_mm']
        scale       = self.width / stock_mm   # px per mm

        y_bar  = self.RULER_H + self.LABEL_H + 2 * mm
        y_top  = y_bar + self.BAR_H

        # ── Draw cut segments ──────────────────────────────────────────────
        for i, cut in enumerate(cuts):
            x = cut['offset_mm'] * scale
            w = cut['effective_mm'] * scale
            seg_color = self.cut_colors[i % len(self.cut_colors)]

            c.setFillColor(seg_color)
            c.setStrokeColor(colors.white)
            c.setLineWidth(0.5)
            c.rect(x, y_bar, w, self.BAR_H, fill=1, stroke=1)

            # Segment index label (white, centered, only if wide enough)
            if w > 6 * mm:
                c.setFillColor(colors.white)
                c.setFont('VeraBd', 7)
                c.drawCentredString(x + w / 2, y_bar + self.BAR_H / 2 - 2.5, str(i + 1))

        # ── Draw waste segment ─────────────────────────────────────────────
        if waste_mm > 0:
            x_waste = (cuts[-1]['offset_mm'] + cuts[-1]['effective_mm']) * scale if cuts else 0
            w_waste = waste_mm * scale

            c.setFillColor(WASTE_COLOR)
            c.setStrokeColor(colors.white)
            c.setLineWidth(0.5)
            c.rect(x_waste, y_bar, w_waste, self.BAR_H, fill=1, stroke=1)

            if w_waste > 8 * mm:
                c.setFillColor(colors.HexColor('#666666'))
                c.setFont('VeraIt', 6)
                label = f"Fire {waste_mm} mm"
                c.drawCentredString(x_waste + w_waste / 2, y_bar + self.BAR_H / 2 - 2.5, label)

        # ── Outer border ───────────────────────────────────────────────────
        c.setStrokeColor(DARK_BLUE)
        c.setLineWidth(1)
        c.rect(0, y_bar, self.width, self.BAR_H, fill=0, stroke=1)

        # ── Ruler ticks ────────────────────────────────────────────────────
        for interval in [500, 1000, 2000]:
            if stock_mm / interval <= 12:
                tick_interval = interval
                break
        else:
            tick_interval = 2000

        c.setStrokeColor(colors.grey)
        c.setFillColor(colors.grey)
        c.setFont('Vera', 5)
        c.setLineWidth(0.3)

        tick = 0
        while tick <= stock_mm:
            x_tick = tick * scale
            is_major = (tick % tick_interval == 0)
            tick_len = 2.5 * mm if is_major else 1.2 * mm
            c.line(x_tick, y_bar, x_tick, y_bar - tick_len)
            if is_major:
                c.drawCentredString(x_tick, y_bar - tick_len - 3.5, str(tick))
            tick += tick_interval // 2

        c.line(self.width, y_bar, self.width, y_bar - 2.5 * mm)
        c.drawCentredString(self.width, y_bar - 2.5 * mm - 3.5, str(stock_mm))


# ─── Style factory (avoids duplicate registration on repeated calls) ──────────

def _make_styles():
    return {
        'title': ParagraphStyle(
            'lc_title',
            fontName='VeraBd', fontSize=15, textColor=DARK_BLUE,
            spaceAfter=2 * mm,
        ),
        'subtitle': ParagraphStyle(
            'lc_subtitle',
            fontName='Vera', fontSize=9, textColor=colors.grey,
            spaceAfter=1 * mm,
        ),
        'group_header': ParagraphStyle(
            'lc_group_header',
            fontName='VeraBd', fontSize=12, textColor=DARK_BLUE,
            spaceBefore=4 * mm, spaceAfter=3 * mm,
        ),
        'bar_header': ParagraphStyle(
            'lc_bar_header',
            fontName='VeraBd', fontSize=10, textColor=DARK_BLUE,
            spaceBefore=5 * mm, spaceAfter=2 * mm,
        ),
        'small': ParagraphStyle(
            'lc_small',
            fontName='Vera', fontSize=8, textColor=colors.grey,
        ),
        'legend': ParagraphStyle(
            'lc_legend',
            fontName='Vera', fontSize=7, textColor=colors.grey,
            spaceAfter=1 * mm,
        ),
    }


def _render_group(group: dict, part_lookup: dict, styles: dict, usable_width: float) -> list:
    """
    Build the story elements for one item group.
    Returns a list of flowables.
    """
    story = []
    col_w = [10*mm, 17*mm, 50*mm, 20*mm, 20*mm, 17*mm, 17*mm, 24*mm]

    item_name    = group.get('item_name', '—')
    item_code    = group.get('item_code', '')
    stock_len    = group.get('stock_length_mm', 0)
    kerf_mm      = group.get('kerf_mm', 0)
    bars_needed  = group.get('bars_needed', 0)
    total_waste  = group.get('total_waste_mm', 0)
    efficiency   = group.get('efficiency_pct', 0)
    bars         = group.get('bars', [])

    # ── Group header ──────────────────────────────────────────────────────
    header_text = f"{item_name}"
    if item_code:
        header_text += f"  <font size='9' color='grey'>({item_code})</font>"
    story.append(Paragraph(header_text, styles['group_header']))

    # ── Group summary table ───────────────────────────────────────────────
    summary_data = [
        ['Stok boyu', f"{stock_len} mm",
         'Testere payı', f"{kerf_mm} mm"],
        ['Gereken çubuk', str(bars_needed),
         'Toplam fire', f"{total_waste} mm"],
        ['Verimlilik', f"{efficiency} %", '', ''],
    ]
    summary_table = Table(summary_data, colWidths=[32*mm, 53*mm, 37*mm, 53*mm])
    summary_table.setStyle(TableStyle([
        ('FONTNAME',      (0, 0), (-1, -1), 'Vera'),
        ('FONTNAME',      (0, 0), (0,  -1), 'VeraBd'),
        ('FONTNAME',      (2, 0), (2,  -1), 'VeraBd'),
        ('FONTSIZE',      (0, 0), (-1, -1), 8),
        ('TEXTCOLOR',     (0, 0), (0,  -1), DARK_BLUE),
        ('TEXTCOLOR',     (2, 0), (2,  -1), DARK_BLUE),
        ('ROWBACKGROUNDS',(0, 0), (-1, -1), [LIGHT_GREY, colors.white]),
        ('GRID',          (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 3 * mm))

    # ── Per-bar sections ──────────────────────────────────────────────────
    for bar in bars:
        bar_idx   = bar.get('global_bar_index', bar['bar_index'])
        waste     = bar['waste_mm']
        bar_stock = bar['stock_length_mm']
        eff       = round((1 - waste / bar_stock) * 100, 1) if bar_stock else 0
        cuts      = bar['cuts']

        story.append(Paragraph(
            f"Çubuk #{bar_idx}  –  {bar_stock} mm"
            f"  |  Fire: {waste} mm  |  Verimlilik: {eff}\u00a0%",
            styles['bar_header'],
        ))

        # Visual bar diagram
        story.append(BarDiagram(bar, _CUT_COLORS, usable_width))

        # Color legend
        legend_parts = []
        for i, cut in enumerate(cuts):
            color_hex = _CUT_COLORS[i % len(_CUT_COLORS)].hexval()
            legend_parts.append(
                f'<font color="{color_hex}">&#9632;</font> {i+1}. {cut.get("label","")}'
            )
        story.append(Paragraph('    '.join(legend_parts), styles['legend']))
        story.append(Spacer(1, 2 * mm))

        # Cut table
        header_row = [
            '#', 'Ofset (mm)', 'Parça adı',
            'Nominal (mm)', 'Efektif (mm)',
            'Sol açı', 'Sağ açı', 'İş No',
        ]
        rows = [header_row]

        for i, cut in enumerate(cuts, start=1):
            part        = part_lookup.get(cut.get('part_id'))
            angle_left  = cut.get('angle_left_deg')
            angle_right = cut.get('angle_right_deg')
            if angle_left is None:
                angle_left  = float(part.angle_left_deg)  if part else 0
            if angle_right is None:
                angle_right = float(part.angle_right_deg) if part else 0

            rows.append([
                str(i),
                str(round(cut.get('offset_mm', 0), 1)),
                cut.get('label', ''),
                str(cut.get('nominal_mm', '')),
                str(round(cut.get('effective_mm', cut.get('nominal_mm', 0)), 1)),
                _fmt_angle(angle_left),
                _fmt_angle(angle_right),
                cut.get('job_no', '') or '—',
            ])

        # Fire (waste) row
        rows.append(['', '', '⟶ FİRE', f"{waste} mm", '', '', '', ''])

        cut_table = Table(rows, colWidths=col_w, repeatRows=1)
        cut_table.setStyle(TableStyle([
            ('BACKGROUND',     (0, 0), (-1, 0),  DARK_BLUE),
            ('TEXTCOLOR',      (0, 0), (-1, 0),  colors.white),
            ('FONTNAME',       (0, 0), (-1, 0),  'VeraBd'),
            ('FONTSIZE',       (0, 0), (-1, 0),  8),
            ('ALIGN',          (0, 0), (-1, 0),  'CENTER'),
            ('LINEBELOW',      (0, 0), (-1, 0),  1, DARK_BLUE),
            ('FONTNAME',       (0, 1), (-1, -2), 'Vera'),
            ('FONTSIZE',       (0, 1), (-1, -2), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, BAR_ACCENT]),
            ('BACKGROUND',     (0, -1), (-1, -1), LIGHT_GREY),
            ('FONTNAME',       (0, -1), (-1, -1), 'VeraIt'),
            ('FONTSIZE',       (0, -1), (-1, -1), 8),
            ('TEXTCOLOR',      (0, -1), (-1, -1), colors.grey),
            ('GRID',           (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('TOPPADDING',     (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 3),
            ('LEFTPADDING',    (0, 0), (-1, -1), 4),
            ('RIGHTPADDING',   (0, 0), (-1, -1), 4),
            ('ALIGN',          (0, 1), (0, -1), 'CENTER'),
            ('ALIGN',          (1, 1), (1, -1), 'RIGHT'),
            ('ALIGN',          (3, 1), (4, -1), 'RIGHT'),
            ('ALIGN',          (5, 1), (6, -1), 'CENTER'),
        ]))
        story.append(cut_table)
        story.append(Spacer(1, 3 * mm))

    return story


def build_cutting_list_pdf(session) -> bytes:
    """
    Build and return a Turkish-language PDF cutting list for the given
    LinearCuttingSession (must have optimization_result populated).

    One section per item group, separated by page breaks.
    """
    result = session.optimization_result or {}
    groups = result.get('groups', [])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title=f"Kesim Listesi – {session.key}",
    )

    USABLE_WIDTH = A4[0] - 30 * mm   # 175 mm
    styles = _make_styles()

    # Part lookup for angle fallback
    part_lookup = {p.id: p for p in session.parts.all()}

    prepared_by = session.created_by.get_full_name() if session.created_by else '—'
    total_bars  = sum(g.get('bars_needed', 0) for g in groups)

    story = []

    # ── Document title ────────────────────────────────────────────────────────
    story.append(Paragraph(f"Kesim Listesi – {session.key}", styles['title']))
    story.append(Paragraph(session.title, styles['subtitle']))

    # ── Document-level info ───────────────────────────────────────────────────
    doc_info_data = [
        ['Toplam çubuk', str(total_bars),
         'Profil grubu', str(len(groups))],
        ['Testere payı', f"{session.kerf_mm} mm",
         'Tarih', str(date.today())],
        ['Hazırlayan', prepared_by, '', ''],
    ]
    doc_info_table = Table(doc_info_data, colWidths=[32*mm, 53*mm, 37*mm, 53*mm])
    doc_info_table.setStyle(TableStyle([
        ('FONTNAME',      (0, 0), (-1, -1), 'Vera'),
        ('FONTNAME',      (0, 0), (0,  -1), 'VeraBd'),
        ('FONTNAME',      (2, 0), (2,  -1), 'VeraBd'),
        ('FONTSIZE',      (0, 0), (-1, -1), 8),
        ('TEXTCOLOR',     (0, 0), (0,  -1), DARK_BLUE),
        ('TEXTCOLOR',     (2, 0), (2,  -1), DARK_BLUE),
        ('ROWBACKGROUNDS',(0, 0), (-1, -1), [LIGHT_GREY, colors.white]),
        ('GRID',          (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(doc_info_table)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width='100%', thickness=1.5, color=DARK_BLUE))

    # ── One section per item group ────────────────────────────────────────────
    for idx, group in enumerate(groups):
        if idx > 0:
            story.append(PageBreak())

        group_story = _render_group(group, part_lookup, styles, USABLE_WIDTH)
        story.extend(group_story)

        # Group footer
        story.append(HRFlowable(width='100%', thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"{group.get('bars_needed', 0)} çubuk × {group.get('stock_length_mm', 0)} mm  |  "
            f"Toplam fire: {group.get('total_waste_mm', 0)} mm  |  "
            f"Verimlilik: {group.get('efficiency_pct', 0)}\u00a0%",
            styles['small'],
        ))

    doc.build(story)
    return buffer.getvalue()


def build_task_pdf(task) -> bytes:
    """
    Build a single-bar work-order PDF for one LinearCuttingTask.
    """
    USABLE_WIDTH = A4[0] - 30 * mm
    styles = _make_styles()

    # Build a synthetic bar dict from the task's stored fields
    bar = {
        'bar_index': task.bar_index,
        'global_bar_index': task.bar_index,
        'stock_length_mm': task.stock_length_mm,
        'waste_mm': task.waste_mm,
        'cuts': task.layout_json or [],
    }

    # Part lookup for angle fallback
    part_ids = [c.get('part_id') for c in bar['cuts'] if c.get('part_id')]
    from .models import LinearCuttingPart
    part_lookup = {
        p.id: p for p in LinearCuttingPart.objects.filter(id__in=part_ids)
    }

    session = task.session
    prepared_by = session.created_by.get_full_name() if session.created_by else '—'
    eff = round((1 - task.waste_mm / task.stock_length_mm) * 100, 1) if task.stock_length_mm else 0

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title=f"İş Emri – {task.key}",
    )

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph(f"İş Emri – {task.key}", styles['title']))
    story.append(Paragraph(task.name, styles['subtitle']))

    info_data = [
        ['Malzeme',    task.material,         'Stok boyu',  f"{task.stock_length_mm} mm"],
        ['Oturum',     session.key,            'Fire',       f"{task.waste_mm} mm"],
        ['Verimlilik', f"{eff} %",             'Tarih',      str(date.today())],
        ['Hazırlayan', prepared_by,            '', ''],
    ]
    info_table = Table(info_data, colWidths=[32*mm, 53*mm, 37*mm, 53*mm])
    info_table.setStyle(TableStyle([
        ('FONTNAME',      (0, 0), (-1, -1), 'Vera'),
        ('FONTNAME',      (0, 0), (0,  -1), 'VeraBd'),
        ('FONTNAME',      (2, 0), (2,  -1), 'VeraBd'),
        ('FONTSIZE',      (0, 0), (-1, -1), 8),
        ('TEXTCOLOR',     (0, 0), (0,  -1), DARK_BLUE),
        ('TEXTCOLOR',     (2, 0), (2,  -1), DARK_BLUE),
        ('ROWBACKGROUNDS',(0, 0), (-1, -1), [LIGHT_GREY, colors.white]),
        ('GRID',          (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width='100%', thickness=1.5, color=DARK_BLUE))
    story.append(Spacer(1, 3 * mm))

    # ── Bar diagram ───────────────────────────────────────────────────────────
    story.append(BarDiagram(bar, _CUT_COLORS, USABLE_WIDTH))

    # Color legend
    legend_parts = []
    for i, cut in enumerate(bar['cuts']):
        color_hex = _CUT_COLORS[i % len(_CUT_COLORS)].hexval()
        legend_parts.append(
            f'<font color="{color_hex}">&#9632;</font> {i+1}. {cut.get("label","")}'
        )
    story.append(Paragraph('    '.join(legend_parts), styles['legend']))
    story.append(Spacer(1, 3 * mm))

    # ── Cut table ─────────────────────────────────────────────────────────────
    col_w = [10*mm, 17*mm, 50*mm, 20*mm, 20*mm, 17*mm, 17*mm, 24*mm]
    rows = [['#', 'Ofset (mm)', 'Parça adı', 'Nominal (mm)', 'Efektif (mm)', 'Sol açı', 'Sağ açı', 'İş No']]

    for i, cut in enumerate(bar['cuts'], start=1):
        part        = part_lookup.get(cut.get('part_id'))
        angle_left  = cut.get('angle_left_deg')
        angle_right = cut.get('angle_right_deg')
        if angle_left is None:
            angle_left  = float(part.angle_left_deg)  if part else 0
        if angle_right is None:
            angle_right = float(part.angle_right_deg) if part else 0

        rows.append([
            str(i),
            str(round(cut.get('offset_mm', 0), 1)),
            cut.get('label', ''),
            str(cut.get('nominal_mm', '')),
            str(round(cut.get('effective_mm', cut.get('nominal_mm', 0)), 1)),
            _fmt_angle(angle_left),
            _fmt_angle(angle_right),
            cut.get('job_no', '') or '—',
        ])

    rows.append(['', '', '⟶ FİRE', f"{task.waste_mm} mm", '', '', '', ''])

    cut_table = Table(rows, colWidths=col_w, repeatRows=1)
    cut_table.setStyle(TableStyle([
        ('BACKGROUND',     (0, 0), (-1, 0),  DARK_BLUE),
        ('TEXTCOLOR',      (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',       (0, 0), (-1, 0),  'VeraBd'),
        ('FONTSIZE',       (0, 0), (-1, 0),  8),
        ('ALIGN',          (0, 0), (-1, 0),  'CENTER'),
        ('LINEBELOW',      (0, 0), (-1, 0),  1, DARK_BLUE),
        ('FONTNAME',       (0, 1), (-1, -2), 'Vera'),
        ('FONTSIZE',       (0, 1), (-1, -2), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, BAR_ACCENT]),
        ('BACKGROUND',     (0, -1), (-1, -1), LIGHT_GREY),
        ('FONTNAME',       (0, -1), (-1, -1), 'VeraIt'),
        ('FONTSIZE',       (0, -1), (-1, -1), 8),
        ('TEXTCOLOR',      (0, -1), (-1, -1), colors.grey),
        ('GRID',           (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING',     (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 3),
        ('LEFTPADDING',    (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 4),
        ('ALIGN',          (0, 1), (0, -1), 'CENTER'),
        ('ALIGN',          (1, 1), (1, -1), 'RIGHT'),
        ('ALIGN',          (3, 1), (4, -1), 'RIGHT'),
        ('ALIGN',          (5, 1), (6, -1), 'CENTER'),
    ]))
    story.append(cut_table)

    doc.build(story)
    return buffer.getvalue()
