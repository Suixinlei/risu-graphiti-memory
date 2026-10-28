"""Real sidecar/Neo4j/model + backfill CLI acceptance on an isolated service.

See docs/verification/v0.1.3-plan.md. Uses only synthetic content. The output
directory must be new; an explicit --base prevents accidental default targets.
"""
import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    events = []
    group = 'e2e-v013-' + str(time.time_ns())

    def record(label, **fields):
        events.append({'check': label, **fields})
        (args.out / 'results.json').write_text(json.dumps(events, ensure_ascii=False, indent=2))
        print(label, flush=True)

    def request(path, body=None, status=200):
        req = urllib.request.Request(args.base + path,
              data=json.dumps(body).encode() if body is not None else None,
              headers={'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            value = json.load(response)
            assert response.status == status, (path, response.status, value)
            return value

    def complete(payload):
        start = time.monotonic()
        while time.monotonic() - start < 600:
            receipt = request('/episode/submit', payload, 202)
            if receipt['status'] == 'completed':
                return receipt
            time.sleep(3)
        raise TimeoutError(payload['name'])

    def names(gid=group):
        return request('/episodes?' + urllib.parse.urlencode({'group_id': gid}))['names']

    payload = {'group_id': group, 'name': 'receipt-1', 'source': 'message',
               'body': '阿澄把钴蓝信标钥匙交给林舟保管。钴蓝信标钥匙现在归林舟所有。',
               'reference_time': '2026-04-22T10:00:00+08:00', 'source_description': 'synthetic-e2e'}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(lambda _: request('/episode/submit', payload, 202), range(3)))
    assert all(r['status'] in ('pending', 'completed') for r in receipts)
    health = request('/health')
    assert health['ingest_protocol'] == 2
    record('PASS concurrent duplicate submission', receipts=receipts, health=health)
    complete(payload)
    assert names().count('receipt-1') == 1
    assert request('/episode/submit', payload, 202)['status'] == 'completed'
    request('/episode/submit', {**payload, 'body': '不同的内容'}, 409)
    record('PASS completion receipt, committed replay, and conflicting-content rejection')

    changed = {**payload, 'name': 'receipt-2', 'reference_time': '2026-04-22T11:00:00+08:00',
               'body': '林舟已把钴蓝信标钥匙归还阿澄。现在钥匙归阿澄所有，林舟不再持有钥匙。'}
    complete(changed)
    facts = request('/search', {'group_id': group, 'query': '钴蓝信标钥匙的所有权如何变化', 'limit': 50})['facts']
    record('OBSERVED temporal extraction', group=group, facts=facts)
    assert any('阿澄' in f['fact'] for f in facts)
    assert any(f['invalid_at'] or f['expired'] for f in facts), 'temporal invalidation missing'
    isolated = request('/search', {'group_id': group + '-empty', 'query': '钴蓝信标钥匙', 'limit': 50})['facts']
    assert not isolated
    record('PASS real extraction, embedding, temporal invalidation and group isolation', facts=facts)

    dump = args.out / 'dump/characters/Synthetic--source-id/chats'
    dump.mkdir(parents=True)
    messages = [{'role': 'char', 'data': text, 'time': 1700000000000 + i * 1000}
                for i, text in enumerate(['图书馆的蓝色书柜收藏星图。', '星图属于图书管理员阿澄。', '林舟负责保管图书馆的红色门卡。'])]
    chat = {'id': 'source-chat', 'message': messages}
    (dump / '000.json').write_text(json.dumps(chat, ensure_ascii=False))

    def export(last, batch, filename):
        file = args.out / filename
        subprocess.run([sys.executable, str(ROOT / 'tools/backfill.py'), 'export',
                        '--dump', str(args.out / 'dump'), '--char', 'source-id',
                        '--last', str(last), '--batch', str(batch), '--out', str(file)], check=True, capture_output=True)
        return file, [json.loads(s) for s in file.read_text().splitlines()]

    short_file, short = export(2, 1, 'short.jsonl')
    full_file, full = export(3, 1, 'full.jsonl')
    _, batched = export(3, 2, 'batch2.jsonl')
    assert short[0]['name'] != full[0]['name']
    assert [e['name'] for e in short] == [e['name'] for e in full[1:]]
    assert batched[0]['name'] not in {e['name'] for e in full}
    # Same text in different source positions and changed source content.
    chat['message'][0]['data'] = chat['message'][1]['data']
    (dump / '000.json').write_text(json.dumps(chat, ensure_ascii=False))
    _, edited = export(3, 1, 'edited.jsonl')
    assert edited[0]['name'] != edited[1]['name'] and edited[0]['name'] != full[0]['name']
    record('PASS absolute-position/content names across windows, batches, repeats and edits')

    def ingest(file, gid):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/backfill.py'), 'ingest',
                  '--file', str(file), '--group', gid, '--sidecar', args.base,
                  '--skip-existing', '--pace', '0', '--interval', '0'], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        record('PASS CLI confirmed completion', output=result.stdout)

    backfill_group = group + '-backfill'
    ingest(short_file, backfill_group)
    ingest(full_file, backfill_group)
    assert sorted(names(backfill_group)) == sorted(e['name'] for e in full)
    record('PASS overlapping real backfills: 3 distinct episodes, no duplicates or skipped first message')

    legacy_group = group + '-legacy'
    legacy = {**payload, 'group_id': legacy_group, 'name': 'bf-0000-0000'}
    complete(legacy)
    oldfile = args.out / 'legacy.jsonl'
    oldfile.write_text(json.dumps(legacy, ensure_ascii=False) + '\n')
    ingest(oldfile, legacy_group)
    assert names(legacy_group) == ['bf-0000-0000']
    oldfile.write_text(json.dumps({**legacy, 'body': '阿澄把黄色罗盘赠送给林舟。'}, ensure_ascii=False) + '\n')
    ingest(oldfile, legacy_group)
    assert len(names(legacy_group)) == 2
    record('PASS legacy migration: identical content reused, same old name/different content ingested')
    record('PASS service and CLI E2E', group=group, health=request('/health'))


if __name__ == '__main__':
    main()
