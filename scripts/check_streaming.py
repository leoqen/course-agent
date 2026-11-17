"""One real course-only request, observe SSE text before the final result."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import httpx


async def main():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=180,trust_env=False) as client:
        health=(await client.get('/api/health')).json()
        if health['mode']!='live':raise RuntimeError('需要live模式')
        r=await client.post('/api/chat',json={'message':'只查课程，K03适合什么基础？是否用于TOPIK II备考？请用三句话回答并引用原文。'})
        r.raise_for_status()
        tid=r.json()['task_id']
        print('task_id',tid,flush=True)
        frames=[]
        try:
            async with asyncio.timeout(180):
                async with client.stream('GET',f'/api/tasks/{tid}/stream') as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith('data: '):
                            frames.append({'received_at':datetime.now(timezone.utc).isoformat(),'data':json.loads(line[6:])})
        except TimeoutError:
            await client.post('/api/task/'+tid+'/cancel')
            raise RuntimeError('超时已取消，不自动重跑付费任务')
        task=(await client.get('/api/tasks/'+tid)).json()
        deltas=[f for f in frames if f['data'].get('event')=='answer_delta']
        final=next((i for i,f in enumerate(frames) if f['data'].get('task',{}).get('status') in {'SUCCEEDED','PARTIAL','FAILED','CANCELLED'}),len(frames))
        checks={'success':task['status']=='SUCCEEDED','multiple_deltas':len(deltas)>1,
                'text_before_final':any(f['data'].get('event')=='answer_delta' for f in frames[:final]),
                'saved_report':bool(task['report']),'cleared_draft':not task.get('draft')}
        folder=Path(__file__).resolve().parents[1]/'data/acceptance'
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'streaming-live.json').write_text(json.dumps({'checks':checks,'frames':frames,'task':task},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'checks':checks,'deltas':len(deltas),'metrics':task['metrics']},ensure_ascii=False),flush=True)
        if not all(checks.values()):raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
