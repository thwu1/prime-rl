#!/usr/bin/python3.12
# ruff: noqa: BLE001, S102
"""Create one rotated authorization for the reviewed VMVM lifecycle diagnostic."""

from __future__ import annotations

import hashlib
import os
import signal
import stat
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

LAUNCHER = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/"
    "vmvm_owner_lifecycle_9d7841b36_v4/launch_vmvm_owner_lifecycle_v4.py"
)
LAUNCHER_SHA256 = "354595d2f0822052d6b42cfe12233d9629f75c82a01060745c33ca308000a731"
AUTHORIZATION = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/approvals/"
    "vmvm_owner_lifecycle_9d7841b36_v4_599a27d3de4dafba2f59981c.authorization.json"
)
JOB_TOKEN = "599a27d3de4dafba2f59981c"
JOB_NAME = f"vmvm-owner-v4-{JOB_TOKEN}"
OWNER_UID = 656177
FILE_MODES = {
    "launcher": ("launch_vmvm_owner_lifecycle_v4.py", 0o500),
    "probe": ("probe_vmvm_owner_lifecycle_v4.py", 0o500),
    "wrapper": ("run_vmvm_owner_lifecycle_v4.sbatch", 0o500),
    "finalizer": ("finalize_vmvm_owner_lifecycle_v4.py", 0o500),
    "readme": ("README.md", 0o400),
    "tests": ("test_vmvm_owner_lifecycle_v4.py", 0o400),
}
BUNDLE_SHA256 = {
    "finalizer": "03b11faee9088da7c65be946752839e1eb6055bc435dc3543b92fec44e4cdc62",
    "launcher": LAUNCHER_SHA256,
    "probe": "4065b1d528f594638b55faa140294106703986103c1bb4821bb545c2aa4859ae",
    "readme": "a665e362557e124b77caef8eb59e178152021545bdf14e5086041990f7488db3",
    "tests": "5660f22fe1b2c1aa46b6020f6df897fbde842f6a52254ce3b6fe94b8766c2d2d",
    "wrapper": "a8fb8c04574d4de1cfa0cdb9137366baf34c74e72469bcd7e3c7a6814da46287",
}
HANDLED_SIGNALS = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
SUCCESS_OUTPUT = b'{"kind":"vmvm_owner_lifecycle_diagnostic_authorization_create_v4_candidate","state":"created"}\n'
FAILURE_OUTPUT = b'{"code":"authorization_create_failed","state":"failed"}\n'
INTERRUPTED = False


def signal_handler(_signum: int, _frame: object) -> None:
    global INTERRUPTED
    INTERRUPTED = True


def install_signal_handlers() -> None:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        for signum in HANDLED_SIGNALS:
            signal.signal(signum, signal_handler)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def emit_bounded(descriptor: int, payload: bytes) -> None:
    if len(payload) > 256 or not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise RuntimeError("output_contract")
    if os.write(descriptor, payload) != len(payload):
        raise RuntimeError("output_write")


def signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def load_launcher() -> types.ModuleType:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    descriptor = -1
    try:
        before = LAUNCHER.lstat()
        descriptor = os.open(LAUNCHER, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = 1 << 20
        while remaining:
            block = os.read(descriptor, min(65536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        named = LAUNCHER.lstat()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    if (
        signature(before) != signature(opened)
        or signature(opened) != signature(after)
        or signature(after) != signature(named)
        or not stat.S_ISREG(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o500
        or opened.st_uid != OWNER_UID
        or opened.st_nlink != 1
        or hashlib.sha256(raw).hexdigest() != LAUNCHER_SHA256
    ):
        raise RuntimeError("launcher_identity")
    module = types.ModuleType("vmvm_owner_lifecycle_authorization_launcher_v4_candidate")
    module.__file__ = str(LAUNCHER)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(LAUNCHER), "exec"), module.__dict__)
    return module


def validate_environment(launcher: types.ModuleType) -> None:
    allowed = {
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
        *launcher.TLS_NAMES,
        *launcher.X2P_NAMES,
    }
    if set(os.environ) != allowed:
        raise RuntimeError("environment_names")
    expected = {
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMUX_PANE": "%0",
        "TZ": "UTC",
        "USER": "tianhaowu",
    }
    if any(os.environ.get(name) != value for name, value in expected.items()):
        raise RuntimeError("environment_values")
    if not os.environ.get("TMUX"):
        raise RuntimeError("environment_values")
    launcher._validate_tmux_ancestry()


def directory_record(launcher: types.ModuleType, path: Path) -> tuple[dict[str, int], dict[str, int]]:
    descriptor = launcher.open_bound_directory(path)
    try:
        identity = launcher.directory_identity(descriptor)
    finally:
        os.close(descriptor)
    return identity, launcher.portable_directory_identity(identity)


def file_record(launcher: types.ModuleType, root_fd: int, root: Path, name: str, mode: int) -> dict[str, str]:
    raw = launcher.stable_file_at(root_fd, name, mode=mode)
    return {
        "path": str((root / name).resolve(strict=True)),
        "sha256": launcher.sha256_bytes(raw),
    }


def authorization_body(launcher: types.ModuleType) -> dict[str, object]:
    bundle_root = LAUNCHER.parent
    bundle_fd = launcher.open_bound_directory(bundle_root)
    try:
        bundle_identity = launcher.directory_identity(bundle_fd)
        bundle: dict[str, object] = {
            label: file_record(launcher, bundle_fd, bundle_root, name, mode)
            for label, (name, mode) in FILE_MODES.items()
        }
        if any(bundle[label]["sha256"] != expected for label, expected in BUNDLE_SHA256.items()):
            raise RuntimeError("bundle_hash")
        if {entry.name for entry in os.scandir(bundle_fd)} != {name for name, _mode in FILE_MODES.values()}:
            raise RuntimeError("bundle_inventory")
    finally:
        os.close(bundle_fd)
    bundle["root_identity"] = bundle_identity
    bundle["portable_root_identity"] = launcher.portable_directory_identity(bundle_identity)

    source_identity, source_portable = directory_record(launcher, launcher.SOURCE_ROOT)
    source = {
        "path": str(launcher.SOURCE_ROOT),
        "revision": launcher.SOURCE_REVISION,
        "tree": launcher.SOURCE_TREE,
        "verifiers_revision": launcher.VERIFIERS_REVISION,
        "renderers_revision": launcher.RENDERERS_REVISION,
        "pydantic_config_revision": launcher.PYDANTIC_CONFIG_REVISION,
        "backend_path": launcher.BACKEND_RELATIVE_PATH,
        "backend_sha256": launcher.BACKEND_SHA256,
        "root_identity": source_identity,
        "portable_root_identity": source_portable,
    }

    site_fd = launcher.open_bound_directory(launcher.X86_SITE)
    try:
        site_identity = launcher.directory_identity(site_fd)
        site_inventory = launcher.directory_manifest(site_fd, expected_owner_uid=OWNER_UID)
    finally:
        os.close(site_fd)
    runtime = {
        "image": "python:3.12-slim",
        "python_name": "python3",
        "site": {
            "path": str(launcher.X86_SITE),
            "root_identity": site_identity,
            "portable_root_identity": launcher.portable_directory_identity(site_identity),
            "inventory": site_inventory,
        },
        "uv": {"path": str(launcher.X86_UV), "sha256": launcher.X86_UV_SHA256},
        "vacli": {
            "path": str(launcher.VACLI),
            "resolved_path": str(launcher.VACLI_RESOLVED),
            "sha256": launcher.VACLI_SHA256,
        },
    }

    tls: dict[str, object] = {}
    canonical_tls: dict[str, str] = {}
    for name in launcher.TLS_NAMES:
        raw_path = os.environ.get(name, "")
        if not raw_path or not Path(raw_path).is_absolute():
            raise RuntimeError("tls_path")
        try:
            path = Path(os.path.realpath(raw_path))
            if path.resolve(strict=True) != path:
                raise RuntimeError("tls_path")
            raw = launcher.stable_file(path, mode=0o500, maximum=launcher.TLS_EXPECTED_SIZE)
        except OSError as error:
            raise RuntimeError("tls_path") from error
        if len(raw) != launcher.TLS_EXPECTED_SIZE:
            raise RuntimeError("tls_size")
        canonical_tls[name] = str(path)
        tls[name] = {"path": str(path), "sha256": launcher.sha256_bytes(raw)}
    x2p: dict[str, object] = {}
    for name in launcher.X2P_NAMES:
        value = os.environ.get(name, "")
        if not value or "\0" in value or "\n" in value or len(value.encode()) > 4096:
            raise RuntimeError("x2p_value")
        x2p[name] = {"sha256": launcher.sha256_bytes(value.encode())}

    output_parent_identity, output_parent_portable = directory_record(launcher, launcher.OUTPUT_ROOT.parent)
    launch = {
        "account": "ram",
        "cluster": launcher.CLUSTER,
        "completion_receipt": str(launcher.COMPLETION_RECEIPT),
        "comment": f"vmvm-owner-v4:{JOB_TOKEN}",
        "cpus": 2,
        "environment_export": launcher.ENVIRONMENT_EXPORT_POLICY,
        "job_name": JOB_NAME,
        "log_root": str(launcher.LOG_ROOT),
        "memory": "8G",
        "nodes": 1,
        "output_parent_identity": output_parent_identity,
        "output_parent_portable_identity": output_parent_portable,
        "output_root": str(launcher.OUTPUT_ROOT),
        "partition": "cpu_x86",
        "probe_failure_receipt": str(launcher.PROBE_FAILURE_RECEIPT),
        "qos": "cpu_x86_lowest",
        "reservation": str(launcher.RESERVATION),
        "scratch_root": str(launcher.SCRATCH_ROOT),
        "signal_seconds_before_end": launcher.SIGNAL_LEAD_SECONDS,
        "time_limit": launcher.JOB_TIME_LIMIT,
        "timeout_budget_seconds": {
            "admission": launcher.ADMISSION_TIMEOUT_SECONDS,
            "finalization": launcher.FINALIZATION_BUDGET_SECONDS,
            "job": launcher.JOB_SECONDS,
            "stage": launcher.STAGE_TIMEOUT_SECONDS,
            "supervisor": launcher.SUPERVISOR_TIMEOUT_SECONDS,
            "timeout_kill_grace": launcher.TIMEOUT_KILL_GRACE_SECONDS,
            "timeout_kill_grace_count": launcher.TIMEOUT_KILL_GRACE_COUNT,
            "wrapper_gate": launcher.WRAPPER_GATE_TIMEOUT_SECONDS,
        },
    }
    for name, path_value in canonical_tls.items():
        os.environ[name] = path_value
    return {
        "artifact_type": "vmvm_owner_lifecycle_diagnostic_authorization_v4",
        "bundle": bundle,
        "credentials": {"tls": tls, "x2p": x2p},
        "launch": launch,
        "protocol": launcher.DIAGNOSTIC_PROTOCOL,
        "runtime": runtime,
        "schema_version": 1,
        "source": source,
        "state": "approved",
    }


def publish_exclusive(path: Path, raw: bytes) -> tuple[int, int]:
    parent_fd = -1
    descriptor = -1
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        if INTERRUPTED:
            raise RuntimeError("interrupted")
        parent_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        descriptor = os.open(
            path.name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o400,
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        inode = (before.st_dev, before.st_ino)
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise RuntimeError("authorization_write")
            view = view[count:]
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        captured = bytearray()
        while len(captured) <= len(raw):
            block = os.read(descriptor, min(65536, len(raw) + 1 - len(captured)))
            if not block:
                break
            captured.extend(block)
        after = os.fstat(descriptor)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
            )
            or not stat.S_ISREG(after.st_mode)
            or stat.S_IMODE(after.st_mode) != 0o400
            or after.st_uid != OWNER_UID
            or after.st_nlink != 1
            or after.st_size != len(raw)
            or bytes(captured) != raw
        ):
            raise RuntimeError("authorization_identity")
        target = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            (target.st_dev, target.st_ino) != inode
            or target.st_nlink != 1
            or stat.S_IMODE(target.st_mode) != 0o400
            or target.st_uid != OWNER_UID
            or target.st_size != len(raw)
        ):
            raise RuntimeError("authorization_identity")
        os.fsync(parent_fd)
        return inode
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def create_authorization() -> None:
    launcher = load_launcher()
    validate_environment(launcher)
    if AUTHORIZATION.exists() or AUTHORIZATION.is_symlink():
        raise RuntimeError("authorization_exists")
    launcher.validate_source()
    launcher._ensure_absent()
    if not launcher._name_absent(JOB_NAME, datetime.now(UTC).date().isoformat()):
        raise RuntimeError("job_name_exists")
    body = authorization_body(launcher)
    authorization_sha = launcher.sha256_bytes(launcher.canonical_json(body))
    authorization = {**body, "authorization_sha256": authorization_sha}
    raw = launcher.canonical_json(authorization)
    paths = {label: LAUNCHER.parent / name for label, (name, _mode) in FILE_MODES.items()}
    launcher.validate_authorization(
        authorization,
        launcher=paths["launcher"],
        wrapper=paths["wrapper"],
        probe=paths["probe"],
        finalizer=paths["finalizer"],
    )
    launcher.validate_source()
    launcher._ensure_absent()
    if not launcher._name_absent(JOB_NAME, datetime.now(UTC).date().isoformat()):
        raise RuntimeError("job_name_exists")
    if INTERRUPTED:
        raise RuntimeError("interrupted")
    publish_exclusive(AUTHORIZATION, raw)


def terminalize(descriptor: int, payload: bytes, returncode: int) -> int:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        for signum in HANDLED_SIGNALS:
            signal.signal(signum, signal.SIG_IGN)
        try:
            emit_bounded(descriptor, payload)
        except BaseException:
            return 2
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    return returncode


def main() -> int:
    terminal = (2, FAILURE_OUTPUT, 2)
    try:
        if len(sys.argv) != 1:
            raise RuntimeError("arguments")
        install_signal_handlers()
        create_authorization()
        terminal = (1, SUCCESS_OUTPUT, 0)
    except BaseException:
        terminal = (2, FAILURE_OUTPUT, 2)
    finally:
        return terminalize(*terminal)


if __name__ == "__main__":
    raise SystemExit(main())
