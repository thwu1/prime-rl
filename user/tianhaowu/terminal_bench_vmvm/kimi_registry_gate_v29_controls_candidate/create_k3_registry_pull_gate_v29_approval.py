#!/usr/bin/python3.12
# ruff: noqa: BLE001, S102
"""Create one exact v29 approval without exposing TLS metadata."""

from __future__ import annotations

import hashlib
import os
import signal
import stat
import sys
import types
from pathlib import Path

GATE_SOURCE_COMMIT = "1aea1e0a4dde7b297f46dd610f79d421d3f23911"
GATE_SOURCE_TREE = "b18cdf375fda206b2c32ce577839b7b69007505a"
GATE_SOURCE_SUBTREE = "bb94c035f0e535f36c17e7e0de8e139e8df24731"
BUNDLE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t170000z_v29")
CONTROLLER = BUNDLE / "controller.py"
CONTROLLER_SHA256 = "4bfc57eae485299a4c93da7b08efe5c5e9037176e9aa5a837f40baab9b70480d"
APPROVAL = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/approvals/k3_registry_pull_gate_20260920t170000z_v29.approval.json"
)
RUN_ROOT = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/k3_registry_pull_gate_20260920t170000z_v29")
LOG_ROOT = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_registry_pull_gate_20260920t170000z_v29")
LOCK = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/locks/k3_registry_pull_gate_20260920t170000z_v29.lock")
JOB_NAME = "k3-reg-pull-170000-v29"
COMMENT_PREFIX = "k3-reg-pull-v29:"
OWNER_UID = 656177
LAUNCH_PYTHON_SHA256 = "1a301bb1763139d48ae638d97b11edf56de6cd185e1b054eae6dc28c271c0c5f"
COMPUTE_PYTHON_SHA256 = "50d2b4d722d4b3b275e16d1d3b23457e5649428af598cc56f83c8544914e4690"
BUNDLE_HASHES = {
    "launcher": "eb1a75c792c6057e0ea3701fa4901d17492f7f785534825f84be46c550e76b17",
    "controller": CONTROLLER_SHA256,
    "batch": "074307fc3d2a92fdb674db281f965ec082ca0112f84e9dd98d436e784fe26925",
    "probe": "558475e3f7aa30e4d61fbf4826549aa675618f66ba68b1b8505045249b64dadf",
    "classifier": "5036ea8df38fac8b5f89d937549e02798e588b2d3cd139265633410feafad948",
    "podman_guard": "9fd712d8b53b69346a7c75e6a1121e03b3f1366b9bf4a89eb5e5e314b636cf31",
    "tools_manifest": "c3bc1ee64a3b17a25b56bd754aa0c4bdc74b1045c2bfaefbe435f8b57044466c",
    "readme": "b5808e39ad1f1de1a2a33410020dd2f9266c3e71b8103935d74a1cc9b7cf452d",
    "tests": "27237a2af952cc9ea402cbb26b400daf4f6958beddf07243d1c5472c6fe8fd5a",
    "pending": "e92fb121a74981943dfb5a55dd70e31137fd49ba18f90b7987833aa65520b6e9",
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
    "vector_sha256": "5e70cb5c938c545de034075ec62876bd976cb1bc042266d7ad3097868bbe48e3",
}
INTERRUPTED = False
HANDLED_SIGNALS = frozenset({signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
SUCCESS_RECORD = b'{"kind":"k3-registry-pull-gate-v29-approval-create","state":"created"}\n'
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
    module = types.ModuleType("k3_registry_pull_gate_v29_approval_controller")
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
        or controller.TOOLS.get(Path("/usr/bin/python3.12")) != LAUNCH_PYTHON_SHA256
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
        or approval.get("kind") != "k3-registry-pull-gate-v29-approval"
    ):
        raise RuntimeError("controller_contract")
    protocol = approval.get("protocol")
    if (
        not isinstance(protocol, dict)
        or protocol.get("compute_tool_manifest_probe") != COMPUTE_TOOL_CONTRACT
        or protocol.get("runtime_allocation_node_bound") is not True
        or protocol.get("cleanup_status_independent") is not True
        or protocol.get("direct_job_result_o_excl") is not True
        or protocol.get("publication_failure_public_only") is not True
        or protocol.get("podman_runroot_cli_bound") is not True
    ):
        raise RuntimeError("controller_contract")
    if COMPUTE_PYTHON_SHA256 == LAUNCH_PYTHON_SHA256:
        raise RuntimeError("controller_contract")
    success = {
        "category": "success",
        "cleanup_status": "verified",
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-pull-gate-v29",
        "platform": "linux/arm64",
        "state": "complete",
    }
    raw = controller.canonical(success)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    if controller.validate_result_payload(captured, True) != (
        controller.digest(raw),
        "success",
        "verified",
    ):
        raise RuntimeError("controller_contract")
    publication_failure = {
        "category": "result_publication",
        "cleanup_status": "unverified",
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-pull-gate-v29",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    raw = controller.canonical(publication_failure)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    if controller.validate_result_payload(captured, False) != (
        controller.digest(raw),
        "result_publication",
        "unverified",
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
            "kind": "k3-registry-pull-gate-v29-audit",
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
