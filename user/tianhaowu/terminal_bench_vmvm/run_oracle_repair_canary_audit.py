#!/usr/bin/env python3
"""Invoke the oracle-repair auditor from two independently pinned sources.

The completed source-oracle checkout and the canary execution checkout are
separate authorities.  This controller derives each checkout's commit,
verifier gitlink, and VMVM source digest directly from clean detached Git
worktrees.  It never uses either oracle's self-reported run identity to derive
an expected value.

Child output is retained only in a private runtime directory.  The final
certificate is published atomically, without overwrite, after a second full
source and input attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_VMVM_ROOT = Path("environments/vmvm_tb_v2/vmvm_tb_v2/_vacli")
WORKFLOW_ROOT = Path("user/tianhaowu/terminal_bench_vmvm")
AUDITOR_RELATIVE_PATH = WORKFLOW_ROOT / "audit_oracle_repair_canary.py"
BUILDER_RELATIVE_PATH = WORKFLOW_ROOT / "build_oracle_repair_canary.py"
EXPORTER_RELATIVE_PATH = WORKFLOW_ROOT / "export_oracle_tasks.py"
CONTROLLER_RELATIVE_PATH = WORKFLOW_ROOT / "run_oracle_repair_canary_audit.py"
LAUNCHER_RELATIVE_PATH = WORKFLOW_ROOT / "run_oracle_repair_canary_audit.sbatch"
ATTESTATION_FILENAME = "controller_attestation.json"
AUDITOR_STDOUT_FILENAME = "auditor.stdout.json"
AUDITOR_STDERR_FILENAME = "auditor.stderr.txt"
STAGED_CERTIFICATE_FILENAME = "auditor.certificate.json"
MAX_CHILD_OUTPUT_BYTES = 1 << 20
TRUSTED_GIT = "/usr/bin/git"
SAFE_PATH = "/usr/bin:/bin"
GIT_ENVIRONMENT = {
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": SAFE_PATH,
}
GIT_OPTIONS = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.untrackedCache=false",
)
GIT_REVISION_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PROVENANCE_FLAGS = (
    "--expected-source-prime-rl-commit",
    "--expected-source-verifiers-commit",
    "--expected-source-vmvm-tb-v2-sha256",
    "--expected-prime-rl-commit",
    "--expected-verifiers-commit",
    "--expected-vmvm-tb-v2-sha256",
)


class OracleAuditControllerError(RuntimeError):
    """A fail-closed controller error represented by a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise OracleAuditControllerError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class ControllerOptions:
    source_project_dir: Path
    expected_source_revision: str
    execution_project_dir: Path
    expected_execution_revision: str
    source_oracle_dir: Path
    builder_receipt: Path
    task_file: Path
    canary_dir: Path
    runtime_root: Path
    runtime_dir: Path
    certificate_root: Path
    certificate: Path
    expected_total: int
    controls: int
    minimum_recovered: int
    seed: str


@dataclass(frozen=True, slots=True)
class FileState:
    device: int
    inode: int
    mode: int
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CheckoutAttestation:
    root: Path
    root_device: int
    root_inode: int
    revision: str
    verifiers_revision: str
    verifiers_device: int
    verifiers_inode: int
    vmvm_tb_v2_sha256: str
    tracked_tree_sha256: str
    tracked_entry_count: int
    verifiers_tree_sha256: str
    verifiers_entry_count: int
    tracked_files: tuple[tuple[str, str, str], ...]

    def public_record(self) -> dict[str, Any]:
        return {
            "prime_rl_commit": self.revision,
            "tracked_entry_count": self.tracked_entry_count,
            "tracked_tree_sha256": self.tracked_tree_sha256,
            "verifiers_commit": self.verifiers_revision,
            "verifiers_entry_count": self.verifiers_entry_count,
            "verifiers_tree_sha256": self.verifiers_tree_sha256,
            "vmvm_tb_v2_sha256": self.vmvm_tb_v2_sha256,
            "tracked_files": {path: {"git_blob": blob, "sha256": digest} for path, blob, digest in self.tracked_files},
        }


@dataclass(frozen=True, slots=True)
class ResolvedPaths:
    source_project_dir: Path
    execution_project_dir: Path
    source_oracle_dir: Path
    builder_receipt: Path
    task_file: Path
    canary_dir: Path
    runtime_root: Path
    runtime_dir: Path
    certificate_root: Path
    certificate: Path


@dataclass(frozen=True, slots=True)
class ChildResult:
    returncode: int
    stdout: bytes
    stderr: bytes


CheckoutValidator = Callable[[Path, str, str], CheckoutAttestation]
ChildRunner = Callable[[Sequence[str], Path], ChildResult]


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as error:
        raise OracleAuditControllerError("controller_json_invalid") from error


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)[:-1]).hexdigest()


def _normalized_absolute(path: Path) -> bool:
    return path.is_absolute() and path == Path(os.path.normpath(path))


def _canonical_directory(path: Path, code: str) -> Path:
    if not _normalized_absolute(path):
        raise OracleAuditControllerError(code)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise OracleAuditControllerError(code) from error
    if not stat.S_ISDIR(metadata.st_mode) or resolved != path:
        raise OracleAuditControllerError(code)
    return path


def _unsafe_boundary(path: Path) -> bool:
    if path == Path(path.anchor) or len(path.parts) < 5:
        return True
    try:
        home = Path.home().resolve(strict=True)
    except OSError:
        return True
    return path == home or home.is_relative_to(path)


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _strict_descendant(path: Path, root: Path) -> bool:
    return path != root and path.is_relative_to(root)


def _file_state(path: Path, code: str, *, required_mode: int | None = None) -> FileState:
    if not _normalized_absolute(path):
        raise OracleAuditControllerError(code)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise OracleAuditControllerError(code) from error
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise OracleAuditControllerError(code)
        mode = stat.S_IMODE(before.st_mode)
        if required_mode is not None and mode != required_mode:
            raise OracleAuditControllerError(code)
        while block := os.read(descriptor, 1 << 20):
            digest.update(block)
        after = os.fstat(descriptor)
    except OSError as error:
        raise OracleAuditControllerError(code) from error
    finally:
        os.close(descriptor)
    before_token = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_token = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_token != after_token:
        raise OracleAuditControllerError(code)
    try:
        current = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise OracleAuditControllerError(code) from error
    if (
        resolved != path
        or not stat.S_ISREG(current.st_mode)
        or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
    ):
        raise OracleAuditControllerError(code)
    return FileState(
        device=before.st_dev,
        inode=before.st_ino,
        mode=mode,
        size=before.st_size,
        sha256=digest.hexdigest(),
    )


def _read_file(path: Path, code: str, *, limit: int) -> bytes:
    state = _file_state(path, code)
    if state.size > limit:
        raise OracleAuditControllerError(code)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            body = handle.read(limit + 1)
    except OSError as error:
        raise OracleAuditControllerError(code) from error
    if len(body) > limit or hashlib.sha256(body).hexdigest() != state.sha256:
        raise OracleAuditControllerError(code)
    return body


def _new_path(path: Path, root: Path, code: str) -> Path:
    if not _normalized_absolute(path) or not path.name or os.path.lexists(path):
        raise OracleAuditControllerError(code)
    parent = _canonical_directory(path.parent, code)
    candidate = parent / path.name
    if candidate != path or not _strict_descendant(candidate, root):
        raise OracleAuditControllerError(code)
    return candidate


def _git(
    root: Path,
    arguments: Sequence[str],
    code: str,
    *,
    accepted_returncodes: frozenset[int] = frozenset({0}),
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            [TRUSTED_GIT, *GIT_OPTIONS, "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            env=GIT_ENVIRONMENT,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleAuditControllerError(code) from error
    if result.returncode not in accepted_returncodes or len(result.stdout) > MAX_CHILD_OUTPUT_BYTES:
        raise OracleAuditControllerError(code)
    return result


def _safe_git_path(path: bytes, role: str) -> tuple[bytes, ...]:
    components = tuple(path.split(b"/"))
    if not path or path.startswith(b"/") or any(component in {b"", b".", b".."} for component in components):
        raise OracleAuditControllerError(f"{role}_tracked_tree_invalid")
    return components


def _tree_entries(body: bytes, role: str) -> dict[bytes, tuple[bytes, bytes]]:
    entries: dict[bytes, tuple[bytes, bytes]] = {}
    for record in body.rstrip(b"\0").split(b"\0"):
        if not record:
            continue
        try:
            header, path = record.split(b"\t", 1)
            mode, object_type, object_id = header.split(b" ")
        except ValueError as error:
            raise OracleAuditControllerError(f"{role}_tracked_tree_invalid") from error
        _safe_git_path(path, role)
        if (
            path in entries
            or mode not in {b"100644", b"100755", b"120000", b"160000"}
            or object_type != (b"commit" if mode == b"160000" else b"blob")
            or GIT_REVISION_RE.fullmatch(object_id.decode("ascii", errors="ignore")) is None
        ):
            raise OracleAuditControllerError(f"{role}_tracked_tree_invalid")
        entries[path] = (mode, object_id)
    if not entries:
        raise OracleAuditControllerError(f"{role}_tracked_tree_invalid")
    return entries


def _index_entries(body: bytes, role: str) -> dict[bytes, tuple[bytes, bytes]]:
    entries: dict[bytes, tuple[bytes, bytes]] = {}
    for record in body.rstrip(b"\0").split(b"\0"):
        if not record:
            continue
        try:
            header, path = record.split(b"\t", 1)
            mode, object_id, stage = header.split(b" ")
        except ValueError as error:
            raise OracleAuditControllerError(f"{role}_index_invalid") from error
        _safe_git_path(path, role)
        if (
            path in entries
            or stage != b"0"
            or mode not in {b"100644", b"100755", b"120000", b"160000"}
            or GIT_REVISION_RE.fullmatch(object_id.decode("ascii", errors="ignore")) is None
        ):
            raise OracleAuditControllerError(f"{role}_index_invalid")
        entries[path] = (mode, object_id)
    return entries


def _index_flags_are_default(root: Path, expected_paths: set[bytes], role: str) -> None:
    for option in ("-t", "-v", "-f"):
        body = _git(
            root,
            ("ls-files", option, "-z"),
            f"{role}_index_unverifiable",
        ).stdout
        records = tuple(record for record in body.rstrip(b"\0").split(b"\0") if record)
        if len(records) != len(expected_paths):
            raise OracleAuditControllerError(f"{role}_index_flags_nondefault")
        observed_paths: set[bytes] = set()
        for record in records:
            if not record.startswith(b"H "):
                raise OracleAuditControllerError(f"{role}_index_flags_nondefault")
            path = record[2:]
            _safe_git_path(path, role)
            if path in observed_paths:
                raise OracleAuditControllerError(f"{role}_index_flags_nondefault")
            observed_paths.add(path)
        if observed_paths != expected_paths:
            raise OracleAuditControllerError(f"{role}_index_flags_nondefault")
    debug = _git(
        root,
        ("ls-files", "--debug", "-z"),
        f"{role}_index_unverifiable",
    ).stdout
    flag_values = re.findall(rb"\tflags: ([0-9A-Fa-f]+)\n", debug)
    if len(flag_values) != len(expected_paths) or any(value != b"0" for value in flag_values):
        raise OracleAuditControllerError(f"{role}_index_flags_nondefault")


def _git_blob_sha1(body: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(body)}\0".encode("ascii"))
    digest.update(body)
    return digest.hexdigest()


def _worktree_blob(root: Path, path: bytes, mode: bytes, role: str) -> str:
    components = _safe_git_path(path, role)
    candidate = os.path.join(os.fsencode(root), *components)
    try:
        before = os.lstat(candidate)
    except OSError as error:
        raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch") from error
    if mode == b"120000":
        if not stat.S_ISLNK(before.st_mode):
            raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch")
        try:
            body = os.readlink(candidate)
            after = os.lstat(candidate)
        except OSError as error:
            raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch") from error
        if not isinstance(body, bytes):
            body = os.fsencode(body)
    else:
        if not stat.S_ISREG(before.st_mode):
            raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch")
        expected_executable = mode == b"100755"
        if bool(before.st_mode & 0o111) != expected_executable:
            raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
        except OSError as error:
            raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch") from error
        digest = hashlib.sha1(usedforsecurity=False)
        digest.update(f"blob {before.st_size}\0".encode("ascii"))
        observed_size = 0
        try:
            while block := os.read(descriptor, 1 << 20):
                observed_size += len(block)
                digest.update(block)
            after = os.fstat(descriptor)
        except OSError as error:
            raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch") from error
        finally:
            os.close(descriptor)
        if observed_size != before.st_size:
            raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch")
        body = b""
    before_token = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_token = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_token != after_token:
        raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch")
    try:
        current = os.lstat(candidate)
    except OSError as error:
        raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch") from error
    current_token = (
        current.st_dev,
        current.st_ino,
        current.st_mode,
        current.st_size,
        current.st_mtime_ns,
        current.st_ctime_ns,
    )
    if current_token != after_token:
        raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch")
    if mode == b"120000":
        return _git_blob_sha1(body)
    return digest.hexdigest()


def _verify_exact_tracked_tree(root: Path, revision: str, role: str) -> tuple[str, int]:
    object_format = _git(
        root,
        ("rev-parse", "--show-object-format"),
        f"{role}_repository_unverifiable",
    ).stdout
    if object_format != b"sha1\n":
        raise OracleAuditControllerError(f"{role}_repository_object_format_unsupported")
    tree = _tree_entries(
        _git(
            root,
            ("ls-tree", "-r", "-z", revision),
            f"{role}_tracked_tree_unverifiable",
        ).stdout,
        role,
    )
    index = _index_entries(
        _git(
            root,
            ("ls-files", "--stage", "-z"),
            f"{role}_index_unverifiable",
        ).stdout,
        role,
    )
    if index != tree:
        raise OracleAuditControllerError(f"{role}_index_mismatch")
    _index_flags_are_default(root, set(tree), role)

    proof = hashlib.sha256()
    for path in sorted(tree):
        mode, expected_blob = tree[path]
        proof.update(mode + b" " + expected_blob + b"\t" + path + b"\0")
        if mode == b"160000":
            continue
        if _worktree_blob(root, path, mode, role).encode("ascii") != expected_blob:
            raise OracleAuditControllerError(f"{role}_tracked_worktree_mismatch")
    return proof.hexdigest(), len(tree)


def _require_detached(root: Path, role: str) -> None:
    result = _git(
        root,
        ("symbolic-ref", "-q", "HEAD"),
        f"{role}_revision_unverifiable",
        accepted_returncodes=frozenset({0, 1}),
    )
    if result.returncode != 1 or result.stdout:
        raise OracleAuditControllerError(f"{role}_checkout_not_detached")


def _tracked_blob(root: Path, revision: str, relative: Path, role: str) -> tuple[str, bytes]:
    relative_text = relative.as_posix()
    record = _git(
        root,
        ("ls-tree", "-z", revision, "--", relative_text),
        f"{role}_script_revision_unverifiable",
    ).stdout
    suffix = f"\t{relative_text}\0".encode()
    if not record.endswith(suffix) or record.count(b"\0") != 1:
        raise OracleAuditControllerError(f"{role}_script_revision_mismatch")
    header = record[: -len(suffix)].split(b" ")
    if len(header) != 3 or header[0] not in {b"100644", b"100755"} or header[1] != b"blob":
        raise OracleAuditControllerError(f"{role}_script_revision_mismatch")
    try:
        blob = header[2].decode("ascii")
    except UnicodeDecodeError as error:
        raise OracleAuditControllerError(f"{role}_script_revision_mismatch") from error
    if GIT_REVISION_RE.fullmatch(blob) is None:
        raise OracleAuditControllerError(f"{role}_script_revision_mismatch")
    body = _git(
        root,
        ("cat-file", "blob", blob),
        f"{role}_script_revision_unverifiable",
    ).stdout
    return blob, body


def _vmvm_tree(root: Path, revision: str, role: str) -> str:
    prefix = SOURCE_VMVM_ROOT.as_posix()
    records = _git(
        root,
        ("ls-tree", "-r", "-z", "--name-only", revision, "--", prefix),
        f"{role}_vmvm_digest_unverifiable",
    ).stdout
    try:
        committed = tuple(
            sorted(
                entry.decode("utf-8")
                for entry in records.rstrip(b"\0").split(b"\0")
                if entry and entry.decode("utf-8").endswith(".py")
            )
        )
    except UnicodeDecodeError as error:
        raise OracleAuditControllerError(f"{role}_vmvm_digest_unverifiable") from error
    if not committed or any(not path.startswith(f"{prefix}/") for path in committed):
        raise OracleAuditControllerError(f"{role}_vmvm_digest_unverifiable")

    source_root = _canonical_directory(root / SOURCE_VMVM_ROOT, f"{role}_vmvm_source_invalid")
    try:
        observed = tuple(
            sorted(path.relative_to(root).as_posix() for path in source_root.iterdir() if path.name.endswith(".py"))
        )
    except OSError as error:
        raise OracleAuditControllerError(f"{role}_vmvm_source_invalid") from error
    if observed != committed:
        raise OracleAuditControllerError(f"{role}_vmvm_digest_mismatch")

    digest = hashlib.sha256()
    for relative_text in committed:
        path = root / relative_text
        body = _read_file(path, f"{role}_vmvm_source_invalid", limit=MAX_CHILD_OUTPUT_BYTES)
        committed_body = _git(
            root,
            ("show", f"{revision}:{relative_text}"),
            f"{role}_vmvm_digest_unverifiable",
        ).stdout
        if body != committed_body:
            raise OracleAuditControllerError(f"{role}_vmvm_digest_mismatch")
        file_sha256 = hashlib.sha256(body).hexdigest()
        digest.update(f"{file_sha256}  {relative_text}\n".encode("utf-8"))
    return digest.hexdigest()


def _attest_checkout(root: Path, expected_revision: str, role: str) -> CheckoutAttestation:
    if role not in {"source", "execution"}:
        raise OracleAuditControllerError("checkout_role_invalid")
    if GIT_REVISION_RE.fullmatch(expected_revision) is None:
        raise OracleAuditControllerError(f"expected_{role}_revision_invalid")
    root = _canonical_directory(root, f"{role}_project_path_unsafe")
    try:
        root_metadata = root.stat()
    except OSError as error:
        raise OracleAuditControllerError(f"{role}_project_path_unsafe") from error
    top = _git(root, ("rev-parse", "--show-toplevel"), f"{role}_repository_unverifiable").stdout
    try:
        top_path = Path(top.decode("utf-8").strip()).resolve(strict=True)
    except (UnicodeDecodeError, OSError, RuntimeError) as error:
        raise OracleAuditControllerError(f"{role}_repository_unverifiable") from error
    if top_path != root:
        raise OracleAuditControllerError(f"{role}_repository_mismatch")
    _require_detached(root, role)
    revision = (
        _git(
            root,
            ("rev-parse", "--verify", "HEAD^{commit}"),
            f"{role}_revision_unverifiable",
        )
        .stdout.decode("ascii")
        .strip()
    )
    if revision != expected_revision:
        raise OracleAuditControllerError(f"{role}_revision_mismatch")
    tracked_tree_sha256, tracked_entry_count = _verify_exact_tracked_tree(root, revision, role)

    gitlink = _git(
        root,
        ("ls-tree", "-z", revision, "--", "deps/verifiers"),
        f"{role}_verifiers_gitlink_unverifiable",
    ).stdout
    suffix = b"\tdeps/verifiers\0"
    if not gitlink.endswith(suffix) or gitlink.count(b"\0") != 1:
        raise OracleAuditControllerError(f"{role}_verifiers_gitlink_missing")
    fields = gitlink[: -len(suffix)].split(b" ")
    if len(fields) != 3 or fields[0] != b"160000" or fields[1] != b"commit":
        raise OracleAuditControllerError(f"{role}_verifiers_gitlink_invalid")
    try:
        verifiers_revision = fields[2].decode("ascii")
    except UnicodeDecodeError as error:
        raise OracleAuditControllerError(f"{role}_verifiers_gitlink_invalid") from error
    if GIT_REVISION_RE.fullmatch(verifiers_revision) is None:
        raise OracleAuditControllerError(f"{role}_verifiers_gitlink_invalid")

    verifiers = _canonical_directory(root / "deps/verifiers", f"{role}_verifiers_checkout_invalid")
    try:
        verifiers_metadata = verifiers.stat()
    except OSError as error:
        raise OracleAuditControllerError(f"{role}_verifiers_checkout_invalid") from error
    verifiers_top = _git(
        verifiers,
        ("rev-parse", "--show-toplevel"),
        f"{role}_verifiers_checkout_invalid",
    ).stdout
    try:
        verifiers_top_path = Path(verifiers_top.decode("utf-8").strip()).resolve(strict=True)
    except (UnicodeDecodeError, OSError, RuntimeError) as error:
        raise OracleAuditControllerError(f"{role}_verifiers_checkout_invalid") from error
    if verifiers_top_path != verifiers:
        raise OracleAuditControllerError(f"{role}_verifiers_checkout_invalid")
    _require_detached(verifiers, f"{role}_verifiers")
    observed_verifier = (
        _git(
            verifiers,
            ("rev-parse", "--verify", "HEAD^{commit}"),
            f"{role}_verifiers_checkout_invalid",
        )
        .stdout.decode("ascii")
        .strip()
    )
    if observed_verifier != verifiers_revision:
        raise OracleAuditControllerError(f"{role}_verifiers_checkout_mismatch")
    verifiers_tree_sha256, verifiers_entry_count = _verify_exact_tracked_tree(
        verifiers,
        verifiers_revision,
        f"{role}_verifiers",
    )

    tracked_files: list[tuple[str, str, str]] = []
    if role == "execution":
        expected_origins = {
            CONTROLLER_RELATIVE_PATH: Path(__file__).resolve(strict=True),
            AUDITOR_RELATIVE_PATH: root / AUDITOR_RELATIVE_PATH,
            BUILDER_RELATIVE_PATH: root / BUILDER_RELATIVE_PATH,
            EXPORTER_RELATIVE_PATH: root / EXPORTER_RELATIVE_PATH,
            LAUNCHER_RELATIVE_PATH: root / LAUNCHER_RELATIVE_PATH,
        }
        for relative, origin in expected_origins.items():
            candidate = root / relative
            try:
                candidate_resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise OracleAuditControllerError("execution_script_origin_mismatch") from error
            if candidate_resolved != candidate or origin != candidate:
                raise OracleAuditControllerError("execution_script_origin_mismatch")
            blob, committed_body = _tracked_blob(root, revision, relative, "execution")
            observed_body = _read_file(candidate, "execution_script_invalid", limit=MAX_CHILD_OUTPUT_BYTES)
            if observed_body != committed_body:
                raise OracleAuditControllerError("execution_script_revision_mismatch")
            tracked_files.append((relative.as_posix(), blob, hashlib.sha256(observed_body).hexdigest()))

    vmvm_digest = _vmvm_tree(root, revision, role)
    final_status = _git(
        root,
        ("status", "--porcelain=v1", "--untracked-files=all"),
        f"{role}_worktree_unverifiable",
    ).stdout
    final_verifier_status = _git(
        verifiers,
        ("status", "--porcelain=v1", "--untracked-files=all"),
        f"{role}_verifiers_checkout_invalid",
    ).stdout
    try:
        final_root_metadata = root.stat()
        final_verifiers_metadata = verifiers.stat()
    except OSError as error:
        raise OracleAuditControllerError(f"{role}_checkout_changed") from error
    if final_status:
        raise OracleAuditControllerError(f"{role}_worktree_not_clean")
    if final_verifier_status:
        raise OracleAuditControllerError(f"{role}_verifiers_checkout_mismatch")
    if (final_root_metadata.st_dev, final_root_metadata.st_ino) != (root_metadata.st_dev, root_metadata.st_ino) or (
        final_verifiers_metadata.st_dev,
        final_verifiers_metadata.st_ino,
    ) != (verifiers_metadata.st_dev, verifiers_metadata.st_ino):
        raise OracleAuditControllerError(f"{role}_checkout_changed")
    return CheckoutAttestation(
        root=root,
        root_device=root_metadata.st_dev,
        root_inode=root_metadata.st_ino,
        revision=revision,
        verifiers_revision=verifiers_revision,
        verifiers_device=verifiers_metadata.st_dev,
        verifiers_inode=verifiers_metadata.st_ino,
        vmvm_tb_v2_sha256=vmvm_digest,
        tracked_tree_sha256=tracked_tree_sha256,
        tracked_entry_count=tracked_entry_count,
        verifiers_tree_sha256=verifiers_tree_sha256,
        verifiers_entry_count=verifiers_entry_count,
        tracked_files=tuple(tracked_files),
    )


def _resolve_paths(options: ControllerOptions) -> ResolvedPaths:
    source_project = _canonical_directory(options.source_project_dir, "source_project_path_unsafe")
    execution_project = _canonical_directory(options.execution_project_dir, "execution_project_path_unsafe")
    if _overlap(source_project, execution_project):
        raise OracleAuditControllerError("project_checkouts_overlap")
    source_oracle = _canonical_directory(options.source_oracle_dir, "source_oracle_path_unsafe")
    canary = _canonical_directory(options.canary_dir, "canary_path_unsafe")
    if _overlap(source_oracle, canary):
        raise OracleAuditControllerError("oracle_directories_overlap")

    builder_receipt = options.builder_receipt
    task_file = options.task_file
    _file_state(builder_receipt, "builder_receipt_invalid", required_mode=0o600)
    _file_state(task_file, "task_file_invalid", required_mode=0o600)
    if builder_receipt == task_file:
        raise OracleAuditControllerError("builder_artifacts_overlap")

    runtime_root = _canonical_directory(options.runtime_root, "runtime_root_unsafe")
    certificate_root = _canonical_directory(options.certificate_root, "certificate_root_unsafe")
    if _unsafe_boundary(runtime_root) or _unsafe_boundary(certificate_root):
        raise OracleAuditControllerError("artifact_boundary_unsafe")
    runtime = _new_path(options.runtime_dir, runtime_root, "runtime_path_unsafe")
    certificate = _new_path(options.certificate, certificate_root, "certificate_path_unsafe")

    existing = (source_project, execution_project, source_oracle, canary)
    if any(_overlap(runtime, path) for path in existing):
        raise OracleAuditControllerError("runtime_path_overlap")
    if certificate.is_relative_to(source_oracle) or certificate.is_relative_to(canary):
        raise OracleAuditControllerError("certificate_path_overlap")
    if certificate.is_relative_to(source_project) or certificate.is_relative_to(execution_project):
        raise OracleAuditControllerError("certificate_path_overlap")
    if certificate.is_relative_to(runtime):
        raise OracleAuditControllerError("certificate_path_overlap")
    return ResolvedPaths(
        source_project_dir=source_project,
        execution_project_dir=execution_project,
        source_oracle_dir=source_oracle,
        builder_receipt=builder_receipt,
        task_file=task_file,
        canary_dir=canary,
        runtime_root=runtime_root,
        runtime_dir=runtime,
        certificate_root=certificate_root,
        certificate=certificate,
    )


def _validate_options(options: ControllerOptions) -> None:
    for role, revision in (
        ("source", options.expected_source_revision),
        ("execution", options.expected_execution_revision),
    ):
        if GIT_REVISION_RE.fullmatch(revision) is None:
            raise OracleAuditControllerError(f"expected_{role}_revision_invalid")
    if type(options.expected_total) is not int or options.expected_total < 1:
        raise OracleAuditControllerError("expected_total_invalid")
    if type(options.controls) is not int or options.controls < 0:
        raise OracleAuditControllerError("controls_invalid")
    if type(options.minimum_recovered) is not int or options.minimum_recovered < 0:
        raise OracleAuditControllerError("minimum_recovered_invalid")
    if (
        not isinstance(options.seed, str)
        or not options.seed
        or options.seed.strip() != options.seed
        or len(options.seed.encode("utf-8")) > 256
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in options.seed)
    ):
        raise OracleAuditControllerError("seed_invalid")


def _auditor_command(
    paths: ResolvedPaths,
    options: ControllerOptions,
    source: CheckoutAttestation,
    execution: CheckoutAttestation,
    staged_certificate: Path,
) -> tuple[str, ...]:
    auditor = execution.root / AUDITOR_RELATIVE_PATH
    command = (
        sys.executable,
        str(auditor),
        str(paths.source_oracle_dir),
        str(paths.builder_receipt),
        str(paths.task_file),
        str(paths.canary_dir),
        str(staged_certificate),
        "--expected-source-prime-rl-commit",
        source.revision,
        "--expected-source-verifiers-commit",
        source.verifiers_revision,
        "--expected-source-vmvm-tb-v2-sha256",
        source.vmvm_tb_v2_sha256,
        "--expected-prime-rl-commit",
        execution.revision,
        "--expected-verifiers-commit",
        execution.verifiers_revision,
        "--expected-vmvm-tb-v2-sha256",
        execution.vmvm_tb_v2_sha256,
        "--expected-total",
        str(options.expected_total),
        "--controls",
        str(options.controls),
        "--minimum-recovered",
        str(options.minimum_recovered),
        "--seed",
        options.seed,
    )
    _validate_provenance_arguments(command)
    return command


def _validate_provenance_arguments(command: Sequence[str]) -> None:
    for flag in PROVENANCE_FLAGS:
        if command.count(flag) != 1:
            raise OracleAuditControllerError("auditor_provenance_argument_omitted")
        position = command.index(flag)
        if position + 1 >= len(command) or not command[position + 1] or command[position + 1].startswith("--"):
            raise OracleAuditControllerError("auditor_provenance_argument_omitted")


def _default_child_runner(command: Sequence[str], working_directory: Path) -> ChildResult:
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": SAFE_PATH,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        result = subprocess.run(
            list(command),
            cwd=working_directory,
            env=environment,
            check=False,
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleAuditControllerError("auditor_execution_failed") from error
    if len(result.stdout) > MAX_CHILD_OUTPUT_BYTES or len(result.stderr) > MAX_CHILD_OUTPUT_BYTES:
        raise OracleAuditControllerError("auditor_output_too_large")
    return ChildResult(result.returncode, result.stdout, result.stderr)


def _write_exclusive(path: Path, body: bytes, code: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
    except OSError as error:
        raise OracleAuditControllerError(code) from error


def _strict_json_object(body: bytes, code: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise OracleAuditControllerError(code) from error
    if not isinstance(value, dict):
        raise OracleAuditControllerError(code)
    return value


def _validate_auditor_outputs(
    result: ChildResult,
    staged_certificate: Path,
    source: CheckoutAttestation,
    execution: CheckoutAttestation,
) -> tuple[dict[str, Any], bytes]:
    if result.returncode not in {0, 1} or result.stderr:
        raise OracleAuditControllerError("auditor_rejected_inputs")
    summary = _strict_json_object(result.stdout, "auditor_summary_invalid")
    expected_summary_keys = {
        "audit_sha256",
        "control_regressions",
        "controls",
        "minimum_recovered",
        "ok",
        "published",
        "reason_counts",
        "recovered",
        "repair_candidates",
        "state",
        "transitions",
        "unrecovered",
    }
    if set(summary) != expected_summary_keys:
        raise OracleAuditControllerError("auditor_summary_invalid")
    if (
        not isinstance(summary.get("ok"), bool)
        or summary.get("state") not in {"passed", "failed"}
        or summary["state"] != ("passed" if summary["ok"] else "failed")
        or result.returncode != (0 if summary["ok"] else 1)
        or summary.get("published") is not True
        or not isinstance(summary.get("audit_sha256"), str)
        or SHA256_RE.fullmatch(summary["audit_sha256"]) is None
    ):
        raise OracleAuditControllerError("auditor_summary_invalid")

    certificate_state = _file_state(staged_certificate, "auditor_certificate_invalid", required_mode=0o600)
    if certificate_state.size > MAX_CHILD_OUTPUT_BYTES:
        raise OracleAuditControllerError("auditor_certificate_invalid")
    certificate_bytes = _read_file(
        staged_certificate,
        "auditor_certificate_invalid",
        limit=MAX_CHILD_OUTPUT_BYTES,
    )
    envelope = _strict_json_object(certificate_bytes, "auditor_certificate_invalid")
    if set(envelope) != {"audit", "audit_sha256", "schema_version"} or envelope.get("schema_version") != 1:
        raise OracleAuditControllerError("auditor_certificate_invalid")
    audit = envelope.get("audit")
    if not isinstance(audit, dict) or _canonical_json_sha256(audit) != envelope.get("audit_sha256"):
        raise OracleAuditControllerError("auditor_certificate_invalid")
    contracts = audit.get("contracts")
    expected_source = {
        "prime_rl_commit": source.revision,
        "prime_rl_tree_sha256": hashlib.sha256(b"").hexdigest(),
        "verifiers_commit": source.verifiers_revision,
        "vmvm_tb_v2_sha256": source.vmvm_tb_v2_sha256,
    }
    expected_execution = {
        "prime_rl_commit": execution.revision,
        "prime_rl_tree_sha256": hashlib.sha256(b"").hexdigest(),
        "verifiers_commit": execution.verifiers_revision,
        "vmvm_tb_v2_sha256": execution.vmvm_tb_v2_sha256,
    }
    if (
        not isinstance(contracts, dict)
        or contracts.get("source_oracle_source") != expected_source
        or contracts.get("canary_source") != expected_execution
        or audit.get("ok") is not summary["ok"]
        or audit.get("state") != summary["state"]
        or envelope.get("audit_sha256") != summary["audit_sha256"]
    ):
        raise OracleAuditControllerError("auditor_certificate_provenance_mismatch")
    return summary, certificate_bytes


def _publish_no_clobber(path: Path, body: bytes) -> None:
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    _write_exclusive(temporary, body, "certificate_staging_failed")
    linked = False
    try:
        try:
            os.link(temporary, path, follow_symlinks=False)
            linked = True
            descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            if linked:
                path.unlink(missing_ok=True)
            raise OracleAuditControllerError("certificate_publication_failed") from error
    finally:
        temporary.unlink(missing_ok=True)


def _input_states(paths: ResolvedPaths) -> Mapping[str, FileState]:
    return {
        "builder_receipt": _file_state(paths.builder_receipt, "builder_receipt_invalid", required_mode=0o600),
        "task_file": _file_state(paths.task_file, "task_file_invalid", required_mode=0o600),
    }


def run_controller(
    options: ControllerOptions,
    *,
    checkout_validator: CheckoutValidator = _attest_checkout,
    child_runner: ChildRunner = _default_child_runner,
) -> dict[str, Any]:
    _validate_options(options)
    paths = _resolve_paths(options)
    source = checkout_validator(paths.source_project_dir, options.expected_source_revision, "source")
    execution = checkout_validator(paths.execution_project_dir, options.expected_execution_revision, "execution")
    if source.root != paths.source_project_dir or execution.root != paths.execution_project_dir:
        raise OracleAuditControllerError("checkout_attestation_path_mismatch")
    required_execution_files = {
        AUDITOR_RELATIVE_PATH.as_posix(),
        BUILDER_RELATIVE_PATH.as_posix(),
        CONTROLLER_RELATIVE_PATH.as_posix(),
        EXPORTER_RELATIVE_PATH.as_posix(),
        LAUNCHER_RELATIVE_PATH.as_posix(),
    }
    if {path for path, _blob, _digest in execution.tracked_files} != required_execution_files:
        raise OracleAuditControllerError("execution_script_attestation_incomplete")
    before_inputs = _input_states(paths)

    try:
        os.mkdir(paths.runtime_dir, 0o700)
        os.chmod(paths.runtime_dir, 0o700)
    except OSError as error:
        raise OracleAuditControllerError("runtime_creation_failed") from error
    staged_certificate = paths.runtime_dir / STAGED_CERTIFICATE_FILENAME
    attestation = {
        "execution": {key: value for key, value in execution.public_record().items() if key != "tracked_files"},
        "execution_files": execution.public_record()["tracked_files"],
        "schema_version": 1,
        "source": {key: value for key, value in source.public_record().items() if key != "tracked_files"},
    }
    _write_exclusive(
        paths.runtime_dir / ATTESTATION_FILENAME,
        _canonical_json_bytes(attestation),
        "attestation_publication_failed",
    )

    command = _auditor_command(paths, options, source, execution, staged_certificate)
    result = child_runner(command, paths.execution_project_dir)
    if len(result.stdout) > MAX_CHILD_OUTPUT_BYTES or len(result.stderr) > MAX_CHILD_OUTPUT_BYTES:
        raise OracleAuditControllerError("auditor_output_too_large")
    _write_exclusive(
        paths.runtime_dir / AUDITOR_STDOUT_FILENAME,
        result.stdout,
        "auditor_log_publication_failed",
    )
    _write_exclusive(
        paths.runtime_dir / AUDITOR_STDERR_FILENAME,
        result.stderr,
        "auditor_log_publication_failed",
    )

    source_after = checkout_validator(paths.source_project_dir, options.expected_source_revision, "source")
    execution_after = checkout_validator(paths.execution_project_dir, options.expected_execution_revision, "execution")
    if source_after != source:
        raise OracleAuditControllerError("source_checkout_changed")
    if execution_after != execution:
        raise OracleAuditControllerError("execution_checkout_changed")
    if _input_states(paths) != before_inputs:
        raise OracleAuditControllerError("audit_input_changed")

    summary, certificate_bytes = _validate_auditor_outputs(
        result,
        staged_certificate,
        source,
        execution,
    )
    certificate_sha256 = hashlib.sha256(certificate_bytes).hexdigest()
    output = {
        "audit_sha256": summary["audit_sha256"],
        "certificate_sha256": certificate_sha256,
        "control_regressions": summary["control_regressions"],
        "controls": summary["controls"],
        "execution": {
            "prime_rl_commit": execution.revision,
            "verifiers_commit": execution.verifiers_revision,
            "vmvm_tb_v2_sha256": execution.vmvm_tb_v2_sha256,
        },
        "minimum_recovered": summary["minimum_recovered"],
        "ok": summary["ok"],
        "recovered": summary["recovered"],
        "repair_candidates": summary["repair_candidates"],
        "source": {
            "prime_rl_commit": source.revision,
            "verifiers_commit": source.verifiers_revision,
            "vmvm_tb_v2_sha256": source.vmvm_tb_v2_sha256,
        },
        "state": summary["state"],
        "unrecovered": summary["unrecovered"],
    }
    _write_exclusive(
        paths.runtime_dir / "controller_summary.json",
        _canonical_json_bytes(output),
        "controller_summary_publication_failed",
    )
    # Publication is intentionally last. After the durable no-clobber link
    # succeeds, no later controller operation can turn a published certificate
    # into an apparent failed invocation.
    _publish_no_clobber(paths.certificate, certificate_bytes)
    return output


def _parser() -> StableArgumentParser:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--source-project-dir", required=True, type=Path)
    parser.add_argument("--expected-source-revision", required=True)
    parser.add_argument("--execution-project-dir", required=True, type=Path)
    parser.add_argument("--expected-execution-revision", required=True)
    parser.add_argument("--source-oracle-dir", required=True, type=Path)
    parser.add_argument("--builder-receipt", required=True, type=Path)
    parser.add_argument("--task-file", required=True, type=Path)
    parser.add_argument("--canary-dir", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--certificate-root", required=True, type=Path)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--expected-total", type=int, default=2_538)
    parser.add_argument("--controls", type=int, default=20)
    parser.add_argument("--minimum-recovered", type=int, default=12)
    parser.add_argument("--seed", default="oracle-dependency-overlay-v1")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        summary = run_controller(
            ControllerOptions(
                source_project_dir=args.source_project_dir,
                expected_source_revision=args.expected_source_revision,
                execution_project_dir=args.execution_project_dir,
                expected_execution_revision=args.expected_execution_revision,
                source_oracle_dir=args.source_oracle_dir,
                builder_receipt=args.builder_receipt,
                task_file=args.task_file,
                canary_dir=args.canary_dir,
                runtime_root=args.runtime_root,
                runtime_dir=args.runtime_dir,
                certificate_root=args.certificate_root,
                certificate=args.certificate,
                expected_total=args.expected_total,
                controls=args.controls,
                minimum_recovered=args.minimum_recovered,
                seed=args.seed,
            )
        )
    except OracleAuditControllerError as error:
        print(f"oracle_repair_canary_controller_error:{error.code}", file=sys.stderr)
        return 2
    except Exception:
        print("oracle_repair_canary_controller_error:internal_failure", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
