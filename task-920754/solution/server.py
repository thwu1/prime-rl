#!/usr/bin/env python3
"""
ESV Protocol Server with mTLS, TOTP authentication, and JWT sessions.

Implements NIST Entropy Source Validation protocol endpoints with
mutual TLS enforcement and SP 800-90B payload validation.
"""

import http.server
import ssl
import json
import hashlib
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validator import (
    ExpressionEvaluator, ScriptExecutor, TreeWalker,
    ValidationResult, PropertyWrapper
)

import jwt
import pyotp

PKI_DIR = "/app/pki"
CONFIG_DIR = "/app/config"
VALIDATION_TREES_DIR = os.path.join(CONFIG_DIR, "validation_trees")
RULE_SCRIPTS_DIR = os.path.join(CONFIG_DIR, "rule_scripts")

# Load TOTP seed
with open(os.path.join(CONFIG_DIR, "totp_seed.txt")) as f:
    TOTP_SEED = f.read().strip()

# JWT secret: SHA-256 of CA key file contents
with open(os.path.join(PKI_DIR, "ca.key")) as f:
    JWT_SECRET = hashlib.sha256(f.read().encode()).hexdigest()

# Initialize validation engine
evaluator = ExpressionEvaluator()
executor = ScriptExecutor(RULE_SCRIPTS_DIR, evaluator)
walker = TreeWalker(executor)


def load_tree(name):
    path = os.path.join(VALIDATION_TREES_DIR, f"{name}.json")
    with open(path) as f:
        return json.load(f)


def validate_esv_payload(payload, tree_name="registerEntropySource"):
    tree = load_tree(tree_name)
    result = ValidationResult()
    walker.validate(tree, payload, result)
    return result.to_dict()


class ESVHandler(http.server.BaseHTTPRequestHandler):

    def get_client_cn(self):
        """Extract CommonName from the peer (client) certificate."""
        try:
            cert = self.connection.getpeercert()
            if cert:
                for rdn in cert.get("subject", ()):
                    for attr_type, value in rdn:
                        if attr_type == "commonName":
                            return value
        except Exception:
            pass
        return None

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/esv/v1/login":
            self._handle_login()
        elif self.path == "/esv/v1/entropyAssessments":
            self._handle_register()
        else:
            self.send_json({"error": "Not found"}, 404)

    def _handle_login(self):
        try:
            data = self.read_body()
        except Exception:
            self.send_json({"error": "Invalid JSON"}, 400)
            return

        if not isinstance(data, list) or len(data) < 2:
            self.send_json({"error": "Invalid request format"}, 400)
            return

        password = str(data[1].get("password", ""))
        totp = pyotp.TOTP(TOTP_SEED, digits=8)

        if not totp.verify(password, valid_window=1):
            self.send_json(
                [{"esvVersion": "1.0"}, {"error": "TOTP verification failed"}],
                403
            )
            return

        cn = self.get_client_cn() or "unknown"
        now = datetime.datetime.utcnow()
        token = jwt.encode(
            {
                "sub": cn,
                "exp": now + datetime.timedelta(minutes=30),
                "iat": now,
            },
            JWT_SECRET,
            algorithm="HS256",
        )

        self.send_json([{"esvVersion": "1.0"}, {"accessToken": token}])

    def _handle_register(self):
        # Check JWT authorization
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self.send_json({"error": "Missing or invalid authorization"}, 401)
            return

        token = auth_header[7:]
        try:
            jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except jwt.InvalidTokenError as e:
            self.send_json({"error": f"Invalid token: {e}"}, 401)
            return

        # Parse request body
        try:
            data = self.read_body()
        except Exception:
            self.send_json({"error": "Invalid JSON"}, 400)
            return

        if not isinstance(data, list) or len(data) < 2:
            self.send_json({"error": "Invalid request format"}, 400)
            return

        payload = data[1]
        result = validate_esv_payload(payload)

        if result["valid"]:
            self.send_json(
                [
                    {"esvVersion": "1.0"},
                    [
                        {
                            "url": "/esv/v1/entropyAssessments/1",
                            "createdOn": datetime.datetime.utcnow().isoformat(),
                            "publishable": False,
                            "accessToken": token,
                        }
                    ],
                ],
                200,
            )
        else:
            self.send_json(result, 400)

    def log_message(self, format, *args):
        # Suppress default request logging
        pass


def run_server(port=8443):
    server = http.server.HTTPServer(("0.0.0.0", port), ESVHandler)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(
        os.path.join(PKI_DIR, "server.pem"),
        os.path.join(PKI_DIR, "server.key"),
    )
    ctx.load_verify_locations(os.path.join(PKI_DIR, "ca.pem"))
    ctx.verify_mode = ssl.CERT_REQUIRED

    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    print(f"ESV server listening on port {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run_server()
