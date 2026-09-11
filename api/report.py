from io import BytesIO
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader


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
                    pdf.setFillColor(HexColor('#146348'));pdf.roundRect(x+12,60,230,25,5,fill=1,stroke=0)
                    pdf.setFillColor(HexColor('#ffffff'));pdf.setFont('Helvetica-Bold',10)
                    pdf.drawString(x+22,69,'WhatsApp: +'+phone)
                    pdf.linkURL('https://wa.me/'+phone,(x+12,60,x+242,85),relative=0)
            pdf.setFillColor(HexColor('#53617b'));pdf.setFont('Helvetica',10)
            status=('Hot' if float(target['score'])>=80 else 'Warm')+f" - {float(target['score']):.0f} poin" if target else 'Belum cocok'
            pdf.drawString(32,30,status);pdf.drawRightString(810,30,f'XM Property Matchmaker | {page}')
            pdf.showPage()
    pdf.save()
    return output.getvalue()
