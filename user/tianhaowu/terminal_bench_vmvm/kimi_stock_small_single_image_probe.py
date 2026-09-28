#!/usr/bin/env python3
"""Recheck one opaque task image selected from a sealed failed soak.

The source task and image are derived in memory from the private c64 soak plan
and its cleanup-verified pool ledger.  Neither identity, provider error text,
nor task content is copied into the c1 plan, run result, receipt, or stdout.
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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sanitize_sandoq_cleanup_audit as cleanup_sanitizer

SCHEMA_VERSION = 1
PLAN_KIND = "kimi-k3-stock-small-single-image-provisioning-probe-plan"
RUN_KIND = "kimi-k3-stock-small-single-image-provisioning-probe-run"
RECEIPT_KIND = "kimi-k3-stock-small-single-image-provisioning-probe"

CONCURRENCY = 1
SELECTED_TASKS = 2_499
SOURCE_CONCURRENCY = 64
SOURCE_PLAN_SCHEMA_VERSION = 1
SOURCE_PLAN_KIND = "kimi-k3-stock-small-task-image-c64-soak-plan"
SOURCE_RUN_KIND = "kimi-k3-stock-small-task-image-c64-soak-run"
SOURCE_FAILURE_ATTEMPTS = 9
PROBE_ATTEMPTS = 3
ATTEMPT_TIMEOUT_SECONDS = 1_800
CLEANUP_TIMEOUT_SECONDS = 900

PROVIDER_ENVIRONMENT = "oci-runner-firecracker-small"
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
CPU_CAP = 1
MEMORY_MB_CAP = 2_048
STORAGE_MB_CAP = 10_240
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024

ECR_REGISTRY = "168653207203.dkr.ecr.us-east-2.amazonaws.com"
ECR_PULL_THROUGH_PREFIX = "pt_dockerio"
STATUS_FILE_ENV = "KIMI_SINGLE_IMAGE_PROBE_STATUS_FILE"
STATUS_FILE_NAME = "single-image-probe-status.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")

SOURCE_ACQUIRED = 392
SOURCE_READY = 383
SOURCE_CLEAN_RELEASES = 383
SOURCE_FAILED_RELEASES = 9
SOURCE_COMPLETED_TASKS = 320

ACQUIRED_KEYS = {
    "schema_version",
    "record_type",
    "event",
    "timestamp",
    "slurm_job_id",
    "wandb_run_id",
    "assignment_id",
    "outer_session_id",
    "slot_id",
    "generation",
    "reuse_count",
    "reuse_threshold",
    "requested_image",
    "exec_url",
    "port_urls",
    "pool_wait_seconds",
    "outer_age_seconds",
    "active_assignment_count",
    "ticket_id",
    "status",
}
READY_KEYS = {
    "schema_version",
    "record_type",
    "event",
    "timestamp",
    "slurm_job_id",
    "wandb_run_id",
    "assignment_id",
    "slot_id",
    "requested_image",
    "bootstrap_seconds",
}
RELEASE_KEYS = {
    "schema_version",
    "record_type",
    "event",
    "timestamp",
    "slurm_job_id",
    "wandb_run_id",
    "assignment_id",
    "outer_session_id",
    "slot_id",
    "generation",
    "reuse_count",
    "reuse_threshold",
    "status",
    "reason",
    "retirement_reason",
    "duration",
    "nested_recycle_verified",
    "outer_retired",
    "outer_deletion_verified_http_status",
    "poisoned",
    "shell_deleted",
    "shell_id",
    "shell_generation",
    "managed_shell_recovery_count",
    "shell_failure_status",
    "cleanup_gateway_retry_count",
    "cleanup_gateway_retry_exhausted_count",
    "timings",
}


class SingleImageProbeError(RuntimeError):
    """A fail-closed condition represented by an aggregate-only code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TargetEvidence:
    image: str
    summary: dict[str, Any]


def _soak_module() -> Any:
    import kimi_stock_small_task_image_soak

    return kimi_stock_small_task_image_soak


def _workflow_dir() -> Path:
    return Path(__file__).resolve(strict=True).parent


def _launcher_path() -> Path:
    return _workflow_dir() / "run_kimi_stock_small_single_image_probe.sbatch"


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


def _strict_json(body: bytes, code: str) -> dict[str, Any]:
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
        raise SingleImageProbeError(code) from error
    if not isinstance(value, dict) or body != _canonical(value):
        raise SingleImageProbeError(code)
    return value


def _json_lines(body: bytes, code: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SingleImageProbeError(code) from error
    if not decoded.endswith("\n"):
        raise SingleImageProbeError(code)
    for raw in decoded.splitlines():
        if not raw:
            raise SingleImageProbeError(code)
        value = _strict_json(raw.encode() + b"\n", code)
        if value.get("schema_version") != 2 or value.get("record_type") != "pool_event":
            raise SingleImageProbeError(code)
        rows.append(value)
    if not rows:
        raise SingleImageProbeError(code)
    return rows


def _stable(path: Path, code: str, *, private: bool = True) -> tuple[dict[str, int | str], bytes]:
    try:
        normalized = Path(os.path.normpath(path))
        resolved = path.resolve(strict=True)
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, RuntimeError) as error:
        raise SingleImageProbeError(code) from error
    try:
        opened = os.fstat(descriptor)
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise SingleImageProbeError(code)
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
        raise SingleImageProbeError(code)
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}, b"".join(chunks)


def _private_directory(path: Path, code: str) -> Path:
    try:
        normalized = Path(os.path.normpath(path))
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except (OSError, RuntimeError) as error:
        raise SingleImageProbeError(code) from error
    if (
        not path.is_absolute()
        or path != normalized
        or path != resolved
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise SingleImageProbeError(code)
    return resolved


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
        raise SingleImageProbeError("source_identity_invalid") from error
    if completed.stderr:
        raise SingleImageProbeError("source_identity_invalid")
    return completed.stdout.strip()


def _validate_source(project_root: Path, expected_revision: str) -> Path:
    if REVISION_RE.fullmatch(expected_revision) is None:
        raise SingleImageProbeError("source_identity_invalid")
    try:
        root = project_root.resolve(strict=True)
    except OSError as error:
        raise SingleImageProbeError("source_identity_invalid") from error
    repositories = (root, root / "deps/verifiers", root / "deps/renderers")
    if (
        root != project_root
        or not root.is_dir()
        or _git(root, "rev-parse", "HEAD") != expected_revision
        or any(
            _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
            for repository in repositories
        )
    ):
        raise SingleImageProbeError("source_identity_invalid")
    return root


def _validate_provider_profile() -> tuple[dict[str, int | str], bytes]:
    path = _provider_profile_path().resolve(strict=True)
    record, body = _stable(path, "provider_profile_invalid", private=False)
    value = _strict_json(body, "provider_profile_invalid")
    if (
        record["sha256"] != PROVIDER_PROFILE_SHA256
        or value.get("schema_version") != 3
        or value.get("environment") != PROVIDER_ENVIRONMENT
        or value.get("task_network") != "host"
        or value.get("effective_task_network") != "public"
        or value.get("transport_mode") != "auto"
    ):
        raise SingleImageProbeError("provider_profile_invalid")
    return record, body


def _record_body(record: object, code: str, *, private: bool = True) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise SingleImageProbeError(code)
    path_value = record.get("path")
    if (
        not isinstance(path_value, str)
        or not _plain_int(record.get("bytes"))
        or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
    ):
        raise SingleImageProbeError(code)
    path = Path(path_value)
    observed, body = _stable(path, code, private=private)
    if observed != record:
        raise SingleImageProbeError(code)
    return path, body


def _publish_private(path: Path, value: Mapping[str, object]) -> bytes:
    body = _canonical(value)
    if len(body) > MAX_RECEIPT_BYTES or path.parent != _private_directory(path.parent, "output_invalid"):
        raise SingleImageProbeError("output_invalid")
    temporary: Path | None = None
    descriptor = -1
    try:
        descriptor, raw_temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        temporary = Path(raw_temporary)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise SingleImageProbeError("output_publish_failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return body


def _publish_terminal_status(*, code: str, state: str) -> None:
    output_value = os.environ.get("PRIME_RL_OUTPUT_DIR")
    status_value = os.environ.get(STATUS_FILE_ENV)
    if output_value is None or status_value is None:
        return
    try:
        output = Path(output_value)
        status = Path(status_value)
        if (
            status != output / "control" / STATUS_FILE_NAME
            or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is None
            or state not in {"blocked", "certified"}
        ):
            return
        _publish_private(
            status,
            {"schema_version": SCHEMA_VERSION, "kind": RECEIPT_KIND, "state": state, "code": code},
        )
    except BaseException:
        return


def _source_plan(path: Path, expected_sha256: str) -> tuple[dict[str, int | str], dict[str, Any]]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise SingleImageProbeError("source_plan_invalid")
    record, body = _stable(path, "source_plan_invalid")
    if record["sha256"] != expected_sha256:
        raise SingleImageProbeError("source_plan_invalid")
    value = _strict_json(body, "source_plan_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("plan_sha256", None)
    source = value.get("source")
    selection = value.get("selection")
    contracts = value.get("contracts")
    sandbox = contracts.get("sandbox") if isinstance(contracts, dict) else None
    execution = contracts.get("execution") if isinstance(contracts, dict) else None
    privacy = contracts.get("privacy") if isinstance(contracts, dict) else None
    if (
        set(value)
        != {
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
        or value.get("schema_version") != SOURCE_PLAN_SCHEMA_VERSION
        or value.get("kind") != SOURCE_PLAN_KIND
        or value.get("state") != "authorized"
        or REVISION_RE.fullmatch(str(value.get("source_revision", ""))) is None
        or claimed != _sha256(_canonical(unsigned))
        or not isinstance(source, dict)
        or not isinstance(selection, dict)
        or selection.get("count") != SELECTED_TASKS
        or not isinstance(contracts, dict)
        or contracts.get("task_count") != SELECTED_TASKS
        or contracts.get("concurrency") != SOURCE_CONCURRENCY
        or not isinstance(sandbox, dict)
        or sandbox.get("provider") != "sandoq"
        or sandbox.get("environment") != PROVIDER_ENVIRONMENT
        or sandbox.get("maximum_provisioning_attempts") != SOURCE_FAILURE_ATTEMPTS
        or not isinstance(execution, dict)
        or execution.get("model_calls") != 0
        or execution.get("harness_invocations") != 0
        or not isinstance(privacy, dict)
        or privacy.get("receipt") != "aggregate-only"
        or privacy.get("raw_command_output_retained") is not False
        or privacy.get("exception_text_retained") is not False
    ):
        raise SingleImageProbeError("source_plan_invalid")
    return record, value


def _pull_image(source_image: str) -> str:
    prefix = "docker.io/"
    if (
        not source_image.startswith(prefix)
        or source_image == prefix
        or any(character.isspace() for character in source_image)
        or "://" in source_image
    ):
        raise SingleImageProbeError("source_selection_invalid")
    upstream = source_image.removeprefix(prefix)
    if "/" not in upstream.split("@", 1)[0]:
        upstream = f"library/{upstream}"
    return f"{ECR_REGISTRY}/{ECR_PULL_THROUGH_PREFIX}/{upstream}"


def _event_identity(event: Mapping[str, Any], code: str) -> str:
    assignment_id = event.get("assignment_id")
    if not isinstance(assignment_id, str) or not assignment_id:
        raise SingleImageProbeError(code)
    return assignment_id


def _analyze_source_events(body: bytes) -> TargetEvidence:
    acquired: dict[str, str] = {}
    ready: set[str] = set()
    released: dict[str, dict[str, Any]] = {}
    high_water = 0
    for event in _json_lines(body, "source_pool_events_invalid"):
        name = event.get("event")
        if name == "assignment_acquired":
            if set(event) != ACQUIRED_KEYS:
                raise SingleImageProbeError("source_pool_events_invalid")
            assignment_id = _event_identity(event, "source_pool_events_invalid")
            image = event.get("requested_image")
            measured = event.get("active_assignment_count")
            if (
                assignment_id in acquired
                or not isinstance(image, str)
                or "@sha256:" not in image
                or not _plain_int(measured, minimum=1, maximum=SOURCE_CONCURRENCY)
            ):
                raise SingleImageProbeError("source_pool_events_invalid")
            acquired[assignment_id] = image
            high_water = max(high_water, measured)
        elif name == "assignment_ready":
            if set(event) != READY_KEYS:
                raise SingleImageProbeError("source_pool_events_invalid")
            assignment_id = _event_identity(event, "source_pool_events_invalid")
            if assignment_id in ready:
                raise SingleImageProbeError("source_pool_events_invalid")
            ready.add(assignment_id)
        elif name == "assignment_released":
            expected_keys = RELEASE_KEYS | ({"error"} if "error" in event else set())
            if set(event) != expected_keys:
                raise SingleImageProbeError("source_pool_events_invalid")
            assignment_id = _event_identity(event, "source_pool_events_invalid")
            if assignment_id in released:
                raise SingleImageProbeError("source_pool_events_invalid")
            released[assignment_id] = event

    if (
        len(acquired) != SOURCE_ACQUIRED
        or len(ready) != SOURCE_READY
        or len(released) != SOURCE_ACQUIRED
        or set(acquired) != set(released)
        or not ready.issubset(acquired)
        or high_water != SOURCE_CONCURRENCY
    ):
        raise SingleImageProbeError("source_pool_events_invalid")

    failed: set[str] = set()
    clean: set[str] = set()
    for assignment_id, event in released.items():
        if "error" in event:
            if (
                not isinstance(event.get("error"), str)
                or not event["error"]
                or event.get("status") != "poisoned"
                or event.get("reason") != "initialization_failure"
                or event.get("poisoned") is not True
                or event.get("nested_recycle_verified") is not False
                or event.get("outer_deletion_verified_http_status") != 404
                or event.get("shell_deleted") is not False
                or event.get("managed_shell_recovery_count") != 0
                or event.get("cleanup_gateway_retry_exhausted_count") != 0
                or assignment_id in ready
            ):
                raise SingleImageProbeError("source_failure_shape_invalid")
            failed.add(assignment_id)
        else:
            if (
                event.get("status") != "retired"
                or event.get("reason") != "rollout_complete"
                or event.get("poisoned") is not False
                or event.get("nested_recycle_verified") is not True
                or event.get("outer_deletion_verified_http_status") != 404
                or event.get("shell_deleted") is not True
                or event.get("cleanup_gateway_retry_exhausted_count") != 0
                or assignment_id not in ready
            ):
                raise SingleImageProbeError("source_failure_shape_invalid")
            clean.add(assignment_id)
    target_images = {acquired[assignment_id] for assignment_id in failed}
    target_assignments = {
        assignment_id for assignment_id, image in acquired.items() if image in target_images
    }
    if (
        len(failed) != SOURCE_FAILED_RELEASES
        or len(clean) != SOURCE_CLEAN_RELEASES
        or len(target_images) != 1
        or target_assignments != failed
    ):
        raise SingleImageProbeError("source_failure_shape_invalid")
    return TargetEvidence(
        image=next(iter(target_images)),
        summary={
            "source_assignments": SOURCE_ACQUIRED,
            "source_ready": SOURCE_READY,
            "source_clean_releases": SOURCE_CLEAN_RELEASES,
            "source_initialization_failures": SOURCE_FAILED_RELEASES,
            "source_failed_assignments": SOURCE_FAILED_RELEASES,
            "source_failed_targets": 1,
            "source_failed_target_ready": 0,
            "source_assignment_high_water": SOURCE_CONCURRENCY,
            "target_disclosed": False,
        },
    )


def _validate_target_membership(plan: Mapping[str, Any], target: str) -> None:
    source = plan.get("source")
    selection = plan.get("selection")
    if not isinstance(source, dict) or not isinstance(selection, dict):
        raise SingleImageProbeError("source_selection_invalid")
    _selector_path, selector_body = _record_body(selection.get("selector"), "source_selection_invalid")
    manifest_path, manifest_body = _record_body(
        source.get("image_manifest"), "source_selection_invalid", private=False
    )
    try:
        members = selector_body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise SingleImageProbeError("source_selection_invalid") from error
    manifest = _strict_json(manifest_body, "source_selection_invalid")
    images = manifest.get("images")
    if (
        len(members) != SELECTED_TASKS
        or len(set(members)) != SELECTED_TASKS
        or any(not member or "\t" in member for member in members)
        or not isinstance(images, dict)
    ):
        raise SingleImageProbeError("source_selection_invalid")
    matched = 0
    for member in members:
        entry = images.get(member)
        if not isinstance(entry, dict) or not isinstance(entry.get("agent"), str):
            raise SingleImageProbeError("source_selection_invalid")
        if _pull_image(entry["agent"]) == target:
            matched += 1
    if matched != 1 or not manifest_path.is_absolute():
        raise SingleImageProbeError("source_selection_invalid")


def _validate_source_run_result(
    value: Mapping[str, Any], source_plan_path: Path, source_plan_sha256: str
) -> None:
    counts = value.get("counts")
    contracts = value.get("contracts")
    expected_counts = {
        "tasks": SELECTED_TASKS,
        "provisioned": SOURCE_READY,
        "provisioning_attempts": SOURCE_ACQUIRED,
        "provisioning_retries": SOURCE_FAILED_RELEASES,
        "provisioning_failures": SELECTED_TASKS - SOURCE_READY,
        "provisioning_cleanup_failures": 0,
        "setup_succeeded": SOURCE_COMPLETED_TASKS,
        "benign_exec_succeeded": SOURCE_COMPLETED_TASKS,
        "shared_verifier_executed": SOURCE_COMPLETED_TASKS,
        "shared_verifier_zero_reward": SOURCE_COMPLETED_TASKS,
        "shared_verifier_positive_reward": 0,
        "shared_verifier_retry_attempts": 0,
        "setup_failures": 0,
        "benign_exec_failures": 0,
        "shared_verifier_failures": 0,
        "taskset_cleanup_succeeded": SOURCE_READY,
        "runtime_cleanup_succeeded": SOURCE_READY,
        "cleanup_failures": 0,
        "taskset_close_succeeded": 1,
    }
    if (
        value.get("schema_version") != SOURCE_PLAN_SCHEMA_VERSION
        or value.get("kind") != SOURCE_RUN_KIND
        or value.get("state") != "unavailable"
        or value.get("plan") != {"path": str(source_plan_path), "sha256": source_plan_sha256}
        or value.get("live_runtime_high_water") != SOURCE_CONCURRENCY
        or value.get("pool_departed") is not True
        or counts != expected_counts
        or not isinstance(contracts, dict)
        or contracts.get("concurrency") != SOURCE_CONCURRENCY
        or contracts.get("maximum_provisioning_attempts") != SOURCE_FAILURE_ATTEMPTS
        or contracts.get("model_calls") != 0
        or contracts.get("harness_invocations") != 0
        or contracts.get("raw_output_retained") is not False
    ):
        raise SingleImageProbeError("source_run_result_invalid")


def _source_evidence(
    source_plan_path: Path,
    source_plan_sha256: str,
    source_run_root: Path,
) -> tuple[dict[str, Any], TargetEvidence, dict[str, Any]]:
    source_plan_record, source_plan = _source_plan(source_plan_path, source_plan_sha256)
    run_root = _private_directory(source_run_root, "source_run_invalid")
    paths = {
        "run_result": run_root / "run-result.json",
        "raw_cleanup": run_root / "pool_cleanup_audit.json",
        "event_log": run_root / "pool_events.jsonl",
        "wal": run_root / "control/sandoq-pool.wal.jsonl",
        "drain_marker": run_root / "pool.drained.json",
        "sanitized_cleanup": run_root / "sandoq_cleanup_audit.json",
    }
    records: dict[str, dict[str, int | str]] = {}
    bodies: dict[str, bytes] = {}
    for label, path in paths.items():
        records[label], bodies[label] = _stable(path, "source_run_invalid")
    run_result = _strict_json(bodies["run_result"], "source_run_result_invalid")
    _validate_source_run_result(run_result, source_plan_path, source_plan_sha256)
    sanitized = _strict_json(bodies["sanitized_cleanup"], "source_cleanup_invalid")
    try:
        with tempfile.TemporaryDirectory(prefix="k3-single-image-source-audit-") as directory:
            recomputed = cleanup_sanitizer.sanitize(
                paths["raw_cleanup"],
                paths["event_log"],
                paths["wal"],
                paths["drain_marker"],
                Path(directory) / "recomputed.json",
            )
    except Exception as error:
        raise SingleImageProbeError("source_cleanup_invalid") from error
    if (
        sanitized != recomputed
        or sanitized.get("state") != "passed"
        or sanitized.get("assignments_acquired") != SOURCE_ACQUIRED
        or sanitized.get("assignments_cleanup_verified") != SOURCE_ACQUIRED
        or sanitized.get("outer_sessions_created") != SOURCE_ACQUIRED
        or sanitized.get("outer_sessions_deleted") != SOURCE_ACQUIRED
        or sanitized.get("recovered_poisoned_assignments") != SOURCE_FAILED_RELEASES
        or sanitized.get("assignment_event_order_high_water") != SOURCE_CONCURRENCY
        or sanitized.get("assignment_measured_high_water") != SOURCE_CONCURRENCY
        or sanitized.get("outer_session_high_water") != SOURCE_CONCURRENCY
        or sanitized.get("failures") != 0
    ):
        raise SingleImageProbeError("source_cleanup_invalid")
    target = _analyze_source_events(bodies["event_log"])
    _validate_target_membership(source_plan, target.image)
    artifact_bundle = {
        "source_plan": source_plan_record,
        "source_run_root": str(run_root),
        **records,
    }
    derivation = {
        **target.summary,
        "selected_target_matches": 1,
        "algorithm": "unique-nine-attempt-initialization-failure-v1",
    }
    return artifact_bundle, target, derivation


def _contracts() -> dict[str, Any]:
    return {
        "purpose": "opaque-single-image-provisioning-recheck",
        "concurrency": CONCURRENCY,
        "source_failure_attempts": SOURCE_FAILURE_ATTEMPTS,
        "probe_attempts": PROBE_ATTEMPTS,
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
            "maximum_live_assignments": CONCURRENCY,
            "maximum_reuse_count": 1,
        },
        "execution": {
            "provisioning_and_readiness_only": True,
            "taskset_setup": False,
            "commands": 0,
            "verifier_invocations": 0,
            "model_calls": 0,
            "harness_invocations": 0,
        },
        "classification": {
            "transient_success": "one_ready_before_attempt_limit",
            "repeatable_failure": "all_attempts_failed_before_ready",
            "repeatable_failure_threshold": PROBE_ATTEMPTS,
        },
        "privacy": {
            "source_evidence": "private-sealed-artifacts",
            "target_identity_retained": False,
            "task_content_read": False,
            "raw_error_retained": False,
            "receipt": "aggregate-only",
        },
        "cleanup": {
            "typed_404_required": True,
            "all_assignments_released": True,
            "all_outer_sessions_deleted": True,
        },
    }


def materialize(
    *,
    project_root: Path,
    expected_revision: str,
    source_plan: Path,
    source_plan_sha256: str,
    source_run_root: Path,
    output: Path,
) -> dict[str, Any]:
    root = _validate_source(project_root, expected_revision)
    output_parent = _private_directory(output.parent, "output_invalid")
    if output != output_parent / output.name or output.name in {"", ".", ".."} or os.path.lexists(output):
        raise SingleImageProbeError("output_invalid")
    artifacts, _target, derivation = _source_evidence(
        source_plan.resolve(strict=True), source_plan_sha256, source_run_root.resolve(strict=True)
    )
    tool = Path(__file__).resolve(strict=True)
    launcher = _launcher_path().resolve(strict=True)
    profile_record, _profile_body = _validate_provider_profile()
    tool_record, _tool_body = _stable(tool, "tool_identity_invalid", private=False)
    launcher_record, _launcher_body = _stable(launcher, "tool_identity_invalid", private=False)
    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "state": "authorized",
        "source_revision": expected_revision,
        "source": {
            "project_root": str(root),
            "tool": tool_record,
            "launcher": launcher_record,
            "provider_profile": profile_record,
            "failed_soak": artifacts,
        },
        "target_derivation": derivation,
        "contracts": _contracts(),
    }
    plan["evidence_bundle_sha256"] = _sha256(
        _canonical({"failed_soak": artifacts, "target_derivation": derivation})
    )
    plan["plan_sha256"] = _sha256(_canonical(plan))
    try:
        os.mkdir(output, 0o700)
    except OSError as error:
        raise SingleImageProbeError("output_publish_failed") from error
    body = _publish_private(output / "plan.json", plan)
    return {
        "kind": PLAN_KIND,
        "state": "authorized",
        "concurrency": CONCURRENCY,
        "probe_attempts": PROBE_ATTEMPTS,
        "plan": str(output / "plan.json"),
        "plan_file_sha256": _sha256(body),
        "target_disclosed": False,
    }


def validate_plan(path: Path, expected_sha256: str) -> tuple[dict[str, Any], TargetEvidence]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise SingleImageProbeError("plan_invalid")
    record, body = _stable(path, "plan_invalid")
    if record["sha256"] != expected_sha256:
        raise SingleImageProbeError("plan_invalid")
    value = _strict_json(body, "plan_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("plan_sha256", None)
    source = value.get("source")
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "source_revision",
            "source",
            "target_derivation",
            "contracts",
            "evidence_bundle_sha256",
            "plan_sha256",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != PLAN_KIND
        or value.get("state") != "authorized"
        or REVISION_RE.fullmatch(str(value.get("source_revision", ""))) is None
        or claimed != _sha256(_canonical(unsigned))
        or value.get("contracts") != _contracts()
        or not isinstance(source, dict)
        or set(source) != {"project_root", "tool", "launcher", "provider_profile", "failed_soak"}
    ):
        raise SingleImageProbeError("plan_invalid")
    root = _validate_source(Path(str(source["project_root"])), str(value["source_revision"]))
    tool, _ = _record_body(source["tool"], "tool_identity_invalid", private=False)
    launcher, _ = _record_body(source["launcher"], "tool_identity_invalid", private=False)
    profile, _ = _record_body(source["provider_profile"], "provider_profile_invalid", private=False)
    expected_profile, _profile_body = _validate_provider_profile()
    failed_soak = source.get("failed_soak")
    if not isinstance(failed_soak, dict):
        raise SingleImageProbeError("source_run_invalid")
    source_plan_record = failed_soak.get("source_plan")
    source_run_root = failed_soak.get("source_run_root")
    if (
        not isinstance(source_plan_record, dict)
        or not isinstance(source_run_root, str)
        or tool != Path(__file__).resolve(strict=True)
        or launcher != _launcher_path().resolve(strict=True)
        or profile != Path(str(expected_profile["path"]))
        or root != Path(str(source["project_root"]))
    ):
        raise SingleImageProbeError("plan_binding_invalid")
    source_plan_path = Path(str(source_plan_record.get("path", "")))
    source_plan_sha256 = str(source_plan_record.get("sha256", ""))
    artifacts, target, derivation = _source_evidence(
        source_plan_path, source_plan_sha256, Path(source_run_root)
    )
    if (
        artifacts != failed_soak
        or derivation != value.get("target_derivation")
        or value.get("evidence_bundle_sha256")
        != _sha256(_canonical({"failed_soak": artifacts, "target_derivation": derivation}))
    ):
        raise SingleImageProbeError("plan_binding_invalid")
    return value, target


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
        "OCI_RUNNER_POOL_SIZE": "1",
        "OCI_RUNNER_POOL_MIN_SIZE": "0",
        "OCI_RUNNER_POOL_CREATE_WORKERS": "1",
        "OCI_RUNNER_POOL_BOOTSTRAP_WORKERS": "1",
        "OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE": "1",
        "OCI_RUNNER_POOL_DRAIN_WORKERS": "1",
        "OCI_RUNNER_SESSION_REUSE": "1",
        "OCI_RUNNER_POOL_MAX_REUSE_COUNT": "1",
        "OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES": "0",
        "OCI_RUNNER_ECR_REGISTRY": ECR_REGISTRY,
        "OCI_RUNNER_ECR_PULL_THROUGH_PREFIX": ECR_PULL_THROUGH_PREFIX,
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
        or any(
            os.environ.get(name)
            for name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            )
        )
    ):
        raise SingleImageProbeError("provider_environment_invalid")


def _select_target_task(plan: Mapping[str, Any], target_image: str) -> tuple[Any, Any]:
    try:
        taskset, tasks = _soak_module()._load_taskset(plan)
        matched = [task for task in tasks if _pull_image(task.image) == target_image]
    except Exception as error:
        raise SingleImageProbeError("target_task_invalid") from error
    if len(matched) != 1:
        raise SingleImageProbeError("target_task_invalid")
    return taskset, matched[0]


async def execute_probe(
    task: Any,
    *,
    runtime_factory: Callable[[Any], Any] | None = None,
    attempts: int = PROBE_ATTEMPTS,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if attempts != PROBE_ATTEMPTS:
        raise SingleImageProbeError("probe_attempt_count_invalid")
    started = monotonic()
    factory = runtime_factory or _soak_module()._runtime_for_task
    counts = {
        "attempts": 0,
        "ready": 0,
        "initialization_failures": 0,
        "runtime_factory_failures": 0,
        "cleanup_attempts": 0,
        "cleanup_succeeded": 0,
        "cleanup_failures": 0,
    }
    for _attempt in range(PROBE_ATTEMPTS):
        runtime: Any | None = None
        try:
            runtime = factory(task)
        except Exception:
            counts["runtime_factory_failures"] += 1
            break
        counts["attempts"] += 1
        try:
            async with asyncio.timeout(ATTEMPT_TIMEOUT_SECONDS):
                await runtime.start()
        except asyncio.CancelledError:
            raise
        except Exception:
            counts["initialization_failures"] += 1
        else:
            counts["ready"] += 1
        finally:
            if runtime is not None:
                counts["cleanup_attempts"] += 1
                try:
                    async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
                        await runtime.stop()
                    counts["cleanup_succeeded"] += 1
                except Exception:
                    counts["cleanup_failures"] += 1
        if counts["cleanup_failures"] or counts["ready"]:
            break
    if (
        counts["runtime_factory_failures"]
        or counts["cleanup_failures"]
        or counts["cleanup_attempts"] != counts["attempts"]
        or counts["cleanup_succeeded"] != counts["attempts"]
    ):
        classification = "inconclusive"
    elif counts["ready"] == 1 and counts["initialization_failures"] == counts["attempts"] - 1:
        classification = "transient_success"
    elif (
        counts["ready"] == 0
        and counts["attempts"] == PROBE_ATTEMPTS
        and counts["initialization_failures"] == PROBE_ATTEMPTS
    ):
        classification = "repeatable_failure"
    else:
        classification = "inconclusive"
    return {
        "classification": classification,
        "counts": counts,
        "elapsed_seconds": round(max(monotonic() - started, 0.0), 3),
    }


def _analyze_probe_events(body: bytes, target_image: str, outcome: Mapping[str, Any]) -> dict[str, int]:
    counts = outcome.get("counts")
    if not isinstance(counts, dict):
        raise SingleImageProbeError("probe_pool_events_invalid")
    expected_attempts = counts.get("attempts")
    expected_ready = counts.get("ready")
    expected_failures = counts.get("initialization_failures")
    acquired: dict[str, str] = {}
    ready: set[str] = set()
    released: dict[str, dict[str, Any]] = {}
    high_water = 0
    for event in _json_lines(body, "probe_pool_events_invalid"):
        name = event.get("event")
        if name == "assignment_acquired":
            if set(event) != ACQUIRED_KEYS:
                raise SingleImageProbeError("probe_pool_events_invalid")
            assignment_id = _event_identity(event, "probe_pool_events_invalid")
            measured = event.get("active_assignment_count")
            if (
                assignment_id in acquired
                or event.get("requested_image") != target_image
                or not _plain_int(measured, minimum=1, maximum=CONCURRENCY)
            ):
                raise SingleImageProbeError("probe_pool_events_invalid")
            acquired[assignment_id] = target_image
            high_water = max(high_water, measured)
        elif name == "assignment_ready":
            if set(event) != READY_KEYS or event.get("requested_image") != target_image:
                raise SingleImageProbeError("probe_pool_events_invalid")
            assignment_id = _event_identity(event, "probe_pool_events_invalid")
            if assignment_id in ready:
                raise SingleImageProbeError("probe_pool_events_invalid")
            ready.add(assignment_id)
        elif name == "assignment_released":
            expected_keys = RELEASE_KEYS | ({"error"} if "error" in event else set())
            if set(event) != expected_keys:
                raise SingleImageProbeError("probe_pool_events_invalid")
            assignment_id = _event_identity(event, "probe_pool_events_invalid")
            if assignment_id in released:
                raise SingleImageProbeError("probe_pool_events_invalid")
            released[assignment_id] = event
    if (
        not _plain_int(expected_attempts, minimum=1, maximum=PROBE_ATTEMPTS)
        or not _plain_int(expected_ready, maximum=1)
        or not _plain_int(expected_failures, maximum=PROBE_ATTEMPTS)
        or len(acquired) != expected_attempts
        or set(acquired) != set(released)
        or len(ready) != expected_ready
        or not ready.issubset(acquired)
        or high_water != CONCURRENCY
    ):
        raise SingleImageProbeError("probe_pool_events_invalid")
    failed = 0
    for assignment_id, event in released.items():
        if assignment_id in ready:
            if (
                "error" in event
                or event.get("status") != "retired"
                or event.get("reason") != "rollout_complete"
                or event.get("poisoned") is not False
                or event.get("nested_recycle_verified") is not True
                or event.get("outer_deletion_verified_http_status") != 404
            ):
                raise SingleImageProbeError("probe_pool_events_invalid")
        else:
            if (
                not isinstance(event.get("error"), str)
                or not event["error"]
                or event.get("status") != "poisoned"
                or event.get("reason") != "initialization_failure"
                or event.get("poisoned") is not True
                or event.get("nested_recycle_verified") is not False
                or event.get("outer_deletion_verified_http_status") != 404
            ):
                raise SingleImageProbeError("probe_pool_events_invalid")
            failed += 1
    if failed != expected_failures:
        raise SingleImageProbeError("probe_pool_events_invalid")
    return {
        "assignments": len(acquired),
        "ready": len(ready),
        "initialization_failures": failed,
        "assignment_high_water": high_water,
    }


def _revalidate_probe_cleanup(
    run_root: Path, expected_attempts: int, expected_failures: int
) -> tuple[dict[str, dict[str, int | str]], dict[str, Any]]:
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
        records[label], bodies[label] = _stable(path, "cleanup_evidence_invalid")
    sanitized = _strict_json(bodies["sanitized_cleanup"], "cleanup_evidence_invalid")
    try:
        with tempfile.TemporaryDirectory(prefix="k3-single-image-cleanup-audit-") as directory:
            recomputed = cleanup_sanitizer.sanitize(
                paths["raw_cleanup"],
                paths["event_log"],
                paths["wal"],
                paths["drain_marker"],
                Path(directory) / "recomputed.json",
            )
    except Exception as error:
        raise SingleImageProbeError("cleanup_evidence_invalid") from error
    count_fields = (
        "recorded_outer_sessions",
        "verified_http_404",
        "assignments_acquired",
        "assignments_cleanup_verified",
        "outer_sessions_created",
        "outer_sessions_deleted",
    )
    if (
        sanitized != recomputed
        or sanitized.get("state") != "passed"
        or any(sanitized.get(field) != expected_attempts for field in count_fields)
        or sanitized.get("recovered_poisoned_assignments") != expected_failures
        or sanitized.get("assignment_event_order_high_water") != CONCURRENCY
        or sanitized.get("assignment_measured_high_water") != CONCURRENCY
        or sanitized.get("outer_session_high_water") != CONCURRENCY
        or sanitized.get("failures") != 0
    ):
        raise SingleImageProbeError("cleanup_contract_invalid")
    return records, sanitized


def run(plan_path: Path, plan_sha256: str, output: Path) -> dict[str, Any]:
    plan, target = validate_plan(plan_path, plan_sha256)
    run_root = _private_directory(output, "run_output_invalid")
    for name in ("run-result.json", "sandoq-provider-context.json"):
        if os.path.lexists(run_root / name):
            raise SingleImageProbeError("run_output_not_fresh")
    _validate_execution_environment(run_root)
    try:
        from terminal_bench_vmvm.sandoq_provider_context import snapshot_provider_context

        snapshot_provider_context(os.environ, run_root / "sandoq-provider-context.json")
        _soak_module()._validate_provider_snapshot(run_root / "sandoq-provider-context.json")
    except Exception as error:
        raise SingleImageProbeError("provider_snapshot_invalid") from error
    taskset, task = _select_target_task(
        _source_plan(
            Path(str(plan["source"]["failed_soak"]["source_plan"]["path"])),
            str(plan["source"]["failed_soak"]["source_plan"]["sha256"]),
        )[1],
        target.image,
    )
    logging.disable(logging.CRITICAL)
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        outcome = asyncio.run(execute_probe(task))
        try:
            asyncio.run(taskset.close())
            taskset_close_succeeded = 1
        except Exception:
            taskset_close_succeeded = 0
        try:
            from sandoq_provider.pool import depart_pool_client

            depart_pool_client()
            pool_departed = True
        except Exception:
            pool_departed = False
    if taskset_close_succeeded != 1 or not pool_departed or outcome["classification"] == "inconclusive":
        classification = "inconclusive"
    else:
        classification = outcome["classification"]
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": RUN_KIND,
        "state": "observed" if classification != "inconclusive" else "unavailable",
        "classification": classification,
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "contracts": {
            "concurrency": CONCURRENCY,
            "probe_attempts": PROBE_ATTEMPTS,
            "taskset_setup": False,
            "commands": 0,
            "verifier_invocations": 0,
            "model_calls": 0,
            "harness_invocations": 0,
            "raw_error_retained": False,
            "target_identity_retained": False,
        },
        "counts": {**outcome["counts"], "taskset_close_succeeded": taskset_close_succeeded},
        "pool_departed": pool_departed,
        "elapsed_seconds": outcome["elapsed_seconds"],
    }
    body = _publish_private(run_root / "run-result.json", value)
    try:
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            _soak_module()._produce_cleanup_evidence(run_root)
    except Exception as error:
        raise SingleImageProbeError("cleanup_evidence_invalid") from error
    return {
        "kind": RUN_KIND,
        "state": value["state"],
        "classification": classification,
        "run_result_sha256": _sha256(body),
        "target_disclosed": False,
    }


def _validate_run_value(value: Mapping[str, Any], plan_path: Path, plan_sha256: str) -> None:
    counts = value.get("counts")
    classification = value.get("classification")
    elapsed = value.get("elapsed_seconds")
    contracts = value.get("contracts")
    if not isinstance(counts, dict):
        raise SingleImageProbeError("run_result_invalid")
    attempts = counts.get("attempts")
    ready = counts.get("ready")
    failures = counts.get("initialization_failures")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != RUN_KIND
        or value.get("state") != "observed"
        or classification not in {"transient_success", "repeatable_failure"}
        or value.get("plan") != {"path": str(plan_path), "sha256": plan_sha256}
        or not isinstance(contracts, dict)
        or contracts.get("concurrency") != CONCURRENCY
        or contracts.get("probe_attempts") != PROBE_ATTEMPTS
        or any(contracts.get(key) != 0 for key in ("commands", "verifier_invocations", "model_calls", "harness_invocations"))
        or contracts.get("taskset_setup") is not False
        or contracts.get("raw_error_retained") is not False
        or contracts.get("target_identity_retained") is not False
        or not _plain_int(attempts, minimum=1, maximum=PROBE_ATTEMPTS)
        or not _plain_int(ready, maximum=1)
        or not _plain_int(failures, maximum=PROBE_ATTEMPTS)
        or counts.get("runtime_factory_failures") != 0
        or counts.get("cleanup_attempts") != attempts
        or counts.get("cleanup_succeeded") != attempts
        or counts.get("cleanup_failures") != 0
        or counts.get("taskset_close_succeeded") != 1
        or value.get("pool_departed") is not True
        or isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or elapsed < 0
    ):
        raise SingleImageProbeError("run_result_invalid")
    if classification == "transient_success":
        valid = ready == 1 and failures == attempts - 1
    else:
        valid = ready == 0 and attempts == PROBE_ATTEMPTS and failures == PROBE_ATTEMPTS
    if not valid:
        raise SingleImageProbeError("run_result_invalid")


def certify(plan_path: Path, plan_sha256: str, run_root: Path, output: Path) -> dict[str, Any]:
    plan, target = validate_plan(plan_path, plan_sha256)
    root = _private_directory(run_root, "run_output_invalid")
    if output != root / "receipt.json" or os.path.lexists(output):
        raise SingleImageProbeError("output_invalid")
    run_record, run_body = _stable(root / "run-result.json", "run_result_invalid")
    run_value = _strict_json(run_body, "run_result_invalid")
    _validate_run_value(run_value, plan_path.resolve(strict=True), plan_sha256)
    attempts = int(run_value["counts"]["attempts"])
    failures = int(run_value["counts"]["initialization_failures"])
    cleanup_records, cleanup = _revalidate_probe_cleanup(root, attempts, failures)
    _event_path, event_body = _record_body(cleanup_records["event_log"], "probe_pool_events_invalid")
    event_summary = _analyze_probe_events(event_body, target.image, run_value)
    snapshot_record, _snapshot = _soak_module()._validate_provider_snapshot(
        root / "sandoq-provider-context.json"
    )
    evidence = {
        "run_result": run_record,
        "provider_snapshot": snapshot_record,
        "cleanup": cleanup_records,
        "cleanup_summary": {
            "assignments_cleanup_verified": cleanup["assignments_cleanup_verified"],
            "outer_sessions_deleted": cleanup["outer_sessions_deleted"],
            "verified_http_404": cleanup["verified_http_404"],
            "failures": cleanup["failures"],
        },
        "pool_summary": event_summary,
    }
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        "state": "certified",
        "classification": run_value["classification"],
        "source_revision": plan["source_revision"],
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "observation": {
            "attempts": attempts,
            "ready": run_value["counts"]["ready"],
            "initialization_failures": failures,
            "concurrency": CONCURRENCY,
            "target_disclosed": False,
            "raw_error_retained": False,
        },
        "contracts": _contracts(),
        "evidence": evidence,
        "evidence_sha256": _sha256(_canonical(evidence)),
    }
    receipt["receipt_payload_sha256"] = _sha256(_canonical(receipt))
    body = _publish_private(output, receipt)
    return {
        "kind": RECEIPT_KIND,
        "state": "certified",
        "classification": receipt["classification"],
        "receipt_sha256": _sha256(body),
        "target_disclosed": False,
    }


def validate_receipt(path: Path, expected_sha256: str, expected_revision: str) -> dict[str, Any]:
    if SHA256_RE.fullmatch(expected_sha256) is None or REVISION_RE.fullmatch(expected_revision) is None:
        raise SingleImageProbeError("receipt_invalid")
    record, body = _stable(path, "receipt_invalid")
    if record["sha256"] != expected_sha256:
        raise SingleImageProbeError("receipt_invalid")
    value = _strict_json(body, "receipt_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("receipt_payload_sha256", None)
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != RECEIPT_KIND
        or value.get("state") != "certified"
        or value.get("classification") not in {"transient_success", "repeatable_failure"}
        or value.get("source_revision") != expected_revision
        or value.get("contracts") != _contracts()
        or value.get("evidence_sha256") != _sha256(_canonical(value.get("evidence")))
        or claimed != _sha256(_canonical(unsigned))
    ):
        raise SingleImageProbeError("receipt_invalid")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--project-root", type=Path, required=True)
    materialize_parser.add_argument("--expected-revision", required=True)
    materialize_parser.add_argument("--source-plan", type=Path, required=True)
    materialize_parser.add_argument("--source-plan-sha256", required=True)
    materialize_parser.add_argument("--source-run-root", type=Path, required=True)
    materialize_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--plan", type=Path, required=True)
    verify_parser.add_argument("--plan-sha256", required=True)
    verify_parser.add_argument("--format", choices=("json", "tsv"), default="json")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--plan", type=Path, required=True)
    run_parser.add_argument("--plan-sha256", required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    certify_parser = subparsers.add_parser("certify")
    certify_parser.add_argument("--plan", type=Path, required=True)
    certify_parser.add_argument("--plan-sha256", required=True)
    certify_parser.add_argument("--run-root", type=Path, required=True)
    certify_parser.add_argument("--output", type=Path, required=True)
    validate_parser = subparsers.add_parser("validate-receipt")
    validate_parser.add_argument("--receipt", type=Path, required=True)
    validate_parser.add_argument("--receipt-sha256", required=True)
    validate_parser.add_argument("--expected-revision", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "materialize":
            result = materialize(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                source_plan=args.source_plan,
                source_plan_sha256=args.source_plan_sha256,
                source_run_root=args.source_run_root,
                output=args.output,
            )
        elif args.command == "verify":
            plan, _target = validate_plan(args.plan, args.plan_sha256)
            if args.format == "tsv":
                print(f"{plan['source_revision']}\t{CONCURRENCY}\t{PROBE_ATTEMPTS}")
                return 0
            result = {
                "kind": PLAN_KIND,
                "state": "authorized",
                "source_revision": plan["source_revision"],
                "concurrency": CONCURRENCY,
                "probe_attempts": PROBE_ATTEMPTS,
                "target_disclosed": False,
            }
        elif args.command == "run":
            result = run(args.plan, args.plan_sha256, args.output)
        elif args.command == "certify":
            result = certify(args.plan, args.plan_sha256, args.run_root, args.output)
        else:
            value = validate_receipt(args.receipt, args.receipt_sha256, args.expected_revision)
            result = {
                "kind": RECEIPT_KIND,
                "state": "certified",
                "classification": value["classification"],
                "receipt_sha256": args.receipt_sha256,
                "target_disclosed": False,
            }
    except BaseException as error:
        if isinstance(error, SingleImageProbeError):
            code = error.code
        elif isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)):
            code = "interrupted"
        elif isinstance(error, OSError):
            code = "io_failure"
        else:
            code = "internal_failure"
        _publish_terminal_status(code=code, state="blocked")
        print(json.dumps({"code": code, "kind": RECEIPT_KIND, "state": "blocked"}, sort_keys=True), file=sys.stderr)
        return 2
    if result.get("state") in {"authorized", "observed", "certified"}:
        _publish_terminal_status(code="completed", state="certified")
    print(json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
