#!/usr/bin/env python3
"""Validate one immutable stock-single Kimi capacity attestation.

The capacity probe is the authority for a concrete deployment epoch.  This
module deliberately derives the endpoint identifier and source hashes from a
caller-supplied, SHA256-pinned receipt instead of another dated source-code
constant.  It retains no model output or task identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CAPACITY_KIND = "kimi-stock-capacity-probe"
MODEL = "Kimi-K3"
BACKEND_MODEL = "openai/Kimi-K3"
CONCURRENCY = 64
STICKY_TTL_SECONDS = 172_800
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
DEPLOYMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
JOB_ID_RE = re.compile(r"[1-9][0-9]*\Z")
MAX_RECEIPT_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024


class StockEndpointBindingError(ValueError):
    """One stable failure for an invalid or changed deployment attestation."""


@dataclass(frozen=True, slots=True)
class StockEndpointBinding:
    capacity_receipt_path: Path
    capacity_receipt_sha256: str
    deployment_root: Path
    deployment_id: str
    endpoint_job_id: str
    endpoint_jobs_sha256: str
    endpoint_authority_sha256: str
    endpoint_bundle_sha256: str
    endpoint_file_sha256: str
    source_spec_sha256: str
    source_proxy_config_sha256: str
    sticky_routing: bool
    sticky_ttl_seconds: int | None

    @property
    def public_record(self) -> dict[str, Any]:
        return {
            "capacity_receipt_sha256": self.capacity_receipt_sha256,
            "deployment_id": self.deployment_id,
            "deployment_root": str(self.deployment_root),
            "endpoint_job_id": self.endpoint_job_id,
            "endpoint_jobs_sha256": self.endpoint_jobs_sha256,
            "endpoint_authority_sha256": self.endpoint_authority_sha256,
            "endpoint_bundle_sha256": self.endpoint_bundle_sha256,
            "source_spec_sha256": self.source_spec_sha256,
            "source_proxy_config_sha256": self.source_proxy_config_sha256,
            "proxy_sticky_routing": self.sticky_routing,
            "proxy_sticky_ttl_seconds": self.sticky_ttl_seconds,
            "single_backend_stable": True,
            "production_router_policy": "consistent_hash",
        }


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _strict_json(body: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise StockEndpointBindingError("capacity_receipt_invalid")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                StockEndpointBindingError("capacity_receipt_invalid")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, StockEndpointBindingError) as error:
        raise StockEndpointBindingError("capacity_receipt_invalid") from error
    if not isinstance(value, dict):
        raise StockEndpointBindingError("capacity_receipt_invalid")
    return value


def _read_regular(path: Path, *, private: bool, maximum_bytes: int) -> bytes:
    try:
        canonical = path.resolve(strict=True)
        before = path.lstat()
    except (OSError, RuntimeError) as error:
        raise StockEndpointBindingError("capacity_artifact_invalid") from error
    if canonical != path or path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise StockEndpointBindingError("capacity_artifact_invalid")
    if private and (before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600):
        raise StockEndpointBindingError("capacity_artifact_invalid")
    try:
        with path.open("rb") as handle:
            body = handle.read(maximum_bytes + 1)
        after = path.lstat()
    except OSError as error:
        raise StockEndpointBindingError("capacity_artifact_invalid") from error
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_uid,
        item.st_nlink,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if identity(before) != identity(after) or len(body) != before.st_size or len(body) > maximum_bytes:
        raise StockEndpointBindingError("capacity_artifact_changed")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, str | int]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _receipt_artifact(record: object, *, name: str) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise StockEndpointBindingError("capacity_receipt_invalid")
    path = Path(str(record.get("path", "")))
    body = _read_regular(path, private=False, maximum_bytes=MAX_SOURCE_BYTES)
    if record != {"path": str(path), "sha256": _sha256(body)}:
        raise StockEndpointBindingError(f"{name}_changed")
    return path, body


def _one_backend(proxy_body: bytes) -> tuple[str, bool, int | None]:
    try:
        proxy = yaml.safe_load(proxy_body.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise StockEndpointBindingError("proxy_config_invalid") from error
    entries = proxy.get("model_list") if isinstance(proxy, dict) else None
    settings = proxy.get("litellm_settings") if isinstance(proxy, dict) else None
    router = proxy.get("router_settings") if isinstance(proxy, dict) else None
    if (
        not isinstance(entries, list)
        or len(entries) != 1
        or not isinstance(entries[0], dict)
        or entries[0].get("model_name") != MODEL
        or not isinstance(entries[0].get("litellm_params"), dict)
        or not isinstance(settings, dict)
        or settings.get("request_timeout") != 600
        or settings.get("num_retries") != 2
        or not isinstance(router, dict)
        or router.get("routing_strategy") != "simple-shuffle"
    ):
        raise StockEndpointBindingError("proxy_config_invalid")
    params = entries[0]["litellm_params"]
    if set(params) != {"api_base", "api_key", "model"} or params.get("api_key") != "EMPTY" or params.get(
        "model"
    ) != BACKEND_MODEL:
        raise StockEndpointBindingError("proxy_config_invalid")
    value = params.get("api_base")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise StockEndpointBindingError("proxy_config_invalid") from error
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65_535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise StockEndpointBindingError("proxy_config_invalid")
    url = urllib.parse.urlunsplit(("http", parsed.netloc, "", "", ""))
    checks = router.get("optional_pre_call_checks")
    sticky = router.get("enable_pre_call_checks") is True and checks == ["session_affinity"]
    ttl = router.get("deployment_affinity_ttl_seconds") if sticky else None
    if sticky and (type(ttl) is not int or ttl < 1):
        raise StockEndpointBindingError("proxy_config_invalid")
    return url, sticky, ttl


def _validate_spec(body: bytes) -> None:
    try:
        document = yaml.safe_load(body.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise StockEndpointBindingError("deployment_spec_invalid") from error
    spec = document.get("spec") if isinstance(document, dict) else None
    worker = spec.get("worker") if isinstance(spec, dict) else None
    proxy = spec.get("proxy") if isinstance(spec, dict) else None
    coordinator = spec.get("coordinator") if isinstance(spec, dict) else None
    if (
        not isinstance(spec, dict)
        or spec.get("model") != "kimi-k3"
        or spec.get("served_model_name") != MODEL
        or spec.get("num_endpoints") != 1
        or not isinstance(worker, dict)
        or worker.get("kind") != "vllm"
        or worker.get("sbatch_params", {}).get("time_limit") != "7-00:00:00"
        or worker.get("sbatch_params", {}).get("gpus_per_endpoint") != 16
        or worker.get("engine", {}).get("tensor_parallel") != 16
        or not isinstance(proxy, dict)
        or proxy.get("kind") != "litellm"
        or proxy.get("sbatch_params", {}).get("time_limit") != "7-00:00:00"
        or not isinstance(coordinator, dict)
        or coordinator.get("sbatch_params", {}).get("time_limit") != "7-00:00:00"
    ):
        raise StockEndpointBindingError("deployment_spec_invalid")


def load_capacity_binding(
    path: Path,
    expected_sha256: str,
    *,
    require_sticky: bool = False,
    sticky_ttl_seconds: int = STICKY_TTL_SECONDS,
) -> tuple[StockEndpointBinding, bytes]:
    """Reopen a c64 receipt and every deployment artifact it pins."""

    if SHA256_RE.fullmatch(str(expected_sha256)) is None:
        raise StockEndpointBindingError("capacity_receipt_invalid")
    receipt_path = path.resolve(strict=True)
    if receipt_path != path:
        raise StockEndpointBindingError("capacity_receipt_invalid")
    receipt_body = _read_regular(receipt_path, private=True, maximum_bytes=MAX_RECEIPT_BYTES)
    if _sha256(receipt_body) != expected_sha256:
        raise StockEndpointBindingError("capacity_receipt_changed")
    value = _strict_json(receipt_body)
    deployment = value.get("deployment")
    concurrency = value.get("concurrency")
    completions = value.get("completions")
    model = value.get("model_identity")
    artifacts = value.get("artifacts")
    metrics = value.get("metrics")
    in_flight = metrics.get("in_flight") if isinstance(metrics, dict) else None
    if (
        set(value)
        != {
            "artifacts",
            "completions",
            "concurrency",
            "deployment",
            "endpoint_unchanged",
            "kind",
            "metrics",
            "model_identity",
            "request_contract",
            "schema_version",
            "state",
            "timings",
        }
        or value.get("schema_version") != 1
        or value.get("kind") != CAPACITY_KIND
        or value.get("state") != "passed"
        or value.get("endpoint_unchanged") is not True
        or not isinstance(deployment, dict)
        or set(deployment) != {"endpoint_authority_sha256", "endpoint_job_id", "id", "model"}
        or DEPLOYMENT_ID_RE.fullmatch(str(deployment.get("id", ""))) is None
        or deployment.get("model") != MODEL
        or JOB_ID_RE.fullmatch(str(deployment.get("endpoint_job_id", ""))) is None
        or SHA256_RE.fullmatch(str(deployment.get("endpoint_authority_sha256", ""))) is None
        or concurrency != {"client_peak_in_flight": CONCURRENCY, "configured": CONCURRENCY}
        or not isinstance(completions, dict)
        or any(
            completions.get(key) != CONCURRENCY
            for key in (
                "attempted",
                "http_200",
                "model_matches",
                "reasoning_present",
                "requested",
                "successful",
                "tool_call_responses",
                "tool_calls_total",
            )
        )
        or completions.get("raw_reasoning_present", 0) + completions.get("reasoning_content_present", 0)
        != CONCURRENCY
        or completions.get("response_errors") != 0
        or completions.get("transport_errors") != 0
        or SHA256_RE.fullmatch(str(completions.get("response_digests_sha256", ""))) is None
        or model
        != {
            "backend_model": BACKEND_MODEL,
            "confirmed": True,
            "response_errors": 0,
            "served_model": MODEL,
            "transport_errors": 0,
        }
        or not isinstance(artifacts, dict)
        or set(artifacts) != {"endpoint_file", "proxy_config", "spec"}
        or not isinstance(in_flight, dict)
        or in_flight.get("maximum_running", 0) < CONCURRENCY
        or in_flight.get("maximum_waiting") != 0
        or in_flight.get("response_errors") != 0
        or in_flight.get("transport_errors") != 0
        or not isinstance(metrics, dict)
        or metrics.get("response_errors") != 0
        or metrics.get("transport_errors") != 0
    ):
        raise StockEndpointBindingError("capacity_receipt_invalid")

    spec_path, spec_body = _receipt_artifact(artifacts["spec"], name="deployment_spec")
    proxy_path, proxy_body = _receipt_artifact(artifacts["proxy_config"], name="proxy_config")
    endpoint_path, endpoint_body = _receipt_artifact(artifacts["endpoint_file"], name="endpoint_file")
    root = spec_path.parent
    deployment_id = str(deployment["id"])
    endpoint_job_id = str(deployment["endpoint_job_id"])
    if (
        root.name != deployment_id
        or proxy_path != root / "proxy_litellm_config.yaml"
        or endpoint_path != root / "endpoints" / f"{endpoint_job_id}.json"
    ):
        raise StockEndpointBindingError("deployment_binding_invalid")
    _validate_spec(spec_body)
    worker_url, sticky, sticky_ttl = _one_backend(proxy_body)
    try:
        endpoint = _strict_json(endpoint_body)
        host = endpoint["host"]
        port = endpoint["port"]
    except (KeyError, TypeError) as error:
        raise StockEndpointBindingError("endpoint_file_invalid") from error
    if (
        set(endpoint) not in ({"host", "port", "started_at"}, {"host", "port", "started_at", "jobid"})
        or not isinstance(host, str)
        or not host
        or type(port) is not int
        or not 1 <= port <= 65_535
        or ("jobid" in endpoint and str(endpoint["jobid"]) != endpoint_job_id)
        or worker_url != f"http://{host}:{port}"
    ):
        raise StockEndpointBindingError("endpoint_file_invalid")
    authority_sha256 = _sha256(f"{worker_url}/v1".encode())
    endpoint_bundle_sha256 = _sha256(f"{authority_sha256}\n".encode())
    if deployment["endpoint_authority_sha256"] != authority_sha256:
        raise StockEndpointBindingError("deployment_binding_invalid")
    if require_sticky and (not sticky or sticky_ttl != sticky_ttl_seconds):
        raise StockEndpointBindingError("sticky_routing_required")
    binding = StockEndpointBinding(
        capacity_receipt_path=receipt_path,
        capacity_receipt_sha256=expected_sha256,
        deployment_root=root,
        deployment_id=deployment_id,
        endpoint_job_id=endpoint_job_id,
        endpoint_jobs_sha256=_sha256(f"{endpoint_job_id}\n".encode()),
        endpoint_authority_sha256=authority_sha256,
        endpoint_bundle_sha256=endpoint_bundle_sha256,
        endpoint_file_sha256=_sha256(endpoint_body),
        source_spec_sha256=_sha256(spec_body),
        source_proxy_config_sha256=_sha256(proxy_body),
        sticky_routing=sticky,
        sticky_ttl_seconds=sticky_ttl,
    )
    return binding, receipt_body
