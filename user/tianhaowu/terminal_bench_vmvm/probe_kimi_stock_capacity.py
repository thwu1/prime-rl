#!/usr/bin/env python3
"""Probe the pinned single-endpoint stock Kimi deployment without retaining model I/O."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.client
import json
import math
import os
import re
import secrets
import stat
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

KIND = "kimi-stock-capacity-probe"
SCHEMA_VERSION = 1
EXPECTED_DEPLOYMENT_ID = "tianhaowu-kimi-k3-stock-eval-20260927"
EXPECTED_MODEL = "Kimi-K3"
EXPECTED_BACKEND_MODEL = "openai/Kimi-K3"
EXPECTED_SPEC_SHA256 = "3b9d7b9e72767b9f65894ea024a08713ed10330c7d55c70cd99b2717056a9b39"
EXPECTED_PROXY_CONFIG_SHA256 = "7894cd7205d0197620fa77edc747377e15c4e311769a0060be760659f5b29595"
DEFAULT_DEPLOYMENT_ROOT = Path("/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-kimi-k3-stock-eval-20260927")
ALLOWED_CONCURRENCY = (24, 64)
DEFAULT_CONCURRENCY = 24
DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0
DEFAULT_METRICS_TIMEOUT_SECONDS = 15.0
IN_FLIGHT_METRICS_INTERVAL_SECONDS = 1.0
BARRIER_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_TOKENS = 256
TOOL_NAME = "report_stock_capacity_probe"
TOOL_MARKER = "KIMI_STOCK_CAPACITY_PROBE_OK_V1"
SESSION_HEADER = "X-Session-ID"
HOST_RE = re.compile(r"[A-Za-z0-9.-]+\Z")
ENDPOINT_FILE_RE = re.compile(r"[1-9][0-9]*\.json\Z")
STARTED_AT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\r\n]+Z\Z")
DEPLOYMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_METRICS = {
    "vllm:num_requests_running": "running",
    "vllm:num_requests_waiting": "waiting",
    "vllm:num_preemptions_total": "preemptions",
    "vllm:generation_tokens_total": "generation_tokens",
    "vllm:request_success_total": "successful_requests",
}
KV_METRICS = ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc")


class KimiStockCapacityProbeError(RuntimeError):
    """A stable probe failure which contains no endpoint or response detail."""


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes = field(repr=False)


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class DirectHttpTransport:
    """One-endpoint transport which cannot consult ambient HTTP proxies."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        if method not in {"GET", "POST"} or not path.startswith("/") or "?" in path or "#" in path:
            raise KimiStockCapacityProbeError("request_target_invalid")
        connection = http.client.HTTPConnection(self._host, self._port, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers=dict(headers))
            response = connection.getresponse()
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            return HttpResponse(status_code=response.status, body=payload)
        finally:
            connection.close()


@dataclass(frozen=True)
class ArtifactSnapshot:
    path: Path
    body: bytes = field(repr=False)
    sha256: str
    signature: tuple[int, int, int, int]

    @property
    def receipt(self) -> dict[str, str]:
        return {"path": str(self.path), "sha256": self.sha256}


@dataclass(frozen=True)
class Endpoint:
    host: str = field(repr=False)
    port: int
    started_at: str
    job_id: str

    @property
    def client_base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"


@dataclass(frozen=True)
class DeploymentBinding:
    root: Path
    deployment_id: str
    spec: ArtifactSnapshot
    proxy_config: ArtifactSnapshot
    endpoint_file: ArtifactSnapshot
    endpoint: Endpoint
    endpoint_authority_sha256: str

    @property
    def fingerprints(self) -> tuple[tuple[str, str, tuple[int, int, int, int]], ...]:
        return tuple(
            (str(item.path), item.sha256, item.signature) for item in (self.spec, self.proxy_config, self.endpoint_file)
        )


@dataclass(frozen=True)
class CompletionObservation:
    outcome: str
    latency_ms: float
    status_code: int | None = None
    response_sha256: str | None = None
    model_match: bool = False
    reasoning_field: str | None = None
    tool_calls: int = 0


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _request_payload() -> dict[str, Any]:
    return {
        "chat_template_kwargs": {
            "enable_thinking": True,
            "preserve_thinking": True,
        },
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "content": (
                    "Think carefully, then call the supplied harmless reporting tool exactly once. "
                    "Do not perform any external action."
                ),
                "role": "system",
            },
            {
                "content": "Report that the fixed stock-capacity probe request was received.",
                "role": "user",
            },
        ],
        "model": EXPECTED_MODEL,
        "parallel_tool_calls": False,
        "reasoning_effort": "max",
        "stream": False,
        "temperature": 0,
        "tool_choice": "required",
        "tools": [
            {
                "function": {
                    "description": "Report completion of a harmless fixed capacity-probe request.",
                    "name": TOOL_NAME,
                    "parameters": {
                        "additionalProperties": False,
                        "properties": {
                            "marker": {
                                "const": TOOL_MARKER,
                                "type": "string",
                            }
                        },
                        "required": ["marker"],
                        "type": "object",
                    },
                },
                "type": "function",
            }
        ],
    }


REQUEST_BODY = _canonical_json(_request_payload())
REQUEST_SHA256 = _sha256(REQUEST_BODY)


def _read_regular(path: Path, *, maximum_bytes: int = MAX_SOURCE_BYTES) -> ArtifactSnapshot:
    if not path.is_absolute():
        raise KimiStockCapacityProbeError("source_path_invalid")
    try:
        resolved = path.resolve(strict=True)
        visible_before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, RuntimeError) as error:
        raise KimiStockCapacityProbeError("source_unreadable") from error
    try:
        opened_before = os.fstat(descriptor)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > maximum_bytes:
                raise KimiStockCapacityProbeError("source_too_large")
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        visible_after = path.lstat()
    except OSError as error:
        raise KimiStockCapacityProbeError("source_changed") from error
    signature = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if (
        resolved != path
        or not stat.S_ISREG(visible_before.st_mode)
        or visible_before.st_nlink != 1
        or signature(visible_before) != signature(opened_before)
        or signature(opened_before) != signature(opened_after)
        or signature(opened_after) != signature(visible_after)
        or len(body) != opened_after.st_size
    ):
        raise KimiStockCapacityProbeError("source_changed")
    raw = bytes(body)
    return ArtifactSnapshot(
        path=resolved,
        body=raw,
        sha256=_sha256(raw),
        signature=signature(opened_after),
    )


def _strict_json_object(body: bytes, *, label: str) -> dict[str, Any]:
    if len(body) > MAX_RESPONSE_BYTES:
        raise KimiStockCapacityProbeError(f"{label}_too_large")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise KimiStockCapacityProbeError(f"{label}_invalid")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise KimiStockCapacityProbeError(f"{label}_invalid")

    try:
        value = json.loads(body, object_pairs_hook=unique, parse_constant=reject_constant)
    except KimiStockCapacityProbeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise KimiStockCapacityProbeError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise KimiStockCapacityProbeError(f"{label}_invalid")
    return value


def _endpoint_from_artifact(artifact: ArtifactSnapshot) -> Endpoint:
    value = _strict_json_object(artifact.body, label="endpoint_file")
    if set(value) != {"host", "port", "started_at"}:
        raise KimiStockCapacityProbeError("endpoint_file_invalid")
    host = value["host"]
    port = value["port"]
    started_at = value["started_at"]
    if (
        not isinstance(host, str)
        or HOST_RE.fullmatch(host) is None
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65_535
        or not isinstance(started_at, str)
        or STARTED_AT_RE.fullmatch(started_at) is None
        or ENDPOINT_FILE_RE.fullmatch(artifact.path.name) is None
    ):
        raise KimiStockCapacityProbeError("endpoint_file_invalid")
    return Endpoint(
        host=host,
        port=port,
        started_at=started_at,
        job_id=artifact.path.stem,
    )


def _load_yaml_object(body: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(body.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise KimiStockCapacityProbeError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise KimiStockCapacityProbeError(f"{label}_invalid")
    return value


def _validate_spec(artifact: ArtifactSnapshot, expected_sha256: str) -> None:
    if artifact.sha256 != expected_sha256:
        raise KimiStockCapacityProbeError("deployment_spec_digest_mismatch")
    document = _load_yaml_object(artifact.body, label="deployment_spec")
    spec = document.get("spec")
    if not isinstance(spec, dict) or spec.get("served_model_name") != EXPECTED_MODEL or spec.get("num_endpoints") != 1:
        raise KimiStockCapacityProbeError("deployment_spec_invalid")


def _validate_proxy_config(
    artifact: ArtifactSnapshot,
    endpoint: Endpoint,
    expected_sha256: str,
    *,
    expected_sticky_ttl_seconds: int | None,
) -> None:
    if artifact.sha256 != expected_sha256:
        raise KimiStockCapacityProbeError("proxy_config_digest_mismatch")
    document = _load_yaml_object(artifact.body, label="proxy_config")
    models = document.get("model_list")
    if not isinstance(models, list) or len(models) != 1 or not isinstance(models[0], dict):
        raise KimiStockCapacityProbeError("proxy_config_invalid")
    entry = models[0]
    params = entry.get("litellm_params")
    router = document.get("router_settings")
    if (
        entry.get("model_name") != EXPECTED_MODEL
        or not isinstance(params, dict)
        or params.get("model") != EXPECTED_BACKEND_MODEL
        or params.get("api_key") != "EMPTY"
        or params.get("api_base") != endpoint.client_base_url
    ):
        raise KimiStockCapacityProbeError("proxy_config_invalid")
    if expected_sticky_ttl_seconds is not None and (
        not isinstance(router, dict)
        or router.get("enable_pre_call_checks") is not True
        or router.get("optional_pre_call_checks") != ["session_affinity"]
        or router.get("deployment_affinity_ttl_seconds") != expected_sticky_ttl_seconds
    ):
        raise KimiStockCapacityProbeError("sticky_routing_invalid")


def _load_binding(
    deployment_root: Path,
    *,
    expected_deployment_id: str | None = None,
    expected_spec_sha256: str | None = None,
    expected_proxy_config_sha256: str | None = None,
    expected_sticky_ttl_seconds: int | None = None,
) -> DeploymentBinding:
    if expected_deployment_id is None:
        expected_deployment_id = EXPECTED_DEPLOYMENT_ID
    if expected_spec_sha256 is None:
        expected_spec_sha256 = EXPECTED_SPEC_SHA256
    if expected_proxy_config_sha256 is None:
        expected_proxy_config_sha256 = EXPECTED_PROXY_CONFIG_SHA256
    if (
        not deployment_root.is_absolute()
        or DEPLOYMENT_ID_RE.fullmatch(expected_deployment_id) is None
        or SHA256_RE.fullmatch(expected_spec_sha256) is None
        or SHA256_RE.fullmatch(expected_proxy_config_sha256) is None
        or (
            expected_sticky_ttl_seconds is not None
            and (isinstance(expected_sticky_ttl_seconds, bool) or expected_sticky_ttl_seconds < 1)
        )
    ):
        raise KimiStockCapacityProbeError("deployment_root_invalid")
    try:
        root = deployment_root.resolve(strict=True)
        root_metadata = deployment_root.lstat()
    except (OSError, RuntimeError) as error:
        raise KimiStockCapacityProbeError("deployment_root_invalid") from error
    if (
        root != deployment_root
        or root.parent != DEFAULT_DEPLOYMENT_ROOT.parent
        or deployment_root.name != expected_deployment_id
        or not stat.S_ISDIR(root_metadata.st_mode)
        or deployment_root.is_symlink()
    ):
        raise KimiStockCapacityProbeError("deployment_root_invalid")
    endpoints = root / "endpoints"
    try:
        endpoint_directory_metadata = endpoints.lstat()
        entries = list(endpoints.iterdir())
    except OSError as error:
        raise KimiStockCapacityProbeError("endpoint_membership_invalid") from error
    if (
        endpoints.is_symlink()
        or not stat.S_ISDIR(endpoint_directory_metadata.st_mode)
        or len(entries) != 1
        or ENDPOINT_FILE_RE.fullmatch(entries[0].name) is None
        or not entries[0].is_file()
        or entries[0].is_symlink()
    ):
        raise KimiStockCapacityProbeError("endpoint_membership_invalid")
    spec = _read_regular(root / "spec.yaml")
    proxy_config = _read_regular(root / "proxy_litellm_config.yaml")
    endpoint_file = _read_regular(entries[0], maximum_bytes=16 * 1024)
    endpoint = _endpoint_from_artifact(endpoint_file)
    _validate_spec(spec, expected_spec_sha256)
    _validate_proxy_config(
        proxy_config,
        endpoint,
        expected_proxy_config_sha256,
        expected_sticky_ttl_seconds=expected_sticky_ttl_seconds,
    )
    authority = _sha256(endpoint.client_base_url.encode("utf-8"))
    return DeploymentBinding(
        root=root,
        deployment_id=expected_deployment_id,
        spec=spec,
        proxy_config=proxy_config,
        endpoint_file=endpoint_file,
        endpoint=endpoint,
        endpoint_authority_sha256=authority,
    )


def _parse_metrics(body: bytes) -> dict[str, int | float]:
    if len(body) > MAX_RESPONSE_BYTES:
        raise KimiStockCapacityProbeError("metrics_response_invalid")
    wanted = {*REQUIRED_METRICS, *KV_METRICS}
    values: dict[str, float] = {}
    try:
        lines = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise KimiStockCapacityProbeError("metrics_response_invalid") from error
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.rsplit(None, 1)
        if len(fields) != 2:
            continue
        name = fields[0].split("{", 1)[0]
        if name not in wanted:
            continue
        try:
            value = float(fields[1])
        except ValueError as error:
            raise KimiStockCapacityProbeError("metrics_response_invalid") from error
        if not math.isfinite(value) or value < 0:
            raise KimiStockCapacityProbeError("metrics_response_invalid")
        values[name] = values.get(name, 0.0) + value
    if any(name not in values for name in REQUIRED_METRICS):
        raise KimiStockCapacityProbeError("metrics_response_invalid")
    if any(values[name] != int(values[name]) for name in REQUIRED_METRICS):
        raise KimiStockCapacityProbeError("metrics_response_invalid")
    cache_values = [values[name] for name in KV_METRICS if name in values]
    if not cache_values:
        raise KimiStockCapacityProbeError("metrics_response_invalid")
    return {output: int(values[name]) for name, output in REQUIRED_METRICS.items()} | {
        "kv_cache_usage": max(cache_values)
    }


def _safe_metrics(
    transport: HttpTransport,
    *,
    timeout: float,
) -> tuple[dict[str, int | float] | None, int, int]:
    try:
        response = transport.request(
            "GET",
            "/metrics",
            headers={"Accept": "text/plain"},
            body=None,
            timeout=timeout,
        )
    except Exception:
        return None, 0, 1
    if response.status_code != 200:
        return None, 1, 0
    try:
        return _parse_metrics(response.body), 0, 0
    except KimiStockCapacityProbeError:
        return None, 1, 0


def _safe_model_identity(
    transport: HttpTransport,
    *,
    timeout: float,
) -> tuple[bool, int, int]:
    try:
        response = transport.request(
            "GET",
            "/v1/models",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer EMPTY",
            },
            body=None,
            timeout=timeout,
        )
    except Exception:
        return False, 0, 1
    if response.status_code != 200:
        return False, 1, 0
    try:
        payload = _strict_json_object(response.body, label="models_response")
    except KimiStockCapacityProbeError:
        return False, 1, 0
    models = payload.get("data")
    if (
        not isinstance(models, list)
        or len(models) != 1
        or not isinstance(models[0], dict)
        or models[0].get("id") != EXPECTED_MODEL
    ):
        return False, 1, 0
    return True, 0, 0


def _reasoning_field(message: Mapping[str, Any]) -> str | None:
    for name in ("reasoning_content", "reasoning"):
        value = message.get(name)
        if isinstance(value, str) and value.strip():
            return name
        if isinstance(value, list):
            parts = [
                item.get("text", "") for item in value if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            if "".join(parts).strip():
                return name
    return None


def _completion_semantics(body: bytes) -> tuple[bool, bool, str | None, int]:
    payload = _strict_json_object(body, label="completion_response")
    model_match = payload.get("model") == EXPECTED_MODEL
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return False, model_match, None, 0
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        return False, model_match, None, 0
    reasoning_field = _reasoning_field(message)
    tool_calls = message.get("tool_calls")
    tool_call_count = len(tool_calls) if isinstance(tool_calls, list) else 0
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        return False, model_match, reasoning_field, tool_call_count
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
        return False, model_match, reasoning_field, tool_call_count
    try:
        arguments = _strict_json_object(
            function["arguments"].encode("utf-8"),
            label="completion_tool_arguments",
        )
    except KimiStockCapacityProbeError:
        return False, model_match, reasoning_field, tool_call_count
    valid = (
        model_match
        and payload.get("error") is None
        and choice.get("finish_reason") == "tool_calls"
        and reasoning_field is not None
        and arguments == {"marker": TOOL_MARKER}
    )
    return valid, model_match, reasoning_field, tool_call_count


def _completion_request(
    transport: HttpTransport,
    *,
    index: int,
    timeout: float,
    monotonic: Any,
) -> CompletionObservation:
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer EMPTY",
        "Content-Type": "application/json",
        SESSION_HEADER: f"kimi-stock-capacity-{index:03d}",
    }
    started = monotonic()
    try:
        response = transport.request(
            "POST",
            "/v1/chat/completions",
            headers=headers,
            body=REQUEST_BODY,
            timeout=timeout,
        )
    except Exception:
        return CompletionObservation(
            outcome="transport_error",
            latency_ms=max(0.0, round((monotonic() - started) * 1000, 3)),
        )
    latency_ms = max(0.0, round((monotonic() - started) * 1000, 3))
    if len(response.body) > MAX_RESPONSE_BYTES:
        return CompletionObservation(
            outcome="response_error",
            latency_ms=latency_ms,
            status_code=response.status_code,
        )
    response_sha256 = _sha256(response.body)
    if response.status_code != 200:
        return CompletionObservation(
            outcome="response_error",
            latency_ms=latency_ms,
            status_code=response.status_code,
            response_sha256=response_sha256,
        )
    try:
        valid, model_match, reasoning_field, tool_calls = _completion_semantics(response.body)
    except KimiStockCapacityProbeError:
        return CompletionObservation(
            outcome="response_error",
            latency_ms=latency_ms,
            status_code=response.status_code,
            response_sha256=response_sha256,
        )
    if not valid:
        return CompletionObservation(
            outcome="response_error",
            latency_ms=latency_ms,
            status_code=response.status_code,
            response_sha256=response_sha256,
            model_match=model_match,
            reasoning_field=reasoning_field,
            tool_calls=tool_calls,
        )
    return CompletionObservation(
        outcome="successful",
        latency_ms=latency_ms,
        status_code=response.status_code,
        response_sha256=response_sha256,
        model_match=model_match,
        reasoning_field=reasoning_field,
        tool_calls=tool_calls,
    )


def _run_completions(
    transport: HttpTransport,
    *,
    concurrency: int,
    timeout: float,
    metrics_timeout: float,
    monotonic: Any,
) -> tuple[list[CompletionObservation], int, float, dict[str, int | float]]:
    start_barrier = threading.Barrier(concurrency + 1)
    in_flight_barrier = threading.Barrier(concurrency + 1)
    lock = threading.Lock()
    active = 0
    peak = 0

    def run(index: int) -> CompletionObservation:
        nonlocal active, peak
        entered = False
        try:
            start_barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            with lock:
                active += 1
                peak = max(peak, active)
                entered = True
            in_flight_barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            return _completion_request(
                transport,
                index=index,
                timeout=timeout,
                monotonic=monotonic,
            )
        except threading.BrokenBarrierError:
            return CompletionObservation(outcome="transport_error", latency_ms=0.0)
        finally:
            if entered:
                with lock:
                    active -= 1

    during: dict[str, int | float] = {
        "maximum_kv_cache_usage": 0.0,
        "maximum_running": 0,
        "maximum_waiting": 0,
        "response_errors": 0,
        "samples": 0,
        "transport_errors": 0,
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        try:
            futures = [executor.submit(run, index) for index in range(concurrency)]
        except BaseException:
            start_barrier.abort()
            in_flight_barrier.abort()
            raise
        started = monotonic()
        released = False
        try:
            start_barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            in_flight_barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            released = True
        except threading.BrokenBarrierError:
            start_barrier.abort()
            in_flight_barrier.abort()
        while released:
            sample, response_errors, transport_errors = _safe_metrics(
                transport,
                timeout=metrics_timeout,
            )
            during["response_errors"] += response_errors
            during["transport_errors"] += transport_errors
            if sample is not None:
                during["samples"] += 1
                during["maximum_running"] = max(during["maximum_running"], sample["running"])
                during["maximum_waiting"] = max(during["maximum_waiting"], sample["waiting"])
                during["maximum_kv_cache_usage"] = max(
                    during["maximum_kv_cache_usage"],
                    sample["kv_cache_usage"],
                )
            if all(future.done() for future in futures):
                break
            concurrent.futures.wait(futures, timeout=IN_FLIGHT_METRICS_INTERVAL_SECONDS)
        observations = [future.result() for future in futures]
        elapsed_ms = max(0.0, round((monotonic() - started) * 1000, 3))
    return observations, peak, elapsed_ms, during


def _response_digest_aggregate(observations: Sequence[CompletionObservation]) -> str:
    digests = sorted(
        observation.response_sha256 for observation in observations if observation.response_sha256 is not None
    )
    return _sha256("".join(f"{digest}\n" for digest in digests).encode("ascii"))


def _timing_summary(observations: Sequence[CompletionObservation], elapsed_ms: float) -> dict[str, float]:
    latencies = [observation.latency_ms for observation in observations]
    if not latencies:
        return {
            "elapsed_milliseconds": elapsed_ms,
            "maximum_request_milliseconds": 0.0,
            "mean_request_milliseconds": 0.0,
            "minimum_request_milliseconds": 0.0,
        }
    return {
        "elapsed_milliseconds": elapsed_ms,
        "maximum_request_milliseconds": max(latencies),
        "mean_request_milliseconds": round(sum(latencies) / len(latencies), 3),
        "minimum_request_milliseconds": min(latencies),
    }


def _metric_deltas(
    before: Mapping[str, int | float] | None,
    after: Mapping[str, int | float] | None,
) -> dict[str, int] | None:
    if before is None or after is None:
        return None
    return {
        name: int(after[name]) - int(before[name])
        for name in ("generation_tokens", "preemptions", "successful_requests")
    }


def _binding_unchanged(
    before: DeploymentBinding,
    deployment_root: Path,
    *,
    expected_spec_sha256: str,
    expected_proxy_config_sha256: str,
    expected_sticky_ttl_seconds: int | None,
) -> bool:
    try:
        after = _load_binding(
            deployment_root,
            expected_deployment_id=before.deployment_id,
            expected_spec_sha256=expected_spec_sha256,
            expected_proxy_config_sha256=expected_proxy_config_sha256,
            expected_sticky_ttl_seconds=expected_sticky_ttl_seconds,
        )
    except KimiStockCapacityProbeError:
        return False
    return (
        after.fingerprints == before.fingerprints
        and after.endpoint == before.endpoint
        and after.endpoint_authority_sha256 == before.endpoint_authority_sha256
    )


def _aggregate_receipt(
    *,
    binding: DeploymentBinding,
    concurrency: int,
    before_metrics: dict[str, int | float] | None,
    after_metrics: dict[str, int | float] | None,
    metrics_response_errors: int,
    metrics_transport_errors: int,
    in_flight_metrics: dict[str, int | float],
    model_confirmed: bool,
    model_response_errors: int,
    model_transport_errors: int,
    observations: Sequence[CompletionObservation],
    client_peak_in_flight: int,
    elapsed_ms: float,
    endpoint_unchanged: bool,
) -> dict[str, Any]:
    successful = sum(observation.outcome == "successful" for observation in observations)
    response_errors = sum(observation.outcome == "response_error" for observation in observations)
    transport_errors = sum(observation.outcome == "transport_error" for observation in observations)
    http_200 = sum(observation.status_code == 200 for observation in observations)
    reasoning_content = sum(observation.reasoning_field == "reasoning_content" for observation in observations)
    raw_reasoning = sum(observation.reasoning_field == "reasoning" for observation in observations)
    reasoning_present = reasoning_content + raw_reasoning
    model_matches = sum(observation.model_match for observation in observations)
    tool_call_responses = sum(observation.tool_calls > 0 for observation in observations)
    tool_calls_total = sum(observation.tool_calls for observation in observations)
    deltas = _metric_deltas(before_metrics, after_metrics)
    metrics_clean = (
        before_metrics is not None
        and after_metrics is not None
        and before_metrics["running"] == 0
        and after_metrics["running"] == 0
        and before_metrics["waiting"] == 0
        and after_metrics["waiting"] == 0
        and deltas is not None
        and deltas["preemptions"] == 0
        and deltas["generation_tokens"] >= 0
        and deltas["successful_requests"] >= 0
        and in_flight_metrics["samples"] >= 1
        and in_flight_metrics["maximum_waiting"] == 0
        and in_flight_metrics["response_errors"] == 0
        and in_flight_metrics["transport_errors"] == 0
        and metrics_response_errors == 0
        and metrics_transport_errors == 0
    )
    passed = (
        len(observations) == concurrency
        and successful == concurrency
        and response_errors == 0
        and transport_errors == 0
        and model_matches == concurrency
        and reasoning_present == concurrency
        and tool_call_responses == concurrency
        and tool_calls_total == concurrency
        and client_peak_in_flight == concurrency
        and model_confirmed
        and model_response_errors == 0
        and model_transport_errors == 0
        and metrics_clean
        and endpoint_unchanged
    )
    return {
        "artifacts": {
            "endpoint_file": binding.endpoint_file.receipt,
            "proxy_config": binding.proxy_config.receipt,
            "spec": binding.spec.receipt,
        },
        "completions": {
            "attempted": len(observations),
            "http_200": http_200,
            "model_matches": model_matches,
            "reasoning_content_present": reasoning_content,
            "reasoning_present": reasoning_present,
            "raw_reasoning_present": raw_reasoning,
            "requested": concurrency,
            "response_digests_sha256": _response_digest_aggregate(observations),
            "response_errors": response_errors,
            "successful": successful,
            "tool_call_responses": tool_call_responses,
            "tool_calls_total": tool_calls_total,
            "transport_errors": transport_errors,
        },
        "concurrency": {
            "client_peak_in_flight": client_peak_in_flight,
            "configured": concurrency,
        },
        "deployment": {
            "endpoint_authority_sha256": binding.endpoint_authority_sha256,
            "endpoint_job_id": binding.endpoint.job_id,
            "id": binding.deployment_id,
            "model": EXPECTED_MODEL,
        },
        "endpoint_unchanged": endpoint_unchanged,
        "kind": KIND,
        "metrics": {
            "after": after_metrics,
            "before": before_metrics,
            "deltas": deltas,
            "in_flight": in_flight_metrics,
            "response_errors": metrics_response_errors,
            "transport_errors": metrics_transport_errors,
        },
        "model_identity": {
            "backend_model": EXPECTED_BACKEND_MODEL,
            "confirmed": model_confirmed,
            "response_errors": model_response_errors,
            "served_model": EXPECTED_MODEL,
            "transport_errors": model_transport_errors,
        },
        "request_contract": {
            "max_tokens": MAX_TOKENS,
            "parallel_tool_calls": False,
            "payload_sha256": REQUEST_SHA256,
            "reasoning_effort": "max",
            "route": "/v1/chat/completions",
            "stream": False,
            "temperature": 0,
            "thinking": {
                "enable_thinking": True,
                "preserve_thinking": True,
            },
            "tool_choice": "required",
            "tool_name": TOOL_NAME,
        },
        "schema_version": SCHEMA_VERSION,
        "state": "passed" if passed else "failed",
        "timings": _timing_summary(observations, elapsed_ms),
    }


def run_probe(
    deployment_root: Path,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    metrics_timeout_seconds: float = DEFAULT_METRICS_TIMEOUT_SECONDS,
    expected_deployment_id: str | None = None,
    expected_spec_sha256: str | None = None,
    expected_proxy_config_sha256: str | None = None,
    expected_sticky_ttl_seconds: int | None = None,
    transport: HttpTransport | None = None,
    monotonic: Any = time.monotonic,
) -> dict[str, Any]:
    if concurrency not in ALLOWED_CONCURRENCY:
        raise KimiStockCapacityProbeError("concurrency_invalid")
    if (
        isinstance(request_timeout_seconds, bool)
        or not isinstance(request_timeout_seconds, (int, float))
        or not math.isfinite(request_timeout_seconds)
        or not 1 <= request_timeout_seconds <= 3_600
        or isinstance(metrics_timeout_seconds, bool)
        or not isinstance(metrics_timeout_seconds, (int, float))
        or not math.isfinite(metrics_timeout_seconds)
        or not 1 <= metrics_timeout_seconds <= 60
    ):
        raise KimiStockCapacityProbeError("timeout_invalid")
    binding = _load_binding(
        deployment_root,
        expected_deployment_id=expected_deployment_id,
        expected_spec_sha256=expected_spec_sha256,
        expected_proxy_config_sha256=expected_proxy_config_sha256,
        expected_sticky_ttl_seconds=expected_sticky_ttl_seconds,
    )
    client = transport or DirectHttpTransport(binding.endpoint.host, binding.endpoint.port)

    before_metrics, before_response_errors, before_transport_errors = _safe_metrics(
        client,
        timeout=metrics_timeout_seconds,
    )
    model_confirmed, model_response_errors, model_transport_errors = _safe_model_identity(
        client,
        timeout=metrics_timeout_seconds,
    )
    observations: list[CompletionObservation] = []
    peak = 0
    elapsed_ms = 0.0
    in_flight_metrics: dict[str, int | float] = {
        "maximum_kv_cache_usage": 0.0,
        "maximum_running": 0,
        "maximum_waiting": 0,
        "response_errors": 0,
        "samples": 0,
        "transport_errors": 0,
    }
    safe_to_start = (
        before_metrics is not None
        and before_metrics["running"] == 0
        and before_metrics["waiting"] == 0
        and before_response_errors == 0
        and before_transport_errors == 0
        and model_confirmed
        and model_response_errors == 0
        and model_transport_errors == 0
    )
    if safe_to_start:
        observations, peak, elapsed_ms, in_flight_metrics = _run_completions(
            client,
            concurrency=concurrency,
            timeout=request_timeout_seconds,
            metrics_timeout=metrics_timeout_seconds,
            monotonic=monotonic,
        )
    after_metrics, after_response_errors, after_transport_errors = _safe_metrics(
        client,
        timeout=metrics_timeout_seconds,
    )
    endpoint_unchanged = _binding_unchanged(
        binding,
        deployment_root,
        expected_spec_sha256=expected_spec_sha256,
        expected_proxy_config_sha256=expected_proxy_config_sha256,
        expected_sticky_ttl_seconds=expected_sticky_ttl_seconds,
    )
    return _aggregate_receipt(
        binding=binding,
        concurrency=concurrency,
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        metrics_response_errors=(
            before_response_errors + after_response_errors + int(in_flight_metrics["response_errors"])
        ),
        metrics_transport_errors=(
            before_transport_errors + after_transport_errors + int(in_flight_metrics["transport_errors"])
        ),
        in_flight_metrics=in_flight_metrics,
        model_confirmed=model_confirmed,
        model_response_errors=model_response_errors,
        model_transport_errors=model_transport_errors,
        observations=observations,
        client_peak_in_flight=peak,
        elapsed_ms=elapsed_ms,
        endpoint_unchanged=endpoint_unchanged,
    )


def _publish(path: Path, value: Mapping[str, Any]) -> str:
    if not path.is_absolute():
        raise KimiStockCapacityProbeError("output_path_invalid")
    try:
        parent = path.parent.resolve(strict=True)
        parent_metadata = path.parent.lstat()
    except (OSError, RuntimeError) as error:
        raise KimiStockCapacityProbeError("output_parent_invalid") from error
    if (
        parent != path.parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        or os.path.lexists(path)
    ):
        raise KimiStockCapacityProbeError("output_path_invalid")
    body = _canonical_json(value) + b"\n"
    temporary = parent / f".{path.name}.stage-{os.getpid()}-{secrets.token_hex(8)}"
    descriptor = -1
    directory_descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        view = memoryview(body)
        while view:
            written = os.write(descriptor, view)
            if written < 1:
                raise KimiStockCapacityProbeError("output_write_failed")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            raise KimiStockCapacityProbeError("output_already_exists") from error
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_CLOEXEC)
        os.fsync(directory_descriptor)
    except KimiStockCapacityProbeError:
        raise
    except OSError as error:
        raise KimiStockCapacityProbeError("output_publish_failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        metadata = path.lstat()
        persisted = path.read_bytes()
    except OSError as error:
        raise KimiStockCapacityProbeError("output_publish_failed") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or persisted != body
    ):
        raise KimiStockCapacityProbeError("output_publish_failed")
    return _sha256(body)


def capture_probe(
    deployment_root: Path,
    output: Path,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    metrics_timeout_seconds: float = DEFAULT_METRICS_TIMEOUT_SECONDS,
    expected_deployment_id: str | None = None,
    expected_spec_sha256: str | None = None,
    expected_proxy_config_sha256: str | None = None,
    expected_sticky_ttl_seconds: int | None = None,
    transport: HttpTransport | None = None,
    monotonic: Any = time.monotonic,
) -> tuple[dict[str, Any], str]:
    receipt = run_probe(
        deployment_root,
        concurrency=concurrency,
        request_timeout_seconds=request_timeout_seconds,
        metrics_timeout_seconds=metrics_timeout_seconds,
        expected_deployment_id=expected_deployment_id,
        expected_spec_sha256=expected_spec_sha256,
        expected_proxy_config_sha256=expected_proxy_config_sha256,
        expected_sticky_ttl_seconds=expected_sticky_ttl_seconds,
        transport=transport,
        monotonic=monotonic,
    )
    return receipt, _publish(output, receipt)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-root", type=Path, default=DEFAULT_DEPLOYMENT_ROOT)
    parser.add_argument("--concurrency", type=int, choices=ALLOWED_CONCURRENCY, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--metrics-timeout-seconds", type=float, default=DEFAULT_METRICS_TIMEOUT_SECONDS)
    parser.add_argument("--expected-deployment-id", default=EXPECTED_DEPLOYMENT_ID)
    parser.add_argument("--expected-spec-sha256", default=EXPECTED_SPEC_SHA256)
    parser.add_argument("--expected-proxy-config-sha256", default=EXPECTED_PROXY_CONFIG_SHA256)
    parser.add_argument("--expected-sticky-ttl-seconds", type=int)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        receipt, receipt_sha256 = capture_probe(
            arguments.deployment_root,
            arguments.output,
            concurrency=arguments.concurrency,
            request_timeout_seconds=arguments.request_timeout_seconds,
            metrics_timeout_seconds=arguments.metrics_timeout_seconds,
            expected_deployment_id=arguments.expected_deployment_id,
            expected_spec_sha256=arguments.expected_spec_sha256,
            expected_proxy_config_sha256=arguments.expected_proxy_config_sha256,
            expected_sticky_ttl_seconds=arguments.expected_sticky_ttl_seconds,
        )
    except (KimiStockCapacityProbeError, OSError, RuntimeError, ValueError):
        print(
            _canonical_json({"kind": KIND, "state": "blocked"}).decode("utf-8"),
            file=sys.stderr,
        )
        return 2
    summary = {
        "kind": KIND,
        "receipt_sha256": receipt_sha256,
        "state": receipt["state"],
    }
    stream = sys.stdout if receipt["state"] == "passed" else sys.stderr
    print(_canonical_json(summary).decode("utf-8"), file=stream)
    return 0 if receipt["state"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
