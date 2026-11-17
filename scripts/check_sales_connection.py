"""Verify real MySQL reads against independent Decimal references and grants."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymysql
from korean.config import Settings
from korean.sales import Sales
from connect_sales_mysql import validate_source


def main():
    s = Settings.env()
    if s.mysql_database != 'korean_sales_demo':
        raise ValueError('仅允许验证独立销售演示库')
    body, manifest = validate_source(s.data)
    sales = Sales(s)
    golden = json.loads((s.data / 'sales-golden.json').read_text('utf-8'))
    results = []
    for key, expected in golden.items():
        course, month = key.split('/')
        actual = sales.summary(course, month + '-01', f'2026-{int(month[-2:])+1:02}-01')
        checks = {field: actual[field] == expected[field] for field in
                  ('orders', 'receipts', 'refunds', 'net_receipts', 'average')}
        results.append({'case': key, 'checks': checks, 'actual': actual})
    conn = pymysql.connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
        password=s.mysql_password, database=s.mysql_database, connect_timeout=5, autocommit=True)
    try:
        with conn.cursor() as c:
            c.execute('SHOW GRANTS')
            grants = [row[0] for row in c.fetchall()]
            only_select = all(g.startswith('GRANT USAGE ON *.*') or
                (g.startswith('GRANT SELECT ON `korean_sales_demo`.') and 'WITH GRANT OPTION' not in g)
                for g in grants)
            try:
                c.execute('UPDATE orders SET amount=amount WHERE 1=0')
                denied = False
            except pymysql.err.OperationalError as exc:
                denied = exc.args[0] == 1142
    finally:
        conn.close()
    # Independently compute the acceptance question's 3-month totals from source.
    selected = [o for o in body['orders'] if o[1]=='K01' and '2026-08-01'<=o[2]<'2026-11-01']
    ids = {o[0] for o in body['orders'] if o[1]=='K01'}
    receipts = sum((Decimal(o[3]) for o in selected), Decimal(0))
    refunds = sum((Decimal(r[3]) for r in body['refunds'] if r[1] in ids and '2026-08-01'<=r[2]<'2026-11-01'), Decimal(0))
    checks = {'reference_cases': all(all(r['checks'].values()) for r in results),
              'only_table_select_grants': only_select, 'server_denies_write': denied}
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
              'sha256': manifest['sha256'], 'orders': len(body['orders']), 'refunds': len(body['refunds']),
              'reference_cases': results, 'k01_aug_oct': {'orders': len(selected), 'receipts': str(receipts),
              'refunds': str(refunds), 'net_receipts': str(receipts-refunds)}, 'synthetic': True}
    folder = s.data / 'acceptance'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'sales-mysql-connection.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks, 'cases': len(results), 'orders': len(body['orders']),
        'refunds': len(body['refunds']), 'k01_aug_oct': report['k01_aug_oct']}, ensure_ascii=False), flush=True)
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
