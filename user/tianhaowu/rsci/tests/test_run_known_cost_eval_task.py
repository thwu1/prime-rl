from __future__ import annotations

import signal
from pathlib import Path

import pytest
import run_known_cost_eval_task as runner
import tomli_w


def _write(path: Path, content: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return runner.file_identity(path)


def _task_contract(tmp_path: Path) -> tuple[runner.PlanContext, dict[str, object]]:
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "config.json").write_text("{}\n", encoding="utf-8")
    (model_path / "model.safetensors").write_bytes(b"weights")
    checkpoint = runner.directory_identity(model_path.resolve(), require_stable=False)
    evaluator_path = tmp_path / "source" / "user" / "tianhaowu" / "rsci" / "figure3_eval.py"
    evaluator_identity = _write(evaluator_path, b"#!/usr/bin/env python3\n")
    inference_path = tmp_path / "plan" / "configs" / "task-a" / "inference.toml"
    inference = {
        "server": {"host": "0.0.0.0", "port": 20_007},
        "model": {"name": str(model_path.resolve())},
        "deployment": {"type": "single_node", "gpus_per_node": 1},
    }
    inference_identity = _write(inference_path, tomli_w.dumps(inference).encode())
    shards = []
    for index, shard_id in enumerate(("untagged", "tag_0", "tag_1", "tag_2", "tag_3", "tag_4", "tag_5")):
        output_dir = tmp_path / "plan" / "results" / "task-a" / shard_id
        eval_path = tmp_path / "plan" / "configs" / "task-a" / shard_id / "eval.toml"
        evaluation = {
            "infer_config": str(inference_path.resolve()),
            "evaluator": str(evaluator_path.resolve()),
            "eval": {
                "model": str(model_path.resolve()),
                "output_dir": str(output_dir.resolve()),
                "api_base_url": "http://127.0.0.1:20007/v1",
            },
        }
        shards.append(
            {
                "shard_id": shard_id,
                "output_dir": str(output_dir.resolve()),
                "eval_config": _write(eval_path, tomli_w.dumps(evaluation).encode()),
                "neutral_tag_index": None if index == 0 else index - 1,
            }
        )
    task = {
        "task_id": "task-a",
        "model_key": "model-a",
        "model_path": str(model_path.resolve()),
        "transport_port": 20_007,
        "result_root": str((tmp_path / "plan" / "results" / "task-a").resolve()),
        "receipt_dir": str((tmp_path / "plan" / "receipts" / "task-a").resolve()),
        "config_bundle_sha256": "a" * 64,
        "checkpoint_inventory_sha256": checkpoint["inventory_sha256"],
        "inference_config": inference_identity,
        "shards": shards,
    }
    plan_path = (tmp_path / "plan" / "plan.json").resolve()
    plan = {
        "plan_id": "b" * 64,
        "plan_root": str((tmp_path / "plan").resolve()),
        "eval_root": str(tmp_path.resolve()),
        "implementations": {
            "evaluator": {
                "repository_path": "user/tianhaowu/rsci/figure3_eval.py",
                **evaluator_identity,
            }
        },
        "models": [
            {
                "model_key": "model-a",
                "checkpoint": checkpoint,
                "occurrences": [{"step": 0}],
            }
        ],
        "tasks": [task],
    }
    context = runner.PlanContext(plan, plan_path, "c" * 64, tmp_path / "source", {})
    return context, task


def test_task_contract_requires_exact_checkpoint_and_all_seven_configs(tmp_path: Path) -> None:
    context, task = _task_contract(tmp_path)

    runner.validate_task_contract(context, task)

    Path(task["shards"][3]["eval_config"]["path"]).write_text("changed = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="shard config bytes changed"):
        runner.validate_task_contract(context, task)


def test_planner_allowlist_requires_exact_repository_and_implementation_pair() -> None:
    historical = {"repository_path": str(runner.PLANNER_REPOSITORY_PATH)}
    promoted = {"repository_path": str(runner.PROMOTED_PLANNER_REPOSITORY_PATH)}

    assert (
        runner._planner_repository_path(
            {"implementation_id": runner.PLANNER_IMPLEMENTATION_IDS[runner.PLANNER_REPOSITORY_PATH]},
            historical,
        )
        == runner.PLANNER_REPOSITORY_PATH
    )
    assert (
        runner._planner_repository_path(
            {"implementation_id": runner.PLANNER_IMPLEMENTATION_IDS[runner.PROMOTED_PLANNER_REPOSITORY_PATH]},
            promoted,
        )
        == runner.PROMOTED_PLANNER_REPOSITORY_PATH
    )
    with pytest.raises(ValueError, match="implementation ID differs"):
        runner._planner_repository_path(
            {"implementation_id": runner.PLANNER_IMPLEMENTATION_IDS[runner.PLANNER_REPOSITORY_PATH]},
            promoted,
        )
    with pytest.raises(ValueError, match="unauthorized planner"):
        runner._planner_repository_path(
            {"implementation_id": "rsci-known-cost-promoted-checkpoint-eval-plan-v1"},
            {"repository_path": "user/tianhaowu/rsci/unpinned_planner.py"},
        )


def test_promoted_planner_must_match_postrun_snapshot_and_exact_bytes(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    planner_path = source_root / runner.PROMOTED_PLANNER_REPOSITORY_PATH
    planner_identity = _write(planner_path, b"# pinned promoted planner\n")
    postrun_path = tmp_path / "run" / "postrun_authority.json"
    postrun = {
        "postrun_control_source": {
            "snapshot_path": str(source_root.resolve()),
            "implementations": {"promoted_eval_authority": planner_identity},
        }
    }
    postrun_path.parent.mkdir(parents=True)
    postrun_path.write_bytes(runner.canonical_json_bytes(postrun))
    postrun_path.chmod(0o444)
    promoted_path = tmp_path / "run" / "promoted_eval_authority.json"
    promoted = {"authority_chain": {"postrun_authority": runner.file_identity(postrun_path)}}
    promoted_path.write_bytes(runner.canonical_json_bytes(promoted))
    promoted_path.chmod(0o444)
    planner = {
        "repository_path": str(runner.PROMOTED_PLANNER_REPOSITORY_PATH),
        **planner_identity,
    }
    plan = {
        "implementation_id": runner.PLANNER_IMPLEMENTATION_IDS[runner.PROMOTED_PLANNER_REPOSITORY_PATH],
        "request": {"promoted_eval_authority": runner.file_identity(promoted_path)},
    }

    runner._validate_planner_source_authority(
        plan,
        planner,
        runner.PROMOTED_PLANNER_REPOSITORY_PATH,
        source_root.resolve(),
    )

    changed = {**planner, "sha256": "f" * 64}
    with pytest.raises(ValueError, match="authority-pinned implementation"):
        runner._validate_planner_source_authority(
            plan,
            changed,
            runner.PROMOTED_PLANNER_REPOSITORY_PATH,
            source_root.resolve(),
        )


def test_attempt_predecessor_is_contiguous_and_stops_after_success(tmp_path: Path) -> None:
    task = {"task_id": "task-a", "receipt_dir": str(tmp_path / "receipts" / "task-a")}
    receipt_path, predecessor = runner.attempt_predecessor(task, 1)
    assert receipt_path.name == "attempt_0001.json"
    assert predecessor is None

    receipt_path.parent.mkdir(parents=True)
    first = {"status": "failed", "failure": "node loss"}
    first_bytes = runner.canonical_json_bytes(first)
    receipt_path.write_bytes(first_bytes)
    receipt_path.chmod(0o444)
    second_path, predecessor = runner.attempt_predecessor(task, 2)
    assert second_path.name == "attempt_0002.json"
    assert predecessor == runner.bytes_sha256(first_bytes)

    second_path.write_bytes(runner.canonical_json_bytes({"status": "succeeded"}))
    second_path.chmod(0o444)
    with pytest.raises(ValueError, match="already succeeded"):
        runner.attempt_predecessor(task, 3)


def test_terminal_receipt_matches_plan_contract_for_failure_and_success(tmp_path: Path) -> None:
    plan_context, task = _task_contract(tmp_path)
    context = runner.AttemptContext(
        plan_context=plan_context,
        task=task,
        attempt=2,
        receipt_path=Path(task["receipt_dir"]) / "attempt_0002.json",
        predecessor_receipt_sha256="d" * 64,
        scheduler={"job_id": "123", "array_task_id": None},
        dispatch_intent={"path": "/intent", "size_bytes": 1, "sha256": "e" * 64},
    )

    failed = runner.build_terminal_receipt(
        context,
        status="failed",
        started_at="2026-08-08T00:00:00Z",
        finished_at="2026-08-08T00:01:00Z",
        exit_code=1,
        failure="evaluator failed",
    )
    assert failed["predecessor_receipt_sha256"] == "d" * 64
    assert failed["failure"] == "evaluator failed"
    assert failed["scheduler"]["job_id"] == "123"

    succeeded = runner.build_terminal_receipt(
        context,
        status="succeeded",
        started_at="2026-08-08T00:00:00Z",
        finished_at="2026-08-08T00:01:00Z",
        exit_code=0,
        shards=[{"shard_id": "untagged"}],
    )
    assert succeeded["status"] == "succeeded"
    assert succeeded["shards"] == [{"shard_id": "untagged"}]
    with pytest.raises(ValueError, match="requires exit_code=0"):
        runner.build_terminal_receipt(
            context,
            status="succeeded",
            started_at="2026-08-08T00:00:00Z",
            finished_at="2026-08-08T00:01:00Z",
            exit_code=1,
            shards=[],
        )


def test_signal_classification_distinguishes_preemption_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_scheduler_signal_state", lambda _job_id: None)
    assert runner.termination_status(runner.TerminationRequested(signal.SIGUSR1), "123") == "preempted"
    assert runner.termination_status(runner.TerminationRequested(signal.SIGTERM), "123") == "cancelled"
    monkeypatch.setattr(runner, "_scheduler_signal_state", lambda _job_id: "PREEMPTED")
    assert runner.termination_status(runner.TerminationRequested(signal.SIGTERM), "123") == "preempted"
