#!/usr/bin/env python3
"""Fail-closed preflight for the cpu-132-021:8103 Kimi evaluation lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import yaml

EXPECTED_MODEL = "Kimi-K3"
EXPECTED_ROUTES = 24
EXPECTED_ROLLOUT_CONCURRENCY = 64
EXPECTED_HTTP_CONCURRENCY = 24
EXPECTED_WAITING_REQUESTS = EXPECTED_ROLLOUT_CONCURRENCY - EXPECTED_HTTP_CONCURRENCY
EXPECTED_PROXY_URL = "http://cpu-132-021:8103"
EXPECTED_SPEC_SHA256 = "ab00213a43083eba87f8b5999a3046e8d27ebe42b933ee845fd0cf4928b266e2"
EXPECTED_PROXY_REQUEST_TIMEOUT = 7_200
EXPECTED_PROXY_NUM_RETRIES = 0
EXPECTED_TASK_SHA256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"
EXPECTED_IMAGE_SHA256 = "118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009"
EXPECTED_DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
EXPECTED_VERIFIERS_REVISION = "04d999177f320e195e3335593688934f32e899d3"
EXPECTED_RENDERERS_REVISION = "044d9e2541f6a911cacae9da353fc063911ef1f8"
EXPECTED_PYDANTIC_CONFIG_REVISION = "896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f"
EXPECTED_TASK_FILE = "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt"
EXPECTED_CONFIG_FILE = (
    "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/mobius_kimi_k3_shared24_2500.toml"
)
EXPECTED_CONFIG_SHA256 = "cfe7891a16f175187d2e892f1293471a1626f3ebda33e9f3d9ae8aab223a7937"
EXPECTED_DATASET_DIR = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9"
EXPECTED_IMAGE_MANIFEST = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json"
TB4_TASK_FILE = "user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt"
TB4_TASK_SHA256 = "9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892"
TB4_CONFIG_FILE = (
    "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/tb4_kimi_k3_shared24_miniswe.toml"
)
TB4_CONFIG_SHA256 = "aa5349078630181d574a55e15c23b487071f6d29cc77d2d79e92ced6003bcda6"
TB4_DATASET_DIR = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks"
TB4_DATASET_TREE_SHA256 = "1a7ffccd2a221b43fa2f4a745fa6ae2e244c45282d5f5efa895aa902cfe79943"
TB4_DATASET_FILE_COUNT = 5_939
TB4_DATASET_DIRECTORY_COUNT = 819
EVAL_OUTPUT_ROOT = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals")
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_TASK_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
JOB_FILE_RE = re.compile(r"^[1-9][0-9]*\.json$")


@dataclass(frozen=True)
class ProfileContract:
    name: str
    config_file: str
    config_sha256: str
    task_file: str
    task_sha256: str
    task_count: int
    dataset_dir: str
    dataset_revision: str | None
    dataset_tree_sha256: str | None
    dataset_file_count: int | None
    dataset_directory_count: int | None
    image_manifest: str | None
    image_sha256: str | None
    image_tag: str
    max_concurrent: int
    http_concurrent: int
    timeout_multiplier: float
    resource_multiplier: float
    use_declared_images: bool
    enable_compose: bool
    default_output_prefix: str


PROFILES = {
    "mobius": ProfileContract(
        name="mobius",
        config_file=EXPECTED_CONFIG_FILE,
        config_sha256=EXPECTED_CONFIG_SHA256,
        task_file=EXPECTED_TASK_FILE,
        task_sha256=EXPECTED_TASK_SHA256,
        task_count=2_500,
        dataset_dir=EXPECTED_DATASET_DIR,
        dataset_revision=EXPECTED_DATASET_REVISION,
        dataset_tree_sha256=None,
        dataset_file_count=None,
        dataset_directory_count=None,
        image_manifest=EXPECTED_IMAGE_MANIFEST,
        image_sha256=EXPECTED_IMAGE_SHA256,
        image_tag="mobius-9b6988a3faf0",
        max_concurrent=64,
        http_concurrent=24,
        timeout_multiplier=2.0,
        resource_multiplier=2.0,
        use_declared_images=False,
        enable_compose=False,
        default_output_prefix="mobius_kimi_k3_shared24_cpu-132-021_8103_",
    ),
    "tb4": ProfileContract(
        name="tb4",
        config_file=TB4_CONFIG_FILE,
        config_sha256=TB4_CONFIG_SHA256,
        task_file=TB4_TASK_FILE,
        task_sha256=TB4_TASK_SHA256,
        task_count=66,
        dataset_dir=TB4_DATASET_DIR,
        dataset_revision=None,
        dataset_tree_sha256=TB4_DATASET_TREE_SHA256,
        dataset_file_count=TB4_DATASET_FILE_COUNT,
        dataset_directory_count=TB4_DATASET_DIRECTORY_COUNT,
        image_manifest=None,
        image_sha256=None,
        image_tag="tb4-452bf305c6da",
        max_concurrent=24,
        http_concurrent=24,
        timeout_multiplier=1.0,
        resource_multiplier=1.0,
        use_declared_images=True,
        enable_compose=True,
        default_output_prefix="tb4_kimi_k3_shared24_cpu-132-021_8103_",
    ),
}


class SharedKimiValidationError(ValueError):
    """A fixed, non-secret launch-contract error."""


@dataclass(frozen=True)
class ProxyMetadata:
    url: str
    api_key: str
    proxy_info_sha256: str
    proxy_litellm_config_sha256: str


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes


class MetadataTransport(Protocol):
    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse: ...


class UrllibMetadataTransport:
    """Proxy-free transport for authenticated health and model metadata."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(MAX_JSON_BYTES + 1)
                status_code = response.status
        except urllib.error.HTTPError as error:
            body = error.read(MAX_JSON_BYTES + 1)
            status_code = error.code
        return HttpResponse(status_code=status_code, body=body)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _fail(code: str) -> None:
    raise SharedKimiValidationError(code)


def _read_bytes(path: Path, *, limit: int, code: str) -> bytes:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            _fail(code)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                _fail(code)
            value = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        current = path.lstat()
    except OSError:
        _fail(code)
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, stat.S_IMODE(before.st_mode))
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, stat.S_IMODE(after.st_mode))
    current_identity = (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
        stat.S_IMODE(current.st_mode),
    )
    if not stat.S_ISREG(current.st_mode) or before_identity != after_identity or after_identity != current_identity:
        _fail(code)
    if len(value) > limit:
        _fail(code)
    return value


def _load_json_bytes(raw: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(code)
    if not isinstance(value, dict):
        _fail(code)
    return value


def _load_json_file(path: Path, *, code: str) -> tuple[bytes, dict[str, Any]]:
    raw = _read_bytes(path, limit=MAX_JSON_BYTES, code=code)
    return raw, _load_json_bytes(raw, code=code)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys at every mapping level."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate key",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml_mapping(raw: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = yaml.load(raw.decode("utf-8"), Loader=_UniqueKeySafeLoader)
    except (UnicodeDecodeError, yaml.YAMLError):
        _fail(code)
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail(code)
    return value


def _validate_proxy_litellm_config(root: Path) -> str:
    raw = _read_bytes(
        root / "proxy_litellm_config.yaml",
        limit=MAX_CONFIG_BYTES,
        code="proxy_litellm_config_unreadable",
    )
    config = _load_yaml_mapping(raw, code="proxy_litellm_config_invalid")
    settings = config.get("litellm_settings")
    if not isinstance(settings, dict):
        _fail("proxy_litellm_config_policy_mismatch")
    if not _values_exact(settings.get("request_timeout"), EXPECTED_PROXY_REQUEST_TIMEOUT):
        _fail("proxy_litellm_config_policy_mismatch")
    if not _values_exact(settings.get("num_retries"), EXPECTED_PROXY_NUM_RETRIES):
        _fail("proxy_litellm_config_policy_mismatch")
    return _sha256(raw)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolve(path: Path, *, code: str) -> Path:
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        _fail(code)


def _exact_keys(value: Mapping[str, Any], keys: set[str], *, code: str) -> None:
    if set(value) != keys:
        _fail(code)


def _valid_port(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65_535


def validate_deployment(
    deployment_root: Path,
    proxy_info_path: Path,
    *,
    expected_spec_sha256: str = EXPECTED_SPEC_SHA256,
    expected_proxy_url: str = EXPECTED_PROXY_URL,
) -> ProxyMetadata:
    """Validate immutable deployment metadata without exposing the credential."""

    root = _resolve(deployment_root, code="deployment_root_unreadable")
    if root.is_symlink() or not root.is_dir():
        _fail("deployment_root_invalid")

    spec_raw = _read_bytes(root / "spec.yaml", limit=MAX_CONFIG_BYTES, code="deployment_spec_unreadable")
    if not SHA256_RE.fullmatch(expected_spec_sha256) or _sha256(spec_raw) != expected_spec_sha256:
        _fail("deployment_spec_hash_mismatch")

    _, proxy_config = _load_json_file(root / "proxy_config.json", code="proxy_config_invalid")
    _exact_keys(proxy_config, {"pixi_env", "sticky", "sticky_ttl"}, code="proxy_config_schema_invalid")
    if (
        not isinstance(proxy_config["pixi_env"], str)
        or not proxy_config["pixi_env"].strip()
        or proxy_config["sticky"] is not True
        or proxy_config["sticky_ttl"] != 14_400
    ):
        _fail("proxy_config_contract_mismatch")

    proxy_litellm_config_sha256 = _validate_proxy_litellm_config(root)

    proxy_raw, proxy_info = _load_json_file(proxy_info_path, code="proxy_info_invalid")
    _exact_keys(
        proxy_info,
        {"url", "api_key", "model", "host", "port", "proxy_jobid", "extras"},
        code="proxy_info_schema_invalid",
    )
    url = proxy_info["url"]
    api_key = proxy_info["api_key"]
    host = proxy_info["host"]
    port = proxy_info["port"]
    if not isinstance(url, str) or url != expected_proxy_url:
        _fail("proxy_url_mismatch")
    if (
        not isinstance(api_key, str)
        or not api_key
        or len(api_key) > 4_096
        or any(character.isspace() or ord(character) < 32 for character in api_key)
    ):
        _fail("proxy_api_key_invalid")
    if proxy_info["model"] != EXPECTED_MODEL:
        _fail("proxy_model_mismatch")
    if not isinstance(host, str) or HOST_RE.fullmatch(host) is None or not _valid_port(port):
        _fail("proxy_address_invalid")
    if not isinstance(proxy_info["proxy_jobid"], str) or not proxy_info["proxy_jobid"].isdigit():
        _fail("proxy_job_invalid")

    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != host
        or parsed.port != port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _fail("proxy_address_mismatch")

    extras = proxy_info["extras"]
    if not isinstance(extras, dict):
        _fail("proxy_extras_invalid")
    _exact_keys(
        extras,
        {"proxy_type", "prometheus_port", "sticky", "sticky_ttl", "redis_port"},
        code="proxy_extras_schema_invalid",
    )
    if (
        extras["proxy_type"] != "litellm"
        or extras["sticky"] is not True
        or extras["sticky_ttl"] != 14_400
        or extras["prometheus_port"] != port
        or not _valid_port(extras["redis_port"])
    ):
        _fail("proxy_extras_contract_mismatch")

    endpoints_dir = root / "endpoints"
    if endpoints_dir.is_symlink() or not endpoints_dir.is_dir():
        _fail("endpoint_directory_invalid")
    try:
        endpoint_paths = sorted(endpoints_dir.iterdir())
    except OSError:
        _fail("endpoint_directory_unreadable")
    if len(endpoint_paths) != EXPECTED_ROUTES:
        _fail("endpoint_count_mismatch")

    endpoints: set[tuple[str, int]] = set()
    for endpoint_path in endpoint_paths:
        if endpoint_path.is_symlink() or JOB_FILE_RE.fullmatch(endpoint_path.name) is None:
            _fail("endpoint_record_invalid")
        _, endpoint = _load_json_file(endpoint_path, code="endpoint_record_invalid")
        _exact_keys(endpoint, {"host", "port", "started_at"}, code="endpoint_record_schema_invalid")
        endpoint_host = endpoint["host"]
        endpoint_port = endpoint["port"]
        started_at = endpoint["started_at"]
        if (
            not isinstance(endpoint_host, str)
            or HOST_RE.fullmatch(endpoint_host) is None
            or not _valid_port(endpoint_port)
            or not isinstance(started_at, str)
        ):
            _fail("endpoint_record_contract_mismatch")
        try:
            parsed_started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            _fail("endpoint_started_at_invalid")
        if parsed_started_at.tzinfo is None:
            _fail("endpoint_started_at_invalid")
        endpoints.add((endpoint_host, endpoint_port))
    if len(endpoints) != EXPECTED_ROUTES:
        _fail("endpoint_records_not_unique")

    return ProxyMetadata(
        url=url,
        api_key=api_key,
        proxy_info_sha256=_sha256(proxy_raw),
        proxy_litellm_config_sha256=proxy_litellm_config_sha256,
    )


def _api_urls(base_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(base_url)
    root_path = parsed.path.rstrip("/")
    if root_path.endswith("/v1"):
        root_path = root_path[:-3].rstrip("/")
    health_url = urllib.parse.urlunsplit(
        parsed._replace(
            path=f"{root_path}/health",
            query=urllib.parse.urlencode({"model": EXPECTED_MODEL}),
        )
    )
    models_url = urllib.parse.urlunsplit(parsed._replace(path=f"{root_path}/v1/models", query=""))
    return health_url, models_url


def _runtime_json(
    transport: MetadataTransport,
    url: str,
    *,
    headers: Mapping[str, str],
    timeout: float,
    code: str,
) -> dict[str, Any]:
    try:
        response = transport.get(url, headers=headers, timeout=timeout)
    except Exception:
        _fail(code)
    if not 200 <= response.status_code < 300 or len(response.body) > MAX_JSON_BYTES:
        _fail(code)
    return _load_json_bytes(response.body, code=code)


def validate_runtime_metadata(
    proxy: ProxyMetadata,
    *,
    transport: MetadataTransport | None = None,
    timeout: float = 120.0,
) -> None:
    """Require the authenticated API to expose one model and 24/0 route health."""

    if timeout <= 0:
        _fail("runtime_timeout_invalid")
    transport = transport or UrllibMetadataTransport()
    headers = {
        "Authorization": f"Bearer {proxy.api_key}",
        "Accept": "application/json",
    }
    health_url, models_url = _api_urls(proxy.url)
    models = _runtime_json(
        transport,
        models_url,
        headers=headers,
        timeout=timeout,
        code="models_endpoint_invalid",
    )
    model_rows = models.get("data")
    if (
        not isinstance(model_rows, list)
        or len(model_rows) != 1
        or not isinstance(model_rows[0], dict)
        or model_rows[0].get("id") != EXPECTED_MODEL
    ):
        _fail("served_models_mismatch")

    health = _runtime_json(
        transport,
        health_url,
        headers=headers,
        timeout=timeout,
        code="health_endpoint_invalid",
    )
    healthy_count = health.get("healthy_count")
    unhealthy_count = health.get("unhealthy_count")
    if isinstance(healthy_count, bool) or not isinstance(healthy_count, int):
        healthy_endpoints = health.get("healthy_endpoints")
        healthy_count = len(healthy_endpoints) if isinstance(healthy_endpoints, list) else None
    if isinstance(unhealthy_count, bool) or not isinstance(unhealthy_count, int):
        unhealthy_endpoints = health.get("unhealthy_endpoints")
        unhealthy_count = len(unhealthy_endpoints) if isinstance(unhealthy_endpoints, list) else None
    if healthy_count != EXPECTED_ROUTES or unhealthy_count != 0:
        _fail("route_health_mismatch")


def _resolve_config_path(project_dir: Path, value: Any, *, code: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        _fail(code)
    path = Path(value)
    if not path.is_absolute():
        path = project_dir / path
    return _resolve(path, code=code)


def _require_config_value(actual: Any, expected: Any, *, code: str) -> None:
    if not _values_exact(actual, expected):
        _fail(code)


def _values_exact(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _values_exact(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _values_exact(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    return actual == expected


def _profile(name: str) -> ProfileContract:
    try:
        return PROFILES[name]
    except KeyError:
        _fail("eval_profile_invalid")


def _parse_toml(raw: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        _fail(code)
    if not isinstance(value, dict):
        _fail(code)
    return value


def _expected_resolved_config(profile: ProfileContract, resume_dir: Path) -> dict[str, Any]:
    taskset: dict[str, Any] = {
        "id": "terminal-bench-vmvm",
        "dataset": "hello-world",
        "timeout_multiplier": profile.timeout_multiplier,
        "resource_multiplier": profile.resource_multiplier,
        "require_image": False,
        "ignore_dockerfile": True,
        "dataset_dir": profile.dataset_dir,
        "task_file": str(resume_dir / "inputs" / "task_file.txt"),
        "task_file_sha256": profile.task_sha256,
        "image_prefix": "vmvm-registry.fbinfra.net/terminal_bench",
        "image_tag": profile.image_tag,
        "verifier_image_suffix": "-verifier",
        "use_declared_images": profile.use_declared_images,
        "enable_compose": profile.enable_compose,
        "verifier_runtime_retries": 2,
        "capture_convention_artifacts": True,
        "oracle_solution_network_mode": "declared",
    }
    if profile.dataset_revision is not None:
        taskset["dataset_revision"] = profile.dataset_revision
    if profile.image_sha256 is not None:
        taskset["image_manifest"] = str(resume_dir / "inputs" / "image_manifest.json")
        taskset["image_manifest_sha256"] = profile.image_sha256

    return {
        "max_turns": 200,
        "max_input_tokens": 262_144,
        "max_output_tokens": 262_144,
        "max_total_tokens": 262_144,
        "multiplex": profile.max_concurrent,
        "model": EXPECTED_MODEL,
        "num_tasks": profile.task_count,
        "num_rollouts": 1,
        "shuffle": False,
        "max_concurrent": profile.max_concurrent,
        "verbose": False,
        "dry_run": False,
        "rich": False,
        "retain_traces": False,
        "server": False,
        "output_dir": str(resume_dir),
        "taskset": taskset,
        "harness": {
            "id": "mini-swe-agent",
            "version": "2.2.8",
            "config_file": "mini",
            "config_overrides": [
                "agent.step_limit=200",
                "environment.environment_class=local",
                "environment.timeout=900",
                "model.model_kwargs.drop_params=true",
                "model.model_kwargs.temperature=1.0",
                "model.model_kwargs.top_p=1.0",
                "model.model_kwargs.parallel_tool_calls=true",
                "model.model_kwargs.timeout=15000",
            ],
            "runtime": {
                "type": "vmvm",
                "image": "python:3.11-slim",
                "workdir": "/app",
                "session_timeout": 43_200.0,
                "tenant_id": "async_2347641",
                "lease_ttl": "60s",
                "tunnel_ready_timeout": 120.0,
                "sshd_ready_timeout": 180.0,
                "max_session_buffer_size": 67_108_864,
            },
            "env": {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"},
        },
        "timeout": {
            "setup": 3_600.0,
            "rollout": 36_000.0,
            "finalize": 3_600.0,
            "scoring": 21_600.0,
        },
        "retries": {
            "rollout": {
                "max_retries": 2,
                "include": ["ProviderError", "SandboxError", "TunnelError"],
                "exclude": [],
            }
        },
        "args": {},
        "extra_env_kwargs": {},
        "pool": {"type": "elastic", "multiplex": 128},
        "client": {
            "base_url": f"{EXPECTED_PROXY_URL}/v1",
            "api_key_var": "OPENAI_API_KEY",
            "timeout": 7_200.0,
            "connect_timeout": 120.0,
            "max_connections": profile.http_concurrent,
            "max_keepalive_connections": profile.http_concurrent,
            "max_retries": 10,
            "type": "eval",
            "outbound_body_denylist": [
                "logprobs",
                "prompt_logprobs",
                "top_logprobs",
                "return_token_ids",
            ],
            "capture_model_io": True,
            "headers": {},
            "extra_headers_from_state": {},
        },
        "sampling": {
            "temperature": 1.0,
            "top_p": 1.0,
            "reasoning_effort": "max",
            "max_tokens": 32_768,
            "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        },
    }


def _validate_common_eval_contract(
    config: Mapping[str, Any],
    profile: ProfileContract,
    *,
    resolved: bool,
    resume_dir: Path | None = None,
) -> None:
    if resolved:
        if resume_dir is None:
            _fail("resume_directory_missing")
        if not _values_exact(config, _expected_resolved_config(profile, resume_dir)):
            _fail("resume_config_contract_mismatch")
        return

    expected_top_level = {
        "model": EXPECTED_MODEL,
        "num_tasks": profile.task_count,
        "num_rollouts": 1,
        "max_concurrent": profile.max_concurrent,
        "multiplex": profile.max_concurrent,
        "max_turns": 200,
        "max_input_tokens": 262_144,
        "max_output_tokens": 262_144,
        "max_total_tokens": 262_144,
        "rich": False,
        "retain_traces": False,
    }
    for key, expected in expected_top_level.items():
        _require_config_value(config.get(key), expected, code=f"eval_config_{key}_mismatch")

    client = config.get("client")
    if not isinstance(client, dict):
        _fail("eval_client_invalid")
    expected_client = {
        "type": "eval",
        "capture_model_io": True,
        "base_url": "http://127.0.0.1:8000/v1",
        "api_key_var": "OPENAI_API_KEY",
        "timeout": 7_200,
        "connect_timeout": 120,
        "max_connections": profile.http_concurrent,
        "max_keepalive_connections": profile.http_concurrent,
    }
    for key, expected in expected_client.items():
        _require_config_value(client.get(key), expected, code=f"eval_client_{key}_mismatch")
    if "headers" in client or "extra_headers" in client or "extra_headers_from_state" in client:
        _fail("eval_client_headers_forbidden")
    if client.get("outbound_body_denylist") != [
        "logprobs",
        "prompt_logprobs",
        "top_logprobs",
        "return_token_ids",
    ]:
        _fail("eval_client_denylist_mismatch")

    sampling = config.get("sampling")
    if not isinstance(sampling, dict):
        _fail("eval_sampling_invalid")
    expected_sampling = {
        "temperature": 1.0,
        "top_p": 1.0,
        "max_tokens": 32_768,
        "reasoning_effort": "max",
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
    }
    for key, expected in expected_sampling.items():
        _require_config_value(sampling.get(key), expected, code=f"eval_sampling_{key}_mismatch")

    taskset = config.get("taskset")
    if not isinstance(taskset, dict):
        _fail("eval_taskset_invalid")
    expected_task_file = profile.task_file
    expected_image_manifest = profile.image_manifest
    expected_taskset: dict[str, Any] = {
        "id": "terminal-bench-vmvm",
        "dataset_dir": profile.dataset_dir,
        "task_file": expected_task_file,
        "task_file_sha256": profile.task_sha256,
        "image_prefix": "vmvm-registry.fbinfra.net/terminal_bench",
        "image_tag": profile.image_tag,
        "ignore_dockerfile": True,
        "verifier_runtime_retries": 2,
    }
    if profile.name == "mobius":
        expected_taskset["timeout_multiplier"] = profile.timeout_multiplier
        expected_taskset["resource_multiplier"] = profile.resource_multiplier
    if profile.dataset_revision is not None:
        expected_taskset["dataset_revision"] = profile.dataset_revision
    if profile.image_manifest is not None:
        expected_taskset["image_manifest"] = expected_image_manifest
        expected_taskset["image_manifest_sha256"] = profile.image_sha256
    if "tasks" in taskset:
        _fail("eval_inline_tasks_forbidden")
    for key, expected in expected_taskset.items():
        _require_config_value(taskset.get(key), expected, code=f"eval_taskset_{key}_mismatch")

    harness = config.get("harness")
    if not isinstance(harness, dict):
        _fail("eval_harness_invalid")
    for key, expected in {"id": "mini-swe-agent", "version": "2.2.8", "config_file": "mini"}.items():
        _require_config_value(harness.get(key), expected, code=f"eval_harness_{key}_mismatch")
    expected_overrides = [
        "agent.step_limit=200",
        "environment.environment_class=local",
        "environment.timeout=900",
        "model.model_kwargs.drop_params=true",
        "model.model_kwargs.temperature=1.0",
        "model.model_kwargs.top_p=1.0",
        "model.model_kwargs.parallel_tool_calls=true",
        "model.model_kwargs.timeout=15000",
    ]
    if harness.get("config_overrides") != expected_overrides:
        _fail("eval_harness_overrides_mismatch")
    if harness.get("env") != {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"}:
        _fail("eval_model_retry_mismatch")
    runtime = harness.get("runtime")
    if not isinstance(runtime, dict):
        _fail("eval_runtime_invalid")
    expected_runtime: dict[str, Any] = {
        "type": "vmvm",
        "session_timeout": 43_200,
        "tenant_id": "async_2347641",
        "lease_ttl": "60s",
        "max_session_buffer_size": 67_108_864,
    }
    for key, expected in expected_runtime.items():
        _require_config_value(runtime.get(key), expected, code=f"eval_runtime_{key}_mismatch")

    timeouts = config.get("timeout")
    if not isinstance(timeouts, dict):
        _fail("eval_timeouts_invalid")
    expected_timeouts = {"setup": 3_600, "rollout": 36_000, "finalize": 3_600, "scoring": 21_600}
    for key, expected in expected_timeouts.items():
        _require_config_value(timeouts.get(key), expected, code=f"eval_timeout_{key}_mismatch")
    rollout_retries = config.get("retries", {}).get("rollout")
    if not isinstance(rollout_retries, dict):
        _fail("eval_rollout_retries_invalid")
    if rollout_retries.get("max_retries") != 2 or set(rollout_retries.get("include", [])) != {
        "ProviderError",
        "SandboxError",
        "TunnelError",
    }:
        _fail("eval_rollout_retries_mismatch")


def validate_eval_config(project_dir: Path, config_path: Path, profile_name: str = "mobius") -> None:
    """Bind a fresh launch to an exact, digest-pinned server-lane config."""

    project = _resolve(project_dir, code="project_root_unreadable")
    profile = _profile(profile_name)
    expected_config = _resolve(project / profile.config_file, code="eval_config_unreadable")
    if _resolve(config_path, code="eval_config_unreadable") != expected_config:
        _fail("eval_config_path_mismatch")
    config_raw = _read_bytes(expected_config, limit=MAX_CONFIG_BYTES, code="eval_config_unreadable")
    if _sha256(config_raw) != profile.config_sha256:
        _fail("eval_config_hash_mismatch")
    config = _parse_toml(config_raw, code="eval_config_invalid")
    _validate_common_eval_contract(config, profile, resolved=False)

    task_file = _resolve_config_path(project, profile.task_file, code="eval_task_file_unreadable")
    task_raw = _read_bytes(task_file, limit=MAX_TASK_BYTES, code="eval_task_file_unreadable")
    if _sha256(task_raw) != profile.task_sha256:
        _fail("eval_task_file_hash_mismatch")
    try:
        task_rows = [line for line in task_raw.decode("utf-8").splitlines() if line.strip()]
    except UnicodeDecodeError:
        _fail("eval_task_file_invalid")
    if len(task_rows) != profile.task_count or len(set(task_rows)) != profile.task_count:
        _fail("eval_task_file_count_mismatch")

    if profile.image_manifest is not None:
        image_manifest = _resolve_config_path(project, profile.image_manifest, code="eval_image_manifest_unreadable")
        image_raw = _read_bytes(image_manifest, limit=MAX_TASK_BYTES, code="eval_image_manifest_unreadable")
        if _sha256(image_raw) != profile.image_sha256:
            _fail("eval_image_manifest_hash_mismatch")


def _git_output(arguments: Sequence[str], *, cwd: Path, code: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        _fail(code)
    if result.returncode != 0:
        _fail(code)
    return result.stdout


def _require_clean_git_worktree(path: Path, *, git_code: str, dirty_code: str) -> None:
    status = _git_output(["status", "--porcelain", "--untracked-files=normal"], cwd=path, code=git_code)
    if status:
        _fail(dirty_code)


def _mode_bits(path: Path, *, expected_type: int) -> int:
    try:
        metadata = path.lstat()
    except OSError:
        _fail("dataset_tree_unreadable")
    if stat.S_IFMT(metadata.st_mode) != expected_type:
        _fail("dataset_tree_entry_invalid")
    return stat.S_IMODE(metadata.st_mode)


def _dataset_tree_identity(root: Path) -> tuple[str, int, int]:
    if root.is_symlink():
        _fail("dataset_root_invalid")
    dataset = _resolve(root, code="dataset_root_unreadable")
    if not dataset.is_dir():
        _fail("dataset_root_invalid")
    digest = hashlib.sha256(b"tree-sha256-v2-mode-bits\0")
    file_count = 0
    directory_count = 0
    try:
        digest.update(_mode_bits(dataset, expected_type=stat.S_IFDIR).to_bytes(4, "big"))
        for current, directory_names, file_names in os.walk(dataset, topdown=True, followlinks=False):
            directory_names.sort()
            file_names.sort()
            current_path = Path(current)
            retained_directories: list[str] = []
            for name in directory_names:
                path = current_path / name
                if path.is_symlink():
                    _fail("dataset_tree_symlink_forbidden")
                if not path.is_dir():
                    _fail("dataset_tree_entry_invalid")
                relative = path.relative_to(dataset).as_posix().encode()
                digest.update(b"D")
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                digest.update(_mode_bits(path, expected_type=stat.S_IFDIR).to_bytes(4, "big"))
                directory_count += 1
                retained_directories.append(name)
            directory_names[:] = retained_directories
            for name in file_names:
                path = current_path / name
                if path.is_symlink():
                    _fail("dataset_tree_symlink_forbidden")
                if not path.is_file():
                    _fail("dataset_tree_entry_invalid")
                relative = path.relative_to(dataset).as_posix().encode()
                content_digest = hashlib.sha256()
                size = 0
                before = path.lstat()
                if not stat.S_ISREG(before.st_mode):
                    _fail("dataset_tree_entry_invalid")
                flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(path, flags)
                with os.fdopen(descriptor, "rb") as handle:
                    opened = os.fstat(handle.fileno())
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                        before.st_dev,
                        before.st_ino,
                    ):
                        _fail("dataset_tree_entry_changed")
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        size += len(chunk)
                        content_digest.update(chunk)
                    after = os.fstat(handle.fileno())
                current_metadata = path.lstat()
                if (
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, stat.S_IMODE(after.st_mode))
                    != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, stat.S_IMODE(before.st_mode))
                    or (
                        current_metadata.st_dev,
                        current_metadata.st_ino,
                        current_metadata.st_size,
                        current_metadata.st_mtime_ns,
                        stat.S_IMODE(current_metadata.st_mode),
                    )
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, stat.S_IMODE(after.st_mode))
                    or size != after.st_size
                ):
                    _fail("dataset_tree_entry_changed")
                digest.update(b"F")
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                digest.update(stat.S_IMODE(after.st_mode).to_bytes(4, "big"))
                digest.update(size.to_bytes(8, "big"))
                digest.update(content_digest.digest())
                file_count += 1
    except OSError:
        _fail("dataset_tree_unreadable")
    return digest.hexdigest(), file_count, directory_count


def validate_resume_location(resume_dir: Path, profile: ProfileContract) -> Path:
    """Restrict the dedicated resume input to this profile's canonical lane."""

    if resume_dir.is_symlink() or not resume_dir.is_absolute():
        _fail("resume_directory_invalid")
    resume = _resolve(resume_dir, code="resume_directory_unreadable")
    output_root = _resolve(EVAL_OUTPUT_ROOT, code="eval_output_root_unreadable")
    if resume.parent != output_root:
        _fail("resume_directory_outside_lane")
    suffix = resume.name.removeprefix(profile.default_output_prefix)
    if not resume.name.startswith(profile.default_output_prefix) or not suffix.isdigit() or suffix.startswith("0"):
        _fail("resume_directory_name_mismatch")
    return resume


def validate_repository(project_dir: Path, profile_name: str = "mobius") -> None:
    """Require checked-out, clean verifier and dataset revisions."""

    project = _resolve(project_dir, code="project_root_unreadable")
    _require_clean_git_worktree(project, git_code="project_git_invalid", dirty_code="project_worktree_dirty")

    submodule_status = _git_output(
        ["submodule", "status", "--", "deps/verifiers", "deps/renderers", "deps/pydantic-config"],
        cwd=project,
        code="project_submodules_invalid",
    ).splitlines()
    if len(submodule_status) != 3 or any(not row.startswith(" ") for row in submodule_status):
        _fail("project_submodules_not_checked_out")
    for directory, expected_revision, label in (
        ("verifiers", EXPECTED_VERIFIERS_REVISION, "verifier"),
        ("renderers", EXPECTED_RENDERERS_REVISION, "renderer"),
        ("pydantic-config", EXPECTED_PYDANTIC_CONFIG_REVISION, "pydantic_config"),
    ):
        checkout = project / "deps" / directory
        revision = _git_output(["rev-parse", "HEAD"], cwd=checkout, code=f"{label}_revision_invalid").strip()
        if revision != expected_revision:
            _fail(f"{label}_revision_mismatch")
        _require_clean_git_worktree(
            checkout,
            git_code=f"{label}_git_invalid",
            dirty_code=f"{label}_worktree_dirty",
        )

    profile = _profile(profile_name)
    if profile.dataset_revision is None:
        if (
            profile.dataset_tree_sha256 is None
            or profile.dataset_file_count is None
            or profile.dataset_directory_count is None
        ):
            _fail("dataset_tree_contract_missing")
        tree_sha256, file_count, directory_count = _dataset_tree_identity(Path(profile.dataset_dir))
        if (
            tree_sha256 != profile.dataset_tree_sha256
            or file_count != profile.dataset_file_count
            or directory_count != profile.dataset_directory_count
        ):
            _fail("dataset_tree_identity_mismatch")
        return
    dataset = _resolve(Path(profile.dataset_dir), code="dataset_root_unreadable")
    revision = _git_output(["rev-parse", "HEAD"], cwd=dataset, code="dataset_revision_invalid").strip()
    if revision != profile.dataset_revision:
        _fail("dataset_revision_mismatch")
    _require_clean_git_worktree(
        dataset,
        git_code="dataset_git_invalid",
        dirty_code="dataset_worktree_dirty",
    )


def _manifest_record(
    manifest: Mapping[str, Any],
    name: str,
    *,
    expected_source: Path,
    expected_snapshot: Path,
    expected_sha256: str,
) -> None:
    record = manifest.get(name)
    if not isinstance(record, dict):
        _fail(f"resume_{name}_record_invalid")
    _exact_keys(record, {"source", "snapshot", "sha256"}, code=f"resume_{name}_record_schema_invalid")
    source = record.get("source")
    if not isinstance(source, str) or not source:
        _fail(f"resume_{name}_source_invalid")
    if _resolve(Path(source), code=f"resume_{name}_source_invalid") != expected_source:
        _fail(f"resume_{name}_source_path_mismatch")
    if record.get("sha256") != expected_sha256:
        _fail(f"resume_{name}_record_hash_mismatch")
    snapshot = record.get("snapshot")
    if not isinstance(snapshot, str):
        _fail(f"resume_{name}_snapshot_invalid")
    if _resolve(Path(snapshot), code=f"resume_{name}_snapshot_invalid") != expected_snapshot:
        _fail(f"resume_{name}_snapshot_path_mismatch")


def _validate_snapshot(path: Path, expected_sha256: str, *, code: str, limit: int) -> bytes:
    raw = _read_bytes(path, limit=limit, code=code)
    if _sha256(raw) != expected_sha256:
        _fail(f"{code}_hash_mismatch")
    return raw


def _parse_provenance(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    raw = _read_bytes(path, limit=MAX_CONFIG_BYTES, code="resume_provenance_unreadable")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        _fail("resume_provenance_invalid")
    if not lines or any("=" not in line for line in lines):
        _fail("resume_provenance_invalid")

    base_lines: list[tuple[str, str]] = []
    resume_lines: list[tuple[str, str]] = []
    saw_resume = False
    for line in lines:
        key, value = line.split("=", 1)
        if not key or "\x00" in value:
            _fail("resume_provenance_invalid")
        if key.startswith("resume_"):
            saw_resume = True
            resume_lines.append((key, value))
        elif saw_resume:
            _fail("resume_provenance_order_invalid")
        else:
            base_lines.append((key, value))
    base = dict(base_lines)
    if len(base) != len(base_lines):
        _fail("resume_provenance_duplicate_base_key")

    resume_keys = [
        "resume_slurm_job_id",
        "resume_prime_rl",
        "resume_verifiers",
        "resume_renderers",
        "resume_pydantic_config",
        "resume_eval_config_sha256",
        "resume_inference_base_url",
        "resume_inference_deployment_id",
        "resume_inference_proxy_info_sha256",
        "resume_inference_proxy_litellm_config_sha256",
        "resume_dataset_tree_sha256",
        "resume_approval_task_file_sha256",
        "resume_approval_task_count",
    ]
    if len(resume_lines) % len(resume_keys) != 0:
        _fail("resume_provenance_incomplete_resume_block")
    blocks: list[dict[str, str]] = []
    for offset in range(0, len(resume_lines), len(resume_keys)):
        block_lines = resume_lines[offset : offset + len(resume_keys)]
        if [key for key, _ in block_lines] != resume_keys:
            _fail("resume_provenance_resume_block_schema_invalid")
        blocks.append(dict(block_lines))
    return base, blocks


def _validate_provenance(
    project_dir: Path,
    resume_dir: Path,
    profile: ProfileContract,
    proxy: ProxyMetadata,
) -> None:
    base, resume_blocks = _parse_provenance(resume_dir / "provenance.txt")
    expected_base_keys = {
        "prime_rl",
        "verifiers",
        "renderers",
        "pydantic_config",
        "eval_config_sha256",
        "inference_base_url",
        "inference_deployment_id",
        "inference_proxy_info_sha256",
        "inference_proxy_litellm_config_sha256",
        "dataset_tree_sha256",
        "slurm_job_id",
        "approval_task_file_sha256",
        "approval_task_count",
    }
    _exact_keys(base, expected_base_keys, code="resume_provenance_base_schema_invalid")
    current_revision = _git_output(["rev-parse", "HEAD"], cwd=project_dir, code="project_revision_invalid").strip()
    expected_values = {
        "prime_rl": current_revision,
        "verifiers": EXPECTED_VERIFIERS_REVISION,
        "renderers": EXPECTED_RENDERERS_REVISION,
        "pydantic_config": EXPECTED_PYDANTIC_CONFIG_REVISION,
        "eval_config_sha256": profile.config_sha256,
        "inference_base_url": f"{EXPECTED_PROXY_URL}/v1",
        "inference_deployment_id": "",
        "inference_proxy_info_sha256": proxy.proxy_info_sha256,
        "inference_proxy_litellm_config_sha256": proxy.proxy_litellm_config_sha256,
        "dataset_tree_sha256": profile.dataset_tree_sha256 or "",
        "approval_task_file_sha256": profile.task_sha256,
        "approval_task_count": str(profile.task_count),
    }
    for key, expected in expected_values.items():
        if base.get(key) != expected:
            _fail(f"resume_provenance_{key}_mismatch")
    if not base.get("slurm_job_id", "").isdigit():
        _fail("resume_provenance_slurm_job_invalid")

    resume_expected = {
        "resume_prime_rl": current_revision,
        "resume_verifiers": EXPECTED_VERIFIERS_REVISION,
        "resume_renderers": EXPECTED_RENDERERS_REVISION,
        "resume_pydantic_config": EXPECTED_PYDANTIC_CONFIG_REVISION,
        "resume_eval_config_sha256": profile.config_sha256,
        "resume_inference_base_url": f"{EXPECTED_PROXY_URL}/v1",
        "resume_inference_deployment_id": "",
        "resume_inference_proxy_info_sha256": proxy.proxy_info_sha256,
        "resume_inference_proxy_litellm_config_sha256": proxy.proxy_litellm_config_sha256,
        "resume_dataset_tree_sha256": profile.dataset_tree_sha256 or "",
        "resume_approval_task_file_sha256": profile.task_sha256,
        "resume_approval_task_count": str(profile.task_count),
    }
    for block in resume_blocks:
        if not block.get("resume_slurm_job_id", "").isdigit():
            _fail("resume_provenance_resume_slurm_job_invalid")
        for key, expected in resume_expected.items():
            if block.get(key) != expected:
                _fail(f"resume_provenance_{key}_mismatch")


def validate_resume(
    project_dir: Path,
    resume_dir: Path,
    profile_name: str,
    proxy: ProxyMetadata,
) -> Path:
    """Validate a saved run completely before allowing generic resume mode."""

    project = _resolve(project_dir, code="project_root_unreadable")
    profile = _profile(profile_name)
    if resume_dir.is_symlink():
        _fail("resume_directory_invalid")
    resume = _resolve(resume_dir, code="resume_directory_unreadable")
    if not resume.is_dir():
        _fail("resume_directory_invalid")
    inputs_path = resume / "inputs"
    if inputs_path.is_symlink():
        _fail("resume_inputs_invalid")
    inputs = _resolve(inputs_path, code="resume_inputs_unreadable")
    if not inputs.is_dir():
        _fail("resume_inputs_invalid")

    _, manifest = _load_json_file(inputs / "manifest.json", code="resume_input_manifest_invalid")
    expected_manifest_keys = {"config", "task_file"}
    if profile.image_manifest is not None:
        expected_manifest_keys.add("image_manifest")
    _exact_keys(manifest, expected_manifest_keys, code="resume_input_manifest_schema_invalid")

    source_config_path = inputs / "source_config.toml"
    task_snapshot_path = inputs / "task_file.txt"
    image_snapshot_path = inputs / "image_manifest.json"
    _manifest_record(
        manifest,
        "config",
        expected_source=_resolve(project / profile.config_file, code="eval_config_unreadable"),
        expected_snapshot=source_config_path,
        expected_sha256=profile.config_sha256,
    )
    _manifest_record(
        manifest,
        "task_file",
        expected_source=_resolve_config_path(project, profile.task_file, code="eval_task_file_unreadable"),
        expected_snapshot=task_snapshot_path,
        expected_sha256=profile.task_sha256,
    )
    if profile.image_sha256 is not None:
        _manifest_record(
            manifest,
            "image_manifest",
            expected_source=_resolve_config_path(
                project,
                profile.image_manifest,
                code="eval_image_manifest_unreadable",
            ),
            expected_snapshot=image_snapshot_path,
            expected_sha256=profile.image_sha256,
        )

    source_raw = _validate_snapshot(
        source_config_path,
        profile.config_sha256,
        code="resume_source_config",
        limit=MAX_CONFIG_BYTES,
    )
    current_source = _read_bytes(
        _resolve(project / profile.config_file, code="eval_config_unreadable"),
        limit=MAX_CONFIG_BYTES,
        code="eval_config_unreadable",
    )
    if source_raw != current_source:
        _fail("resume_source_config_drift")
    _validate_snapshot(
        task_snapshot_path,
        profile.task_sha256,
        code="resume_task_snapshot",
        limit=MAX_TASK_BYTES,
    )
    if profile.image_sha256 is not None:
        _validate_snapshot(
            image_snapshot_path,
            profile.image_sha256,
            code="resume_image_snapshot",
            limit=MAX_TASK_BYTES,
        )

    saved_config_raw = _read_bytes(resume / "config.toml", limit=MAX_CONFIG_BYTES, code="resume_config_unreadable")
    saved_config = _parse_toml(saved_config_raw, code="resume_config_invalid")
    _validate_common_eval_contract(saved_config, profile, resolved=True, resume_dir=resume)
    _validate_provenance(project, resume, profile, proxy)
    return resume


def validate_launch(
    project_dir: Path,
    deployment_root: Path,
    proxy_info_path: Path,
    config_path: Path,
    *,
    profile_name: str = "mobius",
    resume_dir: Path | None = None,
    transport: MetadataTransport | None = None,
    validate_git: bool = True,
    expected_spec_sha256: str = EXPECTED_SPEC_SHA256,
    expected_proxy_url: str = EXPECTED_PROXY_URL,
) -> ProxyMetadata:
    validate_eval_config(project_dir, config_path, profile_name)
    if validate_git:
        validate_repository(project_dir, profile_name)
    proxy = validate_deployment(
        deployment_root,
        proxy_info_path,
        expected_spec_sha256=expected_spec_sha256,
        expected_proxy_url=expected_proxy_url,
    )
    validate_runtime_metadata(proxy, transport=transport)
    if resume_dir is not None:
        validated_resume = validate_resume_location(resume_dir, _profile(profile_name))
        validate_resume(project_dir, validated_resume, profile_name, proxy)
    return proxy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--deployment-root", required=True, type=Path)
    parser.add_argument("--proxy-info", required=True, type=Path)
    parser.add_argument("--eval-config", required=True, type=Path)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="mobius")
    parser.add_argument("--resume-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        proxy = validate_launch(
            args.project_dir,
            args.deployment_root,
            args.proxy_info,
            args.eval_config,
            profile_name=args.profile,
            resume_dir=args.resume_dir,
        )
    except SharedKimiValidationError as error:
        print(f"shared_kimi_validation_error:{error}", file=sys.stderr)
        return 2
    except Exception:
        print("shared_kimi_validation_error:unexpected_failure", file=sys.stderr)
        return 2

    profile = _profile(args.profile)
    print(
        "\t".join(
            (
                proxy.proxy_info_sha256,
                str(EXPECTED_ROUTES),
                str(profile.max_concurrent),
                str(profile.http_concurrent),
                str(profile.max_concurrent - profile.http_concurrent),
                profile.config_sha256,
                proxy.proxy_litellm_config_sha256,
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
