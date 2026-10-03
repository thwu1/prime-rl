from __future__ import annotations

import asyncio
import inspect
import threading
import time
from importlib import metadata
from typing import Any

import pytest
import sandoq_provider.gateway as gateway_module
from sandoq_client import NullSink, SandoqClient
from sandoq_client.client import SHUTDOWN_TIMEOUT
from sandoq_provider.gateway import SandoqGatewayAdapter

EXPECTED_SANDOQ_CLIENT = "1.0.0.2026.9.23.82068.0+hg1a1d394e50c5"


class _Response:
    def __init__(
        self,
        status: int,
        body: dict[str, object],
        *,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self._entered = entered
        self._release = release

    async def __aenter__(self) -> _Response:
        if self._entered is not None:
            self._entered.set()
        if self._release is not None:
            await asyncio.to_thread(self._release.wait)
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def json(self) -> dict[str, object]:
        return dict(self._body)

    async def text(self) -> str:
        return ""


class _Http:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _request(self, method: str, url: str, kwargs: dict[str, Any]) -> _Response:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def post(self, url: str, **kwargs: Any) -> _Response:
        return self._request("POST", url, kwargs)

    def get(self, url: str, **kwargs: Any) -> _Response:
        return self._request("GET", url, kwargs)

    def delete(self, url: str, **kwargs: Any) -> _Response:
        return self._request("DELETE", url, kwargs)

    async def close(self) -> None:
        return None


def _adapter(
    lifecycle: _Http,
    lease: _Http,
) -> tuple[SandoqGatewayAdapter, list[float]]:
    ready_timeouts: list[float] = []

    def factory(base_url: str, owner: str) -> SandoqClient:
        reliable_client = gateway_module._creation_retry_client_type(SandoqClient)

        class RecordingClient(reliable_client):
            async def create_session(self, *args: Any, **kwargs: Any) -> Any:
                ready_timeouts.append(float(kwargs["ready_timeout_seconds"]))
                return await super().create_session(*args, **kwargs)

        client = RecordingClient(base_url, owner=owner, telemetry=NullSink())
        client._http = lifecycle
        client._lease_http = lease
        return client

    return (
        SandoqGatewayAdapter(
            "https://sandoq.example",
            "compatibility-test",
            client_factory=factory,
        ),
        ready_timeouts,
    )


def test_sdk_pin_supports_accepted_firecracker_session_creation() -> None:
    assert metadata.version("sandoq-client") == EXPECTED_SANDOQ_CLIENT
    ready_timeout = inspect.signature(SandoqClient.create_session).parameters.get(
        "ready_timeout_seconds"
    )
    assert ready_timeout is not None
    assert ready_timeout.kind is inspect.Parameter.KEYWORD_ONLY
    assert SHUTDOWN_TIMEOUT.total is not None
    assert gateway_module._OFFICIAL_CLOSE_BUDGET_SECONDS > SHUTDOWN_TIMEOUT.total

    lifecycle = _Http(
        [
            _Response(
                202,
                {
                    "sessionId": "accepted-session",
                    "status": "provisioning",
                    "cluster": "test-cluster",
                },
            )
        ]
    )
    lease = _Http(
        [
            _Response(
                200,
                {
                    "sessionId": "accepted-session",
                    "status": "ready",
                    "portUrls": {"exec": "https://exec.example"},
                    "ports": [{"name": "exec", "port": 8000}],
                },
            )
        ]
    )
    adapter, ready_timeouts = _adapter(lifecycle, lease)
    try:
        session = adapter.create_session(
            "firecracker-environment",
            "30m",
            "stable-request",
            timeout=1,
        )
    finally:
        adapter.close()

    assert session.session_id == "accepted-session"
    assert session.status is not None and session.status.value == "ready"
    assert ready_timeouts == [1.0]
    assert [method for method, _url, _kwargs in lifecycle.calls] == ["POST"]
    assert [method for method, _url, _kwargs in lease.calls] == ["GET"]


def test_adapter_allows_sdk_cleanup_after_accepted_session_times_out() -> None:
    lifecycle = _Http(
        [
            _Response(
                202,
                {
                    "sessionId": "timed-out-session",
                    "status": "provisioning",
                    "cluster": "test-cluster",
                },
            ),
            _Response(204, {}),
        ]
    )
    lease = _Http(
        [
            _Response(
                200,
                {
                    "sessionId": "timed-out-session",
                    "status": "provisioning",
                },
            ),
            _Response(
                200,
                {
                    "sessionId": "timed-out-session",
                    "status": "provisioning",
                },
            ),
        ]
    )
    adapter, ready_timeouts = _adapter(lifecycle, lease)
    try:
        with pytest.raises(TimeoutError):
            asyncio.run(
                adapter.create_session_async(
                    "firecracker-environment",
                    "30m",
                    "stable-timeout-request",
                    timeout=0.01,
                )
            )
    finally:
        adapter.close()

    assert [method for method, _url, _kwargs in lifecycle.calls] == ["POST", "DELETE"]
    assert ready_timeouts == [0.01]
    assert lease.calls
    assert {method for method, _url, _kwargs in lease.calls} == {"GET"}


def test_adapter_keeps_total_deadline_while_create_is_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway_module, "_OFFICIAL_DELETE_BUDGET_SECONDS", 1.0)
    monkeypatch.setattr(gateway_module.random, "uniform", lambda *_args: 60.0)
    lifecycle = _Http([_Response(429, {"message": "pool exhausted"})])
    adapter, ready_timeouts = _adapter(lifecycle, _Http([]))

    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            adapter.create_session(
                "firecracker-environment",
                "30m",
                "stable-retry-request",
                timeout=0.01,
            )
    finally:
        adapter.close()

    assert time.monotonic() - started < 0.5
    assert ready_timeouts == [0.01]
    assert [method for method, _url, _kwargs in lifecycle.calls] == ["POST"]


def test_adapter_defers_external_cancellation_until_accepted_cleanup_finishes() -> None:
    ready_polled = threading.Event()
    delete_started = threading.Event()
    release_delete = threading.Event()
    lifecycle = _Http(
        [
            _Response(
                202,
                {
                    "sessionId": "cancelled-session",
                    "status": "provisioning",
                    "cluster": "test-cluster",
                },
            ),
            _Response(204, {}, entered=delete_started, release=release_delete),
        ]
    )
    lease = _Http(
        [
            _Response(
                200,
                {
                    "sessionId": "cancelled-session",
                    "status": "provisioning",
                },
                entered=ready_polled,
            )
        ]
    )
    adapter, _ready_timeouts = _adapter(lifecycle, lease)

    async def exercise() -> None:
        creation = asyncio.create_task(
            adapter.create_session_async(
                "firecracker-environment",
                "30m",
                "stable-cancelled-request",
                timeout=10,
            )
        )
        assert await asyncio.to_thread(ready_polled.wait, 5)
        creation.cancel()
        assert await asyncio.to_thread(delete_started.wait, 5)
        await asyncio.sleep(0)
        assert not creation.done()
        release_delete.set()
        with pytest.raises(asyncio.CancelledError):
            await creation

    try:
        asyncio.run(exercise())
    finally:
        release_delete.set()
        adapter.close()

    assert [method for method, _url, _kwargs in lifecycle.calls] == ["POST", "DELETE"]
