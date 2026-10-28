"""Fault-inject only assistant summarization; forward other LLM calls unchanged."""
import argparse
import json
import sys
import threading
import urllib.request
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sidecar'))
from config import config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--directory', required=True, type=Path)
    ap.add_argument('--port', type=int, default=18096)
    ap.add_argument('--upstream', help='real LLM base URL; defaults to sidecar config')
    args = ap.parse_args()
    upstream = args.upstream or config.llm_base_url
    target = urllib.parse.urlparse(upstream)
    if target.hostname in ('127.0.0.1', 'localhost') and target.port == args.port:
        raise ValueError('summary proxy cannot forward to itself; pass --upstream')
    args.directory.mkdir(parents=True, exist_ok=True)
    control = args.directory / 'control.json'
    if not control.exists():
        control.write_text('{}')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            request = json.loads(body)
            is_summary = request.get('messages', [{}])[0].get('content', '').startswith('You summarize assistant-authored')
            state = json.loads(control.read_text())
            if is_summary and state.get('empty_summary'):
                response = {'choices': [{'message': {'role': 'assistant', 'content': ''}, 'finish_reason': 'stop'}]}
                data, status = json.dumps(response).encode(), 200
            else:
                req = urllib.request.Request(upstream.rstrip('/') + '/chat/completions',
                    data=body, headers={'Content-Type': 'application/json',
                    'Authorization': self.headers.get('Authorization', '')})
                try:
                    with urllib.request.urlopen(req, timeout=180) as result:
                        data, status = result.read(), result.status
                except urllib.error.HTTPError as error:
                    data, status = error.read(), error.code
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)

    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
