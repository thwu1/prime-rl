#!/usr/bin/env python3
"""Certify a completed retry canary without emitting private row data."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import secrets
import stat
import sys
import types
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

OWNER_UID = 656177
BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
ARTIFACT_ROOT = BASE / "oracle/infrastructure_retry_canary_5873430ff_v22"
ARTIFACT_ROOT_ENTRIES = {
    "README.md": 0o500,
    "audit_infrastructure_retry_canary_v22.py": 0o500,
    "build_infrastructure_retry_selection_v22.py": 0o500,
    "launch_infrastructure_retry_canary_v22.py": 0o500,
    "packaging-26.3-py3-none-any.whl.snapshot.json": 0o400,
    "run_infrastructure_retry_canary_v22.sbatch": 0o500,
    "test_retry_canary_v22_public.py": 0o500,
    "test_retry_launcher_v22_public.py": 0o500,
    "test_retry_postrun_audit_v22_public.py": 0o500,
}
CANONICAL_SELF = ARTIFACT_ROOT / "audit_infrastructure_retry_canary_v22.py"
LAUNCHER = ARTIFACT_ROOT / "launch_infrastructure_retry_canary_v22.py"
LAUNCHER_SHA256 = "62a3255a17532300ad772417000d68f5247db17359811b71baf53982b6532890"
PYTHON_REAL = Path(
    "/storage/home/tianhaowu/.local/share/uv/python/"
    "cpython-3.13.15-linux-aarch64-gnu/bin/python3.13"
)
PYTHON_SHA256 = "f53c112756a06959fd532fa70e3108f89b90550c71f5c1afc26f8985c772a121"
PACKAGING_SNAPSHOT = ARTIFACT_ROOT / "packaging-26.3-py3-none-any.whl.snapshot.json"
PACKAGING_SNAPSHOT_SHA256 = (
    "6025752344370d775f1a22e6c9d3f3bfaa57f9b5e17e2b296088864dfdc14761"
)
PACKAGING_WHEEL_SHA256 = (
    "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c"
)
PACKAGING_MEMBER_MANIFEST_SHA256 = (
    "d02fb4c0b14244ef8a78ef2b91c29d988754c230c977089eb0c65eb5152e6ea4"
)
OUTPUT_ROOT = BASE / "oracle/mobius_infrastructure_retry_run_5873430ff_v22"
AUDIT_ROOT = BASE / "oracle/mobius_infrastructure_retry_audit_5873430ff_v22"
AUDIT_INTENT = AUDIT_ROOT / "audit_intent.json"
CERTIFICATE = AUDIT_ROOT / "post_run_certificate.json"
FAILURE = AUDIT_ROOT / "post_run_failure.json"
EXPECTED_OUTPUT_CHILDREN = {
    ".writer.lock",
    "invocations.jsonl",
    "oracle_network_semantics.json",
    "provenance.txt",
    "results.jsonl",
    "run_config.json",
    "run_identity.json",
    "summary.json",
    "tasks",
}
SAFE_CODE_RE = re.compile(r"[a-z0-9_]{1,96}")


def _load_launcher():
    try:
        descriptor = os.open(LAUNCHER, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            raw = b""
            while len(raw) < before.st_size:
                chunk = os.read(descriptor, min(1 << 20, before.st_size - len(raw)))
                if not chunk:
                    raise RuntimeError("launcher_short_read")
                raw += chunk
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        path_after = os.stat(LAUNCHER, follow_symlinks=False)
    except OSError as error:
        raise RuntimeError("launcher_unavailable") from error

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
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
        LAUNCHER.is_symlink()
        or LAUNCHER.resolve(strict=True) != LAUNCHER
        or identity(before) != identity(after)
        or identity(after) != identity(path_after)
        or not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o500
        or before.st_uid != OWNER_UID
        or before.st_nlink != 1
        or __import__("hashlib").sha256(raw).hexdigest() != LAUNCHER_SHA256
    ):
        raise RuntimeError("launcher_invalid")
    module = types.ModuleType("retry_launcher_v22_frozen")
    module.__file__ = str(LAUNCHER)
    exec(compile(raw, str(LAUNCHER), "exec"), module.__dict__)  # noqa: S102
    return module


LAUNCH = _load_launcher()
AuditError = LAUNCH.LauncherError
fail = LAUNCH.fail
canonical_json = LAUNCH.canonical_json
sha256_bytes = LAUNCH.sha256_bytes
strict_json = LAUNCH.strict_json
file_bytes = LAUNCH.file_bytes
require_directory = LAUNCH.require_directory
bounded_run = LAUNCH.bounded_run
validate_tmux_ancestry = LAUNCH.validate_tmux_ancestry
sync_directory = LAUNCH.sync_directory
envelope = LAUNCH.envelope


def _artifact_directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def validate_artifact_root_inventory(
    root: Path = ARTIFACT_ROOT,
    expected: Mapping[str, int] = ARTIFACT_ROOT_ENTRIES,
) -> None:
    """Require one stable, canonical directory containing exactly nine files."""

    directory_fd = -1
    fresh_fd = -1
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        if root.is_symlink() or root.resolve(strict=True) != root:
            fail("artifact_root_inventory_invalid")
        directory_fd = os.open(root, flags)
        before = os.fstat(directory_fd)
        names_before = os.listdir(directory_fd)
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != OWNER_UID
            or before.st_nlink != 2
            or len(names_before) != len(expected)
            or set(names_before) != set(expected)
        ):
            fail("artifact_root_inventory_invalid")
        for name, mode in expected.items():
            status = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(status.st_mode)
                or stat.S_IMODE(status.st_mode) != mode
                or status.st_uid != OWNER_UID
                or status.st_nlink != 1
            ):
                fail("artifact_root_inventory_invalid")
        after = os.fstat(directory_fd)
        names_after = os.listdir(directory_fd)
        fresh_fd = os.open(root, flags)
        current = os.fstat(fresh_fd)
        names_current = os.listdir(fresh_fd)
        if (
            _artifact_directory_identity(before) != _artifact_directory_identity(after)
            or _artifact_directory_identity(after)
            != _artifact_directory_identity(current)
            or names_after != names_before
            or names_current != names_before
            or root.resolve(strict=True) != root
        ):
            fail("artifact_root_inventory_invalid")
    except AuditError:
        raise
    except (OSError, RuntimeError) as error:
        raise AuditError("artifact_root_inventory_invalid") from error
    finally:
        if fresh_fd >= 0:
            os.close(fresh_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def expected_packaging_provenance() -> dict[str, object]:
    return {
        "name": "packaging",
        "version": "26.3",
        "wheel_sha256": PACKAGING_WHEEL_SHA256,
        "wheel_size": 129_956,
        "member_count": 29,
        "member_manifest_sha256": PACKAGING_MEMBER_MANIFEST_SHA256,
        "snapshot": {
            "path": str(PACKAGING_SNAPSHOT),
            "sha256": PACKAGING_SNAPSHOT_SHA256,
            "mode": "0400",
            "uid": OWNER_UID,
            "nlink": 1,
        },
        "loader": "restricted_in_memory_exact_wheel_sources_v1",
        "site_imports": False,
        "pyc_reads": False,
    }


def validate_invocation() -> str:
    expected_names = {
        "APPROVED_RETRY_AUDITOR_SHA256",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "TMUX",
        "TMUX_PANE",
        "USER",
    }
    if (
        Path(__file__) != CANONICAL_SELF
        or Path(sys.argv[0]) != CANONICAL_SELF
        or CANONICAL_SELF.resolve(strict=True) != CANONICAL_SELF
        or Path.cwd() != Path("/storage/home/tianhaowu")
        or set(os.environ) != expected_names
        or os.environ.get("HOME") != "/storage/home/tianhaowu"
        or os.environ.get("PATH") != "/usr/bin:/bin"
        or os.environ.get("LANG") != "C"
        or os.environ.get("LC_ALL") != "C"
        or os.environ.get("USER") != "tianhaowu"
        or os.environ.get("LOGNAME") != "tianhaowu"
        or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1"
        or os.getuid() != OWNER_UID
        or os.geteuid() != OWNER_UID
        or Path(sys.executable).resolve(strict=True) != PYTHON_REAL
    ):
        fail("outer_environment_invalid")
    approved = os.environ["APPROVED_RETRY_AUDITOR_SHA256"]
    if LAUNCH.SHA_RE.fullmatch(approved) is None:
        fail("auditor_approval_missing")
    validate_artifact_root_inventory()
    file_bytes(CANONICAL_SELF, expected_sha256=approved, mode=0o500, maximum=1 << 20)
    file_bytes(LAUNCHER, expected_sha256=LAUNCHER_SHA256, mode=0o500, maximum=1 << 20)
    if (
        LAUNCH.PACKAGING_SNAPSHOT != PACKAGING_SNAPSHOT
        or LAUNCH.PACKAGING_SNAPSHOT_SHA256 != PACKAGING_SNAPSHOT_SHA256
        or LAUNCH.PACKAGING_WHEEL_SHA256 != PACKAGING_WHEEL_SHA256
        or LAUNCH.PACKAGING_MEMBER_MANIFEST_SHA256
        != PACKAGING_MEMBER_MANIFEST_SHA256
        or LAUNCH.expected_packaging_provenance()
        != expected_packaging_provenance()
    ):
        fail("packaging_dependency_invalid")
    file_bytes(
        PACKAGING_SNAPSHOT,
        expected_sha256=PACKAGING_SNAPSHOT_SHA256,
        mode=0o400,
        maximum=1 << 20,
    )
    file_bytes(PYTHON_REAL, expected_sha256=PYTHON_SHA256, maximum=64 << 20)
    validate_tmux_ancestry()
    return approved


def parse_envelope(raw: bytes, field: str, *, code: str) -> tuple[dict[str, Any], str]:
    value = strict_json(raw)
    body = dict(value)
    digest = body.pop(field, None)
    if (
        not isinstance(digest, str)
        or LAUNCH.SHA_RE.fullmatch(digest) is None
        or digest != sha256_bytes(canonical_json(body))
    ):
        fail(code)
    return body, digest


def validate_intent(
    raw: bytes,
    *,
    launcher_sha: str,
    task_sha: str,
    role_sha: str,
    selection_receipt_file_sha: str,
    selection_receipt_sha: str,
    environment_sha: str,
    job_name: str,
    token: str,
    authorization_path: Path,
    authorization_sha: str,
    activation_permit_path: Path,
    activation_permit_sha: str,
    x2p_sha256: Mapping[str, str],
) -> str:
    body, _digest = parse_envelope(raw, "intent_sha256", code="launch_intent_invalid")
    launch = body.get("launch")
    selection = body.get("selection")
    started = launch.get("submission_started_at") if isinstance(launch, dict) else None
    try:
        from datetime import datetime

        parsed_started = (
            datetime.fromisoformat(started) if isinstance(started, str) else None
        )
    except ValueError as error:
        raise AuditError("launch_intent_invalid") from error
    if (
        set(body)
        != {
            "attempt_policy",
            "generator_sha256",
            "job_wrapper_sha256",
            "kind",
            "launch",
            "launcher_sha256",
            "module_import_closure",
            "schema_version",
            "selection",
            "source_revision",
            "source_tree",
            "state",
            "verifiers_revision",
            "vmvm_tb_v2_sha256",
            "x2p_environment_sha256",
        }
        or body.get("schema_version") != 1
        or body.get("kind")
        != "terminal_bench_vmvm_infrastructure_retry_v22_launch_intent"
        or body.get("state") != "submitting"
        or body.get("launcher_sha256") != launcher_sha
        or body.get("generator_sha256") != LAUNCH.GENERATOR_SHA256
        or body.get("job_wrapper_sha256") != LAUNCH.JOB_WRAPPER_SHA256
        or body.get("source_revision") != LAUNCH.SOURCE_REVISION
        or body.get("source_tree") != LAUNCH.SOURCE_TREE
        or body.get("verifiers_revision") != LAUNCH.VERIFIERS_REVISION
        or body.get("vmvm_tb_v2_sha256") != LAUNCH.VMVM_SHA256
        or body.get("x2p_environment_sha256") != x2p_sha256
        or body.get("attempt_policy") != LAUNCH.ATTEMPT_POLICY
        or body.get("module_import_closure")
        != {"packaging": expected_packaging_provenance()}
        or selection
        != {
            "receipt_file_sha256": selection_receipt_file_sha,
            "receipt_sha256": selection_receipt_sha,
            "task_file_sha256": task_sha,
            "role_file_sha256": role_sha,
            "selected": LAUNCH.EXPECTED_SELECTED,
            "retry_candidates": LAUNCH.EXPECTED_CANDIDATES,
            "controls": LAUNCH.EXPECTED_CONTROLS,
        }
        or not isinstance(launch, dict)
        or set(launch)
        != {
            "cluster",
            "environment_sha256",
            "activation_permit",
            "authorization",
            "held_identity_required_consecutive",
            "job_name",
            "launch_token",
            "max_concurrent",
            "max_concurrent_leases",
            "minimum_valid",
            "output_dir",
            "slurm_time_limit",
            "submission_started_at",
            "submit_held",
        }
        or launch.get("cluster") != LAUNCH.CLUSTER
        or launch.get("environment_sha256") != environment_sha
        or launch.get("job_name") != job_name
        or launch.get("launch_token") != token
        or launch.get("submit_held") is not True
        or launch.get("held_identity_required_consecutive")
        != LAUNCH.HELD_REQUIRED_CONSECUTIVE
        or launch.get("authorization")
        != {"path": str(authorization_path), "sha256": authorization_sha}
        or launch.get("activation_permit")
        != {"path": str(activation_permit_path), "sha256": activation_permit_sha}
        or launch.get("max_concurrent") != 4
        or launch.get("max_concurrent_leases") != 2
        or launch.get("minimum_valid") != LAUNCH.MINIMUM_VALID
        or launch.get("output_dir") != str(OUTPUT_ROOT)
        or launch.get("slurm_time_limit") != "7-00:00:00"
        or parsed_started is None
        or parsed_started.tzinfo is None
    ):
        fail("launch_intent_invalid")
    return sha256_bytes(raw)


def validate_launch_artifacts(launcher_sha: str) -> dict[str, Any]:
    validate_artifact_root_inventory()
    generator = LAUNCH.load_generator()
    task_sha, role_sha, selection_file_sha, selection_sha = LAUNCH.validate_selection()
    LAUNCH.verify_generation(
        generator, task_sha, role_sha, selection_file_sha, selection_sha
    )
    LAUNCH.validate_launch_dependencies(generator)
    require_directory(LAUNCH.RESERVATION, 0o500)
    if LAUNCH.FAILURE_CERTIFICATE.exists() or LAUNCH.FAILURE_CERTIFICATE.is_symlink():
        fail("submission_reservation_invalid")
    environment_raw = file_bytes(LAUNCH.ENVIRONMENT_FILE, mode=0o400, maximum=1 << 20)
    private_x2p_values = LAUNCH.parse_private_x2p_environment(environment_raw)
    x2p_sha256 = LAUNCH.x2p_environment_sha256(private_x2p_values)
    submission_raw = file_bytes(LAUNCH.SUBMISSION_RECEIPT, mode=0o400, maximum=1 << 20)
    submission_value = strict_json(submission_raw)
    (
        job_id,
        job_name,
        intent_sha,
        submission_sha,
        authorization_path,
        authorization_sha,
        activation_permit_path,
        activation_permit_sha,
    ) = LAUNCH.validate_submission_receipt(
        submission_value,
        launcher_sha=launcher_sha,
        task_sha=task_sha,
        role_sha=role_sha,
        receipt_file_sha=selection_file_sha,
        receipt_sha=selection_sha,
        x2p_sha256=x2p_sha256,
    )
    token = job_name.removeprefix("mirc-")
    try:
        children = {entry.name for entry in os.scandir(LAUNCH.RESERVATION)}
    except OSError as error:
        raise AuditError("submission_reservation_invalid") from error
    if children != {
        LAUNCH.INTENT.name,
        LAUNCH.ENVIRONMENT_FILE.name,
        LAUNCH.SUBMISSION_RECEIPT.name,
        authorization_path.name,
        activation_permit_path.name,
    }:
        fail("submission_reservation_invalid")
    expected_authorization_path, authorization_raw, expected_authorization_sha = (
        LAUNCH.authorization_bytes(
            launcher_sha=launcher_sha,
            token=token,
            job_name=job_name,
            task_sha=task_sha,
            role_sha=role_sha,
            receipt_file_sha=selection_file_sha,
            receipt_sha=selection_sha,
            x2p_sha256=x2p_sha256,
        )
    )
    expected_permit_path, permit_raw, expected_permit_sha = (
        LAUNCH.activation_permit_bytes(
            token=token,
            job_name=job_name,
            authorization_sha=authorization_sha,
        )
    )
    if (
        authorization_path != expected_authorization_path
        or authorization_sha != expected_authorization_sha
        or activation_permit_path != expected_permit_path
        or activation_permit_sha != expected_permit_sha
        or file_bytes(
            authorization_path,
            expected_sha256=authorization_sha,
            mode=0o400,
            maximum=1 << 20,
        )
        != authorization_raw
        or file_bytes(
            activation_permit_path,
            expected_sha256=activation_permit_sha,
            mode=0o400,
            maximum=1 << 20,
        )
        != permit_raw
    ):
        fail("submission_authorization_invalid")
    expected_environment = LAUNCH.environment_bytes(
        LAUNCH.slurm_environment(
            task_sha,
            role_sha,
            selection_file_sha,
            selection_sha,
            launcher_sha=launcher_sha,
            token=token,
            job_name=job_name,
            authorization_path=authorization_path,
            authorization_sha=authorization_sha,
            activation_permit_path=activation_permit_path,
            activation_permit_sha=activation_permit_sha,
            private_tls_values=LAUNCH.parse_private_tls_environment(environment_raw),
            private_x2p_values=private_x2p_values,
        )
    )
    if environment_raw != expected_environment:
        fail("submission_environment_invalid")
    environment_sha = sha256_bytes(environment_raw)
    intent_raw = file_bytes(
        LAUNCH.INTENT,
        expected_sha256=intent_sha,
        mode=0o400,
        maximum=1 << 20,
    )
    if (
        validate_intent(
            intent_raw,
            launcher_sha=launcher_sha,
            task_sha=task_sha,
            role_sha=role_sha,
            selection_receipt_file_sha=selection_file_sha,
            selection_receipt_sha=selection_sha,
            environment_sha=environment_sha,
            job_name=job_name,
            token=token,
            authorization_path=authorization_path,
            authorization_sha=authorization_sha,
            activation_permit_path=activation_permit_path,
            activation_permit_sha=activation_permit_sha,
            x2p_sha256=x2p_sha256,
        )
        != intent_sha
    ):
        fail("launch_intent_invalid")
    submission_lifecycle = submission_value["lifecycle"]
    scheduler_lifecycle = {
        "protocol": submission_lifecycle["protocol"],
        "held_validation": submission_lifecycle["held_validation"],
        "release": submission_lifecycle["release"],
    }
    result = {
        "generator": generator,
        "module_import_closure": expected_packaging_provenance(),
        "task_sha": task_sha,
        "role_sha": role_sha,
        "selection_file_sha": selection_file_sha,
        "selection_sha": selection_sha,
        "submission_file_sha": sha256_bytes(submission_raw),
        "submission_sha": submission_sha,
        "intent_sha": intent_sha,
        "environment_sha": environment_sha,
        "authorization_file_sha": sha256_bytes(authorization_raw),
        "authorization_sha": authorization_sha,
        "activation_permit_file_sha": sha256_bytes(permit_raw),
        "activation_permit_sha": activation_permit_sha,
        "job_id": job_id,
        "job_name": job_name,
        "scheduler_lifecycle": scheduler_lifecycle,
        "x2p_sha256": x2p_sha256,
    }
    validate_artifact_root_inventory()
    return result


def require_terminal_job(job_id: str, job_name: str) -> None:
    result = bounded_run(
        [
            "/usr/bin/sacct",
            "-M",
            LAUNCH.CLUSTER,
            "--noheader",
            "--parsable2",
            "--allocations",
            "-j",
            job_id,
            "--format=JobIDRaw,JobName,State,ExitCode",
        ],
        timeout=LAUNCH.V1.QUERY_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or result.stderr:
        fail("scheduler_terminal_unavailable")
    records = [line.split("|") for line in result.stdout.splitlines() if line.strip()]
    if len(records) != 1 or records[0] != [job_id, job_name, "COMPLETED", "0:0"]:
        fail("scheduler_not_successfully_terminal")


def create_audit_reservation(auditor_sha: str, launch: Mapping[str, Any]) -> str:
    if AUDIT_ROOT.exists() or AUDIT_ROOT.is_symlink():
        fail("audit_namespace_not_fresh")
    try:
        AUDIT_ROOT.mkdir(mode=0o700)
        sync_directory(AUDIT_ROOT.parent)
    except OSError as error:
        raise AuditError("audit_reservation_failed") from error
    intent_body = {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_audit_intent",
        "state": "auditing",
        "auditor_sha256": auditor_sha,
        "launcher_sha256": LAUNCHER_SHA256,
        "selection_receipt_file_sha256": launch["selection_file_sha"],
        "selection_receipt_sha256": launch["selection_sha"],
        "submission_receipt_file_sha256": launch["submission_file_sha"],
        "submission_receipt_sha256": launch["submission_sha"],
        "authorization_file_sha256": launch["authorization_file_sha"],
        "authorization_sha256": launch["authorization_sha"],
        "activation_permit_file_sha256": launch["activation_permit_file_sha"],
        "activation_permit_sha256": launch["activation_permit_sha"],
        "verifiers_revision": LAUNCH.VERIFIERS_REVISION,
        "vmvm_tb_v2_sha256": LAUNCH.VMVM_SHA256,
        "x2p_environment_sha256": launch["x2p_sha256"],
        "module_import_closure": launch["module_import_closure"],
        "scheduler_lifecycle": launch["scheduler_lifecycle"],
        "scheduler": {"cluster": LAUNCH.CLUSTER, "job_id": launch["job_id"]},
        "expected": {
            "selected": 19,
            "candidates": 15,
            "controls": 4,
            "all_controls_valid": True,
            "minimum_candidate_recoveries": 6,
            "minimum_valid": 10,
        },
        "automatic_union_or_promotion": False,
    }
    raw = envelope(intent_body, "audit_intent_sha256")
    atomic_publish(AUDIT_INTENT, raw, 0o400)
    sync_directory(AUDIT_ROOT)
    return sha256_bytes(raw)


def atomic_publish(path: Path, raw: bytes, mode: int) -> str:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    descriptor = -1
    linked = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
        )
        os.fchmod(descriptor, mode)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                fail("audit_publication_failed")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        linked = True
        sync_directory(path.parent)
        os.unlink(temporary)
        sync_directory(path.parent)
    except (OSError, AuditError) as error:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            if temporary.exists() and (
                not linked or temporary.stat().st_ino == path.stat().st_ino
            ):
                temporary.unlink()
        except OSError:
            pass
        if isinstance(error, AuditError):
            raise
        raise AuditError("audit_publication_failed") from error
    digest = sha256_bytes(raw)
    if file_bytes(path, expected_sha256=digest, mode=mode, maximum=1 << 20) != raw:
        fail("audit_publication_failed")
    return digest


@contextmanager
def output_lock() -> Iterator[None]:
    require_directory(OUTPUT_ROOT, 0o700)
    lock_path = OUTPUT_ROOT / ".writer.lock"
    descriptor = -1
    try:
        descriptor = os.open(lock_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        after = os.stat(lock_path, follow_symlinks=False)

        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_uid,
                value.st_nlink,
                value.st_size,
            )

        if (
            identity(before) != identity(after)
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != OWNER_UID
            or before.st_nlink != 1
            or before.st_size != 0
        ):
            fail("output_lock_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AuditError("output_writer_active") from error
        yield
    except OSError as error:
        raise AuditError("output_lock_invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def load_audit_modules() -> Iterator[tuple[types.ModuleType, types.ModuleType]]:
    original_path = list(sys.path)
    original_modules = dict(sys.modules)
    generator = None
    v1 = None
    try:
        try:
            generator = LAUNCH.load_generator()
            v1 = generator.load_v1()
            generator.validate_execution_source(v1)
        except Exception as error:
            raise AuditError("pinned_auditor_import_invalid") from error
        try:
            with generator.snapshot_module_scope(v1) as modules:
                yield modules
        except generator.SelectionV22Error as error:
            raise AuditError("pinned_auditor_import_invalid") from error
    finally:
        source_error: Exception | None = None
        if generator is not None and v1 is not None:
            try:
                generator.validate_execution_source(v1)
            except Exception as error:  # noqa: BLE001 - mapped to a stable code below.
                source_error = error
        sys.path[:] = original_path
        for name in tuple(sys.modules):
            if name not in original_modules:
                sys.modules.pop(name, None)
        for name, module in original_modules.items():
            sys.modules[name] = module
        if source_error is not None:
            raise AuditError("pinned_auditor_source_changed") from source_error


def validate_attempt_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    retried_rows = 0
    failure_events = 0
    final_timeouts = 0
    maximum_attempts = 0
    for row in rows:
        attempts = row.get("attempts")
        failures = row.get("infrastructure_failures")
        if (
            type(attempts) is not int
            or not 1 <= attempts <= 5
            or not isinstance(failures, list)
        ):
            fail("result_attempt_policy_invalid")
        for expected_attempt, failure_record in enumerate(failures, start=1):
            if (
                not isinstance(failure_record, dict)
                or set(failure_record) != {"attempt", "error", "error_type"}
                or failure_record.get("attempt") != expected_attempt
                or failure_record.get("error_type") != "SandboxError"
                or not isinstance(failure_record.get("error"), str)
            ):
                fail("result_attempt_policy_invalid")
        exhausted = (
            row.get("reason") == "infrastructure_error"
            and row.get("error_type") == "SandboxError"
        )
        if (exhausted and (attempts != 5 or len(failures) != 5)) or (
            not exhausted and len(failures) != attempts - 1
        ):
            fail("result_attempt_policy_invalid")
        if row.get("reason") == "timeout":
            if row.get("error_type") != "TimeoutError":
                fail("result_attempt_policy_invalid")
            final_timeouts += 1
        elif row.get("error_type") == "SandboxError" and not exhausted:
            fail("result_attempt_policy_invalid")
        retried_rows += attempts > 1
        failure_events += len(failures)
        maximum_attempts = max(maximum_attempts, attempts)
    return {
        "rows_with_sandbox_retries": retried_rows,
        "sandbox_error_events": failure_events,
        "final_asyncio_timeout_rows": final_timeouts,
        "maximum_attempts_observed": maximum_attempts,
    }


def acceptance_counts(
    rows: Sequence[Mapping[str, Any]],
    candidates: set[str],
    controls: set[str],
) -> dict[str, int]:
    if (
        len(rows) != 19
        or len(candidates) != 15
        or len(controls) != 4
        or candidates & controls
        or {row.get("slug") for row in rows} != candidates | controls
    ):
        fail("oracle_output_universe_invalid")
    by_slug = {str(row["slug"]): row for row in rows}
    candidate_valid = sum(bool(by_slug[slug].get("valid")) for slug in candidates)
    control_valid = sum(bool(by_slug[slug].get("valid")) for slug in controls)
    total_valid = candidate_valid + control_valid
    if control_valid != 4:
        fail("control_regression")
    if candidate_valid < 6 or total_valid < 10:
        fail("recovery_threshold_not_met")
    return {
        "selected": 19,
        "completed": 19,
        "candidates": 15,
        "controls": 4,
        "candidate_valid": candidate_valid,
        "control_valid": control_valid,
        "total_valid": total_valid,
    }


def parse_provenance(raw: bytes, *, identity_sha: str, job_id: str) -> str:
    try:
        text = raw.decode("utf-8")
        records: dict[str, str] = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if not separator or not key or not value or key in records:
                fail("output_provenance_invalid")
            records[key] = value
    except UnicodeDecodeError as error:
        raise AuditError("output_provenance_invalid") from error
    if (
        not raw.endswith(b"\n")
        or not text
        or set(records)
        != {
            "prime_rl",
            "prime_rl_tree",
            "verifiers",
            "vmvm_tb_v2",
            "host",
            "slurm_job_id",
            "oracle_solution_network_mode",
            "run_identity_sha256",
        }
        or records.get("prime_rl") != LAUNCH.SOURCE_REVISION
        or records.get("prime_rl_tree")
        != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        or records.get("verifiers") != LAUNCH.VERIFIERS_REVISION
        or records.get("vmvm_tb_v2") != LAUNCH.VMVM_SHA256
        or not records.get("host", "").strip()
        or records.get("slurm_job_id") != job_id
        or records.get("oracle_solution_network_mode") != "public"
        or records.get("run_identity_sha256") != identity_sha
    ):
        fail("output_provenance_invalid")
    return records["host"]


def output_snapshot() -> dict[str, Any]:
    require_directory(OUTPUT_ROOT, 0o700)
    require_directory(OUTPUT_ROOT / "tasks", 0o700)
    try:
        children = {entry.name for entry in os.scandir(OUTPUT_ROOT)}
        status_paths = sorted(
            (Path(entry.path) for entry in os.scandir(OUTPUT_ROOT / "tasks")),
            key=lambda path: path.name,
        )
    except OSError as error:
        raise AuditError("output_directory_invalid") from error
    if children != EXPECTED_OUTPUT_CHILDREN or len(status_paths) != 19:
        fail("output_directory_invalid")
    top_level = {
        name: sha256_bytes(file_bytes(OUTPUT_ROOT / name, mode=0o600))
        for name in sorted(EXPECTED_OUTPUT_CHILDREN - {".writer.lock", "tasks"})
    }
    status_records: list[bytes] = []
    for path in status_paths:
        if path.suffix != ".json":
            fail("output_directory_invalid")
        raw = file_bytes(path, mode=0o600)
        status_records.append(
            sha256_bytes(path.name.encode("utf-8")).encode("ascii")
            + b"\0"
            + sha256_bytes(raw).encode("ascii")
            + b"\n"
        )
    return {
        "top_level_sha256": top_level,
        "task_status_count": len(status_paths),
        "task_status_tree_sha256": sha256_bytes(b"".join(status_records)),
    }


def audit_output(launch: Mapping[str, Any]) -> dict[str, Any]:
    task_raw = file_bytes(
        LAUNCH.TASK_FILE,
        expected_sha256=launch["task_sha"],
        mode=0o600,
        maximum=1 << 20,
    )
    role_raw = file_bytes(
        LAUNCH.ROLE_FILE,
        expected_sha256=launch["role_sha"],
        mode=0o600,
        maximum=1 << 20,
    )
    tasks = task_raw.decode("utf-8").splitlines()
    roles = strict_json(role_raw)
    candidates = set(roles["candidates"])
    controls = set(roles["controls"])
    with output_lock():
        initial_snapshot = output_snapshot()
        try:
            children = {entry.name for entry in os.scandir(OUTPUT_ROOT)}
        except OSError as error:
            raise AuditError("output_directory_invalid") from error
        if children != EXPECTED_OUTPUT_CHILDREN:
            fail("output_directory_invalid")
        require_directory(OUTPUT_ROOT / "tasks", 0o700)
        captured = {
            name: file_bytes(OUTPUT_ROOT / name, mode=0o600)
            for name in EXPECTED_OUTPUT_CHILDREN
            if name not in {".writer.lock", "tasks"}
        }
        identity_wrapper = strict_json(captured["run_identity.json"])
        if set(identity_wrapper) != {
            "schema_version",
            "identity",
            "run_identity_sha256",
        }:
            fail("run_identity_invalid")
        identity = identity_wrapper.get("identity")
        identity_sha = identity_wrapper.get("run_identity_sha256")
        if (
            identity_wrapper.get("schema_version") != 1
            or not isinstance(identity, dict)
            or not isinstance(identity_sha, str)
            or identity_sha != sha256_bytes(canonical_json(identity))
        ):
            fail("run_identity_invalid")
        expected_network = {
            "schema_version": 1,
            "trusted_reference_solution": "public",
            "verifier": "declared",
        }
        expected_execution = {
            "max_concurrent": 4,
            "infra_retries": 4,
            "setup_timeout_sec": 7200.0,
            "validate_timeout_sec": 21600.0,
            "session_timeout_sec": 43200.0,
            "tenant_id": "async_2347641",
            "lease_ttl": "60s",
            "max_session_buffer_size": 67_108_864,
            "verifier_runtime_retries": 2,
            "vacli_lease_retries": 20,
            "vacli_max_concurrent_leases": 2,
            "vacli_max_pull_retries": 20,
            "vacli_image_pull_timeout_seconds": 7200,
            "vacli_container_privileged": True,
            "timeout_multiplier": 4.0,
            "resource_multiplier": 2.0,
            "runtime_image": "python:3.12-slim",
            "runtime_workdir": "/app",
        }
        expected_selection = {
            "count": 19,
            "ordered_task_slugs_sha256": launch["task_sha"],
            "offset": 0,
            "limit": None,
            "task_file": {"path": str(LAUNCH.TASK_FILE), "sha256": launch["task_sha"]},
        }
        if (
            set(identity)
            != {
                "schema_version",
                "dataset",
                "selection",
                "images",
                "source",
                "network_semantics",
                "execution",
                "acceptance",
            }
            or identity.get("schema_version") != 1
            or identity.get("dataset")
            != {
                "path": str(LAUNCH.DATASET),
                "revision": LAUNCH.DATASET_REVISION,
                "archive": {"path": None, "sha256": None},
                "content_sha256": None,
            }
            or identity.get("selection") != expected_selection
            or identity.get("images")
            != {
                "prefix": LAUNCH.IMAGE_PREFIX,
                "tag": LAUNCH.IMAGE_TAG,
                "manifest": {
                    "path": str(LAUNCH.IMAGE_MANIFEST),
                    "sha256": LAUNCH.IMAGE_MANIFEST_SHA256,
                },
                "use_declared_images": False,
                "enable_compose": False,
            }
            or identity.get("source")
            != {
                "prime_rl_commit": LAUNCH.SOURCE_REVISION,
                "prime_rl_tree_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "verifiers_commit": LAUNCH.VERIFIERS_REVISION,
                "vmvm_tb_v2_sha256": LAUNCH.VMVM_SHA256,
            }
            or identity.get("network_semantics") != expected_network
            or identity.get("execution") != expected_execution
            or identity.get("acceptance")
            != {"minimum_pass_rate": 0.0, "minimum_valid": 10}
        ):
            fail("run_identity_invalid")
        if strict_json(captured["oracle_network_semantics.json"]) != expected_network:
            fail("network_semantics_invalid")

        run_config = strict_json(captured["run_config.json"])
        started_at = run_config.pop("started_at", None)
        expected_config = {
            "schema_version": 1,
            "run_identity_sha256": identity_sha,
            "dataset_dir": str(LAUNCH.DATASET),
            "dataset_revision": LAUNCH.DATASET_REVISION,
            "dataset_archive": None,
            "dataset_archive_sha256": None,
            "dataset_content_sha256": None,
            "task_file": str(LAUNCH.TASK_FILE),
            "task_file_sha256": launch["task_sha"],
            "image_prefix": LAUNCH.IMAGE_PREFIX,
            "image_tag": LAUNCH.IMAGE_TAG,
            "image_manifest": str(LAUNCH.IMAGE_MANIFEST),
            "image_manifest_sha256": LAUNCH.IMAGE_MANIFEST_SHA256,
            "use_declared_images": False,
            "enable_compose": False,
            "max_concurrent": 4,
            "infra_retries": 4,
            "setup_timeout": 7200.0,
            "validate_timeout": 21600.0,
            "session_timeout": 43200.0,
            "tenant_id": "async_2347641",
            "lease_ttl": "60s",
            "max_session_buffer_size": 67_108_864,
            "verifier_runtime_retries": 2,
            "vacli_lease_retries": 20,
            "vacli_max_concurrent_leases": 2,
            "vacli_max_pull_retries": 20,
            "vacli_image_pull_timeout_seconds": 7200,
            "vacli_container_privileged": True,
            "timeout_multiplier": 4.0,
            "resource_multiplier": 2.0,
            "minimum_pass_rate": 0.0,
            "minimum_valid": 10,
            "oracle_solution_network_mode": "public",
            "oracle_network_semantics": expected_network,
            "selected_tasks": 19,
        }
        if (
            isinstance(started_at, bool)
            or not isinstance(started_at, (int, float))
            or not math.isfinite(started_at)
            or started_at <= 0
            or run_config != expected_config
        ):
            fail("run_config_invalid")

        host = parse_provenance(
            captured["provenance.txt"],
            identity_sha=identity_sha,
            job_id=launch["job_id"],
        )
        invocation_lines = captured["invocations.jsonl"].splitlines()
        if len(invocation_lines) != 1:
            fail("invocation_history_invalid")
        invocation = strict_json(invocation_lines[0])
        invoked_at = invocation.get("invoked_at")
        if (
            set(invocation)
            != {
                "schema_version",
                "run_identity_sha256",
                "invoked_at",
                "resume",
                "reuse_completed_rows",
                "rerun_invalid",
                "host",
                "slurm_job_id",
                "source",
            }
            or invocation.get("schema_version") != 1
            or invocation.get("run_identity_sha256") != identity_sha
            or isinstance(invoked_at, bool)
            or not isinstance(invoked_at, (int, float))
            or not math.isfinite(invoked_at)
            or invoked_at <= 0
            or invocation.get("resume") is not False
            or invocation.get("reuse_completed_rows") is not True
            or invocation.get("rerun_invalid") is not False
            or invocation.get("host") != host
            or invocation.get("slurm_job_id") != launch["job_id"]
            or invocation.get("source") != identity["source"]
        ):
            fail("invocation_history_invalid")

        with load_audit_modules() as (audit, builder):
            try:
                audit._validate_identity_contract(
                    identity, error="run_identity_invalid"
                )
                rows, reasons, results_sha, results_path, results_raw = (
                    builder._results(
                        OUTPUT_ROOT,
                        expected_total=19,
                        identity_sha256=identity_sha,
                        network_semantics=expected_network,
                        ordered_slugs_sha256=launch["task_sha"],
                    )
                )
                passed = sum(row["valid"] for row in rows)
                summary_sha, summary_path, summary_raw = builder._summary(
                    OUTPUT_ROOT,
                    expected_total=19,
                    identity_sha256=identity_sha,
                    network_semantics=expected_network,
                    reasons=reasons,
                    passed=passed,
                )
                status_count = builder._statuses(OUTPUT_ROOT, rows)
            except Exception as error:
                raise AuditError("oracle_output_invalid") from error
        if [row["slug"] for row in rows] != tasks or status_count != 19:
            fail("oracle_output_universe_invalid")
        counts = acceptance_counts(rows, candidates, controls)
        if counts["total_valid"] != passed:
            fail("oracle_output_invalid")
        attempt_observations = validate_attempt_rows(rows)

        for row in rows:
            file_bytes(
                OUTPUT_ROOT / "tasks" / f"{row['slug']}.json",
                mode=0o600,
            )
        for name, raw in captured.items():
            if (
                file_bytes(
                    OUTPUT_ROOT / name,
                    expected_sha256=sha256_bytes(raw),
                    mode=0o600,
                )
                != raw
            ):
                fail("output_changed")
        if (
            file_bytes(results_path, expected_sha256=results_sha, mode=0o600)
            != results_raw
            or file_bytes(summary_path, expected_sha256=summary_sha, mode=0o600)
            != summary_raw
            or output_snapshot() != initial_snapshot
        ):
            fail("output_changed")
    return {
        "run_identity_sha256": identity_sha,
        "run_identity_file_sha256": sha256_bytes(captured["run_identity.json"]),
        "run_config_file_sha256": sha256_bytes(captured["run_config.json"]),
        "provenance_file_sha256": sha256_bytes(captured["provenance.txt"]),
        "invocations_file_sha256": sha256_bytes(captured["invocations.jsonl"]),
        "results_file_sha256": results_sha,
        "summary_file_sha256": summary_sha,
        "counts": counts,
        "reason_counts": dict(sorted(reasons.items())),
        "attempt_observations": attempt_observations,
        "artifact_snapshot": initial_snapshot,
    }


def publish_after_final_revalidation(
    *,
    launch: Mapping[str, Any],
    output: Mapping[str, Any],
    body: Mapping[str, Any],
) -> str:
    expected_snapshot = output.get("artifact_snapshot")
    if not isinstance(expected_snapshot, dict):
        fail("output_snapshot_invalid")
    with output_lock():
        if output_snapshot() != expected_snapshot:
            fail("output_changed_before_publication")
        require_terminal_job(launch["job_id"], launch["job_name"])
        launch_after = validate_launch_artifacts(LAUNCHER_SHA256)
        if launch_after != launch:
            fail("launch_artifacts_changed")
        validate_artifact_root_inventory()
        return seal_terminal(body, success=True)


def seal_terminal(body: Mapping[str, Any], *, success: bool) -> str:
    validate_artifact_root_inventory()
    target = CERTIFICATE if success else FAILURE
    other = FAILURE if success else CERTIFICATE
    if target.exists() or target.is_symlink() or other.exists() or other.is_symlink():
        fail("audit_terminal_conflict")
    field = "certificate_sha256" if success else "failure_certificate_sha256"
    raw = envelope(body, field)
    digest = atomic_publish(target, raw, 0o400)
    try:
        sync_directory(AUDIT_ROOT)
        os.chmod(AUDIT_ROOT, 0o500, follow_symlinks=False)
        sync_directory(AUDIT_ROOT.parent)
        require_directory(AUDIT_ROOT, 0o500)
        if (
            file_bytes(target, expected_sha256=digest, mode=0o400, maximum=1 << 20)
            != raw
            or other.exists()
            or other.is_symlink()
        ):
            fail("audit_terminal_conflict")
    except (OSError, AuditError) as error:
        try:
            if stat.S_IMODE(AUDIT_ROOT.stat(follow_symlinks=False).st_mode) == 0o700:
                target.unlink(missing_ok=True)
                sync_directory(AUDIT_ROOT)
        except OSError:
            pass
        if isinstance(error, AuditError):
            raise
        raise AuditError("audit_publication_failed") from error
    return digest


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        fail("arguments_forbidden")
    auditor_sha = validate_invocation()
    launch = validate_launch_artifacts(LAUNCHER_SHA256)
    require_terminal_job(launch["job_id"], launch["job_name"])
    intent_file_sha = create_audit_reservation(auditor_sha, launch)
    try:
        output = audit_output(launch)
        body = {
            "schema_version": 1,
            "kind": "terminal_bench_vmvm_infrastructure_retry_v22_post_run_audit",
            "state": "passed",
            "auditor_sha256": auditor_sha,
            "launcher_sha256": LAUNCHER_SHA256,
            "audit_intent_file_sha256": intent_file_sha,
            "selection": {
                "receipt_file_sha256": launch["selection_file_sha"],
                "receipt_sha256": launch["selection_sha"],
                "task_file_sha256": launch["task_sha"],
                "role_file_sha256": launch["role_sha"],
            },
            "submission": {
                "receipt_file_sha256": launch["submission_file_sha"],
                "receipt_sha256": launch["submission_sha"],
                "intent_sha256": launch["intent_sha"],
                "environment_sha256": launch["environment_sha"],
                "authorization_file_sha256": launch["authorization_file_sha"],
                "authorization_sha256": launch["authorization_sha"],
                "activation_permit_file_sha256": launch["activation_permit_file_sha"],
                "activation_permit_sha256": launch["activation_permit_sha"],
                "verifiers_revision": LAUNCH.VERIFIERS_REVISION,
                "vmvm_tb_v2_sha256": LAUNCH.VMVM_SHA256,
                "x2p_environment_sha256": launch["x2p_sha256"],
            },
            "scheduler": {
                "cluster": LAUNCH.CLUSTER,
                "job_id": launch["job_id"],
                "state": "COMPLETED",
                "exit_code": "0:0",
            },
            "attempt_policy": LAUNCH.ATTEMPT_POLICY,
            "module_import_closure": launch["module_import_closure"],
            "scheduler_lifecycle": launch["scheduler_lifecycle"],
            "output": output,
            "acceptance": {
                "exact_completed": 19,
                "all_controls_valid": True,
                "minimum_candidate_recoveries": 6,
                "minimum_valid": 10,
                "passed": True,
            },
            "automatic_union_or_promotion": False,
        }
        certificate_sha = publish_after_final_revalidation(
            launch=launch,
            output=output,
            body=body,
        )
    except Exception as error:  # noqa: BLE001 - seal every post-reservation failure
        code = (
            str(error)
            if isinstance(error, AuditError) and SAFE_CODE_RE.fullmatch(str(error))
            else "audit_failed"
        )
        if AUDIT_ROOT.exists() and not CERTIFICATE.exists() and not FAILURE.exists():
            try:
                seal_terminal(
                    {
                        "schema_version": 1,
                        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_post_run_audit",
                        "state": "failed",
                        "code": code,
                        "auditor_sha256": auditor_sha,
                        "launcher_sha256": LAUNCHER_SHA256,
                        "module_import_closure": launch["module_import_closure"],
                        "scheduler_lifecycle": launch["scheduler_lifecycle"],
                        "audit_intent_file_sha256": intent_file_sha,
                        "selection_receipt_file_sha256": launch["selection_file_sha"],
                        "submission_receipt_file_sha256": launch["submission_file_sha"],
                        "authorization_file_sha256": launch["authorization_file_sha"],
                        "activation_permit_file_sha256": launch[
                            "activation_permit_file_sha"
                        ],
                        "x2p_environment_sha256": launch["x2p_sha256"],
                        "verifiers_revision": LAUNCH.VERIFIERS_REVISION,
                        "vmvm_tb_v2_sha256": LAUNCH.VMVM_SHA256,
                        "scheduler": {
                            "cluster": LAUNCH.CLUSTER,
                            "job_id": launch["job_id"],
                        },
                        "automatic_union_or_promotion": False,
                    },
                    success=False,
                )
            except AuditError:
                pass
        raise AuditError(code) from None
    print(
        json.dumps(
            {"state": "passed", "certificate_sha256": certificate_sha}, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    try:
        raise SystemExit(main())
    except AuditError as error:
        code = str(error) if SAFE_CODE_RE.fullmatch(str(error)) else "audit_failed"
        print(
            json.dumps({"state": "aborted", "code": code}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except Exception:  # noqa: BLE001 - never expose task or result content
        print(
            json.dumps({"state": "aborted", "code": "audit_failed"}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
