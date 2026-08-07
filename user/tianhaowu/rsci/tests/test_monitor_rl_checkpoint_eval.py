import json
from pathlib import Path

from checkpoint_eval_artifacts import (
    EXPECTED_OPERATIONS,
    EXPECTED_PROMPTS,
    EXPECTED_STEPS,
    inspect_metrics,
    load_job_ledger,
    metrics_path,
    metrics_validation_error,
    quarantine_invalid_metrics,
    validate_checkpoint_eval,
    write_job_ledger,
)
from monitor_rl_checkpoint_eval import (
    classify_batch,
    expand_task_spec,
    reconcile_scheduler,
)


def _valid_metrics() -> dict[str, object]:
    per_op = {
        str(operation): {
            "empirical": {"pass@1": 0.25},
            "unbiased": {"pass@1": 0.25},
        }
        for operation in EXPECTED_OPERATIONS
    }
    return {
        "model": "/models/immutable-snapshot",
        "operations": EXPECTED_OPERATIONS,
        "num_prompts": EXPECTED_PROMPTS,
        "samples_per_prompt": 1,
        "num_generations": EXPECTED_PROMPTS,
        "strict_graph": {"per_op": per_op},
    }


def test_metrics_validation_requires_complete_op11_through_op45_payload() -> None:
    metrics = _valid_metrics()
    assert metrics_validation_error(metrics) is None

    metrics["num_generations"] = EXPECTED_PROMPTS - 1
    assert metrics_validation_error(metrics) == "num_generations=6999, expected 7000"


def test_structural_metrics_without_frozen_provenance_are_invalid(tmp_path: Path) -> None:
    path = metrics_path(tmp_path, 0)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_valid_metrics()) + "\n", encoding="utf-8")

    error, _ = validate_checkpoint_eval(tmp_path, 0)

    assert error is not None
    assert "Missing scheduled frozen checkpoint step 0 artifacts" in error


def test_invalid_completion_marker_is_incomplete_and_quarantined(tmp_path: Path) -> None:
    path = metrics_path(tmp_path, 25)
    path.parent.mkdir(parents=True)
    path.write_text("not JSON\n", encoding="utf-8")

    completed, _, invalid, _ = inspect_metrics(tmp_path)
    assert 25 not in completed
    assert "25" in invalid

    quarantine_path = quarantine_invalid_metrics(tmp_path, 25, "job123.task0")
    assert not path.exists()
    assert quarantine_path.read_text(encoding="utf-8") == "not JSON\n"

    path.write_text("not JSON\n", encoding="utf-8")
    assert quarantine_invalid_metrics(tmp_path, 25, "job123.task0") == quarantine_path
    assert not path.exists()


def test_job_ledger_persists_exact_task_to_step_mapping(tmp_path: Path) -> None:
    manifest = tmp_path / "steps.txt"
    manifest.write_text("0\n50\n125\n", encoding="utf-8")

    write_job_ledger(tmp_path, "12345", manifest, "afterok:12000", 8)
    ledger = load_job_ledger(tmp_path, "12345")

    assert ledger is not None
    assert ledger["task_to_step"] == {"0": 0, "1": 50, "2": 125}
    assert ledger["dependency"] == "afterok:12000"


def test_expand_task_spec_handles_throttle_ranges_and_strides() -> None:
    assert expand_task_spec("0-20%8") == list(range(21))
    assert expand_task_spec("0-6:2,9") == [0, 2, 4, 6, 9]


def test_batch_terminates_only_when_complete_or_all_producers_stop() -> None:
    common = {
        "scheduler_seen": True,
        "discovery_grace_expired": True,
    }
    assert (
        classify_batch(
            len(EXPECTED_STEPS),
            producer_active=False,
            all_producers_stopped=True,
            **common,
        )
        == "complete"
    )
    assert classify_batch(20, producer_active=True, all_producers_stopped=False, **common) == "running"
    assert classify_batch(20, producer_active=False, all_producers_stopped=True, **common) == "stopped-incomplete"
    assert (
        classify_batch(
            0,
            producer_active=False,
            all_producers_stopped=False,
            scheduler_seen=False,
            discovery_grace_expired=False,
        )
        == "waiting-for-scheduler"
    )


def test_scheduler_reconciliation_requires_every_expected_task_to_be_terminal() -> None:
    first = {
        "tasks": {
            "0": {"state": "COMPLETED", "source": "sacct"},
            "1": {"state": "RUNNING", "source": "squeue"},
        }
    }
    scheduler, expected, known = reconcile_scheduler(first, set(), {})
    assert scheduler["all_producers_terminal"] is False

    second = {"tasks": {"1": {"state": "FAILED", "source": "sacct"}}}
    scheduler, _, _ = reconcile_scheduler(second, expected, known)
    assert scheduler["all_producers_terminal"] is True
    assert scheduler["expected_task_ids"] == ["0", "1"]

    dependency_failure = {
        "tasks": {
            "0": {"state": "PENDING", "source": "squeue", "reason": "DependencyNeverSatisfied"},
            "1": {"state": "PENDING", "source": "squeue", "reason": "DependencyNeverSatisfied"},
        }
    }
    scheduler, _, _ = reconcile_scheduler(dependency_failure, expected, {})
    assert scheduler["all_producers_terminal"] is False
    assert scheduler["all_producers_stopped"] is True
