from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import signal
import socket
import stat
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PROBE_PATH = HERE / "probe_vmvm_owner_lifecycle_v4.py"
LAUNCHER_PATH = HERE / "launch_vmvm_owner_lifecycle_v4.py"
FINALIZER_PATH = HERE / "finalize_vmvm_owner_lifecycle_v4.py"
WRAPPER_PATH = HERE / "run_vmvm_owner_lifecycle_v4.sbatch"
BACKEND_PATH = ROOT / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py"
FROZEN_SOURCE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-9d7841b36")
SOURCE_REVISION = "9d7841b36bafcd58769041925b00deba7c25ffca"
SOURCE_TREE = "7f4027723ab036b888b1baee8c0d51c962653f68"
BACKEND_SHA256 = "13ba697362a00f8ee8112d2459a7d1c62e5f6b4c02a84c33ac662a7b0ac9f60a"
VERIFIERS_REVISION = "615b1a30ee3d23cf8d835b64174229c19da887bc"
VACLI_SHA256 = "8be49a764bd0fac1a3ef2bef053ced556d18397d44642660eb8a2d22a7c235b3"


def load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe() -> Any:
    return load_module("owner_lifecycle_probe", PROBE_PATH)


@pytest.fixture(scope="module")
def launcher() -> Any:
    return load_module("owner_lifecycle_launcher", LAUNCHER_PATH)


@pytest.fixture(scope="module")
def finalizer() -> Any:
    return load_module("owner_lifecycle_finalizer", FINALIZER_PATH)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_source_and_runtime_bindings(probe: Any, launcher: Any, finalizer: Any) -> None:
    for module in (probe, launcher, finalizer):
        assert module.SOURCE_REVISION == SOURCE_REVISION
        assert module.SOURCE_TREE == SOURCE_TREE
        assert module.VERIFIERS_REVISION == VERIFIERS_REVISION
        assert module.BACKEND_SHA256 == BACKEND_SHA256
        assert module.BACKEND_RELATIVE_PATH == "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py"
        assert module.VACLI_SHA256 == VACLI_SHA256
        assert str(module.VACLI_RESOLVED).endswith("/infra/public/fbpkgs/x86_64/vacli/794/vacli")
    assert launcher.SOURCE_ROOT == FROZEN_SOURCE
    assert finalizer.SOURCE_ROOT == FROZEN_SOURCE
    assert probe.EXPECTED_SOURCE_ROOT == FROZEN_SOURCE
    assert digest(BACKEND_PATH) == BACKEND_SHA256
    frozen_backend = FROZEN_SOURCE / probe.BACKEND_RELATIVE_PATH
    assert stat.S_IMODE(frozen_backend.stat().st_mode) == 0o444
    assert digest(frozen_backend) == BACKEND_SHA256
    source_tree = subprocess.run(
        ["git", "rev-parse", f"{SOURCE_REVISION}^{{tree}}"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    gitlink = subprocess.run(
        ["git", "rev-parse", f"{SOURCE_REVISION}:deps/verifiers"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", SOURCE_REVISION, "HEAD"],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )
    assert (source_tree, gitlink) == (SOURCE_TREE, VERIFIERS_REVISION)
    frozen = tuple(
        subprocess.run(
            ["git", "rev-parse", expression],
            cwd=FROZEN_SOURCE,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for expression in ("HEAD", "HEAD^{tree}", "HEAD:deps/verifiers")
    )
    assert frozen == (SOURCE_REVISION, SOURCE_TREE, VERIFIERS_REVISION)


def test_vacli_alias_and_resolved_binary_are_identical(probe: Any) -> None:
    alias = Path("/public/fbpkgs/x86_64/vacli/stable/vacli")
    resolved = Path(probe.VACLI_RESOLVED)
    assert alias.resolve(strict=True) == resolved
    assert alias.stat().st_ino == resolved.stat().st_ino
    assert digest(resolved) == VACLI_SHA256


def test_exact_six_entry_bundle_and_no_cache() -> None:
    assert {path.name for path in HERE.iterdir()} == {
        "README.md",
        "finalize_vmvm_owner_lifecycle_v4.py",
        "launch_vmvm_owner_lifecycle_v4.py",
        "probe_vmvm_owner_lifecycle_v4.py",
        "run_vmvm_owner_lifecycle_v4.sbatch",
        "test_vmvm_owner_lifecycle_v4.py",
    }


def test_no_stale_matrix_or_task_access() -> None:
    combined = "\n".join(path.read_text() for path in (PROBE_PATH, LAUNCHER_PATH, FINALIZER_PATH, WRAPPER_PATH))
    for stale in (
        "MODE_ORDERS",
        "x2p_mode",
        "pair_index",
        "same_thread_raw",
        "runtime_contract",
        "vmvm_task_free",
        "DIAG_VMVM_SHA256",
        "preflight_only",
        "stage_results",
    ):
        assert stale not in combined
    for forbidden in ("datasets/", "task_id", "OPENAI_API_KEY"):
        assert forbidden not in combined


def test_protocol_is_one_cell_and_exact(probe: Any, launcher: Any, finalizer: Any) -> None:
    expected = {
        "cell_count": 1,
        "diagnostic_only": True,
        "directory_identity_policy": probe.DIRECTORY_IDENTITY_POLICY,
        "external_completion_handoff": "compute_local_cleanup_attestation_v1",
        "fixed_commands": 2,
        "forced_recoveries": 1,
        "lease_attempt_limit": 1,
        "production_authorized": False,
        "renewer_survival_seconds": 2.0,
        "stage_timeout_seconds": 1800,
    }
    assert probe.DIAGNOSTIC_PROTOCOL == expected
    assert launcher.DIAGNOSTIC_PROTOCOL == expected
    assert finalizer.DIAGNOSTIC_PROTOCOL == expected


def test_timeout_arithmetic_and_scheduler_signal(probe: Any, launcher: Any, finalizer: Any) -> None:
    for module in (probe, launcher, finalizer):
        assert module.STAGE_TIMEOUT_SECONDS < module.SUPERVISOR_TIMEOUT_SECONDS
        guarded_seconds = (
            module.WRAPPER_GATE_TIMEOUT_SECONDS
            + module.ADMISSION_TIMEOUT_SECONDS
            + module.SUPERVISOR_TIMEOUT_SECONDS
            + module.TIMEOUT_KILL_GRACE_COUNT * module.TIMEOUT_KILL_GRACE_SECONDS
            + module.FINALIZATION_BUDGET_SECONDS
        )
        assert guarded_seconds == 4_440
        assert module.JOB_SECONDS - module.SIGNAL_LEAD_SECONDS - guarded_seconds == 360
    command = launcher._sbatch_command("vmvm-owner-v4-" + "a" * 24, Path("/tmp/environment.bin"))
    assert "--time=01:30:00" in command
    assert "--signal=B:TERM@600" in command
    wrapper = WRAPPER_PATH.read_text()
    assert "ADMISSION_TIMEOUT_SECONDS=300 SUPERVISOR_TIMEOUT_SECONDS=2700" in wrapper
    assert "TIMEOUT_KILL_GRACE_SECONDS=120 TIMEOUT_KILL_GRACE_COUNT=2" in wrapper
    assert "+ TIMEOUT_KILL_GRACE_COUNT * TIMEOUT_KILL_GRACE_SECONDS" in wrapper
    assert '--kill-after="$TIMEOUT_KILL_GRACE_SECONDS"' in wrapper
    for path in (PROBE_PATH, LAUNCHER_PATH, FINALIZER_PATH):
        source = path.read_text()
        assert "+ TIMEOUT_KILL_GRACE_COUNT * TIMEOUT_KILL_GRACE_SECONDS" in source
        assert '"timeout_kill_grace_count": TIMEOUT_KILL_GRACE_COUNT' in source
    assert "coproc DIAGNOSTIC_RUN" in wrapper
    assert 'kill -TERM -- "-$active_probe_pid"' in wrapper


def test_backend_is_descriptor_verified_in_every_component() -> None:
    launcher = LAUNCHER_PATH.read_text()
    probe = PROBE_PATH.read_text()
    finalizer = FINALIZER_PATH.read_text()
    wrapper = WRAPPER_PATH.read_text()
    assert 'os.open("backend.py", os.O_RDONLY | os.O_NOFOLLOW' in probe
    assert '"environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"' in launcher
    assert '"backend.py",\n                    mode=0o444' in launcher
    assert "backend_record = tracked.get(BACKEND_RELATIVE_PATH)" in finalizer
    assert 'os.open("backend.py", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC' in wrapper
    assert "_vacli/*.py" not in "\n".join((launcher, probe, finalizer, wrapper))


def test_probe_verifies_real_bound_backend(probe: Any) -> None:
    descriptor = os.open(FROZEN_SOURCE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        probe._verify_backend_file(descriptor)
    finally:
        os.close(descriptor)


def test_all_python_components_attest_frozen_source(
    probe: Any,
    launcher: Any,
    finalizer: Any,
) -> None:
    launcher.validate_source()
    descriptor = os.open(FROZEN_SOURCE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        probe_records = probe.attest_imported_source(descriptor)
        finalizer_records = finalizer._attest_imported_source(descriptor)
    finally:
        os.close(descriptor)
    assert probe_records.keys() == finalizer_records.keys()
    assert probe.BACKEND_RELATIVE_PATH in probe_records


def test_wrapper_backend_validator_runs_against_frozen_source() -> None:
    wrapper = WRAPPER_PATH.read_text()
    program = wrapper.split("readonly BACKEND_VALIDATOR_PROGRAM='\n", 1)[1].split("\n'\n\nvalidate_backend()", 1)[0]
    descriptor = os.open(FROZEN_SOURCE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        completed = subprocess.run(
            ["/usr/bin/python3", "-I", "-S", "-B", "-c", program, str(descriptor), BACKEND_SHA256],
            pass_fds=(descriptor,),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        os.close(descriptor)
    assert completed.returncode == 0
    assert not completed.stdout and not completed.stderr


def test_execution_snapshot_is_descriptor_relative_and_inventory_stable(
    probe: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    site = tmp_path / "site"
    scratch = tmp_path / "scratch"
    source.mkdir(mode=0o700)
    site.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)
    (site / "package").mkdir(mode=0o700)
    (site / "package/module.py").write_bytes(b"site-data\n")
    os.chmod(site / "package/module.py", 0o600)
    source_raw = b"source-data\n"
    source_records = {"package/source.py": ("100644", "a" * 40)}
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    site_fd = os.open(site, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    scratch_fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    expected_site = probe.directory_manifest(site_fd, expected_owner_uid=os.getuid())
    monkeypatch.setattr(probe, "attest_imported_source", lambda _descriptor: source_records)

    def read_blob(_descriptor: int, relative: str, git_mode: str, object_id: str) -> bytes:
        assert (relative, git_mode, object_id) == ("package/source.py", "100644", "a" * 40)
        return source_raw

    monkeypatch.setattr(probe, "_read_attested_source_blob", read_blob)
    original_open_anchored = probe.open_anchored_directory

    def reject_procfd_reopen(path: Path, *, code: str = "source_binding_invalid") -> int:
        assert not str(path).startswith("/proc/self/fd/")
        return original_open_anchored(path, code=code)

    monkeypatch.setattr(probe, "open_anchored_directory", reject_procfd_reopen)
    source_snapshot_fd = -1
    site_snapshot_fd = -1
    try:
        source_snapshot_fd, site_snapshot_fd, source_inventory, site_inventory = probe.create_execution_snapshot(
            source_fd,
            site_fd,
            scratch_fd,
            expected_site,
        )
        assert os.path.samefile(
            f"/proc/self/fd/{source_snapshot_fd}",
            scratch / "sealed-inputs/source",
        )
        assert os.path.samefile(
            f"/proc/self/fd/{site_snapshot_fd}",
            scratch / "sealed-inputs/site",
        )
        with pytest.raises(probe.DiagnosticError, match="site_binding_invalid"):
            original_open_anchored(
                Path(f"/proc/self/fd/{scratch_fd}/sealed-inputs/site"),
                code="site_binding_invalid",
            )
        assert source_inventory == probe.directory_manifest(source_snapshot_fd, expected_owner_uid=os.getuid())
        assert site_inventory == probe.directory_manifest(site_snapshot_fd, expected_owner_uid=os.getuid())
        assert source_inventory["entry_count"] == 2
        assert site_inventory["entry_count"] == expected_site["entry_count"]
        assert site_inventory["manifest_sha256"] != expected_site["manifest_sha256"]
        assert stat.S_IMODE(os.fstat(source_snapshot_fd).st_mode) == 0o500
        assert stat.S_IMODE(os.fstat(site_snapshot_fd).st_mode) == 0o500
        assert stat.S_IMODE((scratch / "sealed-inputs/source/package/source.py").stat().st_mode) == 0o400
        assert stat.S_IMODE((scratch / "sealed-inputs/site/package/module.py").stat().st_mode) == 0o400
    finally:
        for descriptor in (source_snapshot_fd, site_snapshot_fd, scratch_fd, site_fd, source_fd):
            if descriptor >= 0:
                os.close(descriptor)
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o700)
    (unsafe / "link").symlink_to(outside)
    unsafe_fd = os.open(unsafe, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with pytest.raises(probe.DiagnosticError, match="site_binding_invalid"):
            probe._seal_tree(unsafe_fd, code="site_binding_invalid")
    finally:
        os.close(unsafe_fd)
    assert outside.read_text() == "preserve"


def test_wrapper_compute_cleanup_validator_binds_certificate_identity(tmp_path: Path) -> None:
    wrapper = WRAPPER_PATH.read_text()
    program = wrapper.split("readonly COMPUTE_CLEANUP_VALIDATOR_PROGRAM='\n", 1)[1].split(
        "\n'\n\nvalidate_compute_cleanup_attestation()", 1
    )[0]
    output_parent = tmp_path / "outputs"
    output_parent.mkdir()
    output = output_parent / "candidate"
    output.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    info = scratch.stat()
    identity = {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "owner_uid": info.st_uid,
    }
    certificate = {
        "execution_inputs": {
            "scratch_cleanup_attestation": {
                "path_sha256": hashlib.sha256(os.fsencode(scratch)).hexdigest(),
                "retained_empty": True,
                "root_identity_sha256": hashlib.sha256(
                    json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "scope": "compute_node_local",
                "verified": True,
            }
        }
    }
    certificate_path = output / "diagnostic_certificate.json"
    certificate_path.write_bytes(json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    os.chmod(certificate_path, 0o400)
    parent_fd = os.open(output_parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        completed = subprocess.run(
            ["/usr/bin/python3", "-I", "-S", "-B", "-c", program, str(parent_fd), "candidate", str(scratch)],
            pass_fds=(parent_fd,),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        os.close(parent_fd)
    assert completed.returncode == 0
    assert not completed.stdout and not completed.stderr
    (scratch / "unexpected").write_text("retain")
    parent_fd = os.open(output_parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        rejected = subprocess.run(
            ["/usr/bin/python3", "-I", "-S", "-B", "-c", program, str(parent_fd), "candidate", str(scratch)],
            pass_fds=(parent_fd,),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        os.close(parent_fd)
    assert rejected.returncode != 0
    assert (scratch / "unexpected").read_text() == "retain"


def test_cross_host_finalizer_consumes_attestation_without_reopening_compute_tmp(
    probe: Any,
    launcher: Any,
    finalizer: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    expected_scratch = Path("/tmp/tianhaowu-vmvm-owner-lifecycle-9d7841b36-v4-scratch")
    assert expected_scratch.parent == Path("/tmp")
    assert probe.EXPECTED_SCRATCH_ROOT == finalizer.SCRATCH_ROOT == expected_scratch
    expected_failure_receipt = Path(f"{launcher.OUTPUT_ROOT}.probe-failure.json")
    assert (
        probe.EXPECTED_PROBE_FAILURE_RECEIPT
        == launcher.PROBE_FAILURE_RECEIPT
        == finalizer.PROBE_FAILURE_RECEIPT
        == expected_failure_receipt
    )

    compute_scratch = {"device": 101, "inode": 2001, "mode": 0o700, "owner_uid": os.getuid()}
    compute_output = {"device": 101, "inode": 2002, "mode": 0o500, "owner_uid": os.getuid()}
    finalizer_output = {**compute_output, "device": 202}
    assert compute_output != finalizer_output
    for module in (probe, launcher, finalizer):
        assert module.portable_directory_identity(compute_output) == module.portable_directory_identity(
            finalizer_output
        )

    attestation = {
        "path_sha256": hashlib.sha256(os.fsencode(expected_scratch)).hexdigest(),
        "retained_empty": True,
        "root_identity_sha256": hashlib.sha256(
            json.dumps(compute_scratch, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "scope": "compute_node_local",
        "verified": True,
    }
    assert finalizer.validate_scratch_cleanup_attestation(attestation) == attestation

    probe_source = PROBE_PATH.read_text()
    finalizer_source = FINALIZER_PATH.read_text()
    wrapper_source = WRAPPER_PATH.read_text()
    assert "scratch_parent_fd = open_anchored_directory(" in probe_source
    assert "args.scratch_root.parent" in probe_source
    assert "def inherited_bound_directory(" not in probe_source
    assert probe_source.count("inherited_portable_bound_directory(") >= 7
    probe_request = probe_source.split("completion_request = {", 1)[1].split("completion_payload =", 1)[0]
    finalizer_request = finalizer_source.split("if request != {", 1)[1].split("}:\n", 1)[0]
    for request_source in (probe_request, finalizer_request):
        assert '"output_root_portable_identity"' in request_source
        assert '"scratch_cleanup_attestation"' in request_source
        assert '"output_root_identity"' not in request_source
        assert '"scratch_root_identity"' not in request_source
    assert 'get("scratch_cleanup_attestation")' in wrapper_source
    assert "_open_anchored_directory(SCRATCH_ROOT)" not in finalizer_source
    assert "os.stat(PROBE_FAILURE_RECEIPT.name" in finalizer_source
    finalizer_host_scratch = tmp_path / "other-host" / expected_scratch.name
    assert not finalizer_host_scratch.exists()
    monkeypatch.setattr(finalizer, "SCRATCH_ROOT", finalizer_host_scratch)
    remote_attestation = {
        **attestation,
        "path_sha256": hashlib.sha256(os.fsencode(finalizer_host_scratch)).hexdigest(),
    }
    assert finalizer.validate_scratch_cleanup_attestation(remote_attestation) == remote_attestation
    assert not finalizer_host_scratch.exists()
    changed = dict(remote_attestation)
    changed["path_sha256"] = "0" * 64
    with pytest.raises(finalizer.FinalizeError, match="scratch_cleanup_unverified"):
        finalizer.validate_scratch_cleanup_attestation(changed)


class _FakeLease:
    instances: list[_FakeLease] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.proc: subprocess.Popen[bytes] | None = None
        self.session_identity_sha256 = "a" * 64
        self.lease_response = '{"sessionId":"fixed","auth_token":"redacted"}'
        self._next_port = 10022
        self.cleaned = False
        self.__class__.instances.append(self)

    @staticmethod
    def _spawn() -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            ["/usr/bin/sleep", "300"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    @staticmethod
    def _reap(process: subprocess.Popen[bytes], process_signal: signal.Signals) -> None:
        if process.poll() is None:
            os.killpg(process.pid, process_signal)
            process.wait(timeout=5)

    def start(self) -> None:
        self.proc = self._spawn()

    def wait_for_tunnel(self) -> int:
        assert self.proc is not None and self.proc.poll() is None
        return self._next_port

    def restart_tunnel(self) -> int:
        assert self.proc is not None
        self._reap(self.proc, signal.SIGKILL)
        self.proc = self._spawn()
        self._next_port += 1
        return self.wait_for_tunnel()

    def cleanup(self) -> None:
        if self.cleaned:
            return
        self.cleaned = True
        if self.proc is not None:
            self._reap(self.proc, signal.SIGTERM)


class _FakeBackendBase:
    lease_type: type[_FakeLease]
    module: Any
    last_instance: _FakeBackendBase | None = None

    def __init__(self, _config: object) -> None:
        self.construct_thread = threading.current_thread()
        self.command_threads: list[threading.Thread] = []
        self.recovery_thread: threading.Thread | None = None
        self._lease = self.lease_type("tenant", Path("unused"))
        self._lease.start()
        self._ssh_port = self._lease.wait_for_tunnel()
        self._container_id = "fixed"
        self.__class__.last_instance = self

    def run_bash(self, command: str, _timeout: float) -> dict[str, object]:
        self.command_threads.append(threading.current_thread())
        expected = {
            "printf owner-lifecycle-first": "owner-lifecycle-first",
            "printf owner-lifecycle-second": "owner-lifecycle-second",
        }
        return {"error_type": "none", "exit_code": 0, "output": expected[command], "status": "success"}

    def restart_session(self) -> bool:
        self.recovery_thread = threading.current_thread()
        try:
            self.module._wait_for_sshd(self._ssh_port)
        except OSError:
            new_port = self._lease.restart_tunnel()
            self.module._wait_for_sshd(new_port)
            self._ssh_port = new_port
            return True
        return False

    def destroy(self) -> None:
        self._lease.cleanup()


def test_full_owner_lifecycle_uses_short_lived_threads_and_no_arg_resume(
    probe: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _FakeLease.instances.clear()
    module = SimpleNamespace(_wait_for_sshd=lambda _port, *_args, **_kwargs: None)
    journal_fd = os.open(
        tmp_path / "renewer-journal.jsonl",
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_APPEND,
        0o600,
    )
    audit = probe.LeaseAudit(journal_fd)
    audit.phase("worker_started")
    tracked_lease = audit.tracking_lease_type(_FakeLease)

    class FakeBackend(_FakeBackendBase):
        lease_type = tracked_lease

    FakeBackend.module = module
    tracked_backend = audit.tracking_backend_type(FakeBackend)
    monkeypatch.setattr(probe, "RENEWER_SURVIVAL_SECONDS", 0.05)
    passed, failure, cleanup = probe.execute_owner_lifecycle(
        backend_module=module,
        backend_type=tracked_backend,
        config=object(),
        audit=audit,
    )
    assert (passed, failure, cleanup) == (True, None, True)
    clock = [time.monotonic()]

    def monotonic() -> float:
        return clock[0]

    def sleeper(seconds: float) -> None:
        clock[0] += seconds

    assert audit.verify_releases(monotonic=monotonic, sleeper=sleeper)
    metadata = audit.metadata(True)
    result = probe._result_payload(
        state="passed",
        failure=None,
        cleanup_complete=True,
        elapsed_seconds=1,
        lifecycle_metadata=metadata,
    )
    probe.validate_stage_result(result)
    instance = tracked_backend.last_instance
    assert instance is not None
    assert instance.construct_thread is not threading.current_thread()
    assert instance.recovery_thread is not None and instance.recovery_thread is not threading.current_thread()
    assert len(instance.command_threads) == 2
    assert all(thread is not threading.current_thread() for thread in instance.command_threads)
    assert metadata["phase_counts"] == {
        "backend_ready": 1,
        "cleanup_called": 1,
        "command_started": 2,
        "command_succeeded": 2,
        "initial_renewer_survived": 1,
        "lease_start": 1,
        "recovery_started": 1,
        "recovery_succeeded": 1,
        "recovery_failed": 0,
        "release_verified": 1,
        "replacement_renewer_survived": 1,
        "tunnel_ready": 2,
        "worker_started": 1,
    }
    assert metadata["renewer_processes"] == 2
    assert metadata["transport_recovery_attempts"] == 1
    assert metadata["process_identity_distinct"] is True
    observed_processes = [item["process"] for record in audit._leases.values() for item in record["processes"]]
    assert len(observed_processes) == 2
    assert all(process.poll() is not None for process in observed_processes)
    assert len(probe._journal_process_identities(journal_fd, require_complete=True)) == 2
    os.close(journal_fd)
    for lease in _FakeLease.instances:
        assert lease.proc is not None and lease.proc.poll() is not None


def passed_result(probe: Any) -> dict[str, object]:
    phases = {
        "backend_ready": 1,
        "cleanup_called": 1,
        "command_started": 2,
        "command_succeeded": 2,
        "initial_renewer_survived": 1,
        "lease_start": 1,
        "recovery_started": 1,
        "recovery_succeeded": 1,
        "recovery_failed": 0,
        "release_verified": 1,
        "replacement_renewer_survived": 1,
        "tunnel_ready": 2,
        "worker_started": 1,
    }
    return probe._result_payload(
        state="passed",
        failure=None,
        cleanup_complete=True,
        elapsed_seconds=1,
        lifecycle_metadata={
            "last_phase": "release_verified",
            "lease_attempt_limit": 1,
            "lease_attempts": 1,
            "phase_counts": phases,
            "process_identity_distinct": True,
            "release_grace_seconds": 5,
            "release_method": "renewer_absent_for_lease_ttl",
            "release_verified": True,
            "renewer_processes": 2,
            "transport_recovery_attempt_limit": 1,
            "transport_recovery_attempts": 1,
        },
    )


def test_exact_pass_schema_and_aggregate(probe: Any, finalizer: Any) -> None:
    result = passed_result(probe)
    probe.validate_stage_result(result)
    finalizer._validate_stage_result(result)
    expected = {
        "cell_count": 1,
        "lifecycle_totals": {
            "lease_attempts": 1,
            "phase_counts": result["lifecycle_metadata"]["phase_counts"],
            "renewer_processes": 2,
            "transport_recovery_attempts": 1,
        },
        "result_counts": {"passed": 1},
        "safe_failure_counts": {},
    }
    assert probe.summarize_cell_results([result]) == expected
    assert finalizer.summarize_cell_results([result]) == expected


def test_exact_certificate_schema_round_trips_finalizer(probe: Any, finalizer: Any) -> None:
    result = passed_result(probe)
    summary = probe.summarize_cell_results([result])
    inventory = {
        "entry_count": 1,
        "manifest_sha256": "a" * 64,
        "owner_uid": os.getuid(),
        "total_bytes": 1,
    }
    execution_inputs = {
        "authorized_site": inventory,
        "scratch_cleanup_attestation": {
            "path_sha256": hashlib.sha256(os.fsencode(probe.EXPECTED_SCRATCH_ROOT)).hexdigest(),
            "retained_empty": True,
            "root_identity_sha256": "9" * 64,
            "scope": "compute_node_local",
            "verified": True,
        },
        "site_snapshot": inventory,
        "source_snapshot": inventory,
    }
    certificate = {
        "artifact_type": "vmvm_owner_lifecycle_diagnostic_certificate_v4",
        "authorization_file_sha256": "b" * 64,
        "authorization_sha256": "c" * 64,
        "automatic_remediation": False,
        "cell_results": [result],
        "diagnostic_only": True,
        "environment_sha256": "d" * 64,
        "execution_inputs": execution_inputs,
        "image": "python:3.12-slim",
        "job": {
            "cluster": "fair-cw-use2-3",
            "job_id": "1",
            "job_name": "vmvm-owner-v4-" + "e" * 24,
        },
        "job_authorization_sha256": "f" * 64,
        "model_endpoint_accessed": False,
        "production_authorized": False,
        "protocol": probe.DIAGNOSTIC_PROTOCOL,
        "result_counts": {"passed": 1},
        "safe_failure_counts": {},
        "schema_version": 1,
        "source": {
            "backend_path": probe.BACKEND_RELATIVE_PATH,
            "backend_sha256": BACKEND_SHA256,
            "pydantic_config_revision": probe.PYDANTIC_CONFIG_REVISION,
            "renderers_revision": probe.RENDERERS_REVISION,
            "revision": SOURCE_REVISION,
            "tree": SOURCE_TREE,
            "verifiers_revision": VERIFIERS_REVISION,
        },
        "submission_receipt_sha256": "1" * 64,
        "summary": summary,
        "task_data_accessed": False,
    }
    finalizer.validate_certificate(
        certificate,
        expected_execution_inputs={
            name: execution_inputs[name] for name in ("authorized_site", "site_snapshot", "source_snapshot")
        },
    )
    certificate["unexpected"] = True
    with pytest.raises(finalizer.FinalizeError, match="certificate_invalid"):
        finalizer.validate_certificate(
            certificate,
            expected_execution_inputs={
                name: execution_inputs[name] for name in ("authorized_site", "site_snapshot", "source_snapshot")
            },
        )


def test_exact_counts_reject_extra_recovery_or_tunnel(probe: Any) -> None:
    for phase in ("recovery_started", "recovery_succeeded", "tunnel_ready"):
        result = json.loads(json.dumps(passed_result(probe)))
        result["lifecycle_metadata"]["phase_counts"][phase] += 1
        with pytest.raises(probe.DiagnosticError, match="stage_result_invalid"):
            probe.validate_stage_result(result)
    failed = probe._result_payload(
        state="failed",
        failure="child_timeout",
        cleanup_complete=False,
        elapsed_seconds=1,
        lifecycle_metadata={
            **probe._empty_lifecycle_metadata(False),
            "last_phase": "worker_started",
        },
    )
    probe.validate_failure_result_for_receipt(failed)
    assert (failed["failure_class"], failed["cleanup_complete"]) == ("child_timeout", False)


def test_continuous_external_release_rejects_reappearance(probe: Any, monkeypatch: Any, tmp_path: Path) -> None:
    events = [
        {"artifact_type": "vmvm_owner_renewer_journal_event_v4", "event": "audit_started", "sequence": 0},
        {
            "artifact_type": "vmvm_owner_renewer_journal_event_v4",
            "event": "operation_started",
            "lease_id": 1,
            "operation": "start",
            "operation_id": 0,
            "sequence": 1,
        },
        {
            "artifact_type": "vmvm_owner_renewer_journal_event_v4",
            "event": "renewer_observed",
            "lease_id": 1,
            "operation": "start",
            "operation_id": 0,
            "pid": 12345,
            "process_group": 12345,
            "running": True,
            "sequence": 2,
            "start_ticks": 77,
        },
        {
            "artifact_type": "vmvm_owner_renewer_journal_event_v4",
            "event": "operation_finished",
            "lease_id": 1,
            "operation": "start",
            "operation_id": 0,
            "outcome": "process_observed",
            "sequence": 3,
        },
        {
            "artifact_type": "vmvm_owner_renewer_journal_event_v4",
            "event": "audit_complete",
            "renewer_processes": 1,
            "sequence": 4,
        },
    ]
    journal = tmp_path / "journal"
    journal.write_bytes(b"".join(probe.canonical_json(event) + b"\n" for event in events))
    descriptor = os.open(journal, os.O_RDONLY)
    clock = [0.0]
    checks = [True, True, False]
    monkeypatch.setattr(probe, "_process_identity_absent", lambda *_args: checks.pop(0) if checks else False)
    monkeypatch.setattr(probe, "_process_group_absent", lambda _group: True)
    try:
        assert not probe.verify_external_renewer_release(
            descriptor,
            54321,
            require_complete=True,
            monotonic=lambda: clock[0],
            sleeper=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        )
    finally:
        os.close(descriptor)


def test_retained_root_scrub_is_descriptor_relative(probe: Any, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "nested").mkdir(mode=0o700)
    (root / "nested/file").write_text("owned")
    os.chmod(root / "nested/file", 0o600)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = probe.descriptor_identity(root_fd)
    try:
        assert probe._scrub_bound_root_verified(parent_fd, "root", root_fd, identity)
        assert probe.descriptor_identity(root_fd) == identity
        assert list(root.iterdir()) == []
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def test_retained_root_scrub_removes_real_unix_socket(probe: Any, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    nested = root / "nested"
    nested.mkdir(mode=0o700)
    (nested / "vacli.log").write_text("owned")
    socket_path = nested / "control.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = probe.descriptor_identity(root_fd)
    try:
        assert stat.S_ISSOCK(os.lstat(socket_path).st_mode)
        assert probe._scrub_bound_root_verified(parent_fd, "root", root_fd, identity)
        assert os.listdir(root_fd) == []
        assert stat.S_IMODE(os.fstat(root_fd).st_mode) == 0o700
    finally:
        os.close(root_fd)
        os.close(parent_fd)
        server.close()


def test_bound_tree_removal_removes_real_unix_socket(probe: Any, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    socket_path = root / "control.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = probe.descriptor_identity(root_fd)
    try:
        assert probe._remove_bound_tree_verified(parent_fd, "root", root_fd, identity)
        assert not root.exists()
        assert os.fstat(root_fd).st_nlink == 0
    finally:
        os.close(root_fd)
        os.close(parent_fd)
        server.close()


def test_socket_cleanup_rejects_path_replacement(
    probe: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    socket_path = root / "control.sock"
    original_path = root / "original.sock"
    original = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    original.bind(str(socket_path))
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = probe.descriptor_identity(root_fd)
    original_detach = probe._detach_entry_verified
    swapped = False

    def swap_then_detach(*args: Any, **kwargs: Any) -> str | None:
        nonlocal swapped
        if not swapped and args[1] == "control.sock":
            socket_path.rename(original_path)
            replacement.bind(str(socket_path))
            swapped = True
        return original_detach(*args, **kwargs)

    monkeypatch.setattr(probe, "_detach_entry_verified", swap_then_detach)
    try:
        assert not probe._scrub_bound_root_verified(parent_fd, "root", root_fd, identity)
        assert swapped
        assert stat.S_ISSOCK(os.lstat(original_path).st_mode)
        assert stat.S_ISSOCK(os.lstat(socket_path).st_mode)
    finally:
        os.close(root_fd)
        os.close(parent_fd)
        original.close()
        replacement.close()


@pytest.mark.parametrize(
    "operation_name",
    ("_scrub_bound_root_verified", "_remove_bound_tree_verified"),
)
def test_cleanup_rejects_fifo(
    probe: Any,
    tmp_path: Path,
    operation_name: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    fifo = root / "control.fifo"
    os.mkfifo(fifo, mode=0o600)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = probe.descriptor_identity(root_fd)
    try:
        operation = getattr(probe, operation_name)
        assert not operation(parent_fd, "root", root_fd, identity)
        assert stat.S_ISFIFO(os.lstat(fifo).st_mode)
    finally:
        os.close(root_fd)
        os.close(parent_fd)


@pytest.mark.parametrize(
    "operation_name",
    ("_scrub_bound_root_verified", "_remove_bound_tree_verified"),
)
def test_cleanup_rejects_hardlinked_regular_file(
    probe: Any,
    tmp_path: Path,
    operation_name: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    owned = root / "vacli.log"
    owned.write_text("owned")
    outside_link = tmp_path / "outside-link"
    os.link(owned, outside_link)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = probe.descriptor_identity(root_fd)
    try:
        operation = getattr(probe, operation_name)
        assert not operation(parent_fd, "root", root_fd, identity)
        assert owned.read_text() == "owned"
        assert os.stat(owned).st_ino == os.stat(outside_link).st_ino
        assert os.stat(owned).st_nlink == 2
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def test_retained_root_scrub_preserves_unrelated_replacement(probe: Any, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "owned").write_text("owned")
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = probe.descriptor_identity(root_fd)
    moved = tmp_path / "moved"
    root.rename(moved)
    root.mkdir(mode=0o700)
    (root / "unrelated").write_text("preserve")
    try:
        assert not probe._scrub_bound_root_verified(parent_fd, "root", root_fd, identity)
        assert (root / "unrelated").read_text() == "preserve"
        assert (moved / "owned").read_text() == "owned"
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def test_retained_root_scrub_recovers_partially_sealed_root(probe: Any, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    (root / "partial").write_text("candidate")
    os.chmod(root / "partial", 0o400)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    expected = probe.descriptor_identity(root_fd)
    os.fchmod(root_fd, 0o500)
    try:
        assert probe._scrub_bound_root_verified(parent_fd, "root", root_fd, expected)
        assert not os.listdir(root_fd)
        assert stat.S_IMODE(os.fstat(root_fd).st_mode) == 0o700
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def test_scrub_rejects_symlink_without_following(probe: Any, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    target = tmp_path / "outside"
    target.write_text("preserve")
    (root / "link").symlink_to(target)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity = probe.descriptor_identity(root_fd)
    try:
        assert not probe._scrub_bound_root_verified(parent_fd, "root", root_fd, identity)
        assert target.read_text() == "preserve"
        assert (root / "link").is_symlink()
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def test_wrapper_reaches_admission_and_default_supervisor() -> None:
    text = WRAPPER_PATH.read_text()
    assert 'run_sealed_probe "$ADMISSION_TIMEOUT_SECONDS" --validate-batch' in text
    assert 'run_sealed_probe "$SUPERVISOR_TIMEOUT_SECONDS" \\' in text
    assert '--environment-sha256 "$environment_sha256"' in text
    assert '"cells":1' in text
    assert 'printf \'%s\\n\' "$probe_output" >&"$public_stdout_fd"' in text
    subprocess.run(["bash", "-n", str(WRAPPER_PATH)], check=True)


def test_sealed_wrapper_and_uv_environment_hardening_are_retained() -> None:
    text = WRAPPER_PATH.read_text()
    for required in (
        "os.memfd_create",
        "F_SEAL_EXEC",
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "environment_sha256",
        "UV_RUN_RECURSION_DEPTH",
        "os.execve(uv_path",
        "os.O_NOFOLLOW",
    ):
        assert required in text


def test_outer_binder_seals_wrapper_with_exec_and_reexecutes() -> None:
    text = WRAPPER_PATH.read_text()
    binder = text.split("readonly DIRECTORY_BINDER_PROGRAM='\n", 1)[1].split("\n'\n\nrequired_environment=(", 1)[0]
    binder_without_entrypoint = binder.rsplit("\nmain()\n", 1)[0]
    namespace: dict[str, Any] = {}
    exec(compile(binder_without_entrypoint, "<directory-binder>", "exec"), namespace)
    descriptor = namespace["sealed_wrapper"](b"exit 37\n")
    try:
        required = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE | 0x20
        observed = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
        assert observed & required == required
        assert observed & ~(required | 0x10) == 0
        assert os.readlink(f"/proc/self/fd/{descriptor}") == "/memfd:vmvm-owner-wrapper-v4 (deleted)"
        with pytest.raises(OSError):
            os.pwrite(descriptor, b"x", 0)
        with pytest.raises(OSError):
            os.fchmod(descriptor, 0o400)
        completed = subprocess.run(
            ["/usr/bin/bash", f"/proc/self/fd/{descriptor}"],
            pass_fds=(descriptor,),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert completed.returncode == 37
        assert not completed.stdout and not completed.stderr
    finally:
        os.close(descriptor)


def test_finalizer_is_sealed_and_self_bound(finalizer: Any) -> None:
    text = FINALIZER_PATH.read_text()
    assert "validate_finalizer_execution" in text
    assert "REQUIRED_MEMFD_SEALS" in text
    assert "/memfd:vmvm-owner-finalizer-v4 (deleted)" in text
    assert finalizer.REQUIRED_MEMFD_SEALS & 0x20


def test_output_is_aggregate_only_and_secret_safe() -> None:
    wrapper = WRAPPER_PATH.read_text()
    assert "readonly probe_output_pattern=" in wrapper
    tail = wrapper.split("readonly probe_output_pattern=", 1)[1]
    assert "X2P_ENV" not in tail
    assert "THRIFT_TLS" not in tail
    probe = PROBE_PATH.read_text()
    assert '"task_data_accessed": False' in probe
    assert '"model_endpoint_accessed": False' in probe


def test_public_cli_has_worker_admission_and_supervisor(probe: Any) -> None:
    parser = probe._parser()
    actions = {option for action in parser._actions for option in action.option_strings}
    assert {"--worker", "--validate-batch", "--source-root", "--output-dir"} <= actions
    source = PROBE_PATH.read_text()
    assert "result = execute_worker(" in source
    assert "result = run_supervisor(args)" in source


def test_atomic_probe_failure_receipt_and_wrapper_normalization(probe: Any, tmp_path: Path) -> None:
    wrapper = WRAPPER_PATH.read_text()
    cleanup_program = wrapper.split("readonly FAILURE_CLEANUP_VALIDATOR_PROGRAM='\n", 1)[1].split(
        "\n'\n\nfailure_cleanup_status()", 1
    )[0]

    def cleanup_status(path: Path) -> str:
        return subprocess.run(
            ["/usr/bin/python3", "-I", "-S", "-B", "-c", cleanup_program, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        ).stdout

    local_scratch = tmp_path / "local-scratch"
    assert cleanup_status(local_scratch) == "verified"
    local_scratch.mkdir(mode=0o700)
    assert cleanup_status(local_scratch) == "verified"
    (local_scratch / "retained").write_text("x")
    assert cleanup_status(local_scratch) == "unverified"
    (local_scratch / "retained").unlink()
    local_scratch.rmdir()
    local_scratch.symlink_to(tmp_path)
    assert cleanup_status(local_scratch) == "unverified"

    program = wrapper.split("readonly FAILURE_RECEIPT_WRITER_PROGRAM='\n", 1)[1].split(
        "\n'\n\npublish_probe_failure()", 1
    )[0]
    namespace: dict[str, Any] = {}
    exec(compile(program.rsplit("\nmain()", 1)[0], "<failure-receipt-writer>", "exec"), namespace)
    assert namespace["FAILURES"] == probe.SAFE_FAILURES
    assert probe.SupervisorFailure("not-allowlisted", "invalid").code == "unclassified"
    assert probe.SupervisorFailure("not-allowlisted", "invalid").cleanup_status == "unverified"
    hashes = [character * 64 for character in "abcdef"]
    job_name = "vmvm-owner-v4-" + "7" * 24

    def invoke(parent: Path, target: str, *, source: str = program) -> subprocess.CompletedProcess[bytes]:
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            return subprocess.run(
                [
                    "/usr/bin/python3",
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    source,
                    str(descriptor),
                    target,
                    "backend_tunnel",
                    "verified",
                    *hashes,
                    "123",
                    job_name,
                ],
                pass_fds=(descriptor,),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        finally:
            os.close(descriptor)

    clean = tmp_path / "clean"
    clean.mkdir(mode=0o700)
    completed = invoke(clean, "failure.json")
    assert completed.returncode == 0
    assert not completed.stdout and not completed.stderr
    receipt_path = clean / "failure.json"
    receipt_raw = receipt_path.read_bytes()
    receipt = json.loads(receipt_raw)
    assert receipt_raw == json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    assert receipt["failure_class"] == "backend_tunnel"
    assert receipt["cleanup_status"] == "verified"
    assert receipt["task_data_accessed"] is False
    assert receipt["model_endpoint_accessed"] is False
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o400
    assert receipt_path.stat().st_nlink == 1
    assert invoke(clean, "failure.json").returncode != 0
    assert receipt_path.read_bytes() == receipt_raw

    symlink_parent = tmp_path / "symlink"
    symlink_parent.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    (symlink_parent / "failure.json").symlink_to(outside)
    assert invoke(symlink_parent, "failure.json").returncode != 0
    assert outside.read_text() == "preserve"

    directory_parent = tmp_path / "directory"
    directory_parent.mkdir(mode=0o700)
    (directory_parent / "failure.json").mkdir(mode=0o700)
    assert invoke(directory_parent, "failure.json").returncode != 0
    assert (directory_parent / "failure.json").is_dir()

    partial_parent = tmp_path / "partial"
    partial_parent.mkdir(mode=0o700)
    partial_source = program.replace(
        "        offset = 0\n        while offset < len(payload):",
        '        os.write(descriptor, b"{")\n'
        "        os.fsync(descriptor)\n"
        '        raise OSError("injected-after-create")\n'
        "        offset = 0\n"
        "        while offset < len(payload):",
    )
    assert partial_source != program
    assert invoke(partial_parent, "failure.json", source=partial_source).returncode != 0
    partial_receipt = partial_parent / "failure.json"
    assert partial_receipt.read_bytes() == b"{"
    assert stat.S_IMODE(partial_receipt.stat().st_mode) == 0o600
    assert list(partial_parent.iterdir()) == [partial_receipt]

    signal_parent = tmp_path / "signal"
    signal_parent.mkdir(mode=0o700)
    signal_source = program.replace(
        "    descriptor = -1",
        "    os.kill(os.getpid(), signal.SIGTERM)\n    descriptor = -1",
    )
    assert signal_source != program
    assert invoke(signal_parent, "failure.json", source=signal_source).returncode == -signal.SIGTERM
    assert json.loads((signal_parent / "failure.json").read_bytes())["failure_class"] == "backend_tunnel"

    concurrent_parent = tmp_path / "concurrent"
    concurrent_parent.mkdir(mode=0o700)
    concurrent_fd = os.open(concurrent_parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    concurrent_argv = [
        "/usr/bin/python3",
        "-I",
        "-S",
        "-B",
        "-c",
        program,
        str(concurrent_fd),
        "failure.json",
        "backend_tunnel",
        "verified",
        *hashes,
        "123",
        job_name,
    ]
    try:
        contenders = [
            subprocess.Popen(
                concurrent_argv,
                pass_fds=(concurrent_fd,),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _index in range(2)
        ]
        outcomes = [process.communicate(timeout=10) + (process.returncode,) for process in contenders]
    finally:
        os.close(concurrent_fd)
    assert sorted(outcome[2] for outcome in outcomes)[0] == 0
    assert sum(outcome[2] == 0 for outcome in outcomes) == 1
    concurrent_raw = (concurrent_parent / "failure.json").read_bytes()
    assert concurrent_raw == receipt_raw
    assert stat.S_IMODE((concurrent_parent / "failure.json").stat().st_mode) == 0o400

    for unsupported in ("renameat2", "RENAME_NOREPLACE", "os.rename(", "os.unlink(", "temporary"):
        assert unsupported not in program
    assert "os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC" in program
    assert program.count("os.pread(descriptor, len(payload) + 1, 0) != payload") == 2

    assert "probe_rc == 124" in wrapper
    assert "primary_failure=unclassified" in wrapper
    assert "${#probe_lines[@]} == 1" in wrapper
    assert 'publish_probe_failure "$primary_failure" "$cleanup_status"' in wrapper
    assert "DIAG_PROBE_FAILURE_RECEIPT" in wrapper
    assert "probe_lines" not in program
    probe_source = PROBE_PATH.read_text()
    assert '"failure_class": code' in probe_source
    assert '"cleanup_status": cleanup_status' in probe_source
    assert "raise SupervisorFailure(primary_failure, cleanup_status) from active_error" in probe_source


def test_canonical_result_contains_no_process_identifiers(probe: Any) -> None:
    raw = probe.canonical_json(passed_result(probe))
    assert b'"pid"' not in raw
    assert b'"process_group"' not in raw
    assert b"auth_token" not in raw
