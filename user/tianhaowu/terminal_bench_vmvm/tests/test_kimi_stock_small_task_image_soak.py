from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import kimi_stock_small_task_image_soak as soak
import pytest
from terminal_bench_vmvm import sandoq_provider_context as provider_context


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


def test_execute_soak_counts_only_attempted_terminal_provisioning_failure() -> None:
    state = _State()
    taskset = _Taskset(state)

    def runtime_factory(task: int) -> _Runtime:
        return _Runtime(task, state, fail_first=task == 0)

    original_attempts = soak.MAX_PROVISIONING_ATTEMPTS
    soak.MAX_PROVISIONING_ATTEMPTS = 1
    try:
        value = asyncio.run(
            soak.execute_soak(
                taskset,
                tuple(range(soak.SELECTED_TASKS)),
                runtime_factory=runtime_factory,
                monotonic=lambda: 1.0,
            )
        )
    finally:
        soak.MAX_PROVISIONING_ATTEMPTS = original_attempts

    assert value["state"] == "unavailable"
    assert value["counts"]["provisioned"] == soak.CONCURRENCY - 1
    assert value["counts"]["provisioning_attempts"] == soak.CONCURRENCY
    assert value["counts"]["provisioning_retries"] == 0
    assert value["counts"]["provisioning_failures"] == 1
    assert value["counts"]["tasks"] - value["counts"]["provisioned"] - value["counts"]["provisioning_failures"] == 2_435


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
    assert value["execution"]["verifier_execution"] == "background-program"
    assert value["execution"]["shared_verifier_taskset_retries"] == 0
    assert value["execution"]["maximum_shared_verifier_attempts"] == 1
    assert value["execution"]["model_calls"] == 0
    assert value["execution"]["harness_invocations"] == 0
    assert value["privacy"]["receipt"] == "aggregate-only"


def test_fixed_capacity_receipts_and_endpoint_epoch_are_valid() -> None:
    lifecycle_record, _ = soak._validate_lifecycle_soak()
    stock_record, _, endpoint_jobs_sha256 = soak._validate_stock_capacity()

    assert lifecycle_record["sha256"] == soak.LIFECYCLE_SOAK_SHA256
    assert stock_record["sha256"] == soak.STOCK_CAPACITY_SHA256
    assert len(endpoint_jobs_sha256) == 64


def test_validate_plan_reopens_image_manifest_artifact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    approved = tmp_path / "approved.txt"
    approved_body = b"opaque\n"
    approved.write_bytes(approved_body)
    image = tmp_path / "images.json"
    image_body = b"{}\n"
    image.write_bytes(image_body)
    profile = tmp_path / "profile.json"
    profile_body = b"{}\n"
    profile.write_bytes(profile_body)
    lifecycle = tmp_path / "lifecycle.json"
    lifecycle_body = b"{}\n"
    lifecycle.write_bytes(lifecycle_body)
    lifecycle.chmod(0o600)
    stock = tmp_path / "stock.json"
    stock_body = b"{}\n"
    stock.write_bytes(stock_body)
    stock.chmod(0o600)

    members = ("opaque-member",)
    coverage = {"opaque": True}
    selector_body = soak.legacy._task_payload(members)
    output = tmp_path / "plan"
    output.mkdir()
    selector = output / "selector.tasks.txt"
    selector.write_bytes(selector_body)
    selector.chmod(0o600)
    selector_receipt = output / "selector.receipt.json"
    selector_receipt_body = soak._canonical(soak._selector_receipt(selector_body, coverage))
    selector_receipt.write_bytes(selector_receipt_body)
    selector_receipt.chmod(0o600)

    tool = Path(soak.__file__).resolve(strict=True)
    launcher = soak._launcher_path().resolve(strict=True)
    endpoint_jobs_sha256 = "e" * 64
    revision = "a" * 40
    monkeypatch.setattr(soak, "_validate_source", lambda project, expected: project)
    monkeypatch.setattr(soak.legacy, "_canonical_source_path", lambda: approved)
    monkeypatch.setattr(soak.legacy, "CANONICAL_SOURCE_SHA256", soak._sha256(approved_body))
    monkeypatch.setattr(soak, "IMAGE_MANIFEST_SHA256", soak._sha256(image_body))
    monkeypatch.setattr(
        soak,
        "_derive_selection",
        lambda requested: (approved, approved_body, dataset, members, coverage),
    )
    monkeypatch.setattr(
        soak,
        "_validate_provider_profile",
        lambda: (soak._artifact(profile, profile_body), profile_body),
    )
    monkeypatch.setattr(
        soak,
        "_validate_lifecycle_soak",
        lambda: (soak._artifact(lifecycle, lifecycle_body), lifecycle_body),
    )
    monkeypatch.setattr(
        soak,
        "_validate_stock_capacity",
        lambda: (soak._artifact(stock, stock_body), stock_body, endpoint_jobs_sha256),
    )

    unsigned = {
        "schema_version": soak.SCHEMA_VERSION,
        "kind": soak.PLAN_KIND,
        "state": "authorized",
        "source_revision": revision,
        "source": {
            "project_root": str(root),
            "approved_selector_source": soak._artifact(approved, approved_body),
            "dataset": {
                "path": str(dataset),
                "revision": soak.legacy.CANONICAL_DATASET_REVISION,
                "tree": soak.legacy.CANONICAL_DATASET_TREE,
            },
            "image_manifest": soak._artifact(image, image_body),
            "provider_profile": soak._artifact(profile, profile_body),
            "lifecycle_c64_soak": soak._artifact(lifecycle, lifecycle_body),
            "stock_model_c64": soak._artifact(stock, stock_body),
            "tool": soak._artifact(tool, tool.read_bytes()),
            "launcher": soak._artifact(launcher, launcher.read_bytes()),
        },
        "selection": {
            "count": soak.SELECTED_TASKS,
            "selector": soak._artifact(selector, selector_body),
            "receipt": soak._artifact(selector_receipt, selector_receipt_body),
        },
        "endpoint_epoch": {"endpoint_jobs_sha256": endpoint_jobs_sha256},
        "contracts": soak._contracts(),
    }
    plan_value = {**unsigned, "plan_sha256": soak._sha256(soak._canonical(unsigned))}
    plan = output / "plan.json"
    plan_body = soak._canonical(plan_value)
    plan.write_bytes(plan_body)
    plan.chmod(0o600)

    assert soak.validate_plan(plan, soak._sha256(plan_body)) == plan_value


@pytest.mark.parametrize("schema_version", [soak.SCHEMA_VERSION, soak.DYNAMIC_SCHEMA_VERSION])
def test_validate_receipt_accepts_only_an_exact_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_version: int,
) -> None:
    run_root = tmp_path / f"run-v{schema_version}"
    run_root.mkdir(mode=0o700)
    plan_path = tmp_path / f"plan-v{schema_version}.json"
    plan_sha256 = "a" * 64
    expected = {
        "schema_version": schema_version,
        "kind": soak.RECEIPT_KIND,
        "state": "passed",
        "source_revision": "b" * 40,
        "plan": {"path": str(plan_path), "sha256": plan_sha256},
    }
    if schema_version == soak.DYNAMIC_SCHEMA_VERSION:
        expected["endpoint_binding"] = {
            "capacity_profile": soak.STOCK_CAPACITY_PROFILE,
            "capacity_receipt_sha256": "c" * 64,
            "deployment_id": "fresh-endpoint",
            "endpoint_jobs_sha256": "d" * 64,
        }
    expected["certificate_sha256"] = soak._sha256(soak._canonical(expected))
    receipt = run_root / "receipt.json"
    body = soak._canonical(expected)
    receipt.write_bytes(body)
    receipt.chmod(0o600)
    observed: list[tuple[Path, str, Path]] = []

    def rebuild(*, plan_path: Path, plan_sha256: str, run_root: Path) -> dict[str, object]:
        observed.append((plan_path, plan_sha256, run_root))
        return copy.deepcopy(expected)

    monkeypatch.setattr(soak, "_build_receipt", rebuild)

    assert soak.validate_task_image_soak_receipt(
        receipt,
        soak._sha256(body),
        expected_revision="b" * 40,
    ) == (receipt, body)
    assert observed == [(plan_path, plan_sha256, run_root)]

    if schema_version == soak.SCHEMA_VERSION:
        changed = copy.deepcopy(expected)
        changed["endpoint_binding"] = {"unexpected": True}
        unsigned = dict(changed)
        unsigned.pop("certificate_sha256")
        changed["certificate_sha256"] = soak._sha256(soak._canonical(unsigned))
        changed_body = soak._canonical(changed)
        receipt.write_bytes(changed_body)
        with pytest.raises(soak.TaskImageSoakError, match="receipt_invalid"):
            soak.validate_task_image_soak_receipt(receipt, soak._sha256(changed_body))


def test_validate_dynamic_receipt_rejects_binding_tamper_shape_and_unknown_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir(mode=0o700)
    plan_path = tmp_path / "plan.json"
    expected = {
        "schema_version": soak.DYNAMIC_SCHEMA_VERSION,
        "kind": soak.RECEIPT_KIND,
        "state": "passed",
        "source_revision": "b" * 40,
        "plan": {"path": str(plan_path), "sha256": "a" * 64},
        "endpoint_binding": {
            "capacity_profile": soak.STOCK_CAPACITY_PROFILE,
            "capacity_receipt_sha256": "c" * 64,
            "deployment_id": "fresh-endpoint",
            "endpoint_jobs_sha256": "d" * 64,
        },
    }
    expected["certificate_sha256"] = soak._sha256(soak._canonical(expected))
    monkeypatch.setattr(soak, "_build_receipt", lambda **_kwargs: copy.deepcopy(expected))
    receipt = run_root / "receipt.json"

    candidates = []
    missing = copy.deepcopy(expected)
    missing.pop("endpoint_binding")
    candidates.append(missing)
    extra = copy.deepcopy(expected)
    extra["unexpected"] = True
    candidates.append(extra)
    tampered = copy.deepcopy(expected)
    tampered["endpoint_binding"]["endpoint_jobs_sha256"] = "e" * 64
    candidates.append(tampered)
    unknown = copy.deepcopy(expected)
    unknown["schema_version"] = soak.DYNAMIC_SCHEMA_VERSION + 1
    candidates.append(unknown)

    for candidate in candidates:
        unsigned = dict(candidate)
        unsigned.pop("certificate_sha256", None)
        candidate["certificate_sha256"] = soak._sha256(soak._canonical(unsigned))
        body = soak._canonical(candidate)
        receipt.write_bytes(body)
        receipt.chmod(0o600)
        with pytest.raises(soak.TaskImageSoakError, match="receipt_invalid"):
            soak.validate_task_image_soak_receipt(receipt, soak._sha256(body))


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
            "verifier_execution": "background-program",
            "shared_verifier_taskset_retries": 0,
            "maximum_shared_verifier_attempts": 1,
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
    assert 'KIMI_TASK_IMAGE_SOAK_STATUS_FILE="$run_dir/control/task-image-soak-status.json"' in launcher
    assert 'blocked "$child_code"' in launcher
    assert '2>"$KIMI_TASK_IMAGE_SOAK_STATUS_FILE"' not in launcher
    assert "mini-swe" not in launcher.lower()
    assert "curl" not in launcher
    assert "\nsbatch " not in launcher


def test_launcher_termination_grace_is_accepted_by_provider_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = Path(soak.__file__).with_name("run_kimi_stock_small_task_image_soak.sbatch").read_text()
    match = re.search(r"SANDOQ_PROVIDER_TERMINATION_GRACE_SECONDS=([0-9]+)", launcher)
    assert match is not None
    monkeypatch.setenv("SANDOQ_PROVIDER_TERMINATION_GRACE_SECONDS", match.group(1))

    assert provider_context._supervisor_termination_grace_seconds() == 600


def test_terminal_status_is_aggregate_only_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "run"
    control = output / "control"
    control.mkdir(parents=True)
    control.chmod(0o700)
    status = control / soak.STATUS_FILE_NAME
    monkeypatch.setenv("PRIME_RL_OUTPUT_DIR", str(output))
    monkeypatch.setenv(soak.STATUS_FILE_ENV, str(status))

    soak._publish_terminal_status(code="provider_environment_invalid", state="blocked")

    assert status.stat().st_mode & 0o777 == 0o600
    assert json.loads(status.read_bytes()) == {
        "schema_version": 1,
        "kind": soak.RECEIPT_KIND,
        "state": "blocked",
        "code": "provider_environment_invalid",
    }


def test_main_marks_returned_unavailable_result_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "run"
    control = output / "control"
    control.mkdir(parents=True)
    control.chmod(0o700)
    status = control / soak.STATUS_FILE_NAME
    monkeypatch.setenv("PRIME_RL_OUTPUT_DIR", str(output))
    monkeypatch.setenv(soak.STATUS_FILE_ENV, str(status))
    monkeypatch.setattr(soak, "run", lambda *args, **kwargs: {"state": "unavailable"})

    result = soak.main(
        [
            "run",
            "--plan",
            str(tmp_path / "plan.json"),
            "--plan-sha256",
            "a" * 64,
            "--output",
            str(output),
            "--worker-manifest",
            str(tmp_path / "workers.json"),
            "--worker-manifest-sha256",
            "b" * 64,
            "--walltime-receipt",
            str(tmp_path / "walltime.json"),
            "--walltime-receipt-sha256",
            "c" * 64,
        ]
    )

    assert result == 2
    assert json.loads(status.read_bytes()) == {
        "schema_version": 1,
        "kind": soak.RECEIPT_KIND,
        "state": "blocked",
        "code": "run_unavailable",
    }
