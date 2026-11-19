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



def test_two_sentence_policy_and_repair_have_no_conflicting_minimum():
    from korean.prompts import revision_instruction
    policy = answer_policy('用两句话说明通常排课', 'course')
    assert policy['max_sentences'] == 2
    instruction = revision_instruction(policy)
    assert '最多2句' in instruction and '2至4句' not in instruction
    assert '不单独写“适合。”' in instruction
    assert any(i['reason'] == '超出用户要求句数'
               for i in check_answer_contract('适合。基础符合。目标明确。', [], [], policy))


def test_anchored_course_name_is_not_a_prose_quotation_but_claim_is_checked():
    eid = 'W111111111111'
    name = '韩语入门至生活会话流畅'
    source = {'kind': 'network', 'evidence_id': eid, 'content': name+'，列表标价0元起。'}
    bundles = [{'facts': [{'entity': name, 'supports': [{'evidence_id': eid,
                  'entity_quote': name, 'quote': name+'，列表标价0元起。'}]}]}]
    assert not check_answer_boundaries('| 沪江「'+name+'」 | 本次尚未确认现价['+eid+'] |', [source], bundles)
    assert check_answer_boundaries('「'+name+'提供全年无限次陪练」['+eid+']', [source], bundles)
    assert check_answer_boundaries('| 「另一门尚未定位的韩语课程」 | 未知 |', [source], bundles)
    # A name may contain a service term; naming it must not assert that service.
    assert check_answer_boundaries('提供一对一陪练['+eid+']', [source], bundles)


def test_no_guarantee_paraphrase_keeps_polarity_and_needs_evidence():
    eid = 'D111111111111'
    source = {'kind': 'rag', 'evidence_id': eid, 'text': '不保证通过或达到指定分数。'}
    assert not check_answer_boundaries('没有保过承诺['+eid+']', [source], [])
    assert check_answer_boundaries('提供保过承诺['+eid+']', [source], [])
    assert check_answer_boundaries('没有保过承诺', [source], [])
    assert check_answer_boundaries('没有保过承诺，但提供永久陪练['+eid+']', [source], [])


def test_retrieval_inventory_does_not_become_a_course_fact_or_page_absence():
    from korean.handoff import retrieval_status
    sources = [{'kind': 'network', 'evidence_id': 'W111111111111', 'content_type': 'page_text'},
               {'kind': 'network', 'evidence_id': 'W222222222222', 'content_type': 'search_summary'}]
    status = retrieval_status(sources)
    assert status['page_text_count'] == status['search_summary_count'] == 1
    policy = answer_policy('200字内说明是否确认完整售价', 'network')
    assert check_answer_contract('仅取得平台级价格说明。', sources, [], policy)
    assert check_answer_contract('没有取得任何正文。', sources, [], policy)
    assert not check_answer_contract('本次尚未确认口语班的现行完整售价。', sources, [], policy)
    assert not check_answer_contract('取得了平台价格说明。', sources, [], policy)


def test_partial_month_rankings_are_flagged_without_rejecting_tables_or_warnings():
    from korean.handoff import check_month_comparisons
    bundles = [{'facts': [], 'tables': [{'type': 'monthly', 'rows': [
        {'month': '2026-08', 'start': '2026-08-10', 'end_exclusive': '2026-09-01'},
        {'month': '2026-09', 'start': '2026-09-01', 'end_exclusive': '2026-10-01'}]}]}]
    assert check_month_comparisons('9月订单与净收款高于8月。', bundles)
    assert check_month_comparisons('2026年9月收款比2026年8月增长。', bundles)
    assert check_month_comparisons('8月与9月不宜直接比较，但9月收款高于8月。', bundles)
    assert not check_month_comparisons('8月为不完整月份，不能与9月直接计算环比。', bundles)
    assert not check_month_comparisons('| 2026-08 | 51 | 126480 |\n| 2026-09 | 76 | 188480 |', bundles)
    assert not check_month_comparisons('8月日均订单低于9月。', bundles)
    full = [{'facts': [], 'tables': [{'type': 'monthly', 'rows': [
        {'month': '2026-08', 'start': '2026-08-01', 'end_exclusive': '2026-09-01'},
        {'month': '2026-09', 'start': '2026-09-01', 'end_exclusive': '2026-10-01'}]}]}]
    assert not check_month_comparisons('9月订单高于8月。', full)
