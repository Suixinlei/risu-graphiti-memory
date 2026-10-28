"""Offline backfill: export chat history from a RisuAI db-dump projection into
the graphiti sidecar.

Read-only w.r.t. the RisuAI save: it only parses db-dump/ JSON files produced
by local/risu_db.py dump (a derived projection).

Message cleaning:
- strip <Thoughts>...</Thoughts> (model reasoning, often English — would
  pollute a Chinese narrative graph with reasoning artifacts)
- strip <statusData>...</statusData> (authoritative numeric state; current
  values stay in the variable system by design, not in the memory layer)

Usage:
  python3 backfill.py export --dump /path/to/db-dump --char 9e172aee --chat 0 \
      --last 100 --out messages.jsonl
  python3 backfill.py ingest --file messages.jsonl --group akademy-main \
      --sidecar http://127.0.0.1:8710 [--interval 2]
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

THOUGHTS_RE = re.compile(r'<Thoughts>.*?</Thoughts>\s*', re.DOTALL | re.IGNORECASE)
STATUS_RE = re.compile(r'<statusData>.*?</statusData>\s*', re.DOTALL | re.IGNORECASE)
TRIM_RE = re.compile(r'<trim>.*?</trim>\s*', re.DOTALL | re.IGNORECASE)


def clean(text: str) -> str:
    for rx in (THOUGHTS_RE, STATUS_RE, TRIM_RE):
        text = rx.sub('', text)
    return text.strip()


def cmd_export(args):
    dump = Path(args.dump)
    cands = list((dump / 'characters').glob(f'*--{args.char}'))
    if len(cands) != 1:
        sys.exit(f'character dir for {args.char} not found (candidates: {cands})')
    chat_files = sorted((cands[0] / 'chats').glob('*.json'))
    if args.chat >= len(chat_files):
        sys.exit(f'chat index {args.chat} out of range ({len(chat_files)} chats)')
    chat = json.loads(chat_files[args.chat].read_text())
    char_name = cands[0].name.rsplit('--', 1)[0]
    messages = chat.get('message') or []
    sel = messages[-args.last:] if args.last else messages
    out = Path(args.out)
    n = 0
    with out.open('w', encoding='utf-8') as f:
        for i, m in enumerate(sel):
            body = clean(m.get('data') or '')
            if not body:
                continue
            f.write(
                json.dumps(
                    {
                        'name': f'bf-{i:04d}',
                        'role': m.get('role'),
                        'body': body,
                        'source_description': f'backfill/{char_name}/{m.get("role", "?")}',
                        'reference_time': datetime.fromtimestamp(
                            (m.get('time') or 0) / 1000, tz=timezone.utc
                        ).isoformat(),
                    },
                    ensure_ascii=False,
                )
                + '\n'
            )
            n += 1
    print(f'exported {n}/{len(sel)} messages -> {out}')


def cmd_ingest(args):
    lines = [json.loads(x) for x in Path(args.file).read_text().splitlines() if x.strip()]
    skip = set()
    if args.skip_existing:
        with urllib.request.urlopen(f'{args.sidecar}/episodes?group_id={args.group}', timeout=30) as r:
            skip = set(json.load(r)['names'])
        print(f'skip-existing: {len(skip)} episodes already in graph')
    todo = [x for x in lines if x['name'] not in skip]
    print(f'{len(todo)}/{len(lines)} to ingest')
    ok = err = 0
    for i, ep in enumerate(todo):
        body = {
            'group_id': args.group,
            'name': ep['name'],
            'body': ep['body'],
            'source': 'message',
            'source_description': ep.get('source_description', 'backfill'),
            'reference_time': ep.get('reference_time'),
        }
        req = urllib.request.Request(
            f'{args.sidecar}/episode',
            data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                assert resp.status == 202
            ok += 1
        except Exception as e:
            err += 1
            print(f'[{i}] queue failed: {e}', file=sys.stderr)
        if args.interval and (i + 1) % args.interval == 0:
            # wait until the queue drains before piling more on (serialized
            # worker: one at a time), then keep the pacing gap
            while True:
                with urllib.request.urlopen(f'{args.sidecar}/health', timeout=10) as r:
                    h = json.load(r)
                if h['queue_depth'] == 0:
                    break
                time.sleep(3)
            time.sleep(args.pace)
        if (i + 1) % 10 == 0:
            print(f'{i+1}/{len(todo)} queued (ok={ok} err={err})', flush=True)
    print(f'done: queued={ok} err={err}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    e = sub.add_parser('export')
    e.add_argument('--dump', required=True, help='db-dump projection directory')
    e.add_argument('--char', required=True)
    e.add_argument('--chat', type=int, default=0)
    e.add_argument('--last', type=int, default=100)
    e.add_argument('--out', required=True)

    g = sub.add_parser('ingest')
    g.add_argument('--file', required=True)
    g.add_argument('--group', required=True)
    g.add_argument('--sidecar', default='http://127.0.0.1:8710')
    g.add_argument('--interval', type=int, default=1, help='queue N then wait for drain')
    g.add_argument('--pace', type=float, default=1.0, help='seconds between batches')
    g.add_argument('--skip-existing', action='store_true', help='resume: skip episode names already in the graph')

    args = ap.parse_args()
    {'export': cmd_export, 'ingest': cmd_ingest}[args.cmd](args)


if __name__ == '__main__':
    main()
