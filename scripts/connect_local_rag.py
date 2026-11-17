"""Link existing local course validation sources, never print or copy model keys."""
from pathlib import Path
import re
import secrets
import sys
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]


def update(path,fields):
    original=path.read_text('utf-8-sig') if path.exists() else ''
    for key,value in fields.items():
        line=key+'='+value
        if re.search(r'^'+re.escape(key)+r'=',original,re.M):
            original=re.sub(r'^'+re.escape(key)+r'=.*$',lambda _:line,original,flags=re.M)
        else:original=original.rstrip()+'\n'+line+'\n'
    path.write_text(original,'utf-8')


if __name__=='__main__':
    rag=ROOT.parent/'local_rag'
    if not (rag/'.env').is_file():raise SystemExit('相邻local_rag/.env不存在')
    source=dotenv_values(rag/'.env')
    if not source.get('DEEPSEEK_API_KEY'):raise SystemExit('现有RAG缺少模型配置')
    token=source.get('RESEARCH_TOKEN') or secrets.token_urlsafe(32)
    update(rag/'.env',{'RESEARCH_TOKEN':token})
    update(ROOT/'.env',{'RESEARCH_MODE':'live','RAG_BASE_URL':'http://127.0.0.1:8899',
        'RAG_RESEARCH_TOKEN':token,'RESEARCH_MODEL_ENV_FILE':(rag/'.env').as_posix()})
    print('共享令牌已配置，模型通过本地文件引用；未复制或输出模型密钥。')
