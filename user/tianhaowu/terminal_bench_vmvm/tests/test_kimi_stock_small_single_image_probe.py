from __future__ import annotations

import asyncio
import json
from pathlib import Path

import kimi_stock_small_single_image_probe as probe
import pytest


def _event(name: str, **values: object) -> dict[str, object]:
    return {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": name,
        "timestamp": 1.0,
        "slurm_job_id": "1",
        "wandb_run_id": None,
        **values,
    }


def _acquired(assignment: str, image: str, active: int) -> dict[str, object]:
    return _event(
        "assignment_acquired",
        assignment_id=assignment,
        outer_session_id=f"outer-{assignment}",
        slot_id=active - 1,
        generation=1,
        reuse_count=1,
        reuse_threshold=1,
        requested_image=image,
        exec_url="https://example.invalid/",
        port_urls={},
        pool_wait_seconds=0.0,
        outer_age_seconds=0.0,
        active_assignment_count=active,
        ticket_id=f"ticket-{assignment}",
        status="assigned",
    )


def _ready(assignment: str, image: str) -> dict[str, object]:
    return _event(
        "assignment_ready",
        assignment_id=assignment,
        slot_id=0,
        requested_image=image,
        bootstrap_seconds=1.0,
    )


def _released(assignment: str, *, failed: bool) -> dict[str, object]:
    value = _event(
        "assignment_released",
        assignment_id=assignment,
        outer_session_id=f"outer-{assignment}",
        slot_id=0,
        generation=1,
        reuse_count=1,
        reuse_threshold=1,
        status="poisoned" if failed else "retired",
        reason="initialization_failure" if failed else "rollout_complete",
        retirement_reason="initialization_failure" if failed else "reuse_limit_reached",
        duration=1.0,
        nested_recycle_verified=not failed,
        outer_retired=not failed,
        outer_deletion_verified_http_status=404,
        poisoned=failed,
        shell_deleted=not failed,
        shell_id=None if failed else "shell",
        shell_generation=0,
        managed_shell_recovery_count=0,
        shell_failure_status="http_500" if failed else None,
        cleanup_gateway_retry_count=0,
        cleanup_gateway_retry_exhausted_count=0,
        timings={},
    )
    if failed:
        value["error"] = "discarded raw provider detail"
    return value


def _body(rows: list[dict[str, object]]) -> bytes:
    return b"".join(probe._canonical(row) for row in rows)


def _source_events() -> bytes:
    target = "registry.invalid/private/opaque@sha256:" + "a" * 64
    rows: list[dict[str, object]] = []
    for index in range(probe.SOURCE_READY):
        assignment = f"clean-{index}"
        image = f"registry.invalid/private/clean-{index}@sha256:" + "b" * 64
        rows.extend((_acquired(assignment, image, (index % 64) + 1), _ready(assignment, image)))
        rows.append(_released(assignment, failed=False))
    for index in range(probe.SOURCE_FAILED_RELEASES):
        assignment = f"failed-{index}"
        rows.append(_acquired(assignment, target, 1))
        rows.append(_released(assignment, failed=True))
    return _body(rows)


def test_source_event_derivation_is_unique_and_aggregate_only() -> None:
    target = probe._analyze_source_events(_source_events())

    assert target.summary == {
        "source_assignments": 392,
        "source_ready": 383,
        "source_clean_releases": 383,
        "source_initialization_failures": 9,
        "source_failed_assignments": 9,
        "source_failed_targets": 1,
        "source_failed_target_ready": 0,
        "source_assignment_high_water": 64,
        "target_disclosed": False,
    }
    serialized = json.dumps(target.summary, sort_keys=True)
    assert target.image not in serialized
    assert "discarded raw provider detail" not in serialized


def test_source_event_derivation_rejects_more_than_one_failed_target() -> None:
    rows = [json.loads(line) for line in _source_events().splitlines()]
    failed_ids = {
        row["assignment_id"]
        for row in rows
        if row.get("event") == "assignment_released" and "error" in row
    }
    changed = False
    for row in rows:
        if row.get("event") == "assignment_acquired" and row.get("assignment_id") in failed_ids:
            if changed:
                row["requested_image"] = "registry.invalid/private/other@sha256:" + "c" * 64
                break
            changed = True

    with pytest.raises(probe.SingleImageProbeError, match="source_failure_shape_invalid"):
        probe._analyze_source_events(_body(rows))


class _Runtime:
    def __init__(self, *, fail_start: bool, fail_stop: bool = False) -> None:
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.stop_calls = 0

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("discarded provider detail")

    async def stop(self) -> None:
        self.stop_calls += 1
        if self.fail_stop:
            raise RuntimeError("discarded cleanup detail")


def test_execute_probe_classifies_transient_success_and_cleans_each_attempt() -> None:
    runtimes = [_Runtime(fail_start=True), _Runtime(fail_start=False)]

    value = asyncio.run(probe.execute_probe(object(), runtime_factory=lambda _task: runtimes.pop(0)))

    assert value["classification"] == "transient_success"
    assert value["counts"] == {
        "attempts": 2,
        "ready": 1,
        "initialization_failures": 1,
        "runtime_factory_failures": 0,
        "cleanup_attempts": 2,
        "cleanup_succeeded": 2,
        "cleanup_failures": 0,
    }
    assert "discarded" not in json.dumps(value)


def test_execute_probe_classifies_three_failures_as_repeatable() -> None:
    runtimes: list[_Runtime] = []

    def factory(_task: object) -> _Runtime:
        runtime = _Runtime(fail_start=True)
        runtimes.append(runtime)
        return runtime

    value = asyncio.run(probe.execute_probe(object(), runtime_factory=factory))

    assert value["classification"] == "repeatable_failure"
    assert value["counts"]["attempts"] == 3
    assert value["counts"]["ready"] == 0
    assert value["counts"]["initialization_failures"] == 3
    assert all(runtime.stop_calls == 1 for runtime in runtimes)


def test_execute_probe_cleanup_failure_is_inconclusive() -> None:
    value = asyncio.run(
        probe.execute_probe(
            object(),
            runtime_factory=lambda _task: _Runtime(fail_start=False, fail_stop=True),
        )
    )

    assert value["classification"] == "inconclusive"
    assert value["counts"]["ready"] == 1
    assert value["counts"]["cleanup_failures"] == 1


def test_probe_event_audit_matches_transient_outcome_without_retaining_target() -> None:
    target = "registry.invalid/private/opaque@sha256:" + "d" * 64
    failed = "failed"
    ready = "ready"
    rows = [
        _acquired(failed, target, 1),
        _released(failed, failed=True),
        _acquired(ready, target, 1),
        _ready(ready, target),
        _released(ready, failed=False),
    ]
    outcome = {
        "counts": {"attempts": 2, "ready": 1, "initialization_failures": 1}
    }

    value = probe._analyze_probe_events(_body(rows), target, outcome)

    assert value == {
        "assignments": 2,
        "ready": 1,
        "initialization_failures": 1,
        "assignment_high_water": 1,
    }
    assert target not in json.dumps(value)


def test_contract_and_launcher_are_c1_provisioning_only() -> None:
    contract = probe._contracts()
    launcher = Path(probe.__file__).with_name(
        "run_kimi_stock_small_single_image_probe.sbatch"
    ).read_text()

    assert contract["concurrency"] == 1
    assert contract["probe_attempts"] == 3
    assert contract["execution"] == {
        "provisioning_and_readiness_only": True,
        "taskset_setup": False,
        "commands": 0,
        "verifier_invocations": 0,
        "model_calls": 0,
        "harness_invocations": 0,
    }
    assert contract["privacy"]["target_identity_retained"] is False
    assert "--concurrency 1" in launcher
    assert "--lease-create-cap 1" in launcher
    assert "python3 \"$tool\" run" in launcher
    assert "python3 \"$tool\" certify" in launcher
    assert "mini-swe" not in launcher.lower()
    assert "curl" not in launcher
    assert "\nsbatch " not in launcher


def test_pull_image_rejects_non_dockerhub_source() -> None:
    source = "docker.io/example/opaque@sha256:" + "e" * 64

    assert probe._pull_image(source).startswith(
        f"{probe.ECR_REGISTRY}/{probe.ECR_PULL_THROUGH_PREFIX}/"
    )
    with pytest.raises(probe.SingleImageProbeError, match="source_selection_invalid"):
        probe._pull_image("other.invalid/example/opaque@sha256:" + "f" * 64)
