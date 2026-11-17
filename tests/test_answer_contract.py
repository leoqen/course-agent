from korean.handoff import (answer_policy, check_answer_boundaries,
                            check_answer_contract, sentence_count, validate_handoff)


def test_direct_quotation_needs_its_own_sentence_evidence():
    sources = [{'kind': 'rag', 'evidence_id': 'D111111111111', 'text': '不保证通过或达到指定分数。'},
               {'kind': 'rag', 'evidence_id': 'D222222222222', 'text': '实际学习进展受基础影响。'}]
    bundles = [{'facts': [{'supports': [{'evidence_id': s['evidence_id'], 'quote': s['text']}]} for s in sources]}]
    assert check_answer_boundaries('原文“不保证通过或达到指定分数”[D222222222222]。', sources, bundles)
    assert check_answer_boundaries('原文“不保证通过或达到指定分数”。实际学习进展受基础影响[D222222222222]。', sources, bundles)
    assert not check_answer_boundaries('原文“不保证通过或达到指定分数”[D111111111111]。实际学习进展受基础影响[D222222222222]。', sources, bundles)
    assert not check_answer_boundaries('原文“不保证通过或达到指定分数”。[D111111111111]', sources, bundles)
    assert not check_answer_boundaries('| 效果 | 原文“不保证通过或达到指定分数” | [D111111111111] |', sources, bundles)


def test_requested_sentence_limit_triggers_contract_check_without_counting_decimal_dots():
    policy = answer_policy('只查课程，三句话即可', 'course')
    assert policy['max_sentences'] == 3
    assert sentence_count('学费1680.00元[D111111111111]。24节。每节50分钟。') == 3
    assert not check_answer_contract('第一句。第二句。第三句。', [], [], policy)
    assert any(i['reason'] == '超出用户要求句数' for i in check_answer_contract('一。二。三。四。', [], [], policy))
    assert answer_policy('简短回答', 'network')['max_sentences'] is None
    assert answer_policy('2句话回答', 'course')['max_sentences'] == 2


def test_unknown_explanation_is_not_forwarded_as_unverified_absence_assertion():
    item = {'subject': 'competitor_course', 'entity': '沪江TOPIK初级强化',
            'field': '现行入学要求', 'reason': '本次全部片段未出现TOPIK I/II名称'}
    bundle = validate_handoff({'facts': [], 'unknowns': [item]}, 'network', [], 'K03')
    unknown = bundle['unknowns'][0]
    assert unknown['entity'] == item['entity'] and unknown['field'] == item['field']
    assert '全部片段未出现' not in unknown['reason']
    assert '尚未确认' in unknown['reason']
