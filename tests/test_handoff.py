from copy import deepcopy

from korean.handoff import answer_policy, body_length, validate_handoff
from korean.handoff import SalesResult
from pydantic import ValidationError
import pytest


def fact(eid='W123456789abc', quote='本历史班采用课件课', **updates):
    return {'subject': 'competitor_course', 'entity': '沪江音标班', 'field': '方式',
            'value': '课件课', 'applicability': 'historical', 'conditions': '2011年班期',
            'supports': [{'evidence_id': eid, 'quote': quote, 'entity_quote': '沪江音标班'}], **updates}


def test_handoff_rejects_wrong_source_invented_quotes_and_unseen_tail():
    source={'kind':'network','evidence_id':'W123456789abc',
            'title':'沪江音标班', 'content':'本历史班采用课件课'+'。'*6000+'末尾独有服务条款'}
    values=[fact(),fact(quote='平台提供全天陪练'),fact(quote='末尾独有服务条款'),
            fact(eid='D123456789abc'),fact(quote='  \n  ')]
    result=validate_handoff({'facts':values,'unknowns':[]},'network',[source],'K01')
    assert len(result['facts'])==1 and len(result['rejected'])==4
    assert result['facts'][0]['conditions']=='2011年班期'
    assert result['facts'][0]['applicability']=='historical'


def test_handoff_separates_own_competitor_and_other_course():
    sources=[{'kind':'network','evidence_id':'W123456789abc','content':'本历史班采用课件课'},
             {'kind':'rag','evidence_id':'D123456789abc','text':'工作日通常一个工作日内回复。'}]
    result=validate_handoff({'facts':[fact(entity='沪江K01'),fact(subject='own_course')],
        'unknowns':[{'subject':'competitor_course','entity':'沪江K01','field':'售价','reason':'本次未取得'}]},
        'network',sources,'K01')
    assert not result['facts'] and not result['unknowns'] and len(result['rejected'])==3
    own=fact(eid='D123456789abc',quote='通常一个工作日内回复',subject='own_course',
             entity='K01',field='答疑',value='通常一个工作日内回复',conditions='工作日',applicability='unconfirmed')
    other=deepcopy(own);other['entity']='K02'
    result=validate_handoff({'facts':[own,other],'unknowns':[]},'course',sources,'K01')
    assert len(result['facts'])==1 and len(result['rejected'])==1


def test_answer_policy_counts_body_without_citations_or_whitespace():
    assert answer_policy('回答不超过400字并引用','network')['max_characters']==400
    assert answer_policy('300字以内回答','comparison')['max_characters']==300
    assert answer_policy('简洁回答','full')['max_characters']==650
    assert body_length('通常回复 [W123456789abc]\n')==4


def test_sales_schema_rejects_model_rewriting_tool_values():
    assert SalesResult(facts=[],unknowns=[]).model_dump()=={'facts':[],'unknowns':[]}
    with pytest.raises(ValidationError):
        SalesResult(facts=[fact()],unknowns=[])
