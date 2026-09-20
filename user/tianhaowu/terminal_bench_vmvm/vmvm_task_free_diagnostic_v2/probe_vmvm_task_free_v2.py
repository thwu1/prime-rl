#!/usr/bin/env python3
# ruff: noqa: BLE001
"""Aggregate-only, task-free VMVM pre-lease admission diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

SOURCE_REVISION = "a09a9a189697034e23b776fdbfccb369522c469d"
SOURCE_TREE = "58bec828df10962ec5411762837aa6e3f71461da"
VERIFIERS_REVISION = "ef35ac787de13c95953ce0ac0225202e544711ce"
RENDERERS_REVISION = "044d9e2541f6a911cacae9da353fc063911ef1f8"
PYDANTIC_CONFIG_REVISION = "896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f"
VMVM_SHA256 = "1e7c8ac2906a45d8212d609b5900fdc3d30f91ba73d4bcdb1c36dfc8bfdd09e2"
X86_UV_SHA256 = "ec831939765474162efb6c8c813e2b10908b26b04eaf98ac3e2972fa12d189b9"
VACLI_SHA256 = "8be49a764bd0fac1a3ef2bef053ced556d18397d44642660eb8a2d22a7c235b3"
VACLI_RESOLVED = "/infra/public/fbpkgs/x86_64/vacli/794/vacli"
IMAGE = "python:3.12-slim"
WORKDIR = "/app"
TENANT_ID = "async_2347641"
LEASE_TTL = "60s"
LEASE_TTL_SECONDS = 60
SESSION_TIMEOUT_SECONDS = 43_200.0
STAGE_TIMEOUT_SECONDS = 1_800
LEASE_ATTEMPT_LIMIT = 2
IMAGE_PULL_TIMEOUT_SECONDS = 300
IMAGE_PULL_RETRY_LIMIT = 1
RECOVERY_ATTEMPTS = 5
RELEASE_GRACE_SECONDS = 5
MAX_CHILD_OUTPUT_BYTES = 1 << 20
MAX_RESULT_BYTES = 1 << 20
MAX_RENEWER_JOURNAL_BYTES = 1 << 20
REQUIRED_MEMFD_SEALS = (
    fcntl.F_SEAL_SEAL
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_WRITE
    | 0x20  # F_SEAL_EXEC; absent from Python 3.12 fcntl constants.
)
X2P_NAMES = ("X2P_ENV", "X2P_CFG_ENV", "X2P_PROXY_URL")
TLS_NAMES = ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH")
DIRECTORY_IDENTITY_POLICY_NAME = "nfs_portable_inode_mode_uid_v1"
DIRECTORY_IDENTITY_POLICY = {
    "batch_fields": ["inode", "mode", "owner_uid"],
    "cross_host_variance": ["device"],
    "launcher_fields": ["device", "inode", "mode", "owner_uid"],
    "path_binding": "absolute_canonical_no_symlink",
}
PREFLIGHT_PROTOCOL = {
    "directory_identity_policy": DIRECTORY_IDENTITY_POLICY,
    "diagnostic_only": True,
    "preflight_only": True,
    "production_authorized": False,
}
ENVIRONMENT_EXPORT_POLICY = "sealed_nul_file_only"
BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
EXPECTED_SOURCE_ROOT = BASE / "sources/prime-rl-a09a9a189-v21"
EXPECTED_OUTPUT_ROOT = BASE / "diagnostics/vmvm_v21_task_free_preflight_a09a9a189_v7_portable_identity"
EXPECTED_RESERVATION = Path(f"{EXPECTED_OUTPUT_ROOT}.launch-reservation")
EXPECTED_SCRATCH_ROOT = Path("/tmp/vmvm-v21-task-free-preflight-v7-portable-identity")
EXPECTED_COMPLETION_RECEIPT = Path(f"{EXPECTED_OUTPUT_ROOT}.external-completion.json")
EXPECTED_CLUSTER = "fair-cw-use2-3"
EXPECTED_OWNER = "tianhaowu"
SHA_RE = re.compile(r"[0-9a-f]{64}")
NAME_RE = re.compile(r"vmvm-v7-preflight-[0-9a-f]{24}")
STAGES = (
    "direct_client",
    "same_thread_raw",
    "same_thread_recovery",
    "cross_thread_raw",
    "cross_thread_recovery",
    "runtime_contract",
)
MODES = ("absent", "present")
# ABBA repeats every stage four times without privileging either wall-clock order.
MODE_ORDERS = (
    ("absent", "present"),
    ("present", "absent"),
    ("present", "absent"),
    ("absent", "present"),
)
REPETITIONS = len(MODE_ORDERS)
CELL_COUNT = len(STAGES) * len(MODES) * REPETITIONS
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


class DiagnosticError(RuntimeError):
    """Stable diagnostic failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _LandlockPathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
        ("reserved", ctypes.c_uint32),
    ]


_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38
_LANDLOCK_WRITE_ACCESS = sum(1 << bit for bit in (1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14))
_INOTIFY_MUTATION_MASK = sum(
    value
    for value in (
        0x00000002,  # IN_MODIFY
        0x00000004,  # IN_ATTRIB
        0x00000008,  # IN_CLOSE_WRITE
        0x00000040,  # IN_MOVED_FROM
        0x00000080,  # IN_MOVED_TO
        0x00000100,  # IN_CREATE
        0x00000200,  # IN_DELETE
        0x00000400,  # IN_DELETE_SELF
        0x00000800,  # IN_MOVE_SELF
        0x00002000,  # IN_UNMOUNT
        0x00004000,  # IN_Q_OVERFLOW
        0x00008000,  # IN_IGNORED
    )
)
_INOTIFY_CLEANUP_MASK = sum(
    value
    for value in (
        0x00000002,  # IN_MODIFY
        0x00000004,  # IN_ATTRIB
        0x00000008,  # IN_CLOSE_WRITE
        0x00000040,  # IN_MOVED_FROM
        0x00000080,  # IN_MOVED_TO
        0x00000100,  # IN_CREATE
        0x00000200,  # IN_DELETE
        0x00000400,  # IN_DELETE_SELF
        0x00000800,  # IN_MOVE_SELF
        0x00002000,  # IN_UNMOUNT
        0x00004000,  # IN_Q_OVERFLOW
        0x00008000,  # IN_IGNORED
    )
)
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_DELETE = 0x00000200
_IN_ISDIR = 0x40000000
_INOTIFY_EVENT = struct.Struct("iIII")


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def descriptor_identity(descriptor: int) -> dict[str, int]:
    info = os.fstat(descriptor)
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "owner_uid": info.st_uid,
    }


def portable_directory_identity(identity: Mapping[str, object]) -> dict[str, int]:
    if set(identity) != {"device", "inode", "mode", "owner_uid"} or any(
        type(identity.get(name)) is not int for name in ("device", "inode", "mode", "owner_uid")
    ):
        raise DiagnosticError("child_invalid")
    return {name: int(identity[name]) for name in ("inode", "mode", "owner_uid")}


def canonical_directory_path(path: Path) -> bool:
    try:
        return path.is_absolute() and path == Path(os.path.normpath(path)) and path.resolve(strict=True) == path
    except OSError:
        return False


def open_bound_directory(
    path: Path,
    expected: Mapping[str, object],
    *,
    required_mode: int | None = None,
) -> int:
    if set(expected) != {"device", "inode", "mode", "owner_uid"}:
        raise DiagnosticError("source_binding_invalid")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise DiagnosticError("source_binding_invalid") from error
    identity = descriptor_identity(descriptor)
    if (
        identity != expected
        or identity["owner_uid"] != os.getuid()
        or (required_mode is not None and identity["mode"] != required_mode)
    ):
        os.close(descriptor)
        raise DiagnosticError("source_binding_invalid")
    return descriptor


def open_portable_bound_directory(
    path: Path,
    expected: Mapping[str, object],
    *,
    code: str = "source_binding_invalid",
    required_mode: int | None = None,
) -> int:
    if set(expected) != {"inode", "mode", "owner_uid"} or not canonical_directory_path(path):
        raise DiagnosticError(code)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise DiagnosticError(code) from error
    identity = portable_directory_identity(descriptor_identity(descriptor))
    if (
        identity != expected
        or identity["owner_uid"] != os.getuid()
        or (required_mode is not None and identity["mode"] != required_mode)
    ):
        os.close(descriptor)
        raise DiagnosticError(code)
    return descriptor


def descriptor_path(descriptor: int) -> Path:
    return Path(f"/proc/self/fd/{descriptor}")


def inherited_descriptor(path: Path) -> int | None:
    match = re.fullmatch(r"/proc/self/fd/([3-9]|[1-9][0-9]+)", str(path))
    if match is None:
        return None
    descriptor = int(match.group(1))
    os.fstat(descriptor)
    return descriptor


def inherited_bound_directory(
    path: Path,
    expected: Mapping[str, object],
    *,
    code: str,
    required_mode: int | None = None,
) -> int:
    """Duplicate an inherited directory descriptor without reopening its path."""
    try:
        inherited = inherited_descriptor(path)
        if inherited is None:
            raise DiagnosticError(code)
        descriptor = os.dup(inherited)
    except (OSError, ValueError) as error:
        raise DiagnosticError(code) from error
    identity = descriptor_identity(descriptor)
    if (
        set(expected) != {"device", "inode", "mode", "owner_uid"}
        or identity != expected
        or identity["owner_uid"] != os.getuid()
        or (required_mode is not None and identity["mode"] != required_mode)
    ):
        os.close(descriptor)
        raise DiagnosticError(code)
    return descriptor


def inherited_portable_bound_directory(
    path: Path,
    expected: Mapping[str, object],
    *,
    code: str,
    required_mode: int | None = None,
) -> int:
    """Duplicate an inherited directory descriptor and verify its portable identity."""
    try:
        inherited = inherited_descriptor(path)
        if inherited is None:
            raise DiagnosticError(code)
        descriptor = os.dup(inherited)
    except (OSError, ValueError) as error:
        raise DiagnosticError(code) from error
    identity = portable_directory_identity(descriptor_identity(descriptor))
    if (
        set(expected) != {"inode", "mode", "owner_uid"}
        or identity != expected
        or identity["owner_uid"] != os.getuid()
        or (required_mode is not None and identity["mode"] != required_mode)
    ):
        os.close(descriptor)
        raise DiagnosticError(code)
    return descriptor


def directory_manifest(
    descriptor: int,
    *,
    expected_owner_uid: int,
    maximum_entries: int = 50_000,
    maximum_bytes: int = 1 << 30,
) -> dict[str, object]:
    entries: list[bytes] = []
    total_bytes = 0
    root_identity = descriptor_identity(descriptor)
    if root_identity["owner_uid"] != expected_owner_uid:
        raise DiagnosticError("site_binding_invalid")

    def visit(current_fd: int, relative_root: str) -> None:
        nonlocal total_bytes
        for name in sorted(os.listdir(current_fd)):
            info = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            if info.st_uid != expected_owner_uid:
                raise DiagnosticError("site_binding_invalid")
            relative = f"{relative_root}/{name}".lstrip("/")
            if stat.S_ISDIR(info.st_mode):
                entries.append(f"d\0{relative}\0{stat.S_IMODE(info.st_mode):o}\0{info.st_uid}\n".encode())
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
                        raise DiagnosticError("site_binding_invalid")
                    visit(child_fd, relative)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(info.st_mode):
                raise DiagnosticError("site_binding_invalid")
            file_descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current_fd)
            try:
                before = os.fstat(file_descriptor)
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(file_descriptor, 1 << 20)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    total_bytes += len(chunk)
                    if total_bytes > maximum_bytes:
                        raise DiagnosticError("site_binding_invalid")
                after = os.fstat(file_descriptor)
            finally:
                os.close(file_descriptor)
            stable_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
            if (
                any(getattr(before, field) != getattr(after, field) for field in stable_fields)
                or size != before.st_size
            ):
                raise DiagnosticError("site_binding_invalid")
            entries.append(
                (
                    f"f\0{relative}\0{stat.S_IMODE(info.st_mode):o}\0{info.st_uid}"
                    f"\0{info.st_size}\0{digest.hexdigest()}\n"
                ).encode()
            )
            if len(entries) > maximum_entries:
                raise DiagnosticError("site_binding_invalid")

    visit(descriptor, "")
    if descriptor_identity(descriptor) != root_identity:
        raise DiagnosticError("site_binding_invalid")
    entries.sort()
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry)
    return {
        "entry_count": len(entries),
        "manifest_sha256": digest.hexdigest(),
        "owner_uid": expected_owner_uid,
        "total_bytes": total_bytes,
    }


def _source_git(command: Sequence[str], *, pass_fds: Sequence[int]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
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


def _source_git_records(result: subprocess.CompletedProcess[str]) -> list[str]:
    if result.returncode != 0 or result.stderr or not result.stdout.endswith("\0"):
        raise DiagnosticError("source_binding_invalid")
    return result.stdout[:-1].split("\0") if result.stdout else []


def _open_source_directory_at(root_fd: int, relative: str) -> int:
    descriptor = os.dup(root_fd)
    try:
        for component in relative.split("/"):
            if component in {"", "."}:
                continue
            if component == "..":
                raise DiagnosticError("source_binding_invalid")
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                raise DiagnosticError("source_binding_invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _source_blob_oid(directory_fd: int, relative: str, git_mode: str) -> str:
    components = relative.split("/")
    if (
        not components
        or any(component in {"", ".", ".."} for component in components)
        or git_mode not in {"100644", "100755"}
    ):
        raise DiagnosticError("source_binding_invalid")
    parent_fd = os.dup(directory_fd)
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
                raise DiagnosticError("source_binding_invalid")
        file_fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as error:
        raise DiagnosticError("source_binding_invalid") from error
    finally:
        os.close(parent_fd)
    try:
        before = os.fstat(file_fd)
        executable = bool(before.st_mode & 0o111)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or executable != (git_mode == "100755")
        ):
            raise DiagnosticError("source_binding_invalid")
        digest = hashlib.sha1(f"blob {before.st_size}\0".encode(), usedforsecurity=False)
        size = 0
        while True:
            chunk = os.read(file_fd, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(file_fd)
    finally:
        os.close(file_fd)
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields) or size != before.st_size:
        raise DiagnosticError("source_binding_invalid")
    return digest.hexdigest()


def _attest_git_repository(
    repository_fd: int,
    *,
    expected_revision: str,
    pathspecs: Sequence[str] = (),
    expected_gitlinks: Mapping[str, str] | None = None,
) -> dict[str, tuple[str, str]]:
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
        raise DiagnosticError("source_binding_invalid")
    stage_result = _source_git(
        ["-C", root, "ls-files", "--stage", "-z", *suffix],
        pass_fds=inherited,
    )
    tree_result = _source_git(
        ["-C", root, "ls-tree", "-r", "-z", "--full-tree", "HEAD", *suffix],
        pass_fds=inherited,
    )
    flag_results = tuple(
        _source_git(
            ["-C", root, "ls-files", option, "-z", *suffix],
            pass_fds=inherited,
        )
        for option in ("-v", "-f")
    )
    stage_records = _source_git_records(stage_result)
    tree_records = _source_git_records(tree_result)
    if not stage_records or not tree_records:
        raise DiagnosticError("source_binding_invalid")
    index: dict[str, tuple[str, str]] = {}
    for record in stage_records:
        metadata, separator, path = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != "0" or path in index:
            raise DiagnosticError("source_binding_invalid")
        index[path] = (fields[0], fields[1])
    tree: dict[str, tuple[str, str]] = {}
    for record in tree_records:
        metadata, separator, path = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or path in tree:
            raise DiagnosticError("source_binding_invalid")
        mode, object_type, object_id = fields
        if object_type != ("commit" if mode == "160000" else "blob"):
            raise DiagnosticError("source_binding_invalid")
        tree[path] = (mode, object_id)
    if index != tree:
        raise DiagnosticError("source_binding_invalid")
    for flag_result in flag_results:
        observed_paths: list[str] = []
        for record in _source_git_records(flag_result):
            tag, separator, path = record.partition(" ")
            if not separator or tag != "H":
                raise DiagnosticError("source_binding_invalid")
            observed_paths.append(path)
        if observed_paths != list(index):
            raise DiagnosticError("source_binding_invalid")
    gitlinks = dict(expected_gitlinks or {})
    for path, (mode, object_id) in index.items():
        if mode == "160000":
            if gitlinks.get(path) != object_id:
                raise DiagnosticError("source_binding_invalid")
            continue
        if mode not in {"100644", "100755"}:
            raise DiagnosticError("source_binding_invalid")
        if _source_blob_oid(repository_fd, path, mode) != object_id:
            raise DiagnosticError("source_binding_invalid")
    if set(gitlinks) != {path for path, (mode, _object_id) in index.items() if mode == "160000"}:
        raise DiagnosticError("source_binding_invalid")
    repeated = _source_git(
        ["-C", root, "ls-files", "--stage", "-z", *suffix],
        pass_fds=inherited,
    )
    if repeated.returncode != 0 or repeated.stderr or repeated.stdout != stage_result.stdout:
        raise DiagnosticError("source_binding_invalid")
    return index


def attest_imported_source(source_fd: int) -> dict[str, tuple[str, str]]:
    dependency_fds: list[int] = []
    tracked: dict[str, tuple[str, str]] = {}
    try:
        root_index = _attest_git_repository(
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
        tracked.update((path, record) for path, record in root_index.items() if record[0] != "160000")
        for relative, revision in (
            ("deps/verifiers", VERIFIERS_REVISION),
            ("deps/renderers", RENDERERS_REVISION),
            ("deps/pydantic-config", PYDANTIC_CONFIG_REVISION),
        ):
            dependency_fd = _open_source_directory_at(source_fd, relative)
            dependency_fds.append(dependency_fd)
            dependency_index = _attest_git_repository(dependency_fd, expected_revision=revision)
            for path, record in dependency_index.items():
                if record[0] == "160000" or f"{relative}/{path}" in tracked:
                    raise DiagnosticError("source_binding_invalid")
                tracked[f"{relative}/{path}"] = record
        for root_fd in (source_fd, *dependency_fds):
            root = f"/proc/self/fd/{root_fd}"
            status_result = _source_git(
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
                status_result.returncode != 0
                or status_result.stderr
                or status_result.stdout
                or ignored.returncode != 0
                or ignored.stderr
                or ignored.stdout
            ):
                raise DiagnosticError("source_binding_invalid")
    finally:
        for dependency_fd in dependency_fds:
            os.close(dependency_fd)
    return dict(sorted(tracked.items()))


def _read_attested_source_blob(
    source_fd: int,
    relative: str,
    git_mode: str,
    expected_oid: str,
) -> bytes:
    components = relative.split("/")
    if (
        not components
        or any(component in {"", ".", ".."} for component in components)
        or git_mode not in {"100644", "100755"}
        or re.fullmatch(r"[0-9a-f]{40}", expected_oid) is None
    ):
        raise DiagnosticError("source_binding_invalid")
    parent_fd = os.dup(source_fd)
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
                raise DiagnosticError("source_binding_invalid")
        file_fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as error:
        raise DiagnosticError("source_binding_invalid") from error
    finally:
        os.close(parent_fd)
    try:
        before = os.fstat(file_fd)
        executable = bool(before.st_mode & 0o111)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or executable != (git_mode == "100755")
        ):
            raise DiagnosticError("source_binding_invalid")
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
    digest = hashlib.sha1(f"blob {len(raw)}\0".encode(), usedforsecurity=False)
    digest.update(raw)
    if (
        any(getattr(before, field) != getattr(after, field) for field in fields)
        or len(raw) != before.st_size
        or digest.hexdigest() != expected_oid
    ):
        raise DiagnosticError("source_binding_invalid")
    return bytes(raw)


def _write_snapshot_file(path: Path, raw: bytes, mode: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _seal_tree(path: Path) -> None:
    directories: list[Path] = []
    for root, names, files in os.walk(path, topdown=True, followlinks=False):
        root_path = Path(root)
        directories.append(root_path)
        for name in (*names, *files):
            entry = root_path / name
            if entry.is_symlink():
                raise DiagnosticError("site_binding_invalid")
        for name in files:
            entry = root_path / name
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise DiagnosticError("site_binding_invalid")
            entry.chmod(0o500 if info.st_mode & 0o111 else 0o400)
    for directory in reversed(directories):
        directory.chmod(0o500)


def create_execution_snapshot(
    source_fd: int,
    site_fd: int,
    scratch_root: Path,
    expected_site_inventory: Mapping[str, object],
) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    """Copy authorized inputs once, then execute only from the sealed copies."""
    source_records = attest_imported_source(source_fd)
    if directory_manifest(site_fd, expected_owner_uid=os.getuid()) != expected_site_inventory:
        raise DiagnosticError("site_binding_invalid")
    snapshot_root = scratch_root / "sealed-inputs"
    source_snapshot = snapshot_root / "source"
    site_snapshot = snapshot_root / "site"
    source_snapshot.mkdir(mode=0o700, parents=True)
    for relative, (git_mode, object_id) in source_records.items():
        raw = _read_attested_source_blob(source_fd, relative, git_mode, object_id)
        _write_snapshot_file(
            source_snapshot / relative,
            raw,
            0o500 if git_mode == "100755" else 0o400,
        )
    shutil.copytree(
        descriptor_path(site_fd),
        site_snapshot,
        copy_function=shutil.copy2,
    )
    copied_site_fd = os.open(site_snapshot, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        copied_site_inventory = directory_manifest(copied_site_fd, expected_owner_uid=os.getuid())
    finally:
        os.close(copied_site_fd)
    if copied_site_inventory != expected_site_inventory:
        raise DiagnosticError("site_binding_invalid")
    if attest_imported_source(source_fd) != source_records:
        raise DiagnosticError("source_binding_invalid")
    if directory_manifest(site_fd, expected_owner_uid=os.getuid()) != expected_site_inventory:
        raise DiagnosticError("site_binding_invalid")
    _seal_tree(source_snapshot)
    _seal_tree(site_snapshot)
    source_snapshot_fd = os.open(source_snapshot, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    site_snapshot_fd = os.open(site_snapshot, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        source_inventory = directory_manifest(source_snapshot_fd, expected_owner_uid=os.getuid())
        site_inventory = directory_manifest(site_snapshot_fd, expected_owner_uid=os.getuid())
    finally:
        os.close(source_snapshot_fd)
        os.close(site_snapshot_fd)
    return source_snapshot, site_snapshot, source_inventory, site_inventory


def _directory_entry_identity(parent_fd: int, name: str) -> dict[str, int]:
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise DiagnosticError("cleanup_failed")
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "owner_uid": info.st_uid,
    }


def _open_cleanup_watch(parent_fd: int) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    descriptor = int(libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC))
    if descriptor < 0:
        raise DiagnosticError("cleanup_failed")
    try:
        watch = int(
            libc.inotify_add_watch(
                ctypes.c_int(descriptor),
                ctypes.c_char_p(os.fsencode(descriptor_path(parent_fd))),
                ctypes.c_uint32(_INOTIFY_CLEANUP_MASK),
            )
        )
        if watch < 0:
            raise DiagnosticError("cleanup_failed")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_cleanup_events(descriptor: int) -> list[tuple[int, int, bytes]]:
    events: list[tuple[int, int, bytes]] = []
    while True:
        try:
            raw = os.read(descriptor, 1 << 20)
        except BlockingIOError:
            break
        if not raw:
            raise DiagnosticError("cleanup_failed")
        offset = 0
        while offset < len(raw):
            if len(raw) - offset < _INOTIFY_EVENT.size:
                raise DiagnosticError("cleanup_failed")
            _watch, mask, cookie, name_length = _INOTIFY_EVENT.unpack_from(raw, offset)
            offset += _INOTIFY_EVENT.size
            if name_length > len(raw) - offset:
                raise DiagnosticError("cleanup_failed")
            name = raw[offset : offset + name_length].split(b"\0", 1)[0]
            offset += name_length
            events.append((mask & ~_IN_ISDIR, cookie, name))
    return events


def _expected_detach_events(events: Sequence[tuple[int, int, bytes]], source: str, target: str) -> bool:
    return (
        len(events) == 2
        and events[0][0] == _IN_MOVED_FROM
        and events[0][1] != 0
        and events[0][2] == os.fsencode(source)
        and events[1] == (_IN_MOVED_TO, events[0][1], os.fsencode(target))
    )


def _rename_noreplace(source_parent_fd: int, source: str, target_parent_fd: int, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = libc.renameat2
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if (
        renameat2(
            source_parent_fd,
            os.fsencode(source),
            target_parent_fd,
            os.fsencode(target),
            1,  # RENAME_NOREPLACE
        )
        != 0
    ):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), source, target)


def _regular_entry_identity(parent_fd: int, name: str) -> dict[str, int]:
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise DiagnosticError("cleanup_failed")
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "nlink": info.st_nlink,
        "owner_uid": info.st_uid,
        "size": info.st_size,
    }


def _restore_detached_entry(parent_fd: int, quarantine_name: str, original_name: str) -> None:
    try:
        _rename_noreplace(parent_fd, quarantine_name, parent_fd, original_name)
        os.fsync(parent_fd)
    except OSError:
        pass


def _detach_entry_verified(
    parent_fd: int,
    name: str,
    expected_identity: Mapping[str, object],
    *,
    directory: bool,
) -> str | None:
    watch_fd = -1
    quarantine_name: str | None = None
    identity = _directory_entry_identity if directory else _regular_entry_identity
    try:
        watch_fd = _open_cleanup_watch(parent_fd)
        if _read_cleanup_events(watch_fd) or identity(parent_fd, name) != expected_identity:
            return None
        for _attempt in range(8):
            candidate = f".vmvm-cleanup-{os.getpid()}-{os.getrandom(32).hex()}"
            try:
                _rename_noreplace(parent_fd, name, parent_fd, candidate)
            except FileExistsError:
                continue
            quarantine_name = candidate
            break
        if quarantine_name is None:
            return None
        os.fsync(parent_fd)
        if (
            not _expected_detach_events(_read_cleanup_events(watch_fd), name, quarantine_name)
            or identity(parent_fd, quarantine_name) != expected_identity
        ):
            _restore_detached_entry(parent_fd, quarantine_name, name)
            return None
        return quarantine_name
    except (DiagnosticError, FileNotFoundError, OSError):
        if quarantine_name is not None:
            _restore_detached_entry(parent_fd, quarantine_name, name)
        return None
    finally:
        if watch_fd >= 0:
            os.close(watch_fd)


def _delete_detached_entry_verified(
    parent_fd: int,
    name: str,
    bound_fd: int,
    expected_identity: Mapping[str, object],
    *,
    directory: bool,
) -> bool:
    watch_fd = -1
    identity = _directory_entry_identity if directory else _regular_entry_identity
    try:
        watch_fd = _open_cleanup_watch(parent_fd)
        if _read_cleanup_events(watch_fd) or identity(parent_fd, name) != expected_identity:
            return False
        if directory:
            os.rmdir(name, dir_fd=parent_fd)
        else:
            os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        removed = os.fstat(bound_fd)
        return (
            removed.st_dev == expected_identity.get("device")
            and removed.st_ino == expected_identity.get("inode")
            and removed.st_nlink == 0
            and _read_cleanup_events(watch_fd) == [(_IN_DELETE, 0, os.fsencode(name))]
        )
    except (DiagnosticError, FileNotFoundError, OSError):
        return False
    finally:
        if watch_fd >= 0:
            os.close(watch_fd)


def _remove_bound_tree_verified(
    parent_fd: int,
    name: str,
    root_fd: int,
    expected_identity: Mapping[str, object],
) -> bool:
    """Atomically detach, then delete only the still-bound created tree."""
    if not name or "/" in name or name in {".", ".."}:
        return False

    def same_object(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
        return all(left.get(field) == right.get(field) for field in ("device", "inode", "owner_uid"))

    def remove_contents(directory_fd: int) -> None:
        if stat.S_IMODE(os.fstat(directory_fd).st_mode) != 0o700:
            os.fchmod(directory_fd, 0o700)
        for child_name in sorted(os.listdir(directory_fd)):
            info = os.stat(child_name, dir_fd=directory_fd, follow_symlinks=False)
            if info.st_uid != os.getuid():
                raise DiagnosticError("cleanup_failed")
            if stat.S_ISDIR(info.st_mode):
                child_fd = os.open(
                    child_name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    child_identity = _directory_entry_identity(directory_fd, child_name)
                    if not same_object(descriptor_identity(child_fd), child_identity):
                        raise DiagnosticError("cleanup_failed")
                    remove_contents(child_fd)
                    child_identity = descriptor_identity(child_fd)
                    quarantine = _detach_entry_verified(
                        directory_fd,
                        child_name,
                        child_identity,
                        directory=True,
                    )
                    if quarantine is None:
                        raise DiagnosticError("cleanup_failed")
                    if not _delete_detached_entry_verified(
                        directory_fd,
                        quarantine,
                        child_fd,
                        child_identity,
                        directory=True,
                    ):
                        _restore_detached_entry(directory_fd, quarantine, child_name)
                        raise DiagnosticError("cleanup_failed")
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(info.st_mode):
                file_fd = os.open(child_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
                try:
                    before = os.fstat(file_fd)
                    if (
                        before.st_dev != info.st_dev
                        or before.st_ino != info.st_ino
                        or before.st_uid != os.getuid()
                        or before.st_nlink != 1
                    ):
                        raise DiagnosticError("cleanup_failed")
                    file_identity = {
                        "device": before.st_dev,
                        "inode": before.st_ino,
                        "mode": stat.S_IMODE(before.st_mode),
                        "nlink": before.st_nlink,
                        "owner_uid": before.st_uid,
                        "size": before.st_size,
                    }
                    quarantine = _detach_entry_verified(
                        directory_fd,
                        child_name,
                        file_identity,
                        directory=False,
                    )
                    if quarantine is None:
                        raise DiagnosticError("cleanup_failed")
                    if not _delete_detached_entry_verified(
                        directory_fd,
                        quarantine,
                        file_fd,
                        file_identity,
                        directory=False,
                    ):
                        _restore_detached_entry(directory_fd, quarantine, child_name)
                        raise DiagnosticError("cleanup_failed")
                finally:
                    os.close(file_fd)
            else:
                raise DiagnosticError("cleanup_failed")
        os.fsync(directory_fd)

    quarantine_name: str | None = None
    cleanup_watch_fd = -1

    def restore_quarantine() -> None:
        if quarantine_name is None:
            return
        try:
            _rename_noreplace(parent_fd, quarantine_name, parent_fd, name)
            os.fsync(parent_fd)
        except OSError:
            pass

    try:
        cleanup_watch_fd = _open_cleanup_watch(parent_fd)
        if _read_cleanup_events(cleanup_watch_fd):
            raise DiagnosticError("cleanup_failed")
        if (
            descriptor_identity(root_fd) != expected_identity
            or expected_identity.get("mode") != 0o700
            or expected_identity.get("owner_uid") != os.getuid()
            or _directory_entry_identity(parent_fd, name) != expected_identity
        ):
            return False
        for _attempt in range(8):
            candidate = f".vmvm-cleanup-{os.getpid()}-{os.getrandom(32).hex()}"
            try:
                _rename_noreplace(parent_fd, name, parent_fd, candidate)
            except FileExistsError:
                continue
            quarantine_name = candidate
            break
        if quarantine_name is None:
            return False
        os.fsync(parent_fd)
        if not _expected_detach_events(
            _read_cleanup_events(cleanup_watch_fd),
            name,
            quarantine_name,
        ):
            raise DiagnosticError("cleanup_failed")
        moved_identity = _directory_entry_identity(parent_fd, quarantine_name)
        if moved_identity != expected_identity:
            try:
                _rename_noreplace(parent_fd, quarantine_name, parent_fd, name)
                os.fsync(parent_fd)
            except OSError:
                pass
            return False
        remove_contents(root_fd)
        if _directory_entry_identity(parent_fd, quarantine_name) != expected_identity:
            return False
        if _read_cleanup_events(cleanup_watch_fd):
            raise DiagnosticError("cleanup_failed")
        os.rmdir(quarantine_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        removed_root = os.fstat(root_fd)
        if (
            removed_root.st_dev != expected_identity.get("device")
            or removed_root.st_ino != expected_identity.get("inode")
            or removed_root.st_nlink != 0
            or _read_cleanup_events(cleanup_watch_fd) != [(_IN_DELETE, 0, os.fsencode(quarantine_name))]
        ):
            raise DiagnosticError("cleanup_failed")
        try:
            os.stat(quarantine_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return not _read_cleanup_events(cleanup_watch_fd)
        return False
    except (DiagnosticError, FileNotFoundError, OSError):
        restore_quarantine()
        return False
    finally:
        if cleanup_watch_fd >= 0:
            os.close(cleanup_watch_fd)


def _exception_chain(error: BaseException) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(parts) < 8:
        seen.add(id(current))
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


def classify_failure(error: BaseException) -> str:
    text = _exception_chain(error)
    lowered = text.lower()
    if "vmvm provisioning failed: [vacli] connection lost (rc=255, truncated reply)" in lowered:
        return "runtime_initial_workdir_rc255"
    if "fifo shell wiring probe failed" in lowered:
        return "backend_fifo_wiring"
    if "vacli died before tunnel was ready" in lowered or "tunnel mapping" in lowered:
        return "backend_tunnel"
    if "vacli" in lowered and ("failed to start" in lowered or "lease" in lowered):
        return "backend_lease"
    if "sshd not ready" in lowered:
        return "backend_sshd"
    if "podman pull failed" in lowered or "podman run failed" in lowered:
        return "backend_container"
    if "provisioning cancel" in lowered or "cancelled" in lowered:
        return "backend_cancelled"
    if "direct client" in lowered:
        return "direct_client_failed"
    if "thread" in lowered:
        return "thread_failed"
    if "vmvm provisioning failed" in lowered:
        return "runtime_other"
    return "unclassified"


class LeaseAudit:
    def __init__(self, journal_fd: int | None = None) -> None:
        self.phase_counts: Counter[str] = Counter()
        self.lease_attempts = 0
        self.transport_recovery_attempts = 0
        self.last_phase = "worker_started"
        self._leases: dict[int, dict[str, object]] = {}
        self._journal_fd = journal_fd
        self._journal_lock = threading.Lock()
        self._journal_sequence = 0
        self._operation_sequence = 0
        self._journal_valid = True
        if journal_fd is not None:
            info = os.fstat(journal_fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or info.st_size != 0
            ):
                raise DiagnosticError("child_invalid")
            self._journal_event("audit_started")

    def _journal_event(self, event: str, **values: object) -> None:
        if self._journal_fd is None:
            return
        with self._journal_lock:
            payload = (
                canonical_json(
                    {
                        "artifact_type": "vmvm_renewer_journal_event_v2",
                        "event": event,
                        "sequence": self._journal_sequence,
                        **values,
                    }
                )
                + b"\n"
            )
            if len(payload) > 4096:
                self._journal_valid = False
                raise DiagnosticError("cleanup_failed")
            offset = 0
            try:
                while offset < len(payload):
                    offset += os.write(self._journal_fd, payload[offset:])
                os.fsync(self._journal_fd)
            except OSError as error:
                self._journal_valid = False
                raise DiagnosticError("cleanup_failed") from error
            self._journal_sequence += 1

    def _begin_process_operation(self, lease: object, operation: str) -> int:
        with self._journal_lock:
            operation_id = self._operation_sequence
            self._operation_sequence += 1
        self._journal_event(
            "operation_started",
            lease_id=id(lease),
            operation=operation,
            operation_id=operation_id,
        )
        return operation_id

    def _finish_process_operation(self, lease: object, operation: str, operation_id: int) -> None:
        process = getattr(lease, "proc", None)
        if process is None:
            self._journal_event(
                "operation_finished",
                lease_id=id(lease),
                operation=operation,
                operation_id=operation_id,
                outcome="no_process",
            )
            return
        pid = getattr(process, "pid", None)
        if type(pid) is not int or pid <= 1:
            self._journal_valid = False
            raise DiagnosticError("cleanup_failed")
        running = process.poll() is None
        start_ticks: int | None = None
        if running:
            try:
                process_group = os.getpgid(pid)
                start_ticks = _process_start_ticks(pid)
            except (OSError, ValueError) as error:
                self._journal_valid = False
                raise DiagnosticError("cleanup_failed") from error
            if process_group != pid or process_group == os.getpgrp():
                self._journal_valid = False
                raise DiagnosticError("cleanup_failed")
        else:
            process_group = pid
        record = self._leases.setdefault(
            id(lease),
            {
                "cleanup_at": None,
                "lease": lease,
                "process": None,
                "process_group": None,
                "processes": [],
                "session_identity_sha256": None,
            },
        )
        processes = record.setdefault("processes", [])
        assert isinstance(processes, list)
        identity = {
            "pid": pid,
            "process_group": process_group,
            "process": process,
            "start_ticks": start_ticks,
        }
        if not any(
            isinstance(item, dict) and item.get("pid") == pid and item.get("start_ticks") == start_ticks
            for item in processes
        ):
            processes.append(identity)
        record.update({"process": process, "process_group": process_group})
        self._journal_event(
            "renewer_observed",
            lease_id=id(lease),
            operation=operation,
            operation_id=operation_id,
            pid=pid,
            process_group=process_group,
            running=running,
            start_ticks=start_ticks,
        )
        self._journal_event(
            "operation_finished",
            lease_id=id(lease),
            operation=operation,
            operation_id=operation_id,
            outcome="process_observed",
        )

    def phase(self, name: str) -> None:
        if name not in PHASES:
            raise DiagnosticError("stage_result_invalid")
        self.phase_counts[name] += 1
        self.last_phase = name

    def tracking_lease_type(self, lease_type: type[Any]) -> type[Any]:
        audit = self

        class TrackedLease(lease_type):
            def start(self) -> None:
                audit.lease_attempts += 1
                audit.phase("lease_start")
                if audit.lease_attempts > LEASE_ATTEMPT_LIMIT:
                    raise DiagnosticError("lease_budget_exceeded")
                audit._leases[id(self)] = {
                    "cleanup_at": None,
                    "lease": self,
                    "process": None,
                    "process_group": None,
                    "processes": [],
                    "session_identity_sha256": None,
                }
                operation_id = audit._begin_process_operation(self, "start")
                try:
                    super().start()
                finally:
                    audit._finish_process_operation(self, "start", operation_id)

            def restart_tunnel(self) -> int | None:
                operation_id = audit._begin_process_operation(self, "restart")
                try:
                    return super().restart_tunnel()
                finally:
                    audit._finish_process_operation(self, "restart", operation_id)

            def wait_for_tunnel(self) -> int:
                port = super().wait_for_tunnel()
                audit.phase("tunnel_ready")
                record = audit._leases.get(id(self))
                if record is not None:
                    record["session_identity_sha256"] = getattr(self, "session_identity_sha256", None)
                return port

            def cleanup(self) -> None:
                try:
                    super().cleanup()
                finally:
                    record = audit._leases.setdefault(
                        id(self),
                        {
                            "lease": self,
                            "process": getattr(self, "proc", None),
                            "process_group": None,
                            "processes": [],
                            "session_identity_sha256": getattr(self, "session_identity_sha256", None),
                        },
                    )
                    if record.get("cleanup_at") is None:
                        audit.phase("cleanup_called")
                    record["process"] = getattr(self, "proc", None)
                    record["cleanup_at"] = time.monotonic()

        TrackedLease.__name__ = f"Tracked{lease_type.__name__}"
        return TrackedLease

    def tracking_backend_type(self, backend_type: type[Any]) -> type[Any]:
        audit = self

        class TrackedBackend(backend_type):
            def restart_session(self) -> bool:
                audit.transport_recovery_attempts += 1
                if audit.transport_recovery_attempts > RECOVERY_ATTEMPTS:
                    raise DiagnosticError("stage_result_invalid")
                return super().restart_session()

        TrackedBackend.__name__ = f"Tracked{backend_type.__name__}"
        return TrackedBackend

    def verify_releases(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> bool:
        records = list(self._leases.values())
        if not self._journal_valid or self.lease_attempts != len(records):
            return False
        if not records:
            self.phase("release_verified")
            self._journal_event("audit_complete", renewer_processes=0)
            return True
        cleanup_times = [record.get("cleanup_at") for record in records]
        if any(not isinstance(value, float) for value in cleanup_times):
            return False
        deadline = max(float(value) for value in cleanup_times) + LEASE_TTL_SECONDS + RELEASE_GRACE_SECONDS
        remaining = deadline - monotonic()
        if remaining > 0:
            sleeper(remaining)
        for record in records:
            processes = record.get("processes", [])
            if not isinstance(processes, list):
                return False
            for process_record in processes:
                if not isinstance(process_record, dict):
                    return False
                process = process_record.get("process")
                process_group = process_record.get("process_group")
                pid = process_record.get("pid")
                start_ticks = process_record.get("start_ticks")
                if process is not None and process.poll() is None:
                    return False
                if (
                    type(pid) is not int
                    or type(process_group) is not int
                    or not _process_identity_absent(pid, start_ticks)
                    or not _process_group_absent(process_group)
                ):
                    return False
        self.phase("release_verified")
        self._journal_event("audit_complete", renewer_processes=self.renewer_process_count)
        return True

    @property
    def renewer_process_count(self) -> int:
        identities: set[tuple[int, int | None]] = set()
        for record in self._leases.values():
            processes = record.get("processes", [])
            if isinstance(processes, list):
                identities.update(
                    (int(item["pid"]), item.get("start_ticks"))
                    for item in processes
                    if isinstance(item, dict) and type(item.get("pid")) is int
                )
        return len(identities)

    def constructor_rollback_recorded(self) -> bool:
        records = list(self._leases.values())
        return (
            self._journal_valid
            and bool(records)
            and self.lease_attempts == len(records)
            and all(isinstance(record.get("cleanup_at"), float) for record in records)
        )

    def metadata(self, release_verified: bool) -> dict[str, object]:
        return {
            "last_phase": self.last_phase,
            "lease_attempt_limit": LEASE_ATTEMPT_LIMIT,
            "lease_attempts": self.lease_attempts,
            "phase_counts": dict(sorted(self.phase_counts.items())),
            "release_grace_seconds": RELEASE_GRACE_SECONDS,
            "release_method": "renewer_absent_for_lease_ttl",
            "release_verified": release_verified,
            "renewer_processes": self.renewer_process_count,
            "transport_recovery_attempt_limit": RECOVERY_ATTEMPTS,
            "transport_recovery_attempts": self.transport_recovery_attempts,
        }


def _call_in_fresh_thread(function: Callable[[], Any]) -> Any:
    outcome: list[tuple[bool, object]] = []

    def invoke() -> None:
        try:
            outcome.append((True, function()))
        except BaseException as error:
            outcome.append((False, error))

    thread = threading.Thread(target=invoke, name="vmvm-diagnostic-worker", daemon=False)
    thread.start()
    thread.join()
    if len(outcome) != 1:
        raise DiagnosticError("thread_failed")
    succeeded, value = outcome[0]
    if succeeded:
        return value
    assert isinstance(value, BaseException)
    raise value


def _install_source_paths(source_root: Path, site_root: Path) -> None:
    paths = (
        source_root / "deps/verifiers",
        source_root / "deps/renderers",
        source_root / "deps/pydantic-config/src",
        source_root / "environments/vmvm_tb_v2",
        site_root,
    )
    for path in reversed(paths):
        sys.path.insert(0, str(path))


def _backend_dependencies(source_root: Path, site_root: Path) -> tuple[Any, type[Any], type[Any], Callable[..., Any]]:
    _install_source_paths(source_root, site_root)
    from vmvm_tb_v2._vacli import backend as backend_module

    return (
        backend_module,
        backend_module.VacliLease,
        backend_module.VacliVMVMBackend,
        (backend_module.VacliVMVMConfig, backend_module._wait_for_sshd),
    )


def _backend_config(config_type: type[Any], scratch: Path) -> Any:
    del scratch
    return config_type(
        image_url=IMAGE,
        work_dir=WORKDIR,
        session_timeout=SESSION_TIMEOUT_SECONDS,
        tenant_id=TENANT_ID,
        lease_ttl=LEASE_TTL,
        tunnel_ready_timeout=120.0,
        sshd_ready_timeout=180.0,
        max_session_buffer_size=67_108_864,
    )


def _result_payload(
    *,
    mode: str,
    stage: str,
    state: Literal["passed", "failed"],
    failure: str | None,
    cleanup_complete: bool,
    elapsed_seconds: float,
    pair_index: int = 0,
    order_position: int = 0,
    phase_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if (
        mode not in MODES
        or stage not in STAGES
        or pair_index not in range(REPETITIONS)
        or order_position not in (0, 1)
        or MODE_ORDERS[pair_index][order_position] != mode
    ):
        raise DiagnosticError("stage_result_invalid")
    if state == "passed" and failure is not None:
        raise DiagnosticError("stage_result_invalid")
    if state == "failed" and failure not in SAFE_FAILURES:
        raise DiagnosticError("stage_result_invalid")
    return {
        "artifact_type": "vmvm_task_free_stage_result_v2",
        "cleanup_complete": cleanup_complete,
        "elapsed_milliseconds": max(0, round(elapsed_seconds * 1000)),
        "failure_class": failure,
        "order_position": order_position,
        "pair_index": pair_index,
        "phase_metadata": dict(phase_metadata or _empty_phase_metadata(cleanup_complete)),
        "stage": stage,
        "state": state,
        "x2p_mode": mode,
    }


def _empty_phase_metadata(release_verified: bool) -> dict[str, object]:
    return {
        "last_phase": "release_verified" if release_verified else "worker_started",
        "lease_attempt_limit": LEASE_ATTEMPT_LIMIT,
        "lease_attempts": 0,
        "phase_counts": {},
        "release_grace_seconds": RELEASE_GRACE_SECONDS,
        "release_method": "renewer_absent_for_lease_ttl",
        "release_verified": release_verified,
        "renewer_processes": 0,
        "transport_recovery_attempt_limit": RECOVERY_ATTEMPTS,
        "transport_recovery_attempts": 0,
    }


def execute_direct_client(
    *,
    lease_type: type[Any],
    wait_for_sshd: Callable[..., Any],
    scratch: Path,
    audit: LeaseAudit | None = None,
) -> tuple[bool, str | None, bool]:
    cleanup_complete = False
    passed = False
    failure: str | None = None
    attempts = LEASE_ATTEMPT_LIMIT if audit is not None else 1
    for attempt in range(attempts):
        lease = lease_type(
            TENANT_ID,
            scratch / f"lease-{attempt}.log",
            lease_ttl=LEASE_TTL,
            tunnel_ready_timeout=120.0,
        )
        try:
            lease.start()
            port = lease.wait_for_tunnel()
            wait_for_sshd(port, timeout=180.0)
            if audit is not None:
                audit.phase("backend_ready")
            passed = True
            failure = None
        except BaseException as error:
            classified = classify_failure(error)
            failure = classified if classified != "unclassified" else "direct_client_failed"
        finally:
            try:
                lease.cleanup()
                cleanup_complete = True
            except BaseException:
                cleanup_complete = False
        if passed or not cleanup_complete:
            break
    if not cleanup_complete:
        return False, "cleanup_failed", False
    if not passed and audit is not None and audit.lease_attempts != LEASE_ATTEMPT_LIMIT:
        return False, "lease_budget_exceeded", True
    return passed, failure, True


def execute_backend_variant(
    *,
    backend_type: type[Any],
    config: Any,
    cross_thread: bool,
    recovery: bool,
    audit: LeaseAudit | None = None,
) -> tuple[bool, str | None, bool]:
    backend: Any | None = None
    cleanup_complete = False
    passed = False
    failure: str | None = None
    try:
        constructor = lambda: backend_type(config)
        backend = _call_in_fresh_thread(constructor) if cross_thread else constructor()
        if audit is not None:
            audit.phase("backend_ready")

        def command() -> Any:
            if audit is not None:
                audit.phase("command_started")
            if recovery:
                return backend.run_bash_with_recovery(
                    f"mkdir -p {WORKDIR}",
                    SESSION_TIMEOUT_SECONDS,
                    RECOVERY_ATTEMPTS,
                )
            return backend.run_bash(f"mkdir -p {WORKDIR}", SESSION_TIMEOUT_SECONDS)

        result = _call_in_fresh_thread(command) if cross_thread else command()
        if (
            not isinstance(result, Mapping)
            or result.get("status") != "success"
            or result.get("error_type") != "none"
            or result.get("exit_code") != 0
        ):
            synthetic = RuntimeError(
                "VMVM provisioning failed: [vacli] connection lost (rc=255, truncated reply)"
                if isinstance(result, Mapping)
                and result.get("error_type") == "broken_pipe"
                and result.get("exit_code") == -1
                else "runtime command result invalid"
            )
            failure = classify_failure(synthetic)
        else:
            passed = True
            if audit is not None:
                audit.phase("command_succeeded")
    except BaseException as error:
        failure = classify_failure(error)
        if backend is None and audit is not None:
            cleanup_complete = audit.constructor_rollback_recorded()
    finally:
        if backend is not None:
            try:
                backend.destroy()
                cleanup_complete = True
            except BaseException:
                cleanup_complete = False
    if not cleanup_complete:
        return False, "cleanup_failed", False
    return passed, failure, True


async def _runtime_contract(
    source_root: Path, site_root: Path, audit: LeaseAudit | None = None
) -> tuple[bool, str | None, bool]:
    _install_source_paths(source_root, site_root)
    from verifiers.v1.runtimes import VMVMConfig, VMVMRuntime

    runtime = VMVMRuntime(
        VMVMConfig(
            image=IMAGE,
            workdir=WORKDIR,
            session_timeout=SESSION_TIMEOUT_SECONDS,
            tenant_id=TENANT_ID,
            lease_ttl=LEASE_TTL,
            max_session_buffer_size=67_108_864,
        ),
        name="task-free-contract",
    )
    cleanup_complete = False
    passed = False
    failure: str | None = None
    try:
        await runtime.start()
        if audit is not None:
            audit.phase("backend_ready")
            audit.phase("command_started")
        result = await runtime.run(["true"], {})
        if result.exit_code != 0 or result.stdout or result.stderr:
            raise RuntimeError("runtime contract result invalid")
        passed = True
        if audit is not None:
            audit.phase("command_succeeded")
    except BaseException as error:
        failure = classify_failure(error)
    finally:
        try:
            await runtime.stop()
            cleanup_complete = True
        except BaseException:
            cleanup_complete = False
    if not cleanup_complete:
        return False, "cleanup_failed", False
    return passed, failure, True


def execute_worker(
    stage: str,
    mode: str,
    source_root: Path,
    site_root: Path,
    scratch: Path,
    pair_index: int,
    order_position: int,
    renewer_journal_fd: int | None = None,
) -> dict[str, object]:
    if (
        stage not in STAGES
        or pair_index not in range(REPETITIONS)
        or order_position not in (0, 1)
        or MODE_ORDERS[pair_index][order_position] != mode
        or inherited_descriptor(source_root) is None
        or inherited_descriptor(site_root) is None
    ):
        raise DiagnosticError("stage_result_invalid")
    started = time.monotonic()
    cleanup_complete = False
    failure: str | None = None
    passed = False
    audit = LeaseAudit(renewer_journal_fd)
    audit.phase("worker_started")
    backend_module: Any | None = None
    original_lease_type: type[Any] | None = None
    original_backend_type: type[Any] | None = None
    try:
        backend_module, lease_type, backend_type, helpers = _backend_dependencies(source_root, site_root)
        original_lease_type = lease_type
        original_backend_type = backend_type
        tracked_lease_type = audit.tracking_lease_type(lease_type)
        tracked_backend_type = audit.tracking_backend_type(backend_type)
        backend_module.VacliLease = tracked_lease_type
        backend_module.VacliVMVMBackend = tracked_backend_type
        config_type, wait_for_sshd = helpers
        if stage == "direct_client":
            passed, failure, cleanup_complete = execute_direct_client(
                lease_type=tracked_lease_type,
                wait_for_sshd=wait_for_sshd,
                scratch=scratch,
                audit=audit,
            )
        elif stage == "runtime_contract":
            passed, failure, cleanup_complete = asyncio.run(_runtime_contract(source_root, site_root, audit))
        else:
            cross_thread = stage.startswith("cross_thread_")
            recovery = stage.endswith("_recovery")
            passed, failure, cleanup_complete = execute_backend_variant(
                backend_type=tracked_backend_type,
                config=_backend_config(config_type, scratch),
                cross_thread=cross_thread,
                recovery=recovery,
                audit=audit,
            )
    except BaseException as error:
        passed = False
        failure = error.code if isinstance(error, DiagnosticError) else classify_failure(error)
    finally:
        if backend_module is not None:
            if original_lease_type is not None:
                backend_module.VacliLease = original_lease_type
            if original_backend_type is not None:
                backend_module.VacliVMVMBackend = original_backend_type
    release_verified = audit.verify_releases()
    cleanup_complete = cleanup_complete and release_verified
    if not cleanup_complete:
        passed = False
        failure = "cleanup_failed"
    return _result_payload(
        mode=mode,
        stage=stage,
        state="passed" if passed else "failed",
        failure=failure or (None if passed else "unclassified"),
        cleanup_complete=cleanup_complete,
        elapsed_seconds=time.monotonic() - started,
        pair_index=pair_index,
        order_position=order_position,
        phase_metadata=audit.metadata(release_verified),
    )


def _child_environment(mode: str, scratch: Path, renewer_journal_fd: int | None = None) -> dict[str, str]:
    if mode not in MODES:
        raise DiagnosticError("stage_result_invalid")
    allowed = {
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": str(scratch / "pycache"),
        "PYTHONSAFEPATH": "1",
        "TMPDIR": str(scratch),
        "TZ": "UTC",
        "USER": "tianhaowu",
        "VACLI_BIN": "/public/fbpkgs/x86_64/vacli/stable/vacli",
        "VACLI_CONTAINER_PRIVILEGED": "1",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": str(IMAGE_PULL_TIMEOUT_SECONDS),
        "VACLI_LEASE_RETRIES": str(LEASE_ATTEMPT_LIMIT),
        "VACLI_MAX_CONCURRENT_LEASES": "1",
        "VACLI_MAX_PULL_RETRIES": str(IMAGE_PULL_RETRY_LIMIT),
    }
    if renewer_journal_fd is not None:
        allowed["DIAG_RENEWER_JOURNAL_FD"] = str(renewer_journal_fd)
    probe_descriptor = os.environ.get("DIAG_EXEC_PROBE_FD")
    probe_sha256 = os.environ.get("DIAG_PROBE_SHA256")
    if not probe_descriptor or not probe_sha256:
        raise DiagnosticError("child_invalid")
    allowed["DIAG_EXEC_PROBE_FD"] = probe_descriptor
    allowed["DIAG_PROBE_SHA256"] = probe_sha256
    for name in TLS_NAMES:
        value = os.environ.get(name)
        if not value:
            raise DiagnosticError("child_invalid")
        allowed[name] = value
    if mode == "present":
        for name in X2P_NAMES:
            value = os.environ.get(name)
            if not value:
                raise DiagnosticError("child_invalid")
            allowed[name] = value
    return allowed


def _terminate_process_group(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return True
    for sig, timeout in ((signal.SIGTERM, 10.0), (signal.SIGKILL, 10.0)):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, sig)
        try:
            process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            continue
    return process.poll() is not None


def _process_group_absent(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _process_start_ticks(pid: int) -> int:
    raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    closing = raw.rfind(")")
    fields = raw[closing + 2 :].split() if closing >= 0 else []
    if len(fields) < 20:
        raise ValueError("invalid process stat")
    return int(fields[19])


def _process_identity_absent(pid: int, start_ticks: object) -> bool:
    try:
        observed = _process_start_ticks(pid)
    except (FileNotFoundError, ProcessLookupError):
        return True
    except (OSError, UnicodeError, ValueError):
        return False
    return type(start_ticks) is int and observed != start_ticks


def _stable_journal_bytes(descriptor: int) -> bytes:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
        or not 0 < before.st_size <= MAX_RENEWER_JOURNAL_BYTES
    ):
        raise DiagnosticError("cleanup_failed")
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = bytearray()
    while len(raw) <= MAX_RENEWER_JOURNAL_BYTES:
        chunk = os.read(descriptor, min(1 << 20, MAX_RENEWER_JOURNAL_BYTES + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    after = os.fstat(descriptor)
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields) or len(raw) != before.st_size:
        raise DiagnosticError("cleanup_failed")
    return bytes(raw)


def _journal_process_identities(descriptor: int, *, require_complete: bool = False) -> set[tuple[int, int, int | None]]:
    raw = _stable_journal_bytes(descriptor)
    if not raw.endswith(b"\n"):
        raise DiagnosticError("cleanup_failed")
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DiagnosticError("cleanup_failed") from error
        if (
            not isinstance(value, dict)
            or canonical_json(value) != line
            or value.get("artifact_type") != "vmvm_renewer_journal_event_v2"
            or value.get("sequence") != len(events)
        ):
            raise DiagnosticError("cleanup_failed")
        events.append(value)
    if not events or events[0] != {
        "artifact_type": "vmvm_renewer_journal_event_v2",
        "event": "audit_started",
        "sequence": 0,
    }:
        raise DiagnosticError("cleanup_failed")
    operations: dict[int, dict[str, object]] = {}
    identities: set[tuple[int, int, int | None]] = set()
    complete = False
    for event in events[1:]:
        if complete:
            raise DiagnosticError("cleanup_failed")
        kind = event.get("event")
        if kind == "audit_complete":
            if set(event) != {
                "artifact_type",
                "event",
                "renewer_processes",
                "sequence",
            } or event.get("renewer_processes") != len(identities):
                raise DiagnosticError("cleanup_failed")
            complete = True
            continue
        operation_id = event.get("operation_id")
        lease_id = event.get("lease_id")
        operation = event.get("operation")
        if (
            type(operation_id) is not int
            or operation_id < 0
            or type(lease_id) is not int
            or lease_id <= 0
            or operation not in {"start", "restart"}
        ):
            raise DiagnosticError("cleanup_failed")
        if kind == "operation_started":
            if (
                set(event)
                != {
                    "artifact_type",
                    "event",
                    "lease_id",
                    "operation",
                    "operation_id",
                    "sequence",
                }
                or operation_id in operations
            ):
                raise DiagnosticError("cleanup_failed")
            operations[operation_id] = {
                "finished": False,
                "lease_id": lease_id,
                "operation": operation,
                "processes": 0,
            }
            continue
        record = operations.get(operation_id)
        if (
            record is None
            or record["lease_id"] != lease_id
            or record["operation"] != operation
            or record["finished"] is True
        ):
            raise DiagnosticError("cleanup_failed")
        if kind == "renewer_observed":
            if set(event) != {
                "artifact_type",
                "event",
                "lease_id",
                "operation",
                "operation_id",
                "pid",
                "process_group",
                "running",
                "sequence",
                "start_ticks",
            }:
                raise DiagnosticError("cleanup_failed")
            pid = event.get("pid")
            process_group = event.get("process_group")
            start_ticks = event.get("start_ticks")
            running = event.get("running")
            if (
                type(pid) is not int
                or pid <= 1
                or type(process_group) is not int
                or process_group != pid
                or type(running) is not bool
                or (running and (type(start_ticks) is not int or start_ticks < 0))
                or (not running and start_ticks is not None)
                or record["processes"] != 0
            ):
                raise DiagnosticError("cleanup_failed")
            identities.add((pid, process_group, start_ticks))
            record["processes"] = 1
        elif kind == "operation_finished":
            if (
                set(event)
                != {
                    "artifact_type",
                    "event",
                    "lease_id",
                    "operation",
                    "operation_id",
                    "outcome",
                    "sequence",
                }
                or event.get("outcome") not in {"no_process", "process_observed"}
                or (event.get("outcome") == "no_process" and record["processes"] != 0)
                or (event.get("outcome") == "process_observed" and record["processes"] != 1)
            ):
                raise DiagnosticError("cleanup_failed")
            record["finished"] = True
        else:
            raise DiagnosticError("cleanup_failed")
    if any(record["finished"] is not True for record in operations.values()):
        raise DiagnosticError("cleanup_failed")
    if require_complete and not complete:
        raise DiagnosticError("cleanup_failed")
    return identities


def verify_external_renewer_release(
    journal_fd: int,
    child_process_group: int,
    *,
    require_complete: bool = False,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    try:
        identities = _journal_process_identities(journal_fd, require_complete=require_complete)
    except DiagnosticError:
        return False
    if any(process_group == child_process_group for _pid, process_group, _ in identities):
        return False
    quiescence_deadline = monotonic() + LEASE_TTL_SECONDS + RELEASE_GRACE_SECONDS
    while monotonic() < quiescence_deadline:
        if _process_group_absent(child_process_group) and all(
            _process_group_absent(process_group) and _process_identity_absent(pid, start_ticks)
            for pid, process_group, start_ticks in identities
        ):
            break
        sleeper(min(1.0, quiescence_deadline - monotonic()))
    else:
        return False
    deadline = monotonic() + LEASE_TTL_SECONDS + RELEASE_GRACE_SECONDS
    while monotonic() < deadline:
        if not _process_group_absent(child_process_group) or any(
            not _process_group_absent(process_group) or not _process_identity_absent(pid, start_ticks)
            for pid, process_group, start_ticks in identities
        ):
            return False
        sleeper(min(1.0, deadline - monotonic()))
    return _process_group_absent(child_process_group) and all(
        _process_group_absent(process_group) and _process_identity_absent(pid, start_ticks)
        for pid, process_group, start_ticks in identities
    )


def verify_timeout_release(
    process_group: int,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    deadline = monotonic() + LEASE_TTL_SECONDS + RELEASE_GRACE_SECONDS
    while monotonic() < deadline:
        if not _process_group_absent(process_group):
            return False
        sleeper(min(1.0, deadline - monotonic()))
    return _process_group_absent(process_group)


def _create_worker_write_ruleset(stage_fd: int) -> int:
    """Create a Landlock ruleset that permits filesystem mutation only in one cell."""
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(
        _LANDLOCK_CREATE_RULESET,
        ctypes.c_void_p(),
        ctypes.c_size_t(0),
        ctypes.c_uint(_LANDLOCK_CREATE_RULESET_VERSION),
    )
    if abi < 3:
        raise DiagnosticError("child_invalid")
    ruleset_attr = _LandlockRulesetAttr(_LANDLOCK_WRITE_ACCESS)
    ruleset_fd = libc.syscall(
        _LANDLOCK_CREATE_RULESET,
        ctypes.byref(ruleset_attr),
        ctypes.sizeof(ruleset_attr),
        ctypes.c_uint(0),
    )
    if ruleset_fd < 0:
        raise DiagnosticError("child_invalid")
    path_fd = -1
    try:
        path_fd = os.open(".", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=stage_fd)
        path_attr = _LandlockPathBeneathAttr(_LANDLOCK_WRITE_ACCESS, path_fd, 0)
        if (
            libc.syscall(
                _LANDLOCK_ADD_RULE,
                ctypes.c_int(ruleset_fd),
                ctypes.c_int(_LANDLOCK_RULE_PATH_BENEATH),
                ctypes.byref(path_attr),
                ctypes.c_uint(0),
            )
            != 0
        ):
            raise DiagnosticError("child_invalid")
    except BaseException:
        os.close(ruleset_fd)
        raise
    finally:
        if path_fd >= 0:
            os.close(path_fd)
    return int(ruleset_fd)


def _restrict_worker_writes(ruleset_fd: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if (
        libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0
        or libc.syscall(
            _LANDLOCK_RESTRICT_SELF,
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint(0),
        )
        != 0
    ):
        raise OSError(ctypes.get_errno(), "Landlock restriction failed")
    os.close(ruleset_fd)


class SnapshotGuard:
    """Kernel-backed write detection and denial for the sealed input tree."""

    def __init__(self, roots: Sequence[Path]) -> None:
        self._lease_fds: list[int] = []
        self._violated = False
        self._closed = False
        self._previous_sigio = signal.getsignal(signal.SIGIO)
        signal.signal(signal.SIGIO, self._lease_break)
        libc = ctypes.CDLL(None, use_errno=True)
        self._inotify_fd = int(libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC))
        if self._inotify_fd < 0:
            signal.signal(signal.SIGIO, self._previous_sigio)
            raise DiagnosticError("source_binding_invalid")
        try:
            for root in roots:
                for directory, names, files in os.walk(root, topdown=True, followlinks=False):
                    directory_path = Path(directory)
                    if any((directory_path / name).is_symlink() for name in (*names, *files)):
                        raise DiagnosticError("source_binding_invalid")
                    encoded = os.fsencode(directory_path)
                    if (
                        libc.inotify_add_watch(
                            ctypes.c_int(self._inotify_fd),
                            ctypes.c_char_p(encoded),
                            ctypes.c_uint32(_INOTIFY_MUTATION_MASK),
                        )
                        < 0
                    ):
                        raise DiagnosticError("source_binding_invalid")
                    for name in files:
                        file_fd = os.open(
                            directory_path / name,
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        )
                        try:
                            info = os.fstat(file_fd)
                            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                                raise DiagnosticError("source_binding_invalid")
                            fcntl.fcntl(file_fd, fcntl.F_SETOWN, os.getpid())
                            fcntl.fcntl(file_fd, fcntl.F_SETLEASE, fcntl.F_RDLCK)
                        except BaseException:
                            os.close(file_fd)
                            raise
                        self._lease_fds.append(file_fd)
        except BaseException:
            self.close()
            raise

    def _lease_break(self, signum: int, frame: object) -> None:
        del signum, frame
        self._violated = True

    def is_clean(self) -> bool:
        if self._closed or self._violated:
            return False
        while True:
            try:
                raw = os.read(self._inotify_fd, 1 << 20)
            except BlockingIOError:
                break
            except OSError:
                self._violated = True
                break
            if not raw:
                self._violated = True
                break
            self._violated = True
        return not self._violated

    def close(self) -> bool:
        if self._closed:
            return False
        clean = self.is_clean()
        self._closed = True
        for descriptor in self._lease_fds:
            try:
                fcntl.fcntl(descriptor, fcntl.F_SETLEASE, fcntl.F_UNLCK)
                os.close(descriptor)
            except OSError:
                clean = False
        self._lease_fds.clear()
        try:
            os.close(self._inotify_fd)
        except OSError:
            clean = False
        signal.signal(signal.SIGIO, self._previous_sigio)
        return clean


def run_stage_child(
    *,
    script: Path,
    python: Path,
    source_root: Path,
    site_root: Path,
    scratch_root_fd: int,
    snapshot_guard: SnapshotGuard,
    mode: str,
    stage: str,
    pair_index: int,
    order_position: int,
) -> dict[str, object]:
    inherited = tuple(
        inherited_descriptor(path)
        for path in (
            script,
            source_root,
            site_root,
        )
    )
    if any(descriptor is None for descriptor in inherited):
        raise DiagnosticError("child_invalid")
    stage_name = f"pair-{pair_index:02d}-position-{order_position}-{mode}-{stage}"
    os.mkdir(stage_name, mode=0o700, dir_fd=scratch_root_fd)
    stage_fd = os.open(
        stage_name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=scratch_root_fd,
    )
    stage_identity = descriptor_identity(stage_fd)
    stage_scratch = descriptor_path(stage_fd)
    journal_fd = -1
    landlock_fd = -1
    try:
        os.mkdir("pycache", mode=0o500, dir_fd=stage_fd)
        journal_fd = os.open(
            "renewer-journal.jsonl",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_APPEND,
            0o600,
            dir_fd=stage_fd,
        )
        landlock_fd = _create_worker_write_ruleset(stage_fd)
    except BaseException:
        for descriptor in (journal_fd, landlock_fd):
            if descriptor >= 0:
                os.close(descriptor)
        removed = _remove_bound_tree_verified(
            scratch_root_fd,
            stage_name,
            stage_fd,
            stage_identity,
        )
        os.close(stage_fd)
        if not removed:
            raise DiagnosticError("cleanup_failed")
        raise
    command = [
        str(python),
        "-I",
        "-S",
        "-B",
        str(script),
        "--worker",
        "--stage",
        stage,
        "--x2p-mode",
        mode,
        "--pair-index",
        str(pair_index),
        "--order-position",
        str(order_position),
        "--source-root",
        str(source_root),
        "--site-root",
        str(site_root),
        "--scratch",
        str(stage_scratch),
        "--renewer-journal-fd",
        str(journal_fd),
    ]
    process: subprocess.Popen[bytes] | None = None
    release_checked = False
    try:
        if not snapshot_guard.is_clean():
            raise DiagnosticError("source_binding_invalid")
        try:
            process = subprocess.Popen(
                command,
                env=_child_environment(mode, stage_scratch, journal_fd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                pass_fds=tuple(
                    descriptor
                    for descriptor in (
                        *inherited,
                        stage_fd,
                        journal_fd,
                        landlock_fd,
                    )
                    if descriptor is not None
                ),
                preexec_fn=lambda: _restrict_worker_writes(landlock_fd),
            )
        finally:
            os.close(landlock_fd)
            landlock_fd = -1
        deadline = time.monotonic() + STAGE_TIMEOUT_SECONDS
        guard_violation = False
        while True:
            if not snapshot_guard.is_clean():
                guard_violation = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                stdout, stderr = process.communicate(timeout=min(1.0, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if guard_violation:
            terminated = _terminate_process_group(process)
            released = terminated and verify_external_renewer_release(journal_fd, process.pid)
            release_checked = True
            renewer_processes = len(_journal_process_identities(journal_fd)) if released else 0
            return _result_payload(
                mode=mode,
                stage=stage,
                state="failed",
                failure="source_binding_invalid" if released else "cleanup_failed",
                cleanup_complete=released,
                elapsed_seconds=max(0.0, STAGE_TIMEOUT_SECONDS - max(0.0, deadline - time.monotonic())),
                pair_index=pair_index,
                order_position=order_position,
                phase_metadata={
                    **_empty_phase_metadata(released),
                    "last_phase": ("release_verified" if released else "worker_started"),
                    "release_verified": released,
                    "renewer_processes": renewer_processes,
                },
            )
        if process.poll() is None:
            terminated = _terminate_process_group(process)
            released = terminated and verify_external_renewer_release(journal_fd, process.pid)
            release_checked = True
            renewer_processes = len(_journal_process_identities(journal_fd)) if released else 0
            return _result_payload(
                mode=mode,
                stage=stage,
                state="failed",
                failure="child_timeout" if released else "cleanup_failed",
                cleanup_complete=released,
                elapsed_seconds=STAGE_TIMEOUT_SECONDS,
                pair_index=pair_index,
                order_position=order_position,
                phase_metadata={
                    **_empty_phase_metadata(released),
                    "last_phase": ("release_verified" if released else "worker_started"),
                    "release_verified": released,
                    "renewer_processes": renewer_processes,
                },
            )
        if not snapshot_guard.is_clean():
            raise DiagnosticError("source_binding_invalid")
        overflow = len(stdout) > MAX_CHILD_OUTPUT_BYTES or len(stderr) > MAX_CHILD_OUTPUT_BYTES
        try:
            value = json.loads(stdout) if not overflow else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = None
        valid = (
            not overflow
            and not stderr
            and process.returncode == 0
            and isinstance(value, dict)
            and canonical_json(value) + b"\n" == stdout
        )
        released = False
        if valid:
            try:
                assert isinstance(value, dict)
                validate_stage_result(
                    value,
                    expected_mode=mode,
                    expected_stage=stage,
                    expected_pair_index=pair_index,
                    expected_order_position=order_position,
                )
                identities = _journal_process_identities(journal_fd, require_complete=True)
                metadata = value["phase_metadata"]
                assert isinstance(metadata, dict)
                if metadata.get("renewer_processes") != len(identities):
                    raise DiagnosticError("stage_result_invalid")
                released = verify_external_renewer_release(
                    journal_fd,
                    process.pid,
                    require_complete=True,
                )
                release_checked = True
                if not released:
                    raise DiagnosticError("cleanup_failed")
            except DiagnosticError:
                valid = False
        if valid:
            assert isinstance(value, dict)
            return value
        if not release_checked:
            released = verify_external_renewer_release(journal_fd, process.pid)
            release_checked = True
        renewer_processes = len(_journal_process_identities(journal_fd)) if released else 0
        return _result_payload(
            mode=mode,
            stage=stage,
            state="failed",
            failure=(
                "child_output_overflow" if overflow and released else "child_invalid" if released else "cleanup_failed"
            ),
            cleanup_complete=released,
            elapsed_seconds=0,
            pair_index=pair_index,
            order_position=order_position,
            phase_metadata={
                **_empty_phase_metadata(released),
                "last_phase": "release_verified" if released else "worker_started",
                "release_verified": released,
                "renewer_processes": renewer_processes,
            },
        )
    except BaseException as error:
        if process is not None and not release_checked:
            terminated = process.poll() is not None or _terminate_process_group(process)
            try:
                released = terminated and verify_external_renewer_release(journal_fd, process.pid)
            except BaseException:
                released = False
            if not released:
                raise DiagnosticError("cleanup_failed") from error
        raise
    finally:
        try:
            os.close(journal_fd)
            journal_closed = True
        except OSError:
            journal_closed = False
        removed = _remove_bound_tree_verified(
            scratch_root_fd,
            stage_name,
            stage_fd,
            stage_identity,
        )
        os.close(stage_fd)
        if not removed or not journal_closed:
            raise DiagnosticError("cleanup_failed")


def validate_stage_result(
    value: Mapping[str, object],
    *,
    expected_mode: str,
    expected_stage: str,
    expected_pair_index: int,
    expected_order_position: int,
) -> None:
    if expected_pair_index not in range(REPETITIONS) or expected_order_position not in (
        0,
        1,
    ):
        raise DiagnosticError("stage_result_invalid")
    if set(value) != {
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
        raise DiagnosticError("stage_result_invalid")
    if (
        value.get("artifact_type") != "vmvm_task_free_stage_result_v2"
        or value.get("stage") != expected_stage
        or value.get("x2p_mode") != expected_mode
        or value.get("pair_index") != expected_pair_index
        or value.get("order_position") != expected_order_position
        or MODE_ORDERS[expected_pair_index][expected_order_position] != expected_mode
        or type(value.get("cleanup_complete")) is not bool
        or type(value.get("elapsed_milliseconds")) is not int
        or int(value["elapsed_milliseconds"]) < 0
        or value.get("state") not in {"passed", "failed"}
    ):
        raise DiagnosticError("stage_result_invalid")
    failure = value.get("failure_class")
    if value["state"] == "passed":
        if failure is not None or value["cleanup_complete"] is not True:
            raise DiagnosticError("stage_result_invalid")
    elif failure not in SAFE_FAILURES:
        raise DiagnosticError("stage_result_invalid")
    metadata = value.get("phase_metadata")
    if not isinstance(metadata, dict) or set(metadata) != {
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
        raise DiagnosticError("stage_result_invalid")
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
        or type(metadata.get("release_verified")) is not bool
        or metadata.get("release_verified") is not value.get("cleanup_complete")
        or type(metadata.get("renewer_processes")) is not int
        or int(metadata["renewer_processes"]) < 0
        or metadata.get("transport_recovery_attempt_limit") != RECOVERY_ATTEMPTS
        or type(metadata.get("transport_recovery_attempts")) is not int
        or not 0 <= int(metadata["transport_recovery_attempts"]) <= RECOVERY_ATTEMPTS
    ):
        raise DiagnosticError("stage_result_invalid")
    _validate_phase_causality(
        expected_stage,
        str(value["state"]),
        failure if isinstance(failure, str) else None,
        metadata,
    )


def _validate_phase_causality(
    stage: str,
    state: str,
    failure: str | None,
    metadata: Mapping[str, object],
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
        raise DiagnosticError("stage_result_invalid")
    if state == "passed":
        if lease_attempts < 1 or count("backend_ready") != 1:
            raise DiagnosticError("stage_result_invalid")
        if stage != "direct_client" and (count("command_started") != 1 or count("command_succeeded") != 1):
            raise DiagnosticError("stage_result_invalid")
    elif stage == "direct_client" and count("backend_ready") != 0:
        raise DiagnosticError("stage_result_invalid")
    elif count("command_succeeded") != 0:
        raise DiagnosticError("stage_result_invalid")


def _atomic_write(directory: Path | int, name: str, payload: bytes, mode: int) -> None:
    directory_fd = (
        os.dup(directory)
        if isinstance(directory, int)
        else os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    )
    temporary = f".{name}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)
    try:
        os.rename(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _stable_bytes(
    path: Path,
    *,
    mode: int,
    expected_sha256: str | None = None,
    maximum: int = 2 << 20,
) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise DiagnosticError("source_binding_invalid") from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != mode
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > maximum
        ):
            raise DiagnosticError("source_binding_invalid")
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = os.read(descriptor, min(1 << 20, maximum + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
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
    )
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise DiagnosticError("source_binding_invalid")
    if expected_sha256 is not None and sha256_bytes(raw) != expected_sha256:
        raise DiagnosticError("source_binding_invalid")
    return bytes(raw)


def _stable_descriptor_bytes(
    path: Path,
    *,
    authorized_fd: int,
    authorized_path: Path,
    mode: int,
    expected_sha256: str,
    maximum: int = 2 << 20,
) -> bytes:
    """Read an inherited procfd with pread and bind it to an authorized inode."""
    try:
        descriptor = inherited_descriptor(path)
        if descriptor is None or os.readlink(path) != str(authorized_path):
            raise DiagnosticError("source_binding_invalid")
        before = os.fstat(descriptor)
        authorized = os.fstat(authorized_fd)
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
        if (
            any(getattr(before, field) != getattr(authorized, field) for field in stable_fields)
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != mode
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum
        ):
            raise DiagnosticError("source_binding_invalid")
        raw = bytearray()
        offset = 0
        while offset <= maximum:
            chunk = os.pread(descriptor, min(1 << 20, maximum + 1 - offset), offset)
            if not chunk:
                break
            raw.extend(chunk)
            offset += len(chunk)
        after = os.fstat(descriptor)
        authorized_after = os.fstat(authorized_fd)
    except (OSError, ValueError) as error:
        raise DiagnosticError("source_binding_invalid") from error
    if (
        any(getattr(before, field) != getattr(after, field) for field in stable_fields)
        or any(getattr(authorized, field) != getattr(authorized_after, field) for field in stable_fields)
        or len(raw) != before.st_size
        or sha256_bytes(raw) != expected_sha256
    ):
        raise DiagnosticError("source_binding_invalid")
    return bytes(raw)


def _sealed_executable_bytes(
    path: Path,
    *,
    expected_descriptor: str,
    expected_name: str,
    expected_mode: int,
    expected_sha256: str,
    maximum: int,
) -> bytes:
    """Read and verify the immutable memfd from which this process executes."""
    try:
        descriptor = inherited_descriptor(path)
        if (
            descriptor is None
            or str(descriptor) != expected_descriptor
            or os.readlink(path) != f"/memfd:{expected_name} (deleted)"
        ):
            raise DiagnosticError("source_binding_invalid")
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
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_uid != os.getuid()
            or before.st_nlink != 0
            or not 0 < before.st_size <= maximum
            or seals & REQUIRED_MEMFD_SEALS != REQUIRED_MEMFD_SEALS
        ):
            raise DiagnosticError("source_binding_invalid")
        raw = bytearray()
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
            if not chunk:
                raise DiagnosticError("source_binding_invalid")
            raw.extend(chunk)
            offset += len(chunk)
        after = os.fstat(descriptor)
    except (OSError, ValueError) as error:
        raise DiagnosticError("source_binding_invalid") from error
    if (
        any(getattr(before, field) != getattr(after, field) for field in stable_fields)
        or fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals
        or len(raw) != before.st_size
        or sha256_bytes(raw) != expected_sha256
    ):
        raise DiagnosticError("source_binding_invalid")
    return bytes(raw)


def _validate_execution_memfds(
    environment: Mapping[str, str],
    script_path: Path,
    *,
    require_uv: bool,
) -> None:
    probe_descriptor = environment.get("DIAG_EXEC_PROBE_FD", "")
    _sealed_executable_bytes(
        script_path,
        expected_descriptor=probe_descriptor,
        expected_name="vmvm-probe-v2",
        expected_mode=0o500,
        expected_sha256=environment.get("DIAG_PROBE_SHA256", ""),
        maximum=2 << 20,
    )
    if require_uv:
        uv_descriptor = environment.get("DIAG_EXEC_UV_FD", "")
        if re.fullmatch(r"([3-9]|[1-9][0-9]+)", uv_descriptor) is None:
            raise DiagnosticError("source_binding_invalid")
        _sealed_executable_bytes(
            Path(f"/proc/self/fd/{uv_descriptor}"),
            expected_descriptor=uv_descriptor,
            expected_name="vmvm-uv-v2",
            expected_mode=0o755,
            expected_sha256=X86_UV_SHA256,
            maximum=64 << 20,
        )


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


def _load_canonical_json(path: Path, *, mode: int, expected_sha256: str) -> dict[str, Any]:
    raw = _stable_bytes(path, mode=mode, expected_sha256=expected_sha256)
    return _canonical_json_bytes(raw)


def _canonical_json_bytes(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DiagnosticError("child_invalid") from error
    if not isinstance(value, dict) or canonical_json(value) != raw.rstrip(b"\n"):
        raise DiagnosticError("child_invalid")
    return value


def _parse_environment_file(raw: bytes) -> dict[str, str]:
    if not raw.endswith(b"\0"):
        raise DiagnosticError("child_invalid")
    values: dict[str, str] = {}
    try:
        entries = raw[:-1].split(b"\0")
        for entry in entries:
            name, separator, value = entry.partition(b"=")
            key = name.decode("ascii")
            if not separator or not key or key in values:
                raise DiagnosticError("child_invalid")
            values[key] = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DiagnosticError("child_invalid") from error
    return values


def parse_identity(value: str) -> dict[str, int]:
    parts = value.split(":")
    if len(parts) != 4 or any(re.fullmatch(r"[0-9]+", part) is None for part in parts):
        raise DiagnosticError("child_invalid")
    device, inode, mode, owner_uid = (int(part) for part in parts)
    return {
        "device": device,
        "inode": inode,
        "mode": mode,
        "owner_uid": owner_uid,
    }


def parse_portable_identity(value: str) -> dict[str, int]:
    parts = value.split(":")
    if len(parts) != 3 or any(re.fullmatch(r"[0-9]+", part) is None for part in parts):
        raise DiagnosticError("child_invalid")
    inode, mode, owner_uid = (int(part) for part in parts)
    return {"inode": inode, "mode": mode, "owner_uid": owner_uid}


def validate_batch_admission(environment: Mapping[str, str], script_path: Path) -> dict[str, object]:
    _validate_execution_memfds(environment, script_path, require_uv=True)
    required = {
        "DIAG_ACTIVATION_PERMIT",
        "DIAG_AUTHORIZATION",
        "DIAG_AUTHORIZATION_FILE_SHA256",
        "DIAG_AUTHORIZATION_SHA256",
        "DIAG_BUNDLE_IDENTITY",
        "DIAG_BUNDLE_PORTABLE_IDENTITY",
        "DIAG_BUNDLE_ROOT",
        "DIAG_COMPLETION_RECEIPT",
        "DIAG_DIRECTORY_IDENTITY_POLICY",
        "DIAG_FINALIZER_PATH",
        "DIAG_FINALIZER_SHA256",
        "DIAG_JOB_AUTHORIZATION",
        "DIAG_JOB_NAME",
        "DIAG_LAUNCHER_PATH",
        "DIAG_LAUNCHER_SHA256",
        "DIAG_OUTPUT_ROOT",
        "DIAG_OUTPUT_PARENT_IDENTITY",
        "DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY",
        "DIAG_PROBE_PATH",
        "DIAG_PROBE_SHA256",
        "DIAG_RESERVATION",
        "DIAG_RESERVATION_IDENTITY",
        "DIAG_RESERVATION_PORTABLE_IDENTITY",
        "DIAG_SCRATCH_ROOT",
        "DIAG_SOURCE_REVISION",
        "DIAG_SOURCE_ROOT",
        "DIAG_SOURCE_IDENTITY",
        "DIAG_SOURCE_PORTABLE_IDENTITY",
        "DIAG_SOURCE_TREE",
        "DIAG_SUBMISSION_RECEIPT",
        "DIAG_VMVM_SHA256",
        "DIAG_WRAPPER_GATE_TIMEOUT_SECONDS",
        "DIAG_WRAPPER_PATH",
        "DIAG_WRAPPER_SHA256",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHON_BIN_X86_64",
        "PYTHON_SITE_X86_64",
        "PYTHON_SITE_X86_64_ENTRY_COUNT",
        "PYTHON_SITE_X86_64_IDENTITY",
        "PYTHON_SITE_X86_64_PORTABLE_IDENTITY",
        "PYTHON_SITE_X86_64_MANIFEST_SHA256",
        "PYTHON_SITE_X86_64_TOTAL_BYTES",
        "SLURM_EXPORT_ENV",
        "SLURM_JOB_ID",
        "SLURM_JOB_NAME",
        "TZ",
        "USER",
        "UV_BIN_X86_64",
        "VACLI_BIN",
        "VACLI_CONTAINER_PRIVILEGED",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS",
        "VACLI_LEASE_RETRIES",
        "VACLI_MAX_CONCURRENT_LEASES",
        "VACLI_MAX_PULL_RETRIES",
        *TLS_NAMES,
        *X2P_NAMES,
    }
    if any(not environment.get(name) for name in required):
        raise DiagnosticError("child_invalid")
    if (
        environment["DIAG_SOURCE_ROOT"] != str(EXPECTED_SOURCE_ROOT)
        or environment["DIAG_SOURCE_REVISION"] != SOURCE_REVISION
        or environment["DIAG_SOURCE_TREE"] != SOURCE_TREE
        or environment["DIAG_VMVM_SHA256"] != VMVM_SHA256
        or environment["DIAG_DIRECTORY_IDENTITY_POLICY"] != DIRECTORY_IDENTITY_POLICY_NAME
        or environment["DIAG_OUTPUT_ROOT"] != str(EXPECTED_OUTPUT_ROOT)
        or environment["DIAG_COMPLETION_RECEIPT"] != str(EXPECTED_COMPLETION_RECEIPT)
        or environment["DIAG_RESERVATION"] != str(EXPECTED_RESERVATION)
        or environment["DIAG_JOB_AUTHORIZATION"] != str(EXPECTED_RESERVATION / "job_authorization.json")
        or environment["DIAG_ACTIVATION_PERMIT"] != str(EXPECTED_RESERVATION / "activation_permit.json")
        or environment["DIAG_SUBMISSION_RECEIPT"] != str(EXPECTED_RESERVATION / "submission_receipt.json")
        or environment["DIAG_SCRATCH_ROOT"] != str(EXPECTED_SCRATCH_ROOT)
        or environment["DIAG_WRAPPER_GATE_TIMEOUT_SECONDS"] != "900"
        or environment["HOME"] != "/storage/home/tianhaowu"
        or environment["LANG"] != "C"
        or environment["LC_ALL"] != "C"
        or environment["LOGNAME"] != EXPECTED_OWNER
        or environment["PATH"] != "/usr/bin:/bin"
        or environment["PYTHONDONTWRITEBYTECODE"] != "1"
        or environment["PYTHON_BIN_X86_64"] != "python3"
        or environment["PYTHON_SITE_X86_64"] != str(BASE / "python_x86_64")
        or environment["SLURM_EXPORT_ENV"] != "NONE"
        or environment["TZ"] != "UTC"
        or environment["USER"] != EXPECTED_OWNER
        or environment["UV_BIN_X86_64"] != "/storage/home/tianhaowu/.local/x86_64/bin/uv"
        or environment["VACLI_BIN"] != "/public/fbpkgs/x86_64/vacli/stable/vacli"
        or environment["VACLI_CONTAINER_PRIVILEGED"] != "1"
        or environment["VACLI_IMAGE_PULL_TIMEOUT_SECONDS"] != str(IMAGE_PULL_TIMEOUT_SECONDS)
        or environment["VACLI_LEASE_RETRIES"] != str(LEASE_ATTEMPT_LIMIT)
        or environment["VACLI_MAX_CONCURRENT_LEASES"] != "1"
        or environment["VACLI_MAX_PULL_RETRIES"] != str(IMAGE_PULL_RETRY_LIMIT)
        or not str(environment.get("SLURM_JOB_ID", "")).isdigit()
        or NAME_RE.fullmatch(environment["DIAG_JOB_NAME"]) is None
        or environment.get("SLURM_JOB_NAME") != environment["DIAG_JOB_NAME"]
    ):
        raise DiagnosticError("child_invalid")
    for name in (*TLS_NAMES, *X2P_NAMES):
        if not environment[name] or "\0" in environment[name] or "\n" in environment[name]:
            raise DiagnosticError("child_invalid")
    for prefix in ("BASH_FUNC_", "LD_", "GIT_"):
        if any(name.startswith(prefix) for name in environment):
            raise DiagnosticError("child_invalid")
    if "UV" in environment or any(name.startswith("UV_") and name != "UV_BIN_X86_64" for name in environment):
        raise DiagnosticError("child_invalid")
    if any(
        name.startswith("PYTHON_")
        and name
        not in {
            "PYTHONDONTWRITEBYTECODE",
            "PYTHON_BIN_X86_64",
            "PYTHON_SITE_X86_64",
            "PYTHON_SITE_X86_64_ENTRY_COUNT",
            "PYTHON_SITE_X86_64_IDENTITY",
            "PYTHON_SITE_X86_64_PORTABLE_IDENTITY",
            "PYTHON_SITE_X86_64_MANIFEST_SHA256",
            "PYTHON_SITE_X86_64_TOTAL_BYTES",
        }
        for name in environment
    ):
        raise DiagnosticError("child_invalid")

    identity_pairs = (
        ("DIAG_BUNDLE_IDENTITY", "DIAG_BUNDLE_PORTABLE_IDENTITY"),
        ("DIAG_OUTPUT_PARENT_IDENTITY", "DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY"),
        ("DIAG_RESERVATION_IDENTITY", "DIAG_RESERVATION_PORTABLE_IDENTITY"),
        ("DIAG_SOURCE_IDENTITY", "DIAG_SOURCE_PORTABLE_IDENTITY"),
        ("PYTHON_SITE_X86_64_IDENTITY", "PYTHON_SITE_X86_64_PORTABLE_IDENTITY"),
    )
    for full_name, portable_name in identity_pairs:
        if portable_directory_identity(parse_identity(environment[full_name])) != parse_portable_identity(
            environment[portable_name]
        ):
            raise DiagnosticError("child_invalid")
    for path in (
        Path(environment["DIAG_BUNDLE_ROOT"]),
        Path(environment["DIAG_SOURCE_ROOT"]),
        Path(environment["PYTHON_SITE_X86_64"]),
        Path(environment["DIAG_RESERVATION"]),
        Path(environment["DIAG_OUTPUT_ROOT"]).parent,
    ):
        if not canonical_directory_path(path):
            raise DiagnosticError("child_invalid")

    reservation_path = Path(environment["DIAG_RESERVATION"])
    reservation_fd = open_portable_bound_directory(
        reservation_path,
        parse_portable_identity(environment["DIAG_RESERVATION_PORTABLE_IDENTITY"]),
        required_mode=0o500,
    )
    reservation = descriptor_path(reservation_fd)
    info = os.fstat(reservation_fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise DiagnosticError("child_invalid")
    expected_children = {
        ".writer.lock",
        "activation_permit.json",
        "job_authorization.json",
        "launch_intent.json",
        "slurm_environment.bin",
        "submission_receipt.json",
    }
    if {entry.name for entry in os.scandir(reservation)} != expected_children:
        raise DiagnosticError("child_invalid")
    authorization_sha = environment["DIAG_AUTHORIZATION_SHA256"]
    authorization_file_sha = environment["DIAG_AUTHORIZATION_FILE_SHA256"]
    receipt_path = reservation / "submission_receipt.json"
    permit_path = reservation / "activation_permit.json"
    job_authorization_path = reservation / "job_authorization.json"
    intent_path = reservation / "launch_intent.json"
    authorization = _load_canonical_json(
        Path(environment["DIAG_AUTHORIZATION"]),
        mode=0o400,
        expected_sha256=authorization_file_sha,
    )
    body = dict(authorization)
    if (
        set(authorization)
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
        or authorization.get("artifact_type") != "vmvm_task_free_diagnostic_authorization_v2"
        or authorization.get("schema_version") != 2
        or authorization.get("state") != "approved"
        or body.pop("authorization_sha256", None) != authorization_sha
        or sha256_bytes(canonical_json(body)) != authorization_sha
    ):
        raise DiagnosticError("child_invalid")
    receipt_raw = _stable_bytes(receipt_path, mode=0o400)
    receipt = _canonical_json_bytes(receipt_raw)
    permit_raw = _stable_bytes(permit_path, mode=0o400)
    permit = _canonical_json_bytes(permit_raw)
    job_auth_raw = _stable_bytes(job_authorization_path, mode=0o400)
    job_auth = _canonical_json_bytes(job_auth_raw)
    intent = _canonical_json_bytes(_stable_bytes(intent_path, mode=0o400))
    telemetry_keys = {
        "converged",
        "deadline_seconds",
        "elapsed_milliseconds",
        "explicit_conflict_fields",
        "final_mismatch_fields",
        "mismatch_occurrences",
        "polls",
        "required_consecutive",
    }
    held = receipt.get("held")
    activation = receipt.get("activation")
    if (
        not isinstance(held, dict)
        or set(held)
        != telemetry_keys
        | {
            "pre_authorization_mismatch_fields",
            "post_authorization_mismatch_fields",
        }
        or not isinstance(activation, dict)
        or set(activation) != telemetry_keys
        or held.get("converged") is not True
        or activation.get("converged") is not True
        or held.get("required_consecutive") != 2
        or activation.get("required_consecutive") != 2
        or held.get("explicit_conflict_fields") != []
        or activation.get("explicit_conflict_fields") != []
        or held.get("pre_authorization_mismatch_fields") != []
        or held.get("post_authorization_mismatch_fields") != []
    ):
        raise DiagnosticError("child_invalid")
    if (
        set(receipt)
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
        or set(job_auth)
        != {
            "artifact_type",
            "authorization_file_sha256",
            "authorization_sha256",
            "job",
            "production_authorized",
            "state",
        }
        or receipt.get("artifact_type") != "vmvm_task_free_submission_receipt_v2"
        or receipt.get("state") != "submitted"
        or receipt.get("authorization_file_sha256") != authorization_file_sha
        or receipt.get("authorization_sha256") != authorization_sha
        or receipt.get("submission_attempts") != 1
        or receipt.get("release_attempts") != 1
        or receipt.get("release_outcome") not in {"completed", "nonzero", "unknown"}
        or receipt.get("production_authorized") is not False
        or receipt.get("job_authorization_sha256") != sha256_bytes(job_auth_raw)
        or permit
        != {
            "artifact_type": "vmvm_task_free_activation_permit_v2",
            "authorization_file_sha256": authorization_file_sha,
            "authorization_sha256": authorization_sha,
            "environment_sha256": receipt.get("environment_sha256"),
            "job_authorization_sha256": sha256_bytes(job_auth_raw),
            "production_authorized": False,
            "state": "activated",
            "submission_receipt_sha256": sha256_bytes(receipt_raw),
        }
        or job_auth.get("artifact_type") != "vmvm_task_free_job_authorization_v2"
        or job_auth.get("state") != "held_verified"
        or job_auth.get("authorization_file_sha256") != authorization_file_sha
        or job_auth.get("authorization_sha256") != authorization_sha
        or job_auth.get("production_authorized") is not False
    ):
        raise DiagnosticError("child_invalid")
    job = receipt.get("job")
    if (
        not isinstance(job, dict)
        or job
        != {
            "cluster": EXPECTED_CLUSTER,
            "job_id": environment["SLURM_JOB_ID"],
            "job_name": environment["DIAG_JOB_NAME"],
        }
        or job_auth.get("job") != job
    ):
        raise DiagnosticError("child_invalid")
    environment_path = reservation / "slurm_environment.bin"
    environment_raw = _stable_bytes(
        environment_path,
        mode=0o400,
        expected_sha256=str(receipt.get("environment_sha256")),
    )
    exported = _parse_environment_file(environment_raw)
    if set(exported) != required - {"SLURM_JOB_ID", "SLURM_JOB_NAME"}:
        raise DiagnosticError("child_invalid")
    if any(environment.get(name) != value for name, value in exported.items()):
        raise DiagnosticError("child_invalid")
    bundle = authorization.get("bundle")
    credentials = authorization.get("credentials")
    source = authorization.get("source")
    runtime = authorization.get("runtime")
    launch = authorization.get("launch")
    protocol = authorization.get("protocol")
    if not all(isinstance(value, dict) for value in (bundle, credentials, source, runtime, launch, protocol)):
        raise DiagnosticError("child_invalid")
    assert isinstance(bundle, dict)
    assert isinstance(credentials, dict)
    assert isinstance(source, dict)
    assert isinstance(runtime, dict)
    assert isinstance(launch, dict)
    assert isinstance(protocol, dict)
    if source != {
        "path": str(EXPECTED_SOURCE_ROOT),
        "portable_root_identity": parse_portable_identity(environment["DIAG_SOURCE_PORTABLE_IDENTITY"]),
        "revision": SOURCE_REVISION,
        "tree": SOURCE_TREE,
        "verifiers_revision": VERIFIERS_REVISION,
        "renderers_revision": RENDERERS_REVISION,
        "pydantic_config_revision": PYDANTIC_CONFIG_REVISION,
        "root_identity": parse_identity(environment["DIAG_SOURCE_IDENTITY"]),
        "vmvm_sha256": VMVM_SHA256,
    }:
        raise DiagnosticError("child_invalid")
    if portable_directory_identity(source["root_identity"]) != source["portable_root_identity"]:
        raise DiagnosticError("child_invalid")
    source_fd = open_portable_bound_directory(Path(environment["DIAG_SOURCE_ROOT"]), source["portable_root_identity"])
    try:
        attest_imported_source(source_fd)
    finally:
        os.close(source_fd)
    site = runtime.get("site")
    if (
        runtime.get("image") != IMAGE
        or runtime.get("python_name") != "python3"
        or set(runtime) != {"image", "python_name", "site", "uv", "vacli"}
        or not isinstance(site, dict)
        or site
        != {
            "inventory": {
                "entry_count": int(environment["PYTHON_SITE_X86_64_ENTRY_COUNT"]),
                "manifest_sha256": environment["PYTHON_SITE_X86_64_MANIFEST_SHA256"],
                "owner_uid": os.getuid(),
                "total_bytes": int(environment["PYTHON_SITE_X86_64_TOTAL_BYTES"]),
            },
            "path": str(BASE / "python_x86_64"),
            "portable_root_identity": parse_portable_identity(environment["PYTHON_SITE_X86_64_PORTABLE_IDENTITY"]),
            "root_identity": parse_identity(environment["PYTHON_SITE_X86_64_IDENTITY"]),
        }
        or set(launch)
        != {
            "account",
            "cluster",
            "comment",
            "completion_receipt",
            "cpus",
            "environment_export",
            "job_name",
            "log_root",
            "memory",
            "nodes",
            "output_parent_identity",
            "output_parent_portable_identity",
            "output_root",
            "partition",
            "qos",
            "reservation",
            "scratch_root",
            "time_limit",
        }
        or launch.get("cluster") != EXPECTED_CLUSTER
        or launch.get("environment_export") != ENVIRONMENT_EXPORT_POLICY
        or launch.get("comment")
        != f"vmvm-v7-preflight:{environment['DIAG_JOB_NAME'].removeprefix('vmvm-v7-preflight-')}"
        or launch.get("job_name") != environment["DIAG_JOB_NAME"]
        or launch.get("output_root") != str(EXPECTED_OUTPUT_ROOT)
        or launch.get("completion_receipt") != str(EXPECTED_COMPLETION_RECEIPT)
        or launch.get("output_parent_identity") != parse_identity(environment["DIAG_OUTPUT_PARENT_IDENTITY"])
        or launch.get("output_parent_portable_identity")
        != parse_portable_identity(environment["DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY"])
        or portable_directory_identity(launch["output_parent_identity"]) != launch["output_parent_portable_identity"]
        or launch.get("reservation") != str(EXPECTED_RESERVATION)
        or launch.get("scratch_root") != str(EXPECTED_SCRATCH_ROOT)
        or launch.get("log_root") != str(BASE / "logs/vmvm_v21_task_free_preflight_a09a9a189_v7_portable_identity")
        or launch.get("nodes") != 1
        or launch.get("cpus") != 2
        or launch.get("memory") != "8G"
        or launch.get("partition") != "cpu_x86"
        or launch.get("qos") != "cpu_x86_lowest"
        or launch.get("account") != "ram"
        or launch.get("time_limit") != "1-12:00:00"
    ):
        raise DiagnosticError("child_invalid")
    if protocol != PREFLIGHT_PROTOCOL:
        raise DiagnosticError("child_invalid")
    if portable_directory_identity(site["root_identity"]) != site["portable_root_identity"]:
        raise DiagnosticError("child_invalid")
    site_fd = open_portable_bound_directory(Path(environment["PYTHON_SITE_X86_64"]), site["portable_root_identity"])
    try:
        if directory_manifest(site_fd, expected_owner_uid=os.getuid()) != site["inventory"]:
            raise DiagnosticError("child_invalid")
    finally:
        os.close(site_fd)
    for label, expected_path, expected_digest in (("uv", environment["UV_BIN_X86_64"], X86_UV_SHA256),):
        record = runtime.get(label)
        if record != {"path": expected_path, "sha256": expected_digest}:
            raise DiagnosticError("child_invalid")
        if Path(expected_path).resolve(strict=True) != Path(expected_path):
            raise DiagnosticError("child_invalid")
        _stable_bytes(
            Path(expected_path),
            mode=0o755,
            expected_sha256=expected_digest,
            maximum=64 << 20,
        )
    if (
        runtime.get("vacli")
        != {
            "path": environment["VACLI_BIN"],
            "resolved_path": VACLI_RESOLVED,
            "sha256": VACLI_SHA256,
        }
        or Path(environment["VACLI_BIN"]).resolve(strict=True) != Path(VACLI_RESOLVED)
        or not _same_open_file(Path(environment["VACLI_BIN"]), Path(VACLI_RESOLVED))
    ):
        raise DiagnosticError("child_invalid")
    artifact_labels = {
        "finalizer",
        "launcher",
        "probe",
        "readme",
        "tests",
        "wrapper",
    }
    if (
        set(bundle) != artifact_labels | {"portable_root_identity", "root_identity"}
        or bundle.get("root_identity") != parse_identity(environment["DIAG_BUNDLE_IDENTITY"])
        or bundle.get("portable_root_identity") != parse_portable_identity(environment["DIAG_BUNDLE_PORTABLE_IDENTITY"])
        or portable_directory_identity(bundle["root_identity"]) != bundle["portable_root_identity"]
    ):
        raise DiagnosticError("child_invalid")
    if any(
        not isinstance(bundle[label], dict)
        or set(bundle[label]) != {"path", "sha256"}
        or SHA_RE.fullmatch(str(bundle[label].get("sha256"))) is None
        for label in artifact_labels
    ):
        raise DiagnosticError("child_invalid")
    if intent != {
        "artifact_type": "vmvm_task_free_launch_intent_v2",
        "authorization_file_sha256": authorization_file_sha,
        "authorization_sha256": authorization_sha,
        "bundle_sha256": {label: bundle[label]["sha256"] for label in ("finalizer", "launcher", "probe", "wrapper")},
        "environment_sha256": receipt.get("environment_sha256"),
        "job_name": environment["DIAG_JOB_NAME"],
        "production_authorized": False,
        "state": "reserved",
    }:
        raise DiagnosticError("child_invalid")
    for label, env_name in (
        ("launcher", "DIAG_LAUNCHER_SHA256"),
        ("wrapper", "DIAG_WRAPPER_SHA256"),
        ("probe", "DIAG_PROBE_SHA256"),
        ("finalizer", "DIAG_FINALIZER_SHA256"),
    ):
        record = bundle.get(label)
        if not isinstance(record, dict) or record.get("sha256") != environment[env_name]:
            raise DiagnosticError("child_invalid")
        if record.get("path") != environment[f"DIAG_{label.upper()}_PATH"]:
            raise DiagnosticError("child_invalid")
    bundle_fd = open_portable_bound_directory(
        Path(environment["DIAG_BUNDLE_ROOT"]),
        parse_portable_identity(environment["DIAG_BUNDLE_PORTABLE_IDENTITY"]),
        required_mode=0o700,
    )
    bundle_root = descriptor_path(bundle_fd)
    bundle_status = os.fstat(bundle_fd)
    if (
        not stat.S_ISDIR(bundle_status.st_mode)
        or stat.S_IMODE(bundle_status.st_mode) != 0o700
        or bundle_status.st_uid != os.getuid()
        or {entry.name for entry in os.scandir(bundle_root)}
        != {
            "README.md",
            "finalize_vmvm_task_free_v2.py",
            "launch_vmvm_task_free_v2.py",
            "probe_vmvm_task_free_v2.py",
            "run_vmvm_task_free_v2.sbatch",
            "test_vmvm_task_free_v2.py",
        }
    ):
        raise DiagnosticError("child_invalid")
    for label, filename in (
        ("readme", "README.md"),
        ("tests", "test_vmvm_task_free_v2.py"),
    ):
        record = bundle.get(label)
        expected_path = Path(environment["DIAG_BUNDLE_ROOT"]) / filename
        if (
            not isinstance(record, dict)
            or record.get("path") != str(expected_path)
            or SHA_RE.fullmatch(str(record.get("sha256"))) is None
        ):
            raise DiagnosticError("child_invalid")
        _stable_bytes(
            bundle_root / filename,
            mode=0o400,
            expected_sha256=str(record["sha256"]),
        )
    probe_record = bundle["probe"]
    if not isinstance(probe_record, dict) or probe_record.get("path") != environment["DIAG_PROBE_PATH"]:
        raise DiagnosticError("child_invalid")
    _stable_bytes(
        bundle_root / "probe_vmvm_task_free_v2.py",
        mode=0o500,
        expected_sha256=environment["DIAG_PROBE_SHA256"],
    )
    os.close(bundle_fd)
    tls = credentials.get("tls")
    x2p = credentials.get("x2p")
    if (
        set(credentials) != {"tls", "x2p"}
        or not isinstance(tls, dict)
        or set(tls) != set(TLS_NAMES)
        or not isinstance(x2p, dict)
        or set(x2p) != set(X2P_NAMES)
    ):
        raise DiagnosticError("child_invalid")
    for name in TLS_NAMES:
        record = tls.get(name)
        if not isinstance(record, dict) or set(record) != {"path", "sha256"} or record.get("path") != environment[name]:
            raise DiagnosticError("child_invalid")
        _stable_bytes(
            Path(environment[name]),
            mode=0o500,
            expected_sha256=str(record.get("sha256")),
            maximum=64 << 10,
        )
    for name in X2P_NAMES:
        record = x2p.get(name)
        if (
            not isinstance(record, dict)
            or set(record) != {"sha256"}
            or sha256_bytes(environment[name].encode()) != record.get("sha256")
        ):
            raise DiagnosticError("child_invalid")
    os.close(reservation_fd)
    return {"state": "admitted"}


def validate_cli_paths(
    args: argparse.Namespace,
    environment: Mapping[str, str],
    *,
    require_output: bool,
) -> None:
    source_fd = inherited_portable_bound_directory(
        args.source_root,
        parse_portable_identity(environment["DIAG_SOURCE_PORTABLE_IDENTITY"]),
        code="source_binding_invalid",
    )
    os.close(source_fd)
    site_fd = inherited_portable_bound_directory(
        args.site_root,
        parse_portable_identity(environment["PYTHON_SITE_X86_64_PORTABLE_IDENTITY"]),
        code="site_binding_invalid",
    )
    try:
        expected_inventory = {
            "entry_count": int(environment["PYTHON_SITE_X86_64_ENTRY_COUNT"]),
            "manifest_sha256": environment["PYTHON_SITE_X86_64_MANIFEST_SHA256"],
            "owner_uid": os.getuid(),
            "total_bytes": int(environment["PYTHON_SITE_X86_64_TOTAL_BYTES"]),
        }
        if directory_manifest(site_fd, expected_owner_uid=os.getuid()) != expected_inventory:
            raise DiagnosticError("site_binding_invalid")
    finally:
        os.close(site_fd)
    if not require_output:
        return
    if (
        args.output_dir is None
        or args.completion_receipt is None
        or args.scratch_root != EXPECTED_SCRATCH_ROOT
        or args.output_dir.name != EXPECTED_OUTPUT_ROOT.name
        or args.completion_receipt.name != EXPECTED_COMPLETION_RECEIPT.name
        or args.output_dir.parent != args.completion_receipt.parent
    ):
        raise DiagnosticError("child_invalid")
    output_parent_fd = inherited_portable_bound_directory(
        args.output_dir.parent,
        parse_portable_identity(environment["DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY"]),
        code="output_binding_invalid",
    )
    os.close(output_parent_fd)


def summarize_stage_results(
    results: Sequence[Mapping[str, object]],
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
        for pair_index in range(REPETITIONS):
            pair = {
                str(item["x2p_mode"]): item
                for item in results
                if item["stage"] == stage and item["pair_index"] == pair_index
            }
            if set(pair) != set(MODES):
                raise DiagnosticError("stage_result_invalid")
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


def run_supervisor(args: argparse.Namespace) -> dict[str, object]:
    source_root = args.source_root
    site_root = args.site_root
    script = Path(__file__)
    completion_receipt = args.completion_receipt
    if inherited_descriptor(script) is None:
        raise DiagnosticError("child_invalid")
    if (
        args.output_dir.exists()
        or args.output_dir.is_symlink()
        or args.scratch_root.exists()
        or args.scratch_root.is_symlink()
        or completion_receipt.exists()
        or completion_receipt.is_symlink()
    ):
        raise DiagnosticError("child_invalid")
    output_parent_fd = inherited_bound_directory(
        args.output_dir.parent,
        parse_identity(os.environ["DIAG_OUTPUT_PARENT_IDENTITY"]),
        code="output_binding_invalid",
    )
    scratch_parent_fd = os.open(
        args.scratch_root.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    output_fd: int | None = None
    scratch_fd: int | None = None
    scratch_identity: dict[str, int] | None = None
    source_snapshot_fd: int | None = None
    site_snapshot_fd: int | None = None
    snapshot_guard: SnapshotGuard | None = None
    scratch_created = False
    results: list[dict[str, object]] = []
    source_fd = inherited_bound_directory(
        source_root,
        parse_identity(os.environ["DIAG_SOURCE_IDENTITY"]),
        code="source_binding_invalid",
    )
    site_fd = inherited_bound_directory(
        site_root,
        parse_identity(os.environ["PYTHON_SITE_X86_64_IDENTITY"]),
        code="site_binding_invalid",
    )
    cleanup_failed = False
    try:
        os.mkdir(args.output_dir.name, mode=0o700, dir_fd=output_parent_fd)
        output_fd = os.open(
            args.output_dir.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=output_parent_fd,
        )
        try:
            os.stat(args.scratch_root.name, dir_fd=scratch_parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise DiagnosticError("child_invalid")
        os.mkdir(args.scratch_root.name, mode=0o700, dir_fd=scratch_parent_fd)
        scratch_fd = os.open(
            args.scratch_root.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=scratch_parent_fd,
        )
        scratch_identity = descriptor_identity(scratch_fd)
        scratch_created = True
        expected_site_inventory = {
            "entry_count": int(os.environ["PYTHON_SITE_X86_64_ENTRY_COUNT"]),
            "manifest_sha256": os.environ["PYTHON_SITE_X86_64_MANIFEST_SHA256"],
            "owner_uid": os.getuid(),
            "total_bytes": int(os.environ["PYTHON_SITE_X86_64_TOTAL_BYTES"]),
        }
        (
            source_snapshot,
            site_snapshot,
            source_snapshot_inventory,
            site_snapshot_inventory,
        ) = create_execution_snapshot(
            source_fd,
            site_fd,
            descriptor_path(scratch_fd),
            expected_site_inventory,
        )
        source_snapshot_fd = os.open(
            source_snapshot,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        site_snapshot_fd = os.open(
            site_snapshot,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        snapshot_source_root = descriptor_path(source_snapshot_fd)
        snapshot_site_root = descriptor_path(site_snapshot_fd)
        snapshot_guard = SnapshotGuard((snapshot_source_root, snapshot_site_root))
        for stage in STAGES:
            for pair_index, order in enumerate(MODE_ORDERS):
                for order_position, mode in enumerate(order):
                    if (
                        not snapshot_guard.is_clean()
                        or directory_manifest(source_snapshot_fd, expected_owner_uid=os.getuid())
                        != source_snapshot_inventory
                        or directory_manifest(site_snapshot_fd, expected_owner_uid=os.getuid())
                        != site_snapshot_inventory
                    ):
                        raise DiagnosticError("source_binding_invalid")
                    result = run_stage_child(
                        script=script,
                        python=Path(sys.executable).resolve(strict=True),
                        source_root=snapshot_source_root,
                        site_root=snapshot_site_root,
                        scratch_root_fd=scratch_fd,
                        snapshot_guard=snapshot_guard,
                        mode=mode,
                        stage=stage,
                        pair_index=pair_index,
                        order_position=order_position,
                    )
                    if result.get("cleanup_complete") is not True:
                        raise DiagnosticError("cleanup_failed")
                    if result.get("failure_class") in {
                        "child_invalid",
                        "child_output_overflow",
                        "child_timeout",
                    }:
                        raise DiagnosticError("stage_result_invalid")
                    validate_stage_result(
                        result,
                        expected_mode=mode,
                        expected_stage=stage,
                        expected_pair_index=pair_index,
                        expected_order_position=order_position,
                    )
                    if (
                        not snapshot_guard.is_clean()
                        or directory_manifest(source_snapshot_fd, expected_owner_uid=os.getuid())
                        != source_snapshot_inventory
                        or directory_manifest(site_snapshot_fd, expected_owner_uid=os.getuid())
                        != site_snapshot_inventory
                    ):
                        raise DiagnosticError("source_binding_invalid")
                    results.append(result)
        attest_imported_source(source_fd)
        if directory_manifest(site_fd, expected_owner_uid=os.getuid()) != expected_site_inventory:
            raise DiagnosticError("site_binding_invalid")
        if len(results) != CELL_COUNT:
            raise DiagnosticError("stage_result_invalid")
        if not snapshot_guard.close():
            raise DiagnosticError("source_binding_invalid")
        snapshot_guard = None
        os.close(source_snapshot_fd)
        source_snapshot_fd = None
        os.close(site_snapshot_fd)
        site_snapshot_fd = None
        if not _remove_bound_tree_verified(
            scratch_parent_fd,
            args.scratch_root.name,
            scratch_fd,
            scratch_identity,
        ):
            raise DiagnosticError("cleanup_failed")
        scratch_created = False
        os.close(scratch_fd)
        scratch_fd = None
        summary = summarize_stage_results(results)
        counts = summary["result_counts"]
        failures = summary["safe_failure_counts"]
        assert isinstance(counts, dict)
        assert isinstance(failures, dict)
        certificate = {
            "artifact_type": "vmvm_task_free_diagnostic_certificate_v2",
            "authorization_file_sha256": args.authorization_file_sha256,
            "authorization_sha256": args.authorization_sha256,
            "automatic_remediation": False,
            "causal_assessment": summary["causal_assessment"],
            "causal_contrasts": summary["causal_contrasts"],
            "diagnostic_only": True,
            "environment_sha256": args.environment_sha256,
            "execution_inputs": {
                "authorized_site": expected_site_inventory,
                "source_snapshot": source_snapshot_inventory,
                "site_snapshot": site_snapshot_inventory,
            },
            "image": IMAGE,
            "job": {
                "cluster": EXPECTED_CLUSTER,
                "job_id": args.job_id,
                "job_name": args.job_name,
            },
            "job_authorization_sha256": args.job_authorization_sha256,
            "model_endpoint_accessed": False,
            "production_authorized": False,
            "protocol": {
                "cell_count": CELL_COUNT,
                "causal_scope": "construction_backend_ready",
                "lease_attempt_limit_per_cell": LEASE_ATTEMPT_LIMIT,
                "mode_orders": [list(order) for order in MODE_ORDERS],
                "repetitions_per_mode": REPETITIONS,
                "stage_timeout_seconds": STAGE_TIMEOUT_SECONDS,
            },
            "outcome_contrasts": summary["outcome_contrasts"],
            "retry_phase_aggregate": summary["retry_phase_aggregate"],
            "result_counts": counts,
            "safe_failure_counts": failures,
            "schema_version": 2,
            "submission_receipt_sha256": args.submission_receipt_sha256,
            "source": {
                "pydantic_config_revision": PYDANTIC_CONFIG_REVISION,
                "renderers_revision": RENDERERS_REVISION,
                "revision": SOURCE_REVISION,
                "tree": SOURCE_TREE,
                "verifiers_revision": VERIFIERS_REVISION,
                "vmvm_sha256": VMVM_SHA256,
            },
            "stage_results": results,
            "task_data_accessed": False,
            "x2p_modes": list(MODES),
        }
        certificate_payload = canonical_json(certificate) + b"\n"
        if len(certificate_payload) > MAX_RESULT_BYTES:
            raise DiagnosticError("stage_result_invalid")
        _atomic_write(output_fd, "diagnostic_certificate.json", certificate_payload, 0o400)
        sealed_identity = descriptor_identity(output_fd)
        sealed_identity["mode"] = 0o500
        completion_request = {
            "artifact_type": "vmvm_task_free_external_completion_request_v2",
            "authorization_file_sha256": args.authorization_file_sha256,
            "authorization_sha256": args.authorization_sha256,
            "certificate_sha256": sha256_bytes(certificate_payload),
            "diagnostic_only": True,
            "environment_sha256": args.environment_sha256,
            "external_completion_receipt": str(EXPECTED_COMPLETION_RECEIPT),
            "job": {
                "cluster": EXPECTED_CLUSTER,
                "job_id": args.job_id,
                "job_name": args.job_name,
            },
            "job_authorization_sha256": args.job_authorization_sha256,
            "output_root_identity": sealed_identity,
            "production_authorized": False,
            "state": "awaiting_external_completion",
            "submission_receipt_sha256": args.submission_receipt_sha256,
        }
        completion_payload = canonical_json(completion_request) + b"\n"
        if (
            _stable_bytes(
                descriptor_path(output_fd) / "diagnostic_certificate.json",
                mode=0o400,
                expected_sha256=sha256_bytes(certificate_payload),
                maximum=MAX_RESULT_BYTES,
            )
            != certificate_payload
        ):
            raise DiagnosticError("child_invalid")
        _atomic_write(output_fd, "completion_request.json", completion_payload, 0o400)
        os.fchmod(output_fd, 0o500)
        os.fsync(output_fd)
        os.fsync(output_parent_fd)
        return {
            "failure_categories": len(failures),
            "passed": counts.get("passed", 0),
            "stages": len(results),
            "state": "awaiting_external_completion",
        }
    finally:
        if snapshot_guard is not None and not snapshot_guard.close():
            cleanup_failed = True
        for descriptor in (
            source_fd,
            site_fd,
            source_snapshot_fd,
            site_snapshot_fd,
        ):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    cleanup_failed = True
        if scratch_created:
            if (
                scratch_fd is None
                or scratch_identity is None
                or not _remove_bound_tree_verified(
                    scratch_parent_fd,
                    args.scratch_root.name,
                    scratch_fd,
                    scratch_identity,
                )
            ):
                cleanup_failed = True
        if scratch_fd is not None:
            try:
                os.close(scratch_fd)
            except OSError:
                cleanup_failed = True
        try:
            os.close(scratch_parent_fd)
        except OSError:
            cleanup_failed = True
        if output_fd is not None:
            try:
                os.close(output_fd)
            except OSError:
                cleanup_failed = True
        try:
            os.close(output_parent_fd)
        except OSError:
            cleanup_failed = True
        if cleanup_failed:
            raise DiagnosticError("cleanup_failed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-batch", action="store_true")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--completion-receipt", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.disable(logging.CRITICAL)
    args = _parser().parse_args(argv)
    try:
        if not args.validate_batch:
            raise DiagnosticError("child_invalid")
        result = validate_batch_admission(os.environ, Path(__file__))
        validate_cli_paths(args, os.environ, require_output=True)
    except BaseException as error:
        code = error.code if isinstance(error, DiagnosticError) else classify_failure(error)
        print(canonical_json({"code": code, "state": "failed"}).decode(), file=sys.stderr)
        return 2
    print(canonical_json(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
