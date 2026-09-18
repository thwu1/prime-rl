#!/usr/bin/env python3
"""Probe a fresh Kimi worker generation and publish a schema-2 smoke bridge.

The artifact contains only hashes and aggregate validation facts.  Model
messages, tool arguments, responses, credentials, and endpoint URLs remain in
memory and are never printed or persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from deployment_endpoint import EndpointBindingError, load_deployment_endpoint
from deployment_proxy_policy import request_timeout_for_model, validate_proxy_policy_binding
from eval_run_identity import load_eval_run_identity
from inference_route_generation import canonical_backend_identifier, validate_route_generation
from smoke_qualification import (
    Artifact,
    artifact_from_record,
    build_bridge_payload,
    canonical_json,
    load_artifact,
    load_json_artifact,
    sha256_bytes,
    validate_readiness,
    validate_smoke_qualification,
    validate_v1_smoke,
)

BACKEND_HEADER = "x-litellm-model-api-base"
SESSION_HEADERS = ("X-LiteLLM-Session-ID", "X-Session-ID")
SESSION_RE = re.compile(r"[A-Za-z0-9._:-]{1,240}")
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TOOL_NAME = "generation_bridge_ping"
PROBE_MAX_TOKENS = 256


class GenerationBridgeError(ValueError):
    """The cross-generation smoke bridge cannot safely be published."""


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    """No-redirect HTTP transport kept injectable for deterministic tests."""

    def __init__(self) -> None:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:
                return None

        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
        )

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                return HttpResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response_body,
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                status_code=error.code,
                headers=dict(error.headers.items()) if error.headers else {},
                body=error.read(MAX_RESPONSE_BYTES + 1),
            )


@dataclass(frozen=True)
class ProbeTarget:
    backend_sha256: str
    session_id: str = field(repr=False)


@dataclass(frozen=True)
class ProbeRuntime:
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    endpoint_authority_sha256: str


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise GenerationBridgeError(f"{label}_duplicate_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise GenerationBridgeError(f"{label}_non_finite")

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    except GenerationBridgeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise GenerationBridgeError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise GenerationBridgeError(f"{label}_invalid")
    return value


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    matches = [str(value).strip() for key, value in headers.items() if key.casefold() == expected]
    if len(matches) != 1 or not matches[0]:
        return None
    return matches[0]


def _reasoning(message: Mapping[str, Any]) -> str:
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            parts = [
                item.get("text", "") for item in value if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            joined = "".join(parts)
            if joined.strip():
                return joined
    return ""


def _message(
    payload: dict[str, Any],
    *,
    model: str,
    expected_finish_reason: str,
) -> dict[str, Any]:
    if payload.get("model") != model or payload.get("error") is not None:
        raise GenerationBridgeError("generation_probe_response_model_invalid")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise GenerationBridgeError("generation_probe_choice_invalid")
    choice = choices[0]
    if (
        not isinstance(choice, dict)
        or choice.get("finish_reason") != expected_finish_reason
        or not isinstance(choice.get("message"), dict)
    ):
        raise GenerationBridgeError("generation_probe_message_invalid")
    message = choice["message"]
    if not _reasoning(message):
        raise GenerationBridgeError("generation_probe_reasoning_empty")
    return message


def _tool_payload(model: str, nonce: str) -> tuple[dict[str, Any], str]:
    marker = f"GENERATION_BRIDGE_OK_{nonce[:16]}"
    return (
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Call the supplied tool exactly once. After its result, return only the result marker."
                    ),
                },
                {
                    "role": "user",
                    "content": "Use the generation bridge tool with the supplied nonce.",
                },
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "description": "Return a generation-local probe nonce.",
                        "parameters": {
                            "type": "object",
                            "properties": {"nonce": {"type": "string", "const": nonce}},
                            "required": ["nonce"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            "tool_choice": "required",
            "reasoning_effort": "max",
            "chat_template_kwargs": {
                "enable_thinking": True,
                "preserve_thinking": True,
            },
            "temperature": 0,
            "max_tokens": PROBE_MAX_TOKENS,
        },
        marker,
    )


def _request(
    transport: HttpTransport,
    runtime: ProbeRuntime,
    *,
    session_id: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[HttpResponse, bytes, str]:
    request_body = canonical_json(payload)
    headers = {
        "Authorization": f"Bearer {runtime.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        SESSION_HEADERS[0]: session_id,
        SESSION_HEADERS[1]: session_id,
    }
    try:
        response = transport.request(
            f"{runtime.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            body=request_body,
            timeout=timeout,
        )
    except Exception as error:
        raise GenerationBridgeError(f"generation_probe_transport:{type(error).__name__}") from error
    if response.status_code != 200 or len(response.body) > MAX_RESPONSE_BYTES:
        raise GenerationBridgeError("generation_probe_http_invalid")
    raw_backend = _header(response.headers, BACKEND_HEADER)
    if raw_backend is None:
        raise GenerationBridgeError("generation_probe_backend_missing")
    try:
        backend = canonical_backend_identifier(raw_backend)
    except ValueError as error:
        raise GenerationBridgeError("generation_probe_backend_invalid") from error
    retries = _header(response.headers, "x-litellm-attempted-retries")
    if retries not in (None, "0"):
        raise GenerationBridgeError("generation_probe_upstream_retry")
    return response, request_body, backend


def _probe_one_backend(
    transport: HttpTransport,
    runtime: ProbeRuntime,
    target: ProbeTarget,
    *,
    model: str,
    timeout: float,
    nonce: str,
) -> list[dict[str, Any]]:
    initial_payload, marker = _tool_payload(model, nonce)
    first, first_request, backend = _request(
        transport,
        runtime,
        session_id=target.session_id,
        payload=initial_payload,
        timeout=timeout,
    )
    if backend != target.backend_sha256:
        raise GenerationBridgeError("generation_probe_backend_changed")
    first_payload = _strict_object(first.body, label="generation_probe_tool_response")
    assistant = _message(
        first_payload,
        model=model,
        expected_finish_reason="tool_calls",
    )
    tool_calls = assistant.get("tool_calls")
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        raise GenerationBridgeError("generation_probe_tool_call_invalid")
    tool_call = tool_calls[0]
    function = tool_call.get("function") if isinstance(tool_call, dict) else None
    if (
        not isinstance(tool_call, dict)
        or tool_call.get("type") != "function"
        or not isinstance(tool_call.get("id"), str)
        or not tool_call["id"].strip()
        or not isinstance(function, dict)
        or function.get("name") != TOOL_NAME
        or not isinstance(function.get("arguments"), str)
    ):
        raise GenerationBridgeError("generation_probe_tool_call_invalid")
    arguments = _strict_object(
        function["arguments"].encode("utf-8"),
        label="generation_probe_tool_arguments",
    )
    if arguments != {"nonce": nonce}:
        raise GenerationBridgeError("generation_probe_tool_arguments_invalid")

    followup = dict(initial_payload)
    followup["tool_choice"] = "none"
    followup["messages"] = [
        *initial_payload["messages"],
        assistant,
        {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": json.dumps(
                {"ok": True, "nonce": nonce, "marker": marker},
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]
    second, second_request, second_backend = _request(
        transport,
        runtime,
        session_id=target.session_id,
        payload=followup,
        timeout=timeout,
    )
    if second_backend != target.backend_sha256:
        raise GenerationBridgeError("generation_probe_backend_changed")
    second_payload = _strict_object(second.body, label="generation_probe_tool_result_response")
    final_message = _message(
        second_payload,
        model=model,
        expected_finish_reason="stop",
    )
    if final_message.get("tool_calls") not in (None, []):
        raise GenerationBridgeError("generation_probe_tool_round_trip_invalid")
    content = final_message.get("content")
    if not isinstance(content, str) or content.strip() != marker:
        raise GenerationBridgeError("generation_probe_tool_round_trip_invalid")
    return [
        {
            "phase": "tool_call",
            "backend_sha256": target.backend_sha256,
            "request_sha256": sha256_bytes(first_request),
            "response_sha256": sha256_bytes(first.body),
            "status_code": first.status_code,
            "response_model": first_payload["model"],
            "reasoning_nonempty": True,
            "tool_call_valid": True,
        },
        {
            "phase": "tool_result",
            "backend_sha256": target.backend_sha256,
            "request_sha256": sha256_bytes(second_request),
            "response_sha256": sha256_bytes(second.body),
            "status_code": second.status_code,
            "response_model": second_payload["model"],
            "reasoning_nonempty": True,
            "tool_call_valid": False,
        },
    ]


def _probe_targets(readiness_payload: dict[str, Any], generation: dict[str, Any]) -> list[ProbeTarget]:
    probe = readiness_payload.get("probe")
    routes = probe.get("routes") if isinstance(probe, dict) else None
    expected = sorted(route["backend_sha256"] for route in generation["routes"])
    mapping: dict[str, str] = {}
    if not isinstance(routes, list):
        raise GenerationBridgeError("readiness_probe_sessions_missing")
    for route in routes:
        backend = route.get("backend") if isinstance(route, dict) else None
        session_id = route.get("representative_session_id") if isinstance(route, dict) else None
        if (
            not isinstance(backend, str)
            or backend not in expected
            or backend in mapping
            or not isinstance(session_id, str)
            or SESSION_RE.fullmatch(session_id) is None
        ):
            raise GenerationBridgeError("readiness_probe_sessions_invalid")
        mapping[backend] = session_id
    if sorted(mapping) != expected:
        raise GenerationBridgeError("readiness_probe_sessions_incomplete")
    return [ProbeTarget(backend, mapping[backend]) for backend in expected]


def run_generation_probe(
    runtime: ProbeRuntime,
    *,
    model: str,
    generation: dict[str, Any],
    readiness_payload: dict[str, Any],
    timeout: float = 300.0,
    transport: HttpTransport | None = None,
    nonce_factory: Any = None,
) -> dict[str, Any]:
    """Exercise reasoning and a real tool round trip on every target backend."""

    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not 1 <= timeout <= 900
        or model != "Kimi-K3"
    ):
        raise GenerationBridgeError("generation_probe_config_invalid")
    generation = validate_route_generation(generation)
    targets = _probe_targets(readiness_payload, generation)
    transport = transport or UrllibTransport()
    nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = {
            executor.submit(
                _probe_one_backend,
                transport,
                runtime,
                target,
                model=model,
                timeout=float(timeout),
                nonce=nonce_factory(),
            ): target.backend_sha256
            for target in targets
        }
        try:
            for future in as_completed(futures):
                records.extend(future.result())
        except Exception:
            for future in futures:
                future.cancel()
            raise
    records.sort(key=lambda item: (item["backend_sha256"], item["phase"]))
    expected_backends = [target.backend_sha256 for target in targets]
    body = {
        "schema_version": 1,
        "state": "passed",
        "ok": True,
        "endpoint_authority_sha256": runtime.endpoint_authority_sha256,
        "serving_route_generation_sha256": sha256_bytes(canonical_json(generation)),
        "request_contract": {
            "provider_route": "/chat/completions",
            "model": model,
            "reasoning_effort": "max",
            "chat_template_kwargs": {
                "enable_thinking": True,
                "preserve_thinking": True,
            },
            "tool_name": TOOL_NAME,
            "tool_choice": {"tool_call": "required", "tool_result": "none"},
            "temperature": 0,
            "max_tokens": PROBE_MAX_TOKENS,
        },
        "coverage": {
            "expected_routes": len(expected_backends),
            "tested_routes": len(expected_backends),
            "backends": expected_backends,
            "round_trips_per_backend": 1,
        },
        "requests": records,
    }
    return {**body, "probe_sha256": sha256_bytes(canonical_json(body))}


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise GenerationBridgeError("bridge_output_invalid")
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise GenerationBridgeError("bridge_output_unreadable") from error
        if existing == raw:
            return
        raise GenerationBridgeError("bridge_output_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fchmod(handle.fileno(), 0o444)
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise GenerationBridgeError("bridge_output_already_exists") from error
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _source_context(
    source_smoke: Artifact,
    *,
    target_spec: Artifact,
    model: str,
) -> tuple[
    Artifact,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    payload = load_json_artifact(source_smoke, label="source_smoke_checkpoint")
    artifacts = payload.get("artifacts")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise GenerationBridgeError("source_smoke_must_be_schema_v1")
    if not isinstance(artifacts, dict):
        raise GenerationBridgeError("source_smoke_artifacts_invalid")
    identity_artifact = artifact_from_record(
        artifacts.get("eval_run_identity"),
        label="source_eval_run_identity",
        load_bytes=True,
    )
    # Duplicate-key rejection precedes the authoritative identity loader.
    load_json_artifact(identity_artifact, label="source_eval_run_identity")
    envelope = load_eval_run_identity(identity_artifact.path, verify_references=True)
    identity = envelope["identity"]
    deployment = identity.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("spec") != target_spec.record:
        raise GenerationBridgeError("source_deployment_spec_mismatch")
    source_readiness = artifact_from_record(
        deployment.get("readiness_checkpoint"),
        label="source_readiness_checkpoint",
        load_bytes=True,
    )
    try:
        endpoint = load_deployment_endpoint(
            Path(deployment["endpoint"]["proxy_info"]["path"]),
            deployment_id=deployment["id"],
            expected_model=model,
            deployment_spec=target_spec.path,
            expected_proxy_info_sha256=deployment["endpoint"]["proxy_info"]["sha256"],
        ).binding
        generation = validate_route_generation(deployment["serving_route_generation"])
        proxy_policy = validate_proxy_policy_binding(
            deployment["proxy_policy"],
            expected_request_timeout=request_timeout_for_model(model),
        )
    except (KeyError, TypeError, ValueError, EndpointBindingError) as error:
        raise GenerationBridgeError("source_smoke_context_invalid") from error
    ready_generation, ready_policy = validate_readiness(
        source_readiness,
        deployment_id=deployment["id"],
        deployment_spec=target_spec,
        endpoint=endpoint,
        model=model,
    )
    if ready_generation != generation or ready_policy != proxy_policy:
        raise GenerationBridgeError("source_smoke_context_mismatch")
    _, evaluator_evidence = validate_v1_smoke(
        source_smoke,
        deployment_id=deployment["id"],
        deployment_spec=target_spec,
        readiness=source_readiness,
        endpoint=endpoint,
        generation=generation,
        proxy_policy=proxy_policy,
        model=model,
    )
    return source_readiness, endpoint, generation, proxy_policy, evaluator_evidence


def create_bridge(
    *,
    output_path: Path,
    source_smoke_path: Path,
    source_smoke_sha256: str,
    deployment_id: str,
    deployment_spec_path: Path,
    deployment_spec_sha256: str,
    target_readiness_path: Path,
    target_readiness_sha256: str,
    proxy_info_path: Path,
    proxy_info_sha256: str,
    model: str,
    timeout: float = 300.0,
    transport: HttpTransport | None = None,
    nonce_factory: Any = None,
) -> dict[str, Any]:
    """Validate, probe, and atomically publish one generation bridge."""

    if model != "Kimi-K3":
        raise GenerationBridgeError("bridge_model_invalid")
    if not output_path.is_absolute() or str(output_path) != str(output_path.resolve(strict=False)):
        raise GenerationBridgeError("bridge_output_path_invalid")
    spec = load_artifact(
        deployment_spec_path,
        deployment_spec_sha256,
        label="deployment_spec",
    )
    target_readiness = load_artifact(
        target_readiness_path,
        target_readiness_sha256,
        label="target_readiness_checkpoint",
        load_bytes=True,
    )
    proxy_info = load_artifact(
        proxy_info_path,
        proxy_info_sha256,
        label="proxy_info",
    )
    source_smoke = load_artifact(
        source_smoke_path,
        source_smoke_sha256,
        label="source_smoke_checkpoint",
        load_bytes=True,
    )
    try:
        output_path.resolve(strict=False).relative_to(source_smoke.path.parent)
    except ValueError:
        pass
    else:
        raise GenerationBridgeError("bridge_must_not_modify_source_smoke_run")
    try:
        endpoint_info = load_deployment_endpoint(
            proxy_info.path,
            deployment_id=deployment_id,
            expected_model=model,
            deployment_spec=spec.path,
            expected_proxy_info_sha256=proxy_info.sha256,
        )
    except EndpointBindingError as error:
        raise GenerationBridgeError("target_endpoint_invalid") from error
    target_endpoint = endpoint_info.binding
    target_generation, target_policy = validate_readiness(
        target_readiness,
        deployment_id=deployment_id,
        deployment_spec=spec,
        endpoint=target_endpoint,
        model=model,
    )
    (
        source_readiness,
        source_endpoint,
        source_generation,
        source_policy,
        evaluator_evidence,
    ) = _source_context(source_smoke, target_spec=spec, model=model)
    if (
        source_endpoint != target_endpoint
        or source_endpoint["proxy_info"] != target_endpoint["proxy_info"]
        or source_policy != target_policy
        or source_generation.get("coordinator") != target_generation.get("coordinator")
        or source_generation.get("proxy") != target_generation.get("proxy")
        or source_generation == target_generation
        or len(source_generation.get("routes", [])) != len(target_generation.get("routes", []))
        or source_generation.get("routes") == target_generation.get("routes")
    ):
        raise GenerationBridgeError("not_a_worker_only_generation_rotation")

    readiness_payload = load_json_artifact(target_readiness, label="target_readiness_checkpoint")
    runtime = ProbeRuntime(
        base_url=endpoint_info.client_base_url,
        api_key=endpoint_info.api_key,
        endpoint_authority_sha256=endpoint_info.authority_sha256,
    )
    probe = run_generation_probe(
        runtime,
        model=model,
        generation=target_generation,
        readiness_payload=readiness_payload,
        timeout=timeout,
        transport=transport,
        nonce_factory=nonce_factory,
    )

    # Close the time-of-check/time-of-use window before publishing.
    target_readiness = load_artifact(
        target_readiness.path,
        target_readiness.sha256,
        label="target_readiness_checkpoint",
        load_bytes=True,
    )
    proxy_info = load_artifact(
        proxy_info.path,
        proxy_info.sha256,
        label="proxy_info",
    )
    source_smoke = load_artifact(
        source_smoke.path,
        source_smoke.sha256,
        label="source_smoke_checkpoint",
        load_bytes=True,
    )
    reloaded_endpoint = load_deployment_endpoint(
        proxy_info.path,
        deployment_id=deployment_id,
        expected_model=model,
        deployment_spec=spec.path,
        expected_proxy_info_sha256=proxy_info.sha256,
    ).binding
    reloaded_generation, reloaded_policy = validate_readiness(
        target_readiness,
        deployment_id=deployment_id,
        deployment_spec=spec,
        endpoint=reloaded_endpoint,
        model=model,
    )
    if (
        reloaded_endpoint != target_endpoint
        or reloaded_generation != target_generation
        or reloaded_policy != target_policy
    ):
        raise GenerationBridgeError("target_generation_changed_during_probe")

    bridge = build_bridge_payload(
        deployment_id=deployment_id,
        deployment_spec=spec,
        model=model,
        proxy_policy=target_policy,
        source_smoke=source_smoke,
        source_readiness=source_readiness,
        source_endpoint=source_endpoint,
        source_generation=source_generation,
        target_readiness=target_readiness,
        target_endpoint=target_endpoint,
        target_generation=target_generation,
        evaluator_evidence=evaluator_evidence,
        probe=probe,
    )
    _write_once(output_path, bridge)
    bridge_artifact = load_artifact(
        output_path.resolve(strict=True),
        hashlib.sha256(output_path.read_bytes()).hexdigest(),
        label="smoke_generation_bridge",
        load_bytes=True,
    )
    validate_smoke_qualification(
        bridge_artifact.path,
        bridge_artifact.sha256,
        deployment_id=deployment_id,
        deployment_spec_path=spec.path,
        deployment_spec_sha256=spec.sha256,
        readiness_path=target_readiness.path,
        readiness_sha256=target_readiness.sha256,
        proxy_info_path=proxy_info.path,
        proxy_info_sha256=proxy_info.sha256,
        model=model,
    )
    if stat.S_IMODE(bridge_artifact.path.stat().st_mode) != 0o444:
        raise GenerationBridgeError("bridge_mode_invalid")
    return bridge


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-smoke-checkpoint", type=Path, required=True)
    parser.add_argument("--source-smoke-checkpoint-sha256", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--deployment-spec", type=Path, required=True)
    parser.add_argument("--deployment-spec-sha256", required=True)
    parser.add_argument("--target-readiness-checkpoint", type=Path, required=True)
    parser.add_argument("--target-readiness-checkpoint-sha256", required=True)
    parser.add_argument("--proxy-info", type=Path, required=True)
    parser.add_argument("--proxy-info-sha256", required=True)
    parser.add_argument("--model", default="Kimi-K3")
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        bridge = create_bridge(
            output_path=args.output,
            source_smoke_path=args.source_smoke_checkpoint,
            source_smoke_sha256=args.source_smoke_checkpoint_sha256,
            deployment_id=args.deployment_id,
            deployment_spec_path=args.deployment_spec,
            deployment_spec_sha256=args.deployment_spec_sha256,
            target_readiness_path=args.target_readiness_checkpoint,
            target_readiness_sha256=args.target_readiness_checkpoint_sha256,
            proxy_info_path=args.proxy_info,
            proxy_info_sha256=args.proxy_info_sha256,
            model=args.model,
            timeout=args.timeout,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"smoke_generation_bridge_error:{error}", file=sys.stderr)
        return 2
    output = args.output.resolve(strict=True)
    print(
        json.dumps(
            {
                "ok": True,
                "bridge": str(output),
                "bridge_file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "smoke_qualification_sha256": bridge["smoke_qualification_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
