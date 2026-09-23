from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from direct_kimi_router import (
    C64_CAPACITY_PROFILE,
    ApiHandler,
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


def _server(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _session_for(index: int) -> str:
    for candidate in range(10_000):
        value = f"opaque-{candidate}"
        if worker_index(value) == index:
            return value
    raise AssertionError("session not found")


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
