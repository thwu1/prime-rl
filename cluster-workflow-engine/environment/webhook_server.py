#!/usr/bin/env python3
"""Simple webhook receiver that logs POST notifications to a JSONL file.

Start with: python3 /app/webhook_server.py [port]
Default port: 9876
"""

import json
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

LOG_PATH = "/app/webhook_log.jsonl"
_log_lock = threading.Lock()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except Exception:
            data = {"raw": body.decode("utf-8", errors="replace")}

        with _log_lock:
            with open(LOG_PATH, "a") as f:
                f.write(json.dumps(data) + "\n")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format, *args):
        pass  # Suppress request logging to stderr


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9876
    server = ThreadedHTTPServer(("127.0.0.1", port), WebhookHandler)
    print(f"Webhook server listening on port {port}", file=sys.stderr)
    server.serve_forever()
