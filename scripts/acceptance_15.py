"""Fixed 15-case acceptance: 12 paid live tasks + 3 isolated local probes."""
import argparse
import asyncio
from collections import Counter
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import httpx
from korean.config import ROOT, Settings
from korean.models import TaskRequest, SCOPE_SOURCES
from korean.runtime import normalize_citations, validate_report
from korean.sales import Sales, money, validate_sql
from korean.server import create_app

CATALOG = ROOT / 'examples/acceptance_15.json'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def reference(case, body):
    """Plain Python/Decimal source reference, independent of SQL/tool output."""
    course = case['course_id']
    start, end = case.get('start_date', '2026-08-01'), case.get('end_date', '2026-11-01')
    orders = [o for o in body['orders'] if o[1] == course]
    ids = {o[0] for o in orders}
    if case.get('reference') == 'channels':
        channels = sorted({o[4] for o in orders if start <= o[2] < end})
        return [{'channel': channel, 'orders': len(selected),
                 'receipts': money(sum((Decimal(o[3]) for o in selected), Decimal(0)))}
                for channel in channels
                for selected in [[o for o in orders if o[4] == channel and start <= o[2] < end]]]
    if case.get('reference') != 'monthly':
        return None
    rows = []
    cursor, stop = date.fromisoformat(start), date.fromisoformat(end)
    while cursor < stop:
        boundary = min(date(cursor.year+(cursor.month == 12), cursor.month % 12+1, 1), stop)
        left, right = cursor.isoformat(), boundary.isoformat()
        paid = [o for o in orders if left <= o[2] < right and o[5] == 'PAID']
        receipts = sum((Decimal(o[3]) for o in paid), Decimal(0))
        refunds = sum((Decimal(r[3]) for r in body['refunds'] if r[1] in ids and left <= r[2] < right), Decimal(0))
        rows.append({'month': left[:7], 'orders': len(paid), 'receipts': money(receipts),
                     'refunds': money(refunds), 'net_receipts': money(receipts-refunds)})
        cursor = boundary
    return rows


def local_probe(case, folder):
    with tempfile.TemporaryDirectory(prefix='acceptance-', dir=folder) as tmp:
        s = Settings(data=Path(tmp), mode='offline')
        if case['probe'] == 'refund_only':
            sales = Sales(s, offline=True)
            with closing(sqlite3.connect(sales.path)) as c, c:
                c.execute('DELETE FROM refunds'); c.execute('DELETE FROM orders')
                c.execute("INSERT INTO orders VALUES('o1','K01','2026-05-31 23:59:00',1680,'自然咨询','PAID')")
                c.execute("INSERT INTO refunds VALUES('r1','o1','2026-06-01 00:00:00',840)")
                c.execute("INSERT INTO orders VALUES('end','K01','2026-08-01 00:00:00',1680,'自然咨询','PAID')")
            rows = sales.monthly('K01','2026-05-31','2026-08-01')
            checks = {'three_months':len(rows)==3, 'refund_only':rows[1]['orders']==0 and rows[1]['refunds']=='840.00',
                      'negative_net':rows[1]['net_receipts']=='-840.00', 'average_unknown':rows[1]['average'] is None,
                      'empty_and_end_excluded':rows[2]['orders']==0 and rows[2]['net_receipts']=='0.00'}
            return {'checks':checks,'actual':rows}
        if case['probe'] == 'sql_guard':
            blocked = {}
            for sql in ('DELETE FROM orders','SELECT * FROM orders; DELETE FROM refunds',
                        'SELECT * FROM local_rag.rag_files', "SELECT LOAD_FILE('/etc/passwd') FROM orders"):
                try: validate_sql(sql); blocked[sql]=False
                except (ValueError, Exception): blocked[sql]=True
            return {'checks':blocked}
        async def partial(settings, store, task, tools, budget, saver):
            item = store.evidence(task['id'],'network',{'url':'https://example.org','content':'合成测试网页'})
            tools.errors.append({'tool':'rag','type':'ConnectError'})
            return '合成测试，课程来源不可用。查询编号 '+item['evidence_id']
        async def empty(*args):
            return '本次无可用证据。'
        s.mode='live'; s.model='test'; s.api_key='test'
        def wait(client, tid):
            for _ in range(200):
                task=client.get('/api/tasks/'+tid).json()
                if task['status'] not in {'QUEUED','RUNNING'}:return task
                time.sleep(.01)
            raise RuntimeError('本地探针超时')
        with TestClient(create_app(s)) as client:
            with patch('korean.server.live_report',partial):
                tid=client.post('/api/task',json={'course_id':'K01','competitors':['测试机构']}).json()['task_id']
                first=wait(client,tid)
            with patch('korean.server.live_report',empty):
                tid=client.post('/api/task',json={'course_id':'K01','research_scope':'course'}).json()['task_id']
                second=wait(client,tid)
        fabricated=False
        try:normalize_citations('Q000000000000',[])
        except ValueError:fabricated=True
        return {'checks':{'partial':first['status']=='PARTIAL','failed':second['status']=='FAILED',
                'normalized_known':bool(re.search(r'\[W[a-f0-9]{12}\]',first['report'])),
                'reject_fabricated':fabricated},'partial':first,'empty':second}


async def live_case(client, case, folder, s, source):
    request = {'query':case['query'], 'course_id':case['course_id'], 'research_scope':case['scope'],
               'start_date':case.get('start_date','2026-08-01'), 'end_date':case.get('end_date','2026-11-01'),
               'competitors':['沪江网校'] if case['scope'] in {'full','comparison','network'} else [],
               'output_format':'none'}
    response=await client.post('/api/task',json=request)
    response.raise_for_status()
    accepted=response.json()
    tid=accepted['task_id']
    # Save task ID immediately so interrupted evaluation never blindly resubmits.
    save(folder/(case['id']+'.json'), {'case':case,'task_id':tid,'review_status':'running'})
    print(case['id'], 'started',tid,flush=True)
    try:
        async with asyncio.timeout(180):
            while True:
                response=await client.get('/api/tasks/'+tid)
                response.raise_for_status()
                task=response.json()
                if task['status'] not in {'QUEUED','RUNNING'}:break
                await asyncio.sleep(1)
    except TimeoutError:
        await client.post('/api/task/'+tid+'/cancel')
        task=(await client.get('/api/tasks/'+tid)).json()
    sources=(await client.get(f'/api/tasks/{tid}/evidence')).json()
    events=(await client.get(f'/api/tasks/{tid}/events')).json()
    checks={'completed':task['status']=='SUCCEEDED','real_mode':task['metrics'].get('mode')=='live'}
    try:
        quality=validate_report(task['report'],sources)
        checks['cited_sources']=SCOPE_SOURCES[case['scope']] <= set(quality['cited_coverage'])
    except ValueError:
        checks['cited_sources']=False
    checks['scope_isolation']={x['kind'] for x in sources} <= (SCOPE_SOURCES[case['scope']] |
        ({'sales_rules'} if 'sales' in SCOPE_SOURCES[case['scope']] else set()))
    replay=[]
    for item in sources:
        if item['kind']=='sales':
            actual=await asyncio.to_thread(Sales(s).query,item['sql'])
            replay.append({'evidence_id':item['evidence_id'], 'matches':actual['columns']==item['columns'] and actual['rows']==item['rows']})
    if replay:checks['sql_replay']=all(r['matches'] for r in replay)
    expected=reference(case,source)
    # Number presence is only a triage hint; reviewer must match each row/field.
    report_numbers={Decimal(n) for n in re.findall(r'(?<![A-Za-z0-9])\d+(?:\.\d+)?',task['report'].split('## 本次来源')[0].replace(',',''))}
    hints=None if expected is None else [{k:Decimal(str(v)) in report_numbers for k,v in row.items() if k not in {'month','channel'}} for row in expected]
    record={'case':case,'task':task,'evidence':sources,'events':events,'mechanical_checks':checks,
            'independent_reference':expected,'number_presence_hints':hints,'sql_replay':replay,
            'manual_review':None,'review_status':'needs_manual_review',
            'note':'机器检查与数字出现不能证明语义正确；需要人工核对每项事实和引用原文。'}
    save(folder/(case['id']+'.json'),record)
    print(case['id'],task['status'],'mechanical',all(checks.values()),'seconds',task['metrics'].get('seconds'),flush=True)


async def run(args):
    catalog_path=(args.catalog or CATALOG).resolve()
    catalog=json.loads(catalog_path.read_text('utf-8'))
    ids=[c['id'] for c in catalog]
    if len(set(ids))!=len(ids) or any(not re.fullmatch(r'[A-Z][0-9]{2}', cid) for cid in ids):
        raise ValueError('题目ID必须为唯一的大写字母和两位数字')
    selected=[c for c in catalog if args.mode=='all' or c['mode']==args.mode]
    if args.ids:selected=[c for c in selected if c['id'] in args.ids.split(',')]
    s=Settings.env()
    folder=args.output or s.data/'acceptance'/('fixed15-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True,exist_ok=True)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [catalog_path,*sorted((ROOT/'korean').glob('*.py'))]}
    manifest_path=folder/'manifest.json'
    if manifest_path.exists():
        if json.loads(manifest_path.read_text('utf-8'))['hashes']!=hashes:raise RuntimeError('代码或题目改变，请用新输出目录，不混合评测版本')
    else:save(manifest_path,{'timezone':'Asia/Shanghai','created':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                           'hashes':hashes,'cases':catalog,'model':s.model,'synthetic_own_data':True})
    source=json.loads((s.data/'sales-source.json').read_text('utf-8'))
    print('output',folder,flush=True)
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=20,trust_env=False) as client:
        if any(c['mode']=='live' and not (folder/(c['id']+'.json')).exists() for c in selected):
            health=(await client.get('/api/health')).json()
            if health['mode']!='live':raise RuntimeError('真实评测必须live')
        for case in selected:
            path=folder/(case['id']+'.json')
            if path.exists():
                print(case['id'],'already recorded, skipped (no automatic rerun)',flush=True)
                continue
            if case['mode']=='local':
                result=await asyncio.to_thread(local_probe,case,folder)
                save(path,{'case':case,'local_result':result,'review_status':'local_probe',
                           'note':'隔离测试数据与脚本桩，不是模型语义评测'})
                print(case['id'],'local',all(result['checks'].values()),flush=True)
            else:await live_case(client,case,folder,s,source)
    records=[json.loads((folder/(case['id']+'.json')).read_text('utf-8')) for case in selected if (folder/(case['id']+'.json')).exists()]
    save(folder/'summary.json',{'records':len(records),'live_records':sum('task' in r for r in records),
        'local_records':sum('local_result' in r for r in records),
        'live_statuses':dict(Counter(r['task']['status'] for r in records if 'task' in r)),
        'manual_review_required':True,'semantic_accuracy':None})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['all','local','live'],default='local')
    parser.add_argument('--ids',default='')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--catalog',type=Path,help='项目目录内的独立题库；新题结果不得与开发回归混算')
    asyncio.run(run(parser.parse_args()))
