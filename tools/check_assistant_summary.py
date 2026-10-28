"""Local HTTP contract checks; no database, real models, or user data.

Run before/after the delimiter change per assistant-memory-plan.md.
"""
import argparse
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sidecar'))
from assistant_memory import AssistantMemory


async def check():
    state = {'content': '', 'finish_reason': 'stop', 'requests': []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append(request)
            response = {'id': 'local-only', 'object': 'chat.completion', 'created': 0,
                        'model': 'local-fixture', 'choices': [{'index': 0,
                        'message': {'role': 'assistant', 'content': state['content']},
                        'finish_reason': state['finish_reason']}]}
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    memory = AssistantMemory(None, asyncio.Lock())
    await memory.client.close()
    memory.client = AsyncOpenAI(base_url=f'http://127.0.0.1:{server.server_port}/v1',
                                api_key='local-only', max_retries=0,
                                http_client=httpx.AsyncClient(trust_env=False))
    results = []
    summary = '阿澄收到蓝色地图。'
    cases = [
        ('complete', f'<assistant_summary>{summary}</assistant_summary>', summary, 'stop'),
        ('whitespace', f' \n<assistant_summary> {summary} </assistant_summary>\n', summary, 'stop'),
        ('complete_at_limit', f'<assistant_summary>{summary}</assistant_summary>', summary, 'length'),
        ('missing_close', f'<assistant_summary>{summary}', None, 'length'),
        ('missing_open', f'{summary}</assistant_summary>', None, 'stop'),
        ('mismatched_close', f'<assistant_summary>{summary}</other>', None, 'stop'),
        ('bare_text', summary, None, 'stop'),
        ('empty', '<assistant_summary> </assistant_summary>', None, 'stop'),
        ('nested', '<assistant_summary><assistant_summary>x</assistant_summary></assistant_summary>', None, 'stop'),
        ('duplicate', '<assistant_summary>x</assistant_summary><assistant_summary>y</assistant_summary>', None, 'stop'),
        ('preamble', 'note<assistant_summary>x</assistant_summary>', None, 'stop'),
        ('trailing_text', '<assistant_summary>x</assistant_summary>note', None, 'stop'),
        ('oversized', '<assistant_summary>' + 'a' * 2001 + '</assistant_summary>', None, 'stop'),
    ]
    try:
        for name, content, expected, finish in cases:
            state.update(content=content, finish_reason=finish)
            try:
                actual = await memory.summarize_piece('合成 assistant 原文。')
            except ValueError:
                assert expected is None, name
            else:
                assert expected is not None and actual == expected, (name, actual)
            prompt = state['requests'][-1]['messages'][0]['content']
            assert '<assistant_summary>' in prompt and '</assistant_summary>' in prompt
            results.append({'case': name, 'result': 'PASS'})
        state.update(content=f'<assistant_summary>{summary}</assistant_summary>', finish_reason='stop', requests=[])
        original = '开头。' + '合成剧情。' * 3000 + '结尾。'
        await memory.summarize(original)
        assert ''.join(r['messages'][1]['content'] for r in state['requests']) == original
        results.append({'case': 'all_input_chunks_processed', 'result': 'PASS'})
    finally:
        await memory.close()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
    return {'mode': 'local HTTP contract; not full E2E', 'real_model_calls': 0, 'results': results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    result = asyncio.run(check())
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
