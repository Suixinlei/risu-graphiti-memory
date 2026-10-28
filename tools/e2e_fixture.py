"""Local synthetic chat endpoint + fault proxy for the v0.1.3 E2E plan.

Run with --directory pointing to a fresh test directory. control.json accepts
offline (bool), drop_next (bool), and reply (string). Never use with real chats.
"""

import argparse
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--sidecar', default='http://127.0.0.1:18710')
    parser.add_argument('--chat-port', type=int, default=18093)
    parser.add_argument('--proxy-port', type=int, default=18711)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    control = args.directory / 'control.json'
    if not control.exists():
        control.write_text(json.dumps({'offline': False, 'drop_next': False}))
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.send_header('Access-Control-Allow-Methods', '*')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.reply(200, {})

        def do_GET(self):
            self.reply(200, {'data': [{'id': 'graphmem-e2e'}]})

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            payload = json.loads(body)
            state = json.loads(control.read_text())
            if self.server.server_port == args.chat_port:
                stamp = time.time_ns()
                (args.directory / f'chat-{stamp}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
                latest = next((m.get('content', '') for m in reversed(payload['messages']) if m['role'] == 'user'), '')
                if 'E2E_RETURN' in latest:
                    reply = '林舟已把钴蓝信标钥匙归还阿澄。现在钥匙归阿澄所有，林舟不再持有钥匙。'
                    clock = '11:00'
                elif 'E2E_ISOLATION' in latest:
                    reply = '隔离测试站的暗号是琥珀风铃，和其他故事没有关系。'
                    clock = '10:30'
                elif 'E2E_DISABLED' in latest:
                    reply = '这是关闭记忆时的回复，关闭标记是银杏石。'
                    clock = '10:45'
                else:
                    reply = '阿澄把钴蓝信标钥匙交给林舟保管。钴蓝信标钥匙现在归林舟所有。'
                    clock = '10:00'
                reply = state.get('reply', reply) + f'<statusData>time:{clock}|date:4月22日 周三|daysElapsed:16</statusData>'
                self.reply(200, {'id': f'e2e-{stamp}', 'object': 'chat.completion', 'model': 'graphmem-e2e',
                                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': reply}, 'finish_reason': 'stop'}],
                                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
                return
            entry = {'path': self.path, 'payload': payload, 'offline': state.get('offline', False)}
            if state.get('offline'):
                entry['result'] = '503'
                self.reply(503, {'error': 'synthetic outage'})
            else:
                request = urllib.request.Request(args.sidecar + self.path, data=body, headers={'Content-Type': 'application/json'})
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        code, result = response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    code, result = error.code, json.loads(error.read())
                entry['receipt'] = result
                if state.get('drop_next') and self.path == '/episode/submit':
                    state['drop_next'] = False
                    control.write_text(json.dumps(state))
                    entry['result'] = 'response_dropped_after_accept'
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                else:
                    entry['result'] = str(code)
                    self.reply(code, result)
            with lock:
                with (args.directory / 'proxy.jsonl').open('a') as file:
                    file.write(json.dumps(entry, ensure_ascii=False) + '\n')

    chat = ThreadingHTTPServer(('127.0.0.1', args.chat_port), Handler)
    proxy = ThreadingHTTPServer(('127.0.0.1', args.proxy_port), Handler)
    threading.Thread(target=chat.serve_forever, daemon=True).start()
    print(f'Synthetic chat :{args.chat_port}; fault proxy :{args.proxy_port}', flush=True)
    proxy.serve_forever()


if __name__ == '__main__':
    main()
