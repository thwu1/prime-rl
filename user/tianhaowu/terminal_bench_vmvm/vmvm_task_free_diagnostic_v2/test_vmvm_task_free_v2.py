from __future__ import annotations

import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

ROOT = Path(__file__).parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROBE = load_module("vmvm_task_free_probe_v2_test", "probe_vmvm_task_free_v2.py")
LAUNCH = load_module("vmvm_task_free_launch_v2_test", "launch_vmvm_task_free_v2.py")
FINALIZE = load_module("vmvm_task_free_finalize_v2_test", "finalize_vmvm_task_free_v2.py")


class CleanSnapshotGuard:
    def is_clean(self) -> bool:
        return True


def valid_phase_metadata(stage: str, module=PROBE) -> dict[str, object]:
    counts = {
        "backend_ready": 1,
        "cleanup_called": 1,
        "lease_start": 1,
        "release_verified": 1,
        "tunnel_ready": 1,
        "worker_started": 1,
    }
    if stage != "direct_client":
        counts.update({"command_started": 1, "command_succeeded": 1})
    return {
        "last_phase": "release_verified",
        "lease_attempt_limit": module.LEASE_ATTEMPT_LIMIT,
        "lease_attempts": 1,
        "phase_counts": counts,
        "release_grace_seconds": module.RELEASE_GRACE_SECONDS,
        "release_method": "renewer_absent_for_lease_ttl",
        "release_verified": True,
        "renewer_processes": 1,
        "transport_recovery_attempt_limit": module.RECOVERY_ATTEMPTS,
        "transport_recovery_attempts": 0,
    }


def set_site_inventory_environment(monkeypatch, site: Path) -> None:
    descriptor = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    try:
        inventory = PROBE.directory_manifest(descriptor, expected_owner_uid=os.getuid())
    finally:
        os.close(descriptor)
    monkeypatch.setenv("PYTHON_SITE_X86_64_ENTRY_COUNT", str(inventory["entry_count"]))
    monkeypatch.setenv("PYTHON_SITE_X86_64_MANIFEST_SHA256", inventory["manifest_sha256"])
    monkeypatch.setenv("PYTHON_SITE_X86_64_TOTAL_BYTES", str(inventory["total_bytes"]))


def set_probe_execution_environment(monkeypatch, descriptor: int = 9) -> None:
    monkeypatch.setenv("DIAG_EXEC_PROBE_FD", str(descriptor))
    monkeypatch.setenv("DIAG_PROBE_SHA256", "0" * 64)


def sealed_memfd(raw: bytes, *, name: str, mode: int) -> int:
    descriptor = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    view = memoryview(raw)
    while view:
        written = os.write(descriptor, view)
        assert written > 0
        view = view[written:]
    os.fchmod(descriptor, mode)
    fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, PROBE.REQUIRED_MEMFD_SEALS)
    os.set_inheritable(descriptor, True)
    return descriptor


def build_git_source_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    def git(repository: Path, *args: str) -> str:
        result = subprocess.run(
            ["/usr/bin/git", "-c", "protocol.file.allow=always", "-C", str(repository), *args],
            env={
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "HOME": "/nonexistent",
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    dependencies: dict[str, tuple[Path, str]] = {}
    for name in ("verifiers", "renderers", "pydantic-config"):
        repository = tmp_path / f"{name}-origin"
        repository.mkdir()
        git(repository, "init", "-q")
        git(repository, "config", "user.email", "fixture@example.invalid")
        git(repository, "config", "user.name", "Fixture")
        (repository / f"{name}.py").write_text(f"NAME = {name!r}\n")
        git(repository, "add", ".")
        git(repository, "commit", "-qm", "fixture")
        dependencies[name] = (repository, git(repository, "rev-parse", "HEAD"))

    source = tmp_path / "source-root"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.email", "fixture@example.invalid")
    git(source, "config", "user.name", "Fixture")
    vmvm_file = source / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py"
    vmvm_file.parent.mkdir(parents=True)
    vmvm_file.write_text("VALUE = 1\n")
    git(source, "add", ".")
    for name, (repository, _revision) in dependencies.items():
        git(source, "submodule", "add", "-q", str(repository), f"deps/{name}")
        git(source / "deps" / name, "checkout", "--detach", "-q")
    git(source, "commit", "-qm", "fixture")
    revision = git(source, "rev-parse", "HEAD")
    tree = git(source, "rev-parse", "HEAD^{tree}")
    git(source, "checkout", "--detach", "-q")
    relative = "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py"
    row = f"{hashlib.sha256(vmvm_file.read_bytes()).hexdigest()}  {relative}\n".encode()
    return source, {
        "revision": revision,
        "tree": tree,
        "verifiers": dependencies["verifiers"][1],
        "renderers": dependencies["renderers"][1],
        "pydantic_config": dependencies["pydantic-config"][1],
        "vmvm": hashlib.sha256(row).hexdigest(),
    }


def test_failure_classifier_is_allowlisted_and_drops_detail() -> None:
    error = RuntimeError("VMVM provisioning failed: [vacli] connection lost (rc=255, truncated reply) PRIVATE")
    assert PROBE.classify_failure(error) == "runtime_initial_workdir_rc255"
    result = PROBE._result_payload(
        mode="present",
        stage="runtime_contract",
        state="failed",
        failure=PROBE.classify_failure(error),
        cleanup_complete=True,
        elapsed_seconds=1.25,
        pair_index=0,
        order_position=1,
    )
    encoded = PROBE.canonical_json(result)
    assert b"PRIVATE" not in encoded
    assert set(result) == {
        "artifact_type",
        "cleanup_complete",
        "elapsed_milliseconds",
        "failure_class",
        "order_position",
        "pair_index",
        "phase_metadata",
        "stage",
        "state",
        "x2p_mode",
    }


class FakeBackend:
    instances: ClassVar[list[FakeBackend]] = []

    def __init__(self, config) -> None:
        self.config = config
        self.constructor_thread = threading.current_thread()
        self.command_thread = None
        self.raw_calls = 0
        self.recovery_calls = 0
        self.destroy_calls = 0
        self.result = {
            "status": "success",
            "output": "",
            "error_type": "none",
            "exit_code": 0,
        }
        self.instances.append(self)

    def run_bash(self, command: str, timeout: float):
        del command, timeout
        self.command_thread = threading.current_thread()
        self.raw_calls += 1
        return self.result

    def run_bash_with_recovery(self, command: str, timeout: float, attempts: int):
        del command, timeout
        assert attempts == PROBE.RECOVERY_ATTEMPTS
        self.command_thread = threading.current_thread()
        self.recovery_calls += 1
        return self.result

    def destroy(self) -> None:
        self.destroy_calls += 1


@pytest.mark.parametrize(
    ("cross_thread", "recovery"),
    ((False, False), (False, True), (True, False), (True, True)),
)
def test_backend_matrix_exercises_thread_and_recovery_axes(cross_thread: bool, recovery: bool) -> None:
    FakeBackend.instances.clear()
    passed, failure, cleaned = PROBE.execute_backend_variant(
        backend_type=FakeBackend,
        config=object(),
        cross_thread=cross_thread,
        recovery=recovery,
    )
    assert (passed, failure, cleaned) == (True, None, True)
    backend = FakeBackend.instances[-1]
    assert (backend.constructor_thread is not backend.command_thread) is cross_thread
    assert backend.raw_calls == (0 if recovery else 1)
    assert backend.recovery_calls == (1 if recovery else 0)
    assert backend.destroy_calls == 1


def test_backend_broken_pipe_is_sanitized_and_cleaned() -> None:
    class BrokenBackend(FakeBackend):
        def run_bash(self, command: str, timeout: float):
            del command, timeout
            return {
                "status": "error",
                "output": "sensitive",
                "error_type": "broken_pipe",
                "exit_code": -1,
            }

    passed, failure, cleaned = PROBE.execute_backend_variant(
        backend_type=BrokenBackend,
        config=object(),
        cross_thread=False,
        recovery=False,
    )
    assert (passed, failure, cleaned) == (False, "runtime_initial_workdir_rc255", True)


def test_constructor_failure_preserves_cause_after_audited_rollback() -> None:
    class ExitedProcess:
        pid = 2_000_000_000

        def poll(self) -> int:
            return 0

    class Lease:
        def __init__(self) -> None:
            self.proc = None

        def start(self) -> None:
            self.proc = ExitedProcess()

        def cleanup(self) -> None:
            return None

    audit = PROBE.LeaseAudit()
    tracked_lease_type = audit.tracking_lease_type(Lease)

    class ConstructorFailure:
        def __init__(self, config) -> None:
            del config
            lease = tracked_lease_type()
            lease.start()
            lease.cleanup()
            raise RuntimeError("vacli failed to start")

    passed, failure, cleaned = PROBE.execute_backend_variant(
        backend_type=ConstructorFailure,
        config=object(),
        cross_thread=False,
        recovery=False,
        audit=audit,
    )
    assert (passed, failure, cleaned) == (False, "backend_lease", True)


def test_direct_client_cleans_on_failure(tmp_path: Path) -> None:
    class Lease:
        cleaned = False

        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def start(self) -> None:
            raise RuntimeError("private detail")

        def wait_for_tunnel(self) -> int:
            raise AssertionError

        def cleanup(self) -> None:
            self.cleaned = True

    passed, failure, cleaned = PROBE.execute_direct_client(
        lease_type=Lease,
        wait_for_sshd=lambda *args, **kwargs: None,
        scratch=tmp_path,
    )
    assert (passed, failure, cleaned) == (False, "direct_client_failed", True)


def test_x2p_modes_are_exact_and_values_never_enter_result(monkeypatch, tmp_path: Path) -> None:
    private = {
        "THRIFT_TLS_CL_CERT_PATH": "/private/tls",
        "THRIFT_TLS_CL_KEY_PATH": "/private/tls",
        "X2P_ENV": "private-x2p-one",
        "X2P_CFG_ENV": "private-x2p-two",
        "X2P_PROXY_URL": "private-x2p-proxy",
    }
    for key, value in private.items():
        monkeypatch.setenv(key, value)
    set_probe_execution_environment(monkeypatch)
    absent = PROBE._child_environment("absent", tmp_path)
    present = PROBE._child_environment("present", tmp_path)
    assert set(absent).isdisjoint(PROBE.X2P_NAMES)
    assert {name: present[name] for name in PROBE.X2P_NAMES} == {name: private[name] for name in PROBE.X2P_NAMES}
    result = PROBE._result_payload(
        mode="present",
        stage="direct_client",
        state="passed",
        failure=None,
        cleanup_complete=True,
        elapsed_seconds=0,
        pair_index=0,
        order_position=1,
    )
    encoded = PROBE.canonical_json(result)
    assert all(value.encode() not in encoded for value in private.values())
    assert PROBE.X2P_NAMES == ("X2P_ENV", "X2P_CFG_ENV", "X2P_PROXY_URL")
    assert LAUNCH.X2P_NAMES == PROBE.X2P_NAMES
    monkeypatch.delenv("X2P_PROXY_URL")
    with pytest.raises(PROBE.DiagnosticError, match="child_invalid"):
        PROBE._child_environment("present", tmp_path)


def test_stage_result_rejects_unapproved_failure() -> None:
    value = PROBE._result_payload(
        mode="absent",
        stage="direct_client",
        state="passed",
        failure=None,
        cleanup_complete=True,
        elapsed_seconds=0,
        phase_metadata=valid_phase_metadata("direct_client"),
    )
    PROBE.validate_stage_result(
        value,
        expected_mode="absent",
        expected_stage="direct_client",
        expected_pair_index=0,
        expected_order_position=0,
    )
    value["state"] = "failed"
    value["failure_class"] = "raw private exception"
    with pytest.raises(PROBE.DiagnosticError, match="stage_result_invalid"):
        PROBE.validate_stage_result(
            value,
            expected_mode="absent",
            expected_stage="direct_client",
            expected_pair_index=0,
            expected_order_position=0,
        )


def test_supervisor_runs_exact_matrix_and_publishes_completion_last(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    site = tmp_path / "site"
    source.mkdir()
    site.mkdir()
    (site / "authorized.py").write_text("VALUE = 1\n")
    output = tmp_path / "output"
    scratch = tmp_path / "scratch"
    calls: list[tuple[str, int, int, str]] = []
    publication_events: list[str] = []

    def fake_stage(**kwargs):
        mode = kwargs["mode"]
        stage = kwargs["stage"]
        calls.append((stage, kwargs["pair_index"], kwargs["order_position"], mode))
        return PROBE._result_payload(
            mode=mode,
            stage=stage,
            state="passed",
            failure=None,
            cleanup_complete=True,
            elapsed_seconds=0,
            pair_index=kwargs["pair_index"],
            order_position=kwargs["order_position"],
            phase_metadata=valid_phase_metadata(stage),
        )

    monkeypatch.setattr(PROBE, "run_stage_child", fake_stage)
    monkeypatch.setattr(PROBE, "attest_imported_source", lambda descriptor: {})

    def fake_snapshot(source_fd, site_fd, scratch_root, expected_site_inventory):
        del source_fd, site_fd, expected_site_inventory
        snapshot_source = scratch_root / "sealed-inputs/source"
        snapshot_site = scratch_root / "sealed-inputs/site"
        snapshot_source.mkdir(parents=True)
        snapshot_site.mkdir()
        (snapshot_source / "fixture.py").write_text("VALUE = 1\n")
        (snapshot_site / "fixture.py").write_text("VALUE = 1\n")
        inventories = []
        for path in (snapshot_source, snapshot_site):
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                inventories.append(PROBE.directory_manifest(descriptor, expected_owner_uid=os.getuid()))
            finally:
                os.close(descriptor)
        return snapshot_source, snapshot_site, *inventories

    monkeypatch.setattr(PROBE, "create_execution_snapshot", fake_snapshot)
    original_remove = PROBE._remove_bound_tree_verified
    original_atomic_write = PROBE._atomic_write

    def observed_remove(*args):
        result = original_remove(*args)
        publication_events.append("scratch_removed" if result else "scratch_remove_failed")
        return result

    def observed_write(*args, **kwargs):
        publication_events.append("output_published")
        return original_atomic_write(*args, **kwargs)

    monkeypatch.setattr(PROBE, "_remove_bound_tree_verified", observed_remove)
    monkeypatch.setattr(PROBE, "_atomic_write", observed_write)
    set_site_inventory_environment(monkeypatch, site)
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    site_fd = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    output_parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    script_fd = os.open(ROOT / "probe_vmvm_task_free_v2.py", os.O_RDONLY)
    try:
        monkeypatch.setattr(PROBE, "__file__", f"/proc/self/fd/{script_fd}")
        monkeypatch.setenv(
            "DIAG_SOURCE_IDENTITY",
            ":".join(str(value) for value in PROBE.descriptor_identity(source_fd).values()),
        )
        monkeypatch.setenv(
            "PYTHON_SITE_X86_64_IDENTITY",
            ":".join(str(value) for value in PROBE.descriptor_identity(site_fd).values()),
        )
        monkeypatch.setenv(
            "DIAG_OUTPUT_PARENT_IDENTITY",
            ":".join(str(value) for value in PROBE.descriptor_identity(output_parent_fd).values()),
        )
        result = PROBE.run_supervisor(
            SimpleNamespace(
                source_root=Path(f"/proc/self/fd/{source_fd}"),
                site_root=Path(f"/proc/self/fd/{site_fd}"),
                output_dir=Path(f"/proc/self/fd/{output_parent_fd}") / output.name,
                completion_receipt=Path(f"/proc/self/fd/{output_parent_fd}") / "external-completion.json",
                scratch_root=scratch,
                environment_sha256="a" * 64,
                authorization_file_sha256="d" * 64,
                authorization_sha256="b" * 64,
                job_authorization_sha256="e" * 64,
                job_id="42",
                job_name="vmvm-v4-preflight-" + "f" * 24,
                submission_receipt_sha256="c" * 64,
            )
        )
    finally:
        os.close(script_fd)
        os.close(output_parent_fd)
        os.close(site_fd)
        os.close(source_fd)
    assert calls == [
        (stage, pair_index, position, mode)
        for stage in PROBE.STAGES
        for pair_index, order in enumerate(PROBE.MODE_ORDERS)
        for position, mode in enumerate(order)
    ]
    assert result == {
        "failure_categories": 0,
        "passed": PROBE.CELL_COUNT,
        "stages": PROBE.CELL_COUNT,
        "state": "awaiting_external_completion",
    }
    assert publication_events == ["scratch_removed", "output_published", "output_published"]
    certificate = json.loads((output / "diagnostic_certificate.json").read_bytes())
    completion = json.loads((output / "completion_request.json").read_bytes())
    FINALIZE.validate_certificate(
        certificate,
        expected_execution_inputs=certificate["execution_inputs"],
    )
    assert certificate["task_data_accessed"] is False
    assert certificate["model_endpoint_accessed"] is False
    assert certificate["production_authorized"] is False
    assert certificate["protocol"]["mode_orders"] == [list(order) for order in PROBE.MODE_ORDERS]
    assert certificate["protocol"]["cell_count"] == PROBE.CELL_COUNT
    for stage in PROBE.STAGES:
        assert certificate["retry_phase_aggregate"][stage]["absent"]["cells"] == 4
        assert certificate["retry_phase_aggregate"][stage]["present"]["cells"] == 4
    assert completion["certificate_sha256"] == PROBE.sha256_bytes((output / "diagnostic_certificate.json").read_bytes())
    assert completion["external_completion_receipt"] == str(PROBE.EXPECTED_COMPLETION_RECEIPT)
    assert stat.S_IMODE((output / "diagnostic_certificate.json").stat().st_mode) == 0o400
    assert stat.S_IMODE((output / "completion_request.json").stat().st_mode) == 0o400
    assert stat.S_IMODE(output.stat().st_mode) == 0o500
    assert not scratch.exists()


def test_sbatch_is_held_single_job_and_uses_stdin_wrapper() -> None:
    command = LAUNCH._sbatch_command("vmvm-v4-preflight-" + "a" * 24, Path("/private/environment"))
    assert command[0] == "/usr/bin/sbatch"
    assert "--hold" in command
    assert "--export=NONE" in command
    assert "--nodes=1" in command
    assert "--ntasks=1" in command
    assert "--cpus-per-task=2" in command
    assert "--time=1-12:00:00" in command
    assert not any(value.endswith(".sbatch") for value in command)


def test_slurm_time_limit_uses_the_scheduler_canonical_identity() -> None:
    job_id = "42"
    job_name = "vmvm-v4-preflight-" + "a" * 24
    record = {
        "Account": "ram",
        "Command": "(null)",
        "Comment": "vmvm-v4-preflight:" + "a" * 24,
        "Dependency": "(null)",
        "JobId": job_id,
        "JobName": job_name,
        "MinMemoryNode": LAUNCH.JOB_MEMORY,
        "NumCPUs": LAUNCH.JOB_CPUS,
        "Partition": "cpu_x86",
        "QOS": "cpu_x86_lowest",
        "Requeue": "0",
        "Restarts": "0",
        "StdErr": str(LAUNCH.LOG_ROOT / f"diagnostic_{job_id}.log"),
        "StdOut": str(LAUNCH.LOG_ROOT / f"diagnostic_{job_id}.log"),
        "TimeLimit": "1-12:00:00",
        "UserId": LAUNCH.OWNER_IDENTITY,
        "WorkDir": str(LAUNCH.SOURCE_ROOT),
    }
    assert LAUNCH.JOB_TIME_LIMIT == FINALIZE.JOB_TIME_LIMIT == "1-12:00:00"
    assert LAUNCH._base_mismatches(record, job_id, job_name) == set()
    record["TimeLimit"] = "36:00:00"
    assert LAUNCH._base_mismatches(record, job_id, job_name) == {"TimeLimit"}


def test_v4_preflight_namespaces_are_exact_and_fresh() -> None:
    assert LAUNCH.OUTPUT_ROOT == PROBE.EXPECTED_OUTPUT_ROOT == FINALIZE.OUTPUT_ROOT
    assert LAUNCH.SCRATCH_ROOT == PROBE.EXPECTED_SCRATCH_ROOT == FINALIZE.SCRATCH_ROOT
    assert LAUNCH.LOG_ROOT == FINALIZE.LOG_ROOT
    assert LAUNCH.OUTPUT_ROOT.name == "vmvm_v21_task_free_preflight_a09a9a189_v4"
    assert LAUNCH.LOG_ROOT.name == "vmvm_v21_task_free_preflight_a09a9a189_v4"
    assert LAUNCH.SCRATCH_ROOT.name == "vmvm-v21-task-free-preflight-v4"
    assert LAUNCH.NAME_RE.fullmatch("vmvm-v4-preflight-" + "a" * 24)


def test_held_poll_requires_two_exact_snapshots(monkeypatch) -> None:
    outcomes = iter(
        [
            (False, {"held_queue"}, set()),
            (True, set(), set()),
            (True, set(), set()),
        ]
    )
    clock = iter((0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
    monkeypatch.setattr(LAUNCH, "_snapshot", lambda *args: next(outcomes))
    monkeypatch.setattr(LAUNCH.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(LAUNCH.time, "sleep", lambda value: None)
    result = LAUNCH.poll_phase("1", "vmvm-v4-preflight-" + "a" * 24, "held", 20, set())
    assert result["converged"] is True
    assert result["polls"] == 3
    assert result["mismatch_occurrences"] == {"held_queue": 1}


def test_conflict_latch_is_monotonic(monkeypatch) -> None:
    outcomes = iter(
        [
            (False, {"JobName"}, {"JobName"}),
            (True, set(), set()),
        ]
    )
    monkeypatch.setattr(LAUNCH, "_snapshot", lambda *args: next(outcomes))
    result = LAUNCH.poll_phase("1", "vmvm-v4-preflight-" + "a" * 24, "held", 20, set())
    assert result["converged"] is False
    assert result["explicit_conflict_fields"] == ["JobName"]
    assert result["polls"] == 1


def test_cancel_conflict_never_calls_scancel(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        LAUNCH,
        "_scontrol",
        lambda *args: {
            "JobId": "1",
            "JobName": "other",
            "UserId": LAUNCH.OWNER_IDENTITY,
        },
    )
    monkeypatch.setattr(LAUNCH, "_run", lambda command, timeout=20: calls.append(list(command)))
    result = LAUNCH.cancel_and_prove(
        "1",
        "vmvm-v4-preflight-" + "a" * 24,
        set(),
        candidate_provenance="sbatch_stdout",
    )
    assert result["control_attempted"] is False
    assert result["terminal_proved"] is False
    assert not calls


def test_wrapper_is_preflight_only_and_never_invokes_supervisor() -> None:
    source = (ROOT / "run_vmvm_task_free_v2.sbatch").read_text()
    permit = source.index("preflight_output=")
    final_gate = source.index("validate_source", permit)
    output_gate = source.index("[[ ! -e $DIAG_OUTPUT_ROOT", final_gate)
    success = source.index('"stage":"prelease_admission"', output_gate)
    assert permit < final_gate < output_gate < success
    assert all(name in source for name in PROBE.X2P_NAMES)
    assert source.count("run_sealed_probe --validate-batch") == 1
    assert "--scratch-root" in source
    assert "probe_output=" not in source
    assert "--environment-sha256" not in source
    assert "run_supervisor" not in source
    preflight = source[permit:final_gate]
    assert '--output-dir "$BOUND_OUTPUT_PARENT/' in preflight
    assert '--completion-receipt "$BOUND_OUTPUT_PARENT/' in preflight


def test_probe_cli_exposes_only_preflight_admission() -> None:
    destinations = {action.dest for action in PROBE._parser()._actions}
    assert destinations == {
        "completion_receipt",
        "help",
        "output_dir",
        "scratch_root",
        "site_root",
        "source_root",
        "validate_batch",
    }
    source = (ROOT / "probe_vmvm_task_free_v2.py").read_text()
    main = source[source.index("def main(") :]
    assert "run_supervisor" not in main
    assert "execute_worker" not in main


def test_preflight_protocol_is_minimal_and_consistent() -> None:
    expected = {
        "diagnostic_only": True,
        "preflight_only": True,
        "production_authorized": False,
    }
    assert LAUNCH.PREFLIGHT_PROTOCOL == PROBE.PREFLIGHT_PROTOCOL == FINALIZE.PREFLIGHT_PROTOCOL == expected


def test_wrapper_public_output_domains_are_closed() -> None:
    source = (ROOT / "run_vmvm_task_free_v2.sbatch").read_text()
    allowed_stages = {
        "activation_gate",
        "bundle_artifacts",
        "bundle_inventory",
        "count_shape",
        "digest_shape",
        "directory_identity",
        "directory_open",
        "entry",
        "executable_binding",
        "fixed_environment",
        "forbidden_environment",
        "identity_shape",
        "lineage_hashes",
        "namespace_freshness",
        "path_shape",
        "post_preflight_source",
        "probe_admission",
        "probe_response",
        "required_environment",
        "runtime_artifacts",
        "runtime_resolution",
        "sealed_builder",
        "source_attestation",
    }
    assigned_stages = set(re.findall(r"^\s*failure_stage=([a-z_]+)$", source, re.MULTILINE))
    assert assigned_stages == allowed_stages
    assert "exec >/dev/null 2>&1" in source
    assert "for public_fd in (public_stdout_fd, public_stderr_fd):" in source
    assert "os.close(public_fd)" in source
    assert "printf '%s\\n' \"$preflight_output\"" not in source
    assert source.count('>&"$public_stderr_fd"') == 1
    assert source.count('>&"$public_stdout_fd"') == 1


def test_source_contains_no_task_or_model_entrypoint() -> None:
    sources = "\n".join(
        (ROOT / name).read_text()
        for name in (
            "probe_vmvm_task_free_v2.py",
            "run_vmvm_task_free_v2.sbatch",
            "launch_vmvm_task_free_v2.py",
            "finalize_vmvm_task_free_v2.py",
        )
    )
    assert "run_oracle.py" not in sources
    assert "TASK_FILE" not in sources
    assert "inference" not in sources.lower()
    assert "chat/completions" not in sources


def test_child_environment_is_exact_and_stage_local(monkeypatch, tmp_path: Path) -> None:
    for name, value in {
        "THRIFT_TLS_CL_CERT_PATH": "/private/tls",
        "THRIFT_TLS_CL_KEY_PATH": "/private/tls",
        "X2P_ENV": "private-one",
        "X2P_CFG_ENV": "private-two",
        "X2P_PROXY_URL": "private-proxy",
    }.items():
        monkeypatch.setenv(name, value)
    set_probe_execution_environment(monkeypatch)
    environment = PROBE._child_environment("present", tmp_path)
    assert environment["TMPDIR"] == str(tmp_path)
    assert environment["VACLI_MAX_CONCURRENT_LEASES"] == "1"
    assert environment["VACLI_LEASE_RETRIES"] == str(PROBE.LEASE_ATTEMPT_LIMIT)
    assert environment["VACLI_MAX_PULL_RETRIES"] == str(PROBE.IMAGE_PULL_RETRY_LIMIT)
    assert "PYTHONPATH" not in environment
    assert "HOME_SECRET" not in environment


@pytest.mark.parametrize(
    ("failure", "cleanup_complete", "expected_error"),
    (
        ("cleanup_failed", False, "cleanup_failed"),
        ("child_invalid", True, "stage_result_invalid"),
    ),
)
def test_supervisor_aborts_before_next_cell_on_unverifiable_result(
    monkeypatch,
    tmp_path: Path,
    failure: str,
    cleanup_complete: bool,
    expected_error: str,
) -> None:
    source = tmp_path / "source"
    site = tmp_path / "site"
    source.mkdir()
    site.mkdir()
    (site / "authorized.py").write_text("VALUE = 1\n")

    calls = 0

    def failed_stage(**kwargs):
        nonlocal calls
        calls += 1
        return PROBE._result_payload(
            mode=kwargs["mode"],
            stage=kwargs["stage"],
            state="failed",
            failure=failure,
            cleanup_complete=cleanup_complete,
            elapsed_seconds=0,
            pair_index=kwargs["pair_index"],
            order_position=kwargs["order_position"],
        )

    monkeypatch.setattr(PROBE, "run_stage_child", failed_stage)
    monkeypatch.setattr(PROBE, "attest_imported_source", lambda descriptor: {})

    def fake_snapshot(source_fd, site_fd, scratch_root, expected_site_inventory):
        del source_fd, site_fd, expected_site_inventory
        source_snapshot = scratch_root / "sealed-inputs/source"
        site_snapshot = scratch_root / "sealed-inputs/site"
        source_snapshot.mkdir(parents=True)
        site_snapshot.mkdir()
        (source_snapshot / "fixture.py").write_text("VALUE = 1\n")
        (site_snapshot / "fixture.py").write_text("VALUE = 1\n")
        inventories = []
        for path in (source_snapshot, site_snapshot):
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                inventories.append(PROBE.directory_manifest(descriptor, expected_owner_uid=os.getuid()))
            finally:
                os.close(descriptor)
        return source_snapshot, site_snapshot, *inventories

    monkeypatch.setattr(PROBE, "create_execution_snapshot", fake_snapshot)
    set_site_inventory_environment(monkeypatch, site)
    output = tmp_path / "output"
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    site_fd = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    output_parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    script_fd = os.open(ROOT / "probe_vmvm_task_free_v2.py", os.O_RDONLY)
    try:
        monkeypatch.setattr(PROBE, "__file__", f"/proc/self/fd/{script_fd}")
        monkeypatch.setenv(
            "DIAG_SOURCE_IDENTITY",
            ":".join(str(value) for value in PROBE.descriptor_identity(source_fd).values()),
        )
        monkeypatch.setenv(
            "PYTHON_SITE_X86_64_IDENTITY",
            ":".join(str(value) for value in PROBE.descriptor_identity(site_fd).values()),
        )
        monkeypatch.setenv(
            "DIAG_OUTPUT_PARENT_IDENTITY",
            ":".join(str(value) for value in PROBE.descriptor_identity(output_parent_fd).values()),
        )
        with pytest.raises(PROBE.DiagnosticError, match=expected_error):
            PROBE.run_supervisor(
                SimpleNamespace(
                    source_root=Path(f"/proc/self/fd/{source_fd}"),
                    site_root=Path(f"/proc/self/fd/{site_fd}"),
                    output_dir=Path(f"/proc/self/fd/{output_parent_fd}") / output.name,
                    completion_receipt=Path(f"/proc/self/fd/{output_parent_fd}") / "external-completion.json",
                    scratch_root=tmp_path / "scratch",
                    environment_sha256="a" * 64,
                    authorization_file_sha256="d" * 64,
                    authorization_sha256="b" * 64,
                    job_authorization_sha256="e" * 64,
                    job_id="42",
                    job_name="vmvm-v4-preflight-" + "f" * 24,
                    submission_receipt_sha256="c" * 64,
                )
            )
    finally:
        os.close(script_fd)
        os.close(output_parent_fd)
        os.close(site_fd)
        os.close(source_fd)
    assert calls == 1
    assert not (output / "completion_request.json").exists()


def test_authorization_uses_distinct_body_and_file_hashes(tmp_path: Path) -> None:
    body = {
        "artifact_type": "vmvm_task_free_diagnostic_authorization_v2",
        "bundle": {},
        "credentials": {},
        "launch": {},
        "protocol": {},
        "runtime": {},
        "schema_version": 2,
        "source": {},
        "state": "approved",
    }
    body_sha = LAUNCH.sha256_bytes(LAUNCH.canonical_json(body))
    value = {**body, "authorization_sha256": body_sha}
    raw = LAUNCH.canonical_json(value) + b"\n"
    path = tmp_path / "authorization.json"
    path.write_bytes(raw)
    path.chmod(0o400)
    loaded, observed, embedded = LAUNCH.load_authorization(path, LAUNCH.sha256_bytes(raw))
    assert loaded == value
    assert observed == raw
    assert embedded == body_sha
    assert embedded != LAUNCH.sha256_bytes(raw)


def test_runtime_binary_limit_covers_the_pinned_vacli() -> None:
    assert LAUNCH.VACLI.stat().st_size < 512 << 20
    assert LAUNCH.VACLI.stat().st_size > 128 << 20


def test_vacli_parent_symlink_must_resolve_to_the_exact_inode(tmp_path: Path) -> None:
    target_directory = tmp_path / "version-794"
    target_directory.mkdir()
    target = target_directory / "vacli"
    target.write_bytes(b"same bytes\n")
    alias_directory = tmp_path / "stable"
    alias_directory.symlink_to(target_directory, target_is_directory=True)
    alias = alias_directory / "vacli"
    copy = tmp_path / "copy"
    copy.write_bytes(target.read_bytes())
    for module in (LAUNCH, PROBE, FINALIZE):
        function = getattr(module, "same_open_file", None) or module._same_open_file
        assert function(alias, target)
        assert not function(alias, copy)


def test_resolve_submission_recovers_timeout_by_exact_name(monkeypatch) -> None:
    monkeypatch.setattr(LAUNCH, "_lookup_submission", lambda *args, **kwargs: ("unique", "42"))
    assert LAUNCH._resolve_submission(
        direct_candidate=None,
        outcome="timeout",
        job_name="vmvm-v4-preflight-" + "a" * 24,
        start_date="2026-09-19",
    ) == ("42", "name_lookup")


def test_resolve_submission_rejects_direct_name_disagreement(monkeypatch) -> None:
    monkeypatch.setattr(LAUNCH, "_lookup_submission", lambda *args, **kwargs: ("unique", "43"))
    with pytest.raises(LAUNCH.LaunchError, match="submission_identity_ambiguous"):
        LAUNCH._resolve_submission(
            direct_candidate="42",
            outcome="completed",
            job_name="vmvm-v4-preflight-" + "a" * 24,
            start_date="2026-09-19",
        )


def test_direct_candidate_unavailable_identity_attempts_one_exact_cancel(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    clock = iter(float(value) for value in range(0, 2000, 100))
    monkeypatch.setattr(LAUNCH.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(LAUNCH.time, "sleep", lambda value: None)
    monkeypatch.setattr(LAUNCH, "_identity_probe", lambda *args: ("unavailable_or_incomplete", set()))
    monkeypatch.setattr(
        LAUNCH,
        "_terminal_snapshot",
        lambda *args: ("unavailable_or_incomplete", set(), ()),
    )

    def fake_run(command, timeout=20):
        del timeout
        calls.append(list(command))
        return SimpleNamespace(returncode=1, stderr="", stdout="")

    monkeypatch.setattr(LAUNCH, "_run", fake_run)
    result = LAUNCH.cancel_and_prove(
        "42",
        "vmvm-v4-preflight-" + "a" * 24,
        set(),
        candidate_provenance="sbatch_stdout",
    )
    controls = [command for command in calls if command[0] == "/usr/bin/scancel"]
    assert controls == [["/usr/bin/scancel", "-M", LAUNCH.CLUSTER, "42"]]
    assert result["terminal_proved"] is False


def test_precontrol_conflict_after_identity_proof_forbids_cancel(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(LAUNCH, "_identity_probe", lambda *args: ("converged", set()))
    monkeypatch.setattr(
        LAUNCH,
        "_terminal_snapshot",
        lambda *args: ("explicit_identity_conflict", {"UserId"}, ()),
    )
    monkeypatch.setattr(LAUNCH, "_run", lambda command, timeout=20: calls.append(list(command)))
    result = LAUNCH.cancel_and_prove(
        "42",
        "vmvm-v4-preflight-" + "a" * 24,
        set(),
        candidate_provenance="sbatch_stdout",
    )
    assert result["control_attempted"] is False
    assert result["explicit_conflict_fields"] == ["UserId"]
    assert calls == []


def test_success_commit_is_monotonic_across_post_chmod_failure(monkeypatch, tmp_path: Path) -> None:
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    for name in (
        ".writer.lock",
        "job_authorization.json",
        "launch_intent.json",
        "slurm_environment.bin",
    ):
        (reservation / name).write_bytes(b"x")
    monkeypatch.setattr(LAUNCH, "RESERVATION", reservation)
    calls = 0

    def injected_sync(path: Path) -> None:
        nonlocal calls
        del path
        calls += 1
        if calls == 2:
            raise OSError("post-commit")

    monkeypatch.setattr(LAUNCH, "_sync_directory", injected_sync)
    state = {"committed": False}
    with pytest.raises(OSError, match="post-commit"):
        LAUNCH._publish_success(
            receipt={"state": "submitted"},
            permit_body={"state": "activated"},
            commit_state=state,
        )
    assert state == {"committed": True}
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    assert (reservation / "submission_receipt.json").is_file()
    assert (reservation / "activation_permit.json").is_file()


def test_failure_publication_never_reopens_admitted_reservation(monkeypatch, tmp_path: Path) -> None:
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    (reservation / "submission_receipt.json").write_bytes(b"sealed")
    reservation.chmod(0o500)
    monkeypatch.setattr(LAUNCH, "RESERVATION", reservation)
    LAUNCH._publish_failure("injected", "42", None)
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    assert not (reservation / "submission_failure.json").exists()


def test_wrapper_gate_bound_and_bundle_inventory_are_static() -> None:
    source = (ROOT / "run_vmvm_task_free_v2.sbatch").read_text()
    assert LAUNCH.WRAPPER_GATE_TIMEOUT_SECONDS > (LAUNCH.QUERY_TIMEOUT_SECONDS + LAUNCH.ACTIVATION_TIMEOUT_SECONDS + 30)
    assert "DIAG_WRAPPER_GATE_TIMEOUT_SECONDS != 900" in source
    assert "${#bundle_entries[@]} == 6" in source
    assert "DIAG_AUTHORIZATION_FILE_SHA256" in source
    assert "&& ! -e $DIAG_SCRATCH_ROOT && ! -L $DIAG_SCRATCH_ROOT" in source
    assert "device_only" in source
    assert "multiple" in source


def test_combined_pem_profile_is_narrow() -> None:
    def block(label: bytes, payload: bytes = b"x") -> bytes:
        import base64

        return b"-----BEGIN " + label + b"-----\n" + base64.b64encode(payload) + b"\n-----END " + label + b"-----\n"

    combined = block(b"CERTIFICATE") + block(b"CERTIFICATE", b"y") + block(b"RSA PRIVATE KEY")
    assert LAUNCH._pem_profile(combined) == "combined"
    assert LAUNCH._pem_profile(combined + block(b"CERTIFICATE")) == "other"
    assert LAUNCH._pem_profile(block(b"EC PRIVATE KEY")) == "other"
    assert LAUNCH._pem_profile(b"prefix" + combined) == "invalid"


def test_counterbalance_has_four_repetitions_and_balanced_positions() -> None:
    assert PROBE.REPETITIONS == 4
    assert PROBE.CELL_COUNT == 48
    assert [order[0] for order in PROBE.MODE_ORDERS].count("absent") == 2
    assert [order[0] for order in PROBE.MODE_ORDERS].count("present") == 2
    assert all(set(order) == set(PROBE.MODES) for order in PROBE.MODE_ORDERS)


def test_causal_assessment_uses_construction_phase_not_terminal_state() -> None:
    results = []
    for stage in PROBE.STAGES:
        for pair_index, order in enumerate(PROBE.MODE_ORDERS):
            for order_position, mode in enumerate(order):
                metadata = PROBE._empty_phase_metadata(True)
                if mode == "present":
                    metadata["phase_counts"] = {"backend_ready": 1}
                results.append(
                    PROBE._result_payload(
                        mode=mode,
                        stage=stage,
                        state="failed",
                        failure="runtime_other",
                        cleanup_complete=True,
                        elapsed_seconds=0,
                        pair_index=pair_index,
                        order_position=order_position,
                        phase_metadata=metadata,
                    )
                )
    summary = PROBE.summarize_stage_results(results)
    assert set(summary["causal_assessment"].values()) == {"x2p_present_construction_benefit"}
    assert all(
        contrasts == {"absent_failed__present_failed": PROBE.REPETITIONS}
        for contrasts in summary["outcome_contrasts"].values()
    )


def test_direct_client_uses_the_same_lease_attempt_budget(tmp_path: Path) -> None:
    starts = 0

    class FailingLease:
        proc = None
        session_identity_sha256 = None

        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def start(self) -> None:
            nonlocal starts
            starts += 1
            raise RuntimeError("vacli failed to start")

        def wait_for_tunnel(self) -> int:
            raise AssertionError

        def cleanup(self) -> None:
            return None

    audit = PROBE.LeaseAudit()
    tracked = audit.tracking_lease_type(FailingLease)
    passed, failure, cleaned = PROBE.execute_direct_client(
        lease_type=tracked,
        wait_for_sshd=lambda *args, **kwargs: None,
        scratch=tmp_path,
        audit=audit,
    )
    assert (passed, failure, cleaned) == (False, "backend_lease", True)
    assert starts == PROBE.LEASE_ATTEMPT_LIMIT
    assert audit.lease_attempts == PROBE.LEASE_ATTEMPT_LIMIT


def test_release_verification_waits_a_full_ttl_after_cleanup() -> None:
    class ExitedProcess:
        def poll(self) -> int:
            return 0

    clock = [10.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    audit = PROBE.LeaseAudit()
    audit.lease_attempts = 1
    audit._leases[1] = {
        "cleanup_at": 10.0,
        "lease": object(),
        "process": ExitedProcess(),
        "process_group": None,
        "session_identity_sha256": "a" * 64,
    }
    assert audit.verify_releases(monotonic=lambda: clock[0], sleeper=sleep) is True
    assert sleeps == [PROBE.LEASE_TTL_SECONDS + PROBE.RELEASE_GRACE_SECONDS]
    assert audit.metadata(True)["release_verified"] is True


def test_timeout_release_verification_requires_absent_process_group_for_ttl(
    monkeypatch,
) -> None:
    clock = [0.0]
    sleeps: list[float] = []
    monkeypatch.setattr(PROBE, "_process_group_absent", lambda process_group: True)

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    assert PROBE.verify_timeout_release(42, monotonic=lambda: clock[0], sleeper=sleep)
    assert sum(sleeps) == PROBE.LEASE_TTL_SECONDS + PROBE.RELEASE_GRACE_SECONDS


def test_external_renewer_journal_verifies_every_separate_process_group(monkeypatch, tmp_path: Path) -> None:
    events = [
        {
            "artifact_type": "vmvm_renewer_journal_event_v2",
            "event": "audit_started",
            "sequence": 0,
        }
    ]
    sequence = 1
    for operation_id, pid in enumerate((2_000_000_001, 2_000_000_002)):
        events.extend(
            [
                {
                    "artifact_type": "vmvm_renewer_journal_event_v2",
                    "event": "operation_started",
                    "lease_id": 100 + operation_id,
                    "operation": "start" if operation_id == 0 else "restart",
                    "operation_id": operation_id,
                    "sequence": sequence,
                },
                {
                    "artifact_type": "vmvm_renewer_journal_event_v2",
                    "event": "renewer_observed",
                    "lease_id": 100 + operation_id,
                    "operation": "start" if operation_id == 0 else "restart",
                    "operation_id": operation_id,
                    "pid": pid,
                    "process_group": pid,
                    "running": False,
                    "sequence": sequence + 1,
                    "start_ticks": None,
                },
                {
                    "artifact_type": "vmvm_renewer_journal_event_v2",
                    "event": "operation_finished",
                    "lease_id": 100 + operation_id,
                    "operation": "start" if operation_id == 0 else "restart",
                    "operation_id": operation_id,
                    "outcome": "process_observed",
                    "sequence": sequence + 2,
                },
            ]
        )
        sequence += 3
    journal = tmp_path / "renewer.jsonl"
    journal.write_bytes(b"".join(PROBE.canonical_json(event) + b"\n" for event in events))
    journal.chmod(0o600)
    descriptor = os.open(journal, os.O_RDWR | os.O_APPEND)
    observed_groups: set[int] = set()
    clock = [0.0]

    def group_absent(process_group: int) -> bool:
        observed_groups.add(process_group)
        return True

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(PROBE, "_process_group_absent", group_absent)
    monkeypatch.setattr(PROBE, "_process_identity_absent", lambda *args: True)
    try:
        assert PROBE.verify_external_renewer_release(
            descriptor,
            2_000_000_003,
            monotonic=lambda: clock[0],
            sleeper=sleep,
        )
    finally:
        os.close(descriptor)
    assert observed_groups == {2_000_000_001, 2_000_000_002, 2_000_000_003}


def test_lease_audit_journals_initial_and_resumed_renewers(tmp_path: Path) -> None:
    class ExitedProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self) -> int:
            return 0

    class Lease:
        def __init__(self) -> None:
            self.proc = None

        def start(self) -> None:
            self.proc = ExitedProcess(2_000_000_011)

        def restart_tunnel(self) -> int:
            self.proc = ExitedProcess(2_000_000_012)
            return 10000

        def cleanup(self) -> None:
            return None

    journal = tmp_path / "renewer.jsonl"
    descriptor = os.open(
        journal,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_APPEND,
        0o600,
    )
    try:
        audit = PROBE.LeaseAudit(descriptor)
        tracked_type = audit.tracking_lease_type(Lease)
        lease = tracked_type()
        lease.start()
        assert lease.restart_tunnel() == 10000
        lease.cleanup()
        assert audit.verify_releases(
            monotonic=lambda: 10**12,
            sleeper=lambda seconds: pytest.fail(f"unexpected sleep: {seconds}"),
        )
        identities = PROBE._journal_process_identities(descriptor, require_complete=True)
    finally:
        os.close(descriptor)
    assert identities == {
        (2_000_000_011, 2_000_000_011, None),
        (2_000_000_012, 2_000_000_012, None),
    }


def test_external_renewer_journal_fails_closed_when_spawn_is_unjournaled(
    tmp_path: Path,
) -> None:
    events = [
        {
            "artifact_type": "vmvm_renewer_journal_event_v2",
            "event": "audit_started",
            "sequence": 0,
        },
        {
            "artifact_type": "vmvm_renewer_journal_event_v2",
            "event": "operation_started",
            "lease_id": 100,
            "operation": "start",
            "operation_id": 0,
            "sequence": 1,
        },
    ]
    journal = tmp_path / "renewer.jsonl"
    journal.write_bytes(b"".join(PROBE.canonical_json(event) + b"\n" for event in events))
    journal.chmod(0o600)
    descriptor = os.open(journal, os.O_RDWR | os.O_APPEND)
    try:
        assert not PROBE.verify_external_renewer_release(descriptor, 2_000_000_003)
    finally:
        os.close(descriptor)


def test_bound_directory_rejects_rename_replacement(tmp_path: Path) -> None:
    original = tmp_path / "root"
    original.mkdir()
    descriptor = os.open(original, os.O_RDONLY | os.O_DIRECTORY)
    identity = PROBE.descriptor_identity(descriptor)
    moved = tmp_path / "moved"
    original.rename(moved)
    original.mkdir()
    try:
        with pytest.raises(PROBE.DiagnosticError, match="source_binding_invalid"):
            PROBE.open_bound_directory(original, identity)
        assert PROBE.descriptor_identity(descriptor) == identity
    finally:
        os.close(descriptor)


def test_bundle_file_is_read_from_bound_dirfd_after_path_swap(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    trusted = bundle / "probe.py"
    trusted.write_bytes(b"trusted\n")
    trusted.chmod(0o500)
    descriptor = os.open(bundle, os.O_RDONLY | os.O_DIRECTORY)
    moved = tmp_path / "moved"
    bundle.rename(moved)
    bundle.mkdir()
    replacement = bundle / "probe.py"
    replacement.write_bytes(b"replacement\n")
    replacement.chmod(0o500)
    try:
        assert LAUNCH.stable_file_at(descriptor, "probe.py", mode=0o500) == b"trusted\n"
    finally:
        os.close(descriptor)


def test_site_inventory_binds_content_and_rejects_symlinks(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    package = site / "package.py"
    package.write_bytes(b"first")
    descriptor = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    try:
        first = PROBE.directory_manifest(descriptor, expected_owner_uid=os.getuid())
        package.write_bytes(b"second")
        second = PROBE.directory_manifest(descriptor, expected_owner_uid=os.getuid())
        assert first["manifest_sha256"] != second["manifest_sha256"]
        (site / "link.py").symlink_to(package)
        with pytest.raises(PROBE.DiagnosticError, match="site_binding_invalid"):
            PROBE.directory_manifest(descriptor, expected_owner_uid=os.getuid())
    finally:
        os.close(descriptor)


def test_source_attestation_rejects_index_flags_and_blob_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    git("init", "-q")
    git("config", "user.email", "diagnostic@example.invalid")
    git("config", "user.name", "Diagnostic Test")
    tracked = repository / "tracked.py"
    tracked.write_text("VALUE = 1\n")
    git("add", "tracked.py")
    git("commit", "-qm", "fixture")
    revision = git("rev-parse", "HEAD")
    git("checkout", "-q", "--detach", revision)
    descriptor = os.open(repository, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for module in (LAUNCH, PROBE, FINALIZE):
            module._attest_git_repository(descriptor, expected_revision=revision)
        git("update-index", "--assume-unchanged", "tracked.py")
        tracked.write_text("VALUE = 2\n")
        for module in (LAUNCH, PROBE, FINALIZE):
            with pytest.raises(
                (LAUNCH.LaunchError, PROBE.DiagnosticError, FINALIZE.FinalizeError),
                match="source_binding_invalid|authorization_invalid",
            ):
                module._attest_git_repository(descriptor, expected_revision=revision)
        git("update-index", "--no-assume-unchanged", "tracked.py")
        for module in (LAUNCH, PROBE, FINALIZE):
            with pytest.raises(
                (LAUNCH.LaunchError, PROBE.DiagnosticError, FINALIZE.FinalizeError),
                match="source_binding_invalid|authorization_invalid",
            ):
                module._attest_git_repository(descriptor, expected_revision=revision)
        tracked.write_text("VALUE = 1\n")
        git("update-index", "--skip-worktree", "tracked.py")
        for module in (LAUNCH, PROBE, FINALIZE):
            with pytest.raises(
                (LAUNCH.LaunchError, PROBE.DiagnosticError, FINALIZE.FinalizeError),
                match="source_binding_invalid|authorization_invalid",
            ):
                module._attest_git_repository(descriptor, expected_revision=revision)
    finally:
        os.close(descriptor)


def test_finalizer_attests_every_submodule_and_derives_exact_source_snapshot(monkeypatch, tmp_path: Path) -> None:
    source, revisions = build_git_source_fixture(tmp_path)
    for module in (PROBE, FINALIZE):
        monkeypatch.setattr(module, "SOURCE_REVISION", revisions["revision"])
        monkeypatch.setattr(module, "SOURCE_TREE", revisions["tree"])
        monkeypatch.setattr(module, "VERIFIERS_REVISION", revisions["verifiers"])
        monkeypatch.setattr(module, "RENDERERS_REVISION", revisions["renderers"])
        monkeypatch.setattr(module, "PYDANTIC_CONFIG_REVISION", revisions["pydantic_config"])
        monkeypatch.setattr(module, "VMVM_SHA256", revisions["vmvm"])
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    scratch = tmp_path / "scratch"
    site = tmp_path / "site"
    scratch.mkdir(mode=0o700)
    site.mkdir()
    (site / "runtime.py").write_text("VALUE = 1\n")
    site_fd = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    try:
        finalizer_records = FINALIZE._attest_imported_source(source_fd)
        expected_source = FINALIZE._source_snapshot_commitment(finalizer_records)
        expected_site = PROBE.directory_manifest(site_fd, expected_owner_uid=os.getuid())
        _, _, observed_source, _ = PROBE.create_execution_snapshot(
            source_fd,
            site_fd,
            scratch,
            expected_site,
        )
        assert observed_source == expected_source
        subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(source / "deps/verifiers"),
                "update-index",
                "--skip-worktree",
                "verifiers.py",
            ],
            check=True,
        )
        with pytest.raises(FINALIZE.FinalizeError, match="authorization_invalid"):
            FINALIZE._attest_imported_source(source_fd)
    finally:
        os.close(site_fd)
        os.close(source_fd)


def test_finalizer_rejects_an_empty_git_source(tmp_path: Path) -> None:
    repository = tmp_path / "empty"
    repository.mkdir()
    for arguments in (
        ("init", "-q"),
        ("config", "user.email", "fixture@example.invalid"),
        ("config", "user.name", "Fixture"),
        ("commit", "--allow-empty", "-qm", "empty"),
    ):
        subprocess.run(["/usr/bin/git", "-C", str(repository), *arguments], check=True)
    revision = subprocess.run(
        ["/usr/bin/git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["/usr/bin/git", "-C", str(repository), "checkout", "--detach", "-q"],
        check=True,
    )
    descriptor = os.open(repository, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FINALIZE.FinalizeError, match="authorization_invalid"):
            FINALIZE._attest_git_repository(descriptor, expected_revision=revision)
    finally:
        os.close(descriptor)


def test_cli_source_binding_rejects_swap_before_supervisor(tmp_path: Path) -> None:
    source = tmp_path / "source"
    site = tmp_path / "site"
    output_parent = tmp_path / "output-parent"
    source.mkdir()
    site.mkdir()
    output_parent.mkdir()
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    site_fd = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    output_fd = os.open(output_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        environment = {
            "DIAG_SOURCE_IDENTITY": ":".join(str(value) for value in PROBE.descriptor_identity(source_fd).values()),
            "PYTHON_SITE_X86_64_IDENTITY": ":".join(
                str(value) for value in PROBE.descriptor_identity(site_fd).values()
            ),
            "DIAG_OUTPUT_PARENT_IDENTITY": ":".join(
                str(value) for value in PROBE.descriptor_identity(output_fd).values()
            ),
        }
        source.rename(tmp_path / "source-original")
        source.mkdir()
        args = SimpleNamespace(source_root=source, site_root=site)
        with pytest.raises(PROBE.DiagnosticError, match="source_binding_invalid"):
            PROBE.validate_cli_paths(args, environment, require_output=False)
    finally:
        os.close(source_fd)
        os.close(site_fd)
        os.close(output_fd)


def test_cli_paths_require_inherited_fds_and_bind_output_parent(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    site = tmp_path / "site"
    output_parent = tmp_path / "output-parent"
    source.mkdir()
    site.mkdir()
    output_parent.mkdir()
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    site_fd = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    output_fd = os.open(output_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        site_inventory = PROBE.directory_manifest(site_fd, expected_owner_uid=os.getuid())
        environment = {
            "DIAG_SOURCE_IDENTITY": ":".join(str(value) for value in PROBE.descriptor_identity(source_fd).values()),
            "PYTHON_SITE_X86_64_IDENTITY": ":".join(
                str(value) for value in PROBE.descriptor_identity(site_fd).values()
            ),
            "PYTHON_SITE_X86_64_ENTRY_COUNT": str(site_inventory["entry_count"]),
            "PYTHON_SITE_X86_64_MANIFEST_SHA256": str(site_inventory["manifest_sha256"]),
            "PYTHON_SITE_X86_64_TOTAL_BYTES": str(site_inventory["total_bytes"]),
            "DIAG_OUTPUT_PARENT_IDENTITY": ":".join(
                str(value) for value in PROBE.descriptor_identity(output_fd).values()
            ),
        }
        monkeypatch.setattr(PROBE, "EXPECTED_OUTPUT_ROOT", Path("/authorized/output"))
        monkeypatch.setattr(PROBE, "EXPECTED_COMPLETION_RECEIPT", Path("/authorized/receipt"))
        monkeypatch.setattr(PROBE, "EXPECTED_SCRATCH_ROOT", Path("/authorized/scratch"))
        bound_parent = Path(f"/proc/self/fd/{output_fd}")
        args = SimpleNamespace(
            source_root=Path(f"/proc/self/fd/{source_fd}"),
            site_root=Path(f"/proc/self/fd/{site_fd}"),
            output_dir=bound_parent / "output",
            completion_receipt=bound_parent / "receipt",
            scratch_root=Path("/authorized/scratch"),
        )
        PROBE.validate_cli_paths(args, environment, require_output=True)
        args.source_root = source
        with pytest.raises(PROBE.DiagnosticError, match="source_binding_invalid"):
            PROBE.validate_cli_paths(args, environment, require_output=True)
    finally:
        os.close(output_fd)
        os.close(site_fd)
        os.close(source_fd)


def test_python_subprocess_executes_script_and_output_through_inherited_fds(tmp_path: Path) -> None:
    script = tmp_path / "fd-check.py"
    source = tmp_path / "source"
    site = tmp_path / "site"
    output = tmp_path / "output"
    source.mkdir()
    site.mkdir()
    output.mkdir()
    script.write_text(
        "import os,sys\n"
        "assert all(value.startswith('/proc/self/fd/') for value in sys.argv[1:])\n"
        "for value in sys.argv[1:]: os.fstat(int(value.rsplit('/',1)[1]))\n"
        "fd=os.open('fd-proof',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400,dir_fd=int(sys.argv[3].rsplit('/',1)[1]))\n"
        "os.write(fd,b'bound\\n');os.fsync(fd);os.close(fd)\n"
    )
    script.chmod(0o500)
    descriptors = [
        os.open(script, os.O_RDONLY),
        os.open(source, os.O_RDONLY | os.O_DIRECTORY),
        os.open(site, os.O_RDONLY | os.O_DIRECTORY),
        os.open(output, os.O_RDONLY | os.O_DIRECTORY),
        os.open(Path(shutil.which("uv") or pytest.fail("host uv unavailable")), os.O_RDONLY),
    ]
    try:
        result = subprocess.run(
            [
                f"/proc/self/fd/{descriptors[4]}",
                "run",
                "--no-project",
                "--offline",
                "--python",
                sys.executable,
                "python3",
                "-I",
                "-S",
                "-B",
                f"/proc/self/fd/{descriptors[0]}",
                f"/proc/self/fd/{descriptors[1]}",
                f"/proc/self/fd/{descriptors[2]}",
                f"/proc/self/fd/{descriptors[3]}",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            pass_fds=tuple(descriptors),
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    assert result.returncode == 0
    assert not result.stdout and not result.stderr
    assert (output / "fd-proof").read_bytes() == b"bound\n"


def test_descriptor_reader_uses_pread_and_rejects_alias_or_inode_substitution(tmp_path: Path) -> None:
    authorized = tmp_path / "authorized.py"
    substituted = tmp_path / "substituted.py"
    authorized.write_bytes(b"authorized bytes\n")
    substituted.write_bytes(authorized.read_bytes())
    authorized.chmod(0o500)
    substituted.chmod(0o500)
    descriptor = os.open(authorized, os.O_RDONLY)
    authorized_fd = os.open(authorized, os.O_RDONLY)
    substituted_fd = os.open(substituted, os.O_RDONLY)
    digest = hashlib.sha256(authorized.read_bytes()).hexdigest()
    try:
        os.lseek(descriptor, 7, os.SEEK_SET)
        assert (
            PROBE._stable_descriptor_bytes(
                Path(f"/proc/self/fd/{descriptor}"),
                authorized_fd=authorized_fd,
                authorized_path=authorized,
                mode=0o500,
                expected_sha256=digest,
            )
            == b"authorized bytes\n"
        )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 7
        with pytest.raises(PROBE.DiagnosticError, match="source_binding_invalid"):
            PROBE._stable_descriptor_bytes(
                Path(f"/proc/self/fd/{descriptor}"),
                authorized_fd=substituted_fd,
                authorized_path=authorized,
                mode=0o500,
                expected_sha256=digest,
            )
        with pytest.raises(PROBE.DiagnosticError, match="source_binding_invalid"):
            PROBE._stable_descriptor_bytes(
                Path(f"/proc/self/fd/{descriptor}"),
                authorized_fd=authorized_fd,
                authorized_path=substituted,
                mode=0o500,
                expected_sha256=digest,
            )
        assert PROBE.inherited_descriptor(Path(f"/proc/self/fd/0{descriptor}")) is None
    finally:
        os.close(substituted_fd)
        os.close(authorized_fd)
        os.close(descriptor)


def test_probe_execution_binding_requires_sealed_named_memfds(tmp_path: Path) -> None:
    probe_raw = b"print('probe')\n"
    uv_raw = b"#!/usr/bin/python3\nprint('uv')\n"
    probe_fd = sealed_memfd(probe_raw, name="vmvm-probe-v2", mode=0o500)
    uv_fd = sealed_memfd(uv_raw, name="vmvm-uv-v2", mode=0o755)
    environment = {
        "DIAG_EXEC_PROBE_FD": str(probe_fd),
        "DIAG_EXEC_UV_FD": str(uv_fd),
        "DIAG_PROBE_SHA256": hashlib.sha256(probe_raw).hexdigest(),
    }
    try:
        PROBE._validate_execution_memfds(
            environment,
            Path(f"/proc/self/fd/{probe_fd}"),
            require_uv=False,
        )
        with pytest.raises(PROBE.DiagnosticError, match="source_binding_invalid"):
            PROBE._validate_execution_memfds(
                {**environment, "DIAG_PROBE_SHA256": "0" * 64},
                Path(f"/proc/self/fd/{probe_fd}"),
                require_uv=False,
            )
        ordinary = tmp_path / "ordinary.py"
        ordinary.write_bytes(probe_raw)
        ordinary.chmod(0o500)
        ordinary_fd = os.open(ordinary, os.O_RDONLY)
        try:
            with pytest.raises(PROBE.DiagnosticError, match="source_binding_invalid"):
                PROBE._validate_execution_memfds(
                    {**environment, "DIAG_EXEC_PROBE_FD": str(ordinary_fd)},
                    Path(f"/proc/self/fd/{ordinary_fd}"),
                    require_uv=False,
                )
        finally:
            os.close(ordinary_fd)
    finally:
        os.close(uv_fd)
        os.close(probe_fd)


def test_sealed_probe_and_uv_execute_after_originals_mutate_and_restore(monkeypatch, tmp_path: Path) -> None:
    authorized_marker = tmp_path / "authorized"
    malicious_marker = tmp_path / "malicious"
    probe_path = tmp_path / "probe.py"
    uv_path = tmp_path / "uv"
    probe_raw = b"import pathlib,sys\npathlib.Path(sys.argv[1]).write_text('authorized\\n')\n"
    uv_raw = (
        b"#!/usr/bin/python3\n"
        b"import os,sys\n"
        b"os.execve('/usr/bin/python3',['/usr/bin/python3','-I','-S','-B',*sys.argv[1:]],dict(os.environ))\n"
    )
    probe_path.write_bytes(probe_raw)
    probe_path.chmod(0o500)
    uv_path.write_bytes(uv_raw)
    uv_path.chmod(0o755)
    probe_source_fd = os.open(probe_path, os.O_RDONLY)
    uv_source_fd = os.open(uv_path, os.O_RDONLY)
    probe_fd = sealed_memfd(os.pread(probe_source_fd, len(probe_raw), 0), name="vmvm-probe-v2", mode=0o500)
    uv_fd = sealed_memfd(os.pread(uv_source_fd, len(uv_raw), 0), name="vmvm-uv-v2", mode=0o755)
    try:
        assert (
            hashlib.sha256(os.pread(probe_source_fd, len(probe_raw), 0)).hexdigest()
            == hashlib.sha256(probe_raw).hexdigest()
        )
        assert hashlib.sha256(os.pread(uv_source_fd, len(uv_raw), 0)).hexdigest() == hashlib.sha256(uv_raw).hexdigest()
        monkeypatch.setattr(PROBE, "X86_UV_SHA256", hashlib.sha256(uv_raw).hexdigest())
        PROBE._validate_execution_memfds(
            {
                "DIAG_EXEC_PROBE_FD": str(probe_fd),
                "DIAG_EXEC_UV_FD": str(uv_fd),
                "DIAG_PROBE_SHA256": hashlib.sha256(probe_raw).hexdigest(),
            },
            Path(f"/proc/self/fd/{probe_fd}"),
            require_uv=True,
        )
        probe_path.chmod(0o700)
        probe_path.write_text(f"import pathlib\npathlib.Path({str(malicious_marker)!r}).touch()\n")
        probe_path.chmod(0o500)
        uv_path.chmod(0o700)
        uv_path.write_text(f"#!/usr/bin/python3\nimport pathlib\npathlib.Path({str(malicious_marker)!r}).touch()\n")
        uv_path.chmod(0o755)
        result = subprocess.run(
            [f"/proc/self/fd/{uv_fd}", f"/proc/self/fd/{probe_fd}", str(authorized_marker)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            pass_fds=(probe_fd, uv_fd),
            timeout=10,
        )
        probe_path.chmod(0o700)
        probe_path.write_bytes(probe_raw)
        probe_path.chmod(0o500)
        uv_path.chmod(0o700)
        uv_path.write_bytes(uv_raw)
        uv_path.chmod(0o755)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert authorized_marker.read_text() == "authorized\n"
        assert not malicious_marker.exists()
    finally:
        os.close(uv_fd)
        os.close(probe_fd)
        os.close(uv_source_fd)
        os.close(probe_source_fd)


def test_finalizer_subprocess_requires_and_executes_its_sealed_bytes(tmp_path: Path) -> None:
    original = tmp_path / "finalize_vmvm_task_free_v2.py"
    raw = (ROOT / "finalize_vmvm_task_free_v2.py").read_bytes()
    original.write_bytes(raw)
    original.chmod(0o500)
    digest = hashlib.sha256(raw).hexdigest()
    descriptor = sealed_memfd(raw, name="vmvm-finalizer-v2", mode=0o500)
    malicious_marker = tmp_path / "malicious-finalizer"
    binding = FINALIZE.validate_finalizer_execution(
        Path(f"/proc/self/fd/{descriptor}"),
        bundle_root=tmp_path,
        expected_sha256=digest,
    )
    assert binding["sha256"] == digest
    original.chmod(0o700)
    original.write_text(f"from pathlib import Path\nPath({str(malicious_marker)!r}).touch()\n")
    original.chmod(0o500)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                f"/proc/self/fd/{descriptor}",
                "--authorization",
                str(tmp_path / "missing.json"),
                "--authorization-file-sha256",
                "0" * 64,
                "--bundle-root",
                str(tmp_path),
                "--self-sha256",
                digest,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            pass_fds=(descriptor,),
            timeout=10,
        )
        original.chmod(0o700)
        original.write_bytes(raw)
        original.chmod(0o500)
        assert result.returncode == 2
        assert result.stderr == b'{"code":"finalizer_failed","state":"failed"}\n'
        assert not malicious_marker.exists()
        pathname_result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(original),
                "--authorization",
                str(tmp_path / "missing.json"),
                "--authorization-file-sha256",
                "0" * 64,
                "--bundle-root",
                str(tmp_path),
                "--self-sha256",
                digest,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert pathname_result.returncode == 2
        assert pathname_result.stderr == b'{"code":"finalizer_execution_invalid","state":"failed"}\n'
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "failure_case",
    ("success", "device_only", "multiple", "unreadable", "probe_rejected", "probe_response"),
)
def test_real_wrapper_emits_only_static_preflight_telemetry(tmp_path: Path, failure_case: str) -> None:
    base = tmp_path / "base"
    source, revisions = build_git_source_fixture(tmp_path)
    expected_source = base / "sources/prime-rl-a09a9a189-v21"
    expected_source.parent.mkdir(parents=True)
    source.rename(expected_source)
    site = base / "python_x86_64"
    site.mkdir(parents=True)
    (site / "runtime.py").write_text("VALUE = 1\n")
    diagnostics = base / "diagnostics"
    diagnostics.mkdir()
    output = diagnostics / "vmvm_v21_task_free_preflight_a09a9a189_v4"
    reservation = Path(f"{output}.launch-reservation")
    completion = Path(f"{output}.external-completion.json")
    scratch = tmp_path / "scratch"
    log_root = base / "logs/vmvm_v21_task_free_preflight_a09a9a189_v4"
    bundle = tmp_path / "bundle"
    bundle.mkdir(mode=0o700)
    bundle.chmod(0o700)

    uv_path = tmp_path / "uv"
    uv_path.write_text(
        "#!/usr/bin/python3\n"
        "import os,sys\n"
        "args=sys.argv[1:]\n"
        "if '--validate-batch' in args:\n"
        f" reject={failure_case == 'probe_rejected'!r}\n"
        f" invalid_response={failure_case == 'probe_response'!r}\n"
        " if reject or invalid_response:\n"
        "  print(os.environ['X2P_ENV'])\n"
        "  print(os.environ['DIAG_SOURCE_ROOT'],file=sys.stderr)\n"
        "  raise SystemExit(2 if reject else 0)\n"
        " start=args.index('-I')\n"
        " os.execve('/usr/bin/python3',['/usr/bin/python3',*args[start:]],dict(os.environ))\n"
        "print('RAW_SUPERVISOR_OUTPUT_MUST_NOT_RUN',file=sys.stderr)\n"
        "raise SystemExit(91)\n"
    )
    uv_path.chmod(0o755)
    uv_sha = hashlib.sha256(uv_path.read_bytes()).hexdigest()

    probe_source = (ROOT / "probe_vmvm_task_free_v2.py").read_text()
    probe_replacements = {
        f'SOURCE_REVISION = "{PROBE.SOURCE_REVISION}"': f'SOURCE_REVISION = "{revisions["revision"]}"',
        f'SOURCE_TREE = "{PROBE.SOURCE_TREE}"': f'SOURCE_TREE = "{revisions["tree"]}"',
        f'VERIFIERS_REVISION = "{PROBE.VERIFIERS_REVISION}"': (f'VERIFIERS_REVISION = "{revisions["verifiers"]}"'),
        f'RENDERERS_REVISION = "{PROBE.RENDERERS_REVISION}"': (f'RENDERERS_REVISION = "{revisions["renderers"]}"'),
        f'PYDANTIC_CONFIG_REVISION = "{PROBE.PYDANTIC_CONFIG_REVISION}"': (
            f'PYDANTIC_CONFIG_REVISION = "{revisions["pydantic_config"]}"'
        ),
        f'VMVM_SHA256 = "{PROBE.VMVM_SHA256}"': f'VMVM_SHA256 = "{revisions["vmvm"]}"',
        f'X86_UV_SHA256 = "{PROBE.X86_UV_SHA256}"': f'X86_UV_SHA256 = "{uv_sha}"',
        'BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")': f"BASE = Path({str(base)!r})",
        'EXPECTED_SCRATCH_ROOT = Path("/tmp/vmvm-v21-task-free-preflight-v4")': (
            f"EXPECTED_SCRATCH_ROOT = Path({str(scratch)!r})"
        ),
        'environment["UV_BIN_X86_64"] != "/storage/home/tianhaowu/.local/x86_64/bin/uv"': (
            f'environment["UV_BIN_X86_64"] != {str(uv_path)!r}'
        ),
    }
    for old, new in probe_replacements.items():
        assert old in probe_source
        probe_source = probe_source.replace(old, new)
    probe_path = bundle / "probe_vmvm_task_free_v2.py"
    probe_path.write_text(probe_source)
    probe_path.chmod(0o500)

    wrapper_source = (ROOT / "run_vmvm_task_free_v2.sbatch").read_text()
    wrapper_replacements = {
        f"readonly SOURCE_REVISION={PROBE.SOURCE_REVISION}": f"readonly SOURCE_REVISION={revisions['revision']}",
        f"readonly SOURCE_TREE={PROBE.SOURCE_TREE}": f"readonly SOURCE_TREE={revisions['tree']}",
        f"readonly VERIFIERS_REVISION={PROBE.VERIFIERS_REVISION}": (
            f"readonly VERIFIERS_REVISION={revisions['verifiers']}"
        ),
        f"readonly RENDERERS_REVISION={PROBE.RENDERERS_REVISION}": (
            f"readonly RENDERERS_REVISION={revisions['renderers']}"
        ),
        f"readonly PYDANTIC_CONFIG_REVISION={PROBE.PYDANTIC_CONFIG_REVISION}": (
            f"readonly PYDANTIC_CONFIG_REVISION={revisions['pydantic_config']}"
        ),
        f"readonly VMVM_SHA256={PROBE.VMVM_SHA256}": f"readonly VMVM_SHA256={revisions['vmvm']}",
        f"readonly X86_UV_SHA256={PROBE.X86_UV_SHA256}": f"readonly X86_UV_SHA256={uv_sha}",
        "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64": str(site),
        "/storage/home/tianhaowu/.local/x86_64/bin/uv": str(uv_path),
    }
    for old, new in wrapper_replacements.items():
        assert old in wrapper_source
        wrapper_source = wrapper_source.replace(old, new)
    wrapper_path = bundle / "run_vmvm_task_free_v2.sbatch"
    wrapper_path.write_text(wrapper_source)
    wrapper_path.chmod(0o500)
    for name, mode in (
        ("README.md", 0o400),
        ("finalize_vmvm_task_free_v2.py", 0o500),
        ("launch_vmvm_task_free_v2.py", 0o500),
        ("test_vmvm_task_free_v2.py", 0o400),
    ):
        target = bundle / name
        target.write_bytes((ROOT / name).read_bytes())
        target.chmod(mode)

    def identity(path: Path) -> dict[str, int]:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return PROBE.descriptor_identity(descriptor)
        finally:
            os.close(descriptor)

    site_fd = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    try:
        site_inventory = PROBE.directory_manifest(site_fd, expected_owner_uid=os.getuid())
    finally:
        os.close(site_fd)
    bundle_records = {
        label: {
            "path": str(bundle / name),
            "sha256": hashlib.sha256((bundle / name).read_bytes()).hexdigest(),
        }
        for label, name in (
            ("finalizer", "finalize_vmvm_task_free_v2.py"),
            ("launcher", "launch_vmvm_task_free_v2.py"),
            ("probe", "probe_vmvm_task_free_v2.py"),
            ("readme", "README.md"),
            ("tests", "test_vmvm_task_free_v2.py"),
            ("wrapper", "run_vmvm_task_free_v2.sbatch"),
        )
    }
    tls_path = tmp_path / "tls.pem"
    tls_path.write_bytes(b"fixture-tls\n")
    tls_path.chmod(0o500)
    tls_record = {"path": str(tls_path), "sha256": hashlib.sha256(tls_path.read_bytes()).hexdigest()}
    x2p_values = {
        "X2P_ENV": "fixture-environment",
        "X2P_CFG_ENV": "fixture-configuration",
        "X2P_PROXY_URL": "https://fixture.invalid/proxy",
    }
    job_name = "vmvm-v4-preflight-" + "f" * 24
    launch_body = {
        "artifact_type": "vmvm_task_free_diagnostic_authorization_v2",
        "bundle": {**bundle_records, "root_identity": identity(bundle)},
        "credentials": {
            "tls": {name: tls_record for name in PROBE.TLS_NAMES},
            "x2p": {name: {"sha256": hashlib.sha256(value.encode()).hexdigest()} for name, value in x2p_values.items()},
        },
        "launch": {
            "account": "ram",
            "cluster": PROBE.EXPECTED_CLUSTER,
            "comment": "vmvm-v4-preflight:" + "f" * 24,
            "completion_receipt": str(completion),
            "cpus": 2,
            "job_name": job_name,
            "log_root": str(log_root),
            "memory": "8G",
            "nodes": 1,
            "output_parent_identity": identity(diagnostics),
            "output_root": str(output),
            "partition": "cpu_x86",
            "qos": "cpu_x86_lowest",
            "reservation": str(reservation),
            "scratch_root": str(scratch),
            "time_limit": "1-12:00:00",
        },
        "protocol": {
            "diagnostic_only": True,
            "preflight_only": True,
            "production_authorized": False,
        },
        "runtime": {
            "image": PROBE.IMAGE,
            "python_name": "python3",
            "site": {"inventory": site_inventory, "path": str(site), "root_identity": identity(site)},
            "uv": {"path": str(uv_path), "sha256": uv_sha},
            "vacli": {
                "path": "/public/fbpkgs/x86_64/vacli/stable/vacli",
                "resolved_path": PROBE.VACLI_RESOLVED,
                "sha256": PROBE.VACLI_SHA256,
            },
        },
        "schema_version": 2,
        "source": {
            "path": str(expected_source),
            "pydantic_config_revision": revisions["pydantic_config"],
            "renderers_revision": revisions["renderers"],
            "revision": revisions["revision"],
            "root_identity": identity(expected_source),
            "tree": revisions["tree"],
            "verifiers_revision": revisions["verifiers"],
            "vmvm_sha256": revisions["vmvm"],
        },
        "state": "approved",
    }
    launch_sha = PROBE.sha256_bytes(PROBE.canonical_json(launch_body))
    launch_authorization = {**launch_body, "authorization_sha256": launch_sha}
    launch_raw = PROBE.canonical_json(launch_authorization) + b"\n"
    launch_path = tmp_path / "launch-authorization.json"
    launch_path.write_bytes(launch_raw)
    launch_path.chmod(0o400)
    launch_file_sha = PROBE.sha256_bytes(launch_raw)

    reservation.mkdir(mode=0o700)
    reservation.chmod(0o700)
    writer_lock = reservation / ".writer.lock"
    writer_lock.write_bytes(b"")
    writer_lock.chmod(0o600)
    reservation_identity = identity(reservation)
    reservation_identity["mode"] = 0o500
    job = {"cluster": PROBE.EXPECTED_CLUSTER, "job_id": "42", "job_name": job_name}
    job_authorization = {
        "artifact_type": "vmvm_task_free_job_authorization_v2",
        "authorization_file_sha256": launch_file_sha,
        "authorization_sha256": launch_sha,
        "job": job,
        "production_authorized": False,
        "state": "held_verified",
    }
    job_authorization_raw = PROBE.canonical_json(job_authorization) + b"\n"
    job_authorization_sha = PROBE.sha256_bytes(job_authorization_raw)
    identity_string = lambda value: ":".join(str(value[name]) for name in ("device", "inode", "mode", "owner_uid"))
    exported = {
        "DIAG_ACTIVATION_PERMIT": str(reservation / "activation_permit.json"),
        "DIAG_AUTHORIZATION": str(launch_path),
        "DIAG_AUTHORIZATION_FILE_SHA256": launch_file_sha,
        "DIAG_AUTHORIZATION_SHA256": launch_sha,
        "DIAG_BUNDLE_IDENTITY": identity_string(identity(bundle)),
        "DIAG_BUNDLE_ROOT": str(bundle),
        "DIAG_COMPLETION_RECEIPT": str(completion),
        "DIAG_FINALIZER_PATH": bundle_records["finalizer"]["path"],
        "DIAG_FINALIZER_SHA256": bundle_records["finalizer"]["sha256"],
        "DIAG_JOB_AUTHORIZATION": str(reservation / "job_authorization.json"),
        "DIAG_JOB_NAME": job_name,
        "DIAG_LAUNCHER_PATH": bundle_records["launcher"]["path"],
        "DIAG_LAUNCHER_SHA256": bundle_records["launcher"]["sha256"],
        "DIAG_OUTPUT_PARENT_IDENTITY": identity_string(identity(diagnostics)),
        "DIAG_OUTPUT_ROOT": str(output),
        "DIAG_PROBE_PATH": bundle_records["probe"]["path"],
        "DIAG_PROBE_SHA256": bundle_records["probe"]["sha256"],
        "DIAG_RESERVATION": str(reservation),
        "DIAG_RESERVATION_IDENTITY": identity_string(reservation_identity),
        "DIAG_SCRATCH_ROOT": str(scratch),
        "DIAG_SOURCE_IDENTITY": identity_string(identity(expected_source)),
        "DIAG_SOURCE_REVISION": revisions["revision"],
        "DIAG_SOURCE_ROOT": str(expected_source),
        "DIAG_SOURCE_TREE": revisions["tree"],
        "DIAG_SUBMISSION_RECEIPT": str(reservation / "submission_receipt.json"),
        "DIAG_VMVM_SHA256": revisions["vmvm"],
        "DIAG_WRAPPER_GATE_TIMEOUT_SECONDS": "900",
        "DIAG_WRAPPER_PATH": bundle_records["wrapper"]["path"],
        "DIAG_WRAPPER_SHA256": bundle_records["wrapper"]["sha256"],
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": PROBE.EXPECTED_OWNER,
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_BIN_X86_64": "python3",
        "PYTHON_SITE_X86_64": str(site),
        "PYTHON_SITE_X86_64_ENTRY_COUNT": str(site_inventory["entry_count"]),
        "PYTHON_SITE_X86_64_IDENTITY": identity_string(identity(site)),
        "PYTHON_SITE_X86_64_MANIFEST_SHA256": str(site_inventory["manifest_sha256"]),
        "PYTHON_SITE_X86_64_TOTAL_BYTES": str(site_inventory["total_bytes"]),
        "SLURM_EXPORT_ENV": "NONE",
        "TZ": "UTC",
        "USER": PROBE.EXPECTED_OWNER,
        "UV_BIN_X86_64": str(uv_path),
        "VACLI_BIN": "/public/fbpkgs/x86_64/vacli/stable/vacli",
        "VACLI_CONTAINER_PRIVILEGED": "1",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": str(PROBE.IMAGE_PULL_TIMEOUT_SECONDS),
        "VACLI_LEASE_RETRIES": str(PROBE.LEASE_ATTEMPT_LIMIT),
        "VACLI_MAX_CONCURRENT_LEASES": "1",
        "VACLI_MAX_PULL_RETRIES": str(PROBE.IMAGE_PULL_RETRY_LIMIT),
        **{name: str(tls_path) for name in PROBE.TLS_NAMES},
        **x2p_values,
    }
    environment_raw = b"".join(f"{name}={exported[name]}".encode() + b"\0" for name in sorted(exported))
    environment_sha = PROBE.sha256_bytes(environment_raw)
    launch_intent = {
        "artifact_type": "vmvm_task_free_launch_intent_v2",
        "authorization_file_sha256": launch_file_sha,
        "authorization_sha256": launch_sha,
        "bundle_sha256": {
            label: bundle_records[label]["sha256"] for label in ("finalizer", "launcher", "probe", "wrapper")
        },
        "environment_sha256": environment_sha,
        "job_name": job_name,
        "production_authorized": False,
        "state": "reserved",
    }
    telemetry = {
        "converged": True,
        "deadline_seconds": 1,
        "elapsed_milliseconds": 1,
        "explicit_conflict_fields": [],
        "final_mismatch_fields": [],
        "mismatch_occurrences": {},
        "polls": 2,
        "required_consecutive": 2,
    }
    submission_receipt = {
        "activation": telemetry,
        "artifact_type": "vmvm_task_free_submission_receipt_v2",
        "authorization_file_sha256": launch_file_sha,
        "authorization_sha256": launch_sha,
        "environment_sha256": environment_sha,
        "held": {
            **telemetry,
            "pre_authorization_mismatch_fields": [],
            "post_authorization_mismatch_fields": [],
        },
        "job": job,
        "job_authorization_sha256": job_authorization_sha,
        "production_authorized": False,
        "release_attempts": 1,
        "release_outcome": "completed",
        "state": "submitted",
        "submission_attempts": 1,
    }
    submission_raw = PROBE.canonical_json(submission_receipt) + b"\n"
    activation_permit = {
        "artifact_type": "vmvm_task_free_activation_permit_v2",
        "authorization_file_sha256": launch_file_sha,
        "authorization_sha256": launch_sha,
        "environment_sha256": environment_sha,
        "job_authorization_sha256": job_authorization_sha,
        "production_authorized": False,
        "state": "activated",
        "submission_receipt_sha256": PROBE.sha256_bytes(submission_raw),
    }
    for name, raw, mode in (
        ("activation_permit.json", PROBE.canonical_json(activation_permit) + b"\n", 0o400),
        ("job_authorization.json", job_authorization_raw, 0o400),
        ("launch_intent.json", PROBE.canonical_json(launch_intent) + b"\n", 0o400),
        ("slurm_environment.bin", environment_raw, 0o400),
        ("submission_receipt.json", submission_raw, 0o400),
    ):
        target = reservation / name
        target.write_bytes(raw)
        target.chmod(mode)
    reservation.chmod(0o500)

    raw_secret = "RAW_PRIVATE_CREDENTIAL_MUST_NOT_APPEAR"
    raw_missing_path = tmp_path / f"missing-{raw_secret}"
    if failure_case == "device_only":
        values = exported["DIAG_BUNDLE_IDENTITY"].split(":")
        values[0] = str(int(values[0]) + 1)
        exported["DIAG_BUNDLE_IDENTITY"] = ":".join(values)
    elif failure_case == "multiple":
        values = exported["DIAG_SOURCE_IDENTITY"].split(":")
        values[0] = str(int(values[0]) + 1)
        values[1] = str(int(values[1]) + 1)
        exported["DIAG_SOURCE_IDENTITY"] = ":".join(values)
    elif failure_case == "unreadable":
        exported["DIAG_SOURCE_ROOT"] = str(raw_missing_path)
    runtime_environment = {**exported, "SLURM_JOB_ID": "42", "SLURM_JOB_NAME": job_name}
    result = subprocess.run(
        [str(wrapper_path)],
        env=runtime_environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    expected_failure = {
        "device_only": (
            b'{"code":"diagnostic_job_failed","directory_identities":{"bundle":"device_only",'
            b'"output_parent":"match","reservation":"match","site":"match","source":"match"},'
            b'"stage":"directory_identity","state":"failed"}\n'
        ),
        "multiple": (
            b'{"code":"diagnostic_job_failed","directory_identities":{"bundle":"match",'
            b'"output_parent":"match","reservation":"match","site":"match","source":"multiple"},'
            b'"stage":"directory_identity","state":"failed"}\n'
        ),
        "unreadable": (
            b'{"code":"diagnostic_job_failed","directory_identities":{"bundle":"not_checked",'
            b'"output_parent":"not_checked","reservation":"not_checked","site":"not_checked",'
            b'"source":"unreadable"},"stage":"directory_open","state":"failed"}\n'
        ),
        "probe_rejected": (
            b'{"code":"diagnostic_job_failed","directory_identities":{"bundle":"match",'
            b'"output_parent":"match","reservation":"match","site":"match","source":"match"},'
            b'"stage":"probe_admission","state":"failed"}\n'
        ),
        "probe_response": (
            b'{"code":"diagnostic_job_failed","directory_identities":{"bundle":"match",'
            b'"output_parent":"match","reservation":"match","site":"match","source":"match"},'
            b'"stage":"probe_response","state":"failed"}\n'
        ),
    }
    if failure_case == "success":
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert result.stderr == b""
        assert result.stdout == (
            b'{"directory_identities":{"bundle":"match","output_parent":"match",'
            b'"reservation":"match","site":"match","source":"match"},'
            b'"stage":"prelease_admission","state":"passed"}\n'
        )
    else:
        assert result.returncode == 2
        assert result.stdout == b""
        assert result.stderr == expected_failure[failure_case]
    public_output = result.stdout + result.stderr
    assert raw_secret.encode() not in public_output
    assert str(raw_missing_path).encode() not in public_output
    assert str(expected_source).encode() not in public_output
    assert b"RAW_SUPERVISOR_OUTPUT_MUST_NOT_RUN" not in public_output
    assert all(value.encode() not in public_output for value in x2p_values.values())
    assert not output.exists()
    assert not completion.exists()
    assert not scratch.exists()


def test_execution_snapshot_defeats_mutate_restore_race(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    site = tmp_path / "site"
    scratch = tmp_path / "scratch"
    source_file = source / "environments/vmvm_tb_v2/backend.py"
    site_file = site / "dependency.py"
    source_file.parent.mkdir(parents=True)
    site.mkdir()
    scratch.mkdir(mode=0o700)
    scratch.chmod(0o700)
    source_raw = b"SOURCE = 'authorized'\n"
    site_raw = b"SITE = 'authorized'\n"
    source_file.write_bytes(source_raw)
    site_file.write_bytes(site_raw)
    digest = hashlib.sha1(
        f"blob {len(source_raw)}\0".encode() + source_raw,
        usedforsecurity=False,
    ).hexdigest()
    records = {"environments/vmvm_tb_v2/backend.py": ("100644", digest)}
    monkeypatch.setattr(PROBE, "attest_imported_source", lambda descriptor: records)
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    site_fd = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    try:
        expected_site = PROBE.directory_manifest(site_fd, expected_owner_uid=os.getuid())
        source_snapshot, site_snapshot, source_inventory, site_inventory = PROBE.create_execution_snapshot(
            source_fd,
            site_fd,
            scratch,
            expected_site,
        )
        source_file.write_bytes(b"SOURCE = 'tampered'\n")
        site_file.write_bytes(b"SITE = 'tampered'\n")
        source_file.write_bytes(source_raw)
        site_file.write_bytes(site_raw)
        assert (source_snapshot / "environments/vmvm_tb_v2/backend.py").read_bytes() == source_raw
        assert (site_snapshot / "dependency.py").read_bytes() == site_raw
        for snapshot, expected in (
            (source_snapshot, source_inventory),
            (site_snapshot, site_inventory),
        ):
            descriptor = os.open(snapshot, os.O_RDONLY | os.O_DIRECTORY)
            try:
                assert PROBE.directory_manifest(descriptor, expected_owner_uid=os.getuid()) == expected
            finally:
                os.close(descriptor)
    finally:
        os.close(site_fd)
        os.close(source_fd)
    scratch_fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert PROBE._remove_bound_tree_verified(
            parent_fd,
            scratch.name,
            scratch_fd,
            PROBE.descriptor_identity(scratch_fd),
        )
    finally:
        os.close(parent_fd)
        os.close(scratch_fd)
    assert not scratch.exists()


def test_landlock_child_can_write_only_to_its_stage(tmp_path: Path) -> None:
    source = tmp_path / "source"
    stage = tmp_path / "stage"
    source.mkdir()
    stage.mkdir()
    source_file = source / "authorized.py"
    source_file.write_text("VALUE = 1\n")
    source_file.chmod(0o600)
    stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
    ruleset_fd = PROBE._create_worker_write_ruleset(stage_fd)
    program = (
        "import os,sys\n"
        "source,stage=sys.argv[1:]\n"
        "blocked=0\n"
        "for operation in (\n"
        " lambda: open(source,'wb').write(b'tampered'),\n"
        " lambda: os.rename(source,source+'.moved'),\n"
        "):\n"
        " try: operation()\n"
        " except PermissionError: blocked += 1\n"
        "open(os.path.join(stage,'allowed'),'wb').write(b'ok')\n"
        "raise SystemExit(0 if blocked == 2 else 3)\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", program, str(source_file), str(stage)],
            capture_output=True,
            check=False,
            pass_fds=(stage_fd, ruleset_fd),
            preexec_fn=lambda: PROBE._restrict_worker_writes(ruleset_fd),
        )
    finally:
        os.close(ruleset_fd)
        os.close(stage_fd)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert source_file.read_text() == "VALUE = 1\n"
    assert (stage / "allowed").read_bytes() == b"ok"


def test_snapshot_guard_detects_external_sibling_mutate_restore(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir(mode=0o700)
    source = snapshot / "authorized.py"
    source.write_bytes(b"authorized\n")
    source.chmod(0o400)
    snapshot.chmod(0o500)
    snapshot_fd = os.open(snapshot, os.O_RDONLY | os.O_DIRECTORY)
    guard = PROBE.SnapshotGuard((Path(f"/proc/self/fd/{snapshot_fd}"),))
    program = (
        "import os,sys\n"
        "root,path=sys.argv[1:]\n"
        "moved=path+'.moved'\n"
        "os.chmod(root,0o700)\n"
        "os.rename(path,moved)\n"
        "os.rename(moved,path)\n"
        "os.chmod(root,0o500)\n"
    )
    sibling = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program, str(snapshot), str(source)],
        capture_output=True,
        check=False,
    )
    assert sibling.returncode == 0, sibling.stderr.decode(errors="replace")
    assert source.read_bytes() == b"authorized\n"
    assert not guard.is_clean()
    assert not guard.close()
    os.close(snapshot_fd)


def test_snapshot_guard_read_lease_blocks_external_sibling_write(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir(mode=0o700)
    source = snapshot / "authorized.py"
    source.write_bytes(b"authorized\n")
    source.chmod(0o600)
    snapshot.chmod(0o500)
    snapshot_fd = os.open(snapshot, os.O_RDONLY | os.O_DIRECTORY)
    guard = PROBE.SnapshotGuard((Path(f"/proc/self/fd/{snapshot_fd}"),))
    writer = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'tampered\\n')",
            str(source),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 5
    try:
        while guard.is_clean() and writer.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not guard.is_clean()
        assert writer.poll() is None
        writer.terminate()
        writer.communicate(timeout=5)
        assert source.read_bytes() == b"authorized\n"
        assert not guard.close()
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.communicate(timeout=5)
        os.close(snapshot_fd)


def test_verified_tree_deletion_fails_closed_on_symlink(tmp_path: Path) -> None:
    removable = tmp_path / "removable"
    removable.mkdir(mode=0o700)
    removable.chmod(0o700)
    (removable / "log").write_text("diagnostic\n")
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    removable_fd = os.open(removable, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert PROBE._remove_bound_tree_verified(
            parent_fd,
            removable.name,
            removable_fd,
            PROBE.descriptor_identity(removable_fd),
        )
    finally:
        os.close(removable_fd)
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o700)
    unsafe.chmod(0o700)
    link = unsafe / "link"
    link.symlink_to(tmp_path)
    unsafe_fd = os.open(unsafe, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert not PROBE._remove_bound_tree_verified(
            parent_fd,
            unsafe.name,
            unsafe_fd,
            PROBE.descriptor_identity(unsafe_fd),
        )
    finally:
        os.close(unsafe_fd)
        os.close(parent_fd)
    link.unlink()
    unsafe.rmdir()


@pytest.mark.parametrize("replacement", (False, True))
def test_verified_tree_deletion_rejects_missing_or_replaced_root(tmp_path: Path, replacement: bool) -> None:
    root = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    expected = PROBE.descriptor_identity(root_fd)
    displaced = tmp_path / "displaced"
    root.rename(displaced)
    if replacement:
        root.mkdir(mode=0o700)
        root.chmod(0o700)
    try:
        assert not PROBE._remove_bound_tree_verified(parent_fd, root.name, root_fd, expected)
        assert displaced.is_dir()
        assert root.is_dir() is replacement
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_verified_tree_deletion_does_not_remove_a_during_detach_replacement(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "scratch"
    displaced = tmp_path / "displaced"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    (root / "owned").write_text("bound tree\n")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    expected = PROBE.descriptor_identity(root_fd)
    original_rename = PROBE._rename_noreplace
    swapped = False

    def swap_before_detach(source_parent_fd, source, target_parent_fd, target):
        nonlocal swapped
        if not swapped and source == root.name:
            swapped = True
            os.rename(root.name, displaced.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            os.mkdir(root.name, mode=0o700, dir_fd=parent_fd)
            replacement_fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent_fd)
            try:
                marker_fd = os.open(
                    "unrelated",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=replacement_fd,
                )
                os.close(marker_fd)
            finally:
                os.close(replacement_fd)
        original_rename(source_parent_fd, source, target_parent_fd, target)

    monkeypatch.setattr(PROBE, "_rename_noreplace", swap_before_detach)
    try:
        assert not PROBE._remove_bound_tree_verified(parent_fd, root.name, root_fd, expected)
        assert displaced.is_dir()
        assert (displaced / "owned").read_text() == "bound tree\n"
        assert root.is_dir()
        assert (root / "unrelated").is_file()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_verified_tree_deletion_removes_an_ordinary_nested_tree(tmp_path: Path) -> None:
    root = tmp_path / "scratch"
    nested = root / "first" / "second"
    nested.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    (nested / "payload").write_text("scratch\n")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert PROBE._remove_bound_tree_verified(
            parent_fd,
            root.name,
            root_fd,
            PROBE.descriptor_identity(root_fd),
        )
        assert not root.exists()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_verified_tree_deletion_preserves_nested_file_swap(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "scratch"
    nested = root / "nested"
    payload = nested / "payload"
    displaced = nested / "displaced-payload"
    nested.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    payload.write_text("bound file\n")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    expected = PROBE.descriptor_identity(root_fd)
    original_rename = PROBE._rename_noreplace
    swapped = False

    def swap_file_before_detach(source_parent_fd, source, target_parent_fd, target):
        nonlocal swapped
        if not swapped and source == payload.name:
            swapped = True
            os.rename(source, displaced.name, src_dir_fd=source_parent_fd, dst_dir_fd=source_parent_fd)
            replacement_fd = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=source_parent_fd,
            )
            os.write(replacement_fd, b"unrelated file\n")
            os.close(replacement_fd)
        original_rename(source_parent_fd, source, target_parent_fd, target)

    monkeypatch.setattr(PROBE, "_rename_noreplace", swap_file_before_detach)
    try:
        assert not PROBE._remove_bound_tree_verified(parent_fd, root.name, root_fd, expected)
        assert displaced.read_text() == "bound file\n"
        assert payload.read_text() == "unrelated file\n"
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_verified_tree_deletion_preserves_nested_directory_swap(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "scratch"
    nested = root / "nested"
    child = nested / "child"
    displaced = nested / "displaced-child"
    child.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    (child / "scratch-file").write_text("remove me\n")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    expected = PROBE.descriptor_identity(root_fd)
    original_rename = PROBE._rename_noreplace
    swapped = False

    def swap_directory_before_detach(source_parent_fd, source, target_parent_fd, target):
        nonlocal swapped
        if not swapped and source == child.name:
            swapped = True
            os.rename(source, displaced.name, src_dir_fd=source_parent_fd, dst_dir_fd=source_parent_fd)
            os.mkdir(source, mode=0o700, dir_fd=source_parent_fd)
            replacement_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY, dir_fd=source_parent_fd)
            try:
                marker_fd = os.open(
                    "unrelated",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=replacement_fd,
                )
                os.close(marker_fd)
            finally:
                os.close(replacement_fd)
        original_rename(source_parent_fd, source, target_parent_fd, target)

    monkeypatch.setattr(PROBE, "_rename_noreplace", swap_directory_before_detach)
    try:
        assert not PROBE._remove_bound_tree_verified(parent_fd, root.name, root_fd, expected)
        assert displaced.is_dir()
        assert not any(displaced.iterdir())
        assert (child / "unrelated").is_file()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_verified_tree_deletion_rejects_name_creation_during_final_rmdir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    expected = PROBE.descriptor_identity(root_fd)
    original_rmdir = os.rmdir
    injected = False

    def create_replacement_before_rmdir(path, *, dir_fd=None):
        nonlocal injected
        if not injected and isinstance(path, str) and path.startswith(".vmvm-cleanup-"):
            injected = True
            os.mkdir(root.name, mode=0o700, dir_fd=parent_fd)
            replacement_fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent_fd)
            try:
                marker_fd = os.open(
                    "unrelated",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=replacement_fd,
                )
                os.close(marker_fd)
            finally:
                os.close(replacement_fd)
        original_rmdir(path, dir_fd=dir_fd)

    monkeypatch.setattr(PROBE.os, "rmdir", create_replacement_before_rmdir)
    try:
        assert not PROBE._remove_bound_tree_verified(parent_fd, root.name, root_fd, expected)
        assert root.is_dir()
        assert (root / "unrelated").is_file()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_valid_child_requires_external_absence_check(monkeypatch, tmp_path: Path) -> None:
    observed: list[bool] = []

    class Process:
        pid = 2_000_000_101
        returncode = 0

        def __init__(self, command, **kwargs) -> None:
            del kwargs
            marker = command.index("--renewer-journal-fd")
            self.journal_fd = int(command[marker + 1])

        def communicate(self, timeout):
            del timeout
            events = (
                {
                    "artifact_type": "vmvm_renewer_journal_event_v2",
                    "event": "audit_started",
                    "sequence": 0,
                },
                {
                    "artifact_type": "vmvm_renewer_journal_event_v2",
                    "event": "operation_started",
                    "lease_id": 101,
                    "operation": "start",
                    "operation_id": 0,
                    "sequence": 1,
                },
                {
                    "artifact_type": "vmvm_renewer_journal_event_v2",
                    "event": "renewer_observed",
                    "lease_id": 101,
                    "operation": "start",
                    "operation_id": 0,
                    "pid": 2_000_000_102,
                    "process_group": 2_000_000_102,
                    "running": False,
                    "sequence": 2,
                    "start_ticks": None,
                },
                {
                    "artifact_type": "vmvm_renewer_journal_event_v2",
                    "event": "operation_finished",
                    "lease_id": 101,
                    "operation": "start",
                    "operation_id": 0,
                    "outcome": "process_observed",
                    "sequence": 3,
                },
                {
                    "artifact_type": "vmvm_renewer_journal_event_v2",
                    "event": "audit_complete",
                    "renewer_processes": 1,
                    "sequence": 4,
                },
            )
            os.write(self.journal_fd, b"".join(PROBE.canonical_json(event) + b"\n" for event in events))
            result = PROBE._result_payload(
                mode="absent",
                stage="direct_client",
                state="passed",
                failure=None,
                cleanup_complete=True,
                elapsed_seconds=0,
                phase_metadata=valid_phase_metadata("direct_client"),
            )
            return PROBE.canonical_json(result) + b"\n", b""

        def poll(self):
            return self.returncode

    def verify(journal_fd, child_process_group, *, require_complete=False, **kwargs):
        del journal_fd, child_process_group, kwargs
        observed.append(require_complete)
        return True

    monkeypatch.setattr(PROBE.subprocess, "Popen", Process)
    monkeypatch.setattr(PROBE, "verify_external_renewer_release", verify)
    set_probe_execution_environment(monkeypatch)
    for name in PROBE.TLS_NAMES:
        monkeypatch.setenv(name, "/fixture/tls")
    descriptors = [
        os.open(ROOT / "probe_vmvm_task_free_v2.py", os.O_RDONLY),
        os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY),
        os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY),
    ]
    try:
        result = PROBE.run_stage_child(
            script=Path(f"/proc/self/fd/{descriptors[0]}"),
            python=Path(sys.executable),
            source_root=Path(f"/proc/self/fd/{descriptors[1]}"),
            site_root=Path(f"/proc/self/fd/{descriptors[2]}"),
            scratch_root_fd=descriptors[1],
            snapshot_guard=CleanSnapshotGuard(),
            mode="absent",
            stage="direct_client",
            pair_index=0,
            order_position=0,
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    assert result["state"] == "passed"
    assert observed == [True]


def test_stage_child_fails_closed_when_scratch_deletion_is_unverified(monkeypatch, tmp_path: Path) -> None:
    original_remove = PROBE._remove_bound_tree_verified

    def fail_to_spawn(*args, **kwargs):
        del args, kwargs
        raise OSError("fixture spawn failure")

    monkeypatch.setattr(PROBE.subprocess, "Popen", fail_to_spawn)
    monkeypatch.setattr(PROBE, "_remove_bound_tree_verified", lambda *args: False)
    set_probe_execution_environment(monkeypatch)
    for name in PROBE.TLS_NAMES:
        monkeypatch.setenv(name, "/fixture/tls")
    descriptors = [
        os.open(ROOT / "probe_vmvm_task_free_v2.py", os.O_RDONLY),
        os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY),
        os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY),
    ]
    try:
        with pytest.raises(PROBE.DiagnosticError, match="cleanup_failed"):
            PROBE.run_stage_child(
                script=Path(f"/proc/self/fd/{descriptors[0]}"),
                python=Path(sys.executable),
                source_root=Path(f"/proc/self/fd/{descriptors[1]}"),
                site_root=Path(f"/proc/self/fd/{descriptors[2]}"),
                scratch_root_fd=descriptors[1],
                snapshot_guard=CleanSnapshotGuard(),
                mode="absent",
                stage="direct_client",
                pair_index=0,
                order_position=0,
            )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    leftovers = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(leftovers) == 1
    leftover_fd = os.open(leftovers[0], os.O_RDONLY | os.O_DIRECTORY)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert original_remove(
            parent_fd,
            leftovers[0].name,
            leftover_fd,
            PROBE.descriptor_identity(leftover_fd),
        )
    finally:
        os.close(parent_fd)
        os.close(leftover_fd)


def test_finalizer_rejects_impossible_phase_causality() -> None:
    result = {
        "artifact_type": "vmvm_task_free_stage_result_v2",
        "cleanup_complete": True,
        "elapsed_milliseconds": 1,
        "failure_class": None,
        "order_position": 0,
        "pair_index": 0,
        "phase_metadata": valid_phase_metadata("same_thread_raw", FINALIZE),
        "stage": "same_thread_raw",
        "state": "passed",
        "x2p_mode": "absent",
    }
    result["phase_metadata"]["phase_counts"]["command_succeeded"] = 2
    with pytest.raises(FINALIZE.FinalizeError, match="certificate_phase_invalid"):
        FINALIZE._validate_stage_result(result)


def test_finalizer_refuses_completion_while_scratch_name_exists(monkeypatch, tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(FINALIZE, "SCRATCH_ROOT", scratch)
    with pytest.raises(FINALIZE.FinalizeError, match="scratch_cleanup_unverified"):
        FINALIZE.finalize(
            tmp_path / "unused.json",
            "0" * 64,
            execution_binding={
                "bundle_root": str(tmp_path),
                "seals": FINALIZE.REQUIRED_MEMFD_SEALS,
                "sha256": "0" * 64,
                "size": 1,
            },
        )


@pytest.mark.parametrize(
    ("module", "error_type", "error_code"),
    (
        (PROBE, PROBE.DiagnosticError, "stage_result_invalid"),
        (FINALIZE, FINALIZE.FinalizeError, "certificate_phase_invalid"),
    ),
)
def test_phase_causality_binds_tunnel_success_to_a_journaled_renewer(module, error_type, error_code) -> None:
    metadata = valid_phase_metadata("same_thread_raw", module)
    metadata["renewer_processes"] = 0
    with pytest.raises(error_type, match=error_code):
        module._validate_phase_causality("same_thread_raw", "passed", None, metadata)


@pytest.mark.parametrize("module", (PROBE, FINALIZE))
def test_phase_causality_accepts_one_lease_one_recovery_and_two_tunnels(module) -> None:
    metadata = valid_phase_metadata("same_thread_recovery", module)
    metadata["transport_recovery_attempts"] = 1
    metadata["renewer_processes"] = 2
    metadata["phase_counts"]["tunnel_ready"] = 2
    module._validate_phase_causality("same_thread_recovery", "passed", None, metadata)


def test_external_finalizer_writes_receipt_outside_sealed_output(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "candidate"
    receipt_path = tmp_path / "candidate.external-completion.json"
    reservation = tmp_path / "candidate.launch-reservation"
    launch_authorization_path = tmp_path / "launch-authorization.json"
    job = {
        "cluster": "fair-cw-use2-3",
        "job_id": "42",
        "job_name": "vmvm-v4-preflight-" + "f" * 24,
    }
    source_root, source_revisions = build_git_source_fixture(tmp_path)
    site_root = tmp_path / "site-root"
    bundle_root = tmp_path / "bundle"
    site_root.mkdir()
    bundle_root.mkdir(mode=0o700)
    (site_root / "runtime.py").write_text("VALUE = 1\n")
    bundle_layout = {
        "finalizer": ("finalize_vmvm_task_free_v2.py", 0o500),
        "launcher": ("launch_vmvm_task_free_v2.py", 0o500),
        "probe": ("probe_vmvm_task_free_v2.py", 0o500),
        "readme": ("README.md", 0o400),
        "tests": ("test_vmvm_task_free_v2.py", 0o400),
        "wrapper": ("run_vmvm_task_free_v2.sbatch", 0o500),
    }
    bundle_records = {}
    for label, (name, mode) in bundle_layout.items():
        path = bundle_root / name
        path.write_bytes(f"fixture:{label}\n".encode())
        path.chmod(mode)
        bundle_records[label] = {
            "path": str(path),
            "sha256": FINALIZE.sha256_bytes(path.read_bytes()),
        }
    execution_binding = {
        "bundle_root": str(bundle_root),
        "seals": FINALIZE.REQUIRED_MEMFD_SEALS,
        "sha256": bundle_records["finalizer"]["sha256"],
        "size": (bundle_root / "finalize_vmvm_task_free_v2.py").stat().st_size,
    }
    uv_path = tmp_path / "uv"
    uv_path.write_bytes(b"fixture executable\n")
    uv_path.chmod(0o755)
    vacli_target_dir = tmp_path / "vacli-794"
    vacli_target_dir.mkdir()
    vacli_resolved = vacli_target_dir / "vacli"
    vacli_resolved.write_bytes(b"fixture vacli executable\n")
    vacli_resolved.chmod(0o755)
    vacli_stable_dir = tmp_path / "vacli-stable"
    vacli_stable_dir.symlink_to(vacli_target_dir, target_is_directory=True)
    vacli_path = vacli_stable_dir / "vacli"
    tls_path = tmp_path / "tls.pem"
    pem = b"".join(
        b"-----BEGIN " + label + b"-----\n" + base64.b64encode(payload) + b"\n-----END " + label + b"-----\n"
        for label, payload in (
            (b"CERTIFICATE", b"certificate-one"),
            (b"CERTIFICATE", b"certificate-two"),
            (b"RSA PRIVATE KEY", b"private-key"),
        )
    ).ljust(FINALIZE.TLS_EXPECTED_SIZE, b"\n")
    tls_path.write_bytes(pem)
    tls_path.chmod(0o500)

    def identity(path: Path) -> dict[str, int]:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return FINALIZE.descriptor_identity(descriptor)
        finally:
            os.close(descriptor)

    site_fd = os.open(site_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        site_inventory = FINALIZE._directory_manifest(site_fd)
    finally:
        os.close(site_fd)
    monkeypatch.setattr(FINALIZE, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(FINALIZE, "SOURCE_REVISION", source_revisions["revision"])
    monkeypatch.setattr(FINALIZE, "SOURCE_TREE", source_revisions["tree"])
    monkeypatch.setattr(FINALIZE, "VERIFIERS_REVISION", source_revisions["verifiers"])
    monkeypatch.setattr(FINALIZE, "RENDERERS_REVISION", source_revisions["renderers"])
    monkeypatch.setattr(FINALIZE, "PYDANTIC_CONFIG_REVISION", source_revisions["pydantic_config"])
    monkeypatch.setattr(FINALIZE, "VMVM_SHA256", source_revisions["vmvm"])
    monkeypatch.setattr(FINALIZE, "X86_SITE", site_root)
    monkeypatch.setattr(FINALIZE, "X86_UV", uv_path)
    monkeypatch.setattr(FINALIZE, "X86_UV_SHA256", FINALIZE.sha256_bytes(uv_path.read_bytes()))
    monkeypatch.setattr(FINALIZE, "VACLI", vacli_path)
    monkeypatch.setattr(FINALIZE, "VACLI_RESOLVED", vacli_resolved)
    monkeypatch.setattr(FINALIZE, "VACLI_SHA256", FINALIZE.sha256_bytes(vacli_resolved.read_bytes()))
    monkeypatch.setattr(FINALIZE, "VACLI_OWNER_UID", os.getuid())
    monkeypatch.setattr(FINALIZE, "OUTPUT_ROOT", output)
    monkeypatch.setattr(FINALIZE, "COMPLETION_RECEIPT", receipt_path)
    monkeypatch.setattr(FINALIZE, "RESERVATION", reservation)
    monkeypatch.setattr(FINALIZE, "LOG_ROOT", tmp_path / "logs")
    monkeypatch.setattr(FINALIZE, "SCRATCH_ROOT", tmp_path / "scratch")
    source_fd = os.open(source_root, os.O_RDONLY | os.O_DIRECTORY)
    site_fd = os.open(site_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        source_snapshot_commitment = FINALIZE._source_snapshot_commitment(FINALIZE._attest_imported_source(source_fd))
        sealed_site_commitment = FINALIZE._directory_manifest(site_fd, sealed_modes=True)
    finally:
        os.close(site_fd)
        os.close(source_fd)
    execution_inputs = {
        "authorized_site": site_inventory,
        "site_snapshot": sealed_site_commitment,
        "source_snapshot": source_snapshot_commitment,
    }
    tls_record = {
        "path": str(tls_path),
        "sha256": FINALIZE.sha256_bytes(tls_path.read_bytes()),
    }
    x2p_values = {name: f"fixture-{name.lower()}" for name in FINALIZE.X2P_NAMES}
    launch_authorization_body = {
        "artifact_type": "vmvm_task_free_diagnostic_authorization_v2",
        "bundle": {
            **bundle_records,
            "root_identity": identity(bundle_root),
        },
        "credentials": {
            "tls": {name: tls_record for name in FINALIZE.TLS_NAMES},
            "x2p": {name: {"sha256": FINALIZE.sha256_bytes(value.encode())} for name, value in x2p_values.items()},
        },
        "launch": {
            "account": "ram",
            "cluster": FINALIZE.CLUSTER,
            "comment": f"vmvm-v4-preflight:{'f' * 24}",
            "completion_receipt": str(receipt_path),
            "cpus": 2,
            "job_name": job["job_name"],
            "log_root": str(FINALIZE.LOG_ROOT),
            "memory": "8G",
            "nodes": 1,
            "output_parent_identity": identity(tmp_path),
            "output_root": str(output),
            "partition": "cpu_x86",
            "qos": "cpu_x86_lowest",
            "reservation": str(reservation),
            "scratch_root": str(FINALIZE.SCRATCH_ROOT),
            "time_limit": FINALIZE.JOB_TIME_LIMIT,
        },
        "protocol": {
            "diagnostic_only": True,
            "preflight_only": True,
            "production_authorized": False,
        },
        "runtime": {
            "image": FINALIZE.IMAGE,
            "python_name": "python3",
            "site": {
                "inventory": site_inventory,
                "path": str(site_root),
                "root_identity": identity(site_root),
            },
            "uv": {
                "path": str(uv_path),
                "sha256": FINALIZE.X86_UV_SHA256,
            },
            "vacli": {
                "path": str(vacli_path),
                "resolved_path": str(vacli_resolved),
                "sha256": FINALIZE.VACLI_SHA256,
            },
        },
        "schema_version": 2,
        "source": {
            "path": str(source_root),
            "pydantic_config_revision": FINALIZE.PYDANTIC_CONFIG_REVISION,
            "renderers_revision": FINALIZE.RENDERERS_REVISION,
            "revision": FINALIZE.SOURCE_REVISION,
            "root_identity": identity(source_root),
            "tree": FINALIZE.SOURCE_TREE,
            "verifiers_revision": FINALIZE.VERIFIERS_REVISION,
            "vmvm_sha256": FINALIZE.VMVM_SHA256,
        },
        "state": "approved",
    }
    launch_authorization_sha = FINALIZE.sha256_bytes(FINALIZE.canonical_json(launch_authorization_body))
    launch_authorization = {
        **launch_authorization_body,
        "authorization_sha256": launch_authorization_sha,
    }
    launch_authorization_raw = FINALIZE.canonical_json(launch_authorization) + b"\n"
    launch_authorization_path.write_bytes(launch_authorization_raw)
    launch_authorization_path.chmod(0o400)
    launch_authorization_file_sha = FINALIZE.sha256_bytes(launch_authorization_raw)

    for name, expected_error, mutate in (
        ("bad-launch-semantics", "authorization_invalid", lambda body: body["launch"].update({"cpus": 3})),
        (
            "bad-bundle-self-hash",
            "finalizer_execution_invalid",
            lambda body: body["bundle"]["finalizer"].update({"sha256": "0" * 64}),
        ),
        (
            "bad-vacli-target",
            "authorization_invalid",
            lambda body: body["runtime"]["vacli"].update({"resolved_path": str(vacli_path)}),
        ),
    ):
        bad_launch_body = json.loads(FINALIZE.canonical_json(launch_authorization_body))
        mutate(bad_launch_body)
        bad_launch_sha = FINALIZE.sha256_bytes(FINALIZE.canonical_json(bad_launch_body))
        bad_launch = {**bad_launch_body, "authorization_sha256": bad_launch_sha}
        bad_launch_raw = FINALIZE.canonical_json(bad_launch) + b"\n"
        bad_launch_path = tmp_path / f"{name}.json"
        bad_launch_path.write_bytes(bad_launch_raw)
        bad_launch_path.chmod(0o400)
        with pytest.raises(FINALIZE.FinalizeError, match=expected_error):
            FINALIZE._validate_launch_authorization(
                {
                    "authorization_sha256": bad_launch_sha,
                    "file_sha256": FINALIZE.sha256_bytes(bad_launch_raw),
                    "path": str(bad_launch_path),
                },
                execution_binding=execution_binding,
            )

    invalid_tls = tmp_path / "invalid-combined.pem"
    invalid_tls.write_bytes(
        (
            b"-----BEGIN CERTIFICATE-----\n" + base64.b64encode(b"certificate-only") + b"\n-----END CERTIFICATE-----\n"
        ).ljust(FINALIZE.TLS_EXPECTED_SIZE, b"\n")
    )
    invalid_tls.chmod(0o500)
    invalid_tls_body = json.loads(FINALIZE.canonical_json(launch_authorization_body))
    invalid_tls_record = {
        "path": str(invalid_tls),
        "sha256": FINALIZE.sha256_bytes(invalid_tls.read_bytes()),
    }
    invalid_tls_body["credentials"]["tls"] = {name: invalid_tls_record for name in FINALIZE.TLS_NAMES}
    invalid_tls_sha = FINALIZE.sha256_bytes(FINALIZE.canonical_json(invalid_tls_body))
    invalid_tls_authorization = {
        **invalid_tls_body,
        "authorization_sha256": invalid_tls_sha,
    }
    invalid_tls_raw = FINALIZE.canonical_json(invalid_tls_authorization) + b"\n"
    invalid_tls_auth_path = tmp_path / "invalid-tls-authorization.json"
    invalid_tls_auth_path.write_bytes(invalid_tls_raw)
    invalid_tls_auth_path.chmod(0o400)
    with pytest.raises(FINALIZE.FinalizeError, match="authorization_invalid"):
        FINALIZE._validate_launch_authorization(
            {
                "authorization_sha256": invalid_tls_sha,
                "file_sha256": FINALIZE.sha256_bytes(invalid_tls_raw),
                "path": str(invalid_tls_auth_path),
            },
            execution_binding=execution_binding,
        )

    reservation.mkdir(mode=0o700)
    writer_lock = reservation / ".writer.lock"
    writer_lock.write_bytes(b"")
    writer_lock.chmod(0o600)
    reservation_environment_identity = identity(reservation)
    reservation_environment_identity["mode"] = 0o500
    job_authorization = {
        "artifact_type": "vmvm_task_free_job_authorization_v2",
        "authorization_file_sha256": launch_authorization_file_sha,
        "authorization_sha256": launch_authorization_sha,
        "job": job,
        "production_authorized": False,
        "state": "held_verified",
    }
    job_authorization_raw = FINALIZE.canonical_json(job_authorization) + b"\n"
    job_authorization_sha = FINALIZE.sha256_bytes(job_authorization_raw)
    identity_string = lambda value: ":".join(str(value[name]) for name in ("device", "inode", "mode", "owner_uid"))
    exported = {
        "DIAG_ACTIVATION_PERMIT": str(reservation / "activation_permit.json"),
        "DIAG_AUTHORIZATION": str(launch_authorization_path),
        "DIAG_AUTHORIZATION_FILE_SHA256": launch_authorization_file_sha,
        "DIAG_AUTHORIZATION_SHA256": launch_authorization_sha,
        "DIAG_BUNDLE_IDENTITY": identity_string(identity(bundle_root)),
        "DIAG_BUNDLE_ROOT": str(bundle_root),
        "DIAG_COMPLETION_RECEIPT": str(receipt_path),
        "DIAG_FINALIZER_PATH": bundle_records["finalizer"]["path"],
        "DIAG_FINALIZER_SHA256": bundle_records["finalizer"]["sha256"],
        "DIAG_JOB_AUTHORIZATION": str(reservation / "job_authorization.json"),
        "DIAG_JOB_NAME": job["job_name"],
        "DIAG_LAUNCHER_PATH": bundle_records["launcher"]["path"],
        "DIAG_LAUNCHER_SHA256": bundle_records["launcher"]["sha256"],
        "DIAG_OUTPUT_PARENT_IDENTITY": identity_string(identity(tmp_path)),
        "DIAG_OUTPUT_ROOT": str(output),
        "DIAG_PROBE_PATH": bundle_records["probe"]["path"],
        "DIAG_PROBE_SHA256": bundle_records["probe"]["sha256"],
        "DIAG_RESERVATION": str(reservation),
        "DIAG_RESERVATION_IDENTITY": identity_string(reservation_environment_identity),
        "DIAG_SCRATCH_ROOT": str(FINALIZE.SCRATCH_ROOT),
        "DIAG_SOURCE_IDENTITY": identity_string(identity(source_root)),
        "DIAG_SOURCE_REVISION": FINALIZE.SOURCE_REVISION,
        "DIAG_SOURCE_ROOT": str(source_root),
        "DIAG_SOURCE_TREE": FINALIZE.SOURCE_TREE,
        "DIAG_SUBMISSION_RECEIPT": str(reservation / "submission_receipt.json"),
        "DIAG_VMVM_SHA256": FINALIZE.VMVM_SHA256,
        "DIAG_WRAPPER_GATE_TIMEOUT_SECONDS": str(FINALIZE.WRAPPER_GATE_TIMEOUT_SECONDS),
        "DIAG_WRAPPER_PATH": bundle_records["wrapper"]["path"],
        "DIAG_WRAPPER_SHA256": bundle_records["wrapper"]["sha256"],
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": FINALIZE.OWNER,
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_BIN_X86_64": "python3",
        "PYTHON_SITE_X86_64": str(site_root),
        "PYTHON_SITE_X86_64_ENTRY_COUNT": str(site_inventory["entry_count"]),
        "PYTHON_SITE_X86_64_IDENTITY": identity_string(identity(site_root)),
        "PYTHON_SITE_X86_64_MANIFEST_SHA256": site_inventory["manifest_sha256"],
        "PYTHON_SITE_X86_64_TOTAL_BYTES": str(site_inventory["total_bytes"]),
        "SLURM_EXPORT_ENV": "NONE",
        "TZ": "UTC",
        "USER": FINALIZE.OWNER,
        "UV_BIN_X86_64": str(uv_path),
        "VACLI_BIN": str(vacli_path),
        "VACLI_CONTAINER_PRIVILEGED": "1",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": str(FINALIZE.IMAGE_PULL_TIMEOUT_SECONDS),
        "VACLI_LEASE_RETRIES": str(FINALIZE.LEASE_ATTEMPT_LIMIT),
        "VACLI_MAX_CONCURRENT_LEASES": "1",
        "VACLI_MAX_PULL_RETRIES": str(FINALIZE.IMAGE_PULL_RETRY_LIMIT),
        **{name: str(tls_path) for name in FINALIZE.TLS_NAMES},
        **x2p_values,
    }
    environment_raw = b"".join(f"{name}={exported[name]}".encode() + b"\0" for name in sorted(exported))
    environment_sha = FINALIZE.sha256_bytes(environment_raw)
    launch_intent = {
        "artifact_type": "vmvm_task_free_launch_intent_v2",
        "authorization_file_sha256": launch_authorization_file_sha,
        "authorization_sha256": launch_authorization_sha,
        "bundle_sha256": {
            label: bundle_records[label]["sha256"] for label in ("finalizer", "launcher", "probe", "wrapper")
        },
        "environment_sha256": environment_sha,
        "job_name": job["job_name"],
        "production_authorized": False,
        "state": "reserved",
    }
    launch_intent_raw = FINALIZE.canonical_json(launch_intent) + b"\n"

    def telemetry(deadline: int, *, held: bool) -> dict[str, object]:
        value: dict[str, object] = {
            "converged": True,
            "deadline_seconds": deadline,
            "elapsed_milliseconds": 1,
            "explicit_conflict_fields": [],
            "final_mismatch_fields": [],
            "mismatch_occurrences": {},
            "polls": FINALIZE.REQUIRED_CONSECUTIVE,
            "required_consecutive": FINALIZE.REQUIRED_CONSECUTIVE,
        }
        if held:
            value.update(
                {
                    "post_authorization_mismatch_fields": [],
                    "pre_authorization_mismatch_fields": [],
                }
            )
        return value

    submission_receipt = {
        "activation": telemetry(FINALIZE.ACTIVATION_TIMEOUT_SECONDS, held=False),
        "artifact_type": "vmvm_task_free_submission_receipt_v2",
        "authorization_file_sha256": launch_authorization_file_sha,
        "authorization_sha256": launch_authorization_sha,
        "environment_sha256": environment_sha,
        "held": telemetry(FINALIZE.HELD_TIMEOUT_SECONDS, held=True),
        "job": job,
        "job_authorization_sha256": job_authorization_sha,
        "production_authorized": False,
        "release_attempts": 1,
        "release_outcome": "completed",
        "state": "submitted",
        "submission_attempts": 1,
    }
    submission_receipt_raw = FINALIZE.canonical_json(submission_receipt) + b"\n"
    submission_receipt_sha = FINALIZE.sha256_bytes(submission_receipt_raw)
    activation_permit = {
        "artifact_type": "vmvm_task_free_activation_permit_v2",
        "authorization_file_sha256": launch_authorization_file_sha,
        "authorization_sha256": launch_authorization_sha,
        "environment_sha256": environment_sha,
        "job_authorization_sha256": job_authorization_sha,
        "production_authorized": False,
        "state": "activated",
        "submission_receipt_sha256": submission_receipt_sha,
    }
    activation_permit_raw = FINALIZE.canonical_json(activation_permit) + b"\n"
    for name, payload, mode in (
        ("activation_permit.json", activation_permit_raw, 0o400),
        ("job_authorization.json", job_authorization_raw, 0o400),
        ("launch_intent.json", launch_intent_raw, 0o400),
        ("slurm_environment.bin", environment_raw, 0o400),
        ("submission_receipt.json", submission_receipt_raw, 0o400),
    ):
        path = reservation / name
        path.write_bytes(payload)
        path.chmod(mode)
    reservation.chmod(0o500)
    reservation_fd = os.open(reservation, os.O_RDONLY | os.O_DIRECTORY)
    reservation_identity = FINALIZE.descriptor_identity(reservation_fd)
    os.close(reservation_fd)

    output.mkdir(mode=0o700)
    results = [
        {
            "artifact_type": "vmvm_task_free_stage_result_v2",
            "cleanup_complete": True,
            "elapsed_milliseconds": 1,
            "failure_class": None,
            "order_position": position,
            "pair_index": pair_index,
            "phase_metadata": valid_phase_metadata(stage, FINALIZE),
            "stage": stage,
            "state": "passed",
            "x2p_mode": mode,
        }
        for stage in FINALIZE.STAGES
        for pair_index, order in enumerate(FINALIZE.MODE_ORDERS)
        for position, mode in enumerate(order)
    ]
    summary = FINALIZE.summarize_stage_results(results)
    certificate = {
        "artifact_type": "vmvm_task_free_diagnostic_certificate_v2",
        "authorization_file_sha256": launch_authorization_file_sha,
        "authorization_sha256": launch_authorization_sha,
        "automatic_remediation": False,
        "causal_assessment": summary["causal_assessment"],
        "causal_contrasts": summary["causal_contrasts"],
        "diagnostic_only": True,
        "environment_sha256": environment_sha,
        "execution_inputs": execution_inputs,
        "image": FINALIZE.IMAGE,
        "job": job,
        "job_authorization_sha256": job_authorization_sha,
        "model_endpoint_accessed": False,
        "outcome_contrasts": summary["outcome_contrasts"],
        "production_authorized": False,
        "protocol": {
            "causal_scope": "construction_backend_ready",
            "cell_count": FINALIZE.CELL_COUNT,
            "lease_attempt_limit_per_cell": FINALIZE.LEASE_ATTEMPT_LIMIT,
            "mode_orders": [list(order) for order in FINALIZE.MODE_ORDERS],
            "repetitions_per_mode": len(FINALIZE.MODE_ORDERS),
            "stage_timeout_seconds": FINALIZE.STAGE_TIMEOUT_SECONDS,
        },
        "result_counts": summary["result_counts"],
        "retry_phase_aggregate": summary["retry_phase_aggregate"],
        "safe_failure_counts": summary["safe_failure_counts"],
        "schema_version": 2,
        "source": {
            "pydantic_config_revision": FINALIZE.PYDANTIC_CONFIG_REVISION,
            "renderers_revision": FINALIZE.RENDERERS_REVISION,
            "revision": FINALIZE.SOURCE_REVISION,
            "tree": FINALIZE.SOURCE_TREE,
            "verifiers_revision": FINALIZE.VERIFIERS_REVISION,
            "vmvm_sha256": FINALIZE.VMVM_SHA256,
        },
        "stage_results": results,
        "submission_receipt_sha256": submission_receipt_sha,
        "task_data_accessed": False,
        "x2p_modes": list(FINALIZE.MODES),
    }
    certificate_raw = FINALIZE.canonical_json(certificate) + b"\n"
    certificate_path = output / "diagnostic_certificate.json"
    certificate_path.write_bytes(certificate_raw)
    certificate_path.chmod(0o400)
    output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    sealed_identity = FINALIZE.descriptor_identity(output_fd)
    sealed_identity["mode"] = 0o500
    request = {
        "artifact_type": "vmvm_task_free_external_completion_request_v2",
        "authorization_file_sha256": launch_authorization_file_sha,
        "authorization_sha256": launch_authorization_sha,
        "certificate_sha256": FINALIZE.sha256_bytes(certificate_raw),
        "diagnostic_only": True,
        "environment_sha256": environment_sha,
        "external_completion_receipt": str(receipt_path),
        "job": job,
        "job_authorization_sha256": job_authorization_sha,
        "output_root_identity": sealed_identity,
        "production_authorized": False,
        "state": "awaiting_external_completion",
        "submission_receipt_sha256": submission_receipt_sha,
    }
    request_raw = FINALIZE.canonical_json(request) + b"\n"
    request_path = output / "completion_request.json"
    request_path.write_bytes(request_raw)
    request_path.chmod(0o400)
    output.chmod(0o500)
    inventory = FINALIZE.output_inventory(output_fd)
    os.close(output_fd)
    monkeypatch.setattr(FINALIZE, "OUTPUT_ROOT", output)
    monkeypatch.setattr(FINALIZE, "COMPLETION_RECEIPT", receipt_path)
    monkeypatch.setattr(FINALIZE, "RESERVATION", reservation)
    authorization_body = {
        "artifact_type": "vmvm_task_free_external_completion_authorization_v2",
        "job": {
            **job,
            "terminal_observation_sha256": "d" * 64,
            "terminal_state": "COMPLETED",
        },
        "launch_authorization": {
            "authorization_sha256": launch_authorization_sha,
            "file_sha256": launch_authorization_file_sha,
            "path": str(launch_authorization_path),
        },
        "output": {
            "certificate_sha256": FINALIZE.sha256_bytes(certificate_raw),
            "completion_request_sha256": FINALIZE.sha256_bytes(request_raw),
            "inventory": inventory,
            "path": str(output),
            "root_identity": sealed_identity,
        },
        "production_authorized": False,
        "receipt_path": str(receipt_path),
        "schema_version": 2,
        "state": "approved",
        "submission": {
            "activation_permit_sha256": FINALIZE.sha256_bytes(activation_permit_raw),
            "environment_sha256": environment_sha,
            "job_authorization_sha256": job_authorization_sha,
            "launch_intent_sha256": FINALIZE.sha256_bytes(launch_intent_raw),
            "reservation_path": str(reservation),
            "reservation_root_identity": reservation_identity,
            "submission_receipt_sha256": submission_receipt_sha,
            "writer_lock_sha256": FINALIZE.sha256_bytes(b""),
        },
    }
    body_sha = FINALIZE.sha256_bytes(FINALIZE.canonical_json(authorization_body))
    authorization = {**authorization_body, "authorization_sha256": body_sha}
    authorization_raw = FINALIZE.canonical_json(authorization) + b"\n"
    authorization_path = tmp_path / "completion-authorization.json"
    authorization_path.write_bytes(authorization_raw)
    authorization_path.chmod(0o400)

    for field in (
        "activation_permit_sha256",
        "environment_sha256",
        "job_authorization_sha256",
        "launch_intent_sha256",
        "submission_receipt_sha256",
        "writer_lock_sha256",
    ):
        bad_body = json.loads(FINALIZE.canonical_json(authorization_body))
        bad_body["submission"][field] = "0" * 64
        bad_body_sha = FINALIZE.sha256_bytes(FINALIZE.canonical_json(bad_body))
        bad_authorization = {**bad_body, "authorization_sha256": bad_body_sha}
        bad_raw = FINALIZE.canonical_json(bad_authorization) + b"\n"
        bad_path = tmp_path / f"bad-{field}.json"
        bad_path.write_bytes(bad_raw)
        bad_path.chmod(0o400)
        with pytest.raises(FINALIZE.FinalizeError, match="submission_lineage_invalid"):
            FINALIZE.finalize(
                bad_path,
                FINALIZE.sha256_bytes(bad_raw),
                execution_binding=execution_binding,
            )

    tampered_certificate = json.loads(FINALIZE.canonical_json(certificate))
    tampered_certificate["result_counts"]["passed"] -= 1
    with pytest.raises(FINALIZE.FinalizeError, match="certificate_aggregate_invalid"):
        FINALIZE.validate_certificate(
            tampered_certificate,
            expected_execution_inputs=execution_inputs,
        )

    arbitrary_snapshot = json.loads(FINALIZE.canonical_json(certificate))
    arbitrary_snapshot["execution_inputs"]["source_snapshot"]["manifest_sha256"] = "0" * 64
    with pytest.raises(FINALIZE.FinalizeError, match="certificate_invalid"):
        FINALIZE.validate_certificate(
            arbitrary_snapshot,
            expected_execution_inputs=execution_inputs,
        )

    result = FINALIZE.finalize(
        authorization_path,
        FINALIZE.sha256_bytes(authorization_raw),
        execution_binding=execution_binding,
    )
    assert result["state"] == "complete"
    assert result["receipt_sha256"] == FINALIZE.sha256_bytes(receipt_path.read_bytes())
    assert stat.S_IMODE(output.stat().st_mode) == 0o500
    completion_receipt = json.loads(receipt_path.read_bytes())
    assert completion_receipt["launch_authorization_file_sha256"] == (launch_authorization_file_sha)
    assert completion_receipt["launch_authorization_sha256"] == (launch_authorization_sha)
    assert completion_receipt["submission_receipt_sha256"] == (submission_receipt_sha)
    assert completion_receipt["job_authorization_sha256"] == job_authorization_sha
    assert completion_receipt["finalizer_execution"] == {
        "seals": FINALIZE.REQUIRED_MEMFD_SEALS,
        "sha256": bundle_records["finalizer"]["sha256"],
        "size": execution_binding["size"],
    }
    assert completion_receipt["job"] == {
        **job,
        "terminal_observation_sha256": "d" * 64,
        "terminal_state": "COMPLETED",
    }
    assert {entry.name for entry in output.iterdir()} == {
        "completion_request.json",
        "diagnostic_certificate.json",
    }
