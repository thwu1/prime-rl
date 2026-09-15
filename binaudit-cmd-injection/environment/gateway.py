#!/usr/bin/env python3
"""binaudit-gateway: HTTP upload service for automated .bscan analysis."""
import configparser
import http.server
import os
import subprocess
import tempfile

CONFIG_PATH = '/etc/binaudit/gateway.conf'


def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    return cfg


_cfg = load_config()
HOST = _cfg.get('service', 'listen_host', fallback='127.0.0.1')
PORT = int(_cfg.get('service', 'listen_port', fallback='4141'))
BINAUDIT = _cfg.get('service', 'binaudit_path', fallback='/app/binaudit/binaudit.py')
UPLOAD_DIR = _cfg.get('service', 'upload_dir', fallback='/tmp/binaudit-uploads')
MAX_UPLOAD = int(_cfg.get('service', 'max_upload_bytes', fallback='65536'))

os.makedirs(UPLOAD_DIR, exist_ok=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/api/v2/scan':
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get('Content-Length', 0))
        if length == 0 or length > MAX_UPLOAD:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Invalid payload size\n')
            return

        body = self.rfile.read(length)

        fd, path = tempfile.mkstemp(suffix='.bscan', dir=UPLOAD_DIR)
        with os.fdopen(fd, 'wb') as f:
            f.write(body)

        try:
            result = subprocess.run(
                ['python3', BINAUDIT, '--execute', path],
                capture_output=True, text=True, timeout=60,
                cwd='/app'
            )
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write((result.stdout + result.stderr).encode())
        except subprocess.TimeoutExpired:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'Processing timeout\n')
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    server = http.server.HTTPServer((HOST, PORT), Handler)
    print(f'binaudit-gateway listening on {HOST}:{PORT}', flush=True)
    server.serve_forever()
