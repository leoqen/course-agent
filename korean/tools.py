"""Source adapters: Tavily, course RAG and read-only sales tools."""
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .sales import Sales
from .web_context import web_sections


class ResearchTools:
    def __init__(self, settings, store, task, budget):
        self.s, self.store, self.task, self.budget = settings, store, task, budget
        self.tid = task['id']
        self.sales = Sales(settings, offline=settings.mode == 'offline')
        self.errors = []
        self.handoffs = []
        requested = re.search(r'最多\s*([一二两三四五六七八九十]|\d{1,2})\s*次(?:联网)?搜索', task['request'].get('query', ''))
        number = requested.group(1) if requested else None
        self.search_limit = (int(number) if number and number.isdigit() else
                             2 if number == '两' else '一二三四五六七八九十'.index(number)+1 if number else None)

    async def io(self, name, fn, search=False):
        for attempt in range(2):
            if search and self.search_limit is not None and self.budget.searches >= self.search_limit:
                self.store.event(self.tid, 'search_limit', '已达到用户指定搜索次数，使用已有证据整合')
                return {'status': 'SEARCH_LIMIT_REACHED', 'results': [],
                        'instruction': '已达到用户指定搜索次数，不再搜索；使用已取得证据，缺失字段明确尚未确认。'}
            self.budget.take('tools')
            if search:
                self.budget.take('searches')
            self.store.event(self.tid, 'tool_start', name, {'attempt': attempt+1})
            try:
                return await fn()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == 0 and (not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500 or exc.response.status_code == 429):
                    continue
                raise

    async def search(self, query: str):
        """Search public competing Korean courses; preserve evidence IDs and snapshot dates."""
        if self.s.mode == 'offline':
            async def sample():
                return {'results': [{'title': '离线示例机构公开课程（虚构）', 'url': 'https://example.org/korean-course',
                    'content': '虚构竞品：线上录播零基础韩语课，30节，每节30分钟，标价1280元；有效期180天；未披露答疑时间。仅测试数据。'}]}
            payload = await self.io('网络搜索（离线合成样例）', sample, search=True)
        else:
            if not self.s.tavily_key:
                raise RuntimeError('未配置 TAVILY_API_KEY')
            async def call():
                async with httpx.AsyncClient(timeout=35, trust_env=False) as c:
                    r = await c.post('https://api.tavily.com/search', json={'api_key': self.s.tavily_key, 'query': query,
                        'max_results': 5, 'include_raw_content': True})
                    r.raise_for_status()
                    return r.json()
            payload = await self.io('联网搜索', call, search=True)
        if payload.get('status') == 'SEARCH_LIMIT_REACHED':
            return payload
        items = []
        for r in payload.get('results', []):
            raw = r.get('raw_content')
            content = raw or r.get('content') or ''
            # Split only the visible prefix. A longer stored snapshot must never
            # become extra model evidence during validation or answer revision.
            sections = web_sections(content[:6000])
            for index, section in enumerate(sections):
                saved = self.store.evidence(self.tid, 'network', {'query': query, 'url': r.get('url'),
                    'title': r.get('title'), 'captured_at': datetime.now(timezone.utc).isoformat(),
                    'published_at': r.get('published_date'),
                    'content': content[:30000] if len(sections) == 1 else section['content'],
                    'section_path': section['section_path'], 'section_index': index,
                    'section_scoped': len(sections) > 1,
                    'stored_content_truncated': len(content)>30000,
                    'content_type': 'page_text' if raw else 'search_summary', 'synthetic': self.s.mode == 'offline'})
                items.append(saved | {'content': section['content'],
                    'model_excerpt_truncated': len(content)>6000,
                    'excerpt_note': '仅展示原页面前6000字符并按标题分段；其他片段或页面的班型不可套用。' if len(sections)>1 else
                        '仅展示前6000字符；未展示部分不可视为已阅读。' if len(content)>6000 else ''})
        return items

    async def retrieve(self, query: str):
        """Retrieve own-course original document chunks, not customer-sales dialogue."""
        req = self.task['request']
        if self.s.mode == 'offline':
            async def sample():
                root = Path(__file__).resolve().parents[1] / 'examples'
                return {'status': 'OK', 'ranking': {'status': 'OFFLINE_SNAPSHOT'}, 'items': [
                    {'document_name': p.name, 'chunk_id': p.stem, 'text': p.read_text('utf-8'), 'page': None,
                     'section_path': '离线原稿快照，包含多个课程，请按课程区分'} for p in sorted(root.glob('*.md')) if p.name != 'README.md']}
            payload = await self.io('课程资料（离线合成原稿）', sample)
        else:
            if not self.s.rag_token:
                raise RuntimeError('未配置 RAG_RESEARCH_TOKEN')
            async def call():
                async with httpx.AsyncClient(timeout=75, trust_env=False) as c:
                    r = await c.post(self.s.rag_url.rstrip('/')+'/api/research/retrieve', headers={'X-Research-Token': self.s.rag_token},
                        json={'query': query, 'course_id': req['course_id'], 'top_k': 6})
                    r.raise_for_status()
                    return r.json()
            payload = await self.io('自家课程资料检索', call)
        return {'status': payload.get('status'), 'ranking': payload.get('ranking'), 'items': [self.store.evidence(self.tid, 'rag',
            dict(x, retrieved_at=datetime.now(timezone.utc).isoformat(), synthetic=True)) for x in payload.get('items', [])]}

    async def schema(self):
        """Read sales schema, synthetic-data range and metric definitions before querying."""
        async def call():
            value = self.sales.schema()
            rules = self.store.evidence(self.tid, 'sales_rules', {
                'title': '销售指标口径与数据能力', 'rules': value['rules'],
                'ddl': value['ddl'], 'date_range': value['date_range'],
                'source_type': 'application_contract', 'synthetic': True})
            return value | {'rules_evidence': rules}
        return await self.io('销售表结构与统计口径', call)

    async def sql(self, query: str):
        """Execute one bounded read-only SELECT and preserve the actual result as evidence."""
        async def call():
            value = await asyncio.to_thread(self.sales.query, query)
            return self.store.evidence(self.tid, 'sales', value)
        return await self.io('销售数据库查询', call)

    async def monthly(self):
        """Fixed monthly calendar, aggregate in SQL and subtract using Decimal."""
        req = self.task['request']
        async def call():
            rows = await asyncio.to_thread(self.sales.monthly, req['course_id'], req['start_date'], req['end_date'])
            for row in rows:
                row['evidence'] = [self.store.evidence(self.tid, 'sales', q) for q in row.pop('queries')]
            return {'rows': rows, 'net_calculation': 'SQL分别聚合后以Decimal精确相减，保留无成交及仅退款月份'}
        return await self.io('销售月度统计（含空月份）', call)

    async def channels(self):
        req = self.task['request']
        async def call():
            value = await asyncio.to_thread(self.sales.channels, req['course_id'], req['start_date'], req['end_date'])
            return self.store.evidence(self.tid, 'sales', value)
        return await self.io('销售渠道成交与收款', call)
