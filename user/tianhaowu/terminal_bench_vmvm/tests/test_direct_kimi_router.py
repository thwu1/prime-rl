from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from direct_kimi_router import (
    C64_CAPACITY_PROFILE,
    C64_W2_CAPACITY_PROFILE,
    ApiHandler,
    MetricsHandler,
    RouterError,
    RouterServer,
    RouterState,
    worker_index,
)


class _Backend(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    bodies: list[bytes] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        type(self).bodies.append(self.rfile.read(length))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for chunk in (b"data: one\n\n", b"data: [DONE]\n\n"):
            self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")


class _BlockingBackend(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    entered = threading.Event()
    release = threading.Event()

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        type(self).entered.set()
        assert type(self).release.wait(timeout=5)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _CountingBlockingBackend(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    lock = threading.Lock()
    active = 0
    max_active = 0
    entered_two = threading.Event()
    release = threading.Event()

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        with type(self).lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
            if type(self).active == 2:
                type(self).entered_two.set()
        try:
            assert type(self).release.wait(timeout=5)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        finally:
            with type(self).lock:
                type(self).active -= 1


class _TestServer(ThreadingHTTPServer):
    request_queue_size = 128


def _server(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = _TestServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _session_for(index: int) -> str:
    for candidate in range(10_000):
        value = f"opaque-{candidate}"
        if worker_index(value) == index:
            return value
    raise AssertionError("session not found")


def _metrics(state: RouterState) -> str:
    server = RouterServer(("127.0.0.1", 0), MetricsHandler, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request("GET", "/metrics")
        response = connection.getresponse()
        assert response.status == 200
        raw = response.read().decode()
        connection.close()
        return raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_transparent_router_preserves_max_body_and_streams_without_retry() -> None:
    _Backend.bodies = []
    backend, backend_thread = _server(_Backend)
    workers = tuple(("127.0.0.1", backend.server_address[1] if index == 0 else 30_000 + index) for index in range(24))
    state = RouterState(workers)
    router = RouterServer(("127.0.0.1", 0), ApiHandler, state)
    router_thread = threading.Thread(target=router.serve_forever, daemon=True)
    router_thread.start()
    body = json.dumps(
        {
            "model": "Kimi-K3",
            "reasoning_effort": "max",
            "stream": True,
            "messages": [{"role": "user", "content": "opaque"}],
            "tools": [{"type": "function", "function": {"name": "shell", "parameters": {}}}],
        },
        separators=(",", ":"),
    ).encode()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", router.server_address[1], timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"Content-Type": "application/json", "x-session-id": _session_for(0)},
        )
        response = connection.getresponse()
        assert response.status == 200
        assert response.read() == b"data: one\n\ndata: [DONE]\n\n"
        connection.close()
        assert _Backend.bodies == [body]
        snapshot = state.snapshot()
        assert snapshot["chat_requests"] == snapshot["total_requests"] == 1
        assert snapshot["upstream_failures"] == 0
        assert snapshot["worker_request_counts"] == [1, *([0] * 23)]
    finally:
        router.shutdown()
        backend.shutdown()
        router.server_close()
        backend.server_close()
        router_thread.join(timeout=5)
        backend_thread.join(timeout=5)


def test_transparent_router_requires_sticky_header_and_does_not_retry() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(workers)
    router = RouterServer(("127.0.0.1", 0), ApiHandler, state)
    router_thread = threading.Thread(target=router.serve_forever, daemon=True)
    router_thread.start()
    body = b'{"reasoning_effort":"max"}'
    try:
        connection = http.client.HTTPConnection("127.0.0.1", router.server_address[1], timeout=5)
        connection.request("POST", "/v1/chat/completions", body=body)
        response = connection.getresponse()
        assert response.status == 400
        response.read()
        connection.close()
        assert state.snapshot()["missing_session_rejections"] == 1
        assert state.snapshot()["total_requests"] == 0

        connection = http.client.HTTPConnection("127.0.0.1", router.server_address[1], timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"x-session-id": _session_for(0)},
        )
        response = connection.getresponse()
        assert response.status == 502
        response.read()
        connection.close()
        snapshot = state.snapshot()
        assert snapshot["total_requests"] == 1
        assert snapshot["worker_request_counts"] == [1, *([0] * 23)]
        assert snapshot["upstream_failures"] == 1
    finally:
        router.shutdown()
        router.server_close()
        router_thread.join(timeout=5)


def test_router_accepts_only_sealed_extended_request_timeout() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))

    state = RouterState(workers, request_timeout_seconds=144_000)

    assert state.snapshot()["request_timeout_seconds"] == 144_000
    assert state.worker_queue_timeout_seconds == 144_000
    with pytest.raises(RouterError, match="request_timeout_invalid"):
        RouterState(workers, request_timeout_seconds=144_001)


def test_c64_profile_is_explicit_bounded_and_tracks_sticky_routes() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(
        workers,
        capacity_profile=C64_CAPACITY_PROFILE,
        endpoint_identifier="cpu-132-021_8103",
    )
    sessions = [f"capacity-{index}" for index in range(65)]
    indexes = [worker_index(session) for session in sessions]

    for session, index in zip(sessions[:64], indexes[:64], strict=True):
        assert state.acquire(chat=True, index=index, session_id=session)
    assert not state.acquire(chat=True, index=indexes[64], session_id=sessions[64])
    for _ in range(64):
        state.release(chat=True)

    assert state.acquire(chat=True, index=indexes[0], session_id=sessions[0])
    state.release(chat=True)
    with pytest.raises(RouterError, match="cross_route_anomaly"):
        state.acquire(chat=True, index=(indexes[0] + 1) % 24, session_id=sessions[0])

    snapshot = state.snapshot()
    assert snapshot["schema_version"] == 2
    assert snapshot["configured_capacity"] == 64
    assert snapshot["max_active_chat_requests"] == 64
    assert snapshot["capacity_rejections"] == 1
    assert snapshot["queue_overflow_rejections"] == 1
    assert snapshot["cross_route_anomalies"] == 1
    assert snapshot["route_tracking_overflows"] == 0


def test_legacy_router_profile_retains_c24_snapshot_shape() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(workers)
    for _ in range(24):
        assert state.acquire(chat=False, index=0)
    assert not state.acquire(chat=False, index=0)
    for _ in range(24):
        state.release(chat=False)

    snapshot = state.snapshot()
    assert snapshot["schema_version"] == 1
    assert snapshot["max_active_requests"] == 24
    assert "capacity_profile" not in snapshot
    assert "capacity_rejections" not in snapshot


def test_legacy_router_metrics_report_real_operational_counters() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(workers, worker_queue_timeout_seconds=0.01)
    for _ in range(24):
        assert state.acquire(chat=False, index=0)
    assert not state.acquire(chat=False, index=0)
    for _ in range(24):
        state.release(chat=False)

    assert state.acquire_worker(0)
    assert not state.acquire_worker(0)
    state.record_worker_queue_timeout()
    state.release_worker(0)
    state.record_upstream_status(429)
    state.record_upstream_status(503)

    # Preserve the schema-1 /stats compatibility contract while ensuring the
    # profile-independent Prometheus endpoint does not silently render zeros.
    snapshot = state.snapshot()
    assert snapshot["schema_version"] == 1
    assert "capacity_rejections" not in snapshot
    metrics = _metrics(state)
    assert "direct_kimi_router_capacity_rejections 1\n" in metrics
    assert "direct_kimi_router_worker_queue_timeouts 1\n" in metrics
    assert "direct_kimi_router_max_active_forwarded_requests 1\n" in metrics
    assert "direct_kimi_router_max_active_requests_on_worker 1\n" in metrics
    assert "direct_kimi_router_upstream_http_429 1\n" in metrics
    assert "direct_kimi_router_upstream_http_5xx 1\n" in metrics


def test_same_worker_requests_queue_while_other_workers_remain_available() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(workers, worker_queue_timeout_seconds=1)
    second_acquired = threading.Event()

    assert state.acquire_worker(0)

    def acquire_second() -> None:
        assert state.acquire_worker(0)
        second_acquired.set()
        state.release_worker(0)

    thread = threading.Thread(target=acquire_second)
    thread.start()
    assert not second_acquired.wait(timeout=0.05)

    # Affinity on one busy worker must not stop an unrelated worker.
    assert state.acquire_worker(1)
    state.release_worker(1)
    state.release_worker(0)

    assert second_acquired.wait(timeout=1)
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_c64_w2_profile_admits_two_requests_per_worker_and_reports_high_water() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(
        workers,
        capacity_profile=C64_W2_CAPACITY_PROFILE,
        endpoint_identifier="cpu-132-021_8103",
        worker_queue_timeout_seconds=0.01,
    )

    for worker in range(24):
        assert state.acquire_worker(worker)
        assert state.acquire_worker(worker)
    assert not state.acquire_worker(0)
    snapshot = state.snapshot()
    assert snapshot["schema_version"] == 3
    assert snapshot["capacity_profile"] == C64_W2_CAPACITY_PROFILE
    assert snapshot["configured_per_worker_capacity"] == 2
    assert snapshot["active_forwarded_requests"] == 48
    assert snapshot["max_active_forwarded_requests"] == 48
    assert snapshot["worker_active_request_counts"] == [2] * 24
    assert snapshot["worker_max_active_request_counts"] == [2] * 24
    assert snapshot["worker_queue_timeouts"] == 0
    assert snapshot["upstream_http_429"] == 0
    assert snapshot["upstream_http_5xx"] == 0
    metrics = _metrics(state)
    assert "direct_kimi_router_configured_per_worker_capacity 2\n" in metrics
    assert "direct_kimi_router_active_forwarded_requests 48\n" in metrics
    assert "direct_kimi_router_max_active_forwarded_requests 48\n" in metrics
    assert "direct_kimi_router_max_active_requests_on_worker 2\n" in metrics
    assert "direct_kimi_router_worker_queue_timeouts 0\n" in metrics
    assert "direct_kimi_router_upstream_http_429 0\n" in metrics
    assert "direct_kimi_router_upstream_http_5xx 0\n" in metrics

    for worker in range(24):
        state.release_worker(worker)
        state.release_worker(worker)
    snapshot = state.snapshot()
    assert snapshot["active_forwarded_requests"] == 0
    assert snapshot["max_active_forwarded_requests"] == 48
    assert snapshot["worker_active_request_counts"] == [0] * 24
    assert snapshot["worker_max_active_request_counts"] == [2] * 24


def test_existing_c64_profile_retains_one_request_per_worker_and_v2_schema() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(
        workers,
        capacity_profile=C64_CAPACITY_PROFILE,
        endpoint_identifier="cpu-132-021_8103",
        worker_queue_timeout_seconds=0.01,
    )

    assert state.acquire_worker(0)
    assert not state.acquire_worker(0)
    state.release_worker(0)
    snapshot = state.snapshot()
    assert snapshot["schema_version"] == 2
    assert "configured_per_worker_capacity" not in snapshot
    assert "worker_active_request_counts" not in snapshot
    assert "worker_max_active_request_counts" not in snapshot


def test_c64_w2_http_path_forwards_two_same_worker_requests_and_queues_third() -> None:
    _CountingBlockingBackend.active = 0
    _CountingBlockingBackend.max_active = 0
    _CountingBlockingBackend.entered_two = threading.Event()
    _CountingBlockingBackend.release = threading.Event()
    backend, backend_thread = _server(_CountingBlockingBackend)
    workers = tuple(("127.0.0.1", backend.server_address[1]) for _ in range(24))
    state = RouterState(
        workers,
        capacity_profile=C64_W2_CAPACITY_PROFILE,
        endpoint_identifier="cpu-132-021_8103",
    )
    router = RouterServer(("127.0.0.1", 0), ApiHandler, state)
    router_thread = threading.Thread(target=router.serve_forever, daemon=True)
    router_thread.start()
    statuses: list[int] = []
    session = _session_for(0)

    def request() -> None:
        connection = http.client.HTTPConnection("127.0.0.1", router.server_address[1], timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=b"{}",
            headers={"Content-Length": "2", "x-session-id": session},
        )
        response = connection.getresponse()
        statuses.append(response.status)
        response.read()
        connection.close()

    threads = [threading.Thread(target=request) for _index in range(3)]
    try:
        for thread in threads:
            thread.start()
        assert _CountingBlockingBackend.entered_two.wait(timeout=2)
        deadline = time.monotonic() + 2
        while state.snapshot()["active_requests"] != 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        snapshot = state.snapshot()
        assert snapshot["active_requests"] == 3
        assert snapshot["active_forwarded_requests"] == 2
        assert snapshot["max_active_forwarded_requests"] == 2
        assert _CountingBlockingBackend.max_active == 2
    finally:
        _CountingBlockingBackend.release.set()
        for thread in threads:
            thread.join(timeout=5)
        router.shutdown()
        backend.shutdown()
        router.server_close()
        backend.server_close()
        router_thread.join(timeout=5)
        backend_thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(statuses) == [200, 200, 200]
    assert state.snapshot()["worker_queue_timeouts"] == 0


def test_new_sessions_fill_workers_evenly_and_remain_sticky() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(workers)
    sessions = [f"balanced-{index}" for index in range(64)]
    assignments = [state.worker_for_session(session) for session in sessions]

    assert set(assignments[:24]) == set(range(24))
    counts = [assignments.count(index) for index in range(24)]
    assert max(counts) - min(counts) <= 1
    assert [state.worker_for_session(session) for session in sessions] == assignments


def test_concurrent_session_assignment_is_thread_safe_and_balanced() -> None:
    workers = tuple(("127.0.0.1", 31_000 + index) for index in range(24))
    state = RouterState(workers)
    sessions = [f"concurrent-{index}" for index in range(64)]
    assignments: list[int | None] = [None] * len(sessions)
    barrier = threading.Barrier(len(sessions))

    def assign(index: int) -> None:
        barrier.wait()
        assignments[index] = state.worker_for_session(sessions[index])

    threads = [threading.Thread(target=assign, args=(index,)) for index in range(len(sessions))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert all(assignment is not None for assignment in assignments)
    counts = [assignments.count(index) for index in range(24)]
    assert max(counts) - min(counts) <= 1
    assert [state.worker_for_session(session) for session in sessions] == assignments


def test_c64_admits_requests_before_per_worker_queueing() -> None:
    _BlockingBackend.entered = threading.Event()
    _BlockingBackend.release = threading.Event()
    backend, backend_thread = _server(_BlockingBackend)
    workers = tuple(("127.0.0.1", backend.server_address[1] if index == 0 else 31_000 + index) for index in range(24))
    state = RouterState(
        workers,
        capacity_profile=C64_CAPACITY_PROFILE,
        endpoint_identifier="cpu-132-021_8103",
    )
    router = RouterServer(("127.0.0.1", 0), ApiHandler, state)
    router_thread = threading.Thread(target=router.serve_forever, daemon=True)
    router_thread.start()
    statuses: list[int] = []

    def request() -> None:
        connection = http.client.HTTPConnection("127.0.0.1", router.server_address[1], timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=b"{}",
            headers={"Content-Length": "2", "x-session-id": _session_for(0)},
        )
        response = connection.getresponse()
        statuses.append(response.status)
        response.read()
        connection.close()

    first = threading.Thread(target=request)
    second = threading.Thread(target=request)
    try:
        first.start()
        assert _BlockingBackend.entered.wait(timeout=2)
        second.start()
        deadline = time.monotonic() + 2
        while state.snapshot()["active_requests"] != 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert state.snapshot()["active_requests"] == 2
        assert state.snapshot()["max_active_chat_requests"] == 2
    finally:
        _BlockingBackend.release.set()
        first.join(timeout=5)
        second.join(timeout=5)
        router.shutdown()
        backend.shutdown()
        router.server_close()
        backend.server_close()
        router_thread.join(timeout=5)
        backend_thread.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert statuses == [200, 200]


def test_c64_http_path_reaches_full_admitted_capacity() -> None:
    _BlockingBackend.entered = threading.Event()
    _BlockingBackend.release = threading.Event()
    backend, backend_thread = _server(_BlockingBackend)
    workers = tuple(("127.0.0.1", backend.server_address[1]) for _ in range(24))
    state = RouterState(
        workers,
        capacity_profile=C64_CAPACITY_PROFILE,
        endpoint_identifier="cpu-132-021_8103",
    )
    router = RouterServer(("127.0.0.1", 0), ApiHandler, state)
    router_thread = threading.Thread(target=router.serve_forever, daemon=True)
    router_thread.start()
    statuses: list[int] = []

    def request(index: int) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", router.server_address[1], timeout=10)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=b"{}",
            headers={"Content-Length": "2", "x-session-id": f"capacity-http-{index}"},
        )
        response = connection.getresponse()
        statuses.append(response.status)
        response.read()
        connection.close()

    threads = [threading.Thread(target=request, args=(index,)) for index in range(64)]
    try:
        for thread in threads:
            thread.start()
        assert _BlockingBackend.entered.wait(timeout=2)
        deadline = time.monotonic() + 5
        while state.snapshot()["active_requests"] != 64 and time.monotonic() < deadline:
            time.sleep(0.01)
        snapshot = state.snapshot()
        assert snapshot["active_requests"] == 64
        assert snapshot["max_active_chat_requests"] == 64
        assert snapshot["tracked_sessions"] == 64
        assert max(state.worker_session_counts) - min(state.worker_session_counts) <= 1
    finally:
        _BlockingBackend.release.set()
        for thread in threads:
            thread.join(timeout=10)
        router.shutdown()
        backend.shutdown()
        router.server_close()
        backend.server_close()
        router_thread.join(timeout=5)
        backend_thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert statuses == [200] * 64
