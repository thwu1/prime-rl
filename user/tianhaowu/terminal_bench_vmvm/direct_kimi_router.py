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

IMPLEMENTATION = "direct-kimi-transparent-v2"
EXPECTED_WORKERS = 24
C23_EXPECTED_WORKERS = 23
POLICY = "consistent_hash"
SESSION_HEADER = "x-session-id"
REQUEST_TIMEOUT_SECONDS = 43_200
EXTENDED_REQUEST_TIMEOUT_SECONDS = 144_000
ALLOWED_REQUEST_TIMEOUT_SECONDS = frozenset({REQUEST_TIMEOUT_SECONDS, EXTENDED_REQUEST_TIMEOUT_SECONDS})
WORKER_QUEUE_TIMEOUT_SECONDS = REQUEST_TIMEOUT_SECONDS
RETRIES = 0
LEGACY_CAPACITY_PROFILE = "legacy-c24"
C23_CAPACITY_PROFILE = "sandoq-c23-v1"
C64_CAPACITY_PROFILE = "sandoq-c64-v1"
C64_W2_CAPACITY_PROFILE = "sandoq-c64-w2-v1"
CAPACITY_PROFILES = {
    LEGACY_CAPACITY_PROFILE: 24,
    C23_CAPACITY_PROFILE: 23,
    C64_CAPACITY_PROFILE: 64,
    C64_W2_CAPACITY_PROFILE: 64,
}
PER_WORKER_CAPACITY_PROFILES = {
    LEGACY_CAPACITY_PROFILE: 1,
    C23_CAPACITY_PROFILE: 1,
    C64_CAPACITY_PROFILE: 1,
    C64_W2_CAPACITY_PROFILE: 2,
}
WORKER_COUNT_PROFILES = {
    LEGACY_CAPACITY_PROFILE: EXPECTED_WORKERS,
    C23_CAPACITY_PROFILE: C23_EXPECTED_WORKERS,
    C64_CAPACITY_PROFILE: EXPECTED_WORKERS,
    C64_W2_CAPACITY_PROFILE: EXPECTED_WORKERS,
}
DEFAULT_CAPACITY_PROFILE = LEGACY_CAPACITY_PROFILE
MAX_CONCURRENT_REQUESTS = CAPACITY_PROFILES[DEFAULT_CAPACITY_PROFILE]
MAX_TRACKED_SESSIONS = 65_536
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


def validate_request_timeout_seconds(value: int) -> int:
    if type(value) is not int or value not in ALLOWED_REQUEST_TIMEOUT_SECONDS:
        raise RouterError("request_timeout_invalid")
    return value


def capacity_for_profile(value: str) -> int:
    try:
        return CAPACITY_PROFILES[value]
    except (KeyError, TypeError) as error:
        raise RouterError("capacity_profile_invalid") from error


def per_worker_capacity_for_profile(value: str) -> int:
    try:
        return PER_WORKER_CAPACITY_PROFILES[value]
    except (KeyError, TypeError) as error:
        raise RouterError("capacity_profile_invalid") from error


def worker_count_for_profile(value: str) -> int:
    try:
        return WORKER_COUNT_PROFILES[value]
    except (KeyError, TypeError) as error:
        raise RouterError("capacity_profile_invalid") from error


def validate_endpoint_identifier(value: str | None, *, capacity_profile: str) -> str | None:
    if capacity_profile == LEGACY_CAPACITY_PROFILE:
        if value is not None:
            raise RouterError("endpoint_identifier_unexpected")
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode()) > 128
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for character in value
        )
    ):
        raise RouterError("endpoint_identifier_invalid")
    return value


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


def load_worker_urls(
    path: Path,
    *,
    capacity_profile: str = DEFAULT_CAPACITY_PROFILE,
) -> tuple[tuple[str, int], ...]:
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
    expected_workers = worker_count_for_profile(capacity_profile)
    if len(workers) != expected_workers or len(set(workers)) != expected_workers:
        raise RouterError("worker_urls_invalid")
    return workers


class RouterState:
    def __init__(
        self,
        workers: tuple[tuple[str, int], ...],
        *,
        capacity_profile: str = DEFAULT_CAPACITY_PROFILE,
        endpoint_identifier: str | None = None,
        request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
        worker_queue_timeout_seconds: float | None = None,
    ) -> None:
        if len(workers) != worker_count_for_profile(capacity_profile):
            raise RouterError("worker_count_invalid")
        capacity = capacity_for_profile(capacity_profile)
        self.workers = workers
        self.capacity_profile = capacity_profile
        self.endpoint_identifier = validate_endpoint_identifier(
            endpoint_identifier,
            capacity_profile=capacity_profile,
        )
        self.request_timeout_seconds = validate_request_timeout_seconds(request_timeout_seconds)
        self.max_concurrent_requests = capacity
        self.capacity = threading.BoundedSemaphore(capacity)
        per_worker_capacity = per_worker_capacity_for_profile(capacity_profile)
        self.per_worker_capacity = per_worker_capacity
        if worker_queue_timeout_seconds is None:
            worker_queue_timeout_seconds = self.request_timeout_seconds
        if worker_queue_timeout_seconds <= 0:
            raise RouterError("worker_queue_timeout_invalid")
        self.worker_queue_timeout_seconds = worker_queue_timeout_seconds
        # Bound each deployment worker independently.  Session affinity can
        # map several concurrent trajectories to the same worker, so excess
        # requests wait locally instead of being forwarded as an unbounded
        # burst.  The mapping remains deterministic and sticky across turns.
        self.worker_capacity = tuple(threading.BoundedSemaphore(per_worker_capacity) for _ in workers)
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.active_chat = 0
        self.max_active_chat = 0
        self.total = 0
        self.chat = 0
        self.missing_session = 0
        self.upstream_failures = 0
        self.upstream_http_429 = 0
        self.upstream_http_5xx = 0
        self.worker_queue_timeouts = 0
        self.capacity_rejections = 0
        self.route_tracking_overflows = 0
        self.cross_route_anomalies = 0
        self.session_routes: dict[bytes, int] = {}
        self.worker_session_counts = [0] * len(workers)
        self.worker_requests = [0] * len(workers)
        self.worker_active_requests = [0] * len(workers)
        self.worker_max_active_requests = [0] * len(workers)
        self.active_forwarded_requests = 0
        self.max_active_forwarded_requests = 0

    def worker_for_session(self, session_id: str) -> int:
        """Return a sticky, bounded-load worker assignment for a session."""
        preferred = worker_index(session_id, len(self.workers))
        session_digest = hashlib.sha256(session_id.encode()).digest()
        with self.lock:
            previous = self.session_routes.get(session_digest)
            if previous is not None:
                return previous
            if len(self.session_routes) >= MAX_TRACKED_SESSIONS:
                self.route_tracking_overflows += 1
                raise RouterError("route_tracking_capacity_exhausted")

            # Preserve consistent-hash ordering while assigning new sessions
            # to the least-loaded worker.  Once selected, every later turn is
            # pinned by session_routes, so prefix-cache locality is retained.
            minimum = min(self.worker_session_counts)
            for offset in range(len(self.workers)):
                index = (preferred + offset) % len(self.workers)
                if self.worker_session_counts[index] == minimum:
                    break
            else:  # pragma: no cover - min() guarantees a candidate
                raise AssertionError("least-loaded worker missing")
            self.session_routes[session_digest] = index
            self.worker_session_counts[index] += 1
            return index

    def acquire_worker(self, index: int) -> bool:
        if not 0 <= index < len(self.worker_capacity):
            raise RouterError("worker_index_invalid")
        acquired = self.worker_capacity[index].acquire(timeout=self.worker_queue_timeout_seconds)
        if acquired:
            with self.lock:
                self.active_forwarded_requests += 1
                self.max_active_forwarded_requests = max(
                    self.max_active_forwarded_requests,
                    self.active_forwarded_requests,
                )
                self.worker_active_requests[index] += 1
                self.worker_max_active_requests[index] = max(
                    self.worker_max_active_requests[index],
                    self.worker_active_requests[index],
                )
        return acquired

    def release_worker(self, index: int) -> None:
        if not 0 <= index < len(self.worker_capacity):
            raise RouterError("worker_index_invalid")
        with self.lock:
            if self.worker_active_requests[index] < 1:
                raise RouterError("worker_capacity_release_invalid")
            if self.active_forwarded_requests < 1:  # pragma: no cover - guarded by the per-worker count
                raise RouterError("worker_capacity_release_invalid")
            self.active_forwarded_requests -= 1
            self.worker_active_requests[index] -= 1
        self.worker_capacity[index].release()

    def acquire(self, *, chat: bool, index: int | None, session_id: str | None = None) -> bool:
        if not self.capacity.acquire(blocking=False):
            with self.lock:
                self.capacity_rejections += 1
            return False
        with self.lock:
            if self.capacity_profile in (C23_CAPACITY_PROFILE, C64_CAPACITY_PROFILE, C64_W2_CAPACITY_PROFILE) and chat:
                if session_id is None or index is None:
                    self.capacity.release()
                    raise RouterError("route_tracking_invalid")
                session_digest = hashlib.sha256(session_id.encode()).digest()
                previous = self.session_routes.get(session_digest)
                if previous is None:
                    if len(self.session_routes) >= MAX_TRACKED_SESSIONS:
                        self.route_tracking_overflows += 1
                        self.capacity.release()
                        raise RouterError("route_tracking_capacity_exhausted")
                    self.session_routes[session_digest] = index
                    self.worker_session_counts[index] += 1
                elif previous != index:
                    self.cross_route_anomalies += 1
                    self.capacity.release()
                    raise RouterError("cross_route_anomaly")
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.total += 1
            if chat:
                self.chat += 1
                self.active_chat += 1
                self.max_active_chat = max(self.max_active_chat, self.active_chat)
            if index is not None:
                self.worker_requests[index] += 1
        return True

    def release(self, *, chat: bool) -> None:
        with self.lock:
            self.active -= 1
            if chat:
                self.active_chat -= 1
        self.capacity.release()

    def record_missing_session(self) -> None:
        with self.lock:
            self.missing_session += 1

    def record_upstream_failure(self) -> None:
        with self.lock:
            self.upstream_failures += 1

    def record_upstream_status(self, status: int) -> None:
        with self.lock:
            if status == 429:
                self.upstream_http_429 += 1
            elif 500 <= status <= 599:
                self.upstream_http_5xx += 1

    def record_worker_queue_timeout(self) -> None:
        with self.lock:
            self.worker_queue_timeouts += 1

    def operational_metrics(self) -> dict[str, Any]:
        """Return profile-independent counters for the Prometheus endpoint."""
        with self.lock:
            return {
                "configured_per_worker_capacity": self.per_worker_capacity,
                "active_forwarded_requests": self.active_forwarded_requests,
                "max_active_forwarded_requests": self.max_active_forwarded_requests,
                "worker_max_active_request_counts": list(self.worker_max_active_requests),
                "worker_queue_timeouts": self.worker_queue_timeouts,
                "capacity_rejections": self.capacity_rejections,
                "cross_route_anomalies": self.cross_route_anomalies,
                "upstream_http_429": self.upstream_http_429,
                "upstream_http_5xx": self.upstream_http_5xx,
            }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            snapshot = {
                "schema_version": 1,
                "kind": "direct-kimi-transparent-router",
                "implementation": IMPLEMENTATION,
                "policy": POLICY,
                "request_id_headers": [SESSION_HEADER],
                "request_timeout_seconds": self.request_timeout_seconds,
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
            if self.capacity_profile in (C23_CAPACITY_PROFILE, C64_CAPACITY_PROFILE):
                snapshot.update(
                    {
                        "schema_version": 2,
                        "capacity_profile": self.capacity_profile,
                        "endpoint_identifier": self.endpoint_identifier,
                        "configured_capacity": self.max_concurrent_requests,
                        "active_chat_requests": self.active_chat,
                        "max_active_chat_requests": self.max_active_chat,
                        "capacity_rejections": self.capacity_rejections,
                        "queue_overflow_rejections": self.capacity_rejections,
                        "route_tracking_overflows": self.route_tracking_overflows,
                        "cross_route_anomalies": self.cross_route_anomalies,
                        "tracked_sessions": len(self.session_routes),
                    }
                )
            elif self.capacity_profile == C64_W2_CAPACITY_PROFILE:
                snapshot.update(
                    {
                        "schema_version": 3,
                        "capacity_profile": self.capacity_profile,
                        "endpoint_identifier": self.endpoint_identifier,
                        "configured_capacity": self.max_concurrent_requests,
                        "configured_per_worker_capacity": self.per_worker_capacity,
                        "active_forwarded_requests": self.active_forwarded_requests,
                        "max_active_forwarded_requests": self.max_active_forwarded_requests,
                        "active_chat_requests": self.active_chat,
                        "max_active_chat_requests": self.max_active_chat,
                        "capacity_rejections": self.capacity_rejections,
                        "queue_overflow_rejections": self.capacity_rejections,
                        "route_tracking_overflows": self.route_tracking_overflows,
                        "cross_route_anomalies": self.cross_route_anomalies,
                        "tracked_sessions": len(self.session_routes),
                        "worker_active_request_counts": list(self.worker_active_requests),
                        "worker_max_active_request_counts": list(self.worker_max_active_requests),
                        "worker_queue_timeouts": self.worker_queue_timeouts,
                        "upstream_http_429": self.upstream_http_429,
                        "upstream_http_5xx": self.upstream_http_5xx,
                    }
                )
            return snapshot


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
            # Validate the affinity key before accepting a potentially large
            # request body.  Placement occurs only after the body is valid.
            worker_index(session_id, len(self.state.workers))
            if self.headers.get("Transfer-Encoding") is not None:
                raise RouterError("request_framing_invalid")
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= MAX_REQUEST_BYTES:
                raise RouterError("request_size_invalid")
            body = self.rfile.read(length)
            if len(body) != length:
                raise RouterError("request_body_truncated")
            index = self.state.worker_for_session(session_id)
        except (RouterError, ValueError):
            _json_error(self, 400, "request_invalid")
            return
        self._forward(chat=True, worker=index, body=body, session_id=session_id)

    def _forward(
        self,
        *,
        chat: bool,
        worker: int,
        body: bytes | None,
        session_id: str | None = None,
    ) -> None:
        admitted = False
        try:
            admitted = self.state.acquire(chat=chat, index=worker, session_id=session_id)
        except RouterError:
            _json_error(self, 503, "router_route_tracking_failed")
            return
        if not admitted:
            _json_error(self, 429, "router_capacity_exhausted")
            return
        connection: http.client.HTTPConnection | None = None
        worker_acquired = False
        headers_sent = False
        try:
            worker_acquired = self.state.acquire_worker(worker)
            if not worker_acquired:
                self.state.record_worker_queue_timeout()
                _json_error(self, 429, "worker_queue_timeout")
                return
            host, port = self.state.workers[worker]
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in _HOP_BY_HOP and key.lower() not in {"host", "content-length"}
            }
            if body is not None:
                headers["Content-Length"] = str(len(body))
            connection = http.client.HTTPConnection(
                host,
                port,
                timeout=self.state.request_timeout_seconds,
            )
            connection.request("POST" if body is not None else "GET", self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.state.record_upstream_status(response.status)
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
            if admitted:
                self.state.release(chat=chat)
            if worker_acquired:
                self.state.release_worker(worker)


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
        operational = state.operational_metrics()
        raw = (
            f"vllm_router_active_workers {snapshot['active_workers']}\n"
            f"direct_kimi_router_active_requests {snapshot['active_requests']}\n"
            f"direct_kimi_router_max_active_requests {snapshot['max_active_requests']}\n"
            f"direct_kimi_router_total_requests {snapshot['total_requests']}\n"
            f"direct_kimi_router_upstream_failures {snapshot['upstream_failures']}\n"
            f"direct_kimi_router_capacity_rejections {operational['capacity_rejections']}\n"
            f"direct_kimi_router_cross_route_anomalies {operational['cross_route_anomalies']}\n"
            f"direct_kimi_router_configured_per_worker_capacity "
            f"{operational['configured_per_worker_capacity']}\n"
            f"direct_kimi_router_active_forwarded_requests {operational['active_forwarded_requests']}\n"
            f"direct_kimi_router_max_active_forwarded_requests "
            f"{operational['max_active_forwarded_requests']}\n"
            f"direct_kimi_router_max_active_requests_on_worker "
            f"{max(operational['worker_max_active_request_counts'])}\n"
            f"direct_kimi_router_worker_queue_timeouts {operational['worker_queue_timeouts']}\n"
            f"direct_kimi_router_upstream_http_429 {operational['upstream_http_429']}\n"
            f"direct_kimi_router_upstream_http_5xx {operational['upstream_http_5xx']}\n"
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
        self.request_queue_size = state.max_concurrent_requests
        super().__init__(address, handler)
        self.router_state = state


def serve(
    workers: tuple[tuple[str, int], ...],
    host: str,
    port: int,
    metrics_port: int,
    *,
    capacity_profile: str = DEFAULT_CAPACITY_PROFILE,
    endpoint_identifier: str | None = None,
    request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
) -> None:
    if host != "127.0.0.1" or not all(1 <= value <= 65_535 for value in (port, metrics_port)) or port == metrics_port:
        raise RouterError("listen_address_invalid")
    state = RouterState(
        workers,
        capacity_profile=capacity_profile,
        endpoint_identifier=endpoint_identifier,
        request_timeout_seconds=request_timeout_seconds,
    )
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
    parser.add_argument(
        "--capacity-profile",
        choices=tuple(CAPACITY_PROFILES),
        default=DEFAULT_CAPACITY_PROFILE,
    )
    parser.add_argument("--endpoint-identifier")
    parser.add_argument(
        "--request-timeout-seconds",
        type=int,
        choices=tuple(sorted(ALLOWED_REQUEST_TIMEOUT_SECONDS)),
        default=REQUEST_TIMEOUT_SECONDS,
    )
    args = parser.parse_args()
    serve(
        load_worker_urls(args.worker_urls_file, capacity_profile=args.capacity_profile),
        args.host,
        args.port,
        args.metrics_port,
        capacity_profile=args.capacity_profile,
        endpoint_identifier=args.endpoint_identifier,
        request_timeout_seconds=args.request_timeout_seconds,
    )


if __name__ == "__main__":
    main()
