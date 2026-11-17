"""Provision a separate synthetic sales DB on the existing local MySQL server."""
import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import secrets
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values
import pymysql
from korean.config import ROOT
from korean.sales import generate, SCHEMA
from connect_local_rag import update

DATABASE = 'korean_sales_demo'
READER = 'korean_research_reader'
ACCOUNT_HOST = '127.0.0.1'
TABLES = {'courses': 4, 'orders': 6, 'refunds': 4}


def validate_source(folder):
    generate(folder)
    body = json.loads((folder / 'sales-source.json').read_text('utf-8'))
    manifest = json.loads((folder / 'sales-manifest.json').read_text('utf-8'))
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if digest != manifest['sha256'] or not body['synthetic']:
        raise ValueError('合成数据来源校验失败')
    orders = {o[0]: o for o in body['orders']}
    if len(orders) != 1800 or len(orders) != len(body['orders']):
        raise ValueError('订单数或订单编号异常')
    courses = {c[0]: c for c in body['courses']}
    refunded = {}
    for o in orders.values():
        if o[1] not in courses or Decimal(o[3]) != Decimal(courses[o[1]][3]):
            raise ValueError('课程或订单金额异常')
        if not body['start'] <= o[2] < body['end_exclusive'] or o[5] != 'PAID':
            raise ValueError('订单日期或状态异常')
    if len({r[0] for r in body['refunds']}) != len(body['refunds']):
        raise ValueError('退款编号重复')
    for r in body['refunds']:
        o = orders.get(r[1])
        if o is None or not o[2] <= r[2] < body['end_exclusive'] or Decimal(r[3]) <= 0:
            raise ValueError('退款关联、日期或金额异常')
        refunded[o[0]] = refunded.get(o[0], Decimal(0)) + Decimal(r[3])
        if refunded[o[0]] > Decimal(o[3]):
            raise ValueError('累计退款超过收款')
    return body, manifest


def normalize(row):
    return tuple(str(v) if isinstance(v, (Decimal, date, datetime)) else v for v in row)


def verify_rows(cursor, body):
    for table in TABLES:
        cursor.execute('SELECT * FROM ' + table)
        actual = sorted(normalize(row) for row in cursor.fetchall())
        if actual != sorted(tuple(row) for row in body[table]):
            raise ValueError('目标销售库数据不一致，保留现有数据，不覆盖：' + table)


def main(args):
    body, manifest = validate_source(ROOT / 'data')
    admin = dotenv_values(args.admin_env)
    if admin.get('MYSQL_HOST') not in {'127.0.0.1', 'localhost'}:
        raise ValueError('本脚本仅支持本机MySQL，不自动修改远程数据库')
    port = int(admin.get('MYSQL_PORT', '3306'))
    config = dotenv_values(ROOT / '.env')
    receipt_path = ROOT / 'data/sales-mysql-provision.json'
    conn = pymysql.connect(host='127.0.0.1', port=port, user=admin.get('MYSQL_USER'),
        password=admin.get('MYSQL_PASSWORD'), charset='utf8mb4', connect_timeout=5, read_timeout=15,
        write_timeout=15, autocommit=False)
    try:
        with conn.cursor() as c:
            c.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (DATABASE,))
            exists = bool(c.fetchone())
            c.execute('SELECT 1 FROM mysql.user WHERE User=%s AND Host=%s', (READER, ACCOUNT_HOST))
            account_exists = bool(c.fetchone())
            if exists or account_exists:
                if not receipt_path.exists():
                    raise ValueError('目标库或账号已存在且无本项目配置记录，不接管或覆盖')
                receipt = json.loads(receipt_path.read_text('utf-8'))
                if receipt.get('sha256') != manifest['sha256'] or config.get('MYSQL_USER') != READER:
                    raise ValueError('已有配置与本次来源不一致')
                if not exists or not account_exists:
                    raise ValueError('销售库配置不完整，请人工检查；不自动重建')
                c.execute('USE ' + DATABASE)
                verify_rows(c, body)
                print('现有合成销售库逐行核对一致；未覆盖数据或账号。')
                return
            c.execute('CREATE DATABASE ' + DATABASE + ' CHARACTER SET utf8mb4')
            c.execute('USE ' + DATABASE)
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    c.execute(statement)
            for table, width in TABLES.items():
                c.executemany('INSERT INTO ' + table + ' VALUES (' + ','.join(['%s'] * width) + ')', body[table])
            verify_rows(c, body)
            conn.commit()
            # Unique indexes also enforce the synthetic dataset's single-refund design.
            c.execute('CREATE INDEX sales_course_paid ON orders(course_id,paid_at)')
            c.execute('CREATE INDEX sales_refund_time ON refunds(refunded_at,order_id)')
            c.execute('CREATE UNIQUE INDEX sales_refund_order ON refunds(order_id)')
            password = secrets.token_urlsafe(32)
            c.execute('CREATE USER %s@%s IDENTIFIED BY %s', (READER, ACCOUNT_HOST, password))
            for table in TABLES:
                c.execute('GRANT SELECT ON ' + DATABASE + '.' + table + ' TO %s@%s', (READER, ACCOUNT_HOST))
        update(ROOT / '.env', {'MYSQL_HOST': '127.0.0.1', 'MYSQL_PORT': str(port),
            'MYSQL_DATABASE': DATABASE, 'MYSQL_USER': READER, 'MYSQL_PASSWORD': password})
        receipt_path.write_text(json.dumps({'database': DATABASE, 'host': '127.0.0.1', 'port': port,
            'reader': READER, 'sha256': manifest['sha256'], 'orders': len(body['orders']),
            'refunds': len(body['refunds']), 'synthetic': True}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('独立销售库已导入，专用账号仅有三张表SELECT权限；运行配置已保存，未复制管理员凭据。')
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin-env', type=Path, default=ROOT.parent / 'local_rag/.env')
    try:
        main(parser.parse_args())
    except Exception as exc:
        # Provider errors can contain identities; report type without credentials.
        print('销售库配置失败：' + type(exc).__name__)
        if isinstance(exc, ValueError):
            print(str(exc))
        raise SystemExit(1)
