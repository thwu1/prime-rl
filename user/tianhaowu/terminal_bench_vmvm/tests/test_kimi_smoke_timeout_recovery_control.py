from __future__ import annotations

import hashlib
import os
import stat
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

WORKFLOW = Path(__file__).resolve().parents[1]
if str(WORKFLOW) not in sys.path:
    sys.path.insert(0, str(WORKFLOW))

import kimi_smoke_timeout_recovery_control as control  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def _plan() -> dict[str, Any]:
    root = "/source"
    return {
        "source_smoke": {
            "job_id": control.SOURCE_JOB_ID,
            "job_name": "legacy-smoke",
            "run_dir": "/source-run",
        },
        "recovery": {
            "job_wrapper": {
                "path": f"{root}/user/tianhaowu/terminal_bench_vmvm/run_kimi_smoke_timeout_recovery_hardened.sbatch",
                "sha256": "a" * 64,
            },
            "log_dir": "/logs",
            "project_root": root,
        },
    }


class PhaseRunner:
    def __init__(
        self,
        *,
        held: bool,
        scontrol_overrides: dict[str, str] | None = None,
        conflicting_user: bool = False,
    ) -> None:
        self.held = held
        self.overrides = scontrol_overrides or {}
        self.conflicting_user = conflicting_user
        self.controls: list[str] = []

    def __call__(self, argv: list[str] | tuple[str, ...], _timeout: float) -> control.CommandResult:
        executable = argv[0]
        job_id = "123"
        job_name = "recovery"
        user_id = "someone(9)" if self.conflicting_user else control.EXPECTED_USER_ID
        if executable == "/usr/bin/scontrol" and "show" in argv:
            values = {
                "JobId": job_id,
                "JobName": job_name,
                "UserId": user_id,
                "JobState": "PENDING" if self.held else "RUNNING",
                "Reason": "JobHeldUser" if self.held else "None",
                "Priority": "0" if self.held else "1",
                "StartTime": "Unknown" if self.held else "2026-09-19T00:00:00",
                "BatchHost": "(null)" if self.held else "node1",
                "Account": "ram",
                "Partition": "cpu_x86",
                "QOS": "cpu_x86_lowest",
                "TimeLimit": "2-00:00:00",
                "NumCPUs": "8",
                "NumNodes": "1-1" if self.held else "1",
                "NodeList": "" if self.held else "node1",
                "Requeue": "0",
                "Restarts": "0",
                "Command": _plan()["recovery"]["job_wrapper"]["path"],
                "WorkDir": "/source",
                "StdOut": "/logs/recovery_123.log",
                "StdErr": "/logs/recovery_123.log",
            }
            values.update(self.overrides)
            raw = " ".join(f"{key}={value}" for key, value in values.items() if value != "") + "\n"
            return control.CommandResult(0, raw, "")
        if executable == "/usr/bin/squeue":
            if "--steps" in argv:
                return control.CommandResult(0, "", "")
            if "%u|%T" in next(item for item in argv if item.startswith("--format=")):
                state = "PENDING" if self.held else "RUNNING"
                reason = "JobHeldUser" if self.held else "None"
                node = "" if self.held else "node1"
                return control.CommandResult(0, f"{job_id}|{job_name}|tianhaowu|{state}|{reason}|1|{node}\n", "")
        if executable == "/usr/bin/sacct":
            if "--allocations" in argv:
                state = "PENDING" if self.held else "RUNNING"
                started = "Unknown" if self.held else "2026-09-19T00:00:00"
                node = "" if self.held else "node1"
                return control.CommandResult(0, f"{job_id}|{job_name}|tianhaowu|{state}|{started}|{node}|0\n", "")
            state = "PENDING" if self.held else "RUNNING"
            return control.CommandResult(0, f"{job_id}|{state}\n", "")
        if executable in {"/usr/bin/scontrol", "/usr/bin/scancel"}:
            self.controls.append(executable)
            return control.CommandResult(0, "", "")
        raise AssertionError(argv)


@pytest.mark.parametrize("held", [True, False])
def test_full_scheduler_phase_accepts_exact_held_and_activation(held: bool) -> None:
    mismatches, conflicts, state = control._scheduler_phase_evidence(
        _plan(), "123", "recovery", held=held, runner=PhaseRunner(held=held)
    )

    assert mismatches == set()
    assert conflicts == set()
    assert state == ("PENDING" if held else "RUNNING")


def test_sbatch_command_is_exactly_one_held_fresh_allocation() -> None:
    command = control._sbatch_command(_plan(), "recovery", Path("/private/environment.bin"))

    assert command[0] == "/usr/bin/sbatch"
    assert command.count("--hold") == 1
    assert command.count("--no-requeue") == 1
    assert "--nodes=1" in command
    assert "--ntasks=1" in command
    assert "--cpus-per-task=8" in command
    assert "--mem=16G" in command
    assert "--time=2-00:00:00" in command
    assert "--export-file=/private/environment.bin" in command
    assert command[-1] == _plan()["recovery"]["job_wrapper"]["path"]


def test_proxy_binding_requires_exact_model_job_and_deployment_local_path(tmp_path: Path) -> None:
    deployment = tmp_path / "deployment"
    deployment.mkdir()
    proxy = deployment / "proxy_info.json"
    spec = deployment / "spec.yaml"
    value = {
        "api_key": "private",
        "extras": {},
        "host": "proxy.example",
        "model": "Kimi-K3",
        "port": 8000,
        "proxy_jobid": "123",
        "url": "http://proxy.example:8000",
    }

    assert control._validate_proxy_binding(
        value,
        proxy_path=proxy,
        spec_path=spec,
        deployment_id="deployment",
        proxy_job_id="123",
    ) == ("proxy.example", 8000)
    value["model"] = "other"
    with pytest.raises(control.RecoveryControlError, match="proxy_info_invalid"):
        control._validate_proxy_binding(
            value,
            proxy_path=proxy,
            spec_path=spec,
            deployment_id="deployment",
            proxy_job_id="123",
        )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"NumNodes": "1"}, "NumNodes"),
        ({"NodeList": "node1"}, "held_state"),
        ({"Restarts": "1"}, "Restarts"),
        ({"Command": "/wrong"}, "Command"),
        ({"WorkDir": "/wrong"}, "WorkDir"),
    ],
)
def test_held_identity_rejects_relaxed_or_conflicting_fields(overrides: dict[str, str], expected: str) -> None:
    mismatches, _conflicts, _state = control._scheduler_phase_evidence(
        _plan(),
        "123",
        "recovery",
        held=True,
        runner=PhaseRunner(held=True, scontrol_overrides=overrides),
    )

    assert expected in mismatches


def test_poll_identity_requires_two_complete_views_and_spans_deadline() -> None:
    clock = Clock()
    runner = PhaseRunner(held=True, scontrol_overrides={"NumNodes": "1"})

    result = control._poll_identity(
        _plan(),
        "123",
        "recovery",
        held=True,
        timeout=10,
        runner=runner,
        sleeper=clock.sleep,
        clock=clock,
    )

    assert result["converged"] is False
    assert result["polls"] == 5
    assert result["elapsed_milliseconds"] == 10_000
    assert result["final_mismatch_fields"] == ["NumNodes"]


def test_phase_certificate_rejects_conflict_even_if_marked_converged() -> None:
    value = {
        "converged": True,
        "polls": 2,
        "elapsed_milliseconds": 2_000,
        "mismatch_fields": [],
        "mismatch_occurrences": {},
        "final_mismatch_fields": [],
        "explicit_conflict_fields": ["UserId"],
        "state": "PENDING",
    }

    with pytest.raises(control.RecoveryControlError, match="scheduler_phase_certificate_invalid"):
        control.validate_phase_certificate(value, state="PENDING", timeout=control.HELD_TIMEOUT_SECONDS)


def test_explicit_identity_conflict_never_controls_job() -> None:
    runner = PhaseRunner(held=True, conflicting_user=True)

    with pytest.raises(control.LifecycleError, match="cancellation_unconfirmed") as raised:
        control.cancel_and_prove(
            "123",
            "recovery",
            _plan(),
            direct_provenance=True,
            runner=runner,
            sleeper=lambda _seconds: None,
            clock=Clock(),
        )

    assert raised.value.cancellation["cancel_attempts"] == 0
    assert "UserId" in raised.value.cancellation["explicit_conflict_fields"]
    assert runner.controls == []


class UnavailableIdentityRunner:
    def __init__(self) -> None:
        self.cancelled = False
        self.cancel_calls = 0

    def __call__(self, argv: list[str] | tuple[str, ...], _timeout: float) -> control.CommandResult:
        executable = argv[0]
        if executable == "/usr/bin/scontrol" and "show" in argv:
            return control.CommandResult(1, "", "unavailable")
        if executable == "/usr/bin/scancel":
            self.cancel_calls += 1
            self.cancelled = True
            return control.CommandResult(0, "", "")
        if executable == "/usr/bin/squeue":
            if self.cancelled:
                return control.CommandResult(0, "", "")
            return control.CommandResult(0, "123|recovery|tianhaowu\n", "")
        if executable == "/usr/bin/sacct" and "--allocations" in argv:
            state = "CANCELLED" if self.cancelled else "PENDING"
            return control.CommandResult(0, f"123|recovery|tianhaowu|{state}\n", "")
        if executable == "/usr/bin/sacct":
            state = "CANCELLED" if self.cancelled else "PENDING"
            return control.CommandResult(0, f"123|{state}\n", "")
        raise AssertionError(argv)


def test_direct_sbatch_provenance_allows_one_cancel_after_identity_unavailable() -> None:
    runner = UnavailableIdentityRunner()
    clock = Clock()

    evidence = control.cancel_and_prove(
        "123",
        "recovery",
        _plan(),
        direct_provenance=True,
        runner=runner,
        sleeper=clock.sleep,
        clock=clock,
    )

    assert runner.cancel_calls == 1
    assert evidence["identity_status"] == "direct_provenance_fallback"
    assert evidence["terminal_state"] == "CANCELLED"
    assert evidence["terminal_consecutive"] == control.TERMINAL_PROOF_ROUNDS


def test_name_only_candidate_is_never_cancelled_when_identity_unavailable() -> None:
    runner = UnavailableIdentityRunner()
    clock = Clock()

    with pytest.raises(control.LifecycleError, match="cancellation_unconfirmed") as raised:
        control.cancel_and_prove(
            "123",
            "recovery",
            _plan(),
            direct_provenance=False,
            runner=runner,
            sleeper=clock.sleep,
            clock=clock,
        )

    assert runner.cancel_calls == 0
    assert raised.value.cancellation["identity_status"] == "unavailable"


def test_ambiguous_submission_requires_six_zero_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    calls = 0

    def no_matches(_name: str, *, runner: Any) -> list[str]:
        nonlocal calls
        del runner
        calls += 1
        return []

    monkeypatch.setattr(control, "scheduler_name_matches", no_matches)
    candidate, evidence = control.resolve_submission_visibility(
        "recovery",
        None,
        runner=lambda _argv, _timeout: control.CommandResult(0, "", ""),
        sleeper=clock.sleep,
        clock=clock,
    )

    assert candidate is None
    assert calls == control.TERMINAL_PROOF_ROUNDS
    assert evidence == {"polls": control.TERMINAL_PROOF_ROUNDS, "zero_rounds": 6}


def test_writer_lock_replacement_is_detected(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    lock_path = run / ".writer.lock"
    lock_path.write_bytes(b"")
    handle, identity = control.acquire_writer_lock(run.resolve())
    replacement = run / ".replacement"
    replacement.write_bytes(b"")
    os.replace(replacement, lock_path)
    try:
        with pytest.raises(control.RecoveryControlError, match="source_writer_lock_changed"):
            control.validate_writer_lock_identity(run.resolve(), handle, identity)
    finally:
        handle.close()


def test_any_existing_smoke_certificate_blocks_recovery(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    (run / "smoke_checkpoint.json").write_text("{}", encoding="utf-8")

    with pytest.raises(control.RecoveryControlError, match="successful_smoke_already_certified"):
        control.validate_source_run({"source_smoke": {"run_dir": str(run.resolve())}})


def test_source_terminal_gate_never_accepts_an_active_allocation() -> None:
    def active_runner(argv: list[str] | tuple[str, ...], _timeout: float) -> control.CommandResult:
        if argv[0] == "/usr/bin/squeue" and "--steps" not in argv:
            return control.CommandResult(
                0, f"{control.SOURCE_JOB_ID}|legacy-smoke|RUNNING\n", ""
            )
        if argv[0] == "/usr/bin/squeue":
            return control.CommandResult(0, "", "")
        raise AssertionError(argv)

    with pytest.raises(control.RecoveryControlError, match="source_job_not_terminal"):
        control.source_terminal_snapshot(_plan(), runner=active_runner)


def test_route_redirects_are_rejected_without_following() -> None:
    handler = control.RejectRedirects()

    with pytest.raises(control.RecoveryControlError, match="route_redirect_forbidden"):
        handler.redirect_request(None, None, 302, "", {}, "http://other.invalid/")


def test_trigger_uses_six_samples_and_at_least_120_seconds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    approval = tmp_path / "approval"
    approval.mkdir(mode=0o700)
    run = tmp_path / "source"
    run.mkdir(mode=0o700)
    (run / ".writer.lock").write_bytes(b"")
    namespace_parent = tmp_path / "certificates"
    namespace_parent.mkdir(mode=0o700)
    output = namespace_parent / "kimi_smoke_terminal_quiescence_test" / "terminal_quiescence_gate.json"
    plan_path = approval / "plan.json"
    plan_path.write_bytes(b"{}")
    os.chmod(plan_path, 0o400)
    plan_artifact = control.stable_file(plan_path.resolve(), code="test", mode=0o400)
    plan = {
        "source_smoke": {"run_dir": str(run.resolve())},
        "recovery": {
            "output_dir": str(tmp_path / "kimi_smoke_recovery_output"),
            "reservation_dir": str(tmp_path / "kimi_smoke_recovery_reservation"),
            "log_dir": str(tmp_path / "kimi_smoke_recovery_logs"),
        },
    }
    artifact_path = run / "artifact"
    artifact_path.write_bytes(b"fixed")
    artifact = control.stable_file(artifact_path.resolve(), code="test")
    calls = {"terminal": 0, "source": 0, "route": 0}

    monkeypatch.setattr(control, "load_plan", lambda _path: (plan, plan_artifact))
    monkeypatch.setattr(control, "validate_source", lambda _plan: {})
    monkeypatch.setattr(control, "validate_runtime_manifest", lambda _plan: {})
    monkeypatch.setattr(control, "validate_external_inputs", lambda _plan: {})

    def terminal(_plan: Any, *, runner: Any) -> dict[str, Any]:
        del runner
        calls["terminal"] += 1
        return {
            "state": "TIMEOUT",
            "accounting_signature_sha256": "e" * 64,
            "exit_code_sha256": "a" * 64,
            "ended_at_sha256": "b" * 64,
            "accounting_rows": 2,
            "queue_rows": 0,
            "step_queue_rows": 0,
            "restarts": 0,
        }

    def source(_plan: Any) -> tuple[dict[str, control.StableFile], dict[str, int]]:
        calls["source"] += 1
        return {"artifact": artifact}, {
            "source_rows": 1,
            "retained_rows": 1,
            "missing_rows": 1,
            "harness_timeout_rows": 0,
        }

    def route(_plan: Any, *, runner: Any, fetcher: Any) -> dict[str, Any]:
        del runner, fetcher
        calls["route"] += 1
        return {
            "readiness_sha256": "c" * 64,
            "route_generation_sha256": "d" * 64,
            "routes": 2,
            "healthy": 2,
            "unhealthy": 0,
            "active": 0,
            "waiting": 0,
            "restart_count": 0,
        }

    monkeypatch.setattr(control, "source_terminal_snapshot", terminal)
    monkeypatch.setattr(control, "validate_source_run", source)
    monkeypatch.setattr(control, "route_idle_snapshot", route)
    clock = Clock()

    result = control.certify_trigger(
        plan_path.resolve(),
        output.resolve(),
        runner=lambda _argv, _timeout: control.CommandResult(0, "", ""),
        fetcher=lambda _url, _timeout: (200, b""),
        sleeper=clock.sleep,
        clock=clock,
        invocation_validator=lambda _plan: None,
    )

    assert result["state"] == "eligible"
    assert result["retained_legacy_rows"] == 0
    assert clock.value == 120
    assert calls == {"terminal": 7, "source": 7, "route": 7}
    value, _artifact = control.strict_envelope(
        output.resolve(),
        kind=control.TRIGGER_KIND,
        hash_field="trigger_sha256",
        code="test",
    )
    assert value["quiescence"]["samples"] == 6
    assert value["quiescence"]["elapsed_milliseconds"] >= 120_000


def test_config_is_exact_fresh_two_vmvm_256k_trace_contract() -> None:
    config_path = WORKFLOW / "configs/eval/tb4_kimi_k3_fresh_smoke12h.toml"
    config_raw = config_path.read_bytes()
    config = tomllib.loads(config_raw.decode("utf-8"))

    assert config["num_tasks"] == 2
    assert config["num_rollouts"] == 1
    assert config["max_concurrent"] == 2
    assert config["multiplex"] == 2
    assert config["max_input_tokens"] == 262_144
    assert config["max_output_tokens"] == 262_144
    assert config["max_total_tokens"] == 262_144
    assert config["client"]["capture_model_io"] is True
    assert config["client"]["timeout"] == 43_200
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["sampling"]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }
    assert config["harness"]["runtime"]["type"] == "vmvm"
    assert config["harness"]["runtime"]["session_timeout"] == 43_200
    assert config["retries"]["rollout"] == {
        "max_retries": 2,
        "include": ["ProviderError", "SandboxError", "InterceptionError", "TunnelError"],
    }
    assert hashlib.sha256(config_raw).hexdigest() == control.FRESH_TWO_CONFIG_SHA256
    assert (
        hashlib.sha256((WORKFLOW / "configs/eval/tb4_kimi_token_smoke.tasks.txt").read_bytes()).hexdigest()
        == control.FRESH_TWO_TASK_SHA256
    )
    assert (
        hashlib.sha256((WORKFLOW / "run_kimi_smoke_recovery.sbatch").read_bytes()).hexdigest()
        == control.RECOVERY_WRAPPER_SHA256
    )


def test_hardened_batch_is_fresh_two_and_clean_environment_only() -> None:
    raw = (WORKFLOW / "run_kimi_smoke_timeout_recovery_hardened.sbatch").read_text(encoding="utf-8")

    assert raw.startswith("#!/usr/bin/bash\n")
    assert "--hold" not in raw
    assert "KIMI_SMOKE_RECOVERY_MODE:-} == fresh-two" in raw
    assert "RESUME_DIR+x" in raw
    assert "KIMI_SMOKE_RECOVERY_SELECTION+x" in raw
    assert "KIMI_SMOKE_COMPOSITE_OUTPUT_DIR+x" in raw
    assert "exec /usr/bin/env -i" in raw
    assert '"$PYTHON_BIN_X86_64" -I -S -B' in raw
    assert "RECOVERY_ACTIVATION_PERMIT" in raw
    assert 'exec {controller_fd}<"$controller"' in raw
    assert '"$controller_fd_path" run-job' in raw
    assert control.ADMISSION_TIMEOUT_SECONDS > (
        control.ACTIVATION_TIMEOUT_SECONDS + 6 * control.COMMAND_TIMEOUT_SECONDS
    )
    assert "RECOVERY_ADMISSION_TIMEOUT_SECONDS=1500" in raw


def test_source_tree_contains_no_ignored_python_cache() -> None:
    root = WORKFLOW.parents[2]
    ignored = control.git_output(
        root,
        "status",
        "--porcelain=v1",
        "--ignored",
        "--untracked-files=all",
        "--",
        "user/tianhaowu/terminal_bench_vmvm",
    )
    assert "__pycache__" not in ignored


def test_publication_modes_are_private(tmp_path: Path) -> None:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    path = parent / "receipt.json"
    control.atomic_write_once(path.resolve(), b"{}\n", mode=0o400)

    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert path.stat().st_nlink == 1

    with pytest.raises(control.RecoveryControlError, match="publication_target_exists"):
        control.atomic_write_once(path.resolve(), b"replacement\n", mode=0o400)
    assert path.read_bytes() == b"{}\n"
