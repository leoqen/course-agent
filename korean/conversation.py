"""Conservative chat context resolution. Ambiguity produces a follow-up question."""
import re
from .config import COURSES
from .models import TaskRequest


def resolve(body, previous, pending):
    text='\n'.join(pending+[body.message.strip()])
    context = previous['request'].copy() if previous else {}
    context.update(query=text,thread_id=body.thread_id,output_format=body.output_format)
    matched=[cid for cid,c in COURSES.items() if re.search(r'(?<![A-Za-z0-9])'+cid+r'(?![A-Za-z0-9])',text,re.I) or c['name'] in text]
    current_matches=[cid for cid,c in COURSES.items() if re.search(r'(?<![A-Za-z0-9])'+cid+r'(?![A-Za-z0-9])',body.message,re.I) or c['name'] in body.message]
    if len(current_matches)==1:
        context['course_id']=current_matches[0]
    elif len(matched)==1:
        context['course_id']=matched[0]
    elif body.course_id and not current_matches:
        context['course_id']=body.course_id
    elif len(matched)>1:
        return None,'本次要分析哪门自家课程？请指定 K01、K02 或 K03 中的一门。'
    names=re.findall(r'竞品(?:机构)?\s*[:：是为]\s*([^\n。；;]+)',text)
    if names:
        value=re.split(r'[，,](?=请|分析|对比|比较|复盘|统计|销售|日期|自家|生成|谢谢)',names[-1])[0]
        context['competitors']=[n.strip() for n in re.split(r'[,，、]',value) if n.strip()]
    elif body.competitors is not None:
        context['competitors']=body.competitors
    dates=re.findall(r'(?<!\d)2026-\d{2}-\d{2}(?!\d)',text)
    if len(dates)==2:
        context.update(start_date=dates[0],end_date=dates[1])
    for key in ('start_date','end_date'):
        if getattr(body,key) is not None:context[key]=getattr(body,key)
    # Scope carries forward so a short follow-up keeps the original investigation.
    if any(x in text for x in ('只查课程','只查询课程','只看课程')):context['research_scope']='course'
    elif any(x in text for x in ('只查销售','只分析销售','只看销售')):context['research_scope']='sales'
    elif any(x in text for x in ('只查竞品','只看竞品')):context['research_scope']='network'
    elif any(x in text for x in ('完整调研','综合调研')):context['research_scope']='full'
    elif any(x in text for x in ('课程对比','对比课程','只对比','不查销售','不分析销售')):context['research_scope']='comparison'
    elif any(x in text for x in ('对比','比较')):context['research_scope']='full'
    missing=[]
    if not context.get('course_id'):missing.append('自家课程（K01 零基础入门 / K02 日常交流 / K03 TOPIK初级）')
    if context.get('research_scope','full') in {'full','comparison','network'} and not context.get('competitors'):
        missing.append('竞品机构，请回复“竞品：机构名”，最多3家')
    if missing:return None,'开始前还需要确认：\n\n'+'\n'.join('- '+x for x in missing)+'\n\n直接在对话中补充即可，例如“自家K01，竞品：机构名”。'
    return TaskRequest(**context),None
