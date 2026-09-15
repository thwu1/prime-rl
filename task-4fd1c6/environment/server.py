#!/usr/bin/env python3
"""HTTP service wrapper for the proxy configuration engine."""
import json
import sys
import os

sys.path.insert(0, "/app")
from http.server import HTTPServer, BaseHTTPRequestHandler
import engine


class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status = {
                "service": "proxy-config-engine",
                "version": "2.3.1",
                "contexts": list(engine.CONTEXTS.keys()),
                "endpoints": {
                    c: {
                        "method": "POST",
                        "path": f"/{c}",
                        "body": {
                            "username": "string",
                            "hostname": "string",
                            "port": "string"
                        },
                        "execution_mode": engine.CONTEXTS[c]["execution"],
                    }
                    for c in engine.CONTEXTS
                },
            }
            self.wfile.write(json.dumps(status, indent=2).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def do_POST(self):
        context = self.path.lstrip("/")
        if context not in engine.CONTEXTS:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": f"Unknown context: {context}"}).encode()
            )
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": f"Invalid JSON: {str(e)}"}).encode()
            )
            return

        for field in ["username", "hostname", "port"]:
            if field not in payload:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": f"Missing field: {field}"}).encode()
                )
                return

        try:
            result = engine.execute_command(
                context,
                str(payload["username"]),
                str(payload["hostname"]),
                str(payload["port"]),
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "status": "executed",
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            self.wfile.write(json.dumps(response).encode())
        except ValueError as e:
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"status": "blocked", "reason": str(e)}).encode()
            )
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        pass  # Suppress request logging


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9443
    server = HTTPServer(("0.0.0.0", port), ProxyHandler)
    print(f"Proxy config engine listening on port {port}")
    sys.stdout.flush()
    server.serve_forever()
