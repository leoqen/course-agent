"""Assemble the main agent and three specialists; synthesize and check reports."""
import asyncio
from decimal import Decimal
import json
import re


from .config import COURSES
from .models import SCOPE_SOURCES
from .budget import Budget, BudgetExceeded
from .tools import ResearchTools
from .streaming import AnswerStream
from .prompts import COMMON, MAIN_PROMPT
from .handoff import (SpecialistResult, SalesResult, EXTRACTION_PROMPT, validate_handoff,
                      answer_policy, body_length, handoff_json, check_answer_contract, sentence_count)


async def live_report(settings, store, task, tools, budget, saver):
    # Lazy imports keep startup, SQL-only tests and offline demonstrations independent
    # of model SDK initialization.
    from deepagents import create_deep_agent, HarnessProfile, GeneralPurposeSubagentProfile, register_harness_profile
    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.structured_output import ToolStrategy
    from langchain_core.callbacks import AsyncCallbackHandler
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI

    allowed_sources = SCOPE_SOURCES[task['request'].get('research_scope', 'full')]
    allowed_roles = {'course' if source == 'rag' else source for source in allowed_sources}

    class Guard(AgentMiddleware):
        async def awrap_tool_call(self, request, handler):
            call = request.tool_call
            # All built-in and delegated tools count, not only application tools.
            if call['name'] not in {'internet_search','retrieve_course','query_sales','sales_schema','sales_monthly','sales_channels'}:
                budget.take('tools')
            if call['name'] == 'task':
                store.event(task['id'], 'assistant_call', '调用专家助手', call['args'])
                if call['args'].get('subagent_type') not in allowed_roles:
                    return ToolMessage(content='本次范围只允许调用 '+ '、'.join(sorted(allowed_roles)), tool_call_id=call['id'])
            return await handler(request)

    class Usage(AsyncCallbackHandler):
        # Count actual model starts, including any framework summarization calls.
        # Propagate budget exceptions before the provider is called.
        raise_error = True

        async def on_chat_model_start(self, serialized, messages, **kwargs):
            budget.take('models')

        async def on_llm_start(self, serialized, prompts, **kwargs):
            budget.take('models')

        async def on_llm_end(self, response, **kwargs):
            total = None
            for generation in response.generations:
                for item in generation:
                    meta = getattr(getattr(item, 'message', None), 'usage_metadata', None)
                    if meta:
                        total = meta
            if total:
                budget.input_tokens += total.get('input_tokens', 0)
                budget.output_tokens += total.get('output_tokens', 0)
            else:
                budget.unknown_usage += 1

    class Handoff(AgentMiddleware):
        def __init__(self, role):
            self.role = role

        async def aafter_agent(self, state, runtime):
            messages = [m for m in state['messages'] if isinstance(m, ToolMessage)]
            # Scope provenance to evidence returned in this specialist invocation.
            returned_ids = set(re.findall(r'[WDQM][a-f0-9]{12}', '\n'.join(str(m.content) for m in messages)))
            sources = [s for s in store.sources(task['id']) if s['evidence_id'] in returned_ids]
            bundle = validate_handoff(state['structured_response'], self.role, sources, task['request']['course_id'])
            bundle['retrieval_status'] = {'obtained_source_count': len(sources),
                'note': '已取得来源不等于字段通过交接；字段未确认或被过滤不能写成未取得正文。'}
            if self.role == 'sales':
                bundle['tables'] = []
                for message in messages:
                    if message.name not in {'sales_schema', 'sales_monthly', 'sales_channels', 'query_sales'}:
                        continue
                    value = json.loads(message.content)
                    if value.get('status') == 'ERROR':
                        continue
                    if message.name == 'sales_schema':
                        # Tool metadata is separate from SQL-result evidence.
                        bundle['metric_rules'] = value['rules_evidence']
                    elif message.name == 'sales_monthly':
                        bundle['tables'].append({'type': 'monthly', 'rows': [
                            {k: v for k, v in row.items() if k != 'evidence'} |
                            {'evidence_ids': [e['evidence_id'] for e in row['evidence']]}
                            for row in value['rows']], 'calculation': value['net_calculation']})
                    else:
                        bundle['tables'].append({'type': 'channels' if message.name == 'sales_channels' else 'custom_sql',
                            'columns': value['columns'], 'rows': value['rows'],
                            'evidence_ids': [value['evidence_id']], 'truncated': value['truncated']})
                bundle['course_id'] = task['request']['course_id']
                bundle['date_range'] = [task['request']['start_date'], task['request']['end_date']]
            tools.handoffs.append(bundle)
            store.event(task['id'], 'specialist_handoff', '专家结构化结果', bundle)
            if bundle['rejected']:
                tools.errors.append({'tool': self.role, 'type': 'HandoffRejected', 'count': len(bundle['rejected'])})
            # Rejected field names may themselves contain fabricated dates/claims.
            # Retain them in audit events, never forward them as synthesis material.
            return {'structured_response': bundle | {'rejected': len(bundle['rejected'])}}

    def protect(fn, name):
        async def run(**kwargs):
            try:
                return json.dumps(await fn(**kwargs), ensure_ascii=False, default=str)
            except BudgetExceeded:
                raise
            except Exception as exc:
                tools.errors.append({'tool': name, 'type': type(exc).__name__})
                store.event(task['id'], 'source_error', '资料源调用失败', {'tool': name, 'error_type': type(exc).__name__})
                return json.dumps({'status': 'ERROR', 'tool': name, 'error_type': type(exc).__name__, 'instruction': '明确说明此来源不可用，不编造，不重复尝试'}, ensure_ascii=False)
        return run

    @tool
    async def internet_search(query: str) -> str:
        """联网搜索指定韩语竞品课程，返回来源证据。"""
        return await protect(tools.search, 'network')(query=query)

    @tool
    async def retrieve_course(query: str) -> str:
        """检索自家课程原文，保留章节和引用。"""
        return await protect(tools.retrieve, 'rag')(query=query)

    @tool
    async def sales_schema() -> str:
        """读取订单、课程、退款表结构和指标口径。"""
        return await protect(tools.schema, 'sales')()

    @tool
    async def query_sales(query: str) -> str:
        """执行只读销售SQL，返回字段、结果、口径与证据ID。"""
        return await protect(tools.sql, 'sales')(query=query)

    @tool
    async def sales_monthly() -> str:
        """按本任务课程和日期统计每月成交、收款、退款、净收款，保留空月份和仅退款月份。"""
        return await protect(tools.monthly, 'sales')()

    @tool
    async def sales_channels() -> str:
        """按本任务课程及日期统计渠道成交订单数和收款，不引入退款或其他课程。"""
        return await protect(tools.channels, 'sales')()

    model_options = dict(model=settings.model, api_key=settings.api_key, base_url=settings.base_url,
                         temperature=0, timeout=75, max_retries=0, streaming=True, stream_usage=True)
    model = ChatOpenAI(**model_options, tags=['answer_main'])
    specialist_model = ChatOpenAI(**model_options, tags=['specialist'])
    register_harness_profile('openai:'+settings.model, HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        excluded_tools=frozenset({'ls','read_file','write_file','edit_file','glob','grep','execute'})))
    specs = [('network', '调查竞品公开课程、价格、服务。', [internet_search]),
             ('course', '查询自家课程资料与服务政策。', [retrieve_course]),
             ('sales', '分析自家订单、收款、退款及渠道变化。先查表结构，月度统计使用sales_monthly，渠道成交收款使用sales_channels，再按请求下钻。', [sales_schema, sales_monthly, sales_channels, query_sales])]
    specs = [spec for spec in specs if spec[0] in allowed_roles]
    policy = answer_policy(task['request']['query'], task['request'].get('research_scope', 'full'))
    prompt = COMMON + MAIN_PROMPT + '\n回答篇幅约定：'+handoff_json(policy)
    if task['request']['analysis_mode'] == 'single':
        graph = create_agent(model, tools=[tool for _, _, role_tools in specs for tool in role_tools],
                             system_prompt=prompt, middleware=[Guard()], checkpointer=saver)
    else:
        subs = [{'name': n, 'description': d, 'runnable': create_agent(specialist_model, tools=ts,
                system_prompt=COMMON+'\n'+d+'\n'+EXTRACTION_PROMPT+'\n任务固定定位（不能改成竞品编号）：'+handoff_json({
                    'own_course_id': task['request']['course_id'], 'request': task['request']}),
                response_format=ToolStrategy(SalesResult if n == 'sales' else SpecialistResult),
                middleware=[Guard(), Handoff(n)])} for n, d, ts in specs]
        graph = create_deep_agent(model=model, tools=[], system_prompt=prompt, subagents=subs,
                                  middleware=[Guard()], checkpointer=saver)
    request = task['request']
    # Each attempt has its own checkpoint namespace: retries cannot inherit stale
    # evidence IDs from an interrupted run, while the store retains session history.
    history = [{'task_id': t['id'], 'summary': t['report'][:1500]} for t in store.tasks()
               if t['thread_id'] == task['thread_id'] and t['id'] != task['id'] and t['status'] in {'SUCCEEDED','PARTIAL'}][:2]
    graph_input = {'messages': [{'role': 'user', 'content': json.dumps({'request': request,
        'course_locator': {'course_id': request['course_id'], 'name': COURSES[request['course_id']]['name']}, 'data_range': ['2026-05-01','2026-11-01'],
        'history_context_only': history, 'instruction': '表单范围优先；历史只供上下文，事实必须重新检索。'}, ensure_ascii=False)}]}
    answer = AnswerStream(store, task['id'])
    result = None
    try:
        async for namespace, mode, value in graph.astream(graph_input,
                config={'configurable': {'thread_id': task['id']}, 'recursion_limit': 100, 'callbacks': [Usage()]},
                stream_mode=['messages', 'values'], subgraphs=True):
            if mode == 'messages':
                answer.push(*value)
            elif mode == 'values' and not namespace:
                result = value
                last = value['messages'][-1]
                if getattr(last, 'tool_calls', None):
                    answer.clear()
    finally:
        answer.flush()
    if result is None:
        raise ValueError('模型未返回回答')
    msg = result['messages'][-1].content
    report = msg if isinstance(msg, str) else json.dumps(msg, ensure_ascii=False)
    # One bounded rewrite, with no source calls, if the answer exceeds its budget.
    # Never truncate the report and risk removing a qualifier or citation.
    revised = False
    boundary_issues = check_answer_contract(report, store.sources(task['id']), tools.handoffs, policy)
    if body_length(report) > policy['max_characters'] or boundary_issues:
        revised = True
        answer.clear()
        store.event(task['id'], 'answer_revision', '修订回答篇幅与引用边界', {
            'max_characters': policy['max_characters'], 'boundary_issues': boundary_issues})
        chunks = []
        compact_bundles = [b | {'rejected': len(b['rejected'])} for b in tools.handoffs]
        async for chunk in model.astream([
                {'role': 'system', 'content': prompt+'\n现在只生成最终回答，不调用工具。把先前草稿视为待纠正文稿，不是事实来源。'
                    f"目标控制在{int(policy['max_characters']*.6)}字符内，引用编号不计。简短问题直接回答2至4句；"
                    '需要月表时仅保留要求的数字表、核心差异及最多2项待确认。删除历史课程细节和重复范围说明，但保留必要适用限制。'
                    '严格遵守max_sentences（如有），不另加标题、总结或未问字段。每个事实分句紧跟自身引用，原文引号逐字匹配。未知仅写尚未确认具体对象字段，不说已取得资料均无某标注。'
                    '逐项解决boundary_issues：星期逐字遵循原摘录，不添加未问排课；匿名分组不可套具体课程。不能用排课摘录支持直播，不能从课时构成推断课件。无法支持的字段删去或写本次未确认。口径说明引用metric_rules的M编号。'},
                {'role': 'user', 'content': handoff_json({'request': request, 'checked_handoffs': compact_bundles,
                    'draft_to_shorten': report, 'answer_policy': policy, 'boundary_issues': boundary_issues})}], config={'callbacks': [Usage()]}):
            answer.push(chunk, {'tags': ['answer_main']})
            if isinstance(chunk.content, str):
                chunks.append(chunk.content)
        answer.flush()
        report = ''.join(chunks)
    length = body_length(report)
    boundary_issues = check_answer_contract(report, store.sources(task['id']), tools.handoffs, policy)
    store.event(task['id'], 'answer_quality', '回答篇幅检查', {
        'characters': length, 'max_characters': policy['max_characters'], 'revised': revised,
        'within_limit': length <= policy['max_characters'], 'boundary_issues': boundary_issues,
        'sentences': sentence_count(report), 'max_sentences': policy.get('max_sentences'),
        'semantic_verified': False})
    if length > policy['max_characters']:
        tools.errors.append({'tool': 'answer', 'type': 'AnswerLengthExceeded'})
    if boundary_issues:
        tools.errors.append({'tool': 'answer', 'type': 'AnswerBoundaryUnresolved', 'count': len(boundary_issues)})
    return report


async def offline_report(store, task, tools):
    """Explicit integration fixture; not an LLM or a multi-agent quality result."""
    req = task['request']
    async def lane(name, fn):
        store.event(task['id'], 'assistant_call', name+'（离线固定流程）')
        return await fn()
    scope=req.get('research_scope','full')
    web,rag=[],{'items':[]}
    if scope in {'full','comparison','network'}:
        web=await lane('竞品研究', lambda: tools.search(' '.join(req['competitors'])))
    if scope in {'full','comparison','course'}:
        rag=await lane('自家课程', lambda: tools.retrieve(req['query'] or '课程信息'))
    course = COURSES[req['course_id']]
    notice='这是**离线固定流程演示**，未调用大模型；以下为合成资料快照，不构成真实经营结论。\n\n'
    if scope=='network':
        return notice+'## 竞品公开信息（虚构）\n'+'\n\n'.join(x['content']+' ['+x['evidence_id']+']' for x in web)
    if scope=='course':
        excerpts=[]
        for x in rag['items']:
            sections=re.split(r'(?=^## )',x['text'],flags=re.M)
            selected=[v for v in sections if course['name'] in v.split('\n')[0]]
            if selected:excerpts.append('\n\n'.join(selected)+'\n['+x['evidence_id']+']')
        return notice+'## '+course['name']+'的资料摘录\n按课程标题筛选原文，演示不对追问进行模型推理。\n\n'+'\n\n'.join(excerpts)
    if scope=='comparison':
        course_refs=''.join('['+x['evidence_id']+']' for x in rag['items'])
        web_refs=''.join('['+x['evidence_id']+']' for x in web)
        return notice+f'''## 课程对比
| 项目 | 自家（合成） | 竞品（合成） |
|---|---|---|
| 课程 | {course['name']} | 离线示例零基础课程 |
| 标价 | {course['price']}元 | 1280元 |
| 方式 | 直播小班 | 录播 |
| 课时 | {course['lessons']}节，每节{course['minutes']}分钟 | 30节，每节30分钟 |

自家依据：{course_refs}；竞品依据：{web_refs}。
授课方式和目标基础需分别确认，不能仅按总价判断优劣。本次未查询销售数据。
'''
    async def sales_call():
        await tools.schema()
        cid, start, end = req['course_id'], req['start_date'], req['end_date']
        paid = await tools.sql(f"SELECT COUNT(*) AS order_count, COALESCE(SUM(amount),0) AS receipts, AVG(amount) AS average FROM orders WHERE course_id='{cid}' AND paid_at>='{start}' AND paid_at<'{end}' AND status='PAID'")
        refunds = await tools.sql(f"SELECT COALESCE(SUM(r.amount),0) AS refunds FROM refunds r JOIN orders o ON r.order_id=o.order_id WHERE o.course_id='{cid}' AND r.refunded_at>='{start}' AND r.refunded_at<'{end}'")
        monthly = await tools.sql(f"SELECT DATE_FORMAT(paid_at,'%Y-%m') AS month, COUNT(*) AS orders, SUM(amount) AS receipts FROM orders WHERE course_id='{cid}' AND paid_at>='{start}' AND paid_at<'{end}' AND status='PAID' GROUP BY DATE_FORMAT(paid_at,'%Y-%m') ORDER BY month")
        channels = await tools.sql(f"SELECT channel, COUNT(*) AS orders, SUM(amount) AS receipts FROM orders WHERE course_id='{cid}' AND paid_at>='{start}' AND paid_at<'{end}' AND status='PAID' GROUP BY channel ORDER BY receipts DESC")
        return paid, refunds, monthly, channels
    sales = await lane('销售记录', sales_call)
    paid, refunds, monthly, channels = sales
    rows = paid['rows'][0]
    returned = Decimal(str(refunds['rows'][0][0]))
    net = Decimal(str(rows[1]))-returned
    trend = '\n'.join(f'| {m} | {n} | {v} |' for m,n,v in monthly['rows'])
    channel_rows = '\n'.join(f'| {c} | {n} | {v} |' for c,n,v in channels['rows'])
    report = f'''## 调研范围与数据说明
这是**离线固定流程演示**，未调用大模型和真实搜索；竞品、自家课程、销售均为合成样例，不能作为真实经营结论。
课程：{course['name']}；销售区间：{req['start_date']} 至 {req['end_date']}（不含结束日）。

## 课程对比
| 项目 | 自家（合成） | 竞品（合成） |
|---|---|---|
| 标价 | {course['price']}元 | 1280元 |
| 方式 | 直播小班 | 录播 |
| 课时 | {course['lessons']}节，每节{course['minutes']}分钟 | 30节，每节30分钟 |

自家依据：{', '.join('['+x['evidence_id']+']' for x in rag['items'])}；竞品依据：{', '.join('['+x['evidence_id']+']' for x in web)}。
两者授课方式不同，不能仅按总价判断优劣。

## 销售表现
成交订单数：{rows[0]}；收款金额：{rows[1]}元；成交客单价：{rows[2] if rows[2] is not None else '未知（无订单）'}元。[{paid['evidence_id']}]

区间退款金额：{returned:.2f}元；区间净收款：{net:.2f}元。退款按退款发生时间统计，订单仍计入原成交数；净收款不等于会计收入。[{refunds['evidence_id']}][{paid['evidence_id']}]

### 月度收款趋势
月份仅统计所选区间内的订单，区间首尾可能不足整月。[{monthly['evidence_id']}]

| 月份 | 成交订单数 | 收款金额（元） |
|---|---|---|
{trend}

### 渠道表现
仅反映成交和收款，缺少咨询人数及投放费用，不能计算转化率或ROI。[{channels['evidence_id']}]

| 渠道 | 成交订单数 | 收款金额（元） |
|---|---|---|
{channel_rows}

## 发现与待确认问题
销售为2026年历史模拟记录，竞品为固定虚构样例。不能推断竞品影响销售。
真实模式应核对竞品适用条件、课程是否可比，并按需要下钻渠道、退款及时间趋势。
'''
    if scope=='sales':
        report=re.sub(r'## 课程对比.*?(?=## 销售表现)','',report,flags=re.S)
        report=report.replace('竞品、自家课程、销售均为合成样例','销售为合成样例').replace('竞品为固定虚构样例','本次未查询竞品')
    return report


def normalize_citations(report, sources):
    """Format only exact known bare IDs. Never invent IDs or attach new claims."""
    known = {x['evidence_id'] for x in sources}
    def replace(match):
        value = match.group()
        if value not in known:
            raise ValueError('报告引用不存在的证据：' + value)
        return '[' + value + ']'
    return re.sub(r'(?<![A-Za-z0-9_\[])[WDQM][a-f0-9]{12}(?![A-Za-z0-9_\]])', replace, report)


def validate_report(report, sources):
    known = {x['evidence_id'] for x in sources}
    cited = set(re.findall(r'\[([WDQM][a-f0-9]{12})\]', report))
    invalid = cited-known
    if invalid:
        raise ValueError('报告引用不存在的证据：'+','.join(sorted(invalid)))
    data_sources = [s for s in sources if s['kind'] != 'sales_rules']
    if sources and not cited:
        raise ValueError('报告缺少可追溯的证据引用')
    return {'cited': len(cited), 'available': len(known), 'coverage': sorted({x['kind'] for x in data_sources}),
            'cited_coverage': sorted({x['kind'] for x in data_sources if x['evidence_id'] in cited}),
            'rules_cited': sorted(x['evidence_id'] for x in sources if x['kind'] == 'sales_rules' and x['evidence_id'] in cited)}


def append_sources(report, sources):
    lines = ['\n## 本次来源与查询附录', '自家课程与销售数据均为合成验证资料。网络资料以采集时状态为准。']
    for x in sources:
        eid = x['evidence_id']
        if x['kind'] == 'network':
            url = x.get('url') or ''
            # Only hyperlink public HTTP URLs; keep punctuation outside the URL.
            link = '<'+url.replace('>', '%3E').replace('<', '%3C')+'>' if re.match(r'^https?://', url) else '未提供网页地址'
            lines.append(f"- [{eid}] {x.get('title')}；来源：{link} ；采集：{x.get('captured_at')}；类型：{x.get('content_type')}")
        elif x['kind'] == 'rag':
            lines.append(f"- [{eid}] {x.get('document_name')}；章节：{x.get('section_path')}；页码：{x.get('page') or '未提供'}")
        elif x['kind'] == 'sales_rules':
            lines.append(f"- [{eid}] 销售指标口径与数据能力（应用定义，非SQL查询结果）：{x['rules']}")
        else:
            lines.append(f"- [{eid}] 销售SQL；是否截断：{x['truncated']}\n```sql\n{x['sql']}\n```\n结果：{json.dumps({'columns': x['columns'], 'rows': x['rows']}, ensure_ascii=False)}")
    return report+'\n'+'\n'.join(lines)
