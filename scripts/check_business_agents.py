"""One bounded live sales-only or three-source acceptance. No automatic reruns."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from korean.config import Settings
from korean.sales import Sales


async def main(args):
    s = Settings.env()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=20, trust_env=False) as client:
        health_response = await client.get('/api/health')
        health_response.raise_for_status()
        health = health_response.json()
        if health['mode'] != 'live' or not health['mysql_configured']:
            raise RuntimeError('需要已加载销售MySQL配置的live服务')
        if args.full:
            if not (health['search_configured'] and health['rag_configured']):
                raise RuntimeError('综合验收需要搜索和RAG配置')
            question = ('完整调研，自家K01，竞品：沪江网校。\n'
                '销售区间2026-08-01至2026-11-01。比较零基础课程的适用人群、方式、价格与课时，'
                '网络仅针对性搜索最多2次，未取得字段写本次未检索到；'
                '同时用SQL汇总本区间成交订单、收款、按退款发生时间的退款和净收款，'
                '列出8、9、10月订单与收款。简洁回答，数字附证据。'
                '最后提出2个待调查问题，不能断言竞品导致销量变化，不计算ROI或咨询转化率。')
        else:
            question = ('只查销售，K01在2026-08-01至2026-11-01的订单、收款和退款如何变化？'
                '请用SQL计算三个月合计成交订单、收款、按退款发生时间的退款和净收款，'
                '并按8、9、10月列出订单、收款、退款、净收款。'
                '收款与退款分别聚合，避免关联造成重复统计。简洁回答并引用查询证据；'
                '不查网络和课程文档，不把净收款叫利润，不计算ROI或咨询转化率。')
        response = await client.post('/api/chat', json={'message': question})
        response.raise_for_status()
        tid = response.json().get('task_id')
        if not tid:
            raise RuntimeError('未创建任务')
        print('task_id', tid, flush=True)
        previous = ''
        try:
            async with asyncio.timeout(300):
                while True:
                    response = await client.get('/api/tasks/' + tid)
                    response.raise_for_status()
                    task = response.json()
                    if task['status'] != previous:
                        print('status', task['status'], flush=True)
                        previous = task['status']
                    if task['status'] not in {'QUEUED', 'RUNNING'}:
                        break
                    await asyncio.sleep(1)
        except TimeoutError:
            await client.post('/api/task/' + tid + '/cancel')
            raise RuntimeError('300秒超时已取消，不自动重跑付费任务')
        events = (await client.get('/api/tasks/' + tid + '/events')).json()
        sources = (await client.get('/api/tasks/' + tid + '/evidence')).json()
        sales_sources = [x for x in sources if x['kind'] == 'sales']
        replay = []
        for source in sales_sources:
            actual = Sales(s).query(source['sql'])
            replay.append({'evidence_id': source['evidence_id'],
                'matches': actual['columns'] == source['columns'] and actual['rows'] == source['rows'],
                'truncated': source['truncated']})
        roles = {e['data'].get('subagent_type') for e in events if e['event']=='assistant_call'}
        normalized = task['report'].replace(',', '').replace('，', '').replace(' ', '')
        expected = json.loads((s.data / 'acceptance/sales-mysql-connection.json').read_text('utf-8'))
        totals = expected['k01_aug_oct']
        checks = {'success': task['status']=='SUCCEEDED', 'real_mode': task['metrics'].get('mode')=='live',
            'roles': roles==({'network', 'course', 'sales'} if args.full else {'sales'}),
            'coverage': {x['kind'] for x in sources if x['kind'] != 'sales_rules'}==({'network','rag','sales'} if args.full else {'sales'}),
            'sql_replay': bool(replay) and all(x['matches'] and not x['truncated'] for x in replay),
            'total_amounts_present': all(str(v).split('.')[0] in normalized for v in totals.values()),
            'no_files': not task['files']}
        record = {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
            'task': task, 'events': events, 'evidence': sources, 'sql_replay': replay, 'expected': totals,
            'note': '合成销售与课程，真实服务调用；数字出现检查不替代人工语义核对，SQL重放不代替独立统计参考'}
        name = 'full-business-agent-live.json' if args.full else 'sales-agent-live.json'
        serialized = json.dumps(record, ensure_ascii=False, indent=2)
        (s.data / 'acceptance' / (tid + '.json')).write_text(serialized, encoding='utf-8')
        target = s.data / 'acceptance' / name
        if target.exists():
            previous_record = json.loads(target.read_text('utf-8'))
            (target.parent / (previous_record['task']['id'] + '.json')).write_text(target.read_text('utf-8'), encoding='utf-8')
        target.write_text(serialized, encoding='utf-8')
        print(json.dumps({'checks': checks, 'metrics': task['metrics'], 'error': task['error'], 'saved': name}, ensure_ascii=False), flush=True)
        if not all(checks.values()):
            raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true')
    asyncio.run(main(parser.parse_args()))
