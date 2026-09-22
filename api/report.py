from io import BytesIO
from urllib.parse import quote
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader


def status_badge(pdf, hot):
    # Vector emoji silhouettes remain sharp and portable without emoji fonts.
    pdf.saveState()
    pdf.setFillColor(HexColor('#fee2e2' if hot else '#ffedd5'))
    pdf.roundRect(32, 18, 108, 30, 10, fill=1, stroke=0)
    pdf.translate(44, 22)
    if hot:
        pdf.setFillColor(HexColor('#ef4444'))
        path = pdf.beginPath()
        path.moveTo(12, 23); path.curveTo(15, 14, 24, 13, 21, 5)
        path.curveTo(18, -3, 3, -1, 3, 8)
        path.curveTo(3, 13, 8, 17, 8, 19)
        path.curveTo(8, 13, 12, 12, 12, 23)
        pdf.drawPath(path, fill=1, stroke=0)
        pdf.setFillColor(HexColor('#fbbf24'))
        path = pdf.beginPath(); path.moveTo(13, 13)
        path.curveTo(13, 8, 18, 6, 15, 2); path.curveTo(8, -1, 6, 5, 13, 13)
        pdf.drawPath(path, fill=1, stroke=0)
    else:
        pdf.setStrokeColor(HexColor('#64748b')); pdf.setLineWidth(1.5)
        pdf.setFillColor(HexColor('#ffffff')); pdf.roundRect(9, 6, 7, 17, 3.5, fill=1, stroke=1)
        pdf.circle(12.5, 5, 5, fill=1, stroke=1)
        pdf.setStrokeColor(HexColor('#f97316')); pdf.setLineWidth(3); pdf.line(12.5, 5, 12.5, 18)
        pdf.setFillColor(HexColor('#f97316')); pdf.circle(12.5, 5, 3, fill=1, stroke=0)
    pdf.restoreState()
    pdf.setFont('Helvetica-Bold', 11)
    pdf.setFillColor(HexColor('#b91c1c' if hot else '#b45309'))
    pdf.drawString(80, 29, 'Hot' if hot else 'Warm')


def contact_url(row, kind):
    phone = ''.join(c for c in row['contact_phone'] if c.isdigit())
    if phone.startswith('0'): phone = '62' + phone[1:]
    elif phone.startswith('8'): phone = '62' + phone
    message = (f"Halo {row.get('contact_name') or 'Bapak/Ibu'}, saya ingin menindaklanjuti "
               f"{'kebutuhan properti' if kind == 'buyer' else 'listing properti'} yang Anda bagikan:\n\n"
               f"{(row.get('raw_text') or row.get('normalized_text') or '')[:500]}\n\n"
               "Apakah masih tersedia? Saya memiliki calon pasangan yang sesuai. "
               "Boleh saya meminta informasi lebih lanjut? Terima kasih.")
    return 'https://wa.me/' + phone + '?text=' + quote(message, safe='')


BODY_FONT_SIZE = 11
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 32
COLUMN_GAP = 18
COLUMN_WIDTH = (PAGE_WIDTH - 2 * MARGIN - COLUMN_GAP) / 2
TEXT_WIDTH = COLUMN_WIDTH - 24
BODY_TOP = PAGE_HEIGHT - 157
BODY_BOTTOM = 108
BODY_HEIGHT = BODY_TOP - BODY_BOTTOM


def fit_paragraph(text, width=TEXT_WIDTH, height=BODY_HEIGHT):
    """Keep the full text on one page, using 11 pt unless it needs to shrink."""
    markup = escape(text.encode('cp1252', 'ignore').decode('cp1252')).replace('\n', '<br/>')

    def measure(size):
        style = ParagraphStyle('body', fontName='Helvetica', fontSize=size,
                               leading=size * 1.35, textColor=HexColor('#25324b'), wordWrap='CJK')
        paragraph = Paragraph(markup, style)
        _, used_height = paragraph.wrap(width, height)
        return paragraph, used_height

    paragraph, used_height = measure(BODY_FONT_SIZE)
    if used_height <= height:
        return paragraph, used_height
    # Fit each column independently so a long listing does not shrink its buyer.
    # No continuation pages, clipping, or text truncation.
    lower, upper = 0, BODY_FONT_SIZE
    for _ in range(24):
        size = (lower + upper) / 2
        candidate, candidate_height = measure(size)
        if candidate_height <= height:
            lower = size
            paragraph, used_height = candidate, candidate_height
        else:
            upper = size
    return paragraph, used_height


def build_report(pairs, direction):
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    pdf.setTitle('XM Property Matchmaker')
    months = ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember']
    now = datetime.now(ZoneInfo('Asia/Jakarta'))
    generated = f'{now.day:02d} {months[now.month-1]} {now.year}'
    logo = Path('/assets/brand-auto-audit.png')
    if not logo.exists():
        logo = Path(__file__).resolve().parent.parent / 'public/brand-auto-audit.png'
    right = PAGE_WIDTH - MARGIN
    labels = ['Buyer request','Property listing'] if direction == 'buyer' else ['Property listing','Buyer request']
    for index, (source, target) in enumerate(pairs, 1):
        pdf.drawImage(ImageReader(str(logo)), MARGIN, PAGE_HEIGHT - 77,
                      width=170, height=69, mask='auto', preserveAspectRatio=True)
        pdf.setFont('Helvetica', 10)
        pdf.setFillColor(HexColor('#53617b'))
        pdf.drawRightString(right, PAGE_HEIGHT - 35, 'Generated on: ' + generated)
        pdf.drawRightString(right, PAGE_HEIGHT - 55, f'Pilihan {index} / {len(pairs)}')
        pdf.setStrokeColor(HexColor('#dbe3ef'))
        pdf.line(MARGIN, PAGE_HEIGHT - 85, right, PAGE_HEIGHT - 85)
        texts = [source.get('raw_text') or source.get('normalized_text', ''),
                 (target.get('raw_text') or target.get('normalized_text', '')) if target else 'Belum ada kecocokan.']
        for col, x in enumerate([MARGIN, MARGIN + COLUMN_WIDTH + COLUMN_GAP]):
            label_y = PAGE_HEIGHT - 142
            pdf.setFillColor(HexColor('#edf3fc'))
            pdf.roundRect(x, label_y, COLUMN_WIDTH, 32, 6, fill=1, stroke=0)
            pdf.setFillColor(HexColor('#1645a0'))
            pdf.setFont('Helvetica-Bold', 11)
            pdf.drawString(x + 12, label_y + 11, labels[col])
            paragraph, used_height = fit_paragraph(texts[col])
            paragraph.drawOn(pdf, x + 12, BODY_TOP - used_height)

        # Only the recommendation on the right has a WhatsApp action.
        if target and target.get('contact_phone'):
            x = MARGIN + COLUMN_WIDTH + COLUMN_GAP + 12
            phone = ''.join(c for c in target['contact_phone'] if c.isdigit())
            if phone.startswith('0'):
                phone = '62' + phone[1:]
            elif phone.startswith('8'):
                phone = '62' + phone
            pdf.setFillColor(HexColor('#146348'))
            pdf.roundRect(x, 60, TEXT_WIDTH, 25, 5, fill=1, stroke=0)
            pdf.setFillColor(HexColor('#ffffff'))
            pdf.setFont('Helvetica-Bold', 11)
            pdf.drawString(x + 10, 68, 'WhatsApp: +' + phone)
            pdf.linkURL(contact_url(target, 'property' if direction == 'buyer' else 'buyer'),
                        (x, 60, x + TEXT_WIDTH, 85), relative=0)
        if target:
            status_badge(pdf, float(target['score']) >= 80)
        else:
            pdf.setFillColor(HexColor('#53617b'))
            pdf.setFont('Helvetica', 11)
            pdf.drawString(MARGIN, 30, 'Belum cocok')
        pdf.setFillColor(HexColor('#53617b'))
        pdf.setFont('Helvetica', 9)
        pdf.drawRightString(right, 30, f'XM Property Matchmaker | {index}')
        pdf.showPage()
    pdf.save()
    return output.getvalue()
