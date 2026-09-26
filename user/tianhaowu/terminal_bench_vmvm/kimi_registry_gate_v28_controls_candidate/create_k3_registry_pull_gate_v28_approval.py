#!/usr/bin/python3.12
# ruff: noqa: BLE001, S102
"""Create one exact v28 approval without exposing TLS metadata."""

from __future__ import annotations

import hashlib
import os
import signal
import stat
import sys
import types
from pathlib import Path

GATE_SOURCE_COMMIT = "4d7b256fdce51a3d2a0dd7f336e18a927dd768ef"
GATE_SOURCE_TREE = "572b4bd1fd2db7deab150374398a9760a7ebf719"
GATE_SOURCE_SUBTREE = "8196764b93e052b4d897eb05cf1e98a123e2003a"
BUNDLE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t153000z_v28")
CONTROLLER = BUNDLE / "controller.py"
CONTROLLER_SHA256 = "71a60e91764b9a1d0d24c9ca0ec87afe3e5719135649fd5ae4b8a029aec171ab"
APPROVAL = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/approvals/k3_registry_pull_gate_20260920t153000z_v28.approval.json"
)
RUN_ROOT = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/k3_registry_pull_gate_20260920t153000z_v28")
LOG_ROOT = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_registry_pull_gate_20260920t153000z_v28")
LOCK = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/locks/k3_registry_pull_gate_20260920t153000z_v28.lock")
JOB_NAME = "k3-reg-pull-153000-v28"
COMMENT_PREFIX = "k3-reg-pull-v28:"
OWNER_UID = 656177
BUNDLE_HASHES = {
    "launcher": "aed35b4e51c4c42c106ff52d7fa372a7d16f6d38ddf7fe1d1f899159b0a7fdcd",
    "controller": CONTROLLER_SHA256,
    "batch": "7bf6df410a16e9d319d8596ce9931d34b110276ef4e1a9fed5fdf8dead7cc170",
    "probe": "8acb57bf1f45112f38cd40eb46e0ba790133506c3799f544aee281ca506b0ca1",
    "classifier": "46086ed6a6bc4eed4555d8bbe5fe4086f32ba601a79db028635f7cae40170d65",
    "podman_guard": "bef59aaf16e7a4950b6426b2c4b1c29c405665b211a6364bd29d22e5af73e200",
    "tools_manifest": "af255efed7ea7eba7ea3214bb24febe480476cb92dffd023021ef5e057e1dfba",
    "readme": "6f46547c9d40dbb9f5c9deacbb78488eddb0214d3c3f94f2f053b97db2dfdea6",
    "tests": "2470aaf4758b5b72f4d861fd30f3dc0dd224d337191f7ce29463ae30c490f23f",
    "pending": "a8d3dc1995cea78555666cc66188e9038a8a3d85a8bd9d41492d02acf70dfa7d",
}
HASH_ENV = {
    "launcher": "EXPECTED_LAUNCHER_SHA256",
    "controller": "EXPECTED_CONTROLLER_SHA256",
    "batch": "EXPECTED_BATCH_SHA256",
    "probe": "EXPECTED_PROBE_SHA256",
    "classifier": "EXPECTED_CLASSIFIER_SHA256",
    "podman_guard": "EXPECTED_PODMAN_GUARD_SHA256",
    "tools_manifest": "EXPECTED_TOOLS_MANIFEST_SHA256",
    "readme": "EXPECTED_README_SHA256",
    "tests": "EXPECTED_TEST_SHA256",
    "pending": "EXPECTED_PENDING_SHA256",
}
SCHEDULER_CONTRACT = {
    "cluster": "fair-cw-use2-3",
    "partition": "g3",
    "account": "ram",
    "qos": "g3_lowest",
    "nodes": 1,
    "tasks": 1,
    "gpus_per_node": 1,
    "cpus_per_task": 4,
    "memory": "16G",
    "time": "00:30:00",
    "no_requeue": True,
    "signal": "TERM@240",
    "exclude": ["g3-136-221", "g3-136-247", "g3-136-251", "g3-136-253"],
    "node_selection": "scheduler",
    "node_name_pattern": "g3-[0-9]{3}-[0-9]{3}",
    "held_submit": True,
    "release_once": True,
    "nested_srun": True,
}
COMPUTE_TOOL_CONTRACT = {
    "node_name_pattern": "g3-[0-9]{3}-[0-9]{3}",
    "records": 32,
    "vector_sha256": "e793125a0c4f8cb41599096f04a9676deaa382d23e620061f756011178a0e16c",
}
INTERRUPTED = False
HANDLED_SIGNALS = frozenset({signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
SUCCESS_RECORD = b'{"kind":"k3-registry-pull-gate-v28-approval-create","state":"created"}\n'
FAILURE_RECORD = b'{"category":"approval_create_failed","state":"blocked"}\n'


class ApprovalInterrupted(BaseException):
    pass


def signal_handler(_signum: int, _frame: object) -> None:
    global INTERRUPTED
    INTERRUPTED = True
    signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    raise ApprovalInterrupted


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


def load_controller() -> types.ModuleType:
    before = CONTROLLER.lstat()
    fd = os.open(CONTROLLER, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        chunks: list[bytes] = []
        remaining = 1 << 20
        while remaining:
            block = os.read(fd, min(65536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    named = CONTROLLER.lstat()
    if (
        signature(before) != signature(opened)
        or signature(opened) != signature(after)
        or signature(after) != signature(named)
        or not stat.S_ISREG(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o500
        or opened.st_uid != OWNER_UID
        or opened.st_nlink != 1
        or hashlib.sha256(raw).hexdigest() != CONTROLLER_SHA256
    ):
        raise RuntimeError("controller_identity")
    module = types.ModuleType("k3_registry_pull_gate_v28_approval_controller")
    module.__file__ = str(CONTROLLER)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(CONTROLLER), "exec"), module.__dict__)
    return module


def install_hash_environment() -> None:
    if "EXPECTED_APPROVAL_SHA256" in os.environ:
        raise RuntimeError("approval_hash_injected")
    for key, name in HASH_ENV.items():
        os.environ[name] = BUNDLE_HASHES[key]


def validate_controller_contract(controller: types.ModuleType, hashes: dict[str, str]) -> None:
    if (
        Path(controller.BUNDLE) != BUNDLE
        or Path(controller.APPROVAL) != APPROVAL
        or Path(controller.RUN_ROOT) != RUN_ROOT
        or Path(controller.LOG_ROOT) != LOG_ROOT
        or Path(controller.LOCK) != LOCK
        or controller.JOB_NAME != JOB_NAME
        or controller.COMMENT_PREFIX != COMMENT_PREFIX
        or hashes != BUNDLE_HASHES
    ):
        raise RuntimeError("controller_contract")
    pending = controller.pending_contract(hashes)
    approval = controller.approval_contract(hashes, None)
    if (
        pending.get("state") != "pending_independent_approval"
        or pending.get("launch_eligible") is not False
        or pending.get("bundle_hashes") != BUNDLE_HASHES
        or pending.get("approval_template") != approval
        or approval.get("scheduler") != SCHEDULER_CONTRACT
        or approval.get("job_name") != JOB_NAME
        or approval.get("kind") != "k3-registry-pull-gate-v28-approval"
    ):
        raise RuntimeError("controller_contract")
    protocol = approval.get("protocol")
    if (
        not isinstance(protocol, dict)
        or protocol.get("compute_tool_manifest_probe") != COMPUTE_TOOL_CONTRACT
        or protocol.get("runtime_allocation_node_bound") is not True
    ):
        raise RuntimeError("controller_contract")


def publish_exclusive(path: Path, raw: bytes) -> tuple[int, int]:
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    descriptor = -1
    previous_mask: set[signal.Signals] | None = None
    try:
        if INTERRUPTED:
            raise RuntimeError("interrupted")
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        if INTERRUPTED:
            raise RuntimeError("interrupted")
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
                raise RuntimeError("approval_write")
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
            raise RuntimeError("approval_identity")
        target = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            (target.st_dev, target.st_ino) != inode
            or target.st_nlink != 1
            or stat.S_IMODE(target.st_mode) != 0o400
            or target.st_uid != OWNER_UID
            or target.st_size != len(raw)
        ):
            raise RuntimeError("approval_identity")
        os.fsync(parent_fd)
        return inode
    finally:
        close_error: OSError | None = None
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError as error:
                close_error = error
        try:
            os.close(parent_fd)
        except OSError as error:
            close_error = error
        if previous_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if close_error is not None:
            raise close_error


def emit_result(success: bool) -> int:
    signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    if INTERRUPTED or signal.sigpending().intersection(HANDLED_SIGNALS):
        success = False
    raw = SUCCESS_RECORD if success else FAILURE_RECORD
    descriptor = 1 if success else 2
    view = memoryview(raw)
    try:
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                return 2
            view = view[count:]
    except OSError:
        return 2
    return 0 if success else 2


def finish_result(success: bool) -> int:
    while True:
        try:
            signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
            return emit_result(success)
        except ApprovalInterrupted:
            success = False


def main() -> int:
    success = False
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        if sys.argv != ["/proc/self/fd/8"]:
            raise RuntimeError("arguments")
        for signum in HANDLED_SIGNALS:
            signal.signal(signum, signal_handler)
        install_hash_environment()
        controller = load_controller()
        controller.validate_tmux()
        hashes = controller.bundle_hashes()
        validate_controller_contract(controller, hashes)
        audited = controller.audit(hashes)
        if audited != {
            "jobs_submitted": 0,
            "kind": "k3-registry-pull-gate-v28-audit",
            "source_revision": "b1f0aa6c1aabcad9182d85a694faaa2eaa3d0f6e",
            "state": "passed",
        }:
            raise RuntimeError("audit")
        if controller.APPROVAL.exists() or controller.APPROVAL.is_symlink():
            raise RuntimeError("approval_exists")
        _paths, private_tls = controller.tls_binding()
        payload = controller.approval_contract(hashes, private_tls)
        expected = controller.canonical(payload)
        approval_sha = hashlib.sha256(expected).hexdigest()
        os.environ["EXPECTED_APPROVAL_SHA256"] = approval_sha
        signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        if INTERRUPTED or signal.sigpending().intersection(HANDLED_SIGNALS):
            raise RuntimeError("interrupted")
        publish_exclusive(controller.APPROVAL, expected)
        captured = controller.stable_file(
            controller.APPROVAL,
            mode=0o400,
            expected=approval_sha,
            maximum=1 << 20,
        )
        if captured.raw != expected:
            raise RuntimeError("approval_bytes")
        validated_sha, validated_payload = controller.validate_approval(hashes, private_tls)
        if validated_sha != approval_sha or validated_payload != payload:
            raise RuntimeError("approval_validation")
        if INTERRUPTED or signal.sigpending().intersection(HANDLED_SIGNALS):
            raise RuntimeError("interrupted")
        success = True
    except BaseException:
        success = False
    return finish_result(success)


if __name__ == "__main__":
    raise SystemExit(main())
