#!/usr/bin/env python3
"""Atomic, secret-free proof that an eval finished inside its route guard."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deployment_endpoint import EndpointBindingError, validate_endpoint_binding
from deployment_proxy_policy import (
    DeploymentProxyPolicyError,
    validate_proxy_policy_binding,
)
from inference_route_generation import RouteGenerationError, validate_route_generation

SCHEMA_VERSION = 1
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_INVOCATIONS_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SLURM_JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
UTC_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")


class GuardReceiptError(ValueError):
    """A route-guard success receipt is absent, stale, or malformed."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise GuardReceiptError("guard_receipt_invalid")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise GuardReceiptError("guard_receipt_invalid")


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def stable_sha256_file(path: Path, *, label: str) -> tuple[Path, str]:
    digest = hashlib.sha256()
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise GuardReceiptError(f"{label}_unreadable")
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = resolved.stat(follow_symlinks=False)
    except OSError as error:
        raise GuardReceiptError(f"{label}_unreadable") from error
    if _stat_signature(before) != _stat_signature(after):
        raise GuardReceiptError(f"{label}_changed")
    return resolved, digest.hexdigest()


def _stable_read_bytes(
    path: Path,
    *,
    label: str,
    limit: int,
) -> tuple[Path, bytes, str]:
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise GuardReceiptError(f"{label}_unreadable")
        raw = resolved.read_bytes()
        after = resolved.stat(follow_symlinks=False)
    except OSError as error:
        raise GuardReceiptError(f"{label}_unreadable") from error
    if _stat_signature(before) != _stat_signature(after) or len(raw) != after.st_size:
        raise GuardReceiptError(f"{label}_changed")
    return resolved, raw, hashlib.sha256(raw).hexdigest()


def artifact_record(path: Path, *, label: str) -> dict[str, str]:
    resolved, digest = stable_sha256_file(path, label=label)
    return {"path": str(resolved), "sha256": digest}


def validate_eval_invocations(
    path: Path,
    *,
    eval_run_identity_sha256: str,
    eval_run_role: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Require the single fresh invocation permitted for guarded Kimi runs."""

    if (
        not isinstance(eval_run_identity_sha256, str)
        or SHA256_RE.fullmatch(eval_run_identity_sha256) is None
        or eval_run_role not in {"smoke", "tb4", "mobius"}
    ):
        raise GuardReceiptError("eval_invocations_binding_invalid")
    resolved, raw, digest = _stable_read_bytes(
        path,
        label="eval_invocations",
        limit=MAX_INVOCATIONS_BYTES,
    )
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise GuardReceiptError("eval_invocations_invalid")
    try:
        record = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuardReceiptError("eval_invocations_invalid") from error
    if (
        not isinstance(record, dict)
        or set(record)
        != {
            "schema_version",
            "eval_run_identity_sha256",
            "role",
            "resume",
            "host",
            "slurm_job_id",
        }
        or record.get("schema_version") != 1
        or record.get("eval_run_identity_sha256") != eval_run_identity_sha256
        or record.get("role") != eval_run_role
        or record.get("resume") is not False
        or not isinstance(record.get("host"), str)
        or not record["host"].strip()
        or any(character in record["host"] for character in "\r\n")
        or not isinstance(record.get("slurm_job_id"), str)
        or SLURM_JOB_ID_RE.fullmatch(record["slurm_job_id"]) is None
    ):
        raise GuardReceiptError("eval_invocations_invalid")
    return record, {"path": str(resolved), "sha256": digest}


def _validate_artifact(value: Any, *, label: str) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not Path(value["path"]).is_absolute()
        or os.path.normpath(value["path"]) != value["path"]
        or not isinstance(value.get("sha256"), str)
        or SHA256_RE.fullmatch(value["sha256"]) is None
    ):
        raise GuardReceiptError(f"{label}_invalid")
    return {"path": value["path"], "sha256": value["sha256"]}


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise GuardReceiptError("guard_receipt_invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GuardReceiptError("guard_receipt_invalid") from error
    return value


def build_guard_success_receipt(
    *,
    eval_run_identity_sha256: str,
    eval_run_role: str,
    eval_run_identity: Path,
    eval_invocations: Path,
    results: Path,
    deployment_id: str,
    deployment_spec_sha256: str,
    readiness_checkpoint: Path,
    readiness_checkpoint_sha256: str,
    endpoint: Any,
    serving_route_generation: Any,
    proxy_policy: Any,
) -> dict[str, Any]:
    """Hash final artifacts and build a self-hashed success receipt."""

    if (
        not isinstance(eval_run_identity_sha256, str)
        or SHA256_RE.fullmatch(eval_run_identity_sha256) is None
        or not isinstance(deployment_id, str)
        or not deployment_id
        or not isinstance(deployment_spec_sha256, str)
        or SHA256_RE.fullmatch(deployment_spec_sha256) is None
        or not isinstance(readiness_checkpoint_sha256, str)
        or SHA256_RE.fullmatch(readiness_checkpoint_sha256) is None
    ):
        raise GuardReceiptError("guard_receipt_binding_invalid")
    try:
        endpoint_binding = validate_endpoint_binding(endpoint)
        route_generation = validate_route_generation(serving_route_generation)
        policy = validate_proxy_policy_binding(proxy_policy)
    except (
        EndpointBindingError,
        RouteGenerationError,
        DeploymentProxyPolicyError,
    ) as error:
        raise GuardReceiptError("guard_receipt_binding_invalid") from error
    _, invocation_artifact = validate_eval_invocations(
        eval_invocations,
        eval_run_identity_sha256=eval_run_identity_sha256,
        eval_run_role=eval_run_role,
    )
    artifacts = {
        "eval_run_identity": artifact_record(
            eval_run_identity,
            label="eval_run_identity",
        ),
        "eval_invocations": invocation_artifact,
        "results": artifact_record(results, label="results"),
    }
    run_dir = Path(artifacts["results"]["path"]).parent
    expected_paths = {
        "eval_run_identity": run_dir / "eval_run_identity.json",
        "eval_invocations": run_dir / "eval_invocations.jsonl",
        "results": run_dir / "results.jsonl",
    }
    if any(Path(artifacts[name]["path"]) != path for name, path in expected_paths.items()):
        raise GuardReceiptError("guard_receipt_artifact_path_mismatch")
    readiness = artifact_record(readiness_checkpoint, label="readiness_checkpoint")
    if readiness["sha256"] != readiness_checkpoint_sha256:
        raise GuardReceiptError("readiness_checkpoint_sha256_mismatch")
    body = {
        "schema_version": SCHEMA_VERSION,
        "state": "passed",
        "evaluator_exit_code": 0,
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "eval_run_role": eval_run_role,
        "eval_run_identity_sha256": eval_run_identity_sha256,
        "deployment": {
            "id": deployment_id,
            "spec_sha256": deployment_spec_sha256,
            "readiness_checkpoint": readiness,
            "endpoint": endpoint_binding,
            "serving_route_generation": route_generation,
            "proxy_policy": policy,
        },
        "artifacts": artifacts,
    }
    return {
        **body,
        "guard_success_receipt_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
    }


def write_guard_success_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Publish a fresh receipt atomically with mode 0600."""

    parent = path.parent.resolve(strict=True)
    resolved = parent / path.name
    if path.name != "route_guard_success.json":
        raise GuardReceiptError("guard_receipt_path_mismatch")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8"))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def load_guard_success_receipt(
    path: Path,
) -> dict[str, Any]:
    """Strictly validate a receipt and rehash its immutable run files."""

    resolved, raw, _ = _stable_read_bytes(
        path,
        label="guard_receipt",
        limit=MAX_RECEIPT_BYTES,
    )
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuardReceiptError("guard_receipt_invalid") from error
    expected_keys = {
        "schema_version",
        "state",
        "evaluator_exit_code",
        "completed_at",
        "eval_run_role",
        "eval_run_identity_sha256",
        "deployment",
        "artifacts",
        "guard_success_receipt_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise GuardReceiptError("guard_receipt_invalid")
    self_hash = value.get("guard_success_receipt_sha256")
    body = {key: item for key, item in value.items() if key != "guard_success_receipt_sha256"}
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("state") != "passed"
        or value.get("evaluator_exit_code") != 0
        or not isinstance(self_hash, str)
        or SHA256_RE.fullmatch(self_hash) is None
        or hashlib.sha256(canonical_json(body)).hexdigest() != self_hash
        or not isinstance(value.get("eval_run_identity_sha256"), str)
        or SHA256_RE.fullmatch(value["eval_run_identity_sha256"]) is None
        or value.get("eval_run_role") not in {"smoke", "tb4", "mobius"}
    ):
        raise GuardReceiptError("guard_receipt_invalid")
    _validate_timestamp(value.get("completed_at"))
    deployment = value.get("deployment")
    if not isinstance(deployment, dict) or set(deployment) != {
        "id",
        "spec_sha256",
        "readiness_checkpoint",
        "endpoint",
        "serving_route_generation",
        "proxy_policy",
    }:
        raise GuardReceiptError("guard_receipt_deployment_invalid")
    if (
        not isinstance(deployment.get("id"), str)
        or not deployment["id"]
        or not isinstance(deployment.get("spec_sha256"), str)
        or SHA256_RE.fullmatch(deployment["spec_sha256"]) is None
    ):
        raise GuardReceiptError("guard_receipt_deployment_invalid")
    readiness = _validate_artifact(
        deployment.get("readiness_checkpoint"),
        label="guard_receipt_readiness",
    )
    try:
        endpoint = validate_endpoint_binding(deployment.get("endpoint"))
        generation = validate_route_generation(deployment.get("serving_route_generation"))
        policy = validate_proxy_policy_binding(deployment.get("proxy_policy"))
    except (
        EndpointBindingError,
        RouteGenerationError,
        DeploymentProxyPolicyError,
    ) as error:
        raise GuardReceiptError("guard_receipt_deployment_invalid") from error
    artifacts_value = value.get("artifacts")
    if not isinstance(artifacts_value, dict) or set(artifacts_value) != {
        "eval_run_identity",
        "eval_invocations",
        "results",
    }:
        raise GuardReceiptError("guard_receipt_artifacts_invalid")
    artifacts = {
        name: _validate_artifact(record, label=f"guard_receipt_{name}") for name, record in artifacts_value.items()
    }
    run_dir = resolved.parent
    if resolved.name != "route_guard_success.json" or {
        name: Path(record["path"]) for name, record in artifacts.items()
    } != {
        "eval_run_identity": run_dir / "eval_run_identity.json",
        "eval_invocations": run_dir / "eval_invocations.jsonl",
        "results": run_dir / "results.jsonl",
    }:
        raise GuardReceiptError("guard_receipt_artifact_path_mismatch")
    for name, record in artifacts.items():
        _, digest = stable_sha256_file(Path(record["path"]), label=name)
        if digest != record["sha256"]:
            raise GuardReceiptError(f"guard_receipt_{name}_sha256_mismatch")
    _, invocation_artifact = validate_eval_invocations(
        Path(artifacts["eval_invocations"]["path"]),
        eval_run_identity_sha256=value["eval_run_identity_sha256"],
        eval_run_role=value["eval_run_role"],
    )
    if invocation_artifact != artifacts["eval_invocations"]:
        raise GuardReceiptError("guard_receipt_eval_invocations_sha256_mismatch")
    return {
        **body,
        "deployment": {
            **deployment,
            "readiness_checkpoint": readiness,
            "endpoint": endpoint,
            "serving_route_generation": generation,
            "proxy_policy": policy,
        },
        "artifacts": artifacts,
        "guard_success_receipt_sha256": self_hash,
    }


def validate_guard_success_linkage(
    receipt: dict[str, Any],
    *,
    run_dir: Path,
    eval_run_identity_sha256: str,
    eval_run_role: str,
    eval_run_identity_file_sha256: str,
    results_sha256: str,
    deployment_id: str,
    deployment_spec_sha256: str,
    readiness_checkpoint: dict[str, str],
    endpoint: dict[str, Any],
    serving_route_generation: dict[str, Any],
    proxy_policy: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Require one receipt to describe the exact run and deployment chain."""

    try:
        resolved_run_dir = run_dir.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise GuardReceiptError("guard_receipt_run_dir_invalid") from error
    artifacts = receipt.get("artifacts")
    deployment = receipt.get("deployment")
    invocations = artifacts.get("eval_invocations") if isinstance(artifacts, dict) else None
    if (
        not isinstance(artifacts, dict)
        or not isinstance(deployment, dict)
        or not isinstance(invocations, dict)
        or receipt.get("eval_run_identity_sha256") != eval_run_identity_sha256
        or receipt.get("eval_run_role") != eval_run_role
        or artifacts.get("eval_run_identity")
        != {
            "path": str(resolved_run_dir / "eval_run_identity.json"),
            "sha256": eval_run_identity_file_sha256,
        }
        or invocations.get("path") != str(resolved_run_dir / "eval_invocations.jsonl")
        or artifacts.get("results")
        != {
            "path": str(resolved_run_dir / "results.jsonl"),
            "sha256": results_sha256,
        }
        or deployment.get("id") != deployment_id
        or deployment.get("spec_sha256") != deployment_spec_sha256
        or deployment.get("readiness_checkpoint") != readiness_checkpoint
        or deployment.get("endpoint") != endpoint
        or deployment.get("serving_route_generation") != serving_route_generation
        or deployment.get("proxy_policy") != proxy_policy
    ):
        raise GuardReceiptError("guard_receipt_linkage_mismatch")
    return artifacts
