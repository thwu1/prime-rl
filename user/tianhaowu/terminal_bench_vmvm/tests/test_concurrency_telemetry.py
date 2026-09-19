from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest
from trace_concurrency import TraceConcurrencyError, measure_peak_active_rollouts
from vmvm_tb_v2._vacli.concurrency_telemetry import (
    ConcurrencyTelemetry,
    ConcurrencyTelemetryError,
    LeaseStartConcurrencyLimiter,
    load_concurrency_telemetry,
    load_concurrency_telemetry_artifact,
)


def _timed_trace(start: float, end: float) -> dict:
    return {
        "timing": {
            "setup": {"start": start},
            "scoring": {"end": end},
        }
    }


def _complete_capacity_observation(path: Path) -> ConcurrencyTelemetry:
    telemetry = ConcurrencyTelemetry(
        path,
        eval_run_identity_sha256="a" * 64,
        eval_run_role="smoke",
        slurm_job_id="123",
        register_atexit=False,
    )
    for _ in range(8):
        telemetry.vmvm_runtime_started()
    for _ in range(2):
        for _ in range(4):
            telemetry.lease_start_entered()
        for _ in range(4):
            telemetry.lease_tunnel_became_ready()
            telemetry.lease_start_finished()
            telemetry.vmvm_runtime_became_ready()
    for _ in range(8):
        telemetry.vmvm_runtime_stopped()
    return telemetry


def test_publishes_write_once_aggregate_concurrency_evidence(tmp_path: Path) -> None:
    path = tmp_path / "concurrency_telemetry.json"
    telemetry = _complete_capacity_observation(path)

    telemetry.publish()
    value = load_concurrency_telemetry(
        path,
        eval_run_identity_sha256="a" * 64,
        eval_run_role="smoke",
        slurm_job_id="123",
    )

    assert path.stat().st_mode & 0o777 == 0o400
    assert value["observations"]["peak_active_vmvm_runtimes"] == 8
    assert value["observations"]["peak_concurrent_lease_startups"] == 4
    assert "task" not in value["observations"]

    loaded, artifact = load_concurrency_telemetry_artifact(
        path,
        eval_run_identity_sha256="a" * 64,
        eval_run_role="smoke",
        slurm_job_id="123",
    )
    assert loaded == value
    assert artifact == {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }

    replacement = _complete_capacity_observation(path)
    with pytest.raises(
        ConcurrencyTelemetryError,
        match="^concurrency_telemetry_already_exists$",
    ):
        replacement.publish()


def test_rejects_incomplete_or_wrongly_bound_evidence(tmp_path: Path) -> None:
    incomplete_path = tmp_path / "incomplete" / "concurrency_telemetry.json"
    incomplete_path.parent.mkdir()
    incomplete = ConcurrencyTelemetry(
        incomplete_path,
        eval_run_identity_sha256="a" * 64,
        eval_run_role="smoke",
        slurm_job_id="123",
        register_atexit=False,
    )
    incomplete.vmvm_runtime_started()
    incomplete.lease_start_entered()
    incomplete.publish()

    with pytest.raises(
        ConcurrencyTelemetryError,
        match="^concurrency_telemetry_invalid$",
    ):
        load_concurrency_telemetry(
            incomplete_path,
            eval_run_identity_sha256="a" * 64,
            eval_run_role="smoke",
            slurm_job_id="123",
        )

    complete_path = tmp_path / "complete" / "concurrency_telemetry.json"
    complete_path.parent.mkdir()
    complete = _complete_capacity_observation(complete_path)
    complete.publish()
    with pytest.raises(
        ConcurrencyTelemetryError,
        match="^concurrency_telemetry_invalid$",
    ):
        load_concurrency_telemetry(
            complete_path,
            eval_run_identity_sha256="b" * 64,
            eval_run_role="smoke",
            slurm_job_id="123",
        )


def test_measures_trace_lifecycle_overlap_without_counting_touching_intervals() -> None:
    assert measure_peak_active_rollouts(
        [
            _timed_trace(1.0, 3.0),
            _timed_trace(2.0, 4.0),
            _timed_trace(4.0, 5.0),
        ]
    ) == {
        "observed_rollouts": 3,
        "peak_active_rollouts_lower_bound": 2,
    }

    with pytest.raises(TraceConcurrencyError, match="^trace_concurrency_timing_invalid$"):
        measure_peak_active_rollouts([_timed_trace(2.0, 1.0)])


def test_lease_limiter_serializes_permit_and_telemetry_transitions() -> None:
    first_entered = threading.Event()
    release_first_transition = threading.Event()
    second_started = threading.Event()
    second_acquired = threading.Event()

    class BlockingTelemetry:
        def __init__(self) -> None:
            self.active = 0
            self.peak = 0
            self.enters = 0

        def lease_start_entered(self) -> None:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.enters += 1
            if self.enters == 1:
                first_entered.set()
                assert release_first_transition.wait(timeout=2)

        def lease_start_finished(self) -> None:
            self.active -= 1

    telemetry = BlockingTelemetry()
    limiter = LeaseStartConcurrencyLimiter(2, telemetry)

    first = threading.Thread(target=limiter.acquire)

    def acquire_second() -> None:
        second_started.set()
        limiter.acquire()
        second_acquired.set()

    second = threading.Thread(target=acquire_second)
    first.start()
    assert first_entered.wait(timeout=2)
    second.start()
    assert second_started.wait(timeout=2)
    assert not second_acquired.wait(timeout=0.05)
    release_first_transition.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert telemetry.peak == 2
    limiter.release()
    limiter.release()
    assert telemetry.active == 0
