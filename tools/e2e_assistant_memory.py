"""Real assistant-summary + Graphiti + Neo4j acceptance. See assistant-memory-plan.md."""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(exist_ok=False, parents=True)
    gid = 'assistant-e2e-' + str(time.time_ns())
    events = []

    def record(check, **fields):
        events.append({'check': check, **fields})
        (args.out / 'results.json').write_text(json.dumps(events, ensure_ascii=False, indent=2))
        print(check, flush=True)

    def request(path, body, expected=200):
        req = urllib.request.Request(args.base + path, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            data = json.load(response)
            assert response.status == expected, (response.status, data)
            return data

    def complete(payload):
        for _ in range(200):
            receipt = request('/assistant/submit', payload, 202)
            assert receipt['protocol'] == 3
            if receipt['status'] == 'completed':
                return
            time.sleep(3)
        raise TimeoutError('assistant summary/graph did not complete')

    payload = {'group_id': gid, 'name': 'assistant-v3-test-1',
               'body': '阿澄把蓝色地图交给林舟保管。林舟承诺明天下午三点在图书馆归还地图。',
               'reference_time': '2026-04-22T10:00:00+08:00', 'source_description': 'synthetic-assistant',
               'message_id': 'source-message-1'}
    start = time.monotonic()
    first = request('/assistant/submit', payload, 202)
    assert first['status'] == 'pending'
    record('PASS durable acceptance without waiting for summary', receipt=first,
           elapsed_seconds=round(time.monotonic() - start, 3))
    request('/assistant/submit', {**payload, 'body': '不同正文'}, 409)
    complete(payload)
    assert request('/assistant/submit', payload, 202)['status'] == 'completed'
    record('PASS assistant summary and graph complete; duplicate replay and conflict rejection')
    memory = request('/memory', {'group_id': gid, 'query': '蓝色地图何时归还，约定在哪里', 'limit': 8})
    assert len(memory['recap']) == 1 and memory['recap'][0]['summary']
    assert any('林舟' in f['fact'] or '地图' in f['fact'] for f in memory['facts'])
    isolated = request('/memory', {'group_id': gid + '-other', 'query': '蓝色地图'})
    assert not isolated['recap'] and not isolated['facts']
    record('PASS narrative recap, graph retrieval, and group isolation', memory=memory)
    visible = request('/memory', {'group_id': gid, 'query': '蓝色地图',
                                 'visible_message_ids': ['source-message-1']})
    assert not visible['recap'] and 'context' not in visible
    record('PASS visible assistant messages do not receive duplicate recap; no rewrite mapping returned')

    # Real export/ingest CLI, not a fabricated plugin callback.
    dump = args.out / 'dump/characters/Synthetic--source/chats'
    dump.mkdir(parents=True)
    messages = [{'role': 'user', 'data': 'FORBIDDEN_USER_ONLY_请不要入库', 'time': 1},
                {'role': 'char', 'data': payload['body'], 'time': 2},
                {'role': 'user', 'data': 'FORBIDDEN_USER_ONLY_第二次', 'time': 3}]
    (dump / '000.json').write_text(json.dumps({'id': 'synthetic-chat', 'message': messages}, ensure_ascii=False))
    outfile = args.out / 'assistant.jsonl'
    subprocess.run([sys.executable, 'tools/backfill.py', 'export', '--dump', str(args.out / 'dump'),
                    '--char', 'source', '--last', '3', '--batch', '2', '--assistant-only',
                    '--out', str(outfile)], check=True, capture_output=True)
    exported = [json.loads(line) for line in outfile.read_text().splitlines()]
    assert len(exported) == 1 and 'FORBIDDEN_USER_ONLY' not in exported[0]['body']
    result = subprocess.run([sys.executable, 'tools/backfill.py', 'ingest', '--file', str(outfile),
                             '--group', gid + '-history', '--sidecar', args.base, '--pace', '0'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    history = request('/memory', {'group_id': gid + '-history', 'query': '蓝色地图'})
    assert len(history['recap']) == 1
    record('PASS assistant-only historical export and async summary ingest', output=result.stdout)
    record('PASS assistant memory service E2E', group=gid)


if __name__ == '__main__':
    main()
