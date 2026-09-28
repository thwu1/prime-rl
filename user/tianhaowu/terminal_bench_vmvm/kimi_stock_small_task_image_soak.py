#!/usr/bin/env python3
"""Plan, run, and certify the aggregate-only Kimi c64 task-image soak.

The soak deliberately performs no model request and invokes no agent harness.
It proves that all 2,499 opaque approved production task images can run in
64-way waves in Sandoq Firecracker-small, prepared by the
real taskset adapter, exercised with a side-effect-free command, scored by the
shared verifier, and then completely removed.  Task and provider identifiers,
prompts, command output, and exception text never enter public output or the
durable aggregate receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import kimi_sandoq_production as legacy
import sanitize_sandoq_cleanup_audit as cleanup_sanitizer
from kimi_stock_endpoint_binding import (
    StockEndpointBinding,
    StockEndpointBindingError,
    load_capacity_binding,
)

SCHEMA_VERSION = 1
DYNAMIC_SCHEMA_VERSION = 2
PLAN_KIND = "kimi-k3-stock-small-task-image-c64-soak-plan"
RUN_KIND = "kimi-k3-stock-small-task-image-c64-soak-run"
RECEIPT_KIND = "kimi-k3-stock-small-task-image-c64-soak"
SELECTOR_KIND = "kimi-k3-stock-small-task-image-c64-selector"

CONCURRENCY = 64
SELECTED_TASKS = 2_499
ENDPOINT_GATE_TASK_COUNT = CONCURRENCY
PROVISIONING_RETRIES = 8
MAX_PROVISIONING_ATTEMPTS = PROVISIONING_RETRIES + 1
CPU_CAP = 1
MEMORY_GIB_CAP = 2
MEMORY_MB_CAP = MEMORY_GIB_CAP * 1024
STORAGE_GIB_CAP = 10
STORAGE_MB_CAP = STORAGE_GIB_CAP * 1024
SESSION_TIMEOUT_SECONDS = 144_000
TASK_PHASE_TIMEOUT_SECONDS = 21_600
CLEANUP_TIMEOUT_SECONDS = 900

PROVIDER_ENVIRONMENT = "oci-runner-firecracker-small"
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
IMAGE_MANIFEST_SHA256 = "a3fb4ec9ac9d1ee8376013013f171584c288321923f2050177157edac58340c8"
LIFECYCLE_SOAK_SHA256 = "400d2c6cc39db2ab83c9dcec38a0e2870b76ced29e3bfb48bcd2478e8ba3b762"
LIFECYCLE_SOAK = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/"
    "sandoq-firecracker-small-c64-soak-20260927/run-1596293/receipt.json"
)
STOCK_CAPACITY_SHA256 = "244dc901a555b4b73649c6185692c8a9d497319e0f8bcdcdb7373f6604c6f946"
STOCK_CAPACITY = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/"
    "kimi-stock-capacity-probes-20260927-v1/c64-fcedd7c6b.json"
)
STOCK_ENDPOINT_IDENTIFIER = "tianhaowu-kimi-k3-stock-eval-20260927"
STOCK_ENDPOINT_BUNDLE_SHA256 = "7ee38ee5d10c9cc7b04c2ddf9ff5b7813df148b2f7d425c1a4ff192f8fc4d581"
STOCK_SOURCE_SPEC_SHA256 = "3b9d7b9e72767b9f65894ea024a08713ed10330c7d55c70cd99b2717056a9b39"
STOCK_SOURCE_PROXY_SHA256 = "7894cd7205d0197620fa77edc747377e15c4e311769a0060be760659f5b29595"
STOCK_CAPACITY_PROFILE = "sandoq-stock-single-c64-v1"
WALLTIME_PROFILE = "tb4-extended-c24-stock-single-three-wave-v1"
MINIMUM_ENDPOINT_REMAINING_SECONDS = 518_400
ECR_TOKEN_FILE = Path("/storage/home/tianhaowu/.config/oci-runner/ecr-token")
PROVIDER_TOKEN_PATH_SHA256 = "19f886485a27dd272af667283ebeb57293a08723782af6c4bc83a05dca6dedc0"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024
STATUS_FILE_ENV = "KIMI_TASK_IMAGE_SOAK_STATUS_FILE"
STATUS_FILE_NAME = "task-image-soak-status.json"

_T = TypeVar("_T")


class TaskImageSoakError(RuntimeError):
    """A fail-closed condition represented by one aggregate-only code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Provisioned:
    runtime: Any
    attempts: int


def _workflow_dir() -> Path:
    return Path(__file__).resolve(strict=True).parent


def _launcher_path() -> Path:
    return _workflow_dir() / "run_kimi_stock_small_task_image_soak.sbatch"


def _provider_profile_path() -> Path:
    return (
        _workflow_dir()
        / "configs/provider_context/use2/cpu-132-021_8103/"
        "kimi_sandoq_firecracker_small_host.json"
    )


def _canonical(value: object) -> bytes:
    return (json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _plain_int(value: object, *, minimum: int = 0, maximum: int | None = None) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
        and (maximum is None or value <= maximum)
    )


def _artifact(path: Path, body: bytes) -> dict[str, int | str]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _strict_json(body: bytes, code: str, *, canonical: bool = True) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            body,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise TaskImageSoakError(code) from error
    if not isinstance(value, dict) or (canonical and body != _canonical(value)):
        raise TaskImageSoakError(code)
    return value


def _stable_artifact(
    path: Path,
    code: str,
    *,
    private: bool = False,
    maximum_bytes: int = MAX_ARTIFACT_BYTES,
) -> tuple[dict[str, int | str], bytes]:
    try:
        normalized = Path(os.path.normpath(path))
        resolved = path.resolve(strict=True)
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, RuntimeError) as error:
        raise TaskImageSoakError(code) from error
    try:
        opened = os.fstat(descriptor)
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > maximum_bytes:
                raise TaskImageSoakError(code)
            digest.update(chunk)
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        not path.is_absolute()
        or path != normalized
        or path != resolved
        or path.is_symlink()
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or (private and stat.S_IMODE(before.st_mode) != 0o600)
        or identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or size != before.st_size
    ):
        raise TaskImageSoakError(code)
    body = b"".join(chunks)
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}, body


def _private_directory(path: Path, code: str) -> Path:
    try:
        normalized = Path(os.path.normpath(path))
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except (OSError, RuntimeError) as error:
        raise TaskImageSoakError(code) from error
    if (
        not path.is_absolute()
        or path != normalized
        or path != resolved
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise TaskImageSoakError(code)
    return resolved


def _publish_private(path: Path, value: Mapping[str, object]) -> bytes:
    body = _canonical(value)
    if len(body) > MAX_RECEIPT_BYTES or path.parent != _private_directory(path.parent, "output_invalid"):
        raise TaskImageSoakError("output_invalid")
    try:
        legacy._publish_bundle(path.parent, {path: body})
    except Exception as error:
        raise TaskImageSoakError("output_publish_failed") from error
    return body


def _publish_terminal_status(*, code: str, state: str) -> None:
    """Best-effort aggregate-only child status; never retain stderr or task data."""

    status_value = os.environ.get(STATUS_FILE_ENV)
    output_value = os.environ.get("PRIME_RL_OUTPUT_DIR")
    if status_value is None or output_value is None:
        return
    try:
        output = Path(output_value)
        status = Path(status_value)
        if (
            status != output / "control" / STATUS_FILE_NAME
            or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is None
            or state not in {"blocked", "passed"}
        ):
            return
        _publish_private(
            status,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": RECEIPT_KIND,
                "state": state,
                "code": code,
            },
        )
    except BaseException:
        # Status publication must never replace the evaluator's actual result.
        return


def _git(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TaskImageSoakError("source_identity_invalid") from error
    if completed.stderr:
        raise TaskImageSoakError("source_identity_invalid")
    return completed.stdout.strip()


def _validate_source(project_root: Path, expected_revision: str) -> Path:
    if REVISION_RE.fullmatch(expected_revision) is None:
        raise TaskImageSoakError("source_identity_invalid")
    try:
        root = project_root.resolve(strict=True)
    except OSError as error:
        raise TaskImageSoakError("source_identity_invalid") from error
    repositories = (root, root / "deps/verifiers", root / "deps/renderers")
    if (
        root != project_root
        or not root.is_dir()
        or _git(root, "rev-parse", "HEAD") != expected_revision
        or any(_git(repository, "status", "--porcelain=v1", "--untracked-files=all") for repository in repositories)
    ):
        raise TaskImageSoakError("source_identity_invalid")
    return root


def _validate_provider_profile() -> tuple[dict[str, int | str], bytes]:
    path = _provider_profile_path().resolve(strict=True)
    artifact, body = _stable_artifact(path, "provider_profile_invalid")
    value = _strict_json(body, "provider_profile_invalid")
    if (
        artifact["sha256"] != PROVIDER_PROFILE_SHA256
        or value.get("schema_version") != 3
        or value.get("environment") != PROVIDER_ENVIRONMENT
        or value.get("task_network") != "host"
        or value.get("effective_task_network") != "public"
        or value.get("transport_mode") != "auto"
    ):
        raise TaskImageSoakError("provider_profile_invalid")
    return artifact, body


def _validate_lifecycle_soak() -> tuple[dict[str, int | str], bytes]:
    path = LIFECYCLE_SOAK.resolve(strict=True)
    if path != LIFECYCLE_SOAK:
        raise TaskImageSoakError("lifecycle_soak_invalid")
    artifact, body = _stable_artifact(path, "lifecycle_soak_invalid", private=True)
    value = _strict_json(body, "lifecycle_soak_invalid")
    failures = value.get("create_failure_counts")
    count_fields = (
        "requested_concurrency",
        "create_attempts",
        "sessions_returned",
        "simultaneous_ready_verified",
        "delete_attempts",
        "typed_404_verified",
    )
    if (
        artifact["sha256"] != LIFECYCLE_SOAK_SHA256
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-firecracker-small-c64-soak"
        or value.get("state") != "passed"
        or value.get("environment") != PROVIDER_ENVIRONMENT
        or value.get("profile_sha256") != PROVIDER_PROFILE_SHA256
        or any(value.get(field) != CONCURRENCY for field in count_fields)
        or value.get("cleanup_failures") != 0
        or value.get("client_close_verified") is not True
        or value.get("mtls_available") is not True
        or value.get("transport_mode") != "proxy"
        or not isinstance(failures, dict)
        or not failures
        or any(not _plain_int(count) or count != 0 for count in failures.values())
    ):
        raise TaskImageSoakError("lifecycle_soak_invalid")
    return artifact, body


def _validate_bound_stock_capacity(
    path: Path,
    expected_sha256: str,
) -> tuple[dict[str, int | str], bytes, StockEndpointBinding]:
    try:
        binding, body = load_capacity_binding(
            path,
            expected_sha256,
        )
    except (OSError, RuntimeError, ValueError, StockEndpointBindingError) as error:
        raise TaskImageSoakError("stock_capacity_invalid") from error
    artifact = _artifact(binding.capacity_receipt_path, body)
    return artifact, body, binding


def _validate_stock_capacity() -> tuple[dict[str, int | str], bytes, str]:
    artifact, body, binding = _validate_bound_stock_capacity(
        STOCK_CAPACITY,
        STOCK_CAPACITY_SHA256,
    )
    if (
        binding.deployment_id != STOCK_ENDPOINT_IDENTIFIER
        or binding.source_spec_sha256 != STOCK_SOURCE_SPEC_SHA256
        or binding.source_proxy_config_sha256 != STOCK_SOURCE_PROXY_SHA256
        or binding.endpoint_bundle_sha256 != STOCK_ENDPOINT_BUNDLE_SHA256
    ):
        raise TaskImageSoakError("stock_capacity_invalid")
    return artifact, body, binding.endpoint_jobs_sha256


def _selection_coverage(dataset: Path, members: Sequence[str]) -> dict[str, Any]:
    if len(members) != SELECTED_TASKS or len(set(members)) != SELECTED_TASKS:
        raise TaskImageSoakError("selection_invalid")
    declared_maximum = {"cpu": 0.0, "memory_gib": 0.0, "storage_gib": 0.0}
    effective_maximum = {"cpu": 0.0, "memory_gib": 0.0, "storage_gib": 0.0}
    vector: list[dict[str, object]] = []
    try:
        for member in members:
            metadata = tomllib.loads((dataset / member / "task.toml").read_text())
            environment = metadata.get("environment")
            verifier = metadata.get("verifier")
            if not isinstance(environment, dict) or not isinstance(verifier, dict):
                raise ValueError("metadata")
            mode = verifier.get("environment_mode")
            if mode is None:
                mode = "separate" if verifier.get("environment") is not None else "shared"
            if mode != "shared" or verifier.get("environment") is not None:
                raise ValueError("verifier mode")
            values = {
                "cpu": environment.get("cpus", 1),
                "memory_gib": float(environment.get("memory_mb", MEMORY_MB_CAP)) / 1024,
                "storage_gib": float(environment.get("storage_mb", STORAGE_MB_CAP)) / 1024,
            }
            if (
                environment.get("gpus")
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values.values())
                or any(not math.isfinite(float(value)) or float(value) <= 0 for value in values.values())
            ):
                raise ValueError("resources")
            effective = {
                "cpu": min(float(values["cpu"]), float(CPU_CAP)),
                "memory_gib": min(float(values["memory_gib"]), float(MEMORY_GIB_CAP)),
                "storage_gib": min(float(values["storage_gib"]), float(STORAGE_GIB_CAP)),
            }
            for key in declared_maximum:
                declared_maximum[key] = max(declared_maximum[key], float(values[key]))
                effective_maximum[key] = max(effective_maximum[key], effective[key])
            vector.append({"mode": mode, "declared": values, "effective": effective})
    except (OSError, UnicodeDecodeError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        raise TaskImageSoakError("selection_coverage_invalid") from error
    return {
        "selected_count": SELECTED_TASKS,
        "verifier_modes": {"shared": SELECTED_TASKS, "separate": 0},
        "declared_maximum": declared_maximum,
        "effective_maximum": effective_maximum,
        "effective_caps": {
            "cpu": CPU_CAP,
            "memory_gib": MEMORY_GIB_CAP,
            "storage_gib": STORAGE_GIB_CAP,
        },
        "resource_vector_sha256": _sha256(_canonical(vector)),
        "membership_disclosed": False,
    }


def _derive_selection(dataset: Path) -> tuple[Path, bytes, Path, tuple[str, ...], dict[str, Any]]:
    source_path = legacy._canonical_source_path().resolve(strict=True)
    source_artifact, source_body = _stable_artifact(source_path, "approved_source_invalid")
    if source_artifact["sha256"] != legacy.CANONICAL_SOURCE_SHA256:
        raise TaskImageSoakError("approved_source_invalid")
    try:
        dataset_path = legacy.verify_canonical_dataset(dataset)
        partition = legacy.derive_partition(source_body, dataset_path)
        selected = tuple(partition.sandoq)
    except Exception as error:
        raise TaskImageSoakError("selection_invalid") from error
    if (
        partition.no_network_count != legacy.EXPECTED_SOURCE_COUNT
        or len(partition.sandoq) != legacy.EXPECTED_TASK_COUNT
        or len(partition.vmvm) != legacy.EXPECTED_EXCLUDED_COUNT
        or len(selected) != SELECTED_TASKS
        or len(set(selected)) != SELECTED_TASKS
    ):
        raise TaskImageSoakError("selection_invalid")
    return source_path, source_body, dataset_path, selected, _selection_coverage(dataset_path, selected)


def _selector_receipt(selector_body: bytes, coverage: Mapping[str, Any]) -> dict[str, Any]:
    selection = {
        "algorithm": "canonical-approved-non-compose-v1",
        "approved_count": legacy.EXPECTED_SOURCE_COUNT,
        "candidate_count": legacy.EXPECTED_TASK_COUNT,
        "excluded_count": legacy.EXPECTED_EXCLUDED_COUNT,
        "selected_count": SELECTED_TASKS,
        "selected_sha256": _sha256(selector_body),
        "membership_disclosed": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SELECTOR_KIND,
        "state": "materialized",
        "dataset": {
            "revision": legacy.CANONICAL_DATASET_REVISION,
            "tree": legacy.CANONICAL_DATASET_TREE,
        },
        "selection": selection,
        "selection_contract_sha256": _sha256(_canonical(selection)),
        "coverage": dict(coverage),
        "coverage_sha256": _sha256(_canonical(coverage)),
    }


def _contracts(binding: StockEndpointBinding | None = None) -> dict[str, Any]:
    endpoint_identifier = binding.deployment_id if binding is not None else STOCK_ENDPOINT_IDENTIFIER
    capacity_receipt_sha256 = (
        binding.capacity_receipt_sha256 if binding is not None else STOCK_CAPACITY_SHA256
    )
    return {
        "purpose": "real-task-image-prelaunch-soak",
        "task_count": SELECTED_TASKS,
        "concurrency": CONCURRENCY,
        "sandbox": {
            "provider": "sandoq",
            "environment": PROVIDER_ENVIRONMENT,
            "task_network": "host",
            "effective_network": "public",
            "resource_caps": {
                "cpu": CPU_CAP,
                "memory_mb": MEMORY_MB_CAP,
                "storage_mb": STORAGE_MB_CAP,
            },
            "provisioning_retries": PROVISIONING_RETRIES,
            "maximum_provisioning_attempts": MAX_PROVISIONING_ATTEMPTS,
            "retry_scope": "pre-execution-only-after-runtime-cleanup",
        },
        "endpoint_epoch": {
            "capacity_profile": STOCK_CAPACITY_PROFILE,
            "endpoint_identifier": endpoint_identifier,
            "capacity_receipt_sha256": capacity_receipt_sha256,
            "minimum_remaining_seconds": MINIMUM_ENDPOINT_REMAINING_SECONDS,
            "walltime_gate_task_count": ENDPOINT_GATE_TASK_COUNT,
            "capture_before_sandbox_start": True,
        },
        "execution": {
            "taskset_setup": True,
            "benign_command": "posix-shell-noop-v1",
            "shared_verifier": True,
            "verifier_execution": "background-program",
            "shared_verifier_taskset_retries": 0,
            "maximum_shared_verifier_attempts": 1,
            "model_calls": 0,
            "harness_invocations": 0,
        },
        "privacy": {
            "task_membership": "private-selector-only",
            "receipt": "aggregate-only",
            "raw_command_output_retained": False,
            "exception_text_retained": False,
        },
        "cleanup": {
            "typed_404_required": True,
            "assignment_high_water_required": CONCURRENCY,
            "outer_session_high_water_required": CONCURRENCY,
            "all_assignments_released": True,
            "all_outer_sessions_deleted": True,
        },
    }


def materialize(
    *,
    project_root: Path,
    expected_revision: str,
    dataset: Path,
    image_manifest: Path,
    output: Path,
    stock_capacity: Path = STOCK_CAPACITY,
    stock_capacity_sha256: str = STOCK_CAPACITY_SHA256,
) -> dict[str, Any]:
    root = _validate_source(project_root, expected_revision)
    try:
        output_parent = legacy._private_root(output.parent)
    except Exception as error:
        raise TaskImageSoakError("output_invalid") from error
    if output != output_parent / output.name or output.name in {"", ".", ".."} or os.path.lexists(output):
        raise TaskImageSoakError("output_invalid")
    source_path, source_body, dataset_path, members, coverage = _derive_selection(dataset)
    image_path = image_manifest.resolve(strict=True)
    image_record, image_body = _stable_artifact(image_path, "image_manifest_invalid")
    if image_record["sha256"] != IMAGE_MANIFEST_SHA256:
        raise TaskImageSoakError("image_manifest_invalid")
    profile_record, profile_body = _validate_provider_profile()
    lifecycle_record, lifecycle_body = _validate_lifecycle_soak()
    dynamic_binding = stock_capacity != STOCK_CAPACITY or stock_capacity_sha256 != STOCK_CAPACITY_SHA256
    if dynamic_binding:
        stock_record, stock_body, binding = _validate_bound_stock_capacity(
            stock_capacity,
            stock_capacity_sha256,
        )
        endpoint_jobs_sha256 = binding.endpoint_jobs_sha256
    else:
        stock_record, stock_body, endpoint_jobs_sha256 = _validate_stock_capacity()
        binding = None
    tool_path = Path(__file__).resolve(strict=True)
    launcher_path = _launcher_path().resolve(strict=True)
    tool_record, tool_body = _stable_artifact(tool_path, "tool_identity_invalid")
    launcher_record, launcher_body = _stable_artifact(launcher_path, "tool_identity_invalid")
    selector_body = legacy._task_payload(members)
    selector_path = output / "selector.tasks.txt"
    selector_receipt_path = output / "selector.receipt.json"
    plan_path = output / "plan.json"
    selector_value = _selector_receipt(selector_body, coverage)
    selector_receipt_body = _canonical(selector_value)
    plan: dict[str, Any] = {
        "schema_version": DYNAMIC_SCHEMA_VERSION if dynamic_binding else SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "state": "authorized",
        "source_revision": expected_revision,
        "source": {
            "project_root": str(root),
            "approved_selector_source": _artifact(source_path, source_body),
            "dataset": {
                "path": str(dataset_path),
                "revision": legacy.CANONICAL_DATASET_REVISION,
                "tree": legacy.CANONICAL_DATASET_TREE,
            },
            "image_manifest": _artifact(image_path, image_body),
            "provider_profile": _artifact(Path(profile_record["path"]), profile_body),
            "lifecycle_c64_soak": _artifact(Path(lifecycle_record["path"]), lifecycle_body),
            "stock_model_c64": _artifact(Path(stock_record["path"]), stock_body),
            "tool": _artifact(tool_path, tool_body),
            "launcher": _artifact(launcher_path, launcher_body),
        },
        "selection": {
            "count": SELECTED_TASKS,
            "selector": _artifact(selector_path, selector_body),
            "receipt": _artifact(selector_receipt_path, selector_receipt_body),
        },
        "endpoint_epoch": {"endpoint_jobs_sha256": endpoint_jobs_sha256},
        "contracts": _contracts(binding if dynamic_binding else None),
    }
    if dynamic_binding:
        plan["endpoint_binding"] = binding.public_record
    plan["plan_sha256"] = _sha256(_canonical(plan))
    try:
        os.mkdir(output, 0o700)
        legacy._publish_bundle(
            output,
            {
                selector_path: selector_body,
                selector_receipt_path: selector_receipt_body,
                plan_path: _canonical(plan),
            },
        )
    except Exception as error:
        raise TaskImageSoakError("output_publish_failed") from error
    plan_body = _canonical(plan)
    return {
        "kind": PLAN_KIND,
        "state": "authorized",
        "selected_tasks": SELECTED_TASKS,
        "concurrency": CONCURRENCY,
        "plan": str(plan_path),
        "plan_file_sha256": _sha256(plan_body),
    }


def _record_body(record: object, code: str, *, private: bool = False) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise TaskImageSoakError(code)
    path_value = record.get("path")
    if (
        not isinstance(path_value, str)
        or not _plain_int(record.get("bytes"))
        or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
    ):
        raise TaskImageSoakError(code)
    path = Path(path_value)
    observed, body = _stable_artifact(path, code, private=private)
    if observed != record:
        raise TaskImageSoakError(code)
    return path, body


def validate_plan(path: Path, expected_sha256: str) -> dict[str, Any]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise TaskImageSoakError("plan_invalid")
    plan_record, body = _stable_artifact(path, "plan_invalid", private=True)
    plan_path = Path(str(plan_record["path"]))
    if plan_path != path or plan_record["sha256"] != expected_sha256:
        raise TaskImageSoakError("plan_invalid")
    value = _strict_json(body, "plan_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("plan_sha256", None)
    source = value.get("source")
    selection = value.get("selection")
    schema_version = value.get("schema_version")
    dynamic_binding = schema_version == DYNAMIC_SCHEMA_VERSION
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "source_revision",
        "source",
        "selection",
        "endpoint_epoch",
        "contracts",
        "plan_sha256",
    }
    if dynamic_binding:
        expected_keys.add("endpoint_binding")
    if (
        set(value) != expected_keys
        or schema_version not in {SCHEMA_VERSION, DYNAMIC_SCHEMA_VERSION}
        or value.get("kind") != PLAN_KIND
        or value.get("state") != "authorized"
        or REVISION_RE.fullmatch(str(value.get("source_revision", ""))) is None
        or claimed != _sha256(_canonical(unsigned))
        or not isinstance(source, dict)
        or set(source)
        != {
            "project_root",
            "approved_selector_source",
            "dataset",
            "image_manifest",
            "provider_profile",
            "lifecycle_c64_soak",
            "stock_model_c64",
            "tool",
            "launcher",
        }
        or not isinstance(selection, dict)
        or set(selection) != {"count", "selector", "receipt"}
        or selection.get("count") != SELECTED_TASKS
    ):
        raise TaskImageSoakError("plan_invalid")
    project_root = _validate_source(Path(str(source["project_root"])), str(value["source_revision"]))
    source_path, source_body = _record_body(source["approved_selector_source"], "approved_source_invalid")
    if source_path != legacy._canonical_source_path().resolve(strict=True) or _sha256(source_body) != legacy.CANONICAL_SOURCE_SHA256:
        raise TaskImageSoakError("approved_source_invalid")
    dataset_record = source.get("dataset")
    if (
        not isinstance(dataset_record, dict)
        or set(dataset_record) != {"path", "revision", "tree"}
        or dataset_record.get("revision") != legacy.CANONICAL_DATASET_REVISION
        or dataset_record.get("tree") != legacy.CANONICAL_DATASET_TREE
    ):
        raise TaskImageSoakError("dataset_invalid")
    source_again, body_again, dataset_path, members, coverage = _derive_selection(Path(str(dataset_record["path"])))
    if source_again != source_path or body_again != source_body:
        raise TaskImageSoakError("selection_invalid")
    selector_path, selector_body = _record_body(selection["selector"], "selector_invalid", private=True)
    selector_receipt_path, selector_receipt_body = _record_body(
        selection["receipt"], "selector_receipt_invalid", private=True
    )
    expected_selector = legacy._task_payload(members)
    expected_selector_receipt = _selector_receipt(expected_selector, coverage)
    if (
        selector_path.parent != plan_path.parent
        or selector_receipt_path.parent != plan_path.parent
        or selector_body != expected_selector
        or selector_receipt_body != _canonical(expected_selector_receipt)
    ):
        raise TaskImageSoakError("selector_invalid")
    image_path, image_body = _record_body(source["image_manifest"], "image_manifest_invalid")
    if _sha256(image_body) != IMAGE_MANIFEST_SHA256:
        raise TaskImageSoakError("image_manifest_invalid")
    profile_path, profile_body = _record_body(source["provider_profile"], "provider_profile_invalid")
    profile_record, expected_profile_body = _validate_provider_profile()
    lifecycle_path, lifecycle_body = _record_body(
        source["lifecycle_c64_soak"], "lifecycle_soak_invalid", private=True
    )
    lifecycle_record, expected_lifecycle_body = _validate_lifecycle_soak()
    stock_path, stock_body = _record_body(source["stock_model_c64"], "stock_capacity_invalid", private=True)
    if dynamic_binding:
        stock_record, expected_stock_body, binding = _validate_bound_stock_capacity(
            stock_path,
            str(source["stock_model_c64"].get("sha256", "")),
        )
        endpoint_jobs_sha256 = binding.endpoint_jobs_sha256
        expected_binding = binding.public_record
    else:
        stock_record, expected_stock_body, endpoint_jobs_sha256 = _validate_stock_capacity()
        binding = None
        expected_binding = None
    tool_path, _tool_body = _record_body(source["tool"], "tool_identity_invalid")
    launcher_path, _launcher_body = _record_body(source["launcher"], "tool_identity_invalid")
    if (
        profile_path != Path(profile_record["path"])
        or profile_body != expected_profile_body
        or lifecycle_path != Path(lifecycle_record["path"])
        or lifecycle_body != expected_lifecycle_body
        or stock_path != Path(stock_record["path"])
        or stock_body != expected_stock_body
        or value.get("endpoint_epoch") != {"endpoint_jobs_sha256": endpoint_jobs_sha256}
        or value.get("contracts") != _contracts(binding if dynamic_binding else None)
        or (dynamic_binding and value.get("endpoint_binding") != expected_binding)
        or tool_path != Path(__file__).resolve(strict=True)
        or launcher_path != _launcher_path().resolve(strict=True)
        or project_root != Path(str(source["project_root"]))
        or image_path != Path(str(source["image_manifest"]["path"]))
        or dataset_path != Path(str(dataset_record["path"]))
    ):
        raise TaskImageSoakError("plan_binding_invalid")
    return value


def _plan_endpoint_binding(plan: Mapping[str, Any]) -> StockEndpointBinding:
    source = plan.get("source")
    record = source.get("stock_model_c64") if isinstance(source, dict) else None
    if not isinstance(record, dict):
        raise TaskImageSoakError("stock_capacity_invalid")
    try:
        binding, _body = load_capacity_binding(
            Path(str(record.get("path", ""))),
            str(record.get("sha256", "")),
        )
    except (OSError, RuntimeError, ValueError, StockEndpointBindingError) as error:
        raise TaskImageSoakError("stock_capacity_invalid") from error
    if plan.get("schema_version") == DYNAMIC_SCHEMA_VERSION:
        if plan.get("endpoint_binding") != binding.public_record:
            raise TaskImageSoakError("endpoint_binding_invalid")
    elif (
        binding.deployment_id != STOCK_ENDPOINT_IDENTIFIER
        or binding.capacity_receipt_sha256 != STOCK_CAPACITY_SHA256
        or binding.source_spec_sha256 != STOCK_SOURCE_SPEC_SHA256
        or binding.source_proxy_config_sha256 != STOCK_SOURCE_PROXY_SHA256
        or binding.endpoint_bundle_sha256 != STOCK_ENDPOINT_BUNDLE_SHA256
    ):
        raise TaskImageSoakError("stock_capacity_invalid")
    return binding


def _validate_execution_environment(output: Path) -> None:
    expected_socket = (
        Path(os.environ.get("SLURM_TMPDIR", "/tmp"))
        / f"oci-runner-pool-{os.getuid()}"
        / f"{os.environ.get('SLURM_JOB_ID', '')}.sock"
    )
    exact = {
        "SANDOQ_PROVIDER_CONTEXT_ACTIVE": "1",
        "SANDOQ_PROVIDER_PROFILE_SHA256": PROVIDER_PROFILE_SHA256,
        "OCI_RUNNER_BASE_URL": "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        "OCI_RUNNER_ENVIRONMENT": PROVIDER_ENVIRONMENT,
        "SANDOQ_EFFECTIVE_TASK_NETWORK": "public",
        "OCI_RUNNER_TASK_NETWORK": "host",
        "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK": "0",
        "SANDOQ_LEASE_PROFILE": "kimi-tb4-long",
        "OCI_RUNNER_LEASE_DURATION": "12h",
        "OCI_RUNNER_POOL_RENEW_INTERVAL": "5m",
        "OCI_RUNNER_MANAGED_SHELL_RECOVERY": "1",
        "OCI_RUNNER_POOL_SIZE": str(CONCURRENCY),
        "OCI_RUNNER_POOL_MIN_SIZE": "0",
        "OCI_RUNNER_POOL_CREATE_WORKERS": "8",
        "OCI_RUNNER_POOL_BOOTSTRAP_WORKERS": str(CONCURRENCY),
        "OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE": "8",
        "OCI_RUNNER_POOL_DRAIN_WORKERS": "32",
        "OCI_RUNNER_SESSION_REUSE": "1",
        "OCI_RUNNER_POOL_MAX_REUSE_COUNT": "1",
        "OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES": "0",
        "PRIME_RL_OUTPUT_DIR": str(output),
        "OCI_RUNNER_POOL_SOCKET": str(expected_socket),
        "OCI_RUNNER_POOL_WAL": str(output / "control/sandoq-pool.wal.jsonl"),
        "OCI_RUNNER_POOL_EVENT_LOG": str(output / "pool_events.jsonl"),
    }
    if (
        any(os.environ.get(key) != value for key, value in exact.items())
        or os.environ.get("VF_SANDBOX_PROVIDER")
        or os.environ.get("FIRECRACKER_KEY")
        or os.environ.get("SANDOQ_AUTH_TOKEN")
        or any(os.environ.get(name) for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"))
    ):
        raise TaskImageSoakError("provider_environment_invalid")
    try:
        from terminal_bench_vmvm.sandoq_provider_context import provider_context_is_active

        active = provider_context_is_active(os.environ)
    except Exception as error:
        raise TaskImageSoakError("provider_environment_invalid") from error
    if not active:
        raise TaskImageSoakError("provider_environment_invalid")


def _load_taskset(plan: Mapping[str, Any]) -> tuple[Any, list[Any]]:
    try:
        from terminal_bench_vmvm.taskset import TerminalBenchVMVMConfig, TerminalBenchVMVMTaskset

        source = plan["source"]
        selection = plan["selection"]
        config = TerminalBenchVMVMConfig(
            dataset_dir=Path(source["dataset"]["path"]),
            dataset_revision=legacy.CANONICAL_DATASET_REVISION,
            task_file=Path(selection["selector"]["path"]),
            task_file_sha256=selection["selector"]["sha256"],
            image_manifest=Path(source["image_manifest"]["path"]),
            image_manifest_sha256=IMAGE_MANIFEST_SHA256,
            ignore_dockerfile=True,
            use_declared_images=True,
            enable_compose=False,
            verifier_runtime_retries=0,
            retry_shared_verifier_scoring=False,
            timeout_multiplier=2.0,
            resource_multiplier=1.0,
            resource_cpu_cap=CPU_CAP,
            resource_memory_mb_cap=MEMORY_MB_CAP,
            resource_storage_mb_cap=STORAGE_MB_CAP,
        )
        taskset = TerminalBenchVMVMTaskset(config)
        tasks = taskset.load_tasks()
    except Exception as error:
        raise TaskImageSoakError("taskset_load_invalid") from error
    if len(tasks) != SELECTED_TASKS:
        raise TaskImageSoakError("taskset_load_invalid")
    for task in tasks:
        resources = task.resources
        if (
            task.verifier_mode != "shared"
            or task.agent_network_mode != "no-network"
            or task.verifier_network_mode != "no-network"
            or not isinstance(task.image, str)
            or "@sha256:" not in task.image
            or task.resources.gpu is not None
            or not 0 < float(resources.cpu or CPU_CAP) <= CPU_CAP
            or not 0 < float(resources.memory or MEMORY_GIB_CAP) <= MEMORY_GIB_CAP
            or not 0 < float(resources.disk or STORAGE_GIB_CAP) <= STORAGE_GIB_CAP
        ):
            raise TaskImageSoakError("taskset_contract_invalid")
    return taskset, tasks


def _runtime_for_task(task: Any) -> Any:
    from verifiers.v1.runtimes import SandoqConfig, SandoqRuntime

    return SandoqRuntime(
        SandoqConfig(
            image=task.image,
            workdir=task.workdir or "/app",
            network_access=True,
            mode="oci-runner",
            session_timeout=SESSION_TIMEOUT_SECONDS,
            cpu=float(task.resources.cpu or CPU_CAP),
            memory=float(task.resources.memory or MEMORY_GIB_CAP),
            disk=float(task.resources.disk or STORAGE_GIB_CAP),
            provisioning_retries=0,
            host_tunnel="sandoq",
            buffered_chat_completions=True,
            guest_tunnel_url="http://127.0.0.1:8485",
            tunnel_pool_size=4,
            tunnel_ready_timeout=30,
            expected_environment=PROVIDER_ENVIRONMENT,
            ecr_token_file=ECR_TOKEN_FILE,
        ),
        name=f"k3-task-image-soak-{os.urandom(8).hex()}",
    )


async def _finish_despite_cancellation(operation: Awaitable[_T]) -> tuple[_T, asyncio.CancelledError | None]:
    task = asyncio.ensure_future(operation)
    interruption: asyncio.CancelledError | None = None
    while True:
        try:
            return await asyncio.shield(task), interruption
        except asyncio.CancelledError as error:
            if interruption is None:
                interruption = error
            if task.done():
                return task.result(), interruption


async def _provision_one(task: Any, runtime_factory: Callable[[Any], Any]) -> tuple[Provisioned | None, int]:
    for attempt in range(1, MAX_PROVISIONING_ATTEMPTS + 1):
        runtime: Any | None = None
        try:
            runtime = runtime_factory(task)
            await runtime.start()
            return Provisioned(runtime=runtime, attempts=attempt), 0
        except asyncio.CancelledError:
            if runtime is not None:
                with contextlib.suppress(Exception):
                    await asyncio.shield(runtime.stop())
            raise
        except Exception:
            if runtime is None:
                continue
            try:
                async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
                    await runtime.stop()
            except Exception:
                return None, 1
    return None, 0


async def _exercise_one(taskset: Any, task: Any, runtime: Any) -> dict[str, int]:
    counts = Counter(
        {
            "setup_succeeded": 0,
            "benign_exec_succeeded": 0,
            "shared_verifier_executed": 0,
            "shared_verifier_zero_reward": 0,
            "shared_verifier_positive_reward": 0,
            "shared_verifier_retry_attempts": 0,
            "setup_failures": 0,
            "benign_exec_failures": 0,
            "shared_verifier_failures": 0,
        }
    )
    try:
        async with asyncio.timeout(TASK_PHASE_TIMEOUT_SECONDS):
            try:
                await taskset.setup(task, runtime)
            except Exception:
                counts["setup_failures"] += 1
                return dict(counts)
            counts["setup_succeeded"] += 1
            try:
                result = await runtime.run(["sh", "-c", ":"], {})
            except Exception:
                counts["benign_exec_failures"] += 1
                return dict(counts)
            if result.exit_code != 0 or result.stdout or result.stderr:
                counts["benign_exec_failures"] += 1
                return dict(counts)
            counts["benign_exec_succeeded"] += 1
            try:
                _result, timed_out, score, rewards, _descriptor, attempts, failures = await taskset._score_shared(
                    task, runtime
                )
            except Exception:
                counts["shared_verifier_failures"] += 1
                return dict(counts)
            if (
                timed_out
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or not 0 <= float(score) <= 1
                or not isinstance(rewards, dict)
                or not rewards
                or attempts != 1
                or failures != []
            ):
                counts["shared_verifier_failures"] += 1
                return dict(counts)
            counts["shared_verifier_executed"] += 1
            counts["shared_verifier_retry_attempts"] += attempts - 1
            counts[
                "shared_verifier_positive_reward" if float(score) > 0 else "shared_verifier_zero_reward"
            ] += 1
    except TimeoutError:
        counts["shared_verifier_failures"] += 1
    return dict(counts)


async def _cleanup_one(taskset: Any, task: Any, runtime: Any) -> dict[str, int]:
    counts = {"taskset_cleanup_succeeded": 0, "runtime_cleanup_succeeded": 0, "cleanup_failures": 0}
    try:
        await taskset.cleanup(task, None, runtime)
        counts["taskset_cleanup_succeeded"] = 1
    except Exception:
        counts["cleanup_failures"] += 1
    try:
        async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
            await runtime.stop()
        counts["runtime_cleanup_succeeded"] = 1
    except Exception:
        counts["cleanup_failures"] += 1
    return counts


async def execute_soak(
    taskset: Any,
    tasks: Sequence[Any],
    *,
    runtime_factory: Callable[[Any], Any] = _runtime_for_task,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if len(tasks) != SELECTED_TASKS:
        raise TaskImageSoakError("task_count_invalid")
    started_at = monotonic()
    interrupted: asyncio.CancelledError | None = None
    live_high_water = 0
    attempts = 0
    attempted_tasks = 0
    provisioning_cleanup_failures = 0
    provisioned_count = 0
    exercise_counts: Counter[str] = Counter()
    cleanup_counts: Counter[str] = Counter()
    for offset in range(0, SELECTED_TASKS, CONCURRENCY):
        wave = tasks[offset : offset + CONCURRENCY]
        attempted_tasks += len(wave)
        provision_tasks = [asyncio.create_task(_provision_one(task, runtime_factory)) for task in wave]
        try:
            provision_results = list(await asyncio.gather(*provision_tasks))
        except asyncio.CancelledError as error:
            interrupted = error
            for operation in provision_tasks:
                if not operation.done():
                    operation.cancel()
            provision_results = []
            settled, settle_interruption = await _finish_despite_cancellation(
                asyncio.gather(*provision_tasks, return_exceptions=True)
            )
            interrupted = interrupted or settle_interruption
            for value in settled:
                provision_results.append(
                    value if isinstance(value, tuple) and len(value) == 2 else (None, 0)
                )

        provisioned: list[tuple[Any, Provisioned]] = []
        for task, outcome in zip(wave, provision_results, strict=False):
            provisioned_value, cleanup_failures = outcome
            provisioning_cleanup_failures += cleanup_failures
            if provisioned_value is None:
                attempts += MAX_PROVISIONING_ATTEMPTS
            else:
                attempts += provisioned_value.attempts
                provisioned.append((task, provisioned_value))
        provisioned_count += len(provisioned)
        live_high_water = max(live_high_water, len(provisioned))

        if interrupted is None and len(provisioned) == len(wave):
            operations = [
                asyncio.create_task(_exercise_one(taskset, task, provisioned_value.runtime))
                for task, provisioned_value in provisioned
            ]
            try:
                for outcome in await asyncio.gather(*operations):
                    exercise_counts.update(outcome)
            except asyncio.CancelledError as error:
                interrupted = error
                for operation in operations:
                    if not operation.done():
                        operation.cancel()
                _, settle_interruption = await _finish_despite_cancellation(
                    asyncio.gather(*operations, return_exceptions=True)
                )
                interrupted = interrupted or settle_interruption

        cleanup_results, cleanup_interruption = await _finish_despite_cancellation(
            asyncio.gather(
                *(
                    _cleanup_one(taskset, task, provisioned_value.runtime)
                    for task, provisioned_value in provisioned
                )
            )
        )
        interrupted = interrupted or cleanup_interruption
        for outcome in cleanup_results:
            cleanup_counts.update(outcome)
        if interrupted is not None or len(provisioned) != len(wave):
            break
    try:
        await taskset.close()
        taskset_close_succeeded = 1
    except Exception:
        taskset_close_succeeded = 0
        cleanup_counts["cleanup_failures"] += 1

    counts = {
        "tasks": SELECTED_TASKS,
        "provisioned": provisioned_count,
        "provisioning_attempts": attempts,
        "provisioning_retries": max(attempts - attempted_tasks, 0),
        "provisioning_failures": attempted_tasks - provisioned_count,
        "provisioning_cleanup_failures": provisioning_cleanup_failures,
        **{
            key: exercise_counts[key]
            for key in (
                "setup_succeeded",
                "benign_exec_succeeded",
                "shared_verifier_executed",
                "shared_verifier_zero_reward",
                "shared_verifier_positive_reward",
                "shared_verifier_retry_attempts",
                "setup_failures",
                "benign_exec_failures",
                "shared_verifier_failures",
            )
        },
        "taskset_cleanup_succeeded": cleanup_counts["taskset_cleanup_succeeded"],
        "runtime_cleanup_succeeded": cleanup_counts["runtime_cleanup_succeeded"],
        "cleanup_failures": cleanup_counts["cleanup_failures"],
        "taskset_close_succeeded": taskset_close_succeeded,
    }
    passed = (
        interrupted is None
        and live_high_water == CONCURRENCY
        and counts["provisioned"] == SELECTED_TASKS
        and SELECTED_TASKS <= counts["provisioning_attempts"] <= SELECTED_TASKS * MAX_PROVISIONING_ATTEMPTS
        and 0 <= counts["provisioning_retries"] <= SELECTED_TASKS * PROVISIONING_RETRIES
        and counts["provisioning_failures"] == 0
        and counts["provisioning_cleanup_failures"] == 0
        and counts["setup_succeeded"] == SELECTED_TASKS
        and counts["benign_exec_succeeded"] == SELECTED_TASKS
        and counts["shared_verifier_executed"] == SELECTED_TASKS
        and counts["shared_verifier_zero_reward"] + counts["shared_verifier_positive_reward"] == SELECTED_TASKS
        and counts["shared_verifier_retry_attempts"] == 0
        and counts["setup_failures"] == 0
        and counts["benign_exec_failures"] == 0
        and counts["shared_verifier_failures"] == 0
        and counts["taskset_cleanup_succeeded"] == SELECTED_TASKS
        and counts["runtime_cleanup_succeeded"] == SELECTED_TASKS
        and counts["cleanup_failures"] == 0
        and counts["taskset_close_succeeded"] == 1
    )
    if interrupted is not None:
        raise interrupted
    return {
        "state": "passed" if passed else "unavailable",
        "live_runtime_high_water": live_high_water,
        "counts": counts,
        "elapsed_seconds": round(max(monotonic() - started_at, 0.0), 3),
    }


def _validate_provider_snapshot(path: Path) -> tuple[dict[str, int | str], dict[str, Any]]:
    artifact, body = _stable_artifact(path, "provider_snapshot_invalid", private=True)
    value = _strict_json(body, "provider_snapshot_invalid")
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "provider_environment",
        "effective_task_network",
        "task_network",
        "network_access",
        "allow_dockerhub_fallback",
        "provider_profile_sha256",
        "provider_token_file_path_sha256",
        "runtime_smoke_receipt_sha256",
        "provider_context_contract_sha256",
    }
    if (
        set(value) != expected_keys
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-provider-context-snapshot"
        or value.get("state") != "validated"
        or value.get("provider_environment") != PROVIDER_ENVIRONMENT
        or value.get("effective_task_network") != "public"
        or value.get("task_network") != "host"
        or value.get("network_access") is not True
        or value.get("allow_dockerhub_fallback") is not False
        or value.get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or value.get("runtime_smoke_receipt_sha256") is not None
        or value.get("provider_token_file_path_sha256") != PROVIDER_TOKEN_PATH_SHA256
        or SHA256_RE.fullmatch(str(value.get("provider_context_contract_sha256", ""))) is None
    ):
        raise TaskImageSoakError("provider_snapshot_invalid")
    return artifact, value


def _validate_endpoint_gate(
    *,
    manifest_path: Path,
    manifest_sha256: str,
    walltime_path: Path,
    walltime_sha256: str,
    endpoint_jobs_sha256: str,
    binding: StockEndpointBinding,
    revalidate_live_source: bool,
) -> dict[str, Any]:
    if any(SHA256_RE.fullmatch(value) is None for value in (manifest_sha256, walltime_sha256, endpoint_jobs_sha256)):
        raise TaskImageSoakError("endpoint_gate_invalid")
    manifest_record, manifest_body = _stable_artifact(
        manifest_path, "endpoint_manifest_invalid", private=True
    )
    walltime_record, walltime_body = _stable_artifact(
        walltime_path, "endpoint_walltime_invalid", private=True
    )
    if manifest_record["sha256"] != manifest_sha256 or walltime_record["sha256"] != walltime_sha256:
        raise TaskImageSoakError("endpoint_gate_invalid")
    try:
        from direct_kimi_workers import validate_saved_manifest
        from kimi_endpoint_walltime_gate import validate_receipt

        manifest = validate_saved_manifest(
            manifest_path,
            body=manifest_body,
            revalidate_live_source=revalidate_live_source,
        )
        router = manifest.get("router")
        workers = manifest.get("workers")
        dynamic_manifest = manifest.get("schema_version") == 6
        if (
            manifest.get("schema_version") not in {5, 6}
            or manifest.get("model") != "Kimi-K3"
            or manifest.get("source_spec_sha256") != binding.source_spec_sha256
            or manifest.get("source_proxy_config_sha256") != binding.source_proxy_config_sha256
            or manifest.get("endpoint_bundle_sha256") != binding.endpoint_bundle_sha256
            or (
                dynamic_manifest
                and manifest.get("stock_capacity")
                != {
                    "path": str(binding.capacity_receipt_path),
                    "sha256": binding.capacity_receipt_sha256,
                }
            )
            or (not dynamic_manifest and binding.capacity_receipt_sha256 != STOCK_CAPACITY_SHA256)
            or not isinstance(workers, list)
            or len(workers) != 1
            or not isinstance(router, dict)
            or router.get("capacity_profile") != STOCK_CAPACITY_PROFILE
            or router.get("endpoint_identifier") != binding.deployment_id
            or router.get("max_concurrent_requests") != CONCURRENCY
            or router.get("queue_size") != CONCURRENCY
            or router.get("per_worker_capacity") != CONCURRENCY
            or router.get("request_timeout_seconds") != SESSION_TIMEOUT_SECONDS
            or router.get("queue_timeout_seconds") != SESSION_TIMEOUT_SECONDS
            or router.get("retries") != 0
        ):
            raise TaskImageSoakError("endpoint_manifest_invalid")
        walltime = validate_receipt(
            _strict_json(walltime_body, "endpoint_walltime_invalid"),
            manifest_sha256=manifest_sha256,
            endpoint_bundle_sha256=binding.endpoint_bundle_sha256,
            profile=WALLTIME_PROFILE,
            minimum_remaining_seconds=MINIMUM_ENDPOINT_REMAINING_SECONDS,
            task_count=ENDPOINT_GATE_TASK_COUNT,
            deployment=binding.deployment_id,
        )
    except TaskImageSoakError:
        raise
    except Exception as error:
        raise TaskImageSoakError("endpoint_gate_invalid") from error
    if (
        walltime.get("endpoint_jobs_sha256") != endpoint_jobs_sha256
        or endpoint_jobs_sha256 != binding.endpoint_jobs_sha256
        or walltime.get("observed_minimum_remaining_seconds", 0) < MINIMUM_ENDPOINT_REMAINING_SECONDS
    ):
        raise TaskImageSoakError("endpoint_epoch_invalid")
    return {
        "worker_manifest": manifest_record,
        "walltime_receipt": walltime_record,
        "endpoint_jobs_sha256": endpoint_jobs_sha256,
        "minimum_remaining_seconds": MINIMUM_ENDPOINT_REMAINING_SECONDS,
        "walltime_gate_task_count": ENDPOINT_GATE_TASK_COUNT,
        "observed_minimum_remaining_seconds": walltime["observed_minimum_remaining_seconds"],
    }


def _validate_run_value(
    value: Mapping[str, Any],
    plan_path: Path,
    plan_sha256: str,
    plan: Mapping[str, Any],
) -> None:
    counts = value.get("counts")
    required_counts = {
        "tasks",
        "provisioned",
        "provisioning_attempts",
        "provisioning_retries",
        "provisioning_failures",
        "provisioning_cleanup_failures",
        "setup_succeeded",
        "benign_exec_succeeded",
        "shared_verifier_executed",
        "shared_verifier_zero_reward",
        "shared_verifier_positive_reward",
        "shared_verifier_retry_attempts",
        "setup_failures",
        "benign_exec_failures",
        "shared_verifier_failures",
        "taskset_cleanup_succeeded",
        "runtime_cleanup_succeeded",
        "cleanup_failures",
        "taskset_close_succeeded",
    }
    elapsed = value.get("elapsed_seconds")
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "plan",
            "contracts",
            "live_runtime_high_water",
            "counts",
            "pool_departed",
            "endpoint_gate",
            "elapsed_seconds",
        }
        or value.get("schema_version") not in {SCHEMA_VERSION, DYNAMIC_SCHEMA_VERSION}
        or value.get("kind") != RUN_KIND
        or value.get("state") != "passed"
        or value.get("plan") != {"path": str(plan_path), "sha256": plan_sha256}
        or not isinstance(value.get("endpoint_gate"), dict)
        or value["endpoint_gate"].get("endpoint_jobs_sha256")
        != plan.get("endpoint_epoch", {}).get("endpoint_jobs_sha256")
        or value.get("contracts") != {
            "concurrency": CONCURRENCY,
            "provisioning_retries": PROVISIONING_RETRIES,
            "maximum_provisioning_attempts": MAX_PROVISIONING_ATTEMPTS,
            "resource_caps": {
                "cpu": CPU_CAP,
                "memory_mb": MEMORY_MB_CAP,
                "storage_mb": STORAGE_MB_CAP,
            },
            "model_calls": 0,
            "harness_invocations": 0,
            "verifier_execution": "background-program",
            "shared_verifier_taskset_retries": 0,
            "maximum_shared_verifier_attempts": 1,
            "raw_output_retained": False,
        }
        or value.get("live_runtime_high_water") != CONCURRENCY
        or not isinstance(counts, dict)
        or set(counts) != required_counts
        or any(not _plain_int(counts.get(key)) for key in required_counts)
        or counts["tasks"] != SELECTED_TASKS
        or counts["provisioned"] != SELECTED_TASKS
        or not SELECTED_TASKS <= counts["provisioning_attempts"] <= SELECTED_TASKS * MAX_PROVISIONING_ATTEMPTS
        or counts["provisioning_retries"] != counts["provisioning_attempts"] - SELECTED_TASKS
        or counts["provisioning_retries"] > SELECTED_TASKS * PROVISIONING_RETRIES
        or any(
            counts[key] != 0
            for key in (
                "provisioning_failures",
                "provisioning_cleanup_failures",
                "setup_failures",
                "benign_exec_failures",
                "shared_verifier_failures",
                "cleanup_failures",
            )
        )
        or any(
            counts[key] != SELECTED_TASKS
            for key in (
                "setup_succeeded",
                "benign_exec_succeeded",
                "shared_verifier_executed",
                "taskset_cleanup_succeeded",
                "runtime_cleanup_succeeded",
            )
        )
        or counts["shared_verifier_zero_reward"] + counts["shared_verifier_positive_reward"] != SELECTED_TASKS
        or counts["shared_verifier_retry_attempts"] != 0
        or counts["taskset_close_succeeded"] != 1
        or isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or elapsed < 0
    ):
        raise TaskImageSoakError("run_result_invalid")


def run(
    plan_path: Path,
    plan_sha256: str,
    output: Path,
    *,
    worker_manifest: Path,
    worker_manifest_sha256: str,
    walltime_receipt: Path,
    walltime_receipt_sha256: str,
) -> dict[str, Any]:
    plan = validate_plan(plan_path, plan_sha256)
    binding = _plan_endpoint_binding(plan)
    run_root = _private_directory(output, "run_output_invalid")
    if (
        worker_manifest != run_root / "endpoint-generation/direct_kimi_workers.json"
        or walltime_receipt != run_root / "endpoint-walltime.json"
    ):
        raise TaskImageSoakError("endpoint_gate_path_invalid")
    for name in ("run-result.json", "sandoq-provider-context.json"):
        if os.path.lexists(run_root / name):
            raise TaskImageSoakError("run_output_not_fresh")
    _validate_execution_environment(run_root)
    endpoint_gate = _validate_endpoint_gate(
        manifest_path=worker_manifest,
        manifest_sha256=worker_manifest_sha256,
        walltime_path=walltime_receipt,
        walltime_sha256=walltime_receipt_sha256,
        endpoint_jobs_sha256=plan["endpoint_epoch"]["endpoint_jobs_sha256"],
        binding=binding,
        revalidate_live_source=True,
    )
    try:
        from terminal_bench_vmvm.sandoq_provider_context import snapshot_provider_context

        snapshot_provider_context(os.environ, run_root / "sandoq-provider-context.json")
    except Exception as error:
        raise TaskImageSoakError("provider_snapshot_invalid") from error
    _validate_provider_snapshot(run_root / "sandoq-provider-context.json")
    taskset, tasks = _load_taskset(plan)
    logging.disable(logging.CRITICAL)
    outcome = asyncio.run(execute_soak(taskset, tasks))
    pool_departed = False
    try:
        from sandoq_provider.pool import depart_pool_client

        depart_pool_client()
        pool_departed = True
    except Exception:
        pool_departed = False
    passed = outcome["state"] == "passed" and pool_departed
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": RUN_KIND,
        "state": "passed" if passed else "unavailable",
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "endpoint_gate": endpoint_gate,
        "contracts": {
            "concurrency": CONCURRENCY,
            "provisioning_retries": PROVISIONING_RETRIES,
            "maximum_provisioning_attempts": MAX_PROVISIONING_ATTEMPTS,
            "resource_caps": {
                "cpu": CPU_CAP,
                "memory_mb": MEMORY_MB_CAP,
                "storage_mb": STORAGE_MB_CAP,
            },
            "model_calls": 0,
            "harness_invocations": 0,
            "verifier_execution": "background-program",
            "shared_verifier_taskset_retries": 0,
            "maximum_shared_verifier_attempts": 1,
            "raw_output_retained": False,
        },
        "live_runtime_high_water": outcome["live_runtime_high_water"],
        "counts": outcome["counts"],
        "pool_departed": pool_departed,
        "elapsed_seconds": outcome["elapsed_seconds"],
    }
    body = _publish_private(run_root / "run-result.json", value)
    _produce_cleanup_evidence(run_root)
    if passed:
        _revalidate_cleanup(run_root)
    return {
        "kind": RUN_KIND,
        "state": value["state"],
        "run_result_sha256": _sha256(body),
    }


def _produce_cleanup_evidence(run_root: Path) -> None:
    """Close the durable pool ledger and retain revalidatable private evidence."""

    socket_value = os.environ.get("OCI_RUNNER_POOL_SOCKET", "")
    owner = os.environ.get("SANDOQ_OWNER", "")
    if not socket_value or not owner:
        raise TaskImageSoakError("cleanup_environment_invalid")
    socket_path = Path(socket_value)
    marker_path = socket_path.with_suffix(".drained.json")
    marker_record, marker_body = _stable_artifact(marker_path, "pool_drain_invalid", private=True)
    if marker_record["bytes"] < 1:
        raise TaskImageSoakError("pool_drain_invalid")
    destination = run_root / "pool.drained.json"
    try:
        legacy._publish_bundle(run_root, {destination: marker_body})
        from sandoq_pool_cleanup import verify_pool_cleanup

        asyncio.run(
            verify_pool_cleanup(
                run_root,
                base_url=os.environ["OCI_RUNNER_BASE_URL"],
                owner=owner,
                concurrency=32,
                wal_path=run_root / "control/sandoq-pool.wal.jsonl",
            )
        )
        cleanup_sanitizer.sanitize(
            run_root / "pool_cleanup_audit.json",
            run_root / "pool_events.jsonl",
            run_root / "control/sandoq-pool.wal.jsonl",
            destination,
            run_root / "sandoq_cleanup_audit.json",
        )
    except Exception as error:
        raise TaskImageSoakError("cleanup_evidence_invalid") from error


def _revalidate_cleanup(run_root: Path) -> tuple[dict[str, int | str], dict[str, Any], dict[str, dict[str, int | str]]]:
    paths = {
        "raw_cleanup": run_root / "pool_cleanup_audit.json",
        "event_log": run_root / "pool_events.jsonl",
        "wal": run_root / "control/sandoq-pool.wal.jsonl",
        "drain_marker": run_root / "pool.drained.json",
        "sanitized_cleanup": run_root / "sandoq_cleanup_audit.json",
    }
    records: dict[str, dict[str, int | str]] = {}
    bodies: dict[str, bytes] = {}
    for label, path in paths.items():
        records[label], bodies[label] = _stable_artifact(path, "cleanup_evidence_invalid", private=True)
    sanitized = _strict_json(bodies["sanitized_cleanup"], "cleanup_evidence_invalid")
    try:
        with tempfile.TemporaryDirectory(prefix="k3-task-image-cleanup-audit-") as directory:
            recomputed = cleanup_sanitizer.sanitize(
                paths["raw_cleanup"],
                paths["event_log"],
                paths["wal"],
                paths["drain_marker"],
                Path(directory) / "recomputed.json",
            )
    except Exception as error:
        raise TaskImageSoakError("cleanup_evidence_invalid") from error
    if sanitized != recomputed:
        raise TaskImageSoakError("cleanup_evidence_invalid")
    count_keys = (
        "recorded_outer_sessions",
        "verified_http_404",
        "assignments_acquired",
        "assignments_cleanup_verified",
        "outer_sessions_created",
        "outer_sessions_deleted",
    )
    if (
        sanitized.get("schema_version") != 1
        or sanitized.get("kind") != "sandoq-pool-cleanup"
        or sanitized.get("state") != "passed"
        or sanitized.get("failures") != 0
        or any(not _plain_int(sanitized.get(key), minimum=1) for key in count_keys)
        or sanitized["recorded_outer_sessions"] != sanitized["verified_http_404"]
        or sanitized["recorded_outer_sessions"] != sanitized["outer_sessions_created"]
        or sanitized["outer_sessions_created"] != sanitized["outer_sessions_deleted"]
        or sanitized["assignments_acquired"] != sanitized["assignments_cleanup_verified"]
        or not SELECTED_TASKS <= sanitized["assignments_acquired"] <= SELECTED_TASKS * MAX_PROVISIONING_ATTEMPTS
        or sanitized.get("assignment_event_order_high_water") != CONCURRENCY
        or sanitized.get("assignment_measured_high_water") != CONCURRENCY
        or sanitized.get("outer_session_high_water") != CONCURRENCY
    ):
        raise TaskImageSoakError("cleanup_contract_invalid")
    return records["sanitized_cleanup"], sanitized, records


def _build_receipt(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_root: Path,
) -> dict[str, Any]:
    plan = validate_plan(plan_path, plan_sha256)
    binding = _plan_endpoint_binding(plan)
    run_record, run_body = _stable_artifact(run_root / "run-result.json", "run_result_invalid", private=True)
    run_value = _strict_json(run_body, "run_result_invalid")
    _validate_run_value(run_value, plan_path.resolve(strict=True), plan_sha256, plan)
    endpoint_gate = run_value["endpoint_gate"]
    if (
        Path(str(endpoint_gate["worker_manifest"]["path"]))
        != run_root / "endpoint-generation/direct_kimi_workers.json"
        or Path(str(endpoint_gate["walltime_receipt"]["path"]))
        != run_root / "endpoint-walltime.json"
    ):
        raise TaskImageSoakError("endpoint_gate_path_invalid")
    observed_endpoint_gate = _validate_endpoint_gate(
        manifest_path=Path(str(endpoint_gate["worker_manifest"]["path"])),
        manifest_sha256=str(endpoint_gate["worker_manifest"]["sha256"]),
        walltime_path=Path(str(endpoint_gate["walltime_receipt"]["path"])),
        walltime_sha256=str(endpoint_gate["walltime_receipt"]["sha256"]),
        endpoint_jobs_sha256=str(endpoint_gate["endpoint_jobs_sha256"]),
        binding=binding,
        revalidate_live_source=False,
    )
    if observed_endpoint_gate != endpoint_gate:
        raise TaskImageSoakError("endpoint_gate_invalid")
    if run_value.get("pool_departed") is not True:
        raise TaskImageSoakError("run_result_invalid")
    snapshot_record, _snapshot = _validate_provider_snapshot(run_root / "sandoq-provider-context.json")
    cleanup_record, cleanup, cleanup_records = _revalidate_cleanup(run_root)
    value: dict[str, Any] = {
        "schema_version": plan["schema_version"],
        "kind": RECEIPT_KIND,
        "state": "passed",
        "source_revision": plan["source_revision"],
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "selection": {
            "candidate_count": legacy.EXPECTED_TASK_COUNT,
            "selected_count": SELECTED_TASKS,
            "selector_sha256": plan["selection"]["selector"]["sha256"],
            "membership_disclosed": False,
        },
        "execution": {
            "concurrency": CONCURRENCY,
            "live_runtime_high_water": run_value["live_runtime_high_water"],
            "taskset_setup_succeeded": run_value["counts"]["setup_succeeded"],
            "benign_exec_succeeded": run_value["counts"]["benign_exec_succeeded"],
            "shared_verifier_executed": run_value["counts"]["shared_verifier_executed"],
            "provisioning_retries": PROVISIONING_RETRIES,
            "model_calls": 0,
            "harness_invocations": 0,
            "raw_output_retained": False,
        },
        "sandbox": {
            "environment": PROVIDER_ENVIRONMENT,
            "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
            "lifecycle_c64_soak_sha256": LIFECYCLE_SOAK_SHA256,
            "resource_caps": {
                "cpu": CPU_CAP,
                "memory_mb": MEMORY_MB_CAP,
                "storage_mb": STORAGE_MB_CAP,
            },
        },
        "endpoint_epoch": {
            "capacity_receipt_sha256": binding.capacity_receipt_sha256,
            "endpoint_jobs_sha256": endpoint_gate["endpoint_jobs_sha256"],
            "minimum_remaining_seconds": MINIMUM_ENDPOINT_REMAINING_SECONDS,
            "walltime_gate_task_count": ENDPOINT_GATE_TASK_COUNT,
            "observed_minimum_remaining_seconds": endpoint_gate["observed_minimum_remaining_seconds"],
            "worker_manifest": endpoint_gate["worker_manifest"],
            "walltime_receipt": endpoint_gate["walltime_receipt"],
        },
        "cleanup": {
            "assignment_high_water": cleanup["assignment_measured_high_water"],
            "outer_session_high_water": cleanup["outer_session_high_water"],
            "assignments_acquired": cleanup["assignments_acquired"],
            "assignments_cleanup_verified": cleanup["assignments_cleanup_verified"],
            "outer_sessions_created": cleanup["outer_sessions_created"],
            "outer_sessions_deleted": cleanup["outer_sessions_deleted"],
            "verified_http_404": cleanup["verified_http_404"],
            "failures": 0,
        },
        "artifacts": {
            "run_result": run_record,
            "provider_context": snapshot_record,
            "sanitized_cleanup": cleanup_record,
            "raw_cleanup": cleanup_records["raw_cleanup"],
            "pool_event_log": cleanup_records["event_log"],
            "pool_wal": cleanup_records["wal"],
            "pool_drain": cleanup_records["drain_marker"],
        },
        "privacy": {
            "aggregate_only": True,
            "task_ids_present": False,
            "provider_session_ids_present": False,
            "prompts_present": False,
            "raw_output_present": False,
            "error_text_present": False,
        },
    }
    if plan["schema_version"] == DYNAMIC_SCHEMA_VERSION:
        value["endpoint_binding"] = binding.public_record
    value["certificate_sha256"] = _sha256(_canonical(value))
    return value


def certify(plan_path: Path, plan_sha256: str, run_root: Path, output: Path) -> dict[str, Any]:
    root = _private_directory(run_root, "run_output_invalid")
    if output != root / "receipt.json" or os.path.lexists(output):
        raise TaskImageSoakError("receipt_output_invalid")
    value = _build_receipt(plan_path=plan_path, plan_sha256=plan_sha256, run_root=root)
    body = _publish_private(output, value)
    return {"kind": RECEIPT_KIND, "state": "passed", "receipt_sha256": _sha256(body)}


def validate_task_image_soak_receipt(
    path: Path,
    expected_sha256: str,
    *,
    expected_revision: str | None = None,
) -> tuple[Path, bytes]:
    """Revalidate a durable soak receipt for production-plan binding."""

    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise TaskImageSoakError("receipt_invalid")
    canonical_path = path.resolve(strict=True)
    record, body = _stable_artifact(canonical_path, "receipt_invalid", private=True)
    value = _strict_json(body, "receipt_invalid")
    plan_record = value.get("plan")
    if (
        canonical_path != path
        or record["sha256"] != expected_sha256
        or value.get("schema_version") not in {SCHEMA_VERSION, DYNAMIC_SCHEMA_VERSION}
        or value.get("kind") != RECEIPT_KIND
        or value.get("state") != "passed"
        or not isinstance(plan_record, dict)
        or set(plan_record) != {"path", "sha256"}
        or SHA256_RE.fullmatch(str(plan_record.get("sha256", ""))) is None
    ):
        raise TaskImageSoakError("receipt_invalid")
    run_root = _private_directory(canonical_path.parent, "receipt_invalid")
    expected = _build_receipt(
        plan_path=Path(str(plan_record["path"])),
        plan_sha256=str(plan_record["sha256"]),
        run_root=run_root,
    )
    schema_version = value["schema_version"]
    if (
        schema_version == DYNAMIC_SCHEMA_VERSION
        and (
            not isinstance(value.get("endpoint_binding"), dict)
            or expected.get("schema_version") != DYNAMIC_SCHEMA_VERSION
            or value.get("endpoint_binding") != expected.get("endpoint_binding")
        )
    ) or (
        schema_version == SCHEMA_VERSION
        and ("endpoint_binding" in value or "endpoint_binding" in expected)
    ):
        raise TaskImageSoakError("receipt_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("certificate_sha256", None)
    if (
        value != expected
        or claimed != _sha256(_canonical(unsigned))
        or (expected_revision is not None and value.get("source_revision") != expected_revision)
    ):
        raise TaskImageSoakError("receipt_invalid")
    return canonical_path, body


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--project-root", type=Path, required=True)
    materialize_parser.add_argument("--expected-revision", required=True)
    materialize_parser.add_argument("--dataset", type=Path, required=True)
    materialize_parser.add_argument("--image-manifest", type=Path, required=True)
    materialize_parser.add_argument("--stock-capacity", type=Path, default=STOCK_CAPACITY)
    materialize_parser.add_argument("--stock-capacity-sha256", default=STOCK_CAPACITY_SHA256)
    materialize_parser.add_argument("--output", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--plan", type=Path, required=True)
    verify_parser.add_argument("--plan-sha256", required=True)
    verify_parser.add_argument("--format", choices=("json", "tsv", "launch-tsv"), default="json")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--plan", type=Path, required=True)
    run_parser.add_argument("--plan-sha256", required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--worker-manifest", type=Path, required=True)
    run_parser.add_argument("--worker-manifest-sha256", required=True)
    run_parser.add_argument("--walltime-receipt", type=Path, required=True)
    run_parser.add_argument("--walltime-receipt-sha256", required=True)

    certify_parser = subparsers.add_parser("certify")
    certify_parser.add_argument("--plan", type=Path, required=True)
    certify_parser.add_argument("--plan-sha256", required=True)
    certify_parser.add_argument("--run-root", type=Path, required=True)
    certify_parser.add_argument("--output", type=Path, required=True)

    receipt_parser = subparsers.add_parser("validate-receipt")
    receipt_parser.add_argument("--receipt", type=Path, required=True)
    receipt_parser.add_argument("--receipt-sha256", required=True)
    receipt_parser.add_argument("--expected-revision")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "materialize":
            result = materialize(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                dataset=args.dataset,
                image_manifest=args.image_manifest,
                output=args.output,
                stock_capacity=args.stock_capacity,
                stock_capacity_sha256=args.stock_capacity_sha256,
            )
        elif args.command == "verify":
            plan = validate_plan(args.plan, args.plan_sha256)
            if args.format == "tsv":
                print(
                    plan["source_revision"],
                    plan["selection"]["count"],
                    plan["selection"]["selector"]["sha256"],
                    sep="\t",
                )
                return 0
            if args.format == "launch-tsv":
                binding = _plan_endpoint_binding(plan)
                capacity = plan["source"]["stock_model_c64"]
                print(
                    plan["source_revision"],
                    plan["selection"]["count"],
                    plan["selection"]["selector"]["sha256"],
                    binding.deployment_id,
                    str(binding.deployment_root),
                    capacity["path"],
                    capacity["sha256"],
                    binding.endpoint_jobs_sha256,
                    sep="\t",
                )
                return 0
            result = {
                "kind": PLAN_KIND,
                "state": "authorized",
                "selected_tasks": plan["selection"]["count"],
                "concurrency": CONCURRENCY,
            }
        elif args.command == "run":
            result = run(
                args.plan,
                args.plan_sha256,
                args.output,
                worker_manifest=args.worker_manifest,
                worker_manifest_sha256=args.worker_manifest_sha256,
                walltime_receipt=args.walltime_receipt,
                walltime_receipt_sha256=args.walltime_receipt_sha256,
            )
        elif args.command == "certify":
            result = certify(args.plan, args.plan_sha256, args.run_root, args.output)
        else:
            path, body = validate_task_image_soak_receipt(
                args.receipt,
                args.receipt_sha256,
                expected_revision=args.expected_revision,
            )
            result = {
                "kind": RECEIPT_KIND,
                "state": "passed",
                "receipt": str(path),
                "receipt_sha256": _sha256(body),
            }
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:
        code = error.code if isinstance(error, TaskImageSoakError) else "unexpected_failure"
        _publish_terminal_status(code=code, state="blocked")
        print(json.dumps({"code": code, "kind": RECEIPT_KIND, "state": "blocked"}, sort_keys=True), file=sys.stderr)
        return 2
    if result.get("state") in {"authorized", "passed"}:
        _publish_terminal_status(code="completed", state="passed")
    else:
        _publish_terminal_status(code="run_unavailable", state="blocked")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("state") in {"authorized", "passed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
