"""Run real DeepAgents orchestration against a scripted chat model (no paid API)."""
import json
from unittest.mock import patch
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from korean.config import Settings
from korean.models import TaskRequest
from korean.runtime import Budget, ResearchTools, live_report, validate_report
from korean.store import Store


class ScriptedModel(BaseChatModel):
    """Tool-aware deterministic model. It exercises graph wiring, not reasoning."""
    model_name: str = 'test-model'
    @property
    def _llm_type(self):return 'test-model'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        system=str(messages[0].content)
        tools=[m for m in messages if isinstance(m,ToolMessage)]
        def call(name,args):
            return AIMessage(content='',tool_calls=[{'name':name,'args':args,'id':'call'+str(len(messages))}],
                             usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15})
        if '你是主Agent' in system:
            roles=['network','course'] if '"research_scope": "comparison"' in str(messages) else ['network','course','sales']
            if len(tools)<len(roles):return ChatResult(generations=[ChatGeneration(message=call('task',{'subagent_type':roles[len(tools)],'description':'查询韩语课程与销售'}))])
            import re
            text='\n'.join(str(t.content) for t in tools)
            ids=set(re.findall(r'[WDQM][a-f0-9]{12}',text))
            answer=AIMessage(content='合成验证数据。'+''.join('['+i+']' for i in sorted(ids)),usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15})
        else:
            if '分析自家订单' in system:
                if not tools:return ChatResult(generations=[ChatGeneration(message=call('sales_schema',{}))])
                if len(tools)==1:return ChatResult(generations=[ChatGeneration(message=call('query_sales',{'query':'SELECT COUNT(*) AS orders FROM orders'}))])
            elif not tools:
                name='retrieve_course' if '查询自家课程' in system else 'internet_search'
                return ChatResult(generations=[ChatGeneration(message=call(name,{'query':'韩语课程'}))])
            facts=[]
            if '分析自家订单' not in system:
                value=json.loads(tools[-1].content)
                items=value['items'] if isinstance(value,dict) else value
                for item in items:
                    own='text' in item
                    facts.append({'subject':'own_course' if own else 'competitor_course',
                        'entity':'K01' if own else item['title'],'field':'测试摘录',
                        'value':'合成资料','applicability':'unconfirmed','conditions':'测试',
                        'supports':[{'evidence_id':item['evidence_id'],'quote':item.get('text',item.get('content',''))[:80],
                                     'entity_quote':'' if own else item['title']}]})
            name='SalesResult' if '分析自家订单' in system else 'SpecialistResult'
            return ChatResult(generations=[ChatGeneration(message=call(name,{'facts':facts,'unknowns':[]}))])
        return ChatResult(generations=[ChatGeneration(message=answer)])


@pytest.mark.asyncio
async def test_real_deepagents_delegation_and_budget(tmp_path):
    s=Settings(data=tmp_path,mode='offline',model='test-model',api_key='test')
    store=Store(tmp_path)
    task=store.create(TaskRequest(course_id='K01',competitors=['离线示例机构']))
    budget=Budget(s);tools=ResearchTools(s,store,task,budget)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'checkpoints.sqlite')) as saver:
        with patch('langchain_openai.ChatOpenAI',return_value=ScriptedModel()):
            report=await live_report(s,store,task,tools,budget,saver)
    sources=store.sources(task['id'])
    # Convert raw IDs into citations, as a real report model is instructed to do.
    assert {x['kind'] for x in sources}=={'network','rag','sales','sales_rules'}
    assert validate_report(report,sources)['cited']==len(sources)
    assert budget.models==11
    assert budget.input_tokens==110
    assert budget.tools>=7
    assert len([e for e in store.events(task['id']) if e['event']=='assistant_call'])==3
    handoffs=[e['data'] for e in store.events(task['id']) if e['event']=='specialist_handoff']
    assert {h['role'] for h in handoffs}=={'network','course','sales'}
    assert all(not h['rejected'] for h in handoffs)
    assert next(h for h in handoffs if h['role']=='sales')['tables'][0]['rows']==[[1800]]


@pytest.mark.asyncio
async def test_graph_stops_before_model_budget_exceeded(tmp_path):
    from korean.runtime import BudgetExceeded
    s=Settings(data=tmp_path,mode='offline',model='test-model',api_key='test',max_models=1)
    store=Store(tmp_path);task=store.create(TaskRequest(course_id='K01',competitors=['机构']))
    budget=Budget(s);tools=ResearchTools(s,store,task,budget)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'checkpoints.sqlite')) as saver:
        with patch('langchain_openai.ChatOpenAI',return_value=ScriptedModel()):
            with pytest.raises(BudgetExceeded):
                await live_report(s,store,task,tools,budget,saver)
    assert budget.models==1


@pytest.mark.asyncio
async def test_comparison_delegates_only_network_and_course(tmp_path):
    s=Settings(data=tmp_path,mode='offline',model='test-model',api_key='test')
    store=Store(tmp_path)
    task=store.create(TaskRequest(course_id='K01',competitors=['示例机构'],research_scope='comparison'))
    budget=Budget(s);tools=ResearchTools(s,store,task,budget)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'checkpoints.sqlite')) as saver:
        with patch('langchain_openai.ChatOpenAI',return_value=ScriptedModel()), \
             patch.object(tools,'schema',side_effect=AssertionError('sales excluded')):
            report=await live_report(s,store,task,tools,budget,saver)
    assert {x['kind'] for x in store.sources(task['id'])}=={'network','rag'}
    assert {e['data']['subagent_type'] for e in store.events(task['id']) if e['event']=='assistant_call'}=={'network','course'}
    assert validate_report(report,store.sources(task['id']))['cited']>0


class VerboseModel(ScriptedModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        import re
        if '现在只生成最终回答' in str(messages[0].content):
            ids=set(re.findall(r'[WDQM][a-f0-9]{12}',str(messages[-1].content)))
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content='按原文保留限制。'+''.join('['+i+']' for i in sorted(ids)),
                usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15}))])
        result=super()._generate(messages,stop,run_manager,**kwargs)
        answer=result.generations[0].message
        if '你是主Agent' in str(messages[0].content) and not answer.tool_calls:
            answer.content='重复长文'*100+answer.content
        return result


@pytest.mark.asyncio
async def test_long_answer_rewrites_once_with_stream_reset_and_same_evidence(tmp_path):
    s=Settings(data=tmp_path,mode='offline',model='test-model',api_key='test')
    store=Store(tmp_path)
    task=store.create(TaskRequest(course_id='K01',competitors=['示例机构'],research_scope='comparison',query='100字内对比'))
    budget=Budget(s);tools=ResearchTools(s,store,task,budget)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'checkpoints.sqlite')) as saver:
        with patch('langchain_openai.ChatOpenAI',return_value=VerboseModel()):
            report=await live_report(s,store,task,tools,budget,saver)
    events=store.events(task['id'])
    assert len([e for e in events if e['event']=='answer_revision'])==1
    quality=next(e['data'] for e in events if e['event']=='answer_quality')
    assert quality['within_limit'] and quality['revised']
    assert '重复长文' not in report
    assert validate_report(report,store.sources(task['id']))['cited']==len(store.sources(task['id']))


class BoundaryModel(ScriptedModel):
    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        import re
        if '现在只生成最终回答' in str(messages[0].content):
            ids=set(re.findall(r'[WDQ][a-f0-9]{12}',str(messages[-1].content)))
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content='本次未确认授课方式。'+''.join('['+i+']' for i in sorted(ids)),
                usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15}))])
        result=super()._generate(messages,stop,run_manager,**kwargs)
        answer=result.generations[0].message
        if '你是主Agent' in str(messages[0].content) and not answer.tool_calls:
            eid=re.search(r'D[a-f0-9]{12}',answer.content).group()
            answer.content='永久一对一陪练['+eid+']'
        return result


@pytest.mark.asyncio
async def test_short_answer_with_bad_citation_triggers_one_repair(tmp_path):
    s=Settings(data=tmp_path,mode='offline',model='test-model',api_key='test')
    store=Store(tmp_path)
    task=store.create(TaskRequest(course_id='K01',competitors=['示例'],research_scope='comparison'))
    budget=Budget(s);tools=ResearchTools(s,store,task,budget)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'checkpoints.sqlite')) as saver:
        with patch('langchain_openai.ChatOpenAI',return_value=BoundaryModel()):
            report=await live_report(s,store,task,tools,budget,saver)
    revisions=[e for e in store.events(task['id']) if e['event']=='answer_revision']
    assert len(revisions)==1 and revisions[0]['data']['boundary_issues']
    quality=next(e['data'] for e in store.events(task['id']) if e['event']=='answer_quality')
    assert not quality['boundary_issues'] and quality['revised']
    assert '永久一对一陪练' not in report


class WeekdayModel(ScriptedModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        import re
        if '现在只生成最终回答' in str(messages[0].content):
            eid=re.search(r'D[a-f0-9]{12}',str(messages[-1].content)).group()
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content='通常周一、周三上课['+eid+']',
                usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15}))])
        result=super()._generate(messages,stop,run_manager,**kwargs)
        message=result.generations[0].message
        if '你是主Agent' in str(messages[0].content) and not message.tool_calls:
            eid=re.search(r'D[a-f0-9]{12}',message.content).group()
            message.content='通常周一、周二上课['+eid+']'
        return result


@pytest.mark.asyncio
async def test_wrong_weekday_in_synthesis_is_revised_once_with_original_evidence(tmp_path):
    s=Settings(data=tmp_path,mode='offline',model='test-model',api_key='test')
    store=Store(tmp_path)
    task=store.create(TaskRequest(course_id='K01',competitors=['示例'],research_scope='comparison'))
    budget=Budget(s);tools=ResearchTools(s,store,task,budget)
    async def retrieve(query):
        source=store.evidence(task['id'],'rag',{'text':'通常周一、周三上课。','document_name':'排课'})
        return {'items':[source]}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'checkpoints.sqlite')) as saver:
        with patch('langchain_openai.ChatOpenAI',return_value=WeekdayModel()),patch.object(tools,'retrieve',retrieve):
            report=await live_report(s,store,task,tools,budget,saver)
    revisions=[e for e in store.events(task['id']) if e['event']=='answer_revision']
    assert len(revisions)==1
    assert any('星期' in i['reason'] for i in revisions[0]['data']['boundary_issues'])
    assert '周一、周三' in report and '周二' not in report
    quality=next(e['data'] for e in store.events(task['id']) if e['event']=='answer_quality')
    assert not quality['boundary_issues']
    assert not tools.errors
