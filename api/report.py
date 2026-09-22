from io import BytesIO
from urllib.parse import quote
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
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


def build_report(pairs, direction):
    output=BytesIO()
    pdf=canvas.Canvas(output,pagesize=(842,595))
    pdf.setTitle('XM Property Matchmaker')
    style=ParagraphStyle('body',fontName='Helvetica',fontSize=10,leading=15,textColor=HexColor('#25324b'),wordWrap='CJK')
    months=['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember']
    now=datetime.now(ZoneInfo('Asia/Jakarta'))
    generated=f'{now.day:02d} {months[now.month-1]} {now.year}'
    logo=Path('/assets/brand-auto-audit.png')
    if not logo.exists(): logo=Path(__file__).resolve().parent.parent/'public/brand-auto-audit.png'
    page=0
    for index,(source,target) in enumerate(pairs,1):
        texts=[source.get('raw_text') or source['normalized_text'], (target.get('raw_text') or target.get('normalized_text','')) if target else 'Belum ada kecocokan.']
        # Escape chat markup; never interpret messages as HTML or links.
        paragraphs=[Paragraph(escape(t.encode("cp1252", "ignore").decode("cp1252")).replace('\n','<br/>'),style) for t in texts]
        chunks=[[p] for p in paragraphs]
        while any(chunks):
            page+=1
            pdf.drawImage(ImageReader(str(logo)),32,518,width=170,height=69,mask='auto',preserveAspectRatio=True)
            pdf.setFont('Helvetica',10);pdf.setFillColor(HexColor('#53617b'))
            pdf.drawRightString(810,560,'Generated on: '+generated)
            pdf.drawRightString(810,540,f'Pilihan {index} / {len(pairs)}')
            pdf.setStrokeColor(HexColor('#dbe3ef'));pdf.line(32,510,810,510)
            labels=['Buyer request','Property listing'] if direction=='buyer' else ['Property listing','Buyer request']
            for col,x in enumerate([32,432]):
                pdf.setFillColor(HexColor('#edf3fc'));pdf.roundRect(x,464,378,32,6,fill=1,stroke=0)
                pdf.setFillColor(HexColor('#1645a0'));pdf.setFont('Helvetica-Bold',12);pdf.drawString(x+12,475,labels[col])
                y=448
                pending=chunks[col]
                if pending:
                    p=pending.pop(0);_,h=p.wrap(354,354)
                    if h>354:
                        parts=p.split(354,354)
                        if parts:
                            p=parts[0];pending[0:0]=parts[1:];_,h=p.wrap(354,354)
                    p.drawOn(pdf,x+12,y-h)
                row=source if col==0 else target
                if row and row.get('contact_phone'):
                    phone=''.join(c for c in row['contact_phone'] if c.isdigit())
                    if phone.startswith('0'): phone='62'+phone[1:]
                    elif phone.startswith('8'): phone='62'+phone
                    pdf.setFillColor(HexColor('#146348'));pdf.roundRect(x+12,60,230,25,5,fill=1,stroke=0)
                    pdf.setFillColor(HexColor('#ffffff'));pdf.setFont('Helvetica-Bold',10)
                    pdf.drawString(x+22,69,'WhatsApp: +'+phone)
                    pdf.linkURL(contact_url(row, direction if col == 0 else ('property' if direction == 'buyer' else 'buyer')),(x+12,60,x+242,85),relative=0)
            pdf.setFillColor(HexColor('#53617b'));pdf.setFont('Helvetica',10)
            if target:
                status_badge(pdf, float(target['score']) >= 80)
            else:
                pdf.drawString(32,30,'Belum cocok')
            pdf.setFillColor(HexColor('#53617b'));pdf.setFont('Helvetica',10)
            pdf.drawRightString(810,30,f'XM Property Matchmaker | {page}')
            pdf.showPage()
    pdf.save()
    return output.getvalue()
