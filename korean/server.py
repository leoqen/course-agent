import asyncio
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
import uuid
import json

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import COURSES, ROOT, Settings
from .models import TaskRequest, ChatRequest, ExportRequest, SCOPE_SOURCES
from .conversation import resolve
from .pdf import write_pdf
from .budget import Budget, BudgetExceeded
from .tools import ResearchTools
from .runtime import append_sources, live_report, offline_report, validate_report, normalize_citations
from .store import Conflict, Store, TERMINAL


def create_app(settings=None):
    s = settings or Settings.env()
    store = Store(s.data)
    active = {}
    semaphore = asyncio.Semaphore(2)
    export_lock = asyncio.Lock()
    chat_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        for t in list(active.values()):
            t.cancel()
        if active:
            await asyncio.gather(*list(active.values()), return_exceptions=True)

    app = FastAPI(title='韩语课程经营调研', version='1.0.0', lifespan=lifespan)
    app.state.store, app.state.settings, app.state.active = store, s, active
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],
                       allow_methods=['GET','POST'], allow_headers=['Content-Type'])

    def require(tid):
        task = store.get(tid)
        if not task:
            raise HTTPException(404, '任务不存在')
        return task

    async def execute(task):
        tid = task['id']
        budget = Budget(s)
        tools = None
        try:
            async with semaphore:
                store.update(tid, status='RUNNING')
                store.event(tid, 'task_status', '开始执行', {'status': 'RUNNING', 'mode': s.mode})
                tools = ResearchTools(s, store, task, budget)
                async with asyncio.timeout(s.max_seconds):
                    if s.mode == 'offline':
                        report = await offline_report(store, task, tools)
                    else:
                        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
                        async with AsyncSqliteSaver.from_conn_string(str(s.data/'checkpoints.sqlite')) as saver:
                            report = await live_report(s, store, task, tools, budget, saver)
                    sources = store.sources(tid)
                    report = normalize_citations(report, sources)
                    # Missing citations yield a reviewable PARTIAL response;
                    # fabricated IDs remain an error even in this mode.
                    quality = validate_report(report, sources, require_citations=False)
                    if not any(x['kind'] != 'sales_rules' for x in sources):
                        raise ValueError('未获取任何可用来源')
                    partial = bool(tools.errors)
                    if not quality['cited']:
                        tools.errors.append({'tool': 'answer', 'type': 'MissingCitations'})
                        partial = True
                    scope = task['request'].get('research_scope', 'full')
                    expected = SCOPE_SOURCES[scope]
                    if expected-set(quality['cited_coverage']):
                        partial = True
                    if partial:
                        report = '⚠ 本报告未完全通过来源、引用或格式检查，请结合来源与任务记录阅读。\n\n'+report
                    if not ('合成' in report or '模拟' in report):
                        report = '自家课程与销售数据为合成验证资料。\n\n'+report
                    report = append_sources(report, sources)
                    output = task['request']['output_format']
                    out = s.data/'artifacts'/tid
                    if output != 'none':
                        out.mkdir(parents=True, exist_ok=True)
                    if output in {'markdown','both'}:
                        md = out/'调研报告.md'
                        md.write_text(report, 'utf-8')
                        store.artifact(tid, md)
                    pdf_error = None
                    if output in {'pdf','both'}:
                        try:
                            await asyncio.to_thread(write_pdf, out/'调研报告.pdf', report)
                            store.artifact(tid, out/'调研报告.pdf')
                        except Exception as exc:
                            pdf_error = type(exc).__name__
                            partial = True
                            store.event(tid, 'artifact_error', 'PDF生成失败，回答已保留，可再次导出', {'error_type': pdf_error})
                    metrics = budget.metrics() | {'evidence': quality, 'mode': s.mode, 'source_errors': tools.errors,
                        'pdf_error': pdf_error, 'offline_fixture': s.mode == 'offline'}
                    state = 'PARTIAL' if partial else 'SUCCEEDED'
                    store.update(tid, status=state, report=report, draft='', metrics=metrics)
                    store.event(tid, 'task_result', '报告已保存', {'status': state})
        except asyncio.CancelledError:
            store.update(tid, status='CANCELLED', metrics=budget.metrics())
            store.event(tid, 'task_cancelled', '任务已取消；已获取的证据保留')
            raise
        except (BudgetExceeded, TimeoutError) as exc:
            message = str(exc) if isinstance(exc, BudgetExceeded) else '任务达到时间上限'
            sources = store.sources(tid)
            has_data = any(x['kind'] != 'sales_rules' for x in sources)
            report = append_sources('## 未完成报告\n'+message+'。以下仅为已获取的证据，未形成完整分析。', sources) if sources else ''
            if report and task['request']['output_format'] in {'markdown','both'}:
                out = s.data/'artifacts'/tid
                out.mkdir(parents=True, exist_ok=True)
                md = out/'未完成报告.md'
                md.write_text(report, 'utf-8')
                store.artifact(tid, md)
            store.update(tid, status='PARTIAL' if has_data else 'FAILED', report=report, error=message, metrics=budget.metrics())
            store.event(tid, 'error', message)
        except Exception as exc:
            # Do not leak model HTTP bodies, credentials or connection strings.
            message = '执行失败：'+type(exc).__name__+'。请检查服务配置和来源状态。'
            store.update(tid, status='FAILED', error=message, metrics=budget.metrics())
            store.event(tid, 'error', message)

    @app.get('/api/health')
    def health():
        return {'status': 'OK', 'mode': s.mode, 'synthetic_sales': True, 'synthetic_courses': True,
                'model_configured': bool(s.model and s.api_key), 'search_configured': bool(s.tavily_key),
                'rag_configured': bool(s.rag_token), 'mysql_configured': bool(s.mysql_password),
                'courses': COURSES, 'data_range': ['2026-05-01','2026-11-01']}

    @app.post('/api/task', status_code=202)
    async def submit(body: TaskRequest):
        if not body.course_id:
            # Only unambiguous identifiers/names; no paid model for input parsing.
            matches = [cid for cid, c in COURSES.items() if cid in body.query.upper() or c['name'] in body.query]
            if len(matches) == 1:
                body.course_id = matches[0]
            else:
                raise HTTPException(422, {'message': '请选择自家课程', 'missing_fields': ['course_id']})
        if body.research_scope in {'full','comparison','network'} and not body.competitors:
            raise HTTPException(422, {'message': '请指定1至3家竞品机构', 'missing_fields': ['competitors']})
        if 'sales' in SCOPE_SOURCES[body.research_scope] and (body.start_date < date(2026,5,1) or body.end_date > date(2026,11,1)):
            raise HTTPException(422, '模拟销售覆盖2026-05-01至2026-11-01（不含结束日），请调整区间')
        if s.mode not in {'live','offline'}:
            raise HTTPException(503, 'RESEARCH_MODE 必须为 live 或 offline')
        if s.mode == 'live' and not (s.model and s.api_key):
            raise HTTPException(503, '未配置 RESEARCH_MODEL / OPENAI_API_KEY；可显式使用离线演示模式')
        try:
            task = store.create(body)
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        store.event(task['id'], 'task_status', '任务已排队', {'status': 'QUEUED'})
        worker = asyncio.create_task(execute(task))
        active[task['id']] = worker
        worker.add_done_callback(lambda _: active.pop(task['id'], None))
        return {'status': 'started', 'task_id': task['id'], 'thread_id': task['thread_id']}

    @app.get('/api/conversations')
    def conversations():
        return store.conversations()

    @app.get('/api/conversations/{thread_id}')
    def conversation(thread_id: str):
        return {'messages':store.messages(thread_id),
                'tasks':[t | {'files':store.files(t['id'])} for t in store.tasks() if t['thread_id']==thread_id]}

    @app.post('/api/chat')
    async def chat(body: ChatRequest):
        async with chat_lock:
            return await send_chat(body)

    async def send_chat(body: ChatRequest):
        body.message=body.message.strip()
        if not body.message:raise HTTPException(422,'请输入内容')
        thread=body.thread_id or uuid.uuid4().hex
        body.thread_id=thread
        history=[t for t in store.tasks() if t['thread_id']==thread]
        if any(t['status'] not in TERMINAL for t in history):raise HTTPException(409,'请等待当前回答完成，或先停止生成')
        messages=store.messages(thread)
        last=max((i for i,m in enumerate(messages) if m['task_id']),default=-1)
        pending=[m['content'] for m in messages[last+1:] if m['role']=='user']
        try:
            request,question=resolve(body,history[0] if history else None,pending)
        except ValueError:
            raise HTTPException(422,'调研范围不合法，请检查日期、课程或最多3家竞品')
        if question:
            store.message(thread,'user',body.message)
            store.message(thread,'assistant',question)
            return {'thread_id':thread,'status':'clarification','message':question}
        result=await submit(request)
        store.message(thread,'user',body.message,result['task_id'])
        return result

    @app.post('/api/tasks/{tid}/export')
    async def export(tid: str, body: ExportRequest):
        async with export_lock:
            task=require(tid)
            if task['status'] not in TERMINAL or not task['report']:
                raise HTTPException(409,'回答完成后才能导出')
            suffix='md' if body.format=='markdown' else 'pdf'
            existing=next((f for f in store.files(tid) if f['name']=='调研报告.'+suffix),None)
            if existing:return existing
            folder=s.data/'artifacts'/tid
            folder.mkdir(parents=True,exist_ok=True)
            path=folder/('调研报告.'+suffix)
            try:
                if suffix=='md':path.write_text(task['report'],'utf-8')
                else:await asyncio.to_thread(write_pdf,path,task['report'])
            except Exception:
                raise HTTPException(500,'文件生成失败，回答仍已保存，请稍后重试')
            return store.artifact(tid,path)

    @app.get('/api/tasks')
    def tasks():
        return [{k:v for k,v in t.items() if k!='report'} for t in store.tasks()]

    @app.get('/api/tasks/{tid}')
    def detail(tid: str):
        return require(tid) | {'files': store.files(tid)}

    @app.get('/api/tasks/{tid}/events')
    def events(tid: str, after: int = 0):
        require(tid)
        return store.events(tid, max(0,after))

    @app.get('/api/tasks/{tid}/stream')
    async def stream(tid: str, request: Request):
        require(tid)
        def frame(event, data, seq):
            return f'id: {seq}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'
        async def generate():
            snapshot = store.stream_snapshot(tid)
            after = snapshot['after']
            # Reconnect sends an authoritative snapshot instead of replaying old tokens.
            yield frame('snapshot', snapshot, after)
            if snapshot['task']['status'] in TERMINAL:
                return
            heartbeat = asyncio.get_running_loop().time()
            while not await request.is_disconnected():
                for event in store.events(tid, after):
                    after = event['seq']
                    yield frame('update', event, after)
                task = require(tid)
                if task['status'] in TERMINAL:
                    snapshot = store.stream_snapshot(tid)
                    yield frame('snapshot', snapshot, snapshot['after'])
                    return
                now = asyncio.get_running_loop().time()
                if now - heartbeat >= 15:
                    yield ': keepalive\n\n'
                    heartbeat = now
                await asyncio.sleep(.1)
        return StreamingResponse(generate(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.get('/api/tasks/{tid}/evidence')
    def evidence(tid: str):
        require(tid)
        return store.sources(tid)

    @app.post('/api/task/{identifier}/cancel')
    async def cancel(identifier: str):
        task = store.get(identifier)
        if not task:
            task = next((t for t in store.tasks() if t['thread_id']==identifier and t['status'] not in TERMINAL), None)
        if not task or task['id'] not in active:
            raise HTTPException(404, '运行任务不存在')
        worker = active[task['id']]
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        # A queued task may be cancelled before its coroutine ever starts.
        if store.get(task['id'])['status'] not in TERMINAL:
            store.update(task['id'], status='CANCELLED')
            store.event(task['id'], 'task_cancelled', '排队任务已取消')
        return {'status': 'CANCELLED', 'task_id': task['id']}

    @app.get('/api/files')
    def files(task_id: str):
        require(task_id)
        return {'files': store.files(task_id)}

    @app.get('/api/download/{aid}')
    def download(aid: str):
        f = store.file(aid)
        if not f:
            raise HTTPException(404, '文件不存在')
        path = Path(f['path']).resolve()
        if not path.is_relative_to((s.data/'artifacts'/f['task_id']).resolve()) or not path.is_file():
            raise HTTPException(404, '文件不可用')
        return FileResponse(path, filename=f['name'])

    @app.post('/api/upload')
    async def upload(files: list[UploadFile] = File(...), thread_id: str = Form(...)):
        if not thread_id.replace('-','').replace('_','').isalnum() or len(thread_id)>64:
            raise HTTPException(422, '会话ID不合法')
        if len(files)>5:
            raise HTTPException(422, '最多上传5个文件')
        saved = []
        for f in files:
            name = f.filename or ''
            if '/' in name or '\\' in name or name in {'.','..'} or ':' in name or Path(name).suffix.lower() not in {'.pdf','.txt','.md'}:
                raise HTTPException(422, '仅支持安全命名的PDF/文本/Markdown')
            body = await f.read(10*1024*1024+1)
            if len(body)>10*1024*1024:
                raise HTTPException(413, '每个附件最多10MB')
            # Upload is retained for future/manual use, not silently injected into RAG.
            folder = s.data/'uploads'/thread_id
            folder.mkdir(parents=True,exist_ok=True)
            name = uuid.uuid4().hex+'_'+name
            (folder/name).write_bytes(body)
            saved.append(name)
        return {'files': saved, 'note': '附件已保存；第一版课程知识仍通过RAG正式发布资料获取，附件不自动成为报告依据'}

    @app.websocket('/ws/{thread_id}')
    async def websocket(ws: WebSocket, thread_id: str):
        await ws.accept()
        after = int(ws.query_params.get('after','0')) if ws.query_params.get('after','0').isdigit() else 0
        try:
            while True:
                task = next((t for t in store.tasks() if t['thread_id']==thread_id), None)
                if task:
                    for event in store.events(task['id'], after):
                        await ws.send_json(event)
                        after = event['seq']
                try:
                    await asyncio.wait_for(ws.receive_text(), timeout=.5)
                    await ws.send_json({'type':'pong'})
                except TimeoutError:
                    pass
        except (WebSocketDisconnect, RuntimeError):
            pass

    dist = ROOT/'frontend/dist'
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist,html=True), name='frontend')
    return app


app = create_app()
