from __future__ import annotations

from pathlib import Path

import materialize_fixed_clock_sft_evals as base
import materialize_fixed_clock_sft_gstar_evals as evaluator
import materialize_fixed_clock_sft_gstar_runs as training
import pytest
from materialize_fixed_clock_sft_gstar_evals import (
    EXPECTED_COMMON_EVALUATIONS,
    EXPECTED_EVALUATIONS,
    EXPECTED_FINAL_EVALUATIONS,
    build_submission_plan,
    discover_evaluations,
    job_receipt,
    parse_scheduler_array_ids,
    submission_command,
    submission_intent,
    validate_runtime_submission,
    validate_submission_intent,
    validate_submission_plan,
    validate_template,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_STEPS = (98, 157, 96, 156, 97, 163)


def make_training_manifest(tmp_path: Path) -> dict:
    launch_root = tmp_path / "training"
    arms = []
    final_iterator = iter(FINAL_STEPS)
    for index in range(15):
        label = f"arm{index:02d}_gstar"
        fixed_raw = index >= 9
        max_steps = next(final_iterator) if fixed_raw else 64
        readouts = [64, max_steps] if fixed_raw else [64]
        output_dir = launch_root / "runs" / label
        arms.append(
            {
                "label": label,
                "output_dir": str(output_dir),
                "metadata": {
                    "assignment": training.gstar.ASSIGNMENT,
                    "clock": "fixed_raw" if fixed_raw else "fixed_m",
                },
                "rows": 1_024 + index,
                "schedule": "at_least_two_dataset_passes" if fixed_raw else "common_64_steps",
                "max_steps": max_steps,
                "readout_steps": readouts,
                "checkpoint_steps": readouts,
                "resolved_config": {"path": str(tmp_path / f"{label}.toml"), "sha256": "a" * 64},
                "sbatch": {"path": str(tmp_path / f"{label}.sbatch"), "sha256": "b" * 64},
            }
        )
    return {
        "study_id": training.STUDY_ID,
        "launch_root": str(launch_root),
        "arms": arms,
    }


def test_discovers_exact_15_common_plus_6_final_readouts(tmp_path: Path) -> None:
    tasks = discover_evaluations(make_training_manifest(tmp_path))

    assert len(tasks) == EXPECTED_EVALUATIONS == 21
    assert sum(task["readout"] == "common" for task in tasks) == EXPECTED_COMMON_EVALUATIONS == 15
    assert sum(task["readout"] == "final" for task in tasks) == EXPECTED_FINAL_EVALUATIONS == 6
    assert sorted(task["step"] for task in tasks if task["readout"] == "final") == sorted(FINAL_STEPS)
    assert [task["task_index"] for task in tasks] == list(range(21))

    malformed = make_training_manifest(tmp_path / "other")
    malformed["arms"][9]["readout_steps"] = [64]
    with pytest.raises(ValueError, match="readouts differ"):
        discover_evaluations(malformed)


def test_template_is_nonexclusive_and_calls_gstar_runtime_validator() -> None:
    path = REPO_ROOT / evaluator.TEMPLATE_REPO_PATH
    validate_template(path)
    text = path.read_text(encoding="utf-8")

    assert "#SBATCH --gres=gpu:1" in text
    assert "--exclusive" not in text
    assert "materialize_fixed_clock_sft_gstar_evals.py prepare-task" in text


def test_plan_hashes_21_checkpoints_and_caps_concurrency(tmp_path: Path) -> None:
    tasks = discover_evaluations(make_training_manifest(tmp_path))
    eval_root = tmp_path / "eval"
    manifest_path = eval_root / evaluator.EVAL_LAUNCH_MANIFEST_NAME
    eval_root.mkdir()
    base.write_json_once(manifest_path, {"fixture": True})
    eval_config = tmp_path / "eval.toml"
    eval_config.write_text("[eval]\n", encoding="utf-8")
    for task in tasks:
        checkpoint = Path(task["model_path"])
        checkpoint.mkdir(parents=True)
        (checkpoint / "STABLE").touch()
        (checkpoint / "config.json").write_text("{}\n", encoding="utf-8")
        (checkpoint / "model.safetensors").write_bytes(task["eval_id"].encode())
        task["eval_config"] = base.file_identity(eval_config)
    manifest = {
        "eval_root": str(eval_root),
        "tasks": tasks,
        "array_template": {"path": str(REPO_ROOT / evaluator.TEMPLATE_REPO_PATH)},
        "source": {"run_dir": str(tmp_path / "source")},
    }
    validated = {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": base.file_sha256(manifest_path),
    }
    assert evaluator.submission_status(validated) == {
        "state": "not_submitted",
        "submitted": False,
        "array_job_id": None,
    }
    plan, plan_sha256 = build_submission_plan(validated, max_parallel=8, dependency=None)
    plan_path = eval_root / "submissions" / "plans" / f"{plan_sha256}.json"
    base.write_json_once(plan_path, plan)
    validate_submission_plan(plan_path, validated)

    assert plan["array_spec"] == "0-20%8"
    assert plan["task_count"] == 21
    command = submission_command(
        manifest,
        validated=validated,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        max_parallel=8,
        dependency=None,
    )
    assert "--array=0-20%8" in command
    assert "--oversubscribe" in command
    assert "--exclusive" not in command
    assert any(value.startswith("--comment=rsci-gstar-eval-v1-") for value in command)
    with pytest.raises(ValueError, match=r"\[1, 8\]"):
        build_submission_plan(validated, max_parallel=9, dependency=None)

    control_tmux = {
        "socket": evaluator.CONTROL_TMUX_SOCKET,
        "session": evaluator.CONTROL_TMUX_SESSION,
        "window": evaluator.CONTROL_TMUX_WINDOW,
    }
    intent = submission_intent(
        plan_sha256=plan_sha256,
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
    )
    intent_path = eval_root / "submissions" / evaluator.SUBMISSION_INTENT_NAME
    base.write_json_once(intent_path, intent)
    assert validate_submission_intent(intent_path, intent) == intent
    receipt = job_receipt(
        array_job_id=12345,
        plan_sha256=plan_sha256,
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
        submission_source="sbatch_stdout",
        sbatch_stdout="12345",
    )
    base.write_json_once(eval_root / "submissions" / "jobs" / "12345.json", receipt)
    validated_plan = validate_submission_plan(plan_path, validated)
    assert validate_runtime_submission(validated, validated_plan, array_job_id=12345)["array_job_id"] == 12345
    with pytest.raises(FileNotFoundError):
        validate_runtime_submission(validated, validated_plan, array_job_id=12346)


def test_scheduler_array_parser_normalizes_master_job_id() -> None:
    output = "10264536|target|\n10264536_0|target|\n10264536_20|target|\n10270000_0|other|\n"
    assert parse_scheduler_array_ids(output, comment="target") == {10264536}
