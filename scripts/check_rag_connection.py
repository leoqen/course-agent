"""Small real retrieval acceptance, limited to two queries; saves no credentials."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from korean.config import Settings


async def main():
    s=Settings.env();output=[]
    async with httpx.AsyncClient(timeout=100,trust_env=False) as c:
        health=await c.get(s.rag_url+'/api/research/health')
        print('gateway',health.status_code,health.json())
        for cid,query,expected in [('K01','价格、课时和每节时长','1680'),('K03','适合什么基础？是否适用于TOPIK II中高级备考？','TOPIK')]:
            r=await c.post(s.rag_url+'/api/research/retrieve',headers={'X-Research-Token':s.rag_token},
                           json={'course_id':cid,'query':query,'top_k':6})
            if r.status_code!=200:raise RuntimeError('RAG HTTP '+str(r.status_code))
            payload=r.json()
            if not payload['items']:raise RuntimeError('RAG没有返回资料')
            if not all(x.get('chunk_id') and x.get('document_name') and x.get('text') for x in payload['items']):
                raise RuntimeError('资料缺少可追溯字段')
            text='\n'.join(x['text'] for x in payload['items'])
            matched=expected in text
            output.append({'course_id':cid,'query':query,'expected_term_found':matched,'response':payload})
            print(cid,'chunks',len(payload['items']),'ranking',payload.get('ranking',{}).get('status'),'expected_term',matched)
            if not matched:raise RuntimeError('未检索到验收关键字段')
    folder=s.data/'acceptance';folder.mkdir(parents=True,exist_ok=True)
    (folder/'rag-connection.json').write_text(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),
        'type':'real HTTP retrieval on synthetic published documents','checks':output},ensure_ascii=False,indent=2),'utf-8')

if __name__=='__main__':asyncio.run(main())
