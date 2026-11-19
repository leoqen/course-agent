from langchain_core.messages import AIMessageChunk

from korean.report_tables import (SALES_MARKER, SalesMarkerStream, compose_sales_answer,
                                  render_sales_tables, remember_table, sales_render_instruction)
from korean.streaming import AnswerStream
from korean.store import Store
from korean.models import TaskRequest


def monthly():
    return {'type': 'monthly', 'rows': [
        {'month': '2026-08', 'start': '2026-08-10', 'end_exclusive': '2026-09-01',
         'orders': 0, 'receipts': '0.00', 'refunds': '1680.00', 'net_receipts': '-1680.00',
         'evidence_ids': ['Q111111111111', 'Q222222222222']},
        {'month': '2026-12', 'start': '2026-12-30', 'end_exclusive': '2027-01-01',
         'orders': 1, 'receipts': '0.01', 'refunds': '0.00', 'net_receipts': '0.01',
         'evidence_ids': ['Q333333333333', 'Q444444444444']} ]}


def test_monthly_output_keeps_empty_refund_only_rows_decimal_and_cross_year_bounds():
    table = render_sales_tables([monthly()], 'M111111111111')
    assert '| 2026-08-10～09-01 | 0 | 0.00 | 1680.00 | -1680.00 | [Q111111111111][Q222222222222] |' in table
    assert '2026-12-30～2027-01-01' in table
    assert '| 0.01 | 0.00 | 0.01 |' in table
    assert '净收款非利润[M111111111111]' in table
    assert '非利润' not in render_sales_tables([monthly()])


def test_custom_channel_cells_empty_results_and_truncation_are_preserved():
    t = {'type': 'channels', 'columns': ['channel', 'orders', 'receipts'],
         'rows': [['内容|平台\n换行', 3, '0.10']], 'evidence_ids': ['Q111111111111'], 'truncated': True}
    text = render_sales_tables([t])
    assert '内容\\|平台 换行' in text and '| 3 | 0.10 |' in text and '已截断' in text
    assert '无结果' in render_sales_tables([t | {'rows': []}])
    custom = t | {'type': 'custom_sql', 'columns': ['average'], 'rows': [[None]]}
    assert '| 未知 |' in render_sales_tables([custom])
    custom_note = render_sales_tables([custom], 'M111111111111')
    assert '实际查询返回结果' in custom_note and '成交及收款按付款时间统计' not in custom_note


def test_repeat_queries_replace_evidence_but_distinct_custom_queries_remain():
    tables = []; a = monthly()
    remember_table(tables, a)
    remember_table(tables, a | {'rows': []})
    assert tables == [a | {'rows': []}]
    for sql in ['SELECT 1', 'SELECT 2']:
        remember_table(tables, {'type': 'custom_sql', 'columns': ['n'], 'rows': [[1]], 'sql': sql})
    assert len(tables) == 3


def test_slot_contract_cannot_hide_model_sales_table_or_missing_slot():
    table = render_sales_tables([monthly()])
    text, issues = compose_sales_answer('课程说明\n'+SALES_MARKER, table)
    assert not issues and text == '课程说明\n'+table
    assert compose_sales_answer('没写标记', table)[1]
    assert compose_sales_answer(SALES_MARKER*2, table)[1]
    assert compose_sales_answer('| 订单 | 收款 |\n| 9 | 123 |\n'+SALES_MARKER, table)[1]
    assert SALES_MARKER not in compose_sales_answer(SALES_MARKER*2, table)[0]
    assert compose_sales_answer('课程说明', '') == ('课程说明', [])
    assert '其他正文硬上限0字符' in sales_render_instruction(table, 20)


def test_end_boundary_cannot_match_the_next_months_row():
    from korean.handoff import check_sales_row_citations
    rows = [monthly()['rows'][0], monthly()['rows'][0] | {
        'month': '2026-09', 'start': '2026-09-01', 'end_exclusive': '2026-10-01',
        'evidence_ids': ['Q333333333333', 'Q444444444444']}]
    t = {'type': 'monthly', 'rows': rows}
    assert not check_sales_row_citations(render_sales_tables([t]), [{'tables': [t]}])


def test_slot_expands_across_every_chunk_split_and_reconnect_uses_same_text(tmp_path):
    table = render_sales_tables([monthly()])
    raw = '开头\n'+SALES_MARKER+'\n结尾'
    for split in range(len(raw)+1):
        transform = SalesMarkerStream(lambda: table)
        actual = transform.feed(raw[:split])+transform.feed(raw[split:])
        assert actual == raw.replace(SALES_MARKER, table)
    store = Store(tmp_path); task = store.create(TaskRequest(course_id='K01', research_scope='sales'))
    stream = AnswerStream(store, task['id'], SalesMarkerStream(lambda: table))
    for chunk in ['开头\n[[SALE', 'S_TABLES]]', '\n结尾']:
        stream.push(AIMessageChunk(content=chunk, id='one'), {'tags': ['answer_main']})
    stream.flush()
    assert store.stream_snapshot(task['id'])['task']['draft'] == raw.replace(SALES_MARKER, table)
    stream.clear()
    stream.push(AIMessageChunk(content=SALES_MARKER, id='two'), {'tags': ['answer_main']})
    stream.flush()
    assert Store(tmp_path).get(task['id'])['draft'] == table
