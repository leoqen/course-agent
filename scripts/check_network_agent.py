"""Bounded real search / course-comparison acceptance. Each mode sends one task."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from korean.config import Settings
from korean.models import TaskRequest
from korean.runtime import Budget, ResearchTools
from korean.store import Store


async def main(args):
    settings = Settings.env()
    if settings.mode != 'live' or not settings.tavily_key:
        raise RuntimeError('需要live配置和TAVILY_API_KEY')
    folder = settings.data / 'acceptance'
    folder.mkdir(parents=True, exist_ok=True)
    if args.search_only:
        # This diagnostic writes to its own store, outside the user's chat history.
        store = Store(folder / 'network-probe')
        task = store.create(TaskRequest(course_id='K01', competitors=[args.competitor], research_scope='network'))
        budget = Budget(settings)
        sources = await ResearchTools(settings, store, task, budget).search(
            args.competitor + ' 韩语 零基础 课程 价格 课时 官网'
        )
        checks = {'nonempty': bool(sources), 'urls_and_content': bool(sources) and all(
            x.get('url', '').startswith(('http://', 'https://')) and x.get('content') for x in sources),
            'real_sources': bool(sources) and all(not x['synthetic'] for x in sources)}
        record = {'checks': checks, 'evidence': sources, 'metrics': budget.metrics()}
        name = 'network-search-live.json'
    else:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=20, trust_env=False) as client:
            health = (await client.get('/api/health')).json()
            if health['mode'] != 'live' or not health['search_configured']:
                raise RuntimeError('需要已加载搜索密钥的live服务，请重启调研服务')
            response = await client.post('/api/chat', json={'message':
                f'课程对比，自家K01，竞品：{args.competitor}。\n'
                '只比较双方韩语零基础课程的适用人群、教学方式、价格与课时，不查销售。'
                '优先竞品官方页面，找不到的字段写未公开；简洁回答并引用来源，不要仅凭搜索摘要认定现行价格。'})
            response.raise_for_status()
            tid = response.json().get('task_id')
            if not tid:
                raise RuntimeError('未创建课程对比任务')
            print('task_id', tid, flush=True)
            try:
                async with asyncio.timeout(240):
                    while True:
                        task_response = await client.get('/api/tasks/' + tid)
                        task_response.raise_for_status()
                        task = task_response.json()
                        if task['status'] not in {'QUEUED', 'RUNNING'}:
                            break
                        await asyncio.sleep(1)
            except TimeoutError:
                await client.post('/api/task/' + tid + '/cancel')
                raise RuntimeError('240秒超时，已取消；不自动重复付费任务')
            events = (await client.get('/api/tasks/' + tid + '/events')).json()
            sources = (await client.get('/api/tasks/' + tid + '/evidence')).json()
            delegated = {e['data'].get('subagent_type') for e in events if e['event'] == 'assistant_call'}
            checks = {'success': task['status'] == 'SUCCEEDED',
                'scope': task['request']['research_scope'] == 'comparison',
                'two_delegated': delegated == {'network', 'course'},
                'two_sources': {s['kind'] for s in sources} == {'network', 'rag'},
                'real_search': any(s['kind'] == 'network' and not s.get('synthetic', True) for s in sources),
                'real_mode': task['metrics'].get('mode') == 'live', 'no_files': not task['files']}
            record = {'checks': checks, 'task': task, 'events': events, 'evidence': sources}
            name = 'network-course-agent-live.json'
    record['checked_at'] = datetime.now(timezone.utc).isoformat()
    record['note'] = '真实网络/模型服务，自家课程为合成资料；机器检查不替代人工来源核对'
    (folder / name).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks, 'saved': name}, ensure_ascii=False), flush=True)
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--competitor', default='沪江网校')
    parser.add_argument('--search-only', action='store_true')
    asyncio.run(main(parser.parse_args()))
