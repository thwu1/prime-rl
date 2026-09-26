from __future__ import annotations

import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest
import sandoq_ecr_rotation as rotation


class FakeClock:
    def __init__(self, now: int = 0) -> None:
        self.now = float(now)

    def time(self) -> float:
        return float(self.now)

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def monotonic(self) -> float:
        return float(self.now)


class FakeProcess:
    next_pid = 100_000

    def __init__(self, code=None) -> None:
        type(self).next_pid += 1
        self.pid = type(self).next_pid
        self.code = code
        self.group_alive = code is None
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self) -> None:
        self.terminated = True
        self.code = -15

    def kill(self) -> None:
        self.code = -9

    def wait(self, timeout: int):
        if self.code is None:
            raise subprocess.TimeoutExpired(["fixture"], timeout)
        return self.code


def _terminate_fake_group(process: FakeProcess, timeout: int) -> None:
    del timeout
    process.terminated = True
    process.code = -15
    process.group_alive = False


def _fake_groups(*processes: FakeProcess):
    by_pid = {process.pid: process for process in processes}
    return lambda process_id: by_pid[process_id].group_alive


def _start_fake_evaluator(command, *, process_factory, **_kwargs):
    return process_factory(list(command), start_new_session=True), None


def _private_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def _write_private(path: Path, body: bytes) -> None:
    path.write_bytes(body)
    path.chmod(0o600)


def _state(token_path: Path, now: int = 0, *, status: str = "running") -> dict:
    return rotation._state_value(
        status=status,
        generation=1,
        issued_at=now,
        heartbeat_at=now,
        consecutive_failures=0,
        token_identity=rotation._token_identity(token_path),
    )


def _verified_cleanup_command(monkeypatch, tmp_path: Path) -> tuple[Path, list[str]]:
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    control_dir = output_dir / "control"
    control_dir.mkdir(mode=0o700)
    event_log = output_dir / "pool_events.jsonl"
    wal = control_dir / "sandoq-pool.wal.jsonl"
    _write_private(event_log, b"fixture\n")
    _write_private(wal, b"fixture\n")
    pool_root = tmp_path / "pool"
    pool_root.mkdir(mode=0o700)
    pool_socket = pool_root / "job.sock"
    project_root = Path(rotation.__file__).resolve().parents[3]
    command = [
        sys.executable,
        "-B",
        str(project_root / "user/tianhaowu/terminal_bench_vmvm/run_sandoq_verified_cleanup.py"),
        "--output-dir",
        str(output_dir),
        "--provider-cleanup",
        str(
            project_root
            / "deps/sandoq-provider/recipes/sandoq_swerebench_v2_oci/verify_pool_cleanup.py"
        ),
        "--base-url",
        rotation.VERIFIED_CLEANUP_BASE_URL,
        "--owner",
        "fixture-owner",
        "--concurrency",
        str(rotation.VERIFIED_CLEANUP_CONCURRENCY),
        "--event-log",
        str(event_log),
        "--wal",
        str(wal),
        "--drain-marker",
        str(pool_root / "job.drained.json"),
        "--sanitized-output",
        str(output_dir / "sandoq_cleanup_audit.json"),
        "--project-root",
        str(project_root),
        "--provider-root",
        str(project_root / "deps/sandoq-provider"),
        "--expected-prime-commit",
        "1" * 40,
        "--expected-prime-tree",
        "2" * 40,
        "--expected-self-sha256",
        "3" * 64,
        "--expected-sanitizer-sha256",
        "4" * 64,
        "--expected-provider-cleanup-sha256",
        "5" * 64,
    ]
    command_file = control_dir / "cleanup-command.json"
    _write_private(command_file, rotation.canonical_json(command))
    monkeypatch.setenv("PRIME_RL_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("SANDOQ_OWNER", "fixture-owner")
    monkeypatch.setenv("OCI_RUNNER_POOL_EVENT_LOG", str(event_log))
    monkeypatch.setenv("OCI_RUNNER_POOL_WAL", str(wal))
    monkeypatch.setenv("OCI_RUNNER_POOL_SOCKET", str(pool_socket))
    return command_file, command


def test_fake_ucloud_mints_without_echoing_or_hashing_secret(tmp_path: Path, capsys) -> None:
    directory = _private_dir(tmp_path)
    executable = directory / "fake-ucloud"
    executable.write_text("#!/bin/sh\nprintf 'private-fixture-token\\n'\n")
    executable.chmod(0o700)

    token = rotation.mint_ecr_token(str(executable), "us-east-2", 5)

    assert token == b"private-fixture-token"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    "payload",
    [b" leading", b"trailing ", b"two\nlines\n", b"two\n\n", b"non-ascii-\xff"],
)
def test_fake_ucloud_rejects_noncanonical_secret_line(payload: bytes) -> None:
    def runner(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, payload, b"")

    with pytest.raises(rotation.RotationError, match="^ecr_mint_failed$"):
        rotation.mint_ecr_token("ucloud", "us-east-2", 5, runner=runner)


def test_ucloud_client_certificate_environment_is_scoped(monkeypatch, tmp_path: Path) -> None:
    certificate = tmp_path / "client.pem"
    certificate.write_text("fixture")
    captured: dict = {}

    def runner(*_args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0, b"private-fixture-token\n", b"")

    monkeypatch.setenv("THRIFT_TLS_CL_CERT_PATH", "/wrong/cert")
    monkeypatch.delenv("THRIFT_TLS_CL_KEY_PATH", raising=False)
    rotation.mint_ecr_token(
        "ucloud",
        "us-east-2",
        5,
        client_cert_path=certificate,
        runner=runner,
    )

    assert captured["env"]["THRIFT_TLS_CL_CERT_PATH"] == str(certificate)
    assert captured["env"]["THRIFT_TLS_CL_KEY_PATH"] == str(certificate)
    assert os.environ["THRIFT_TLS_CL_CERT_PATH"] == "/wrong/cert"
    assert "THRIFT_TLS_CL_KEY_PATH" not in os.environ


def test_mint_failure_retains_prior_token_and_never_records_it(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    log_path = directory / "rotator.jsonl"
    old = b"prior-private-fixture"
    _write_private(token_path, old + b"\n")

    with pytest.raises(rotation.RotationError, match="^ecr_mint_failed$"):
        rotation.run_rotation_service(
            rotation.RotationConfig(token_path, state_path, log_path),
            clock=FakeClock(100),
            mint=lambda: (_ for _ in ()).throw(rotation.RotationError("ecr_mint_failed")),
            max_iterations=1,
        )

    assert token_path.read_bytes() == old + b"\n"
    assert old not in log_path.read_bytes()
    assert not state_path.exists()


def test_fake_clock_rotates_every_four_hours_with_atomic_mode_0600(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    log_path = directory / "rotator.jsonl"
    clock = FakeClock(1_000)
    issued: list[bytes] = []

    def mint() -> bytes:
        value = f"private-fixture-{len(issued) + 1}".encode()
        issued.append(value)
        return value

    rotation.run_rotation_service(
        rotation.RotationConfig(
            token_path,
            state_path,
            log_path,
            heartbeat_seconds=150,
        ),
        clock=clock,
        mint=mint,
        max_iterations=98,
    )

    assert len(issued) == 2
    assert token_path.read_bytes() == issued[-1] + b"\n"
    assert os.stat(token_path).st_mode & 0o777 == 0o600
    assert os.stat(state_path).st_mode & 0o777 == 0o600
    public = state_path.read_bytes() + log_path.read_bytes()
    assert all(secret not in public for secret in issued)
    assert b"sha256" not in public.lower()


def test_secret_silent_read_rejects_embedded_newline(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    _write_private(token_path, b"part-one\npart-two")

    with pytest.raises(rotation.RotationError, match="^credential_read_proof_failed$"):
        rotation.read_secret_silent(token_path)


def test_rotator_death_terminates_evaluator_then_runs_cleanup(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    guard_log = directory / "guard.jsonl"
    _write_private(token_path, b"private-fixture\n")
    _write_private(state_path, rotation.canonical_json(_state(token_path)))
    clock = FakeClock(0)
    process = FakeProcess()
    cleanup_process = FakeProcess(code=0)
    cleaned: list[list[str]] = []

    def cleanup_process_factory(command, **kwargs):
        assert kwargs["start_new_session"] is True
        cleaned.append(command)
        return cleanup_process

    code = rotation.supervise_rollout(
        rotation.GuardConfig(
            token_file=token_path,
            state_file=state_path,
            event_log=guard_log,
            heartbeat_timeout_seconds=60,
            cleanup_reserve_seconds=10,
            fail_closed_before_expiry_seconds=2,
            termination_timeout_seconds=2,
            cleanup_timeout_seconds=5,
            final_safety_seconds=2,
            poll_seconds=30,
        ),
        ["evaluator"],
        ["cleanup"],
        clock=clock,
        machine=lambda: "x86_64",
        process_factory=lambda *_args, **_kwargs: process,
        cleanup_process_factory=cleanup_process_factory,
        process_group_exists=_fake_groups(process, cleanup_process),
        terminate_process_group=_terminate_fake_group,
        evaluator_starter=_start_fake_evaluator,
    )

    assert code == 86
    assert process.terminated
    assert cleaned == [["cleanup"]]
    public = guard_log.read_text()
    assert "credential_guard_failed" in public
    assert "private-fixture" not in public


def test_guard_rejects_non_x86_before_starting_evaluator(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    guard_log = directory / "guard.jsonl"
    _write_private(token_path, b"private-fixture\n")
    _write_private(state_path, rotation.canonical_json(_state(token_path)))
    started = False

    def process_factory(*_args, **_kwargs):
        nonlocal started
        started = True
        return FakeProcess()

    with pytest.raises(rotation.GuardViolation, match="^batch_architecture_invalid$"):
        rotation.supervise_rollout(
            rotation.GuardConfig(
                token_file=token_path,
                state_file=state_path,
                event_log=guard_log,
            ),
            ["evaluator"],
            ["cleanup"],
            clock=FakeClock(0),
            machine=lambda: "aarch64",
            process_factory=process_factory,
        )
    assert not started


def test_supervisor_handshake_uses_authenticated_socket_bound_to_evaluator_group(
    tmp_path: Path,
) -> None:
    observed = tmp_path / "handshake.json"
    script = """
import json
import os
import socket
from pathlib import Path

if "SANDOQ_CLEANUP_SUPERVISOR_SOCKET" in os.environ:
    raise SystemExit(2)
descriptor = int(os.environ["SANDOQ_CLEANUP_SUPERVISOR_CHANNEL_FD"])
channel = socket.socket(fileno=descriptor)
peer_pid, peer_uid, _peer_gid = __import__("struct").unpack(
    "3i", channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
)
if (
    channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_SEQPACKET
    or peer_uid != os.getuid()
    or peer_pid != os.getppid()
    or os.getpid() != os.getpgrp()
):
    raise SystemExit(2)
Path(os.environ["HANDSHAKE_OUTPUT"]).write_text(json.dumps({
    "channel_inherited": True,
    "evaluator_pid": os.getpid(),
}, sort_keys=True))
"""
    previous = os.environ.get("HANDSHAKE_OUTPUT")
    os.environ["HANDSHAKE_OUTPUT"] = str(observed)
    try:
        process, channel = rotation._start_supervised_evaluator(
            [sys.executable, "-c", script],
            process_factory=subprocess.Popen,
            termination_timeout=2,
            terminate_process_group=rotation._terminate_process_group,
        )
        assert process.wait(timeout=10) == 0
        channel.close()
    finally:
        if previous is None:
            os.environ.pop("HANDSHAKE_OUTPUT", None)
        else:
            os.environ["HANDSHAKE_OUTPUT"] = previous

    assert json.loads(observed.read_text()) == {
        "channel_inherited": True,
        "evaluator_pid": process.pid,
    }


def test_supervisor_rejects_spoofed_post_exec_identity() -> None:
    processes: list[subprocess.Popen] = []
    script = """
import json
import os
import socket
import time

channel = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
channel.connect(os.environ["SANDOQ_CLEANUP_SUPERVISOR_SOCKET"])
channel.sendall(json.dumps({
    "schema_version": 1,
    "kind": "sandoq-cleanup-supervisor-v1-hello",
    "evaluator_pid": os.getpid(),
    "evaluator_process_group_id": os.getpgrp(),
    "evaluator_start_ticks": 1,
}, sort_keys=True, separators=(",", ":")).encode() + b"\\n")
time.sleep(30)
"""

    def malicious_factory(_command, **kwargs):
        process = subprocess.Popen([sys.executable, "-c", script], **kwargs)
        processes.append(process)
        return process

    with pytest.raises(rotation.GuardViolation, match="^supervisor_handshake_failed$"):
        rotation._start_supervised_evaluator(
            [sys.executable, "-c", "raise SystemExit(0)"],
            process_factory=malicious_factory,
            termination_timeout=2,
            terminate_process_group=rotation._terminate_process_group,
        )

    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_supervisor_close_rejects_socket_path_substitution(tmp_path: Path) -> None:
    root = tmp_path / "supervisor"
    root.mkdir(mode=0o700)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    root_descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    root_identity = rotation._supervisor_root_identity(os.fstat(root_descriptor))
    socket_path = root / "channel.sock"
    original = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    original.bind(str(socket_path))
    socket_path.chmod(0o600)
    socket_identity = rotation._supervisor_socket_identity(socket_path.lstat())
    connection, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    channel = rotation._SupervisorChannel(
        connection,
        parent_descriptor,
        root_descriptor,
        root.name,
        root_identity,
        socket_identity,
    )
    socket_path.unlink()
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    replacement.bind(str(socket_path))
    socket_path.chmod(0o600)

    with pytest.raises(
        rotation.GuardViolation, match="^supervisor_socket_cleanup_failed$"
    ):
        channel.close()

    assert socket_path.exists()
    peer.close()
    original.close()
    replacement.close()
    socket_path.unlink()
    root.rmdir()


def test_supervisor_start_failure_still_runs_cleanup(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    guard_log = directory / "guard.jsonl"
    _write_private(token_path, b"private-fixture\n")
    _write_private(state_path, rotation.canonical_json(_state(token_path)))
    cleanup_process = FakeProcess(code=0)
    cleanups = 0

    def failing_starter(*_args, **_kwargs):
        raise rotation.GuardViolation("supervisor_handshake_failed")

    def cleanup_process_factory(command, **kwargs):
        nonlocal cleanups
        assert command == ["cleanup"]
        assert kwargs["start_new_session"] is True
        cleanups += 1
        return cleanup_process

    with pytest.raises(rotation.GuardViolation, match="^supervisor_handshake_failed$"):
        rotation.supervise_rollout(
            rotation.GuardConfig(
                token_file=token_path,
                state_file=state_path,
                event_log=guard_log,
                cleanup_reserve_seconds=10,
                fail_closed_before_expiry_seconds=2,
                termination_timeout_seconds=2,
                cleanup_timeout_seconds=5,
                final_safety_seconds=2,
            ),
            ["evaluator"],
            ["cleanup"],
            clock=FakeClock(0),
            machine=lambda: "x86_64",
            cleanup_process_factory=cleanup_process_factory,
            process_group_exists=_fake_groups(cleanup_process),
            terminate_process_group=_terminate_fake_group,
            evaluator_starter=failing_starter,
        )

    assert cleanups == 1
    assert "cleanup_completed" in guard_log.read_text()


def test_supervisor_channel_eof_terminates_group_then_cleans(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    guard_log = directory / "guard.jsonl"
    _write_private(token_path, b"private-fixture\n")
    _write_private(state_path, rotation.canonical_json(_state(token_path)))
    process = FakeProcess()
    cleanup_process = FakeProcess(code=0)
    guard_channel, evaluator_channel = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_SEQPACKET
    )
    evaluator_channel.close()

    def starter(*_args, **_kwargs):
        return process, guard_channel

    code = rotation.supervise_rollout(
        rotation.GuardConfig(
            token_file=token_path,
            state_file=state_path,
            event_log=guard_log,
            cleanup_reserve_seconds=10,
            fail_closed_before_expiry_seconds=2,
            termination_timeout_seconds=2,
            cleanup_timeout_seconds=5,
            final_safety_seconds=2,
        ),
        ["evaluator"],
        ["cleanup"],
        clock=FakeClock(0),
        machine=lambda: "x86_64",
        cleanup_process_factory=lambda *_args, **_kwargs: cleanup_process,
        process_group_exists=_fake_groups(process, cleanup_process),
        terminate_process_group=_terminate_fake_group,
        evaluator_starter=starter,
    )

    assert code == 86
    assert process.terminated
    assert not process.group_alive
    assert "supervisor_channel_closed" in guard_log.read_text()


def test_cleanup_command_is_bound_to_verified_cleanup_contract(
    monkeypatch, tmp_path: Path
) -> None:
    command_file, command = _verified_cleanup_command(monkeypatch, tmp_path)

    assert rotation._command_from_json(command_file) == command


def test_cleanup_command_allows_broker_evidence_to_be_created_after_guard_start(
    monkeypatch, tmp_path: Path
) -> None:
    command_file, command = _verified_cleanup_command(monkeypatch, tmp_path)
    Path(os.environ["OCI_RUNNER_POOL_EVENT_LOG"]).unlink()
    Path(os.environ["OCI_RUNNER_POOL_WAL"]).unlink()

    assert rotation._command_from_json(command_file) == command


@pytest.mark.parametrize(
    ("target", "replacement"),
    [
        ("program", "/bin/true"),
        ("--base-url", "https://example.invalid"),
        ("--concurrency", "1"),
        ("--sanitized-output", "/tmp/forged-cleanup.json"),
    ],
)
def test_cleanup_command_rejects_unbound_or_noop_program(
    monkeypatch, tmp_path: Path, target: str, replacement: str
) -> None:
    command_file, command = _verified_cleanup_command(monkeypatch, tmp_path)
    if target == "program":
        command[0] = replacement
    else:
        command[command.index(target) + 1] = replacement
    command_file.write_bytes(rotation.canonical_json(command))
    command_file.chmod(0o600)

    with pytest.raises(rotation.RotationError, match="^command_file_invalid$"):
        rotation._command_from_json(command_file)


def test_cleanup_command_rejects_public_or_hardlinked_plan(
    monkeypatch, tmp_path: Path
) -> None:
    command_file, _command = _verified_cleanup_command(monkeypatch, tmp_path)
    command_file.chmod(0o644)

    with pytest.raises(rotation.RotationError, match="^command_file_invalid$"):
        rotation._command_from_json(command_file)

    command_file.chmod(0o600)
    alias = command_file.with_name("cleanup-command-alias.json")
    os.link(command_file, alias)
    with pytest.raises(rotation.RotationError, match="^command_file_invalid$"):
        rotation._command_from_json(command_file)


def test_cleanup_command_rejects_same_directory_path_substitution(
    monkeypatch, tmp_path: Path
) -> None:
    command_file, _command = _verified_cleanup_command(monkeypatch, tmp_path)
    original_read = rotation.os.read
    replaced = False

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, size)
        if chunk and not replaced:
            replaced = True
            backup = command_file.with_name("original-command.json")
            command_file.rename(backup)
            _write_private(command_file, rotation.canonical_json(["/bin/true"]))
        return chunk

    monkeypatch.setattr(rotation.os, "read", racing_read)
    with pytest.raises(rotation.RotationError, match="^command_file_invalid$"):
        rotation._command_from_json(command_file)


def test_guard_signal_request_terminates_then_cleans_once(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    guard_log = directory / "guard.jsonl"
    _write_private(token_path, b"private-fixture\n")
    _write_private(state_path, rotation.canonical_json(_state(token_path)))
    process = FakeProcess()
    cleanup_process = FakeProcess(code=0)
    cleanups = 0

    def cleanup_process_factory(command, **kwargs):
        nonlocal cleanups
        assert kwargs["start_new_session"] is True
        cleanups += 1
        return cleanup_process

    code = rotation.supervise_rollout(
        rotation.GuardConfig(
            token_file=token_path,
            state_file=state_path,
            event_log=guard_log,
            cleanup_reserve_seconds=10,
            fail_closed_before_expiry_seconds=2,
            termination_timeout_seconds=2,
            cleanup_timeout_seconds=5,
            final_safety_seconds=2,
        ),
        ["evaluator"],
        ["cleanup"],
        clock=FakeClock(0),
        machine=lambda: "x86_64",
        process_factory=lambda *_args, **_kwargs: process,
        cleanup_process_factory=cleanup_process_factory,
        process_group_exists=_fake_groups(process, cleanup_process),
        terminate_process_group=_terminate_fake_group,
        evaluator_starter=_start_fake_evaluator,
        stop_requested=lambda: True,
    )

    assert code == 86
    assert process.terminated
    assert cleanups == 1
    assert "guard_signal_requested" in guard_log.read_text()


def test_guard_log_failure_still_terminates_and_cleans_once(monkeypatch, tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    guard_log = directory / "guard.jsonl"
    _write_private(token_path, b"private-fixture\n")
    _write_private(state_path, rotation.canonical_json(_state(token_path)))
    process = FakeProcess()
    cleanup_process = FakeProcess(code=0)
    cleanups = 0
    original_append = rotation.DurableEventLog.append

    def failing_append(self, **kwargs):
        if kwargs["event"] == "heartbeat_verified":
            raise OSError("injected event-log failure")
        return original_append(self, **kwargs)

    def cleanup_process_factory(command, **kwargs):
        nonlocal cleanups
        assert kwargs["start_new_session"] is True
        cleanups += 1
        return cleanup_process

    monkeypatch.setattr(rotation.DurableEventLog, "append", failing_append)
    with pytest.raises(OSError, match="injected event-log failure"):
        rotation.supervise_rollout(
            rotation.GuardConfig(
                token_file=token_path,
                state_file=state_path,
                event_log=guard_log,
                cleanup_reserve_seconds=10,
                fail_closed_before_expiry_seconds=2,
                termination_timeout_seconds=2,
                cleanup_timeout_seconds=5,
                final_safety_seconds=2,
            ),
            ["evaluator"],
            ["cleanup"],
            clock=FakeClock(0),
            machine=lambda: "x86_64",
            process_factory=lambda *_args, **_kwargs: process,
            cleanup_process_factory=cleanup_process_factory,
            process_group_exists=_fake_groups(process, cleanup_process),
            terminate_process_group=_terminate_fake_group,
            evaluator_starter=_start_fake_evaluator,
        )
    assert process.terminated
    assert cleanups == 1


def test_signal_handlers_only_set_stop_event(monkeypatch) -> None:
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler))
    stop = threading.Event()
    rotation._install_stop_handlers(stop)
    assert set(handlers) == {signal.SIGTERM, signal.SIGINT}
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert stop.is_set()


def test_process_group_termination_kills_survivors_after_leader_exit() -> None:
    process = FakeProcess(code=0)
    process.group_alive = True
    clock = FakeClock()
    signals: list[int] = []

    def send_group_signal(process_group_id: int, signum: int) -> None:
        assert process_group_id == process.pid
        signals.append(signum)
        if signum == signal.SIGKILL:
            process.group_alive = False

    rotation._terminate_process_group(
        process,
        2,
        group_exists=lambda process_group_id: (
            process_group_id == process.pid and process.group_alive
        ),
        send_group_signal=send_group_signal,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert not process.group_alive


def test_process_group_termination_fails_if_kill_does_not_extinguish_group() -> None:
    process = FakeProcess(code=0)
    process.group_alive = True
    clock = FakeClock()

    with pytest.raises(rotation.GuardViolation, match="^process_group_cleanup_failed$"):
        rotation._terminate_process_group(
            process,
            2,
            group_exists=lambda _process_group_id: True,
            send_group_signal=lambda _process_group_id, _signum: None,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )


def test_cleanup_timeout_uses_private_process_group_and_tears_it_down() -> None:
    process = FakeProcess()
    invocation: dict = {}

    def process_factory(command, **kwargs):
        invocation["command"] = command
        invocation.update(kwargs)
        return process

    with pytest.raises(rotation.GuardViolation, match="^cleanup_failed$"):
        rotation._run_cleanup_command(
            ["cleanup"],
            timeout=5,
            termination_timeout=2,
            process_factory=process_factory,
            group_exists=_fake_groups(process),
            terminate_process_group=_terminate_fake_group,
        )

    assert invocation["command"] == ["cleanup"]
    assert invocation["start_new_session"] is True
    assert invocation["stdout"] == subprocess.DEVNULL
    assert invocation["stderr"] == subprocess.DEVNULL
    assert process.terminated
    assert not process.group_alive


def test_guard_rejects_and_cleans_descendants_after_evaluator_leader_exit(
    tmp_path: Path,
) -> None:
    directory = _private_dir(tmp_path)
    token_path = directory / "ecr-token"
    state_path = directory / "state.json"
    guard_log = directory / "guard.jsonl"
    _write_private(token_path, b"private-fixture\n")
    _write_private(state_path, rotation.canonical_json(_state(token_path)))
    process = FakeProcess(code=0)
    process.group_alive = True
    cleanup_process = FakeProcess(code=0)

    with pytest.raises(
        rotation.GuardViolation,
        match="^evaluator_process_group_survived$",
    ):
        rotation.supervise_rollout(
            rotation.GuardConfig(
                token_file=token_path,
                state_file=state_path,
                event_log=guard_log,
                cleanup_reserve_seconds=10,
                fail_closed_before_expiry_seconds=2,
                termination_timeout_seconds=2,
                cleanup_timeout_seconds=5,
                final_safety_seconds=2,
            ),
            ["evaluator"],
            ["cleanup"],
            clock=FakeClock(0),
            machine=lambda: "x86_64",
            process_factory=lambda *_args, **_kwargs: process,
            cleanup_process_factory=lambda *_args, **_kwargs: cleanup_process,
            process_group_exists=_fake_groups(process, cleanup_process),
            terminate_process_group=_terminate_fake_group,
            evaluator_starter=_start_fake_evaluator,
        )

    assert process.terminated
    assert not process.group_alive


def _event(
    log: rotation.DurableEventLog,
    event: str,
    timestamp: int,
    *,
    detail: str = "ok",
    generation: int = 1,
    issued_at: int | None = 0,
) -> None:
    log.append(
        event=event,
        timestamp=timestamp,
        generation=generation,
        issued_at=issued_at,
        expires_at=None if issued_at is None else issued_at + rotation.TOKEN_LIFETIME_SECONDS,
        detail=detail,
    )


def test_sanitized_audit_contains_only_aggregate_rotation_evidence(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    rotator_path = directory / "rotator.jsonl"
    guard_path = directory / "guard.jsonl"
    rotator = rotation.DurableEventLog(rotator_path, kind="sandoq-ecr-rotation-event")
    _event(rotator, "rotator_started", 0, generation=0, issued_at=None)
    _event(rotator, "token_replaced", 0)
    _event(rotator, "heartbeat", 60, detail="running")
    _event(rotator, "rotator_stopped", 103)
    rotator.close()
    guard = rotation.DurableEventLog(guard_path, kind="sandoq-ecr-guard-event")
    _event(guard, "guard_started", 1)
    _event(guard, "initial_read_verified", 1, detail="x86_64")
    _event(guard, "evaluator_started", 1)
    _event(guard, "heartbeat_verified", 2, detail="running")
    _event(guard, "heartbeat_verified", 50, detail="running")
    _event(guard, "evaluator_exited", 100, detail="0")
    _event(guard, "cleanup_started", 100)
    _event(guard, "cleanup_completed", 101, detail="0")
    _event(guard, "guard_stopped", 102, detail="passed")
    guard.close()

    audit = rotation.sanitize_rotation_audit(
        rotator_path,
        guard_path,
        eval_run_identity_sha256="a" * 64,
        results_sha256="b" * 64,
    )

    assert audit["state"] == "passed"
    assert audit["successful_replacements"] == 1
    assert audit["batch_heartbeats"] == 2
    assert audit["maximum_observed_heartbeat_gap_seconds"] == 50
    assert audit["credential_payload_records"] == 0
    encoded = json.dumps(audit, sort_keys=True)
    assert "token_file" not in encoded
    assert "private-fixture" not in encoded


def test_sanitizer_rejects_rotator_death_evidence(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    rotator_path = directory / "rotator.jsonl"
    guard_path = directory / "guard.jsonl"
    rotator = rotation.DurableEventLog(rotator_path, kind="sandoq-ecr-rotation-event")
    _event(rotator, "rotator_started", 0, generation=0, issued_at=None)
    _event(rotator, "token_replaced", 0)
    _event(rotator, "rotator_stopped", 103)
    rotator.close()
    guard = rotation.DurableEventLog(guard_path, kind="sandoq-ecr-guard-event")
    _event(guard, "guard_started", 1)
    _event(guard, "initial_read_verified", 1, detail="x86_64")
    _event(guard, "evaluator_started", 1)
    _event(guard, "heartbeat_verified", 2, detail="running")
    _event(guard, "heartbeat_verified", 50, detail="running")
    _event(guard, "guard_triggered", 100, detail="credential_guard_failed")
    _event(guard, "evaluator_terminated", 100, detail="credential_guard_failed")
    _event(guard, "cleanup_started", 100)
    _event(guard, "cleanup_completed", 101, detail="0")
    _event(guard, "guard_stopped", 102, detail="failed")
    guard.close()

    with pytest.raises(rotation.RotationError, match="^rotation_audit_not_passed$"):
        rotation.sanitize_rotation_audit(
            rotator_path,
            guard_path,
            eval_run_identity_sha256="a" * 64,
            results_sha256="b" * 64,
        )


def test_sanitizer_rejects_nonzero_evaluator_and_missing_rotator_stop(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    rotator_path = directory / "rotator.jsonl"
    guard_path = directory / "guard.jsonl"
    rotator = rotation.DurableEventLog(rotator_path, kind="sandoq-ecr-rotation-event")
    _event(rotator, "rotator_started", 0, generation=0, issued_at=None)
    _event(rotator, "token_replaced", 0)
    _event(rotator, "heartbeat", 60, detail="running")
    rotator.close()
    guard = rotation.DurableEventLog(guard_path, kind="sandoq-ecr-guard-event")
    _event(guard, "guard_started", 1)
    _event(guard, "initial_read_verified", 1, detail="x86_64")
    _event(guard, "evaluator_started", 1)
    _event(guard, "heartbeat_verified", 2, detail="running")
    _event(guard, "heartbeat_verified", 50, detail="running")
    _event(guard, "evaluator_exited", 100, detail="1")
    _event(guard, "cleanup_started", 100)
    _event(guard, "cleanup_completed", 101, detail="0")
    _event(guard, "guard_stopped", 102, detail="passed")
    guard.close()

    with pytest.raises(rotation.RotationError, match="^rotation_audit_not_passed$"):
        rotation.sanitize_rotation_audit(
            rotator_path,
            guard_path,
            eval_run_identity_sha256="a" * 64,
            results_sha256="b" * 64,
        )


def test_path_alias_and_service_lock_are_rejected(tmp_path: Path) -> None:
    directory = _private_dir(tmp_path)
    token = directory / "token"
    _write_private(token, b"private-fixture\n")
    with pytest.raises(rotation.RotationError, match="^rotation_path_alias$"):
        rotation.run_rotation_service(
            rotation.RotationConfig(token, token, directory / "events"),
            clock=FakeClock(),
            mint=lambda: b"replacement",
            max_iterations=1,
        )

    service_lock = rotation._lock_path(token, "service")
    with rotation._file_lock(service_lock, exclusive=True):
        with pytest.raises(rotation.RotationError, match="^rotation_lock_busy$"):
            rotation.run_rotation_service(
                rotation.RotationConfig(token, directory / "state", directory / "events"),
                clock=FakeClock(),
                mint=lambda: b"replacement",
                max_iterations=1,
            )


def test_provider_cache_observes_atomic_replacement_at_five_seconds(
    monkeypatch, tmp_path: Path
) -> None:
    provider_root = (
        Path(__file__).resolve().parents[4]
        / "deps/sandoq-provider/extensions/sandoq"
    )
    if not provider_root.is_dir():
        pytest.skip("pinned Sandoq provider submodule is not initialized")
    package = types.ModuleType("sandoq_provider")
    package.__path__ = [str(provider_root / "sandoq_provider")]
    errors = types.ModuleType("prime_sandboxes.exceptions")

    class APIError(RuntimeError):
        pass

    errors.APIError = APIError
    prime_sandboxes = types.ModuleType("prime_sandboxes")
    prime_sandboxes.__path__ = []
    monkeypatch.setitem(sys.modules, "prime_sandboxes", prime_sandboxes)
    monkeypatch.setitem(sys.modules, "prime_sandboxes.exceptions", errors)
    monkeypatch.setitem(sys.modules, "sandoq_provider", package)
    for name in ("secrets", "utils", "ecr"):
        module_name = f"sandoq_provider.{name}"
        spec = importlib.util.spec_from_file_location(
            module_name,
            provider_root / "sandoq_provider" / f"{name}.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
    ecr = sys.modules["sandoq_provider.ecr"]

    directory = _private_dir(tmp_path)
    token = directory / "token"
    _write_private(token, b"first-fixture\n")
    now = [0.0]
    monkeypatch.setattr(ecr.time, "monotonic", lambda: now[0])
    config = ecr.ECRConfig(
        registry="168653207203.dkr.ecr.us-east-2.amazonaws.com",
        region="us-east-2",
        pull_through_prefix="pt_dockerio",
        token_file=token,
        client_cert_path=None,
        ucloud_executable="ucloud",
        refresh_interval_s=14_400,
        command_timeout_s=60,
    )
    cache = ecr.ECRCredentialCache(config)
    first = cache.get()
    rotation._atomic_replace(token, b"second-fixture\n", secret=True)
    now[0] = 4.999
    held = cache.get()
    now[0] = 5.0
    replaced = cache.get()

    assert first["generation"] == held["generation"] == 1
    assert held["reused"] is True
    assert replaced["generation"] == 2
    assert replaced["reused"] is False
