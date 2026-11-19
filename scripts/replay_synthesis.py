"""Replay synthesis from saved handoffs; no search, RAG, SQL or expert calls.

Requires --live because it calls a paid model. This is a development regression,
not end-to-end retrieval validation or an independent holdout evaluation.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from korean.config import ROOT, Settings
from korean.handoff import (answer_policy, body_length, check_answer_contract,
                            handoff_json, retrieval_status, sentence_count, focus_handoff)
from korean.prompts import COMMON, MAIN_PROMPT, revision_instruction
from korean.runtime import normalize_citations, validate_report


def prepare_record(record):
    request = record['task']['request']
    sources = record['evidence']
    bundles = []
    for event in record['events']:
        if event['event'] != 'specialist_handoff':
            continue
        bundle = dict(event['data'])
        kind = {'network': 'network', 'course': 'rag', 'sales': 'sales'}[bundle['role']]
        bundle['retrieval_status'] = retrieval_status([s for s in sources if s['kind'] == kind])
        bundle['rejected'] = len(bundle['rejected'])
        bundles.append(focus_handoff(bundle, answer_policy(request['query'], request['research_scope'])))
    if not bundles:
        raise ValueError('Saved record has no specialist handoffs')
    return request, sources, bundles


def assess(report, request, sources, bundles):
    policy = answer_policy(request['query'], request['research_scope'])
    report = normalize_citations(report, sources)
    return report, {'characters': body_length(report), 'max_characters': policy['max_characters'],
                    'sentences': sentence_count(report), 'max_sentences': policy['max_sentences'],
                    'boundary_issues': check_answer_contract(report, sources, bundles, policy),
                    'citations': validate_report(report, sources)}


async def run(args):
    if not args.live:
        raise SystemExit('Pass --live to authorize paid synthesis calls; no automatic offline substitute.')
    settings = Settings.env()
    from langchain_openai import ChatOpenAI
    model = ChatOpenAI(model=settings.model, api_key=settings.api_key, base_url=settings.base_url,
                       temperature=0, timeout=75, max_retries=0)
    args.output.mkdir(parents=True, exist_ok=True)
    for path in args.records:
        path = path.resolve()
        path.relative_to(ROOT)
        raw = path.read_bytes()
        record = json.loads(raw)
        target = args.output / (record['case']['id'] + '.json')
        if target.exists():
            print(target.name, 'already recorded or attempted; skipped', flush=True)
            continue
        request, sources, bundles = prepare_record(record)
        policy = answer_policy(request['query'], request['research_scope'])
        prompt = COMMON + MAIN_PROMPT + '\n回答约定：' + handoff_json(policy)
        value = {'case': record['case'], 'source_record': str(path.relative_to(ROOT)),
                 'source_sha256': hashlib.sha256(raw).hexdigest(),
                 'code_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted((ROOT / 'korean').glob('*.py')) + [Path(__file__)]},
                 'type': 'paid synthesis on recorded handoffs; not end-to-end or holdout',
                 'attempts': [], 'review_status': 'running'}

        def save():
            target.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')

        # Persist before every request; failures and interruption never resubmit.
        save()
        try:
            messages = [{'role': 'system', 'content': prompt},
                        {'role': 'user', 'content': handoff_json({'request': request, 'checked_handoffs': bundles})}]
            for attempt in range(2):
                value['request_in_flight'] = attempt + 1
                save()
                response = await model.ainvoke(messages)
                report, quality = assess(response.content, request, sources, bundles)
                value['attempts'].append({'report': report, 'quality': quality, 'usage': response.usage_metadata})
                value['request_in_flight'] = None
                save()
                if not quality['boundary_issues'] and quality['characters'] <= quality['max_characters']:
                    break
                messages = [{'role': 'system', 'content': prompt + revision_instruction(policy)},
                            {'role': 'user', 'content': handoff_json({'request': request, 'checked_handoffs': bundles,
                             'draft_to_shorten': report, 'answer_policy': policy,
                             'boundary_issues': quality['boundary_issues']})}]
            value['review_status'] = 'needs_manual_review'
        except Exception as exc:
            value['review_status'] = 'error'
            value['error_type'] = type(exc).__name__
        save()
        print(target.name, value['review_status'], 'calls', len(value['attempts']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--records', nargs='+', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
