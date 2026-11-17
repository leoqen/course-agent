import json
from contextlib import contextmanager
import sqlite3
import time
import uuid
from pathlib import Path

TERMINAL = {'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED', 'INTERRUPTED'}


class Conflict(Exception):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'research.sqlite'
        with self.connection() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS tasks(
              id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, status TEXT NOT NULL,
              request TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
              report TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', metrics TEXT NOT NULL DEFAULT '{}');
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_thread ON tasks(thread_id)
              WHERE status IN ('QUEUED','RUNNING');
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence(
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts(
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_messages(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, role TEXT NOT NULL,
              content TEXT NOT NULL, task_id TEXT, created REAL NOT NULL);
            ''')
            columns = {r['name'] for r in c.execute('PRAGMA table_info(tasks)')}
            if 'draft' not in columns:
                c.execute("ALTER TABLE tasks ADD COLUMN draft TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def recover(self):
        with self.connection() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM tasks WHERE status IN ('QUEUED','RUNNING')")]
            c.execute("UPDATE tasks SET status='INTERRUPTED',error='服务重启，任务已中断，可新建任务重试',updated=? WHERE status IN ('QUEUED','RUNNING')", (time.time(),))
        for task_id in ids:
            self.event(task_id, 'task_status', '服务重启导致中断', {'status': 'INTERRUPTED'})

    def create(self, request):
        tid, thread = uuid.uuid4().hex, request.thread_id or uuid.uuid4().hex
        payload = request.model_dump(mode='json') | {'thread_id': thread}
        try:
            with self.connection() as c:
                c.execute('INSERT INTO tasks(id,thread_id,status,request,created,updated) VALUES(?,?,?,?,?,?)',
                          (tid, thread, 'QUEUED', json.dumps(payload, ensure_ascii=False), time.time(), time.time()))
        except sqlite3.IntegrityError as exc:
            raise Conflict('该会话已有运行任务') from exc
        return self.get(tid)

    def get(self, tid):
        with self.connection() as c:
            r = c.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
        if not r:
            return None
        return {**dict(r), 'request': json.loads(r['request']), 'metrics': json.loads(r['metrics'])}

    def message(self, thread, role, content, task_id=None):
        with self.connection() as c:
            c.execute('INSERT INTO chat_messages(thread_id,role,content,task_id,created) VALUES(?,?,?,?,?)',
                      (thread,role,content,task_id,time.time()))

    def messages(self, thread):
        with self.connection() as c:
            return [dict(r) for r in c.execute('SELECT * FROM chat_messages WHERE thread_id=? ORDER BY seq',(thread,))]

    def conversations(self):
        with self.connection() as c:
            rows=c.execute('SELECT thread_id, MIN(seq) AS first, MAX(created) AS updated FROM chat_messages GROUP BY thread_id ORDER BY updated DESC').fetchall()
            return [{'thread_id':r['thread_id'],'updated':r['updated'],
                     'title':c.execute('SELECT content FROM chat_messages WHERE seq=?',(r['first'],)).fetchone()[0][:60]} for r in rows]

    def tasks(self):
        with self.connection() as c:
            ids = [r[0] for r in c.execute('SELECT id FROM tasks ORDER BY created DESC LIMIT 100')]
        return [self.get(tid) for tid in ids]

    def update(self, tid, **fields):
        allowed = {'status', 'report', 'error', 'metrics', 'draft'}
        if not set(fields) <= allowed:
            raise ValueError('Invalid fields')
        fields['updated'] = time.time()
        if 'metrics' in fields:
            fields['metrics'] = json.dumps(fields['metrics'], ensure_ascii=False)
        with self.connection() as c:
            c.execute('UPDATE tasks SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), tid))

    def answer_chunk(self, tid, text, reset=False):
        """Persist visible draft and replay event in one transaction."""
        body = {'type': 'monitor_event', 'event': 'answer_reset' if reset else 'answer_delta',
                'message': '', 'data': {'text': text}, 'task_id': tid, 'timestamp': time.time()}
        with self.connection() as c:
            c.execute("UPDATE tasks SET draft=" + ('?' if reset else 'draft || ?') + ',updated=? WHERE id=?',
                      (text, time.time(), tid))
            cur = c.execute('INSERT INTO events(task_id,payload) VALUES(?,?)',
                            (tid, json.dumps(body, ensure_ascii=False)))
            body['seq'] = cur.lastrowid
        return body

    def stream_snapshot(self, tid):
        """Read draft and event cursor consistently, avoiding duplicate replay."""
        with self.connection() as c:
            c.execute('BEGIN')
            row = c.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
            after = c.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE task_id=?', (tid,)).fetchone()[0]
            files = [dict(r) for r in c.execute('SELECT id,name,task_id FROM artifacts WHERE task_id=?', (tid,))]
        if row is None:
            return None
        return {'task': dict(row) | {'request': json.loads(row['request']),
                'metrics': json.loads(row['metrics']), 'files': files}, 'after': after}

    def event(self, tid, name, message, data=None):
        body = {'type': 'monitor_event', 'event': name, 'message': message, 'data': data or {},
                'task_id': tid, 'timestamp': time.time()}
        with self.connection() as c:
            cur = c.execute('INSERT INTO events(task_id,payload) VALUES(?,?)', (tid, json.dumps(body, ensure_ascii=False)))
            body['seq'] = cur.lastrowid
        return body

    def events(self, tid, after=0):
        with self.connection() as c:
            rows = c.execute('SELECT seq,payload FROM events WHERE task_id=? AND seq>? ORDER BY seq', (tid, after)).fetchall()
        return [json.loads(r['payload']) | {'seq': r['seq']} for r in rows]

    def evidence(self, tid, kind, payload):
        eid = {'network': 'W', 'rag': 'D', 'sales': 'Q', 'sales_rules': 'M'}[kind] + uuid.uuid4().hex[:12]
        with self.connection() as c:
            c.execute('INSERT INTO evidence VALUES(?,?,?,?)', (eid, tid, kind, json.dumps(payload, ensure_ascii=False, default=str)))
        return {'evidence_id': eid, 'kind': kind, **payload}

    def sources(self, tid):
        with self.connection() as c:
            rows = c.execute('SELECT * FROM evidence WHERE task_id=? ORDER BY rowid', (tid,)).fetchall()
        return [{'evidence_id': r['id'], 'kind': r['kind'], **json.loads(r['payload'])} for r in rows]

    def artifact(self, tid, path):
        aid = uuid.uuid4().hex
        with self.connection() as c:
            c.execute('INSERT INTO artifacts VALUES(?,?,?,?)', (aid, tid, path.name, str(path.resolve())))
        return {'id': aid, 'name': path.name, 'task_id': tid}

    def files(self, tid):
        with self.connection() as c:
            return [dict(r) for r in c.execute('SELECT id,name,task_id FROM artifacts WHERE task_id=?', (tid,))]

    def file(self, aid):
        with self.connection() as c:
            r = c.execute('SELECT * FROM artifacts WHERE id=?', (aid,)).fetchone()
        return dict(r) if r else None
