import httpx
import pytest

from korean.config import Settings
from scripts.acceptance_15 import source_preflight
from scripts.replay_synthesis import assess, prepare_record


@pytest.mark.asyncio
async def test_preflight_uses_retrieval_not_just_gateway_health():
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == '/api/health':
            return httpx.Response(200, json={'mode': 'live', 'model_configured': True})
        if request.url.path == '/api/research/retrieve':
            return httpx.Response(500, text='private infrastructure detail')
        raise AssertionError('No agent task may be submitted')

    async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RuntimeError, match='课程真实检索预检失败') as error:
            await source_preflight(client, [{'scope': 'course', 'course_id': 'K02'}], Settings())
    assert 'private infrastructure' not in str(error.value)
    assert calls == ['/api/health', '/api/research/retrieve']


@pytest.mark.asyncio
async def test_network_only_preflight_does_not_query_rag_or_pay_for_search():
    def handle(request):
        assert request.url.path == '/api/health'
        return httpx.Response(200, json={'mode': 'live', 'model_configured': True, 'search_configured': True})

    async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(handle)) as client:
        result = await source_preflight(client, [{'scope': 'network'}], Settings())
    assert result['required_sources'] == ['network']
    assert not result['model_connection_verified']


def test_synthesis_replay_keeps_recorded_tables_and_limits_separate_from_coverage():
    source = {'kind': 'rag', 'evidence_id': 'D111111111111', 'text': '课程目标。'}
    record = {'task': {'request': {'query': '两句话回答', 'research_scope': 'course'}},
              'evidence': [source], 'events': [{'event': 'specialist_handoff', 'data': {
                  'role': 'course', 'facts': [], 'rejected': [], 'tables': [{'rows': [[51, '126480.00']]}]}}]}
    request, sources, bundles = prepare_record(record)
    assert bundles[0]['tables'][0]['rows'] == [[51, '126480.00']]
    assert record['events'][0]['data']['rejected'] == []
    _, quality = assess('一。二。三。[D111111111111]', request, sources, bundles)
    assert quality['citations']['cited_coverage'] == ['rag']
    assert quality['boundary_issues'][0]['reason'] == '超出用户要求句数'
