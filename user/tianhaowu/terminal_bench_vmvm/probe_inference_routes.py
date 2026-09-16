#!/usr/bin/env python3
"""Semantically probe every observable route behind an OpenAI-compatible proxy.

The probe deliberately uses only the Python standard library so it can run on
the login host or an x86 compute node without changing the environment.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

BACKEND_HEADER = "x-litellm-model-api-base"
SESSION_HEADERS = ("X-LiteLLM-Session-ID", "X-Session-ID")
FORBIDDEN_REQUEST_FIELDS = frozenset({"logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"})
MAX_RESPONSE_BYTES = 1 << 20
SESSION_PREFIX_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


@dataclass(frozen=True)
class ProxyInfo:
    base_url: str
    api_key: str = field(repr=False)
    served_model: str | None = None
    sticky: bool | None = None
    redis_port: int | None = None


@dataclass(frozen=True)
class ProbeConfig:
    model: str
    expected_routes: int
    discovery_requests: int
    affinity_repeats: int = 2
    concurrency: int = 16
    request_timeout: float = 120.0
    health_timeout: float = 30.0
    max_tokens: int = 4096
    repeated_char_threshold: int = 8
    require_reasoning: bool = False
    require_shared_affinity: bool = True
    check_health: bool = True
    session_prefix: str = field(default_factory=lambda: f"semantic-route-probe-{uuid.uuid4().hex}")


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class UrllibTransport:
    """Small urllib adapter kept injectable for deterministic unit tests."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                response_headers = dict(response.headers.items())
                status_code = response.status
        except urllib.error.HTTPError as exc:
            response_body = exc.read(MAX_RESPONSE_BYTES + 1)
            response_headers = dict(exc.headers.items()) if exc.headers else {}
            status_code = exc.code
        return HttpResponse(
            status_code=status_code,
            headers=response_headers,
            body=response_body,
        )


@dataclass(frozen=True)
class RequestSpec:
    phase: str
    request_index: int
    session_id: str
    marker: str
    expected_backend: str | None = None


@dataclass(frozen=True)
class RequestResult:
    phase: str
    request_index: int
    session_id: str
    expected_backend: str | None
    backend: str | None
    status_code: int | None
    attempted_retries: int | None
    content_length: int
    reasoning_length: int
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def load_proxy_info(path: Path) -> ProxyInfo:
    """Read URL and credential without logging or returning the source object."""

    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read proxy info at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("proxy info must be a JSON object")

    base_url = value.get("url")
    api_key = value.get("api_key")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("proxy info must contain a nonempty string 'url'")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("proxy info must contain a nonempty string 'api_key'")
    served_model = value.get("model")
    if served_model is not None and not isinstance(served_model, str):
        raise ValueError("proxy info 'model' must be a string when present")

    extras = value.get("extras", {})
    if not isinstance(extras, dict):
        raise ValueError("proxy info 'extras' must be an object when present")
    sticky_value = extras.get("sticky")
    sticky = sticky_value if isinstance(sticky_value, bool) else None
    redis_value = extras.get("redis_port")
    redis_port = (
        redis_value
        if isinstance(redis_value, int)
        and not isinstance(redis_value, bool)
        and 1 <= redis_value <= 65535
        else None
    )
    return ProxyInfo(
        base_url=_validate_base_url(base_url.strip()),
        api_key=api_key,
        served_model=served_model,
        sticky=sticky,
        redis_port=redis_port,
    )


def _validate_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("proxy URL must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("proxy URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("proxy URL must not contain a query or fragment")
    return urllib.parse.urlunsplit(parsed)


def _endpoint_urls(base_url: str, model: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(_validate_base_url(base_url))
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        root_path = path[:-3].rstrip("/")
        chat_path = f"{path}/chat/completions"
    else:
        root_path = path
        chat_path = f"{path}/v1/chat/completions"
    health_path = f"{root_path}/health"
    health_url = urllib.parse.urlunsplit(
        parsed._replace(path=health_path, query=urllib.parse.urlencode({"model": model}))
    )
    chat_url = urllib.parse.urlunsplit(parsed._replace(path=chat_path))
    return health_url, chat_url


def _validate_config(config: ProbeConfig) -> None:
    if not config.model.strip():
        raise ValueError("model must be nonempty")
    if config.expected_routes < 1:
        raise ValueError("expected_routes must be at least 1")
    if config.discovery_requests < config.expected_routes:
        raise ValueError("discovery_requests must be at least expected_routes")
    if config.affinity_repeats < 1:
        raise ValueError("affinity_repeats must be at least 1")
    if config.concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if config.request_timeout <= 0 or config.health_timeout <= 0:
        raise ValueError("timeouts must be positive")
    if config.max_tokens < 1:
        raise ValueError("max_tokens must be at least 1")
    if config.repeated_char_threshold < 2:
        raise ValueError("repeated_char_threshold must be at least 2")
    if not config.session_prefix or not SESSION_PREFIX_RE.fullmatch(config.session_prefix):
        raise ValueError("session_prefix may contain only letters, digits, '.', '_', ':', and '-'")
    longest_session = f"{config.session_prefix}-discovery-{config.discovery_requests - 1}"
    if len(longest_session) > 240:
        raise ValueError("generated session IDs must be at most 240 characters")


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "<redacted>") if secret else text


def _redact_json(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return _redact(value, secret)
    if isinstance(value, list):
        return [_redact_json(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(str(key), secret): _redact_json(item, secret) for key, item in value.items()}
    return value


def _response_header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.casefold()
    for key, value in headers.items():
        if key.casefold() == wanted:
            stripped = str(value).strip()
            return stripped or None
    return None


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _has_whitespace_separated_run(text: str, character: str, threshold: int) -> bool:
    """Detect a repeated character separated by whitespace, without joining unrelated text."""
    pattern = rf"{re.escape(character)}(?:\s*{re.escape(character)}){{{threshold - 1},}}"
    return re.search(pattern, text) is not None


def _semantic_problems(
    payload: Any,
    marker: str,
    *,
    repeated_char_threshold: int,
    require_reasoning: bool,
) -> tuple[int, int, list[str]]:
    problems: list[str] = []
    if not isinstance(payload, dict):
        return 0, 0, ["response_json_not_object"]
    if payload.get("error") is not None:
        return 0, 0, ["api_error_response"]

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return 0, 0, ["missing_choice"]
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        return 0, 0, ["missing_message"]

    message = choice["message"]
    content = _extract_text(message.get("content"))
    reasoning = _extract_text(message.get("reasoning_content"))
    if not reasoning:
        reasoning = _extract_text(message.get("reasoning"))
    if not content.strip() and not reasoning.strip():
        problems.append("empty_response_and_reasoning")
    elif not content.strip():
        problems.append("empty_response_content")
    if require_reasoning and not reasoning.strip():
        problems.append("empty_reasoning_content")
    if content.strip() != marker:
        problems.append("semantic_marker_mismatch")

    finish_reason = choice.get("finish_reason")
    if finish_reason != "stop":
        problems.append(f"unexpected_finish_reason:{finish_reason!s}")

    repeated = {
        "@": "at",
        "!": "bang",
    }
    for field_name, text in (("content", content), ("reasoning", reasoning)):
        for character, label in repeated.items():
            if _has_whitespace_separated_run(text, character, repeated_char_threshold):
                problems.append(f"repeated_{label}_in_{field_name}")
    return len(content), len(reasoning), problems


def _completion_payload(config: ProbeConfig, marker: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": "Follow the user's exact output-format instruction.",
            },
            {
                "role": "user",
                "content": (f"Return exactly the marker on the next line, with no other text.\n{marker}"),
            },
        ],
        "temperature": 0,
        "max_tokens": config.max_tokens,
    }
    assert FORBIDDEN_REQUEST_FIELDS.isdisjoint(payload)
    return payload


def _marker(session_prefix: str, phase: str, request_index: int) -> str:
    digest = hashlib.sha256(f"{session_prefix}:{phase}:{request_index}".encode()).hexdigest()[:16]
    return f"SEMANTIC_ROUTE_PROBE_OK_{digest}"


def _backend_identifier(raw_backend: str) -> tuple[str, str | None]:
    """Return a safe comparable API-base value without leaking embedded credentials."""

    try:
        return _validate_base_url(raw_backend), None
    except ValueError:
        digest = hashlib.sha256(raw_backend.encode()).hexdigest()[:16]
        return f"invalid-backend-{digest}", "invalid_backend_header"


def _attempted_retries(headers: Mapping[str, str]) -> tuple[int | None, str | None]:
    raw_value = _response_header(headers, "x-litellm-attempted-retries")
    if raw_value is None:
        return None, None
    try:
        value = int(raw_value)
    except ValueError:
        return None, "invalid_attempted_retries_header"
    if value < 0:
        return value, "invalid_attempted_retries_header"
    if value > 0:
        return value, f"upstream_retries:{value}"
    return value, None


def _send_completion(
    transport: HttpTransport,
    proxy: ProxyInfo,
    config: ProbeConfig,
    chat_url: str,
    spec: RequestSpec,
) -> RequestResult:
    payload = _completion_payload(config, spec.marker)
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        "Authorization": f"Bearer {proxy.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        SESSION_HEADERS[0]: spec.session_id,
        SESSION_HEADERS[1]: spec.session_id,
    }
    try:
        response = transport.request(
            "POST",
            chat_url,
            headers=headers,
            body=body,
            timeout=config.request_timeout,
        )
    except Exception as exc:  # The summary, rather than a traceback, is the gate.
        problem = _redact(f"transport_error:{type(exc).__name__}:{exc}", proxy.api_key)
        return RequestResult(
            phase=spec.phase,
            request_index=spec.request_index,
            session_id=spec.session_id,
            expected_backend=spec.expected_backend,
            backend=None,
            status_code=None,
            attempted_retries=None,
            content_length=0,
            reasoning_length=0,
            problems=(problem,),
        )

    problems: list[str] = []
    raw_backend = _response_header(response.headers, BACKEND_HEADER)
    if raw_backend is None:
        backend = None
        problems.append("missing_backend_header")
    else:
        backend, backend_problem = _backend_identifier(raw_backend)
        if backend_problem is not None:
            problems.append(backend_problem)
    attempted_retries, retry_problem = _attempted_retries(response.headers)
    if retry_problem is not None:
        problems.append(retry_problem)
    if spec.expected_backend is not None and backend != spec.expected_backend:
        problems.append("sticky_backend_changed")
    if not 200 <= response.status_code < 300:
        problems.append(f"http_status_{response.status_code}")
        return RequestResult(
            phase=spec.phase,
            request_index=spec.request_index,
            session_id=spec.session_id,
            expected_backend=spec.expected_backend,
            backend=backend,
            status_code=response.status_code,
            attempted_retries=attempted_retries,
            content_length=0,
            reasoning_length=0,
            problems=tuple(problems),
        )
    if len(response.body) > MAX_RESPONSE_BYTES:
        problems.append("response_too_large")
        return RequestResult(
            phase=spec.phase,
            request_index=spec.request_index,
            session_id=spec.session_id,
            expected_backend=spec.expected_backend,
            backend=backend,
            status_code=response.status_code,
            attempted_retries=attempted_retries,
            content_length=0,
            reasoning_length=0,
            problems=tuple(problems),
        )

    try:
        response_payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        problems.append("invalid_json_response")
        content_length = 0
        reasoning_length = 0
    else:
        content_length, reasoning_length, semantic_problems = _semantic_problems(
            response_payload,
            spec.marker,
            repeated_char_threshold=config.repeated_char_threshold,
            require_reasoning=config.require_reasoning,
        )
        problems.extend(semantic_problems)
    return RequestResult(
        phase=spec.phase,
        request_index=spec.request_index,
        session_id=spec.session_id,
        expected_backend=spec.expected_backend,
        backend=backend,
        status_code=response.status_code,
        attempted_retries=attempted_retries,
        content_length=content_length,
        reasoning_length=reasoning_length,
        problems=tuple(problems),
    )


def _run_specs(
    specs: Sequence[RequestSpec],
    worker: Any,
    concurrency: int,
) -> list[RequestResult]:
    if not specs:
        return []
    results: list[RequestResult | None] = [None] * len(specs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, len(specs))) as executor:
        futures = {executor.submit(worker, spec): position for position, spec in enumerate(specs)}
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()
    return [result for result in results if result is not None]


def _run_session_sequences(
    specs: Sequence[RequestSpec],
    worker: Any,
    concurrency: int,
) -> list[RequestResult]:
    """Run each session serially while allowing different sessions to overlap."""

    by_session: dict[str, list[RequestSpec]] = {}
    for spec in specs:
        by_session.setdefault(spec.session_id, []).append(spec)

    def run_sequence(sequence: Sequence[RequestSpec]) -> list[RequestResult]:
        return [worker(spec) for spec in sequence]

    if not by_session:
        return []
    results: list[RequestResult] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(concurrency, len(by_session))
    ) as executor:
        futures = [executor.submit(run_sequence, sequence) for sequence in by_session.values()]
        for future in concurrent.futures.as_completed(futures):
            results.extend(future.result())
    return sorted(results, key=lambda result: result.request_index)


def _health_check(
    transport: HttpTransport,
    proxy: ProxyInfo,
    health_url: str,
    timeout: float,
    expected_routes: int,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {proxy.api_key}",
        "Accept": "application/json",
    }
    try:
        response = transport.request("GET", health_url, headers=headers, body=None, timeout=timeout)
    except Exception as exc:
        problem = _redact(f"transport_error:{type(exc).__name__}:{exc}", proxy.api_key)
        return {
            "ok": False,
            "status_code": None,
            "problem": problem,
            "problems": [problem],
            "healthy_count": None,
            "unhealthy_count": None,
        }
    problems: list[str] = []
    if not 200 <= response.status_code < 300:
        problem = f"http_status_{response.status_code}"
        return {
            "ok": False,
            "status_code": response.status_code,
            "problem": problem,
            "problems": [problem],
            "healthy_count": None,
            "unhealthy_count": None,
        }

    healthy_count: int | None = None
    unhealthy_count: int | None = None
    if len(response.body) > MAX_RESPONSE_BYTES:
        problems.append("response_too_large")
    else:
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            problems.append("invalid_json_response")
        else:
            if isinstance(payload, dict):
                healthy_value = payload.get("healthy_count")
                unhealthy_value = payload.get("unhealthy_count")
                if isinstance(healthy_value, int) and not isinstance(healthy_value, bool):
                    healthy_count = healthy_value
                elif isinstance(payload.get("healthy_endpoints"), list):
                    healthy_count = len(payload["healthy_endpoints"])
                if isinstance(unhealthy_value, int) and not isinstance(unhealthy_value, bool):
                    unhealthy_count = unhealthy_value
                elif isinstance(payload.get("unhealthy_endpoints"), list):
                    unhealthy_count = len(payload["unhealthy_endpoints"])
            if healthy_count is None or unhealthy_count is None:
                problems.append("missing_endpoint_health_counts")

    if healthy_count is not None and healthy_count != expected_routes:
        problems.append(f"healthy_route_count:{healthy_count}")
    if unhealthy_count is not None and unhealthy_count != 0:
        problems.append(f"unhealthy_route_count:{unhealthy_count}")
    return {
        "ok": not problems,
        "status_code": response.status_code,
        "problem": problems[0] if len(problems) == 1 else None,
        "problems": problems,
        "healthy_count": healthy_count,
        "unhealthy_count": unhealthy_count,
    }


def _failure_record(result: RequestResult) -> dict[str, Any]:
    return {
        "phase": result.phase,
        "request_index": result.request_index,
        "session_id": result.session_id,
        "expected_backend": result.expected_backend,
        "observed_backend": result.backend,
        "status_code": result.status_code,
        "attempted_retries": result.attempted_retries,
        "problems": list(result.problems),
    }


def _build_summary(
    proxy: ProxyInfo,
    config: ProbeConfig,
    health: dict[str, Any],
    discovery: Sequence[RequestResult],
    affinity: Sequence[RequestResult],
    representatives: Mapping[str, RequestResult],
) -> dict[str, Any]:
    discovered = sorted({result.backend for result in discovery if result.backend is not None})
    observed = sorted({result.backend for result in (*discovery, *affinity) if result.backend is not None})
    coverage_ok = len(discovered) == config.expected_routes
    expected_affinity_requests = len(discovered) * config.affinity_repeats
    affinity_ok = (
        bool(discovered)
        and len(representatives) == len(discovered)
        and len(affinity) == expected_affinity_requests
        and all(result.ok for result in affinity)
    )
    all_results = [*discovery, *affinity]
    request_ok = bool(discovery) and all(result.ok for result in all_results)

    routes: list[dict[str, Any]] = []
    for backend in discovered:
        relevant = [result for result in discovery if result.backend == backend] + [
            result for result in affinity if result.expected_backend == backend
        ]
        problem_counts = Counter(problem for result in relevant for problem in result.problems)
        representative = representatives.get(backend)
        routes.append(
            {
                "backend": backend,
                "representative_session_id": (representative.session_id if representative is not None else None),
                "requests": len(relevant),
                "passed": sum(result.ok for result in relevant),
                "failed": sum(not result.ok for result in relevant),
                "problem_counts": dict(sorted(problem_counts.items())),
                "ok": bool(relevant) and all(result.ok for result in relevant),
            }
        )

    failures = [_failure_record(result) for result in all_results if not result.ok]
    sticky_mismatches = [
        {
            "session_id": result.session_id,
            "expected_backend": result.expected_backend,
            "observed_backend": result.backend,
        }
        for result in affinity
        if result.expected_backend != result.backend
    ]
    ok = bool(health["ok"] and coverage_ok and affinity_ok and request_ok)
    summary = {
        "ok": ok,
        "config": {
            "model": config.model,
            "expected_routes": config.expected_routes,
            "discovery_requests": config.discovery_requests,
            "affinity_repeats": config.affinity_repeats,
            "concurrency": config.concurrency,
            "request_timeout_seconds": config.request_timeout,
            "health_timeout_seconds": config.health_timeout,
            "max_tokens": config.max_tokens,
            "repeated_char_threshold": config.repeated_char_threshold,
            "require_reasoning": config.require_reasoning,
            "require_shared_affinity": config.require_shared_affinity,
            "session_prefix": config.session_prefix,
        },
        "proxy_base_url": proxy.base_url,
        "health": health,
        "coverage": {
            "ok": coverage_ok,
            "expected_routes": config.expected_routes,
            "discovered_routes": len(discovered),
            "missing_routes": max(config.expected_routes - len(discovered), 0),
            "extra_routes": max(len(discovered) - config.expected_routes, 0),
            "backends": discovered,
            "all_observed_backends": observed,
        },
        "requests": {
            "ok": request_ok,
            "total": len(all_results),
            "passed": sum(result.ok for result in all_results),
            "failed": len(failures),
            "discovery": len(discovery),
            "affinity": len(affinity),
        },
        "affinity": {
            "ok": affinity_ok,
            "routes_checked": len(representatives),
            "requests": len(affinity),
            "expected_requests": expected_affinity_requests,
            "mismatches": sticky_mismatches,
        },
        "routes": routes,
        "failures": failures,
    }
    return _redact_json(summary, proxy.api_key)


def run_probe(
    proxy: ProxyInfo,
    config: ProbeConfig,
    *,
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    """Run health, route discovery, and same-session affinity gates."""

    _validate_config(config)
    proxy = ProxyInfo(
        base_url=_validate_base_url(proxy.base_url),
        api_key=proxy.api_key,
        served_model=proxy.served_model,
        sticky=proxy.sticky,
        redis_port=proxy.redis_port,
    )
    if not proxy.api_key:
        raise ValueError("api_key must be nonempty")
    if proxy.served_model is not None and proxy.served_model != config.model:
        raise ValueError(
            f"proxy serves model {proxy.served_model!r}, not requested model {config.model!r}"
        )
    if config.require_shared_affinity:
        if proxy.sticky is not True:
            raise ValueError("proxy_info extras.sticky must be true for the sticky-route gate")
        if proxy.redis_port is None:
            raise ValueError(
                "proxy_info must publish a valid extras.redis_port for shared affinity"
            )
    transport = transport or UrllibTransport()
    health_url, chat_url = _endpoint_urls(proxy.base_url, config.model)

    if config.check_health:
        health_before = _health_check(
            transport,
            proxy,
            health_url,
            config.health_timeout,
            config.expected_routes,
        )
    else:
        health_before = {"ok": True, "skipped": True}
    if not health_before["ok"]:
        health = {"ok": False, "before": health_before, "after": None}
        return _build_summary(proxy, config, health, [], [], {})

    discovery_specs = [
        RequestSpec(
            phase="discovery",
            request_index=index,
            session_id=f"{config.session_prefix}-discovery-{index}",
            marker=_marker(config.session_prefix, "discovery", index),
        )
        for index in range(config.discovery_requests)
    ]
    worker = lambda spec: _send_completion(  # noqa: E731
        transport, proxy, config, chat_url, spec
    )
    discovery = _run_specs(discovery_specs, worker, config.concurrency)

    representatives: dict[str, RequestResult] = {}
    for result in discovery:
        if result.backend is None:
            continue
        current = representatives.get(result.backend)
        if current is None or (result.ok and not current.ok):
            representatives[result.backend] = result

    affinity_specs: list[RequestSpec] = []
    affinity_index = 0
    for backend in sorted(representatives):
        representative = representatives[backend]
        for _ in range(config.affinity_repeats):
            affinity_specs.append(
                RequestSpec(
                    phase="affinity",
                    request_index=affinity_index,
                    session_id=representative.session_id,
                    marker=_marker(config.session_prefix, "affinity", affinity_index),
                    expected_backend=backend,
                )
            )
            affinity_index += 1
    affinity = _run_session_sequences(affinity_specs, worker, config.concurrency)
    if config.check_health:
        health_after = _health_check(
            transport,
            proxy,
            health_url,
            config.health_timeout,
            config.expected_routes,
        )
    else:
        health_after = {"ok": True, "skipped": True}
    health = {
        "ok": bool(health_before["ok"] and health_after["ok"]),
        "before": health_before,
        "after": health_after,
    }
    return _build_summary(proxy, config, health, discovery, affinity, representatives)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe semantic correctness and sticky routing through an "
            "OpenAI-compatible proxy. The final stdout record is JSON."
        )
    )
    parser.add_argument("--proxy-info", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--expected-routes", required=True, type=int)
    parser.add_argument(
        "--requests",
        dest="discovery_requests",
        type=int,
        default=64,
        help="number of distinct-session discovery completions (default: 64)",
    )
    parser.add_argument(
        "--repeats",
        dest="affinity_repeats",
        type=int,
        default=2,
        help="additional same-session completions per discovered route (default: 2)",
    )
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument(
        "--timeout",
        "--request-timeout",
        dest="request_timeout",
        type=float,
        default=120.0,
    )
    parser.add_argument("--health-timeout", type=float, default=30.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--repeated-char-threshold", type=int, default=8)
    parser.add_argument("--require-reasoning", action="store_true")
    parser.add_argument(
        "--allow-unverified-affinity",
        action="store_true",
        help=(
            "allow proxy metadata without sticky=true and a Redis sidecar; "
            "do not use this for the production readiness gate"
        ),
    )
    parser.add_argument("--skip-health", action="store_true")
    parser.add_argument(
        "--session-prefix",
        default=None,
        help="safe run-unique prefix; generated automatically when omitted",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    proxy: ProxyInfo | None = None
    try:
        proxy = load_proxy_info(args.proxy_info)
        config = ProbeConfig(
            model=args.model,
            expected_routes=args.expected_routes,
            discovery_requests=args.discovery_requests,
            affinity_repeats=args.affinity_repeats,
            concurrency=args.concurrency,
            request_timeout=args.request_timeout,
            health_timeout=args.health_timeout,
            max_tokens=args.max_tokens,
            repeated_char_threshold=args.repeated_char_threshold,
            require_reasoning=args.require_reasoning,
            require_shared_affinity=not args.allow_unverified_affinity,
            check_health=not args.skip_health,
            session_prefix=(
                args.session_prefix if args.session_prefix is not None else f"semantic-route-probe-{uuid.uuid4().hex}"
            ),
        )
        summary = run_probe(proxy, config)
        exit_code = 0 if summary["ok"] else 1
    except Exception as exc:
        secret = proxy.api_key if proxy is not None else ""
        summary = {
            "ok": False,
            "fatal_error": _redact(f"{type(exc).__name__}: {exc}", secret),
        }
        exit_code = 2

    json.dump(
        summary,
        sys.stdout,
        indent=2 if args.pretty else None,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
