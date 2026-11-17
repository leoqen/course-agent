"""One bounded live main->course->RAG acceptance; no web/sales queries required."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx


async def main():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=20,trust_env=False) as c:
        health=(await c.get('/api/health')).json()
        if health['mode']!='live':raise RuntimeError('需要live模式服务，禁止用离线流程冒充验收')
        r=await c.post('/api/chat',json={'message':'只查课程，K03适合什么基础的学员？是否适用于TOPIK II中高级备考？请简短回答并引用原文。'})
        r.raise_for_status();tid=r.json().get('task_id')
        if not tid:raise RuntimeError('未建立课程任务')
        print('task_id',tid,flush=True)
        last=''
        for _ in range(180):
            task=(await c.get('/api/tasks/'+tid)).json()
            if task['status']!=last:print('status',task['status'],flush=True);last=task['status']
            if task['status'] not in {'RUNNING','QUEUED'}:break
            await asyncio.sleep(1)
        else:
            await c.post('/api/task/'+tid+'/cancel')
            raise RuntimeError('验收180秒超时，已取消，禁止重复付费请求')
        events=(await c.get('/api/tasks/'+tid+'/events')).json()
        sources=(await c.get('/api/tasks/'+tid+'/evidence')).json()
        checks={'success':task['status']=='SUCCEEDED','real_mode':task['metrics'].get('mode')=='live',
            'course_delegated':any(e['event']=='assistant_call' and e['data'].get('subagent_type')=='course' for e in events),
            'rag_evidence':bool(sources) and all(x['kind']=='rag' for x in sources),
            'original_documents':bool(sources) and all(x.get('chunk_id') and x.get('document_name') and x.get('text') for x in sources),
            'no_search':task['metrics'].get('search_calls')==0,
            'scope':task['request']['research_scope']=='course','no_files':not task['files'],
            'topic_boundary_mentioned':'TOPIK II' in task['report'] and '不' in task['report']}
        folder=Path(__file__).resolve().parents[1]/'data/acceptance';folder.mkdir(parents=True,exist_ok=True)
        (folder/'course-agent-live.json').write_text(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),
            'checks':checks,'task':task,'events':events,'evidence':sources,
            'note':'真实服务+合成已发布课程资料；机器检查不替代原文语义核对'},ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps({'checks':checks,'metrics':task['metrics'],'error':task['error']},ensure_ascii=False,indent=2))
        if not all(checks.values()):raise SystemExit(1)

if __name__=='__main__':asyncio.run(main())
