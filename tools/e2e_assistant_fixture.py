"""Loopback chat/embedding fixture and recording proxy; captures stay private.

See docs/verification/assistant-memory-plan.md. Main and auxiliary completions
have distinct markers. Never publish captures from a real database copy.
"""
import argparse
import hashlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--directory', type=Path, required=True)
    ap.add_argument('--sidecar', required=True)
    ap.add_argument('--chat-port', type=int, default=18095)
    ap.add_argument('--proxy-port', type=int, default=18731)
    args = ap.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    control = args.directory / 'control.json'
    if not control.exists():
        control.write_text('{}')
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_headers(self, status=200, content_type='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
            self.end_headers()

        def reply(self, value, status=200):
            self.send_headers(status)
            self.wfile.write(json.dumps(value, ensure_ascii=False).encode())

        def do_OPTIONS(self):
            self.reply({})

        def do_GET(self):
            self.reply({'data': [{'id': 'assistant-fixture'}]})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            state = json.loads(control.read_text())
            stamp = time.time_ns()
            if self.server.server_port == args.proxy_port:
                row = {'path': self.path, 'payload': payload}
                if state.get('offline'):
                    code, result = 503, {'error': 'synthetic outage'}
                else:
                    req = urllib.request.Request(args.sidecar + self.path,
                          data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
                    try:
                        with urllib.request.urlopen(req, timeout=30) as response:
                            code, result = response.status, json.load(response)
                    except urllib.error.HTTPError as error:
                        code, result = error.code, json.loads(error.read())
                    except OSError:
                        code, result = 503, {'error': 'test sidecar unavailable'}
                row.update(status=code, receipt=result)
                with lock:
                    with (args.directory / 'proxy.jsonl').open('a') as file:
                        file.write(json.dumps(row, ensure_ascii=False) + '\n')
                if state.get('drop_next') and self.path == '/assistant/submit' and code == 202:
                    state['drop_next'] = False
                    control.write_text(json.dumps(state))
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.reply(result, code)
                return
            if self.path.endswith('/embeddings'):
                texts = payload['input'] if isinstance(payload['input'], list) else [payload['input']]
                self.reply({'data': [{'index': i, 'embedding': [v / 255 for v in hashlib.sha256(s.encode()).digest()]}
                                     for i, s in enumerate(texts)], 'model': 'local-test', 'usage': {}})
                return
            kind = 'auxiliary' if self.path.startswith('/summary/') else 'main'
            (args.directory / f'{kind}-{stamp}.json').write_text(json.dumps(payload, ensure_ascii=False))
            if kind == 'main' and state.get('fail_main'):
                self.reply({'error': 'synthetic generation failure'}, 503)
                return
            text = ('HYPAV3_AUXILIARY_ONLY。辅助摘要标记：阿澄保存红色门卡。' if kind == 'auxiliary'
                    else '<Thoughts>HIDDEN_REASONING_ONLY</Thoughts>ASSISTANT_REPLY_ONLY。林舟已归还蓝色地图，阿澄将地图收藏在图书馆。')
            if kind == 'main':
                text = state.get('assistant_reply', text)
            if kind == 'main' and not state.get('no_clock'):
                text += '<statusData>time:14:00|date:4月22日 周三|daysElapsed:16</statusData>'
            if payload.get('stream'):
                self.send_headers(content_type='text/event-stream')
                for part in (text[:25], text[25:70], text[70:]):
                    chunk = {'id': str(stamp), 'object': 'chat.completion.chunk', 'model': kind,
                             'choices': [{'index': 0, 'delta': {'content': part}, 'finish_reason': None}]}
                    self.wfile.write(('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n').encode())
                    self.wfile.flush()
                    time.sleep(.05)
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
            else:
                self.reply({'id': str(stamp), 'object': 'chat.completion', 'model': kind,
                            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text},
                                         'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})

    for port in (args.chat_port, args.proxy_port):
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print('Assistant E2E fixtures ready', flush=True)
    threading.Event().wait()


if __name__ == '__main__':
    main()
