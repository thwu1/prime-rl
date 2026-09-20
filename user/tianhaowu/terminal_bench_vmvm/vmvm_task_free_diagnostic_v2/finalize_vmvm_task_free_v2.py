#!/usr/bin/env python3
"""Validate completion artifacts for the task-free diagnostic bundle."""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
SOURCE_ROOT = BASE / "sources/prime-rl-a09a9a189-v21"
OUTPUT_ROOT = BASE / "diagnostics/vmvm_v21_task_free_preflight_a09a9a189_v4"
COMPLETION_RECEIPT = Path(f"{OUTPUT_ROOT}.external-completion.json")
RESERVATION = Path(f"{OUTPUT_ROOT}.launch-reservation")
LOG_ROOT = BASE / "logs/vmvm_v21_task_free_preflight_a09a9a189_v4"
SCRATCH_ROOT = Path("/tmp/vmvm-v21-task-free-preflight-v4")
X86_UV = Path("/storage/home/tianhaowu/.local/x86_64/bin/uv")
X86_SITE = BASE / "python_x86_64"
VACLI = Path("/public/fbpkgs/x86_64/vacli/stable/vacli")
VACLI_RESOLVED = Path("/infra/public/fbpkgs/x86_64/vacli/794/vacli")
VACLI_OWNER_UID = 0
SOURCE_REVISION = "a09a9a189697034e23b776fdbfccb369522c469d"
SOURCE_TREE = "58bec828df10962ec5411762837aa6e3f71461da"
VERIFIERS_REVISION = "ef35ac787de13c95953ce0ac0225202e544711ce"
RENDERERS_REVISION = "044d9e2541f6a911cacae9da353fc063911ef1f8"
PYDANTIC_CONFIG_REVISION = "896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f"
VMVM_SHA256 = "1e7c8ac2906a45d8212d609b5900fdc3d30f91ba73d4bcdb1c36dfc8bfdd09e2"
X86_UV_SHA256 = "ec831939765474162efb6c8c813e2b10908b26b04eaf98ac3e2972fa12d189b9"
VACLI_SHA256 = "8be49a764bd0fac1a3ef2bef053ced556d18397d44642660eb8a2d22a7c235b3"
IMAGE = "python:3.12-slim"
CLUSTER = "fair-cw-use2-3"
JOB_TIME_LIMIT = "1-12:00:00"
TLS_NAMES = ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH")
X2P_NAMES = ("X2P_ENV", "X2P_CFG_ENV", "X2P_PROXY_URL")
PREFLIGHT_PROTOCOL = {
    "diagnostic_only": True,
    "preflight_only": True,
    "production_authorized": False,
}
REQUIRED_MEMFD_SEALS = (
    fcntl.F_SEAL_SEAL
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_WRITE
    | 0x20  # F_SEAL_EXEC; absent from Python 3.12 fcntl constants.
)
TLS_EXPECTED_SIZE = 5580
STAGES = (
    "direct_client",
    "same_thread_raw",
    "same_thread_recovery",
    "cross_thread_raw",
    "cross_thread_recovery",
    "runtime_contract",
)
MODE_ORDERS = (
    ("absent", "present"),
    ("present", "absent"),
    ("present", "absent"),
    ("absent", "present"),
)
CELL_COUNT = len(STAGES) * 2 * len(MODE_ORDERS)
MODES = ("absent", "present")
PHASES = (
    "worker_started",
    "lease_start",
    "tunnel_ready",
    "backend_ready",
    "command_started",
    "command_succeeded",
    "cleanup_called",
    "release_verified",
)
LEASE_ATTEMPT_LIMIT = 2
RECOVERY_ATTEMPTS = 5
RELEASE_GRACE_SECONDS = 5
STAGE_TIMEOUT_SECONDS = 1_800
HELD_TIMEOUT_SECONDS = 982
ACTIVATION_TIMEOUT_SECONDS = 742
REQUIRED_CONSECUTIVE = 2
WRAPPER_GATE_TIMEOUT_SECONDS = 900
IMAGE_PULL_TIMEOUT_SECONDS = 300
IMAGE_PULL_RETRY_LIMIT = 1
OWNER = "tianhaowu"
SAFE_FAILURES = {
    "backend_cancelled",
    "backend_container",
    "backend_fifo_wiring",
    "backend_lease",
    "backend_sshd",
    "backend_tunnel",
    "child_invalid",
    "child_output_overflow",
    "child_timeout",
    "cleanup_failed",
    "direct_client_failed",
    "lease_budget_exceeded",
    "runtime_initial_workdir_rc255",
    "runtime_other",
    "source_binding_invalid",
    "site_binding_invalid",
    "stage_result_invalid",
    "thread_failed",
    "unclassified",
}
SHA_RE = re.compile(r"[0-9a-f]{64}")
JOB_RE = re.compile(r"[1-9][0-9]*")
PEM_BLOCK_RE = re.compile(
    rb"-----BEGIN ([A-Z0-9 ]+)-----\s+([A-Za-z0-9+/=\r\n]+?)\s+"
    rb"-----END \1-----"
)


class FinalizeError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def fail(code: str) -> None:
    raise FinalizeError(code)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def descriptor_identity(descriptor: int) -> dict[str, int]:
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        fail("output_binding_invalid")
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "owner_uid": info.st_uid,
    }


def stable_file_at(
    directory_fd: int,
    name: str,
    *,
    expected_sha256: str | None = None,
    code: str = "output_binding_invalid",
    expected_mode: int = 0o400,
    expected_uid: int | None = None,
    maximum: int = 2 << 20,
) -> bytes:
    if not name or "/" in name:
        fail(code)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise FinalizeError(code) from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_uid != (os.getuid() if expected_uid is None else expected_uid)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum
        ):
            fail(code)
        raw = bytearray()
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
    if any(getattr(before, field) != getattr(after, field) for field in fields) or len(raw) != before.st_size:
        fail(code)
    digest = sha256_bytes(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        fail(code)
    return bytes(raw)


def validate_finalizer_execution(
    script_path: Path,
    *,
    bundle_root: Path,
    expected_sha256: str,
) -> dict[str, object]:
    match = re.fullmatch(r"/proc/self/fd/([3-9]|[1-9][0-9]+)", str(script_path))
    if (
        match is None
        or SHA_RE.fullmatch(expected_sha256) is None
        or not bundle_root.is_absolute()
        or bundle_root.name in {"", ".", ".."}
    ):
        fail("finalizer_execution_invalid")
    descriptor = int(match.group(1))
    try:
        if os.readlink(script_path) != "/memfd:vmvm-finalizer-v2 (deleted)":
            fail("finalizer_execution_invalid")
        before = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o500
            or before.st_uid != os.getuid()
            or before.st_nlink != 0
            or not 0 < before.st_size <= (2 << 20)
            or seals & REQUIRED_MEMFD_SEALS != REQUIRED_MEMFD_SEALS
        ):
            fail("finalizer_execution_invalid")
        raw = bytearray()
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
            if not chunk:
                fail("finalizer_execution_invalid")
            raw.extend(chunk)
            offset += len(chunk)
        after = os.fstat(descriptor)
        observed_seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
    except (OSError, ValueError) as error:
        raise FinalizeError("finalizer_execution_invalid") from error
    if (
        any(getattr(before, field) != getattr(after, field) for field in stable_fields)
        or observed_seals != seals
        or len(raw) != before.st_size
        or sha256_bytes(raw) != expected_sha256
    ):
        fail("finalizer_execution_invalid")
    return {
        "bundle_root": str(bundle_root),
        "seals": seals,
        "sha256": expected_sha256,
        "size": len(raw),
    }


def load_canonical(raw: bytes, code: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FinalizeError(code) from error
    if not isinstance(value, dict) or canonical_json(value) != raw.rstrip(b"\n"):
        fail(code)
    return value


def output_inventory(output_fd: int) -> dict[str, object]:
    names = sorted(entry.name for entry in os.scandir(output_fd))
    if names != ["completion_request.json", "diagnostic_certificate.json"]:
        fail("output_binding_invalid")
    rows: list[bytes] = []
    total_bytes = 0
    for name in names:
        raw = stable_file_at(output_fd, name)
        total_bytes += len(raw)
        rows.append(f"{name}\0{len(raw)}\0{sha256_bytes(raw)}\n".encode())
    return {
        "entry_count": len(rows),
        "manifest_sha256": sha256_bytes(b"".join(rows)),
        "total_bytes": total_bytes,
    }


def _validate_stage_result(result: Mapping[str, Any]) -> None:
    if set(result) != {
        "artifact_type",
        "cleanup_complete",
        "elapsed_milliseconds",
        "failure_class",
        "order_position",
        "pair_index",
        "phase_metadata",
        "stage",
        "state",
        "x2p_mode",
    }:
        fail("certificate_invalid")
    stage = result.get("stage")
    pair_index = result.get("pair_index")
    order_position = result.get("order_position")
    mode = result.get("x2p_mode")
    state = result.get("state")
    failure = result.get("failure_class")
    metadata = result.get("phase_metadata")
    if (
        result.get("artifact_type") != "vmvm_task_free_stage_result_v2"
        or stage not in STAGES
        or type(pair_index) is not int
        or pair_index not in range(len(MODE_ORDERS))
        or type(order_position) is not int
        or order_position not in (0, 1)
        or mode not in MODES
        or MODE_ORDERS[pair_index][order_position] != mode
        or state not in {"passed", "failed"}
        or type(result.get("elapsed_milliseconds")) is not int
        or int(result["elapsed_milliseconds"]) < 0
        or result.get("cleanup_complete") is not True
        or (state == "passed" and failure is not None)
        or (state == "failed" and failure not in SAFE_FAILURES)
        or not isinstance(metadata, dict)
    ):
        fail("certificate_invalid")
    assert isinstance(metadata, dict)
    if set(metadata) != {
        "last_phase",
        "lease_attempt_limit",
        "lease_attempts",
        "phase_counts",
        "release_grace_seconds",
        "release_method",
        "release_verified",
        "renewer_processes",
        "transport_recovery_attempt_limit",
        "transport_recovery_attempts",
    }:
        fail("certificate_invalid")
    phase_counts = metadata.get("phase_counts")
    if (
        metadata.get("last_phase") not in PHASES
        or metadata.get("lease_attempt_limit") != LEASE_ATTEMPT_LIMIT
        or type(metadata.get("lease_attempts")) is not int
        or not 0 <= int(metadata["lease_attempts"]) <= LEASE_ATTEMPT_LIMIT
        or not isinstance(phase_counts, dict)
        or any(phase not in PHASES or type(count) is not int or count < 0 for phase, count in phase_counts.items())
        or metadata.get("release_grace_seconds") != RELEASE_GRACE_SECONDS
        or metadata.get("release_method") != "renewer_absent_for_lease_ttl"
        or metadata.get("release_verified") is not True
        or type(metadata.get("renewer_processes")) is not int
        or int(metadata["renewer_processes"]) < 0
        or metadata.get("transport_recovery_attempt_limit") != RECOVERY_ATTEMPTS
        or type(metadata.get("transport_recovery_attempts")) is not int
        or not 0 <= int(metadata["transport_recovery_attempts"]) <= RECOVERY_ATTEMPTS
    ):
        fail("lease_release_unverified")
    assert isinstance(stage, str)
    assert isinstance(state, str)
    _validate_phase_causality(
        stage,
        state,
        failure if isinstance(failure, str) else None,
        metadata,
    )


def _validate_phase_causality(
    stage: str,
    state: str,
    failure: str | None,
    metadata: Mapping[str, Any],
) -> None:
    phase_counts = metadata["phase_counts"]
    assert isinstance(phase_counts, dict)
    count = lambda name: int(phase_counts.get(name, 0))
    lease_attempts = int(metadata["lease_attempts"])
    recovery_attempts = int(metadata["transport_recovery_attempts"])
    renewers = int(metadata["renewer_processes"])
    if (
        metadata.get("last_phase") != "release_verified"
        or count("worker_started") != 1
        or count("release_verified") != 1
        or count("lease_start") != lease_attempts
        or count("cleanup_called") != lease_attempts
        or count("tunnel_ready") > lease_attempts + recovery_attempts
        or count("tunnel_ready") > renewers
        or count("backend_ready") not in (0, 1)
        or count("backend_ready") > count("tunnel_ready")
        or count("command_started") not in (0, 1)
        or count("command_succeeded") not in (0, 1)
        or count("command_succeeded") > count("command_started")
        or count("command_started") > count("backend_ready")
        or renewers > lease_attempts + recovery_attempts
        or (count("backend_ready") == 1 and renewers == 0)
        or failure
        in {
            "child_invalid",
            "child_output_overflow",
            "child_timeout",
            "cleanup_failed",
            "site_binding_invalid",
            "source_binding_invalid",
            "stage_result_invalid",
        }
        or (stage == "direct_client" and (count("command_started") or count("command_succeeded")))
        or (stage in {"direct_client", "same_thread_raw", "cross_thread_raw"} and recovery_attempts != 0)
    ):
        fail("certificate_phase_invalid")
    if state == "passed":
        if lease_attempts < 1 or count("backend_ready") != 1:
            fail("certificate_phase_invalid")
        if stage != "direct_client" and (count("command_started") != 1 or count("command_succeeded") != 1):
            fail("certificate_phase_invalid")
    elif stage == "direct_client" and count("backend_ready") != 0:
        fail("certificate_phase_invalid")
    elif count("command_succeeded") != 0:
        fail("certificate_phase_invalid")


def summarize_stage_results(
    results: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    counts = Counter(str(item["state"]) for item in results)
    failures = Counter(str(item["failure_class"]) for item in results if item["failure_class"] is not None)
    aggregate: dict[str, dict[str, object]] = {}
    outcome_contrasts: dict[str, dict[str, int]] = {}
    construction_contrasts: dict[str, dict[str, int]] = {}
    causal_assessment: dict[str, str] = {}
    for stage in STAGES:
        aggregate[stage] = {}
        outcome_pairs = Counter[str]()
        construction_pairs = Counter[str]()
        for mode in MODES:
            cells = [item for item in results if item["stage"] == stage and item["x2p_mode"] == mode]
            phase_counts: Counter[str] = Counter()
            for cell in cells:
                metadata = cell["phase_metadata"]
                assert isinstance(metadata, dict)
                cell_phase_counts = metadata["phase_counts"]
                assert isinstance(cell_phase_counts, dict)
                phase_counts.update(cell_phase_counts)
            aggregate[stage][mode] = {
                "cells": len(cells),
                "failures": sum(item["state"] == "failed" for item in cells),
                "lease_attempts": sum(int(item["phase_metadata"]["lease_attempts"]) for item in cells),
                "passes": sum(item["state"] == "passed" for item in cells),
                "phase_counts": dict(sorted(phase_counts.items())),
                "renewer_processes": sum(int(item["phase_metadata"]["renewer_processes"]) for item in cells),
                "transport_recovery_attempts": sum(
                    int(item["phase_metadata"]["transport_recovery_attempts"]) for item in cells
                ),
            }
        for pair_index in range(len(MODE_ORDERS)):
            pair = {
                str(item["x2p_mode"]): item
                for item in results
                if item["stage"] == stage and item["pair_index"] == pair_index
            }
            if set(pair) != set(MODES):
                fail("certificate_invalid")
            outcome_pairs[f"absent_{pair['absent']['state']}__present_{pair['present']['state']}"] += 1
            readiness: dict[str, str] = {}
            for mode, item in pair.items():
                metadata = item["phase_metadata"]
                assert isinstance(metadata, dict)
                phase_counts = metadata["phase_counts"]
                assert isinstance(phase_counts, dict)
                readiness[mode] = "ready" if int(phase_counts.get("backend_ready", 0)) > 0 else "not_ready"
            construction_pairs[f"absent_{readiness['absent']}__present_{readiness['present']}"] += 1
        outcome_contrasts[stage] = dict(sorted(outcome_pairs.items()))
        construction_contrasts[stage] = dict(sorted(construction_pairs.items()))
        present_only = construction_pairs["absent_not_ready__present_ready"]
        absent_only = construction_pairs["absent_ready__present_not_ready"]
        if present_only >= 3 and absent_only == 0:
            causal_assessment[stage] = "x2p_present_construction_benefit"
        elif absent_only >= 3 and present_only == 0:
            causal_assessment[stage] = "x2p_present_construction_harm"
        elif construction_pairs["absent_ready__present_ready"] >= 3:
            causal_assessment[stage] = "both_modes_reach_construction"
        elif construction_pairs["absent_not_ready__present_not_ready"] >= 3:
            causal_assessment[stage] = "neither_mode_reaches_construction"
        else:
            causal_assessment[stage] = "inconclusive"
    return {
        "causal_assessment": causal_assessment,
        "causal_contrasts": construction_contrasts,
        "outcome_contrasts": outcome_contrasts,
        "result_counts": dict(sorted(counts.items())),
        "retry_phase_aggregate": aggregate,
        "safe_failure_counts": dict(sorted(failures.items())),
    }


def validate_certificate(
    certificate: Mapping[str, Any],
    *,
    expected_execution_inputs: Mapping[str, object],
) -> None:
    expected_keys = {
        "artifact_type",
        "authorization_file_sha256",
        "authorization_sha256",
        "automatic_remediation",
        "causal_assessment",
        "causal_contrasts",
        "diagnostic_only",
        "environment_sha256",
        "execution_inputs",
        "image",
        "job",
        "job_authorization_sha256",
        "model_endpoint_accessed",
        "outcome_contrasts",
        "production_authorized",
        "protocol",
        "result_counts",
        "retry_phase_aggregate",
        "safe_failure_counts",
        "schema_version",
        "source",
        "stage_results",
        "submission_receipt_sha256",
        "task_data_accessed",
        "x2p_modes",
    }
    results = certificate.get("stage_results")
    protocol = certificate.get("protocol")
    job = certificate.get("job")
    execution_inputs = certificate.get("execution_inputs")
    if (
        set(certificate) != expected_keys
        or certificate.get("artifact_type") != "vmvm_task_free_diagnostic_certificate_v2"
        or certificate.get("schema_version") != 2
        or certificate.get("diagnostic_only") is not True
        or certificate.get("automatic_remediation") is not False
        or certificate.get("production_authorized") is not False
        or certificate.get("task_data_accessed") is not False
        or certificate.get("model_endpoint_accessed") is not False
        or certificate.get("image") != IMAGE
        or certificate.get("x2p_modes") != list(MODES)
        or not isinstance(execution_inputs, dict)
        or execution_inputs != expected_execution_inputs
        or set(execution_inputs) != {"authorized_site", "site_snapshot", "source_snapshot"}
        or any(
            not isinstance(inventory, dict)
            or set(inventory) != {"entry_count", "manifest_sha256", "owner_uid", "total_bytes"}
            or type(inventory.get("entry_count")) is not int
            or int(inventory["entry_count"]) < 1
            or SHA_RE.fullmatch(str(inventory.get("manifest_sha256"))) is None
            or inventory.get("owner_uid") != os.getuid()
            or type(inventory.get("total_bytes")) is not int
            or int(inventory["total_bytes"]) < 1
            for inventory in execution_inputs.values()
        )
        or any(
            SHA_RE.fullmatch(str(certificate.get(name))) is None
            for name in (
                "authorization_file_sha256",
                "authorization_sha256",
                "environment_sha256",
                "job_authorization_sha256",
                "submission_receipt_sha256",
            )
        )
        or certificate.get("source")
        != {
            "pydantic_config_revision": PYDANTIC_CONFIG_REVISION,
            "renderers_revision": RENDERERS_REVISION,
            "revision": SOURCE_REVISION,
            "tree": SOURCE_TREE,
            "verifiers_revision": VERIFIERS_REVISION,
            "vmvm_sha256": VMVM_SHA256,
        }
        or not isinstance(job, dict)
        or set(job) != {"cluster", "job_id", "job_name"}
        or job.get("cluster") != "fair-cw-use2-3"
        or JOB_RE.fullmatch(str(job.get("job_id"))) is None
        or re.fullmatch(r"vmvm-v4-preflight-[0-9a-f]{24}", str(job.get("job_name"))) is None
        or protocol
        != {
            "causal_scope": "construction_backend_ready",
            "cell_count": CELL_COUNT,
            "lease_attempt_limit_per_cell": LEASE_ATTEMPT_LIMIT,
            "mode_orders": [list(order) for order in MODE_ORDERS],
            "repetitions_per_mode": len(MODE_ORDERS),
            "stage_timeout_seconds": STAGE_TIMEOUT_SECONDS,
        }
        or not isinstance(results, list)
        or len(results) != CELL_COUNT
    ):
        fail("certificate_invalid")
    expected_coordinates = {
        (stage, pair_index, order_position, mode)
        for stage in STAGES
        for pair_index, order in enumerate(MODE_ORDERS)
        for order_position, mode in enumerate(order)
    }
    observed: set[tuple[object, object, object, object]] = set()
    for result in results:
        if not isinstance(result, dict):
            fail("certificate_invalid")
        _validate_stage_result(result)
        observed.add(
            (
                result.get("stage"),
                result.get("pair_index"),
                result.get("order_position"),
                result.get("x2p_mode"),
            )
        )
    if observed != expected_coordinates:
        fail("certificate_invalid")
    summary = summarize_stage_results(results)
    for key, expected in summary.items():
        if certificate.get(key) != expected:
            fail("certificate_aggregate_invalid")


def _write_receipt(parent_fd: int, name: str, receipt: Mapping[str, Any]) -> str:
    payload = canonical_json(receipt) + b"\n"
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
        dir_fd=parent_fd,
    )
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(parent_fd)
    return sha256_bytes(payload)


def _stable_path_file(
    path: Path,
    *,
    expected_sha256: str,
    expected_mode: int = 0o400,
    expected_uid: int | None = None,
    maximum: int = 2 << 20,
    require_resolved: bool = True,
) -> bytes:
    if (
        not path.is_absolute()
        or path != Path(os.path.normpath(path))
        or (require_resolved and path.resolve(strict=True) != path)
    ):
        fail("authorization_invalid")
    parent_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | (os.O_NOFOLLOW if require_resolved else 0),
    )
    try:
        return stable_file_at(
            parent_fd,
            path.name,
            expected_sha256=expected_sha256,
            expected_mode=expected_mode,
            expected_uid=expected_uid,
            maximum=maximum,
        )
    finally:
        os.close(parent_fd)


def _same_open_file(first: Path, second: Path) -> bool:
    descriptors: list[int] = []
    try:
        for path in (first, second):
            descriptors.append(os.open(path, os.O_RDONLY | os.O_NOFOLLOW))
        identities = [
            (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size)
            for info in (os.fstat(descriptor) for descriptor in descriptors)
        ]
        return identities[0] == identities[1]
    except OSError:
        return False
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def _open_bound_directory(
    path: Path,
    expected: object,
    *,
    required_mode: int | None = None,
) -> int:
    if not isinstance(expected, dict) or set(expected) != {
        "device",
        "inode",
        "mode",
        "owner_uid",
    }:
        fail("authorization_invalid")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise FinalizeError("authorization_invalid") from error
    identity = descriptor_identity(descriptor)
    if (
        identity != expected
        or identity["owner_uid"] != os.getuid()
        or (required_mode is not None and identity["mode"] != required_mode)
    ):
        os.close(descriptor)
        fail("authorization_invalid")
    return descriptor


def _directory_manifest(descriptor: int, *, sealed_modes: bool = False) -> dict[str, object]:
    rows: list[bytes] = []
    total_bytes = 0
    root_identity = descriptor_identity(descriptor)

    def visit(current_fd: int, relative_root: str) -> None:
        nonlocal total_bytes
        for name in sorted(os.listdir(current_fd)):
            info = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            if info.st_uid != os.getuid():
                fail("authorization_invalid")
            relative = f"{relative_root}/{name}".lstrip("/")
            if stat.S_ISDIR(info.st_mode):
                directory_mode = 0o500 if sealed_modes else stat.S_IMODE(info.st_mode)
                rows.append(f"d\0{relative}\0{directory_mode:o}\0{info.st_uid}\n".encode())
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current_fd,
                )
                try:
                    if descriptor_identity(child_fd) != {
                        "device": info.st_dev,
                        "inode": info.st_ino,
                        "mode": stat.S_IMODE(info.st_mode),
                        "owner_uid": info.st_uid,
                    }:
                        fail("authorization_invalid")
                    visit(child_fd, relative)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(info.st_mode):
                fail("authorization_invalid")
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current_fd)
            try:
                before = os.fstat(file_fd)
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(file_fd, 1 << 20)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    total_bytes += len(chunk)
                    if total_bytes > 1 << 30:
                        fail("authorization_invalid")
                after = os.fstat(file_fd)
            finally:
                os.close(file_fd)
            fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
            if any(getattr(before, field) != getattr(after, field) for field in fields) or size != before.st_size:
                fail("authorization_invalid")
            file_mode = (
                0o500
                if sealed_modes and before.st_mode & 0o111
                else 0o400
                if sealed_modes
                else stat.S_IMODE(before.st_mode)
            )
            rows.append(f"f\0{relative}\0{file_mode:o}\0{before.st_uid}\0{size}\0{digest.hexdigest()}\n".encode())
            if len(rows) > 50_000:
                fail("authorization_invalid")

    visit(descriptor, "")
    if descriptor_identity(descriptor) != root_identity:
        fail("authorization_invalid")
    rows.sort()
    return {
        "entry_count": len(rows),
        "manifest_sha256": sha256_bytes(b"".join(rows)),
        "owner_uid": os.getuid(),
        "total_bytes": total_bytes,
    }


def _artifact_record(value: object) -> tuple[Path, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        fail("authorization_invalid")
    path = Path(str(value.get("path")))
    digest = str(value.get("sha256"))
    if not path.is_absolute() or SHA_RE.fullmatch(digest) is None:
        fail("authorization_invalid")
    return path, digest


def _source_git(command: Sequence[str], *, pass_fds: Sequence[int]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.untrackedCache=false",
            *command,
        ],
        env={
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        pass_fds=tuple(pass_fds),
    )


def _git_records(result: subprocess.CompletedProcess[str]) -> list[str]:
    if result.returncode != 0 or result.stderr or not result.stdout.endswith("\0"):
        fail("authorization_invalid")
    records = result.stdout[:-1].split("\0")
    if not records or any(not record for record in records):
        fail("authorization_invalid")
    return records


def _open_source_directory_at(root_fd: int, relative: str) -> int:
    descriptor = os.dup(root_fd)
    try:
        for component in relative.split("/"):
            if component in {"", ".", ".."}:
                fail("authorization_invalid")
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                fail("authorization_invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_source_blob(
    root_fd: int,
    relative: str,
    git_mode: str,
    expected_oid: str,
) -> tuple[str, int]:
    components = relative.split("/")
    if (
        not components
        or any(component in {"", ".", ".."} for component in components)
        or git_mode not in {"100644", "100755"}
        or re.fullmatch(r"[0-9a-f]{40}", expected_oid) is None
    ):
        fail("authorization_invalid")
    parent_fd = os.dup(root_fd)
    try:
        for component in components[:-1]:
            child_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            os.close(parent_fd)
            parent_fd = child_fd
            info = os.fstat(parent_fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                fail("authorization_invalid")
        file_fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    try:
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or bool(before.st_mode & 0o111) != (git_mode == "100755")
        ):
            fail("authorization_invalid")
        raw = bytearray()
        while True:
            chunk = os.read(file_fd, 1 << 20)
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(file_fd)
    finally:
        os.close(file_fd)
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
    git_digest = hashlib.sha1(f"blob {len(raw)}\0".encode(), usedforsecurity=False)
    git_digest.update(raw)
    if (
        any(getattr(before, field) != getattr(after, field) for field in fields)
        or len(raw) != before.st_size
        or git_digest.hexdigest() != expected_oid
    ):
        fail("authorization_invalid")
    return sha256_bytes(raw), len(raw)


def _attest_git_repository(
    repository_fd: int,
    *,
    expected_revision: str,
    pathspecs: Sequence[str] = (),
    expected_gitlinks: Mapping[str, str] | None = None,
) -> dict[str, tuple[str, str, str, int]]:
    root = f"/proc/self/fd/{repository_fd}"
    inherited = (repository_fd,)
    suffix = ["--", *pathspecs] if pathspecs else []
    revision = _source_git(["-C", root, "rev-parse", "--verify", "HEAD"], pass_fds=inherited)
    object_format = _source_git(["-C", root, "rev-parse", "--show-object-format"], pass_fds=inherited)
    detached = _source_git(["-C", root, "symbolic-ref", "-q", "HEAD"], pass_fds=inherited)
    if (
        revision.returncode != 0
        or revision.stderr
        or revision.stdout.strip() != expected_revision
        or object_format.returncode != 0
        or object_format.stderr
        or object_format.stdout.strip() != "sha1"
        or detached.returncode != 1
        or detached.stderr
        or detached.stdout
    ):
        fail("authorization_invalid")
    stage = _source_git(["-C", root, "ls-files", "--stage", "-z", *suffix], pass_fds=inherited)
    tree = _source_git(["-C", root, "ls-tree", "-r", "-z", "--full-tree", "HEAD", *suffix], pass_fds=inherited)
    flags = tuple(
        _source_git(["-C", root, "ls-files", option, "-z", *suffix], pass_fds=inherited) for option in ("-v", "-f")
    )
    index: dict[str, tuple[str, str]] = {}
    for record in _git_records(stage):
        metadata, separator, path = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != "0" or path in index:
            fail("authorization_invalid")
        index[path] = (fields[0], fields[1])
    tree_records: dict[str, tuple[str, str]] = {}
    for record in _git_records(tree):
        metadata, separator, path = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or path in tree_records:
            fail("authorization_invalid")
        mode, object_type, object_id = fields
        if object_type != ("commit" if mode == "160000" else "blob"):
            fail("authorization_invalid")
        tree_records[path] = (mode, object_id)
    if index != tree_records:
        fail("authorization_invalid")
    for result in flags:
        observed: list[str] = []
        for record in _git_records(result):
            tag, separator, path = record.partition(" ")
            if not separator or tag != "H":
                fail("authorization_invalid")
            observed.append(path)
        if observed != list(index):
            fail("authorization_invalid")
    expected_links = dict(expected_gitlinks or {})
    result: dict[str, tuple[str, str, str, int]] = {}
    for path, (mode, oid) in index.items():
        if mode == "160000":
            if expected_links.get(path) != oid:
                fail("authorization_invalid")
            continue
        digest, size = _read_source_blob(repository_fd, path, mode, oid)
        result[path] = (mode, oid, digest, size)
    if set(expected_links) != {path for path, (mode, _oid) in index.items() if mode == "160000"}:
        fail("authorization_invalid")
    repeated = _source_git(["-C", root, "ls-files", "--stage", "-z", *suffix], pass_fds=inherited)
    if repeated.returncode != 0 or repeated.stderr or repeated.stdout != stage.stdout:
        fail("authorization_invalid")
    return result


def _attest_imported_source(source_fd: int) -> dict[str, tuple[str, str, str, int]]:
    dependency_fds: list[int] = []
    tree = _source_git(
        ["-C", f"/proc/self/fd/{source_fd}", "rev-parse", "HEAD^{tree}"],
        pass_fds=(source_fd,),
    )
    if tree.returncode != 0 or tree.stderr or tree.stdout.strip() != SOURCE_TREE:
        fail("authorization_invalid")
    tracked = _attest_git_repository(
        source_fd,
        expected_revision=SOURCE_REVISION,
        pathspecs=(
            "environments/vmvm_tb_v2",
            "deps/verifiers",
            "deps/renderers",
            "deps/pydantic-config",
        ),
        expected_gitlinks={
            "deps/verifiers": VERIFIERS_REVISION,
            "deps/renderers": RENDERERS_REVISION,
            "deps/pydantic-config": PYDANTIC_CONFIG_REVISION,
        },
    )
    try:
        for relative, revision in (
            ("deps/verifiers", VERIFIERS_REVISION),
            ("deps/renderers", RENDERERS_REVISION),
            ("deps/pydantic-config", PYDANTIC_CONFIG_REVISION),
        ):
            dependency_fd = _open_source_directory_at(source_fd, relative)
            dependency_fds.append(dependency_fd)
            for path, record in _attest_git_repository(
                dependency_fd,
                expected_revision=revision,
            ).items():
                combined = f"{relative}/{path}"
                if combined in tracked:
                    fail("authorization_invalid")
                tracked[combined] = record
        for root_fd in (source_fd, *dependency_fds):
            root = f"/proc/self/fd/{root_fd}"
            status = _source_git(
                ["-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
                pass_fds=(root_fd,),
            )
            ignored = _source_git(
                [
                    "-C",
                    root,
                    "ls-files",
                    "--others",
                    "--ignored",
                    "--exclude-standard",
                    "--",
                    ":(glob)**/*.py",
                    ":(glob)**/*.pyc",
                    ":(glob)**/*.so",
                    ":(glob)**/*.pyd",
                    ":(glob)**/sitecustomize.py",
                    ":(glob)**/usercustomize.py",
                ],
                pass_fds=(root_fd,),
            )
            if (
                status.returncode != 0
                or status.stderr
                or status.stdout
                or ignored.returncode != 0
                or ignored.stderr
                or ignored.stdout
            ):
                fail("authorization_invalid")
    finally:
        for descriptor in dependency_fds:
            os.close(descriptor)
    vmvm_rows = []
    for path, (_mode, _oid, digest, _size) in sorted(tracked.items()):
        if re.fullmatch(r"environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/[^/]+\.py", path):
            vmvm_rows.append(f"{digest}  {path}\n".encode())
    if not vmvm_rows or sha256_bytes(b"".join(vmvm_rows)) != VMVM_SHA256:
        fail("authorization_invalid")
    return dict(sorted(tracked.items()))


def _source_snapshot_commitment(
    records: Mapping[str, tuple[str, str, str, int]],
) -> dict[str, object]:
    directories: set[str] = set()
    rows: list[bytes] = []
    total_bytes = 0
    for path, (mode, _oid, digest, size) in records.items():
        current = Path(path).parent
        while str(current) != ".":
            directories.add(str(current))
            current = current.parent
        sealed_mode = 0o500 if mode == "100755" else 0o400
        rows.append(f"f\0{path}\0{sealed_mode:o}\0{os.getuid()}\0{size}\0{digest}\n".encode())
        total_bytes += size
    rows.extend(f"d\0{path}\0{0o500:o}\0{os.getuid()}\n".encode() for path in directories)
    rows.sort()
    return {
        "entry_count": len(rows),
        "manifest_sha256": sha256_bytes(b"".join(rows)),
        "owner_uid": os.getuid(),
        "total_bytes": total_bytes,
    }


def _pem_profile(raw: bytes) -> str:
    labels: list[bytes] = []
    position = 0
    for match in PEM_BLOCK_RE.finditer(raw):
        if raw[position : match.start()].strip(b" \t\r\n"):
            return "invalid"
        try:
            decoded = base64.b64decode(b"".join(match.group(2).split()), validate=True)
        except (ValueError, binascii.Error):
            return "invalid"
        if not decoded:
            return "invalid"
        labels.append(match.group(1))
        position = match.end()
    if raw[position:].strip(b" \t\r\n"):
        return "invalid"
    counts = Counter(labels)
    return "combined" if len(labels) == 3 and counts == {b"CERTIFICATE": 2, b"RSA PRIVATE KEY": 1} else "other"


def _validate_launch_authorization(
    record: object,
    *,
    execution_binding: Mapping[str, object],
) -> tuple[str, str, str, dict[str, object], dict[str, Any], str]:
    if (
        set(execution_binding) != {"bundle_root", "seals", "sha256", "size"}
        or not isinstance(execution_binding.get("bundle_root"), str)
        or SHA_RE.fullmatch(str(execution_binding.get("sha256"))) is None
        or type(execution_binding.get("seals")) is not int
        or int(execution_binding["seals"]) & REQUIRED_MEMFD_SEALS != REQUIRED_MEMFD_SEALS
        or type(execution_binding.get("size")) is not int
        or not 0 < int(execution_binding["size"]) <= (2 << 20)
    ):
        fail("finalizer_execution_invalid")
    bundle_root = Path(str(execution_binding["bundle_root"]))
    if not isinstance(record, dict) or set(record) != {
        "authorization_sha256",
        "file_sha256",
        "path",
    }:
        fail("authorization_invalid")
    path = Path(str(record.get("path")))
    file_sha256 = str(record.get("file_sha256"))
    body_sha256 = str(record.get("authorization_sha256"))
    if SHA_RE.fullmatch(file_sha256) is None or SHA_RE.fullmatch(body_sha256) is None:
        fail("authorization_invalid")
    value = load_canonical(
        _stable_path_file(path, expected_sha256=file_sha256),
        "authorization_invalid",
    )
    body = dict(value)
    if (
        set(value)
        != {
            "artifact_type",
            "authorization_sha256",
            "bundle",
            "credentials",
            "launch",
            "protocol",
            "runtime",
            "schema_version",
            "source",
            "state",
        }
        or value.get("artifact_type") != "vmvm_task_free_diagnostic_authorization_v2"
        or value.get("schema_version") != 2
        or value.get("state") != "approved"
        or body.pop("authorization_sha256", None) != body_sha256
        or sha256_bytes(canonical_json(body)) != body_sha256
    ):
        fail("authorization_invalid")
    source = value.get("source")
    bundle = value.get("bundle")
    runtime = value.get("runtime")
    credentials = value.get("credentials")
    launch = value.get("launch")
    protocol = value.get("protocol")
    if not all(isinstance(item, dict) for item in (source, bundle, runtime, credentials, launch, protocol)):
        fail("authorization_invalid")
    assert isinstance(source, dict)
    assert isinstance(bundle, dict)
    assert isinstance(runtime, dict)
    assert isinstance(credentials, dict)
    assert isinstance(launch, dict)
    assert isinstance(protocol, dict)

    if set(source) != {
        "path",
        "pydantic_config_revision",
        "renderers_revision",
        "revision",
        "root_identity",
        "tree",
        "verifiers_revision",
        "vmvm_sha256",
    } or source != {
        "path": str(SOURCE_ROOT),
        "pydantic_config_revision": PYDANTIC_CONFIG_REVISION,
        "renderers_revision": RENDERERS_REVISION,
        "revision": SOURCE_REVISION,
        "root_identity": source.get("root_identity"),
        "tree": SOURCE_TREE,
        "verifiers_revision": VERIFIERS_REVISION,
        "vmvm_sha256": VMVM_SHA256,
    }:
        fail("authorization_invalid")
    source_fd = _open_bound_directory(SOURCE_ROOT, source["root_identity"])
    try:
        source_records = _attest_imported_source(source_fd)
        source_snapshot = _source_snapshot_commitment(source_records)
    finally:
        os.close(source_fd)

    expected_bundle = {
        "finalizer": (bundle_root / "finalize_vmvm_task_free_v2.py", 0o500),
        "launcher": (bundle_root / "launch_vmvm_task_free_v2.py", 0o500),
        "probe": (bundle_root / "probe_vmvm_task_free_v2.py", 0o500),
        "readme": (bundle_root / "README.md", 0o400),
        "tests": (bundle_root / "test_vmvm_task_free_v2.py", 0o400),
        "wrapper": (bundle_root / "run_vmvm_task_free_v2.sbatch", 0o500),
    }
    if set(bundle) != set(expected_bundle) | {"root_identity"}:
        fail("authorization_invalid")
    bundle_fd = _open_bound_directory(bundle_root, bundle.get("root_identity"), required_mode=0o700)
    try:
        bundle_status = os.fstat(bundle_fd)
        if (
            not bundle_root.is_absolute()
            or bundle_root.resolve(strict=True) != bundle_root
            or bundle_status.st_nlink != 2
            or {entry.name for entry in os.scandir(bundle_fd)}
            != {expected.name for expected, _mode in expected_bundle.values()}
        ):
            fail("authorization_invalid")
        for label, (expected_path, expected_mode) in expected_bundle.items():
            authorized_path, digest = _artifact_record(bundle[label])
            if authorized_path != expected_path.resolve(strict=True):
                fail("authorization_invalid")
            if label == "finalizer" and digest != execution_binding["sha256"]:
                fail("finalizer_execution_invalid")
            artifact_raw = stable_file_at(
                bundle_fd,
                expected_path.name,
                expected_sha256=digest,
                code="authorization_invalid",
                expected_mode=expected_mode,
            )
            if label == "finalizer" and len(artifact_raw) != execution_binding["size"]:
                fail("finalizer_execution_invalid")
    finally:
        os.close(bundle_fd)

    if set(runtime) != {"image", "python_name", "site", "uv", "vacli"}:
        fail("authorization_invalid")
    site = runtime.get("site")
    if (
        runtime.get("image") != IMAGE
        or runtime.get("python_name") != "python3"
        or not isinstance(site, dict)
        or set(site) != {"inventory", "path", "root_identity"}
        or site.get("path") != str(X86_SITE)
        or not isinstance(site.get("inventory"), dict)
    ):
        fail("authorization_invalid")
    site_fd = _open_bound_directory(X86_SITE, site.get("root_identity"))
    try:
        if _directory_manifest(site_fd) != site["inventory"]:
            fail("authorization_invalid")
        site_snapshot = _directory_manifest(site_fd, sealed_modes=True)
    finally:
        os.close(site_fd)
    for label, expected_path, expected_digest, expected_uid in (("uv", X86_UV, X86_UV_SHA256, os.getuid()),):
        artifact_path, digest = _artifact_record(runtime[label])
        if artifact_path != expected_path or digest != expected_digest:
            fail("authorization_invalid")
        _stable_path_file(
            artifact_path,
            expected_sha256=digest,
            expected_mode=0o755,
            expected_uid=expected_uid,
            maximum=128 << 20,
        )
    vacli_record = runtime["vacli"]
    if not isinstance(vacli_record, dict) or set(vacli_record) != {
        "path",
        "resolved_path",
        "sha256",
    }:
        fail("authorization_invalid")
    if (
        vacli_record.get("path") != str(VACLI)
        or vacli_record.get("resolved_path") != str(VACLI_RESOLVED)
        or vacli_record.get("sha256") != VACLI_SHA256
        or VACLI.resolve(strict=True) != VACLI_RESOLVED
        or not _same_open_file(VACLI, VACLI_RESOLVED)
    ):
        fail("authorization_invalid")
    vacli_raw = _stable_path_file(
        VACLI,
        expected_sha256=VACLI_SHA256,
        expected_mode=0o755,
        expected_uid=VACLI_OWNER_UID,
        maximum=512 << 20,
        require_resolved=False,
    )
    if (
        _stable_path_file(
            VACLI_RESOLVED,
            expected_sha256=VACLI_SHA256,
            expected_mode=0o755,
            expected_uid=VACLI_OWNER_UID,
            maximum=512 << 20,
        )
        != vacli_raw
    ):
        fail("authorization_invalid")

    if set(credentials) != {"tls", "x2p"}:
        fail("authorization_invalid")
    tls = credentials.get("tls")
    x2p = credentials.get("x2p")
    if (
        not isinstance(tls, dict)
        or set(tls) != set(TLS_NAMES)
        or not isinstance(x2p, dict)
        or set(x2p) != set(X2P_NAMES)
    ):
        fail("authorization_invalid")
    tls_identities: list[tuple[Path, str, tuple[int, int], str]] = []
    for name in TLS_NAMES:
        tls_path, digest = _artifact_record(tls[name])
        raw = _stable_path_file(
            tls_path,
            expected_sha256=digest,
            expected_mode=0o500,
            maximum=TLS_EXPECTED_SIZE,
        )
        if len(raw) != TLS_EXPECTED_SIZE:
            fail("authorization_invalid")
        info = tls_path.stat(follow_symlinks=False)
        tls_identities.append((tls_path, digest, (info.st_dev, info.st_ino), _pem_profile(raw)))
    first, second = tls_identities
    aliases = (first[0] == second[0], first[1] == second[1], first[2] == second[2])
    if any(aliases) and not (all(aliases) and first[3] == second[3] == "combined"):
        fail("authorization_invalid")
    for name in X2P_NAMES:
        x2p_record = x2p[name]
        if (
            not isinstance(x2p_record, dict)
            or set(x2p_record) != {"sha256"}
            or SHA_RE.fullmatch(str(x2p_record.get("sha256"))) is None
        ):
            fail("authorization_invalid")

    job_name = str(launch.get("job_name"))
    token_match = re.fullmatch(r"vmvm-v4-preflight-([0-9a-f]{24})", job_name)
    expected_launch = {
        "account": "ram",
        "cluster": CLUSTER,
        "comment": f"vmvm-v4-preflight:{token_match.group(1)}" if token_match else None,
        "completion_receipt": str(COMPLETION_RECEIPT),
        "cpus": 2,
        "job_name": job_name,
        "log_root": str(LOG_ROOT),
        "memory": "8G",
        "nodes": 1,
        "output_parent_identity": launch.get("output_parent_identity"),
        "output_root": str(OUTPUT_ROOT),
        "partition": "cpu_x86",
        "qos": "cpu_x86_lowest",
        "reservation": str(RESERVATION),
        "scratch_root": str(SCRATCH_ROOT),
        "time_limit": JOB_TIME_LIMIT,
    }
    if token_match is None or launch != expected_launch:
        fail("authorization_invalid")
    output_parent_fd = _open_bound_directory(OUTPUT_ROOT.parent, launch["output_parent_identity"])
    os.close(output_parent_fd)
    if protocol != PREFLIGHT_PROTOCOL:
        fail("authorization_invalid")
    execution_inputs = {
        "authorized_site": dict(site["inventory"]),
        "site_snapshot": site_snapshot,
        "source_snapshot": source_snapshot,
    }
    return file_sha256, body_sha256, job_name, execution_inputs, value, str(path)


def _identity_string(value: Mapping[str, object]) -> str:
    if set(value) != {"device", "inode", "mode", "owner_uid"} or any(
        type(value.get(name)) is not int for name in value
    ):
        fail("submission_lineage_invalid")
    return ":".join(str(value[name]) for name in ("device", "inode", "mode", "owner_uid"))


def _parse_environment(raw: bytes) -> dict[str, str]:
    if not raw.endswith(b"\0"):
        fail("submission_lineage_invalid")
    result: dict[str, str] = {}
    try:
        for entry in raw[:-1].split(b"\0"):
            name, separator, value = entry.partition(b"=")
            key = name.decode("ascii")
            if not separator or not key or key in result:
                fail("submission_lineage_invalid")
            result[key] = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FinalizeError("submission_lineage_invalid") from error
    return result


def _validate_scheduler_telemetry(value: object, *, deadline: int, held: bool) -> None:
    common = {
        "converged",
        "deadline_seconds",
        "elapsed_milliseconds",
        "explicit_conflict_fields",
        "final_mismatch_fields",
        "mismatch_occurrences",
        "polls",
        "required_consecutive",
    }
    expected_keys = common | (
        {"post_authorization_mismatch_fields", "pre_authorization_mismatch_fields"} if held else set()
    )
    if not isinstance(value, dict) or set(value) != expected_keys:
        fail("submission_lineage_invalid")
    mismatch_occurrences = value.get("mismatch_occurrences")
    common_mismatches = {
        "Account",
        "Command",
        "Comment",
        "Dependency",
        "JobId",
        "JobName",
        "MinMemoryNode",
        "NumCPUs",
        "Partition",
        "QOS",
        "Requeue",
        "Restarts",
        "StdErr",
        "StdOut",
        "TimeLimit",
        "UserId",
        "WorkDir",
        "scontrol_unavailable",
        "squeue_unavailable",
    }
    phase_mismatches = (
        {
            "JobState",
            "NumNodes",
            "Priority",
            "Reason",
            "StartTime",
            "held_accounting",
            "held_accounting_unavailable",
            "held_allocation",
            "held_queue",
            "held_steps",
            "held_steps_unavailable",
        }
        if held
        else {
            "activation_accounting",
            "activation_accounting_unavailable",
            "activation_allocation",
            "activation_hold",
            "activation_queue",
            "activation_state",
        }
    )
    if (
        value.get("converged") is not True
        or value.get("deadline_seconds") != deadline
        or type(value.get("elapsed_milliseconds")) is not int
        or not 0 <= int(value["elapsed_milliseconds"]) <= deadline * 1000
        or value.get("explicit_conflict_fields") != []
        or value.get("final_mismatch_fields") != []
        or type(value.get("polls")) is not int
        or int(value["polls"]) < REQUIRED_CONSECUTIVE
        or value.get("required_consecutive") != REQUIRED_CONSECUTIVE
        or not isinstance(mismatch_occurrences, dict)
        or any(
            name not in common_mismatches | phase_mismatches
            or type(count) is not int
            or not 1 <= count <= int(value["polls"])
            for name, count in mismatch_occurrences.items()
        )
        or (held and value.get("pre_authorization_mismatch_fields") != [])
        or (held and value.get("post_authorization_mismatch_fields") != [])
    ):
        fail("submission_lineage_invalid")


def _stable_writer_lock(reservation_fd: int, expected_sha256: str) -> None:
    descriptor = os.open(".writer.lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=reservation_fd)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or before.st_size != 0
            or expected_sha256 != sha256_bytes(b"")
        ):
            fail("submission_lineage_invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        after = os.fstat(descriptor)
    except BlockingIOError as error:
        raise FinalizeError("submission_lineage_invalid") from error
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        fail("submission_lineage_invalid")


def _validate_submission_lineage(
    record: object,
    *,
    launch_file_sha256: str,
    launch_authorization_sha256: str,
    launch_authorization_path: str,
    launch_authorization: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str, str]:
    if not isinstance(record, dict) or set(record) != {
        "activation_permit_sha256",
        "environment_sha256",
        "job_authorization_sha256",
        "launch_intent_sha256",
        "reservation_path",
        "reservation_root_identity",
        "submission_receipt_sha256",
        "writer_lock_sha256",
    }:
        fail("authorization_invalid")
    if (
        record.get("reservation_path") != str(RESERVATION)
        or not isinstance(record.get("reservation_root_identity"), dict)
        or SHA_RE.fullmatch(str(record.get("job_authorization_sha256"))) is None
        or SHA_RE.fullmatch(str(record.get("submission_receipt_sha256"))) is None
        or any(
            SHA_RE.fullmatch(str(record.get(name))) is None
            for name in (
                "activation_permit_sha256",
                "environment_sha256",
                "launch_intent_sha256",
                "writer_lock_sha256",
            )
        )
    ):
        fail("authorization_invalid")
    reservation_fd = os.open(RESERVATION, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        reservation_identity = descriptor_identity(reservation_fd)
        if (
            reservation_identity != record["reservation_root_identity"]
            or reservation_identity["owner_uid"] != os.getuid()
            or directory_identity_mode(reservation_fd) != 0o500
            or {entry.name for entry in os.scandir(reservation_fd)}
            != {
                ".writer.lock",
                "activation_permit.json",
                "job_authorization.json",
                "launch_intent.json",
                "slurm_environment.bin",
                "submission_receipt.json",
            }
        ):
            fail("submission_lineage_invalid")
        job_auth_raw = stable_file_at(
            reservation_fd,
            "job_authorization.json",
            expected_sha256=str(record["job_authorization_sha256"]),
            code="submission_lineage_invalid",
        )
        receipt_raw = stable_file_at(
            reservation_fd,
            "submission_receipt.json",
            expected_sha256=str(record["submission_receipt_sha256"]),
            code="submission_lineage_invalid",
        )
        permit_raw = stable_file_at(
            reservation_fd,
            "activation_permit.json",
            expected_sha256=str(record["activation_permit_sha256"]),
            code="submission_lineage_invalid",
        )
        intent_raw = stable_file_at(
            reservation_fd,
            "launch_intent.json",
            expected_sha256=str(record["launch_intent_sha256"]),
            code="submission_lineage_invalid",
        )
        environment_raw = stable_file_at(
            reservation_fd,
            "slurm_environment.bin",
            expected_sha256=str(record["environment_sha256"]),
            code="submission_lineage_invalid",
            maximum=1 << 20,
        )
        _stable_writer_lock(reservation_fd, str(record["writer_lock_sha256"]))
    finally:
        os.close(reservation_fd)
    job_authorization = load_canonical(job_auth_raw, "submission_lineage_invalid")
    submission_receipt = load_canonical(receipt_raw, "submission_lineage_invalid")
    activation_permit = load_canonical(permit_raw, "submission_lineage_invalid")
    launch_intent = load_canonical(intent_raw, "submission_lineage_invalid")
    if (
        set(job_authorization)
        != {
            "artifact_type",
            "authorization_file_sha256",
            "authorization_sha256",
            "job",
            "production_authorized",
            "state",
        }
        or job_authorization.get("artifact_type") != "vmvm_task_free_job_authorization_v2"
        or job_authorization.get("authorization_file_sha256") != launch_file_sha256
        or job_authorization.get("authorization_sha256") != launch_authorization_sha256
        or job_authorization.get("production_authorized") is not False
        or job_authorization.get("state") != "held_verified"
        or set(submission_receipt)
        != {
            "activation",
            "artifact_type",
            "authorization_file_sha256",
            "authorization_sha256",
            "environment_sha256",
            "held",
            "job",
            "job_authorization_sha256",
            "production_authorized",
            "release_attempts",
            "release_outcome",
            "state",
            "submission_attempts",
        }
        or submission_receipt.get("artifact_type") != "vmvm_task_free_submission_receipt_v2"
        or submission_receipt.get("authorization_file_sha256") != launch_file_sha256
        or submission_receipt.get("authorization_sha256") != launch_authorization_sha256
        or submission_receipt.get("job_authorization_sha256") != sha256_bytes(job_auth_raw)
        or submission_receipt.get("job") != job_authorization.get("job")
        or submission_receipt.get("production_authorized") is not False
        or submission_receipt.get("state") != "submitted"
        or submission_receipt.get("submission_attempts") != 1
        or submission_receipt.get("release_attempts") != 1
        or submission_receipt.get("release_outcome") not in {"completed", "nonzero", "unknown"}
        or SHA_RE.fullmatch(str(submission_receipt.get("environment_sha256"))) is None
        or submission_receipt.get("environment_sha256") != sha256_bytes(environment_raw)
        or submission_receipt.get("environment_sha256") != record.get("environment_sha256")
    ):
        fail("submission_lineage_invalid")
    job = submission_receipt.get("job")
    if (
        not isinstance(job, dict)
        or set(job) != {"cluster", "job_id", "job_name"}
        or job.get("cluster") != "fair-cw-use2-3"
        or JOB_RE.fullmatch(str(job.get("job_id"))) is None
        or re.fullmatch(r"vmvm-v4-preflight-[0-9a-f]{24}", str(job.get("job_name"))) is None
    ):
        fail("submission_lineage_invalid")
    _validate_scheduler_telemetry(
        submission_receipt.get("held"),
        deadline=HELD_TIMEOUT_SECONDS,
        held=True,
    )
    _validate_scheduler_telemetry(
        submission_receipt.get("activation"),
        deadline=ACTIVATION_TIMEOUT_SECONDS,
        held=False,
    )
    if activation_permit != {
        "artifact_type": "vmvm_task_free_activation_permit_v2",
        "authorization_file_sha256": launch_file_sha256,
        "authorization_sha256": launch_authorization_sha256,
        "environment_sha256": sha256_bytes(environment_raw),
        "job_authorization_sha256": sha256_bytes(job_auth_raw),
        "production_authorized": False,
        "state": "activated",
        "submission_receipt_sha256": sha256_bytes(receipt_raw),
    }:
        fail("submission_lineage_invalid")
    bundle = launch_authorization["bundle"]
    source = launch_authorization["source"]
    runtime = launch_authorization["runtime"]
    credentials = launch_authorization["credentials"]
    launch = launch_authorization["launch"]
    assert all(isinstance(item, dict) for item in (bundle, source, runtime, credentials, launch))
    if launch_intent != {
        "artifact_type": "vmvm_task_free_launch_intent_v2",
        "authorization_file_sha256": launch_file_sha256,
        "authorization_sha256": launch_authorization_sha256,
        "bundle_sha256": {label: bundle[label]["sha256"] for label in ("finalizer", "launcher", "probe", "wrapper")},
        "environment_sha256": sha256_bytes(environment_raw),
        "job_name": job["job_name"],
        "production_authorized": False,
        "state": "reserved",
    }:
        fail("submission_lineage_invalid")
    exported = _parse_environment(environment_raw)
    site = runtime["site"]
    assert isinstance(site, dict)
    inventory = site["inventory"]
    assert isinstance(inventory, dict)
    expected_environment = {
        "DIAG_ACTIVATION_PERMIT": str(RESERVATION / "activation_permit.json"),
        "DIAG_AUTHORIZATION": launch_authorization_path,
        "DIAG_AUTHORIZATION_FILE_SHA256": launch_file_sha256,
        "DIAG_AUTHORIZATION_SHA256": launch_authorization_sha256,
        "DIAG_BUNDLE_IDENTITY": _identity_string(bundle["root_identity"]),
        "DIAG_BUNDLE_ROOT": str(Path(str(bundle["finalizer"]["path"])).parent),
        "DIAG_COMPLETION_RECEIPT": str(COMPLETION_RECEIPT),
        "DIAG_FINALIZER_PATH": str(bundle["finalizer"]["path"]),
        "DIAG_FINALIZER_SHA256": str(bundle["finalizer"]["sha256"]),
        "DIAG_JOB_AUTHORIZATION": str(RESERVATION / "job_authorization.json"),
        "DIAG_JOB_NAME": str(job["job_name"]),
        "DIAG_LAUNCHER_PATH": str(bundle["launcher"]["path"]),
        "DIAG_LAUNCHER_SHA256": str(bundle["launcher"]["sha256"]),
        "DIAG_OUTPUT_PARENT_IDENTITY": _identity_string(launch["output_parent_identity"]),
        "DIAG_OUTPUT_ROOT": str(OUTPUT_ROOT),
        "DIAG_PROBE_PATH": str(bundle["probe"]["path"]),
        "DIAG_PROBE_SHA256": str(bundle["probe"]["sha256"]),
        "DIAG_RESERVATION": str(RESERVATION),
        "DIAG_RESERVATION_IDENTITY": _identity_string(record["reservation_root_identity"]),
        "DIAG_SCRATCH_ROOT": str(SCRATCH_ROOT),
        "DIAG_SOURCE_IDENTITY": _identity_string(source["root_identity"]),
        "DIAG_SOURCE_REVISION": SOURCE_REVISION,
        "DIAG_SOURCE_ROOT": str(SOURCE_ROOT),
        "DIAG_SOURCE_TREE": SOURCE_TREE,
        "DIAG_SUBMISSION_RECEIPT": str(RESERVATION / "submission_receipt.json"),
        "DIAG_VMVM_SHA256": VMVM_SHA256,
        "DIAG_WRAPPER_GATE_TIMEOUT_SECONDS": str(WRAPPER_GATE_TIMEOUT_SECONDS),
        "DIAG_WRAPPER_PATH": str(bundle["wrapper"]["path"]),
        "DIAG_WRAPPER_SHA256": str(bundle["wrapper"]["sha256"]),
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": OWNER,
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_BIN_X86_64": "python3",
        "PYTHON_SITE_X86_64": str(X86_SITE),
        "PYTHON_SITE_X86_64_ENTRY_COUNT": str(inventory["entry_count"]),
        "PYTHON_SITE_X86_64_IDENTITY": _identity_string(site["root_identity"]),
        "PYTHON_SITE_X86_64_MANIFEST_SHA256": str(inventory["manifest_sha256"]),
        "PYTHON_SITE_X86_64_TOTAL_BYTES": str(inventory["total_bytes"]),
        "SLURM_EXPORT_ENV": "NONE",
        "TZ": "UTC",
        "USER": OWNER,
        "UV_BIN_X86_64": str(X86_UV),
        "VACLI_BIN": str(VACLI),
        "VACLI_CONTAINER_PRIVILEGED": "1",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": str(IMAGE_PULL_TIMEOUT_SECONDS),
        "VACLI_LEASE_RETRIES": str(LEASE_ATTEMPT_LIMIT),
        "VACLI_MAX_CONCURRENT_LEASES": "1",
        "VACLI_MAX_PULL_RETRIES": str(IMAGE_PULL_RETRY_LIMIT),
        **{name: str(credentials["tls"][name]["path"]) for name in TLS_NAMES},
    }
    for name in X2P_NAMES:
        value = exported.get(name)
        if (
            not isinstance(value, str)
            or not value
            or "\0" in value
            or "\n" in value
            or len(value.encode()) > 4096
            or sha256_bytes(value.encode()) != credentials["x2p"][name]["sha256"]
        ):
            fail("submission_lineage_invalid")
        expected_environment[name] = value
    if exported != expected_environment:
        fail("submission_lineage_invalid")
    return (
        job,
        sha256_bytes(job_auth_raw),
        sha256_bytes(receipt_raw),
        str(submission_receipt["environment_sha256"]),
    )


def finalize(
    authorization_path: Path,
    authorization_file_sha256: str,
    *,
    execution_binding: Mapping[str, object],
) -> dict[str, str]:
    if os.path.lexists(SCRATCH_ROOT):
        fail("scratch_cleanup_unverified")
    if SHA_RE.fullmatch(authorization_file_sha256) is None:
        fail("authorization_invalid")
    auth_fd = os.open(authorization_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(auth_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o400
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or not 0 < info.st_size <= (1 << 20)
        ):
            fail("authorization_invalid")
        raw = os.read(auth_fd, info.st_size + 1)
        after = os.fstat(auth_fd)
    finally:
        os.close(auth_fd)
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
    if (
        any(getattr(info, field) != getattr(after, field) for field in stable_fields)
        or len(raw) != info.st_size
        or sha256_bytes(raw) != authorization_file_sha256
    ):
        fail("authorization_invalid")
    authorization = load_canonical(raw, "authorization_invalid")
    body = dict(authorization)
    embedded = body.pop("authorization_sha256", None)
    if (
        set(authorization)
        != {
            "artifact_type",
            "authorization_sha256",
            "job",
            "launch_authorization",
            "output",
            "production_authorized",
            "receipt_path",
            "schema_version",
            "state",
            "submission",
        }
        or authorization.get("artifact_type") != "vmvm_task_free_external_completion_authorization_v2"
        or authorization.get("schema_version") != 2
        or authorization.get("state") != "approved"
        or authorization.get("production_authorized") is not False
        or embedded != sha256_bytes(canonical_json(body))
        or authorization.get("receipt_path") != str(COMPLETION_RECEIPT)
    ):
        fail("authorization_invalid")
    (
        launch_file_sha256,
        launch_authorization_sha256,
        launch_job_name,
        expected_execution_inputs,
        launch_authorization,
        launch_authorization_path,
    ) = _validate_launch_authorization(
        authorization.get("launch_authorization"),
        execution_binding=execution_binding,
    )
    (
        lineage_job,
        job_authorization_sha256,
        submission_receipt_sha256,
        environment_sha256,
    ) = _validate_submission_lineage(
        authorization.get("submission"),
        launch_file_sha256=launch_file_sha256,
        launch_authorization_sha256=launch_authorization_sha256,
        launch_authorization_path=launch_authorization_path,
        launch_authorization=launch_authorization,
    )
    job = authorization.get("job")
    if (
        not isinstance(job, dict)
        or set(job)
        != {
            "cluster",
            "job_id",
            "job_name",
            "terminal_observation_sha256",
            "terminal_state",
        }
        or job.get("cluster") != "fair-cw-use2-3"
        or JOB_RE.fullmatch(str(job.get("job_id"))) is None
        or re.fullmatch(r"vmvm-v4-preflight-[0-9a-f]{24}", str(job.get("job_name"))) is None
        or job.get("terminal_state") not in {"COMPLETED", "FAILED", "TIMEOUT", "CANCELLED"}
        or SHA_RE.fullmatch(str(job.get("terminal_observation_sha256"))) is None
        or {
            "cluster": job.get("cluster"),
            "job_id": job.get("job_id"),
            "job_name": job.get("job_name"),
        }
        != lineage_job
        or job.get("job_name") != launch_job_name
    ):
        fail("authorization_invalid")
    output = authorization.get("output")
    if (
        not isinstance(output, dict)
        or set(output)
        != {
            "certificate_sha256",
            "completion_request_sha256",
            "inventory",
            "path",
            "root_identity",
        }
        or output.get("path") != str(OUTPUT_ROOT)
        or not isinstance(output.get("root_identity"), dict)
        or not isinstance(output.get("inventory"), dict)
    ):
        fail("authorization_invalid")
    parent_fd = os.open(OUTPUT_ROOT.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if COMPLETION_RECEIPT.exists() or COMPLETION_RECEIPT.is_symlink():
            fail("receipt_exists")
        output_fd = os.open(
            OUTPUT_ROOT.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        try:
            output_identity = descriptor_identity(output_fd)
            if (
                output_identity != output["root_identity"]
                or output_identity["owner_uid"] != os.getuid()
                or directory_identity_mode(output_fd) != 0o500
                or output_inventory(output_fd) != output["inventory"]
            ):
                fail("output_binding_invalid")
            certificate_raw = stable_file_at(
                output_fd,
                "diagnostic_certificate.json",
                expected_sha256=str(output["certificate_sha256"]),
            )
            request_raw = stable_file_at(
                output_fd,
                "completion_request.json",
                expected_sha256=str(output["completion_request_sha256"]),
            )
            certificate = load_canonical(certificate_raw, "certificate_invalid")
            request = load_canonical(request_raw, "completion_request_invalid")
            validate_certificate(
                certificate,
                expected_execution_inputs=expected_execution_inputs,
            )
            certificate_job = certificate.get("job")
            expected_job = {
                "cluster": job["cluster"],
                "job_id": job["job_id"],
                "job_name": job["job_name"],
            }
            if (
                certificate.get("authorization_file_sha256") != launch_file_sha256
                or certificate.get("authorization_sha256") != launch_authorization_sha256
                or certificate.get("environment_sha256") != environment_sha256
                or certificate.get("job_authorization_sha256") != job_authorization_sha256
                or certificate.get("submission_receipt_sha256") != submission_receipt_sha256
                or certificate_job != expected_job
            ):
                fail("certificate_lineage_invalid")
            if request != {
                "artifact_type": "vmvm_task_free_external_completion_request_v2",
                "authorization_file_sha256": launch_file_sha256,
                "authorization_sha256": launch_authorization_sha256,
                "certificate_sha256": sha256_bytes(certificate_raw),
                "diagnostic_only": True,
                "environment_sha256": environment_sha256,
                "external_completion_receipt": str(COMPLETION_RECEIPT),
                "job": expected_job,
                "job_authorization_sha256": job_authorization_sha256,
                "output_root_identity": descriptor_identity(output_fd),
                "production_authorized": False,
                "state": "awaiting_external_completion",
                "submission_receipt_sha256": submission_receipt_sha256,
            }:
                fail("completion_request_invalid")
            receipt = {
                "artifact_type": "vmvm_task_free_external_completion_receipt_v2",
                "certificate_sha256": sha256_bytes(certificate_raw),
                "completion_authorization_file_sha256": authorization_file_sha256,
                "completion_authorization_sha256": embedded,
                "completion_request_sha256": sha256_bytes(request_raw),
                "diagnostic_only": True,
                "environment_sha256": environment_sha256,
                "finalizer_execution": {
                    "seals": execution_binding["seals"],
                    "sha256": execution_binding["sha256"],
                    "size": execution_binding["size"],
                },
                "job": job,
                "job_authorization_sha256": job_authorization_sha256,
                "launch_authorization_file_sha256": launch_file_sha256,
                "launch_authorization_sha256": launch_authorization_sha256,
                "output_inventory": output["inventory"],
                "output_root_identity": descriptor_identity(output_fd),
                "production_authorized": False,
                "source_revision": SOURCE_REVISION,
                "state": "complete",
                "submission_receipt_sha256": submission_receipt_sha256,
            }
        finally:
            os.close(output_fd)
        receipt_sha256 = _write_receipt(parent_fd, COMPLETION_RECEIPT.name, receipt)
    finally:
        os.close(parent_fd)
    return {"receipt_sha256": receipt_sha256, "state": "complete"}


def directory_identity_mode(descriptor: int) -> int:
    return stat.S_IMODE(os.fstat(descriptor).st_mode)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--authorization-file-sha256", required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--self-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        execution_binding = validate_finalizer_execution(
            Path(__file__),
            bundle_root=args.bundle_root,
            expected_sha256=args.self_sha256,
        )
        result = finalize(
            args.authorization,
            args.authorization_file_sha256,
            execution_binding=execution_binding,
        )
    except BaseException as error:
        code = error.code if isinstance(error, FinalizeError) else "finalizer_failed"
        print(canonical_json({"code": code, "state": "failed"}).decode(), file=sys.stderr)
        return 2
    print(canonical_json(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
