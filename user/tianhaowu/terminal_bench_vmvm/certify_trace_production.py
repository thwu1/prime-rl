#!/usr/bin/env python3
"""Publish a write-once, aggregate-only certificate for a production trace run."""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO

import audit_traces as audit_traces_module
import certify_trace_smoke as certify_trace_smoke_module
import deployment_endpoint as deployment_endpoint_module
import deployment_proxy_policy as deployment_proxy_policy_module
import eval_run_identity as eval_run_identity_module
import guard_success_receipt as guard_success_receipt_module
import inference_route_generation as inference_route_generation_module
import mobius_launch_certificate as launch_certificate_module
import trace_concurrency as trace_concurrency_module
from audit_traces import KIMI_K3_MAX_MODEL_IO_CONTRACT, _iter_traces, _summarize_traces
from certify_trace_smoke import (
    EXPECTED_MODEL_IO_CONTRACT,
    MAX_SEQUENCE_TOKENS,
    _canonical_json,
    _identity_artifact,
    _sha256_bytes,
    _validated_endpoint,
)
from deployment_endpoint import EndpointBindingError, validate_endpoint_binding
from deployment_proxy_policy import (
    DeploymentProxyPolicyError,
    revalidate_deployment_proxy_policy,
    validate_proxy_policy_binding,
)
from eval_run_identity import load_eval_run_identity
from guard_success_receipt import (
    GuardReceiptError,
    load_guard_success_receipt,
    validate_eval_invocations,
    validate_guard_success_linkage,
)
from inference_route_generation import (
    RouteGenerationError,
    validate_readiness_route_generation,
    validate_route_generation,
)
from mobius_launch_certificate import (
    EXPECTED_MOBIUS_LEASE_START_CONCURRENCY,
    EXPECTED_MOBIUS_STEADY_STATE_CONCURRENCY,
    EXPECTED_TASKS,
    LaunchCertificateError,
    validate_launch_certificate_for_run,
)
from trace_concurrency import TraceConcurrencyError, measure_peak_active_rollouts
from vmvm_tb_v2._vacli import concurrency_telemetry as concurrency_telemetry_module
from vmvm_tb_v2._vacli.concurrency_telemetry import (
    ConcurrencyTelemetryError,
    load_concurrency_telemetry_artifact,
)

SCHEMA_VERSION = 2
ARTIFACT_TYPE = "terminal_bench_vmvm_production_trace_certificate_v2"
AUTHORIZATION_ARTIFACT_TYPE = (
    "terminal_bench_vmvm_production_trace_audit_authorization_v2"
)
CHECKPOINT_NAME = "production_trace_checkpoint.json"
PAYLOAD_NAME = "production_trace_certificate.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
EXPECTED_DENYLIST = {
    "logprobs",
    "prompt_logprobs",
    "return_token_ids",
    "top_logprobs",
}
EXPECTED_FULL_TIMEOUTS = {
    "connect_timeout": 120,
    "finalize_timeout": 3_600,
    "harness_request_timeout": 43_200,
    "request_timeout": 43_200,
    "rollout_timeout": 36_000,
    "scoring_timeout": 21_600,
    "session_timeout": 43_200,
    "setup_timeout": 3_600,
}
SFT_READINESS_REQUIREMENTS = (
    "format_v3_export_manifest",
    "schema_v2_immutable_local_tokenizer_tree_preflight_attestation",
)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_COMMAND_OUTPUT_BYTES = 64 * 1024
SLURM_JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
SLURM_CLUSTER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
SLURM_AUTH_ENV = ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH")
RUNTIME_TOOL_PATHS = {
    "bash": "/usr/bin/bash",
    "chmod": "/usr/bin/chmod",
    "env": "/usr/bin/env",
    "git": "/usr/bin/git",
    "id": "/usr/bin/id",
    "mktemp": "/usr/bin/mktemp",
    "realpath": "/usr/bin/realpath",
    "rmdir": "/usr/bin/rmdir",
    "sacct": "/usr/bin/sacct",
    "sbatch": "/usr/bin/sbatch",
    "scancel": "/usr/bin/scancel",
    "scontrol": "/usr/bin/scontrol",
    "sha256sum": "/usr/bin/sha256sum",
    "sleep": "/usr/bin/sleep",
    "squeue": "/usr/bin/squeue",
    "stat": "/usr/bin/stat",
}
EXPECTED_SOURCE_ARTIFACT_LABELS = frozenset(
    {
        "concurrency_telemetry_validator",
        "deployment_endpoint_validator",
        "deployment_proxy_policy_validator",
        "eval_run_identity_validator",
        "guard_success_validator",
        "launch_certificate_validator",
        "production_audit_bootstrap",
        "production_audit_submission_controller",
        "production_audit_submitter",
        "production_audit_wrapper",
        "production_certificate",
        "route_generation_validator",
        "sft_export_preflight",
        "sft_preflight_cli",
        "sft_target_rendering_contract",
        "sft_training_entrypoint",
        "smoke_certificate_helpers",
        "strict_sft_exporter",
        "terminal_bench_taskset",
        "trace_auditor",
        "trace_concurrency_validator",
        "vmvm_backend",
    }
)
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
SACCT_FIELDS = (
    "JobIDRaw",
    "JobName",
    "User",
    "UID",
    "Account",
    "Partition",
    "QOS",
    "State",
    "ExitCode",
    "DerivedExitCode",
    "Submit",
    "Start",
    "End",
    "Elapsed",
    "Restarts",
    "NNodes",
    "AllocCPUS",
    "ReqMem",
)


class ProductionCertificateError(ValueError):
    """The production trace run cannot be certified without weakening an invariant."""


@dataclass
class StableFile:
    """An open, path-anchored regular file whose bytes and identity stay bound."""

    path: Path
    parent_fd: int
    descriptor: int
    signature: tuple[int, int, int, int, int, int, int]
    sha256: str
    size: int

    def read(self, *, limit: int = MAX_ARTIFACT_BYTES) -> bytes:
        if self.size > limit:
            raise ProductionCertificateError("artifact_too_large")
        chunks: list[bytes] = []
        offset = 0
        while offset < self.size:
            try:
                chunk = os.pread(
                    self.descriptor, min(1 << 20, self.size - offset), offset
                )
            except OSError as error:
                raise ProductionCertificateError("artifact_unreadable") from error
            if not chunk:
                raise ProductionCertificateError("artifact_short_read")
            chunks.append(chunk)
            offset += len(chunk)
        body = b"".join(chunks)
        self.revalidate()
        if _sha256_bytes(body) != self.sha256:
            raise ProductionCertificateError("artifact_changed")
        return body

    def revalidate(self) -> None:
        try:
            descriptor_status = os.fstat(self.descriptor)
            path_status = os.stat(
                self.path.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            fresh_parent = os.open(
                self.path.parent,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                original_parent = os.fstat(self.parent_fd)
                current_parent = os.fstat(fresh_parent)
            finally:
                os.close(fresh_parent)
        except OSError as error:
            raise ProductionCertificateError("artifact_changed") from error
        if (
            _stat_signature(descriptor_status) != self.signature
            or _stat_signature(path_status) != self.signature
            or (original_parent.st_dev, original_parent.st_ino)
            != (current_parent.st_dev, current_parent.st_ino)
        ):
            raise ProductionCertificateError("artifact_changed")

    def close(self) -> None:
        os.close(self.descriptor)
        os.close(self.parent_fd)


@dataclass
class ResultsSnapshot:
    source: StableFile
    handle: BinaryIO
    path: Path

    def revalidate(self) -> None:
        try:
            self.source.revalidate()
        except ProductionCertificateError as error:
            raise ProductionCertificateError("results_changed_during_audit") from error
        if (
            _sha256_descriptor(self.source.descriptor, self.source.size)
            != self.source.sha256
        ):
            raise ProductionCertificateError("results_changed_during_audit")
        status = os.fstat(self.handle.fileno())
        if (
            not stat.S_ISREG(status.st_mode)
            or stat.S_IMODE(status.st_mode) != 0o400
            or status.st_nlink != 0
            or status.st_size != self.source.size
            or _sha256_descriptor(self.handle.fileno(), status.st_size)
            != self.source.sha256
        ):
            raise ProductionCertificateError("results_snapshot_changed")

    def close(self) -> None:
        self.handle.close()
        self.source.close()


@dataclass
class DirectoryAnchor:
    path: Path
    parent_fd: int
    descriptor: int
    signature: tuple[int, int, int, int, int]

    def revalidate(self) -> None:
        try:
            descriptor_status = os.fstat(self.descriptor)
            visible = os.stat(
                self.path.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            fresh_parent = os.open(
                self.path.parent,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                parent_before = os.fstat(self.parent_fd)
                parent_after = os.fstat(fresh_parent)
            finally:
                os.close(fresh_parent)
        except OSError as error:
            raise ProductionCertificateError("run_dir_changed") from error
        if (
            _directory_signature(descriptor_status) != self.signature
            or _directory_signature(visible) != self.signature
            or (parent_before.st_dev, parent_before.st_ino)
            != (parent_after.st_dev, parent_after.st_ino)
        ):
            raise ProductionCertificateError("run_dir_changed")

    def close(self) -> None:
        os.close(self.descriptor)
        os.close(self.parent_fd)


def _normalized_absolute(path: Path) -> bool:
    return path.is_absolute() and path == Path(os.path.normpath(path))


def _directory_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid)


def _open_stable_file(
    path: Path,
    *,
    label: str,
    expected_sha256: str | None = None,
    allowed_modes: frozenset[int] = frozenset({0o400, 0o444, 0o600, 0o640, 0o644}),
    maximum: int | None = MAX_ARTIFACT_BYTES,
    anchor: DirectoryAnchor | None = None,
) -> StableFile:
    if not _normalized_absolute(path) or not path.name or "/" in path.name:
        raise ProductionCertificateError(f"{label}_path_invalid")
    if expected_sha256 is not None and SHA256_RE.fullmatch(expected_sha256) is None:
        raise ProductionCertificateError(f"{label}_sha256_invalid")
    parent_fd = -1
    descriptor = -1
    try:
        if anchor is not None:
            anchor.revalidate()
            if path.parent != anchor.path:
                raise ProductionCertificateError(f"{label}_path_invalid")
            parent_fd = os.dup(anchor.descriptor)
        else:
            resolved_parent = path.parent.resolve(strict=True)
            if resolved_parent != path.parent:
                raise ProductionCertificateError(f"{label}_path_invalid")
            parent_fd = os.open(
                path.parent,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
        descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        path_before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        mode = stat.S_IMODE(before.st_mode)
        if (
            _stat_signature(before) != _stat_signature(path_before)
            or not stat.S_ISREG(before.st_mode)
            or mode not in allowed_modes
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or before.st_size < 1
            or (maximum is not None and before.st_size > maximum)
        ):
            raise ProductionCertificateError(f"{label}_identity_invalid")
        digest = hashlib.sha256()
        offset = 0
        while offset < before.st_size:
            block = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
            if not block:
                raise ProductionCertificateError(f"{label}_short_read")
            digest.update(block)
            offset += len(block)
        after = os.fstat(descriptor)
        path_after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        observed_sha256 = digest.hexdigest()
        if (
            _stat_signature(before) != _stat_signature(after)
            or _stat_signature(after) != _stat_signature(path_after)
            or (expected_sha256 is not None and observed_sha256 != expected_sha256)
        ):
            raise ProductionCertificateError(f"{label}_changed")
        return StableFile(
            path=path,
            parent_fd=parent_fd,
            descriptor=descriptor,
            signature=_stat_signature(after),
            sha256=observed_sha256,
            size=after.st_size,
        )
    except ProductionCertificateError:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
        raise
    except (OSError, RuntimeError) as error:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
        raise ProductionCertificateError(f"{label}_unreadable") from error


def _sha256_descriptor(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        try:
            block = os.pread(descriptor, min(1 << 20, size - offset), offset)
        except OSError as error:
            raise ProductionCertificateError("artifact_unreadable") from error
        if not block:
            raise ProductionCertificateError("artifact_short_read")
        digest.update(block)
        offset += len(block)
    return digest.hexdigest()


def _snapshot_results(
    path: Path,
    *,
    anchor: DirectoryAnchor | None = None,
) -> ResultsSnapshot:
    source = _open_stable_file(
        path,
        label="results",
        maximum=None,
        anchor=anchor,
    )
    handle: BinaryIO | None = None
    try:
        temporary_parent = (
            Path(f"/proc/self/fd/{anchor.descriptor}")
            if anchor is not None
            else path.parent
        )
        handle = tempfile.TemporaryFile(mode="w+b", dir=temporary_parent)
        copied = False
        try:
            fcntl.ioctl(
                handle.fileno(), 0x40049409, source.descriptor
            )  # Linux FICLONE.
            copied = True
        except OSError:
            pass
        if not copied:
            offset = 0
            while offset < source.size:
                block = os.pread(
                    source.descriptor, min(1 << 20, source.size - offset), offset
                )
                if not block:
                    raise ProductionCertificateError("results_snapshot_failed")
                view = memoryview(block)
                while view:
                    written = os.write(handle.fileno(), view)
                    if written <= 0:
                        raise ProductionCertificateError("results_snapshot_failed")
                    view = view[written:]
                offset += len(block)
        os.fchmod(handle.fileno(), 0o400)
        os.fsync(handle.fileno())
        snapshot = ResultsSnapshot(
            source=source,
            handle=handle,
            path=Path(f"/proc/self/fd/{handle.fileno()}"),
        )
        snapshot.revalidate()
        return snapshot
    except BaseException:
        if handle is not None:
            handle.close()
        source.close()
        raise


def _expected_slugs_from_bytes(raw: bytes) -> set[str]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ProductionCertificateError("expected_task_file_invalid") from error
    lines = text.splitlines()
    if (
        not lines
        or any(
            not line
            or line != line.strip()
            or line.startswith("#")
            or "\t" in line
            or any(character in line for character in "\x00\r\n")
            for line in lines
        )
        or len(set(lines)) != len(lines)
    ):
        raise ProductionCertificateError("expected_task_file_invalid")
    return set(lines)


def _open_directory_anchor(path: Path) -> DirectoryAnchor:
    if not _normalized_absolute(path) or not path.name:
        raise ProductionCertificateError("run_dir_invalid")
    parent_fd = -1
    descriptor = -1
    try:
        if path.parent.resolve(strict=True) != path.parent:
            raise ProductionCertificateError("run_dir_invalid")
        parent_fd = os.open(
            path.parent,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptor = os.open(
            path.name,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        visible = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _directory_signature(opened) != _directory_signature(visible)
            or not stat.S_ISDIR(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o700
            or opened.st_uid != os.getuid()
        ):
            raise ProductionCertificateError("run_dir_invalid")
        return DirectoryAnchor(
            path, parent_fd, descriptor, _directory_signature(opened)
        )
    except ProductionCertificateError:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
        raise
    except (OSError, RuntimeError) as error:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
        raise ProductionCertificateError("run_dir_invalid") from error


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise ProductionCertificateError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise ProductionCertificateError(f"{label}_invalid")
    return value


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _scheduler_environment() -> dict[str, str]:
    environment = {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    for name in SLURM_AUTH_ENV:
        descriptor = -1
        value = os.environ.get(name)
        if (
            not isinstance(value, str)
            or not value
            or not os.path.isabs(value)
            or "\n" in value
            or "\r" in value
        ):
            raise ProductionCertificateError("scheduler_auth_invalid")
        try:
            descriptor = os.open(
                value,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            status = os.fstat(descriptor)
        except OSError as error:
            raise ProductionCertificateError("scheduler_auth_invalid") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise ProductionCertificateError("scheduler_auth_invalid")
        environment[name] = value
    return environment


def _scheduler_command(argv: Sequence[str]) -> bytes:
    try:
        result = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=False,
            stdin=subprocess.DEVNULL,
            env=_scheduler_environment(),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ProductionCertificateError("evaluation_job_state_unavailable") from error
    if (
        result.returncode != 0
        or result.stderr
        or len(result.stdout) > MAX_COMMAND_OUTPUT_BYTES
    ):
        raise ProductionCertificateError("evaluation_job_state_unavailable")
    return result.stdout


def _parse_scontrol_identity(raw: bytes, job_id: str) -> dict[str, str]:
    try:
        text = raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise ProductionCertificateError("evaluation_job_identity_invalid") from error
    if not text or "\n" in text or "\r" in text:
        raise ProductionCertificateError("evaluation_job_identity_invalid")
    matches = tuple(re.finditer(r"(?:^| )([A-Za-z][A-Za-z0-9/]*)=", text))
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip()
        if key in values or not value:
            raise ProductionCertificateError("evaluation_job_identity_invalid")
        values[key] = value
    required = {
        "Account",
        "Command",
        "JobId",
        "JobName",
        "JobState",
        "Partition",
        "QOS",
        "Requeue",
        "Restarts",
        "UserId",
        "WorkDir",
    }
    if (
        not required.issubset(values)
        or values["JobId"] != job_id
        or values["UserId"] != f"tianhaowu({os.getuid()})"
        or values["JobState"].removesuffix("+") != "COMPLETED"
        or values["Requeue"] != "0"
        or values["Restarts"] != "0"
    ):
        raise ProductionCertificateError("evaluation_job_identity_invalid")
    return {key: values[key] for key in sorted(required)}


def _parse_sacct_identity(
    raw: bytes, job_id: str
) -> tuple[dict[str, str], list[dict[str, str]]]:
    try:
        lines = [
            line for line in raw.decode("utf-8", errors="strict").splitlines() if line
        ]
    except UnicodeDecodeError as error:
        raise ProductionCertificateError("evaluation_job_identity_invalid") from error
    rows: list[dict[str, str]] = []
    for line in lines:
        fields = line.split("|")
        if len(fields) != len(SACCT_FIELDS):
            raise ProductionCertificateError("evaluation_job_identity_invalid")
        row = dict(zip(SACCT_FIELDS, fields, strict=True))
        row_id = row["JobIDRaw"]
        is_allocation = row_id == job_id
        if (
            not row_id
            or not (is_allocation or row_id.startswith(f"{job_id}."))
            or row["State"].removesuffix("+") != "COMPLETED"
            or row["ExitCode"] != "0:0"
            or (
                is_allocation
                and (row["DerivedExitCode"] != "0:0" or row["Restarts"] != "0")
            )
            or (
                not is_allocation
                and (
                    row["DerivedExitCode"] not in {"", "0:0"}
                    or row["Restarts"] not in {"", "0"}
                )
            )
        ):
            raise ProductionCertificateError("evaluation_job_not_successfully_terminal")
        rows.append(row)
    allocations = [row for row in rows if row["JobIDRaw"] == job_id]
    steps = [row for row in rows if row["JobIDRaw"] != job_id]
    if (
        len(allocations) != 1
        or not steps
        or allocations[0]["User"] != "tianhaowu"
        or allocations[0]["UID"] != str(os.getuid())
        or len({row["JobIDRaw"] for row in steps}) != len(steps)
    ):
        raise ProductionCertificateError("evaluation_job_identity_invalid")
    return allocations[0], steps


def _terminal_scheduler_snapshot(job_id: str, cluster: str) -> dict[str, Any]:
    """Capture one exact terminal view, including empty allocation and step queues."""

    allocation_queue = _scheduler_command(
        [
            "/usr/bin/squeue",
            "-M",
            cluster,
            "--noheader",
            "--jobs",
            job_id,
            "--format=%A|%j|%u|%T",
        ]
    )
    step_queue = _scheduler_command(
        [
            "/usr/bin/squeue",
            "-M",
            cluster,
            "--steps",
            "--noheader",
            "--jobs",
            job_id,
            "--format=%i|%j|%u|%T",
        ]
    )
    if allocation_queue.strip() or step_queue.strip():
        raise ProductionCertificateError("evaluation_job_still_queued")
    sacct_raw = _scheduler_command(
        [
            "/usr/bin/sacct",
            "-M",
            cluster,
            "--noheader",
            "--parsable2",
            "--duplicates",
            "--jobs",
            job_id,
            f"--format={','.join(SACCT_FIELDS)}",
        ]
    )
    allocation, steps = _parse_sacct_identity(sacct_raw, job_id)
    scontrol_raw = _scheduler_command(
        ["/usr/bin/scontrol", "-M", cluster, "show", "job", "--oneliner", job_id]
    )
    scontrol = _parse_scontrol_identity(scontrol_raw, job_id)
    record = {
        "cluster": cluster,
        "job_id": job_id,
        "allocation": allocation,
        "steps": steps,
        "sacct_fields": list(SACCT_FIELDS),
        "sacct_sha256": _sha256_bytes(sacct_raw),
        "scontrol": scontrol,
        "scontrol_sha256": _sha256_bytes(scontrol_raw),
        "queue": {
            "allocation_rows": 0,
            "allocation_sha256": _sha256_bytes(allocation_queue),
            "step_rows": 0,
            "steps_sha256": _sha256_bytes(step_queue),
        },
        "requeue": {
            "duplicate_allocation_rows": 0,
            "restarts": 0,
            "scontrol_requeue": 0,
        },
    }
    return record


def require_slurm_terminal(
    job_id: str,
    cluster: str,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Require two stable terminal views with no allocation or step queued."""

    if (
        SLURM_JOB_ID_RE.fullmatch(job_id) is None
        or SLURM_CLUSTER_RE.fullmatch(cluster) is None
    ):
        raise ProductionCertificateError("evaluation_job_identity_invalid")
    first = _terminal_scheduler_snapshot(job_id, cluster)
    sleeper(2.0)
    second = _terminal_scheduler_snapshot(job_id, cluster)
    if second != first:
        raise ProductionCertificateError("evaluation_job_identity_changed")
    record = {**second, "terminal_observations": 2}
    return _validate_terminal_record(
        record,
        expected_job_id=job_id,
        expected_cluster=cluster,
        authorized_record=record,
    )


def _validate_terminal_record(
    record: object,
    *,
    expected_job_id: str,
    expected_cluster: str,
    authorized_record: object,
) -> dict[str, Any]:
    if not isinstance(record, dict) or record != authorized_record:
        raise ProductionCertificateError("evaluation_job_authorization_mismatch")
    if (
        record.get("cluster") != expected_cluster
        or record.get("job_id") != expected_job_id
    ):
        raise ProductionCertificateError("evaluation_job_identity_invalid")
    allocation = record.get("allocation")
    steps = record.get("steps")
    queue = record.get("queue")
    requeue = record.get("requeue")
    scontrol = record.get("scontrol")
    exact_row_keys = set(SACCT_FIELDS)
    if (
        not isinstance(allocation, dict)
        or set(allocation) != exact_row_keys
        or any(not isinstance(value, str) for value in allocation.values())
        or allocation.get("JobIDRaw") != expected_job_id
        or allocation.get("User") != "tianhaowu"
        or allocation.get("UID") != str(os.getuid())
        or any(
            not allocation.get(field)
            for field in (
                "JobName",
                "Account",
                "Partition",
                "QOS",
                "Submit",
                "Start",
                "End",
                "Elapsed",
                "NNodes",
                "AllocCPUS",
                "ReqMem",
            )
        )
        or allocation.get("State", "").removesuffix("+") != "COMPLETED"
        or allocation.get("ExitCode") != "0:0"
        or allocation.get("DerivedExitCode") != "0:0"
        or allocation.get("Restarts") != "0"
        or not isinstance(steps, list)
        or not steps
        or any(
            not isinstance(step, dict)
            or set(step) != exact_row_keys
            or any(not isinstance(value, str) for value in step.values())
            or not str(step.get("JobIDRaw", "")).startswith(f"{expected_job_id}.")
            or str(step.get("State", "")).removesuffix("+") != "COMPLETED"
            or step.get("ExitCode") != "0:0"
            or step.get("DerivedExitCode") not in {"", "0:0"}
            or step.get("Restarts") not in {"", "0"}
            for step in steps
        )
        or len({step["JobIDRaw"] for step in steps}) != len(steps)
        or record.get("sacct_fields") != list(SACCT_FIELDS)
        or record.get("terminal_observations") != 2
        or not isinstance(record.get("sacct_sha256"), str)
        or SHA256_RE.fullmatch(record["sacct_sha256"]) is None
        or not isinstance(scontrol, dict)
        or set(scontrol)
        != {
            "Account",
            "Command",
            "JobId",
            "JobName",
            "JobState",
            "Partition",
            "QOS",
            "Requeue",
            "Restarts",
            "UserId",
            "WorkDir",
        }
        or any(not isinstance(value, str) or not value for value in scontrol.values())
        or scontrol.get("JobId") != expected_job_id
        or scontrol.get("JobName") != allocation.get("JobName")
        or scontrol.get("UserId") != f"tianhaowu({os.getuid()})"
        or scontrol.get("JobState", "").removesuffix("+") != "COMPLETED"
        or scontrol.get("Account") != allocation.get("Account")
        or scontrol.get("Partition") != allocation.get("Partition")
        or scontrol.get("QOS") != allocation.get("QOS")
        or scontrol.get("Requeue") != "0"
        or scontrol.get("Restarts") != "0"
        or not isinstance(record.get("scontrol_sha256"), str)
        or SHA256_RE.fullmatch(record["scontrol_sha256"]) is None
        or requeue
        != {
            "duplicate_allocation_rows": 0,
            "restarts": 0,
            "scontrol_requeue": 0,
        }
        or queue
        != {
            "allocation_rows": 0,
            "allocation_sha256": _sha256_bytes(b""),
            "step_rows": 0,
            "steps_sha256": _sha256_bytes(b""),
        }
    ):
        raise ProductionCertificateError("evaluation_job_not_successfully_terminal")
    return record


def _acquire_writer_lock(
    run_dir: Path, anchor: DirectoryAnchor | None = None
) -> BinaryIO:
    lock_path = run_dir / ".writer.lock"
    descriptor = -1
    try:
        descriptor = os.open(
            lock_path.name if anchor is not None else lock_path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=anchor.descriptor if anchor is not None else None,
        )
        before = os.fstat(descriptor)
        path_before = os.stat(
            lock_path.name if anchor is not None else lock_path,
            dir_fd=anchor.descriptor if anchor is not None else None,
            follow_symlinks=False,
        )
        if (
            _stat_signature(before) != _stat_signature(path_before)
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or before.st_size != 0
        ):
            raise ProductionCertificateError("writer_lock_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ProductionCertificateError("writer_active") from error
        after = os.fstat(descriptor)
        path_after = os.stat(
            lock_path.name if anchor is not None else lock_path,
            dir_fd=anchor.descriptor if anchor is not None else None,
            follow_symlinks=False,
        )
        if _stat_signature(before) != _stat_signature(after) or _stat_signature(
            after
        ) != _stat_signature(path_after):
            raise ProductionCertificateError("writer_lock_changed")
        return os.fdopen(descriptor, "rb", closefd=True)
    except OSError as error:
        raise ProductionCertificateError("writer_lock_unreadable") from error
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _revalidate_writer_lock(
    lock: BinaryIO,
    run_dir: Path,
    anchor: DirectoryAnchor | None = None,
) -> None:
    lock_path = run_dir / ".writer.lock"
    try:
        descriptor_status = os.fstat(lock.fileno())
        path_status = os.stat(
            lock_path.name if anchor is not None else lock_path,
            dir_fd=anchor.descriptor if anchor is not None else None,
            follow_symlinks=False,
        )
    except (OSError, ValueError) as error:
        raise ProductionCertificateError("writer_lock_changed") from error
    if (
        _stat_signature(descriptor_status) != _stat_signature(path_status)
        or not stat.S_ISREG(descriptor_status.st_mode)
        or stat.S_IMODE(descriptor_status.st_mode) != 0o600
        or descriptor_status.st_uid != os.getuid()
        or descriptor_status.st_nlink != 1
        or descriptor_status.st_size != 0
    ):
        raise ProductionCertificateError("writer_lock_changed")


def _pinned_artifact(path: Path, expected_sha256: str, *, label: str) -> dict[str, str]:
    snapshot: StableFile | None = None
    try:
        snapshot = _open_stable_file(
            path,
            label=label,
            expected_sha256=expected_sha256,
        )
        snapshot.revalidate()
        return {"path": str(path), "sha256": snapshot.sha256}
    finally:
        if snapshot is not None:
            snapshot.close()


def _observed_artifact(path: Path, *, label: str) -> dict[str, str]:
    snapshot: StableFile | None = None
    try:
        snapshot = _open_stable_file(path, label=label)
        snapshot.revalidate()
        return {"path": str(path), "sha256": snapshot.sha256}
    finally:
        if snapshot is not None:
            snapshot.close()


def _module_artifact(
    module: ModuleType,
    relative_path: str,
    *,
    label: str,
) -> dict[str, str]:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        raise ProductionCertificateError(f"{label}_source_mismatch")
    try:
        expected = (PROJECT_ROOT / relative_path).resolve(strict=True)
        observed = Path(module_file).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ProductionCertificateError(f"{label}_source_mismatch") from error
    if observed != expected:
        raise ProductionCertificateError(f"{label}_source_mismatch")
    snapshot: StableFile | None = None
    try:
        snapshot = _open_stable_file(expected, label=label)
        return {"path": str(expected), "sha256": snapshot.sha256}
    finally:
        if snapshot is not None:
            snapshot.close()


def _source_path_artifact(relative_path: str, *, label: str) -> dict[str, str]:
    expected = PROJECT_ROOT / relative_path
    try:
        observed = expected.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ProductionCertificateError(f"{label}_source_invalid") from error
    if observed != expected:
        raise ProductionCertificateError(f"{label}_source_mismatch")
    snapshot: StableFile | None = None
    try:
        snapshot = _open_stable_file(expected, label=label)
        return {"path": str(expected), "sha256": snapshot.sha256}
    finally:
        if snapshot is not None:
            snapshot.close()


def _provenance_job_id(
    path: Path,
    *,
    anchor: DirectoryAnchor | None = None,
) -> str:
    snapshot: StableFile | None = None
    try:
        snapshot = _open_stable_file(
            path,
            label="provenance",
            maximum=MAX_COMMAND_OUTPUT_BYTES,
            anchor=anchor,
        )
        raw = snapshot.read(limit=MAX_COMMAND_OUTPUT_BYTES)
    finally:
        if snapshot is not None:
            snapshot.close()
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ProductionCertificateError("provenance_invalid") from error
    values = [
        line.removeprefix("slurm_job_id=")
        for line in lines
        if line.startswith("slurm_job_id=")
    ]
    if len(values) != 1 or SLURM_JOB_ID_RE.fullmatch(values[0]) is None:
        raise ProductionCertificateError("provenance_job_identity_invalid")
    return values[0]


def _rehash_artifacts(artifacts: dict[str, dict[str, str]]) -> None:
    for name, record in artifacts.items():
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise ProductionCertificateError(f"artifact_invalid:{name}")
        try:
            path = Path(record["path"])
            expected = record["sha256"]
        except (KeyError, TypeError, ValueError) as error:
            raise ProductionCertificateError(f"artifact_invalid:{name}") from error
        try:
            _pinned_artifact(path, expected, label=f"artifact_{name}")
        except ProductionCertificateError as error:
            raise ProductionCertificateError(
                f"artifact_hash_mismatch:{name}"
            ) from error


def _sft_training_readiness_scope() -> dict[str, object]:
    return {
        "established": False,
        "trace_certificate_sufficient": False,
        "required_downstream_artifacts": list(SFT_READINESS_REQUIREMENTS),
    }


def _validate_sft_training_readiness_scope(value: object) -> None:
    if value != _sft_training_readiness_scope():
        raise ProductionCertificateError("sft_training_readiness_claim_invalid")


def _validate_submission_attestation(
    value: object, authorization: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "activation_permit",
        "held_authorization",
        "intent",
        "job",
        "reservation",
        "submission_receipt",
    }:
        raise ProductionCertificateError("audit_submission_attestation_invalid")
    reservation = value.get("reservation")
    job = value.get("job")
    submission = authorization.get("audit_submission")
    if (
        not isinstance(submission, dict)
        or reservation != {"path": submission.get("reservation_dir"), "mode": "0500"}
        or not isinstance(job, dict)
        or job.get("cluster") != submission.get("cluster")
        or job.get("name") != submission.get("job_name")
        or not isinstance(job.get("id"), str)
        or SLURM_JOB_ID_RE.fullmatch(job["id"]) is None
    ):
        raise ProductionCertificateError("audit_submission_attestation_invalid")
    for label in (
        "intent",
        "held_authorization",
        "submission_receipt",
        "activation_permit",
    ):
        _authorization_artifact(value.get(label), label=f"submission_{label}")
    return dict(value)


def _expected_audit_policy() -> dict[str, object]:
    return {
        "aggregate_only": True,
        "expected_traces": EXPECTED_TASKS,
        "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        "model_io_contract": EXPECTED_MODEL_IO_CONTRACT,
        "require_exact_provider_json": True,
        "require_logprobs": False,
        "require_clean_stop": True,
        "require_model_io": True,
        "require_reasoning": True,
        "require_request_graph_match": True,
        "require_token_data": False,
        "rollouts_per_task": 1,
    }


def _authorization_artifact(value: object, *, label: str) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not _normalized_absolute(Path(value["path"]))
        or not isinstance(value.get("sha256"), str)
        or SHA256_RE.fullmatch(value["sha256"]) is None
    ):
        raise ProductionCertificateError(f"audit_authorization_{label}_invalid")
    return {"path": value["path"], "sha256": value["sha256"]}


def _validate_authorized_scheduler(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProductionCertificateError("audit_authorization_scheduler_invalid")
    expected_keys = {
        "allocation",
        "cluster",
        "job_id",
        "queue",
        "requeue",
        "sacct_fields",
        "sacct_sha256",
        "scontrol",
        "scontrol_sha256",
        "steps",
        "terminal_observations",
    }
    if set(value) != expected_keys:
        raise ProductionCertificateError("audit_authorization_scheduler_invalid")
    job_id = value.get("job_id")
    cluster = value.get("cluster")
    if (
        not isinstance(job_id, str)
        or SLURM_JOB_ID_RE.fullmatch(job_id) is None
        or not isinstance(cluster, str)
        or SLURM_CLUSTER_RE.fullmatch(cluster) is None
        or value.get("sacct_fields") != list(SACCT_FIELDS)
        or not isinstance(value.get("sacct_sha256"), str)
        or SHA256_RE.fullmatch(value["sacct_sha256"]) is None
        or not isinstance(value.get("scontrol_sha256"), str)
        or SHA256_RE.fullmatch(value["scontrol_sha256"]) is None
    ):
        raise ProductionCertificateError("audit_authorization_scheduler_invalid")
    return _validate_terminal_record(
        value,
        expected_job_id=job_id,
        expected_cluster=cluster,
        authorized_record=value,
    )


def _load_audit_authorization(
    path: Path,
    expected_sha256: str,
) -> tuple[dict[str, Any], dict[str, str], StableFile]:
    snapshot = _open_stable_file(
        path,
        label="audit_authorization",
        expected_sha256=expected_sha256,
        allowed_modes=frozenset({0o400}),
        maximum=2 * 1024 * 1024,
    )
    try:
        raw = snapshot.read(limit=2 * 1024 * 1024)
        value = _strict_json_object(raw, label="audit_authorization")
        if raw != _canonical_json(value) + b"\n":
            raise ProductionCertificateError("audit_authorization_not_canonical")
        expected_keys = {
            "artifact_type",
            "audit_submission",
            "audit_policy",
            "authorization_nonce",
            "authorization_sha256",
            "inputs",
            "run",
            "scheduler",
            "schema_version",
            "source",
            "state",
        }
        if set(value) != expected_keys:
            raise ProductionCertificateError("audit_authorization_invalid")
        embedded = value.get("authorization_sha256")
        body = dict(value)
        body.pop("authorization_sha256", None)
        nonce = value.get("authorization_nonce")
        if (
            value.get("schema_version") != 1
            or value.get("artifact_type") != AUTHORIZATION_ARTIFACT_TYPE
            or value.get("state") != "approved"
            or not isinstance(embedded, str)
            or embedded != _sha256_bytes(_canonical_json(body))
            or not isinstance(nonce, str)
            or SHA256_RE.fullmatch(nonce) is None
            or len(set(nonce)) < 8
        ):
            raise ProductionCertificateError("audit_authorization_invalid")
        if value.get("audit_policy") != _expected_audit_policy():
            raise ProductionCertificateError("audit_authorization_policy_invalid")

        audit_submission = value.get("audit_submission")
        if (
            not isinstance(audit_submission, dict)
            or set(audit_submission)
            != {
                "cluster",
                "job_name",
                "launch_token_sha256",
                "log_path",
                "policy",
                "reservation_dir",
                "resources",
            }
            or audit_submission.get("job_name")
            != f"trace-production-audit-{str(value.get('authorization_nonce', ''))[:16]}"
            or audit_submission.get("launch_token_sha256")
            != _sha256_bytes(str(value.get("authorization_nonce", "")).encode("ascii"))
            or audit_submission.get("policy")
            != {
                "held_submission": True,
                "one_shot": True,
                "requeue": False,
                "wrapper_transport": "sbatch_stdin_exact_bytes",
            }
            or audit_submission.get("resources")
            != {
                "account": "ram",
                "cpus_per_task": 2,
                "memory": "8G",
                "nodes": 1,
                "ntasks": 1,
                "partition": "cpu_x86",
                "qos": "cpu_x86_lowest",
                "time_limit": "02:00:00",
            }
            or not isinstance(audit_submission.get("cluster"), str)
            or SLURM_CLUSTER_RE.fullmatch(audit_submission["cluster"]) is None
            or not isinstance(audit_submission.get("reservation_dir"), str)
            or not _normalized_absolute(Path(audit_submission["reservation_dir"]))
            or not isinstance(audit_submission.get("log_path"), str)
            or not _normalized_absolute(Path(audit_submission["log_path"]))
            or "%j" not in Path(audit_submission["log_path"]).name
        ):
            raise ProductionCertificateError("audit_authorization_submission_invalid")

        run = value.get("run")
        if (
            not isinstance(run, dict)
            or set(run)
            != {
                "eval_run_identity_file_sha256",
                "eval_run_identity_sha256",
                "path",
                "resume",
                "role",
            }
            or not isinstance(run.get("path"), str)
            or not _normalized_absolute(Path(run["path"]))
            or run.get("role") != "mobius"
            or run.get("resume") is not False
            or any(
                not isinstance(run.get(key), str)
                or SHA256_RE.fullmatch(run[key]) is None
                for key in ("eval_run_identity_file_sha256", "eval_run_identity_sha256")
            )
        ):
            raise ProductionCertificateError("audit_authorization_run_invalid")

        inputs = value.get("inputs")
        if not isinstance(inputs, dict) or set(inputs) != {
            "launch_certificate",
            "oracle_receipt",
            "production_config",
            "task_file",
        }:
            raise ProductionCertificateError("audit_authorization_inputs_invalid")
        for label in ("launch_certificate", "oracle_receipt", "production_config"):
            _authorization_artifact(inputs[label], label=label)
        task = inputs.get("task_file")
        if not isinstance(task, dict) or set(task) != {"count", "path", "sha256"}:
            raise ProductionCertificateError("audit_authorization_task_file_invalid")
        _authorization_artifact(
            {"path": task.get("path"), "sha256": task.get("sha256")},
            label="task_file",
        )
        if type(task.get("count")) is not int or task["count"] != EXPECTED_TASKS:
            raise ProductionCertificateError("audit_authorization_task_file_invalid")

        source = value.get("source")
        if (
            not isinstance(source, dict)
            or set(source)
            != {
                "artifacts",
                "gitlinks",
                "import_manifests",
                "prime_rl_commit",
                "prime_rl_git_tree",
                "project_root",
                "runtime",
            }
            or source.get("project_root") != str(PROJECT_ROOT)
            or not isinstance(source.get("prime_rl_commit"), str)
            or re.fullmatch(r"[0-9a-f]{40}", source["prime_rl_commit"]) is None
            or not isinstance(source.get("prime_rl_git_tree"), str)
            or re.fullmatch(r"[0-9a-f]{40}", source["prime_rl_git_tree"]) is None
            or not isinstance(source.get("gitlinks"), dict)
            or set(source["gitlinks"]) != {"pydantic_config", "renderers", "verifiers"}
            or any(
                not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{40}", item) is None
                for item in source["gitlinks"].values()
            )
            or not isinstance(source.get("import_manifests"), dict)
            or set(source["import_manifests"])
            != {"prime_rl", "pydantic_config", "renderers", "verifiers"}
            or any(
                not isinstance(item, str) or SHA256_RE.fullmatch(item) is None
                for item in source["import_manifests"].values()
            )
            or not isinstance(source.get("artifacts"), dict)
            or set(source["artifacts"]) != EXPECTED_SOURCE_ARTIFACT_LABELS
            or not isinstance(source.get("runtime"), dict)
        ):
            raise ProductionCertificateError("audit_authorization_source_invalid")
        for label, record in source["artifacts"].items():
            if not isinstance(label, str) or not label:
                raise ProductionCertificateError("audit_authorization_source_invalid")
            _authorization_artifact(record, label=f"source_{label}")
        runtime = source["runtime"]
        if (
            set(runtime)
            != {
                "isolation",
                "python",
                "site_packages",
                "stdlib",
                "submission",
                "tools",
            }
            or runtime.get("isolation")
            != {
                "dont_write_bytecode": True,
                "isolated": True,
                "no_site": True,
                "pycache_prefix": "fresh_empty_mode_0500",
                "safe_path": True,
            }
            or runtime.get("submission")
            != {
                "environment": "env_i_exact_allowlist",
                "sbatch_export": "NONE",
            }
            or not isinstance(runtime.get("tools"), dict)
            or set(runtime["tools"]) != set(RUNTIME_TOOL_PATHS)
        ):
            raise ProductionCertificateError("audit_authorization_runtime_invalid")
        _authorization_artifact(runtime.get("python"), label="runtime_python")
        for label, expected_path in RUNTIME_TOOL_PATHS.items():
            record = _authorization_artifact(
                runtime["tools"][label], label=f"runtime_{label}"
            )
            if record["path"] != expected_path:
                raise ProductionCertificateError("audit_authorization_runtime_invalid")
        for label in ("stdlib", "site_packages"):
            tree = runtime.get(label)
            if (
                not isinstance(tree, dict)
                or set(tree) != {"path", "tree_sha256"}
                or not isinstance(tree.get("path"), str)
                or not _normalized_absolute(Path(tree["path"]))
                or not isinstance(tree.get("tree_sha256"), str)
                or SHA256_RE.fullmatch(tree["tree_sha256"]) is None
            ):
                raise ProductionCertificateError("audit_authorization_runtime_invalid")
        scheduler = _validate_authorized_scheduler(value.get("scheduler"))
        if audit_submission["cluster"] != scheduler["cluster"]:
            raise ProductionCertificateError("audit_authorization_submission_invalid")
        value["scheduler"] = scheduler
        snapshot.revalidate()
        return value, {"path": str(path), "sha256": snapshot.sha256}, snapshot
    except BaseException:
        snapshot.close()
        raise


def _require_production_contract(identity: dict[str, Any]) -> None:
    contract = identity.get("contract")
    context = contract.get("context_tokens") if isinstance(contract, dict) else None
    thinking = contract.get("thinking") if isinstance(contract, dict) else None
    denylist = (
        contract.get("outbound_body_denylist") if isinstance(contract, dict) else None
    )
    sampling_max_tokens = (
        contract.get("sampling_max_tokens") if isinstance(contract, dict) else None
    )
    if (
        identity.get("role") != "mobius"
        or not isinstance(contract, dict)
        or contract.get("model") != "Kimi-K3"
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort") != "max"
        or contract.get("capture_model_io") is not True
        or contract.get("retain_traces") is not False
        or isinstance(sampling_max_tokens, bool)
        or not isinstance(sampling_max_tokens, int)
        or not 0 < sampling_max_tokens <= MAX_SEQUENCE_TOKENS
        or not isinstance(context, dict)
        or set(context) != {"max_input_tokens", "max_output_tokens", "max_total_tokens"}
        or any(value != MAX_SEQUENCE_TOKENS for value in context.values())
        or _canonical_json(thinking)
        != _canonical_json({"enable_thinking": True, "preserve_thinking": True})
        or not isinstance(denylist, list)
        or len(denylist) != len(EXPECTED_DENYLIST)
        or set(denylist) != EXPECTED_DENYLIST
    ):
        raise ProductionCertificateError("eval_identity_contract_invalid")


def _require_execution(
    identity: dict[str, Any],
) -> tuple[dict[str, int], dict[str, Any]]:
    execution = identity.get("execution")
    vmvm_environment = (
        execution.get("vmvm_environment") if isinstance(execution, dict) else None
    )
    fields = {
        "rollout_concurrency": execution.get("rollout_concurrency")
        if isinstance(execution, dict)
        else None,
        "multiplex": execution.get("multiplex")
        if isinstance(execution, dict)
        else None,
        "http_max_connections": execution.get("http_max_connections")
        if isinstance(execution, dict)
        else None,
        "http_max_keepalive_connections": (
            execution.get("http_max_keepalive_connections")
            if isinstance(execution, dict)
            else None
        ),
        "lease_start_concurrency": (
            vmvm_environment.get("lease_start_concurrency")
            if isinstance(vmvm_environment, dict)
            else None
        ),
    }
    runtime = execution.get("runtime") if isinstance(execution, dict) else None
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in fields.values()
        )
        or any(
            fields[key] != EXPECTED_MOBIUS_STEADY_STATE_CONCURRENCY
            for key in (
                "rollout_concurrency",
                "multiplex",
                "http_max_connections",
                "http_max_keepalive_connections",
            )
        )
        or fields["lease_start_concurrency"] != EXPECTED_MOBIUS_LEASE_START_CONCURRENCY
        or not isinstance(runtime, dict)
        or runtime.get("type") != "vmvm"
    ):
        raise ProductionCertificateError("eval_identity_execution_invalid")
    assert isinstance(vmvm_environment, dict)
    return fields, vmvm_environment


def _qualified_rollout_contract(
    identity: Mapping[str, Any],
    launch_certificate: Mapping[str, Any],
    execution_fields: Mapping[str, int],
) -> dict[str, Any]:
    """Project the reviewed launch contract into aggregate trace evidence."""

    production = launch_certificate.get("production")
    launch_contract = (
        production.get("contract") if isinstance(production, dict) else None
    )
    identity_contract = identity.get("contract")
    source = identity.get("source")
    if (
        not isinstance(launch_contract, dict)
        or not isinstance(identity_contract, dict)
        or not isinstance(source, dict)
        or launch_contract.get("model") != "Kimi-K3"
        or launch_contract.get("num_tasks") != EXPECTED_TASKS
        or launch_contract.get("num_rollouts") != 1
        or launch_contract.get("pass_at_1") is not True
        or launch_contract.get("reasoning_effort") != "max"
        or launch_contract.get("thinking")
        != {"enable_thinking": True, "preserve_thinking": True}
        or launch_contract.get("context_tokens")
        != {
            "max_input_tokens": MAX_SEQUENCE_TOKENS,
            "max_output_tokens": MAX_SEQUENCE_TOKENS,
            "max_total_tokens": MAX_SEQUENCE_TOKENS,
        }
        or launch_contract.get("capture_model_io") is not True
        or launch_contract.get("retain_traces") is not False
        or launch_contract.get("vmvm") is not True
        or launch_contract.get("timeouts") != EXPECTED_FULL_TIMEOUTS
        or launch_contract.get("execution")
        != {
            key: execution_fields[key]
            for key in (
                "http_max_connections",
                "http_max_keepalive_connections",
                "multiplex",
                "rollout_concurrency",
            )
        }
        or any(
            launch_contract.get(key) != identity_contract.get(key)
            for key in (
                "capture_model_io",
                "context_tokens",
                "model",
                "num_rollouts",
                "pass_at_1",
                "reasoning_effort",
                "retain_traces",
                "sampling_max_tokens",
                "thinking",
            )
        )
        or not isinstance(source.get("vmvm_tb_v2_sha256"), str)
        or SHA256_RE.fullmatch(source["vmvm_tb_v2_sha256"]) is None
    ):
        raise ProductionCertificateError("qualified_rollout_contract_invalid")
    return {
        "capture_model_io": True,
        "context_tokens": dict(launch_contract["context_tokens"]),
        "execution": dict(execution_fields),
        "model": "Kimi-K3",
        "num_rollouts": 1,
        "num_tasks": EXPECTED_TASKS,
        "pass_at_1": True,
        "reasoning_effort": "max",
        "retain_traces": False,
        "runtime_provider": "vmvm",
        "sampling_max_tokens": launch_contract["sampling_max_tokens"],
        "thinking": dict(launch_contract["thinking"]),
        "timeouts": dict(launch_contract["timeouts"]),
        "vmvm_source_sha256": source["vmvm_tb_v2_sha256"],
    }


def _require_auditor_source(identity: dict[str, Any]) -> dict[str, dict[str, str]]:
    source = identity.get("source")
    project_root = source.get("project_root") if isinstance(source, dict) else None
    if not isinstance(project_root, str):
        raise ProductionCertificateError("auditor_source_mismatch")
    try:
        if Path(project_root).resolve(strict=True) != PROJECT_ROOT:
            raise ProductionCertificateError("auditor_source_mismatch")
    except (OSError, RuntimeError) as error:
        raise ProductionCertificateError("auditor_source_mismatch") from error
    workflow = "user/tianhaowu/terminal_bench_vmvm"
    return {
        "production_certificate": _source_path_artifact(
            f"{workflow}/certify_trace_production.py",
            label="production_certificate_source",
        ),
        "production_audit_wrapper": _source_path_artifact(
            f"{workflow}/run_trace_production_audit.sbatch",
            label="production_audit_wrapper",
        ),
        "production_audit_submitter": _source_path_artifact(
            f"{workflow}/submit_trace_production_audit.sh",
            label="production_audit_submitter",
        ),
        "production_audit_submission_controller": _source_path_artifact(
            f"{workflow}/trace_production_submit_control.py",
            label="production_audit_submission_controller",
        ),
        "production_audit_bootstrap": _source_path_artifact(
            f"{workflow}/trace_production_bootstrap.py",
            label="production_audit_bootstrap",
        ),
        "smoke_certificate_helpers": _module_artifact(
            certify_trace_smoke_module,
            f"{workflow}/certify_trace_smoke.py",
            label="smoke_certificate_helpers",
        ),
        "trace_auditor": _module_artifact(
            audit_traces_module,
            f"{workflow}/audit_traces.py",
            label="trace_auditor",
        ),
        "deployment_endpoint_validator": _module_artifact(
            deployment_endpoint_module,
            f"{workflow}/deployment_endpoint.py",
            label="deployment_endpoint_validator",
        ),
        "deployment_proxy_policy_validator": _module_artifact(
            deployment_proxy_policy_module,
            f"{workflow}/deployment_proxy_policy.py",
            label="deployment_proxy_policy_validator",
        ),
        "eval_run_identity_validator": _module_artifact(
            eval_run_identity_module,
            f"{workflow}/eval_run_identity.py",
            label="eval_run_identity_validator",
        ),
        "guard_success_validator": _module_artifact(
            guard_success_receipt_module,
            f"{workflow}/guard_success_receipt.py",
            label="guard_success_validator",
        ),
        "route_generation_validator": _module_artifact(
            inference_route_generation_module,
            f"{workflow}/inference_route_generation.py",
            label="route_generation_validator",
        ),
        "launch_certificate_validator": _module_artifact(
            launch_certificate_module,
            f"{workflow}/mobius_launch_certificate.py",
            label="launch_certificate_validator",
        ),
        "trace_concurrency_validator": _module_artifact(
            trace_concurrency_module,
            f"{workflow}/trace_concurrency.py",
            label="trace_concurrency_validator",
        ),
        "concurrency_telemetry_validator": _module_artifact(
            concurrency_telemetry_module,
            "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/concurrency_telemetry.py",
            label="concurrency_telemetry_validator",
        ),
        "vmvm_backend": _source_path_artifact(
            "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py",
            label="vmvm_backend",
        ),
        "terminal_bench_taskset": _source_path_artifact(
            f"{workflow}/terminal_bench_vmvm/taskset.py",
            label="terminal_bench_taskset",
        ),
        "strict_sft_exporter": _source_path_artifact(
            f"{workflow}/export_sft.py",
            label="strict_sft_exporter",
        ),
        "sft_preflight_cli": _source_path_artifact(
            f"{workflow}/preflight_sft.py",
            label="sft_preflight_cli",
        ),
        "sft_target_rendering_contract": _source_path_artifact(
            f"{workflow}/configs/sft/target-rendering-contract.json",
            label="sft_target_rendering_contract",
        ),
        "sft_export_preflight": _source_path_artifact(
            "src/prime_rl/trainer/sft/export_preflight.py",
            label="sft_export_preflight",
        ),
        "sft_training_entrypoint": _source_path_artifact(
            "src/prime_rl/trainer/sft/train.py",
            label="sft_training_entrypoint",
        ),
    }


def _entry_absent(anchor: DirectoryAnchor, name: str) -> bool:
    try:
        os.stat(name, dir_fd=anchor.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError as error:
        raise ProductionCertificateError("checkpoint_path_invalid") from error
    return False


def _rename_noreplace(directory_fd: int, source: str, destination: str) -> None:
    """Atomically commit one directory entry without an overwrite window."""

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
    except (AttributeError, OSError) as error:
        raise ProductionCertificateError(
            "checkpoint_publication_unsupported"
        ) from error
    if (
        renameat2(
            directory_fd, os.fsencode(source), directory_fd, os.fsencode(destination), 1
        )
        == 0
    ):
        return
    observed_errno = ctypes.get_errno()
    if observed_errno == errno.EEXIST:
        raise FileExistsError(destination)
    raise OSError(observed_errno, os.strerror(observed_errno), destination)


def _publish_anchored_entry(
    anchor: DirectoryAnchor,
    name: str,
    payload: Mapping[str, Any],
    *,
    authoritative: bool,
) -> tuple[str, bytes]:
    if name not in {PAYLOAD_NAME, CHECKPOINT_NAME}:
        raise ProductionCertificateError("checkpoint_path_invalid")
    anchor.revalidate()
    if not _entry_absent(anchor, name):
        raise ProductionCertificateError("checkpoint_already_exists")
    encoded = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    temporary = f".{name}.{os.getpid()}.{os.urandom(16).hex()}.tmp"
    descriptor = -1
    committed = False
    previous_mask: set[signal.Signals] | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=anchor.descriptor,
        )
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise ProductionCertificateError("checkpoint_publication_failed")
            offset += written
        os.fsync(descriptor)
        if _sha256_descriptor(descriptor, len(encoded)) != _sha256_bytes(encoded):
            raise ProductionCertificateError("checkpoint_verification_failed")
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
        anchor.revalidate()
        # Persist the complete temporary entry before the one-way commit.  No
        # fallible validation may occur between renameat2 and `committed=True`.
        os.fsync(anchor.descriptor)
        blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        _rename_noreplace(anchor.descriptor, temporary, name)
        committed = True
        temporary = ""
        try:
            os.fsync(anchor.descriptor)
        except OSError:
            # renameat2 is the irreversible commit point.  A post-rename fsync
            # failure can lose the entry after a host crash, but cannot justify
            # deleting or reporting an ordinary failure while a valid pass
            # marker is already visible.
            pass
        return _sha256_bytes(encoded), encoded
    except FileExistsError as error:
        raise ProductionCertificateError("checkpoint_already_exists") from error
    except ProductionCertificateError:
        raise
    except OSError as error:
        if committed:
            raise ProductionCertificateError("checkpoint_commit_ambiguous") from error
        raise ProductionCertificateError("checkpoint_publication_failed") from error
    finally:
        if previous_mask is not None:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            except OSError:
                if not committed:
                    raise
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                if not committed:
                    raise
        if temporary and not committed:
            try:
                os.unlink(temporary, dir_fd=anchor.descriptor)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        # Never remove a destination after renameat2 has committed it.


def _publish_certificate(
    anchor: DirectoryAnchor,
    certificate: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    if not _entry_absent(anchor, PAYLOAD_NAME) or not _entry_absent(
        anchor, CHECKPOINT_NAME
    ):
        raise ProductionCertificateError("checkpoint_already_exists")
    payload_sha256, _payload_bytes = _publish_anchored_entry(
        anchor,
        PAYLOAD_NAME,
        certificate,
        authoritative=False,
    )
    marker_body = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "terminal_bench_vmvm_production_trace_completion_v1",
        "state": "passed",
        "ok": True,
        "certificate": {
            "path": str(anchor.path / PAYLOAD_NAME),
            "sha256": payload_sha256,
        },
        "audit_authorization_sha256": authorization["authorization_sha256"],
        "eval_run_identity_sha256": authorization["run"]["eval_run_identity_sha256"],
        "evaluation_job_id": authorization["scheduler"]["job_id"],
        "automatic_export_or_promotion": False,
    }
    marker = {
        **marker_body,
        "production_trace_checkpoint_sha256": _sha256_bytes(
            _canonical_json(marker_body)
        ),
    }
    _publish_anchored_entry(
        anchor,
        CHECKPOINT_NAME,
        marker,
        authoritative=True,
    )
    return marker


def _validate_launch_chain(
    identity: dict[str, Any],
    *,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    expected_production_config: Path,
    expected_production_config_sha256: str,
    expected_launch_certificate: Path,
    expected_launch_certificate_sha256: str,
    expected_oracle_receipt: Path,
    expected_oracle_receipt_sha256: str,
    launch_validator: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    task_record = _pinned_artifact(
        expected_task_file,
        expected_task_file_sha256,
        label="expected_task_file",
    )
    config_record = _pinned_artifact(
        expected_production_config,
        expected_production_config_sha256,
        label="expected_production_config",
    )
    launch_record = _pinned_artifact(
        expected_launch_certificate,
        expected_launch_certificate_sha256,
        label="expected_launch_certificate",
    )
    oracle_record = _pinned_artifact(
        expected_oracle_receipt,
        expected_oracle_receipt_sha256,
        label="expected_oracle_receipt",
    )
    deployment = identity.get("deployment")
    inputs = identity.get("inputs")
    config = identity.get("config")
    dataset = identity.get("dataset")
    execution = identity.get("execution")
    vmvm_environment = (
        execution.get("vmvm_environment") if isinstance(execution, dict) else None
    )
    if not all(
        isinstance(value, dict)
        for value in (deployment, inputs, config, dataset, vmvm_environment)
    ):
        raise ProductionCertificateError("eval_identity_launch_binding_invalid")
    assert isinstance(deployment, dict)
    assert isinstance(inputs, dict)
    assert isinstance(config, dict)
    assert isinstance(dataset, dict)
    assert isinstance(vmvm_environment, dict)
    promotion_record = _identity_artifact(
        identity, "deployment", "promotion_certificate"
    )
    identity_task = _identity_artifact(identity, "inputs", "task_file")
    identity_config = _identity_artifact(identity, "config", "source")
    image_record = _identity_artifact(identity, "inputs", "image_manifest")
    spec_record = _identity_artifact(identity, "deployment", "spec")
    readiness_record = _identity_artifact(
        identity, "deployment", "readiness_checkpoint"
    )
    capacity_record = _identity_artifact(identity, "deployment", "smoke_checkpoint")
    endpoint = deployment.get("endpoint")
    try:
        endpoint = validate_endpoint_binding(endpoint)
    except EndpointBindingError as error:
        raise ProductionCertificateError(
            "eval_identity_launch_binding_invalid"
        ) from error
    if (
        promotion_record != launch_record
        or identity_task != task_record
        or identity_config != config_record
        or inputs.get("task_file", {}).get("count") != EXPECTED_TASKS
        or dataset.get("kind") != "git_revision"
    ):
        raise ProductionCertificateError("eval_identity_launch_binding_invalid")
    try:
        launch_certificate = launch_validator(
            Path(launch_record["path"]),
            launch_record["sha256"],
            production_config=Path(config_record["path"]),
            approved_manifest=Path(task_record["path"]),
            approved_manifest_sha256=task_record["sha256"],
            deployment_id=deployment["id"],
            deployment_spec=Path(spec_record["path"]),
            deployment_spec_sha256=spec_record["sha256"],
            deployment_proxy_info=Path(endpoint["proxy_info"]["path"]),
            deployment_proxy_info_sha256=endpoint["proxy_info"]["sha256"],
            readiness_checkpoint=Path(readiness_record["path"]),
            readiness_checkpoint_sha256=readiness_record["sha256"],
            capacity_smoke_checkpoint=Path(capacity_record["path"]),
            capacity_smoke_checkpoint_sha256=capacity_record["sha256"],
            requested_lease_start_concurrency=vmvm_environment[
                "lease_start_concurrency"
            ],
        )
    except (KeyError, OSError, TypeError, ValueError, LaunchCertificateError) as error:
        raise ProductionCertificateError("launch_certificate_invalid") from error
    gates = launch_certificate.get("gates")
    oracle_gate = gates.get("oracle_promotion") if isinstance(gates, dict) else None
    production = launch_certificate.get("production")
    launch_manifest = (
        production.get("approved_manifest") if isinstance(production, dict) else None
    )
    launch_config = production.get("config") if isinstance(production, dict) else None
    if (
        not isinstance(oracle_gate, dict)
        or oracle_gate.get("artifact") != oracle_record
        or oracle_gate.get("dataset_revision") != dataset.get("revision")
        or oracle_gate.get("image_manifest_sha256") != image_record["sha256"]
        or launch_config != config_record
        or launch_manifest != {**task_record, "count": EXPECTED_TASKS}
    ):
        raise ProductionCertificateError("launch_certificate_binding_mismatch")
    return launch_certificate, {
        "approved_task_file": task_record,
        "approved_production_config": config_record,
        "launch_certificate": launch_record,
        "oracle_promotion": oracle_record,
    }


def certify_production(
    run_dir: Path,
    *,
    audit_authorization: Path,
    audit_authorization_sha256: str,
    slurm_cluster: str,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    expected_production_config: Path,
    expected_production_config_sha256: str,
    expected_launch_certificate: Path,
    expected_launch_certificate_sha256: str,
    expected_oracle_receipt: Path,
    expected_oracle_receipt_sha256: str,
    expected_traces: int = EXPECTED_TASKS,
    identity_loader: Callable[..., dict[str, Any]] = load_eval_run_identity,
    launch_validator: Callable[
        ..., dict[str, Any]
    ] = validate_launch_certificate_for_run,
    terminal_validator: Callable[[str, str], dict[str, Any]] = require_slurm_terminal,
    runtime_revalidator: Callable[[], Mapping[str, Any]] | None = None,
    submission_attestation: Mapping[str, Any] | None = None,
    submission_revalidator: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit a terminal Mobius run and publish its immutable trace certificate."""

    if isinstance(expected_traces, bool) or expected_traces != EXPECTED_TASKS:
        raise ProductionCertificateError("expected_traces_invalid")
    if SLURM_CLUSTER_RE.fullmatch(slurm_cluster) is None:
        raise ProductionCertificateError("slurm_cluster_invalid")
    if runtime_revalidator is None:
        raise ProductionCertificateError("verified_runtime_required")
    if submission_attestation is None or submission_revalidator is None:
        raise ProductionCertificateError("audit_submission_attestation_required")
    authorization: dict[str, Any] | None = None
    authorization_record: dict[str, str] | None = None
    authorization_snapshot: StableFile | None = None
    anchor: DirectoryAnchor | None = None
    identity_snapshot: StableFile | None = None
    task_snapshot: StableFile | None = None
    results_snapshot: ResultsSnapshot | None = None
    lock: BinaryIO | None = None
    committed = False
    try:
        authorization, authorization_record, authorization_snapshot = (
            _load_audit_authorization(
                audit_authorization,
                audit_authorization_sha256,
            )
        )
        admitted_submission = _validate_submission_attestation(
            submission_attestation,
            authorization,
        )
        try:
            run_dir = run_dir.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ProductionCertificateError("run_dir_invalid") from error
        if authorization["run"]["path"] != str(run_dir):
            raise ProductionCertificateError("audit_authorization_run_mismatch")
        anchor = _open_directory_anchor(run_dir)
        if not _entry_absent(anchor, CHECKPOINT_NAME) or not _entry_absent(
            anchor, PAYLOAD_NAME
        ):
            raise ProductionCertificateError("checkpoint_already_exists")
        lock = _acquire_writer_lock(run_dir, anchor)
        identity_path = run_dir / "eval_run_identity.json"
        identity_snapshot = _open_stable_file(
            identity_path,
            label="eval_run_identity",
            expected_sha256=authorization["run"]["eval_run_identity_file_sha256"],
            anchor=anchor,
        )
        identity_file_sha256 = identity_snapshot.sha256
        try:
            envelope = identity_loader(
                Path(f"/proc/self/fd/{identity_snapshot.descriptor}"),
                verify_references=True,
            )
        except (OSError, ValueError) as error:
            raise ProductionCertificateError("eval_run_identity_invalid") from error
        identity_snapshot.revalidate()
        identity = envelope.get("identity")
        identity_sha256 = envelope.get("eval_run_identity_sha256")
        if (
            not isinstance(identity, dict)
            or not isinstance(identity_sha256, str)
            or SHA256_RE.fullmatch(identity_sha256) is None
        ):
            raise ProductionCertificateError("eval_run_identity_invalid")
        if identity_sha256 != authorization["run"]["eval_run_identity_sha256"]:
            raise ProductionCertificateError("audit_authorization_run_mismatch")
        _require_production_contract(identity)
        execution_fields, _vmvm_environment = _require_execution(identity)
        auditor_sources = _require_auditor_source(identity)
        authorized_source = authorization["source"]
        identity_source = identity.get("source")
        if (
            not isinstance(identity_source, dict)
            or authorized_source["prime_rl_commit"]
            != identity_source.get("prime_rl_commit")
            or authorized_source["gitlinks"].get("verifiers")
            != identity_source.get("verifiers_commit")
            or authorized_source["gitlinks"].get("renderers")
            != identity_source.get("renderers_commit")
            or authorized_source["artifacts"] != auditor_sources
        ):
            raise ProductionCertificateError("audit_authorization_source_mismatch")

        task_snapshot = _open_stable_file(
            expected_task_file,
            label="expected_task_file",
            expected_sha256=expected_task_file_sha256,
        )
        task_bytes = task_snapshot.read()
        expected_slugs = _expected_slugs_from_bytes(task_bytes)
        if len(expected_slugs) != EXPECTED_TASKS:
            raise ProductionCertificateError("expected_task_file_invalid")
        identity_task = _identity_artifact(identity, "inputs", "task_file")
        expected_task_record = {
            "path": str(task_snapshot.path),
            "sha256": expected_task_file_sha256,
        }
        if (
            identity_task != expected_task_record
            or identity.get("inputs", {}).get("task_file", {}).get("count")
            != EXPECTED_TASKS
        ):
            raise ProductionCertificateError("eval_identity_task_mismatch")
        authorized_inputs = authorization["inputs"]
        if (
            authorized_inputs["task_file"]
            != {**expected_task_record, "count": EXPECTED_TASKS}
            or authorized_inputs["production_config"]
            != {
                "path": str(expected_production_config),
                "sha256": expected_production_config_sha256,
            }
            or authorized_inputs["launch_certificate"]
            != {
                "path": str(expected_launch_certificate),
                "sha256": expected_launch_certificate_sha256,
            }
            or authorized_inputs["oracle_receipt"]
            != {
                "path": str(expected_oracle_receipt),
                "sha256": expected_oracle_receipt_sha256,
            }
        ):
            raise ProductionCertificateError("audit_authorization_inputs_mismatch")

        results_path = run_dir / "results.jsonl"
        results_snapshot = _snapshot_results(results_path, anchor=anchor)
        before_results_sha256 = results_snapshot.source.sha256
        try:
            summary, failed = _summarize_traces(
                _iter_traces(results_snapshot.path),
                expected_slugs=expected_slugs,
                expected_count=EXPECTED_TASKS,
                rollouts_per_task=1,
                require_reasoning=True,
                require_token_data=False,
                require_logprobs=False,
                require_model_io=True,
                aggregate_only=True,
                model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
                require_request_graph_match=True,
                require_exact_provider_json=True,
                require_clean_stop=True,
                max_sequence_tokens=MAX_SEQUENCE_TOKENS,
            )
        except (OSError, ValueError) as error:
            raise ProductionCertificateError("trace_audit_invalid") from error
        if (
            failed
            or summary.get("traces") != EXPECTED_TASKS
            or summary.get("tasks") != EXPECTED_TASKS
            or summary.get("model_io_turns", 0) < EXPECTED_TASKS
            or summary.get("sampled_tokens", 0) < 1
            or summary.get("trace_failures") != 0
            or summary.get("global_problems") != []
            or summary.get("problem_counts") != {}
        ):
            raise ProductionCertificateError("trace_audit_failed")
        try:
            rollout_observation = measure_peak_active_rollouts(
                _iter_traces(results_snapshot.path)
            )
        except (OSError, ValueError, TraceConcurrencyError) as error:
            raise ProductionCertificateError("trace_concurrency_invalid") from error
        if rollout_observation["observed_rollouts"] != EXPECTED_TASKS:
            raise ProductionCertificateError("trace_concurrency_invalid")
        results_snapshot.revalidate()
        after_audit_results_sha256 = results_snapshot.source.sha256

        deployment = identity.get("deployment")
        if not isinstance(deployment, dict):
            raise ProductionCertificateError("eval_identity_deployment_invalid")
        endpoint = _validated_endpoint(identity)
        deployment_id = deployment.get("id")
        spec = deployment.get("spec")
        try:
            serving_route_generation = validate_route_generation(
                deployment.get("serving_route_generation")
            )
            proxy_policy = validate_proxy_policy_binding(deployment.get("proxy_policy"))
        except (RouteGenerationError, DeploymentProxyPolicyError) as error:
            raise ProductionCertificateError(
                "eval_identity_deployment_invalid"
            ) from error
        if (
            not isinstance(deployment_id, str)
            or not deployment_id
            or not isinstance(spec, dict)
            or SHA256_RE.fullmatch(str(spec.get("sha256", ""))) is None
        ):
            raise ProductionCertificateError("eval_identity_deployment_invalid")
        try:
            revalidate_deployment_proxy_policy(
                Path(spec["path"]),
                expected_spec_sha256=spec["sha256"],
                expected_binding=proxy_policy,
            )
        except DeploymentProxyPolicyError as error:
            raise ProductionCertificateError(
                "eval_identity_proxy_policy_changed"
            ) from error

        readiness_record = _identity_artifact(
            identity, "deployment", "readiness_checkpoint"
        )
        readiness_snapshot = _open_stable_file(
            Path(readiness_record["path"]),
            label="readiness_checkpoint",
            expected_sha256=readiness_record["sha256"],
        )
        try:
            readiness_payload = _strict_json_object(
                readiness_snapshot.read(),
                label="readiness_checkpoint",
            )
        finally:
            readiness_snapshot.close()
        try:
            readiness_endpoint = validate_endpoint_binding(
                readiness_payload.get("endpoint")
            )
            readiness_generation = validate_readiness_route_generation(
                readiness_payload,
                deployment_id=deployment_id,
                deployment_spec_sha256=spec["sha256"],
            )
            readiness_proxy_policy = validate_proxy_policy_binding(
                readiness_payload.get("proxy_policy")
            )
        except (
            EndpointBindingError,
            RouteGenerationError,
            DeploymentProxyPolicyError,
        ) as error:
            raise ProductionCertificateError("readiness_binding_invalid") from error
        if (
            readiness_endpoint != endpoint
            or readiness_generation != serving_route_generation
            or readiness_proxy_policy != proxy_policy
        ):
            raise ProductionCertificateError("readiness_binding_mismatch")

        guard_receipt_path = run_dir / "route_guard_success.json"
        try:
            if guard_receipt_path.resolve(strict=True) != guard_receipt_path:
                raise GuardReceiptError("guard_receipt_path_mismatch")
            guard_receipt = load_guard_success_receipt(guard_receipt_path)
            guard_artifacts = validate_guard_success_linkage(
                guard_receipt,
                run_dir=run_dir,
                eval_run_identity_sha256=identity_sha256,
                eval_run_role="mobius",
                eval_run_identity_file_sha256=identity_file_sha256,
                results_sha256=before_results_sha256,
                deployment_id=deployment_id,
                deployment_spec_sha256=spec["sha256"],
                readiness_checkpoint=readiness_record,
                endpoint=endpoint,
                serving_route_generation=serving_route_generation,
                proxy_policy=proxy_policy,
                require_concurrency_telemetry=True,
            )
            invocation, invocation_artifact = validate_eval_invocations(
                Path(guard_artifacts["eval_invocations"]["path"]),
                eval_run_identity_sha256=identity_sha256,
                eval_run_role="mobius",
            )
            if invocation_artifact != guard_artifacts["eval_invocations"]:
                raise GuardReceiptError("eval_invocations_changed")
            if (
                authorization["scheduler"]["cluster"] != slurm_cluster
                or authorization["scheduler"]["job_id"] != invocation["slurm_job_id"]
            ):
                raise GuardReceiptError("audit_authorization_job_mismatch")
            provenance_path = run_dir / "provenance.txt"
            if (
                _provenance_job_id(provenance_path, anchor=anchor)
                != invocation["slurm_job_id"]
            ):
                raise GuardReceiptError("provenance_job_identity_mismatch")
            telemetry, telemetry_artifact = load_concurrency_telemetry_artifact(
                run_dir / "concurrency_telemetry.json",
                eval_run_identity_sha256=identity_sha256,
                eval_run_role="mobius",
                slurm_job_id=invocation["slurm_job_id"],
            )
            if guard_artifacts.get("concurrency_telemetry") != telemetry_artifact:
                raise GuardReceiptError("concurrency_telemetry_changed")
        except (OSError, GuardReceiptError, ConcurrencyTelemetryError) as error:
            raise ProductionCertificateError("terminal_guard_invalid") from error
        observations = telemetry["observations"]
        if (
            rollout_observation["peak_active_rollouts_lower_bound"]
            < EXPECTED_MOBIUS_STEADY_STATE_CONCURRENCY
            or rollout_observation["peak_active_rollouts_lower_bound"]
            > execution_fields["rollout_concurrency"]
            or observations["peak_active_vmvm_runtimes"]
            < EXPECTED_MOBIUS_STEADY_STATE_CONCURRENCY
            or observations["peak_active_vmvm_runtimes"]
            > execution_fields["rollout_concurrency"]
            or observations["peak_concurrent_lease_startups"]
            < EXPECTED_MOBIUS_LEASE_START_CONCURRENCY
            or observations["peak_concurrent_lease_startups"]
            > execution_fields["lease_start_concurrency"]
            or observations["vmvm_runtime_ready"] < EXPECTED_TASKS
        ):
            raise ProductionCertificateError("observed_concurrency_below_required")

        launch_certificate, external_artifacts = _validate_launch_chain(
            identity,
            expected_task_file=expected_task_file,
            expected_task_file_sha256=expected_task_file_sha256,
            expected_production_config=expected_production_config,
            expected_production_config_sha256=expected_production_config_sha256,
            expected_launch_certificate=expected_launch_certificate,
            expected_launch_certificate_sha256=expected_launch_certificate_sha256,
            expected_oracle_receipt=expected_oracle_receipt,
            expected_oracle_receipt_sha256=expected_oracle_receipt_sha256,
            launch_validator=launch_validator,
        )
        qualified_rollout_contract = _qualified_rollout_contract(
            identity,
            launch_certificate,
            execution_fields,
        )
        if (
            authorized_inputs["task_file"]
            != {**external_artifacts["approved_task_file"], "count": EXPECTED_TASKS}
            or authorized_inputs["production_config"]
            != external_artifacts["approved_production_config"]
            or authorized_inputs["launch_certificate"]
            != external_artifacts["launch_certificate"]
            or authorized_inputs["oracle_receipt"]
            != external_artifacts["oracle_promotion"]
        ):
            raise ProductionCertificateError("audit_authorization_inputs_mismatch")

        inputs = identity.get("inputs")
        if not isinstance(inputs, dict) or inputs.get("image_manifest") is None:
            raise ProductionCertificateError("eval_identity_inputs_invalid")
        artifacts = {
            "audit_authorization": authorization_record,
            "audit_submission_intent": admitted_submission["intent"],
            "audit_submission_held_authorization": admitted_submission[
                "held_authorization"
            ],
            "audit_submission_receipt": admitted_submission["submission_receipt"],
            "audit_submission_activation_permit": admitted_submission[
                "activation_permit"
            ],
            "results": {"path": str(results_path), "sha256": before_results_sha256},
            "eval_run_identity": {
                "path": str(identity_path),
                "sha256": identity_file_sha256,
            },
            "eval_invocations": guard_artifacts["eval_invocations"],
            "route_guard_success": _observed_artifact(
                guard_receipt_path,
                label="route_guard_success",
            ),
            "concurrency_telemetry": telemetry_artifact,
            "config_source": _identity_artifact(identity, "config", "source"),
            "config_resolved": _identity_artifact(identity, "config", "resolved"),
            "inputs_manifest": _identity_artifact(identity, "inputs", "manifest"),
            "task_file": _identity_artifact(identity, "inputs", "task_file"),
            "image_manifest": _identity_artifact(identity, "inputs", "image_manifest"),
            "provenance": _observed_artifact(provenance_path, label="provenance"),
            "deployment_spec": _identity_artifact(identity, "deployment", "spec"),
            "readiness_checkpoint": readiness_record,
            "capacity_smoke_checkpoint": _identity_artifact(
                identity,
                "deployment",
                "smoke_checkpoint",
            ),
            "proxy_info": endpoint["proxy_info"],
            "proxy_litellm_config": proxy_policy["proxy_litellm_config"],
            **external_artifacts,
            **{f"source_{name}": record for name, record in auditor_sources.items()},
        }
        try:
            terminal_record = _validate_terminal_record(
                terminal_validator(invocation["slurm_job_id"], slurm_cluster),
                expected_job_id=invocation["slurm_job_id"],
                expected_cluster=slurm_cluster,
                authorized_record=authorization["scheduler"],
            )
        except ProductionCertificateError:
            raise
        except Exception as error:
            raise ProductionCertificateError(
                "evaluation_job_state_unavailable"
            ) from error

        try:
            final_envelope = identity_loader(
                Path(f"/proc/self/fd/{identity_snapshot.descriptor}"),
                verify_references=True,
            )
        except (OSError, ValueError) as error:
            raise ProductionCertificateError("eval_run_identity_changed") from error
        if final_envelope != envelope:
            raise ProductionCertificateError("eval_run_identity_changed")
        try:
            final_endpoint = _validated_endpoint(identity)
        except (OSError, ValueError) as error:
            raise ProductionCertificateError("deployment_endpoint_changed") from error
        if final_endpoint != endpoint:
            raise ProductionCertificateError("deployment_endpoint_changed")
        try:
            revalidate_deployment_proxy_policy(
                Path(spec["path"]),
                expected_spec_sha256=spec["sha256"],
                expected_binding=proxy_policy,
            )
        except (KeyError, OSError, DeploymentProxyPolicyError) as error:
            raise ProductionCertificateError(
                "eval_identity_proxy_policy_changed"
            ) from error
        final_launch_certificate, final_external_artifacts = _validate_launch_chain(
            identity,
            expected_task_file=expected_task_file,
            expected_task_file_sha256=expected_task_file_sha256,
            expected_production_config=expected_production_config,
            expected_production_config_sha256=expected_production_config_sha256,
            expected_launch_certificate=expected_launch_certificate,
            expected_launch_certificate_sha256=expected_launch_certificate_sha256,
            expected_oracle_receipt=expected_oracle_receipt,
            expected_oracle_receipt_sha256=expected_oracle_receipt_sha256,
            launch_validator=launch_validator,
        )
        if (
            final_launch_certificate != launch_certificate
            or final_external_artifacts != external_artifacts
        ):
            raise ProductionCertificateError("launch_certificate_changed")
        if (
            _qualified_rollout_contract(
                identity,
                final_launch_certificate,
                execution_fields,
            )
            != qualified_rollout_contract
        ):
            raise ProductionCertificateError("qualified_rollout_contract_changed")
        _revalidate_writer_lock(lock, run_dir, anchor)
        _rehash_artifacts(artifacts)
        identity_snapshot.revalidate()
        task_snapshot.revalidate()
        results_snapshot.revalidate()
        final_results_sha256 = results_snapshot.source.sha256
        sft_training_readiness = _sft_training_readiness_scope()
        _validate_sft_training_readiness_scope(sft_training_readiness)
        certificate_body = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": ARTIFACT_TYPE,
            "state": "audited",
            "ok": True,
            "authoritative": False,
            "eval_run_role": "mobius",
            "eval_run_identity_sha256": identity_sha256,
            "evaluation_job": terminal_record,
            "audit_authorization": authorization_record,
            "source": identity["source"],
            "deployment": {
                "id": deployment_id,
                "spec_sha256": spec["sha256"],
                "serving_route_generation": serving_route_generation,
                "proxy_policy": proxy_policy,
                "endpoint": endpoint,
            },
            "launch_chain": {
                "launch_certificate_sha256": launch_certificate[
                    "launch_certificate_sha256"
                ],
                "oracle_receipt_sha256": external_artifacts["oracle_promotion"][
                    "sha256"
                ],
            },
            "qualified_execution": execution_fields,
            "qualified_rollout_contract": qualified_rollout_contract,
            "observed_concurrency": {
                "active_rollout_signal": "completed_trace_lifecycle_timing_overlap",
                "lease_start_signal": "vacli_lease_start_semaphore_holders",
                "peak_active_rollouts_lower_bound": rollout_observation[
                    "peak_active_rollouts_lower_bound"
                ],
                "peak_active_vmvm_runtimes": observations["peak_active_vmvm_runtimes"],
                "peak_concurrent_lease_startups": observations[
                    "peak_concurrent_lease_startups"
                ],
            },
            "audit_policy": _expected_audit_policy(),
            "audit_window": {
                "results_sha256_before": before_results_sha256,
                "results_sha256_after_trace_audit": after_audit_results_sha256,
                "results_sha256_after": final_results_sha256,
            },
            "counts": {
                "traces": summary["traces"],
                "tasks": summary["tasks"],
                "sampled_tokens": summary["sampled_tokens"],
                "model_io_turns": summary["model_io_turns"],
                "provider_reported_zero_reasoning_tool_turns": summary[
                    "provider_reported_zero_reasoning_tool_turns"
                ],
                "provider_explicit_empty_reasoning_tool_turns": summary[
                    "provider_explicit_empty_reasoning_tool_turns"
                ],
                "trace_failures": summary["trace_failures"],
                "global_problems": len(summary["global_problems"]),
            },
            "artifacts": artifacts,
            "sft_training_readiness": sft_training_readiness,
            "automatic_export_or_promotion": False,
        }
        certificate = {
            **certificate_body,
            "production_trace_certificate_sha256": _sha256_bytes(
                _canonical_json(certificate_body)
            ),
        }
        # Recheck the complete checkout/gitlink/import/runtime closure only
        # after all certificate bytes have been derived.  The remaining
        # validations are descriptor-bound and publication is the next state
        # transition, keeping mutable source out of the execution-to-commit
        # gap.
        try:
            runtime_attestation = dict(runtime_revalidator())
        except ProductionCertificateError:
            raise
        except Exception as error:
            raise ProductionCertificateError("verified_runtime_changed") from error
        if runtime_attestation != authorized_source:
            raise ProductionCertificateError("verified_runtime_changed")
        try:
            final_submission_attestation = dict(submission_revalidator())
        except ProductionCertificateError:
            raise
        except Exception as error:
            raise ProductionCertificateError(
                "audit_submission_attestation_changed"
            ) from error
        if final_submission_attestation != admitted_submission:
            raise ProductionCertificateError("audit_submission_attestation_changed")
        _revalidate_writer_lock(lock, run_dir, anchor)
        authorization_snapshot.revalidate()
        identity_snapshot.revalidate()
        task_snapshot.revalidate()
        results_snapshot.revalidate()
        _rehash_artifacts(artifacts)
        anchor.revalidate()
        try:
            final_terminal_record = _validate_terminal_record(
                terminal_validator(invocation["slurm_job_id"], slurm_cluster),
                expected_job_id=invocation["slurm_job_id"],
                expected_cluster=slurm_cluster,
                authorized_record=authorization["scheduler"],
            )
        except ProductionCertificateError:
            raise
        except Exception as error:
            raise ProductionCertificateError(
                "evaluation_job_state_unavailable"
            ) from error
        if final_terminal_record != terminal_record:
            raise ProductionCertificateError("evaluation_job_identity_changed")
        # Only descriptor/metadata checks remain after the final two-view
        # scheduler proof. They close the terminal-query race without another
        # pathname parse or a second full results scan.
        _revalidate_writer_lock(lock, run_dir, anchor)
        authorization_snapshot.revalidate()
        identity_snapshot.revalidate()
        task_snapshot.revalidate()
        try:
            results_snapshot.source.revalidate()
        except ProductionCertificateError as error:
            raise ProductionCertificateError("results_changed_during_audit") from error
        anchor.revalidate()
        _publish_certificate(anchor, certificate, authorization=authorization)
        committed = True
        return certificate
    finally:
        resources = (
            results_snapshot,
            task_snapshot,
            identity_snapshot,
            lock,
            authorization_snapshot,
            anchor,
        )
        for resource in resources:
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                if not committed:
                    raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--audit-authorization", type=Path, required=True)
    parser.add_argument("--audit-authorization-sha256", required=True)
    parser.add_argument("--slurm-cluster", required=True)
    parser.add_argument("--expected-task-file", type=Path, required=True)
    parser.add_argument("--expected-task-file-sha256", required=True)
    parser.add_argument("--expected-production-config", type=Path, required=True)
    parser.add_argument("--expected-production-config-sha256", required=True)
    parser.add_argument("--expected-launch-certificate", type=Path, required=True)
    parser.add_argument("--expected-launch-certificate-sha256", required=True)
    parser.add_argument("--expected-oracle-receipt", type=Path, required=True)
    parser.add_argument("--expected-oracle-receipt-sha256", required=True)
    parser.add_argument("--expected-traces", type=int, default=EXPECTED_TASKS)
    args = parser.parse_args(argv)
    runtime_revalidator = globals().get("__production_trace_runtime_revalidator__")
    submission_attestation = globals().get(
        "__production_trace_submission_attestation__"
    )
    submission_revalidator = globals().get(
        "__production_trace_submission_revalidator__"
    )
    if not callable(runtime_revalidator):
        print(
            "production_trace_checkpoint_error:verified_runtime_required",
            file=sys.stderr,
        )
        return 2
    if not isinstance(submission_attestation, Mapping) or not callable(
        submission_revalidator
    ):
        print(
            "production_trace_checkpoint_error:audit_submission_attestation_required",
            file=sys.stderr,
        )
        return 2
    try:
        certificate = certify_production(
            args.run_dir,
            audit_authorization=args.audit_authorization,
            audit_authorization_sha256=args.audit_authorization_sha256,
            slurm_cluster=args.slurm_cluster,
            expected_task_file=args.expected_task_file,
            expected_task_file_sha256=args.expected_task_file_sha256,
            expected_production_config=args.expected_production_config,
            expected_production_config_sha256=args.expected_production_config_sha256,
            expected_launch_certificate=args.expected_launch_certificate,
            expected_launch_certificate_sha256=args.expected_launch_certificate_sha256,
            expected_oracle_receipt=args.expected_oracle_receipt,
            expected_oracle_receipt_sha256=args.expected_oracle_receipt_sha256,
            expected_traces=args.expected_traces,
            runtime_revalidator=runtime_revalidator,
            submission_attestation=submission_attestation,
            submission_revalidator=submission_revalidator,
        )
    except ProductionCertificateError as error:
        print(f"production_trace_checkpoint_error:{error}", file=sys.stderr)
        return 2
    except Exception:  # CLI output must remain aggregate-only on unexpected failures.
        print("production_trace_checkpoint_error:unexpected_failure", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "checkpoint": os.path.abspath(args.run_dir / CHECKPOINT_NAME),
                "certificate": os.path.abspath(args.run_dir / PAYLOAD_NAME),
                "production_trace_certificate_sha256": certificate[
                    "production_trace_certificate_sha256"
                ],
                "counts": certificate["counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
