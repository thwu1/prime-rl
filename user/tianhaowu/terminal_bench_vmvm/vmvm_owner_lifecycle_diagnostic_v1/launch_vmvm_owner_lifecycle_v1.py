#!/usr/bin/env python3
# ruff: noqa: BLE001
"""Submit one held, task-free VMVM owner-lifecycle diagnostic after authorization."""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
SOURCE_ROOT = BASE / "sources/prime-rl-9d7841b36"
SOURCE_REVISION = "9d7841b36bafcd58769041925b00deba7c25ffca"
SOURCE_TREE = "7f4027723ab036b888b1baee8c0d51c962653f68"
VERIFIERS_REVISION = "615b1a30ee3d23cf8d835b64174229c19da887bc"
RENDERERS_REVISION = "044d9e2541f6a911cacae9da353fc063911ef1f8"
PYDANTIC_CONFIG_REVISION = "896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f"
BACKEND_SHA256 = "13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a"
BACKEND_RELATIVE_PATH = "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py"
X86_UV = Path("/storage/home/tianhaowu/.local/x86_64/bin/uv")
X86_UV_SHA256 = "ec831939765474162efb6c8c813e2b10908b26b04eaf98ac3e2972fa12d189b9"
X86_SITE = BASE / "python_x86_64"
VACLI = Path("/public/fbpkgs/x86_64/vacli/stable/vacli")
VACLI_RESOLVED = Path("/infra/public/fbpkgs/x86_64/vacli/794/vacli")
VACLI_SHA256 = "8be49a764bd0fac1a3ef2bef053ced556d18397d44642660eb8a2d22a7c235b3"
OUTPUT_ROOT = BASE / "diagnostics/vmvm_owner_lifecycle_9d7841b36_v1"
RESERVATION = Path(f"{OUTPUT_ROOT}.launch-reservation")
COMPLETION_RECEIPT = Path(f"{OUTPUT_ROOT}.external-completion.json")
LOG_ROOT = BASE / "logs/vmvm_owner_lifecycle_9d7841b36_v1"
SCRATCH_ROOT = Path(f"{OUTPUT_ROOT}.scratch")
CLUSTER = "fair-cw-use2-3"
OWNER = "tianhaowu"
OWNER_IDENTITY = "tianhaowu(656177)"
OWNER_UID = 656177
CANONICAL_TMUX_TARGET = "swebench_vmvm:Launcher.0"
SYSTEM_PYTHON = Path("/usr/bin/python3.12")
SYSTEM_PYTHON_SHA256 = "1a301bb1763139d48ae638d97b11edf56de6cd185e1b054eae6dc28c271c0c5f"
TMUX_SHA256 = "e38ba2aef1810640f05fd8afaa62daf47ccce6bc0e18d73f73b8b6cc94deade2"
SBATCH_SHA256 = "3c1029c3a436107bf48b3b2d450e5fd1c9b204e6674906005cbbbb3c7df7feda"
QUERY_TIMEOUT_SECONDS = 20
SUBMIT_TIMEOUT_SECONDS = 30
SUBMISSION_LOOKUP_TIMEOUT_SECONDS = 120
SUBMISSION_LOOKUP_INTERVAL_SECONDS = 2
HELD_TIMEOUT_SECONDS = 982
ACTIVATION_TIMEOUT_SECONDS = 742
POLL_INTERVAL_SECONDS = 2
REQUIRED_CONSECUTIVE = 2
WRAPPER_GATE_TIMEOUT_SECONDS = 600
JOB_TIME_LIMIT = "01:30:00"
JOB_SECONDS = 5_400
SIGNAL_LEAD_SECONDS = 600
FINALIZATION_BUDGET_SECONDS = 600
ADMISSION_TIMEOUT_SECONDS = 300
SUPERVISOR_TIMEOUT_SECONDS = 2_700
TIMEOUT_KILL_GRACE_SECONDS = 120
TIMEOUT_KILL_GRACE_COUNT = 2
JOB_CPUS = "2"
JOB_MEMORY = "8G"
SHA_RE = re.compile(r"[0-9a-f]{64}")
REV_RE = re.compile(r"[0-9a-f]{40}")
JOB_RE = re.compile(r"[1-9][0-9]*")
TOKEN_RE = re.compile(r"[0-9a-f]{24}")
NAME_RE = re.compile(r"vmvm-owner-life-([0-9a-f]{24})")
ACTIVE_STATES = {"PENDING", "CONFIGURING", "RUNNING", "COMPLETING"}
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
X2P_NAMES = ("X2P_ENV", "X2P_CFG_ENV", "X2P_PROXY_URL")
TLS_NAMES = ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH")
DIRECTORY_IDENTITY_POLICY_NAME = "nfs_portable_inode_mode_uid_anchored_v2"
DIRECTORY_IDENTITY_POLICY = {
    "batch_fields": ["inode", "mode", "owner_uid"],
    "cross_host_variance": ["device"],
    "launcher_fields": ["device", "inode", "mode", "owner_uid"],
    "path_binding": "absolute_anchored_openat_nofollow",
}
DIAGNOSTIC_PROTOCOL = {
    "cell_count": 1,
    "directory_identity_policy": DIRECTORY_IDENTITY_POLICY,
    "diagnostic_only": True,
    "external_completion_handoff": "shared_nfs_portable_inode_mode_uid_v1",
    "fixed_commands": 2,
    "forced_recoveries": 1,
    "lease_attempt_limit": 1,
    "production_authorized": False,
    "renewer_survival_seconds": 2.0,
    "stage_timeout_seconds": 1_800,
}
ENVIRONMENT_EXPORT_POLICY = "sealed_nul_file_only"
LEASE_ATTEMPT_LIMIT = 1
IMAGE_PULL_TIMEOUT_SECONDS = 300
IMAGE_PULL_RETRY_LIMIT = 1
STAGE_TIMEOUT_SECONDS = 1_800
if (
    STAGE_TIMEOUT_SECONDS >= SUPERVISOR_TIMEOUT_SECONDS
    or WRAPPER_GATE_TIMEOUT_SECONDS
    + ADMISSION_TIMEOUT_SECONDS
    + SUPERVISOR_TIMEOUT_SECONDS
    + TIMEOUT_KILL_GRACE_COUNT * TIMEOUT_KILL_GRACE_SECONDS
    + FINALIZATION_BUDGET_SECONDS
    >= JOB_SECONDS - SIGNAL_LEAD_SECONDS
):
    raise RuntimeError("invalid diagnostic timeout budget")
TLS_EXPECTED_SIZE = 5580
PEM_BLOCK_RE = re.compile(
    rb"-----BEGIN ([A-Z0-9 ]+)-----\s+([A-Za-z0-9+/=\r\n]+?)\s+"
    rb"-----END \1-----"
)


class LaunchError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LaunchInterrupted(BaseException):
    pass


def fail(code: str) -> None:
    raise LaunchError(code)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pem_profile(raw: bytes) -> str:
    labels: list[bytes] = []
    position = 0
    for match in PEM_BLOCK_RE.finditer(raw):
        if raw[position : match.start()].strip(b" \t\r\n"):
            return "invalid"
        compact = b"".join(match.group(2).split())
        try:
            decoded = base64.b64decode(compact, validate=True)
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


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
    )


def directory_identity(descriptor: int) -> dict[str, int]:
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        fail("directory_binding_invalid")
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "owner_uid": info.st_uid,
    }


def portable_directory_identity(
    identity: Mapping[str, object], *, code: str = "directory_binding_invalid"
) -> dict[str, int]:
    if set(identity) != {"device", "inode", "mode", "owner_uid"} or any(
        type(identity.get(name)) is not int for name in ("device", "inode", "mode", "owner_uid")
    ):
        fail(code)
    return {name: int(identity[name]) for name in ("inode", "mode", "owner_uid")}


def portable_identity_string(identity: Mapping[str, object]) -> str:
    if set(identity) != {"inode", "mode", "owner_uid"} or any(
        type(identity.get(name)) is not int for name in ("inode", "mode", "owner_uid")
    ):
        fail("directory_binding_invalid")
    return ":".join(str(identity[name]) for name in ("inode", "mode", "owner_uid"))


def open_anchored_directory(path: Path, *, code: str = "directory_binding_invalid") -> int:
    """Open an absolute directory without following any pathname component."""

    raw_path = os.fspath(path)
    if (
        not path.is_absolute()
        or path.anchor != "/"
        or raw_path != os.path.normpath(raw_path)
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        fail(code)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    chains: list[list[int]] = []
    result = -1
    try:
        for _pass in range(2):
            chain = [os.open("/", flags)]
            chains.append(chain)
            for part in path.parts[1:]:
                chain.append(os.open(part, flags, dir_fd=chain[-1]))
        signatures = [
            [
                (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
                for info in (os.fstat(descriptor) for descriptor in chain)
            ]
            for chain in chains
        ]
        if signatures[0] != signatures[1]:
            fail(code)
        result = os.dup(chains[0][-1])
    except OSError as error:
        raise LaunchError(code) from error
    finally:
        for chain in chains:
            for descriptor in reversed(chain):
                os.close(descriptor)
    return result


def open_bound_directory(
    path: Path,
    expected: Mapping[str, object] | None = None,
    *,
    code: str = "directory_binding_invalid",
) -> int:
    descriptor = open_anchored_directory(path, code=code)
    identity = directory_identity(descriptor)
    if identity["owner_uid"] != os.getuid() or (expected is not None and identity != expected):
        os.close(descriptor)
        fail(code)
    return descriptor


def identity_string(identity: Mapping[str, object]) -> str:
    if set(identity) != {"device", "inode", "mode", "owner_uid"} or any(
        type(identity[key]) is not int for key in identity
    ):
        fail("directory_binding_invalid")
    return ":".join(str(identity[key]) for key in ("device", "inode", "mode", "owner_uid"))


def stable_file_at(
    directory_fd: int,
    name: str,
    *,
    mode: int,
    expected_sha256: str | None = None,
    maximum: int = 2 << 20,
) -> bytes:
    if not name or "/" in name or name in {".", ".."}:
        fail("artifact_invalid")
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise LaunchError("artifact_invalid") from error
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
            fail("artifact_invalid")
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = os.read(descriptor, min(1 << 20, maximum + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after) or len(raw) != before.st_size:
        fail("artifact_changed")
    if expected_sha256 is not None and sha256_bytes(raw) != expected_sha256:
        fail("artifact_hash_mismatch")
    return bytes(raw)


def directory_manifest(
    descriptor: int,
    *,
    expected_owner_uid: int,
    maximum_entries: int = 50_000,
    maximum_bytes: int = 1 << 30,
) -> dict[str, object]:
    entries: list[bytes] = []
    total_bytes = 0
    root_identity = directory_identity(descriptor)
    if root_identity["owner_uid"] != expected_owner_uid:
        fail("site_binding_invalid")

    def visit(current_fd: int, relative_root: str) -> None:
        nonlocal total_bytes
        for name in sorted(os.listdir(current_fd)):
            info = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            if info.st_uid != expected_owner_uid:
                fail("site_binding_invalid")
            relative = f"{relative_root}/{name}".lstrip("/")
            if stat.S_ISDIR(info.st_mode):
                entries.append(f"d\0{relative}\0{stat.S_IMODE(info.st_mode):o}\0{info.st_uid}\n".encode())
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current_fd,
                )
                try:
                    if directory_identity(child_fd) != {
                        "device": info.st_dev,
                        "inode": info.st_ino,
                        "mode": stat.S_IMODE(info.st_mode),
                        "owner_uid": info.st_uid,
                    }:
                        fail("site_binding_invalid")
                    visit(child_fd, relative)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(info.st_mode):
                fail("site_binding_invalid")
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
                    if total_bytes > maximum_bytes:
                        fail("site_binding_invalid")
                after = os.fstat(file_fd)
            finally:
                os.close(file_fd)
            if _identity(before) != _identity(after) or size != before.st_size:
                fail("site_binding_invalid")
            entries.append(
                (
                    f"f\0{relative}\0{stat.S_IMODE(info.st_mode):o}\0{info.st_uid}"
                    f"\0{info.st_size}\0{digest.hexdigest()}\n"
                ).encode()
            )
            if len(entries) > maximum_entries:
                fail("site_binding_invalid")

    visit(descriptor, "")
    if directory_identity(descriptor) != root_identity:
        fail("site_binding_invalid")
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


def stable_file(
    path: Path,
    *,
    mode: int,
    expected_sha256: str | None = None,
    expected_uid: int | None = None,
    maximum: int = 2 << 20,
) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise LaunchError("artifact_invalid") from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != mode
            or before.st_uid != (os.getuid() if expected_uid is None else expected_uid)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > maximum
        ):
            fail("artifact_invalid")
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = os.read(descriptor, min(1 << 20, maximum + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after) or len(raw) != before.st_size:
        fail("artifact_changed")
    if expected_sha256 is not None and sha256_bytes(raw) != expected_sha256:
        fail("artifact_hash_mismatch")
    return bytes(raw)


def same_open_file(first: Path, second: Path) -> bool:
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


def _strict_json(raw: bytes, code: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LaunchError(code) from error
    if not isinstance(value, dict) or canonical_json(value) != raw.rstrip(b"\n"):
        fail(code)
    return value


def _artifact_record(value: object) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        fail("authorization_invalid")
    path = value.get("path")
    digest = value.get("sha256")
    if not isinstance(path, str) or not path.startswith("/") or SHA_RE.fullmatch(str(digest)) is None:
        fail("authorization_invalid")
    return path, str(digest)


def load_authorization(path: Path, file_digest: str) -> tuple[dict[str, Any], bytes, str]:
    if (
        SHA_RE.fullmatch(file_digest) is None
        or not path.is_absolute()
        or path != Path(os.path.normpath(path))
        or path.resolve(strict=True) != path
    ):
        fail("authorization_invalid")
    raw = stable_file(path, mode=0o400, expected_sha256=file_digest, maximum=1 << 20)
    value = _strict_json(raw, "authorization_invalid")
    if set(value) != {
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
    }:
        fail("authorization_invalid")
    body = dict(value)
    embedded = body.pop("authorization_sha256", None)
    if (
        value.get("artifact_type") != "vmvm_owner_lifecycle_diagnostic_authorization_v1"
        or value.get("schema_version") != 1
        or value.get("state") != "approved"
        or embedded != sha256_bytes(canonical_json(body))
    ):
        fail("authorization_invalid")
    assert isinstance(embedded, str)
    return value, raw, embedded


def validate_authorization(
    authorization: Mapping[str, Any],
    *,
    launcher: Path,
    wrapper: Path,
    probe: Path,
    finalizer: Path,
) -> dict[str, str]:
    source = authorization.get("source")
    bundle = authorization.get("bundle")
    runtime = authorization.get("runtime")
    credentials = authorization.get("credentials")
    launch = authorization.get("launch")
    protocol = authorization.get("protocol")
    if not all(isinstance(value, dict) for value in (source, bundle, runtime, credentials, launch, protocol)):
        fail("authorization_invalid")
    assert isinstance(source, dict)
    assert isinstance(bundle, dict)
    assert isinstance(runtime, dict)
    assert isinstance(credentials, dict)
    assert isinstance(launch, dict)
    assert isinstance(protocol, dict)
    if set(source) != {
        "path",
        "portable_root_identity",
        "pydantic_config_revision",
        "renderers_revision",
        "revision",
        "root_identity",
        "tree",
        "verifiers_revision",
        "backend_path",
        "backend_sha256",
    } or any(
        source.get(key) != value
        for key, value in {
            "path": str(SOURCE_ROOT),
            "revision": SOURCE_REVISION,
            "tree": SOURCE_TREE,
            "verifiers_revision": VERIFIERS_REVISION,
            "renderers_revision": RENDERERS_REVISION,
            "pydantic_config_revision": PYDANTIC_CONFIG_REVISION,
            "backend_path": BACKEND_RELATIVE_PATH,
            "backend_sha256": BACKEND_SHA256,
        }.items()
    ):
        fail("authorization_source_invalid")
    source_identity = source.get("root_identity")
    source_portable_identity = source.get("portable_root_identity")
    if (
        not isinstance(source_identity, dict)
        or not isinstance(source_portable_identity, dict)
        or source_portable_identity != portable_directory_identity(source_identity, code="authorization_source_invalid")
    ):
        fail("authorization_source_invalid")
    source_fd = open_bound_directory(SOURCE_ROOT, source_identity, code="authorization_source_invalid")
    os.close(source_fd)
    artifact_root = launcher.parent
    expected_bundle = {
        "launcher": (launcher, 0o500),
        "probe": (probe, 0o500),
        "wrapper": (wrapper, 0o500),
        "finalizer": (finalizer, 0o500),
        "readme": (artifact_root / "README.md", 0o400),
        "tests": (artifact_root / "test_vmvm_owner_lifecycle_v1.py", 0o400),
    }
    bundle_identity = bundle.get("root_identity")
    if not isinstance(bundle_identity, dict):
        fail("authorization_bundle_invalid")
    artifact_fd = open_bound_directory(artifact_root, bundle_identity, code="authorization_bundle_invalid")
    root_status = os.fstat(artifact_fd)
    bundle_portable_identity = bundle.get("portable_root_identity")
    if (
        set(bundle) != set(expected_bundle) | {"portable_root_identity", "root_identity"}
        or not isinstance(bundle_portable_identity, dict)
        or bundle_portable_identity != portable_directory_identity(bundle_identity, code="authorization_bundle_invalid")
        or artifact_root.resolve(strict=True) != artifact_root
        or not stat.S_ISDIR(root_status.st_mode)
        or stat.S_IMODE(root_status.st_mode) != 0o700
        or root_status.st_uid != os.getuid()
        or root_status.st_nlink != 2
        or {entry.name for entry in os.scandir(artifact_fd)} != {path.name for path, _mode in expected_bundle.values()}
    ):
        os.close(artifact_fd)
        fail("authorization_bundle_invalid")
    for label, (expected, mode) in expected_bundle.items():
        path_value, digest = _artifact_record(bundle.get(label))
        if path_value != str(expected.resolve(strict=True)):
            os.close(artifact_fd)
            fail("authorization_bundle_invalid")
        stable_file_at(artifact_fd, expected.name, mode=mode, expected_sha256=digest)
    os.close(artifact_fd)
    if set(runtime) != {"image", "python_name", "site", "uv", "vacli"}:
        fail("authorization_runtime_invalid")
    if runtime.get("image") != "python:3.12-slim" or runtime.get("python_name") != "python3":
        fail("authorization_runtime_invalid")
    site = runtime.get("site")
    if (
        not isinstance(site, dict)
        or set(site) != {"inventory", "path", "portable_root_identity", "root_identity"}
        or site.get("path") != str(X86_SITE)
    ):
        fail("authorization_runtime_invalid")
    site_identity = site.get("root_identity")
    site_portable_identity = site.get("portable_root_identity")
    inventory = site.get("inventory")
    if (
        not isinstance(site_identity, dict)
        or not isinstance(site_portable_identity, dict)
        or site_portable_identity != portable_directory_identity(site_identity, code="authorization_runtime_invalid")
        or not isinstance(inventory, dict)
    ):
        fail("authorization_runtime_invalid")
    site_fd = open_bound_directory(X86_SITE, site_identity, code="authorization_runtime_invalid")
    try:
        if directory_manifest(site_fd, expected_owner_uid=os.getuid()) != inventory:
            fail("authorization_runtime_invalid")
    finally:
        os.close(site_fd)
    for label, expected_path, expected_digest in (("uv", X86_UV, X86_UV_SHA256),):
        path_value, digest = _artifact_record(runtime.get(label))
        if path_value != str(expected_path) or digest != expected_digest:
            fail("authorization_runtime_invalid")
        if expected_path.resolve(strict=True) != expected_path:
            fail("authorization_runtime_invalid")
        stable_file(
            expected_path,
            mode=0o755,
            expected_sha256=expected_digest,
            expected_uid=os.getuid(),
            maximum=128 << 20,
        )
    vacli_record = runtime.get("vacli")
    if not isinstance(vacli_record, dict) or set(vacli_record) != {
        "path",
        "resolved_path",
        "sha256",
    }:
        fail("authorization_runtime_invalid")
    if (
        vacli_record.get("path") != str(VACLI)
        or vacli_record.get("resolved_path") != str(VACLI_RESOLVED)
        or vacli_record.get("sha256") != VACLI_SHA256
        or VACLI.resolve(strict=True) != VACLI_RESOLVED
        or not same_open_file(VACLI, VACLI_RESOLVED)
    ):
        fail("authorization_runtime_invalid")
    vacli_raw = stable_file(
        VACLI,
        mode=0o755,
        expected_sha256=VACLI_SHA256,
        expected_uid=0,
        maximum=512 << 20,
    )
    if (
        stable_file(
            VACLI_RESOLVED,
            mode=0o755,
            expected_sha256=VACLI_SHA256,
            expected_uid=0,
            maximum=512 << 20,
        )
        != vacli_raw
    ):
        fail("authorization_runtime_invalid")
    if set(credentials) != {"tls", "x2p"}:
        fail("authorization_credentials_invalid")
    tls = credentials.get("tls")
    x2p = credentials.get("x2p")
    if not isinstance(tls, dict) or set(tls) != set(TLS_NAMES):
        fail("authorization_credentials_invalid")
    if not isinstance(x2p, dict) or set(x2p) != set(X2P_NAMES):
        fail("authorization_credentials_invalid")
    private: dict[str, str] = {}
    tls_bindings: list[tuple[Path, str, tuple[int, int], str]] = []
    for name in TLS_NAMES:
        path_value, expected_digest = _artifact_record(tls[name])
        path = Path(path_value)
        if path != Path(os.path.normpath(path)) or path.resolve(strict=True) != path:
            fail("authorization_credentials_invalid")
        raw = stable_file(
            path,
            mode=0o500,
            expected_sha256=expected_digest,
            maximum=TLS_EXPECTED_SIZE,
        )
        if len(raw) != TLS_EXPECTED_SIZE:
            fail("authorization_credentials_invalid")
        if os.environ.get(name) != path_value:
            fail("authorization_credentials_invalid")
        private[name] = path_value
        status = path.stat(follow_symlinks=False)
        tls_bindings.append((path, expected_digest, (status.st_dev, status.st_ino), _pem_profile(raw)))
    first, second = tls_bindings
    aliases = (
        first[0] == second[0],
        first[1] == second[1],
        first[2] == second[2],
    )
    if any(aliases) and not (all(aliases) and first[3] == second[3] == "combined"):
        fail("authorization_credentials_invalid")
    for name in X2P_NAMES:
        record = x2p.get(name)
        if not isinstance(record, dict) or set(record) != {"sha256"}:
            fail("authorization_credentials_invalid")
        value = os.environ.get(name)
        if not value or "\0" in value or "\n" in value or len(value.encode()) > 4096:
            fail("authorization_credentials_invalid")
        if SHA_RE.fullmatch(str(record.get("sha256"))) is None or sha256_bytes(value.encode()) != record["sha256"]:
            fail("authorization_credentials_invalid")
        private[name] = value
    expected_launch = {
        "account": "ram",
        "cluster": CLUSTER,
        "completion_receipt": str(COMPLETION_RECEIPT),
        "comment": (
            f"vmvm-owner-life:{NAME_RE.fullmatch(str(launch.get('job_name'))).group(1)}"
            if NAME_RE.fullmatch(str(launch.get("job_name"))) is not None
            else None
        ),
        "cpus": 2,
        "environment_export": ENVIRONMENT_EXPORT_POLICY,
        "job_name": launch.get("job_name"),
        "log_root": str(LOG_ROOT),
        "memory": "8G",
        "nodes": 1,
        "output_parent_identity": launch.get("output_parent_identity"),
        "output_parent_portable_identity": launch.get("output_parent_portable_identity"),
        "output_root": str(OUTPUT_ROOT),
        "partition": "cpu_x86",
        "qos": "cpu_x86_lowest",
        "reservation": str(RESERVATION),
        "scratch_root": str(SCRATCH_ROOT),
        "signal_seconds_before_end": SIGNAL_LEAD_SECONDS,
        "time_limit": JOB_TIME_LIMIT,
        "timeout_budget_seconds": {
            "admission": ADMISSION_TIMEOUT_SECONDS,
            "finalization": FINALIZATION_BUDGET_SECONDS,
            "job": JOB_SECONDS,
            "stage": STAGE_TIMEOUT_SECONDS,
            "supervisor": SUPERVISOR_TIMEOUT_SECONDS,
            "timeout_kill_grace": TIMEOUT_KILL_GRACE_SECONDS,
            "timeout_kill_grace_count": TIMEOUT_KILL_GRACE_COUNT,
            "wrapper_gate": WRAPPER_GATE_TIMEOUT_SECONDS,
        },
    }
    if launch != expected_launch or NAME_RE.fullmatch(str(launch.get("job_name"))) is None:
        fail("authorization_launch_invalid")
    output_parent_identity = launch.get("output_parent_identity")
    output_parent_portable_identity = launch.get("output_parent_portable_identity")
    if (
        not isinstance(output_parent_identity, dict)
        or not isinstance(output_parent_portable_identity, dict)
        or output_parent_portable_identity
        != portable_directory_identity(output_parent_identity, code="authorization_launch_invalid")
    ):
        fail("authorization_launch_invalid")
    output_parent_fd = open_bound_directory(
        OUTPUT_ROOT.parent,
        output_parent_identity,
        code="authorization_launch_invalid",
    )
    os.close(output_parent_fd)
    if protocol != DIAGNOSTIC_PROTOCOL:
        fail("authorization_protocol_invalid")
    private["job_name"] = str(launch["job_name"])
    private["source_identity"] = identity_string(source_identity)
    private["source_portable_identity"] = portable_identity_string(source_portable_identity)
    private["bundle_identity"] = identity_string(bundle_identity)
    private["bundle_portable_identity"] = portable_identity_string(bundle_portable_identity)
    private["site_identity"] = identity_string(site_identity)
    private["site_portable_identity"] = portable_identity_string(site_portable_identity)
    private["site_manifest_sha256"] = str(inventory.get("manifest_sha256"))
    private["site_entry_count"] = str(inventory.get("entry_count"))
    private["site_total_bytes"] = str(inventory.get("total_bytes"))
    private["output_parent_identity"] = identity_string(output_parent_identity)
    private["output_parent_portable_identity"] = portable_identity_string(output_parent_portable_identity)
    return private


def _git(command: Sequence[str], *, pass_fds: Sequence[int] = ()) -> subprocess.CompletedProcess[str]:
    environment = {
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
    }
    return subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            *command,
        ],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        pass_fds=tuple(pass_fds),
    )


def _open_directory_at(root_fd: int, relative: str) -> int:
    descriptor = os.dup(root_fd)
    try:
        for component in relative.split("/"):
            if component in {"", "."}:
                continue
            if component == "..":
                fail("source_binding_invalid")
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                fail("source_binding_invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _tracked_blob_oid(directory_fd: int, relative: str, git_mode: str) -> str:
    components = relative.split("/")
    if (
        not components
        or any(component in {"", ".", ".."} for component in components)
        or git_mode not in {"100644", "100755"}
    ):
        fail("source_binding_invalid")
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
            directory_info = os.fstat(parent_fd)
            if directory_info.st_uid != os.getuid() or stat.S_IMODE(directory_info.st_mode) & 0o022:
                fail("source_binding_invalid")
        file_fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as error:
        raise LaunchError("source_binding_invalid") from error
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
            fail("source_binding_invalid")
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
    if _identity(before) != _identity(after) or size != before.st_size:
        fail("source_binding_invalid")
    return digest.hexdigest()


def _git_records(result: subprocess.CompletedProcess[str]) -> list[str]:
    if result.returncode != 0 or result.stderr or not result.stdout.endswith("\0"):
        fail("source_binding_invalid")
    return result.stdout[:-1].split("\0") if result.stdout else []


def _attest_git_repository(
    repository_fd: int,
    *,
    expected_revision: str,
    pathspecs: Sequence[str] = (),
    expected_gitlinks: Mapping[str, str] | None = None,
) -> None:
    root = f"/proc/self/fd/{repository_fd}"
    inherited = (repository_fd,)
    suffix = ["--", *pathspecs] if pathspecs else []
    revision = _git(["-C", root, "rev-parse", "--verify", "HEAD"], pass_fds=inherited)
    object_format = _git(["-C", root, "rev-parse", "--show-object-format"], pass_fds=inherited)
    if (
        revision.returncode != 0
        or revision.stderr
        or revision.stdout.strip() != expected_revision
        or object_format.returncode != 0
        or object_format.stderr
        or object_format.stdout.strip() != "sha1"
    ):
        fail("source_binding_invalid")
    detached = _git(["-C", root, "symbolic-ref", "-q", "HEAD"], pass_fds=inherited)
    if detached.returncode != 1 or detached.stderr or detached.stdout:
        fail("source_binding_invalid")

    stage_result = _git(
        ["-C", root, "ls-files", "--stage", "-z", *suffix],
        pass_fds=inherited,
    )
    tree_result = _git(
        ["-C", root, "ls-tree", "-r", "-z", "--full-tree", "HEAD", *suffix],
        pass_fds=inherited,
    )
    flag_results = tuple(
        _git(
            ["-C", root, "ls-files", option, "-z", *suffix],
            pass_fds=inherited,
        )
        for option in ("-v", "-f")
    )
    stage_records = _git_records(stage_result)
    tree_records = _git_records(tree_result)
    if not stage_records or not tree_records:
        fail("source_binding_invalid")

    index: dict[str, tuple[str, str]] = {}
    for record in stage_records:
        metadata, separator, path = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != "0" or path in index:
            fail("source_binding_invalid")
        index[path] = (fields[0], fields[1])
    tree: dict[str, tuple[str, str]] = {}
    for record in tree_records:
        metadata, separator, path = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or path in tree:
            fail("source_binding_invalid")
        mode, object_type, object_id = fields
        if object_type != ("commit" if mode == "160000" else "blob"):
            fail("source_binding_invalid")
        tree[path] = (mode, object_id)
    if index != tree:
        fail("source_binding_invalid")

    for flag_result in flag_results:
        flag_records = _git_records(flag_result)
        observed_paths: list[str] = []
        for record in flag_records:
            tag, separator, path = record.partition(" ")
            if not separator or tag != "H":
                fail("source_binding_invalid")
            observed_paths.append(path)
        if observed_paths != list(index):
            fail("source_binding_invalid")

    gitlinks = dict(expected_gitlinks or {})
    for path, (mode, object_id) in index.items():
        if mode == "160000":
            if gitlinks.get(path) != object_id:
                fail("source_binding_invalid")
            continue
        if mode not in {"100644", "100755"}:
            fail("source_binding_invalid")
        if _tracked_blob_oid(repository_fd, path, mode) != object_id:
            fail("source_binding_invalid")
    if set(gitlinks) != {path for path, (mode, _object_id) in index.items() if mode == "160000"}:
        fail("source_binding_invalid")

    repeated = _git(
        ["-C", root, "ls-files", "--stage", "-z", *suffix],
        pass_fds=inherited,
    )
    if repeated.returncode != 0 or repeated.stderr or repeated.stdout != stage_result.stdout:
        fail("source_binding_invalid")


def validate_source(source_fd: int | None = None) -> None:
    owned_source_fd = source_fd is None
    if source_fd is None:
        source_fd = open_bound_directory(SOURCE_ROOT, code="source_binding_invalid")
    source_root = Path(f"/proc/self/fd/{source_fd}")
    inherited = (source_fd,)
    checks = (
        (["-C", str(source_root), "rev-parse", "--verify", "HEAD"], SOURCE_REVISION),
        (["-C", str(source_root), "rev-parse", "HEAD^{tree}"], SOURCE_TREE),
        (
            ["-C", str(source_root), "rev-parse", "HEAD:deps/verifiers"],
            VERIFIERS_REVISION,
        ),
        (
            ["-C", str(source_root), "rev-parse", "HEAD:deps/renderers"],
            RENDERERS_REVISION,
        ),
        (
            ["-C", str(source_root), "rev-parse", "HEAD:deps/pydantic-config"],
            PYDANTIC_CONFIG_REVISION,
        ),
    )
    dependency_fds: list[int] = []
    try:
        for command, expected in checks:
            result = _git(command, pass_fds=inherited)
            if result.returncode != 0 or result.stderr or result.stdout.strip() != expected:
                fail("source_binding_invalid")
        _attest_git_repository(
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
        backend_parent_fd = _open_directory_at(
            source_fd,
            "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli",
        )
        try:
            try:
                stable_file_at(
                    backend_parent_fd,
                    "backend.py",
                    mode=0o444,
                    expected_sha256=BACKEND_SHA256,
                    maximum=2 << 20,
                )
            except LaunchError as error:
                raise LaunchError("source_binding_invalid") from error
        finally:
            os.close(backend_parent_fd)
        for relative, revision in (
            ("deps/verifiers", VERIFIERS_REVISION),
            ("deps/renderers", RENDERERS_REVISION),
            ("deps/pydantic-config", PYDANTIC_CONFIG_REVISION),
        ):
            dependency_fd = _open_directory_at(source_fd, relative)
            dependency_fds.append(dependency_fd)
            _attest_git_repository(
                dependency_fd,
                expected_revision=revision,
            )
        for root_fd in (source_fd, *dependency_fds):
            root = f"/proc/self/fd/{root_fd}"
            status_result = _git(
                ["-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
                pass_fds=(root_fd,),
            )
            ignored = _git(
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
                fail("source_binding_invalid")
    finally:
        for dependency_fd in dependency_fds:
            os.close(dependency_fd)
        if owned_source_fd:
            os.close(source_fd)


def _run(
    command: Sequence[str],
    timeout: float = QUERY_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            env=(
                dict(environment)
                if environment is not None
                else {
                    "HOME": "/nonexistent",
                    "LANG": "C",
                    "LC_ALL": "C",
                    "PATH": "/usr/bin:/bin",
                }
            ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise LaunchError("scheduler_unavailable") from error
    except (OSError, subprocess.SubprocessError) as error:
        raise LaunchError("scheduler_unavailable") from error


def _scheduler_state(value: str | None) -> str:
    return value.split()[0].rstrip("+") if isinstance(value, str) and value else "UNKNOWN"


def _scontrol(job_id: str, deadline: float) -> dict[str, str] | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        result = _run(
            ["/usr/bin/scontrol", "-M", CLUSTER, "show", "job", "-o", job_id],
            timeout=min(QUERY_TIMEOUT_SECONDS, remaining),
        )
    except LaunchError:
        return None
    if result.returncode != 0 or result.stderr or not result.stdout.strip():
        return None
    try:
        fields = shlex.split(result.stdout.strip())
    except ValueError:
        return None
    record: dict[str, str] = {}
    for field in fields:
        key, separator, value = field.partition("=")
        if not separator or not key or key in record:
            return None
        record[key] = value
    return record


def _identity_conflicts(record: Mapping[str, str], job_id: str, job_name: str) -> set[str]:
    expected = {"JobId": job_id, "JobName": job_name, "UserId": OWNER_IDENTITY}
    return {
        key
        for key, expected_value in expected.items()
        if isinstance(record.get(key), str) and record[key] and record[key] != expected_value
    }


def _identity_missing(record: Mapping[str, str], job_id: str, job_name: str) -> set[str]:
    expected = {"JobId": job_id, "JobName": job_name, "UserId": OWNER_IDENTITY}
    return {key for key, expected_value in expected.items() if record.get(key) != expected_value}


def _base_mismatches(record: Mapping[str, str], job_id: str, job_name: str) -> set[str]:
    log_path = str(LOG_ROOT / f"diagnostic_{job_id}.log")
    token = NAME_RE.fullmatch(job_name)
    if token is None:
        return {"JobName"}
    expected = {
        "Account": "ram",
        "Command": "(null)",
        "Comment": f"vmvm-owner-life:{token.group(1)}",
        "Dependency": "(null)",
        "JobId": job_id,
        "JobName": job_name,
        "MinMemoryNode": JOB_MEMORY,
        "NumCPUs": JOB_CPUS,
        "Partition": "cpu_x86",
        "QOS": "cpu_x86_lowest",
        "Requeue": "0",
        "Restarts": "0",
        "StdErr": log_path,
        "StdOut": log_path,
        "TimeLimit": JOB_TIME_LIMIT,
        "UserId": OWNER_IDENTITY,
        "WorkDir": str(SOURCE_ROOT),
    }
    return {field for field, value in expected.items() if record.get(field) != value}


def _queue_rows(job_id: str, deadline: float) -> list[list[str]] | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        result = _run(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--noheader",
                "--jobs",
                job_id,
                "--format=%A|%j|%T|%r",
            ],
            timeout=min(QUERY_TIMEOUT_SECONDS, remaining),
        )
    except LaunchError:
        return None
    if result.returncode != 0 or result.stderr:
        return None
    rows = [line.split("|") for line in result.stdout.splitlines() if line.strip()]
    return rows if all(len(row) == 4 for row in rows) else None


def _pipe_rows(command: Sequence[str], width: int, deadline: float) -> list[list[str]] | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        result = _run(command, timeout=min(QUERY_TIMEOUT_SECONDS, remaining))
    except LaunchError:
        return None
    if result.returncode != 0 or result.stderr:
        return None
    rows = [line.split("|") for line in result.stdout.splitlines() if line.strip()]
    return rows if all(len(row) == width for row in rows) else None


def _snapshot(job_id: str, job_name: str, phase: str, deadline: float) -> tuple[bool, set[str], set[str]]:
    record = _scontrol(job_id, deadline)
    if record is None:
        return False, {"scontrol_unavailable"}, set()
    conflicts = _identity_conflicts(record, job_id, job_name)
    mismatches = _base_mismatches(record, job_id, job_name)
    rows = _queue_rows(job_id, deadline)
    if rows is None:
        mismatches.add("squeue_unavailable")
    else:
        for row in rows:
            if row[0] and row[0] != job_id:
                conflicts.add("JobId")
            if row[1] and row[1] != job_name:
                conflicts.add("JobName")
    if phase == "held":
        expected_held = {
            "JobState": "PENDING",
            "Reason": "JobHeldUser",
            "Priority": "0",
            "StartTime": "Unknown",
            "NumNodes": "1-1",
        }
        mismatches.update(field for field, value in expected_held.items() if record.get(field) != value)
        if record.get("NodeList") not in {None, ""} or record.get("BatchHost") not in {
            None,
            "(null)",
        }:
            mismatches.add("held_allocation")
        if rows != [[job_id, job_name, "PENDING", "JobHeldUser"]]:
            mismatches.add("held_queue")
        allocations = _pipe_rows(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,State,Start,NodeList",
            ],
            5,
            deadline,
        )
        if allocations is None:
            mismatches.add("held_accounting_unavailable")
        else:
            for row in allocations:
                if row[0] and row[0] != job_id:
                    conflicts.add("JobId")
                if row[1] and row[1] != job_name:
                    conflicts.add("JobName")
            if (
                len(allocations) != 1
                or allocations[0][0] != job_id
                or allocations[0][1] != job_name
                or _scheduler_state(allocations[0][2]) != "PENDING"
                or allocations[0][3] not in {"Unknown", "N/A", ""}
                or allocations[0][4] not in {"None assigned", "(null)", "", "N/A"}
            ):
                mismatches.add("held_accounting")
        steps = _pipe_rows(
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
            2,
            deadline,
        )
        if steps is None:
            mismatches.add("held_steps_unavailable")
        elif steps != [[job_id, "PENDING"]]:
            for row in steps:
                if row[0] and row[0] != job_id:
                    conflicts.add("JobId")
            mismatches.add("held_steps")
    elif phase == "activation":
        state = _scheduler_state(record.get("JobState"))
        if state not in ACTIVE_STATES:
            mismatches.add("activation_state")
        if state == "PENDING":
            if record.get("Reason") == "JobHeldUser" or record.get("Priority") == "0":
                mismatches.add("activation_hold")
        elif state in ACTIVE_STATES and (
            record.get("NumNodes") != "1"
            or record.get("NodeList")
            in {
                None,
                "",
                "(null)",
            }
        ):
            mismatches.add("activation_allocation")
        if rows is None or len(rows) != 1:
            mismatches.add("activation_queue")
        allocations = _pipe_rows(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,State",
            ],
            3,
            deadline,
        )
        if allocations is None:
            mismatches.add("activation_accounting_unavailable")
        else:
            for row in allocations:
                if row[0] and row[0] != job_id:
                    conflicts.add("JobId")
                if row[1] and row[1] != job_name:
                    conflicts.add("JobName")
            if (
                len(allocations) != 1
                or allocations[0][:2] != [job_id, job_name]
                or _scheduler_state(allocations[0][2]) != state
            ):
                mismatches.add("activation_accounting")
    else:
        fail("scheduler_state_invalid")
    mismatches.update(_identity_missing(record, job_id, job_name))
    mismatches.update(conflicts)
    return not mismatches, mismatches, conflicts


def poll_phase(job_id: str, job_name: str, phase: str, timeout: int, conflict_latch: set[str]) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout
    consecutive = 0
    polls = 0
    observed: Counter[str] = Counter()
    final: set[str] = set()
    while time.monotonic() < deadline:
        exact, mismatches, conflicts = _snapshot(job_id, job_name, phase, deadline)
        polls += 1
        conflict_latch.update(conflicts)
        final = set(mismatches)
        observed.update(mismatches)
        if conflict_latch:
            break
        consecutive = consecutive + 1 if exact else 0
        if consecutive >= REQUIRED_CONSECUTIVE:
            break
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))
    return {
        "converged": consecutive >= REQUIRED_CONSECUTIVE and not conflict_latch,
        "deadline_seconds": timeout,
        "elapsed_milliseconds": max(0, round((time.monotonic() - started) * 1000)),
        "explicit_conflict_fields": sorted(conflict_latch),
        "final_mismatch_fields": sorted(final),
        "mismatch_occurrences": dict(sorted(observed.items())),
        "polls": polls,
        "required_consecutive": REQUIRED_CONSECUTIVE,
    }


def _write_file(
    directory: Path | int,
    name: str,
    value: Mapping[str, Any],
    mode: int = 0o400,
) -> tuple[bytes, str]:
    payload = canonical_json(value) + b"\n"
    directory_fd = os.dup(directory) if isinstance(directory, int) else open_anchored_directory(directory)
    descriptor = os.open(
        name,
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
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return payload, sha256_bytes(payload)


def _write_environment_at(directory_fd: int, name: str, values: Mapping[str, str]) -> tuple[bytes, str]:
    if any(not key or "=" in key or "\0" in key or "\0" in value for key, value in values.items()):
        fail("environment_invalid")
    payload = b"".join(f"{key}={values[key]}".encode() + b"\0" for key in sorted(values))
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
        dir_fd=directory_fd,
    )
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory_fd)
    return payload, sha256_bytes(payload)


def _write_environment(path: Path, values: Mapping[str, str]) -> tuple[bytes, str]:
    if any(not name or "=" in name or "\0" in name or "\0" in value for name, value in values.items()):
        fail("environment_invalid")
    payload = b"".join(f"{name}={values[name]}".encode() + b"\0" for name in sorted(values))
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _sync_directory(path.parent)
    return payload, sha256_bytes(payload)


def _sync_directory(path: Path | int) -> None:
    descriptor = os.dup(path) if isinstance(path, int) else open_anchored_directory(path)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_absent() -> None:
    for path in (
        OUTPUT_ROOT,
        RESERVATION,
        COMPLETION_RECEIPT,
        LOG_ROOT,
        SCRATCH_ROOT,
    ):
        if path.exists() or path.is_symlink():
            fail("namespace_not_fresh")


def _scheduler_matches(job_name: str, start_date: str) -> set[str]:
    if NAME_RE.fullmatch(job_name) is None or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", start_date) is None:
        fail("scheduler_lookup_invalid")
    commands = (
        [
            "/usr/bin/squeue",
            "-M",
            CLUSTER,
            "--noheader",
            f"--name={job_name}",
            f"--user={OWNER}",
            "--format=%A|%j",
        ],
        [
            "/usr/bin/sacct",
            "-M",
            CLUSTER,
            "--noheader",
            "--parsable2",
            "--allocations",
            f"--name={job_name}",
            f"--user={OWNER}",
            f"--starttime={start_date}",
            "--format=JobIDRaw,JobName",
        ],
    )
    matches: set[str] = set()
    for command in commands:
        result = _run(command)
        if result.returncode != 0 or result.stderr:
            fail("scheduler_lookup_unavailable")
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            fields = [field.strip() for field in line.split("|")]
            if len(fields) != 2 or JOB_RE.fullmatch(fields[0]) is None or fields[1] != job_name:
                fail("scheduler_lookup_invalid")
            matches.add(fields[0])
    if len(matches) > 1:
        fail("scheduler_submission_not_unique")
    return matches


def _name_absent(job_name: str, start_date: str) -> bool:
    return not _scheduler_matches(job_name, start_date)


def _lookup_submission(job_name: str, start_date: str, *, timeout: float) -> tuple[str, str | None]:
    deadline = time.monotonic() + timeout
    successful_empty = 0
    while time.monotonic() < deadline:
        try:
            matches = _scheduler_matches(job_name, start_date)
        except LaunchError:
            matches = None
        if matches:
            return "unique", next(iter(matches))
        if matches == set():
            successful_empty += 1
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(SUBMISSION_LOOKUP_INTERVAL_SECONDS, remaining))
    return ("zero_proved", None) if successful_empty >= 2 else ("unknown", None)


def _submission_environment(
    *,
    private: Mapping[str, str],
    authorization: Path,
    authorization_file_sha256: str,
    authorization_sha256: str,
    launcher_sha256: str,
    wrapper_sha256: str,
    wrapper_size: int,
    probe_sha256: str,
    finalizer_sha256: str,
    reservation_identity: Mapping[str, object],
) -> dict[str, str]:
    values = {
        "DIAG_ACTIVATION_PERMIT": str(RESERVATION / "activation_permit.json"),
        "DIAG_AUTHORIZATION": str(authorization),
        "DIAG_AUTHORIZATION_FILE_SHA256": authorization_file_sha256,
        "DIAG_AUTHORIZATION_SHA256": authorization_sha256,
        "DIAG_BUNDLE_PORTABLE_IDENTITY": private["bundle_portable_identity"],
        "DIAG_BUNDLE_ROOT": str(Path(__file__).resolve(strict=True).parent),
        "DIAG_BUNDLE_IDENTITY": private["bundle_identity"],
        "DIAG_COMPLETION_RECEIPT": str(COMPLETION_RECEIPT),
        "DIAG_FINALIZER_PATH": str(Path(__file__).resolve(strict=True).parent / "finalize_vmvm_owner_lifecycle_v1.py"),
        "DIAG_FINALIZER_SHA256": finalizer_sha256,
        "DIAG_JOB_AUTHORIZATION": str(RESERVATION / "job_authorization.json"),
        "DIAG_JOB_NAME": private["job_name"],
        "DIAG_LAUNCHER_PATH": str(Path(__file__).resolve(strict=True)),
        "DIAG_LAUNCHER_SHA256": launcher_sha256,
        "DIAG_DIRECTORY_IDENTITY_POLICY": DIRECTORY_IDENTITY_POLICY_NAME,
        "DIAG_OUTPUT_ROOT": str(OUTPUT_ROOT),
        "DIAG_OUTPUT_PARENT_IDENTITY": private["output_parent_identity"],
        "DIAG_OUTPUT_PARENT_PORTABLE_IDENTITY": private["output_parent_portable_identity"],
        "DIAG_PROBE_PATH": str(Path(__file__).resolve(strict=True).parent / "probe_vmvm_owner_lifecycle_v1.py"),
        "DIAG_PROBE_SHA256": probe_sha256,
        "DIAG_RESERVATION": str(RESERVATION),
        "DIAG_RESERVATION_IDENTITY": identity_string(reservation_identity),
        "DIAG_RESERVATION_PORTABLE_IDENTITY": portable_identity_string(
            portable_directory_identity(reservation_identity)
        ),
        "DIAG_SCRATCH_ROOT": str(SCRATCH_ROOT),
        "DIAG_SOURCE_REVISION": SOURCE_REVISION,
        "DIAG_SOURCE_ROOT": str(SOURCE_ROOT),
        "DIAG_SOURCE_IDENTITY": private["source_identity"],
        "DIAG_SOURCE_PORTABLE_IDENTITY": private["source_portable_identity"],
        "DIAG_SOURCE_TREE": SOURCE_TREE,
        "DIAG_SUBMISSION_RECEIPT": str(RESERVATION / "submission_receipt.json"),
        "DIAG_BACKEND_SHA256": BACKEND_SHA256,
        "DIAG_WRAPPER_GATE_TIMEOUT_SECONDS": str(WRAPPER_GATE_TIMEOUT_SECONDS),
        "DIAG_WRAPPER_PATH": str(Path(__file__).resolve(strict=True).parent / "run_vmvm_owner_lifecycle_v1.sbatch"),
        "DIAG_WRAPPER_SHA256": wrapper_sha256,
        "DIAG_WRAPPER_SIZE": str(wrapper_size),
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": OWNER,
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_BIN_X86_64": "python3",
        "PYTHON_SITE_X86_64": str(X86_SITE),
        "PYTHON_SITE_X86_64_ENTRY_COUNT": private["site_entry_count"],
        "PYTHON_SITE_X86_64_IDENTITY": private["site_identity"],
        "PYTHON_SITE_X86_64_PORTABLE_IDENTITY": private["site_portable_identity"],
        "PYTHON_SITE_X86_64_MANIFEST_SHA256": private["site_manifest_sha256"],
        "PYTHON_SITE_X86_64_TOTAL_BYTES": private["site_total_bytes"],
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
        **{name: private[name] for name in (*TLS_NAMES, *X2P_NAMES)},
    }
    return values


def _sbatch_command(job_name: str, environment_path: Path) -> list[str]:
    log = LOG_ROOT / "diagnostic_%j.log"
    token = NAME_RE.fullmatch(job_name)
    if token is None:
        fail("job_name_invalid")
    return [
        "/usr/bin/sbatch",
        "-M",
        CLUSTER,
        "--parsable",
        "--hold",
        f"--job-name={job_name}",
        f"--comment=vmvm-owner-life:{token.group(1)}",
        f"--chdir={SOURCE_ROOT}",
        f"--time={JOB_TIME_LIMIT}",
        "--nodes=1",
        "--ntasks=1",
        f"--cpus-per-task={JOB_CPUS}",
        f"--mem={JOB_MEMORY}",
        "--partition=cpu_x86",
        "--qos=cpu_x86_lowest",
        "--account=ram",
        "--no-requeue",
        f"--signal=B:TERM@{SIGNAL_LEAD_SECONDS}",
        f"--output={log}",
        f"--error={log}",
        "--open-mode=truncate",
        f"--export-file={environment_path}",
    ]


def _reap_process_group(process: subprocess.Popen[bytes]) -> bool:
    for process_signal in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is not None:
            return True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, process_signal)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            continue
    return process.poll() is not None


def _invoke_sbatch(
    command: Sequence[str],
    wrapper_raw: bytes,
    *,
    pass_fds: Sequence[int] = (),
) -> tuple[str, int, str]:
    outcome = "completed"
    with (
        tempfile.TemporaryFile() as stdin_file,
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        stdin_file.write(wrapper_raw)
        stdin_file.seek(0)
        try:
            process = subprocess.Popen(
                list(command),
                stdin=stdin_file,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=SOURCE_ROOT,
                env={
                    "HOME": "/nonexistent",
                    "LANG": "C",
                    "LC_ALL": "C",
                    "PATH": "/usr/bin:/bin",
                },
                start_new_session=True,
                pass_fds=tuple(pass_fds),
            )
        except OSError:
            return "exec_error", 127, ""
        try:
            try:
                return_code = process.wait(timeout=SUBMIT_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                outcome = "timeout"
                return_code = 124
                if not _reap_process_group(process):
                    outcome = "cleanup_failed"
        except BaseException:
            _reap_process_group(process)
            raise
        stdout_file.flush()
        stderr_file.flush()
        if os.fstat(stdout_file.fileno()).st_size > 1 << 20 or os.fstat(stderr_file.fileno()).st_size > 1 << 20:
            return "malformed", return_code, ""
        if outcome == "completed" and os.fstat(stderr_file.fileno()).st_size:
            outcome = "stderr"
        stdout_file.seek(0)
        try:
            stdout = stdout_file.read().decode("ascii")
        except UnicodeDecodeError:
            return "malformed", return_code, ""
    return outcome, return_code, stdout


def _parse_job_id(stdout: str) -> str:
    lines = stdout.splitlines()
    if len(lines) != 1:
        fail("submission_result_invalid")
    job_id, separator, cluster = lines[0].partition(";")
    if JOB_RE.fullmatch(job_id) is None or (separator and cluster != CLUSTER):
        fail("submission_result_invalid")
    return job_id


def _resolve_submission(
    *,
    direct_candidate: str | None,
    outcome: str,
    job_name: str,
    start_date: str,
) -> tuple[str | None, str | None]:
    lookup_state, recovered = _lookup_submission(job_name, start_date, timeout=SUBMISSION_LOOKUP_TIMEOUT_SECONDS)
    if lookup_state == "unique" and recovered is not None:
        if direct_candidate is not None and direct_candidate != recovered:
            fail("submission_identity_ambiguous")
        provenance = "sbatch_and_name" if direct_candidate else "name_lookup"
        return recovered, provenance
    if direct_candidate is not None:
        fail("submission_visibility_ambiguous")
    if outcome == "cleanup_failed":
        fail("sbatch_cleanup_failed")
    if lookup_state == "zero_proved":
        return None, None
    fail("submission_outcome_unknown")


def _identity_probe(job_id: str, job_name: str, deadline: float) -> tuple[str, set[str]]:
    record = _scontrol(job_id, deadline)
    if record is None:
        return "unavailable_or_incomplete", set()
    conflicts = _identity_conflicts(record, job_id, job_name)
    if conflicts:
        return "explicit_identity_conflict", conflicts
    if _identity_missing(record, job_id, job_name):
        return "unavailable_or_incomplete", set()
    return "converged", set()


def _terminal_snapshot(
    job_id: str, job_name: str, deadline: float
) -> tuple[str, set[str], tuple[tuple[str, str], ...]]:
    conflicts: set[str] = set()
    incomplete = False
    record = _scontrol(job_id, deadline)
    if record is None:
        incomplete = True
    else:
        conflicts.update(_identity_conflicts(record, job_id, job_name))
        incomplete = bool(_identity_missing(record, job_id, job_name))
    queue = _queue_rows(job_id, deadline)
    if queue is None:
        incomplete = True
    else:
        for row in queue:
            if row[0] and row[0] != job_id:
                conflicts.add("JobId")
            if row[1] and row[1] != job_name:
                conflicts.add("JobName")
    allocation = _pipe_rows(
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
        4,
        deadline,
    )
    steps = _pipe_rows(
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
        2,
        deadline,
    )
    if allocation is None or steps is None:
        incomplete = True
        allocation = [] if allocation is None else allocation
        steps = [] if steps is None else steps
    for row in allocation:
        if row[0] and row[0] != job_id:
            conflicts.add("JobId")
        if row[1] and row[1] != job_name:
            conflicts.add("JobName")
        if row[2] and row[2] != OWNER:
            conflicts.add("UserId")
    for row in steps:
        if row[0] and row[0] != job_id and not row[0].startswith(f"{job_id}."):
            conflicts.add("JobId")
    if conflicts:
        return "explicit_identity_conflict", conflicts, ()
    signature = tuple((row[0], _scheduler_state(row[1])) for row in steps)
    terminal = (
        not incomplete
        and queue == []
        and len(allocation) == 1
        and allocation[0][:3] == [job_id, job_name, OWNER]
        and _scheduler_state(allocation[0][3]) in TERMINAL_STATES
        and bool(steps)
        and all(_scheduler_state(row[1]) in TERMINAL_STATES for row in steps)
    )
    if terminal:
        return "terminal", set(), signature
    return ("unavailable_or_incomplete" if incomplete else "active"), set(), signature


def cancel_and_prove(
    job_id: str,
    job_name: str,
    conflict_latch: set[str],
    *,
    candidate_provenance: str,
) -> dict[str, Any]:
    trusted_direct = candidate_provenance in {"sbatch_stdout", "sbatch_and_name"}
    identity_deadline = time.monotonic() + 180
    identity_polls = 0
    identity_status = "unavailable_or_incomplete"
    while time.monotonic() < identity_deadline and not conflict_latch:
        identity_status, conflicts = _identity_probe(job_id, job_name, identity_deadline)
        identity_polls += 1
        conflict_latch.update(conflicts)
        if identity_status in {"converged", "explicit_identity_conflict"}:
            break
        remaining = identity_deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))
    if conflict_latch:
        return {
            "candidate_provenance": candidate_provenance,
            "control_attempted": False,
            "control_outcome": "not_authorized",
            "explicit_conflict_fields": sorted(conflict_latch),
            "identity_polls": identity_polls,
            "identity_status": "explicit_identity_conflict",
            "polls": 0,
            "terminal_proved": False,
        }
    precontrol_status, conflicts, _ = _terminal_snapshot(job_id, job_name, time.monotonic() + QUERY_TIMEOUT_SECONDS * 4)
    conflict_latch.update(conflicts)
    attempted = False
    control_outcome = "not_authorized"
    if not conflict_latch and precontrol_status != "terminal" and (identity_status == "converged" or trusted_direct):
        attempted = True
        try:
            result = _run(["/usr/bin/scancel", "-M", CLUSTER, job_id])
            control_outcome = "completed" if result.returncode == 0 else "nonzero"
        except LaunchError:
            control_outcome = "unknown"
    elif not conflict_latch and precontrol_status == "terminal":
        control_outcome = "not_needed"
    terminal_deadline = time.monotonic() + 300
    stable = 0
    polls = 0
    previous_signature: tuple[tuple[str, str], ...] | None = None
    while time.monotonic() < terminal_deadline and not conflict_latch:
        status, conflicts, signature = _terminal_snapshot(job_id, job_name, terminal_deadline)
        polls += 1
        conflict_latch.update(conflicts)
        if status == "terminal" and signature == previous_signature:
            stable += 1
        elif status == "terminal":
            stable = 1
        else:
            stable = 0
        previous_signature = signature if status == "terminal" else None
        if stable >= REQUIRED_CONSECUTIVE:
            break
        remaining = terminal_deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))
    return {
        "candidate_provenance": candidate_provenance,
        "control_attempted": attempted,
        "control_outcome": control_outcome,
        "explicit_conflict_fields": sorted(conflict_latch),
        "identity_polls": identity_polls,
        "identity_status": ("explicit_identity_conflict" if conflict_latch else identity_status),
        "polls": polls,
        "terminal_proved": stable >= REQUIRED_CONSECUTIVE and not conflict_latch,
    }


def _install_signal_handlers() -> None:
    def interrupted(signum: int, frame: object) -> None:
        del signum, frame
        raise LaunchInterrupted

    for value in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(value, interrupted)


def _validate_tmux_ancestry() -> None:
    tmux_value = os.environ.get("TMUX", "")
    pane_value = os.environ.get("TMUX_PANE", "")
    if not tmux_value or re.fullmatch(r"%[0-9]+", pane_value) is None:
        fail("tmux_ancestry_invalid")
    result = _run(
        [
            "/usr/bin/tmux",
            "display-message",
            "-p",
            "-t",
            pane_value,
            "#{session_name}:#{window_name}.#{pane_index}|#{pane_id}|#{pane_pid}",
        ],
        timeout=10,
        environment={
            "HOME": "/storage/home/tianhaowu",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "TMUX": tmux_value,
            "TMUX_PANE": pane_value,
        },
    )
    fields = result.stdout.strip().split("|")
    if (
        result.returncode != 0
        or result.stderr
        or len(fields) != 3
        or fields[0] != CANONICAL_TMUX_TARGET
        or fields[1] != pane_value
        or not fields[2].isdigit()
    ):
        fail("tmux_ancestry_invalid")
    pane_pid = int(fields[2])
    current = os.getppid()
    visited: set[int] = set()
    for _ in range(64):
        if current == pane_pid:
            return
        if current <= 1 or current in visited:
            break
        visited.add(current)
        try:
            lines = Path(f"/proc/{current}/status").read_text(encoding="utf-8").splitlines()
            parent = next(line for line in lines if line.startswith("PPid:"))
            current = int(parent.split()[1])
        except (OSError, UnicodeError, StopIteration, ValueError, IndexError) as error:
            raise LaunchError("tmux_ancestry_invalid") from error
    fail("tmux_ancestry_invalid")


def _authorization_summary(
    authorization_file_sha256: str,
    authorization_sha256: str,
    job_name: str,
    job_id: str,
) -> dict[str, Any]:
    return {
        "artifact_type": "vmvm_owner_lifecycle_job_authorization_v1",
        "authorization_file_sha256": authorization_file_sha256,
        "authorization_sha256": authorization_sha256,
        "job": {"cluster": CLUSTER, "job_id": job_id, "job_name": job_name},
        "production_authorized": False,
        "state": "held_verified",
    }


def _publish_failure(
    code: str,
    job_id: str | None,
    cancellation: Mapping[str, Any] | None,
    reservation_fd: int | None = None,
) -> None:
    owned_fd = reservation_fd is None
    try:
        directory_fd = open_bound_directory(RESERVATION) if reservation_fd is None else reservation_fd
    except LaunchError:
        return
    names = {entry.name for entry in os.scandir(directory_fd)}
    if {"submission_receipt.json", "activation_permit.json"} & names or directory_identity(directory_fd)[
        "mode"
    ] != 0o700:
        if owned_fd:
            os.close(directory_fd)
        return
    body = {
        "artifact_type": "vmvm_owner_lifecycle_submission_failure_v1",
        "cancellation": cancellation,
        "code": code,
        "known_job": job_id is not None,
        "production_authorized": False,
        "state": "failed",
    }
    with contextlib.suppress(FileExistsError, OSError):
        _write_file(directory_fd, "submission_failure.json", body)
        os.fchmod(directory_fd, 0o500)
        _sync_directory(directory_fd)
        _sync_directory(RESERVATION.parent)
    if owned_fd:
        os.close(directory_fd)


def _publish_success(
    *,
    receipt: Mapping[str, Any],
    permit_body: Mapping[str, Any],
    commit_state: dict[str, bool],
    reservation_fd: int | None = None,
) -> str:
    if commit_state != {"committed": False}:
        fail("success_commit_state_invalid")
    owned_fd = reservation_fd is None
    directory_fd = open_bound_directory(RESERVATION) if reservation_fd is None else reservation_fd
    receipt_name = "submission_receipt.json"
    permit_name = "activation_permit.json"
    failure_name = "submission_failure.json"
    if {receipt_name, permit_name, failure_name} & {entry.name for entry in os.scandir(directory_fd)}:
        fail("terminal_receipt_conflict")
    expected_before = {
        ".writer.lock",
        "job_authorization.json",
        "launch_intent.json",
        "slurm_environment.bin",
    }
    if (
        directory_identity(directory_fd)["mode"] != 0o700
        or {entry.name for entry in os.scandir(directory_fd)} != expected_before
    ):
        fail("success_reservation_invalid")
    blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    receipt_written = False
    permit_written = False
    try:
        _, receipt_sha = _write_file(directory_fd, receipt_name, receipt)
        receipt_written = True
        final_permit = dict(permit_body)
        final_permit["submission_receipt_sha256"] = receipt_sha
        _write_file(directory_fd, permit_name, final_permit)
        permit_written = True
        expected_after = expected_before | {receipt_name, permit_name}
        if {entry.name for entry in os.scandir(directory_fd)} != expected_after:
            fail("success_reservation_invalid")
        _sync_directory(directory_fd)
        os.fchmod(directory_fd, 0o500)
        commit_state["committed"] = True
        _sync_directory(directory_fd)
        _sync_directory(RESERVATION.parent)
        return receipt_sha
    except BaseException:
        if not commit_state["committed"]:
            for name, written in (
                (permit_name, permit_written),
                (receipt_name, receipt_written),
            ):
                if written:
                    with contextlib.suppress(OSError):
                        os.unlink(name, dir_fd=directory_fd)
            with contextlib.suppress(OSError):
                _sync_directory(directory_fd)
        raise
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if owned_fd:
            os.close(directory_fd)


def launch(authorization_path: Path, authorization_file_sha256: str) -> dict[str, Any]:
    artifact_root = Path(__file__).resolve(strict=True).parent
    launcher = artifact_root / "launch_vmvm_owner_lifecycle_v1.py"
    wrapper = artifact_root / "run_vmvm_owner_lifecycle_v1.sbatch"
    probe = artifact_root / "probe_vmvm_owner_lifecycle_v1.py"
    finalizer = artifact_root / "finalize_vmvm_owner_lifecycle_v1.py"
    authorization, authorization_raw, authorization_sha256 = load_authorization(
        authorization_path, authorization_file_sha256
    )
    private = validate_authorization(
        authorization,
        launcher=launcher,
        wrapper=wrapper,
        probe=probe,
        finalizer=finalizer,
    )
    validate_source()
    _ensure_absent()
    job_name = private["job_name"]
    start_date = datetime.now(UTC).date().isoformat()
    if not _name_absent(job_name, start_date):
        fail("scheduler_name_not_fresh")
    lock_descriptor = -1
    reservation_fd = -1
    bundle_fd = -1
    source_fd = -1
    site_fd = -1
    output_parent_fd = -1
    try:
        bundle_fd = open_bound_directory(artifact_root, authorization["bundle"]["root_identity"])
        source_fd = open_bound_directory(SOURCE_ROOT, authorization["source"]["root_identity"])
        site_fd = open_bound_directory(X86_SITE, authorization["runtime"]["site"]["root_identity"])
        output_parent_fd = open_bound_directory(OUTPUT_ROOT.parent, authorization["launch"]["output_parent_identity"])
        os.mkdir(RESERVATION.name, 0o700, dir_fd=output_parent_fd)
        reservation_fd = os.open(
            RESERVATION.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=output_parent_fd,
        )
        os.mkdir(LOG_ROOT, 0o700)
        _sync_directory(output_parent_fd)
        _sync_directory(LOG_ROOT.parent)
        lock_descriptor = os.open(
            ".writer.lock",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=reservation_fd,
        )
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.fsync(lock_descriptor)
        _sync_directory(reservation_fd)
        launcher_raw = stable_file_at(bundle_fd, launcher.name, mode=0o500)
        wrapper_raw = stable_file_at(bundle_fd, wrapper.name, mode=0o500)
        probe_raw = stable_file_at(bundle_fd, probe.name, mode=0o500)
        finalizer_raw = stable_file_at(bundle_fd, finalizer.name, mode=0o500)
        admitted_reservation_identity = directory_identity(reservation_fd)
        admitted_reservation_identity["mode"] = 0o500
        environment = _submission_environment(
            private=private,
            authorization=authorization_path,
            authorization_file_sha256=authorization_file_sha256,
            authorization_sha256=authorization_sha256,
            launcher_sha256=sha256_bytes(launcher_raw),
            wrapper_sha256=sha256_bytes(wrapper_raw),
            wrapper_size=len(wrapper_raw),
            probe_sha256=sha256_bytes(probe_raw),
            finalizer_sha256=sha256_bytes(finalizer_raw),
            reservation_identity=admitted_reservation_identity,
        )
        environment_path = Path(f"/proc/self/fd/{reservation_fd}/slurm_environment.bin")
        environment_raw, environment_sha = _write_environment_at(reservation_fd, "slurm_environment.bin", environment)
        intent = {
            "artifact_type": "vmvm_owner_lifecycle_launch_intent_v1",
            "authorization_file_sha256": authorization_file_sha256,
            "authorization_sha256": authorization_sha256,
            "bundle_sha256": {
                "launcher": sha256_bytes(launcher_raw),
                "probe": sha256_bytes(probe_raw),
                "wrapper": sha256_bytes(wrapper_raw),
                "finalizer": sha256_bytes(finalizer_raw),
            },
            "environment_sha256": environment_sha,
            "job_name": job_name,
            "production_authorized": False,
            "state": "reserved",
        }
        _write_file(reservation_fd, "launch_intent.json", intent)
    except BaseException as error:
        code = error.code if isinstance(error, LaunchError) else "reservation_failed"
        _publish_failure(code, None, None, reservation_fd if reservation_fd >= 0 else None)
        for descriptor in (
            lock_descriptor,
            reservation_fd,
            bundle_fd,
            source_fd,
            site_fd,
            output_parent_fd,
        ):
            if descriptor >= 0:
                os.close(descriptor)
        raise
    job_id: str | None = None
    candidate_provenance: str | None = None
    conflict_latch: set[str] = set()
    commit_state = {"committed": False}
    try:
        stable_file(
            authorization_path,
            mode=0o400,
            expected_sha256=authorization_file_sha256,
        )
        stable_file_at(bundle_fd, launcher.name, mode=0o500, expected_sha256=sha256_bytes(launcher_raw))
        stable_file_at(bundle_fd, wrapper.name, mode=0o500, expected_sha256=sha256_bytes(wrapper_raw))
        stable_file_at(bundle_fd, probe.name, mode=0o500, expected_sha256=sha256_bytes(probe_raw))
        stable_file_at(
            bundle_fd,
            finalizer.name,
            mode=0o500,
            expected_sha256=sha256_bytes(finalizer_raw),
        )
        if (
            stable_file_at(
                reservation_fd,
                "slurm_environment.bin",
                mode=0o400,
                expected_sha256=environment_sha,
                maximum=1 << 20,
            )
            != environment_raw
        ):
            fail("environment_changed")
        private_again = validate_authorization(
            authorization,
            launcher=launcher,
            wrapper=wrapper,
            probe=probe,
            finalizer=finalizer,
        )
        if private_again != private:
            fail("authorization_changed")
        validate_source(source_fd)
        if directory_manifest(site_fd, expected_owner_uid=os.getuid()) != authorization["runtime"]["site"]["inventory"]:
            fail("site_binding_invalid")
        if (
            not _name_absent(job_name, start_date)
            or OUTPUT_ROOT.exists()
            or OUTPUT_ROOT.is_symlink()
            or SCRATCH_ROOT.exists()
            or SCRATCH_ROOT.is_symlink()
            or COMPLETION_RECEIPT.exists()
            or COMPLETION_RECEIPT.is_symlink()
            or directory_identity(reservation_fd)["mode"] != 0o700
        ):
            fail("final_submission_gate_changed")
        blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        try:
            outcome, return_code, stdout = _invoke_sbatch(
                _sbatch_command(job_name, environment_path),
                wrapper_raw,
                pass_fds=(reservation_fd,),
            )
            direct_candidate: str | None = None
            if outcome == "completed" and return_code == 0:
                try:
                    direct_candidate = _parse_job_id(stdout.strip())
                except LaunchError:
                    outcome = "malformed"
            elif outcome == "completed":
                outcome = "nonzero"
            if direct_candidate is not None:
                job_id = direct_candidate
                candidate_provenance = "sbatch_stdout"
            resolved, resolved_provenance = _resolve_submission(
                direct_candidate=direct_candidate,
                outcome=outcome,
                job_name=job_name,
                start_date=start_date,
            )
            if resolved is None or resolved_provenance is None:
                fail("submission_failed")
            job_id = resolved
            candidate_provenance = resolved_provenance
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        held = poll_phase(job_id, job_name, "held", HELD_TIMEOUT_SECONDS, conflict_latch)
        if not held["converged"]:
            fail("held_identity_invalid")
        exact_before, before_mismatches, before_conflicts = _snapshot(
            job_id, job_name, "held", time.monotonic() + QUERY_TIMEOUT_SECONDS * 4
        )
        conflict_latch.update(before_conflicts)
        held["pre_authorization_mismatch_fields"] = sorted(before_mismatches)
        if not exact_before or conflict_latch:
            fail("held_state_lost_before_authorization")
        authorization_body = _authorization_summary(authorization_file_sha256, authorization_sha256, job_name, job_id)
        authorization_payload, job_authorization_sha = _write_file(
            reservation_fd, "job_authorization.json", authorization_body
        )
        del authorization_payload
        exact_after, after_mismatches, after_conflicts = _snapshot(
            job_id, job_name, "held", time.monotonic() + QUERY_TIMEOUT_SECONDS * 4
        )
        conflict_latch.update(after_conflicts)
        held["post_authorization_mismatch_fields"] = sorted(after_mismatches)
        if not exact_after or conflict_latch:
            fail("held_state_lost_after_authorization")
        try:
            release = _run(["/usr/bin/scontrol", "-M", CLUSTER, "release", job_id])
            release_outcome = "completed" if release.returncode == 0 and not release.stderr else "nonzero"
        except LaunchError:
            release_outcome = "unknown"
        activation = poll_phase(job_id, job_name, "activation", ACTIVATION_TIMEOUT_SECONDS, conflict_latch)
        if not activation["converged"]:
            fail("activation_identity_invalid")
        receipt = {
            "artifact_type": "vmvm_owner_lifecycle_submission_receipt_v1",
            "activation": activation,
            "authorization_file_sha256": authorization_file_sha256,
            "authorization_sha256": authorization_sha256,
            "environment_sha256": environment_sha,
            "held": held,
            "job": {"cluster": CLUSTER, "job_id": job_id, "job_name": job_name},
            "job_authorization_sha256": job_authorization_sha,
            "production_authorized": False,
            "release_outcome": release_outcome,
            "release_attempts": 1,
            "state": "submitted",
            "submission_attempts": 1,
        }
        permit = {
            "artifact_type": "vmvm_owner_lifecycle_activation_permit_v1",
            "authorization_file_sha256": authorization_file_sha256,
            "authorization_sha256": authorization_sha256,
            "environment_sha256": environment_sha,
            "job_authorization_sha256": job_authorization_sha,
            "production_authorized": False,
            "state": "activated",
        }
        _publish_success(
            receipt=receipt,
            permit_body=permit,
            commit_state=commit_state,
            reservation_fd=reservation_fd,
        )
        return {"state": "submitted", "submission_attempts": 1}
    except BaseException as error:
        if commit_state["committed"]:
            return {"state": "submitted", "submission_attempts": 1}
        code = error.code if isinstance(error, LaunchError) else "launcher_failed"
        blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        try:
            cancellation = (
                cancel_and_prove(
                    job_id,
                    job_name,
                    conflict_latch,
                    candidate_provenance=candidate_provenance,
                )
                if job_id is not None and candidate_provenance is not None
                else None
            )
            if cancellation is not None and not cancellation["terminal_proved"]:
                code = "cancellation_unconfirmed"
            _publish_failure(code, job_id, cancellation, reservation_fd)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if isinstance(error, (KeyboardInterrupt, LaunchInterrupted)):
            raise
        raise LaunchError(code) from error
    finally:
        for descriptor in (
            lock_descriptor,
            reservation_fd,
            bundle_fd,
            source_fd,
            site_fd,
            output_parent_fd,
        ):
            if descriptor >= 0:
                os.close(descriptor)
        del authorization_raw


def _validate_outer_environment() -> None:
    allowed = {
        "APPROVED_DIAGNOSTIC_LAUNCHER_SHA256",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "TMUX",
        "TMUX_PANE",
        "TZ",
        "USER",
        *TLS_NAMES,
        *X2P_NAMES,
    }
    if set(os.environ) != allowed:
        fail("outer_environment_invalid")
    if (
        os.environ.get("HOME") != "/storage/home/tianhaowu"
        or os.environ.get("LANG") != "C"
        or os.environ.get("LC_ALL") != "C"
        or os.environ.get("LOGNAME") != OWNER
        or os.environ.get("PATH") != "/usr/bin:/bin"
        or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1"
        or os.environ.get("TZ") != "UTC"
        or os.environ.get("USER") != OWNER
        or os.getuid() != OWNER_UID
        or os.geteuid() != OWNER_UID
        or Path.cwd() != Path("/storage/home/tianhaowu")
        or Path(sys.executable).resolve(strict=True) != SYSTEM_PYTHON
    ):
        fail("outer_environment_invalid")
    launcher = Path(__file__).resolve(strict=True)
    approved = os.environ.get("APPROVED_DIAGNOSTIC_LAUNCHER_SHA256", "")
    if SHA_RE.fullmatch(approved) is None or Path(sys.argv[0]).resolve(strict=True) != launcher:
        fail("outer_environment_invalid")
    stable_file(launcher, mode=0o500, expected_sha256=approved)
    stable_file(
        SYSTEM_PYTHON,
        mode=0o755,
        expected_sha256=SYSTEM_PYTHON_SHA256,
        expected_uid=0,
        maximum=64 << 20,
    )
    stable_file(
        Path("/usr/bin/tmux"),
        mode=0o755,
        expected_sha256=TMUX_SHA256,
        expected_uid=0,
        maximum=8 << 20,
    )
    stable_file(
        Path("/usr/bin/sbatch"),
        mode=0o755,
        expected_sha256=SBATCH_SHA256,
        expected_uid=0,
        maximum=8 << 20,
    )
    _validate_tmux_ancestry()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--authorization-file-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        _validate_outer_environment()
        _install_signal_handlers()
        result = launch(args.authorization, args.authorization_file_sha256)
    except BaseException as error:
        code = error.code if isinstance(error, LaunchError) else "launcher_failed"
        print(canonical_json({"code": code, "state": "failed"}).decode(), file=sys.stderr)
        return 2
    print(canonical_json(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
