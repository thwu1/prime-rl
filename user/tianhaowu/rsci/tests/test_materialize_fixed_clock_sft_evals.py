from __future__ import annotations

import copy
from pathlib import Path

import pytest
from materialize_fixed_clock_sft_evals import (
    DEFAULT_MAX_PARALLEL,
    EVAL_LAUNCH_MANIFEST_NAME,
    EXPECTED_COMMON_EVALUATIONS,
    EXPECTED_EVALUATIONS,
    EXPECTED_FINAL_EVALUATIONS,
    OPERATIONS,
    SANITIZED_SBATCH_ENV_VARS,
    SCRIPT_REPO_PATH,
    TEMPLATE_REPO_PATH,
    TRAINING_STUDY_ID,
    build_config_pair,
    build_runtime_config_pair,
    build_submission_plan,
    checkpoint_identity,
    discover_evaluations,
    runtime_config_paths,
    runtime_port,
    submission_command,
    submission_intent,
    validate_config_pair,
    validate_existing_training_identity,
    validate_submission_intent,
    validate_submission_plan,
    validate_template,
    write_json_once,
    write_toml_once,
)
from prepare_rl_checkpoint_eval import DATA_SOURCES

REPO_ROOT = Path(__file__).resolve().parents[4]


def _training_manifest(tmp_path: Path) -> dict:
    launch_root = tmp_path / "training"
    arms = []
    for index in range(55):
        label = f"arm{index:02d}"
        max_steps = 96 if index < EXPECTED_FINAL_EVALUATIONS else 64
        readouts = [64, max_steps] if max_steps > 64 else [64]
        arms.append(
            {
                "label": label,
                "output_dir": str(launch_root / "runs" / label),
                "metadata": {"selection_seed": index},
                "rows": 1_024 + index,
                "schedule": "at_least_two_dataset_passes" if max_steps > 64 else "common_64_steps",
                "max_steps": max_steps,
                "readout_steps": readouts,
                "checkpoint_steps": readouts,
                "resolved_config": {"path": str(tmp_path / f"{label}.toml"), "sha256": "a" * 64},
                "sbatch": {"path": str(tmp_path / f"{label}.sbatch"), "sha256": "b" * 64},
            }
        )
    return {
        "study_id": TRAINING_STUDY_ID,
        "launch_root": str(launch_root),
        "arms": arms,
    }


def test_discovers_only_declared_common_and_distinct_final_readouts(tmp_path: Path) -> None:
    manifest = _training_manifest(tmp_path)
    tasks = discover_evaluations(manifest)

    assert len(tasks) == EXPECTED_EVALUATIONS == 82
    assert sum(task["readout"] == "common" for task in tasks) == EXPECTED_COMMON_EVALUATIONS == 55
    assert sum(task["readout"] == "final" for task in tasks) == EXPECTED_FINAL_EVALUATIONS == 27
    assert {task["step"] for task in tasks} == {64, 96}
    assert [task["task_index"] for task in tasks] == list(range(EXPECTED_EVALUATIONS))

    tampered = copy.deepcopy(manifest)
    tampered["arms"][0]["readout_steps"] = [64, 80, 96]
    with pytest.raises(ValueError, match="common/final contract"):
        discover_evaluations(tampered)


def test_configs_pin_clean_strict_op11_45_pass_at_one(tmp_path: Path) -> None:
    task = discover_evaluations(_training_manifest(tmp_path))[0]
    eval_root = (tmp_path / "eval").resolve()
    inference, evaluation = build_config_pair(
        task,
        task_index=task["task_index"],
        eval_root=eval_root,
        source_root=REPO_ROOT,
    )
    config_dir = eval_root / "configs" / task["eval_id"]
    inference_path = config_dir / "inference.toml"
    eval_path = config_dir / "eval.toml"
    write_toml_once(inference_path, inference)
    write_toml_once(eval_path, evaluation)
    validate_config_pair(
        task,
        task_index=task["task_index"],
        eval_root=eval_root,
        source_root=REPO_ROOT,
        inference_path=inference_path,
        eval_path=eval_path,
    )

    assert evaluation["evaluator"] == str(REPO_ROOT / "user/tianhaowu/rsci/figure3_eval.py")
    assert evaluation["eval"]["data_sources"] == DATA_SOURCES
    assert evaluation["eval"]["operations"] == list(OPERATIONS) == list(range(11, 46))
    assert evaluation["eval"]["examples_per_operation"] == 200
    assert evaluation["eval"]["samples_per_prompt"] == 1
    assert evaluation["eval"]["pass_at"] == [1]
    assert evaluation["eval"]["request_seed"] == 20260807
    assert not {
        "reward",
        "proxy_reward",
        "defect",
        "false_positive_rate",
        "false_negative_rate",
    } & set(evaluation["eval"])
    assert inference["enable_fp32_lm_head"] is True

    array_job_id = 1_025_7755
    runtime_inference, runtime_evaluation = build_runtime_config_pair(
        task,
        task_index=task["task_index"],
        array_job_id=array_job_id,
        eval_root=eval_root,
        source_root=REPO_ROOT,
    )
    runtime_inference_path, _ = runtime_config_paths(
        eval_root,
        array_job_id=array_job_id,
        task_index=task["task_index"],
    )
    expected_port = runtime_port(array_job_id, task["task_index"])
    assert runtime_inference["server"]["port"] == expected_port
    assert runtime_evaluation["infer_config"] == str(runtime_inference_path)
    assert runtime_evaluation["eval"]["api_base_url"] == f"http://127.0.0.1:{expected_port}/v1"
    assert runtime_evaluation["eval"] | {"api_base_url": evaluation["eval"]["api_base_url"]} == evaluation["eval"]

    tampered = copy.deepcopy(evaluation)
    tampered["eval"]["proxy_reward"] = True
    eval_path.unlink()
    write_toml_once(eval_path, tampered)
    with pytest.raises(ValueError, match="strict evaluation contract"):
        validate_config_pair(
            task,
            task_index=task["task_index"],
            eval_root=eval_root,
            source_root=REPO_ROOT,
            inference_path=inference_path,
            eval_path=eval_path,
        )


def test_array_submission_is_nonexclusive_and_plan_binds_checkpoint_bytes(tmp_path: Path) -> None:
    template = REPO_ROOT / TEMPLATE_REPO_PATH
    validate_template(template)
    checkpoint = (tmp_path / "checkpoint").resolve()
    checkpoint.mkdir()
    (checkpoint / "STABLE").touch()
    (checkpoint / "config.json").write_text("{}\n", encoding="utf-8")
    (checkpoint / "model.safetensors").write_bytes(b"weights")

    eval_root = (tmp_path / "eval").resolve()
    manifest_path = eval_root / EVAL_LAUNCH_MANIFEST_NAME
    write_json_once(manifest_path, {"study": "fixture"})
    eval_config = (tmp_path / "eval.toml").resolve()
    eval_config.write_text("[eval]\n", encoding="utf-8")
    tasks = [
        {
            "task_index": index,
            "eval_id": f"eval-{index}",
            "arm_label": f"arm-{index}",
            "step": 64,
            "model_path": str(checkpoint),
            "eval_config": {
                "path": str(eval_config),
                "sha256": "c" * 64,
            },
        }
        for index in range(EXPECTED_EVALUATIONS)
    ]
    manifest = {
        "eval_root": str(eval_root),
        "tasks": tasks,
        "array_template": {"path": str(template)},
        "source": {"run_dir": str(tmp_path / "source")},
    }
    validated = {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": "d" * 64,
    }
    plan, plan_sha256 = build_submission_plan(validated, max_parallel=8, dependency=None)
    plan_path = eval_root / "submissions" / "plans" / f"{plan_sha256}.json"
    write_json_once(plan_path, plan)
    validate_submission_plan(plan_path, validated, selected_task_index=0)

    command = submission_command(manifest, plan_path=plan_path, max_parallel=8, dependency=None)
    assert command[0] == "env"
    for variable in SANITIZED_SBATCH_ENV_VARS:
        assert ["-u", variable] == command[command.index(variable) - 1 : command.index(variable) + 1]
    assert "--parsable" in command
    assert "--oversubscribe" in command
    assert "--array=0-81%8" in command
    assert "--exclusive" not in " ".join(command)
    assert checkpoint_identity(checkpoint) == plan["tasks"][0]["checkpoint"]
    with pytest.raises(ValueError, match=r"\[1, 8\]"):
        build_submission_plan(validated, max_parallel=DEFAULT_MAX_PARALLEL + 1, dependency=None)

    control_tmux = {"socket": "socket", "session": "session", "window": "window"}
    intent = submission_intent(
        plan_sha256=plan_sha256,
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
    )
    intent_path = eval_root / "submissions" / "submission_intent.json"
    write_json_once(intent_path, intent)
    assert validate_submission_intent(intent_path, intent) == intent
    with pytest.raises(ValueError, match="different immutable submission intent"):
        validate_submission_intent(intent_path, {**intent, "plan_sha256": "e" * 64})

    training_identity = {"path": "/training/launch_manifest.json", "sha256": "f" * 64}
    validate_existing_training_identity(
        {
            "training_launch_manifest": training_identity,
            "training_launch_manifest_sha256": "f" * 64,
        },
        requested_identity=training_identity,
        requested_sha256="f" * 64,
    )
    with pytest.raises(ValueError, match="different training launch manifest"):
        validate_existing_training_identity(
            {
                "training_launch_manifest": training_identity,
                "training_launch_manifest_sha256": "f" * 64,
            },
            requested_identity={**training_identity, "sha256": "0" * 64},
            requested_sha256="0" * 64,
        )

    (checkpoint / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Checkpoint bytes changed"):
        validate_submission_plan(plan_path, validated, selected_task_index=0)
    with pytest.raises(ValueError, match="immutable JSON"):
        write_json_once(plan_path, {**plan, "max_parallel": 9})

    assert (REPO_ROOT / SCRIPT_REPO_PATH).is_file()
