from __future__ import annotations

import hashlib
import importlib.util
import os
import signal
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
HELPER = HERE / "recover_vmvm_owner_lifecycle_v4_scratch.py"


def load_helper() -> Any:
    specification = importlib.util.spec_from_file_location("vmvm_v4_scratch_recovery", HELPER)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def helper() -> Any:
    return load_helper()


def test_exact_fixed_lineage_and_closed_output(helper: Any) -> None:
    assert helper.TARGET_NODE == "cpu-140-255"
    assert helper.TARGET_ROOT == Path("/tmp/tianhaowu-vmvm-owner-lifecycle-9d7841b36-v4-scratch")
    assert helper.FAILED_JOB_ID == "1760059"
    assert helper.FAILED_RECEIPT_SHA256 == ("d99b126b71913a59304e9cc8af400dee09ac84901a0f4dad52eef18111824ae2")
    assert helper.V4_SOURCE_COMMIT == "ea035668d4b43d1bf8fe588ca4469a2b7a46c5a3"
    assert helper.V4_SOURCE_TREE == "9ed4462ca48f288608fccfeb79dadae23b6470c8"
    result = helper._result(
        state="quarantined",
        inventory_class="mixed_supported",
        owner_state="absent",
        cleanup_status="quarantined",
    )
    assert set(result) == helper.RESULT_FIELDS
    payload = helper.canonical_json(result)
    for forbidden in (b"/tmp", b"vacli", b"pid", b"inode", b"error", b"sha256"):
        assert forbidden not in payload.lower()


def test_v4_bundle_hashes_match_tracked_source(helper: Any) -> None:
    v4 = HERE.parent / "vmvm_owner_lifecycle_diagnostic_v4"
    observed = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in v4.iterdir()}
    assert observed == helper.V4_BUNDLE_HASHES


def test_inventory_accepts_only_regular_socket_directory(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    (nested / "log").write_bytes(b"fixed")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(root / "control"))
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        classification, sockets, inventory = helper._inventory(root_fd)
        assert classification == "mixed_supported"
        assert sockets == ("control",)
        assert len(inventory.entries) == 3
    finally:
        if "inventory" in locals():
            inventory.close()
        os.close(root_fd)
        server.close()


def test_descriptor_mount_id_is_attested_and_nested_boundary_is_rejected(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_inode = os.fstat(root_fd).st_ino
    actual_mount = helper._descriptor_mount_id(root_fd, helper._known_mount_ids())
    original = helper._descriptor_mount_id

    def different_nested_mount(descriptor: int, known: set[int] | None = None) -> int:
        value = original(descriptor, known)
        return value if os.fstat(descriptor).st_ino == root_inode else value + 1

    monkeypatch.setattr(helper, "_descriptor_mount_id", different_nested_mount)
    try:
        with pytest.raises(helper.RecoveryError, match="retained_inventory_unsupported"):
            helper._inventory(root_fd)
    finally:
        os.close(root_fd)
    assert actual_mount > 0


def test_real_mount_boundary_is_rejected(helper: Any) -> None:
    parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    mounted_fd = os.open("/proc", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        known = helper._known_mount_ids()
        parent_mount = helper._descriptor_mount_id(parent_fd, known)
        with pytest.raises(helper.RecoveryError, match="retained_inventory_unsupported"):
            helper._require_mount_id(
                mounted_fd,
                parent_mount,
                known,
                "retained_inventory_unsupported",
            )
    finally:
        os.close(mounted_fd)
        os.close(parent_fd)


@pytest.mark.parametrize("kind", ("symlink", "fifo"))
def test_inventory_rejects_unsupported_entries(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
    kind: str,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    target = root / "entry"
    if kind == "symlink":
        target.symlink_to("missing")
    else:
        os.mkfifo(target)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with pytest.raises(helper.RecoveryError, match="retained_inventory_unsupported"):
            helper._inventory(root_fd)
    finally:
        os.close(root_fd)


def test_recovery_quarantines_exact_root_without_deleting_contents(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True, mode=0o700)
    nested.chmod(0o755)
    root.chmod(0o700)
    (nested / "log").write_bytes(b"fixed")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(root / "control"))
    monkeypatch.setattr(helper, "TARGET_ROOT", root)
    quarantine = tmp_path / "quarantine"
    monkeypatch.setattr(helper, "QUARANTINE_ROOT", quarantine)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = helper.descriptor_identity(root_fd)
    try:
        helper._quarantine_root_verified(parent_fd, root_fd, identity)
        assert not root.exists()
        assert quarantine.is_dir()
        assert (quarantine / "nested" / "log").read_bytes() == b"fixed"
        assert (quarantine / "control").exists()
        assert helper.descriptor_identity(root_fd) == identity
    finally:
        os.close(root_fd)
        os.close(parent_fd)
        server.close()


def test_live_socket_owner_is_detected_without_identity_output(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    monkeypatch.setattr(helper, "TARGET_ROOT", tmp_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = tmp_path / "vacli_ctl_123_deadbeef"
    server.bind(str(path))
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.stat(path, follow_symlinks=False)
    _classification, _sockets, inventory = helper._inventory(root_fd)
    try:
        # The current process is intentionally excluded; make the ownership
        # predicate deterministic without exposing an identifier in output.
        monkeypatch.setattr(helper, "_same_uid_process_references", lambda *_args: True)
        assert not helper._quiesce(
            root_fd,
            (path.name,),
            {(info.st_dev, info.st_ino)},
            inventory,
        )
    finally:
        inventory.close()
        os.close(root_fd)
        server.close()


def test_stale_socket_quiescence_never_uses_mutable_control_path(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = root / "vacli_ctl_123_deadbeef"
    server.bind(str(path))
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    before = path.stat()
    _classification, sockets, inventory = helper._inventory(root_fd)
    monkeypatch.setattr(helper, "_same_uid_process_references", lambda *_args: False)
    monkeypatch.setattr(helper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(helper.time, "monotonic", iter((0.0, 3.0)).__next__)
    try:
        assert not hasattr(helper, "_request_control_exit")
        assert helper._quiesce(
            root_fd,
            sockets,
            inventory.identities,
            inventory,
        )
        after = path.stat()
        assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    finally:
        inventory.close()
        os.close(root_fd)
        server.close()


def test_real_same_uid_open_file_owner_is_detected(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    monkeypatch.setattr(helper, "TARGET_ROOT", tmp_path)
    owned = tmp_path / "owned.log"
    owned.write_bytes(b"fixed")
    info = owned.stat()
    ready_read, ready_write = os.pipe()
    child = os.fork()
    if child == 0:
        try:
            os.close(ready_read)
            descriptor = os.open(owned, os.O_RDONLY | os.O_NOFOLLOW)
            os.write(ready_write, b"1")
            signal.pause()
            os.close(descriptor)
        finally:
            os._exit(0)
    os.close(ready_write)
    try:
        assert os.read(ready_read, 1) == b"1"
        assert helper._process_references(
            Path(f"/proc/{child}"),
            socket_names=(),
            socket_object_ids=set(),
            bound_identities={(info.st_dev, info.st_ino)},
        )
    finally:
        os.close(ready_read)
        os.kill(child, signal.SIGTERM)
        os.waitpid(child, 0)


@pytest.mark.parametrize("owner_kind", ("directory_fd", "cwd"))
def test_real_same_uid_directory_owner_is_detected(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
    owner_kind: str,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "owned-directory"
    root.mkdir()
    info = root.stat()
    ready_read, ready_write = os.pipe()
    child = os.fork()
    if child == 0:
        try:
            os.close(ready_read)
            descriptor = -1
            if owner_kind == "directory_fd":
                descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            else:
                os.chdir(root)
            os.write(ready_write, b"1")
            signal.pause()
            if descriptor >= 0:
                os.close(descriptor)
        finally:
            os._exit(0)
    os.close(ready_write)
    try:
        assert os.read(ready_read, 1) == b"1"
        assert helper._process_references(
            Path(f"/proc/{child}"),
            socket_names=(),
            socket_object_ids=set(),
            bound_identities={(info.st_dev, info.st_ino)},
        )
    finally:
        os.close(ready_read)
        os.kill(child, signal.SIGTERM)
        os.waitpid(child, 0)


def test_real_proc_root_owner_is_detected(helper: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(helper, "TARGET_ROOT", Path("/definitely-not-in-command-line"))
    info = Path("/").stat()
    assert helper._process_references(
        Path("/proc/self"),
        socket_names=(),
        socket_object_ids=set(),
        bound_identities={(info.st_dev, info.st_ino)},
    )


def test_inaccessible_same_uid_proc_fails_closed(helper: Any, monkeypatch: Any) -> None:
    real_read_bytes = Path.read_bytes

    def deny_cmdline(path: Path) -> bytes:
        if path.name == "cmdline" and path.parent.parent == Path("/proc"):
            raise PermissionError("hidden")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deny_cmdline)
    with pytest.raises(helper.RecoveryError, match="retained_quiescence_unverified"):
        helper._same_uid_process_references((), {(0, 0)})


def test_real_unix_socket_owner_is_detected(helper: Any, monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    monkeypatch.setattr(helper, "TARGET_ROOT", tmp_path)
    socket_path = tmp_path / "vacli_ctl_123_deadbeef"
    ready_read, ready_write = os.pipe()
    child = os.fork()
    if child == 0:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            os.close(ready_read)
            server.bind(str(socket_path))
            server.listen()
            os.write(ready_write, b"1")
            signal.pause()
        finally:
            server.close()
            os._exit(0)
    os.close(ready_write)
    try:
        assert os.read(ready_read, 1) == b"1"
        info = socket_path.stat()
        object_ids = {
            fields[6]
            for line in Path("/proc/net/unix").read_bytes().splitlines()[1:]
            for fields in (line.split(maxsplit=7),)
            if len(fields) == 8 and fields[7] == os.fsencode(socket_path)
        }
        assert helper._process_references(
            Path(f"/proc/{child}"),
            socket_names=(socket_path.name,),
            socket_object_ids=object_ids,
            bound_identities={(info.st_dev, info.st_ino)},
        )
    finally:
        os.close(ready_read)
        os.kill(child, signal.SIGTERM)
        os.waitpid(child, 0)


def test_quarantine_rejects_prerename_root_replacement_without_deletion(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "evidence").write_bytes(b"original")
    displaced = tmp_path / "displaced"
    quarantine = tmp_path / "quarantine"
    monkeypatch.setattr(helper, "TARGET_ROOT", root)
    monkeypatch.setattr(helper, "QUARANTINE_ROOT", quarantine)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = helper.descriptor_identity(root_fd)
    real_rename = helper._rename_noreplace

    def swap_before_rename(parent_fd: int, source: str, target: str) -> None:
        os.rename(source, displaced.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.mkdir(source, 0o700, dir_fd=parent_fd)
        (tmp_path / source / "replacement").write_bytes(b"replacement")
        real_rename(parent_fd, source, target)

    monkeypatch.setattr(helper, "_rename_noreplace", swap_before_rename)
    try:
        with pytest.raises(helper.RecoveryError, match="retained_cleanup_unverified"):
            helper._quarantine_root_verified(parent_fd, root_fd, identity)
        assert (displaced / "evidence").read_bytes() == b"original"
        assert (quarantine / "replacement").read_bytes() == b"replacement"
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def test_quarantine_postrename_replacement_is_retained(
    helper: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "evidence").write_bytes(b"original")
    displaced = tmp_path / "displaced"
    quarantine = tmp_path / "quarantine"
    monkeypatch.setattr(helper, "TARGET_ROOT", root)
    monkeypatch.setattr(helper, "QUARANTINE_ROOT", quarantine)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = helper.descriptor_identity(root_fd)
    real_events = helper._read_events
    reads = 0

    def swap_after_rename(watch_fd: int):
        nonlocal reads
        reads += 1
        if reads == 2:
            os.rename(quarantine, displaced)
            quarantine.mkdir(mode=0o700)
            (quarantine / "replacement").write_bytes(b"replacement")
        return real_events(watch_fd)

    monkeypatch.setattr(helper, "_read_events", swap_after_rename)
    try:
        with pytest.raises(helper.RecoveryError, match="retained_cleanup_unverified"):
            helper._quarantine_root_verified(parent_fd, root_fd, identity)
        assert (displaced / "evidence").read_bytes() == b"original"
        assert (quarantine / "replacement").read_bytes() == b"replacement"
        assert not root.exists()
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def test_authorization_schema_rejects_wrong_root_identity(helper: Any, tmp_path: Path) -> None:
    value = {
        "artifact_type": "vmvm_v4_scratch_recovery_authorization_v1",
        "authorized_mode": "audit",
        "backend_sha256": helper.BACKEND_SHA256,
        "candidate_token": helper.TOKEN,
        "evaluator_commit": helper.EVALUATOR_COMMIT,
        "evaluator_tree": helper.EVALUATOR_TREE,
        "failed_job": {"exit_code": "2:0", "job_id": helper.FAILED_JOB_ID, "state": "FAILED"},
        "failure_receipt_sha256": helper.FAILED_RECEIPT_SHA256,
        "quarantine_root": str(helper.QUARANTINE_ROOT),
        "schema_version": 1,
        "scratch_identity": {
            "device": 1,
            "inode": 2,
            "mode": 0o755,
            "mount_id": 3,
            "owner_uid": helper.EXPECTED_UID,
        },
        "scratch_root": str(helper.TARGET_ROOT),
        "target_node": helper.TARGET_NODE,
        "v4_bundle_hashes": helper.V4_BUNDLE_HASHES,
        "v4_source_commit": helper.V4_SOURCE_COMMIT,
        "v4_source_tree": helper.V4_SOURCE_TREE,
    }
    payload = helper.canonical_json(value) + b"\n"
    authorization = tmp_path / "authorization.json"
    authorization.write_bytes(payload)
    authorization.chmod(0o400)
    descriptor = os.open(authorization, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.environ["VMVM_V4_RECOVERY_AUTH_FD"] = str(descriptor)
        os.environ["VMVM_V4_RECOVERY_AUTH_SHA256"] = helper.sha256_bytes(payload)
        with pytest.raises(helper.RecoveryError, match="retained_authorization_invalid"):
            helper._read_authorization("audit")
    finally:
        os.environ.pop("VMVM_V4_RECOVERY_AUTH_FD", None)
        os.environ.pop("VMVM_V4_RECOVERY_AUTH_SHA256", None)
        os.close(descriptor)


def test_source_has_no_scheduler_or_sensitive_surface() -> None:
    source = HELPER.read_text()
    for forbidden in (
        'subprocess.run(["sbatch"',
        'subprocess.run(["scontrol"',
        'subprocess.run(["scancel"',
        "OPENAI_API_KEY",
        "X2P_PROXY_URL",
        "datasets/",
        "task_id",
    ):
        assert forbidden not in source
    assert "subprocess" not in source
    assert "_request_control_exit" not in source
    assert "os.O_NOFOLLOW" in source
    assert "os.O_PATH" in source
    assert "os.unlink(" not in source
    assert "os.rmdir(" not in source
    assert "os.rmdir(" not in source
    assert "os.fchmod(" not in source


def test_terminal_write_handles_partial_writes(helper: Any, monkeypatch: Any) -> None:
    emitted = bytearray()

    def partial_write(descriptor: int, payload: bytes) -> int:
        assert descriptor == 1
        amount = min(3, len(payload))
        emitted.extend(payload[:amount])
        return amount

    monkeypatch.setattr(helper.os, "write", partial_write)
    result = helper._result(
        state="quarantined",
        inventory_class="empty",
        owner_state="absent",
        cleanup_status="quarantined",
    )
    with pytest.raises(SystemExit) as exited:
        helper._terminal_record(result)
    assert exited.value.code == 0
    assert bytes(emitted) == helper.canonical_json(result) + b"\n"


def test_pending_signal_is_safely_terminalized_once(helper: Any) -> None:
    output_read, output_write = os.pipe()
    child = os.fork()
    if child == 0:
        try:
            os.close(output_read)
            os.dup2(output_write, 1)
            os.close(output_write)

            def execute_with_pending_signal(_mode: str) -> dict[str, str]:
                os.kill(os.getpid(), signal.SIGTERM)
                return helper._result(
                    state="audited",
                    inventory_class="empty",
                    owner_state="not_checked",
                    cleanup_status="not_requested",
                )

            helper.execute = execute_with_pending_signal
            sys.argv = [str(HELPER), "audit"]
            helper.main()
        except BaseException as error:
            if isinstance(error, SystemExit):
                os._exit(int(error.code))
            os._exit(99)
    os.close(output_write)
    payload = bytearray()
    while chunk := os.read(output_read, 4096):
        payload.extend(chunk)
    os.close(output_read)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert payload.count(b"\n") == 1
    assert b'"state":"audited"' in payload


def test_signal_boundary_stays_blocked_through_terminal_write() -> None:
    source = HELPER.read_text()
    assert "signal.pthread_sigmask(signal.SIG_UNBLOCK" not in source
    assert source.index("signal.pthread_sigmask(signal.SIG_BLOCK") < source.index("result = execute(mode)")
    assert source.index("signal.signal(handled_signal, signal.SIG_IGN)") < source.index("_terminal_record(result)")


def test_bundle_inventory_is_exact() -> None:
    assert {path.name for path in HERE.iterdir()} == {
        "README.md",
        "recover_vmvm_owner_lifecycle_v4_scratch.py",
        "test_vmvm_owner_lifecycle_v4_scratch_recovery.py",
    }
