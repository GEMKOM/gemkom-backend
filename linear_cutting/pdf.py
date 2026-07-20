"""
PDF generator for linear cutting lists using ReportLab.

Uses Bitstream Vera Sans (bundled with ReportLab) for full Unicode support —
covers all Turkish characters (Ğ ğ İ ı Ş ş Ö ö Ü ü Ç ç) and the degree symbol (°).

Rendering follows CUTTING_MODEL.md:
* pieces are drawn as their true quadrilaterals (near edge "alt" at the
  bottom of the diagram, far edge "üst" at the top),
* saw passes are drawn as dark blade bands; everything not covered by a
  piece is hatched scrap,
* every bar gets a "Kesim Sırası" pass table with the stop distances the
  operator dials (measured from the fresh edge of the remaining bar).
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

from .geometry import ANGLE_TOL_DEG, piece_faces, passes_for_bar


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
SCRAP_BG    = colors.HexColor('#E4E7EA')
BLADE_COLOR = colors.HexColor('#14181C')
REMNANT_ACC = colors.HexColor('#B98900')

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

PASS_KIND_TR = {
    'lead': 'Baş kesim',
    'shared': 'Ortak kesim',
    'end': 'Parça ayırma',
}


def _fmt_angle(val) -> str:
    """'0°' for square; otherwise magnitude + which edge holds the long point."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return '—'
    if abs(f) < ANGLE_TOL_DEG:
        return '0°'
    side = 'alt' if f > 0 else 'üst'
    return f"{abs(f):g}° ({side})"


def _fmt_num(val, nd=1):
    try:
        f = float(val)
    except (TypeError, ValueError):
        return '—'
    return f"{round(f, nd):g}"


def _fmt_pass_angle(pss: dict) -> str:
    """Pass angle with the physical lean of the cut plane: the direction the
    plane leans toward the far ("üst") edge — that is what the operator sets
    on the saw."""
    try:
        a = float(pss.get('angle_deg') or 0)
    except (TypeError, ValueError):
        return '—'
    if abs(a) < ANGLE_TOL_DEG:
        return '0°'
    near = float(pss.get('x_near_mm') or 0)
    far = float(pss.get('x_far_mm') or 0)
    side = 'sağa' if far > near else 'sola'
    return f"{abs(a):g}° {side}"


# ─── Custom Flowable: bar diagram ─────────────────────────────────────────────

class BarDiagram(Flowable):
    """
    Horizontal diagram of one stock bar.

    Pieces are drawn as their true quadrilaterals (angled faces), the blade
    bands of every saw pass are shown in dark, and any bar area not covered
    by a piece is hatched scrap.  A mm ruler runs below the bar.
    """

    BAR_H    = 16 * mm
    RULER_H  =  5 * mm
    LABEL_H  =  5 * mm
    TOTAL_H  = BAR_H + RULER_H + LABEL_H + 4 * mm

    def __init__(self, bar: dict, cut_colors: list, width: float, kerf_mm: float = 0.0):
        super().__init__()
        self.bar        = bar
        self.cut_colors = cut_colors
        self.width      = width
        self.kerf_mm    = kerf_mm
        self.height     = self.TOTAL_H

    def draw(self):
        c        = self.canv
        bar      = self.bar
        stock_mm = float(bar.get('stock_length_mm') or 1)
        cuts     = bar.get('cuts') or []
        passes   = bar.get('passes') or []
        scale    = self.width / stock_mm

        y_bar = self.RULER_H + self.LABEL_H + 2 * mm    # near edge ("alt")
        y_top = y_bar + self.BAR_H                       # far edge ("üst")

        # ── Scrap background with hatching ─────────────────────────────────
        c.saveState()
        c.setFillColor(SCRAP_BG)
        c.rect(0, y_bar, self.width, self.BAR_H, fill=1, stroke=0)
        p = c.beginPath()
        p.rect(0, y_bar, self.width, self.BAR_H)
        c.clipPath(p, stroke=0, fill=0)
        c.setStrokeColor(colors.HexColor('#C9CDD2'))
        c.setLineWidth(0.4)
        step = 2.2 * mm
        x = -self.BAR_H
        while x < self.width + self.BAR_H:
            c.line(x, y_bar, x + self.BAR_H, y_top)
            x += step
        c.restoreState()

        # ── Pieces as quadrilaterals ───────────────────────────────────────
        for i, cut in enumerate(cuts):
            faces = piece_faces(
                float(cut.get('offset_mm') or 0),
                float(cut.get('nominal_mm') or cut.get('effective_mm') or 0),
                float(cut.get('angle_left_deg') or 0),
                float(cut.get('angle_right_deg') or 0),
                float(cut.get('profile_height_mm') or 0),
            )
            xln, xlf = (v * scale for v in faces['left'])
            xrn, xrf = (v * scale for v in faces['right'])

            c.setFillColor(self.cut_colors[i % len(self.cut_colors)])
            c.setStrokeColor(colors.white)
            c.setLineWidth(0.5)
            p = c.beginPath()
            p.moveTo(xln, y_bar)
            p.lineTo(xlf, y_top)
            p.lineTo(xrf, y_top)
            p.lineTo(xrn, y_bar)
            p.close()
            c.drawPath(p, fill=1, stroke=1)

            # Index label (+d for flipped, +b for bending)
            x_center = (xln + xlf + xrf + xrn) / 4
            w_box = (float(cut.get('nominal_mm') or 0)) * scale
            if w_box > 7 * mm:
                marks = ''
                if cut.get('flipped'):
                    marks += 'd'
                if cut.get('requires_bending'):
                    marks += 'b'
                label = f"{i + 1}{marks}"
                c.setFillColor(colors.white)
                c.setFont('VeraBd', 7)
                c.drawCentredString(x_center, y_bar + self.BAR_H / 2 - 2.5, label)

        # ── Blade bands for saw passes ─────────────────────────────────────
        if passes:
            c.saveState()
            try:
                c.setFillAlpha(0.55)
            except Exception:
                pass
            c.setFillColor(BLADE_COLOR)
            for pss in passes:
                blade = float(pss.get('blade_axial_mm') or 0) * scale
                if blade <= 0:
                    continue
                sign = -1 if pss.get('kind') == 'lead' else 1
                xn = float(pss.get('x_near_mm') or 0) * scale
                xf = float(pss.get('x_far_mm') or 0) * scale
                p = c.beginPath()
                p.moveTo(xn, y_bar)
                p.lineTo(xf, y_top)
                p.lineTo(xf + sign * blade, y_top)
                p.lineTo(xn + sign * blade, y_bar)
                p.close()
                c.drawPath(p, fill=1, stroke=0)
            c.restoreState()

            # Angle labels above the bar (only when there is room)
            if len(passes) and self.width / len(passes) > 9 * mm:
                c.setFillColor(colors.HexColor('#495057'))
                c.setFont('Vera', 5.5)
                for pss in passes:
                    ang = float(pss.get('angle_deg') or 0)
                    if abs(ang) < ANGLE_TOL_DEG:
                        continue
                    xm = (float(pss.get('x_near_mm') or 0)
                          + float(pss.get('x_far_mm') or 0)) / 2 * scale
                    c.drawCentredString(xm, y_top + 1.2 * mm, f"{abs(ang):g}°")

        # ── Waste label ────────────────────────────────────────────────────
        waste_mm = float(bar.get('waste_mm') or 0)
        if waste_mm * scale > 14 * mm:
            c.setFillColor(colors.HexColor('#666666'))
            c.setFont('VeraIt', 6)
            c.drawCentredString(self.width - waste_mm * scale / 2,
                                y_bar + self.BAR_H / 2 - 2.5,
                                f"Fire {waste_mm:g} mm")

        # ── Outer border ───────────────────────────────────────────────────
        c.setStrokeColor(REMNANT_ACC if bar.get('is_remnant') else DARK_BLUE)
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
        c.drawCentredString(self.width, y_bar - 2.5 * mm - 3.5, f"{stock_mm:g}")

        # Edge naming (matches the angle convention wording)
        c.setFont('VeraIt', 5)
        c.setFillColor(colors.grey)
        c.drawString(-0.5 * mm, y_bar - 6.5 * mm, '')
        c.saveState()
        c.setFont('Vera', 5)
        c.drawRightString(-1 * mm, y_top - 2, 'üst')
        c.drawRightString(-1 * mm, y_bar + 0.5, 'alt')
        c.restoreState()


# ─── Style factory ────────────────────────────────────────────────────────────

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
        'section': ParagraphStyle(
            'lc_section',
            fontName='VeraBd', fontSize=8.5, textColor=DARK_BLUE,
            spaceBefore=2 * mm, spaceAfter=1 * mm,
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


_CONVENTION_NOTE = (
    "Boylar <b>uzun kenardan</b> (en uzun nokta) ölçülür. "
    "Açı: <b>(alt)</b> = uzun kenar alt kenarda, <b>(üst)</b> = uzun kenar üst kenarda. "
    "Diyagramda parça numarası yanındaki <b>d</b> = parça 180° döndürülerek yerleştirilir, "
    "<b>b</b> = büküm var (boy açınım boyudur). Koyu bantlar testere kesimini, taralı alanlar fireyi gösterir."
)

_PASS_KIND_NOTE = (
    "Tür — <b>Ortak kesim:</b> tek geçiş iki parçaya hizmet eder (bıçağın iki tarafı da parça). "
    "<b>Parça ayırma:</b> parçayı bitirir; kesimin öbür tarafı parça yüzeyi değildir. "
    "<b>Baş kesim:</b> parça çıkmaz, bir sonraki parçanın yüzeyini hazırlar (çıkan küçük parça firedir)."
)

_STOP_NOTE = (
    "Ayar mesafeleri kalan barın <b>taze kesilmiş kenarından</b> ölçülür ve boy dayamasına "
    "doğrudan girilebilir. Alt/Üst: barın alt (yakın) ve üst (uzak) kenarı boyunca ölçü. "
    "Kesim sırası tablosundaki açı yönü (<b>sola/sağa</b>): kesim çizgisinin üst kenara doğru yattığı yön."
)


def _table_style_common():
    return [
        ('BACKGROUND',     (0, 0), (-1, 0),  DARK_BLUE),
        ('TEXTCOLOR',      (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',       (0, 0), (-1, 0),  'VeraBd'),
        ('FONTSIZE',       (0, 0), (-1, 0),  7.5),
        ('ALIGN',          (0, 0), (-1, 0),  'CENTER'),
        ('FONTNAME',       (0, 1), (-1, -1), 'Vera'),
        ('FONTSIZE',       (0, 1), (-1, -1), 7.5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, BAR_ACCENT]),
        ('GRID',           (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING',     (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING',    (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 3),
    ]


def _cut_table(cuts: list, waste_mm) -> Table:
    col_w = [8*mm, 17*mm, 18*mm, 34*mm, 17*mm, 14*mm, 20*mm, 20*mm, 7*mm, 7*mm, 18*mm]
    header = ['#', 'Başlangıç', 'Resim No', 'Parça adı', 'Boy (mm)',
              'Profil', 'Sol açı', 'Sağ açı', 'D', 'B', 'İş No']
    rows = [header]
    for i, cut in enumerate(cuts, start=1):
        rows.append([
            str(i),
            _fmt_num(cut.get('offset_mm', 0)),
            cut.get('image_no') or '—',
            cut.get('label', ''),
            _fmt_num(cut.get('nominal_mm', cut.get('effective_mm', 0))),
            _fmt_num(cut.get('profile_height_mm') or 0, 0) if cut.get('profile_height_mm') else '—',
            _fmt_angle(cut.get('angle_left_deg', 0)),
            _fmt_angle(cut.get('angle_right_deg', 0)),
            'D' if cut.get('flipped') else '—',
            'B' if cut.get('requires_bending') else '—',
            cut.get('job_no', '') or '—',
        ])
    rows.append(['', '', '', 'FİRE', f"{waste_mm} mm", '', '', '', '', '', ''])

    t = Table(rows, colWidths=col_w, repeatRows=1)
    style = _table_style_common() + [
        ('BACKGROUND',    (0, -1), (-1, -1), LIGHT_GREY),
        ('FONTNAME',      (0, -1), (-1, -1), 'VeraIt'),
        ('TEXTCOLOR',     (0, -1), (-1, -1), colors.grey),
        ('ALIGN',         (0, 1), (0, -1), 'CENTER'),
        ('ALIGN',         (1, 1), (1, -1), 'RIGHT'),
        ('ALIGN',         (4, 1), (5, -1), 'RIGHT'),
        ('ALIGN',         (6, 1), (9, -1), 'CENTER'),
    ]
    t.setStyle(TableStyle(style))
    return t


def _pass_table(passes: list) -> Table:
    col_w = [13*mm, 26*mm, 24*mm, 24*mm, 24*mm, 49*mm]
    header = ['Kesim', 'Tür', 'Açı', 'Ayar Alt (mm)', 'Ayar Üst (mm)', 'Çıkan Parça']
    rows = [header]
    for p in passes:
        rows.append([
            str(p.get('seq', '')),
            PASS_KIND_TR.get(p.get('kind'), p.get('kind', '')),
            _fmt_pass_angle(p),
            _fmt_num(p.get('stop_near_mm')),
            _fmt_num(p.get('stop_far_mm')),
            p.get('releases') or 'fire parçası',
        ])
    t = Table(rows, colWidths=col_w, repeatRows=1)
    style = _table_style_common() + [
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),
        ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
    ]
    t.setStyle(TableStyle(style))
    return t


def _render_bar(bar: dict, styles: dict, usable_width: float,
                kerf_mm: float, header_text: str) -> list:
    """Story elements for one bar: header, diagram, legend, tables."""
    story = []
    cuts = bar.get('cuts') or []
    waste = bar.get('waste_mm', 0)

    story.append(Paragraph(header_text, styles['bar_header']))
    story.append(BarDiagram(bar, _CUT_COLORS, usable_width, kerf_mm))

    legend_parts = []
    for i, cut in enumerate(cuts):
        color_hex = _CUT_COLORS[i % len(_CUT_COLORS)].hexval()
        legend_parts.append(
            f'<font color="{color_hex}">&bull;</font> <b>{i+1}.</b> {cut.get("label","")}'
        )
    story.append(Paragraph('    '.join(legend_parts), styles['legend']))
    story.append(Spacer(1, 1.5 * mm))

    story.append(Paragraph('Parçalar', styles['section']))
    story.append(_cut_table(cuts, waste))

    passes = bar.get('passes') or []
    if passes:
        story.append(Spacer(1, 1.5 * mm))
        story.append(Paragraph('Kesim Sırası', styles['section']))
        story.append(_pass_table(passes))
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph(_PASS_KIND_NOTE, styles['legend']))
    story.append(Spacer(1, 3 * mm))
    return story


def _bar_header_text(bar, material: str) -> str:
    bar_idx = bar.get('global_bar_index', bar.get('bar_index'))
    stock = bar.get('stock_length_mm', 0)
    waste = bar.get('waste_mm', 0)
    eff = round((1 - waste / stock) * 100, 1) if stock else 0
    src = '  |  <font color="#B98900">STOKTAN</font>' if bar.get('is_remnant') else ''
    mat = f"  |  <font color='grey'>{material}</font>" if material else ''
    return (f"Bar #{bar_idx}  –  {stock} mm{src}{mat}"
            f"  |  Fire: {waste} mm  |  Verim: {eff} %")


def _info_table(data):
    t = Table(data, colWidths=[32*mm, 53*mm, 37*mm, 53*mm])
    t.setStyle(TableStyle([
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
    return t


def _group_overview_table(groups: list) -> Table:
    """Cover-page overview: one row per profile group."""
    header = ['Profil', 'Kod', 'Stok (mm)', 'Yeni bar', 'Stoktan',
              'Fire (mm)', 'Verim %', 'Kesim', 'Açı değişimi']
    rows = [header]
    for g in groups:
        rows.append([
            g.get('item_name', '—'),
            g.get('item_code', '') or '—',
            str(g.get('stock_length_mm', 0)),
            str(g.get('bars_needed', 0)),
            str(g.get('remnant_bars_used', 0)),
            str(g.get('total_waste_mm', 0)),
            str(g.get('efficiency_pct', 0)),
            str(g.get('total_pass_count', '—')),
            str(g.get('saw_setup_changes', '—')),
        ])
    t = Table(rows, colWidths=[46*mm, 28*mm, 17*mm, 14*mm, 14*mm,
                               16*mm, 14*mm, 12*mm, 19*mm], repeatRows=1)
    style = _table_style_common() + [
        ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
    ]
    t.setStyle(TableStyle(style))
    return t


def build_cutting_list_pdf(session) -> bytes:
    """
    Turkish-language PDF cutting list for a LinearCuttingSession
    (requires optimization_result). One section per item group.
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

    USABLE_WIDTH = A4[0] - 30 * mm
    styles = _make_styles()

    prepared_by = session.created_by.get_full_name() if session.created_by else '—'
    total_bars  = sum(g.get('bars_needed', 0) for g in groups)

    story = []
    story.append(Paragraph(f"Kesim Listesi – {session.key}", styles['title']))
    story.append(Paragraph(session.title, styles['subtitle']))

    # ── Page 1: cover — session info, conventions, group overview ────────
    story.append(_info_table([
        ['Toplam bar', str(total_bars),
         'Profil grubu', str(len(groups))],
        ['Testere payı', f"{session.kerf_mm} mm",
         'Tarih', str(date.today())],
        ['Hazırlayan', prepared_by, '', ''],
    ]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(_CONVENTION_NOTE, styles['legend']))
    story.append(Paragraph(_STOP_NOTE, styles['legend']))
    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width='100%', thickness=1.5, color=DARK_BLUE))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph('Profil Grupları', styles['group_header']))
    story.append(_group_overview_table(groups))

    # ── One page per bar ─────────────────────────────────────────────────
    for group in groups:
        item_name = group.get('item_name', '—')
        item_code = group.get('item_code', '')
        kerf_mm = float(group.get('kerf_mm', 0) or 0)
        context = f"{item_name}"
        if item_code:
            context += f"  <font size='9' color='grey'>({item_code})</font>"
        context += (f"  <font size='8' color='grey'>|  Stok: "
                    f"{group.get('stock_length_mm', 0)} mm  |  "
                    f"Testere payı: {kerf_mm:g} mm  |  {session.key}</font>")
        for bar in group.get('bars', []):
            story.append(PageBreak())
            story.append(Paragraph(context, styles['group_header']))
            story.append(HRFlowable(width='100%', thickness=0.8, color=DARK_BLUE))
            story.extend(_render_bar(
                bar, styles, USABLE_WIDTH, kerf_mm,
                _bar_header_text(bar, ''),
            ))

    doc.build(story)
    return buffer.getvalue()


def build_task_pdf(task) -> bytes:
    """Single-bar work-order PDF for one LinearCuttingTask."""
    USABLE_WIDTH = A4[0] - 30 * mm
    styles = _make_styles()
    session = task.session
    kerf_mm = float(session.kerf_mm or 0)

    bar = {
        'bar_index': task.bar_index,
        'global_bar_index': task.bar_index,
        'stock_length_mm': task.stock_length_mm,
        'waste_mm': task.waste_mm,
        'is_remnant': task.is_remnant_bar,
        'cuts': task.layout_json or [],
    }
    # Recompute passes only for layouts produced by the current model —
    # legacy layout_json (pre-redesign tasks) lacks shared_right/end_mm and
    # would yield wrong operator instructions.
    new_schema = bool(bar['cuts']) and all(
        isinstance(c, dict) and 'shared_right' in c for c in bar['cuts']
    )
    bar['passes'] = task.passes_json or (
        passes_for_bar(bar, kerf_mm) if new_schema else []
    )

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
    story.append(Paragraph(f"İş Emri – {task.key}", styles['title']))
    story.append(Paragraph(task.name, styles['subtitle']))

    story.append(_info_table([
        ['Malzeme',    task.material,
         'Stok boyu',  f"{task.stock_length_mm} mm"
                       + (' (stoktan)' if task.is_remnant_bar else '')],
        ['Oturum',     session.key,  'Fire', f"{task.waste_mm} mm"],
        ['Verimlilik', f"{eff} %",   'Tarih', str(date.today())],
        ['Hazırlayan', prepared_by,  'Testere payı', f"{kerf_mm:g} mm"],
    ]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(_CONVENTION_NOTE, styles['legend']))
    story.append(Paragraph(_STOP_NOTE, styles['legend']))
    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width='100%', thickness=1.5, color=DARK_BLUE))

    story.extend(_render_bar(bar, styles, USABLE_WIDTH, kerf_mm, ''))

    doc.build(story)
    return buffer.getvalue()
