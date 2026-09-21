from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import signal
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
PROBE_PATH = HERE / "probe_vmvm_owner_lifecycle_v1.py"
LAUNCHER_PATH = HERE / "launch_vmvm_owner_lifecycle_v1.py"
FINALIZER_PATH = HERE / "finalize_vmvm_owner_lifecycle_v1.py"
WRAPPER_PATH = HERE / "run_vmvm_owner_lifecycle_v1.sbatch"
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
        "finalize_vmvm_owner_lifecycle_v1.py",
        "launch_vmvm_owner_lifecycle_v1.py",
        "probe_vmvm_owner_lifecycle_v1.py",
        "run_vmvm_owner_lifecycle_v1.sbatch",
        "test_vmvm_owner_lifecycle_v1.py",
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
        "external_completion_handoff": "shared_nfs_portable_inode_mode_uid_v1",
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
    command = launcher._sbatch_command("vmvm-owner-life-" + "a" * 24, Path("/tmp/environment.bin"))
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


def test_wrapper_retained_root_validator_binds_certificate_identity(tmp_path: Path) -> None:
    wrapper = WRAPPER_PATH.read_text()
    program = wrapper.split("readonly RETAINED_ROOT_VALIDATOR_PROGRAM='\n", 1)[1].split(
        "\n'\n\nvalidate_retained_root()", 1
    )[0]
    output_parent = tmp_path / "outputs"
    output_parent.mkdir()
    output = output_parent / "candidate"
    output.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    info = scratch.stat()
    certificate = {
        "execution_inputs": {
            "scratch_root_portable_identity": {
                "inode": info.st_ino,
                "mode": stat.S_IMODE(info.st_mode),
                "owner_uid": info.st_uid,
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


def test_cross_host_two_root_handoff_uses_shared_portable_identities(
    probe: Any,
    launcher: Any,
    finalizer: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    expected_scratch = Path(f"{launcher.OUTPUT_ROOT}.scratch")
    assert expected_scratch.parent == launcher.OUTPUT_ROOT.parent
    assert str(expected_scratch).startswith("/checkpoint/ram/")
    assert probe.EXPECTED_SCRATCH_ROOT == finalizer.SCRATCH_ROOT == expected_scratch

    compute_scratch = {"device": 101, "inode": 2001, "mode": 0o700, "owner_uid": os.getuid()}
    finalizer_scratch = {**compute_scratch, "device": 202}
    compute_output = {"device": 101, "inode": 2002, "mode": 0o500, "owner_uid": os.getuid()}
    finalizer_output = {**compute_output, "device": 202}
    assert compute_scratch != finalizer_scratch
    assert compute_output != finalizer_output
    for module in (probe, launcher, finalizer):
        assert module.portable_directory_identity(compute_scratch) == module.portable_directory_identity(
            finalizer_scratch
        )
        assert module.portable_directory_identity(compute_output) == module.portable_directory_identity(
            finalizer_output
        )

    probe_source = PROBE_PATH.read_text()
    finalizer_source = FINALIZER_PATH.read_text()
    wrapper_source = WRAPPER_PATH.read_text()
    assert "scratch_parent_fd = os.dup(output_parent_fd)" in probe_source
    assert "def inherited_bound_directory(" not in probe_source
    assert probe_source.count("inherited_portable_bound_directory(") == 7
    probe_request = probe_source.split("completion_request = {", 1)[1].split("completion_payload =", 1)[0]
    finalizer_request = finalizer_source.split("if request != {", 1)[1].split("}:\n", 1)[0]
    for request_source in (probe_request, finalizer_request):
        assert '"output_root_portable_identity"' in request_source
        assert '"scratch_root_portable_identity"' in request_source
        assert '"output_root_identity"' not in request_source
        assert '"scratch_root_identity"' not in request_source
    assert 'get("scratch_root_portable_identity")' in wrapper_source

    shared_parent = tmp_path / "shared"
    shared_parent.mkdir()
    output = shared_parent / "output"
    output.mkdir(mode=0o500)
    scratch = shared_parent / "output.scratch"
    scratch.mkdir(mode=0o700)
    scratch_fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        observed_scratch = finalizer.descriptor_identity(scratch_fd)
    finally:
        os.close(scratch_fd)
    simulated_compute_scratch = {**observed_scratch, "device": observed_scratch["device"] + 1}
    expected_portable = finalizer.portable_directory_identity(simulated_compute_scratch)
    monkeypatch.setattr(finalizer, "SCRATCH_ROOT", scratch)
    assert finalizer._validate_retained_scratch(expected_portable_identity=expected_portable) == expected_portable
    with pytest.raises(finalizer.FinalizeError, match="scratch_cleanup_unverified"):
        finalizer._validate_retained_scratch(
            expected_portable_identity={**expected_portable, "inode": expected_portable["inode"] + 1}
        )


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
        "scratch_root_portable_identity": {
            "inode": 2,
            "mode": 0o700,
            "owner_uid": os.getuid(),
        },
        "site_snapshot": inventory,
        "source_snapshot": inventory,
    }
    certificate = {
        "artifact_type": "vmvm_owner_lifecycle_diagnostic_certificate_v1",
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
            "job_name": "vmvm-owner-life-" + "e" * 24,
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
    finalizer.validate_certificate(certificate, expected_execution_inputs=execution_inputs)
    certificate["unexpected"] = True
    with pytest.raises(finalizer.FinalizeError, match="certificate_invalid"):
        finalizer.validate_certificate(certificate, expected_execution_inputs=execution_inputs)


def test_exact_counts_reject_extra_recovery_or_tunnel(probe: Any) -> None:
    for phase in ("recovery_started", "recovery_succeeded", "tunnel_ready"):
        result = json.loads(json.dumps(passed_result(probe)))
        result["lifecycle_metadata"]["phase_counts"][phase] += 1
        with pytest.raises(probe.DiagnosticError, match="stage_result_invalid"):
            probe.validate_stage_result(result)


def test_continuous_external_release_rejects_reappearance(probe: Any, monkeypatch: Any, tmp_path: Path) -> None:
    events = [
        {"artifact_type": "vmvm_owner_renewer_journal_event_v1", "event": "audit_started", "sequence": 0},
        {
            "artifact_type": "vmvm_owner_renewer_journal_event_v1",
            "event": "operation_started",
            "lease_id": 1,
            "operation": "start",
            "operation_id": 0,
            "sequence": 1,
        },
        {
            "artifact_type": "vmvm_owner_renewer_journal_event_v1",
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
            "artifact_type": "vmvm_owner_renewer_journal_event_v1",
            "event": "operation_finished",
            "lease_id": 1,
            "operation": "start",
            "operation_id": 0,
            "outcome": "process_observed",
            "sequence": 3,
        },
        {
            "artifact_type": "vmvm_owner_renewer_journal_event_v1",
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
        assert os.readlink(f"/proc/self/fd/{descriptor}") == "/memfd:vmvm-owner-wrapper-v1 (deleted)"
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
    assert "/memfd:vmvm-owner-finalizer-v1 (deleted)" in text
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


def test_finalizer_requires_retained_empty_scratch() -> None:
    source = FINALIZER_PATH.read_text()
    assert "scratch_info.st_uid != os.getuid()" in source
    assert "stat.S_IMODE(scratch_info.st_mode) != 0o700" in source
    assert "or os.listdir(scratch_fd)" in source


def test_canonical_result_contains_no_process_identifiers(probe: Any) -> None:
    raw = probe.canonical_json(passed_result(probe))
    assert b'"pid"' not in raw
    assert b'"process_group"' not in raw
    assert b"auth_token" not in raw
