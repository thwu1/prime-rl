from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import analyze_known_cost_boundary_results as results
import numpy as np
import pytest
from analyze_known_cost_boundary_results import TaskOutcomes


def _task_outcomes(tagged_value: float, untagged_value: float) -> TaskOutcomes:
    return TaskOutcomes(
        tagged_keys=((21, "source-a", "raw-a", 101),),
        tagged={metric: np.full((1, 6), tagged_value, dtype=np.float64) for metric in results.OUTCOMES},
        untagged_keys=((21, 0, "prompt-a"),),
        untagged={metric: np.asarray([untagged_value], dtype=np.float64) for metric in results.OUTCOMES},
    )


def _gate_row(dose: float, clock_type: str, target: int, value: float) -> dict[str, object]:
    return {
        "block_seed": results.SMOKE_BLOCK_SEED,
        "dose": dose,
        "clock_kind": clock_type,
        "target": target,
        "paired_localization_D_T_minus_G": {
            "A_answer_correct_strict_wrong": {
                "all_op11_45": value,
                "per_op": {},
                "bands": {"op21_40": value},
            }
        },
    }


def test_selected_unselected_localization_and_paired_t_minus_g_are_source_paired() -> None:
    group = np.asarray(
        [
            [0, 0, 0, 0, 0, 0],
            [1, 0, 1, 0, 1, 1],
        ],
        dtype=np.float64,
    )
    tag = np.asarray(
        [
            [1, 1, 0, 0, 0, 0],
            [1, 1, 1, 0, 1, 0],
        ],
        dtype=np.float64,
    )

    np.testing.assert_allclose(results.localization_by_source(group, (0, 1)), [0.0, -0.25])
    np.testing.assert_allclose(results.localization_by_source(tag, (0, 1)), [1.0, 0.5])
    np.testing.assert_allclose(results.paired_localization_difference(tag, group, (0, 1)), [1.0, 0.75])

    with pytest.raises(ValueError, match="different shapes"):
        results.paired_localization_difference(tag, group[:1], (0, 1))


def test_raw_clock_interpolation_is_sourcewise_and_uses_recorded_weight() -> None:
    lower = _task_outcomes(0.0, 0.25)
    upper = _task_outcomes(1.0, 0.75)

    interpolated = results.interpolate_task_outcomes(lower, upper, 0.4)

    for metric in results.OUTCOMES:
        np.testing.assert_allclose(interpolated.tagged[metric], np.full((1, 6), 0.4))
        np.testing.assert_allclose(interpolated.untagged[metric], [0.45])
    assert interpolated.tagged_keys == lower.tagged_keys
    assert interpolated.untagged_keys == lower.untagged_keys

    mismatched = TaskOutcomes(
        tagged_keys=((21, "different", "raw", 101),),
        tagged=upper.tagged,
        untagged_keys=upper.untagged_keys,
        untagged=upper.untagged,
    )
    with pytest.raises(ValueError, match="source identities"):
        results.interpolate_task_outcomes(lower, mismatched, 0.4)


def test_all_planned_tasks_must_have_terminal_success() -> None:
    validation = {
        "plan": {"tasks": [{"task_id": "task-a"}, {"task_id": "task-b"}]},
        "receipts": {"receipt_count": 3, "task_statuses": {"task-a": "succeeded", "task-b": "succeeded"}},
    }

    assert results.require_all_tasks_succeeded(validation) == {
        "task-a": "succeeded",
        "task-b": "succeeded",
    }

    missing = copy.deepcopy(validation)
    missing["receipts"]["task_statuses"].pop("task-b")
    with pytest.raises(ValueError, match="receipt coverage"):
        results.require_all_tasks_succeeded(missing)

    failed = copy.deepcopy(validation)
    failed["receipts"]["task_statuses"]["task-b"] = "failed"
    with pytest.raises(ValueError, match="not all succeeded"):
        results.require_all_tasks_succeeded(failed)


def test_result_analyzer_requires_adjacent_matching_postrun_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "runs"
    intent_identity = {"path": "/intent", "size_bytes": 10, "sha256": "a" * 64}
    decision = {
        "eligible_design": "full_30_arm_grid",
        "eligible_arm_count": 30,
        "eligible_arm_filenames": [f"arm-{index}" for index in range(30)],
    }
    intent = {
        "inputs": {"run_root": str(run_root.resolve())},
        "preregistered_decision": decision,
    }
    authority_identity = {"path": "/authority", "size_bytes": 20, "sha256": "b" * 64}
    artifact = {
        "initial_launch_authority": {
            "intent": intent_identity,
            **decision,
        }
    }
    observed = []

    def validate(path: Path) -> dict[str, object]:
        observed.append(path)
        return {"authority": artifact, "identity": authority_identity}

    monkeypatch.setattr(results.postrun_authority, "validate_authority", validate)
    monkeypatch.setattr(
        results.postrun_authority,
        "validate_recorded_implementation",
        lambda *args, **kwargs: {"sha256": "c" * 64},
    )

    record = results._load_postrun_authority(intent, intent_identity)

    assert record["identity"] == authority_identity
    assert observed == [run_root.resolve() / results.postrun_authority.AUTHORITY_NAME]

    artifact["initial_launch_authority"]["intent"] = {**intent_identity, "sha256": "d" * 64}
    with pytest.raises(ValueError, match="different initial launch intents"):
        results._load_postrun_authority(intent, intent_identity)


def test_plan_validation_uses_the_recorded_old_planner_path_from_a_new_analyzer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old_rsci = tmp_path / "old-control-plane" / "user" / "tianhaowu" / "rsci"
    old_planner = old_rsci / "materialize_known_cost_eval_plan.py"
    old_launch = old_rsci / "materialize_known_cost_boundary_launch.py"
    old_planner.parent.mkdir(parents=True)
    old_planner.write_text("# frozen old planner\n", encoding="utf-8")
    old_launch.write_text("# frozen old launch materializer\n", encoding="utf-8")
    old_planner.chmod(0o444)
    old_launch.chmod(0o444)
    assert old_planner.resolve() != Path(results.eval_plan.__file__).resolve()
    assert old_launch.resolve() != Path(results.launch.__file__).resolve()

    tokenizer_path = tmp_path / "tokenizer"
    tokenizer_path.write_text("frozen tokenizer\n", encoding="utf-8")
    tokenizer_path.chmod(0o444)
    run_root = tmp_path / "launch"
    intent_path = run_root / results.launch.INTENT_NAME
    intent = {
        "schema_version": results.launch.SCHEMA_VERSION,
        "artifact_type": results.launch.ARTIFACT_TYPE,
        "study_id": results.launch.STUDY_ID,
        "inputs": {
            "run_root": str(run_root.resolve()),
            "tokenizer_path": str(tokenizer_path.resolve()),
        },
        "implementation": results.eval_plan.file_identity(old_launch),
        "preregistered_decision": {
            "eligible_design": "four_arm_smoke_screen",
            "eligible_arm_count": 1,
            "eligible_arm_filenames": ["arm-a.toml"],
        },
        "eligible_runs": [{"arm_filename": "arm-a.toml"}],
    }
    intent["payload_without_self_hash_sha256"] = results.eval_plan.canonical_json_sha256(intent)
    results.eval_plan._write_bytes_once(intent_path, results.eval_plan.canonical_json_bytes(intent))
    intent_identity = results.eval_plan.file_identity(intent_path)

    plan_id = "b" * 64
    eval_root = tmp_path / "evals"
    plan_root = eval_root / "plans" / plan_id
    plan_path = plan_root / results.eval_plan.PLAN_NAME
    receipts = {"receipt_count": 1, "task_statuses": {"task-a": "succeeded"}}
    plan = {
        "schema_version": results.eval_plan.SCHEMA_VERSION,
        "artifact_type": results.eval_plan.ARTIFACT_TYPE,
        "study_id": results.eval_plan.STUDY_ID,
        "implementation_id": results.eval_plan.PLAN_IMPLEMENTATION_ID,
        "plan_id": plan_id,
        "eval_root": str(eval_root.resolve()),
        "plan_root": str(plan_root.resolve()),
        "plan_path": str(plan_path.resolve()),
        "implementations": {
            "planner": {
                "repository_path": results.eval_plan.SCRIPT_REPOSITORY_PATH,
                **results.eval_plan.file_identity(old_planner),
            }
        },
        "request": {
            "launch": {
                "submission_intent": intent_identity,
                "tokenizer_path": str(tokenizer_path.resolve()),
            }
        },
        "runs": [{"run_id": "run-a"}],
        "models": [{"model_key": "task-a", "occurrences": [{"run_id": "run-a", "step": 0}]}],
        "tasks": [{"task_id": "task-a"}],
        "shards_per_task": 7,
    }
    results.eval_plan._write_bytes_once(plan_path, results.eval_plan.canonical_json_bytes(plan))
    raw = plan_path.read_bytes()
    expected_summary = {
        "command": "validate",
        "dry_run": False,
        "already_materialized": None,
        "plan_id": plan_id,
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": results.eval_plan.bytes_sha256(raw),
        "run_count": 1,
        "model_count": 1,
        "task_count": 1,
        "shards_per_task": 7,
        "step_zero_occurrences": 1,
        "receipts": receipts,
    }
    expected_intent_summary = {
        "command": "validate",
        "intent": intent_identity,
        "eligible_design": "four_arm_smoke_screen",
        "eligible_arm_count": 1,
        "submission_performed": False,
    }
    observed = []

    def recorded_validator(path, arguments):
        observed.append((path, arguments))
        if path == old_planner.resolve():
            return expected_summary
        if path == old_launch.resolve():
            return expected_intent_summary
        raise AssertionError(f"unexpected recorded validator: {path}")

    monkeypatch.setattr(results.launch, "_run_exact_validator", recorded_validator)
    monkeypatch.setattr(results.eval_plan, "validate_receipt_chain", lambda **kwargs: receipts)
    monkeypatch.setattr(
        results.eval_plan,
        "validate_plan",
        lambda path: (_ for _ in ()).throw(AssertionError("current-path planner must not run")),
    )
    monkeypatch.setattr(
        results.launch,
        "validate_intent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("current-path launch validator must not run")),
    )

    validated = results.validate_plan_with_recorded_planner(plan_path)
    loaded_intent, eligible_runs = results._load_launch_authority(validated["plan"])

    assert observed == [
        (old_planner.resolve(), ["validate", "--plan", str(plan_path.resolve())]),
        (
            old_launch.resolve(),
            [
                "validate",
                "--intent",
                str(intent_path.resolve()),
                "--tokenizer",
                str(tokenizer_path.resolve()),
            ],
        ),
    ]
    assert validated["plan"] == plan
    assert validated["recorded_planner"]["path"] == str(old_planner.resolve())
    assert loaded_intent == intent
    assert eligible_runs == {"arm-a.toml": {"arm_filename": "arm-a.toml"}}


def test_terminal_receipts_use_the_authority_pinned_dispatcher_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher_path = tmp_path / "old-control" / "user" / "tianhaowu" / "rsci" / "dispatch_known_cost_eval.py"
    dispatcher_path.parent.mkdir(parents=True)
    dispatcher_path.write_text("# pinned dispatcher\n", encoding="utf-8")
    dispatcher_path.chmod(0o444)
    dispatcher_identity = results.eval_plan.file_identity(dispatcher_path)

    plan_id = "b" * 64
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(results.eval_plan.canonical_json_bytes({"plan_id": plan_id}))
    plan_path.chmod(0o444)
    plan_identity = results.eval_plan.file_identity(plan_path)

    def sealed(name: str) -> dict[str, object]:
        path = tmp_path / name
        path.write_text(f"sealed {name}\n", encoding="utf-8")
        path.chmod(0o444)
        return results.eval_plan.file_identity(path)

    global_identity = sealed("global.json")
    terminal_identity = sealed("terminal.json")
    task_intent_identity = sealed("task-intent.json")
    batch_identity = sealed("batch.json")
    submission_identity = sealed("submission.json")
    script_identity = sealed("task.sbatch")
    statuses = {"task-a": "succeeded"}
    summary = {
        "command": "validate-terminals",
        "study_id": results.eval_plan.STUDY_ID,
        "plan": plan_identity,
        "state_root": str((tmp_path / plan_id).resolve()),
        "global_dispatch_intent": global_identity,
        "terminal_receipt_count": 1,
        "runner_produced_receipt_count": 1,
        "scheduler_recovered_failure_count": 0,
        "task_statuses": statuses,
        "attempts": [
            {
                "task_id": "task-a",
                "attempt": 1,
                "status": "succeeded",
                "provenance_kind": "pinned_runner",
                "terminal_receipt": terminal_identity,
                "task_dispatch_intent": task_intent_identity,
                "batch_dispatch_intent": batch_identity,
                "global_dispatch_intent": global_identity,
                "submission_receipt": submission_identity,
                "sealed_batch_script": script_identity,
                "job_id": "123",
                "comment": "sealed-comment",
                "job_name": "sealed-job-name",
                "account": "ram",
                "qos": "h100_ram_high",
                "submitted_batch_script_sha256": script_identity["sha256"],
                "terminal_allocation": {
                    "queried_at": "2026-08-08T00:00:00Z",
                    "sacct_command": [
                        "sacct",
                        "--noheader",
                        "--parsable2",
                        "--allocations",
                        "--jobs",
                        "123",
                        "--format=JobIDRaw%32,JobName%256,State%64,ExitCode%32,Account%128,QOS%128,Comment%256",
                    ],
                    "sacct_stdout": ("123|sealed-job-name|COMPLETED|0:0|ram|h100_ram_high|sealed-comment|\n"),
                    "sacct_stdout_sha256": hashlib.sha256(
                        b"123|sealed-job-name|COMPLETED|0:0|ram|h100_ram_high|sealed-comment|\n"
                    ).hexdigest(),
                    "submitted_batch_script_command": [
                        "scontrol",
                        "write",
                        "batch_script",
                        "123",
                        "-",
                    ],
                    "record": {
                        "job_id": "123",
                        "comment": "sealed-comment",
                        "job_name": "sealed-job-name",
                        "account": "ram",
                        "qos": "h100_ram_high",
                        "state": "COMPLETED",
                        "exit_code": "0:0",
                    },
                    "submitted_batch_script_sha256": script_identity["sha256"],
                },
            }
        ],
        "scheduler_mutation": False,
        "receipt_mutation": False,
    }
    plan_root = tmp_path / "plan-root"
    terminal_provenance_path = plan_root / "terminal_provenance.json"
    terminal_artifact = {
        key: summary[key]
        for key in (
            "plan",
            "state_root",
            "global_dispatch_intent",
            "terminal_receipt_count",
            "runner_produced_receipt_count",
            "scheduler_recovered_failure_count",
            "task_statuses",
            "attempts",
            "scheduler_mutation",
            "receipt_mutation",
        )
    }
    terminal_artifact["payload_without_self_hash_sha256"] = results.eval_plan.canonical_json_sha256(terminal_artifact)
    terminal_provenance_path.parent.mkdir(parents=True)
    terminal_provenance_path.write_bytes(results.eval_plan.canonical_json_bytes(terminal_artifact))
    terminal_provenance_path.chmod(0o444)
    summary.update(
        {
            "terminal_provenance": results.eval_plan.file_identity(terminal_provenance_path),
            "terminal_provenance_payload_without_self_hash_sha256": terminal_artifact[
                "payload_without_self_hash_sha256"
            ],
            "live_scheduler_recheck_performed": False,
            "live_scheduler_recheck_count": 0,
        }
    )
    validation = {
        "plan": {"plan_id": plan_id, "plan_root": str(plan_root)},
        "receipts": {"receipt_count": 1, "task_statuses": statuses},
    }
    authority = {
        "postrun_control_source": {"implementations": {"eval_dispatcher": dispatcher_identity}},
        "eval_execution_contract": {"dispatcher": dispatcher_identity},
    }
    postrun = {"authority": authority}
    observed = []

    def exact_validator(path: Path, arguments: list[str]) -> dict[str, object]:
        observed.append((path, arguments))
        return summary

    monkeypatch.setattr(results.launch, "_run_exact_validator", exact_validator)
    monkeypatch.setattr(
        results.postrun_authority,
        "validate_recorded_implementation",
        lambda artifact, **kwargs: dispatcher_identity,
    )

    result = results.validate_terminal_receipts_with_recorded_dispatcher(plan_path, validation, postrun)

    assert observed == [
        (
            dispatcher_path.resolve(),
            ["validate-terminals", "--plan", str(plan_path.resolve())],
        )
    ]
    assert result["implementation"] == dispatcher_identity
    assert result["summary"] == summary
    assert result["identity"] == results.eval_plan.file_identity(terminal_provenance_path)
    assert result["artifact"] == terminal_artifact


def test_smoke_spend_requires_one_same_dose_to_pass_all_four_targets() -> None:
    rows = []
    for dose in results.SMOKE_DOSES:
        for clock_type, target in results.SMOKE_REQUIRED_CLOCKS:
            value = 0.02 if dose == 0.0125 else 0.019
            rows.append(_gate_row(dose, clock_type, target, value))

    decision = results.smoke_spend_decision(rows, eligible_design="four_arm_smoke_screen")

    assert decision["qualifying_doses"] == [0.0125]
    assert decision["proceed_to_full_grid"] is True
    assert decision["per_dose"][0] == {
        "nominal_p": 0.0125,
        "dose_label": "p0125",
        "targets": [
            {"clock_type": clock_type, "target": target, "value": 0.02, "passes": True}
            for clock_type, target in results.SMOKE_REQUIRED_CLOCKS
        ],
        "passes_all_required_clocks": True,
    }


def test_smoke_spend_does_not_mix_passing_clocks_across_doses_or_authorize_a_full_grid() -> None:
    rows = []
    for dose_index, dose in enumerate(results.SMOKE_DOSES):
        for clock_index, (clock_type, target) in enumerate(results.SMOKE_REQUIRED_CLOCKS):
            value = 0.021 if clock_index % 2 == dose_index else 0.019
            rows.append(_gate_row(dose, clock_type, target, value))

    smoke = results.smoke_spend_decision(rows, eligible_design="four_arm_smoke_screen")
    full = results.smoke_spend_decision(rows, eligible_design="full_30_arm_grid")

    assert smoke["qualifying_doses"] == []
    assert smoke["proceed_to_full_grid"] is False
    assert full["applicable"] is False
    assert full["proceed_to_full_grid"] is False

    with pytest.raises(ValueError, match="Missing smoke D_A row"):
        results.smoke_spend_decision(rows[:-1], eligible_design="four_arm_smoke_screen")


def test_validate_stdout_is_the_exact_promotion_summary(monkeypatch, capsys) -> None:
    identity = {"path": "/analysis.json", "size_bytes": 123, "sha256": "a" * 64}
    validated = {
        "analysis_identity": identity,
        "analysis": {"smoke_spend_decision": {"proceed_to_full_grid": True}},
    }
    monkeypatch.setattr(
        results,
        "parse_args",
        lambda: SimpleNamespace(command="validate", analysis=Path("/analysis.json")),
    )
    monkeypatch.setattr(results, "validate_analysis", lambda path: validated)

    results.main()

    assert json.loads(capsys.readouterr().out) == {
        "command": "validate",
        "analysis": identity,
        "smoke_proceed_to_full_grid": True,
    }
