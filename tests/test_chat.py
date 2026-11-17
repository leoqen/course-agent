from unittest.mock import patch
from fastapi.testclient import TestClient
from korean.config import Settings
from korean.server import create_app
from test_research import wait_task


def test_chat_clarifies_preserves_thread_and_exports_on_demand(tmp_path):
    with TestClient(create_app(Settings(data=tmp_path,mode='offline'))) as client:
        r=client.post('/api/chat',json={'message':'帮我对比一下韩语课程'})
        assert r.status_code==200
        thread=r.json()['thread_id']
        assert r.json()['status']=='clarification'
        r=client.post('/api/chat',json={'message':'自家K01，竞品：离线示例机构','thread_id':thread})
        assert r.status_code==200,r.text
        first=wait_task(client,r.json()['task_id'])
        assert first['status']=='SUCCEEDED',first
        assert first['files']==[]
        history=client.get('/api/conversations/'+thread).json()
        assert len(history['messages'])==3 and len(history['tasks'])==1
        assert history['messages'][-1]['task_id']==first['id']
        for kind in ('markdown','pdf'):
            f=client.post('/api/tasks/'+first['id']+'/export',json={'format':kind})
            assert f.status_code==200,f.text
            assert client.post('/api/tasks/'+first['id']+'/export',json={'format':kind}).json()['id']==f.json()['id']
            assert client.get('/api/download/'+f.json()['id']).status_code==200
        r=client.post('/api/chat',json={'message':'进一步分析渠道表现','thread_id':thread})
        second=wait_task(client,r.json()['task_id'])
        assert second['thread_id']==thread and second['request']['course_id']=='K01'
        assert second['request']['competitors']==['离线示例机构']
        assert second['id']!=first['id'] and second['files']==[]
        assert client.get('/api/conversations').json()[0]['thread_id']==thread


def test_chat_dates_and_file_choices(tmp_path):
    with TestClient(create_app(Settings(data=tmp_path,mode='offline'))) as client:
        r=client.post('/api/chat',json={'message':'对比K02，竞品：离线示例机构\n2026-06-01至2026-07-01','output_format':'pdf'})
        assert r.status_code==200,r.text
        task=wait_task(client,r.json()['task_id'])
        assert task['request']['start_date']=='2026-06-01'
        assert [f['name'] for f in task['files']]==['调研报告.pdf']
        assert client.post('/api/chat',json={'message':' '}).status_code==422
        assert client.post('/api/tasks/'+task['id']+'/export',json={'format':'exe'}).status_code==422


def test_export_rejects_unfinished_or_missing_answer(tmp_path):
    import asyncio
    async def slow(*args):await asyncio.sleep(10)
    with patch('korean.server.offline_report',slow),TestClient(create_app(Settings(data=tmp_path,mode='offline'))) as client:
        result=client.post('/api/chat',json={'message':'K01，竞品：离线示例机构'}).json()
        assert client.post('/api/tasks/'+result['task_id']+'/export',json={'format':'pdf'}).status_code==409
        assert client.post('/api/chat',json={'message':'继续','thread_id':result['thread_id']}).status_code==409
        client.post('/api/task/'+result['task_id']+'/cancel')


def test_course_comparison_excludes_sales_and_preserves_scope(tmp_path):
    from korean.models import ChatRequest
    from korean.conversation import resolve
    with patch('korean.runtime.ResearchTools.schema', side_effect=AssertionError('must not query sales')), \
         TestClient(create_app(Settings(data=tmp_path,mode='offline'))) as client:
        missing=client.post('/api/chat',json={'message':'课程对比，K01'}).json()
        assert missing['status']=='clarification'
        response=client.post('/api/chat',json={'message':'竞品：离线示例机构','thread_id':missing['thread_id']})
        task=wait_task(client,response.json()['task_id'])
        assert task['status']=='SUCCEEDED',task
        assert task['request']['research_scope']=='comparison'
        sources=client.get('/api/tasks/'+task['id']+'/evidence').json()
        assert {source['kind'] for source in sources}=={'network','rag'}
        assert task['files']==[]
        followup,question=resolve(ChatRequest(message='再详细说说适用人群'),task,[])
        assert question is None and followup.research_scope=='comparison'
        full,question=resolve(ChatRequest(message='改为完整调研，结合销售表现'),task,[])
        assert question is None and full.research_scope=='full'
