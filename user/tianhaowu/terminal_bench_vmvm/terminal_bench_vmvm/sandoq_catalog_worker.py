"""Pinned Sandoq worker for offline verifier catalog materialization.

This executable is intentionally separate from rollout execution.  ``probe``
and ``validate`` run in the exact digest-pinned task image inside the pinned
OCI Firecracker provider with nested networking disabled.  ``build`` resolves
binary artifacts in a fresh, pinned Firecracker trusted-builder session, then
validates the result in the same image with networking disabled. Every
provider session is covered by the provider WAL and an authoritative,
assignment-bound release receipt before a response is committed. Global drain
and zero-live WAL proofs are reserved for quiescent controller boundaries.

Operational stdout/stderr are redirected to ``/dev/null``.  Worker response
files and the provider WAL are private; the controller publishes hashes and
aggregate counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shlex
import signal
import stat
import sys
import tarfile
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Protocol
from zipfile import ZipFile

SCHEMA_VERSION = 1
WORKER_PROTOCOL_VERSION = 2
PINNED_PROVIDER_COMMIT = "4890302104d76220cef791c86d2009168597d35f"
PINNED_PROVIDER_TREE = "33f092a3982916660e12f472588e6ce34a906fc2"
PINNED_SANDOQ_CLIENT = "0.4.0.2026.8.20.58304.0+hga81e4ca4d312"
PINNED_PROVIDER_SOURCE_SHA256 = "7a8ea69a6421793299245296995cfc5598fa66052e04b738cda54261f570b764"
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_WORKER_SITE_BYTES = 2 * 1024 * 1024 * 1024
MAX_WORKER_SITE_FILES = 100_000
PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS = 5
RUNTIME_ROOT = PurePosixPath("/tmp/terminal-bench-offline-verifier")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DIGEST_IMAGE_RE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_EXACT_REQUIREMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.!+_-]+")

_PROVIDER_FILES = {
    "__init__.py": ("178c823a8b3ad39042b9d72964ec7c0fbdd26bbd4ff7c9bdc0469abef1c30672", 6864),
    "buffered_chat.py": ("f9112a6a9dc33b09927ea2df0e36a8f23810a3d01a8230440417d2d9064f7e49", 19371),
    "client.py": ("e104058f118eb5ae7cf6c30706d10783508019f519806e7ef7df04bdc68dccf3", 21291),
    "config.py": ("082458cd3124928c58931514e3717b41ad9aeb041b4fed96bdecdcf1a25ccc3f", 3379),
    "ecr.py": ("101cafaf6d38bd26016532b1e6084087930b937b0e20ee4fdf2ed2c33a05d869", 10841),
    "gateway.py": ("ab596cc14076a913b8e3248e9924ea94111ce2b586c18d3310e6866b51bb34be", 22971),
    "oci_client.py": ("95f14a8af679a6d022e41eae2c77a506bb1024074f4759ff8220cab0bd7c62ff", 156601),
    "pool.py": ("bc69b970332d3db741e9b54deec0c8b86534e164b0c4554b874c378114f9639f", 126397),
    "registry.py": ("63fbc7de54428803e582f62d5f22dc0be4cc29463b907ea392061790c8658ea6", 3444),
    "secrets.py": ("3ee859610ee38c7d54296a8fa1f0d1e263a23e91f5a4c54d39181dfdb226cb0a", 2864),
    "sync_client.py": ("d8ff459280fb7ee3482d1a483f851132d4d072ace88565bbab518823e21835b9", 1990),
    "tunnel.py": ("6bdb26e3676e161eb0a7cd57f42d4975c72ec51ba2fbb9ba1351c29eab4674bb", 11700),
    "utils.py": ("cfc3b479ebd0dbaf067cdac2110e1ef45f4689d219c7d32b0ec66dfe248743f1", 1577),
}

_REQUIRED_ENVIRONMENT = {
    "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK": "0",
    "OCI_RUNNER_ENVIRONMENT": "oci-runner-firecracker",
    "OCI_RUNNER_POOL_MIN_SIZE": "0",
    "OCI_RUNNER_REQUIRE_RESOURCE_LIMITS": "1",
    "OCI_RUNNER_SESSION_REUSE": "1",
    "OCI_RUNNER_TASK_NETWORK": "none",
    "SANDOQ_CATALOG_EXCLUSIVE_POOL": "1",
    "VF_SANDBOX_PROVIDER": "sandoq",
}
_REQUIRED_ENVIRONMENT_NAMES = {
    *_REQUIRED_ENVIRONMENT,
    "OCI_RUNNER_BASE_URL",
    "OCI_RUNNER_ECR_PULL_THROUGH_PREFIX",
    "OCI_RUNNER_ECR_REGION",
    "OCI_RUNNER_ECR_REGISTRY",
    "OCI_RUNNER_ECR_TOKEN_FILE",
    "OCI_RUNNER_ECR_TOKEN_METADATA_PATH",
    "OCI_RUNNER_POOL_SOCKET",
    "OCI_RUNNER_POOL_WAL",
    "OCI_RUNNER_TOKEN_FILE",
    "SANDOQ_CATALOG_WORKER_MODULE",
    "SANDOQ_CATALOG_WORKER_PYTHON",
    "SANDOQ_CATALOG_BUILDER_IMAGE",
    "SANDOQ_CATALOG_PYTHON_RUNTIME_MANIFEST_SHA256",
    "SANDOQ_CATALOG_WORKER_PROVISION_IDENTITY_SHA256",
    "SANDOQ_CATALOG_WORKER_SITE_MANIFEST",
    "SANDOQ_CATALOG_WORKER_SITE_MANIFEST_SHA256",
    "SANDOQ_CATALOG_WORKER_SITE_ROOT",
    "SANDOQ_OWNER",
    "SANDOQ_PROVIDER_ROOT",
}
_WORKER_KEYS = (
    "executable_sha256",
    "runtime_sha256",
    "materializer_code_sha256",
    "cleanup_receipt_verifier_sha256",
    "environment_sha256",
    "recovery_scope_sha256",
    "ecr_rotator_sha256",
    "credential_rotation_sha256",
)

CLEANUP_RECEIPT_VERIFIER_CONTRACT = {
    "schema_version": 2,
    "provider": "sandoq",
    "provider_commit": PINNED_PROVIDER_COMMIT,
    "outer_terminal_status": 404,
    "nested_cleanup_required": True,
    "provider_wal_required": True,
    "recovery_remaining_sessions": 0,
    "normal_cleanup": "assignment-release-only",
    "terminal_states": ["deleted", "recycled"],
}
_STAGED_PROVIDER_ROOT: Path | None = None
_WORKER_SITE_ROOT: Path | None = None
_WORKER_SITE_DIRECTORY: Path | None = None
_WORKER_SITE_MANIFEST_SHA256: str | None = None
_WORKER_SITE_RECORD: dict[str, object] | None = None


class WorkerError(RuntimeError):
    """Aggregate-safe worker failure."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise WorkerError(code)
    raise WorkerError(code) from error


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _allowlist_sha256(kind: str, values: list[str]) -> str:
    return _sha256(
        _canonical(
            {
                "schema_version": SCHEMA_VERSION,
                "kind": kind,
                "values": values,
            }
        )
    )


def _builder_code_sha256(worker: dict[str, object]) -> str:
    return _sha256(
        _canonical(
            {
                "schema_version": SCHEMA_VERSION,
                "contract": "isolated-binary-wheel-resolver-v1",
                "worker_executable_sha256": worker["executable_sha256"],
                "worker_runtime_sha256": worker["runtime_sha256"],
            }
        )
    )


def _builder_environment_sha256(worker: dict[str, object], builder_image: str) -> str:
    return _sha256(
        _canonical(
            {
                "schema_version": SCHEMA_VERSION,
                "builder_image": builder_image,
                "worker_environment_sha256": worker["environment_sha256"],
            }
        )
    )


def _strict_json(payload: bytes) -> object:
    if len(payload) > MAX_JSON_BYTES:
        _fail("json_too_large")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result = dict(items)
        if len(result) != len(items):
            _fail("json_duplicate_key")
        return result

    try:
        return json.loads(
            payload,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: _fail("json_constant_invalid"),
        )
    except WorkerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("json_invalid", error)


def _exact(value: object, keys: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys or not all(isinstance(key, str) for key in value):
        _fail(code)
    return value


def _validate_runtime_path(value: object, code: str) -> str:
    if not isinstance(value, str):
        _fail(code)
    path = PurePosixPath(value)
    if (
        not value
        or not path.is_absolute()
        or path.as_posix() != value
        or ".." in path.parts
        or path == RUNTIME_ROOT
        or not path.is_relative_to(RUNTIME_ROOT)
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        _fail(code)
    return value


def _open_private_parent(path: Path, code: str) -> tuple[int, os.stat_result]:
    if not path.is_absolute() or ".." in path.parts:
        _fail(code)
    current = -1
    try:
        current = os.open("/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        for part in path.parts[1:-1]:
            following = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            os.close(current)
            current = following
        parent = os.fstat(current)
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            _fail(code)
        return current, parent
    except WorkerError:
        if current >= 0:
            os.close(current)
        raise
    except OSError as error:
        if current >= 0:
            os.close(current)
        _fail(code, error)


def _private_file(path: Path, maximum: int, code: str) -> bytes:
    parent_descriptor, parent_before = _open_private_parent(path, code)
    descriptor = -1
    try:
        before = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
            or not 0 <= before.st_size <= maximum
        ):
            _fail(code)
        descriptor = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_descriptor)
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            total = 0
            while chunk := os.read(descriptor, min(1024 * 1024, maximum + 1)):
                total += len(chunk)
                if total > maximum:
                    _fail(code)
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        fresh = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        parent_after = os.fstat(parent_descriptor)
    except WorkerError:
        raise
    except OSError as error:
        _fail(code, error)
    finally:
        os.close(parent_descriptor)
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_nlink,
        item.st_uid,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(fresh)
        or (parent_before.st_dev, parent_before.st_ino, parent_before.st_mode, parent_before.st_uid)
        != (parent_after.st_dev, parent_after.st_ino, parent_after.st_mode, parent_after.st_uid)
    ):
        _fail(code)
    return b"".join(chunks)


def _site_identity(status: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_nlink,
        status.st_uid,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _runtime_site_tree_record(root: Path, site_directory: str) -> dict[str, object]:
    if (
        not root.is_absolute()
        or root.as_posix() != str(root)
        or ".." in root.parts
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in str(root))
    ):
        _fail("worker_site_invalid")
    site_path = PurePosixPath(site_directory)
    if (
        not site_directory
        or site_path.is_absolute()
        or site_path.as_posix() != site_directory
        or any(part in {"", ".", ".."} for part in site_path.parts)
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in site_directory)
    ):
        _fail("worker_site_invalid")
    parent_descriptor, _ = _open_private_parent(root, "worker_site_invalid")
    root_descriptor = -1
    directories: list[dict[str, object]] = []
    files: list[dict[str, object]] = []
    total_size = 0

    def validate_directory(status: os.stat_result) -> None:
        if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.geteuid() or stat.S_IMODE(status.st_mode) != 0o500:
            _fail("worker_site_invalid")

    def walk(directory_descriptor: int, prefix: PurePosixPath) -> None:
        nonlocal total_size
        before = os.fstat(directory_descriptor)
        validate_directory(before)
        names = sorted(os.listdir(directory_descriptor))
        for name in names:
            if (
                not name
                or name in {".", ".."}
                or "/" in name
                or any(ord(character) < 0x20 or ord(character) == 0x7F for character in name)
            ):
                _fail("worker_site_invalid")
            relative = prefix / name
            relative_text = relative.as_posix()
            listed = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if stat.S_ISDIR(listed.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_descriptor,
                )
                try:
                    opened = os.fstat(child)
                    if _site_identity(listed) != _site_identity(opened):
                        _fail("worker_site_invalid")
                    validate_directory(opened)
                    directories.append({"path": relative_text, "mode": stat.S_IMODE(opened.st_mode)})
                    walk(child, relative)
                    after = os.fstat(child)
                finally:
                    os.close(child)
                fresh = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
                if _site_identity(opened) != _site_identity(after) or _site_identity(after) != _site_identity(fresh):
                    _fail("worker_site_invalid")
                continue
            if (
                not stat.S_ISREG(listed.st_mode)
                or listed.st_uid != os.geteuid()
                or listed.st_nlink != 1
                or stat.S_IMODE(listed.st_mode) not in {0o400, 0o500}
                or not 0 <= listed.st_size <= MAX_WORKER_SITE_BYTES
                or "__pycache__" in relative.parts
                or relative_text.endswith((".pyc", ".pyo", ".pth", ".egg-link"))
                or relative.name in {"sitecustomize.py", "usercustomize.py"}
            ):
                _fail("worker_site_invalid")
            descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_descriptor)
            try:
                opened = os.fstat(descriptor)
                digest = hashlib.sha256()
                size = 0
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    if size > MAX_WORKER_SITE_BYTES:
                        _fail("worker_site_invalid")
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            fresh = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if (
                _site_identity(listed) != _site_identity(opened)
                or _site_identity(opened) != _site_identity(after)
                or _site_identity(after) != _site_identity(fresh)
                or size != listed.st_size
            ):
                _fail("worker_site_invalid")
            total_size += size
            if total_size > MAX_WORKER_SITE_BYTES or len(files) >= MAX_WORKER_SITE_FILES:
                _fail("worker_site_invalid")
            files.append(
                {
                    "path": relative_text,
                    "mode": stat.S_IMODE(listed.st_mode),
                    "size": size,
                    "sha256": digest.hexdigest(),
                }
            )
        after_directory = os.fstat(directory_descriptor)
        if _site_identity(before) != _site_identity(after_directory):
            _fail("worker_site_invalid")

    try:
        listed_root = os.stat(root.name, dir_fd=parent_descriptor, follow_symlinks=False)
        root_descriptor = os.open(
            root.name,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        opened_root = os.fstat(root_descriptor)
        if _site_identity(listed_root) != _site_identity(opened_root):
            _fail("worker_site_invalid")
        validate_directory(opened_root)
        walk(root_descriptor, PurePosixPath())
        after_root = os.fstat(root_descriptor)
        fresh_root = os.stat(root.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if _site_identity(opened_root) != _site_identity(after_root) or _site_identity(after_root) != _site_identity(
            fresh_root
        ):
            _fail("worker_site_invalid")
    except WorkerError:
        raise
    except OSError as error:
        _fail("worker_site_invalid", error)
    finally:
        if root_descriptor >= 0:
            os.close(root_descriptor)
        os.close(parent_descriptor)
    if site_directory not in {str(item["path"]) for item in directories} or not files:
        _fail("worker_site_invalid")
    return {
        "schema_version": 1,
        "python": {
            "implementation": sys.implementation.name,
            "major": sys.version_info.major,
            "minor": sys.version_info.minor,
            "machine": platform.machine(),
        },
        "site_directory": site_directory,
        "directories": sorted(directories, key=lambda item: str(item["path"])),
        "files": sorted(files, key=lambda item: str(item["path"])),
    }


def _verified_worker_site(
    root: Path,
    manifest_path: Path,
    expected_sha256: str,
) -> tuple[dict[str, object], Path]:
    if not _is_sha256(expected_sha256):
        _fail("worker_site_invalid")
    payload = _private_file(manifest_path, MAX_JSON_BYTES, "worker_site_invalid")
    if _sha256(payload) != expected_sha256:
        _fail("worker_site_invalid")
    manifest = _exact(
        _strict_json(payload),
        {"schema_version", "python", "site_directory", "directories", "files"},
        "worker_site_invalid",
    )
    target = _exact(
        manifest["python"],
        {"implementation", "major", "minor", "machine"},
        "worker_site_invalid",
    )
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or target
        != {
            "implementation": sys.implementation.name,
            "major": sys.version_info.major,
            "minor": sys.version_info.minor,
            "machine": platform.machine(),
        }
    ):
        _fail("worker_site_invalid")
    observed = _runtime_site_tree_record(root, str(manifest["site_directory"]))
    if observed != manifest:
        _fail("worker_site_invalid")
    return manifest, root / str(manifest["site_directory"])


def _activate_worker_site() -> None:
    global _WORKER_SITE_DIRECTORY, _WORKER_SITE_MANIFEST_SHA256, _WORKER_SITE_RECORD, _WORKER_SITE_ROOT

    root = Path(os.environ.get("SANDOQ_CATALOG_WORKER_SITE_ROOT", ""))
    manifest_path = Path(os.environ.get("SANDOQ_CATALOG_WORKER_SITE_MANIFEST", ""))
    expected_sha256 = os.environ.get("SANDOQ_CATALOG_WORKER_SITE_MANIFEST_SHA256", "")
    manifest, site = _verified_worker_site(root, manifest_path, expected_sha256)
    bootstrap_packages = ("aiohttp", "packaging", "prime_sandboxes", "sandoq_client", "sandoq_provider")
    if any(name == package or name.startswith(f"{package}.") for name in sys.modules for package in bootstrap_packages):
        _fail("worker_site_invalid")
    if _WORKER_SITE_ROOT is not None and (
        _WORKER_SITE_ROOT != root or _WORKER_SITE_DIRECTORY != site or _WORKER_SITE_MANIFEST_SHA256 != expected_sha256
    ):
        _fail("worker_site_invalid")
    _WORKER_SITE_ROOT = root
    _WORKER_SITE_DIRECTORY = site
    _WORKER_SITE_MANIFEST_SHA256 = expected_sha256
    _WORKER_SITE_RECORD = manifest
    if str(site) not in sys.path:
        sys.path.insert(0, str(site))


def _atomic_private_write(path: Path, payload: bytes) -> None:
    parent_descriptor, parent_before = _open_private_parent(path, "worker_output_invalid")
    temporary = f".{path.name}.{os.getpid()}.tmp"
    descriptor = -1
    try:
        try:
            os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            _fail("worker_output_invalid")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_descriptor,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _fail("worker_output_invalid")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o400)
        os.close(descriptor)
        descriptor = -1
        os.link(
            temporary,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        os.unlink(temporary, dir_fd=parent_descriptor)
        final = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if not stat.S_ISREG(final.st_mode) or final.st_nlink != 1 or stat.S_IMODE(final.st_mode) != 0o400:
            _fail("worker_output_invalid")
        parent_after = os.fstat(parent_descriptor)
        if (
            parent_before.st_dev,
            parent_before.st_ino,
            parent_before.st_mode,
            parent_before.st_uid,
        ) != (
            parent_after.st_dev,
            parent_after.st_ino,
            parent_after.st_mode,
            parent_after.st_uid,
        ):
            _fail("worker_output_invalid")
        os.fsync(parent_descriptor)
    except WorkerError:
        raise
    except OSError as error:
        _fail("worker_output_invalid", error)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_descriptor)
        os.close(parent_descriptor)


def cleanup_receipt_verifier_sha256() -> str:
    return _sha256(_canonical(CLEANUP_RECEIPT_VERIFIER_CONTRACT))


def _provider_source_record(
    source_root: Path,
    *,
    exact_staged_tree: bool = False,
) -> tuple[dict[str, object], dict[str, bytes]]:
    root_descriptor = -1
    package_descriptor = -1
    try:
        root_descriptor = os.open(
            source_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        package_descriptor = os.open(
            "sandoq_provider",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_descriptor,
        )
        root_identity = os.fstat(root_descriptor)
        package_identity = os.fstat(package_descriptor)
        if (
            not stat.S_ISDIR(root_identity.st_mode)
            or not stat.S_ISDIR(package_identity.st_mode)
            or (
                exact_staged_tree
                and (
                    root_identity.st_uid != os.geteuid()
                    or package_identity.st_uid != os.geteuid()
                    or stat.S_IMODE(root_identity.st_mode) != 0o700
                    or stat.S_IMODE(package_identity.st_mode) != 0o700
                    or os.listdir(root_descriptor) != ["sandoq_provider"]
                    or sorted(os.listdir(package_descriptor)) != sorted(_PROVIDER_FILES)
                )
            )
        ):
            _fail("provider_source_invalid")
        observed_names = sorted(name for name in os.listdir(package_descriptor) if name.endswith(".py"))
        if observed_names != sorted(_PROVIDER_FILES):
            _fail("provider_source_invalid")
        records: list[dict[str, object]] = []
        payloads: dict[str, bytes] = {}
        for name in sorted(_PROVIDER_FILES):
            descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=package_descriptor)
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or (exact_staged_tree and (before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o400))
                ):
                    _fail("provider_source_invalid")
                chunks: list[bytes] = []
                while chunk := os.read(descriptor, 1024 * 1024):
                    chunks.append(chunk)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                _fail("provider_source_invalid")
            payload = b"".join(chunks)
            expected_sha256, expected_size = _PROVIDER_FILES[name]
            if len(payload) != expected_size or _sha256(payload) != expected_sha256:
                _fail("provider_source_invalid")
            records.append({"path": name, "sha256": expected_sha256, "size": expected_size})
            payloads[name] = payload
        if (
            (
                os.fstat(root_descriptor).st_dev,
                os.fstat(root_descriptor).st_ino,
                os.fstat(root_descriptor).st_mode,
                os.fstat(root_descriptor).st_ctime_ns,
            )
            != (
                root_identity.st_dev,
                root_identity.st_ino,
                root_identity.st_mode,
                root_identity.st_ctime_ns,
            )
            or (
                os.fstat(package_descriptor).st_dev,
                os.fstat(package_descriptor).st_ino,
                os.fstat(package_descriptor).st_mode,
                os.fstat(package_descriptor).st_ctime_ns,
            )
            != (
                package_identity.st_dev,
                package_identity.st_ino,
                package_identity.st_mode,
                package_identity.st_ctime_ns,
            )
            or (
                exact_staged_tree
                and (
                    os.listdir(root_descriptor) != ["sandoq_provider"]
                    or sorted(os.listdir(package_descriptor)) != sorted(_PROVIDER_FILES)
                )
            )
        ):
            _fail("provider_source_invalid")
    except WorkerError:
        raise
    except OSError as error:
        _fail("provider_source_invalid", error)
    finally:
        if package_descriptor >= 0:
            os.close(package_descriptor)
        if root_descriptor >= 0:
            os.close(root_descriptor)
    record = {
        "schema_version": 1,
        "provider_commit": PINNED_PROVIDER_COMMIT,
        "files": records,
    }
    if _sha256(_canonical(record)) != PINNED_PROVIDER_SOURCE_SHA256:
        _fail("provider_source_invalid")
    return record, payloads


def _module_payload() -> bytes:
    path = Path(__file__)
    descriptor = -1
    try:
        listed = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        fresh = path.lstat()
    except OSError as error:
        _fail("worker_module_invalid", error)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    payload = b"".join(chunks)
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_nlink,
        item.st_uid,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if (
        not stat.S_ISREG(listed.st_mode)
        or listed.st_nlink != 1
        or identity(listed) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(fresh)
    ):
        _fail("worker_module_invalid")
    return payload


def _distribution_record(
    name: str,
    distribution: importlib.metadata.Distribution,
) -> tuple[dict[str, object], set[str]]:
    if _WORKER_SITE_ROOT is None or _WORKER_SITE_RECORD is None:
        _fail("worker_site_invalid")
    files = distribution.files
    if not files:
        _fail("worker_runtime_invalid")
    manifest_files = {
        str(item["path"]): item
        for item in _WORKER_SITE_RECORD["files"]  # type: ignore[union-attr]
    }
    records: list[dict[str, object]] = []
    claimed: set[str] = set()
    for relative in sorted(files, key=lambda item: str(item)):
        relative_text = str(relative)
        relative_path = PurePosixPath(relative_text)
        if (
            relative_path.is_absolute()
            or relative_path.as_posix() != relative_text
            or any(part in {"", "."} for part in relative_path.parts)
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in relative_text)
        ):
            _fail("worker_runtime_invalid")
        path = Path(os.path.abspath(distribution.locate_file(relative)))
        try:
            resolved = path.resolve(strict=True)
            if resolved != path or not path.is_relative_to(_WORKER_SITE_ROOT):
                _fail("worker_runtime_invalid")
            status = path.lstat()
        except OSError as error:
            _fail("worker_runtime_invalid", error)
        if stat.S_ISDIR(status.st_mode):
            continue
        if not stat.S_ISREG(status.st_mode) or path.is_symlink():
            _fail("worker_runtime_invalid")
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(descriptor)
                digest = hashlib.sha256()
                size = 0
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            _fail("worker_runtime_invalid", error)
        if (
            status.st_dev,
            status.st_ino,
            status.st_mode,
            status.st_size,
            status.st_mtime_ns,
            status.st_ctime_ns,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            _fail("worker_runtime_invalid")
        manifest_path = path.relative_to(_WORKER_SITE_ROOT).as_posix()
        expected = manifest_files.get(manifest_path)
        if expected != {
            "path": manifest_path,
            "mode": stat.S_IMODE(status.st_mode),
            "size": size,
            "sha256": digest.hexdigest(),
        }:
            _fail("worker_runtime_invalid")
        records.append({"path": manifest_path, "sha256": digest.hexdigest(), "size": size})
        claimed.add(manifest_path)
    if not records:
        _fail("worker_runtime_invalid")
    return {"name": name, "version": distribution.version, "files": records}, claimed


def _runtime_distributions() -> tuple[dict[str, importlib.metadata.Distribution], tuple[str, ...]]:
    """Return the active transitive distribution closure used by the worker."""

    try:
        from packaging.markers import default_environment
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
    except ImportError as error:
        _fail("worker_runtime_invalid", error)
    if _WORKER_SITE_DIRECTORY is None:
        _fail("worker_site_invalid")
    available: dict[str, importlib.metadata.Distribution] = {}
    for distribution in importlib.metadata.distributions(path=[str(_WORKER_SITE_DIRECTORY)]):
        raw_name = distribution.metadata.get("Name")
        if not isinstance(raw_name, str) or not raw_name:
            _fail("worker_runtime_invalid")
        name = canonicalize_name(raw_name)
        if name in available:
            _fail("worker_runtime_invalid")
        available[name] = distribution
    roots = ("aiohttp", "packaging", "prime-sandboxes", "sandoq-client")
    pending = [(Requirement(root), frozenset()) for root in roots]
    visited: set[tuple[str, str, tuple[str, ...]]] = set()
    selected: set[str] = set()
    while pending:
        requirement, parent_extras = pending.pop()
        name = canonicalize_name(requirement.name)
        key = (name, str(requirement.specifier), tuple(sorted(parent_extras)))
        if key in visited:
            continue
        visited.add(key)
        distribution = available.get(name)
        if distribution is None or (
            requirement.specifier and not requirement.specifier.contains(distribution.version, prereleases=True)
        ):
            _fail("worker_runtime_invalid")
        selected.add(name)
        environments = []
        for extra in parent_extras or {""}:
            environment = default_environment()
            environment["extra"] = extra
            environments.append(environment)
        for dependency_text in distribution.requires or ():
            try:
                dependency = Requirement(dependency_text)
            except ValueError as error:
                _fail("worker_runtime_invalid", error)
            if dependency.marker is not None and not any(
                dependency.marker.evaluate(environment) for environment in environments
            ):
                continue
            pending.append((dependency, frozenset(dependency.extras)))
    if selected != set(available):
        _fail("worker_runtime_extra_distribution")
    return available, tuple(sorted(selected))


def _validate_runtime_site_ownership(claimed: set[str]) -> None:
    if _WORKER_SITE_RECORD is None:
        _fail("worker_site_invalid")
    manifest_files = {str(item["path"]) for item in _WORKER_SITE_RECORD["files"]}  # type: ignore[union-attr]
    expected_directories: set[str] = set()
    for filename in claimed:
        parent = PurePosixPath(filename).parent
        while parent != PurePosixPath("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    manifest_directories = {str(item["path"]) for item in _WORKER_SITE_RECORD["directories"]}  # type: ignore[union-attr]
    if claimed != manifest_files or expected_directories != manifest_directories:
        _fail("worker_runtime_extra_file")


def _runtime_record() -> dict[str, object]:
    if _WORKER_SITE_ROOT is None or _WORKER_SITE_DIRECTORY is None or _WORKER_SITE_RECORD is None:
        _fail("worker_site_invalid")
    observed_site = _runtime_site_tree_record(
        _WORKER_SITE_ROOT,
        _WORKER_SITE_DIRECTORY.relative_to(_WORKER_SITE_ROOT).as_posix(),
    )
    if observed_site != _WORKER_SITE_RECORD:
        _fail("worker_site_invalid")
    source_root = Path(os.environ.get("SANDOQ_PROVIDER_ROOT", ""))
    if not source_root.is_absolute():
        _fail("provider_source_invalid")
    provider, _ = _provider_source_record(source_root)
    available, selected = _runtime_distributions()
    distributions: list[dict[str, object]] = []
    claimed: set[str] = set()
    for name in selected:
        record, distribution_claims = _distribution_record(name, available[name])
        if claimed.intersection(distribution_claims):
            _fail("worker_runtime_duplicate_file")
        claimed.update(distribution_claims)
        distributions.append(record)
    _validate_runtime_site_ownership(claimed)
    versions = {str(record["name"]): str(record["version"]) for record in distributions}
    if versions["sandoq-client"] != PINNED_SANDOQ_CLIENT:
        _fail("worker_runtime_invalid")
    executable = Path(sys.executable).resolve(strict=True)
    try:
        executable_payload = executable.read_bytes()
    except OSError as error:
        _fail("worker_runtime_invalid", error)
    return {
        "schema_version": 1,
        "python_version": sys.version,
        "python_executable_sha256": _sha256(executable_payload),
        "worker_module_sha256": _sha256(_module_payload()),
        "provider_commit": PINNED_PROVIDER_COMMIT,
        "provider_tree": PINNED_PROVIDER_TREE,
        "provider_source_sha256": _sha256(_canonical(provider)),
        "python_runtime_manifest_sha256": os.environ["SANDOQ_CATALOG_PYTHON_RUNTIME_MANIFEST_SHA256"],
        "worker_provision_identity_sha256": os.environ["SANDOQ_CATALOG_WORKER_PROVISION_IDENTITY_SHA256"],
        "worker_site_manifest_sha256": _WORKER_SITE_MANIFEST_SHA256,
        "distributions": distributions,
    }


def worker_runtime_sha256() -> str:
    return _sha256(_canonical(_runtime_record()))


def _stage_provider_source(destination: Path) -> None:
    global _STAGED_PROVIDER_ROOT

    source_root = Path(os.environ["SANDOQ_PROVIDER_ROOT"])
    _, payloads = _provider_source_record(source_root)
    package = destination / "sandoq_provider"
    if destination.exists():
        status = destination.lstat()
        if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700 or status.st_uid != os.geteuid():
            _fail("provider_staging_invalid")
        _provider_source_record(destination, exact_staged_tree=True)
        if "sandoq_provider" in sys.modules:
            _fail("provider_staging_invalid")
        _STAGED_PROVIDER_ROOT = destination
        sys.path.insert(0, str(destination))
        return
    destination.mkdir(mode=0o700)
    package.mkdir(mode=0o700)
    for name, payload in payloads.items():
        path = package / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    _fail("provider_staging_invalid")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    package_descriptor = os.open(package, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    try:
        os.fsync(package_descriptor)
    finally:
        os.close(package_descriptor)
    destination_descriptor = os.open(destination, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    try:
        os.fsync(destination_descriptor)
    finally:
        os.close(destination_descriptor)
    _provider_source_record(destination, exact_staged_tree=True)
    if "sandoq_provider" in sys.modules:
        _fail("provider_staging_invalid")
    _STAGED_PROVIDER_ROOT = destination
    sys.path.insert(0, str(destination))


def _validate_environment() -> None:
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
        _fail("worker_environment_invalid")
    if any(os.environ.get(name) != value for name, value in _REQUIRED_ENVIRONMENT.items()):
        _fail("worker_environment_invalid")
    if any(not os.environ.get(name) for name in _REQUIRED_ENVIRONMENT_NAMES):
        _fail("worker_environment_invalid")
    if (
        os.environ["OCI_RUNNER_ECR_REGION"] != "us-east-2"
        or os.environ["OCI_RUNNER_ECR_PULL_THROUGH_PREFIX"] != "pt_dockerio"
    ):
        _fail("worker_environment_invalid")
    for name in (
        "OCI_RUNNER_ECR_TOKEN_FILE",
        "OCI_RUNNER_ECR_TOKEN_METADATA_PATH",
        "OCI_RUNNER_POOL_SOCKET",
        "OCI_RUNNER_POOL_WAL",
        "OCI_RUNNER_TOKEN_FILE",
        "SANDOQ_CATALOG_WORKER_MODULE",
        "SANDOQ_CATALOG_WORKER_PYTHON",
        "SANDOQ_CATALOG_WORKER_SITE_MANIFEST",
        "SANDOQ_CATALOG_WORKER_SITE_ROOT",
        "SANDOQ_PROVIDER_ROOT",
    ):
        value = os.environ[name]
        if not Path(value).is_absolute() or ".." in Path(value).parts:
            _fail("worker_environment_invalid")
    module_path = Path(os.environ["SANDOQ_CATALOG_WORKER_MODULE"])
    python_path = Path(os.environ["SANDOQ_CATALOG_WORKER_PYTHON"])
    try:
        if (
            module_path.is_symlink()
            or module_path != Path(__file__)
            or python_path.is_symlink()
            or python_path.resolve(strict=True) != Path(sys.executable).resolve(strict=True)
        ):
            _fail("worker_environment_invalid")
    except OSError as error:
        _fail("worker_environment_invalid", error)
    if _DIGEST_IMAGE_RE.fullmatch(os.environ["SANDOQ_CATALOG_BUILDER_IMAGE"]) is None:
        _fail("worker_environment_invalid")
    if not all(
        _is_sha256(os.environ[name])
        for name in (
            "SANDOQ_CATALOG_PYTHON_RUNTIME_MANIFEST_SHA256",
            "SANDOQ_CATALOG_WORKER_PROVISION_IDENTITY_SHA256",
            "SANDOQ_CATALOG_WORKER_SITE_MANIFEST_SHA256",
        )
    ):
        _fail("worker_environment_invalid")
    _activate_worker_site()


def _prepare_provider_paths() -> None:
    wal = Path(os.environ["OCI_RUNNER_POOL_WAL"])
    socket = Path(os.environ["OCI_RUNNER_POOL_SOCKET"])
    if wal == socket or wal.parent == socket or socket.parent == wal:
        _fail("provider_paths_invalid")
    wal_parent, _ = _open_private_parent(wal, "provider_paths_invalid")
    try:
        try:
            descriptor = os.open(
                wal.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=wal_parent,
            )
        except FileExistsError:
            descriptor = -1
        if descriptor >= 0:
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(wal_parent)
    finally:
        os.close(wal_parent)
    _private_file(wal, MAX_JSON_BYTES, "provider_wal_invalid")
    socket_parent, _ = _open_private_parent(socket, "provider_paths_invalid")
    try:
        try:
            socket_status = os.stat(socket.name, dir_fd=socket_parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if (
            not stat.S_ISSOCK(socket_status.st_mode)
            or socket_status.st_uid != os.geteuid()
            or stat.S_IMODE(socket_status.st_mode) != 0o700
        ):
            _fail("provider_paths_invalid")
    finally:
        os.close(socket_parent)


def _validate_requirements(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 256:
        _fail("worker_request_invalid")
    requirements: list[str] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, str) or _EXACT_REQUIREMENT_RE.fullmatch(item) is None:
            _fail("worker_request_invalid")
        name = re.sub(r"[-_.]+", "-", item.partition("[")[0].partition("==")[0].lower())
        if name in names:
            _fail("worker_request_invalid")
        names.add(name)
        requirements.append(item)
    return tuple(requirements)


@dataclass
class RemoteSession:
    client: Any
    registry: Any
    sandbox_id: str
    runtime_name: str
    outer_session_id: str
    metadata: dict[str, object]


class SessionBackend(Protocol):
    async def anchor_status(self) -> dict[str, object]: ...

    async def anchor_heartbeat(self) -> dict[str, object]: ...

    async def recover(self, reason: str) -> dict[str, object]: ...

    async def start(self, image: str, request_sha256: str, *, network: str) -> RemoteSession: ...

    async def upload(self, session: RemoteSession, path: str, payload: bytes) -> None: ...

    async def download(self, session: RemoteSession, path: str) -> bytes: ...

    async def execute(
        self,
        session: RemoteSession,
        command: str,
        *,
        timeout: int,
        environment: dict[str, str] | None = None,
    ) -> tuple[int, str, str]: ...

    async def cleanup(
        self,
        session: RemoteSession,
        reason: str,
        *,
        poison: bool,
    ) -> dict[str, object]: ...


class PinnedSandoqBackend:
    """Thin adapter over the exact provider source pinned above."""

    def __init__(self) -> None:
        if _STAGED_PROVIDER_ROOT is None:
            _fail("provider_staging_invalid")
        from sandoq_provider import registry
        from sandoq_provider.oci_client import OCIRunnerAsyncSandboxClient

        _provider_source_record(_STAGED_PROVIDER_ROOT, exact_staged_tree=True)
        package_root = _STAGED_PROVIDER_ROOT / "sandoq_provider"
        for name, module in tuple(sys.modules.items()):
            if name != "sandoq_provider" and not name.startswith("sandoq_provider."):
                continue
            module_file = getattr(module, "__file__", None)
            if not isinstance(module_file, str):
                _fail("provider_staging_invalid")
            module_path = Path(module_file)
            expected_name = "__init__.py" if name == "sandoq_provider" else f"{name.rpartition('.')[2]}.py"
            if (
                module_path.parent != package_root
                or module_path.name != expected_name
                or expected_name not in _PROVIDER_FILES
            ):
                _fail("provider_staging_invalid")
        _provider_source_record(_STAGED_PROVIDER_ROOT, exact_staged_tree=True)
        self._registry = registry
        self._client_type = OCIRunnerAsyncSandboxClient

    async def anchor_status(self) -> dict[str, object]:
        from sandoq_provider.pool import get_pool_client

        client = await asyncio.to_thread(get_pool_client)
        return await asyncio.to_thread(client._request, "status", 10.0)  # noqa: SLF001 - pinned API.

    async def anchor_heartbeat(self) -> dict[str, object]:
        from sandoq_provider.pool import get_pool_client

        client = await asyncio.to_thread(get_pool_client)
        heartbeat = await asyncio.to_thread(client._request, "heartbeat", 10.0)  # noqa: SLF001 - pinned API.
        if heartbeat.get("heartbeat") is not True:
            _fail("provider_anchor_unverified")
        return await asyncio.to_thread(client._request, "status", 10.0)  # noqa: SLF001 - pinned API.

    async def recover(self, reason: str) -> dict[str, object]:
        from sandoq_provider.pool import get_pool_client

        client = await asyncio.to_thread(get_pool_client)
        deadline = time.monotonic() + 60.0
        while True:
            status = await asyncio.to_thread(client._request, "status", 10.0)  # noqa: SLF001 - pinned API.
            if status.get("recovering") is False:
                break
            if time.monotonic() >= deadline:
                _fail("provider_recovery_timeout")
            await asyncio.sleep(0.1)
        return await asyncio.to_thread(client.drain, reason)

    async def start(self, image: str, request_sha256: str, *, network: str) -> RemoteSession:
        if (
            network not in {"none", "trusted-builder"}
            or _DIGEST_IMAGE_RE.fullmatch(image) is None
            or not _is_sha256(request_sha256)
        ):
            _fail("provider_network_invalid")
        previous_network = os.environ["OCI_RUNNER_TASK_NETWORK"]
        os.environ["OCI_RUNNER_TASK_NETWORK"] = "none" if network == "none" else "host"
        try:
            client = self._client_type()
        finally:
            os.environ["OCI_RUNNER_TASK_NETWORK"] = previous_network
        runtime_name = f"offline-catalog-{request_sha256[:24]}"
        context = {
            "requested_image": image,
            "working_dir": "/tmp",
            "cpu": 2,
            "memory": 8,
            "disk": 20,
        }
        token = self._registry.bind_task_context(context)
        sandbox = None
        try:
            try:
                sandbox = await client.create(
                    SimpleNamespace(
                        name=runtime_name,
                        docker_image=image,
                        environment_vars={"OCI_EXPECTED_WORKDIR": "/tmp"},
                        cpu_cores=2,
                        memory_gb=8,
                        disk_size_gb=20,
                        start_command=None,
                    )
                )
                await client.wait_for_creation(sandbox.id)
                metadata = await client.session_metadata(sandbox.id)
                outer = metadata.get("outer_session_id")
                expected_digest = "sha256:" + image.rpartition("@sha256:")[2]
                if (
                    metadata.get("environment") != "oci-runner-firecracker"
                    or metadata.get("task_network") != ("none" if network == "none" else "host")
                    or metadata.get("requested_image") != image
                    or metadata.get("resolved_digest") != expected_digest
                    or not isinstance(outer, str)
                    or not outer
                ):
                    _fail("provider_runtime_attestation_invalid")
            except BaseException as primary_error:

                async def cleanup_failed_start() -> None:
                    cleanup_errors: list[BaseException] = []
                    if sandbox is not None:
                        with contextlib.suppress(BaseException):
                            await client.poison_assignment(
                                sandbox.id,
                                reason="catalog_start_failed",
                            )
                        try:
                            await client.delete(sandbox.id)
                        except BaseException as error:
                            cleanup_errors.append(error)
                    if len(cleanup_errors) == 1:
                        raise cleanup_errors[0]
                    if cleanup_errors:
                        raise BaseExceptionGroup("ambiguous create cleanup failed", cleanup_errors)

                cleanup_task = asyncio.create_task(cleanup_failed_start())
                cleanup_error: BaseException | None = None
                interrupted = False
                while not cleanup_task.done():
                    try:
                        await asyncio.shield(cleanup_task)
                    except asyncio.CancelledError:
                        interrupted = True
                    except BaseException as error:
                        cleanup_error = error
                        break
                if cleanup_error is None:
                    try:
                        cleanup_task.result()
                    except BaseException as error:
                        cleanup_error = error
                if cleanup_error is not None:
                    raise primary_error.with_traceback(primary_error.__traceback__) from cleanup_error
                if interrupted and not isinstance(primary_error, asyncio.CancelledError):
                    raise asyncio.CancelledError from primary_error
                raise primary_error.with_traceback(primary_error.__traceback__)
            return RemoteSession(client, self._registry, sandbox.id, runtime_name, outer, metadata)
        finally:
            self._registry.reset_task_context(token)

    async def upload(self, session: RemoteSession, path: str, payload: bytes) -> None:
        await session.client.upload_bytes(session.sandbox_id, path, payload)

    async def download(self, session: RemoteSession, path: str) -> bytes:
        payload = await session.client._download_bytes(session.sandbox_id, path, 300)  # noqa: SLF001 - pinned API.
        if len(payload) > MAX_ARCHIVE_BYTES:
            _fail("provider_download_too_large")
        return payload

    async def execute(
        self,
        session: RemoteSession,
        command: str,
        *,
        timeout: int,
        environment: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        if environment:
            prefix = " ".join(f"{name}={shlex.quote(value)}" for name, value in sorted(environment.items()))
            command = f"env {prefix} {command}"
        result = await session.client.execute_idempotent_command(
            session.sandbox_id,
            command,
            timeout=timeout,
        )
        stdout = str(result.stdout or "")
        stderr = str(result.stderr or "")
        if len(stdout.encode()) + len(stderr.encode()) > MAX_COMMAND_OUTPUT_BYTES:
            _fail("provider_command_output_too_large")
        return int(result.exit_code), stdout, stderr

    async def cleanup(
        self,
        session: RemoteSession,
        reason: str,
        *,
        poison: bool,
    ) -> dict[str, object]:
        if poison:
            with contextlib.suppress(BaseException):
                await session.client.poison_assignment(session.sandbox_id, reason=reason)
        try:
            release = await session.client.delete(session.sandbox_id)
            registry_receipt = session.registry.pop_cleanup_receipt(session.runtime_name)
        except BaseException as error:
            raise error.with_traceback(error.__traceback__)
        return {
            "release": release,
            "registry_receipt": registry_receipt,
            "assignment_id": session.sandbox_id,
            "runtime_name": session.runtime_name,
            "outer_session_id": session.outer_session_id,
        }


NETWORK_PROBE_CODE = r"""import json
from pathlib import Path

interfaces = sorted(path.name for path in Path('/sys/class/net').iterdir())
default_route = False
for route in (Path('/proc/net/route'), Path('/proc/net/ipv6_route')):
    try:
        rows = route.read_text().splitlines()[1:]
    except OSError:
        rows = []
    for row in rows:
        fields = row.split()
        if len(fields) >= 2 and set(fields[1]) == {'0'}:
            default_route = True
print(json.dumps({
    'default_route': default_route,
    'interfaces': interfaces,
    'network': 'none' if interfaces == ['lo'] and not default_route else 'present',
}, sort_keys=True, separators=(',', ':')))
""".strip()


BUILDER_PROBE_CODE = r"""import json
import platform
import pip

print(json.dumps({
    'pip_version': pip.__version__,
    'python_version': platform.python_version(),
}, sort_keys=True, separators=(',', ':')))
""".strip()


INVENTORY_PROBE_CODE = r"""import hashlib
import importlib.metadata as metadata
import json
import platform
import sys
import sysconfig

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.tags import sys_tags
    from packaging.utils import canonicalize_name
except ModuleNotFoundError:
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.tags import sys_tags
    from pip._vendor.packaging.utils import canonicalize_name

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()

def digest(distributions):
    return hashlib.sha256(canonical({
        'schema_version': 1,
        'distributions': distributions,
    })).hexdigest()

try:
    payload = open(sys.argv[1], 'rb').read()
    if hashlib.sha256(payload).hexdigest() != sys.argv[2]:
        raise RuntimeError
    control = json.loads(payload)
    if set(control) != {'schema_version', 'requirements', 'requirements_sha256'}:
        raise RuntimeError
    if type(control['schema_version']) is not int or control['schema_version'] != 1:
        raise RuntimeError
    available = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get('Name')
        version = distribution.version
        if not name or not version:
            raise RuntimeError
        key = canonicalize_name(name)
        if key in available:
            raise RuntimeError
        available[key] = distribution
    inventory = sorted([[name, distribution.version] for name, distribution in available.items()])
    pending = [(Requirement(text), frozenset(Requirement(text).extras)) for text in control['requirements']]
    visited = set()
    resolved = set()
    satisfied = True
    while pending:
        requirement, parent_extras = pending.pop()
        name = canonicalize_name(requirement.name)
        key = (name, str(requirement.specifier), tuple(sorted(parent_extras)))
        if key in visited:
            continue
        visited.add(key)
        distribution = available.get(name)
        if distribution is None or (
            requirement.specifier and not requirement.specifier.contains(distribution.version, prereleases=True)
        ):
            satisfied = False
            break
        resolved.add((name, distribution.version))
        environments = []
        for extra in parent_extras or {''}:
            environment = default_environment()
            environment['extra'] = extra
            environments.append(environment)
        for dependency_text in distribution.requires or ():
            dependency = Requirement(dependency_text)
            if dependency.url is not None:
                raise RuntimeError
            if dependency.marker is not None and not any(
                dependency.marker.evaluate(environment) for environment in environments
            ):
                continue
            pending.append((dependency, frozenset(dependency.extras)))
    closure = sorted([list(item) for item in resolved]) if satisfied else None
    libc_name, libc_version = platform.libc_ver()
    marker_environment = dict(sorted(default_environment().items()))
    supported_tags = sorted({str(tag) for tag in sys_tags()})
    result = {
        'schema_version': 1,
        'runtime_fingerprint': {
            'schema_version': 1,
            'implementation': sys.implementation.name,
            'python_full_version': platform.python_version(),
            'abi': sysconfig.get_config_var('SOABI') or 'none',
            'platform': sysconfig.get_platform(),
            'machine': platform.machine() or 'unknown',
            'libc': f"{libc_name or 'unknown'}-{libc_version or 'unknown'}",
            'pip_version': __import__('pip').__version__,
            'marker_environment_sha256': hashlib.sha256(canonical(marker_environment)).hexdigest(),
            'supported_tags_sha256': hashlib.sha256(canonical(supported_tags)).hexdigest(),
        },
        'marker_environment': marker_environment,
        'supported_tags': supported_tags,
        'installed_inventory': inventory,
        'installed_inventory_sha256': digest(inventory),
        'satisfied': satisfied,
        'closure': ({'distributions': closure, 'sha256': digest(closure)} if closure is not None else None),
    }
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
except BaseException:
    raise SystemExit(1)
""".strip()


CLOSURE_PROBE_CODE = r"""import hashlib
import importlib.metadata as metadata
import json
import sys

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ModuleNotFoundError:
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()

def digest(distributions):
    return hashlib.sha256(canonical({'schema_version': 1, 'distributions': distributions})).hexdigest()

try:
    payload = open(sys.argv[1], 'rb').read()
    if hashlib.sha256(payload).hexdigest() != sys.argv[2]:
        raise RuntimeError
    control = json.loads(payload)
    if set(control) != {
        'schema_version', 'site_directory', 'requirements', 'inventory',
        'inventory_sha256', 'closure', 'closure_sha256',
    } or type(control['schema_version']) is not int or control['schema_version'] != 1:
        raise RuntimeError
    site_directory = control['site_directory']
    available = {}
    iterator = metadata.distributions(path=[site_directory]) if site_directory is not None else metadata.distributions()
    for distribution in iterator:
        name = distribution.metadata.get('Name')
        version = distribution.version
        if not name or not version:
            raise RuntimeError
        key = canonicalize_name(name)
        if key in available:
            raise RuntimeError
        available[key] = distribution
    inventory = sorted([[name, distribution.version] for name, distribution in available.items()])
    if inventory != control['inventory'] or digest(inventory) != control['inventory_sha256']:
        raise RuntimeError
    pending = [(Requirement(text), frozenset(Requirement(text).extras)) for text in control['requirements']]
    visited = set()
    resolved = set()
    while pending:
        requirement, parent_extras = pending.pop()
        name = canonicalize_name(requirement.name)
        key = (name, str(requirement.specifier), tuple(sorted(parent_extras)))
        if key in visited:
            continue
        visited.add(key)
        distribution = available.get(name)
        if distribution is None or (
            requirement.specifier and not requirement.specifier.contains(distribution.version, prereleases=True)
        ):
            raise RuntimeError
        resolved.add((name, distribution.version))
        environments = []
        for extra in parent_extras or {''}:
            environment = default_environment()
            environment['extra'] = extra
            environments.append(environment)
        for dependency_text in distribution.requires or ():
            dependency = Requirement(dependency_text)
            if dependency.url is not None:
                raise RuntimeError
            if dependency.marker is not None and not any(
                dependency.marker.evaluate(environment) for environment in environments
            ):
                continue
            pending.append((dependency, frozenset(dependency.extras)))
    closure = sorted([list(item) for item in resolved])
    if closure != control['closure'] or digest(closure) != control['closure_sha256']:
        raise RuntimeError
except BaseException:
    print('{"status":"failed"}')
    raise SystemExit(1)
print(json.dumps({'count': len(closure), 'status': 'ok'}, sort_keys=True, separators=(',', ':')))
""".strip()


def inventory_probe_code_sha256() -> str:
    return _sha256(INVENTORY_PROBE_CODE.encode())


def inventory_probe_environment_sha256(runtime_sha256: str) -> str:
    return _sha256(
        _canonical(
            {
                "schema_version": 1,
                "runtime_sha256": runtime_sha256,
                "provider_commit": PINNED_PROVIDER_COMMIT,
                "environment": "oci-runner-firecracker",
                "task_network": "none",
            }
        )
    )


def _closure_sha256(distributions: list[list[str]]) -> str:
    return _sha256(_canonical({"schema_version": 1, "distributions": distributions}))


def _requirements_sha256(requirements: tuple[str, ...]) -> str:
    return _sha256(_canonical({"schema_version": 1, "requirements": list(requirements)}))


async def _network_isolated(backend: SessionBackend, session: RemoteSession) -> bool:
    command = f"python3 -c {shlex.quote(NETWORK_PROBE_CODE)}"
    exit_code, stdout, _ = await backend.execute(session, command, timeout=30)
    if exit_code != 0:
        return False
    try:
        record = _exact(
            _strict_json(stdout.encode()), {"default_route", "interfaces", "network"}, "network_probe_invalid"
        )
    except WorkerError:
        return False
    return (
        record["network"] == "none"
        and record["default_route"] is False
        and record["interfaces"] == ["lo"]
        and session.metadata.get("task_network") == "none"
        and session.metadata.get("environment") == "oci-runner-firecracker"
    )


def _wal_snapshot() -> tuple[str, int]:
    path = Path(os.environ["OCI_RUNNER_POOL_WAL"])
    payload = _private_file(path, MAX_JSON_BYTES, "provider_wal_invalid")
    live: set[str] = set()
    for line in payload.splitlines():
        if not line:
            continue
        row = _strict_json(line)
        if not isinstance(row, dict) or type(row.get("schema_version")) is not int:
            _fail("provider_wal_invalid")
        event = row.get("event")
        session_id = row.get("outer_session_id")
        if event == "outer_created":
            if not isinstance(session_id, str) or not session_id:
                _fail("provider_wal_invalid")
            live.add(session_id)
        elif event == "outer_deleted":
            if not isinstance(session_id, str) or not session_id:
                _fail("provider_wal_invalid")
            live.discard(session_id)
    return _sha256(payload), len(live)


def _verify_drain(drain: object, outer_session_id: str | None = None) -> dict[str, object]:
    if not isinstance(drain, dict) or drain.get("drained") is not True or drain.get("failures") != {}:
        _fail("provider_cleanup_unverified")
    deleted = drain.get("deleted")
    if not isinstance(deleted, list):
        _fail("provider_cleanup_unverified")
    matching = []
    for entry in deleted:
        if not isinstance(entry, dict) or entry.get("verified_http_status") != 404:
            _fail("provider_cleanup_unverified")
        if outer_session_id is not None and entry.get("outer_session_id") == outer_session_id:
            matching.append(entry)
    if outer_session_id is not None and len(matching) != 1:
        _fail("provider_cleanup_unverified")
    _, remaining = _wal_snapshot()
    if remaining != 0:
        _fail("provider_cleanup_unverified")
    return matching[0] if matching else {"verified_http_status": 404}


def _provider_cleanup_record(
    request_sha256: str,
    recovery_scope_sha256: str,
    cleanup_verifier_sha256: str,
    cleanup: dict[str, object],
) -> dict[str, object]:
    outer = cleanup.get("outer_session_id")
    assignment = cleanup.get("assignment_id")
    runtime_name = cleanup.get("runtime_name")
    if (
        not isinstance(outer, str)
        or not outer
        or not isinstance(assignment, str)
        or not assignment
        or not isinstance(runtime_name, str)
        or not runtime_name
    ):
        _fail("provider_cleanup_unverified")
    release = cleanup.get("release")
    receipt = cleanup.get("registry_receipt")
    if not isinstance(release, dict) or not isinstance(receipt, dict):
        _fail("provider_cleanup_unverified")
    release_status = release.get("status")
    nested_recycled = (
        release_status == "recycled"
        and release.get("nested_recycle_verified") is True
        and release.get("shell_deleted") is True
        and release.get("outer_session_id") == outer
    )
    outer_deleted = (
        release_status in {"poisoned", "retired", "deleted"}
        and (release.get("outer_deletion_verified_http_status") == 404 or release.get("verified_http_status") == 404)
        and release.get("outer_session_id", outer) == outer
    )
    if (
        release.get("assignment_id", release.get("sandbox_id")) != assignment
        or receipt.get("runtime_name") != runtime_name
        or receipt.get("assignment_id") != assignment
        or receipt.get("outer_session_id") != outer
        or receipt.get("cleanup_verified") is not True
        or receipt.get("shell_deleted") is not True
        or not (nested_recycled or outer_deleted)
    ):
        _fail("provider_cleanup_unverified")
    private_receipt = {
        "schema_version": 2,
        "request_sha256": request_sha256,
        "assignment_sha256": _sha256(assignment.encode()),
        "runtime_name_sha256": _sha256(runtime_name.encode()),
        "outer_session_sha256": _sha256(outer.encode()),
        "nested_cleanup_verified": True,
        "terminal_state": "recycled" if nested_recycled else "deleted",
    }
    return {
        "provider": "sandoq",
        "request_sha256": request_sha256,
        "recovery_scope_sha256": recovery_scope_sha256,
        "session_sha256": _sha256(outer.encode()),
        "assignment_sha256": _sha256(assignment.encode()),
        "receipt_sha256": _sha256(_canonical(private_receipt)),
        "receipt_verifier_sha256": cleanup_verifier_sha256,
        "terminal_state": "recycled" if nested_recycled else "deleted",
    }


async def _run_in_session(
    backend: SessionBackend,
    image: str,
    request_sha256: str,
    operation,
    *,
    network: str = "none",
) -> tuple[object, dict[str, object]]:
    session: RemoteSession | None = None
    primary_error: BaseException | None = None
    result: object = None
    try:
        session = await backend.start(image, request_sha256, network=network)
        if network == "none":
            if not await _network_isolated(backend, session):
                _fail("provider_network_isolation_unverified")
        elif (
            network != "trusted-builder"
            or session.metadata.get("task_network") != "host"
            or session.metadata.get("environment") != "oci-runner-firecracker"
        ):
            _fail("provider_builder_network_unverified")
        result = await operation(session)
    except BaseException as error:
        primary_error = error
    if session is None:
        assert primary_error is not None
        raise primary_error.with_traceback(primary_error.__traceback__)
    cleanup_task = asyncio.create_task(
        backend.cleanup(
            session,
            f"catalog_{request_sha256[:16]}",
            poison=primary_error is not None,
        )
    )
    cancellation: asyncio.CancelledError | None = None
    cleanup_error: BaseException | None = None
    while not cleanup_task.done():
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError as error:
            cancellation = error
        except BaseException as error:
            cleanup_error = error
            break
    if cleanup_error is None:
        try:
            cleanup = cleanup_task.result()
        except BaseException as error:
            cleanup_error = error
    if cleanup_error is not None:
        if cancellation is not None:
            raise cancellation from cleanup_error
        if primary_error is not None:
            raise primary_error.with_traceback(primary_error.__traceback__) from cleanup_error
        raise cleanup_error
    if cancellation is not None:
        if primary_error is not None:
            raise cancellation from primary_error
        raise cancellation
    if primary_error is not None:
        raise primary_error.with_traceback(primary_error.__traceback__)
    assert isinstance(cleanup, dict)
    return result, cleanup


async def _probe(
    request: dict[str, object],
    request_sha256: str,
    backend: SessionBackend,
) -> tuple[dict[str, object], dict[str, object]]:
    task = _exact(
        request,
        {
            "schema_version",
            "protocol_version",
            "operation",
            "worker",
            "runtime_role",
            "image",
            "requirements",
            "requirements_sha256",
            "network",
            "attestation_policy",
        },
        "worker_request_invalid",
    )
    requirements = _validate_requirements(task["requirements"])
    image = task["image"]
    attestation = _exact(
        task["attestation_policy"],
        {"code_sha256", "environment_sha256", "approval_sha256"},
        "worker_request_invalid",
    )
    runtime_sha256 = str(_exact(task["worker"], set(_WORKER_KEYS), "worker_request_invalid")["runtime_sha256"])
    if (
        task["runtime_role"] not in {"shared-agent", "separate-verifier"}
        or not isinstance(image, str)
        or _DIGEST_IMAGE_RE.fullmatch(image) is None
        or task["requirements_sha256"] != _requirements_sha256(requirements)
        or task["network"] != "none"
        or attestation["code_sha256"] != inventory_probe_code_sha256()
        or attestation["environment_sha256"] != inventory_probe_environment_sha256(runtime_sha256)
        or not _is_sha256(attestation["approval_sha256"])
    ):
        _fail("worker_request_invalid")

    async def run(session: RemoteSession) -> dict[str, object]:
        root = RUNTIME_ROOT / f"probe-{request_sha256}"
        script_path = str(root / "inventory-probe.py")
        control_path = str(root / "control.json")
        _validate_runtime_path(script_path, "worker_request_invalid")
        _validate_runtime_path(control_path, "worker_request_invalid")
        control = _canonical(
            {
                "schema_version": 1,
                "requirements": list(requirements),
                "requirements_sha256": task["requirements_sha256"],
            }
        )
        await backend.upload(session, script_path, INVENTORY_PROBE_CODE.encode())
        await backend.upload(session, control_path, control)
        script_sha256 = _sha256(INVENTORY_PROBE_CODE.encode())
        control_sha256 = _sha256(control)
        command = (
            f"test \"$(sha256sum {shlex.quote(script_path)} | cut -d' ' -f1)\" = {script_sha256} && "
            f"test \"$(sha256sum {shlex.quote(control_path)} | cut -d' ' -f1)\" = {control_sha256} && "
            + shlex.join(("python3", script_path, control_path, control_sha256))
        )
        exit_code, stdout, _ = await backend.execute(session, command, timeout=300)
        if exit_code != 0:
            _fail("provider_probe_failed")
        raw = _exact(
            _strict_json(stdout.encode()),
            {
                "schema_version",
                "runtime_fingerprint",
                "marker_environment",
                "supported_tags",
                "installed_inventory",
                "installed_inventory_sha256",
                "satisfied",
                "closure",
            },
            "provider_probe_invalid",
        )
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            _fail("provider_probe_invalid")
        fingerprint = _exact(
            raw["runtime_fingerprint"],
            {
                "schema_version",
                "implementation",
                "python_full_version",
                "abi",
                "platform",
                "machine",
                "libc",
                "pip_version",
                "marker_environment_sha256",
                "supported_tags_sha256",
            },
            "provider_probe_invalid",
        )
        inventory = raw["installed_inventory"]
        if not isinstance(inventory, list) or raw["installed_inventory_sha256"] != _closure_sha256(inventory):
            _fail("provider_probe_invalid")
        closure = raw["closure"]
        if raw["satisfied"] is True:
            parsed_closure = _exact(closure, {"distributions", "sha256"}, "provider_probe_invalid")
            if parsed_closure["sha256"] != _closure_sha256(parsed_closure["distributions"]):  # type: ignore[arg-type]
                _fail("provider_probe_invalid")
            if not requirements and parsed_closure["distributions"] != []:
                _fail("provider_probe_invalid")
        elif raw["satisfied"] is not False or closure is not None:
            _fail("provider_probe_invalid")
        return {
            "image": image,
            "requirements_sha256": task["requirements_sha256"],
            "compatibility": {
                "runtime_fingerprint": fingerprint,
                "runtime_fingerprint_sha256": _sha256(_canonical(fingerprint)),
                "marker_environment": raw["marker_environment"],
                "supported_tags": raw["supported_tags"],
            },
            "installed_inventory": inventory,
            "installed_inventory_sha256": raw["installed_inventory_sha256"],
            "satisfied": raw["satisfied"],
            "closure": closure,
            "attestation": dict(attestation),
        }

    result, cleanup = await _run_in_session(backend, image, request_sha256, run)
    assert isinstance(result, dict)
    return result, cleanup


def _wheel_metadata(payload: bytes, filename: str) -> tuple[str, str, bool]:
    try:
        from packaging.utils import canonicalize_name, parse_wheel_filename

        distribution, version, _, tags = parse_wheel_filename(filename)
        if len(payload) > MAX_ARCHIVE_BYTES:
            _fail("trusted_builder_artifact_invalid")
        with ZipFile(BytesIO(payload), "r") as archive:
            members = archive.infolist()
            if (
                len(members) > 100_000
                or sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES
                or any(member.file_size > MAX_ARCHIVE_BYTES for member in members)
            ):
                _fail("trusted_builder_artifact_invalid")
            metadata_names = sorted(
                member.filename
                for member in members
                if member.filename.endswith(".dist-info/METADATA") and member.file_size <= 8 * 1024 * 1024
            )
            if len(metadata_names) != 1:
                _fail("trusted_builder_artifact_invalid")
            metadata_payload = archive.read(metadata_names[0]).decode("utf-8")
        fields: dict[str, str] = {}
        for line in metadata_payload.splitlines():
            name, separator, value = line.partition(":")
            if separator and name in {"Name", "Version"} and name not in fields:
                fields[name] = value.strip()
        canonical_name = canonicalize_name(str(distribution))
        if canonicalize_name(fields.get("Name", "")) != canonical_name or fields.get("Version") != str(version):
            _fail("trusted_builder_artifact_invalid")
        universal = bool(tags) and all(tag.abi == "none" and tag.platform == "any" for tag in tags)
        return canonical_name, str(version), universal
    except WorkerError:
        raise
    except (ImportError, OSError, ValueError) as error:
        _fail("trusted_builder_artifact_invalid", error)


def _pack_wheelhouse(wheels: dict[str, bytes]) -> bytes:
    estimated_size = 10_240 + sum(512 + ((len(payload) + 511) // 512) * 512 for payload in wheels.values())
    if not wheels or len(wheels) > 10_000 or estimated_size > MAX_ARCHIVE_BYTES:
        _fail("trusted_builder_artifact_invalid")
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for filename in sorted(wheels):
            payload = wheels[filename]
            info = tarfile.TarInfo(filename)
            info.size = len(payload)
            info.mode = 0o444
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            archive.addfile(info, BytesIO(payload))
    payload = output.getvalue()
    if len(payload) > MAX_ARCHIVE_BYTES:
        _fail("trusted_builder_artifact_invalid")
    return payload


def _report_downloads(report: object) -> list[dict[str, object]]:
    raw = _exact(report, {"version", "pip_version", "install", "environment"}, "trusted_builder_report_invalid")
    installs = raw["install"]
    if not isinstance(installs, list) or not 1 <= len(installs) <= 10_000:
        _fail("trusted_builder_report_invalid")
    parsed: list[dict[str, object]] = []
    for item in installs:
        if not isinstance(item, dict):
            _fail("trusted_builder_report_invalid")
        download = item.get("download_info")
        metadata = item.get("metadata")
        if not isinstance(download, dict) or not isinstance(metadata, dict):
            _fail("trusted_builder_report_invalid")
        archive_info = download.get("archive_info")
        hashes = archive_info.get("hashes") if isinstance(archive_info, dict) else None
        sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
        url = download.get("url")
        name = metadata.get("name")
        version = metadata.get("version")
        if not _is_sha256(sha256) or not all(isinstance(value, str) and value for value in (url, name, version)):
            _fail("trusted_builder_report_invalid")
        parsed.append(
            {
                "name": re.sub(r"[-_.]+", "-", str(name).lower()),
                "version": version,
                "sha256": sha256,
                "url": url,
                "source_snapshot_sha256": _sha256(
                    _canonical(
                        {
                            "schema_version": 1,
                            "kind": "pip-report-download-info",
                            "download_info": download,
                        }
                    )
                ),
            }
        )
    return parsed


def _target_pip_flags(fingerprint: dict[str, object], supported_tags: list[str]) -> tuple[str, ...]:
    python_version = fingerprint["python_full_version"]
    implementation = fingerprint["implementation"]
    if (
        not isinstance(python_version, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", python_version) is None
        or implementation not in {"cpython", "pypy"}
        or not 1 <= len(supported_tags) <= 4096
        or supported_tags != sorted(set(supported_tags))
        or not all(isinstance(tag, str) and 1 <= len(tag) <= 256 for tag in supported_tags)
    ):
        _fail("worker_compatibility_invalid")
    major, minor, *_ = python_version.split(".")
    implementation_tag = "cp" if implementation == "cpython" else "pp"
    interpreter = f"{implementation_tag}{major}{minor}"
    parsed = [tag.split("-", 2) for tag in supported_tags]
    selected = [parts for parts in parsed if len(parts) == 3 and parts[0] == interpreter]
    if not selected:
        _fail("worker_compatibility_invalid")
    abis = sorted({parts[1] for parts in selected})
    platforms = sorted({parts[2] for parts in selected})
    return (
        "--python-version",
        f"{major}.{minor}",
        "--implementation",
        implementation_tag,
        *(value for abi in abis for value in ("--abi", abi)),
        *(value for platform in platforms for value in ("--platform", platform)),
    )


async def _build_wheelhouse(
    request: dict[str, object],
    artifact_directory: Path,
    backend: SessionBackend,
    session: RemoteSession,
    request_sha256: str,
    builder_image: str,
) -> dict[str, object]:
    requirements = _validate_requirements(request["requirements"])
    compatibility = _exact(
        request["compatibility"],
        {"runtime_fingerprint", "runtime_fingerprint_sha256", "marker_environment", "supported_tags"},
        "worker_request_invalid",
    )
    fingerprint = _exact(
        compatibility["runtime_fingerprint"],
        {
            "schema_version",
            "implementation",
            "python_full_version",
            "abi",
            "platform",
            "machine",
            "libc",
            "pip_version",
            "marker_environment_sha256",
            "supported_tags_sha256",
        },
        "worker_request_invalid",
    )
    marker_environment = compatibility["marker_environment"]
    supported_tags = compatibility["supported_tags"]
    if (
        compatibility["runtime_fingerprint_sha256"] != _sha256(_canonical(fingerprint))
        or not isinstance(marker_environment, dict)
        or fingerprint["marker_environment_sha256"] != _sha256(_canonical(marker_environment))
        or not isinstance(supported_tags, list)
        or fingerprint["supported_tags_sha256"] != _sha256(_canonical(supported_tags))
    ):
        _fail("worker_request_invalid")
    target_flags = _target_pip_flags(fingerprint, supported_tags)
    policy = _exact(
        request["policy"],
        {
            "source_policy_sha256",
            "source_policy_approval_sha256",
            "approved_binary_artifacts",
            "approved_binary_artifacts_sha256",
            "approved_source_attestations",
            "approved_source_attestations_sha256",
            "approved_toolchains",
            "approved_toolchains_sha256",
        },
        "worker_request_invalid",
    )
    approved_binaries = policy["approved_binary_artifacts"]
    approved_sources = policy["approved_source_attestations"]
    approved_toolchains = policy["approved_toolchains"]
    if not all(
        isinstance(values, list)
        and len(values) <= 100_000
        and values == sorted(set(values))
        and all(_is_sha256(value) for value in values)
        for values in (approved_binaries, approved_sources, approved_toolchains)
    ) or (
        not _is_sha256(policy["source_policy_sha256"])
        or not _is_sha256(policy["source_policy_approval_sha256"])
        or policy["approved_binary_artifacts_sha256"] != _allowlist_sha256("binary-artifacts", approved_binaries)
        or policy["approved_source_attestations_sha256"] != _allowlist_sha256("source-attestations", approved_sources)
        or policy["approved_toolchains_sha256"] != _allowlist_sha256("toolchains", approved_toolchains)
    ):
        _fail("worker_request_invalid")
    worker = _exact(request["worker"], set(_WORKER_KEYS), "worker_request_invalid")
    probe_exit, probe_stdout, _ = await backend.execute(
        session,
        f"python3 -I -c {shlex.quote(BUILDER_PROBE_CODE)}",
        timeout=30,
    )
    if probe_exit != 0:
        _fail("trusted_builder_toolchain_unapproved")
    builder_probe = _exact(
        _strict_json(probe_stdout.encode()),
        {"pip_version", "python_version"},
        "trusted_builder_toolchain_unapproved",
    )
    if not all(
        isinstance(builder_probe[name], str)
        and 1 <= len(builder_probe[name]) <= 256
        and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in builder_probe[name])
        for name in ("pip_version", "python_version")
    ):
        _fail("trusted_builder_toolchain_unapproved")
    toolchain = {
        "schema_version": 1,
        "python_version": builder_probe["python_version"],
        "pip_version": builder_probe["pip_version"],
        "resolver": "pip",
        "resolver_version": builder_probe["pip_version"],
        "builder_code_sha256": _builder_code_sha256(worker),
        "build_environment_sha256": _builder_environment_sha256(worker, builder_image),
    }
    toolchain_sha256 = _sha256(_canonical(toolchain))
    if toolchain_sha256 not in approved_toolchains:
        _fail("trusted_builder_toolchain_unapproved")
    root = RUNTIME_ROOT / f"build-{request_sha256}"
    requirements_path = str(root / "requirements.txt")
    report_path = str(root / "report.json")
    wheels_directory = str(root / "wheels")
    for path in (requirements_path, report_path, wheels_directory):
        _validate_runtime_path(path, "worker_request_invalid")
    prepared, _, _ = await backend.execute(
        session,
        f"rm -rf {shlex.quote(str(root))} && mkdir -p {shlex.quote(wheels_directory)}",
        timeout=60,
    )
    if prepared != 0:
        _fail("trusted_builder_prepare_failed")
    await backend.upload(session, requirements_path, "".join(f"{item}\n" for item in requirements).encode())
    pip_base = ("python3", "-m", "pip", "--disable-pip-version-check")
    build_environment = {
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONNOUSERSITE": "1",
    }
    report_argv = (
        *pip_base,
        "install",
        "--dry-run",
        "--ignore-installed",
        "--no-cache-dir",
        "--no-input",
        "--only-binary=:all:",
        *target_flags,
        "--report",
        report_path,
        "--requirement",
        requirements_path,
    )
    download_argv = (
        *pip_base,
        "download",
        "--no-cache-dir",
        "--no-input",
        "--only-binary=:all:",
        *target_flags,
        "--dest",
        wheels_directory,
        "--requirement",
        requirements_path,
    )
    report_exit, _, _ = await backend.execute(
        session,
        f"test \"$(sha256sum {shlex.quote(requirements_path)} | cut -d' ' -f1)\" = "
        f"{_sha256(''.join(f'{item}\n' for item in requirements).encode())} && {shlex.join(report_argv)}",
        timeout=3600,
        environment=build_environment,
    )
    download_exit, _, _ = await backend.execute(
        session,
        f"test \"$(sha256sum {shlex.quote(requirements_path)} | cut -d' ' -f1)\" = "
        f"{_sha256(''.join(f'{item}\n' for item in requirements).encode())} && {shlex.join(download_argv)}",
        timeout=3600,
        environment=build_environment,
    )
    if report_exit != 0 or download_exit != 0:
        _fail("trusted_binary_resolution_failed")
    report_payload = await backend.download(session, report_path)
    downloads = _report_downloads(_strict_json(report_payload))
    listing_code = (
        "import json,pathlib; p=pathlib.Path(" + repr(wheels_directory) + "); "
        "print(json.dumps(sorted(x.name for x in p.iterdir()),separators=(',',':')))"
    )
    listing_exit, listing_stdout, _ = await backend.execute(
        session,
        f"python3 -c {shlex.quote(listing_code)}",
        timeout=60,
    )
    if listing_exit != 0:
        _fail("trusted_builder_artifact_invalid")
    names = _strict_json(listing_stdout.encode())
    if (
        not isinstance(names, list)
        or names != sorted(set(names))
        or not names
        or not all(
            isinstance(name, str) and PurePosixPath(name).name == name and name.endswith(".whl") for name in names
        )
    ):
        _fail("trusted_builder_artifact_invalid")
    wheel_payloads: dict[str, bytes] = {}
    report_by_sha = {str(item["sha256"]): item for item in downloads}
    for name in names:
        payload = await backend.download(session, f"{wheels_directory}/{name}")
        if _sha256(payload) not in report_by_sha:
            _fail("trusted_builder_report_invalid")
        wheel_payloads[name] = payload
    if {_sha256(payload) for payload in wheel_payloads.values()} != set(report_by_sha):
        _fail("trusted_builder_report_invalid")
    wheel_records: list[dict[str, object]] = []
    closure: list[list[str]] = []
    universal = True
    for filename in sorted(wheel_payloads):
        payload = wheel_payloads[filename]
        distribution, version, is_universal = _wheel_metadata(payload, filename)
        digest = _sha256(payload)
        item = report_by_sha[digest]
        universal = universal and is_universal
        closure.append([distribution, version])
        binary_policy = {
            "schema_version": 1,
            "distribution": distribution,
            "version": version,
            "filename": filename,
            "size": len(payload),
            "sha256": digest,
            "source_url_sha256": _sha256(str(item["url"]).encode()),
            "source_snapshot_sha256": item["source_snapshot_sha256"],
        }
        binary_policy_sha256 = _sha256(_canonical(binary_policy))
        if binary_policy_sha256 not in approved_binaries:
            _fail("trusted_binary_unapproved")
        wheel_records.append(
            {
                "distribution": distribution,
                "version": version,
                "filename": filename,
                "size": len(payload),
                "sha256": digest,
                "universal": is_universal,
                "origin": "binary",
                "binary_artifact_policy": binary_policy,
                "binary_artifact_policy_sha256": binary_policy_sha256,
                "source_attestation_sha256": None,
            }
        )
    closure.sort()
    if len(closure) != len({item[0] for item in closure}):
        _fail("trusted_builder_artifact_invalid")
    archive = _pack_wheelhouse(wheel_payloads)
    with contextlib.suppress(BaseException):
        await backend.execute(session, f"rm -rf {shlex.quote(str(root))}", timeout=60)
    archive_path = artifact_directory / "wheelhouse.tar"
    if os.path.lexists(archive_path):
        if _private_file(archive_path, MAX_ARCHIVE_BYTES, "trusted_builder_artifact_invalid") != archive:
            _fail("trusted_builder_artifact_invalid")
    else:
        _atomic_private_write(archive_path, archive)
    scope = "universal" if universal and request["scope_policy"] == "discover" else "image"
    image = None if scope == "universal" else request["image"]
    return {
        "scope": scope,
        "image": image,
        "archive": {"filename": "wheelhouse.tar", "sha256": _sha256(archive), "size": len(archive)},
        "closure": {"distributions": closure, "sha256": _closure_sha256(closure)},
        "toolchain": {"record": toolchain, "sha256": toolchain_sha256},
        "source_policy": {
            "policy_sha256": policy["source_policy_sha256"],
            "approval_sha256": policy["source_policy_approval_sha256"],
        },
        "wheels": wheel_records,
    }


async def _build(
    request: dict[str, object],
    request_sha256: str,
    artifact_directory: Path,
    backend: SessionBackend,
) -> tuple[dict[str, object], dict[str, object]]:
    _exact(
        request,
        {
            "schema_version",
            "protocol_version",
            "operation",
            "worker",
            "image",
            "requirements",
            "requirements_sha256",
            "compatibility",
            "scope_policy",
            "network",
            "policy",
            "artifact_contract",
        },
        "worker_request_invalid",
    )
    requirements = _validate_requirements(request["requirements"])
    artifact_contract = _exact(
        request["artifact_contract"],
        {"filename", "deterministic_format", "binary_only_unless_source_attested"},
        "worker_request_invalid",
    )
    if (
        not isinstance(request["image"], str)
        or _DIGEST_IMAGE_RE.fullmatch(request["image"]) is None
        or request["requirements_sha256"] != _requirements_sha256(requirements)
        or request["scope_policy"] not in {"discover", "image"}
        or request["network"] != "trusted-builder"
        or artifact_contract
        != {
            "filename": "wheelhouse.tar",
            "deterministic_format": "ustar-sorted-zero-mtime-v1",
            "binary_only_unless_source_attested": True,
        }
    ):
        _fail("worker_request_invalid")
    builder_image = os.environ["SANDOQ_CATALOG_BUILDER_IMAGE"]
    if _DIGEST_IMAGE_RE.fullmatch(builder_image) is None or builder_image == request["image"]:
        _fail("trusted_builder_image_invalid")

    async def run(session: RemoteSession) -> dict[str, object]:
        return await _build_wheelhouse(
            request,
            artifact_directory,
            backend,
            session,
            request_sha256,
            builder_image,
        )

    result, cleanup = await _run_in_session(
        backend,
        builder_image,
        request_sha256,
        run,
        network="trusted-builder",
    )
    assert isinstance(result, dict)
    return result, cleanup


def _validated_validation_evidence(value: object) -> dict[str, object]:
    evidence = _exact(
        value,
        {
            "runtime_paths",
            "wheel_inventory",
            "wheel_inventory_sha256",
            "install_request_sha256",
            "install_argv_sha256",
            "install_environment_sha256",
            "probe_script_sha256",
            "probe_control_sha256",
            "probe_argv_sha256",
            "expected_probe_stdout_sha256",
            "expected_inventory_sha256",
            "expected_closure_sha256",
        },
        "worker_request_invalid",
    )
    paths = _exact(
        evidence["runtime_paths"],
        {"archive", "wheel_directory", "site_directory", "install_request", "probe_script", "probe_control"},
        "worker_request_invalid",
    )
    normalized = [_validate_runtime_path(value, "worker_request_invalid") for value in paths.values()]
    for index, first in enumerate(map(PurePosixPath, normalized)):
        for second in map(PurePosixPath, normalized[index + 1 :]):
            if first == second or first.is_relative_to(second) or second.is_relative_to(first):
                _fail("worker_request_invalid")
    inventory = evidence["wheel_inventory"]
    if not isinstance(inventory, list) or not inventory:
        _fail("worker_request_invalid")
    filenames: list[str] = []
    for item in inventory:
        wheel = _exact(item, {"filename", "sha256", "size"}, "worker_request_invalid")
        filename = wheel["filename"]
        if (
            not isinstance(filename, str)
            or PurePosixPath(filename).name != filename
            or not filename.endswith(".whl")
            or not _is_sha256(wheel["sha256"])
            or type(wheel["size"]) is not int
            or not 1 <= wheel["size"] <= MAX_ARCHIVE_BYTES
        ):
            _fail("worker_request_invalid")
        filenames.append(filename)
    if filenames != sorted(set(filenames)) or evidence["wheel_inventory_sha256"] != _sha256(_canonical(inventory)):
        _fail("worker_request_invalid")
    if not all(_is_sha256(evidence[name]) for name in set(evidence) - {"runtime_paths", "wheel_inventory"}):
        _fail("worker_request_invalid")
    return evidence


def _archive_wheels(payload: bytes) -> list[dict[str, object]]:
    if not 0 < len(payload) <= MAX_ARCHIVE_BYTES:
        _fail("validation_archive_invalid")
    entries: list[dict[str, object]] = []
    try:
        with tarfile.open(fileobj=BytesIO(payload), mode="r:") as archive:
            members = archive.getmembers()
            for member in members:
                if (
                    not member.isfile()
                    or PurePosixPath(member.name).name != member.name
                    or not member.name.endswith(".whl")
                    or member.size < 1
                    or member.mode != 0o444
                    or member.uid != 0
                    or member.gid != 0
                    or member.mtime != 0
                ):
                    _fail("validation_archive_invalid")
                stream = archive.extractfile(member)
                if stream is None:
                    _fail("validation_archive_invalid")
                wheel = stream.read()
                entries.append({"filename": member.name, "sha256": _sha256(wheel), "size": len(wheel)})
    except WorkerError:
        raise
    except (OSError, tarfile.TarError) as error:
        _fail("validation_archive_invalid", error)
    if [entry["filename"] for entry in entries] != sorted({str(entry["filename"]) for entry in entries}):
        _fail("validation_archive_invalid")
    return entries


async def _validate(
    request: dict[str, object],
    request_sha256: str,
    backend: SessionBackend,
) -> tuple[dict[str, object], dict[str, object]]:
    _exact(
        request,
        {
            "schema_version",
            "protocol_version",
            "operation",
            "worker",
            "runtime_role",
            "image",
            "requirements",
            "requirements_sha256",
            "compatibility",
            "network",
            "archive",
            "closure",
            "validation_evidence",
        },
        "worker_request_invalid",
    )
    requirements = _validate_requirements(request["requirements"])
    image = request["image"]
    archive_record = _exact(request["archive"], {"path", "sha256", "size"}, "worker_request_invalid")
    closure = _exact(request["closure"], {"distributions", "sha256"}, "worker_request_invalid")
    compatibility = _exact(
        request["compatibility"],
        {"runtime_fingerprint", "runtime_fingerprint_sha256", "marker_environment", "supported_tags"},
        "worker_request_invalid",
    )
    evidence = _validated_validation_evidence(request["validation_evidence"])
    if (
        request["runtime_role"] not in {"shared-agent", "separate-verifier"}
        or not isinstance(image, str)
        or _DIGEST_IMAGE_RE.fullmatch(image) is None
        or request["requirements_sha256"] != _requirements_sha256(requirements)
        or request["network"] != "none"
        or not isinstance(archive_record["path"], str)
        or not _is_sha256(archive_record["sha256"])
        or type(archive_record["size"]) is not int
        or not isinstance(closure["distributions"], list)
        or closure["sha256"] != _closure_sha256(closure["distributions"])  # type: ignore[arg-type]
    ):
        _fail("worker_request_invalid")
    archive = _private_file(Path(str(archive_record["path"])), MAX_ARCHIVE_BYTES, "validation_archive_invalid")
    if len(archive) != archive_record["size"] or _sha256(archive) != archive_record["sha256"]:
        _fail("validation_archive_invalid")
    wheel_inventory = _archive_wheels(archive)
    if wheel_inventory != evidence["wheel_inventory"]:
        _fail("validation_archive_invalid")
    paths = evidence["runtime_paths"]
    assert isinstance(paths, dict)
    install_request = "".join(
        f"{paths['wheel_directory']}/{item['filename']} --hash=sha256:{item['sha256']}\n" for item in wheel_inventory
    ).encode()
    install_argv = (
        "python3",
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-deps",
        "--no-cache-dir",
        "--disable-pip-version-check",
        "--no-input",
        "--require-hashes",
        "--target",
        str(paths["site_directory"]),
        "--requirement",
        str(paths["install_request"]),
    )
    install_environment = {
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONNOUSERSITE": "1",
    }
    probe_control = _canonical(
        {
            "schema_version": 1,
            "site_directory": paths["site_directory"],
            "requirements": list(requirements),
            "inventory": closure["distributions"],
            "inventory_sha256": closure["sha256"],
            "closure": closure["distributions"],
            "closure_sha256": closure["sha256"],
        }
    )
    probe_argv = (
        "python3",
        str(paths["probe_script"]),
        str(paths["probe_control"]),
        _sha256(probe_control),
    )
    expected_stdout = _canonical({"count": len(closure["distributions"]), "status": "ok"}) + b"\n"  # type: ignore[arg-type]
    expected_hashes = {
        "install_request_sha256": _sha256(install_request),
        "install_argv_sha256": _sha256(_canonical(list(install_argv))),
        "install_environment_sha256": _sha256(_canonical(install_environment)),
        "probe_script_sha256": _sha256(CLOSURE_PROBE_CODE.encode()),
        "probe_control_sha256": _sha256(probe_control),
        "probe_argv_sha256": _sha256(_canonical(list(probe_argv))),
        "expected_probe_stdout_sha256": _sha256(expected_stdout),
        "expected_inventory_sha256": closure["sha256"],
        "expected_closure_sha256": closure["sha256"],
    }
    if any(evidence[name] != value for name, value in expected_hashes.items()):
        _fail("worker_request_invalid")
    fingerprint = compatibility["runtime_fingerprint"]
    if compatibility["runtime_fingerprint_sha256"] != _sha256(_canonical(fingerprint)):
        _fail("worker_request_invalid")

    async def run(session: RemoteSession) -> dict[str, object]:
        root = str(PurePosixPath(str(paths["archive"])).parent)
        prepared_command = (
            f"rm -rf {shlex.quote(root)} && mkdir -p "
            f"{shlex.quote(str(paths['wheel_directory']))} {shlex.quote(str(paths['site_directory']))} && "
            f"chmod 700 {shlex.quote(root)} {shlex.quote(str(paths['wheel_directory']))} "
            f"{shlex.quote(str(paths['site_directory']))}"
        )
        prepared, _, _ = await backend.execute(session, prepared_command, timeout=60)
        if prepared != 0:
            _fail("provider_validation_prepare_failed")
        await backend.upload(session, str(paths["archive"]), archive)
        await backend.upload(session, str(paths["install_request"]), install_request)
        await backend.upload(session, str(paths["probe_script"]), CLOSURE_PROBE_CODE.encode())
        await backend.upload(session, str(paths["probe_control"]), probe_control)
        extract_command = (
            f"test \"$(sha256sum {shlex.quote(str(paths['archive']))} | cut -d' ' -f1)\" = "
            f"{shlex.quote(str(archive_record['sha256']))} && "
            f"test \"$(sha256sum {shlex.quote(str(paths['install_request']))} | cut -d' ' -f1)\" = "
            f"{_sha256(install_request)} && "
            f"test \"$(sha256sum {shlex.quote(str(paths['probe_script']))} | cut -d' ' -f1)\" = "
            f"{_sha256(CLOSURE_PROBE_CODE.encode())} && "
            f"test \"$(sha256sum {shlex.quote(str(paths['probe_control']))} | cut -d' ' -f1)\" = "
            f"{_sha256(probe_control)} && "
            f"tar --no-same-owner --no-same-permissions -xf {shlex.quote(str(paths['archive']))} "
            f"-C {shlex.quote(str(paths['wheel_directory']))}"
        )
        extracted, _, _ = await backend.execute(session, extract_command, timeout=120)
        if extracted != 0:
            _fail("provider_validation_extract_failed")
        install_code, _, _ = await backend.execute(
            session,
            shlex.join(install_argv),
            timeout=1200,
            environment=install_environment,
        )
        probe_code, probe_stdout, _ = await backend.execute(
            session,
            shlex.join(probe_argv),
            timeout=300,
        )
        with contextlib.suppress(BaseException):
            await backend.execute(session, f"rm -rf {shlex.quote(root)}", timeout=60)
        return {
            "image": image,
            "requirements_sha256": request["requirements_sha256"],
            "runtime_fingerprint_sha256": compatibility["runtime_fingerprint_sha256"],
            "archive_sha256": archive_record["sha256"],
            "closure_sha256": closure["sha256"],
            "observed": {
                "network": "none",
                "network_isolation_verified": True,
                "archive_sha256": archive_record["sha256"],
                "wheel_inventory_sha256": _sha256(_canonical(wheel_inventory)),
                "install_request_sha256": _sha256(install_request),
                "install_argv_sha256": _sha256(_canonical(list(install_argv))),
                "install_environment_sha256": _sha256(_canonical(install_environment)),
                "install_exit_code": install_code,
                "probe_script_sha256": _sha256(CLOSURE_PROBE_CODE.encode()),
                "probe_control_sha256": _sha256(probe_control),
                "probe_argv_sha256": _sha256(_canonical(list(probe_argv))),
                "probe_exit_code": probe_code,
                "probe_stdout_sha256": _sha256(probe_stdout.encode()),
                "observed_inventory_sha256": closure["sha256"] if probe_code == 0 else _sha256(b"failed"),
                "observed_closure_sha256": closure["sha256"] if probe_code == 0 else _sha256(b"failed"),
                "missing_distributions": 0 if probe_code == 0 else 1,
                "unexpected_distributions": 0 if probe_code == 0 else 1,
            },
        }

    result, cleanup = await _run_in_session(backend, image, request_sha256, run)
    assert isinstance(result, dict)
    return result, cleanup


def _validate_common_request(request: object, request_sha256: str) -> dict[str, object]:
    if not isinstance(request, dict):
        _fail("worker_request_invalid")
    if type(request.get("schema_version")) is not int or request.get("schema_version") != SCHEMA_VERSION:
        _fail("worker_request_invalid")
    if type(request.get("protocol_version")) is not int or request.get("protocol_version") != WORKER_PROTOCOL_VERSION:
        _fail("worker_request_invalid")
    operation = request.get("operation")
    if operation not in {"recover", "probe", "build", "validate", "anchor"}:
        _fail("worker_request_invalid")
    worker = _exact(request.get("worker"), set(_WORKER_KEYS), "worker_request_invalid")
    if (
        worker["runtime_sha256"] != worker_runtime_sha256()
        or worker["cleanup_receipt_verifier_sha256"] != cleanup_receipt_verifier_sha256()
        or not all(
            _is_sha256(worker[name])
            for name in (
                "executable_sha256",
                "runtime_sha256",
                "materializer_code_sha256",
                "cleanup_receipt_verifier_sha256",
                "environment_sha256",
                "recovery_scope_sha256",
                "credential_rotation_sha256",
            )
        )
        or (worker["ecr_rotator_sha256"] is not None and not _is_sha256(worker["ecr_rotator_sha256"]))
        or not _is_sha256(request_sha256)
    ):
        _fail("worker_request_invalid")
    return request


async def _provider_recovery_result(
    request: dict[str, object],
    request_sha256: str,
    backend: SessionBackend,
    *,
    phase: str,
    reason: str,
) -> dict[str, object]:
    drain = await backend.recover(reason)
    _verify_drain(drain)
    wal_sha256, remaining = _wal_snapshot()
    worker = _exact(request["worker"], set(_WORKER_KEYS), "worker_request_invalid")
    receipt = {
        "schema_version": 1,
        "request_sha256": request_sha256,
        "recovery_scope_sha256": worker["recovery_scope_sha256"],
        "phase": phase,
        "wal_snapshot_sha256": wal_sha256,
        "remaining_sessions": remaining,
    }
    return {
        "durable_provider_wal": True,
        "recovery_attempted": True,
        "remaining_sessions": remaining,
        "cleanup_receipts_verified": True,
        "recovery_scope_sha256": worker["recovery_scope_sha256"],
        "phase": phase,
        "wal_snapshot_sha256": wal_sha256,
        "recovery_receipt_sha256": _sha256(_canonical(receipt)),
        "receipt_verifier_sha256": worker["cleanup_receipt_verifier_sha256"],
    }


async def _recover(request: dict[str, object], request_sha256: str, backend: SessionBackend) -> dict[str, object]:
    _exact(
        request,
        {
            "schema_version",
            "protocol_version",
            "operation",
            "worker",
            "run_nonce",
            "phase",
            "network",
            "recovery_contract",
        },
        "worker_request_invalid",
    )
    contract = _exact(
        request["recovery_contract"],
        {"durable_provider_wal", "drain_or_retire_orphans", "require_cleanup_receipts"},
        "worker_request_invalid",
    )
    if (
        request["network"] != "control-plane"
        or not isinstance(request["run_nonce"], str)
        or len(request["run_nonce"]) != 32
        or request["phase"] not in {"startup", "final", "failure"}
        or any(value is not True for value in contract.values())
    ):
        _fail("worker_request_invalid")
    return await _provider_recovery_result(
        request,
        request_sha256,
        backend,
        phase=str(request["phase"]),
        reason=f"catalog_recover_{request_sha256[:16]}",
    )


async def _anchor(
    request: dict[str, object],
    request_sha256: str,
    artifact_directory: Path,
    backend: SessionBackend,
) -> dict[str, object]:
    _exact(
        request,
        {
            "schema_version",
            "protocol_version",
            "operation",
            "worker",
            "run_nonce",
            "network",
            "anchor_contract",
        },
        "worker_request_invalid",
    )
    contract = _exact(
        request["anchor_contract"],
        {
            "active_client_required",
            "heartbeat_interval_seconds",
            "sole_terminal_drain",
            "zero_live_wal_required",
        },
        "worker_request_invalid",
    )
    run_nonce = request["run_nonce"]
    if (
        request["network"] != "control-plane"
        or not isinstance(run_nonce, str)
        or len(run_nonce) != 32
        or any(character not in "0123456789abcdef" for character in run_nonce)
        or contract
        != {
            "active_client_required": True,
            "heartbeat_interval_seconds": PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS,
            "sole_terminal_drain": True,
            "zero_live_wal_required": True,
        }
    ):
        _fail("worker_request_invalid")
    status = await backend.anchor_status()
    active_clients = status.get("clients")
    if (
        type(active_clients) is not int
        or active_clients < 1
        or status.get("accepting") is not True
        or status.get("draining") is not False
    ):
        _fail("provider_anchor_unverified")
    worker = _exact(request["worker"], set(_WORKER_KEYS), "worker_request_invalid")
    ready_path = artifact_directory / "anchor-ready.json"
    stop_path = artifact_directory / "anchor-stop.json"
    _atomic_private_write(
        ready_path,
        _canonical(
            {
                "schema_version": 1,
                "request_sha256": request_sha256,
                "recovery_scope_sha256": worker["recovery_scope_sha256"],
                "active_client_registered": True,
                "pool_accepting": True,
                "pool_draining": False,
            }
        ),
    )
    phase: str | None = None
    heartbeat_checks = 0
    try:
        loop = asyncio.get_running_loop()
        next_heartbeat = loop.time() + PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS
        while phase is None:
            if os.path.lexists(stop_path):
                stop_payload = _private_file(stop_path, MAX_JSON_BYTES, "provider_anchor_stop_invalid")
                stop = _exact(
                    _strict_json(stop_payload),
                    {"schema_version", "request_sha256", "run_nonce", "phase"},
                    "provider_anchor_stop_invalid",
                )
                if (
                    stop_payload != _canonical(stop)
                    or type(stop["schema_version"]) is not int
                    or stop["schema_version"] != 1
                    or stop["request_sha256"] != request_sha256
                    or stop["run_nonce"] != run_nonce
                    or stop["phase"] not in {"final", "failure"}
                ):
                    _fail("provider_anchor_stop_invalid")
                phase = str(stop["phase"])
                break
            now = loop.time()
            if now >= next_heartbeat:
                status = await backend.anchor_heartbeat()
                if (
                    type(status.get("clients")) is not int
                    or status["clients"] < 1
                    or status.get("accepting") is not True
                    or status.get("draining") is not False
                ):
                    _fail("provider_anchor_unverified")
                heartbeat_checks += 1
                next_heartbeat = now + PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS
            await asyncio.sleep(min(0.1, max(next_heartbeat - loop.time(), 0.01)))
    except BaseException as primary_error:
        cleanup_task = asyncio.create_task(
            _provider_recovery_result(
                request,
                request_sha256,
                backend,
                phase="failure",
                reason=f"catalog_anchor_cancelled_{request_sha256[:16]}",
            )
        )
        cleanup_error: BaseException | None = None
        interrupted = isinstance(primary_error, asyncio.CancelledError)
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                interrupted = True
                continue
            except BaseException as error:
                cleanup_error = error
                break
        if cleanup_error is None:
            try:
                cleanup_task.result()
            except BaseException as error:
                cleanup_error = error
        if cleanup_error is not None:
            raise primary_error.with_traceback(primary_error.__traceback__) from cleanup_error
        if interrupted and not isinstance(primary_error, asyncio.CancelledError):
            raise asyncio.CancelledError from primary_error
        raise primary_error.with_traceback(primary_error.__traceback__)
    recovery = await _provider_recovery_result(
        request,
        request_sha256,
        backend,
        phase=phase,
        reason=f"catalog_anchor_{phase}_{request_sha256[:16]}",
    )
    recovery["anchor_liveness"] = {
        "active_client_registered": True,
        "heartbeat_checks": heartbeat_checks,
        "stop_received": True,
    }
    return recovery


async def _dispatch(
    request: dict[str, object],
    request_sha256: str,
    artifact_directory: Path,
    backend: SessionBackend,
) -> tuple[dict[str, object], dict[str, object] | None]:
    operation = request["operation"]
    if operation == "recover":
        return await _recover(request, request_sha256, backend), None
    if operation == "anchor":
        return await _anchor(request, request_sha256, artifact_directory, backend), None
    if operation == "probe":
        return await _probe(request, request_sha256, backend)
    if operation == "build":
        return await _build(request, request_sha256, artifact_directory, backend)
    if operation == "validate":
        return await _validate(request, request_sha256, backend)
    _fail("worker_request_invalid")


async def _run_worker(args: argparse.Namespace, backend: SessionBackend | None = None) -> None:
    _validate_environment()
    _prepare_provider_paths()
    request_path = Path(args.request)
    response_path = Path(args.response)
    artifact_directory = Path(args.artifact_dir)
    request_payload = _private_file(request_path, MAX_JSON_BYTES, "worker_request_invalid")
    if _sha256(request_payload) != args.request_sha256:
        _fail("worker_request_invalid")
    request = _validate_common_request(_strict_json(request_payload), args.request_sha256)
    if request_payload != _canonical(request):
        _fail("worker_request_invalid")
    if not artifact_directory.is_absolute() or artifact_directory.parent != response_path.parent:
        _fail("worker_output_invalid")
    runtime_directory = response_path.parent / "provider-runtime"
    _stage_provider_source(runtime_directory)
    provider = backend or PinnedSandoqBackend()
    result, cleanup = await _dispatch(request, args.request_sha256, artifact_directory, provider)
    worker = _exact(request["worker"], set(_WORKER_KEYS), "worker_request_invalid")
    operation = str(request["operation"])
    provider_cleanup = None
    if cleanup is not None:
        provider_cleanup = _provider_cleanup_record(
            args.request_sha256,
            str(worker["recovery_scope_sha256"]),
            str(worker["cleanup_receipt_verifier_sha256"]),
            cleanup,
        )
    _provider_source_record(runtime_directory, exact_staged_tree=True)
    if worker_runtime_sha256() != worker["runtime_sha256"]:
        _fail("worker_runtime_changed")
    response = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "operation": operation,
        "request_sha256": args.request_sha256,
        "worker_executable_sha256": worker["executable_sha256"],
        "worker_runtime_sha256": worker["runtime_sha256"],
        "worker_environment_sha256": worker["environment_sha256"],
        "recovery_scope_sha256": worker["recovery_scope_sha256"],
        "credential_rotation_sha256": worker["credential_rotation_sha256"],
        "status": "complete",
        "lifecycle": {
            "network": "control-plane"
            if operation in {"recover", "anchor"}
            else ("trusted-builder" if operation == "build" else "none"),
            "session_started": operation not in {"recover", "anchor"},
            "process_cleanup_verified": True,
            "cleanup_verified": True,
            "provider_cleanup": provider_cleanup,
        },
        "result": result,
    }
    _atomic_private_write(response_path, _canonical(response))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pinned Sandoq offline-catalog worker")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--request-sha256")
    parser.add_argument("--response", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--print-contract", action="store_true")
    parser.add_argument("--write-site-manifest", type=Path)
    parser.add_argument("--site-root", type=Path)
    parser.add_argument("--site-directory")
    return parser


def contract_record() -> dict[str, object]:
    runtime_sha256 = worker_runtime_sha256()
    return {
        "schema_version": 1,
        "worker_protocol_version": WORKER_PROTOCOL_VERSION,
        "provider_commit": PINNED_PROVIDER_COMMIT,
        "provider_tree": PINNED_PROVIDER_TREE,
        "provider_source_sha256": PINNED_PROVIDER_SOURCE_SHA256,
        "sandoq_client_version": PINNED_SANDOQ_CLIENT,
        "worker_runtime_sha256": runtime_sha256,
        "python_runtime_manifest_sha256": os.environ["SANDOQ_CATALOG_PYTHON_RUNTIME_MANIFEST_SHA256"],
        "worker_provision_identity_sha256": os.environ["SANDOQ_CATALOG_WORKER_PROVISION_IDENTITY_SHA256"],
        "worker_site_manifest_sha256": os.environ["SANDOQ_CATALOG_WORKER_SITE_MANIFEST_SHA256"],
        "cleanup_receipt_verifier_sha256": cleanup_receipt_verifier_sha256(),
        "inventory_probe_code_sha256": inventory_probe_code_sha256(),
        "inventory_probe_environment_sha256": inventory_probe_environment_sha256(runtime_sha256),
        "required_environment_names": sorted(_REQUIRED_ENVIRONMENT_NAMES),
        "runtime_invariants": dict(sorted(_REQUIRED_ENVIRONMENT.items())),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.write_site_manifest is not None:
        if (
            args.site_root is None
            or args.site_directory is None
            or args.print_contract
            or any(value is not None for value in (args.request, args.request_sha256, args.response, args.artifact_dir))
        ):
            return 2
        try:
            manifest = _runtime_site_tree_record(args.site_root, args.site_directory)
            _atomic_private_write(args.write_site_manifest, _canonical(manifest))
        except BaseException:
            return 1
        print(
            _canonical(
                {
                    "schema_version": 1,
                    "directories": len(manifest["directories"]),
                    "files": len(manifest["files"]),
                }
            ).decode()
        )
        return 0
    if args.print_contract:
        if any(
            value is not None
            for value in (
                args.request,
                args.request_sha256,
                args.response,
                args.artifact_dir,
                args.site_root,
                args.site_directory,
            )
        ):
            return 2
        try:
            # The contract probe is deliberately task-free and credential-free.  It
            # seals the immutable runtime/provider inputs, while operational requests
            # perform the complete environment and credential-path validation below.
            _activate_worker_site()
            contract = contract_record()
        except BaseException:
            return 1
        print(_canonical(contract).decode())
        return 0
    if (
        args.site_root is not None
        or args.site_directory is not None
        or any(value is None for value in (args.request, args.request_sha256, args.response, args.artifact_dir))
    ):
        return 2
    # The controller redirects these too.  Do it again here so provider logs or
    # exception strings cannot disclose private task/image/session material if
    # an operator invokes the worker directly.
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        try:

            async def run() -> None:
                loop = asyncio.get_running_loop()
                worker_task = asyncio.create_task(_run_worker(args))
                installed: list[signal.Signals] = []
                for current_signal in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(current_signal, worker_task.cancel)
                    except (NotImplementedError, RuntimeError):
                        continue
                    installed.append(current_signal)
                try:
                    await worker_task
                finally:
                    for current_signal in installed:
                        loop.remove_signal_handler(current_signal)

            asyncio.run(run())
        except BaseException:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
