#!/usr/bin/env python3
"""Fail-closed trigger and held launcher for the legacy Kimi two-task smoke.

This module is intentionally stdlib-only until :func:`activate_reviewed_imports`
has validated the exact source and dependency snapshot.  It never prints task
identifiers, scheduler records, endpoint addresses, or trace bodies.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
PLAN_KIND = "kimi_smoke_fresh_two_recovery_plan"
REVIEW_KIND = "kimi_smoke_fresh_two_recovery_review"
RUNTIME_KIND = "kimi_smoke_recovery_runtime_manifest"
TRIGGER_KIND = "kimi_smoke_terminal_quiescence_gate"
INTENT_KIND = "kimi_smoke_fresh_two_launch_intent"
AUTHORIZATION_KIND = "kimi_smoke_fresh_two_held_authorization"
PERMIT_KIND = "kimi_smoke_fresh_two_activation_permit"
SUBMISSION_KIND = "kimi_smoke_fresh_two_submission_receipt"
FAILURE_KIND = "kimi_smoke_fresh_two_submission_failure"

OWNER = "tianhaowu"
OWNER_UID = 656177
EXPECTED_USER_ID = f"{OWNER}({OWNER_UID})"
CLUSTER = "fair-cw-use2-3"
LEGACY_SOURCE_REVISION = "3d1c4906c398f26198cda158d3f05f9276bfd1fb"
SOURCE_JOB_ID = "1753515"
FRESH_TWO_TASK_SHA256 = "ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83"
FRESH_TWO_CONFIG_SHA256 = "ff6edee61c10e8c1d08c26b94fd186af96f3e06ad3d85a9d78728c3bc1ede7d3"
RECOVERY_WRAPPER_SHA256 = "d23f41efbd68d4da70901c55d5a85bd5adbfffa4ae525a2d6526b1798f062b93"
EXPECTED_TASKS = 2
EXPECTED_ROUTES = 2
MAX_SEQUENCE_TOKENS = 262_144
QUIESCENCE_SAMPLES = 6
QUIESCENCE_MIN_SECONDS = 120
QUIESCENCE_INTERVAL_SECONDS = 24
HELD_TIMEOUT_SECONDS = 982
ACTIVATION_TIMEOUT_SECONDS = 742
ADMISSION_TIMEOUT_SECONDS = 1_500
CANCEL_IDENTITY_TIMEOUT_SECONDS = 180
CANCEL_TERMINAL_TIMEOUT_SECONDS = 300
POLL_SECONDS = 2
TERMINAL_PROOF_ROUNDS = 6
COMMAND_TIMEOUT_SECONDS = 20
MAX_FILE_BYTES = 256 * 1024 * 1024
ISOLATED_STDLIB_PATHS = [
    "/usr/lib/python312.zip",
    "/usr/lib/python3.12",
    "/usr/lib/python3.12/lib-dynload",
]

SHA_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
JOB_RE = re.compile(r"[1-9][0-9]{0,19}")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
SAFE_CODE_RE = re.compile(r"[a-z0-9_]{1,96}")
HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")
NODELIST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._,\[\]-]*")
UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")
STARTED_AT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
TERMINAL_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
}
RECOVERABLE_SOURCE_STATES = {"FAILED", "TIMEOUT"}
ACTIVE_STATES = {"CONFIGURING", "PENDING", "RUNNING"}
DANGEROUS_ENV_PREFIXES = (
    "BASH_",
    "ENV",
    "GIT_",
    "LD_",
    "PYTHON",
    "SBATCH_",
)


class RecoveryControlError(ValueError):
    """An invariant failed with a stable, non-sensitive code."""


class LifecycleError(RecoveryControlError):
    """A submitted allocation could not safely reach the launch commit point."""

    def __init__(self, code: str, *, cancellation: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.cancellation = dict(cancellation or {})


class LaunchInterrupted(BaseException):
    """A launcher signal that must enter the exact-job cleanup path."""

    def __init__(self, signum: int) -> None:
        super().__init__("launcher_interrupted")
        self.signum = signum


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        fail("route_redirect_forbidden")


@dataclass(frozen=True)
class StableFile:
    path: Path
    raw: bytes
    sha256: str
    signature: tuple[int, ...]

    @property
    def record(self) -> dict[str, str]:
        return {"path": str(self.path), "sha256": self.sha256}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], CommandResult]
Fetcher = Callable[[str, float], tuple[int, bytes]]


def fail(code: str) -> None:
    if SAFE_CODE_RE.fullmatch(code) is None:
        code = "recovery_control_failed"
    raise RecoveryControlError(code)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            fail("json_duplicate_key")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    fail("json_nonfinite_number")


def strict_json(raw: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except RecoveryControlError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise RecoveryControlError(code) from error
    if not isinstance(value, dict):
        fail(code)
    return value


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def stable_file(
    path: Path,
    *,
    code: str,
    mode: int | None = None,
    uid: int | None = OWNER_UID,
    maximum: int = MAX_FILE_BYTES,
) -> StableFile:
    try:
        if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
            fail(code)
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size < 0
                or before.st_size > maximum
                or (mode is not None and stat.S_IMODE(before.st_mode) != mode)
                or (uid is not None and before.st_uid != uid)
            ):
                fail(code)
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1 << 20, remaining))
                if not chunk:
                    fail(code)
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                fail(code)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        final = os.stat(path, follow_symlinks=False)
    except RecoveryControlError:
        raise
    except OSError as error:
        raise RecoveryControlError(code) from error
    if _signature(before) != _signature(after) or _signature(after) != _signature(final):
        fail(code)
    raw = b"".join(chunks)
    return StableFile(path, raw, sha256_bytes(raw), _signature(final))


def stable_directory(path: Path, *, code: str, mode: int, uid: int = OWNER_UID) -> tuple[int, ...]:
    try:
        if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
            fail(code)
        metadata = path.stat(follow_symlinks=False)
    except RecoveryControlError:
        raise
    except OSError as error:
        raise RecoveryControlError(code) from error
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != mode or metadata.st_uid != uid:
        fail(code)
    return _signature(metadata)


def strict_envelope(path: Path, *, kind: str, hash_field: str, code: str) -> tuple[dict[str, Any], StableFile]:
    artifact = stable_file(path, code=code, mode=0o400)
    value = strict_json(artifact.raw, code=code)
    body = {key: item for key, item in value.items() if key != hash_field}
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != kind
        or value.get(hash_field) != sha256_bytes(canonical_json(body))
    ):
        fail(code)
    return value, artifact


def envelope(body: Mapping[str, Any], hash_field: str) -> bytes:
    value = {**body, hash_field: sha256_bytes(canonical_json(body))}
    return json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_once(path: Path, raw: bytes, *, mode: int) -> str:
    """Publish one file through an anchored parent and reject parent replacement."""

    parent = path.parent
    stable_directory(parent, code="publication_parent_invalid", mode=0o700)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    temporary = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor = -1
    try:
        before = os.fstat(parent_fd)
        if os.path.lexists(path):
            fail("publication_target_exists")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                fail("publication_write_failed")
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(
            temporary,
            path.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
        fresh_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if _signature(before)[:2] != _signature(os.fstat(fresh_fd))[:2]:
                fail("publication_parent_changed")
        finally:
            os.close(fresh_fd)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(parent_fd)
    digest = sha256_bytes(raw)
    if stable_file(path, code="publication_changed", mode=mode).sha256 != digest:
        fail("publication_changed")
    return digest


def clean_command_environment() -> dict[str, str]:
    return {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": OWNER,
        "PATH": "/usr/bin:/bin",
        "USER": OWNER,
    }


def run_command(argv: Sequence[str], timeout: float) -> CommandResult:
    if not argv or not Path(argv[0]).is_absolute():
        fail("command_not_absolute")
    try:
        result = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            env=clean_command_environment(),
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RecoveryControlError("command_unavailable") from error
    if len(result.stdout) > (1 << 20) or len(result.stderr) > (1 << 20):
        fail("command_output_oversize")
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _parse_pipe_rows(result: CommandResult, *, width: int, code: str) -> list[list[str]]:
    if result.returncode != 0 or result.stderr:
        fail(code)
    rows = [line.split("|") for line in result.stdout.splitlines() if line.strip()]
    if any(len(row) != width for row in rows):
        fail(code)
    return rows


def scheduler_state(value: str) -> str:
    return value.split()[0].rstrip("+") if value else "UNKNOWN"


def parse_scontrol_record(raw: str) -> dict[str, str]:
    record: dict[str, str] = {}
    for token in raw.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key in record:
            fail("scheduler_record_invalid")
        record[key] = value
    if not record:
        fail("scheduler_record_invalid")
    return record


def scontrol_record(job_id: str, *, runner: Runner = run_command) -> dict[str, str]:
    result = runner(
        ["/usr/bin/scontrol", "-M", CLUSTER, "show", "job", "-o", job_id],
        COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or result.stderr or len(result.stdout.splitlines()) != 1:
        fail("scheduler_identity_unavailable")
    return parse_scontrol_record(result.stdout.strip())


def _validate_timestamp(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or UTC_RE.fullmatch(value) is None:
        fail(code)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RecoveryControlError(code) from error
    return value


def _artifact_record(value: Any, *, code: str) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not Path(value["path"]).is_absolute()
        or not isinstance(value.get("sha256"), str)
        or SHA_RE.fullmatch(value["sha256"]) is None
    ):
        fail(code)
    return {"path": value["path"], "sha256": value["sha256"]}


def load_plan(path: Path) -> tuple[dict[str, Any], StableFile]:
    stable_directory(path.parent, code="recovery_plan_invalid", mode=0o700)
    value, artifact = strict_envelope(
        path,
        kind=PLAN_KIND,
        hash_field="plan_sha256",
        code="recovery_plan_invalid",
    )
    if value.get("state") != "approved":
        fail("recovery_plan_invalid")
    owner = value.get("owner")
    source = value.get("source_smoke")
    recovery = value.get("recovery")
    runtime = value.get("runtime")
    policy = value.get("policy")
    launcher = value.get("launcher")
    if set(value) != {
        "cluster",
        "kind",
        "launcher",
        "owner",
        "plan_sha256",
        "policy",
        "recovery",
        "runtime",
        "schema_version",
        "source_smoke",
        "state",
    } or not all(isinstance(item, dict) for item in (owner, source, recovery, runtime, policy, launcher)):
        fail("recovery_plan_invalid")
    if owner != {"name": OWNER, "uid": OWNER_UID, "user_id": EXPECTED_USER_ID}:
        fail("recovery_plan_invalid")
    if set(source) != {"job_id", "job_name", "run_dir", "source_revision"}:
        fail("recovery_plan_invalid")
    if (
        set(launcher) != {"pane_id", "pane_pid", "session_id", "socket", "target", "tmux"}
        or not isinstance(launcher.get("socket"), str)
        or not Path(launcher["socket"]).is_absolute()
        or not isinstance(launcher.get("target"), str)
        or not launcher["target"]
        or not isinstance(launcher.get("pane_id"), str)
        or re.fullmatch(r"%[1-9][0-9]*", launcher["pane_id"]) is None
        or type(launcher.get("pane_pid")) is not int
        or launcher["pane_pid"] <= 1
        or not isinstance(launcher.get("session_id"), str)
        or re.fullmatch(r"\$[1-9][0-9]*", launcher["session_id"]) is None
    ):
        fail("recovery_plan_invalid")
    _artifact_record(launcher.get("tmux"), code="recovery_plan_invalid")
    if (
        value.get("cluster") != CLUSTER
        or source.get("job_id") != SOURCE_JOB_ID
        or source.get("source_revision") != LEGACY_SOURCE_REVISION
        or not isinstance(source.get("job_name"), str)
        or NAME_RE.fullmatch(source["job_name"]) is None
        or not isinstance(source.get("run_dir"), str)
        or not Path(source["run_dir"]).is_absolute()
        or policy
        != {
            "activation_timeout_seconds": ACTIVATION_TIMEOUT_SECONDS,
            "admission_timeout_seconds": ADMISSION_TIMEOUT_SECONDS,
            "fresh_two_only": True,
            "held_timeout_seconds": HELD_TIMEOUT_SECONDS,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
            "quiescence_interval_seconds": QUIESCENCE_INTERVAL_SECONDS,
            "quiescence_min_seconds": QUIESCENCE_MIN_SECONDS,
            "quiescence_samples": QUIESCENCE_SAMPLES,
            "resume": False,
            "routes": EXPECTED_ROUTES,
            "tasks": EXPECTED_TASKS,
        }
    ):
        fail("recovery_plan_invalid")
    required_recovery = {
        "config_file",
        "controller",
        "dataset_archive",
        "dataset_content_sha256",
        "deployment_id",
        "deployment_spec",
        "endpoints_dir",
        "job_wrapper",
        "log_dir",
        "output_dir",
        "project_root",
        "proxy_info",
        "readiness_checkpoint",
        "recovery_wrapper",
        "reservation_dir",
        "route_generation_sha256",
        "source_revision",
        "source_tree",
        "task_file",
    }
    if set(recovery) != required_recovery:
        fail("recovery_plan_invalid")
    for key in (
        "config_file",
        "controller",
        "dataset_archive",
        "deployment_spec",
        "job_wrapper",
        "proxy_info",
        "readiness_checkpoint",
        "recovery_wrapper",
        "task_file",
    ):
        _artifact_record(recovery.get(key), code="recovery_plan_invalid")
    if (
        recovery["task_file"]["sha256"] != FRESH_TWO_TASK_SHA256
        or recovery["config_file"]["sha256"] != FRESH_TWO_CONFIG_SHA256
        or recovery["recovery_wrapper"]["sha256"] != RECOVERY_WRAPPER_SHA256
    ):
        fail("recovery_plan_invalid")
    for key in ("project_root", "endpoints_dir", "log_dir", "output_dir", "reservation_dir"):
        if not isinstance(recovery.get(key), str) or not Path(recovery[key]).is_absolute():
            fail("recovery_plan_invalid")
    if (
        not isinstance(recovery.get("deployment_id"), str)
        or NAME_RE.fullmatch(recovery["deployment_id"]) is None
        or not isinstance(recovery.get("source_revision"), str)
        or REVISION_RE.fullmatch(recovery["source_revision"]) is None
        or not isinstance(recovery.get("source_tree"), str)
        or REVISION_RE.fullmatch(recovery["source_tree"]) is None
        or SHA_RE.fullmatch(str(recovery.get("route_generation_sha256", ""))) is None
        or SHA_RE.fullmatch(str(recovery.get("dataset_content_sha256", ""))) is None
    ):
        fail("recovery_plan_invalid")
    if set(runtime) != {"auth", "binaries", "manifest", "python", "uv", "vacli"}:
        fail("recovery_plan_invalid")
    for key in ("manifest", "python", "uv", "vacli"):
        _artifact_record(runtime.get(key), code="recovery_plan_invalid")
    auth = runtime.get("auth")
    if not isinstance(auth, dict) or set(auth) != {"certificate", "private_key"}:
        fail("recovery_plan_invalid")
    for key in ("certificate", "private_key"):
        _artifact_record(auth.get(key), code="recovery_plan_invalid")
    binaries = runtime.get("binaries")
    required_binaries = {
        "bash": "/usr/bin/bash",
        "env": "/usr/bin/env",
        "git": "/usr/bin/git",
        "readlink": "/usr/bin/readlink",
        "sacct": "/usr/bin/sacct",
        "sbatch": "/usr/bin/sbatch",
        "scancel": "/usr/bin/scancel",
        "scontrol": "/usr/bin/scontrol",
        "sha256sum": "/usr/bin/sha256sum",
        "squeue": "/usr/bin/squeue",
        "stat": "/usr/bin/stat",
        "tmux": "/usr/bin/tmux",
        "uname": "/usr/bin/uname",
    }
    if not isinstance(binaries, dict) or set(binaries) != set(required_binaries):
        fail("recovery_plan_invalid")
    for key, expected_path in required_binaries.items():
        record = _artifact_record(binaries.get(key), code="recovery_plan_invalid")
        if record["path"] != expected_path:
            fail("recovery_plan_invalid")
    if launcher["tmux"] != binaries["tmux"]:
        fail("recovery_plan_invalid")
    return value, artifact


def load_review(
    path: Path,
    *,
    plan: StableFile,
    trigger: StableFile,
    controller_sha256: str,
    wrapper_sha256: str,
) -> StableFile:
    stable_directory(path.parent, code="recovery_review_invalid", mode=0o700)
    value, artifact = strict_envelope(
        path,
        kind=REVIEW_KIND,
        hash_field="review_sha256",
        code="recovery_review_invalid",
    )
    if (
        set(value)
        != {
            "controller_sha256",
            "fresh_two_only",
            "job_wrapper_sha256",
            "kind",
            "launches",
            "plan",
            "review_sha256",
            "reviewer",
            "schema_version",
            "state",
            "trigger",
        }
        or value.get("state") != "approved"
        or value.get("launches") != 1
        or value.get("fresh_two_only") is not True
        or value.get("plan") != plan.record
        or value.get("trigger") != trigger.record
        or value.get("controller_sha256") != controller_sha256
        or value.get("job_wrapper_sha256") != wrapper_sha256
        or not isinstance(value.get("reviewer"), str)
        or not value["reviewer"]
    ):
        fail("recovery_review_invalid")
    return artifact


def clean_git_environment() -> dict[str, str]:
    return {
        **clean_command_environment(),
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def git_output(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            env=clean_git_environment(),
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RecoveryControlError("source_git_unavailable") from error
    if result.returncode != 0 or result.stderr:
        fail("source_git_invalid")
    return result.stdout


def validate_source(plan: Mapping[str, Any]) -> dict[str, str]:
    recovery = plan["recovery"]
    root = Path(recovery["project_root"])
    stable_directory(root, code="source_root_invalid", mode=0o555)
    revision = recovery["source_revision"]
    tree = recovery["source_tree"]
    if (
        git_output(root, "rev-parse", "--verify", "HEAD").strip() != revision
        or git_output(root, "rev-parse", "--verify", "HEAD^{tree}").strip() != tree
        or git_output(root, "rev-parse", "--abbrev-ref", "HEAD").strip() != "HEAD"
        or git_output(root, "status", "--porcelain=v1", "--untracked-files=all").strip()
    ):
        fail("source_checkout_invalid")
    ignored = git_output(
        root,
        "status",
        "--porcelain=v1",
        "--ignored",
        "--untracked-files=all",
        "--",
        "user/tianhaowu/terminal_bench_vmvm",
        "environments/vmvm_tb_v2",
        "deps/verifiers",
        "deps/renderers",
        "deps/pydantic-config",
    )
    if ignored.strip():
        fail("source_ignored_entries_present")
    gitlinks: dict[str, str] = {}
    for relative in ("deps/verifiers", "deps/renderers", "deps/pydantic-config"):
        fields = git_output(root, "ls-tree", revision, "--", relative).strip().split()
        if len(fields) != 4 or fields[:2] != ["160000", "commit"] or fields[3] != relative:
            fail("source_gitlink_invalid")
        child = root / relative
        if (
            git_output(child, "rev-parse", "--verify", "HEAD").strip() != fields[2]
            or git_output(child, "rev-parse", "--abbrev-ref", "HEAD").strip() != "HEAD"
            or git_output(child, "status", "--porcelain=v1", "--untracked-files=all").strip()
            or git_output(child, "status", "--porcelain=v1", "--ignored", "--untracked-files=all").strip()
        ):
            fail("source_gitlink_invalid")
        gitlinks[relative] = fields[2]
    expected_paths = {
        "controller": root / "user/tianhaowu/terminal_bench_vmvm/kimi_smoke_timeout_recovery_control.py",
        "job_wrapper": root / "user/tianhaowu/terminal_bench_vmvm/run_kimi_smoke_timeout_recovery_hardened.sbatch",
        "recovery_wrapper": root / "user/tianhaowu/terminal_bench_vmvm/run_kimi_smoke_recovery.sbatch",
        "config_file": root / "user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_fresh_smoke12h.toml",
        "task_file": root / "user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_token_smoke.tasks.txt",
    }
    for key, expected_path in expected_paths.items():
        record = _artifact_record(recovery[key], code="source_artifact_invalid")
        artifact = stable_file(Path(record["path"]), code="source_artifact_invalid", uid=OWNER_UID)
        if artifact.sha256 != record["sha256"] or artifact.path != expected_path:
            fail("source_artifact_invalid")
    return {
        "revision": revision,
        "tree": tree,
        "gitlinks_sha256": sha256_bytes(canonical_json(gitlinks)),
    }


def _validate_binary(record: Any, *, code: str, root_owned: bool) -> StableFile:
    normalized = _artifact_record(record, code=code)
    artifact = stable_file(
        Path(normalized["path"]),
        code=code,
        uid=0 if root_owned else OWNER_UID,
        maximum=64 * 1024 * 1024,
    )
    if artifact.sha256 != normalized["sha256"] or not os.access(artifact.path, os.X_OK):
        fail(code)
    return artifact


def validate_runtime_manifest(plan: Mapping[str, Any]) -> dict[str, str]:
    runtime = plan["runtime"]
    manifest_record = _artifact_record(runtime["manifest"], code="runtime_manifest_invalid")
    value, artifact = strict_envelope(
        Path(manifest_record["path"]),
        kind=RUNTIME_KIND,
        hash_field="manifest_sha256",
        code="runtime_manifest_invalid",
    )
    if (
        artifact.sha256 != manifest_record["sha256"]
        or value.get("state") != "approved"
        or set(value)
        != {
            "entries",
            "kind",
            "manifest_sha256",
            "root",
            "schema_version",
            "state",
        }
    ):
        fail("runtime_manifest_invalid")
    root_value = value.get("root")
    entries = value.get("entries")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute() or not isinstance(entries, list):
        fail("runtime_manifest_invalid")
    root = Path(root_value)
    stable_directory(root, code="runtime_root_invalid", mode=0o500)
    expected: dict[str, dict[str, Any]] = {}
    for item in entries:
        if (
            not isinstance(item, dict)
            or set(item) != {"mode", "path", "sha256", "size"}
            or not isinstance(item.get("path"), str)
            or PurePosixPath(item["path"]).is_absolute()
            or ".." in PurePosixPath(item["path"]).parts
            or item["path"] in expected
            or not isinstance(item.get("mode"), int)
            or item["mode"] != 0o400
            or not isinstance(item.get("size"), int)
            or item["size"] < 0
            or SHA_RE.fullmatch(str(item.get("sha256", ""))) is None
        ):
            fail("runtime_manifest_invalid")
        lower_parts = tuple(part.casefold() for part in PurePosixPath(item["path"]).parts)
        if (
            "__pycache__" in lower_parts
            or item["path"].casefold().endswith((".pyc", ".pyo", ".pth"))
            or PurePosixPath(item["path"]).name.casefold() in {"sitecustomize.py", "usercustomize.py"}
        ):
            fail("runtime_executable_metadata_forbidden")
        expected[item["path"]] = item
    observed: set[str] = set()
    for directory, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        metadata = current.stat(follow_symlinks=False)
        if (
            current.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o500
            or metadata.st_uid != OWNER_UID
        ):
            fail("runtime_tree_invalid")
        for name in sorted(directory_names):
            child = current / name
            if child.is_symlink() or name.casefold() == "__pycache__":
                fail("runtime_tree_invalid")
        for name in sorted(file_names):
            child = current / name
            relative = child.relative_to(root).as_posix()
            record = expected.get(relative)
            if record is None:
                fail("runtime_manifest_set_mismatch")
            observed.add(relative)
            file = stable_file(child, code="runtime_file_invalid", mode=0o400)
            if file.sha256 != record["sha256"] or len(file.raw) != record["size"]:
                fail("runtime_file_invalid")
    if observed != set(expected) or not observed:
        fail("runtime_manifest_set_mismatch")
    python = _validate_binary(runtime["python"], code="runtime_python_invalid", root_owned=True)
    uv = _validate_binary(runtime["uv"], code="runtime_uv_invalid", root_owned=False)
    vacli = _validate_binary(runtime["vacli"], code="runtime_vacli_invalid", root_owned=True)
    auth = runtime["auth"]
    binary_hashes: dict[str, str] = {}
    for name, record in sorted(runtime["binaries"].items()):
        binary_hashes[name] = _validate_binary(record, code="runtime_binary_invalid", root_owned=True).sha256
    certificate_record = _artifact_record(auth["certificate"], code="runtime_auth_invalid")
    private_key_record = _artifact_record(auth["private_key"], code="runtime_auth_invalid")
    certificate = stable_file(Path(certificate_record["path"]), code="runtime_auth_invalid", uid=OWNER_UID)
    private_key = stable_file(
        Path(private_key_record["path"]),
        code="runtime_auth_invalid",
        mode=0o400,
        uid=OWNER_UID,
    )
    if certificate.sha256 != certificate_record["sha256"] or private_key.sha256 != private_key_record["sha256"]:
        fail("runtime_auth_invalid")
    return {
        "manifest_sha256": artifact.sha256,
        "python_sha256": python.sha256,
        "uv_sha256": uv.sha256,
        "vacli_sha256": vacli.sha256,
        "auth_sha256": sha256_bytes(
            canonical_json({"certificate": certificate.sha256, "private_key": private_key.sha256})
        ),
        "binaries_sha256": sha256_bytes(canonical_json(binary_hashes)),
    }


def validate_external_inputs(plan: Mapping[str, Any]) -> dict[str, str]:
    recovery = plan["recovery"]
    dataset_record = _artifact_record(recovery["dataset_archive"], code="dataset_archive_invalid")
    dataset = stable_file(
        Path(dataset_record["path"]),
        code="dataset_archive_invalid",
        uid=OWNER_UID,
        maximum=4 * 1024 * 1024 * 1024,
    )
    if dataset.sha256 != dataset_record["sha256"]:
        fail("dataset_archive_invalid")
    mutable_namespaces = [
        Path(recovery["output_dir"]),
        Path(recovery["reservation_dir"]),
        Path(recovery["log_dir"]),
    ]
    if len(set(mutable_namespaces)) != 3:
        fail("launch_namespaces_invalid")
    for path in mutable_namespaces:
        parent = path.parent.resolve(strict=True)
        if path != parent / path.name or not path.name.startswith("kimi_smoke_recovery_"):
            fail("launch_namespaces_invalid")
        stable_directory(parent, code="launch_parent_invalid", mode=0o700)
    return {
        "dataset_archive_sha256": dataset.sha256,
        "dataset_content_sha256": recovery["dataset_content_sha256"],
    }


def _process_parent(pid: int) -> int:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        close = raw.rfind(")")
        fields = raw[close + 2 :].split()
        if close < 1 or len(fields) < 2:
            fail("launcher_ancestry_invalid")
        return int(fields[1])
    except (OSError, UnicodeError, ValueError) as error:
        raise RecoveryControlError("launcher_ancestry_invalid") from error


def _process_executable(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError as error:
        raise RecoveryControlError("launcher_ancestry_invalid") from error


def validate_invocation(plan: Mapping[str, Any], *, runner: Runner = run_command) -> None:
    """Require isolated Python directly owned by one approved canonical tmux pane."""

    launcher = plan["launcher"]
    tmux_record = _artifact_record(launcher["tmux"], code="launcher_invocation_invalid")
    tmux = _validate_binary(tmux_record, code="launcher_invocation_invalid", root_owned=True)
    runtime_python = _artifact_record(plan["runtime"]["python"], code="launcher_invocation_invalid")
    executable = Path(sys.executable).resolve(strict=True)
    if (
        str(executable) != runtime_python["path"]
        or sha256_bytes(stable_file(executable, code="launcher_invocation_invalid", uid=0).raw)
        != runtime_python["sha256"]
        or not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.flags.dont_write_bytecode
        or not sys.flags.safe_path
        or sys.version_info[:2] != (3, 12)
        or sys.path != ISOLATED_STDLIB_PATHS
    ):
        fail("launcher_invocation_invalid")
    allowed_environment = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "TMUX",
        "TMUX_PANE",
        "USER",
    }
    if set(os.environ) != allowed_environment or any(
        os.environ.get(key) != value
        for key, value in {
            "HOME": "/storage/home/tianhaowu",
            "LANG": "C",
            "LC_ALL": "C",
            "LOGNAME": OWNER,
            "PATH": "/usr/bin:/bin",
            "TMUX_PANE": launcher["pane_id"],
            "USER": OWNER,
        }.items()
    ):
        fail("launcher_environment_invalid")
    tmux_value = os.environ.get("TMUX", "")
    tmux_fields = tmux_value.rsplit(",", 2)
    if (
        len(tmux_fields) != 3
        or tmux_fields[0] != launcher["socket"]
        or not tmux_fields[1].isdigit()
        or not tmux_fields[2].isdigit()
    ):
        fail("launcher_invocation_invalid")
    try:
        socket_path = Path(launcher["socket"])
        socket_metadata = os.stat(socket_path, follow_symlinks=False)
    except OSError as error:
        raise RecoveryControlError("launcher_invocation_invalid") from error
    if (
        socket_path.is_symlink()
        or socket_path.resolve(strict=True) != socket_path
        or not stat.S_ISSOCK(socket_metadata.st_mode)
        or socket_metadata.st_uid != OWNER_UID
        or socket_metadata.st_nlink != 1
        or _process_executable(int(tmux_fields[1])) != str(tmux.path)
    ):
        fail("launcher_invocation_invalid")
    result = runner(
        [
            str(tmux.path),
            "-S",
            launcher["socket"],
            "display-message",
            "-p",
            "-t",
            launcher["target"],
            "#{pane_id}|#{pane_pid}|#{session_id}|#{session_attached}|#{pane_dead}|#{pane_current_command}",
        ],
        COMMAND_TIMEOUT_SECONDS,
    )
    rows = _parse_pipe_rows(result, width=6, code="launcher_invocation_invalid")
    if len(rows) != 1:
        fail("launcher_invocation_invalid")
    pane_id, pane_pid, session_id, attached, dead, current_command = rows[0]
    parent = _process_parent(os.getpid())
    if (
        pane_id != launcher["pane_id"]
        or pane_pid != str(launcher["pane_pid"])
        or session_id != launcher["session_id"]
        or attached != "1"
        or dead != "0"
        or current_command not in {executable.name, "python3.12"}
        or parent != launcher["pane_pid"]
        or _process_executable(parent) not in {"/usr/bin/bash", "/bin/bash"}
    ):
        fail("launcher_invocation_invalid")


def _load_json_artifact(record: Any, *, code: str) -> tuple[dict[str, Any], StableFile]:
    normalized = _artifact_record(record, code=code)
    artifact = stable_file(Path(normalized["path"]), code=code, uid=OWNER_UID)
    if artifact.sha256 != normalized["sha256"]:
        fail(code)
    return strict_json(artifact.raw, code=code), artifact


def _canonical_backend(host: str, port: int) -> str:
    if HOST_RE.fullmatch(host) is None or not 1 <= port <= 65535:
        fail("route_endpoint_invalid")
    return "backend-sha256:" + sha256_bytes(f"http://{host}:{port}/v1".encode("utf-8"))


def _validate_proxy_binding(
    value: Mapping[str, Any],
    *,
    proxy_path: Path,
    spec_path: Path,
    deployment_id: str,
    proxy_job_id: str,
) -> tuple[str, int]:
    if set(value) != {"api_key", "extras", "host", "model", "port", "proxy_jobid", "url"}:
        fail("proxy_info_invalid")
    host = value.get("host")
    port = value.get("port")
    url = value.get("url")
    if (
        proxy_path.name != "proxy_info.json"
        or spec_path.name != "spec.yaml"
        or proxy_path.parent != spec_path.parent
        or proxy_path.parent.name != deployment_id
        or not isinstance(host, str)
        or HOST_RE.fullmatch(host) is None
        or type(port) is not int
        or not 1 <= port <= 65535
        or not isinstance(url, str)
        or url != f"http://{host}:{port}"
        or value.get("model") != "Kimi-K3"
        or value.get("proxy_jobid") != proxy_job_id
        or not isinstance(value.get("api_key"), str)
        or not value["api_key"]
        or not isinstance(value.get("extras"), dict)
    ):
        fail("proxy_info_invalid")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != host
        or parsed.port != port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        fail("proxy_info_invalid")
    return host, port


def fetch_http(url: str, timeout: float) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectRedirects())
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read((1 << 20) + 1)
            return int(response.status), body
    except (OSError, urllib.error.URLError, ValueError) as error:
        raise RecoveryControlError("route_probe_unavailable") from error


def _metric_sum(raw: bytes, name: str) -> int:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RecoveryControlError("route_metrics_invalid") from error
    values: list[float] = []
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        if line == name or line.startswith(f"{name}{{") or line.startswith(f"{name} "):
            fields = line.rsplit(None, 1)
            if len(fields) != 2:
                fail("route_metrics_invalid")
            try:
                value = float(fields[1])
            except ValueError as error:
                raise RecoveryControlError("route_metrics_invalid") from error
            if not math.isfinite(value) or value < 0 or not value.is_integer():
                fail("route_metrics_invalid")
            values.append(value)
    if not values:
        fail("route_metrics_missing")
    return int(sum(values))


def _job_identity(record: Mapping[str, str], *, job_id: str, state: str) -> None:
    if (
        record.get("JobId") != job_id
        or record.get("UserId") != EXPECTED_USER_ID
        or scheduler_state(record.get("JobState", "")) != state
        or record.get("Restarts") != "0"
    ):
        fail("deployment_job_identity_invalid")


def route_idle_snapshot(
    plan: Mapping[str, Any],
    *,
    runner: Runner = run_command,
    fetcher: Fetcher = fetch_http,
) -> dict[str, Any]:
    """Prove the exact two-route generation is healthy and has no live requests."""

    recovery = plan["recovery"]
    readiness, readiness_artifact = _load_json_artifact(recovery["readiness_checkpoint"], code="readiness_invalid")
    spec = _artifact_record(recovery["deployment_spec"], code="deployment_spec_invalid")
    proxy = _artifact_record(recovery["proxy_info"], code="proxy_info_invalid")
    external_artifacts: dict[str, StableFile] = {}
    for record, code in ((spec, "deployment_spec_invalid"), (proxy, "proxy_info_invalid")):
        artifact = stable_file(Path(record["path"]), code=code, uid=OWNER_UID)
        if artifact.sha256 != record["sha256"]:
            fail(code)
        external_artifacts[code] = artifact
    generation = readiness.get("serving_route_generation")
    last = readiness.get("last_status")
    endpoint = readiness.get("endpoint")
    proxy_policy = readiness.get("proxy_policy")
    last_generation_matches = isinstance(last, dict) and readiness.get("serving_route_generation") == last.get(
        "serving_route_generation"
    )
    if (
        readiness.get("schema_version") != 1
        or readiness.get("state") != "passed"
        or readiness.get("deployment") != recovery["deployment_id"]
        or readiness.get("expected_routes") != EXPECTED_ROUTES
        or readiness.get("observed_spec_sha256") != spec["sha256"]
        or not isinstance(generation, dict)
        or sha256_bytes(canonical_json(generation)) != recovery.get("route_generation_sha256")
        or not last_generation_matches
    ):
        fail("readiness_invalid")
    if (
        not isinstance(last, dict)
        or last.get("phase") != "serving"
        or last.get("desired") != EXPECTED_ROUTES
        or last.get("ready") != EXPECTED_ROUTES
        or last.get("running_not_ready") != 0
        or last.get("pending") != 0
        or not isinstance(endpoint, dict)
        or endpoint.get("proxy_info") != proxy
        or not isinstance(proxy_policy, dict)
        or proxy_policy.get("request_timeout") != 43_200
        or proxy_policy.get("num_retries") != 0
    ):
        fail("readiness_invalid")
    routes = generation.get("routes")
    coordinator = generation.get("coordinator")
    generation_proxy = generation.get("proxy")
    if (
        generation.get("schema_version") != 2
        or set(generation) != {"coordinator", "proxy", "routes", "schema_version"}
        or not isinstance(routes, list)
        or len(routes) != EXPECTED_ROUTES
        or not isinstance(coordinator, dict)
        or not isinstance(generation_proxy, dict)
    ):
        fail("route_generation_invalid")
    if (
        set(coordinator) != {"slurm_job_id", "started_at"}
        or set(generation_proxy) != {"first_ready_at", "slurm_job_id"}
        or STARTED_AT_RE.fullmatch(str(coordinator.get("started_at", ""))) is None
        or STARTED_AT_RE.fullmatch(str(generation_proxy.get("first_ready_at", ""))) is None
        or any(
            not isinstance(item, dict)
            or set(item) != {"backend_sha256", "slurm_job_id", "started_at"}
            or STARTED_AT_RE.fullmatch(str(item.get("started_at", ""))) is None
            or re.fullmatch(r"backend-sha256:[0-9a-f]{64}", str(item.get("backend_sha256", ""))) is None
            for item in routes
        )
    ):
        fail("route_generation_invalid")
    proxy_value = strict_json(
        external_artifacts["proxy_info_invalid"].raw,
        code="proxy_info_invalid",
    )
    proxy_host, proxy_port = _validate_proxy_binding(
        proxy_value,
        proxy_path=external_artifacts["proxy_info_invalid"].path,
        spec_path=external_artifacts["deployment_spec_invalid"].path,
        deployment_id=recovery["deployment_id"],
        proxy_job_id=str(generation_proxy.get("slurm_job_id", "")),
    )
    job_records = [coordinator, generation_proxy, *routes]
    job_ids: list[str] = []
    for record in job_records:
        job_id = record.get("slurm_job_id") if isinstance(record, dict) else None
        if not isinstance(job_id, str) or JOB_RE.fullmatch(job_id) is None:
            fail("route_generation_invalid")
        job_ids.append(job_id)
        _job_identity(scontrol_record(job_id, runner=runner), job_id=job_id, state="RUNNING")
    if len(set(job_ids)) != 2 + EXPECTED_ROUTES:
        fail("route_generation_invalid")

    endpoint_root = Path(recovery["endpoints_dir"])
    stable_directory(endpoint_root, code="route_endpoints_invalid", mode=0o755)
    try:
        children = sorted(os.scandir(endpoint_root), key=lambda item: item.name)
    except OSError as error:
        raise RecoveryControlError("route_endpoints_invalid") from error
    if len(children) != EXPECTED_ROUTES:
        fail("route_endpoints_invalid")
    expected_routes = {
        (str(item.get("slurm_job_id")), str(item.get("started_at")), str(item.get("backend_sha256")))
        for item in routes
        if isinstance(item, dict)
    }
    if len(expected_routes) != EXPECTED_ROUTES:
        fail("route_generation_invalid")
    observed_routes: set[tuple[str, str, str]] = set()
    running = 0
    waiting = 0
    for child in children:
        path = endpoint_root / child.name
        if not child.name.endswith(".json") or JOB_RE.fullmatch(path.stem) is None:
            fail("route_endpoints_invalid")
        artifact = stable_file(path, code="route_endpoint_invalid", mode=0o644, maximum=4096)
        value = strict_json(artifact.raw, code="route_endpoint_invalid")
        if set(value) != {"host", "port", "started_at"}:
            fail("route_endpoint_invalid")
        host = value.get("host")
        port = value.get("port")
        started = value.get("started_at")
        if (
            not isinstance(host, str)
            or HOST_RE.fullmatch(host) is None
            or type(port) is not int
            or not 1 <= port <= 65535
            or not isinstance(started, str)
        ):
            fail("route_endpoint_invalid")
        observed_routes.add((path.stem, started, _canonical_backend(host, port)))
        health_status, health_raw = fetcher(f"http://{host}:{port}/health", 10.0)
        metrics_status, metrics_raw = fetcher(f"http://{host}:{port}/metrics", 10.0)
        if health_status != 200 or health_raw not in {b"", b"\n"} or metrics_status != 200:
            fail("route_health_invalid")
        running += _metric_sum(metrics_raw, "vllm:num_requests_running")
        waiting += _metric_sum(metrics_raw, "vllm:num_requests_waiting")
    if observed_routes != expected_routes or running != 0 or waiting != 0:
        fail("route_not_idle")
    proxy_health_status, proxy_health_raw = fetcher(f"http://{proxy_host}:{proxy_port}/health", 10.0)
    if proxy_health_status != 200 or proxy_health_raw not in {b"", b"\n"}:
        fail("route_health_invalid")
    return {
        "readiness_sha256": readiness_artifact.sha256,
        "route_generation_sha256": recovery["route_generation_sha256"],
        "routes": EXPECTED_ROUTES,
        "healthy": EXPECTED_ROUTES,
        "unhealthy": 0,
        "active": running,
        "waiting": waiting,
        "restart_count": 0,
    }


def _source_artifacts(run_dir: Path) -> dict[str, StableFile]:
    names = (
        "eval_run_identity.json",
        "eval_invocations.jsonl",
        "results.jsonl",
        "route_guard_success.json",
    )
    return {name: stable_file(run_dir / name, code="source_run_invalid", uid=OWNER_UID) for name in names}


def _source_artifact_digest(artifacts: Mapping[str, StableFile]) -> str:
    return sha256_bytes(canonical_json({name: item.record for name, item in sorted(artifacts.items())}))


def activate_reviewed_imports(plan: Mapping[str, Any]) -> tuple[Path, ...]:
    """Add only validated source and runtime roots after isolated startup."""

    recovery = plan["recovery"]
    runtime_manifest, _ = strict_envelope(
        Path(plan["runtime"]["manifest"]["path"]),
        kind=RUNTIME_KIND,
        hash_field="manifest_sha256",
        code="runtime_manifest_invalid",
    )
    root = Path(recovery["project_root"])
    paths = (
        root / "user/tianhaowu/terminal_bench_vmvm",
        root / "environments/vmvm_tb_v2",
        root / "deps/verifiers",
        root / "deps/renderers",
        root / "deps/pydantic-config/src",
        Path(runtime_manifest["root"]),
    )
    for path in paths:
        if not path.is_absolute() or not path.is_dir() or path.is_symlink():
            fail("runtime_import_path_invalid")
    if sys.path != ISOLATED_STDLIB_PATHS:
        fail("runtime_import_path_invalid")
    sys.path[:] = [str(path) for path in paths] + ISOLATED_STDLIB_PATHS
    sys.dont_write_bytecode = True
    return paths


def validate_reviewed_imports(baseline: set[str], allowed_roots: Sequence[Path]) -> None:
    stdlib_roots = tuple(
        Path(path).resolve() for path in ("/usr/lib/python3.12", "/usr/local/lib/python3.12") if Path(path).is_dir()
    )
    for name in sorted(set(sys.modules) - baseline):
        module = sys.modules.get(name)
        origin = getattr(module, "__file__", None)
        if origin is None:
            continue
        try:
            path = Path(origin).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise RecoveryControlError("reviewed_import_origin_invalid") from error
        if not any(path.is_relative_to(root) for root in (*allowed_roots, *stdlib_roots)):
            fail("reviewed_import_origin_invalid")


def validate_source_run(plan: Mapping[str, Any]) -> tuple[dict[str, StableFile], dict[str, int]]:
    """Validate the guard-linked legacy run and classify rows without exposing them."""

    run_dir = Path(plan["source_smoke"]["run_dir"])
    stable_directory(run_dir, code="source_run_invalid", mode=0o700)
    if any(child.name.startswith("smoke_checkpoint") and child.name.endswith(".json") for child in os.scandir(run_dir)):
        fail("successful_smoke_already_certified")
    runtime_before = validate_runtime_manifest(plan)
    source_before = validate_source(plan)
    artifacts = _source_artifacts(run_dir)
    protected_modules = {
        "audit_traces",
        "deployment_endpoint",
        "deployment_proxy_policy",
        "eval_run_identity",
        "guard_success_receipt",
        "inference_route_generation",
        "smoke_qualification",
        "smoke_timeout_recovery",
    }
    if protected_modules & set(sys.modules):
        fail("reviewed_import_collision")
    baseline = set(sys.modules)
    previous_path = list(sys.path)
    allowed_roots = activate_reviewed_imports(plan)
    try:
        import smoke_timeout_recovery as recovery_module

        source = recovery_module._load_run(
            run_dir,
            identity_loader=recovery_module.load_eval_run_identity,
        )
        task_record = source["identity"].get("inputs", {}).get("task_file")
        if not isinstance(task_record, dict):
            fail("source_run_invalid")
        task = stable_file(Path(task_record.get("path", "")), code="source_task_invalid", uid=OWNER_UID)
        if task.sha256 != task_record.get("sha256") or task_record.get("count") != EXPECTED_TASKS:
            fail("source_task_invalid")
        selection = recovery_module.derive_selection(task.raw, source["rows"])
        identity_source = source["identity"].get("source")
        invocation = recovery_module.validate_eval_invocations(
            artifacts["eval_invocations.jsonl"].path,
            eval_run_identity_sha256=source["identity_sha256"],
            eval_run_role="smoke",
        )[0]
        validate_reviewed_imports(baseline, allowed_roots)
    except RecoveryControlError:
        raise
    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise RecoveryControlError("source_run_invalid") from error
    finally:
        for name in set(sys.modules) - baseline:
            sys.modules.pop(name, None)
        sys.path[:] = previous_path
    if (
        not isinstance(identity_source, dict)
        or identity_source.get("prime_rl_commit") != LEGACY_SOURCE_REVISION
        or invocation.get("slurm_job_id") != SOURCE_JOB_ID
        or invocation.get("resume") is not False
        or selection.source_rows not in {1, 2}
        or selection.missing_rows + selection.harness_timeout_rows != 1
    ):
        fail("source_run_invalid")
    if validate_runtime_manifest(plan) != runtime_before or validate_source(plan) != source_before:
        fail("source_runtime_changed")
    return artifacts, {
        "source_rows": selection.source_rows,
        "retained_rows": 1,
        "missing_rows": selection.missing_rows,
        "harness_timeout_rows": selection.harness_timeout_rows,
    }


def acquire_writer_lock(run_dir: Path) -> tuple[Any, tuple[int, ...]]:
    path = run_dir / ".writer.lock"
    descriptor = -1
    try:
        if path.is_symlink() or path.resolve(strict=True) != path:
            fail("source_writer_lock_invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
        final = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != OWNER_UID
            or metadata.st_nlink != 1
            or _signature(metadata) != _signature(final)
        ):
            fail("source_writer_lock_invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = os.fstat(descriptor)
        final_locked = os.stat(path, follow_symlinks=False)
        if _signature(metadata) != _signature(locked) or _signature(locked) != _signature(final_locked):
            fail("source_writer_lock_changed")
        handle = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
    except BlockingIOError as error:
        raise RecoveryControlError("source_writer_active") from error
    except RecoveryControlError:
        raise
    except OSError as error:
        raise RecoveryControlError("source_writer_lock_invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return handle, _signature(metadata)


def validate_writer_lock_identity(run_dir: Path, handle: Any, expected_signature: tuple[int, ...]) -> None:
    path = run_dir / ".writer.lock"
    try:
        descriptor_signature = _signature(os.fstat(handle.fileno()))
        path_signature = _signature(os.stat(path, follow_symlinks=False))
    except OSError as error:
        raise RecoveryControlError("source_writer_lock_changed") from error
    if path.is_symlink() or descriptor_signature != expected_signature or path_signature != expected_signature:
        fail("source_writer_lock_changed")


def source_terminal_snapshot(plan: Mapping[str, Any], *, runner: Runner = run_command) -> dict[str, Any]:
    source = plan["source_smoke"]
    job_id = source["job_id"]
    queue = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--noheader",
                "--jobs",
                job_id,
                "--format=%A|%j|%T",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=3,
        code="source_queue_unavailable",
    )
    steps = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--steps",
                "--noheader",
                "--jobs",
                job_id,
                "--format=%i|%j|%T",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=3,
        code="source_steps_unavailable",
    )
    if queue or steps:
        fail("source_job_not_terminal")
    allocations = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,User,State,ExitCode,End,Restarts",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=7,
        code="source_accounting_unavailable",
    )
    all_rows = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "-j",
                job_id,
                "--format=JobIDRaw,State",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=2,
        code="source_accounting_unavailable",
    )
    if len(allocations) != 1:
        fail("source_job_identity_invalid")
    observed_id, name, user, raw_state, exit_code, ended_at, restarts = allocations[0]
    state = scheduler_state(raw_state)
    if (
        observed_id != job_id
        or name != source["job_name"]
        or user != OWNER
        or state not in RECOVERABLE_SOURCE_STATES
        or not exit_code
        or not ended_at
        or ended_at in {"Unknown", "N/A"}
        or restarts != "0"
        or not all_rows
        or any(
            (row_id != job_id and not row_id.startswith(f"{job_id}."))
            or scheduler_state(row_state) not in TERMINAL_STATES
            for row_id, row_state in all_rows
        )
    ):
        fail("source_job_identity_invalid")
    return {
        "state": state,
        "accounting_signature_sha256": sha256_bytes(
            canonical_json(sorted((row_id, scheduler_state(row_state)) for row_id, row_state in all_rows))
        ),
        "exit_code_sha256": sha256_bytes(exit_code.encode("utf-8")),
        "ended_at_sha256": sha256_bytes(ended_at.encode("utf-8")),
        "accounting_rows": len(all_rows),
        "queue_rows": 0,
        "step_queue_rows": 0,
        "restarts": 0,
    }


def certify_trigger(
    plan_path: Path,
    output_path: Path,
    *,
    runner: Runner = run_command,
    fetcher: Fetcher = fetch_http,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    invocation_validator: Callable[[Mapping[str, Any]], None] = validate_invocation,
) -> dict[str, Any]:
    """Publish a private trigger only after terminal and 120-second quiescence proof."""

    plan, plan_artifact = load_plan(plan_path)
    invocation_validator(plan)
    validate_runtime_manifest(plan)
    validate_source(plan)
    validate_external_inputs(plan)
    source_dir = Path(plan["source_smoke"]["run_dir"])
    lock, lock_signature = acquire_writer_lock(source_dir)
    started = clock()
    try:
        reference_digest: str | None = None
        reference_terminal: dict[str, Any] | None = None
        reference_route: dict[str, Any] | None = None
        counts: dict[str, int] | None = None
        terminal: dict[str, Any] | None = None
        route: dict[str, Any] | None = None
        for index in range(QUIESCENCE_SAMPLES):
            terminal = source_terminal_snapshot(plan, runner=runner)
            artifacts, observed_counts = validate_source_run(plan)
            route = route_idle_snapshot(plan, runner=runner, fetcher=fetcher)
            digest = _source_artifact_digest(artifacts)
            if reference_digest is None:
                reference_digest = digest
                counts = observed_counts
                reference_terminal = terminal
                reference_route = route
            elif (
                digest != reference_digest
                or observed_counts != counts
                or terminal != reference_terminal
                or route != reference_route
            ):
                fail("source_artifacts_changed")
            validate_writer_lock_identity(source_dir, lock, lock_signature)
            if index + 1 < QUIESCENCE_SAMPLES:
                sleeper(QUIESCENCE_INTERVAL_SECONDS)
        elapsed = clock() - started
        if elapsed < QUIESCENCE_MIN_SECONDS:
            fail("quiescence_interval_too_short")
        validate_runtime_manifest(plan)
        validate_source(plan)
        validate_external_inputs(plan)
        validate_writer_lock_identity(source_dir, lock, lock_signature)
        terminal = source_terminal_snapshot(plan, runner=runner)
        final_artifacts, final_counts = validate_source_run(plan)
        route = route_idle_snapshot(plan, runner=runner, fetcher=fetcher)
        validate_writer_lock_identity(source_dir, lock, lock_signature)
        if (
            _source_artifact_digest(final_artifacts) != reference_digest
            or final_counts != counts
            or terminal != reference_terminal
            or route != reference_route
        ):
            fail("source_artifacts_changed")
        if (
            counts is None
            or terminal is None
            or route is None
            or reference_digest is None
            or reference_terminal is None
            or reference_route is None
        ):
            fail("quiescence_evidence_incomplete")
        body = {
            "schema_version": SCHEMA_VERSION,
            "kind": TRIGGER_KIND,
            "state": "eligible",
            "mode": "fresh_two",
            "plan": plan_artifact.record,
            "source_job": {
                "job_id_sha256": sha256_bytes(SOURCE_JOB_ID.encode("ascii")),
                **terminal,
            },
            "source_artifacts_sha256": reference_digest,
            "source_counts": counts,
            "route": route,
            "quiescence": {
                "samples": QUIESCENCE_SAMPLES,
                "interval_seconds": QUIESCENCE_INTERVAL_SECONDS,
                "minimum_seconds": QUIESCENCE_MIN_SECONDS,
                "elapsed_milliseconds": int(elapsed * 1000),
                "writer_lock_identity_sha256": sha256_bytes(canonical_json(lock_signature)),
            },
            "policy": {
                "successful_smoke_certificate_forbidden": True,
                "legacy_rows_reused": 0,
                "resume": False,
                "tasks": EXPECTED_TASKS,
            },
        }
        raw = envelope(body, "trigger_sha256")
        parent = output_path.parent
        grandparent = parent.parent.resolve(strict=True)
        if (
            not output_path.is_absolute()
            or output_path != parent / "terminal_quiescence_gate.json"
            or parent != grandparent / parent.name
            or not parent.name.startswith("kimi_smoke_terminal_quiescence_")
            or os.path.lexists(parent)
        ):
            fail("trigger_namespace_not_fresh")
        _mkdir_fresh(parent)
        atomic_write_once(output_path, raw, mode=0o400)
        validate_writer_lock_identity(source_dir, lock, lock_signature)
        sync_directory(grandparent)
        stable_directory(parent, code="trigger_publication_invalid", mode=0o700)
        published = stable_file(output_path, code="trigger_publication_invalid", mode=0o400)
        if published.sha256 != sha256_bytes(raw):
            fail("trigger_publication_invalid")
        return {
            "state": "eligible",
            "mode": "fresh_two",
            "source_rows": counts["source_rows"],
            "retained_legacy_rows": 0,
            "tasks": EXPECTED_TASKS,
            "trigger_file_sha256": sha256_bytes(raw),
        }
    finally:
        lock.close()


def load_trigger(path: Path, *, plan: StableFile) -> tuple[dict[str, Any], StableFile]:
    stable_directory(path.parent, code="terminal_trigger_invalid", mode=0o700)
    value, artifact = strict_envelope(
        path,
        kind=TRIGGER_KIND,
        hash_field="trigger_sha256",
        code="terminal_trigger_invalid",
    )
    source_counts = value.get("source_counts")
    quiescence = value.get("quiescence")
    policy = value.get("policy")
    route = value.get("route")
    source_job = value.get("source_job")
    if (
        set(value)
        != {
            "kind",
            "mode",
            "plan",
            "policy",
            "quiescence",
            "route",
            "schema_version",
            "source_artifacts_sha256",
            "source_counts",
            "source_job",
            "state",
            "trigger_sha256",
        }
        or value.get("state") != "eligible"
        or value.get("mode") != "fresh_two"
        or value.get("plan") != plan.record
        or SHA_RE.fullmatch(str(value.get("source_artifacts_sha256", ""))) is None
        or source_counts
        not in (
            {"source_rows": 1, "retained_rows": 1, "missing_rows": 1, "harness_timeout_rows": 0},
            {"source_rows": 2, "retained_rows": 1, "missing_rows": 0, "harness_timeout_rows": 1},
        )
        or policy
        != {
            "successful_smoke_certificate_forbidden": True,
            "legacy_rows_reused": 0,
            "resume": False,
            "tasks": EXPECTED_TASKS,
        }
        or not isinstance(quiescence, dict)
        or quiescence.get("samples") != QUIESCENCE_SAMPLES
        or quiescence.get("interval_seconds") != QUIESCENCE_INTERVAL_SECONDS
        or quiescence.get("minimum_seconds") != QUIESCENCE_MIN_SECONDS
        or not isinstance(quiescence.get("elapsed_milliseconds"), int)
        or quiescence["elapsed_milliseconds"] < QUIESCENCE_MIN_SECONDS * 1000
        or SHA_RE.fullmatch(str(quiescence.get("writer_lock_identity_sha256", ""))) is None
        or not isinstance(route, dict)
        or route.get("routes") != EXPECTED_ROUTES
        or route.get("healthy") != EXPECTED_ROUTES
        or route.get("unhealthy") != 0
        or route.get("active") != 0
        or route.get("waiting") != 0
        or route.get("restart_count") != 0
        or SHA_RE.fullmatch(str(route.get("readiness_sha256", ""))) is None
        or SHA_RE.fullmatch(str(route.get("route_generation_sha256", ""))) is None
        or not isinstance(source_job, dict)
        or set(source_job)
        != {
            "accounting_rows",
            "accounting_signature_sha256",
            "ended_at_sha256",
            "exit_code_sha256",
            "job_id_sha256",
            "queue_rows",
            "restarts",
            "state",
            "step_queue_rows",
        }
        or set(route)
        != {
            "active",
            "healthy",
            "readiness_sha256",
            "restart_count",
            "route_generation_sha256",
            "routes",
            "unhealthy",
            "waiting",
        }
        or set(quiescence)
        != {
            "elapsed_milliseconds",
            "interval_seconds",
            "minimum_seconds",
            "samples",
            "writer_lock_identity_sha256",
        }
        or source_job.get("job_id_sha256") != sha256_bytes(SOURCE_JOB_ID.encode("ascii"))
        or source_job.get("state") not in RECOVERABLE_SOURCE_STATES
        or source_job.get("restarts") != 0
        or source_job.get("queue_rows") != 0
        or source_job.get("step_queue_rows") != 0
        or type(source_job.get("accounting_rows")) is not int
        or source_job["accounting_rows"] < 1
        or any(
            SHA_RE.fullmatch(str(source_job.get(field, ""))) is None
            for field in (
                "accounting_signature_sha256",
                "ended_at_sha256",
                "exit_code_sha256",
            )
        )
    ):
        fail("terminal_trigger_invalid")
    return value, artifact


def _mkdir_fresh(path: Path, *, mode: int = 0o700) -> None:
    parent_fd = -1
    try:
        parent = path.parent.resolve(strict=True)
        if not path.is_absolute() or path != parent / path.name or os.path.lexists(path):
            fail("launch_namespace_not_fresh")
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        parent_identity = _signature(os.fstat(parent_fd))[:2]
        os.mkdir(path.name, mode, dir_fd=parent_fd)
        os.chmod(path.name, mode, dir_fd=parent_fd, follow_symlinks=False)
        os.fsync(parent_fd)
        child_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        try:
            child_metadata = os.fstat(child_fd)
        finally:
            os.close(child_fd)
        fresh_parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if _signature(os.fstat(fresh_parent_fd))[:2] != parent_identity:
                fail("launch_parent_changed")
        finally:
            os.close(fresh_parent_fd)
        if (
            not stat.S_ISDIR(child_metadata.st_mode)
            or stat.S_IMODE(child_metadata.st_mode) != mode
            or child_metadata.st_uid != OWNER_UID
        ):
            fail("launch_namespace_invalid")
        stable_directory(path, code="launch_namespace_invalid", mode=mode)
    except RecoveryControlError:
        raise
    except OSError as error:
        raise RecoveryControlError("launch_namespace_not_fresh") from error
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _environment_bytes(values: Mapping[str, str]) -> bytes:
    if (
        not values
        or any(not key or "=" in key or "\x00" in key for key in values)
        or any("\x00" in value for value in values.values())
    ):
        fail("slurm_environment_invalid")
    return b"\0".join(f"{key}={value}".encode("utf-8") for key, value in sorted(values.items())) + b"\0"


def _launch_environment(
    plan: Mapping[str, Any],
    *,
    plan_artifact: StableFile,
    review_artifact: StableFile,
    trigger_artifact: StableFile,
    authorization_path: Path,
    permit_path: Path,
    submission_path: Path,
    job_name: str,
    token: str,
) -> dict[str, str]:
    recovery = plan["recovery"]
    runtime = plan["runtime"]
    auth = runtime["auth"]
    return {
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": OWNER,
        "PATH": "/usr/bin:/bin",
        "USER": OWNER,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "UV_NO_CONFIG": "1",
        "PROJECT_DIR": recovery["project_root"],
        "EVAL_EXPECTED_PRIME_RL_REVISION": recovery["source_revision"],
        "EVAL_EXPECTED_MODEL": "Kimi-K3",
        "EVAL_DEPLOYMENT_ID": recovery["deployment_id"],
        "EVAL_DATASET_ARCHIVE": recovery["dataset_archive"]["path"],
        "EVAL_DATASET_ARCHIVE_SHA256": recovery["dataset_archive"]["sha256"],
        "EVAL_DATASET_CONTENT_SHA256": recovery["dataset_content_sha256"],
        "INFERENCE_DEPLOYMENT_SPEC": recovery["deployment_spec"]["path"],
        "INFERENCE_DEPLOYMENT_SPEC_SHA256": recovery["deployment_spec"]["sha256"],
        "INFERENCE_READINESS_CHECKPOINT": recovery["readiness_checkpoint"]["path"],
        "INFERENCE_READINESS_CHECKPOINT_SHA256": recovery["readiness_checkpoint"]["sha256"],
        "INFERENCE_PROXY_INFO": recovery["proxy_info"]["path"],
        "INFERENCE_PROXY_INFO_SHA256": recovery["proxy_info"]["sha256"],
        "OUTPUT_DIR": recovery["output_dir"],
        "KIMI_SMOKE_RECOVERY_MODE": "fresh-two",
        "VACLI_BIN": runtime["vacli"]["path"],
        "VACLI_LEASE_RETRIES": "20",
        "VACLI_MAX_CONCURRENT_LEASES": "2",
        "VACLI_MAX_PULL_RETRIES": "20",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": "3600",
        "VACLI_CONTAINER_PRIVILEGED": "1",
        "PYTHON_BIN_X86_64": runtime["python"]["path"],
        "PYTHON_BIN_X86_64_SHA256": runtime["python"]["sha256"],
        "PYTHON_SITE_X86_64": strict_envelope(
            Path(runtime["manifest"]["path"]),
            kind=RUNTIME_KIND,
            hash_field="manifest_sha256",
            code="runtime_manifest_invalid",
        )[0]["root"],
        "UV_BIN_X86_64": runtime["uv"]["path"],
        "UV_BIN_X86_64_SHA256": runtime["uv"]["sha256"],
        "VACLI_BIN_SHA256": runtime["vacli"]["sha256"],
        "RECOVERY_RUNTIME_MANIFEST_SHA256": runtime["manifest"]["sha256"],
        "THRIFT_TLS_CL_CERT_PATH": auth["certificate"]["path"],
        "THRIFT_TLS_CL_KEY_PATH": auth["private_key"]["path"],
        "RECOVERY_PLAN": str(plan_artifact.path),
        "RECOVERY_PLAN_SHA256": plan_artifact.sha256,
        "RECOVERY_REVIEW": str(review_artifact.path),
        "RECOVERY_REVIEW_SHA256": review_artifact.sha256,
        "RECOVERY_TRIGGER": str(trigger_artifact.path),
        "RECOVERY_TRIGGER_SHA256": trigger_artifact.sha256,
        "RECOVERY_AUTHORIZATION": str(authorization_path),
        "RECOVERY_ACTIVATION_PERMIT": str(permit_path),
        "RECOVERY_SUBMISSION_RECEIPT": str(submission_path),
        "RECOVERY_EXPECTED_JOB_NAME": job_name,
        "RECOVERY_LAUNCH_TOKEN": token,
        "RECOVERY_ADMISSION_TIMEOUT_SECONDS": str(ADMISSION_TIMEOUT_SECONDS),
        "RECOVERY_CONTROLLER_SHA256": recovery["controller"]["sha256"],
        "RECOVERY_JOB_WRAPPER_SHA256": recovery["job_wrapper"]["sha256"],
        "RECOVERY_WRAPPER_SHA256": recovery["recovery_wrapper"]["sha256"],
    }


def scheduler_name_matches(
    job_name: str,
    *,
    runner: Runner = run_command,
) -> list[str]:
    rows = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--noheader",
                "--user",
                OWNER,
                "--name",
                job_name,
                "--format=%A|%j",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=2,
        code="scheduler_name_query_unavailable",
    )
    candidates = [row[0] for row in rows if row[1] == job_name and JOB_RE.fullmatch(row[0])]
    if len(candidates) != len(rows):
        fail("scheduler_name_query_invalid")
    accounting = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--starttime",
                datetime.now(UTC).date().isoformat(),
                "--name",
                job_name,
                "--allocations",
                "--format=JobIDRaw,JobName",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=2,
        code="scheduler_name_query_unavailable",
    )
    for job_id, observed_name in accounting:
        if observed_name != job_name or JOB_RE.fullmatch(job_id) is None:
            fail("scheduler_name_query_invalid")
        candidates.append(job_id)
    return sorted(set(candidates), key=int)


def _sbatch_command(plan: Mapping[str, Any], job_name: str, environment_file: Path) -> list[str]:
    recovery = plan["recovery"]
    return [
        "/usr/bin/sbatch",
        "-M",
        CLUSTER,
        "--parsable",
        "--hold",
        f"--job-name={job_name}",
        f"--chdir={recovery['project_root']}",
        "--partition=cpu_x86",
        "--qos=cpu_x86_lowest",
        "--account=ram",
        "--time=2-00:00:00",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=8",
        "--mem=16G",
        "--no-requeue",
        f"--output={Path(recovery['log_dir']) / 'recovery_%j.log'}",
        f"--error={Path(recovery['log_dir']) / 'recovery_%j.log'}",
        "--open-mode=truncate",
        f"--export-file={environment_file}",
        recovery["job_wrapper"]["path"],
    ]


def invoke_sbatch(command: Sequence[str]) -> tuple[str, int, str]:
    """Run the sole sbatch call in a bounded process group."""

    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_command_environment(),
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        raise RecoveryControlError("sbatch_start_failed") from error
    outcome = "completed"
    try:
        stdout, stderr = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        outcome = "timeout"
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=10)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RecoveryControlError("sbatch_cleanup_unproven") from error
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    except BaseException as primary:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
        cleanup_error: BaseException | None = None
        try:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
        except BaseException as error:
            cleanup_error = error
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        if cleanup_error is not None:
            primary.add_note("sbatch_cleanup_unproven")
        raise
    if process.poll() is None:
        fail("sbatch_cleanup_unproven")
    if len(stdout) > 4096 or len(stderr) > 4096:
        fail("sbatch_output_oversize")
    return outcome, int(process.returncode), stdout


def parse_sbatch_response(outcome: str, returncode: int, stdout: str) -> str | None:
    lines = stdout.splitlines()
    if outcome == "completed" and returncode == 0 and len(lines) == 1:
        fields = lines[0].split(";", 1)
        if JOB_RE.fullmatch(fields[0]) is not None and (len(fields) == 1 or fields[1] == CLUSTER):
            return fields[0]
    return None


def resolve_submission_visibility(
    job_name: str,
    direct_candidate: str | None,
    *,
    runner: Runner,
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
) -> tuple[str | None, dict[str, int]]:
    """Resolve a submission without ever controlling a name-only candidate."""

    deadline = clock() + 60
    polls = 0
    zero_rounds = 0
    while clock() < deadline:
        matches = scheduler_name_matches(job_name, runner=runner)
        polls += 1
        if direct_candidate is not None:
            if matches == [direct_candidate]:
                return direct_candidate, {"polls": polls, "zero_rounds": zero_rounds}
            if matches and matches != [direct_candidate]:
                fail("sbatch_submission_ambiguous")
        else:
            if len(matches) == 1:
                return matches[0], {"polls": polls, "zero_rounds": zero_rounds}
            if len(matches) > 1:
                fail("sbatch_submission_ambiguous")
            zero_rounds += 1
            if zero_rounds >= TERMINAL_PROOF_ROUNDS:
                return None, {"polls": polls, "zero_rounds": zero_rounds}
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    if direct_candidate is not None:
        fail("sbatch_submission_visibility_unproven")
    fail("sbatch_submission_ambiguity_unresolved")


def _identity_mismatches(
    record: Mapping[str, str],
    plan: Mapping[str, Any],
    job_id: str,
    job_name: str,
    *,
    held: bool,
) -> tuple[set[str], set[str], str]:
    recovery = plan["recovery"]
    expected = {
        "JobId": job_id,
        "JobName": job_name,
        "UserId": EXPECTED_USER_ID,
        "Command": recovery["job_wrapper"]["path"],
        "WorkDir": recovery["project_root"],
        "StdOut": str(Path(recovery["log_dir"]) / f"recovery_{job_id}.log"),
        "StdErr": str(Path(recovery["log_dir"]) / f"recovery_{job_id}.log"),
        "Account": "ram",
        "Partition": "cpu_x86",
        "QOS": "cpu_x86_lowest",
        "TimeLimit": "2-00:00:00",
        "NumCPUs": "8",
        "NumNodes": "1-1" if held else "1",
        "Requeue": "0",
        "Restarts": "0",
    }
    mismatches = {key for key, expected_value in expected.items() if record.get(key) != expected_value}
    conflicts = {
        key
        for key in ("Command", "JobId", "JobName", "UserId", "WorkDir")
        if record.get(key) not in {None, "", expected[key]}
    }
    state = scheduler_state(record.get("JobState", ""))
    if held:
        if (
            state != "PENDING"
            or record.get("Reason") != "JobHeldUser"
            or record.get("Priority") != "0"
            or record.get("StartTime") != "Unknown"
            or record.get("NodeList") not in {None, ""}
            or record.get("BatchHost") not in {None, "(null)"}
        ):
            mismatches.add("held_state")
    else:
        node_list = record.get("NodeList")
        if (
            state != "RUNNING"
            or not isinstance(node_list, str)
            or NODELIST_RE.fullmatch(node_list) is None
            or node_list in {"N/A", "None", "Unknown"}
            or record.get("Reason") == "JobHeldUser"
        ):
            mismatches.add("activation_state")
    mismatches.update(conflicts)
    return mismatches, conflicts, state


def _scheduler_phase_evidence(
    plan: Mapping[str, Any],
    job_id: str,
    job_name: str,
    *,
    held: bool,
    runner: Runner,
) -> tuple[set[str], set[str], str]:
    """Return aggregate mismatches for one full identity/queue/accounting view."""

    record = scontrol_record(job_id, runner=runner)
    mismatches, conflicts, state = _identity_mismatches(record, plan, job_id, job_name, held=held)
    queue = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--noheader",
                "--jobs",
                job_id,
                "--format=%A|%j|%u|%T|%r|%D|%N",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=7,
        code="scheduler_phase_unavailable",
    )
    allocations = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,User,State,Start,NodeList,Restarts",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=7,
        code="scheduler_phase_unavailable",
    )
    all_rows = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "-j",
                job_id,
                "--format=JobIDRaw,State",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=2,
        code="scheduler_phase_unavailable",
    )
    if len(queue) != 1:
        mismatches.add("queue_cardinality")
    else:
        queue_id, queue_name, queue_user, queue_state, reason, nodes, node_list = queue[0]
        for field, observed, expected in (
            ("JobId", queue_id, job_id),
            ("JobName", queue_name, job_name),
            ("UserId", queue_user, OWNER),
        ):
            if observed != expected:
                mismatches.add(f"queue_{field}")
                conflicts.add(field)
        if held:
            if (
                scheduler_state(queue_state) != "PENDING"
                or reason != "JobHeldUser"
                or nodes != "1"
                or node_list not in {"", "(null)", "N/A"}
            ):
                mismatches.add("held_queue")
        elif scheduler_state(queue_state) != "RUNNING" or nodes != "1" or NODELIST_RE.fullmatch(node_list) is None:
            mismatches.add("activation_queue")
    if len(allocations) != 1:
        mismatches.add("accounting_cardinality")
    else:
        allocation_id, allocation_name, user, raw_state, started, node_list, restarts = allocations[0]
        for field, observed, expected in (
            ("JobId", allocation_id, job_id),
            ("JobName", allocation_name, job_name),
            ("UserId", user, OWNER),
        ):
            if observed != expected:
                mismatches.add(f"accounting_{field}")
                conflicts.add(field)
        accounting_state = scheduler_state(raw_state)
        if held:
            if (
                accounting_state != "PENDING"
                or started not in {"", "Unknown", "N/A"}
                or node_list not in {"", "(null)", "N/A"}
                or restarts != "0"
            ):
                mismatches.add("held_accounting")
        elif (
            accounting_state != "RUNNING"
            or started in {"", "Unknown", "N/A"}
            or NODELIST_RE.fullmatch(node_list) is None
            or restarts != "0"
        ):
            mismatches.add("activation_accounting")
    if held:
        if len(all_rows) != 1 or all_rows[0][0] != job_id or scheduler_state(all_rows[0][1]) != "PENDING":
            mismatches.add("held_steps")
    elif (
        not all_rows
        or all_rows[0][0] != job_id
        or scheduler_state(all_rows[0][1]) != "RUNNING"
        or any(
            (row_id != job_id and not row_id.startswith(f"{job_id}."))
            or scheduler_state(row_state) not in ACTIVE_STATES
            for row_id, row_state in all_rows
        )
    ):
        mismatches.add("activation_steps")
    mismatches.update(conflicts)
    return mismatches, conflicts, state


def _poll_identity(
    plan: Mapping[str, Any],
    job_id: str,
    job_name: str,
    *,
    held: bool,
    timeout: int,
    runner: Runner,
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, Any]:
    deadline = clock() + timeout
    consecutive = 0
    polls = 0
    observed: Counter[str] = Counter()
    conflicts: set[str] = set()
    final: set[str] = set()
    state = "UNKNOWN"
    max_iterations = timeout // POLL_SECONDS + 2
    while clock() < deadline and polls < max_iterations:
        try:
            mismatches, current_conflicts, state = _scheduler_phase_evidence(
                plan, job_id, job_name, held=held, runner=runner
            )
        except RecoveryControlError:
            mismatches = {"scheduler_phase_unavailable"}
            current_conflicts = set()
        polls += 1
        observed.update(mismatches)
        final = set(mismatches)
        conflicts.update(current_conflicts)
        if conflicts:
            break
        consecutive = consecutive + 1 if not mismatches else 0
        if consecutive >= 2:
            return {
                "converged": True,
                "polls": polls,
                "elapsed_milliseconds": int((timeout - max(0.0, deadline - clock())) * 1000),
                "mismatch_fields": sorted(observed),
                "mismatch_occurrences": dict(sorted(observed.items())),
                "final_mismatch_fields": [],
                "explicit_conflict_fields": [],
                "state": state,
            }
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    return {
        "converged": False,
        "polls": polls,
        "elapsed_milliseconds": int((timeout - max(0.0, deadline - clock())) * 1000),
        "mismatch_fields": sorted(observed),
        "mismatch_occurrences": dict(sorted(observed.items())),
        "final_mismatch_fields": sorted(final),
        "explicit_conflict_fields": sorted(conflicts),
        "state": state,
    }


def validate_phase_certificate(value: Any, *, state: str, timeout: int) -> None:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "converged",
            "elapsed_milliseconds",
            "explicit_conflict_fields",
            "final_mismatch_fields",
            "mismatch_fields",
            "mismatch_occurrences",
            "polls",
            "state",
        }
        or value.get("converged") is not True
        or value.get("state") != state
        or type(value.get("polls")) is not int
        or value["polls"] < 2
        or type(value.get("elapsed_milliseconds")) is not int
        or not 0 <= value["elapsed_milliseconds"] <= timeout * 1000
        or value.get("explicit_conflict_fields") != []
        or value.get("final_mismatch_fields") != []
        or not isinstance(value.get("mismatch_fields"), list)
        or any(not isinstance(item, str) or not item for item in value["mismatch_fields"])
        or not isinstance(value.get("mismatch_occurrences"), dict)
        or set(value["mismatch_occurrences"]) != set(value["mismatch_fields"])
        or any(type(count) is not int or count <= 0 for count in value["mismatch_occurrences"].values())
    ):
        fail("scheduler_phase_certificate_invalid")


def _terminal_snapshot(
    job_id: str,
    job_name: str,
    plan: Mapping[str, Any],
    *,
    runner: Runner,
) -> tuple[str, str, tuple[tuple[str, str], ...], tuple[str, ...]]:
    conflicts: set[str] = set()
    try:
        record = scontrol_record(job_id, runner=runner)
    except RecoveryControlError:
        record = None
    if record is not None:
        for field, expected in (
            ("JobId", job_id),
            ("JobName", job_name),
            ("UserId", EXPECTED_USER_ID),
            ("Command", plan["recovery"]["job_wrapper"]["path"]),
            ("WorkDir", plan["recovery"]["project_root"]),
        ):
            observed = record.get(field)
            if observed not in {None, "", expected}:
                conflicts.add(field)
    queue = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--noheader",
                "--jobs",
                job_id,
                "--format=%A|%j|%u",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=3,
        code="terminal_queue_unavailable",
    )
    for observed_id, observed_name, observed_user in queue:
        if observed_id != job_id:
            conflicts.add("JobId")
        if observed_name != job_name:
            conflicts.add("JobName")
        if observed_user != OWNER:
            conflicts.add("UserId")
    allocations = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,User,State",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=4,
        code="terminal_accounting_unavailable",
    )
    all_rows = _parse_pipe_rows(
        runner(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "-j",
                job_id,
                "--format=JobIDRaw,State",
            ],
            COMMAND_TIMEOUT_SECONDS,
        ),
        width=2,
        code="terminal_accounting_unavailable",
    )
    for observed_id, observed_name, observed_user, _state in allocations:
        if observed_id != job_id:
            conflicts.add("JobId")
        if observed_name != job_name:
            conflicts.add("JobName")
        if observed_user != OWNER:
            conflicts.add("UserId")
    for observed_id, _state in all_rows:
        if observed_id != job_id and not observed_id.startswith(f"{job_id}."):
            conflicts.add("JobId")
    if conflicts:
        return "conflict", "UNKNOWN", (), tuple(sorted(conflicts))
    if queue:
        return "active", "UNKNOWN", (), ()
    if len(allocations) != 1 or allocations[0][:3] != [job_id, job_name, OWNER] or not all_rows:
        return "incomplete", "UNKNOWN", (), ()
    state = scheduler_state(allocations[0][3])
    signature = tuple((row[0], scheduler_state(row[1])) for row in all_rows)
    if state in TERMINAL_STATES and all(item[1] in TERMINAL_STATES for item in signature):
        return "terminal", state, signature, ()
    return "active", state, signature, ()


def cancel_and_prove(
    job_id: str,
    job_name: str,
    plan: Mapping[str, Any],
    *,
    direct_provenance: bool,
    runner: Runner = run_command,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Cancel at most one exact-ID candidate and prove all its steps terminal."""

    identity_deadline = clock() + CANCEL_IDENTITY_TIMEOUT_SECONDS
    conflicts: set[str] = set()
    identity_exact = False
    identity_polls = 0
    while clock() < identity_deadline:
        try:
            record = scontrol_record(job_id, runner=runner)
        except RecoveryControlError:
            record = None
        identity_polls += 1
        if record is not None:
            missing = False
            for field, expected in (
                ("JobId", job_id),
                ("JobName", job_name),
                ("UserId", EXPECTED_USER_ID),
                ("Command", plan["recovery"]["job_wrapper"]["path"]),
                ("WorkDir", plan["recovery"]["project_root"]),
            ):
                observed = record.get(field)
                if observed in {None, ""}:
                    missing = True
                elif observed != expected:
                    conflicts.add(field)
            if conflicts:
                break
            if not missing:
                identity_exact = True
                break
        remaining = identity_deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    if conflicts or (not identity_exact and not direct_provenance):
        raise LifecycleError(
            "cancellation_unconfirmed",
            cancellation={
                "identity_status": "conflict" if conflicts else "unavailable",
                "identity_polls": identity_polls,
                "explicit_conflict_fields": sorted(conflicts),
                "cancel_attempts": 0,
            },
        )
    pre_status, pre_state, _pre_signature, pre_conflicts = _terminal_snapshot(job_id, job_name, plan, runner=runner)
    if pre_conflicts:
        raise LifecycleError(
            "cancellation_unconfirmed",
            cancellation={
                "identity_status": "conflict",
                "identity_polls": identity_polls,
                "explicit_conflict_fields": list(pre_conflicts),
                "cancel_attempts": 0,
            },
        )
    cancel_attempts = 0
    cancel_outcome = "not_needed"
    if pre_status != "terminal":
        cancel_attempts = 1
        result = runner(
            ["/usr/bin/scancel", "-M", CLUSTER, job_id],
            COMMAND_TIMEOUT_SECONDS,
        )
        cancel_outcome = (
            "completed" if result.returncode == 0 and not result.stdout and not result.stderr else "nonzero"
        )
    deadline = clock() + CANCEL_TERMINAL_TIMEOUT_SECONDS
    consecutive = 0
    previous: tuple[tuple[str, str], ...] | None = None
    polls = 0
    final_state = pre_state
    while clock() < deadline:
        status, state, signature, terminal_conflicts = _terminal_snapshot(job_id, job_name, plan, runner=runner)
        polls += 1
        final_state = state
        if terminal_conflicts:
            raise LifecycleError(
                "cancellation_unconfirmed",
                cancellation={
                    "identity_status": "conflict",
                    "identity_polls": identity_polls,
                    "explicit_conflict_fields": list(terminal_conflicts),
                    "cancel_attempts": cancel_attempts,
                    "cancel_command_outcome": cancel_outcome,
                },
            )
        consecutive = consecutive + 1 if status == "terminal" and signature == previous else int(status == "terminal")
        previous = signature if status == "terminal" else None
        if consecutive >= TERMINAL_PROOF_ROUNDS:
            return {
                "identity_status": "exact" if identity_exact else "direct_provenance_fallback",
                "identity_polls": identity_polls,
                "explicit_conflict_fields": [],
                "cancel_attempts": cancel_attempts,
                "cancel_command_outcome": cancel_outcome,
                "terminal_state": final_state,
                "terminal_polls": polls,
                "terminal_consecutive": consecutive,
            }
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(POLL_SECONDS, remaining))
    raise LifecycleError(
        "cancellation_unconfirmed",
        cancellation={
            "identity_status": "exact" if identity_exact else "direct_provenance_fallback",
            "identity_polls": identity_polls,
            "explicit_conflict_fields": [],
            "cancel_attempts": cancel_attempts,
            "cancel_command_outcome": cancel_outcome,
            "terminal_state": final_state,
            "terminal_polls": polls,
            "terminal_consecutive": consecutive,
        },
    )


def _reservation_paths(plan: Mapping[str, Any]) -> dict[str, Path]:
    reservation = Path(plan["recovery"]["reservation_dir"])
    return {
        "root": reservation,
        "intent": reservation / "launch_intent.json",
        "environment": reservation / "slurm_environment.bin",
        "authorization": reservation / "held_authorization.json",
        "permit": reservation / "activation_permit.json",
        "receipt": reservation / "submission_receipt.json",
        "failure": reservation / "submission_failure.json",
    }


def _publish_reservation_file(path: Path, body: Mapping[str, Any], hash_field: str) -> tuple[str, bytes]:
    raw = envelope(body, hash_field)
    digest = atomic_write_once(path, raw, mode=0o400)
    return digest, raw


def _validate_trigger_current(
    plan: Mapping[str, Any],
    trigger: Mapping[str, Any],
    *,
    runner: Runner,
    fetcher: Fetcher,
) -> None:
    run_dir = Path(plan["source_smoke"]["run_dir"])
    lock, lock_signature = acquire_writer_lock(run_dir)
    try:
        expected_lock_sha = trigger.get("quiescence", {}).get("writer_lock_identity_sha256")
        if sha256_bytes(canonical_json(lock_signature)) != expected_lock_sha:
            fail("terminal_trigger_stale")
        validate_writer_lock_identity(run_dir, lock, lock_signature)
        terminal = source_terminal_snapshot(plan, runner=runner)
        artifacts, counts = validate_source_run(plan)
        route = route_idle_snapshot(plan, runner=runner, fetcher=fetcher)
        validate_writer_lock_identity(run_dir, lock, lock_signature)
        trigger_terminal = {
            key: value for key, value in trigger.get("source_job", {}).items() if key != "job_id_sha256"
        }
        if (
            terminal != trigger_terminal
            or _source_artifact_digest(artifacts) != trigger.get("source_artifacts_sha256")
            or counts != trigger.get("source_counts")
            or route != trigger.get("route")
        ):
            fail("terminal_trigger_stale")
    finally:
        lock.close()


def _static_digest(plan: Mapping[str, Any]) -> dict[str, str]:
    return {
        "runtime": sha256_bytes(canonical_json(validate_runtime_manifest(plan))),
        "source": sha256_bytes(canonical_json(validate_source(plan))),
        "inputs": sha256_bytes(canonical_json(validate_external_inputs(plan))),
    }


def _authorization_body(
    *,
    plan_artifact: StableFile,
    review_artifact: StableFile,
    trigger_artifact: StableFile,
    token: str,
    job_name: str,
    static: Mapping[str, str],
    job_id: str,
    held: Mapping[str, Any],
    intent: StableFile,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": AUTHORIZATION_KIND,
        "state": "held_authorized",
        "plan": plan_artifact.record,
        "review": review_artifact.record,
        "trigger": trigger_artifact.record,
        "launch_token_sha256": sha256_bytes(token.encode("ascii")),
        "job": {"cluster": CLUSTER, "id": job_id, "name": job_name},
        "job_id_sha256": sha256_bytes(job_id.encode("ascii")),
        "job_name_sha256": sha256_bytes(job_name.encode("ascii")),
        "intent": intent.record,
        "held": dict(held),
        "static": dict(static),
        "policy": {"fresh_two_only": True, "resume": False, "legacy_rows_reused": 0},
    }


def _permit_body(*, authorization: StableFile, job_name: str, static: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": PERMIT_KIND,
        "state": "activated",
        "authorization": authorization.record,
        "job_name_sha256": sha256_bytes(job_name.encode("ascii")),
        "static": dict(static),
        "policy": {"fresh_two_only": True, "resume": False, "legacy_rows_reused": 0},
    }


def _seal_reservation(path: Path) -> None:
    sync_directory(path)
    os.chmod(path, 0o500, follow_symlinks=False)
    sync_directory(path)
    sync_directory(path.parent)
    stable_directory(path, code="reservation_seal_failed", mode=0o500)


def _publish_failure(
    paths: Mapping[str, Path],
    *,
    code: str,
    plan_artifact: StableFile,
    review_artifact: StableFile,
    trigger_artifact: StableFile,
    cancellation: Mapping[str, Any] | None,
    lifecycle: Mapping[str, Any] | None,
) -> str:
    try:
        root_mode = stat.S_IMODE(paths["root"].stat(follow_symlinks=False).st_mode)
    except OSError as error:
        raise RecoveryControlError("failure_publication_conflict") from error
    if root_mode == 0o500:
        fail("failure_publication_conflict")
    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": FAILURE_KIND,
        "state": "failed",
        "code": code if SAFE_CODE_RE.fullmatch(code) else "recovery_control_failed",
        "plan": plan_artifact.record,
        "review": review_artifact.record,
        "trigger": trigger_artifact.record,
        "cancellation": dict(cancellation or {}),
        "lifecycle": dict(lifecycle or {}),
        "promotion_authorized": False,
    }
    digest, _ = _publish_reservation_file(paths["failure"], body, "failure_sha256")
    _seal_reservation(paths["root"])
    return digest


def launch(
    plan_path: Path,
    review_path: Path,
    trigger_path: Path,
    *,
    runner: Runner = run_command,
    fetcher: Fetcher = fetch_http,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    sbatch_invoker: Callable[[Sequence[str]], tuple[str, int, str]] = invoke_sbatch,
    invocation_validator: Callable[[Mapping[str, Any]], None] = validate_invocation,
) -> dict[str, Any]:
    """Submit exactly one held fresh-two job and commit admission after revalidation."""

    plan, plan_artifact = load_plan(plan_path)
    invocation_validator(plan)
    controller = stable_file(Path(plan["recovery"]["controller"]["path"]), code="controller_invalid", mode=0o500)
    wrapper = stable_file(Path(plan["recovery"]["job_wrapper"]["path"]), code="job_wrapper_invalid", mode=0o500)
    if (
        controller.sha256 != plan["recovery"]["controller"]["sha256"]
        or wrapper.sha256 != plan["recovery"]["job_wrapper"]["sha256"]
    ):
        fail("launch_code_changed")
    trigger, trigger_artifact = load_trigger(trigger_path, plan=plan_artifact)
    review_artifact = load_review(
        review_path,
        plan=plan_artifact,
        trigger=trigger_artifact,
        controller_sha256=controller.sha256,
        wrapper_sha256=wrapper.sha256,
    )
    _validate_trigger_current(plan, trigger, runner=runner, fetcher=fetcher)
    static = _static_digest(plan)
    recovery = plan["recovery"]
    for path in (Path(recovery["output_dir"]), Path(recovery["reservation_dir"]), Path(recovery["log_dir"])):
        if os.path.lexists(path):
            fail("launch_namespace_not_fresh")
    paths = _reservation_paths(plan)
    job_id: str | None = None
    job_name: str | None = None
    direct_provenance = False
    committed = False
    held_evidence: Mapping[str, Any] | None = None
    held_after_authorization_evidence: Mapping[str, Any] | None = None
    activation_evidence: Mapping[str, Any] | None = None
    submission_visibility: Mapping[str, Any] | None = None
    release_outcome = "not_attempted"
    handled_signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous_handlers: dict[signal.Signals, Any] = {}

    def interrupted(signum: int, _frame: Any) -> None:
        if not committed:
            raise LaunchInterrupted(signum)

    for handled_signal in handled_signals:
        previous_handlers[handled_signal] = signal.signal(handled_signal, interrupted)
    try:
        _mkdir_fresh(paths["root"])
        _mkdir_fresh(Path(recovery["log_dir"]))
        token = secrets.token_hex(12)
        job_name = f"k3-smoke-recovery-{token}"
        if scheduler_name_matches(job_name, runner=runner):
            fail("scheduler_name_not_fresh")
        environment = _launch_environment(
            plan,
            plan_artifact=plan_artifact,
            review_artifact=review_artifact,
            trigger_artifact=trigger_artifact,
            authorization_path=paths["authorization"],
            permit_path=paths["permit"],
            submission_path=paths["receipt"],
            job_name=job_name,
            token=token,
        )
        environment_raw = _environment_bytes(environment)
        intent = {
            "schema_version": SCHEMA_VERSION,
            "kind": INTENT_KIND,
            "state": "reserved",
            "plan": plan_artifact.record,
            "review": review_artifact.record,
            "trigger": trigger_artifact.record,
            "job_name_sha256": sha256_bytes(job_name.encode("ascii")),
            "launch_token_sha256": sha256_bytes(token.encode("ascii")),
            "environment_sha256": sha256_bytes(environment_raw),
            "static": static,
            "policy": {"held_submission": True, "launches": 1, "fresh_two_only": True},
        }
        intent_sha, _ = _publish_reservation_file(paths["intent"], intent, "intent_sha256")
        atomic_write_once(paths["environment"], environment_raw, mode=0o400)
        _validate_trigger_current(plan, trigger, runner=runner, fetcher=fetcher)
        if _static_digest(plan) != static:
            fail("static_bindings_changed")
        if os.path.lexists(recovery["output_dir"]):
            fail("launch_namespace_not_fresh")
        if scheduler_name_matches(job_name, runner=runner):
            fail("scheduler_name_not_fresh")
        if (
            stable_file(controller.path, code="controller_changed", mode=0o500).sha256 != controller.sha256
            or stable_file(wrapper.path, code="job_wrapper_changed", mode=0o500).sha256 != wrapper.sha256
        ):
            fail("launch_code_changed")
        outcome, returncode, stdout = sbatch_invoker(_sbatch_command(plan, job_name, paths["environment"]))
        candidate = parse_sbatch_response(outcome, returncode, stdout)
        direct_provenance = candidate is not None
        job_id, visibility = resolve_submission_visibility(
            job_name,
            candidate,
            runner=runner,
            sleeper=sleeper,
            clock=clock,
        )
        submission_visibility = visibility
        if job_id is None:
            if outcome == "completed" and returncode == 0:
                fail("sbatch_success_without_job")
            fail("sbatch_submission_failed")

        held = _poll_identity(
            plan,
            job_id,
            job_name,
            held=True,
            timeout=HELD_TIMEOUT_SECONDS,
            runner=runner,
            sleeper=sleeper,
            clock=clock,
        )
        held_evidence = held
        if held["explicit_conflict_fields"]:
            raise LifecycleError("scheduler_identity_conflict")
        if held["converged"] is not True:
            raise LifecycleError("held_identity_not_converged")
        validate_phase_certificate(held, state="PENDING", timeout=HELD_TIMEOUT_SECONDS)
        _validate_trigger_current(plan, trigger, runner=runner, fetcher=fetcher)
        if _static_digest(plan) != static:
            raise LifecycleError("static_bindings_changed")
        if os.path.lexists(recovery["output_dir"]):
            raise LifecycleError("launch_namespace_not_fresh")
        intent_artifact = stable_file(paths["intent"], code="launch_intent_changed", mode=0o400)
        authorization_body = _authorization_body(
            plan_artifact=plan_artifact,
            review_artifact=review_artifact,
            trigger_artifact=trigger_artifact,
            token=token,
            job_name=job_name,
            static=static,
            job_id=job_id,
            held=held,
            intent=intent_artifact,
        )
        authorization_sha, authorization_raw = _publish_reservation_file(
            paths["authorization"], authorization_body, "authorization_sha256"
        )
        held_after = _poll_identity(
            plan,
            job_id,
            job_name,
            held=True,
            timeout=10,
            runner=runner,
            sleeper=sleeper,
            clock=clock,
        )
        held_after_authorization_evidence = held_after
        if held_after["converged"] is not True or held_after["explicit_conflict_fields"]:
            raise LifecycleError("held_state_lost_after_authorization")
        validate_phase_certificate(held_after, state="PENDING", timeout=10)
        release_result = runner(
            ["/usr/bin/scontrol", "-M", CLUSTER, "release", job_id],
            COMMAND_TIMEOUT_SECONDS,
        )
        release_outcome = (
            "completed"
            if release_result.returncode == 0 and not release_result.stdout and not release_result.stderr
            else "nonzero"
        )
        if release_outcome != "completed":
            raise LifecycleError("release_failed")
        activation = _poll_identity(
            plan,
            job_id,
            job_name,
            held=False,
            timeout=ACTIVATION_TIMEOUT_SECONDS,
            runner=runner,
            sleeper=sleeper,
            clock=clock,
        )
        activation_evidence = activation
        if activation["explicit_conflict_fields"]:
            raise LifecycleError("scheduler_identity_conflict")
        if activation["converged"] is not True:
            raise LifecycleError("activation_not_converged")
        validate_phase_certificate(activation, state="RUNNING", timeout=ACTIVATION_TIMEOUT_SECONDS)
        _validate_trigger_current(plan, trigger, runner=runner, fetcher=fetcher)
        post_static = _static_digest(plan)
        if post_static != static:
            raise LifecycleError("static_bindings_changed")
        if os.path.lexists(recovery["output_dir"]):
            raise LifecycleError("output_started_before_admission")
        permit_body = _permit_body(
            authorization=stable_file(paths["authorization"], code="authorization_changed", mode=0o400),
            job_name=job_name,
            static=post_static,
        )
        permit_raw = envelope(permit_body, "permit_sha256")
        permit_sha = sha256_bytes(permit_raw)
        if authorization_raw != envelope(authorization_body, "authorization_sha256"):
            raise LifecycleError("admission_artifact_precommit_mismatch")
        receipt_body = {
            "schema_version": SCHEMA_VERSION,
            "kind": SUBMISSION_KIND,
            "state": "submitted",
            "plan": plan_artifact.record,
            "review": review_artifact.record,
            "trigger": trigger_artifact.record,
            "intent_sha256": intent_sha,
            "environment_sha256": sha256_bytes(environment_raw),
            "submission_visibility": visibility,
            "authorization": {"path": str(paths["authorization"]), "sha256": authorization_sha},
            "activation_permit": {"path": str(paths["permit"]), "sha256": permit_sha},
            "job_id_sha256": sha256_bytes(job_id.encode("ascii")),
            "job_name_sha256": sha256_bytes(job_name.encode("ascii")),
            "job": {"cluster": CLUSTER, "id": job_id, "name": job_name},
            "held": held,
            "held_after_authorization": held_after,
            "release": {"attempts": 1, "outcome": release_outcome},
            "activation": activation,
            "static": post_static,
            "policy": {
                "fresh_two_only": True,
                "legacy_rows_reused": 0,
                "promotion_authorized": False,
                "resume": False,
            },
        }
        receipt_raw = envelope(receipt_body, "submission_receipt_sha256")
        blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        try:
            atomic_write_once(paths["receipt"], receipt_raw, mode=0o400)
            atomic_write_once(paths["permit"], permit_raw, mode=0o400)
            sync_directory(paths["root"])
            os.chmod(paths["root"], 0o500, follow_symlinks=False)
            committed = True
            sync_directory(paths["root"])
            sync_directory(paths["root"].parent)
            stable_directory(paths["root"], code="reservation_seal_failed", mode=0o500)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        if not committed:
            raise LifecycleError("admission_publication_failed")
        return {
            "state": "submitted",
            "mode": "fresh_two",
            "tasks": EXPECTED_TASKS,
            "legacy_rows_reused": 0,
            "submission_receipt_sha256": sha256_bytes(receipt_raw),
        }
    except BaseException:
        primary = sys.exception()
        if primary is None:
            primary = RecoveryControlError("recovery_control_failed")
        if committed:
            raise
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(handled_signals))
        cancellation: Mapping[str, Any] | None = None
        try:
            if job_id is not None and job_name is not None:
                try:
                    cancellation = cancel_and_prove(
                        job_id,
                        job_name,
                        plan,
                        direct_provenance=direct_provenance,
                        runner=runner,
                        sleeper=sleeper,
                        clock=clock,
                    )
                except LifecycleError as error:
                    primary = error
                    cancellation = error.cancellation
            if (
                os.path.lexists(paths["root"])
                and not paths["root"].is_symlink()
                and stat.S_IMODE(paths["root"].stat(follow_symlinks=False).st_mode) == 0o700
            ):
                code = str(primary)
                if SAFE_CODE_RE.fullmatch(code) is None:
                    code = "recovery_control_failed"
                _publish_failure(
                    paths,
                    code=code,
                    plan_artifact=plan_artifact,
                    review_artifact=review_artifact,
                    trigger_artifact=trigger_artifact,
                    cancellation=cancellation,
                    lifecycle={
                        "activation": activation_evidence,
                        "held": held_evidence,
                        "held_after_authorization": held_after_authorization_evidence,
                        "job": (
                            {
                                "direct_sbatch_provenance": direct_provenance,
                                "cluster": CLUSTER,
                                "id": job_id,
                                "name": job_name,
                                "job_id_sha256": sha256_bytes(job_id.encode("ascii")),
                                "job_name_sha256": sha256_bytes(job_name.encode("ascii")),
                            }
                            if job_id is not None and job_name is not None
                            else None
                        ),
                        "release_outcome": release_outcome,
                        "submission_visibility": submission_visibility,
                    },
                )
        finally:
            for handled_signal, previous_handler in previous_handlers.items():
                signal.signal(handled_signal, previous_handler)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        raise primary
    finally:
        if committed:
            for handled_signal, previous_handler in previous_handlers.items():
                signal.signal(handled_signal, previous_handler)


def verify_job_admission(plan_path: Path, review_path: Path, trigger_path: Path) -> dict[str, Any]:
    """Batch-side admission gate; it performs no scheduler control."""

    plan, plan_artifact = load_plan(plan_path)
    controller = stable_file(Path(plan["recovery"]["controller"]["path"]), code="controller_invalid", mode=0o500)
    wrapper = stable_file(Path(plan["recovery"]["job_wrapper"]["path"]), code="job_wrapper_invalid", mode=0o500)
    trigger_value, trigger = load_trigger(trigger_path, plan=plan_artifact)
    review = load_review(
        review_path,
        plan=plan_artifact,
        trigger=trigger,
        controller_sha256=controller.sha256,
        wrapper_sha256=wrapper.sha256,
    )
    if review.path != review_path or review.sha256 != os.environ.get("RECOVERY_REVIEW_SHA256"):
        fail("recovery_review_invalid")
    if trigger.path != trigger_path or trigger.sha256 != os.environ.get("RECOVERY_TRIGGER_SHA256"):
        fail("terminal_trigger_invalid")
    paths = _reservation_paths(plan)
    timeout = int(os.environ.get("RECOVERY_ADMISSION_TIMEOUT_SECONDS", "0"))
    if timeout != ADMISSION_TIMEOUT_SECONDS:
        fail("admission_timeout_invalid")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and stat.S_IMODE(paths["root"].stat(follow_symlinks=False).st_mode) != 0o500:
        time.sleep(1)
    stable_directory(paths["root"], code="reservation_not_committed", mode=0o500)
    permit_value, permit = strict_envelope(
        paths["permit"],
        kind=PERMIT_KIND,
        hash_field="permit_sha256",
        code="activation_permit_invalid",
    )
    receipt_value, receipt = strict_envelope(
        paths["receipt"],
        kind=SUBMISSION_KIND,
        hash_field="submission_receipt_sha256",
        code="submission_receipt_invalid",
    )
    authorization_value, authorization = strict_envelope(
        paths["authorization"],
        kind=AUTHORIZATION_KIND,
        hash_field="authorization_sha256",
        code="authorization_invalid",
    )
    environment = stable_file(paths["environment"], code="slurm_environment_invalid", mode=0o400)
    intent_value, intent = strict_envelope(
        paths["intent"],
        kind=INTENT_KIND,
        hash_field="intent_sha256",
        code="launch_intent_invalid",
    )
    expected_children = {paths[name].name for name in ("intent", "environment", "authorization", "permit", "receipt")}
    if {entry.name for entry in os.scandir(paths["root"])} != expected_children:
        fail("reservation_shape_invalid")
    job_id = os.environ.get("SLURM_JOB_ID", "")
    job_name = os.environ.get("RECOVERY_EXPECTED_JOB_NAME", "")
    token = os.environ.get("RECOVERY_LAUNCH_TOKEN", "")
    if (
        JOB_RE.fullmatch(job_id) is None
        or NAME_RE.fullmatch(job_name) is None
        or re.fullmatch(r"[0-9a-f]{24}", token) is None
    ):
        fail("job_admission_invalid")
    expected_environment = _launch_environment(
        plan,
        plan_artifact=plan_artifact,
        review_artifact=review,
        trigger_artifact=trigger,
        authorization_path=paths["authorization"],
        permit_path=paths["permit"],
        submission_path=paths["receipt"],
        job_name=job_name,
        token=token,
    )
    if environment.raw != _environment_bytes(expected_environment) or any(
        os.environ.get(key) != value for key, value in expected_environment.items()
    ):
        fail("slurm_environment_changed")
    for key in os.environ:
        if (
            key.startswith(("BASH_", "GIT_", "LD_", "SBATCH_"))
            or key in {"ENV", "RESUME_DIR", "KIMI_SMOKE_RECOVERY_SELECTION", "KIMI_SMOKE_COMPOSITE_OUTPUT_DIR"}
            or key.startswith("PYTHON")
        ) and key not in expected_environment:
            fail("job_environment_invalid")
    expected_intent_keys = {
        "environment_sha256",
        "intent_sha256",
        "job_name_sha256",
        "kind",
        "launch_token_sha256",
        "plan",
        "policy",
        "review",
        "schema_version",
        "state",
        "static",
        "trigger",
    }
    expected_authorization_keys = {
        "authorization_sha256",
        "held",
        "held_after_authorization",
        "intent",
        "job",
        "job_id_sha256",
        "job_name_sha256",
        "kind",
        "launch_token_sha256",
        "plan",
        "policy",
        "review",
        "schema_version",
        "state",
        "static",
        "trigger",
    }
    expected_permit_keys = {
        "authorization",
        "job_name_sha256",
        "kind",
        "permit_sha256",
        "policy",
        "schema_version",
        "state",
        "static",
    }
    expected_receipt_keys = {
        "activation",
        "activation_permit",
        "authorization",
        "environment_sha256",
        "held",
        "intent_sha256",
        "job",
        "job_id_sha256",
        "job_name_sha256",
        "kind",
        "plan",
        "policy",
        "release",
        "review",
        "schema_version",
        "state",
        "static",
        "submission_receipt_sha256",
        "submission_visibility",
        "trigger",
    }
    if (
        set(intent_value) != expected_intent_keys
        or set(authorization_value) != expected_authorization_keys
        or set(permit_value) != expected_permit_keys
        or set(receipt_value) != expected_receipt_keys
        or receipt.path != Path(os.environ.get("RECOVERY_SUBMISSION_RECEIPT", ""))
        or plan_artifact.sha256 != os.environ.get("RECOVERY_PLAN_SHA256")
        or str(plan_artifact.path) != os.environ.get("RECOVERY_PLAN")
        or str(review.path) != os.environ.get("RECOVERY_REVIEW")
        or str(trigger.path) != os.environ.get("RECOVERY_TRIGGER")
        or str(authorization.path) != os.environ.get("RECOVERY_AUTHORIZATION")
        or str(permit.path) != os.environ.get("RECOVERY_ACTIVATION_PERMIT")
        or intent_value.get("environment_sha256") != environment.sha256
        or receipt_value.get("state") != "submitted"
        or intent_value.get("state") != "reserved"
        or authorization_value.get("state") != "held_authorized"
        or permit_value.get("state") != "activated"
        or receipt_value.get("plan") != plan_artifact.record
        or receipt_value.get("review") != review.record
        or receipt_value.get("trigger") != trigger.record
        or intent_value.get("plan") != plan_artifact.record
        or intent_value.get("review") != review.record
        or intent_value.get("trigger") != trigger.record
        or receipt_value.get("activation_permit") != permit.record
        or receipt_value.get("authorization") != authorization.record
        or receipt_value.get("intent_sha256") != intent.sha256
        or permit_value.get("authorization") != authorization.record
        or authorization_value.get("plan") != plan_artifact.record
        or authorization_value.get("review") != review.record
        or authorization_value.get("trigger") != trigger.record
        or authorization_value.get("intent") != intent.record
        or authorization_value.get("held") != receipt_value.get("held")
        or receipt_value.get("job_id_sha256") != sha256_bytes(job_id.encode("ascii"))
        or authorization_value.get("job_id_sha256") != sha256_bytes(job_id.encode("ascii"))
        or authorization_value.get("job") != {"cluster": CLUSTER, "id": job_id, "name": job_name}
        or receipt_value.get("job") != {"cluster": CLUSTER, "id": job_id, "name": job_name}
        or receipt_value.get("job_name_sha256") != sha256_bytes(job_name.encode("ascii"))
        or authorization_value.get("job_name_sha256") != sha256_bytes(job_name.encode("ascii"))
        or permit_value.get("job_name_sha256") != sha256_bytes(job_name.encode("ascii"))
        or intent_value.get("job_name_sha256") != sha256_bytes(job_name.encode("ascii"))
        or authorization_value.get("launch_token_sha256") != sha256_bytes(token.encode("ascii"))
        or intent_value.get("launch_token_sha256") != sha256_bytes(token.encode("ascii"))
        or receipt_value.get("held", {}).get("converged") is not True
        or receipt_value.get("activation", {}).get("converged") is not True
        or receipt_value.get("release") != {"attempts": 1, "outcome": "completed"}
        or receipt_value.get("policy")
        != {
            "fresh_two_only": True,
            "legacy_rows_reused": 0,
            "promotion_authorized": False,
            "resume": False,
        }
        or intent_value.get("policy") != {"fresh_two_only": True, "held_submission": True, "launches": 1}
        or authorization_value.get("policy") != {"fresh_two_only": True, "legacy_rows_reused": 0, "resume": False}
        or permit_value.get("policy") != {"fresh_two_only": True, "legacy_rows_reused": 0, "resume": False}
    ):
        fail("job_admission_invalid")
    validate_phase_certificate(receipt_value.get("held"), state="PENDING", timeout=HELD_TIMEOUT_SECONDS)
    validate_phase_certificate(receipt_value.get("held_after_authorization"), state="PENDING", timeout=10)
    validate_phase_certificate(receipt_value.get("activation"), state="RUNNING", timeout=ACTIVATION_TIMEOUT_SECONDS)
    phase_mismatches, phase_conflicts, phase_state = _scheduler_phase_evidence(
        plan, job_id, job_name, held=False, runner=run_command
    )
    if phase_mismatches or phase_conflicts or phase_state != "RUNNING":
        fail("job_scheduler_admission_invalid")
    _validate_trigger_current(plan, trigger_value, runner=run_command, fetcher=fetch_http)
    static = _static_digest(plan)
    if (
        static != receipt_value.get("static")
        or static != permit_value.get("static")
        or static != authorization_value.get("static")
        or static != intent_value.get("static")
        or os.path.lexists(plan["recovery"]["output_dir"])
    ):
        fail("static_bindings_changed")
    return {"state": "admitted", "tasks": EXPECTED_TASKS, "mode": "fresh_two"}


def _clean_recovery_environment(plan: Mapping[str, Any]) -> dict[str, str]:
    allowed = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "USER",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONNOUSERSITE",
        "PYTHONSAFEPATH",
        "UV_NO_CONFIG",
        "PROJECT_DIR",
        "EVAL_EXPECTED_PRIME_RL_REVISION",
        "EVAL_EXPECTED_MODEL",
        "EVAL_DEPLOYMENT_ID",
        "EVAL_DATASET_ARCHIVE",
        "EVAL_DATASET_ARCHIVE_SHA256",
        "EVAL_DATASET_CONTENT_SHA256",
        "INFERENCE_DEPLOYMENT_SPEC",
        "INFERENCE_DEPLOYMENT_SPEC_SHA256",
        "INFERENCE_READINESS_CHECKPOINT",
        "INFERENCE_READINESS_CHECKPOINT_SHA256",
        "INFERENCE_PROXY_INFO",
        "INFERENCE_PROXY_INFO_SHA256",
        "OUTPUT_DIR",
        "KIMI_SMOKE_RECOVERY_MODE",
        "VACLI_BIN",
        "VACLI_LEASE_RETRIES",
        "VACLI_MAX_CONCURRENT_LEASES",
        "VACLI_MAX_PULL_RETRIES",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS",
        "VACLI_CONTAINER_PRIVILEGED",
        "PYTHON_BIN_X86_64",
        "PYTHON_BIN_X86_64_SHA256",
        "PYTHON_SITE_X86_64",
        "UV_BIN_X86_64",
        "UV_BIN_X86_64_SHA256",
        "VACLI_BIN_SHA256",
        "RECOVERY_RUNTIME_MANIFEST_SHA256",
        "THRIFT_TLS_CL_CERT_PATH",
        "THRIFT_TLS_CL_KEY_PATH",
        "SLURM_JOB_ID",
        "SLURM_JOB_NAME",
    }
    missing = allowed - set(os.environ)
    if missing:
        fail("job_environment_incomplete")
    environment = {name: os.environ[name] for name in sorted(allowed)}
    expected = plan["recovery"]
    runtime = plan["runtime"]
    runtime_manifest, _ = strict_envelope(
        Path(runtime["manifest"]["path"]),
        kind=RUNTIME_KIND,
        hash_field="manifest_sha256",
        code="runtime_manifest_invalid",
    )
    if (
        environment["PROJECT_DIR"] != expected["project_root"]
        or environment["OUTPUT_DIR"] != expected["output_dir"]
        or environment["KIMI_SMOKE_RECOVERY_MODE"] != "fresh-two"
        or environment["PYTHON_BIN_X86_64"] != runtime["python"]["path"]
        or environment["UV_BIN_X86_64"] != runtime["uv"]["path"]
        or environment["VACLI_BIN"] != runtime["vacli"]["path"]
        or environment["PYTHON_BIN_X86_64_SHA256"] != runtime["python"]["sha256"]
        or environment["UV_BIN_X86_64_SHA256"] != runtime["uv"]["sha256"]
        or environment["VACLI_BIN_SHA256"] != runtime["vacli"]["sha256"]
        or environment["RECOVERY_RUNTIME_MANIFEST_SHA256"] != runtime["manifest"]["sha256"]
        or environment["PYTHON_SITE_X86_64"] != runtime_manifest.get("root")
        or environment["VACLI_MAX_CONCURRENT_LEASES"] != "2"
        or environment["VACLI_LEASE_RETRIES"] != "20"
        or environment["VACLI_MAX_PULL_RETRIES"] != "20"
        or environment["VACLI_IMAGE_PULL_TIMEOUT_SECONDS"] != "3600"
        or environment["VACLI_CONTAINER_PRIVILEGED"] != "1"
        or environment["EVAL_EXPECTED_MODEL"] != "Kimi-K3"
        or JOB_RE.fullmatch(environment["SLURM_JOB_ID"]) is None
        or environment["SLURM_JOB_NAME"] != os.environ.get("RECOVERY_EXPECTED_JOB_NAME")
    ):
        fail("job_environment_invalid")
    return environment


def _run_sealed_shell(path: Path, expected_sha256: str, environment: Mapping[str, str]) -> int:
    artifact = stable_file(path, code="recovery_wrapper_invalid", uid=OWNER_UID)
    if artifact.sha256 != expected_sha256:
        fail("recovery_wrapper_invalid")
    descriptor = os.memfd_create("kimi_smoke_recovery", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        view = memoryview(artifact.raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                fail("recovery_wrapper_capture_failed")
            view = view[written:]
        os.fchmod(descriptor, 0o500)
        seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            fail("recovery_wrapper_capture_failed")
        os.set_inheritable(descriptor, True)
        command = [
            "/usr/bin/bash",
            "--noprofile",
            "--norc",
            "-c",
            f"source /proc/self/fd/{descriptor}",
            str(path),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                env=dict(environment),
                pass_fds=(descriptor,),
            )
        except OSError as error:
            raise RecoveryControlError("recovery_wrapper_start_failed") from error
        return int(completed.returncode)
    finally:
        os.close(descriptor)


def validate_recovery_output(plan: Mapping[str, Any]) -> StableFile:
    output = Path(plan["recovery"]["output_dir"])
    stable_directory(output, code="recovery_output_invalid", mode=0o700)
    checkpoints = sorted(
        entry.name
        for entry in os.scandir(output)
        if entry.name.startswith("smoke_checkpoint") and entry.name.endswith(".json")
    )
    if checkpoints != ["smoke_checkpoint.json"]:
        fail("recovery_output_invalid")
    checkpoint = stable_file(
        output / "smoke_checkpoint.json",
        code="recovery_output_invalid",
        mode=0o444,
        uid=OWNER_UID,
    )
    protected_modules = {
        "deployment_endpoint",
        "deployment_proxy_policy",
        "eval_run_identity",
        "guard_success_receipt",
        "inference_route_generation",
        "smoke_qualification",
    }
    if protected_modules & set(sys.modules):
        fail("reviewed_import_collision")
    baseline = set(sys.modules)
    previous_path = list(sys.path)
    allowed_roots = activate_reviewed_imports(plan)
    try:
        import eval_run_identity
        import smoke_qualification

        evidence = smoke_qualification.validate_smoke_qualification(
            checkpoint.path,
            checkpoint.sha256,
            deployment_id=plan["recovery"]["deployment_id"],
            deployment_spec_path=Path(plan["recovery"]["deployment_spec"]["path"]),
            deployment_spec_sha256=plan["recovery"]["deployment_spec"]["sha256"],
            readiness_path=Path(plan["recovery"]["readiness_checkpoint"]["path"]),
            readiness_sha256=plan["recovery"]["readiness_checkpoint"]["sha256"],
            proxy_info_path=Path(plan["recovery"]["proxy_info"]["path"]),
            proxy_info_sha256=plan["recovery"]["proxy_info"]["sha256"],
            model="Kimi-K3",
            identity_loader=eval_run_identity.load_eval_run_identity,
        )
        validate_reviewed_imports(baseline, allowed_roots)
    except RecoveryControlError:
        raise
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise RecoveryControlError("recovery_output_invalid") from error
    finally:
        for name in set(sys.modules) - baseline:
            sys.modules.pop(name, None)
        sys.path[:] = previous_path
    if evidence.schema_version != 1:
        fail("recovery_output_invalid")
    return checkpoint


def run_job(plan_path: Path, review_path: Path, trigger_path: Path) -> dict[str, Any]:
    admitted = verify_job_admission(plan_path, review_path, trigger_path)
    plan, _ = load_plan(plan_path)
    before = _static_digest(plan)
    environment = _clean_recovery_environment(plan)
    result = _run_sealed_shell(
        Path(plan["recovery"]["recovery_wrapper"]["path"]),
        plan["recovery"]["recovery_wrapper"]["sha256"],
        environment,
    )
    after = _static_digest(plan)
    if before != after:
        fail("static_bindings_changed")
    if result != 0:
        fail("recovery_evaluation_failed")
    checkpoint = validate_recovery_output(plan)
    if _static_digest(plan) != before:
        fail("static_bindings_changed")
    return {**admitted, "state": "completed", "smoke_checkpoint_sha256": checkpoint.sha256}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    certify = subparsers.add_parser("certify-trigger")
    certify.add_argument("--plan", type=Path, required=True)
    certify.add_argument("--output", type=Path, required=True)
    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--plan", type=Path, required=True)
    launch_parser.add_argument("--review", type=Path, required=True)
    launch_parser.add_argument("--trigger", type=Path, required=True)
    admission = subparsers.add_parser("verify-job-admission")
    admission.add_argument("--plan", type=Path, required=True)
    admission.add_argument("--review", type=Path, required=True)
    admission.add_argument("--trigger", type=Path, required=True)
    run_parser = subparsers.add_parser("run-job")
    run_parser.add_argument("--plan", type=Path, required=True)
    run_parser.add_argument("--review", type=Path, required=True)
    run_parser.add_argument("--trigger", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "certify-trigger":
            result = certify_trigger(args.plan, args.output)
        elif args.command == "launch":
            result = launch(args.plan, args.review, args.trigger)
        elif args.command == "verify-job-admission":
            result = verify_job_admission(args.plan, args.review, args.trigger)
        else:
            result = run_job(args.plan, args.review, args.trigger)
    except BaseException as error:  # noqa: BLE001 - signals/errors must fail closed
        code = str(error)
        if SAFE_CODE_RE.fullmatch(code) is None:
            code = "recovery_control_failed"
        print(json.dumps({"state": "aborted", "code": code}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
