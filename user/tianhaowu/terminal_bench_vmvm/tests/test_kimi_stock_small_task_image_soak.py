from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import kimi_stock_small_task_image_soak as soak
import pytest


class _State:
    def __init__(self) -> None:
        self.active = 0
        self.high_water = 0
        self.attempts: dict[int, int] = {}


class _Runtime:
    def __init__(self, task: int, state: _State, fail_first: bool) -> None:
        self.task = task
        self.state = state
        self.fail_first = fail_first
        self.active = False

    async def start(self) -> None:
        await asyncio.sleep(0)
        self.state.attempts[self.task] = self.state.attempts.get(self.task, 0) + 1
        if self.fail_first and self.state.attempts[self.task] == 1:
            raise RuntimeError("opaque")
        self.active = True
        self.state.active += 1
        self.state.high_water = max(self.state.high_water, self.state.active)

    async def run(self, argv: list[str], env: dict[str, str]) -> SimpleNamespace:
        assert argv == ["sh", "-c", ":"]
        assert env == {}
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    async def stop(self) -> None:
        if self.active:
            self.active = False
            self.state.active -= 1


class _Taskset:
    def __init__(self, state: _State) -> None:
        self.state = state
        self.closed = False

    async def setup(self, task: int, runtime: _Runtime) -> None:
        assert 1 <= self.state.active <= soak.CONCURRENCY
        assert runtime.active

    async def _score_shared(self, task: int, runtime: _Runtime):
        assert runtime.active
        result = SimpleNamespace(exit_code=1, stdout="discarded", stderr="discarded")
        return result, False, 0.0, {"solved": 0.0}, None, 1, []

    async def cleanup(self, task: int, trace: object, runtime: _Runtime) -> None:
        assert trace is None

    async def close(self) -> None:
        self.closed = True


def test_execute_soak_holds_all_images_before_setup_and_retains_only_aggregates() -> None:
    state = _State()
    taskset = _Taskset(state)

    def runtime_factory(task: int) -> _Runtime:
        return _Runtime(task, state, fail_first=False)

    value = asyncio.run(
        soak.execute_soak(
            taskset,
            tuple(range(soak.SELECTED_TASKS)),
            runtime_factory=runtime_factory,
            monotonic=lambda: 1.0,
        )
    )

    assert value["state"] == "passed"
    assert value["live_runtime_high_water"] == 64
    assert value["counts"]["setup_succeeded"] == soak.SELECTED_TASKS
    assert value["counts"]["benign_exec_succeeded"] == soak.SELECTED_TASKS
    assert value["counts"]["shared_verifier_executed"] == soak.SELECTED_TASKS
    assert value["counts"]["shared_verifier_zero_reward"] == soak.SELECTED_TASKS
    assert value["counts"]["runtime_cleanup_succeeded"] == soak.SELECTED_TASKS
    assert state.high_water == 64
    assert state.active == 0
    assert taskset.closed
    serialized = json.dumps(value, sort_keys=True)
    assert "discarded" not in serialized
    assert "opaque" not in serialized


def test_execute_soak_allows_eight_bounded_pre_execution_retries() -> None:
    state = _State()
    taskset = _Taskset(state)

    def runtime_factory(task: int) -> _Runtime:
        return _Runtime(task, state, fail_first=task == 0)

    value = asyncio.run(
        soak.execute_soak(
            taskset,
            tuple(range(soak.SELECTED_TASKS)),
            runtime_factory=runtime_factory,
            monotonic=lambda: 1.0,
        )
    )

    assert value["state"] == "passed"
    assert value["counts"]["provisioning_attempts"] == soak.SELECTED_TASKS + 1
    assert value["counts"]["provisioning_retries"] == 1
    assert state.attempts[0] == 2
    assert state.high_water == 64
    assert state.active == 0


def test_execute_soak_retries_runtime_factory_failure_without_leaking() -> None:
    state = _State()
    taskset = _Taskset(state)
    factory_attempts: dict[int, int] = {}

    def runtime_factory(task: int) -> _Runtime:
        factory_attempts[task] = factory_attempts.get(task, 0) + 1
        if task == 0 and factory_attempts[task] == 1:
            raise RuntimeError("opaque")
        return _Runtime(task, state, fail_first=False)

    value = asyncio.run(
        soak.execute_soak(
            taskset,
            tuple(range(soak.SELECTED_TASKS)),
            runtime_factory=runtime_factory,
            monotonic=lambda: 1.0,
        )
    )

    assert value["state"] == "passed"
    assert value["counts"]["provisioning_attempts"] == soak.SELECTED_TASKS + 1
    assert factory_attempts[0] == 2
    assert state.high_water == soak.CONCURRENCY
    assert state.active == 0


def test_contract_is_no_model_c64_firecracker_small() -> None:
    value = soak._contracts()

    assert value["task_count"] == 2_499
    assert value["concurrency"] == 64
    assert value["sandbox"]["environment"] == "oci-runner-firecracker-small"
    assert value["sandbox"]["resource_caps"] == {
        "cpu": 1,
        "memory_mb": 2048,
        "storage_mb": 10240,
    }
    assert value["sandbox"]["provisioning_retries"] == 8
    assert value["endpoint_epoch"] == {
        "capacity_profile": "sandoq-stock-single-c64-v1",
        "endpoint_identifier": "tianhaowu-kimi-k3-stock-eval-20260927",
        "capacity_receipt_sha256": soak.STOCK_CAPACITY_SHA256,
        "minimum_remaining_seconds": 518400,
        "walltime_gate_task_count": 64,
        "capture_before_sandbox_start": True,
    }
    assert value["execution"]["taskset_setup"] is True
    assert value["execution"]["shared_verifier"] is True
    assert value["execution"]["model_calls"] == 0
    assert value["execution"]["harness_invocations"] == 0
    assert value["privacy"]["receipt"] == "aggregate-only"


def test_fixed_capacity_receipts_and_endpoint_epoch_are_valid() -> None:
    lifecycle_record, _ = soak._validate_lifecycle_soak()
    stock_record, _, endpoint_jobs_sha256 = soak._validate_stock_capacity()

    assert lifecycle_record["sha256"] == soak.LIFECYCLE_SOAK_SHA256
    assert stock_record["sha256"] == soak.STOCK_CAPACITY_SHA256
    assert len(endpoint_jobs_sha256) == 64


def test_run_result_validator_rejects_less_than_c64_high_water(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan_sha256 = "a" * 64
    counts = {
        "tasks": 2_499,
        "provisioned": 2_499,
        "provisioning_attempts": 2_499,
        "provisioning_retries": 0,
        "provisioning_failures": 0,
        "provisioning_cleanup_failures": 0,
        "setup_succeeded": 2_499,
        "benign_exec_succeeded": 2_499,
        "shared_verifier_executed": 2_499,
        "shared_verifier_zero_reward": 2_499,
        "shared_verifier_positive_reward": 0,
        "shared_verifier_retry_attempts": 0,
        "setup_failures": 0,
        "benign_exec_failures": 0,
        "shared_verifier_failures": 0,
        "taskset_cleanup_succeeded": 2_499,
        "runtime_cleanup_succeeded": 2_499,
        "cleanup_failures": 0,
        "taskset_close_succeeded": 1,
    }
    value = {
        "schema_version": 1,
        "kind": soak.RUN_KIND,
        "state": "passed",
        "plan": {"path": str(plan), "sha256": plan_sha256},
        "endpoint_gate": {"endpoint_jobs_sha256": "b" * 64},
        "contracts": {
            "concurrency": 64,
            "provisioning_retries": 8,
            "maximum_provisioning_attempts": 9,
            "resource_caps": {"cpu": 1, "memory_mb": 2048, "storage_mb": 10240},
            "model_calls": 0,
            "harness_invocations": 0,
            "raw_output_retained": False,
        },
        "live_runtime_high_water": 64,
        "counts": counts,
        "pool_departed": True,
        "elapsed_seconds": 1.0,
    }
    plan_value = {"endpoint_epoch": {"endpoint_jobs_sha256": "b" * 64}}
    soak._validate_run_value(value, plan, plan_sha256, plan_value)
    value["live_runtime_high_water"] = 63
    with pytest.raises(soak.TaskImageSoakError, match="run_result_invalid"):
        soak._validate_run_value(value, plan, plan_sha256, plan_value)


def test_launcher_is_c64_no_inference_and_fails_closed() -> None:
    launcher = Path(soak.__file__).with_name("run_kimi_stock_small_task_image_soak.sbatch").read_text()

    assert "--concurrency 64" in launcher
    assert "--lease-create-cap 8" in launcher
    assert "--lease-profile kimi-tb4-long" in launcher
    assert "--minimum-remaining-seconds 518400" in launcher
    assert "--task-count 64" in launcher
    assert '"$selected_tasks" == 2499' in launcher
    assert "36b0dff6c18affb3d40b7c46d5836381d568050b" in launcher
    assert "kimi_endpoint_walltime_gate.py\" capture" in launcher
    assert launcher.index("kimi_endpoint_walltime_gate.py\" capture") < launcher.index("--concurrency 64")
    assert "#SBATCH --cpus-per-task=72" in launcher
    assert "#SBATCH --mem=96G" in launcher
    assert "python3 \"$tool\" run" in launcher
    assert "python3 \"$tool\" certify" in launcher
    assert "mini-swe" not in launcher.lower()
    assert "curl" not in launcher
    assert "\nsbatch " not in launcher
