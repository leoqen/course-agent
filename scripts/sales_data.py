"""Generate demo SQLite/reference files or explicitly import into the demo MySQL DB."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from korean.config import Settings
from korean.sales import generate, SCHEMA


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--import-mysql',action='store_true')
    args=parser.parse_args()
    s=Settings.env()
    path=generate(s.data)
    print('合成数据已生成：',path)
    if not args.import_mysql:
        return
    if s.mysql_database!='korean_sales_demo':
        raise SystemExit('仅允许导入 korean_sales_demo，禁止操作现有RAG数据库')
    import pymysql
    conn=pymysql.connect(host=s.mysql_host,port=s.mysql_port,user=s.mysql_user,password=s.mysql_password,
                         database=s.mysql_database,charset='utf8mb4',autocommit=False)
    try:
        with conn.cursor() as c:
            for statement in SCHEMA.split(';'):
                if statement.strip():c.execute(statement)
            for table in ('courses','orders','refunds'):
                c.execute('SELECT COUNT(*) FROM '+table)
                if c.fetchone()[0]:raise ValueError('目标库不为空，请使用已有数据；禁止覆盖')
            body=json.loads((s.data/'sales-source.json').read_text('utf-8'))
            for table,width in [('courses',4),('orders',6),('refunds',4)]:
                c.executemany('INSERT INTO '+table+' VALUES('+','.join(['%s']*width)+')',body[table])
        conn.commit()
        print('已导入MySQL合成销售库。运行时切换为只读账号。')
    except Exception:
        conn.rollback()
        raise
    finally:conn.close()


if __name__=='__main__':main()
