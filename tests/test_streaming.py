import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, ToolMessage

from korean.config import Settings
from korean.models import TaskRequest
from korean.runtime import AnswerStream
from korean.server import create_app
from korean.store import Store


def test_draft_replay_reset_and_restart(tmp_path):
    store = Store(tmp_path)
    task = store.create(TaskRequest(course_id='K01', research_scope='course'))
    stream = AnswerStream(store, task['id'])
    stream.push(AIMessageChunk(content='专家内部文本', id='s'), {'tags': ['specialist']})
    stream.push(ToolMessage(content='工具参数', tool_call_id='x'), {'tags': ['answer_main']})
    assert not store.get(task['id'])['draft']
    stream.push(AIMessageChunk(content='你好', id='a', additional_kwargs={'reasoning_content': '隐藏思考'}), {'tags': ['answer_main']})
    stream.push(AIMessageChunk(content='，课程', id='a'), {'tags': ['answer_main']})
    stream.flush()
    snapshot = store.stream_snapshot(task['id'])
    assert snapshot['task']['draft'] == '你好，课程'
    store.answer_chunk(task['id'], '资料')
    replay = store.events(task['id'], snapshot['after'])
    assert [e['data']['text'] for e in replay] == ['资料']
    stream.clear()
    stream.push(AIMessageChunk(content=[{'type':'reasoning','text':'隐藏'}, {'type':'text','text':'最终正文'}],id='b'), {'tags':['answer_main']})
    stream.flush()
    store.recover()
    assert Store(tmp_path).get(task['id'])['draft'] == '最终正文'
    assert store.get(task['id'])['status'] == 'INTERRUPTED'


def test_sse_deltas_before_completion_and_cancel_preserves_draft(tmp_path):
    async def generate(s, store, task, tools, budget, saver):
        await asyncio.sleep(.05)
        store.answer_chunk(task['id'], '正在回答')
        await asyncio.sleep(.3)
        store.answer_chunk(task['id'], '，后续内容')
        await asyncio.sleep(.3)
        source=store.evidence(task['id'],'rag',{'text':'测试原文','document_name':'课程'})
        return '正在回答，后续内容 ['+source['evidence_id']+']'
    settings=Settings(data=tmp_path,mode='live',model='test',api_key='test')
    with patch('korean.server.live_report',generate), TestClient(create_app(settings)) as client:
        tid=client.post('/api/chat',json={'message':'只查课程K01'}).json()['task_id']
        with client.stream('GET', f'/api/tasks/{tid}/stream') as response:
            assert response.headers['content-type'].startswith('text/event-stream')
            frames=[json.loads(line[6:]) for line in response.iter_lines() if line.startswith('data: ')]
        assert any(f.get('event')=='answer_delta' for f in frames)
        assert frames[-1]['task']['status']=='SUCCEEDED'
        assert not frames[-1]['task']['draft']
        assert '后续内容' in frames[-1]['task']['report']
        # Reconnecting after completion sends only the authoritative final snapshot.
        replay=client.get(f'/api/tasks/{tid}/stream').text
        assert replay.count('event: snapshot')==1 and 'event: update' not in replay


def test_cancelled_stream_keeps_partial_text(tmp_path):
    import time
    async def generate(s, store, task, tools, budget, saver):
        store.answer_chunk(task['id'],'已经生成的草稿')
        await asyncio.sleep(20)
    settings=Settings(data=tmp_path,mode='live',model='test',api_key='test')
    with patch('korean.server.live_report',generate), TestClient(create_app(settings)) as client:
        tid=client.post('/api/chat',json={'message':'只查课程K01'}).json()['task_id']
        for _ in range(100):
            if client.get('/api/tasks/'+tid).json()['draft']:break
            time.sleep(.01)
        assert client.post('/api/task/'+tid+'/cancel').status_code==200
        task=client.get('/api/tasks/'+tid).json()
        assert task['status']=='CANCELLED' and task['draft']=='已经生成的草稿'
        assert client.post('/api/tasks/'+tid+'/export',json={'format':'markdown'}).status_code==409
        assert '已经生成的草稿' in client.get('/api/tasks/'+tid+'/stream').text
