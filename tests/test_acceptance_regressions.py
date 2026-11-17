import sqlite3
from contextlib import closing
import pytest
from korean.config import Settings
from korean.sales import Sales
from korean.runtime import normalize_citations, validate_report


def test_monthly_calendar_refund_only_empty_and_partial_months(tmp_path):
    sales = Sales(Settings(data=tmp_path), offline=True)
    with closing(sqlite3.connect(sales.path)) as c, c:
        c.execute('DELETE FROM refunds')
        c.execute('DELETE FROM orders')
        c.execute("INSERT INTO orders VALUES('prior','K01','2026-05-31 23:59:00',1680,'自然咨询','PAID')")
        c.execute("INSERT INTO refunds VALUES('r1','prior','2026-06-01 00:00:00',840)")
        c.execute("INSERT INTO orders VALUES('excluded','K01','2026-06-15 00:00:00',1680,'自然咨询','PAID')")
        c.execute("INSERT INTO orders VALUES('boundary','K01','2026-08-01 00:00:00',1680,'自然咨询','PAID')")
    rows = sales.monthly('K01','2026-05-31','2026-06-15')
    assert [r['month'] for r in rows] == ['2026-05','2026-06']
    assert rows[1]['orders']==0 and rows[1]['refunds']=='840.00'
    assert rows[1]['net_receipts']=='-840.00' and rows[1]['average'] is None
    empty = sales.monthly('K01','2026-07-01','2026-08-01')
    assert len(empty)==1 and empty[0]['orders']==0
    assert empty[0]['receipts']=='0.00' and empty[0]['average'] is None


def test_citation_formatting_only_known_ids_and_cited_coverage():
    sources=[{'evidence_id':'Q123456789abc','kind':'sales'}, {'evidence_id':'D123456789abc','kind':'rag'}]
    report=normalize_citations('数字 Q123456789abc，与[Q123456789abc]相同。',sources)
    assert report=='数字 [Q123456789abc]，与[Q123456789abc]相同。'
    assert normalize_citations(report,sources)==report
    assert validate_report(report,sources)['cited_coverage']==['sales']
    with pytest.raises(ValueError):normalize_citations('Q000000000000',sources)
    with pytest.raises(ValueError):validate_report('[Q000000000000]',sources)


def test_channel_tool_limits_course_and_date_without_refund_join(tmp_path):
    sales=Sales(Settings(data=tmp_path),offline=True)
    with closing(sqlite3.connect(sales.path)) as c, c:
        c.execute('DELETE FROM refunds');c.execute('DELETE FROM orders')
        c.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?)',[
            ('a','K01','2026-08-01 00:00:00',1680,'自然咨询','PAID'),
            ('b','K01','2026-08-31 23:59:00',1680,'自然咨询','PAID'),
            ('outside','K01','2026-09-01 00:00:00',1680,'广告投放','PAID'),
            ('other','K02','2026-08-05 00:00:00',2480,'自然咨询','PAID')])
        c.execute("INSERT INTO refunds VALUES('r','a','2026-08-03 00:00:00',840)")
    result=sales.channels('K01','2026-08-01','2026-09-01')
    assert result['columns']==['channel','orders','receipts']
    assert result['rows']==[['自然咨询',2,3360]]
