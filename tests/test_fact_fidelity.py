"""Regression cases from r8 failures plus neighboring counterexamples.

Small synthetic excerpts isolate the failure mechanism; no network or paid model.
"""
from copy import deepcopy

import pytest

from korean.handoff import check_answer_boundaries, unsupported_terms, validate_handoff
from korean.web_context import web_sections


def own_fact(value, conditions=''):
    return {'subject': 'own_course', 'entity': 'K02', 'field': '排课', 'value': value,
            'applicability': 'current', 'conditions': conditions,
            'supports': [{'evidence_id': 'D111111111111',
                          'quote': '通常上课安排：周一、周三20:00—20:50。'}]}


def test_weekday_change_in_handoff_value_conditions_and_final_answer():
    source = {'kind': 'rag', 'evidence_id': 'D111111111111',
              'text': '通常上课安排：周一、周三20:00—20:50。'}
    result = validate_handoff({'facts': [own_fact('通常周一、周三上课'),
        own_fact('通常周一、周二上课'), own_fact('32节', '通常周一、周二上课')], 'unknowns': []},
        'course', [source], 'K02')
    assert len(result['facts']) == 1 and len(result['rejected']) == 2
    bundles = [result]
    bad = '| 课次 | 32节，通常周一、周二上课[D111111111111] |'
    assert any('星期' in i['reason'] for i in check_answer_boundaries(bad, [source], bundles))
    assert not check_answer_boundaries('通常星期一、星期三上课[D111111111111]', [source], bundles)


@pytest.mark.parametrize(('claim', 'quotes', 'rejected'), [
    ('不承诺保过', '不承诺考试通过、录取或就业。', False),
    ('不能用于TOPIK II中高级或保过', '不保证通过或达到指定分数。', False),
    ('承诺保过', '不承诺考试通过。', True),
    ('提供永久回放', '不提供永久回放。', True),
    ('不提供永久回放', '不含永久访问权。', False),
    ('通常排课，非永久固定', '通常周二上课。', False),
    ('本次未确认一对一陪练', '答疑区发帖。', False),
    ('未提一对一陪练', '助教答疑。', False),
    ('平台时效不代表课程提供一对一陪练', '24小时内回复。', False),
    ('不能据此视为一对一陪练承诺', '24小时内回复。', False),
    ('K03批改服务本次尚未确认', '课程介绍。', False),
    ('24小时内回复不等于一对一陪练', '24小时内回复。', False),
    ('陪练本次未确认，但提供直播', '答疑区发帖。', True),
    ('服务未知，提供永久陪练', '工作日答疑。', True),
    ('提供一对一陪练', '不提供24小时一对一陪练。', True),
])
def test_polarity_and_unknowns_do_not_disable_positive_promise_checks(claim, quotes, rejected):
    assert bool(unsupported_terms(claim, quotes)) is rejected


def test_office_hours_do_not_require_reply_duration_qualifier():
    source = {'kind': 'rag', 'evidence_id': 'D111111111111',
              'text': '工作日10:00—18:00提供课程答疑，通常1个工作日内回复。'}
    for claim in ('工作日10:00—18:00答疑', '通常1个工作日内回复'):
        assert not check_answer_boundaries(claim+'[D111111111111]', [source], [])
    assert check_answer_boundaries('1个工作日内回复[D111111111111]', [source], [])
    assert check_answer_boundaries('通常提供答疑；1个工作日内回复[D111111111111]', [source], [])


def test_outline_sections_prevent_cross_group_quote_and_name_stitching():
    text = ('课程汇总\n\n**二、适合有初级水平的你：**\n考前冲刺强化。\n'
            '初级语法6课时。\n\n**三、适合有中级水平的你：**\n'
            '适合已学完中级基础教材的学员。\n中级听力26课时。')
    sections = web_sections(text)
    assert len(sections) == 3
    assert '中级基础教材' not in sections[1]['content']
    source = dict(sections[1], kind='network', evidence_id='W111111111111',
                  title='课程汇总', section_scoped=True)
    fact = {'subject': 'competitor_course', 'entity': '韩语TOPIK中级强化', 'field': '入学基础',
            'value': '已学完中级基础教材', 'conditions': '', 'applicability': 'unconfirmed',
            'supports': [{'evidence_id': source['evidence_id'], 'quote': '考前冲刺强化。',
                          'entity_quote': '韩语TOPIK中级强化'}]}
    # A matching course name on another page cannot name this anonymous section.
    other = {'kind': 'network', 'evidence_id': 'W222222222222',
             'content': '韩语TOPIK中级强化，详情待查。'}
    result = validate_handoff({'facts': [fact], 'unknowns': []}, 'network', [source, other], 'K03')
    assert not result['facts'] and '对象' in result['rejected'][0]['reason']
    forged = deepcopy(fact)
    forged['supports'][0]['quote'] = '适合已学完中级基础教材的学员。'
    result = validate_handoff({'facts': [forged], 'unknowns': []}, 'network', [source, other], 'K03')
    assert not result['facts'] and '摘录' in result['rejected'][0]['reason']
    assert check_answer_boundaries('中级强化要求已学完中级基础教材[W111111111111]', [source], [])


def test_same_section_named_course_and_group_only_observation_are_allowed():
    source = {'kind': 'network', 'evidence_id': 'W111111111111', 'section_scoped': True,
              'section_path': ['三、适合有中级水平的你：'],
              'content': '三、适合有中级水平的你：\n韩语TOPIK中级强化\n适合已学完中级基础教材的学员。'}
    fact = {'subject': 'competitor_course', 'entity': '韩语TOPIK中级强化', 'field': '入学基础',
            'value': '已学完中级基础教材', 'conditions': '', 'applicability': 'unconfirmed',
            'supports': [{'evidence_id': source['evidence_id'], 'quote': '韩语TOPIK中级强化\n适合已学完中级基础教材的学员。',
                          'entity_quote': '韩语TOPIK中级强化'}]}
    assert validate_handoff({'facts': [fact], 'unknowns': []}, 'network', [source], 'K03')['facts']
    group = deepcopy(fact)
    group.update(entity='适合有中级水平的你', value='有中级水平')
    group['supports'][0].update(entity_quote='适合有中级水平的你', quote='三、适合有中级水平的你：')
    assert validate_handoff({'facts': [group], 'unknowns': []}, 'network', [source], 'K03')['facts']
    group['entity'] += '的TOPIK中级强化'
    assert not validate_handoff({'facts': [group], 'unknowns': []}, 'network', [source], 'K03')['facts']


def test_course_name_elsewhere_on_list_cannot_validate_another_courses_requirement():
    source = {'kind': 'network', 'evidence_id': 'W111111111111', 'title': '课程列表',
              'content': '韩语初级强化：适合有初级水平。\n韩语中级强化：适合已学完中级教材。'}
    fact = {'subject': 'competitor_course', 'entity': '韩语初级强化', 'field': '基础',
            'value': '已学完中级教材', 'conditions': '', 'applicability': 'unconfirmed',
            'supports': [{'evidence_id': source['evidence_id'], 'quote': '适合已学完中级教材。',
                          'entity_quote': '韩语初级强化'}]}
    result = validate_handoff({'facts': [fact], 'unknowns': []}, 'network', [source], 'K03')
    assert not result['facts'] and '对象名称或局部标题' in result['rejected'][0]['reason']
    fact['value'] = '有初级水平'
    fact['supports'][0]['quote'] = '韩语初级强化：适合有初级水平。'
    assert validate_handoff({'facts': [fact], 'unknowns': []}, 'network', [source], 'K03')['facts']


def test_markdown_parent_headings_are_retained_without_sibling_leakage():
    sections = web_sections('# 课程\n## 初级\n### 班型甲\n甲说明\n### 班型乙\n乙说明\n## 中级\n中说明')
    assert sections[2]['section_path'] == ['课程', '初级', '班型甲']
    assert '乙说明' not in sections[2]['content']
    assert sections[-1]['section_path'] == ['课程', '中级']
