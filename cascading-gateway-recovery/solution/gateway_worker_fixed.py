#!/usr/bin/env python3
"""API Gateway Worker - FIXED version with null-rules handling, backoff, and hotfix removal."""

import http.server
import json
import sqlite3
import sys
import os
import time
import logging
import threading
import random

DB_PATH = "/app/data/config.db"
WORKER_ID = int(os.environ.get("WORKER_ID", 1))
PORT = 8080 + WORKER_ID
LOG_FILE = f"/app/logs/worker_{WORKER_ID}.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format=f'%(asctime)s worker-{WORKER_ID} %(levelname)s %(message)s'
)
logger = logging.getLogger(f"worker-{WORKER_ID}")


class DatabasePool:
    """Simple SQLite connection manager with reconnection."""

    def __init__(self, db_path, max_retries=50):
        self.db_path = db_path
        self.max_retries = max_retries
        self._conn = None
        self._lock = threading.Lock()

    def get_connection(self):
        with self._lock:
            if self._conn is None:
                self._connect()
            try:
                self._conn.execute("SELECT 1")
            except (sqlite3.OperationalError, sqlite3.ProgrammingError):
                self._connect()
            return self._conn

    def _connect(self):
        """Connect to the database with exponential backoff and jitter."""
        retries = 0
        while retries < self.max_retries:
            try:
                self._conn = sqlite3.connect(self.db_path, timeout=1)
                self._conn.row_factory = sqlite3.Row
                logger.info("Connected to database")
                return
            except sqlite3.OperationalError as e:
                retries += 1
                logger.warning(f"DB connection attempt {retries}/{self.max_retries} failed: {e}")
                delay = min(0.1 * (2 ** retries) + random.uniform(0, 0.1), 5.0)
                logger.info(f"Backing off for {delay:.2f}s before retry")
                time.sleep(delay)
        raise RuntimeError(f"Failed to connect to database after {self.max_retries} retries")

    def reconnect(self):
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None
            self._connect()


db_pool = DatabasePool(DB_PATH)


def _warm_policy_cache():
    """Pre-load and validate quota policies on startup."""
    logger.info("Loading quota policies for cache warmup...")
    conn = db_pool.get_connection()
    cursor = conn.execute(
        "SELECT policy_id, name, rules, enforce_mode FROM quota_policies WHERE active = 1"
    )
    policies = cursor.fetchall()

    for policy in policies:
        logger.info(f"Loaded policy: {policy['name']} ({policy['enforce_mode']})")
        policy_rules = json.loads(policy['rules'])
        if not isinstance(policy_rules, list):
            logger.warning(
                f"Policy '{policy['name']}' has invalid rules type "
                f"({type(policy_rules).__name__}), skipping validation"
            )
            continue
        for rule in policy_rules:
            logger.info(f"  Rule: {rule.get('path_pattern', '*')}")

    logger.info(f"Successfully loaded {len(policies)} policies")


class GatewayHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the API gateway."""

    def log_message(self, format, *args):
        logger.info(format % args)

    def do_GET(self):
        if self.path == "/health":
            self._handle_health()
        elif self.path.startswith("/api/"):
            self._handle_api_request()
        else:
            self.send_error(404)

    def _handle_health(self):
        """Health check endpoint."""
        try:
            conn = db_pool.get_connection()
            conn.execute("SELECT 1")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "status": "healthy",
                "worker_id": WORKER_ID,
                "port": PORT,
                "timestamp": time.time()
            }
            self.wfile.write(json.dumps(response).encode())
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "unhealthy", "error": str(e)}).encode())

    def _handle_api_request(self):
        """Process an API request with quota enforcement."""
        path = self.path

        try:
            conn = db_pool.get_connection()
            cursor = conn.execute(
                "SELECT policy_id, name, rules, enforce_mode FROM quota_policies WHERE active = 1"
            )
            policies = cursor.fetchall()

            applicable_rules = []
            for policy in policies:
                policy_rules = json.loads(policy['rules'])
                if not isinstance(policy_rules, list):
                    logger.warning(
                        f"Skipping policy '{policy['name']}': "
                        f"rules is {type(policy_rules).__name__}, expected list"
                    )
                    continue
                for rule in policy_rules:
                    if self._path_matches(path, rule.get('path_pattern', '*')):
                        applicable_rules.append(rule)

            if applicable_rules:
                quota_result = self._check_quota(applicable_rules)
                if not quota_result['allowed']:
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "error": "quota_exceeded",
                        "retry_after": quota_result.get('retry_after', 60)
                    }).encode())
                    return

            response = self._process_request(path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except sqlite3.OperationalError as e:
            logger.error(f"Database error: {e}")
            db_pool.reconnect()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "service_unavailable"}).encode())

        except Exception as e:
            logger.error(f"Unhandled error: {type(e).__name__}: {e}")
            raise

    def _path_matches(self, request_path, pattern):
        """Check if a request path matches a rule pattern."""
        if pattern == '*':
            return True
        return request_path.startswith(pattern)

    def _check_quota(self, rules):
        """Apply quota rules to the request."""
        return {"allowed": True}

    def _process_request(self, path):
        """Process the API request and return response data."""
        return {
            "status": "ok",
            "path": path,
            "worker_id": WORKER_ID,
            "timestamp": time.time()
        }


def main():
    logger.info(f"Starting worker {WORKER_ID} on port {PORT}")

    try:
        _warm_policy_cache()
    except Exception as e:
        logger.error(f"Fatal error during policy cache warmup: {e}")
        logger.error(f"Worker {WORKER_ID} shutting down due to startup failure")
        sys.exit(1)

    server = http.server.HTTPServer(('0.0.0.0', PORT), GatewayHandler)
    logger.info(f"Server started on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
