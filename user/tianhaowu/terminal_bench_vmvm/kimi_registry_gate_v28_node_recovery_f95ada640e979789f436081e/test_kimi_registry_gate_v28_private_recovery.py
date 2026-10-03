from __future__ import annotations

import errno
import hashlib
import importlib.util
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
HELPER = HERE / "recover_kimi_registry_gate_v28_private.py"


def load_helper() -> Any:
    specification = importlib.util.spec_from_file_location("k3_v28_private_recovery", HELPER)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def helper() -> Any:
    return load_helper()


@pytest.fixture
def short_tmp_path() -> Any:
    with tempfile.TemporaryDirectory(prefix="k3r-", dir="/tmp") as value:
        yield Path(value)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(*arguments: str) -> bytes:
    return subprocess.run(
        ["/usr/bin/git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def accounting_record(helper: Any) -> dict[str, str]:
    tres = "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1"
    return {
        "Account": helper.FAILED_ACCOUNT,
        "AllocTRES": tres,
        "Comment": "k3-reg-pull-v28:0123456789abcdef01234567",
        "Elapsed": helper.FAILED_ELAPSED,
        "ExitCode": helper.FAILED_EXIT_CODE,
        "JobIDRaw": helper.FAILED_JOB_ID,
        "JobName": helper.FAILED_JOB_NAME,
        "NNodes": "1",
        "NodeList": helper.TARGET_NODE,
        "Partition": helper.FAILED_PARTITION,
        "QOS": helper.FAILED_QOS,
        "ReqCPUS": "4",
        "ReqTRES": tres,
        "State": helper.FAILED_STATE,
        "TimeLimit": helper.FAILED_TIME_LIMIT,
        "User": "tianhaowu",
    }


def authorization(helper: Any, binding: object = None, mode: str = "audit") -> dict[str, object]:
    record = accounting_record(helper)
    return {
        "artifact_type": "k3_registry_pull_gate_v28_private_recovery_authorization_v1",
        "authorized_mode": mode,
        "candidate_token": helper.TOKEN,
        "lineage": helper.EXPECTED_LINEAGE,
        "schema_version": 1,
        "scratch_binding": binding,
        "scratch_pattern": str(helper.TARGET_PARENT / helper.TARGET_NAME_PATTERN),
        "target_node": helper.TARGET_NODE,
        "terminal_evidence": {
            "squeue_absent": True,
            "stable_accounting_reads": [record, dict(record)],
        },
    }


def test_exact_v28_source_and_launch_lineage(helper: Any) -> None:
    assert git("rev-parse", f"{helper.V28_SOURCE_COMMIT}^{{tree}}").decode().strip() == helper.V28_SOURCE_TREE
    assert (
        git(
            "rev-parse",
            f"{helper.V28_SOURCE_COMMIT}:user/tianhaowu/terminal_bench_vmvm/kimi_registry_gate_v28_candidate",
        )
        .decode()
        .strip()
        == helper.V28_SOURCE_SUBTREE
    )
    observed = {
        name: digest(
            git(
                "show",
                f"{helper.V28_SOURCE_COMMIT}:user/tianhaowu/terminal_bench_vmvm/"
                f"kimi_registry_gate_v28_candidate/{name}",
            )
        )
        for name in helper.V28_BUNDLE_HASHES
    }
    assert observed == helper.V28_BUNDLE_HASHES
    assert git("rev-parse", f"{helper.V28_CONTROL_COMMIT}^{{tree}}").decode().strip() == helper.V28_CONTROL_TREE
    assert (
        git(
            "rev-parse",
            f"{helper.V28_CONTROL_COMMIT}:user/tianhaowu/terminal_bench_vmvm/kimi_registry_gate_v28_controls_candidate",
        )
        .decode()
        .strip()
        == helper.V28_CONTROL_SUBTREE
    )
    controls = {
        name: digest(
            git(
                "show",
                f"{helper.V28_CONTROL_COMMIT}:user/tianhaowu/terminal_bench_vmvm/"
                f"kimi_registry_gate_v28_controls_candidate/{name}",
            )
        )
        for name in helper.V28_CONTROL_HASHES
    }
    assert controls == helper.V28_CONTROL_HASHES


def test_public_log_and_lock_hashes_are_exact_fixed_records(helper: Any) -> None:
    public = {
        "category": "podman_info_runroot",
        "image_digest": helper.IMAGE_DIGEST,
        "kind": "k3-registry-pull-gate-v28",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    terminal_lock = {
        "category": "file_identity",
        "kind": "k3-registry-pull-gate-v28-lock",
        "state": "terminal",
    }
    submission = {
        "job_id": helper.FAILED_JOB_ID,
        "kind": "k3-registry-pull-gate-v28-submission",
        "state": "held_identity_proven",
    }
    assert digest(helper.canonical_json(public) + b"\n") == helper.PUBLIC_LOG_SHA256
    assert digest(helper.canonical_json(terminal_lock) + b"\n") == helper.TERMINAL_LOCK_SHA256
    expected_submission = helper.EXPECTED_LINEAGE["run_namespace"]["submission"]
    assert digest(helper.canonical_json(submission) + b"\n") == expected_submission["sha256"]
    assert len(helper.canonical_json(submission) + b"\n") == expected_submission["size"]


def test_authorization_requires_two_identical_terminal_reads_and_queue_absence(helper: Any) -> None:
    value = authorization(helper)
    assert helper._validate_authorization_value(value, "audit") == value

    changed = authorization(helper)
    changed["terminal_evidence"]["stable_accounting_reads"][1]["Elapsed"] = "00:00:29"  # type: ignore[index]
    with pytest.raises(helper.RecoveryError, match="retained_authorization_invalid"):
        helper._validate_authorization_value(changed, "audit")

    queued = authorization(helper)
    queued["terminal_evidence"]["squeue_absent"] = False  # type: ignore[index]
    with pytest.raises(helper.RecoveryError, match="retained_authorization_invalid"):
        helper._validate_authorization_value(queued, "audit")


def test_authorization_rejects_lineage_or_root_drift(helper: Any) -> None:
    changed = authorization(helper)
    changed["lineage"] = {**helper.EXPECTED_LINEAGE, "image_digest": "sha256:" + "0" * 64}
    with pytest.raises(helper.RecoveryError, match="retained_authorization_invalid"):
        helper._validate_authorization_value(changed, "audit")

    bad_binding = {
        "identity": {
            "device": 1,
            "inode": 2,
            "mode": 0o755,
            "mount_id": 3,
            "nlink": 2,
            "owner_uid": helper.EXPECTED_UID,
        },
        "name": "k3-registry-pull-v28.1760071.0.Abc123",
        "path": "/tmp/k3-registry-pull-v28.1760071.0.Abc123",
    }
    with pytest.raises(helper.RecoveryError, match="retained_authorization_invalid"):
        helper._validate_authorization_value(authorization(helper, bad_binding), "audit")


def test_retained_authorization_descriptor_contract(helper: Any, tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    path.write_bytes(b"{}\n")
    path.chmod(0o400)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        duplicate = helper._inherited_fd(str(descriptor), mode=0o400, nlink=1)
        assert os.fstat(duplicate).st_ino == os.fstat(descriptor).st_ino
        os.close(duplicate)
    finally:
        os.close(descriptor)


def test_canonical_authorization_is_read_from_retained_fd(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    value = authorization(helper)
    raw = helper.canonical_json(value) + b"\n"
    path = tmp_path / "authorization.json"
    path.write_bytes(raw)
    path.chmod(0o400)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    monkeypatch.setenv(helper.AUTH_FD_ENV, str(descriptor))
    monkeypatch.setenv(helper.AUTH_SHA_ENV, digest(raw))
    try:
        retained, observed = helper._read_authorization("audit")
        assert observed == value
        assert os.fstat(retained).st_ino == os.fstat(descriptor).st_ino
        os.close(retained)
    finally:
        os.close(descriptor)


def test_zero_one_and_ambiguous_root_enumeration(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "ROOT_STABILITY_SECONDS", 0)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        assert helper._stable_matching_names(parent_fd) == ()
        first = tmp_path / "k3-registry-pull-v28.1760071.0.Abc123"
        first.mkdir(mode=0o700)
        assert helper._stable_matching_names(parent_fd) == (first.name,)
        second = tmp_path / "k3-registry-pull-v28.1760071.0.Zyx987"
        second.mkdir(mode=0o700)
        assert helper._stable_matching_names(parent_fd) == (first.name, second.name)
    finally:
        os.close(parent_fd)


def test_absent_root_is_already_verified_without_mutation(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "TARGET_PARENT", tmp_path)
    monkeypatch.setattr(helper, "ROOT_STABILITY_SECONDS", 0)
    before = tuple(tmp_path.iterdir())
    parent_fd, root_fd, root_path, root_identity = helper._open_bound_root(None)
    try:
        assert root_fd == -1
        assert root_path is None
        assert root_identity is None
        assert tuple(tmp_path.iterdir()) == before
    finally:
        os.close(parent_fd)


def test_absent_root_rejects_a_stale_nonnull_binding(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "TARGET_PARENT", tmp_path)
    monkeypatch.setattr(helper, "ROOT_STABILITY_SECONDS", 0)
    stale = {
        "identity": {
            "device": 1,
            "inode": 2,
            "mode": 0o700,
            "mount_id": 3,
            "nlink": 2,
            "owner_uid": helper.EXPECTED_UID,
        },
        "name": "k3-registry-pull-v28.1760071.0.Abc123",
        "path": str(tmp_path / "k3-registry-pull-v28.1760071.0.Abc123"),
    }
    with pytest.raises(helper.RecoveryError, match="retained_root_binding_invalid"):
        helper._open_bound_root(stale)
    assert tuple(tmp_path.iterdir()) == ()


def make_tree(helper: Any, tmp_path: Path) -> tuple[Path, Path, socket.socket]:
    root = tmp_path / "k3-registry-pull-v28.1760071.0.Abc123"
    nested = root / "nested"
    nested.mkdir(parents=True, mode=0o755)
    nested.chmod(0o755)
    root.chmod(0o700)
    (nested / "private").write_bytes(b"private-fixture")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(root / "control.sock"))
    return root, nested, server


def test_inventory_collects_root_directories_leaves_and_socket(
    helper: Any,
    monkeypatch: Any,
    short_tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root, nested, server = make_tree(helper, short_tmp_path)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_identity = helper._identity(root_fd)
        inventory = helper._inventory(root_fd, root_identity)
        assert inventory.classification == "mixed_supported"
        assert {name for name, _identity in inventory.manifest} == {
            "",
            "control.sock",
            "nested",
            "nested/private",
        }
        assert len(inventory.identities()) == 4
        assert inventory.socket_names == ("control.sock",)
        assert dict(inventory.manifest)["nested"].mode == 0o755
        assert nested.exists()
    finally:
        os.close(root_fd)
        server.close()


@pytest.mark.parametrize("kind", ("symlink", "fifo"))
def test_inventory_rejects_unsupported_type_before_mutation(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
    kind: str,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    entry = root / "entry"
    if kind == "symlink":
        entry.symlink_to("missing")
    else:
        os.mkfifo(entry)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_identity = helper._identity(root_fd)
        with pytest.raises(helper.RecoveryError, match="retained_inventory_unsupported"):
            helper._inventory(root_fd, root_identity)
        assert stat.S_IFMT(entry.lstat().st_mode) in {stat.S_IFLNK, stat.S_IFIFO}
    finally:
        os.close(root_fd)


def test_inventory_rejects_control_character_name_before_mutation(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    entry = root / "socket\nrecord"
    entry.write_bytes(b"private-fixture")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_identity = helper._identity(root_fd)
        with pytest.raises(helper.RecoveryError, match="retained_inventory_unsupported"):
            helper._inventory(root_fd, root_identity)
        assert entry.read_bytes() == b"private-fixture"
    finally:
        os.close(root_fd)


def test_mountinfo_rejects_cross_device_and_same_device_bind_mounts(helper: Any, monkeypatch: Any) -> None:
    root = Path("/tmp/k3-registry-pull-v28.1760071.0.Abc123")
    monkeypatch.setattr(helper, "_mount_records", lambda: (helper.MountRecord(7, "/"),))
    assert helper._validate_mount_boundary(root, 7, 7) == (helper.MountRecord(7, "/"),)
    with pytest.raises(helper.RecoveryError, match="retained_mount_boundary"):
        helper._validate_mount_boundary(root, 7, 8)

    monkeypatch.setattr(
        helper,
        "_mount_records",
        lambda: (
            helper.MountRecord(7, "/"),
            helper.MountRecord(8, str(root / "nested")),
        ),
    )
    with pytest.raises(helper.RecoveryError, match="retained_mount_boundary"):
        helper._validate_mount_boundary(root, 7, 7)


def test_inventory_rejects_mount_id_change_before_mutation(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_identity = helper._identity(root_fd)
    nested_inode = nested.stat().st_ino
    real_mount_id = helper._mount_id

    def changed_mount_id(descriptor: int) -> int:
        if os.fstat(descriptor).st_ino == nested_inode:
            return root_identity.mount_id + 1
        return real_mount_id(descriptor)

    monkeypatch.setattr(helper, "_mount_id", changed_mount_id)
    try:
        with pytest.raises(helper.RecoveryError, match="retained_mount_boundary"):
            helper._inventory(root_fd, root_identity)
        assert nested.exists()
        assert stat.S_IMODE(nested.stat().st_mode) == 0o700
    finally:
        os.close(root_fd)


def fork_holder(action: Any) -> tuple[int, int]:
    ready_read, ready_write = os.pipe()
    child = os.fork()
    if child == 0:
        try:
            os.close(ready_read)
            held = action()
            os.write(ready_write, b"1")
            os.close(ready_write)
            signal.pause()
            if hasattr(held, "close"):
                held.close()
            elif isinstance(held, int):
                os.close(held)
        finally:
            os._exit(0)
    os.close(ready_write)
    assert os.read(ready_read, 1) == b"1"
    os.close(ready_read)
    return child, child


def reap(child: int) -> None:
    os.kill(child, signal.SIGTERM)
    os.waitpid(child, 0)


def test_same_uid_directory_fd_owner_is_detected(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    child, _ = fork_holder(lambda: os.open(nested, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        inventory = helper._inventory(root_fd, helper._identity(root_fd))
        monkeypatch.setattr(helper, "_process_ids", lambda: (str(child),))
        assert helper._same_uid_process_references(root, inventory.identities(), ())
    finally:
        os.close(root_fd)
        reap(child)


def test_same_uid_cwd_owner_is_detected(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)

    def enter_directory() -> None:
        os.chdir(nested)
        return None

    child, _ = fork_holder(enter_directory)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        inventory = helper._inventory(root_fd, helper._identity(root_fd))
        monkeypatch.setattr(helper, "_process_ids", lambda: (str(child),))
        assert helper._same_uid_process_references(root, inventory.identities(), ())
    finally:
        os.close(root_fd)
        reap(child)


def test_same_uid_unix_socket_owner_is_detected(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    socket_path = root / "control.sock"

    def bind_socket() -> socket.socket:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        return server

    child, _ = fork_holder(bind_socket)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        inventory = helper._inventory(root_fd, helper._identity(root_fd))
        monkeypatch.setattr(helper, "_process_ids", lambda: (str(child),))
        assert helper._same_uid_process_references(root, inventory.identities(), inventory.socket_names)
    finally:
        os.close(root_fd)
        reap(child)


def test_inaccessible_same_uid_proc_is_fail_closed(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "_process_ids", lambda: ("123456",))
    monkeypatch.setattr(helper, "_process_owner", lambda _process_id: helper.EXPECTED_UID)

    def inaccessible(_process_id: str) -> int:
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(helper, "_open_process", inaccessible)
    with pytest.raises(helper.RecoveryError, match="retained_quiescence_unverified"):
        helper._same_uid_process_references(tmp_path, set(), ())


def test_inaccessible_other_uid_proc_is_outside_scan(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "_process_ids", lambda: ("123456",))
    monkeypatch.setattr(helper, "_process_owner", lambda _process_id: helper.EXPECTED_UID + 1)
    monkeypatch.setattr(helper, "_open_process", lambda _process_id: pytest.fail("foreign process opened"))
    assert not helper._same_uid_process_references(tmp_path, set(), ())


def test_scrub_handles_noncanonical_directory_mode_and_retains_empty_root(
    helper: Any,
    monkeypatch: Any,
    short_tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root, nested, server = make_tree(helper, short_tmp_path)
    parent_fd = os.open(short_tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_identity = helper._identity(root_fd)
        inventory = helper._inventory(root_fd, root_identity)
        helper._scrub(root_fd, parent_fd, root, root_identity, inventory)
        final = helper._identity(root_fd)
        assert final.object_key() == root_identity.object_key()
        assert final.mount_id == root_identity.mount_id
        assert final.mode == 0o700
        assert final.nlink == 2
        assert os.listdir(root_fd) == []
        assert not nested.exists()
    finally:
        os.close(root_fd)
        os.close(parent_fd)
        server.close()


def test_replacement_is_never_deleted(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    original = root / "entry"
    moved = root / "moved"
    original.write_bytes(b"original")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_identity = helper._identity(root_fd)
    descriptor, identity = helper._open_entry(root_fd, original.name, root_identity)
    real_rename = helper._rename_noreplace
    injected = False

    def replace(parent_fd: int, source: str, target: str) -> None:
        nonlocal injected
        if injected:
            real_rename(parent_fd, source, target)
            return
        injected = True
        os.rename(source, moved.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        replacement = os.open(
            source,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        os.write(replacement, b"replacement")
        os.close(replacement)
        real_rename(parent_fd, source, target)

    monkeypatch.setattr(helper, "_rename_noreplace", replace)
    try:
        with pytest.raises(helper.RecoveryError, match="retained_cleanup_unverified"):
            helper._detach_delete(root_fd, original.name, descriptor, identity, directory=False)
        assert moved.read_bytes() == b"original"
        retained = [path for path in root.iterdir() if path != moved]
        assert len(retained) == 1
        assert retained[0].read_bytes() == b"replacement"
    finally:
        os.close(descriptor)
        os.close(root_fd)


def test_bounded_write_handles_partial_and_rejects_zero(helper: Any, monkeypatch: Any) -> None:
    captured = bytearray()

    def partial(_descriptor: int, payload: bytes) -> int:
        count = min(2, len(payload))
        captured.extend(payload[:count])
        return count

    monkeypatch.setattr(helper.os, "write", partial)
    helper._write_all(99, b"abcdef")
    assert captured == b"abcdef"

    monkeypatch.setattr(helper.os, "write", lambda _descriptor, _payload: 0)
    with pytest.raises(helper.RecoveryError, match="retained_unclassified"):
        helper._write_all(99, b"x")


def test_signal_mask_remains_blocked_through_terminal_write(helper: Any, monkeypatch: Any) -> None:
    calls: list[tuple[str, object]] = []
    result = helper._result(
        state="audited",
        match_state="single",
        inventory_class="empty",
        owner_state="not_checked",
        cleanup_status="not_requested",
    )
    monkeypatch.setattr(helper.sys, "argv", [str(HELPER), "audit"])
    monkeypatch.setattr(helper, "execute", lambda _mode: result)
    monkeypatch.setattr(
        helper.signal,
        "pthread_sigmask",
        lambda operation, signals: calls.append(("mask", (operation, frozenset(signals)))),
    )
    monkeypatch.setattr(
        helper.signal,
        "signal",
        lambda handled_signal, action: calls.append(("handler", (handled_signal, action))),
    )

    def terminal(observed: object) -> None:
        assert observed == result
        calls.append(("terminal", observed))
        raise SystemExit(0)

    monkeypatch.setattr(helper, "_terminal_record", terminal)
    with pytest.raises(SystemExit) as exited:
        helper.main()
    assert exited.value.code == 0
    masks = [value for kind, value in calls if kind == "mask"]
    assert masks
    assert all(operation == signal.SIG_BLOCK for operation, _signals in masks)
    assert calls[-1][0] == "terminal"


def test_audit_inventory_is_nonmutating(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True, mode=0o750)
    root.chmod(0o700)
    private = nested / "private"
    private.write_bytes(b"fixed")
    private.chmod(0o400)
    before = {
        path.relative_to(root).as_posix(): (
            stat.S_IMODE(path.lstat().st_mode),
            path.lstat().st_size,
            digest(path.read_bytes()) if path.is_file() else None,
        )
        for path in (root, nested, private)
    }
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        identity = helper._identity(root_fd)
        first = helper._inventory(root_fd, identity)
        second = helper._inventory(root_fd, identity)
        assert first == second
    finally:
        os.close(root_fd)
    after = {
        path.relative_to(root).as_posix(): (
            stat.S_IMODE(path.lstat().st_mode),
            path.lstat().st_size,
            digest(path.read_bytes()) if path.is_file() else None,
        )
        for path in (root, nested, private)
    }
    assert after == before


def test_full_audit_path_is_nonmutating(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    monkeypatch.setattr(helper, "TARGET_PARENT", tmp_path)
    monkeypatch.setattr(helper, "ROOT_STABILITY_SECONDS", 0)
    root = tmp_path / "k3-registry-pull-v28.1760071.0.Abc123"
    nested = root / "nested"
    nested.mkdir(parents=True, mode=0o750)
    root.chmod(0o700)
    private = nested / "private"
    private.write_bytes(b"fixed")
    private.chmod(0o400)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    binding = {
        "identity": helper._identity(root_fd).root_binding(),
        "name": root.name,
        "path": str(root),
    }
    os.close(root_fd)
    before = {
        path.relative_to(root).as_posix(): (
            stat.S_IMODE(path.lstat().st_mode),
            path.lstat().st_size,
            digest(path.read_bytes()) if path.is_file() else None,
        )
        for path in (root, nested, private)
    }
    monkeypatch.setattr(helper, "_validate_host", lambda: None)
    monkeypatch.setattr(helper, "_validate_self", lambda: os.open(HELPER, os.O_RDONLY | os.O_NOFOLLOW))
    monkeypatch.setattr(
        helper,
        "_read_authorization",
        lambda _mode: (os.open(HELPER, os.O_RDONLY | os.O_NOFOLLOW), authorization(helper, binding)),
    )
    result = helper.execute("audit")
    assert result == helper._result(
        state="audited",
        match_state="single",
        inventory_class="mixed_supported",
        owner_state="not_checked",
        cleanup_status="not_requested",
    )
    after = {
        path.relative_to(root).as_posix(): (
            stat.S_IMODE(path.lstat().st_mode),
            path.lstat().st_size,
            digest(path.read_bytes()) if path.is_file() else None,
        )
        for path in (root, nested, private)
    }
    assert after == before


def test_pending_signal_prevents_first_mutation(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    monkeypatch.setattr(helper, "TARGET_PARENT", tmp_path)
    monkeypatch.setattr(helper, "ROOT_STABILITY_SECONDS", 0)
    root = tmp_path / "k3-registry-pull-v28.1760071.0.Abc123"
    root.mkdir(mode=0o700)
    private = root / "private"
    private.write_bytes(b"fixed")
    private.chmod(0o400)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    binding = {
        "identity": helper._identity(root_fd).root_binding(),
        "name": root.name,
        "path": str(root),
    }
    os.close(root_fd)
    monkeypatch.setattr(helper, "_validate_host", lambda: None)
    monkeypatch.setattr(helper, "_validate_self", lambda: os.open(HELPER, os.O_RDONLY | os.O_NOFOLLOW))
    monkeypatch.setattr(
        helper,
        "_read_authorization",
        lambda _mode: (os.open(HELPER, os.O_RDONLY | os.O_NOFOLLOW), authorization(helper, binding, "recover")),
    )
    monkeypatch.setattr(helper, "_quiesce", lambda *_arguments: True)
    monkeypatch.setattr(helper, "_signals_pending", lambda: True)
    monkeypatch.setattr(helper, "_scrub", lambda *_arguments: pytest.fail("scrub ran after pending signal"))
    with pytest.raises(helper.RecoveryError, match="retained_signal"):
        helper.execute("recover")
    assert private.read_bytes() == b"fixed"
    assert stat.S_IMODE(private.stat().st_mode) == 0o400


def test_closed_output_and_no_scheduler_or_secret_surface(helper: Any) -> None:
    result = helper._result(
        state="recovered",
        match_state="single",
        inventory_class="mixed_supported",
        owner_state="absent",
        cleanup_status="verified",
    )
    raw = helper.canonical_json(result)
    assert set(result) == helper.RESULT_FIELDS
    for forbidden in (b"/tmp", b"inode", b"path", b"pid", b"error", b"sha256", b"credential"):
        assert forbidden not in raw.lower()
    source = HELPER.read_text()
    for forbidden in (
        "subprocess",
        "/usr/bin/sbatch",
        "/usr/bin/sacct",
        "/usr/bin/squeue",
        "/usr/bin/scancel",
        "THRIFT_TLS",
        "X2P_PROXY",
        "task_id",
        "model_id",
    ):
        assert forbidden not in source


def test_source_bundle_inventory_is_exact() -> None:
    assert {path.name for path in HERE.iterdir()} == {
        "README.md",
        "recover_kimi_registry_gate_v28_private.py",
        "test_kimi_registry_gate_v28_private_recovery.py",
    }
