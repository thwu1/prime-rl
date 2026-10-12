from __future__ import annotations

import json
import signal
import stat
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from vmvm_tb_v2._vacli import backend as vmvm_backend


class FakeProcess:
    def __init__(self, waits: list[int | BaseException], *, poll_value: int | None = None) -> None:
        self.pid = 42
        self.returncode = poll_value
        self._poll_value = poll_value
        self._waits = list(waits)

    def poll(self) -> int | None:
        return self._poll_value

    def wait(self, timeout: float) -> int:
        value = self._waits.pop(0)
        if isinstance(value, BaseException):
            raise value
        self.returncode = value
        self._poll_value = value
        return value


class FakeSubprocess:
    TimeoutExpired = subprocess.TimeoutExpired
    DEVNULL = subprocess.DEVNULL

    def run(self, *_args, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


class FakeSession:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> bool:
        self.stopped = True
        return True


class FakeLease:
    def __init__(self, receipt: vmvm_backend.VacliLeaseCleanupReceipt) -> None:
        self.receipt = receipt

    def cleanup(self) -> vmvm_backend.VacliLeaseCleanupReceipt:
        return self.receipt


def _private_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    output = tmp_path / "run"
    control = output / "control"
    control.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    control.chmod(0o700)
    path = control / "vmvm_cleanup_receipts.jsonl"
    identity_sha256 = "a" * 64
    monkeypatch.setenv("PRIME_RL_OUTPUT_DIR", str(output))
    monkeypatch.setenv("VMVM_CLEANUP_RECEIPT_LOG", str(path))
    monkeypatch.setenv("VMVM_CLEANUP_RUN_IDENTITY_SHA256", identity_sha256)
    assert vmvm_backend._cleanup_receipt_binding() == (path, identity_sha256)
    return path, identity_sha256


def test_vacli_release_receipt_requires_graceful_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess([0])
    lease = vmvm_backend.VacliLease(
        "synthetic-tenant",
        Path("/tmp/synthetic-vacli.log"),
        subprocess_mod=FakeSubprocess(),
    )
    lease.proc = process
    signals: list[int] = []
    monkeypatch.setattr(vmvm_backend.os, "getpgid", lambda _pid: 42)
    monkeypatch.setattr(vmvm_backend.os, "killpg", lambda _pgid, sig: signals.append(sig))

    receipt = lease.cleanup()

    assert receipt.release_on_exit_completed is True
    assert receipt.sigkill_used is False
    assert receipt.exit_code == 0
    assert signals == [signal.SIGTERM]
    assert lease.cleanup() is receipt


def test_vacli_release_receipt_rejects_sigkill_ttl_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess([subprocess.TimeoutExpired("vacli", 1), -signal.SIGKILL])
    lease = vmvm_backend.VacliLease(
        "synthetic-tenant",
        Path("/tmp/synthetic-vacli.log"),
        cleanup_timeout=1,
        subprocess_mod=FakeSubprocess(),
    )
    lease.proc = process
    signals: list[int] = []
    monkeypatch.setattr(vmvm_backend.os, "getpgid", lambda _pid: 42)
    monkeypatch.setattr(vmvm_backend.os, "killpg", lambda _pgid, sig: signals.append(sig))

    receipt = lease.cleanup()

    assert receipt.release_on_exit_completed is False
    assert receipt.sigkill_used is True
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def _backend_for_cleanup(path: Path, identity_sha256: str) -> vmvm_backend.VacliVMVMBackend:
    backend = object.__new__(vmvm_backend.VacliVMVMBackend)
    backend._sp = FakeSubprocess()
    backend._destroyed = False
    backend._cleanup_result = None
    backend._cleanup_binding = (path, identity_sha256)
    backend._cleanup_instance_nonce = "b" * 32
    backend._cleanup_passes = 0
    backend._command_cancel_lock = threading.Lock()
    backend._telemetry_runtime_active = False
    backend._host_tunnels = set()
    backend._network_isolation = SimpleNamespace(firewall_active=False, network="synthetic-network")
    backend._session = FakeSession()
    backend._fifo_mode = False
    backend._compose_project = "synthetic-compose"
    backend._compose_dir = "/tmp/synthetic-compose"
    backend._compose_services = ("synthetic-service",)
    backend._container_id = "a" * 12
    backend._ssh_port = 1234
    backend._control_path = "/tmp/synthetic-control"
    backend._compose_command = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0,
        stdout=b"",
        stderr=b"",
    )
    backend._ssh_call_raw = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0,
        stdout=b"",
        stderr=b"",
    )
    backend._lease = FakeLease(
        vmvm_backend.VacliLeaseCleanupReceipt(
            process_was_alive=True,
            sigterm_sent=True,
            wait_completed=True,
            exit_code=0,
            sigkill_used=False,
            release_on_exit_completed=True,
        )
    )
    return backend


def test_backend_persists_private_aggregate_cleanup_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, identity_sha256 = _private_binding(tmp_path, monkeypatch)
    backend = _backend_for_cleanup(path, identity_sha256)

    backend.destroy()

    receipt = json.loads(path.read_text())
    assert receipt["state"] == "passed"
    assert receipt["runtime_instance_nonce"] == "b" * 32
    assert receipt["cleanup_pass"] == 1
    assert receipt["compose_present"] is True
    assert receipt["compose_teardown_completed"] is True
    assert receipt["release_on_exit_completed"] is True
    assert receipt["remote_deletion_verified"] is False
    assert receipt["eval_run_identity_sha256"] == identity_sha256
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    encoded = path.read_text().lower()
    assert "sessionid" not in encoded
    assert "container_id" not in encoded
    assert "task" not in encoded
    backend.destroy()
    receipts = [json.loads(line) for line in path.read_text().splitlines()]
    assert [receipt["cleanup_pass"] for receipt in receipts] == [1, 2]


def test_backend_persists_private_runtime_creation_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, identity_sha256 = _private_binding(tmp_path, monkeypatch)

    vmvm_backend._append_runtime_created((path, identity_sha256), "b" * 32)

    lifecycle = path.with_name("vmvm_runtime_lifecycle.jsonl")
    assert stat.S_IMODE(lifecycle.stat().st_mode) == 0o600
    assert lifecycle.stat().st_nlink == 1
    assert json.loads(lifecycle.read_text()) == {
        "schema_version": 1,
        "kind": "vmvm-runtime-created",
        "runtime_instance_nonce": "b" * 32,
        "eval_run_identity_sha256": identity_sha256,
    }


def test_backend_destroy_failure_is_durable_and_propagated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, identity_sha256 = _private_binding(tmp_path, monkeypatch)
    backend = _backend_for_cleanup(path, identity_sha256)
    backend._compose_command = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=1,
        stdout=b"synthetic failure",
        stderr=b"",
    )

    with pytest.raises(RuntimeError, match="strict local release"):
        backend.destroy()

    receipt = json.loads(path.read_text())
    assert receipt["state"] == "failed"
    assert receipt["failures"] == 1
    assert receipt["compose_teardown_completed"] is False
    assert receipt["remote_deletion_verified"] is False


def test_cleanup_binding_rejects_alias_and_partial_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _identity_sha256 = _private_binding(tmp_path, monkeypatch)
    alias = path.parent / "alias.jsonl"
    monkeypatch.setenv("VMVM_CLEANUP_RECEIPT_LOG", str(alias))
    with pytest.raises(vmvm_backend.BackendInitError, match="path is invalid"):
        vmvm_backend._cleanup_receipt_binding()

    monkeypatch.delenv("VMVM_CLEANUP_RUN_IDENTITY_SHA256")
    with pytest.raises(vmvm_backend.BackendInitError, match="binding is incomplete"):
        vmvm_backend._cleanup_receipt_binding()


def test_cleanup_receipt_partial_append_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _identity_sha256 = _private_binding(tmp_path, monkeypatch)
    original = b'{"prior":"receipt"}\n'
    path.write_bytes(original)
    path.chmod(0o600)
    real_write = vmvm_backend.os.write
    calls = 0

    def interrupted_write(descriptor: int, payload: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            prefix = payload[: max(1, len(payload) // 2)]
            return real_write(descriptor, prefix)
        raise OSError("injected append failure")

    monkeypatch.setattr(vmvm_backend.os, "write", interrupted_write)
    with pytest.raises(OSError, match="injected append failure"):
        vmvm_backend._append_cleanup_receipt(path, {"new": "receipt"})

    assert path.read_bytes() == original
