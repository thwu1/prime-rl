#!/usr/bin/env python3
"""Fail-closed preflight for the shared 24-route Kimi Mobius rollout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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

EXPECTED_MODEL = "Kimi-K3"
EXPECTED_ROUTES = 24
EXPECTED_ROLLOUT_CONCURRENCY = 64
EXPECTED_HTTP_CONCURRENCY = 24
EXPECTED_WAITING_REQUESTS = EXPECTED_ROLLOUT_CONCURRENCY - EXPECTED_HTTP_CONCURRENCY
EXPECTED_PROXY_URL = "http://cpu-132-021:8103"
EXPECTED_SPEC_SHA256 = "ab00213a43083eba87f8b5999a3046e8d27ebe42b933ee845fd0cf4928b266e2"
EXPECTED_TASK_SHA256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"
EXPECTED_IMAGE_SHA256 = "118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009"
EXPECTED_DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
EXPECTED_VERIFIERS_REVISION = "04d999177f320e195e3335593688934f32e899d3"
EXPECTED_TASK_FILE = "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt"
EXPECTED_CONFIG_FILE = (
    "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/mobius_kimi_k3_shared24_2500.toml"
)
EXPECTED_DATASET_DIR = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9"
EXPECTED_IMAGE_MANIFEST = "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_TASK_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
JOB_FILE_RE = re.compile(r"^[1-9][0-9]*\.json$")


class SharedKimiValidationError(ValueError):
    """A fixed, non-secret launch-contract error."""


@dataclass(frozen=True)
class ProxyMetadata:
    url: str
    api_key: str
    proxy_info_sha256: str


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
        if path.is_symlink() or not path.is_file():
            _fail(code)
        with path.open("rb") as handle:
            value = handle.read(limit + 1)
    except OSError:
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
    if isinstance(actual, bool) != isinstance(expected, bool) or actual != expected:
        _fail(code)


def validate_eval_config(project_dir: Path, config_path: Path) -> None:
    """Bind the launch to the exact high-concurrency trace-retention contract."""

    project = _resolve(project_dir, code="project_root_unreadable")
    expected_config = _resolve(project / EXPECTED_CONFIG_FILE, code="eval_config_unreadable")
    if _resolve(config_path, code="eval_config_unreadable") != expected_config:
        _fail("eval_config_path_mismatch")
    config_raw = _read_bytes(expected_config, limit=MAX_CONFIG_BYTES, code="eval_config_unreadable")
    try:
        config = tomllib.loads(config_raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        _fail("eval_config_invalid")

    expected_top_level = {
        "model": EXPECTED_MODEL,
        "num_tasks": 2_500,
        "num_rollouts": 1,
        "max_concurrent": EXPECTED_ROLLOUT_CONCURRENCY,
        "multiplex": EXPECTED_ROLLOUT_CONCURRENCY,
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
        "max_connections": EXPECTED_HTTP_CONCURRENCY,
        "max_keepalive_connections": EXPECTED_HTTP_CONCURRENCY,
    }
    for key, expected in expected_client.items():
        _require_config_value(client.get(key), expected, code=f"eval_client_{key}_mismatch")
    if "headers" in client or "extra_headers" in client:
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
    for key, expected in {
        "temperature": 1.0,
        "top_p": 1.0,
        "max_tokens": 32_768,
        "reasoning_effort": "max",
    }.items():
        _require_config_value(sampling.get(key), expected, code=f"eval_sampling_{key}_mismatch")
    if sampling.get("chat_template_kwargs") != {
        "enable_thinking": True,
        "preserve_thinking": True,
    }:
        _fail("eval_reasoning_retention_mismatch")

    taskset = config.get("taskset")
    if not isinstance(taskset, dict):
        _fail("eval_taskset_invalid")
    expected_taskset = {
        "id": "terminal-bench-vmvm",
        "dataset_dir": EXPECTED_DATASET_DIR,
        "dataset_revision": EXPECTED_DATASET_REVISION,
        "task_file": EXPECTED_TASK_FILE,
        "task_file_sha256": EXPECTED_TASK_SHA256,
        "image_prefix": "vmvm-registry.fbinfra.net/terminal_bench",
        "image_tag": "mobius-9b6988a3faf0",
        "image_manifest": EXPECTED_IMAGE_MANIFEST,
        "image_manifest_sha256": EXPECTED_IMAGE_SHA256,
        "ignore_dockerfile": True,
        "verifier_runtime_retries": 2,
        "timeout_multiplier": 2.0,
        "resource_multiplier": 2.0,
    }
    for key, expected in expected_taskset.items():
        _require_config_value(taskset.get(key), expected, code=f"eval_taskset_{key}_mismatch")
    if "tasks" in taskset:
        _fail("eval_inline_tasks_forbidden")

    task_file = _resolve_config_path(project, taskset.get("task_file"), code="eval_task_file_unreadable")
    task_raw = _read_bytes(task_file, limit=MAX_TASK_BYTES, code="eval_task_file_unreadable")
    if _sha256(task_raw) != EXPECTED_TASK_SHA256:
        _fail("eval_task_file_hash_mismatch")
    try:
        task_rows = [line for line in task_raw.decode("utf-8").splitlines() if line.strip()]
    except UnicodeDecodeError:
        _fail("eval_task_file_invalid")
    if len(task_rows) != 2_500 or len(set(task_rows)) != 2_500:
        _fail("eval_task_file_count_mismatch")

    image_manifest = _resolve_config_path(
        project,
        taskset.get("image_manifest"),
        code="eval_image_manifest_unreadable",
    )
    image_raw = _read_bytes(image_manifest, limit=MAX_TASK_BYTES, code="eval_image_manifest_unreadable")
    if _sha256(image_raw) != EXPECTED_IMAGE_SHA256:
        _fail("eval_image_manifest_hash_mismatch")

    harness = config.get("harness")
    if not isinstance(harness, dict):
        _fail("eval_harness_invalid")
    for key, expected in {"id": "mini-swe-agent", "version": "2.2.8", "config_file": "mini"}.items():
        _require_config_value(harness.get(key), expected, code=f"eval_harness_{key}_mismatch")
    overrides = harness.get("config_overrides")
    if not isinstance(overrides, list) or "model.model_kwargs.timeout=15000" not in overrides:
        _fail("eval_model_timeout_mismatch")
    environment = harness.get("env")
    if not isinstance(environment, dict) or environment.get("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT") != "10":
        _fail("eval_model_retry_mismatch")
    runtime = harness.get("runtime")
    if not isinstance(runtime, dict):
        _fail("eval_runtime_invalid")
    for key, expected in {
        "type": "vmvm",
        "session_timeout": 43_200,
        "tenant_id": "async_2347641",
        "lease_ttl": "60s",
        "max_session_buffer_size": 67_108_864,
    }.items():
        _require_config_value(runtime.get(key), expected, code=f"eval_runtime_{key}_mismatch")

    timeouts = config.get("timeout")
    if not isinstance(timeouts, dict):
        _fail("eval_timeouts_invalid")
    for key, expected in {
        "setup": 3_600,
        "rollout": 36_000,
        "finalize": 3_600,
        "scoring": 21_600,
    }.items():
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


def validate_repository(project_dir: Path) -> None:
    """Require checked-out, clean verifier and dataset revisions."""

    project = _resolve(project_dir, code="project_root_unreadable")
    if _git_output(["status", "--porcelain", "--untracked-files=normal"], cwd=project, code="project_git_invalid"):
        _fail("project_worktree_dirty")

    submodule_status = _git_output(
        ["submodule", "status", "--", "deps/verifiers", "deps/renderers", "deps/pydantic-config"],
        cwd=project,
        code="project_submodules_invalid",
    ).splitlines()
    if len(submodule_status) != 3 or any(not row.startswith(" ") for row in submodule_status):
        _fail("project_submodules_not_checked_out")
    verifier = project / "deps" / "verifiers"
    verifier_revision = _git_output(["rev-parse", "HEAD"], cwd=verifier, code="verifier_revision_invalid").strip()
    if verifier_revision != EXPECTED_VERIFIERS_REVISION:
        _fail("verifier_revision_mismatch")
    if _git_output(["status", "--porcelain", "--untracked-files=normal"], cwd=verifier, code="verifier_git_invalid"):
        _fail("verifier_worktree_dirty")

    dataset = _resolve(Path(EXPECTED_DATASET_DIR), code="dataset_root_unreadable")
    revision = _git_output(["rev-parse", "HEAD"], cwd=dataset, code="dataset_revision_invalid").strip()
    if revision != EXPECTED_DATASET_REVISION:
        _fail("dataset_revision_mismatch")
    try:
        result = subprocess.run(
            ["git", "diff-index", "--quiet", "HEAD", "--"],
            cwd=dataset,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        _fail("dataset_git_invalid")
    if result.returncode != 0:
        _fail("dataset_worktree_dirty")


def validate_launch(
    project_dir: Path,
    deployment_root: Path,
    proxy_info_path: Path,
    config_path: Path,
    *,
    transport: MetadataTransport | None = None,
    validate_git: bool = True,
    expected_spec_sha256: str = EXPECTED_SPEC_SHA256,
    expected_proxy_url: str = EXPECTED_PROXY_URL,
) -> ProxyMetadata:
    validate_eval_config(project_dir, config_path)
    if validate_git:
        validate_repository(project_dir)
    proxy = validate_deployment(
        deployment_root,
        proxy_info_path,
        expected_spec_sha256=expected_spec_sha256,
        expected_proxy_url=expected_proxy_url,
    )
    validate_runtime_metadata(proxy, transport=transport)
    return proxy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--deployment-root", required=True, type=Path)
    parser.add_argument("--proxy-info", required=True, type=Path)
    parser.add_argument("--eval-config", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        proxy = validate_launch(
            args.project_dir,
            args.deployment_root,
            args.proxy_info,
            args.eval_config,
        )
    except SharedKimiValidationError as error:
        print(f"shared_kimi_validation_error:{error}", file=sys.stderr)
        return 2
    except Exception:
        print("shared_kimi_validation_error:unexpected_failure", file=sys.stderr)
        return 2

    print(
        "\t".join(
            (
                proxy.proxy_info_sha256,
                str(EXPECTED_ROUTES),
                str(EXPECTED_HTTP_CONCURRENCY),
                str(EXPECTED_WAITING_REQUESTS),
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
