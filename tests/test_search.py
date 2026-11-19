from unittest.mock import patch
import httpx
import pytest
from korean.config import Settings
from korean.models import TaskRequest
from korean.runtime import Budget, ResearchTools
from korean.store import Store


@pytest.mark.asyncio
async def test_live_search_preserves_snapshot_and_bounds_model_excerpt(tmp_path):
    settings=Settings(data=tmp_path, mode='live', tavily_key='test-search-key')
    store=Store(tmp_path)
    task=store.create(TaskRequest(course_id='K01',competitors=['示例'],research_scope='comparison'))
    content='课程正文。'*2000
    def handler(request):
        assert request.url.host=='api.tavily.com'
        return httpx.Response(200,json={'results':[{
            'title':'官方课程','url':'https://example.org/course','raw_content':content}]})
    real_client=httpx.AsyncClient
    with patch('korean.tools.httpx.AsyncClient',side_effect=lambda **kwargs:
               real_client(transport=httpx.MockTransport(handler),**kwargs)):
        items=await ResearchTools(settings,store,task,Budget(settings)).search('课程')
    assert len(items[0]['content'])==6000
    assert items[0]['model_excerpt_truncated']
    assert not items[0]['synthetic']
    assert store.sources(task['id'])[0]['content']==content
    assert items[0]['evidence_id']==store.sources(task['id'])[0]['evidence_id']


@pytest.mark.asyncio
async def test_live_search_sections_use_separate_ids_and_only_visible_prefix(tmp_path):
    settings=Settings(data=tmp_path, mode='live', tavily_key='test-search-key')
    store=Store(tmp_path)
    task=store.create(TaskRequest(course_id='K03',competitors=['示例'],research_scope='network'))
    content='课程汇总\n**二、适合有初级水平的你：**\n初级资料\n**三、适合有中级水平的你：**\n中级资料\n'+'。'*6000+'隐藏班型'
    def handler(request):
        return httpx.Response(200,json={'results':[{'title':'课程汇总','raw_content':content,'url':'https://example.org'}]})
    real_client=httpx.AsyncClient
    with patch('korean.tools.httpx.AsyncClient',side_effect=lambda **kwargs:
               real_client(transport=httpx.MockTransport(handler),**kwargs)):
        items=await ResearchTools(settings,store,task,Budget(settings)).search('TOPIK')
    assert len(items)==3 and len({i['evidence_id'] for i in items})==3
    assert sum(len(i['content']) for i in items)==6000
    assert '中级资料' not in items[1]['content']
    assert all(i['section_scoped'] and i['model_excerpt_truncated'] for i in items)
    assert '隐藏班型' not in str(items)
    assert [s['section_path'] for s in store.sources(task['id'])]==[i['section_path'] for i in items]


@pytest.mark.asyncio
async def test_user_search_limit_counts_provider_retries_and_blocks_extra_calls(tmp_path):
    settings = Settings(data=tmp_path, mode='live', tavily_key='test-search-key')
    store = Store(tmp_path)
    task = store.create(TaskRequest(course_id='K01', competitors=['示例'], research_scope='network', query='最多两次搜索'))
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json={'results': []})
    real_client = httpx.AsyncClient
    budget = Budget(settings)
    tools = ResearchTools(settings, store, task, budget)
    with patch('korean.tools.httpx.AsyncClient', side_effect=lambda **kwargs:
               real_client(transport=httpx.MockTransport(handler), **kwargs)):
        assert await tools.search('第一次') == []
        assert (await tools.search('不应发出'))['status'] == 'SEARCH_LIMIT_REACHED'
    assert len(calls) == budget.searches == 2
    assert budget.tools == 2
