"""Fake OpenAI-compatible chat endpoint for E2E testing the RisuAI plugin.

Logs every request body to /tmp/fakellm-captures/<n>.json and returns a fixed
assistant reply — verifies (a) the memory block injected by beforeRequest
actually reaches the wire, and (b) afterRequest ingests the reply, without
spending real tokens.

Run: python3 tools/fake_llm.py   (listens 127.0.0.1:18090)
"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OUT = Path('/tmp/fakellm-captures')
OUT.mkdir(exist_ok=True)
COUNTER = {'n': 0}

REPLY = '（测试回复）柚月把伞递了过来，小声说："一起走吧，雨太大了。"'


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', '*')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == '/seed/database.bin':
            data = Path('/tmp/risu6002/patched/database.bin').read_bytes()
            self.send_response(200)
            self._cors()
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            print('[fake-llm] served patched seed', len(data), flush=True)
            return
        self.send_response(200)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'data': [{'id': 'fake-model'}]}).encode())

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        COUNTER['n'] += 1
        name = OUT / f"req-{COUNTER['n']:03d}-{int(time.time())}.json"
        name.write_bytes(body)
        stream = b'"stream": true' in body or b'"stream":true' in body
        self.send_response(200)
        self._cors()
        if stream:
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            chunk = {
                'choices': [{'delta': {'content': REPLY}, 'index': 0}],
            }
            for line in (json.dumps(chunk), '[DONE]'):
                self.wfile.write(f'data: {line}\n\n'.encode())
        else:
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        'id': 'fake',
                        'object': 'chat.completion',
                        'created': int(time.time()),
                        'model': 'fake-model',
                        'choices': [
                            {'index': 0, 'message': {'role': 'assistant', 'content': REPLY}, 'finish_reason': 'stop'}
                        ],
                        'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
                    }
                ).encode()
            )
        print(f'[fake-llm] captured {name} stream={stream}', flush=True)

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    print('fake llm on http://127.0.0.1:18090/v1/chat/completions', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 18090), Handler).serve_forever()
