"""Frozen SQL reference evaluation + optional actual agent comparison. No fake quality scores."""
import argparse
import asyncio
from datetime import date
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from korean.config import Settings, COURSES
from korean.sales import Sales, generate


def cases():
    result=[]
    prompts = {
        'sales': [
            '统计区间成交订单、收款、按退款发生时间的退款和净收款，给出SQL依据。',
            '按渠道比较成交订单与收款，说明为什么无法据此计算转化率和ROI。',
            '复盘月度销售，不将退款从成交订单数中扣除，不使用区间外的订单。',
            '统计成交客单价；若分组没有订单，客单价应标记未知而不是零。',
            '分析退款；区分退款发生时间与原订单付款时间，不能用退款笔数直接计算退款率。'],
        'rag': [
            '查询本课程价格、课时和授课方式，保留原文引用。',
            '查询服务与答疑政策，区分承诺与未公开的信息。',
            '说明本课程适合谁、有哪些前置基础，不混用其他课程字段。',
            '查询课程购买后的有效期及退款规则，注明适用条件。',
            '核实本课程学习目标和课时长度，无法查到的字段显示未知。'],
        'network': [
            '调查竞品同目标课程的公开价格、授课形式与课时，给出URL和采集时间。',
            '调查竞品是否为直播或录播，不把二者按价格直接排名。',
            '搜索竞品答疑与服务政策，搜索摘要与网页正文分别标注。',
            '查询竞品公开优惠及适用期限，不能把网页采集时间当成活动生效时间。',
            '查询竞品目标人群及学习目标；未公开价格标记未知，禁止估价。'],
        'combined': [
            '比较竞品与自家课程的目标、价格和服务，结合区间销售，区分事实与推测。',
            '对比同目标课程的课时与形式；分析渠道成交，缺少费用时不计算ROI。',
            '对比课程适用人群并复盘销售收款及退款，不声称竞品造成销售变化。',
            '对比课程每节时长，明确可比性，汇总成交与净收款并给出来源。',
            '生成课程差异和经营复盘报告，缺失字段列为待确认问题，保留SQL与文档引用。'],
        'missing': [
            '核实是否提供TOPIK II备考、24小时答疑和保过承诺；无依据则说明未知或不适用。',
            '有人声称自家课能保证考级通过，请核对原文，不得将营销推测写成承诺。',
            '能否证明竞品降价导致自家销量下降？明确现有资料能支持的结论与缺失条件。',
            '能否由销售订单计算咨询转化率和投放ROI？明确缺失字段，不能自行补造。',
            '若竞品未披露单节时长或服务范围，能否计算小时单价并排名？说明缺失与可比性。']}
    for i in range(50):
        course=list(COURSES)[i%3]
        month=5+(i//3)%6
        kind=['sales','rag','network','combined','missing'][i%5]
        result.append({'id':f'E{i+1:02}','split':'dev' if i<30 else 'holdout','kind':kind,'course_id':course,
                       'start_date':f'2026-{month:02}-01','end_date':f'2026-{month+1:02}-01',
                       'research_scope': {'rag':'course','network':'network','sales':'sales'}.get(kind,'full'),
                       'query':prompts[kind][(i//5)%5],
                       'review_criteria':['事实字段与引用原文一致','SQL统计口径正确且金额与独立参考一致',
                                          '未知字段不编造','不作竞品影响销量的因果断言']})
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--split',choices=['dev','holdout'],default='dev')
    p.add_argument('--base-url',default='http://127.0.0.1:8000');p.add_argument('--competitors',default='')
    p.add_argument('--cases',type=Path,default=Path(__file__).resolve().parents[1]/'examples/eval_cases.json')
    p.add_argument('--limit',type=int,default=0,help='只运行前N例；live每例对比两次付费任务')
    args=p.parse_args();s=Settings.env();generate(s.data)
    catalog=json.loads(args.cases.read_text('utf-8'))
    selected=[x for x in catalog if x['split']==args.split]
    if args.limit:
        if args.limit<0:raise SystemExit('--limit 必须非负')
        selected=selected[:args.limit]
    if args.live:
        if not args.competitors:raise SystemExit('--live 必须指定真实竞品机构；会产生模型和搜索费用')
        asyncio.run(run_agents(args,selected,s));return
    golden=json.loads((s.data/'sales-golden.json').read_text('utf-8'));sales=Sales(s,offline=True);rows=[]
    for case in selected:
        if case['kind'] not in {'sales','combined'}:continue
        actual=sales.summary(case['course_id'],case['start_date'],case['end_date'])
        expected=golden[case['course_id']+'/'+case['start_date'][:7]]
        checks={k:actual[k]==expected[k] for k in ['orders','receipts','refunds','net_receipts','average']}
        rows.append({'id':case['id'],'checks':checks,'passed':all(checks.values())})
    report={'type':'deterministic SQL only; not agent quality','split':args.split,'cases':rows,
            'passed':sum(x['passed'] for x in rows),'total':len(rows)}
    (s.data/f'sql-evaluation-{args.split}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if any(not r['passed'] for r in rows):raise SystemExit(1)


async def run_agents(args,cases,s):
    import httpx
    folder=s.data/'evaluations'/str(time.time_ns());folder.mkdir(parents=True)
    async with httpx.AsyncClient(base_url=args.base_url,timeout=30,trust_env=False) as c:
        health=(await c.get('/api/health')).json()
        if health['mode']!='live':raise SystemExit('比较必须在live服务模式运行，不能用离线固定流程代替')
        for index,case in enumerate(cases):
            for mode in (['single','multi'] if index%2==0 else ['multi','single']):
                body={k:case[k] for k in ['query','course_id','start_date','end_date','research_scope']}
                body.update(competitors=args.competitors.split(','),analysis_mode=mode)
                response=await c.post('/api/task',json=body);response.raise_for_status();tid=response.json()['task_id']
                while True:
                    r=await c.get('/api/tasks/'+tid);r.raise_for_status();task=r.json()
                    if task['status'] not in {'QUEUED','RUNNING'}:break
                    await asyncio.sleep(1)
                evidence=(await c.get(f'/api/tasks/{tid}/evidence')).json()
                (folder/f"{case['id']}-{mode}.json").write_text(json.dumps({'case':case,'task':task,'evidence':evidence,
                   'manual_review':{'field_accuracy':None,'citation_support':None,'comparability':None}},ensure_ascii=False,indent=2),'utf-8')
    print('结果已保存，需要逐项人工标注；没有自动生成语义准确率：',folder)


if __name__=='__main__':main()
