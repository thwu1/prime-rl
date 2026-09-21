#!/usr/bin/env python3
"""Run a bounded, credential-safe probe against a named model endpoint."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from deployment_endpoint import EndpointBindingError, load_deployment_endpoint

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MIN_COMPLETION_TOKENS = 128
MAX_COMPLETION_TOKENS = 4096
DEFAULT_PROFILE = "qwen38-2p4t"
SESSION_HEADER = "X-Session-ID"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ModelEndpointProbeError(RuntimeError):
    """Stable endpoint-probe failure without response or credential detail."""


@dataclass(frozen=True)
class EndpointProfile:
    name: str
    deployment_id: str
    model: str
    proxy_info: Path
    deployment_spec: Path
    health_timeout_seconds: float
    request_timeout_seconds: float
    max_tokens: int


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes = field(repr=False)


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


class UrllibTransport:
    """HTTP transport which deliberately ignores ambient proxy variables."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                status_code = response.status
        except urllib.error.HTTPError as error:
            payload = error.read(MAX_RESPONSE_BYTES + 1)
            status_code = error.code
        return HttpResponse(status_code=status_code, body=payload)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


PROFILES = {
    DEFAULT_PROFILE: EndpointProfile(
        name=DEFAULT_PROFILE,
        deployment_id="shared_qwen38_2p4t",
        model="Qwen3.8-2.4T-A95B",
        proxy_info=Path(
            "/checkpoint/ram/shared/vllm_deployments_v2/"
            "shared_qwen38_2p4t/proxy_info.json"
        ),
        deployment_spec=Path(
            "/checkpoint/ram/shared/vllm_deployments_v2/"
            "shared_qwen38_2p4t/spec.yaml"
        ),
        health_timeout_seconds=15.0,
        request_timeout_seconds=300.0,
        max_tokens=128,
    )
}


def _strict_json_object(body: bytes) -> dict[str, Any]:
    if len(body) > MAX_RESPONSE_BYTES:
        raise ModelEndpointProbeError("response_too_large")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ModelEndpointProbeError("response_duplicate_key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ModelEndpointProbeError("response_non_finite")
            ),
        )
    except ModelEndpointProbeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ModelEndpointProbeError("response_invalid_json") from error
    if not isinstance(value, dict):
        raise ModelEndpointProbeError("response_invalid_shape")
    return value


def _urls(base_url: str, model: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ModelEndpointProbeError("endpoint_url_invalid")
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        raise ModelEndpointProbeError("endpoint_url_invalid")
    health_path = f"{path[:-3].rstrip('/')}/health"
    health = urllib.parse.urlunsplit(
        parsed._replace(path=health_path, query=urllib.parse.urlencode({"model": model}))
    )
    completion = urllib.parse.urlunsplit(parsed._replace(path=f"{path}/chat/completions"))
    return health, completion


def _reasoning_summary(message: Mapping[str, Any]) -> tuple[bool, str | None]:
    for name in ("reasoning_content", "reasoning", "reasoning_details"):
        value = message.get(name)
        if isinstance(value, str) and value.strip():
            return True, name
        if isinstance(value, list) and value:
            return True, name
    return False, None


def run_probe(
    profile: EndpointProfile,
    *,
    expected_proxy_info_sha256: str | None = None,
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    if not MIN_COMPLETION_TOKENS <= profile.max_tokens <= MAX_COMPLETION_TOKENS:
        raise ModelEndpointProbeError("max_tokens_invalid")
    if expected_proxy_info_sha256 is not None and (
        _SHA256_RE.fullmatch(expected_proxy_info_sha256) is None
    ):
        raise ModelEndpointProbeError("proxy_info_sha256_invalid")
    endpoint = load_deployment_endpoint(
        profile.proxy_info,
        deployment_id=profile.deployment_id,
        expected_model=profile.model,
        deployment_spec=profile.deployment_spec,
        expected_proxy_info_sha256=expected_proxy_info_sha256,
    )
    health_url, completion_url = _urls(endpoint.client_base_url, profile.model)
    client = transport or UrllibTransport()
    session_id = f"endpoint-smoke-{uuid.uuid4().hex}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {endpoint.api_key}",
        "Content-Type": "application/json",
        SESSION_HEADER: session_id,
    }
    started = time.monotonic()
    health = client.request(
        "GET",
        health_url,
        headers=headers,
        body=None,
        timeout=profile.health_timeout_seconds,
    )
    health_latency_ms = round((time.monotonic() - started) * 1000, 3)
    if health.status_code != 200 or len(health.body) > MAX_RESPONSE_BYTES:
        raise ModelEndpointProbeError("health_check_failed")

    body = json.dumps(
        {
            "model": profile.model,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with a brief acknowledgement.",
                }
            ],
            "temperature": 0,
            "max_tokens": profile.max_tokens,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    started = time.monotonic()
    completion = client.request(
        "POST",
        completion_url,
        headers=headers,
        body=body,
        timeout=profile.request_timeout_seconds,
    )
    completion_latency_ms = round((time.monotonic() - started) * 1000, 3)
    if completion.status_code != 200:
        raise ModelEndpointProbeError("completion_request_failed")
    payload = _strict_json_object(completion.body)
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ModelEndpointProbeError("completion_response_invalid")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(message, dict):
        raise ModelEndpointProbeError("completion_response_invalid")
    content = message.get("content")
    content_present = isinstance(content, str) and bool(content.strip())
    reasoning_present, reasoning_field = _reasoning_summary(message)
    if not content_present and not reasoning_present:
        raise ModelEndpointProbeError("completion_response_empty")
    usage = payload.get("usage")
    return {
        "schema_version": 1,
        "kind": "authenticated-model-endpoint-probe",
        "state": "passed",
        "profile": profile.name,
        "model": profile.model,
        "endpoint_authority_sha256": endpoint.authority_sha256,
        "proxy_info_sha256": endpoint.proxy_info_sha256,
        "session_header": SESSION_HEADER.casefold(),
        "max_tokens": profile.max_tokens,
        "health": {
            "status_code": health.status_code,
            "latency_ms": health_latency_ms,
        },
        "completion": {
            "status_code": completion.status_code,
            "latency_ms": completion_latency_ms,
            "response_bytes": len(completion.body),
            "content_present": content_present,
            "reasoning_present": reasoning_present,
            "reasoning_field": reasoning_field,
            "finish_reason_present": isinstance(choice.get("finish_reason"), str),
            "usage_present": isinstance(usage, dict),
        },
    }


def _publish(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute() or path.name != "model-endpoint-probe.json":
        raise ModelEndpointProbeError("output_path_invalid")
    parent = path.parent.resolve(strict=True)
    metadata = parent.lstat()
    if (
        parent != path.parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ModelEndpointProbeError("output_parent_invalid")
    payload = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(PROFILES), default=DEFAULT_PROFILE)
    parser.add_argument("--expected-proxy-info-sha256")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    profile_name = DEFAULT_PROFILE
    try:
        arguments = _parser().parse_args(argv)
        profile_name = arguments.profile
        result = run_probe(
            PROFILES[profile_name],
            expected_proxy_info_sha256=arguments.expected_proxy_info_sha256,
        )
        if arguments.output is not None:
            _publish(arguments.output, result)
    except (EndpointBindingError, ModelEndpointProbeError, OSError):
        print(
            json.dumps(
                {
                    "kind": "authenticated-model-endpoint-probe",
                    "profile": profile_name,
                    "state": "failed",
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
