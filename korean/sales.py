"""Deterministic demo sales and read-only, bounded analytics."""
import calendar
from contextlib import closing
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import time

from .config import COURSES

SCHEMA = '''
CREATE TABLE IF NOT EXISTS courses(course_id VARCHAR(8) PRIMARY KEY,name VARCHAR(100),version VARCHAR(20),price DECIMAL(12,2));
CREATE TABLE IF NOT EXISTS orders(order_id VARCHAR(32) PRIMARY KEY,course_id VARCHAR(8) NOT NULL,paid_at DATETIME NOT NULL,
 amount DECIMAL(12,2) NOT NULL,channel VARCHAR(30) NOT NULL,status VARCHAR(20) NOT NULL);
CREATE TABLE IF NOT EXISTS refunds(refund_id VARCHAR(32) PRIMARY KEY,order_id VARCHAR(32) NOT NULL,
 refunded_at DATETIME NOT NULL,amount DECIMAL(12,2) NOT NULL);
'''


def money(value):
    return str(Decimal(str(value or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def generate(root: Path):
    """Idempotent generation; refuses silently overwriting different existing data."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'sales-demo.sqlite'
    rng = random.Random(20261117)
    orders, refunds = [], []
    for i in range(1800):
        month = 5 + i // 300
        course = rng.choices(['K01', 'K02', 'K03'], weights=([6, 3, 2] if month < 9 else [3, 3, 5]))[0]
        day = rng.randint(1, calendar.monthrange(2026, month)[1])
        paid = datetime(2026, month, day, rng.randint(8, 21), rng.randint(0, 59))
        oid = f'O{i+1:05}'
        channel = rng.choices(['自然咨询', '内容平台', '广告投放'], weights=([4, 3, 5] if month < 9 else [4, 3, 2]))[0]
        amount = COURSES[course]['price']
        orders.append((oid, course, paid.isoformat(sep=' '), money(amount), channel, 'PAID'))
        if rng.random() < (.05 if month < 9 else .10):
            when = paid + timedelta(days=rng.randint(1, 7))
            if when < datetime(2026, 11, 1):
                refunds.append((f'R{i+1:05}', oid, when.isoformat(sep=' '), money(amount)))
    courses = [(k, v['name'], 'demo-v1', money(v['price'])) for k, v in COURSES.items()]
    body = {'synthetic': True, 'seed': 20261117, 'timezone': 'Asia/Shanghai', 'start': '2026-05-01',
            'end_exclusive': '2026-11-01', 'courses': courses, 'orders': orders, 'refunds': refunds}
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if path.exists():
        manifest = root / 'sales-manifest.json'
        if not manifest.exists() or json.loads(manifest.read_text('utf-8'))['sha256'] != digest:
            raise ValueError('已有销售库来源不一致，请使用新的 DATA_DIR，不覆盖已有数据')
        return path
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.executemany('INSERT INTO courses VALUES(?,?,?,?)', courses)
        conn.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?)', orders)
        conn.executemany('INSERT INTO refunds VALUES(?,?,?,?)', refunds)
    (root / 'sales-manifest.json').write_text(json.dumps({k: v for k, v in body.items() if k not in {'courses', 'orders', 'refunds'}} |
        {'sha256': digest, 'order_count': len(orders), 'refund_count': len(refunds)}, ensure_ascii=False, indent=2), 'utf-8')
    (root / 'sales-source.json').write_text(json.dumps(body, ensure_ascii=False, indent=2), 'utf-8')
    # Independent reference: plain Python/Decimal, not the SQL under evaluation.
    golden = {}
    for course in COURSES:
        for month in range(5, 11):
            prefix = f'2026-{month:02}'
            selected = [o for o in orders if o[1] == course and o[2].startswith(prefix)]
            selected_ids = {o[0] for o in selected}
            course_ids = {o[0] for o in orders if o[1] == course}
            paid = sum((Decimal(o[3]) for o in selected), Decimal(0))
            returned = sum((Decimal(r[3]) for r in refunds if r[1] in course_ids and r[2].startswith(prefix)), Decimal(0))
            refunded_ids = {r[1] for r in refunds if r[1] in selected_ids}
            golden[f'{course}/{prefix}'] = {'orders': len(selected), 'receipts': money(paid), 'refunds': money(returned),
                'net_receipts': money(paid-returned), 'average': money(paid/len(selected)) if selected else None,
                'refunded_order_count': len(refunded_ids)}
    (root / 'sales-golden.json').write_text(json.dumps(golden, ensure_ascii=False, indent=2), 'utf-8')
    return path


def validate_sql(sql):
    import sqlglot
    from sqlglot import exp
    statements = sqlglot.parse(sql, read='mysql')
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError('只允许单条 SELECT；不允许多语句或写入')
    tree = statements[0]
    forbidden = (exp.Into, exp.Lock, exp.Command, exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop)
    if any(isinstance(node, forbidden) for node in tree.walk()):
        raise ValueError('查询包含禁止操作')
    # CTE/UNION are deliberately not part of v1; keeps the accepted SQL surface small.
    if tree.args.get('with_') or tree.find(exp.Union):
        raise ValueError('第一版不支持 CTE/UNION，请使用关联或聚合查询')
    tables = list(tree.find_all(exp.Table))
    if not tables or any(t.name.lower() not in {'orders', 'refunds', 'courses'} or t.db or t.catalog for t in tables):
        raise ValueError('只允许访问课程、订单与退款三张表，禁止跨库')
    allowed_funcs = {'SUM','COUNT','AVG','MIN','MAX','ROUND','COALESCE','NULLIF','ABS', 'DATE', 'YEAR', 'MONTH',
                     'DATE_FORMAT','TIME_TO_STR','TS_OR_DS_TO_TIMESTAMP','CAST','IF','CASE','IFNULL'}
    for fn in tree.find_all(exp.Func):
        name = fn.name.upper() if isinstance(fn, exp.Anonymous) else fn.sql_name().upper()
        if name not in allowed_funcs and not isinstance(fn, (exp.And, exp.Or)):
            raise ValueError('不支持的 SQL 函数：' + name)
    if tree.find(exp.Parameter) or tree.find(exp.SessionParameter):
        raise ValueError('禁止 SQL 会话变量')
    limit = tree.args.get('limit')
    if limit:
        try:
            if int(limit.expression.this) > 500:
                tree = tree.limit(501)
        except (ValueError, TypeError):
            raise ValueError('LIMIT 必须为常量')
    else:
        tree = tree.limit(501)
    return tree


class Sales:
    def __init__(self, settings, offline=False):
        self.settings, self.offline = settings, offline
        self.path = generate(settings.data) if offline else None

    def query(self, sql):
        tree = validate_sql(sql)
        started = time.perf_counter()
        if self.offline:
            with closing(sqlite3.connect(f'file:{self.path.as_posix()}?mode=ro', uri=True)) as conn:
                deadline = time.monotonic() + 5
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                cur = conn.execute(tree.sql(dialect='sqlite'))
                columns = [c[0] for c in cur.description]
                rows = cur.fetchmany(501)
        else:
            import pymysql
            s = self.settings
            conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user, password=s.mysql_password,
                database=s.mysql_database, charset='utf8mb4', connect_timeout=5, read_timeout=7,
                write_timeout=5, autocommit=True)
            try:
                with conn.cursor() as cur:
                    cur.execute('SET SESSION MAX_EXECUTION_TIME=5000')
                    cur.execute('START TRANSACTION READ ONLY')
                    cur.execute(tree.sql(dialect='mysql'))
                    columns = [c[0] for c in cur.description]
                    rows = cur.fetchmany(501)
            finally:
                conn.rollback()
                conn.close()
        return {'sql': tree.sql(dialect='sqlite' if self.offline else 'mysql'), 'columns': columns,
                'rows': [[str(v) if isinstance(v, (Decimal, date, datetime)) else v for v in row] for row in rows[:500]],
                'truncated': len(rows) > 500, 'seconds': round(time.perf_counter()-started, 3), 'synthetic': True,
                'coverage': ['2026-05-01', '2026-11-01'], 'timezone': 'Asia/Shanghai'}

    def schema(self):
        return {'ddl': SCHEMA, 'course_ids': COURSES, 'date_range': ['2026-05-01', '2026-11-01'],
                'sql_dialect': 'MySQL 8；仅单条SELECT，支持派生子查询、JOIN、GROUP BY和DATE_FORMAT(date_column,\'%Y-%m\')。'
                '不支持WITH/CTE、UNION、FULL OUTER JOIN或SQLite strftime。月度收款与退款可各用一条GROUP BY查询，保留各自证据。'
                '净收款用SELECT派生表相减计算，或逐月SELECT两个标量聚合子查询相减；不要为查询引入其他表。',
                'rules': '销售均为模拟记录。按付款时间统计成交及收款，按退款时间统计退款，区间左闭右开。退款不扣除成交订单数。金额人民币。日期字段带时间，查询使用完整日期边界。退款率按选定付款区间订单截至指定日期的成功退款订单占比。'
                '订单与退款应分别聚合后再按月份合并；按退款时间查询时，不得同时限定原订单付款时间必须在同一区间，否则会漏掉跨月退款。'
                'orders.status=PAID代表已成交，发生退款后仍保留PAID；无退款状态字段。区间净收款=区间收款-区间退款，不是利润或会计收入。'
                '没有线索、咨询人数、广告费用数据，不能计算咨询转化率或ROI。'}

    def summary(self, course_id, start, end):
        # Parameters are validated by TaskRequest, course ID from fixed catalog.
        if course_id not in COURSES:
            raise ValueError('未知课程')
        start, end = date.fromisoformat(str(start)).isoformat(), date.fromisoformat(str(end)).isoformat()
        paid = self.query(f"SELECT COUNT(*) AS orders,SUM(amount) AS receipts,AVG(amount) AS average FROM orders WHERE course_id='{course_id}' AND status='PAID' AND paid_at>='{start}' AND paid_at<'{end}'")
        refunded = self.query(f"SELECT SUM(r.amount) AS refunds FROM refunds r JOIN orders o ON o.order_id=r.order_id WHERE o.course_id='{course_id}' AND r.refunded_at>='{start}' AND r.refunded_at<'{end}'")
        count, receipts, average = paid['rows'][0]
        returned = refunded['rows'][0][0]
        return {'orders': count, 'receipts': money(receipts), 'refunds': money(returned),
                'net_receipts': money(Decimal(str(receipts or 0))-Decimal(str(returned or 0))),
                'average': money(average) if count else None, 'queries': [paid, refunded]}

    def monthly(self, course_id, start, end):
        """Calendar spine includes empty and refund-only months, with clipped bounds."""
        start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        if course_id not in COURSES or not date(2026,5,1) <= start < end <= date(2026,11,1):
            raise ValueError('月度统计仅支持已知课程及合成数据覆盖区间')
        rows = []
        cursor = start
        while cursor < end:
            next_month = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
            stop = min(next_month, end)
            rows.append({'month': cursor.strftime('%Y-%m'), 'start': cursor.isoformat(),
                         'end_exclusive': stop.isoformat(), **self.summary(course_id, cursor, stop)})
            cursor = stop
        return rows

    def channels(self, course_id, start, end):
        if course_id not in COURSES:
            raise ValueError('未知课程')
        start, end = date.fromisoformat(str(start)).isoformat(), date.fromisoformat(str(end)).isoformat()
        if not '2026-05-01' <= start < end <= '2026-11-01':
            raise ValueError('渠道统计日期超出合成资料范围')
        return self.query(f"SELECT channel,COUNT(*) AS orders,COALESCE(SUM(amount),0) AS receipts FROM orders WHERE course_id='{course_id}' AND status='PAID' AND paid_at>='{start}' AND paid_at<'{end}' GROUP BY channel ORDER BY channel")
