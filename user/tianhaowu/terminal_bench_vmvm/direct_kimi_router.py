#!/usr/bin/env python3
"""Transparent, sticky, zero-retry router for the sealed Kimi deployment."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import signal
import stat
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

IMPLEMENTATION = "direct-kimi-transparent-v1"
EXPECTED_WORKERS = 24
POLICY = "consistent_hash"
SESSION_HEADER = "x-session-id"
REQUEST_TIMEOUT_SECONDS = 43_200
RETRIES = 0
MAX_CONCURRENT_REQUESTS = 24
MAX_REQUEST_BYTES = 64 * 1024 * 1024
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class RouterError(ValueError):
    """The transparent router contract is invalid."""


def worker_index(session_id: str, worker_count: int = EXPECTED_WORKERS) -> int:
    if not isinstance(session_id, str) or not session_id or len(session_id.encode()) > 4_096:
        raise RouterError("session_id_invalid")
    if type(worker_count) is not int or worker_count < 1:
        raise RouterError("worker_count_invalid")
    return int.from_bytes(hashlib.sha256(session_id.encode()).digest(), "big") % worker_count


def _canonical_worker_url(value: str) -> tuple[str, int]:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise RouterError("worker_url_invalid") from error
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65_535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise RouterError("worker_url_invalid")
    return parsed.hostname, port


def load_worker_urls(path: Path) -> tuple[tuple[str, int], ...]:
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
        raw = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RouterError("worker_urls_unreadable") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or bool(stat.S_IMODE(metadata.st_mode) & 0o077)
        or len(raw.encode()) > 64 * 1024
    ):
        raise RouterError("worker_urls_unreadable")
    lines = raw.splitlines()
    workers = tuple(_canonical_worker_url(line) for line in lines)
    if len(workers) != EXPECTED_WORKERS or len(set(workers)) != EXPECTED_WORKERS:
        raise RouterError("worker_urls_invalid")
    return workers


class RouterState:
    def __init__(self, workers: tuple[tuple[str, int], ...]) -> None:
        if len(workers) != EXPECTED_WORKERS:
            raise RouterError("worker_count_invalid")
        self.workers = workers
        self.capacity = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.total = 0
        self.chat = 0
        self.missing_session = 0
        self.upstream_failures = 0
        self.worker_requests = [0] * len(workers)

    def acquire(self, *, chat: bool, index: int | None) -> bool:
        if not self.capacity.acquire(blocking=False):
            return False
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.total += 1
            if chat:
                self.chat += 1
            if index is not None:
                self.worker_requests[index] += 1
        return True

    def release(self) -> None:
        with self.lock:
            self.active -= 1
        self.capacity.release()

    def record_missing_session(self) -> None:
        with self.lock:
            self.missing_session += 1

    def record_upstream_failure(self) -> None:
        with self.lock:
            self.upstream_failures += 1

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "schema_version": 1,
                "kind": "direct-kimi-transparent-router",
                "implementation": IMPLEMENTATION,
                "policy": POLICY,
                "request_id_headers": [SESSION_HEADER],
                "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
                "retries": RETRIES,
                "worker_count": len(self.workers),
                "active_workers": len(self.workers),
                "active_requests": self.active,
                "max_active_requests": self.max_active,
                "total_requests": self.total,
                "chat_requests": self.chat,
                "missing_session_rejections": self.missing_session,
                "upstream_failures": self.upstream_failures,
                "worker_request_counts": list(self.worker_requests),
            }


def _json_error(handler: BaseHTTPRequestHandler, status: int, code: str) -> None:
    raw = json.dumps({"error": {"code": code}}, sort_keys=True, separators=(",", ":")).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(raw)
    handler.close_connection = True


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "direct-kimi-router"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        return

    @property
    def state(self) -> RouterState:
        return self.server.router_state  # type: ignore[attr-defined,no-any-return]

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            raw = b'{"status":"ok"}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == "/stats":
            raw = (json.dumps(self.state.snapshot(), sort_keys=True, separators=(",", ":")) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == "/v1/models":
            self._forward(chat=False, worker=0, body=None)
            return
        _json_error(self, 404, "route_not_found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            _json_error(self, 404, "route_not_found")
            return
        session_id = self.headers.get(SESSION_HEADER)
        if session_id is None:
            self.state.record_missing_session()
            _json_error(self, 400, "session_id_required")
            return
        try:
            index = worker_index(session_id, len(self.state.workers))
            if self.headers.get("Transfer-Encoding") is not None:
                raise RouterError("request_framing_invalid")
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= MAX_REQUEST_BYTES:
                raise RouterError("request_size_invalid")
            body = self.rfile.read(length)
            if len(body) != length:
                raise RouterError("request_body_truncated")
        except (RouterError, ValueError):
            _json_error(self, 400, "request_invalid")
            return
        self._forward(chat=True, worker=index, body=body)

    def _forward(self, *, chat: bool, worker: int, body: bytes | None) -> None:
        if not self.state.acquire(chat=chat, index=worker):
            _json_error(self, 429, "router_capacity_exhausted")
            return
        connection: http.client.HTTPConnection | None = None
        headers_sent = False
        try:
            host, port = self.state.workers[worker]
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in _HOP_BY_HOP and key.lower() not in {"host", "content-length"}
            }
            if body is not None:
                headers["Content-Length"] = str(len(body))
            connection = http.client.HTTPConnection(host, port, timeout=REQUEST_TIMEOUT_SECONDS)
            connection.request("POST" if body is not None else "GET", self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status, response.reason)
            has_length = False
            for key, value in response.getheaders():
                lowered = key.lower()
                if lowered in _HOP_BY_HOP:
                    continue
                if lowered == "content-length":
                    has_length = True
                self.send_header(key, value)
            if not has_length:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            headers_sent = True
            while chunk := response.read1(64 * 1024):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, http.client.HTTPException):
            self.state.record_upstream_failure()
            if not headers_sent and not self.wfile.closed:
                try:
                    _json_error(self, 502, "upstream_failed")
                except OSError:
                    pass
            else:
                self.close_connection = True
        finally:
            if connection is not None:
                connection.close()
            self.state.release()


class MetricsHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/metrics":
            _json_error(self, 404, "route_not_found")
            return
        state: RouterState = self.server.router_state  # type: ignore[attr-defined]
        snapshot = state.snapshot()
        raw = (
            f"vllm_router_active_workers {snapshot['active_workers']}\n"
            f"direct_kimi_router_active_requests {snapshot['active_requests']}\n"
            f"direct_kimi_router_total_requests {snapshot['total_requests']}\n"
            f"direct_kimi_router_upstream_failures {snapshot['upstream_failures']}\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class RouterServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], state: RouterState) -> None:
        super().__init__(address, handler)
        self.router_state = state


def serve(workers: tuple[tuple[str, int], ...], host: str, port: int, metrics_port: int) -> None:
    if host != "127.0.0.1" or not all(1 <= value <= 65_535 for value in (port, metrics_port)) or port == metrics_port:
        raise RouterError("listen_address_invalid")
    state = RouterState(workers)
    api = RouterServer((host, port), ApiHandler, state)
    metrics = RouterServer((host, metrics_port), MetricsHandler, state)
    metrics_thread = threading.Thread(target=metrics.serve_forever, name="metrics", daemon=True)
    metrics_thread.start()

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=api.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        api.serve_forever()
    finally:
        metrics.shutdown()
        api.server_close()
        metrics.server_close()
        metrics_thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-urls-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--metrics-port", type=int, required=True)
    args = parser.parse_args()
    serve(load_worker_urls(args.worker_urls_file), args.host, args.port, args.metrics_port)


if __name__ == "__main__":
    main()
