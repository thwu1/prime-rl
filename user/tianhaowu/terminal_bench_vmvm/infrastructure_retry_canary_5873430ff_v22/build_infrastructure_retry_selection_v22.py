#!/usr/bin/env python3
"""Build or verify the opaque v22 infrastructure-retry selection."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import types
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
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
SOURCE_ROOT = BASE / "sources/prime-rl-5873430ff-v22"
SOURCE_REVISION = "5873430ffbabc32672368c7df74f56023865d2b5"
SOURCE_TREE = "e7d9d5a8cf4ca06b9ff6496ea4318154c6fcd730"
VERIFIERS_REVISION = "615b1a30ee3d23cf8d835b64174229c19da887bc"
RENDERERS_REVISION = "044d9e2541f6a911cacae9da353fc063911ef1f8"
PYDANTIC_CONFIG_REVISION = "896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f"
VMVM_SHA256 = "1e7c8ac2906a45d8212d609b5900fdc3d30f91ba73d4bcdb1c36dfc8bfdd09e2"
WORKFLOW = SOURCE_ROOT / "user/tianhaowu/terminal_bench_vmvm"
PINNED_SOURCE_FILES = {
    WORKFLOW
    / "audit_oracle_repair_canary.py": "414d68f9aa238af239af013f2f58f5e3aeec94540b3270852ee797c0ed938b64",
    WORKFLOW
    / "build_oracle_repair_canary.py": "95b6743dc39c9de3fa3aa73d38ed5a5fee411fc9fc9c7e9f9959d176dda1349e",
    WORKFLOW
    / "export_oracle_tasks.py": "a820467fabdc3bcfb44f9670b92cda7d09cc40c15ab817eb70eaa9ea20e00211",
    WORKFLOW
    / "run_oracle.py": "a148d85f0637deee36af31b1277f4df21df9d11c4fd12bf3b67a0b2dc49b7c98",
    WORKFLOW
    / "run_oracle.sbatch": "9f4e746a5a05217f43c684b1d5737a846555d284ea0fb924466358181e0d253c",
    WORKFLOW
    / "terminal_bench_vmvm/taskset.py": "94d12722279f11ccd34b00c28d00db545c4f254af907af4ee774b0e1c7079330",
}
SELF = ARTIFACT_ROOT / "build_infrastructure_retry_selection_v22.py"
V1_ROOT = BASE / "oracle/infrastructure_retry_canary_63dc81dee_v1"
V1_GENERATOR = V1_ROOT / "build_infrastructure_retry_selection.py"
V1_GENERATOR_SHA256 = "61ea59b4ce6470c77e0e1f4ae4beef1c5709bab27edfb373698bb8c7b570ee86"
PYTHON_REAL = Path(
    "/storage/home/tianhaowu/.local/share/uv/python/"
    "cpython-3.13.15-linux-aarch64-gnu/bin/python3.13"
)
PYTHON_SHA256 = "f53c112756a06959fd532fa70e3108f89b90550c71f5c1afc26f8985c772a121"
SOURCE_WHEELS_SHA256 = (
    "fc699fe41c867f4646fa9f383da96a16492df7dd1d780eb1351437691f61224e"
)
PACKAGING_SNAPSHOT = SELF.parent / "packaging-26.3-py3-none-any.whl.snapshot.json"
PACKAGING_SNAPSHOT_SHA256 = (
    "6025752344370d775f1a22e6c9d3f3bfaa57f9b5e17e2b296088864dfdc14761"
)
PACKAGING_VERSION = "26.3"
PACKAGING_WHEEL_SHA256 = (
    "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c"
)
PACKAGING_WHEEL_SIZE = 129_956
PACKAGING_MEMBER_COUNT = 29
PACKAGING_MEMBER_MANIFEST_SHA256 = (
    "d02fb4c0b14244ef8a78ef2b91c29d988754c230c977089eb0c65eb5152e6ea4"
)
PACKAGING_MODULE_MEMBERS = (
    "packaging/__init__.py",
    "packaging/_elffile.py",
    "packaging/_manylinux.py",
    "packaging/_musllinux.py",
    "packaging/_parser.py",
    "packaging/_ranges.py",
    "packaging/_structures.py",
    "packaging/_tokenizer.py",
    "packaging/dependency_groups.py",
    "packaging/direct_url.py",
    "packaging/errors.py",
    "packaging/licenses/__init__.py",
    "packaging/licenses/_spdx.py",
    "packaging/markers.py",
    "packaging/metadata.py",
    "packaging/pylock.py",
    "packaging/ranges.py",
    "packaging/requirements.py",
    "packaging/specifiers.py",
    "packaging/tags.py",
    "packaging/utils.py",
    "packaging/version.py",
)
SNAPSHOT_MODULE_NAMES = (
    "terminal_bench_vmvm",
    "terminal_bench_vmvm.source_wheels",
    "export_oracle_tasks",
    "build_oracle_repair_canary",
    "audit_oracle_repair_canary",
)

SOURCE_ORACLE = BASE / "oracle/mobius_full_oracle_public_fb8b5c1fd_use2-3_v1"
REPAIR_ORACLE = BASE / "oracle/mobius_repair_canary_8186ec935_use2-3_v3"
REPAIR_PRIVATE = BASE / "oracle/mobius_repair_canary_8186ec935_use2-3_v3_private"
SOURCE_WHEEL_INPUT = (
    BASE / "oracle/source_wheel_policy_probe_v1/probe_inputs.private.json"
)
OUTPUT_ROOT = BASE / "oracle/mobius_infrastructure_retry_selection_5873430ff_v22"
TASK_FILE = OUTPUT_ROOT / "retry.tasks.txt"
ROLE_FILE = OUTPUT_ROOT / "selection_roles.private.json"
RECEIPT = OUTPUT_ROOT / "selection_receipt.json"

SOURCE_ARTIFACTS = {
    "run_identity.json": "389d3d69535aa6d488fee6fc9c8c422c3379992fbb512a4800bdce45c5bfe8a0",
    "run_config.json": "c200156b5ee949391bd69b2c2d5c641cdb23587884243edcad2802360ffdaff0",
    "results.jsonl": "b5e6e6952781cd7e3d6b141b2431ddd152c7e538d520f79c14317173ec071ec9",
    "summary.json": "5fb752308c392a78b8e074c7d9222ad6c663ddae9cf98e34ada0e0499fe9f18b",
    "provenance.txt": "3b5aedafe811b499d6e60520342112d0dec77e1c6f9eb77adafd0791317c0551",
    "invocations.jsonl": "ad97b470a75ade63d6af2a15ed3740b2a3a1808bef9f81d6cd942111d774e553",
}
REPAIR_ARTIFACTS = {
    "run_identity.json": "56bb6d8737f3baa5241d958e9c177fb45cd3ff532c795ef29742dc1a9e4c6119",
    "run_config.json": "0e8126d13f0177c79037fc4de0cd5d9b0dab1e132af528bd8885dc36ce4d46cf",
    "results.jsonl": "12d7e8668998229777d079f7890535bf95a7800f4029ad3393616ac448cba75b",
    "summary.json": "77eae5835ec2944c590e8ce5fb92ef045122f4459211add184c772776ac8f3dd",
    "provenance.txt": "3316062055fdc33ab95b6ede32bb70733af6678e1b7ceafbd56453eee1813e6b",
    "invocations.jsonl": "a6b65d39fec5752cc0b1b39430f5c6c17d91e2f287247952760a3a5ad931a548",
}
REPAIR_TASK_FILE = REPAIR_PRIVATE / "canary.tasks.txt"
REPAIR_TASK_FILE_SHA256 = (
    "24795da8792d8fad07b0b5b6c5cf2c47c56278ff57577139f3eb64de2b03facb"
)
REPAIR_RECEIPT = REPAIR_PRIVATE / "builder.receipt.json"
REPAIR_RECEIPT_SHA256 = (
    "655f969784133bf6218441ebd35f44fe49a94272c1e9d80945c5a0b0fc73d384"
)
SOURCE_WHEEL_INPUT_SHA256 = (
    "407a7b960f8a35e5116584db9cbb905e51b31d2031e7f8c481185188c31d6350"
)

ATTEMPT_POLICY = {
    "sandbox_error": {
        "retry_scope": "exception_type_only",
        "infra_retries": 4,
        "maximum_attempts": 5,
    },
    "asyncio_timeout_error": {
        "retry_scope": "none",
        "infra_retries": 0,
        "maximum_attempts": 1,
    },
    "timeout_category_candidates": {
        "count": 11,
        "classification_only": True,
        "category_does_not_enable_retries": True,
    },
    "timeout_bounds_seconds": {"setup": 7200, "validate": 21600, "session": 43200},
    "broad_harness_error_retry": False,
}
SHA_RE = re.compile(r"[0-9a-f]{64}")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class SelectionV22Error(RuntimeError):
    """A stable, aggregate-only v22 selection failure."""


def fail(code: str) -> None:
    raise SelectionV22Error(
        code if re.fullmatch(r"[a-z0-9_]{1,96}", code) else "internal_error"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def stable_file(
    path: Path, digest: str | None, mode: int, *, allow_empty: bool = False
) -> bytes:
    if digest is not None and SHA_RE.fullmatch(digest) is None:
        fail("artifact_hash_invalid")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != mode
            or before.st_uid != OWNER_UID
            or before.st_nlink != 1
            or (before.st_size == 0 and not allow_empty)
            or before.st_size > 64 << 20
        ):
            fail("artifact_identity_invalid")
        raw = b""
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(1 << 20, remaining))
            if not chunk:
                fail("artifact_short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        path_after = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise SelectionV22Error("artifact_unreadable") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    def signature(value: os.stat_result) -> tuple[int, ...]:
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

    if signature(before) != signature(after) or signature(after) != signature(
        path_after
    ):
        fail("artifact_changed")
    if digest is not None and sha256_bytes(raw) != digest:
        fail("artifact_hash_mismatch")
    return raw


def require_directory(path: Path, mode: int) -> None:
    try:
        status = path.stat(follow_symlinks=False)
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SelectionV22Error("directory_invalid") from error
    if (
        canonical != path
        or not stat.S_ISDIR(status.st_mode)
        or stat.S_IMODE(status.st_mode) != mode
        or status.st_uid != OWNER_UID
    ):
        fail("directory_invalid")


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
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
            _directory_identity(before) != _directory_identity(after)
            or _directory_identity(after) != _directory_identity(current)
            or names_after != names_before
            or names_current != names_before
            or root.resolve(strict=True) != root
        ):
            fail("artifact_root_inventory_invalid")
    except SelectionV22Error:
        raise
    except (OSError, RuntimeError) as error:
        raise SelectionV22Error("artifact_root_inventory_invalid") from error
    finally:
        if fresh_fd >= 0:
            os.close(fresh_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def load_v1():
    require_directory(V1_ROOT, 0o700)
    raw = stable_file(V1_GENERATOR, V1_GENERATOR_SHA256, 0o500)
    module = types.ModuleType("retry_selection_v1_frozen")
    module.__file__ = str(V1_GENERATOR)
    try:
        exec(compile(raw, str(V1_GENERATOR), "exec"), module.__dict__)  # noqa: S102
    except Exception as error:
        raise SelectionV22Error("v1_import_invalid") from error
    # V22 keeps the reviewed V1 algorithms but redirects every execution-source
    # global to its fresh, clean detached snapshot.  No V1 source byte changes.
    module.SOURCE_ROOT = SOURCE_ROOT
    module.SOURCE_REVISION = SOURCE_REVISION
    module.SOURCE_TREE = SOURCE_TREE
    module.VERIFIERS_REVISION = VERIFIERS_REVISION
    module.RENDERERS_REVISION = RENDERERS_REVISION
    module.PYDANTIC_CONFIG_REVISION = PYDANTIC_CONFIG_REVISION
    module.VMVM_SHA256 = VMVM_SHA256
    module.WORKFLOW = WORKFLOW
    module.PINNED_SOURCE_FILES = dict(PINNED_SOURCE_FILES)
    return module


def call_v1(code: str, function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except SelectionV22Error:
        raise
    except Exception as error:
        raise SelectionV22Error(code) from error


def git_output(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin",
            },
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SelectionV22Error("git_unavailable") from error
    if (
        result.returncode != 0
        or result.stderr
        or len(result.stdout.encode("utf-8")) > 1 << 20
    ):
        fail("git_validation_failed")
    return result.stdout


def validate_execution_source(v1: Any) -> None:
    source_root = v1.SOURCE_ROOT
    try:
        source_status = source_root.stat(follow_symlinks=False)
        source_canonical = source_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SelectionV22Error("source_identity_invalid") from error
    if (
        source_canonical != source_root
        or source_root.is_symlink()
        or not stat.S_ISDIR(source_status.st_mode)
        or source_status.st_uid != OWNER_UID
    ):
        fail("source_identity_invalid")

    try:
        symbolic = subprocess.run(
            ["/usr/bin/git", "-C", str(source_root), "symbolic-ref", "-q", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin",
            },
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SelectionV22Error("git_unavailable") from error
    if symbolic.returncode != 1 or symbolic.stdout or symbolic.stderr:
        fail("source_not_detached")

    if (
        git_output(source_root, "rev-parse", "--verify", "HEAD").strip()
        != v1.SOURCE_REVISION
        or git_output(source_root, "rev-parse", "HEAD^{tree}").strip() != v1.SOURCE_TREE
        or git_output(
            source_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        != ""
        or git_output(
            source_root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            ":(glob)**/_version.py",
        )
        != ""
    ):
        fail("source_identity_invalid")

    for relative, revision in (
        ("deps/verifiers", v1.VERIFIERS_REVISION),
        ("deps/renderers", v1.RENDERERS_REVISION),
        ("deps/pydantic-config", v1.PYDANTIC_CONFIG_REVISION),
    ):
        checkout = source_root / relative
        if (
            git_output(source_root, "rev-parse", f"HEAD:{relative}").strip() != revision
            or git_output(checkout, "rev-parse", "HEAD").strip() != revision
            or git_output(checkout, "status", "--porcelain=v1", "--untracked-files=all")
            != ""
            or git_output(
                checkout,
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--",
                ":(glob)**/_version.py",
            )
            != ""
        ):
            fail("source_dependency_mismatch")

    for path, digest in v1.PINNED_SOURCE_FILES.items():
        stable_file(path, digest, 0o644)

    vmvm_root = source_root / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    initializer = vmvm_root / "__init__.py"
    vmvm_files = sorted(vmvm_root.glob("*.py"))
    if not vmvm_files or vmvm_files.count(initializer) != 1:
        fail("vmvm_binding_invalid")
    records: list[bytes] = []
    for path in vmvm_files:
        raw = stable_file(
            path,
            EMPTY_SHA256 if path == initializer else None,
            0o644,
            allow_empty=path == initializer,
        )
        if path == initializer and raw != b"":
            fail("vmvm_binding_invalid")
        records.append(
            f"{sha256_bytes(raw)}  {path.relative_to(source_root).as_posix()}\n".encode()
        )
    if sha256_bytes(b"".join(records)) != v1.VMVM_SHA256:
        fail("vmvm_binding_invalid")


def validate_source_wheel_cardinality(v1: Any) -> None:
    call_v1(
        "source_wheel_cardinality_invalid",
        v1.validate_source_wheel_cardinality,
    )


@contextmanager
def locked_oracle(
    directory: Path, *, directory_mode: int, lock_mode: int
) -> Iterator[None]:
    require_directory(directory, directory_mode)
    lock_path = directory / ".writer.lock"
    descriptor = -1
    try:
        descriptor = os.open(lock_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        descriptor_status = os.fstat(descriptor)
        path_status = os.stat(lock_path, follow_symlinks=False)

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
            identity(descriptor_status) != identity(path_status)
            or not stat.S_ISREG(descriptor_status.st_mode)
            or stat.S_IMODE(descriptor_status.st_mode) != lock_mode
            or descriptor_status.st_uid != OWNER_UID
            or descriptor_status.st_nlink != 1
            or descriptor_status.st_size != 0
        ):
            fail("oracle_lock_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SelectionV22Error("oracle_writer_active") from error
        yield
    except OSError as error:
        raise SelectionV22Error("oracle_lock_invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def validate_inputs(v1: Any) -> dict[Path, tuple[bytes, int]]:
    captured: dict[Path, tuple[bytes, int]] = {}
    captured[PACKAGING_SNAPSHOT] = (
        stable_file(PACKAGING_SNAPSHOT, PACKAGING_SNAPSHOT_SHA256, 0o400),
        0o400,
    )
    require_directory(SOURCE_ORACLE, 0o755)
    require_directory(REPAIR_ORACLE, 0o700)
    for root, records, mode in (
        (SOURCE_ORACLE, SOURCE_ARTIFACTS, 0o644),
        (REPAIR_ORACLE, REPAIR_ARTIFACTS, 0o600),
    ):
        for name, digest in records.items():
            path = root / name
            captured[path] = (stable_file(path, digest, mode), mode)
    captured[REPAIR_TASK_FILE] = (
        stable_file(REPAIR_TASK_FILE, REPAIR_TASK_FILE_SHA256, 0o600),
        0o600,
    )
    captured[REPAIR_RECEIPT] = (
        stable_file(REPAIR_RECEIPT, REPAIR_RECEIPT_SHA256, 0o600),
        0o600,
    )
    captured[SOURCE_WHEEL_INPUT] = (
        stable_file(SOURCE_WHEEL_INPUT, SOURCE_WHEEL_INPUT_SHA256, 0o600),
        0o600,
    )
    validate_source_wheel_cardinality(v1)
    return captured


def _snapshot_module_collision(name: str) -> bool:
    return (
        name in SNAPSHOT_MODULE_NAMES
        or name.startswith(("terminal_bench_vmvm.", "packaging."))
        or name == "packaging"
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            fail("packaging_snapshot_invalid")
        value[key] = item
    return value


def _packaging_module_name(member: str) -> str:
    if member == "packaging/__init__.py":
        return "packaging"
    if member.endswith("/__init__.py"):
        return member.removesuffix("/__init__.py").replace("/", ".")
    return member.removesuffix(".py").replace("/", ".")


def load_packaging_snapshot() -> tuple[bytes, dict[str, tuple[str, bytes]]]:
    try:
        if PACKAGING_SNAPSHOT.resolve(strict=True) != PACKAGING_SNAPSHOT:
            fail("packaging_snapshot_invalid")
    except (OSError, RuntimeError) as error:
        raise SelectionV22Error("packaging_snapshot_invalid") from error
    raw = stable_file(
        PACKAGING_SNAPSHOT,
        PACKAGING_SNAPSHOT_SHA256,
        0o400,
    )
    try:
        value = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SelectionV22Error("packaging_snapshot_invalid") from error
    if (
        not isinstance(value, dict)
        or canonical_json(value) + b"\n" != raw
        or set(value)
        != {
            "artifact_type",
            "encoding",
            "filename",
            "member_count",
            "member_manifest_sha256",
            "version",
            "wheel_base64",
            "wheel_sha256",
            "wheel_size",
        }
        or value.get("artifact_type")
        != "terminal_bench_vmvm_python_wheel_snapshot_v1"
        or value.get("encoding") != "base64"
        or value.get("filename") != "packaging-26.3-py3-none-any.whl"
        or value.get("version") != PACKAGING_VERSION
        or value.get("wheel_sha256") != PACKAGING_WHEEL_SHA256
        or value.get("wheel_size") != PACKAGING_WHEEL_SIZE
        or value.get("member_count") != PACKAGING_MEMBER_COUNT
        or value.get("member_manifest_sha256")
        != PACKAGING_MEMBER_MANIFEST_SHA256
        or not isinstance(value.get("wheel_base64"), str)
    ):
        fail("packaging_snapshot_invalid")
    try:
        wheel = base64.b64decode(value["wheel_base64"], validate=True)
    except (ValueError, TypeError) as error:
        raise SelectionV22Error("packaging_snapshot_invalid") from error
    if len(wheel) != PACKAGING_WHEEL_SIZE or sha256_bytes(wheel) != PACKAGING_WHEEL_SHA256:
        fail("packaging_wheel_invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            infos = archive.infolist()
            if len(infos) != PACKAGING_MEMBER_COUNT or len(
                {item.filename for item in infos}
            ) != len(infos):
                fail("packaging_wheel_manifest_invalid")
            records: list[dict[str, object]] = []
            members: dict[str, bytes] = {}
            for item in sorted(infos, key=lambda candidate: candidate.filename):
                if (
                    item.flag_bits & 0x1
                    or item.is_dir()
                    or item.filename.startswith("/")
                    or "\\" in item.filename
                    or any(part in {"", ".", ".."} for part in item.filename.split("/"))
                    or item.file_size > 2 << 20
                ):
                    fail("packaging_wheel_manifest_invalid")
                payload = archive.read(item)
                if len(payload) != item.file_size:
                    fail("packaging_wheel_manifest_invalid")
                records.append(
                    {
                        "mode": stat.S_IMODE(item.external_attr >> 16),
                        "path": item.filename,
                        "sha256": sha256_bytes(payload),
                        "size": len(payload),
                    }
                )
                members[item.filename] = payload
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise SelectionV22Error("packaging_wheel_invalid") from error
    if sha256_bytes(canonical_json(records)) != PACKAGING_MEMBER_MANIFEST_SHA256:
        fail("packaging_wheel_manifest_invalid")
    module_members = {name for name in members if name.endswith(".py")}
    if module_members != set(PACKAGING_MODULE_MEMBERS):
        fail("packaging_wheel_module_set_invalid")
    sources = {
        _packaging_module_name(member): (
            f"{PACKAGING_SNAPSHOT}!/{member}",
            members[member],
        )
        for member in PACKAGING_MODULE_MEMBERS
    }
    if len(sources) != len(PACKAGING_MODULE_MEMBERS):
        fail("packaging_wheel_module_set_invalid")
    return raw, sources


class _PackagingSnapshotFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, sources: Mapping[str, tuple[str, bytes]]) -> None:
        self.sources = dict(sources)

    def find_spec(
        self,
        fullname: str,
        _path: Sequence[str] | None,
        _target: types.ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname in self.sources:
            return importlib.util.spec_from_loader(
                fullname,
                self,
                origin=self.sources[fullname][0],
                is_package=fullname in {"packaging", "packaging.licenses"},
            )
        if fullname == "packaging" or fullname.startswith("packaging."):
            raise ModuleNotFoundError("unmanifested_packaging_module")
        return None

    def create_module(self, _spec: importlib.machinery.ModuleSpec) -> None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        name = module.__name__
        if name not in self.sources:
            raise ModuleNotFoundError("unmanifested_packaging_module")
        origin, raw = self.sources[name]
        module.__file__ = origin
        module.__package__ = name if name in {"packaging", "packaging.licenses"} else name.rpartition(".")[0]
        if name in {"packaging", "packaging.licenses"}:
            module.__path__ = []
        exec(compile(raw, origin, "exec"), module.__dict__)  # noqa: S102


def _load_packaging_modules(
    sources: Mapping[str, tuple[str, bytes]],
) -> _PackagingSnapshotFinder:
    finder = _PackagingSnapshotFinder(sources)
    sys.meta_path.insert(0, finder)
    try:
        markers = importlib.import_module("packaging.markers")
        requirements = importlib.import_module("packaging.requirements")
        utils = importlib.import_module("packaging.utils")
        packaging = sys.modules["packaging"]
        requirement = requirements.Requirement(
            "example_pkg>=1; python_version >= '3.8'"
        )
        marker = markers.Marker("python_version >= '3.8'")
        if (
            getattr(packaging, "__version__", None) != PACKAGING_VERSION
            or utils.canonicalize_name(requirement.name) != "example-pkg"
            or str(marker) != 'python_version >= "3.8"'
        ):
            fail("packaging_semantic_probe_invalid")
    except SelectionV22Error:
        raise
    except Exception as error:
        raise SelectionV22Error("snapshot_packaging_import_invalid") from error
    return finder


def _snapshot_source(v1: Any, name: str) -> tuple[Path, bytes]:
    if name == "terminal_bench_vmvm.source_wheels":
        path = v1.WORKFLOW / "terminal_bench_vmvm/source_wheels.py"
        digest = SOURCE_WHEELS_SHA256
    else:
        filename = f"{name}.py"
        path = v1.WORKFLOW / filename
        digest = v1.PINNED_SOURCE_FILES.get(path)
    if not isinstance(digest, str) or SHA_RE.fullmatch(digest) is None:
        fail("snapshot_source_binding_invalid")
    try:
        if path.resolve(strict=True) != path:
            fail("snapshot_source_binding_invalid")
        raw = stable_file(path, digest, 0o644)
    except SelectionV22Error as error:
        raise SelectionV22Error("snapshot_source_binding_invalid") from error
    except (OSError, RuntimeError) as error:
        raise SelectionV22Error("snapshot_source_binding_invalid") from error
    return path, raw


def _exec_snapshot_module(
    name: str,
    path: Path,
    raw: bytes,
    *,
    failure_code: str,
) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)  # noqa: S102
    except Exception as error:
        raise SelectionV22Error(failure_code) from error
    return module


@contextmanager
def snapshot_module_scope(
    v1: Any,
) -> Iterator[tuple[types.ModuleType, types.ModuleType]]:
    if any(_snapshot_module_collision(name) for name in sys.modules):
        fail("snapshot_module_collision")
    original_path = list(sys.path)
    original_modules = dict(sys.modules)
    original_meta_path = list(sys.meta_path)
    original_importer_cache = dict(sys.path_importer_cache)
    source_records: dict[str, tuple[Path, bytes]] = {}
    packaging_snapshot_raw = b""
    packaging_sources: dict[str, tuple[str, bytes]] = {}
    try:
        for name in SNAPSHOT_MODULE_NAMES[1:]:
            source_records[name] = _snapshot_source(v1, name)

        packaging_snapshot_raw, packaging_sources = load_packaging_snapshot()
        packaging_finder = _load_packaging_modules(packaging_sources)

        package_root = v1.WORKFLOW / "terminal_bench_vmvm"
        package = types.ModuleType("terminal_bench_vmvm")
        package.__file__ = str(package_root / "__init__.py")
        package.__package__ = "terminal_bench_vmvm"
        package.__path__ = []
        sys.modules["terminal_bench_vmvm"] = package

        source_wheels = _exec_snapshot_module(
            "terminal_bench_vmvm.source_wheels",
            *source_records["terminal_bench_vmvm.source_wheels"],
            failure_code="snapshot_source_wheels_import_invalid",
        )
        package.source_wheels = source_wheels
        exported = _exec_snapshot_module(
            "export_oracle_tasks",
            *source_records["export_oracle_tasks"],
            failure_code="snapshot_export_import_invalid",
        )
        builder = _exec_snapshot_module(
            "build_oracle_repair_canary",
            *source_records["build_oracle_repair_canary"],
            failure_code="snapshot_builder_import_invalid",
        )
        audit = _exec_snapshot_module(
            "audit_oracle_repair_canary",
            *source_records["audit_oracle_repair_canary"],
            failure_code="snapshot_auditor_import_invalid",
        )
        modules = {
            "terminal_bench_vmvm.source_wheels": source_wheels,
            "export_oracle_tasks": exported,
            "build_oracle_repair_canary": builder,
            "audit_oracle_repair_canary": audit,
        }
        for name, module in modules.items():
            path, _raw = source_records[name]
            try:
                observed = Path(module.__file__).resolve(strict=True)
            except (AttributeError, OSError, RuntimeError, TypeError) as error:
                raise SelectionV22Error("snapshot_module_origin_invalid") from error
            if observed != path:
                fail("snapshot_module_origin_invalid")
        for name, module in tuple(sys.modules.items()):
            if name != "packaging" and not name.startswith("packaging."):
                continue
            if name not in packaging_sources:
                fail("snapshot_packaging_unmanifested_module")
            module_spec = getattr(module, "__spec__", None)
            if (
                getattr(module, "__file__", None) != packaging_sources[name][0]
                or module_spec is None
                or module_spec.loader is not packaging_finder
                or module_spec.origin != packaging_sources[name][0]
            ):
                fail("snapshot_packaging_origin_invalid")
        yield audit, builder
    finally:
        sys.path[:] = original_path
        sys.meta_path[:] = original_meta_path
        sys.path_importer_cache.clear()
        sys.path_importer_cache.update(original_importer_cache)
        for name in tuple(sys.modules):
            if name not in original_modules:
                sys.modules.pop(name, None)
        for name, module in original_modules.items():
            sys.modules[name] = module
        for name, (path, raw) in source_records.items():
            try:
                if stable_file(path, sha256_bytes(raw), 0o644) != raw:
                    fail("snapshot_source_changed")
            except SelectionV22Error as error:
                raise SelectionV22Error("snapshot_source_changed") from error
        if packaging_snapshot_raw:
            try:
                if (
                    stable_file(
                        PACKAGING_SNAPSHOT,
                        PACKAGING_SNAPSHOT_SHA256,
                        0o400,
                    )
                    != packaging_snapshot_raw
                ):
                    fail("packaging_snapshot_changed")
            except SelectionV22Error as error:
                raise SelectionV22Error("packaging_snapshot_changed") from error


def load_snapshots(v1: Any, captured: Mapping[Path, tuple[bytes, int]]):
    try:
        with snapshot_module_scope(v1) as (audit, builder):
            source = audit._load_full_source(
                SOURCE_ORACLE,
                v1.EXPECTED_TOTAL,
                expected_prime_rl_commit=v1.SOURCE_PRIME_REVISION,
                expected_verifiers_commit=v1.SOURCE_VERIFIERS_REVISION,
                expected_vmvm_tb_v2_sha256=v1.SOURCE_VMVM_SHA256,
            )
            task_path, task_raw, repair_tasks, task_sha = audit._task_file(
                REPAIR_TASK_FILE
            )
            audit._builder_receipt(
                REPAIR_RECEIPT,
                source=source,
                task_bytes=task_raw,
                task_sha256=task_sha,
                control_count=20,
                seed=builder.DEFAULT_SEED,
            )
            repair = audit._load_canary(
                REPAIR_ORACLE,
                task_file=task_path,
                task_sha256=task_sha,
                tasks=repair_tasks,
                source=source,
                expected_prime_rl_commit=v1.REPAIR_PRIME_REVISION,
                expected_verifiers_commit=v1.REPAIR_VERIFIERS_REVISION,
                expected_vmvm_tb_v2_sha256=v1.REPAIR_VMVM_SHA256,
            )
    except SelectionV22Error:
        raise
    except Exception as error:
        raise SelectionV22Error("oracle_snapshot_invalid") from error
    wheel_value = call_v1(
        "source_wheel_input_invalid",
        v1.strict_json,
        captured[SOURCE_WHEEL_INPUT][0],
    )
    entries = wheel_value.get("entries")
    provenance = wheel_value.get("provenance")
    if (
        captured[SOURCE_WHEEL_INPUT][0] != canonical_json(wheel_value) + b"\n"
        or wheel_value.get("kind") != "source-wheel-policy-probe-input"
        or wheel_value.get("complete") is not False
        or not isinstance(entries, list)
        or len(entries) != v1.EXPECTED_SOURCE_WHEEL
        or not isinstance(provenance, dict)
        or provenance.get("oracle_results_sha256") != SOURCE_ARTIFACTS["results.jsonl"]
    ):
        fail("source_wheel_input_invalid")
    wheel_tasks = [entry.get("task") for entry in entries if isinstance(entry, dict)]
    if (
        len(wheel_tasks) != v1.EXPECTED_SOURCE_WHEEL
        or any(
            not isinstance(task, str) or v1.SLUG_RE.fullmatch(task) is None
            for task in wheel_tasks
        )
        or len(set(wheel_tasks)) != len(wheel_tasks)
    ):
        fail("source_wheel_input_invalid")
    return source, repair, wheel_tasks


def packaging_provenance() -> dict[str, object]:
    return {
        "name": "packaging",
        "version": PACKAGING_VERSION,
        "wheel_sha256": PACKAGING_WHEEL_SHA256,
        "wheel_size": PACKAGING_WHEEL_SIZE,
        "member_count": PACKAGING_MEMBER_COUNT,
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


def derive_roles(
    v1: Any, source_rows: Sequence[Mapping[str, Any]], selected: Sequence[str]
) -> dict[str, Any]:
    source_by_slug = {str(row["slug"]): row for row in source_rows}
    candidates = [
        slug
        for slug in selected
        if call_v1(
            "selection_classification_failed",
            v1.evidence_categories,
            source_by_slug[slug],
        )
    ]
    controls = [slug for slug in selected if slug not in set(candidates)]
    categories = {
        slug: list(
            call_v1(
                "selection_classification_failed",
                v1.evidence_categories,
                source_by_slug[slug],
            )
        )
        for slug in candidates
    }
    primary_categories = {slug: values[0] for slug, values in categories.items()}
    if (
        len(candidates) != v1.EXPECTED_CANDIDATES
        or len(controls) != v1.CONTROL_COUNT
        or sum(value == "timeout" for value in primary_categories.values()) != 11
    ):
        fail("selection_roles_invalid")
    return {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_roles",
        "candidates": candidates,
        "candidate_categories": categories,
        "candidate_primary_category": primary_categories,
        "controls": controls,
    }


def prepare(
    generator_sha256: str,
    *,
    verify_only: bool,
    validate_inputs_only: bool = False,
) -> dict[str, Any]:
    if verify_only and validate_inputs_only:
        fail("operation_mode_invalid")
    validate_artifact_root_inventory()
    v1 = load_v1()
    validate_execution_source(v1)
    if validate_inputs_only and (OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink()):
        fail("selection_output_not_fresh")
    with ExitStack() as locks:
        locks.enter_context(
            locked_oracle(SOURCE_ORACLE, directory_mode=0o755, lock_mode=0o644)
        )
        locks.enter_context(
            locked_oracle(REPAIR_ORACLE, directory_mode=0o700, lock_mode=0o600)
        )
        captured = validate_inputs(v1)
        source, repair, wheel_tasks = load_snapshots(v1, captured)
        selected, metadata = call_v1(
            "selection_derivation_failed",
            v1.select_rows,
            source.results,
            repair.results,
            wheel_tasks,
        )
        roles = derive_roles(v1, source.results, selected)
        task_raw = "".join(f"{slug}\n" for slug in selected).encode()
        roles_raw = canonical_json(roles) + b"\n"
        v1.CANONICAL_SELF = SELF
        v1.OUTPUT_ROOT = OUTPUT_ROOT
        v1.TASK_FILE = TASK_FILE
        v1.RECEIPT = RECEIPT
        body = call_v1(
            "selection_receipt_build_failed",
            v1.receipt_body,
            selected,
            metadata,
            generator_sha256,
        )
        body["artifact_type"] = "terminal_bench_vmvm_infrastructure_retry_selection_v22"
        body["selection"]["role_file"] = {
            "path": str(ROLE_FILE),
            "mode": "0600",
            "sha256": sha256_bytes(roles_raw),
            "candidate_count": v1.EXPECTED_CANDIDATES,
            "control_count": v1.CONTROL_COUNT,
        }
        body["attempt_policy"] = ATTEMPT_POLICY
        body["module_import_closure"] = {
            "packaging": packaging_provenance(),
        }
        receipt_raw = call_v1(
            "selection_receipt_build_failed",
            v1.receipt_envelope,
            body,
        )
        expected = {
            TASK_FILE: task_raw,
            ROLE_FILE: roles_raw,
            RECEIPT: receipt_raw,
        }
        if validate_inputs_only:
            if OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink():
                fail("selection_output_not_fresh")
        elif verify_only:
            require_directory(OUTPUT_ROOT, 0o700)
            for path, raw in expected.items():
                if stable_file(path, sha256_bytes(raw), 0o600) != raw:
                    fail("selection_output_mismatch")
        else:
            if OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink():
                fail("selection_output_not_fresh")
            require_directory(OUTPUT_ROOT.parent, 0o755)
            parent_fd = os.open(
                OUTPUT_ROOT.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            directory_fd = -1
            try:
                os.mkdir(OUTPUT_ROOT.name, mode=0o700, dir_fd=parent_fd)
                os.fsync(parent_fd)
                directory_fd = os.open(
                    OUTPUT_ROOT.name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
                for path, raw in expected.items():
                    call_v1(
                        "selection_output_write_failed",
                        v1.write_private_at,
                        directory_fd,
                        path.name,
                        raw,
                    )
                os.fsync(directory_fd)
            finally:
                if directory_fd >= 0:
                    os.close(directory_fd)
                os.close(parent_fd)
        for path, (raw, mode) in captured.items():
            if stable_file(path, sha256_bytes(raw), mode) != raw:
                fail("oracle_source_changed")
        validate_execution_source(v1)
        validate_source_wheel_cardinality(v1)
        stable_file(SELF, generator_sha256, 0o500)
        validate_artifact_root_inventory()
        if validate_inputs_only:
            if OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink():
                fail("selection_output_not_fresh")
        else:
            require_directory(OUTPUT_ROOT, 0o700)
            for path, raw in expected.items():
                if stable_file(path, sha256_bytes(raw), 0o600) != raw:
                    fail("selection_output_mismatch")
    return {
        "state": (
            "validated_inputs"
            if validate_inputs_only
            else "verified"
            if verify_only
            else "prepared"
        ),
        "selected": len(selected),
        "retry_candidates": len(roles["candidates"]),
        "controls": len(roles["controls"]),
        "task_file_sha256": sha256_bytes(task_raw),
        "role_file_sha256": sha256_bytes(roles_raw),
        "selection_receipt_file_sha256": sha256_bytes(receipt_raw),
        "selection_receipt_sha256": json.loads(receipt_raw)["selection_receipt_sha256"],
        "projected_minimum_valid": body["final_union"]["projected_minimum_valid"],
    }


def validate_invocation() -> str:
    if (
        Path(__file__) != SELF
        or Path(sys.argv[0]) != SELF
        or SELF.resolve(strict=True) != SELF
    ):
        fail("noncanonical_invocation")
    if Path.cwd() != Path("/storage/home/tianhaowu"):
        fail("wrong_working_directory")
    expected_environment = {
        "APPROVED_RETRY_GENERATOR_SHA256",
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
    if set(os.environ) != expected_environment:
        fail("outer_environment_invalid")
    digest = os.environ["APPROVED_RETRY_GENERATOR_SHA256"]
    if (
        os.environ["HOME"] != "/storage/home/tianhaowu"
        or os.environ["PATH"] != "/usr/bin:/bin"
        or os.environ["LANG"] != "C"
        or os.environ["LC_ALL"] != "C"
        or os.environ["USER"] != "tianhaowu"
        or os.environ["LOGNAME"] != "tianhaowu"
        or os.environ["PYTHONDONTWRITEBYTECODE"] != "1"
        or Path(sys.executable).resolve(strict=True) != PYTHON_REAL
    ):
        fail("outer_environment_invalid")
    validate_artifact_root_inventory()
    stable_file(SELF, digest, 0o500)
    stable_file(PYTHON_REAL, PYTHON_SHA256, 0o755)
    load_v1().validate_tmux_ancestry()
    return digest


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--verify-only", action="store_true")
    modes.add_argument("--validate-inputs-only", action="store_true")
    args = parser.parse_args(argv)
    result = prepare(
        validate_invocation(),
        verify_only=args.verify_only,
        validate_inputs_only=args.validate_inputs_only,
    )
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    try:
        raise SystemExit(main())
    except SelectionV22Error as error:
        print(
            json.dumps({"state": "aborted", "code": str(error)}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except Exception:  # noqa: BLE001 - private failures must never escape
        print(
            json.dumps(
                {"state": "aborted", "code": "selection_failed"}, sort_keys=True
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
