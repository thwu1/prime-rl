from __future__ import annotations

import json
import threading
import urllib.request
from collections import Counter
from typing import Any, Callable, Mapping

import pytest
from probe_inference_routes import (
    FORBIDDEN_REQUEST_FIELDS,
    HttpResponse,
    ProbeConfig,
    ProxyInfo,
    UrllibTransport,
    _attempted_retries,
    _backend_identifier,
    run_probe,
)

ReplyFactory = Callable[[str, str, int], tuple[int, str | None, Any]]
RawReplyFactory = Callable[[str, Mapping[str, Any], int], tuple[int, str | None, Any]]


class FakeTransport:
    def __init__(
        self,
        reply_factory: ReplyFactory,
        *,
        healthy_count: int = 2,
        raw_reply_factory: RawReplyFactory | None = None,
    ) -> None:
        self.reply_factory = reply_factory
        self.raw_reply_factory = raw_reply_factory
        self.healthy_count = healthy_count
        self.requests: list[dict[str, Any]] = []
        self._session_calls: Counter[str] = Counter()
        self._raw_session_calls: Counter[str] = Counter()
        self._session_backends: dict[str, str] = {}
        self._lock = threading.Lock()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        if method == "GET":
            with self._lock:
                self.requests.append(
                    {
                        "method": method,
                        "url": url,
                        "headers": dict(headers),
                        "body": body,
                        "timeout": timeout,
                    }
                )
            return HttpResponse(
                200,
                {},
                json.dumps(
                    {
                        "healthy_count": self.healthy_count,
                        "unhealthy_count": 0,
                    }
                ).encode(),
            )

        assert body is not None
        payload = json.loads(body)
        session_id = headers["X-LiteLLM-Session-ID"]
        if url.endswith("/v1/completions"):
            with self._lock:
                call_index = self._raw_session_calls[session_id]
                self._raw_session_calls[session_id] += 1
                self.requests.append(
                    {
                        "method": method,
                        "url": url,
                        "headers": dict(headers),
                        "body": body,
                        "timeout": timeout,
                    }
                )
                default_backend = self._session_backends.get(session_id)
            if self.raw_reply_factory is None:
                max_tokens = payload["max_tokens"]
                is_target = max_tokens == 1
                response_payload = _raw_completion(
                    " stable-target-canary" if is_target else " predecessor-canary",
                    prompt_tokens=1 if is_target else 64,
                    completion_tokens=max_tokens,
                )
                status, backend = 200, default_backend
            else:
                status, backend, response_payload = self.raw_reply_factory(
                    session_id,
                    payload,
                    call_index,
                )
            response_headers = {"X-LiteLLM-Model-API-Base": backend} if backend is not None else {}
            return HttpResponse(
                status,
                response_headers,
                json.dumps(response_payload).encode(),
            )

        marker = payload["messages"][-1]["content"].splitlines()[-1]
        with self._lock:
            call_index = self._session_calls[session_id]
            self._session_calls[session_id] += 1
            self.requests.append(
                {
                    "method": method,
                    "url": url,
                    "headers": dict(headers),
                    "body": body,
                    "timeout": timeout,
                }
            )
        status, backend, response_payload = self.reply_factory(session_id, marker, call_index)
        if backend is not None:
            with self._lock:
                self._session_backends.setdefault(session_id, backend)
        response_headers = {"X-LiteLLM-Model-API-Base": backend} if backend is not None else {}
        return HttpResponse(
            status,
            response_headers,
            json.dumps(response_payload).encode(),
        )


def _completion(content: str | None, reasoning: str | None = "reasoning") -> dict:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning,
                },
            }
        ]
    }


def _raw_completion(
    text: str | None,
    *,
    prompt_tokens: int = 1,
    completion_tokens: int = 1,
    finish_reason: str = "length",
) -> dict:
    choice: dict[str, Any] = {
        "finish_reason": finish_reason,
    }
    if text is not None:
        choice["text"] = text
    return {
        "choices": [choice],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _config(**overrides: Any) -> ProbeConfig:
    values: dict[str, Any] = {
        "model": "Kimi-K3",
        "expected_routes": 2,
        "discovery_requests": 4,
        "affinity_repeats": 2,
        "concurrency": 4,
        "session_prefix": "unit-probe",
    }
    values.update(overrides)
    return ProbeConfig(**values)


def _proxy(base_url: str = "http://proxy:8100", api_key: str = "secret") -> ProxyInfo:
    return ProxyInfo(
        base_url,
        api_key,
        served_model="Kimi-K3",
        sticky=True,
        redis_port=6379,
        endpoint_authority_sha256="a" * 64,
    )


def test_probe_covers_routes_and_reuses_stable_session_headers() -> None:
    def reply(session_id: str, marker: str, _call_index: int) -> tuple[int, str, dict]:
        discovery_index = int(session_id.rsplit("-", 1)[-1])
        backend = f"http://worker-{discovery_index % 2}:8000/v1"
        return 200, backend, _completion(marker)

    transport = FakeTransport(reply)
    summary = run_probe(
        _proxy(api_key="super-secret-key"),
        _config(),
        transport=transport,
    )

    assert summary["ok"] is True
    assert summary["endpoint_authority_sha256"] == "a" * 64
    assert summary["coverage"] == {
        "ok": True,
        "expected_routes": 2,
        "discovered_routes": 2,
        "missing_routes": 0,
        "extra_routes": 0,
        "backends": sorted(
            [
                _backend_identifier("http://worker-0:8000/v1")[0],
                _backend_identifier("http://worker-1:8000/v1")[0],
            ]
        ),
        "all_observed_backends": sorted(
            [
                _backend_identifier("http://worker-0:8000/v1")[0],
                _backend_identifier("http://worker-1:8000/v1")[0],
            ]
        ),
    }
    assert summary["requests"]["total"] == 8
    assert summary["affinity"]["ok"] is True
    assert summary["state_reuse"]["ok"] is True
    assert summary["state_reuse"]["routes_checked"] == 2
    assert summary["state_reuse"]["cycles_per_route"] == 3
    assert summary["state_reuse"]["requests"] == 12
    assert summary["state_reuse"]["expected_requests"] == 12

    chat_posts = [
        request
        for request in transport.requests
        if request["method"] == "POST" and request["url"].endswith("/v1/chat/completions")
    ]
    assert len(chat_posts) == 8
    bodies = [json.loads(request["body"]) for request in chat_posts]
    assert all(FORBIDDEN_REQUEST_FIELDS.isdisjoint(body) for body in bodies)
    assert all(
        request["headers"]["X-LiteLLM-Session-ID"] == request["headers"]["X-Session-ID"] for request in chat_posts
    )
    session_counts = Counter(request["headers"]["X-LiteLLM-Session-ID"] for request in chat_posts)
    assert sorted(session_counts.values()) == [1, 1, 3, 3]

    raw_posts = [
        request
        for request in transport.requests
        if request["method"] == "POST" and request["url"].endswith("/v1/completions")
    ]
    assert len(raw_posts) == 12
    raw_by_session: dict[str, list[dict[str, Any]]] = {}
    for request in raw_posts:
        session_id = request["headers"]["X-LiteLLM-Session-ID"]
        assert session_id == request["headers"]["X-Session-ID"]
        raw_by_session.setdefault(session_id, []).append(json.loads(request["body"]))
    assert sorted(len(requests) for requests in raw_by_session.values()) == [6, 6]
    for requests in raw_by_session.values():
        assert [request["max_tokens"] for request in requests] == [32, 1, 32, 1, 32, 1]
        assert len({request["prompt"] for request in requests[::2]}) == 3
        assert len({request["prompt"] for request in requests[1::2]}) == 1
        assert all(FORBIDDEN_REQUEST_FIELDS.isdisjoint(request) for request in requests)

    health_requests = [request for request in transport.requests if request["method"] == "GET"]
    assert len(health_requests) == 2
    assert all(request["url"].endswith("/health?model=Kimi-K3") for request in health_requests)
    serialized = json.dumps(summary)
    assert "super-secret-key" not in serialized
    assert "http://proxy:8100" not in serialized
    assert "http://worker-" not in serialized
    assert "stable-target-canary" not in serialized
    assert "predecessor-canary" not in serialized


def test_probe_fails_a_same_session_backend_change() -> None:
    def reply(_session_id: str, marker: str, call_index: int) -> tuple[int, str, dict]:
        backend = "http://worker-a/v1" if call_index == 0 else "http://worker-b/v1"
        return 200, backend, _completion(marker)

    summary = run_probe(
        _proxy("http://proxy:8100/v1"),
        _config(
            expected_routes=1,
            discovery_requests=1,
            affinity_repeats=1,
            concurrency=1,
        ),
        transport=FakeTransport(reply, healthy_count=1),
    )

    assert summary["ok"] is False
    assert summary["affinity"]["ok"] is False
    assert summary["affinity"]["mismatches"] == [
        {
            "session_id": "unit-probe-discovery-0",
            "expected_backend": _backend_identifier("http://worker-a/v1")[0],
            "observed_backend": _backend_identifier("http://worker-b/v1")[0],
        }
    ]
    assert summary["failures"][0]["problems"] == ["sticky_backend_changed"]


@pytest.mark.parametrize(
    ("content", "reasoning", "finish_reason", "problem"),
    [
        (None, None, "stop", "empty_response_and_reasoning"),
        ("@@@@@@@@", "reasoning", "stop", "repeated_at_in_content"),
        ("@ @ @ @ @ @ @ @", "reasoning", "stop", "repeated_at_in_content"),
        ("marker", "!!!!!!!!", "stop", "repeated_bang_in_reasoning"),
        ("marker", "!\n!\n!\n!\n!\n!\n!\n!", "stop", "repeated_bang_in_reasoning"),
        ("prefix marker suffix", "reasoning", "stop", "semantic_marker_mismatch"),
        ("marker", "reasoning", "length", "unexpected_finish_reason:length"),
    ],
)
def test_probe_rejects_empty_or_repeated_character_responses(
    content: str | None,
    reasoning: str | None,
    finish_reason: str,
    problem: str,
) -> None:
    def reply(_session_id: str, marker: str, _call_index: int) -> tuple[int, str, dict]:
        rendered = marker if content == "marker" else content
        response = _completion(rendered, reasoning)
        response["choices"][0]["finish_reason"] = finish_reason
        return 200, "http://worker/v1", response

    summary = run_probe(
        _proxy(),
        _config(
            expected_routes=1,
            discovery_requests=1,
            affinity_repeats=1,
            concurrency=1,
        ),
        transport=FakeTransport(reply, healthy_count=1),
    )

    assert summary["ok"] is False
    assert any(problem in failure["problems"] for failure in summary["failures"])


def test_probe_repeated_character_check_does_not_join_unrelated_text() -> None:
    def reply(_session_id: str, marker: str, _call_index: int) -> tuple[int, str, dict]:
        reasoning = " ".join(f"user{index}@example.com" for index in range(8))
        return 200, "http://worker/v1", _completion(marker, reasoning)

    summary = run_probe(
        _proxy(),
        _config(
            expected_routes=1,
            discovery_requests=1,
            affinity_repeats=1,
            concurrency=1,
        ),
        transport=FakeTransport(reply, healthy_count=1),
    )

    assert summary["ok"] is True


def test_probe_fails_http_errors_and_route_undercoverage() -> None:
    def reply(_session_id: str, marker: str, call_index: int) -> tuple[int, str, dict]:
        if call_index == 0:
            return 503, "http://only-worker/v1", {"error": "unavailable"}
        return 200, "http://only-worker/v1", _completion(marker)

    summary = run_probe(
        _proxy(),
        _config(expected_routes=2, discovery_requests=2, affinity_repeats=1),
        transport=FakeTransport(reply),
    )

    assert summary["ok"] is False
    assert summary["coverage"]["discovered_routes"] == 1
    assert summary["coverage"]["missing_routes"] == 1
    assert summary["coverage"]["extra_routes"] == 0
    assert summary["requests"]["failed"] >= 1
    assert any("http_status_503" in failure["problems"] for failure in summary["failures"])


def test_probe_fails_when_more_routes_exist_than_expected() -> None:
    def reply(session_id: str, marker: str, _call_index: int) -> tuple[int, str, dict]:
        backend = f"http://worker-{session_id.rsplit('-', 1)[-1]}/v1"
        return 200, backend, _completion(marker)

    summary = run_probe(
        _proxy(),
        _config(expected_routes=2, discovery_requests=3, affinity_repeats=1),
        transport=FakeTransport(reply),
    )

    assert summary["ok"] is False
    assert summary["coverage"]["discovered_routes"] == 3
    assert summary["coverage"]["missing_routes"] == 0
    assert summary["coverage"]["extra_routes"] == 1


def test_health_route_count_must_match_before_requests_start() -> None:
    def reply(_session_id: str, marker: str, _call_index: int) -> tuple[int, str, dict]:
        return 200, "http://worker/v1", _completion(marker)

    transport = FakeTransport(reply, healthy_count=1)
    summary = run_probe(_proxy(), _config(), transport=transport)

    assert summary["ok"] is False
    assert summary["health"]["before"]["healthy_count"] == 1
    assert summary["health"]["before"]["problems"] == ["healthy_route_count:1"]
    assert all(request["method"] == "GET" for request in transport.requests)


def test_shared_affinity_metadata_is_required() -> None:
    with pytest.raises(ValueError, match="extras.redis_port"):
        run_probe(
            ProxyInfo(
                "http://proxy:8100",
                "secret",
                served_model="Kimi-K3",
                sticky=True,
                endpoint_authority_sha256="a" * 64,
            ),
            _config(),
            transport=FakeTransport(lambda *_: (500, None, {})),
        )


def test_retry_and_unsafe_backend_headers_are_rejected_without_leaking() -> None:
    assert _attempted_retries({"X-LiteLLM-Attempted-Retries": "2"}) == (
        2,
        "upstream_retries:2",
    )
    unsafe = "http://user:password@worker:8000/v1?api_key=credential"
    backend, problem = _backend_identifier(unsafe)
    assert problem == "invalid_backend_header"
    assert backend == "invalid-backend"
    assert "password" not in backend
    assert "credential" not in backend


def test_health_failure_stops_before_completions() -> None:
    class FailedHealthTransport:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, *args: Any, **kwargs: Any) -> HttpResponse:
            self.calls += 1
            return HttpResponse(401, {}, b"unauthorized")

    transport = FailedHealthTransport()
    summary = run_probe(
        _proxy(),
        _config(),
        transport=transport,
    )

    assert summary["ok"] is False
    assert summary["health"]["ok"] is False
    assert summary["health"]["after"] is None
    assert summary["health"]["before"] == {
        "ok": False,
        "status_code": 401,
        "problem": "http_status_401",
        "problems": ["http_status_401"],
        "healthy_count": None,
        "unhealthy_count": None,
    }
    assert summary["requests"]["total"] == 0
    assert transport.calls == 1


@pytest.mark.parametrize(
    ("failure_mode", "expected_problem"),
    [
        ("unsupported", "http_status_404"),
        ("routing", "sticky_backend_changed"),
        ("corrupt", "empty_completion_text"),
        ("changed", "state_reuse_target_changed"),
    ],
)
def test_state_reuse_gate_fails_closed(
    failure_mode: str,
    expected_problem: str,
) -> None:
    backend = "http://worker/v1"

    def chat_reply(_session_id: str, marker: str, _call_index: int) -> tuple[int, str, dict]:
        return 200, backend, _completion(marker)

    def raw_reply(
        _session_id: str,
        payload: Mapping[str, Any],
        call_index: int,
    ) -> tuple[int, str | None, dict]:
        is_target = payload["max_tokens"] == 1
        prompt_tokens = 1 if is_target else 64
        completion_tokens = payload["max_tokens"]
        text = " stable-target-a" if is_target else " predecessor-canary"
        response_backend: str | None = backend
        status = 200
        if failure_mode == "unsupported":
            status = 404
        elif failure_mode == "routing" and is_target:
            response_backend = None
        elif failure_mode == "corrupt" and is_target:
            text = "   "
        elif failure_mode == "changed" and is_target and call_index > 1:
            text = " stable-target-b"
        return (
            status,
            response_backend,
            _raw_completion(
                text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
        )

    summary = run_probe(
        _proxy("http://proxy:8100/v1"),
        _config(
            expected_routes=1,
            discovery_requests=1,
            affinity_repeats=1,
            concurrency=1,
            state_reuse_cycles=2,
        ),
        transport=FakeTransport(
            chat_reply,
            healthy_count=1,
            raw_reply_factory=raw_reply,
        ),
    )

    assert summary["ok"] is False
    assert summary["state_reuse"]["ok"] is False
    route = summary["state_reuse"]["routes"][0]
    assert expected_problem in route["problem_counts"]
    serialized = json.dumps(summary)
    assert "stable-target-a" not in serialized
    assert "stable-target-b" not in serialized
    assert "predecessor-canary" not in serialized


def test_state_reuse_rejects_non_one_token_target_usage() -> None:
    backend = "http://worker/v1"

    def raw_reply(
        _session_id: str,
        payload: Mapping[str, Any],
        _call_index: int,
    ) -> tuple[int, str, dict]:
        is_target = payload["max_tokens"] == 1
        return (
            200,
            backend,
            _raw_completion(
                " target" if is_target else " predecessor",
                prompt_tokens=2 if is_target else 64,
                completion_tokens=payload["max_tokens"],
            ),
        )

    summary = run_probe(
        _proxy(),
        _config(
            expected_routes=1,
            discovery_requests=1,
            affinity_repeats=1,
            concurrency=1,
            state_reuse_cycles=2,
        ),
        transport=FakeTransport(
            lambda _session_id, marker, _call_index: (200, backend, _completion(marker)),
            healthy_count=1,
            raw_reply_factory=raw_reply,
        ),
    )

    assert summary["ok"] is False
    assert summary["state_reuse"]["routes"][0]["problem_counts"] == {"target_prompt_not_one_token": 2}


def test_urllib_transport_does_not_consult_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: list[Any] = []
    build_opener = urllib.request.build_opener

    def fail_getproxies() -> dict[str, str]:
        raise AssertionError("ambient proxy discovery must not run")

    def capture_build_opener(*requested_handlers: Any) -> Any:
        handlers.extend(requested_handlers)
        return build_opener(*requested_handlers)

    monkeypatch.setattr(urllib.request, "getproxies", fail_getproxies)
    monkeypatch.setattr(urllib.request, "build_opener", capture_build_opener)

    UrllibTransport()

    proxy_handlers = [handler for handler in handlers if isinstance(handler, urllib.request.ProxyHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
