"""Small, escaped Markdown renderer for downloadable research reports."""
import html
import os
from pathlib import Path
import re


def write_pdf(path, report):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    font = 'STSong-Light'
    candidates = [os.getenv('RESEARCH_PDF_FONT', ''), 'C:/Windows/Fonts/simsun.ttc']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            pdfmetrics.registerFont(TTFont('ResearchCJK', candidate, subfontIndex=0))
            font = 'ResearchCJK'
            break
    if font == 'STSong-Light':
        pdfmetrics.registerFont(UnicodeCIDFont(font))
    body = ParagraphStyle('Body', fontName=font, fontSize=10, leading=15,
                          wordWrap='CJK', spaceAfter=5, splitLongWords=True)
    heading = ParagraphStyle('Heading', parent=body, fontSize=15, leading=22,
                             textColor=colors.HexColor('#164e63'), spaceBefore=10, spaceAfter=7, keepWithNext=True)
    small = ParagraphStyle('Small', parent=body, fontSize=8, leading=12)
    width = A4[0]-80

    def plain(text):
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1（\2）', text)
        text = text.replace('**', '').replace('`', '').replace('⚠', '提示：')
        return html.escape(text)

    flow = [Paragraph('韩语课程经营调研报告', ParagraphStyle('Title', parent=heading,
                       fontSize=21, leading=29, alignment=TA_CENTER)), Spacer(1, 12)]
    lines = report.splitlines()
    i = 0
    code = False
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('```'):
            code = not code
            i += 1
            continue
        if line.startswith('|') and not code:
            cells = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                raw = [x.strip() for x in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', x) for x in raw):
                    cells.append(raw)
                i += 1
            count = max(len(row) for row in cells)
            table = Table([[Paragraph(plain(x), small) for x in row+['']*(count-len(row))]
                          for row in cells], colWidths=[width/count]*count, repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e0f2fe')),
                ('GRID', (0,0), (-1,-1), .4, colors.HexColor('#b5c7ce')),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 7), ('RIGHTPADDING', (0,0), (-1,-1), 7),
                ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ]))
            flow.extend([table, Spacer(1, 9)])
            continue
        if not line:
            flow.append(Spacer(1, 5))
        elif line.startswith('#') and not code:
            flow.append(Paragraph(plain(line.lstrip('#').strip()), heading))
        else:
            flow.append(Paragraph(plain(line), small if code else body))
        i += 1

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#526575'))
        canvas.drawString(40, 24, '自家课程与销售为合成验证数据 | 来源详见报告附录')
        canvas.drawRightString(A4[0]-40, 24, str(doc.page))
        canvas.restoreState()

    SimpleDocTemplate(str(path), title='韩语课程调研报告', pagesize=A4,
                      leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=42).build(
                          flow, onFirstPage=footer, onLaterPages=footer)
