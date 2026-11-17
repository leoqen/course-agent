import asyncio
from datetime import date
import json
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from korean.config import Settings
from korean.models import TaskRequest
from korean.runtime import Budget, BudgetExceeded, validate_report
from korean.sales import Sales, generate, validate_sql
from korean.server import create_app, write_pdf
from korean.store import Store, Conflict


@pytest.fixture
def settings(tmp_path):
    return Settings(data=tmp_path,mode='offline')


def test_generated_sales_against_independent_decimal_reference(settings):
    path=generate(settings.data)
    assert generate(settings.data)==path
    sales=Sales(settings,offline=True)
    golden=json.loads((settings.data/'sales-golden.json').read_text('utf-8'))
    for key,ref in golden.items():
        course,month=key.split('/')
        end=f'2026-{int(month[-2:])+1:02}-01'
        actual=sales.summary(course,month+'-01',end)
        for field in ['orders','receipts','refunds','net_receipts','average']:
            assert actual[field]==ref[field],(key,field)
    assert sales.query('SELECT COUNT(*) FROM orders')['rows'][0][0]==1800
    assert sales.query('SELECT * FROM orders')['truncated']
    assert sales.query('SELECT * FROM orders LIMIT 3')['truncated'] is False
    source=json.loads((settings.data/'sales-source.json').read_text('utf-8'))
    orders={o[0]:o for o in source['orders']}
    for refund in source['refunds']:
        assert refund[2]>=orders[refund[1]][2]
        assert float(refund[3])<=float(orders[refund[1]][3])


@pytest.mark.parametrize('sql',[
    'DELETE FROM orders','UPDATE orders SET amount=0','DROP TABLE orders',
    'SELECT * FROM orders; DELETE FROM orders','SELECT * FROM other.orders',
    'SELECT * FROM information_schema.tables','SELECT SLEEP(5) FROM orders',
    "SELECT LOAD_FILE('/etc/passwd') FROM orders",'SELECT * INTO OUTFILE "/tmp/x" FROM orders',
    'SELECT * FROM orders FOR UPDATE','SELECT @@version FROM orders',
    'WITH x AS (SELECT * FROM orders) SELECT * FROM x',
])
def test_sql_guard(sql):
    with pytest.raises((ValueError, Exception)):
        validate_sql(sql)


def test_refund_month_and_empty_base(settings):
    sales=Sales(settings,offline=True)
    with sqlite3.connect(sales.path) as c:
        c.execute('DELETE FROM refunds');c.execute('DELETE FROM orders')
        c.execute("INSERT INTO orders VALUES('o1','K01','2026-05-31 23:59:00',1680,'自然咨询','PAID')")
        c.execute("INSERT INTO refunds VALUES('r1','o1','2026-06-01 00:00:00',840)")
    may=sales.summary('K01','2026-05-01','2026-06-01')
    june=sales.summary('K01','2026-06-01','2026-07-01')
    assert may['orders']==1 and may['refunds']=='0.00'
    assert june['orders']==0 and june['refunds']=='840.00' and june['net_receipts']=='-840.00' and june['average'] is None


def test_store_conflict_history_recovery(settings):
    store=Store(settings.data)
    req=TaskRequest(course_id='K01',competitors=['机构'],thread_id='same')
    first=store.create(req)
    with pytest.raises(Conflict):store.create(req)
    e1=store.event(first['id'],'x','one');e2=store.event(first['id'],'x','two')
    assert store.events(first['id'],e1['seq'])[0]['seq']==e2['seq']
    store.recover()
    assert store.get(first['id'])['status']=='INTERRUPTED'
    second=store.create(req)
    assert first['id']!=second['id']
    assert store.events(first['id'])


def wait_task(client,tid):
    for _ in range(100):
        data=client.get('/api/tasks/'+tid).json()
        if data['status'] not in {'QUEUED','RUNNING'}:return data
        time.sleep(.03)
    raise AssertionError(data)


def test_offline_end_to_end_and_artifacts(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/health').json()['mode']=='offline'
        assert client.post('/api/task',json={'query':'韩语课'}).status_code==422
        body={'course_id':'K01','competitors':['离线示例机构'],'output_format':'both'}
        response=client.post('/api/task',json=body)
        assert response.status_code==202
        tid=response.json()['task_id'];result=wait_task(client,tid)
        assert result['status']=='SUCCEEDED',result
        assert '离线固定流程' in result['report']
        assert {s['kind'] for s in client.get(f'/api/tasks/{tid}/evidence').json()}=={'network','rag','sales','sales_rules'}
        assert result['metrics']['offline_fixture'] is True
        assert result['metrics']['model_calls']==0
        assert len(result['files'])==2
        for f in result['files']:
            r=client.get('/api/download/'+f['id']);assert r.status_code==200
            if f['name'].endswith('.pdf'):assert r.content.startswith(b'%PDF')
        assert client.get('/api/download/not-an-artifact').status_code==404
        assert client.get(f'/api/tasks/{tid}/events').json()
        # Retry creates new artifacts/evidence, preserving previous task.
        retry=client.post('/api/task',json=result['request'])
        assert retry.json()['task_id']!=tid


def test_cancel_conflict_and_upload_traversal(settings):
    async def slow(*args):
        await asyncio.sleep(10)
        return 'never'
    with patch('korean.server.offline_report',slow),TestClient(create_app(settings)) as client:
        req={'course_id':'K01','competitors':['机构'],'thread_id':'same'}
        tid=client.post('/api/task',json=req).json()['task_id']
        assert client.post('/api/task',json=req).status_code==409
        assert client.post('/api/task/'+tid+'/cancel').json()['status']=='CANCELLED'
        assert client.get('/api/tasks/'+tid).json()['status']=='CANCELLED'
        assert client.post('/api/upload',data={'thread_id':'same'},files={'files':('../outside.md',b'x')}).status_code==422
        assert client.post('/api/upload',data={'thread_id':'../../outside'},files={'files':('safe.md',b'x')}).status_code==422


def test_budget_and_fabricated_citation(settings):
    settings.max_tools=1
    budget=Budget(settings);budget.take('tools')
    with pytest.raises(BudgetExceeded):budget.take('tools')
    with pytest.raises(ValueError):validate_report('结论[W000000000000]',[])
    with pytest.raises(ValueError):validate_report('无引用',[{'evidence_id':'W111111111111','kind':'network'}])


def test_budget_partial_keeps_downloadable_evidence(settings):
    settings.max_tools=2
    with TestClient(create_app(settings)) as client:
        tid=client.post('/api/task',json={'course_id':'K01','competitors':['机构'],'output_format':'markdown'}).json()['task_id']
        task=wait_task(client,tid)
        assert task['status']=='PARTIAL',task
        assert '未完成报告' in task['report']
        assert len(task['files'])==1
        assert client.get('/api/download/'+task['files'][0]['id']).status_code==200


def test_missing_one_source_preserves_other_results(settings):
    async def partial(s,store,task,tools,budget,saver):
        sources=await tools.search('韩语')
        tools.errors.append({'tool':'rag','type':'ConnectError'})
        return '课程及销售来源不可用。合成测试竞品。['+sources[0]['evidence_id']+']'
    settings.mode='live';settings.model='test';settings.api_key='test'
    # Use fixture network data inside the live orchestration stub, no paid requests.
    async def fixture_search(self,query):
        return [self.store.evidence(self.tid,'network',{'title':'样例','url':'https://example.org',
                'captured_at':'2026-11-17','content_type':'search_summary','synthetic':True})]
    with patch('korean.server.live_report',partial),patch('korean.runtime.ResearchTools.search',fixture_search),TestClient(create_app(settings)) as client:
        tid=client.post('/api/task',json={'course_id':'K01','competitors':['机构']}).json()['task_id']
        task=wait_task(client,tid)
        assert task['status']=='PARTIAL',task
        assert task['report'] and task['metrics']['source_errors']


def test_unconfigured_live_fails_before_paid_calls(settings):
    settings.mode='live'
    with TestClient(create_app(settings)) as client:
        r=client.post('/api/task',json={'course_id':'K01','competitors':['机构']})
        assert r.status_code==503
        assert client.get('/api/tasks').json()==[]


def test_pdf_escapes_markup(tmp_path):
    file=tmp_path/'report.pdf'
    write_pdf(file,'中文报告\n<script>unsafe & text</script>')
    assert file.read_bytes().startswith(b'%PDF')
