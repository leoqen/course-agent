"""Render the latest saved Markdown to a shareable sample; never calls providers."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from korean.config import ROOT
from korean.pdf import write_pdf

if __name__ == '__main__':
    reports = sorted((ROOT/'data/artifacts').glob('*/调研报告.md'), key=lambda p:p.stat().st_mtime)
    if not reports:
        raise SystemExit('请先运行一份离线演示报告')
    out=ROOT/'output/pdf/韩语课程调研示例.pdf'
    out.parent.mkdir(parents=True,exist_ok=True)
    write_pdf(out,reports[-1].read_text('utf-8'))
    print(out)
