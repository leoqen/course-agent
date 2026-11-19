"""Render executed sales results, leaving interpretation to the main model."""
import json
import re

SALES_MARKER = '[[SALES_TABLES]]'


def cell(value):
    if value is None:
        return '未知'
    return str(value).replace('\\', '\\\\').replace('|', '\\|').replace('\r', '').replace('\n', ' ')


def remember_table(tables, table):
    """Repeat queries replace the same result shape, retaining latest evidence."""
    def key(t):
        return (t['type'], json.dumps(t.get('columns'), ensure_ascii=False),
                t.get('sql', ''), json.dumps(t.get('rows'), ensure_ascii=False,
                    sort_keys=True, default=str) if t['type'] == 'custom_sql' else '')
    for index, previous in enumerate(tables):
        if key(previous) == key(table):
            tables[index] = table
            return
    tables.append(table)


def sales_tables(bundles):
    tables = []
    rules = None
    for bundle in bundles:
        if bundle.get('role') != 'sales':
            continue
        for table in bundle.get('tables', []):
            remember_table(tables, table)
        if bundle.get('metric_rules'):
            rules = bundle['metric_rules']['evidence_id']
    return tables, rules


def render_sales_tables(tables, rules_id=None):
    """No recomputation, rounding, model-written values, or invented citations."""
    sections = []
    monthly = False
    for table in tables:
        if table['type'] == 'monthly':
            monthly = True
            lines = ['| 区间（左闭右开） | 订单 | 收款 | 退款 | 净收款 | 依据 |',
                     '|---|---:|---:|---:|---:|---|']
            for row in table['rows']:
                start, end = row['start'], row['end_exclusive']
                # Retain the year when crossing a year boundary.
                label = start + '～' + (end[5:] if end[:4] == start[:4] else end)
                refs = ''.join('['+eid+']' for eid in row['evidence_ids'])
                lines.append('| '+label+' | '+' | '.join(cell(row[k]) for k in
                    ['orders', 'receipts', 'refunds', 'net_receipts'])+' | '+refs+' |')
        else:
            columns = table['columns']
            labels = {'channel': '渠道', 'orders': '订单', 'receipts': '收款'}
            lines = ['| '+' | '.join(cell(labels.get(c, c)) for c in columns)+' | 依据 |',
                     '|'+'---|'*(len(columns)+1)]
            refs = ''.join('['+eid+']' for eid in table['evidence_ids'])
            lines.extend('| '+' | '.join(cell(v) for v in row)+' | '+refs+' |' for row in table['rows'])
            if not table['rows']:
                lines.append('| '+' | '.join(['无结果']+['—']*(len(columns)-1))+' | '+refs+' |')
            if table.get('truncated'):
                lines.extend(['', '查询结果已截断，仅展示实际返回记录。'+refs])
        sections.append('\n'.join(lines))
    if not sections:
        return ''
    text = '## 销售统计（合成数据，金额单位：元）\n\n'+'\n\n'.join(sections)
    if rules_id:
        note = ('收款按付款时间、退款按发生时间统计，净收款非利润' if monthly else
                '成交及收款按付款时间统计，区间左闭右开' if any(t['type'] == 'channels' for t in tables) else
                '以上为实际查询返回结果，指标解释应结合对应查询与统计口径')
        text += '\n\n'+note+'['+rules_id+']。'
    return text


def compose_sales_answer(narrative, table_text):
    """Expand one explicit slot. Missing/duplicate slots remain quality issues."""
    count = narrative.count(SALES_MARKER)
    if not table_text:
        return narrative.replace(SALES_MARKER, ''), []
    issues = []
    if count != 1:
        issues.append({'reason': '销售表格位置标记必须出现一次', 'actual': count})
    # Model-authored sales rows are never certified by inserting a correct table.
    if any(line.lstrip().startswith('|') and (re.search(r'\[Q[a-f0-9]{12}\]', line) or
           re.search(r'订单|净收款|退款|收款', line)) for line in narrative.splitlines()):
        issues.append({'reason': '销售表格由程序呈现，请删除模型撰写的销售表并仅保留位置标记'})
    if count:
        head, tail = narrative.split(SALES_MARKER, 1)
        return head + table_text + tail.replace(SALES_MARKER, ''), issues
    return narrative.rstrip()+'\n\n'+table_text, issues


def sales_render_instruction(table_text, max_characters):
    from .handoff import body_length
    remaining = max(0, max_characters - body_length(table_text))
    return ('\n销售表格由程序根据本次执行结果自动呈现。最终回答用 '+SALES_MARKER+
            ' 单独一行标记销售表位置，必须恰好一次；不要自己写销售表，也不要在正文重复订单、金额、退款等数值。'
            '你负责课程比较和必要解释。表格及必要口径同样计入整份回答字数。'
            f'当前表格占{body_length(table_text)}字符，其他正文硬上限{remaining}字符，目标{int(remaining*.65)}字符内。'
            '表格已自带收退款口径，不要再写统计时间、净收款定义、合成数据声明等重复说明。'
            '只给表和一句口径的请求仅返回位置标记，程序已提供这一句；需要说明统计能力时保留M口径引用。'
            '严格短篇课程比较只选择一门相关竞品，不复制多门未知清单。')


class SalesMarkerStream:
    """Expand a slot split across provider chunks without exposing its syntax."""
    def __init__(self, render):
        self.render = render
        self.reset()

    def reset(self):
        self.pending = ''
        self.inserted = False

    def feed(self, text):
        self.pending += text
        out = ''
        while self.pending:
            if self.pending.startswith(SALES_MARKER):
                if not self.inserted:
                    out += self.render()
                    self.inserted = True
                self.pending = self.pending[len(SALES_MARKER):]
            elif SALES_MARKER.startswith(self.pending):
                break
            else:
                out += self.pending[0]
                self.pending = self.pending[1:]
        return out
