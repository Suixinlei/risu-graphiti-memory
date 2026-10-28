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
from datetime import datetime, timedelta, timezone
from pathlib import Path

THOUGHTS_RE = re.compile(r'<Thoughts>.*?</Thoughts>\s*', re.DOTALL | re.IGNORECASE)
STATUS_RE = re.compile(r'<statusData>.*?</statusData>\s*', re.DOTALL | re.IGNORECASE)
TRIM_RE = re.compile(r'<trim>.*?</trim>\s*', re.DOTALL | re.IGNORECASE)


def clean(text: str) -> str:
    for rx in (THOUGHTS_RE, STATUS_RE, TRIM_RE):
        text = rx.sub('', text)
    return text.strip()


def parse_story_time(text: str):
    """Extract the in-story clock from a <statusData> block:
    time:17:05|date:4月20日 周一|daysElapsed:14|...
    Returns {'dt': datetime, 'label': str} or None."""
    m = re.search(r'<statusData>(.*?)</statusData>', text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    fields = {}
    for kv in m.group(1).split('|'):
        if ':' in kv:
            k, _, v = kv.partition(':')
            fields[k.strip()] = v.strip()
    md = re.search(r'(\d{1,2})月(\d{1,2})日', fields.get('date', ''))
    hm = re.match(r'(\d{1,2}):(\d{2})', fields.get('time', ''))
    if not (md and hm):
        return None
    days = fields.get('daysElapsed')
    label = f"{fields.get('date', '')} {fields.get('time', '')}".strip()
    if days:
        label += f"（故事第{days}天）"
    try:
        dt = datetime(
            2026, int(md.group(1)), int(md.group(2)),
            int(hm.group(1)), int(hm.group(2)),
            tzinfo=timezone(timedelta(hours=8)),
        )
        return {'dt': dt, 'label': label}
    except ValueError:
        return None


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
    batch = max(1, args.batch)
    n = 0
    n_msg = 0
    last_story = None
    with out.open('w', encoding='utf-8') as f:
        for start in range(0, len(sel), batch):
            chunk = sel[start : start + batch]
            # 剧情时间：批内优先取最新的 statusData，没有则沿用上一次
            story = None
            for m in reversed(chunk):
                story = parse_story_time(m.get('data') or '')
                if story:
                    break
            if story:
                last_story = story
            cur = story or last_story
            parts = []
            for m in chunk:
                body = clean(m.get('data') or '')
                if not body:
                    continue
                who = '用户' if m.get('role') == 'user' else '角色'
                parts.append(f'——{who}——\n{body}')
                n_msg += 1
            if not parts:
                continue
            header = f"【剧情时间】{cur['label']}\n\n" if cur else ''
            ref = (
                cur['dt'].isoformat()
                if cur
                else datetime.fromtimestamp(
                    (chunk[-1].get('time') or 0) / 1000, tz=timezone.utc
                ).isoformat()
            )
            f.write(
                json.dumps(
                    {
                        'name': f'bf-{start:04d}-{start + len(chunk) - 1:04d}',
                        'body': header + '\n'.join(parts),
                        'source_description': f'backfill/{char_name}/batch',
                        'reference_time': ref,
                    },
                    ensure_ascii=False,
                )
                + '\n'
            )
            n += 1
    print(f'exported {n} episodes ({n_msg} msgs, batch={batch}) -> {out}')


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
    e.add_argument('--batch', type=int, default=1, help='messages per episode (more context = better entity/relationship extraction)')
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
