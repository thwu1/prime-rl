from __future__ import annotations

import asyncio
import http.client
import threading
from pathlib import Path

from smoke_qwen_router_affinity import (
    _concurrency_probe,
    _ConcurrencyTracker,
    _handler,
    _TrackingServer,
)


def test_real_eval_client_pool_holds_64_requests_at_32() -> None:
    tracker = _ConcurrencyTracker()
    server = _TrackingServer(("127.0.0.1", 0), _handler(0, tracker))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = Path(__file__).parents[1] / "configs" / "eval" / "mobius_qwen_a95b_2500.toml"
    try:
        asyncio.run(
            _concurrency_probe(
                f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                config,
                tracker,
                32,
                64,
            )
        )
    finally:
        tracker.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    active, peak, started = tracker.snapshot()
    assert active == 0
    assert peak == 32
    assert started == 64


def test_stub_health_response_has_http11_message_boundary() -> None:
    tracker = _ConcurrencyTracker()
    server = _TrackingServer(("127.0.0.1", 0), _handler(0, tracker))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Length") == "2"
        assert response.read() == b"ok"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
