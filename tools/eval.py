"""M2 decision-gate evaluation: run representative retrieval questions against
a backfilled group and print the facts for human assessment.

Three categories (per plan):
  A. attribute/relationship change history  (状态变化链)
  B. event causality / what happened        (事件因果)
  C. side-character scene recall            (配角场景召回)

Also runs two automatic checks:
  - duplicate entity names (dedupe failure)
  - orphan episodes / failed ingest ratio (via /health)

Usage:
  python3 eval.py --group akademy-main-eval --sidecar http://127.0.0.1:8710
  python3 eval.py --group ... --question "自定义问题"
"""

import argparse
import json
import urllib.request

QUESTIONS = {
    'A · 状态变化': [
        '柚月最近对主角的态度变化',
        '主角和柚月的关系现在怎么样了',
        '诗织对主角的态度有什么变化',
    ],
    'B · 事件因果': [
        '合鸣银戒是怎么来的',
        '医疗检查那次发生了什么',
        '最近有什么重要的约定或计划',
    ],
    'C · 配角场景': [
        '达莉娅最近出现在哪些场景',
        '香奈诗和主角之间发生过什么',
    ],
}


def post(base: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f'{base}{path}', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(f'{base}{path}', timeout=30) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--group', required=True)
    ap.add_argument('--sidecar', default='http://127.0.0.1:8710')
    ap.add_argument('--question', help='run a single custom question instead of the set')
    ap.add_argument('--limit', type=int, default=6)
    args = ap.parse_args()

    health = get(args.sidecar, '/health')
    print(f"health: processed={health['processed']} failed={health['failed']} queue={health['queue_depth']}")
    if health['queue_depth']:
        print('!! ingestion still in progress — results are partial')

    # duplicate-name check
    ents = get(args.sidecar, f'/entities?group_id={args.group}&limit=500')['entities']
    names = {}
    for e in ents:
        names.setdefault(e['name'], []).append(e['labels'])
    dups = {k: v for k, v in names.items() if len(v) > 1}
    print(f'entities: {len(ents)} distinct names, duplicates: {dups if dups else "none ✓"}')

    questions = (
        {'custom': [args.question]} if args.question else QUESTIONS
    )
    for cat, qs in questions.items():
        print(f'\n{"=" * 12} {cat} {"=" * 12}')
        for q in qs:
            print(f'\nQ: {q}')
            try:
                facts = post(
                    args.sidecar, '/search', {'group_id': args.group, 'query': q, 'limit': args.limit}
                )['facts']
            except Exception as e:
                print(f'  SEARCH ERROR: {e}')
                continue
            if not facts:
                print('  (no facts returned)')
            for i, f in enumerate(facts, 1):
                mark = '[已失效]' if f['expired'] else ('[被推翻]' if f['invalid_at'] else '[有效]')
                print(f'  {i}. {mark} {f["fact"]}')


if __name__ == '__main__':
    main()
