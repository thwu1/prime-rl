#!/usr/bin/env python3
"""Simple HTTP backend server that identifies itself in responses.

"""
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('X-Backend-Port', str(self.server.server_port))
        self.end_headers()
        self.wfile.write(f'backend:{self.server.server_port}\n'.encode())

    def log_message(self, format, *args):
        pass  # suppress access logs


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    server = HTTPServer(('127.0.0.1', port), Handler)
    print(f'Backend listening on 127.0.0.1:{port}')
    server.serve_forever()
