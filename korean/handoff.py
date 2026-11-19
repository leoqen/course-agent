"""Typed specialist handoffs; checks provenance, not semantic entailment."""
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import COURSES


CITATION = r'\[([WDQM][a-f0-9]{12})\]'
# Conservative literal checks for high-impact delivery/service terms. These are
# boundary checks, not a general natural-language entailment classifier.
BOUNDARY_TERMS = ('课件', '录播', '直播', '陪练', '批改', '保过', '永久', '一对一')


def _clauses(text):
    return re.split(r'[，,；;。\n]|但是|但|然而|不过', text.replace('**', ''))


def _uncertain(text):
    return bool(re.search(r'本次未|本次已展示片段未|尚未确认|未确认|未说明|不明|未知|待确认|未提(?:及)?|未见|'
                          r'不能(?:直接)?(?:证明|推出|等同|视为)|不能据此|不代表|不意味着|'
                          r'未就|无法(?:确认|证明)|不等于|并非.*承诺', text))


def _negative(text, start):
    return bool(re.search(r'(?:不提供|不含|不承诺|不保证|不能保证|没有|并无|无|非|不支持|不自动补)[^，；。]{0,8}$|'
                          r'不能用于[^，；。]{0,24}$', text[:start]))


def unsupported_terms(claim, quotes):
    """Limited local polarity checks; an unknown clause cannot hide its neighbor."""
    unsupported = []
    for clause in _clauses(claim):
        if _uncertain(clause):
            continue
        for term in BOUNDARY_TERMS:
            for occurrence in re.finditer(term, clause):
                negative = _negative(clause, occurrence.start())
                # A qualified schedule is not a promise of permanent access.
                if term == '永久' and '非永久固定' in clause and '通常' in quotes:
                    continue
                supported = any(_negative(q, m.start()) == negative
                                for q in _clauses(quotes) for m in re.finditer(term, q))
                if term == '保过' and negative and re.search(r'不(?:承诺|保证)(?:考试)?通过', quotes):
                    supported = True
                if not supported and term not in unsupported:
                    unsupported.append(term)
    return unsupported


def _weekdays(text):
    text = re.sub(r'(周|星期)([一二三四五六日天])([、和及与])([一二三四五六日天])',
                  r'\1\2\3\1\4', text)
    return {m.replace('天', '日') for m in re.findall(r'(?:周|星期)([一二三四五六日天])', text)}


def _timing_error(claim, quotes):
    # Only reply-duration assertions need the reply-duration qualifier. Merely
    # listing office hours does not turn a typical reply time into a guarantee.
    reply_duration = r'(?:\d+|[一两三])\s*(?:个)?(?:工作日|小时|分钟|天)(?:之)?内.{0,5}(?:回复|答复|答疑)|(?:回复|答复|答疑).{0,8}(?:\d+|[一两三])\s*(?:个)?(?:工作日|小时|分钟|天)(?:之)?内|工作日(?:回复|答复)'
    return ('通常' in quotes and any(re.search(reply_duration, c) and '通常' not in c and
            not _uncertain(c) for c in _clauses(claim)))


def _entity_key(text):
    return re.sub(r'\s+|[·：:（）()【】\[\]]', '', text).replace('Ⅱ', 'II').replace('Ⅰ', 'I').casefold()


def _anchored_quote(anchor, quote, source):
    """Name and claim must share an excerpt or an explicit local heading.

    A list containing many names is not enough: the excerpt must include the
    chosen name. A detail page title or a course heading can scope a short quote.
    """
    if _flat(anchor) in _flat(quote):
        return True
    headings = source.get('section_path', [])
    if not source.get('section_scoped'):
        headings = headings + [source.get('title') or '']
    return any(_flat(anchor) in _flat(h) for h in headings)


class Support(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence_id: str = Field(pattern=r'^[WDQ][a-f0-9]{12}$')
    quote: str = Field(min_length=2, max_length=600)
    entity_quote: str = Field(default='', max_length=160,
                              description='竞品课程名称或分组名称的逐字摘录，必须在同一证据片段中；无法定位对象时不要提取课程事实')


class Fact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: Literal['own_course', 'competitor_course', 'competitor_platform']
    entity: str = Field(min_length=1, max_length=160)
    field: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=400)
    applicability: Literal['current', 'historical', 'unconfirmed']
    conditions: str = Field(max_length=240)
    supports: list[Support] = Field(min_length=1, max_length=3)


class Unknown(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: Literal['own_course', 'competitor_course', 'competitor_platform']
    entity: str = Field(min_length=1, max_length=160)
    field: str = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=1, max_length=160)


class SpecialistResult(BaseModel):
    """Extract requested atomic facts; never write a narrative report here."""
    model_config = ConfigDict(extra='forbid')
    facts: list[Fact] = Field(max_length=18)
    unknowns: list[Unknown] = Field(max_length=8)


class SalesResult(SpecialistResult):
    """Sales values come directly from tool messages, never model extraction."""
    facts: list[Fact] = Field(max_length=0)
    unknowns: list[Unknown] = Field(max_length=0)


EXTRACTION_PROMPT = '''
最终必须调用绑定的结构化响应工具（SpecialistResult或SalesResult），不能写Markdown报告或建议长文。
facts仅提取用户所问的原子事实，每个字段都给出subject、entity、field、value、applicability、conditions和supports。
supports使用本次工具真实编号和逐字原文quote（不是你改写的句子，不引用未展示部分）。一条事实只涉及一个对象一个字段。
competitor_course每个support必须填写entity_quote：同一证据片段中逐字出现的完整课程名或分组名，entity必须包含这个名称。多课程列表的quote必须连同名称一起摘录；课程详情页标题或局部标题含名称时可引用其下短句。分组名只能支撑分组事实，不代表具体班型。缺课程名的汇总页不得借其他网页课程名拼接；可记录分组原文，具体班型归属写unknowns。
section_path是本片段标题层级，其他分组的基础要求不可套用；事实和对象都必须在同一片段内定位。
subject区分own_course、competitor_course、competitor_platform；平台承诺不得填成课程承诺。
entity写证据中的课程标题或平台名称。K01/K02/K03是自家内部编号，不得作为竞品编号。
历史班期标historical；无法确认现行的汇总/列表/平台文本标unconfirmed；current须有对应现行课程依据。
conditions保留“通常”、适用班期、非永久、限制条件等，不扩大承诺。不能从“直播冲刺”补写“录播”。
方式和服务字段尽量逐字摘取原文，不将课时构成改写成课件课，不把排课时段改写成直播；每种方式/服务必须在本条supports摘录中明确出现。
unknowns只记录用户所问且尚未确认的对象和字段。reason不得断言所有来源没有/全页没有/未出现某考试标注，不能用单片段未见概括全部检索。列表已经显示课程名时，未知的是该班型现行条款，而不是课程名是否出现。未知字段不塞进facts。
销售专家facts与unknowns均返回空数组：平台会将你实际调用的统计工具结果、表结构限制整理为结构化表格。
只提取当前请求需要的字段，不展开其他课程、不作因果分析，不生成重复来源清单。conditions只保留本字段的必要限制，不能顺带展开回放、教材、退费、排课等未问字段。平台答疑问题只需时效、平台适用范围和不能推断课程陪练，无需提取历史班型及整份平台规则。
network只返回竞品字段（包括unknowns），course只返回自家字段（包括unknowns）；不要替另一个专家补充缺失项。
'''


def _flat(text):
    return re.sub(r'\s+', '', text)


def validate_handoff(result, role, sources, course_id):
    """Drop unsupported IDs/quotes/objects; retain explicit rejection reasons."""
    result = SpecialistResult.model_validate(result)
    kind = {'network': 'network', 'course': 'rag', 'sales': 'sales'}[role]
    known = {s['evidence_id']: s for s in sources if s['kind'] == kind}
    accepted, unknowns, rejected = [], [], []

    def object_error(item):
        if role == 'sales':
            return '销售事实由实际工具表格提供'
        if role == 'course' and item.subject != 'own_course':
            return '课程专家仅处理自家课程'
        if role == 'network' and item.subject == 'own_course':
            return '网络专家不能提供自家事实'
        text = item.entity + ' ' + (item.value + ' ' + item.conditions if isinstance(item, Fact) else '')
        ids = set(re.findall(r'(?<![A-Za-z0-9])K0[123](?![A-Za-z0-9])', text, flags=re.I))
        if role == 'network' and ids:
            return '竞品对象包含自家内部编号'
        if role == 'course' and (any(i.upper() != course_id for i in ids) or
                any(c['name'] in text for cid, c in COURSES.items() if cid != course_id)):
            return '混入其他自家课程'
        return None

    for fact in result.facts:
        error = object_error(fact)
        for support in fact.supports:
            source = known.get(support.evidence_id)
            if not source:
                error = '证据不存在或来源类别错误'
                break
            visible = source.get('content', '')[:6000] if role == 'network' else source.get('text', '')
            if len(_flat(support.quote)) < 2 or _flat(support.quote) not in _flat(visible):
                error = '原文摘录不在模型取得的片段中'
                break
            if fact.subject == 'competitor_course':
                anchor = support.entity_quote
                local = visible + '\n' + '\n'.join(source.get('section_path', []))
                if not source.get('section_scoped'):
                    local += '\n' + (source.get('title') or '')
                if len(_flat(anchor)) < 4 or _flat(anchor) not in _flat(local) or _entity_key(anchor) not in _entity_key(fact.entity):
                    error = '竞品对象名称未在同一证据片段定位'
                    break
                if not _anchored_quote(anchor, support.quote, source):
                    error = '列表事实摘录未包含对象名称或局部标题'
                    break
                # A group heading supports the group, not a named course added
                # to it. Preserve such material as group-level observations.
                if re.search(r'适合.+(?:的你|人群)|基础(?:学员|人群)', anchor) and re.search(r'班|强化|全程|签约', fact.entity.replace(anchor, '')):
                    error = '分组依据不能绑定到未出现名称的具体班型'
                    break
        quotes = ''.join(s.quote for s in fact.supports)
        claim = fact.value + '；' + fact.conditions
        if not error and unsupported_terms(claim, quotes):
            error = '方式或服务超出所引摘录：' + '、'.join(unsupported_terms(claim, quotes))
        if not error and _weekdays(claim) - _weekdays(quotes):
            error = '上课星期超出所引摘录'
        if not error and _timing_error(claim, quotes):
            error = '答疑时效丢失通常限定'
        if error:
            rejected.append({'field': fact.field, 'reason': error})
        else:
            accepted.append(fact.model_dump())
    for item in result.unknowns:
        error = object_error(item)
        if error:
            rejected.append({'field': item.field, 'reason': error})
        else:
            # A specialist's absence explanation is not a verified search of
            # every visible page. Keep its precise entity/field, never promote
            # free-form absence assertions to synthesis evidence.
            unknowns.append(item.model_dump() | {'reason': '本次尚未确认该对象的此项信息；不能据此断言原页面或全部来源没有。'})
    return {'role': role, 'facts': accepted, 'unknowns': unknowns, 'rejected': rejected}


def answer_policy(query, scope):
    """Character budget is for the answer body, excluding citation IDs/appendix."""
    match = re.search(r'(\d{2,4})\s*字(?:以内|内|以下)?', query)
    limit = min(int(match.group(1)), 4000) if match else (
        650 if any(s in query for s in ['简短', '简洁', '简要', '表格即可', '几句话']) else
        1000 if scope in {'full', 'comparison'} else 650)
    sentence_match = re.search(r'([一二两三四五六七八九十]|\d{1,2})\s*句(?:话)?', query)
    sentence_limit = None
    if sentence_match:
        number = sentence_match.group(1)
        sentence_limit = int(number) if number.isdigit() else 2 if number == '两' else '一二三四五六七八九十'.index(number)+1
    return {'max_characters': limit, 'max_sentences': sentence_limit,
            'counting': '正文去引用编号及空白，不含来源附录',
            'instruction': '直接回答问题，少量表格或短段落；不重复调研范围/来源/发现章节，不输出内部工具名和编号说明。'}


def body_length(text):
    return len(re.sub(r'\s+|\[[WDQM][a-f0-9]{12}\]', '', text))


def sentence_count(text):
    text = re.sub(CITATION, '', text)
    return len([s for s in re.split(r'[。！？!?]+', text) if re.search(r'[\w\u4e00-\u9fff]', s)])


def _citation_units(cell):
    # A citation following a full stop still belongs to that sentence; a later
    # sentence's citation cannot justify an earlier quoted assertion. Decimal
    # dots are deliberately not sentence boundaries.
    return re.findall(r'[^。！？；;\n]+[。！？；;]?(?:\s*\[[WDQM][a-f0-9]{12}\])*', cell)


def check_answer_contract(report, sources, bundles, policy):
    issues = check_answer_boundaries(report, sources, bundles)
    issues.extend(check_retrieval_claims(report, sources))
    issues.extend(check_month_comparisons(report, bundles))
    if policy.get('max_sentences') and sentence_count(report) > policy['max_sentences']:
        issues.append({'reason': '超出用户要求句数', 'actual': sentence_count(report), 'limit': policy['max_sentences']})
    return issues


def retrieval_status(sources):
    """Describe retrieved material, independently of accepted fact extraction."""
    network = [s for s in sources if s['kind'] == 'network']
    return {'obtained_source_count': len(sources),
            'page_text_count': sum(s.get('content_type') == 'page_text' for s in network),
            'search_summary_count': sum(s.get('content_type') == 'search_summary' for s in network),
            'note': '计数为证据片段数，不是独立网页数；正文或摘要不等于现行条款已确认。'
                    '事实被过滤不代表没有取得正文。未知只针对具体对象字段，不总结为仅取得平台说明。'}


def check_retrieval_claims(report, sources):
    """Catch a narrow class of overbroad absence claims; not a page classifier."""
    issues = []
    status = retrieval_status(sources)
    for number, line in enumerate(report.splitlines(), 1):
        if re.search(r'(?:仅|只)(?:取得|获取|检索到|获得)(?:了|到)?平台(?:级)?', line):
            issues.append({'line': number, 'reason': '将字段未知扩大为仅取得平台资料；只说明具体对象字段尚未确认'})
        if status['page_text_count'] and re.search(r'(?:未|没有)(?:取得|获取|获得)(?:到)?任何(?:页面)?正文', line):
            issues.append({'line': number, 'reason': '已取得网页正文片段，不能写成未取得任何正文'})
    return issues


def check_month_comparisons(report, bundles):
    """Reject raw month-total rankings when one of the named months is partial."""
    partial = set()
    for bundle in bundles:
        for table in bundle.get('tables', []):
            if table.get('type') != 'monthly':
                continue
            for row in table['rows']:
                start, end = row.get('start', ''), row.get('end_exclusive', '')
                if start and end and (not start.endswith('-01') or not end.endswith('-01')):
                    partial.add(int(row['month'][-2:]))
    issues = []
    if not partial:
        return issues
    for number, line in enumerate(report.splitlines(), 1):
        for unit in _citation_units(line):
            text = re.sub(CITATION, '', unit)
            months = {int(m) for m in re.findall(r'(?<!\d)(?:20\d{2}[-年])?(1[0-2]|0?[1-9])月', text)}
            if len(months) < 2 or not months & partial:
                continue
            if not re.search(r'高于|低于|多于|少于|增长|下降|增加|减少|上升|环比', text):
                continue
            if re.search(r'不能|不可|不宜|不应|不作|不做|无法', text) and not re.search(r'但|然而|不过', text):
                continue
            # An explicit daily metric is not a raw monthly total comparison.
            if re.search(r'日均|每天|每日', text):
                continue
            issues.append({'line': number, 'reason': '不完整月份与其他月份不能直接按月总量排名或计算环比'})
    return issues


def check_answer_boundaries(report, sources, bundles):
    """Check local claim/citation boundaries; never attach a replacement citation."""
    known = {s['evidence_id']: s for s in sources}
    # Only accepted fact excerpts are used in multi-agent mode. A whole document
    # containing the word elsewhere must not validate the wrong fact's citation.
    excerpts = {}
    entities = set()
    for bundle in bundles:
        for fact in bundle['facts']:
            if fact.get('entity'):
                entities.add(_entity_key(fact['entity']))
            for support in fact['supports']:
                excerpts.setdefault(support['evidence_id'], []).append(support['quote'])
                if support.get('entity_quote'):
                    entities.add(_entity_key(support['entity_quote']))
    def direct_quotes(cell):
        # Exact names already anchored in accepted facts are labels, not prose
        # quotations. A longer assertion containing a name is still checked.
        return [q for q in re.findall(r'[“「]([^”」\n]+)[”」]', cell)
                if _entity_key(q) not in entities]
    issues = []
    for line_number, line in enumerate(report.splitlines(), 1):
        cells = line.strip().strip('|').split('|') if line.lstrip().startswith('|') else [line]
        trailing = cells[-1] if len(cells) > 1 else ''
        shared = re.findall(CITATION, trailing) if re.fullmatch(r'(?:\s*\[[WDQM][a-f0-9]{12}\]\s*)+', trailing) else []
        for cell in [unit for value in cells for unit in _citation_units(value)]:
            ids = re.findall(CITATION, cell) or shared
            if not ids:
                # Long direct quotations should be attributable, even if other
                # sentences in this paragraph happen to have valid citations.
                if any(len(_flat(q)) >= 6 for q in direct_quotes(cell)):
                    issues.append({'line': line_number, 'reason': '原文引语缺少就近引用'})
                if unsupported_terms(cell, ''):
                    issues.append({'line': line_number, 'reason': '方式或服务断言缺少就近引用'})
                continue
            quotes = ''.join(''.join(excerpts.get(eid, [])) for eid in ids)
            # Single-agent baseline has no handoffs; use the actual visible text.
            if not bundles:
                quotes = ''.join((known.get(eid, {}).get('content', '')[:6000] or
                                  known.get(eid, {}).get('text', '')) for eid in ids)
            if any(known.get(eid, {}).get('kind') in {'network', 'rag'} for eid in ids):
                for quoted in direct_quotes(cell):
                    if len(_flat(quoted)) >= 6 and not any(
                            _flat(quoted) in _flat(q) for eid in ids for q in excerpts.get(eid, [])
                            ) and (bundles or _flat(quoted) not in _flat(quotes)):
                        issues.append({'line': line_number, 'reason': '原文引语不在就近引用摘录中', 'quote': quoted})
                terms = unsupported_terms(cell, quotes)
                if terms:
                    issues.append({'line': line_number, 'reason': '方式或服务缺少同处引用支持', 'terms': terms})
                if _weekdays(cell) - _weekdays(quotes):
                    issues.append({'line': line_number, 'reason': '上课星期超出同处引用摘录'})
                if _timing_error(cell, quotes):
                    issues.append({'line': line_number, 'reason': '答疑时效丢失通常限定'})
                # Use the actual section to verify named course attribution.
                # A group-only observation must not become a specific course's
                # admission requirement merely because both have a valid W ID.
                for clause in _clauses(cell):
                    if _uncertain(clause) or not re.search(r'要求|适合|基础|已学完|具备', clause):
                        continue
                    for alias in re.findall(r'[\u4e00-\u9fff]{2,12}(?:强化|全程|签约班)', clause):
                        local_sources = [known[eid] for eid in ids if known.get(eid, {}).get('kind') == 'network']
                        located = any(_entity_key(alias) in _entity_key(
                                (s.get('content', '')[:6000]) + '\n' +
                                (s.get('title', '') if not s.get('section_scoped') else '')
                                ) for s in local_sources)
                        if bundles:
                            located = any(_entity_key(alias) in _entity_key(support.get('entity_quote', ''))
                                          and support['evidence_id'] in ids
                                          for bundle in bundles for fact in bundle['facts']
                                          for support in fact['supports'])
                        if local_sources and not located:
                            issues.append({'line': line_number, 'reason': '具体班型基础要求缺少同片段对象定位', 'entity': alias})
            if any(t in cell for t in ('咨询转化率', 'ROI', '线索', '广告费用', '广告费', '投放花费')) and any(
                    t in cell for t in ('没有', '缺少', '缺乏', '不能计算', '无法计算', '不可计算')):
                if not any(known.get(eid, {}).get('kind') == 'sales_rules' for eid in ids):
                    issues.append({'line': line_number, 'reason': '统计能力或缺失字段说明必须引用口径，不能只引SQL'})
    return issues


def handoff_json(value):
    return json.dumps(value, ensure_ascii=False, default=str)
