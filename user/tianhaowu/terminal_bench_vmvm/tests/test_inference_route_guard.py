from __future__ import annotations

import hashlib
import json
import signal
import subprocess
from pathlib import Path
from typing import Any

import inference_route_guard as guard_module
import pytest
from deployment_endpoint import load_deployment_endpoint
from deployment_proxy_policy import load_deployment_proxy_policy
from guard_success_receipt import load_guard_success_receipt
from inference_route_generation import route_generation_from_status_endpoints
from inference_route_guard import (
    RouteBinding,
    RouteGuardError,
    load_route_binding,
    prepare_guard_receipt,
    publish_guard_success_receipt,
    run_guarded,
    verify_live_route_generation,
)
from vmvm_tb_v2._vacli.concurrency_telemetry import ConcurrencyTelemetry
from wait_for_inference_routes import ProcessResult


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status(
    endpoints: list[dict[str, Any]],
    *,
    coord_job_id: str = "900",
    coord_started_at: str = "2026-09-17T00:00:00Z",
    coord_ticks: int = 10,
    proxy_job_id: str = "999",
    proxy_first_ready_at: str = "2026-09-17T00:30:00Z",
) -> ProcessResult:
    payload = {
        "schema_version": 4,
        "deployment_id": "deployment-test",
        "phase": "serving",
        "coord": {
            "jobid": coord_job_id,
            "started_at": coord_started_at,
            "ticks_completed": coord_ticks,
        },
        "proxy": {
            "jobid": proxy_job_id,
            "slurm_state": "RUNNING",
            "first_ready_at": proxy_first_ready_at,
        },
        "endpoints_summary": {
            "desired": len(endpoints),
            "ready": len(endpoints),
            "running_not_ready": 0,
            "pending": 0,
        },
        "endpoints": endpoints,
    }
    return ProcessResult(0, json.dumps(payload))


def _binding(
    tmp_path: Path,
    *,
    model: str = "Kimi-K3",
) -> tuple[RouteBinding, list[dict[str, Any]]]:
    request_timeout = 43_200 if model == "Kimi-K3" else 7_200
    deployment_dir = tmp_path / "deployment-test"
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    spec.write_text(f"spec:\n  proxy:\n    config:\n      request_timeout: {request_timeout}\n      num_retries: 0\n")
    (deployment_dir / "proxy_litellm_config.yaml").write_text(
        f"litellm_settings:\n  request_timeout: {request_timeout}\n  num_retries: 0\n"
    )
    proxy_info = deployment_dir / "proxy_info.json"
    proxy_info.write_text(
        json.dumps(
            {
                "host": "proxy-host",
                "port": 8100,
                "url": "http://proxy-host:8100",
                "api_key": "unit-test-secret",
                "model": model,
                "proxy_jobid": "999",
                "extras": {"proxy_type": "litellm", "sticky": True, "redis_port": 6379},
            }
        )
    )
    endpoint = load_deployment_endpoint(
        proxy_info,
        deployment_id="deployment-test",
        expected_model=model,
        deployment_spec=spec,
        expected_proxy_info_sha256=_sha256(proxy_info),
    ).binding
    endpoints = [
        {
            "jobid": str(100 + index),
            "host": f"worker-{index}",
            "port": 8000 + index,
            "slurm_state": "RUNNING",
            "sub_state": "ready",
            "started_at": "2026-09-17T01:00:00Z",
        }
        for index in range(2)
    ]
    coordinator = {
        "jobid": "900",
        "started_at": "2026-09-17T00:00:00Z",
        "ticks_completed": 10,
    }
    generation = route_generation_from_status_endpoints(
        endpoints,
        coordinator,
        {
            "jobid": "999",
            "slurm_state": "RUNNING",
            "first_ready_at": "2026-09-17T00:30:00Z",
        },
    )
    policy = load_deployment_proxy_policy(
        spec,
        expected_spec_sha256=_sha256(spec),
        expected_request_timeout=request_timeout,
    )
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "passed",
                "deployment": "deployment-test",
                "observed_spec_sha256": _sha256(spec),
                "expected_routes": 2,
                "endpoint": endpoint,
                "proxy_policy": policy,
                "serving_route_generation": generation,
                "last_status": {
                    "schema_version": 4,
                    "deployment_id": "deployment-test",
                    "phase": "serving",
                    "desired": 2,
                    "ready": 2,
                    "running_not_ready": 0,
                    "pending": 0,
                    "coordinator_incarnation": generation["coordinator"],
                    "coord_ticks_completed": 10,
                    "serving_route_generation": generation,
                },
                "probe": {
                    "ok": True,
                    "endpoint_authority_sha256": endpoint["authority_sha256"],
                    "coverage": {
                        "ok": True,
                        "expected_routes": 2,
                        "discovered_routes": 2,
                        "backends": sorted(route["backend_sha256"] for route in generation["routes"]),
                    },
                },
            }
        )
    )
    return (
        load_route_binding(
            deployment_id="deployment-test",
            deployment_spec=spec,
            deployment_spec_sha256=_sha256(spec),
            readiness_checkpoint=readiness,
            readiness_checkpoint_sha256=_sha256(readiness),
            proxy_info=proxy_info,
            proxy_info_sha256=_sha256(proxy_info),
            expected_model=model,
        ),
        endpoints,
    )


def test_live_guard_accepts_only_the_bound_job_and_backend_set(tmp_path: Path) -> None:
    binding, endpoints = _binding(tmp_path)
    verify_live_route_generation(
        binding,
        runner=lambda _argv, _timeout: _status(endpoints),
        serve_sh=tmp_path / "serve.sh",
    )

    rotated = [dict(endpoint) for endpoint in endpoints]
    rotated[0]["jobid"] = "999"
    with pytest.raises(RouteGuardError, match="serving_route_generation_changed"):
        verify_live_route_generation(
            binding,
            runner=lambda _argv, _timeout: _status(rotated),
            serve_sh=tmp_path / "serve.sh",
        )


def test_qwen_route_binding_preserves_7200_policy(tmp_path: Path) -> None:
    binding, endpoints = _binding(
        tmp_path,
        model="Qwen3-Coder-480B-A35B-Instruct-FP8",
    )
    assert binding.proxy_policy["request_timeout"] == 7_200
    verify_live_route_generation(
        binding,
        runner=lambda _argv, _timeout: _status(endpoints),
        serve_sh=tmp_path / "serve.sh",
    )

    with pytest.raises(RouteGuardError, match="serving_route_generation_changed"):
        verify_live_route_generation(
            binding,
            runner=lambda _argv, _timeout: _status(
                endpoints,
                proxy_job_id="998",
            ),
            serve_sh=tmp_path / "serve.sh",
        )
    moved = [dict(endpoint) for endpoint in endpoints]
    moved[0]["port"] = 9000
    with pytest.raises(RouteGuardError, match="serving_route_generation_changed"):
        verify_live_route_generation(
            binding,
            runner=lambda _argv, _timeout: _status(moved),
            serve_sh=tmp_path / "serve.sh",
        )

    restarted = [dict(endpoint) for endpoint in endpoints]
    restarted[0]["started_at"] = "2026-09-17T01:01:00Z"
    with pytest.raises(RouteGuardError, match="serving_route_generation_changed"):
        verify_live_route_generation(
            binding,
            runner=lambda _argv, _timeout: _status(restarted),
            serve_sh=tmp_path / "serve.sh",
        )

    with pytest.raises(RouteGuardError, match="serving_route_generation_changed"):
        verify_live_route_generation(
            binding,
            runner=lambda _argv, _timeout: _status(
                endpoints,
                coord_started_at="2026-09-17T00:01:00Z",
            ),
            serve_sh=tmp_path / "serve.sh",
        )


def test_live_guard_rejects_coordinator_tick_regression(tmp_path: Path) -> None:
    binding, endpoints = _binding(tmp_path)

    with pytest.raises(RouteGuardError, match="coordinator_ticks_regressed"):
        verify_live_route_generation(
            binding,
            runner=lambda _argv, _timeout: _status(endpoints, coord_ticks=9),
            serve_sh=tmp_path / "serve.sh",
        )


def test_live_guard_rejects_generated_proxy_policy_rotation(tmp_path: Path) -> None:
    binding, endpoints = _binding(tmp_path)
    generated = binding.deployment_spec.parent / "proxy_litellm_config.yaml"
    generated.write_text(generated.read_text().replace("num_retries: 0", "num_retries: 2"))

    with pytest.raises(RouteGuardError, match="deployment_proxy_policy_changed"):
        verify_live_route_generation(
            binding,
            runner=lambda _argv, _timeout: _status(endpoints),
            serve_sh=tmp_path / "serve.sh",
        )


def test_guard_receipt_removes_stale_and_binds_final_run_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, _ = _binding(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    identity_path = run_dir / "eval_run_identity.json"
    identity_path.write_text("{}\n")
    invocations = run_dir / "eval_invocations.jsonl"
    identity_sha256 = "d" * 64
    invocations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": identity_sha256,
                "role": "smoke",
                "resume": False,
                "host": "test-host",
                "slurm_job_id": "1",
            }
        )
        + "\n"
    )
    results = run_dir / "results.jsonl"
    receipt_path = run_dir / "route_guard_success.json"
    receipt_path.write_text("stale\n")
    monkeypatch.setattr(
        guard_module,
        "load_eval_run_identity",
        lambda *_args, **_kwargs: {
            "eval_run_identity_sha256": identity_sha256,
            "identity": {
                "role": "smoke",
                "deployment": {
                    "id": binding.deployment_id,
                    "spec": {
                        "path": str(binding.deployment_spec),
                        "sha256": binding.deployment_spec_sha256,
                    },
                    "readiness_checkpoint": {
                        "path": str(binding.readiness_checkpoint),
                        "sha256": binding.readiness_checkpoint_sha256,
                    },
                    "endpoint": binding.endpoint,
                    "serving_route_generation": binding.route_generation,
                    "proxy_policy": binding.proxy_policy,
                },
            },
        },
    )

    plan = prepare_guard_receipt(
        binding,
        eval_run_identity=identity_path,
        eval_run_identity_sha256=identity_sha256,
        eval_invocations=invocations,
        results=results,
        receipt=receipt_path,
    )

    assert not receipt_path.exists()
    assert plan.concurrency_telemetry == run_dir / "concurrency_telemetry.json"
    assert plan.slurm_job_id == "1"
    results.write_text('{"aggregate":"result"}\n')
    with pytest.raises(RouteGuardError, match="^guard_receipt_publish_failed$"):
        publish_guard_success_receipt(binding, plan)
    assert not receipt_path.exists()

    telemetry = ConcurrencyTelemetry(
        plan.concurrency_telemetry,
        eval_run_identity_sha256=identity_sha256,
        eval_run_role="smoke",
        slurm_job_id=plan.slurm_job_id,
        register_atexit=False,
    )
    telemetry.vmvm_runtime_started()
    telemetry.lease_start_entered()
    telemetry.lease_tunnel_became_ready()
    telemetry.lease_start_finished()
    telemetry.vmvm_runtime_became_ready()
    telemetry.vmvm_runtime_stopped()
    telemetry.publish()
    publish_guard_success_receipt(binding, plan)
    receipt = load_guard_success_receipt(receipt_path)
    assert receipt["state"] == "passed"
    assert receipt["artifacts"]["results"]["path"] == str(results)
    assert receipt["artifacts"]["concurrency_telemetry"]["path"] == str(plan.concurrency_telemetry)
    assert receipt_path.stat().st_mode & 0o777 == 0o600


def test_supervisor_starts_only_after_preflight_and_aborts_on_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = RouteBinding(
        deployment_id="deployment-test",
        deployment_spec=Path("/spec"),
        deployment_spec_sha256="a" * 64,
        readiness_checkpoint=Path("/readiness"),
        readiness_checkpoint_sha256="b" * 64,
        proxy_info=Path("/proxy"),
        proxy_info_sha256="c" * 64,
        expected_model="Kimi-K3",
        endpoint={},
        proxy_policy={},
        expected_routes=1,
        route_generation={},
        minimum_coord_ticks_completed=0,
    )
    verification_count = 0

    def verifier(_binding: RouteBinding) -> None:
        nonlocal verification_count
        verification_count += 1
        if verification_count == 2:
            raise RouteGuardError("serving_route_generation_changed")

    class FakeProcess:
        pid = 123

        def __init__(self) -> None:
            self.terminated = False

        def wait(self, timeout: float | None = None) -> int:
            if self.terminated:
                return -15
            raise subprocess.TimeoutExpired("evaluator", timeout)

        def poll(self) -> None:
            return None

    process = FakeProcess()
    monkeypatch.setattr(guard_module.subprocess, "Popen", lambda *_args, **_kwargs: process)

    def kill_group(_pid: int, requested_signal: int) -> None:
        if requested_signal == 0 and process.terminated:
            raise ProcessLookupError
        if requested_signal != 0:
            process.terminated = True

    monkeypatch.setattr(
        guard_module.os,
        "killpg",
        kill_group,
    )

    with pytest.raises(RouteGuardError, match="serving_route_generation_changed"):
        run_guarded(["evaluator"], binding, verifier=verifier, poll_interval=0.01)

    assert verification_count == 2
    assert process.terminated is True


@pytest.mark.parametrize("returncode", [0, 7])
def test_supervisor_preserves_route_valid_child_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
) -> None:
    binding = RouteBinding(
        deployment_id="deployment-test",
        deployment_spec=Path("/spec"),
        deployment_spec_sha256="a" * 64,
        readiness_checkpoint=Path("/readiness"),
        readiness_checkpoint_sha256="b" * 64,
        proxy_info=Path("/proxy"),
        proxy_info_sha256="c" * 64,
        expected_model="Kimi-K3",
        endpoint={},
        proxy_policy={},
        expected_routes=1,
        route_generation={},
        minimum_coord_ticks_completed=0,
    )
    verification_count = 0
    callback_count = 0

    def verifier(_binding: RouteBinding) -> None:
        nonlocal verification_count
        verification_count += 1

    def success_callback() -> None:
        nonlocal callback_count
        callback_count += 1

    class FinishedProcess:
        pid = 123

        def wait(self, timeout: float | None = None) -> int:
            return returncode

        def poll(self) -> int:
            return returncode

    monkeypatch.setattr(
        guard_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FinishedProcess(),
    )
    monkeypatch.setattr(
        guard_module.os,
        "killpg",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError),
    )

    assert (
        run_guarded(
            ["evaluator"],
            binding,
            verifier=verifier,
            success_callback=success_callback,
        )
        == returncode
    )
    assert verification_count == 2
    assert callback_count == int(returncode == 0)


def test_supervisor_rejects_rotation_observed_only_after_child_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = RouteBinding(
        deployment_id="deployment-test",
        deployment_spec=Path("/spec"),
        deployment_spec_sha256="a" * 64,
        readiness_checkpoint=Path("/readiness"),
        readiness_checkpoint_sha256="b" * 64,
        proxy_info=Path("/proxy"),
        proxy_info_sha256="c" * 64,
        expected_model="Kimi-K3",
        endpoint={},
        proxy_policy={},
        expected_routes=1,
        route_generation={},
        minimum_coord_ticks_completed=0,
    )
    verification_count = 0
    callback_called = False

    def verifier(_binding: RouteBinding) -> None:
        nonlocal verification_count
        verification_count += 1
        if verification_count == 2:
            raise RouteGuardError("serving_route_generation_changed")

    def success_callback() -> None:
        nonlocal callback_called
        callback_called = True

    class FinishedProcess:
        pid = 123

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(
        guard_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FinishedProcess(),
    )
    monkeypatch.setattr(
        guard_module.os,
        "killpg",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError),
    )

    with pytest.raises(RouteGuardError, match="serving_route_generation_changed"):
        run_guarded(
            ["evaluator"],
            binding,
            verifier=verifier,
            success_callback=success_callback,
        )

    assert verification_count == 2
    assert callback_called is False


def test_supervisor_rejects_ticks_regressing_between_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = RouteBinding(
        deployment_id="deployment-test",
        deployment_spec=Path("/spec"),
        deployment_spec_sha256="a" * 64,
        readiness_checkpoint=Path("/readiness"),
        readiness_checkpoint_sha256="b" * 64,
        proxy_info=Path("/proxy"),
        proxy_info_sha256="c" * 64,
        expected_model="Kimi-K3",
        endpoint={},
        proxy_policy={},
        expected_routes=1,
        route_generation={},
        minimum_coord_ticks_completed=0,
    )
    ticks = iter([11, 10])

    class FakeProcess:
        pid = 123
        terminated = False

        def wait(self, timeout: float | None = None) -> int:
            if self.terminated:
                return -15
            raise subprocess.TimeoutExpired("evaluator", timeout)

        def poll(self) -> None:
            return None

    process = FakeProcess()
    monkeypatch.setattr(guard_module.subprocess, "Popen", lambda *_args, **_kwargs: process)

    def kill_group(_pid: int, requested_signal: int) -> None:
        if requested_signal == 0 and process.terminated:
            raise ProcessLookupError
        if requested_signal != 0:
            process.terminated = True

    monkeypatch.setattr(
        guard_module.os,
        "killpg",
        kill_group,
    )

    with pytest.raises(RouteGuardError, match="coordinator_ticks_regressed"):
        run_guarded(
            ["evaluator"],
            binding,
            verifier=lambda _binding: next(ticks),
            poll_interval=0.01,
        )

    assert process.terminated is True


def test_supervisor_rejects_frozen_ticks_after_bounded_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = RouteBinding(
        deployment_id="deployment-test",
        deployment_spec=Path("/spec"),
        deployment_spec_sha256="a" * 64,
        readiness_checkpoint=Path("/readiness"),
        readiness_checkpoint_sha256="b" * 64,
        proxy_info=Path("/proxy"),
        proxy_info_sha256="c" * 64,
        expected_model="Kimi-K3",
        endpoint={},
        proxy_policy={},
        expected_routes=1,
        route_generation={},
        minimum_coord_ticks_completed=0,
    )
    times = iter([0.0, 10.0, 20.0, 30.0])

    class FakeProcess:
        pid = 123
        terminated = False

        def wait(self, timeout: float | None = None) -> int:
            if self.terminated:
                return -15
            raise subprocess.TimeoutExpired("evaluator", timeout)

        def poll(self) -> None:
            return None

    process = FakeProcess()
    monkeypatch.setattr(guard_module.subprocess, "Popen", lambda *_args, **_kwargs: process)

    def kill_group(_pid: int, requested_signal: int) -> None:
        if requested_signal == 0 and process.terminated:
            raise ProcessLookupError
        if requested_signal != 0:
            process.terminated = True

    monkeypatch.setattr(guard_module.os, "killpg", kill_group)

    with pytest.raises(RouteGuardError, match="coordinator_ticks_not_advancing"):
        run_guarded(
            ["evaluator"],
            binding,
            verifier=lambda _binding: 10,
            poll_interval=10.0,
            coordinator_stall_timeout=30.0,
            monotonic=lambda: next(times),
        )

    assert process.terminated is True


def test_supervisor_rejects_and_kills_descendants_after_leader_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = RouteBinding(
        deployment_id="deployment-test",
        deployment_spec=Path("/spec"),
        deployment_spec_sha256="a" * 64,
        readiness_checkpoint=Path("/readiness"),
        readiness_checkpoint_sha256="b" * 64,
        proxy_info=Path("/proxy"),
        proxy_info_sha256="c" * 64,
        expected_model="Kimi-K3",
        endpoint={},
        proxy_policy={},
        expected_routes=1,
        route_generation={},
        minimum_coord_ticks_completed=0,
    )

    class FinishedLeader:
        pid = 123

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self) -> int:
            return 0

    descendants_alive = True

    def kill_group(_pid: int, requested_signal: int) -> None:
        nonlocal descendants_alive
        if requested_signal == 0:
            if not descendants_alive:
                raise ProcessLookupError
            return
        descendants_alive = False

    callback_called = False

    def success_callback() -> None:
        nonlocal callback_called
        callback_called = True

    monkeypatch.setattr(
        guard_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FinishedLeader(),
    )
    monkeypatch.setattr(guard_module.os, "killpg", kill_group)

    with pytest.raises(RouteGuardError, match="evaluator_process_group_survived"):
        run_guarded(
            ["evaluator"],
            binding,
            verifier=lambda _binding: 10,
            success_callback=success_callback,
        )

    assert descendants_alive is False
    assert callback_called is False


def test_supervisor_terminates_child_group_before_exiting_on_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = RouteBinding(
        deployment_id="deployment-test",
        deployment_spec=Path("/spec"),
        deployment_spec_sha256="a" * 64,
        readiness_checkpoint=Path("/readiness"),
        readiness_checkpoint_sha256="b" * 64,
        proxy_info=Path("/proxy"),
        proxy_info_sha256="c" * 64,
        expected_model="Kimi-K3",
        endpoint={},
        proxy_policy={},
        expected_routes=1,
        route_generation={},
        minimum_coord_ticks_completed=0,
    )
    installed: dict[signal.Signals, Any] = {}
    previous = object()

    monkeypatch.setattr(guard_module.signal, "getsignal", lambda _sig: previous)
    monkeypatch.setattr(
        guard_module.signal,
        "signal",
        lambda sig, handler: installed.__setitem__(sig, handler),
    )

    class SignalledProcess:
        pid = 123
        terminated = False

        def wait(self, timeout: float | None = None) -> int:
            if self.terminated:
                return -15
            installed[signal.SIGTERM](signal.SIGTERM, None)
            raise AssertionError("signal handler must interrupt the wait")

        def poll(self) -> None:
            return None

    process = SignalledProcess()
    monkeypatch.setattr(guard_module.subprocess, "Popen", lambda *_args, **_kwargs: process)

    def kill_group(_pid: int, requested_signal: int) -> None:
        if requested_signal == 0 and process.terminated:
            raise ProcessLookupError
        if requested_signal != 0:
            installed[signal.SIGINT](signal.SIGINT, None)
            process.terminated = True

    monkeypatch.setattr(
        guard_module.os,
        "killpg",
        kill_group,
    )

    with pytest.raises(RouteGuardError, match="guard_interrupted"):
        run_guarded(["evaluator"], binding, verifier=lambda _binding: 10)

    assert process.terminated is True
    assert installed == {signal.SIGTERM: previous, signal.SIGINT: previous}
