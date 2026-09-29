"""Local browser interface for CostGuard; no third-party packages needed."""
import argparse
import json
import sqlite3
import sys
import threading
import webbrowser
from decimal import InvalidOperation
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import costguard

WEB = Path(__file__).resolve().parent
SAMPLES = {
    'terraform-azure-create', 'terraform-azure-upgrade', 'terraform-azure-delete',
    'plan-a-small-add', 'plan-b-upgrade-delete', '01-create', '02-delete',
    '03-upgrade', '04-hostile-noise', '05-tags-only', '06-replace', '07-downgrade',
}
MAX_REQUEST = 10 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_bytes(self, code, body, content_type):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, data):
        self.send_bytes(code, json.dumps(data, default=str).encode('utf-8'), 'application/json; charset=utf-8')

    def do_GET(self):
        paths = {'/': ('index.html','text/html; charset=utf-8'),
                 '/style.css': ('style.css','text/css; charset=utf-8'),
                 '/app.js': ('app.js','text/javascript; charset=utf-8')}
        if self.path not in paths:
            self.send_json(404, {'error':'Not found'})
            return
        filename, content_type = paths[self.path]
        self.send_bytes(200, (WEB / filename).read_bytes(), content_type)

    def do_POST(self):
        expected_host = f'127.0.0.1:{self.server.server_port}'
        origin = self.headers.get('Origin')
        if self.headers.get('Host') != expected_host or (origin and origin != 'http://' + expected_host):
            self.send_json(403, {'error':'Open this page through the local CostGuard address.'})
            return
        try:
            length = int(self.headers.get('Content-Length','0'))
            if length < 1 or length > MAX_REQUEST:
                raise ValueError('Plan request must be between 1 byte and 10 MB')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Expected a JSON request object')
            if self.path == '/api/clear-cache':
                pricing = costguard.Pricing(ROOT / 'pricing_cache.db')
                try:
                    pricing.clear()
                finally:
                    pricing.db.close()
                self.send_json(200, {'message':'Price cache cleared. The next run will request fresh Azure prices.'})
            elif self.path == '/api/analyze':
                self.send_json(200, evaluate(payload))
            else:
                self.send_json(404, {'error':'Not found'})
        except (ValueError, TypeError, KeyError, InvalidOperation) as error:
            self.send_json(400, {'error':str(error)})
        except (OSError, sqlite3.Error) as error:
            self.send_json(500, {'error':str(error)})


def evaluate(payload, transport=costguard.fetch, cache=None):
    source = payload.get('source')
    if source == 'sample':
        sample = payload.get('sample')
        if sample not in SAMPLES:
            raise ValueError('Choose one of the included sample plans')
        plan = json.loads((ROOT / 'test-plans' / (sample + '.json')).read_text(encoding='utf-8'))
    elif source == 'upload':
        plan = payload.get('plan')
    else:
        raise ValueError('Choose a sample or upload a plan JSON file')
    currency = payload.get('currency','USD')
    if currency not in ('USD','EUR','GBP','INR'):
        raise ValueError('Unsupported currency')
    limit = costguard.decimal(payload.get('max_increase','50'))
    if limit < 0:
        raise ValueError('Budget limit must be zero or greater')
    offline = payload.get('offline') is True
    refresh = payload.get('refresh') is True
    auto_refresh_hours = 24 if payload.get('auto_refresh') is True else 0
    if offline and (refresh or auto_refresh_hours):
        raise ValueError('Cached-only mode cannot be combined with an Azure refresh option.')
    pricing = costguard.Pricing(cache or ROOT / 'pricing_cache.db', currency, timeout=20,
                                offline=offline, transport=transport, refresh=refresh,
                                auto_refresh_hours=auto_refresh_hours)
    try:
        rows, warnings, skipped = costguard.analyze(plan, pricing)
        return costguard.summarize(rows, warnings, skipped, pricing, limit, strict=True)
    finally:
        pricing.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='Print URL without opening a browser')
    args = parser.parse_args()
    server = HTTPServer(('127.0.0.1', 0), Handler)
    address = f'http://127.0.0.1:{server.server_port}/'
    print('CostGuard is running at', address, flush=True)
    print('Keep this window open. Press Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(address, new=1)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nCostGuard stopped.', flush=True)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
