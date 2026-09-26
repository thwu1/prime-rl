from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from vmvm_tb_v2._vacli import backend
from vmvm_tb_v2._vacli import capacity_attestor as attestor


def _keypair(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, str]:
    root.mkdir(mode=0o700)
    key = Ed25519PrivateKey.generate()
    private = root / "private.pem"
    public = root / "public.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private.chmod(0o600)
    public_body = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public.write_bytes(public_body)
    public.chmod(0o600)
    digest = hashlib.sha256(public_body).hexdigest()
    monkeypatch.setattr(attestor, "PINNED_PUBLIC_KEY_SHA256", digest)
    return private, public, digest


def _identity() -> dict:
    return {
        "source": {
            "prime_rl_commit": "1" * 40,
            "verifiers_commit": "2" * 40,
            "renderers_commit": "3" * 40,
            "vmvm_tb_v2_sha256": "4" * 64,
        },
        "execution": {
            "runtime": {"type": "vmvm", "mode": "vacli"},
            "vmvm_environment": {
                "vacli_bin": "/bin/vacli",
                "lease_start_concurrency": 4,
                "lease_retries": 20,
                "max_pull_retries": 20,
                "image_pull_timeout_sec": 3600,
                "container_privileged": True,
            },
        },
    }


def _prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path, str]:
    run = tmp_path / "run"
    control = run / "control"
    control.mkdir(parents=True, mode=0o700)
    run.chmod(0o700)
    control.chmod(0o700)
    private, public, digest = _keypair(tmp_path / "keys", monkeypatch)
    request = control / "vmvm_capacity_request.json"
    attestor.prepare_request(
        identity=_identity(),
        eval_run_identity_sha256="a" * 64,
        invocation_identity_sha256="b" * 64,
        manifest_sha256="c" * 64,
        selector_sha256="d" * 64,
        public_key=public,
        output=request,
    )
    receipt = control / "vmvm_capacity_receipt.json"
    monkeypatch.setenv("VMVM_CAPACITY_REQUEST", str(request))
    monkeypatch.setenv("VMVM_CAPACITY_RECEIPT", str(receipt))
    monkeypatch.setenv("VMVM_CAPACITY_PRIVATE_KEY", str(private))
    monkeypatch.setattr(attestor, "_SIGNING_KEY_PATH", None)
    attestor.consume_capacity_signing_key()
    return request, receipt, public, digest


def _capacity() -> dict[str, int]:
    return {
        "actual_cpu_count": 32,
        "outer_memory_bytes": 36 * 1024**3,
        "disk_available_bytes": 105 * 1024**3,
    }


def test_signed_capacity_happy_path_is_private_exactly_once_and_verifiable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _request, receipt, public, digest = _prepared(tmp_path, monkeypatch)
    nonce = "1" * 32

    attestor.emit_capacity_receipt(nonce, _capacity)

    body = receipt.read_bytes()
    envelope = json.loads(body)
    payload = envelope["payload"]
    assert envelope["key_sha256"] == digest
    assert payload["runtime_instance_nonce"] == nonce
    assert payload["measured_capacity"] == _capacity()
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert receipt.stat().st_nlink == 1
    key = serialization.load_pem_public_key(public.read_bytes())
    key.verify(base64.b64decode(envelope["signature"]), attestor._canonical(payload))

    attestor.emit_capacity_receipt("2" * 32, lambda: (_ for _ in ()).throw(AssertionError("replayed")))
    assert receipt.read_bytes() == body


def test_capacity_rejects_untrusted_key_invalid_request_and_each_shortfall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    _private, public, _digest = _keypair(tmp_path / "keys", monkeypatch)
    monkeypatch.setattr(attestor, "PINNED_PUBLIC_KEY_SHA256", "f" * 64)
    with pytest.raises(attestor.CapacityAttestationError, match="^capacity_public_key_untrusted$"):
        attestor.prepare_request(
            identity=_identity(),
            eval_run_identity_sha256="a" * 64,
            invocation_identity_sha256="b" * 64,
            manifest_sha256="c" * 64,
            selector_sha256="d" * 64,
            public_key=public,
            output=run / "request.json",
        )
    with pytest.raises(attestor.CapacityAttestationError, match="^capacity_request_invalid$"):
        attestor.prepare_request(
            identity={},
            eval_run_identity_sha256="a" * 64,
            invocation_identity_sha256="b" * 64,
            manifest_sha256="c" * 64,
            selector_sha256="d" * 64,
            public_key=public,
            output=run / "request.json",
        )

    for field in _capacity():
        case = tmp_path / field
        _request, _receipt, _public, _digest = _prepared(case, monkeypatch)
        measured = _capacity()
        measured[field] = attestor.MINIMUM_CAPACITY[field] - 1
        with pytest.raises(attestor.CapacityAttestationError, match="^capacity_measurement_invalid$"):
            attestor.emit_capacity_receipt("1" * 32, lambda measured=measured: measured)


def test_capacity_receipt_has_one_concurrent_first_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _request, receipt, _public, _digest = _prepared(tmp_path, monkeypatch)
    calls = 0

    def measured() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return _capacity()

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda index: attestor.emit_capacity_receipt(f"{index + 1:032x}", measured), range(4)))

    assert calls == 1
    assert json.loads(receipt.read_bytes())["payload"]["runtime_instance_nonce"] in {
        f"{index + 1:032x}" for index in range(4)
    }


def test_capacity_private_paths_and_atomic_publication_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "receipt.json"
    attestor._write_once(output, b"first")
    assert output.read_bytes() == b"first"
    with pytest.raises(attestor.CapacityAttestationError, match="^capacity_output_exists$"):
        attestor._write_once(output, b"second")

    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)
    with pytest.raises(attestor.CapacityAttestationError, match="capacity_private_parent_invalid"):
        attestor._write_once(alias / "elsewhere", b"value")

    failed = private / "failed.json"
    real_write = attestor.os.write

    def fail_write(descriptor: int, body: bytes | memoryview) -> int:
        del descriptor, body
        raise OSError("synthetic")

    monkeypatch.setattr(attestor.os, "write", fail_write)
    with pytest.raises(OSError, match="synthetic"):
        attestor._write_once(failed, b"value")
    monkeypatch.setattr(attestor.os, "write", real_write)
    assert not failed.exists()
    residues = list(private.glob(".failed.json.stage-*"))
    assert len(residues) == 1
    assert stat.S_IMODE(residues[0].stat().st_mode) == 0o600


def test_capacity_publication_indeterminate_is_exactly_adoptable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "request.json"
    original_fsync = attestor.os.fsync
    calls = 0

    def fail_postcommit(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic postcommit failure")
        original_fsync(descriptor)

    monkeypatch.setattr(attestor.os, "fsync", fail_postcommit)
    with pytest.raises(attestor.CapacityAttestationError, match="^capacity_publication_indeterminate$"):
        attestor._write_once(output, b"bound request\n")
    monkeypatch.setattr(attestor.os, "fsync", original_fsync)
    assert output.read_bytes() == b"bound request\n"

    attestor._write_once(output, b"bound request\n")
    with pytest.raises(attestor.CapacityAttestationError, match="^capacity_output_exists$"):
        attestor._write_once(output, b"different request\n")


def test_capacity_destination_race_never_replaces_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "request.json"
    original = attestor._rename_noreplace

    def race(parent: int, source: str, destination: str) -> None:
        winner = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent,
        )
        try:
            os.write(winner, b"winner\n")
            os.fsync(winner)
        finally:
            os.close(winner)
        original(parent, source, destination)

    monkeypatch.setattr(attestor, "_rename_noreplace", race)
    with pytest.raises(attestor.CapacityAttestationError, match="^capacity_output_exists$"):
        attestor._write_once(output, b"candidate\n")
    assert output.read_bytes() == b"winner\n"


def test_capacity_checkpoint_style_noreplace_fallback_requires_commit_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "request.json"

    def unsupported(_parent: int, _source: str, _destination: str) -> None:
        raise attestor.CapacityAttestationError("capacity_noreplace_unsupported")

    monkeypatch.setattr(attestor, "_rename_noreplace", unsupported)
    attestor._write_once(output, b"bound request\n")

    parent, _identity = attestor._open_private_directory(private)
    try:
        assert attestor._read_committed_at(parent, output.name) == b"bound request\n"
    finally:
        os.close(parent)
    assert output.with_name(f".{output.name}{attestor.COMMIT_SUFFIX}").is_file()


def test_backend_capacity_measurement_binds_effective_cgroup_limits() -> None:
    observed: list[str] = []
    instance = object.__new__(backend.VacliVMVMBackend)

    def run(command: str, *, timeout: int) -> SimpleNamespace:
        observed.append(command)
        assert timeout == 30
        return SimpleNamespace(returncode=0, stdout=f"32\t{36 * 1024**3}\t{105 * 1024**3}\n".encode())

    instance._ssh_call_raw = run
    assert instance._measure_outer_capacity() == _capacity()
    command = observed[0]
    assert "cpuset.cpus.effective" in command
    assert "cpu.max" in command
    assert "quota / period" in command
    assert "memory.max" in command
    assert "df -PB1" in command


def test_signing_key_path_is_consumed_before_vm_or_container_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = tmp_path / "host-only-key.pem"
    monkeypatch.setenv("VMVM_CAPACITY_PRIVATE_KEY", str(key))
    monkeypatch.setattr(attestor, "_SIGNING_KEY_PATH", None)

    attestor.consume_capacity_signing_key()

    assert "VMVM_CAPACITY_PRIVATE_KEY" not in os.environ
    assert str(key) not in inspect.getsource(backend.VacliVMVMBackend._start_container)
    instance = object.__new__(backend.VacliVMVMBackend)
    instance.config = SimpleNamespace(secret="unrelated")
    instance._container_id = None
    instance._ssh_port = 1
    instance._vacli_log = Path("/tmp/nonsecret")
    instance._control_path = "/tmp/nonsecret-control"
    assert str(key) not in json.dumps(instance.get_debugging_info(), default=str)
