import pytest
import time
from unittest.mock import patch
from fastapi.testclient import TestClient

from korean.config import Settings
from korean.models import TaskRequest
from korean.store import Store
from korean.runtime import ResearchTools, Budget, validate_report, normalize_citations, append_sources
from korean.runtime import BudgetExceeded
from korean.server import create_app
from korean.handoff import check_answer_boundaries, validate_handoff, body_length


def test_delivery_expansion_and_usually_qualifier_are_rejected():
    source={'kind':'network','evidence_id':'W123456789abc','title':'韩语初级班',
            'content':'发音21课时+初级强化20课时+在线直播冲刺课程。通常工作日答复。'}
    def fact(value,quote,conditions=''):
        return {'subject':'competitor_course','entity':'韩语初级班','field':'方式或服务',
                'value':value,'applicability':'unconfirmed','conditions':conditions,
                'supports':[{'evidence_id':source['evidence_id'],'quote':quote,'entity_quote':'韩语初级班'}]}
    result=validate_handoff({'facts':[
        fact('课件课+直播冲刺','发音21课时+初级强化20课时+在线直播冲刺课程。'),
        fact('工作日答复','通常工作日答复。'),
        fact('通常工作日答复','通常工作日答复。'),
        fact('直播冲刺','在线直播冲刺课程。')],'unknowns':[]},'network',[source],'K03')
    assert len(result['facts'])==2 and len(result['rejected'])==2


def test_answer_checks_cell_citations_and_separate_metric_rule_evidence():
    sources=[{'kind':'rag','evidence_id':'D111111111111','text':'通常周二上课。'},
             {'kind':'rag','evidence_id':'D222222222222','text':'含24节直播课。'},
             {'kind':'sales','evidence_id':'Q111111111111'},
             {'kind':'sales_rules','evidence_id':'M111111111111'}]
    bundles=[{'facts':[{'supports':[{'evidence_id':s['evidence_id'],'quote':s['text']}]} for s in sources[:2]]}]
    bad='| 方式 | 24节直播课[D111111111111] |\n无法计算ROI，没有广告费用[Q111111111111]'
    assert len(check_answer_boundaries(bad,sources,bundles))==2
    good='| 方式 | 24节直播课[D222222222222]，通常周二上课[D111111111111] |\n无法计算ROI，没有广告费用[M111111111111]'
    assert not check_answer_boundaries(good,sources,bundles)
    # A citation-only table column is shared with this row's cells.
    assert not check_answer_boundaries('| 方式 | 直播 | [D222222222222] |',sources,bundles)
    assert not check_answer_boundaries('直播节数与回放本次未检索到[D111111111111]',sources,bundles)
    assert check_answer_boundaries('直播课程；回放本次未检索到[D111111111111]',sources,bundles)
    timed=[{'kind':'rag','evidence_id':'D333333333333','text':'工作日答疑，通常1个工作日内回复。'}]
    assert check_answer_boundaries('答疑1个工作日内回复[D333333333333]',timed,[])
    assert not check_answer_boundaries('答疑通常1个工作日内回复[D333333333333]',timed,[])


@pytest.mark.asyncio
async def test_rule_evidence_is_persisted_but_never_counts_as_sales_query(tmp_path):
    s=Settings(data=tmp_path,mode='offline');store=Store(tmp_path)
    task=store.create(TaskRequest(course_id='K01',research_scope='sales'))
    result=await ResearchTools(s,store,task,Budget(s)).schema()
    source=result['rules_evidence'];eid=source['evidence_id']
    assert source['kind']=='sales_rules' and eid.startswith('M')
    report=normalize_citations('无法计算ROI，依据'+eid,store.sources(task['id']))
    quality=validate_report(report,store.sources(task['id']))
    assert quality['rules_cited']==[eid] and not quality['cited_coverage']
    assert body_length(report)==10
    assert '非SQL查询结果' in append_sources(report,store.sources(task['id']))
    with pytest.raises(ValueError):normalize_citations('M000000000000',store.sources(task['id']))


@pytest.mark.parametrize('budget_stop',[False,True])
def test_schema_only_cannot_make_sales_task_succeed(tmp_path,budget_stop):
    async def only_schema(s,store,task,tools,budget,saver):
        value=await tools.schema()
        if budget_stop:raise BudgetExceeded('测试预算停止')
        return '不能计算ROI ['+value['rules_evidence']['evidence_id']+']'
    settings=Settings(data=tmp_path,mode='live',model='test',api_key='test')
    with patch('korean.server.live_report',only_schema),TestClient(create_app(settings)) as client:
        tid=client.post('/api/task',json={'course_id':'K01','research_scope':'sales'}).json()['task_id']
        for _ in range(200):
            task=client.get('/api/tasks/'+tid).json()
            if task['status'] not in {'QUEUED','RUNNING'}:break
            time.sleep(.01)
        assert task['status']=='FAILED'
        assert {s['kind'] for s in client.get(f'/api/tasks/{tid}/evidence').json()}=={'sales_rules'}
