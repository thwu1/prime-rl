from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import threading
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


def set_site_inventory_environment(monkeypatch, site: Path) -> None:
    descriptor = os.open(site, os.O_RDONLY | os.O_DIRECTORY)
    try:
        inventory = PROBE.directory_manifest(descriptor, expected_owner_uid=os.getuid())
    finally:
        os.close(descriptor)
    monkeypatch.setenv("PYTHON_SITE_X86_64_ENTRY_COUNT", str(inventory["entry_count"]))
    monkeypatch.setenv("PYTHON_SITE_X86_64_MANIFEST_SHA256", inventory["manifest_sha256"])
    monkeypatch.setenv("PYTHON_SITE_X86_64_TOTAL_BYTES", str(inventory["total_bytes"]))


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
    output = tmp_path / "output"
    scratch = tmp_path / "scratch"
    calls: list[tuple[str, int, int, str]] = []

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
        )

    monkeypatch.setattr(PROBE, "run_stage_child", fake_stage)
    monkeypatch.setattr(PROBE, "attest_imported_source", lambda descriptor: None)
    set_site_inventory_environment(monkeypatch, site)
    result = PROBE.run_supervisor(
        SimpleNamespace(
            source_root=source,
            site_root=site,
            output_dir=output,
            completion_receipt=tmp_path / "external-completion.json",
            scratch_root=scratch,
            environment_sha256="a" * 64,
            authorization_file_sha256="d" * 64,
            authorization_sha256="b" * 64,
            job_authorization_sha256="e" * 64,
            job_id="42",
            job_name="vmvm-diag-" + "f" * 24,
            submission_receipt_sha256="c" * 64,
        )
    )
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
    certificate = json.loads((output / "diagnostic_certificate.json").read_bytes())
    completion = json.loads((output / "completion_request.json").read_bytes())
    assert certificate["task_data_accessed"] is False
    assert certificate["model_endpoint_accessed"] is False
    assert certificate["production_authorized"] is False
    assert certificate["protocol"]["mode_orders"] == [list(order) for order in PROBE.MODE_ORDERS]
    assert certificate["protocol"]["cell_count"] == PROBE.CELL_COUNT
    for stage in PROBE.STAGES:
        assert certificate["retry_phase_aggregate"][stage]["absent"]["cells"] == 4
        assert certificate["retry_phase_aggregate"][stage]["present"]["cells"] == 4
    assert completion["certificate_sha256"] == PROBE.sha256_bytes((output / "diagnostic_certificate.json").read_bytes())
    assert stat.S_IMODE((output / "diagnostic_certificate.json").stat().st_mode) == 0o400
    assert stat.S_IMODE((output / "completion_request.json").stat().st_mode) == 0o400
    assert stat.S_IMODE(output.stat().st_mode) == 0o500
    assert not scratch.exists()


def test_sbatch_is_held_single_job_and_uses_stdin_wrapper() -> None:
    command = LAUNCH._sbatch_command("vmvm-diag-" + "a" * 24, Path("/private/environment"))
    assert command[0] == "/usr/bin/sbatch"
    assert "--hold" in command
    assert "--export=NONE" in command
    assert "--nodes=1" in command
    assert "--ntasks=1" in command
    assert "--cpus-per-task=2" in command
    assert not any(value.endswith(".sbatch") for value in command)


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
    result = LAUNCH.poll_phase("1", "vmvm-diag-" + "a" * 24, "held", 20, set())
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
    result = LAUNCH.poll_phase("1", "vmvm-diag-" + "a" * 24, "held", 20, set())
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
        "vmvm-diag-" + "a" * 24,
        set(),
        candidate_provenance="sbatch_stdout",
    )
    assert result["control_attempted"] is False
    assert result["terminal_proved"] is False
    assert not calls


def test_wrapper_orders_admission_before_runtime_or_output() -> None:
    source = (ROOT / "run_vmvm_task_free_v2.sbatch").read_text()
    permit = source.index("preflight_output=")
    final_gate = source.index("validate_source", permit)
    output_gate = source.index("[[ ! -e $DIAG_OUTPUT_ROOT", final_gate)
    probe = source.index("probe_output=", output_gate)
    assert permit < final_gate < output_gate < probe
    assert "X2P_ENV X2P_CFG_ENV" in source
    assert "--validate-batch" in source
    assert "--scratch-root" in source


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
    environment = PROBE._child_environment("present", tmp_path)
    assert environment["TMPDIR"] == str(tmp_path)
    assert environment["VACLI_MAX_CONCURRENT_LEASES"] == "1"
    assert environment["VACLI_LEASE_RETRIES"] == str(PROBE.LEASE_ATTEMPT_LIMIT)
    assert environment["VACLI_MAX_PULL_RETRIES"] == str(PROBE.IMAGE_PULL_RETRY_LIMIT)
    assert "PYTHONPATH" not in environment
    assert "HOME_SECRET" not in environment


def test_supervisor_refuses_completion_when_cleanup_is_incomplete(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    site = tmp_path / "site"
    source.mkdir()
    site.mkdir()

    def failed_stage(**kwargs):
        return PROBE._result_payload(
            mode=kwargs["mode"],
            stage=kwargs["stage"],
            state="failed",
            failure="cleanup_failed",
            cleanup_complete=False,
            elapsed_seconds=0,
            pair_index=kwargs["pair_index"],
            order_position=kwargs["order_position"],
        )

    monkeypatch.setattr(PROBE, "run_stage_child", failed_stage)
    monkeypatch.setattr(PROBE, "attest_imported_source", lambda descriptor: None)
    set_site_inventory_environment(monkeypatch, site)
    output = tmp_path / "output"
    with pytest.raises(PROBE.DiagnosticError, match="cleanup_failed"):
        PROBE.run_supervisor(
            SimpleNamespace(
                source_root=source,
                site_root=site,
                output_dir=output,
                completion_receipt=tmp_path / "external-completion.json",
                scratch_root=tmp_path / "scratch",
                environment_sha256="a" * 64,
                authorization_file_sha256="d" * 64,
                authorization_sha256="b" * 64,
                job_authorization_sha256="e" * 64,
                job_id="42",
                job_name="vmvm-diag-" + "f" * 24,
                submission_receipt_sha256="c" * 64,
            )
        )
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


def test_resolve_submission_recovers_timeout_by_exact_name(monkeypatch) -> None:
    monkeypatch.setattr(LAUNCH, "_lookup_submission", lambda *args, **kwargs: ("unique", "42"))
    assert LAUNCH._resolve_submission(
        direct_candidate=None,
        outcome="timeout",
        job_name="vmvm-diag-" + "a" * 24,
        start_date="2026-09-19",
    ) == ("42", "name_lookup")


def test_resolve_submission_rejects_direct_name_disagreement(monkeypatch) -> None:
    monkeypatch.setattr(LAUNCH, "_lookup_submission", lambda *args, **kwargs: ("unique", "43"))
    with pytest.raises(LAUNCH.LaunchError, match="submission_identity_ambiguous"):
        LAUNCH._resolve_submission(
            direct_candidate="42",
            outcome="completed",
            job_name="vmvm-diag-" + "a" * 24,
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
        "vmvm-diag-" + "a" * 24,
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
        "vmvm-diag-" + "a" * 24,
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
        for module in (LAUNCH, PROBE):
            module._attest_git_repository(descriptor, expected_revision=revision)
        git("update-index", "--assume-unchanged", "tracked.py")
        tracked.write_text("VALUE = 2\n")
        for module in (LAUNCH, PROBE):
            with pytest.raises(
                (LAUNCH.LaunchError, PROBE.DiagnosticError),
                match="source_binding_invalid",
            ):
                module._attest_git_repository(descriptor, expected_revision=revision)
        git("update-index", "--no-assume-unchanged", "tracked.py")
        for module in (LAUNCH, PROBE):
            with pytest.raises(
                (LAUNCH.LaunchError, PROBE.DiagnosticError),
                match="source_binding_invalid",
            ):
                module._attest_git_repository(descriptor, expected_revision=revision)
        tracked.write_text("VALUE = 1\n")
        git("update-index", "--skip-worktree", "tracked.py")
        for module in (LAUNCH, PROBE):
            with pytest.raises(
                (LAUNCH.LaunchError, PROBE.DiagnosticError),
                match="source_binding_invalid",
            ):
                module._attest_git_repository(descriptor, expected_revision=revision)
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


def test_external_finalizer_writes_receipt_outside_sealed_output(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "candidate"
    receipt_path = tmp_path / "candidate.external-completion.json"
    reservation = tmp_path / "candidate.launch-reservation"
    launch_authorization_path = tmp_path / "launch-authorization.json"
    job = {
        "cluster": "fair-cw-use2-3",
        "job_id": "42",
        "job_name": "vmvm-diag-" + "f" * 24,
    }
    launch_authorization_body = {
        "artifact_type": "vmvm_task_free_diagnostic_authorization_v2",
        "bundle": {},
        "credentials": {},
        "launch": {
            "cluster": job["cluster"],
            "job_name": job["job_name"],
        },
        "protocol": {},
        "runtime": {},
        "schema_version": 2,
        "source": {},
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

    reservation.mkdir(mode=0o700)
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
    submission_receipt = {
        "activation": {},
        "artifact_type": "vmvm_task_free_submission_receipt_v2",
        "authorization_file_sha256": launch_authorization_file_sha,
        "authorization_sha256": launch_authorization_sha,
        "environment_sha256": "a" * 64,
        "held": {},
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
    for name, payload, mode in (
        (".writer.lock", b"lock", 0o600),
        ("activation_permit.json", b"permit", 0o400),
        ("job_authorization.json", job_authorization_raw, 0o400),
        ("launch_intent.json", b"intent", 0o400),
        ("slurm_environment.bin", b"environment", 0o400),
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
            "phase_metadata": {
                "last_phase": "release_verified",
                "lease_attempt_limit": FINALIZE.LEASE_ATTEMPT_LIMIT,
                "lease_attempts": 1,
                "phase_counts": {
                    "backend_ready": 1,
                    "release_verified": 1,
                },
                "release_grace_seconds": FINALIZE.RELEASE_GRACE_SECONDS,
                "release_method": "renewer_absent_for_lease_ttl",
                "release_verified": True,
                "renewer_processes": 1,
                "transport_recovery_attempt_limit": FINALIZE.RECOVERY_ATTEMPTS,
                "transport_recovery_attempts": 0,
            },
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
        "environment_sha256": "a" * 64,
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
        "environment_sha256": "a" * 64,
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
            "job_authorization_sha256": job_authorization_sha,
            "reservation_path": str(reservation),
            "reservation_root_identity": reservation_identity,
            "submission_receipt_sha256": submission_receipt_sha,
        },
    }
    body_sha = FINALIZE.sha256_bytes(FINALIZE.canonical_json(authorization_body))
    authorization = {**authorization_body, "authorization_sha256": body_sha}
    authorization_raw = FINALIZE.canonical_json(authorization) + b"\n"
    authorization_path = tmp_path / "completion-authorization.json"
    authorization_path.write_bytes(authorization_raw)
    authorization_path.chmod(0o400)

    bad_body = json.loads(FINALIZE.canonical_json(authorization_body))
    bad_body["submission"]["submission_receipt_sha256"] = "0" * 64
    bad_body_sha = FINALIZE.sha256_bytes(FINALIZE.canonical_json(bad_body))
    bad_authorization = {**bad_body, "authorization_sha256": bad_body_sha}
    bad_raw = FINALIZE.canonical_json(bad_authorization) + b"\n"
    bad_path = tmp_path / "bad-completion-authorization.json"
    bad_path.write_bytes(bad_raw)
    bad_path.chmod(0o400)
    with pytest.raises(FINALIZE.FinalizeError, match="submission_lineage_invalid"):
        FINALIZE.finalize(bad_path, FINALIZE.sha256_bytes(bad_raw))

    tampered_certificate = json.loads(FINALIZE.canonical_json(certificate))
    tampered_certificate["result_counts"]["passed"] -= 1
    with pytest.raises(FINALIZE.FinalizeError, match="certificate_aggregate_invalid"):
        FINALIZE.validate_certificate(tampered_certificate)

    result = FINALIZE.finalize(authorization_path, FINALIZE.sha256_bytes(authorization_raw))
    assert result["state"] == "complete"
    assert result["receipt_sha256"] == FINALIZE.sha256_bytes(receipt_path.read_bytes())
    assert stat.S_IMODE(output.stat().st_mode) == 0o500
    completion_receipt = json.loads(receipt_path.read_bytes())
    assert completion_receipt["launch_authorization_file_sha256"] == (launch_authorization_file_sha)
    assert completion_receipt["launch_authorization_sha256"] == (launch_authorization_sha)
    assert completion_receipt["submission_receipt_sha256"] == (submission_receipt_sha)
    assert completion_receipt["job_authorization_sha256"] == job_authorization_sha
    assert completion_receipt["job"] == {
        **job,
        "terminal_observation_sha256": "d" * 64,
        "terminal_state": "COMPLETED",
    }
    assert {entry.name for entry in output.iterdir()} == {
        "completion_request.json",
        "diagnostic_certificate.json",
    }
