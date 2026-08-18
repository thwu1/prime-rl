#!/usr/bin/env python3
"""Materialize and guard strict OP11-45 evaluations for Gstar SFT readouts."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import materialize_fixed_clock_sft_evals as base
import materialize_fixed_clock_sft_gstar_runs as training_runs

TRAINING_STUDY_ID = training_runs.STUDY_ID
STUDY_ID = "verifier_defect_fixed_clock_sft_gstar_eval_v1"
SCHEMA_VERSION = 1
EXPECTED_TRAINING_ARMS = 15
EXPECTED_COMMON_EVALUATIONS = 15
EXPECTED_FINAL_EVALUATIONS = 6
EXPECTED_EVALUATIONS = 21
COMMON_STEP = 64
DEFAULT_MAX_PARALLEL = 8
SHA256_RE = re.compile(r"[0-9a-f]{64}")
DEFAULT_TRAINING_LAUNCH_MANIFEST = training_runs.DEFAULT_LAUNCH_ROOT / training_runs.LAUNCH_MANIFEST_NAME
DEFAULT_EVAL_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-fixed-clock-sft-gstar-v1")
EVAL_LAUNCH_MANIFEST_NAME = "eval_launch_manifest.json"
SUBMISSION_INTENT_NAME = "submission_intent.json"
SUBMISSION_LOCK_NAME = "submission.lock"
COMMENT_PREFIX = "rsci-gstar-eval-v1"
SCRIPT_REPO_PATH = Path("user/tianhaowu/rsci/materialize_fixed_clock_sft_gstar_evals.py")
TEMPLATE_REPO_PATH = Path("user/tianhaowu/rsci/templates/fixed_clock_sft_gstar_eval_array.sbatch")
TRAINING_MATERIALIZER_REPO_PATH = training_runs.SCRIPT_REPO_PATH
BASE_EVAL_HELPER_REPO_PATH = base.SCRIPT_REPO_PATH
ACTIVATOR_REPO_PATH = base.ACTIVATOR_REPO_PATH
RUN_EVAL_REPO_PATH = base.RUN_EVAL_REPO_PATH
SCORER_REPO_PATH = base.SCORER_REPO_PATH
SOLUTION_GRAPH_REPO_PATH = base.SOLUTION_GRAPH_REPO_PATH
PREPARE_REPO_PATH = base.PREPARE_REPO_PATH
SANITIZED_SBATCH_ENV_VARS = base.SANITIZED_SBATCH_ENV_VARS
CONTROL_TMUX_SOCKET = base.CONTROL_TMUX_SOCKET
CONTROL_TMUX_SESSION = base.CONTROL_TMUX_SESSION
CONTROL_TMUX_WINDOW = base.CONTROL_TMUX_WINDOW

EVALUATION_CONTRACT = {
    **base.EVALUATION_CONTRACT,
    "readouts": "step 64 for all 15 Gstar arms plus the distinct final step for six fixed-raw arms",
    "expected_training_arms": EXPECTED_TRAINING_ARMS,
    "expected_common_evaluations": EXPECTED_COMMON_EVALUATIONS,
    "expected_final_evaluations": EXPECTED_FINAL_EVALUATIONS,
    "expected_evaluations": EXPECTED_EVALUATIONS,
    "max_parallel_cap": DEFAULT_MAX_PARALLEL,
    "submission_guard": "one immutable intent and one immutable array-job receipt per launch manifest",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--training-launch-manifest", type=Path, default=DEFAULT_TRAINING_LAUNCH_MANIFEST)
    materialize.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    materialize.add_argument("--source-run-dir", type=Path)
    materialize.add_argument("--dry-run", action="store_true")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    validate_task = subparsers.add_parser("validate-task")
    validate_task.add_argument("--eval-launch-manifest", type=Path, required=True)
    validate_task.add_argument("--submission-plan", type=Path, required=True)
    validate_task.add_argument("--task-index", type=int, required=True)
    validate_task.add_argument("--print-config", action="store_true")
    prepare_task = subparsers.add_parser("prepare-task")
    prepare_task.add_argument("--eval-launch-manifest", type=Path, required=True)
    prepare_task.add_argument("--submission-plan", type=Path, required=True)
    prepare_task.add_argument("--task-index", type=int, required=True)
    prepare_task.add_argument("--array-job-id", type=int, required=True)
    prepare_task.add_argument("--print-config", action="store_true")
    submit = subparsers.add_parser("submit")
    submit.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    submit.add_argument("--max-parallel", type=int, default=DEFAULT_MAX_PARALLEL)
    submit.add_argument("--dependency")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--confirm-study-id")
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    reconcile.add_argument("--dry-run", action="store_true")
    reconcile.add_argument("--confirm-study-id")
    return parser.parse_args()


def active_source_state(source_run_dir: Path) -> base.SourceState:
    source_run_dir = source_run_dir.expanduser().resolve()
    from source_provenance import verify_snapshot

    provenance = verify_snapshot(source_run_dir, require_launch=False)
    source_root = Path(provenance["snapshot_path"]).resolve()
    if Path(__file__).resolve() != (source_root / SCRIPT_REPO_PATH).resolve():
        raise ValueError(
            "Gstar evaluation materialization must run from the pinned source snapshot; source "
            f"{source_root / ACTIVATOR_REPO_PATH} first"
        )
    if os.environ.get("RSCI_SOURCE_SNAPSHOT") != str(source_root):
        raise ValueError("Pinned Gstar evaluation source activation is missing")
    required = (
        TEMPLATE_REPO_PATH,
        TRAINING_MATERIALIZER_REPO_PATH,
        BASE_EVAL_HELPER_REPO_PATH,
        ACTIVATOR_REPO_PATH,
        RUN_EVAL_REPO_PATH,
        SCORER_REPO_PATH,
        SOLUTION_GRAPH_REPO_PATH,
        PREPARE_REPO_PATH,
    )
    for relative in required:
        if not (source_root / relative).is_file():
            raise FileNotFoundError(source_root / relative)
    return base.SourceState(source_run_dir, source_root, provenance)


def validate_template(path: Path) -> None:
    base.validate_template(path)
    text = path.read_text(encoding="utf-8")
    required = (
        "#SBATCH --job-name=rsci-vd-gstar-eval",
        "materialize_fixed_clock_sft_gstar_evals.py prepare-task",
        "rsci-vd-gstar-eval-${ARRAY_JOB_ID}-${TASK_INDEX}",
        "SUBMISSION_RECEIPT",
        "{1..120}",
    )
    for value in required:
        if value not in text:
            raise ValueError(f"Gstar evaluation template lacks {value!r}: {path}")
    if "materialize_fixed_clock_sft_evals.py prepare-task" in text:
        raise ValueError("Gstar evaluation template invokes the v2 task validator")


def validate_training_launch_manifest(path: Path) -> dict[str, Any]:
    return training_runs.validate_launch_manifest(path)


def discover_evaluations(training_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if training_manifest.get("study_id") != TRAINING_STUDY_ID:
        raise ValueError("Gstar training launch manifest has the wrong study identity")
    arms = training_manifest.get("arms")
    if not isinstance(arms, list) or len(arms) != EXPECTED_TRAINING_ARMS:
        raise ValueError(f"Gstar training launch must contain {EXPECTED_TRAINING_ARMS} arms")
    labels = [arm.get("label") for arm in arms if isinstance(arm, dict)]
    if len(labels) != len(arms) or labels != sorted(labels) or len(set(labels)) != len(labels):
        raise ValueError("Gstar training arm labels are missing, duplicated, or unsorted")
    launch_root = Path(str(training_manifest.get("launch_root", ""))).expanduser().resolve()
    tasks: list[dict[str, Any]] = []
    fixed_m_count = 0
    fixed_raw_count = 0
    for arm in arms:
        label = arm["label"]
        metadata = arm.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("assignment") != training_runs.gstar.ASSIGNMENT:
            raise ValueError(f"Training arm {label} is not a Gstar arm")
        clock = metadata.get("clock")
        if clock == "fixed_m":
            fixed_m_count += 1
        elif clock == "fixed_raw":
            fixed_raw_count += 1
        else:
            raise ValueError(f"Training arm {label} has an invalid clock")
        output_dir = Path(str(arm.get("output_dir", ""))).expanduser().resolve()
        if output_dir != launch_root / "runs" / label:
            raise ValueError(f"Training output path differs for arm {label}")
        max_steps = arm.get("max_steps")
        readouts = arm.get("readout_steps")
        checkpoints = arm.get("checkpoint_steps")
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < COMMON_STEP:
            raise ValueError(f"Training arm {label} has invalid max_steps")
        expected_readouts = [COMMON_STEP] if clock == "fixed_m" else [COMMON_STEP, max_steps]
        if clock == "fixed_raw" and max_steps <= COMMON_STEP:
            raise ValueError(f"Fixed-raw Gstar arm {label} has no distinct final step")
        if readouts != expected_readouts:
            raise ValueError(f"Training arm {label} readouts differ: {readouts!r} != {expected_readouts!r}")
        if not isinstance(checkpoints, list) or any(step not in checkpoints for step in expected_readouts):
            raise ValueError(f"Training arm {label} does not retain every declared readout checkpoint")
        for step in expected_readouts:
            tasks.append(
                {
                    "eval_id": f"{label}__step_{step}",
                    "arm_label": label,
                    "step": step,
                    "readout": "common" if step == COMMON_STEP else "final",
                    "model_path": str(output_dir / "weights" / f"step_{step}"),
                    "training_output_dir": str(output_dir),
                    "training_resolved_config": arm.get("resolved_config"),
                    "training_sbatch": arm.get("sbatch"),
                    "arm_contract_sha256": base.canonical_json_sha256(
                        {
                            "label": label,
                            "metadata": metadata,
                            "rows": arm.get("rows"),
                            "schedule": arm.get("schedule"),
                            "max_steps": max_steps,
                            "checkpoint_steps": checkpoints,
                            "readout_steps": readouts,
                        }
                    ),
                }
            )
    if (fixed_m_count, fixed_raw_count) != (9, 6):
        raise ValueError("Gstar training clock dimensions differ from 9 fixed-M plus 6 fixed-raw")
    tasks.sort(key=lambda task: (task["arm_label"], task["step"]))
    for index, task in enumerate(tasks):
        task["task_index"] = index
    observed_counts = (
        len(tasks),
        sum(task["readout"] == "common" for task in tasks),
        sum(task["readout"] == "final" for task in tasks),
    )
    if observed_counts != (EXPECTED_EVALUATIONS, EXPECTED_COMMON_EVALUATIONS, EXPECTED_FINAL_EVALUATIONS):
        raise ValueError(f"Gstar evaluation grid differs: {observed_counts!r}")
    return tasks


def _source_record(source: base.SourceState) -> dict[str, Any]:
    return {
        "run_dir": str(source.run_dir),
        "snapshot_path": str(source.root),
        "parent_commit_sha": source.provenance["parent_commit_sha"],
        "source_tree_sha256": source.provenance["source_tree_sha256"],
        "provenance_manifest": base.file_identity(source.run_dir / "source_provenance.json"),
    }


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    eval_root = args.eval_root.expanduser().resolve()
    source_run_dir = (args.source_run_dir or eval_root).expanduser().resolve()
    source = active_source_state(source_run_dir)
    training = validate_training_launch_manifest(args.training_launch_manifest.expanduser().resolve())
    if (
        training["manifest"]["implementation"]["sha256"]
        != base.file_identity(source.root / TRAINING_MATERIALIZER_REPO_PATH)["sha256"]
    ):
        raise ValueError("Evaluation source has different Gstar training-materializer bytes")
    tasks = discover_evaluations(training["manifest"])
    inputs = base.evaluation_input_state()
    plan = {
        "study_id": STUDY_ID,
        "eval_root": str(eval_root),
        "training_arms": len(training["manifest"]["arms"]),
        "evaluation_count": len(tasks),
        "common_step_evaluations": EXPECTED_COMMON_EVALUATIONS,
        "distinct_final_evaluations": EXPECTED_FINAL_EVALUATIONS,
        "prompts_per_evaluation": base.EXPECTED_PROMPTS,
        "total_generations": len(tasks) * base.EXPECTED_PROMPTS,
        "gpus_per_task": 1,
        "default_max_parallel": DEFAULT_MAX_PARALLEL,
    }
    if args.dry_run:
        return plan
    if source.root.parent != source.run_dir or eval_root != source.run_dir:
        raise ValueError("The Gstar evaluation source snapshot must be rooted at eval_root/source_snapshot")
    manifest_path = eval_root / EVAL_LAUNCH_MANIFEST_NAME
    if manifest_path.exists():
        validated = validate_eval_launch_manifest(manifest_path)
        base.validate_existing_training_identity(
            validated["manifest"],
            requested_identity=base.file_identity(Path(training["manifest_path"])),
            requested_sha256=training["manifest_sha256"],
        )
        return {**plan, "manifest_sha256": validated["manifest_sha256"], "already_materialized": True}
    eval_root.mkdir(parents=True, exist_ok=True)
    task_records = []
    for task in tasks:
        index = task["task_index"]
        config_dir = eval_root / "configs" / task["eval_id"]
        inference_path = config_dir / "inference.toml"
        eval_path = config_dir / "eval.toml"
        inference, evaluation = base.build_config_pair(
            task,
            task_index=index,
            eval_root=eval_root,
            source_root=source.root,
        )
        base.write_toml_once(inference_path, inference)
        base.write_toml_once(eval_path, evaluation)
        base.validate_config_pair(
            task,
            task_index=index,
            eval_root=eval_root,
            source_root=source.root,
            inference_path=inference_path,
            eval_path=eval_path,
        )
        task_records.append(
            {
                **task,
                "output_dir": evaluation["eval"]["output_dir"],
                "port": inference["server"]["port"],
                "inference_config": base.file_identity(inference_path),
                "eval_config": base.file_identity(eval_path),
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "eval_root": str(eval_root),
        "source": _source_record(source),
        "training_launch_manifest": base.file_identity(Path(training["manifest_path"])),
        "training_launch_manifest_sha256": training["manifest_sha256"],
        "evaluation_contract": EVALUATION_CONTRACT,
        "evaluation_inputs": inputs,
        "implementation": base.file_identity(source.root / SCRIPT_REPO_PATH),
        "base_eval_helper": base.file_identity(source.root / BASE_EVAL_HELPER_REPO_PATH),
        "training_materializer": base.file_identity(source.root / TRAINING_MATERIALIZER_REPO_PATH),
        "array_template": base.file_identity(source.root / TEMPLATE_REPO_PATH),
        "activator": base.file_identity(source.root / ACTIVATOR_REPO_PATH),
        "run_eval": base.file_identity(source.root / RUN_EVAL_REPO_PATH),
        "scorer": base.file_identity(source.root / SCORER_REPO_PATH),
        "solution_graph": base.file_identity(source.root / SOLUTION_GRAPH_REPO_PATH),
        "prepare_reference": base.file_identity(source.root / PREPARE_REPO_PATH),
        "training_arm_count": EXPECTED_TRAINING_ARMS,
        "evaluation_count": EXPECTED_EVALUATIONS,
        "common_step_evaluation_count": EXPECTED_COMMON_EVALUATIONS,
        "distinct_final_evaluation_count": EXPECTED_FINAL_EVALUATIONS,
        "tasks": task_records,
    }
    base.write_json_once(manifest_path, manifest)
    validated = validate_eval_launch_manifest(manifest_path)
    return {**plan, "manifest_sha256": validated["manifest_sha256"], "already_materialized": False}


def _validate_source_record(source: object) -> base.SourceState:
    if not isinstance(source, dict):
        raise ValueError("Gstar evaluation manifest has no source record")
    run_dir = Path(str(source.get("run_dir", ""))).expanduser().resolve()
    from source_provenance import verify_snapshot

    provenance = verify_snapshot(run_dir, require_launch=False)
    root = Path(provenance["snapshot_path"]).resolve()
    expected = {
        "run_dir": str(run_dir),
        "snapshot_path": str(root),
        "parent_commit_sha": provenance["parent_commit_sha"],
        "source_tree_sha256": provenance["source_tree_sha256"],
        "provenance_manifest": base.file_identity(run_dir / "source_provenance.json"),
    }
    if source != expected:
        raise ValueError("Gstar evaluation source record differs from pinned provenance")
    return base.SourceState(run_dir, root, provenance)


def _validate_header(manifest_path: Path) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    manifest = base.read_json_object(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("study_id") != STUDY_ID:
        raise ValueError("Gstar evaluation manifest has the wrong schema or study identity")
    eval_root = Path(str(manifest.get("eval_root", ""))).expanduser().resolve()
    if manifest_path.resolve() != eval_root / EVAL_LAUNCH_MANIFEST_NAME:
        raise ValueError("Gstar evaluation manifest is not at its recorded root")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != EXPECTED_EVALUATIONS:
        raise ValueError(f"Gstar evaluation manifest must contain {EXPECTED_EVALUATIONS} tasks")
    if [task.get("task_index") for task in tasks if isinstance(task, dict)] != list(range(len(tasks))):
        raise ValueError("Gstar evaluation task indices are not contiguous")
    eval_ids = [task.get("eval_id") for task in tasks]
    if len(set(eval_ids)) != len(tasks) or any(not isinstance(value, str) for value in eval_ids):
        raise ValueError("Gstar evaluation task IDs are missing or duplicated")
    expected_counts = {
        "training_arm_count": EXPECTED_TRAINING_ARMS,
        "evaluation_count": EXPECTED_EVALUATIONS,
        "common_step_evaluation_count": EXPECTED_COMMON_EVALUATIONS,
        "distinct_final_evaluation_count": EXPECTED_FINAL_EVALUATIONS,
    }
    if manifest.get("evaluation_contract") != EVALUATION_CONTRACT:
        raise ValueError("Gstar evaluation scientific contract differs")
    for field, expected in expected_counts.items():
        if manifest.get(field) != expected:
            raise ValueError(f"Gstar evaluation {field} differs")
    return manifest, eval_root, tasks


def _validate_shared_inputs(manifest: dict[str, Any], source: base.SourceState) -> None:
    fields = (
        "implementation",
        "base_eval_helper",
        "training_materializer",
        "array_template",
        "activator",
        "run_eval",
        "scorer",
        "solution_graph",
        "prepare_reference",
        "training_launch_manifest",
    )
    for field in fields:
        base._verify_file_identity(manifest.get(field), field)
    expected_paths = {
        "implementation": source.root / SCRIPT_REPO_PATH,
        "base_eval_helper": source.root / BASE_EVAL_HELPER_REPO_PATH,
        "training_materializer": source.root / TRAINING_MATERIALIZER_REPO_PATH,
        "array_template": source.root / TEMPLATE_REPO_PATH,
        "activator": source.root / ACTIVATOR_REPO_PATH,
        "run_eval": source.root / RUN_EVAL_REPO_PATH,
        "scorer": source.root / SCORER_REPO_PATH,
        "solution_graph": source.root / SOLUTION_GRAPH_REPO_PATH,
        "prepare_reference": source.root / PREPARE_REPO_PATH,
    }
    for field, expected in expected_paths.items():
        if Path(manifest[field]["path"]).resolve() != expected.resolve():
            raise ValueError(f"Gstar evaluation {field} path differs")
    validate_template(Path(manifest["array_template"]["path"]))
    if manifest.get("evaluation_inputs") != base.evaluation_input_state():
        raise ValueError("Held-out OP11-45 inputs changed after Gstar evaluator materialization")


def validate_eval_launch_manifest(manifest_path: Path, *, runtime_task_index: int | None = None) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest, eval_root, tasks = _validate_header(manifest_path)
    source = _validate_source_record(manifest.get("source"))
    _validate_shared_inputs(manifest, source)
    training_identity = manifest["training_launch_manifest"]
    if manifest.get("training_launch_manifest_sha256") != training_identity["sha256"]:
        raise ValueError("Gstar training launch hash fields disagree")
    if runtime_task_index is None:
        training = validate_training_launch_manifest(Path(training_identity["path"]))
        if training["manifest_sha256"] != manifest["training_launch_manifest_sha256"]:
            raise ValueError("Gstar training launch changed after evaluator materialization")
        if training["manifest"]["implementation"]["sha256"] != manifest["training_materializer"]["sha256"]:
            raise ValueError("Gstar training and evaluation source implementations differ")
        discovered = discover_evaluations(training["manifest"])
        indices = range(len(tasks))
    else:
        if not 0 <= runtime_task_index < len(tasks):
            raise ValueError(f"Task index is outside [0, {len(tasks)}): {runtime_task_index}")
        discovered = None
        indices = (runtime_task_index,)
    for index in indices:
        task = tasks[index]
        if discovered is not None:
            fields = set(discovered[index])
            if {field: task.get(field) for field in fields} != discovered[index]:
                raise ValueError(f"Gstar evaluation task {index} differs from its training readout")
        for field in ("training_resolved_config", "training_sbatch", "inference_config", "eval_config"):
            base._verify_file_identity(task.get(field), f"tasks.{index}.{field}")
        base.validate_config_pair(
            task,
            task_index=index,
            eval_root=eval_root,
            source_root=source.root,
            inference_path=Path(task["inference_config"]["path"]),
            eval_path=Path(task["eval_config"]["path"]),
        )
    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": base.file_sha256(manifest_path),
    }


def build_submission_plan(
    validated: dict[str, Any], *, max_parallel: int, dependency: str | None
) -> tuple[dict[str, Any], str]:
    base._validate_max_parallel(max_parallel)
    base._validate_dependency(dependency)
    tasks = []
    for task in validated["manifest"]["tasks"]:
        tasks.append(
            {
                "task_index": task["task_index"],
                "eval_id": task["eval_id"],
                "arm_label": task["arm_label"],
                "step": task["step"],
                "eval_config_sha256": task["eval_config"]["sha256"],
                "checkpoint": base.checkpoint_identity(Path(task["model_path"])),
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "eval_launch_manifest": base.file_identity(Path(validated["manifest_path"])),
        "max_parallel": max_parallel,
        "dependency": dependency,
        "array_spec": f"0-{len(tasks) - 1}%{max_parallel}",
        "task_count": len(tasks),
        "tasks": tasks,
    }
    return payload, base.canonical_json_sha256(payload)


def validate_submission_plan(
    path: Path, validated: dict[str, Any], *, selected_task_index: int | None = None
) -> dict[str, Any]:
    path = path.expanduser().resolve()
    plan = base.read_json_object(path)
    plan_sha256 = base.canonical_json_sha256(plan)
    if path.stem != plan_sha256 or SHA256_RE.fullmatch(path.stem) is None:
        raise ValueError("Gstar eval plan filename does not match its SHA-256")
    if plan.get("schema_version") != SCHEMA_VERSION or plan.get("study_id") != STUDY_ID:
        raise ValueError("Gstar eval plan has the wrong study identity")
    if plan.get("eval_launch_manifest") != base.file_identity(Path(validated["manifest_path"])):
        raise ValueError("Gstar eval plan belongs to another manifest")
    tasks = plan.get("tasks")
    manifest_tasks = validated["manifest"]["tasks"]
    if not isinstance(tasks, list) or plan.get("task_count") != len(tasks) or len(tasks) != len(manifest_tasks):
        raise ValueError("Gstar eval plan has an invalid task list")
    max_parallel = plan.get("max_parallel")
    base._validate_max_parallel(max_parallel)
    dependency = plan.get("dependency")
    if dependency is not None and not isinstance(dependency, str):
        raise ValueError("Gstar eval dependency must be a string or null")
    base._validate_dependency(dependency)
    if plan.get("array_spec") != f"0-{len(tasks) - 1}%{max_parallel}":
        raise ValueError("Gstar eval array specification differs")
    indices = range(len(tasks)) if selected_task_index is None else (selected_task_index,)
    for index in indices:
        if not 0 <= index < len(tasks):
            raise ValueError(f"Gstar eval task index is outside [0, {len(tasks)}): {index}")
        task = tasks[index]
        manifest_task = manifest_tasks[index]
        expected = {
            "task_index": index,
            "eval_id": manifest_task["eval_id"],
            "arm_label": manifest_task["arm_label"],
            "step": manifest_task["step"],
            "eval_config_sha256": manifest_task["eval_config"]["sha256"],
        }
        if any(task.get(field) != value for field, value in expected.items()):
            raise ValueError(f"Gstar eval plan task {index} differs")
        if task.get("checkpoint") != base.checkpoint_identity(Path(manifest_task["model_path"])):
            raise ValueError(f"Gstar eval checkpoint changed for task {index}")
    return {"plan": plan, "plan_sha256": plan_sha256, "path": str(path)}


def submission_comment(validated: dict[str, Any], plan_sha256: str) -> str:
    material = {
        "study_id": STUDY_ID,
        "eval_launch_manifest_sha256": validated["manifest_sha256"],
        "plan_sha256": plan_sha256,
    }
    return f"{COMMENT_PREFIX}-{base.canonical_json_sha256(material)}"


def submission_command(
    manifest: dict[str, Any],
    *,
    validated: dict[str, Any],
    plan_path: Path,
    plan_sha256: str,
    max_parallel: int,
    dependency: str | None,
) -> list[str]:
    command = base.submission_command(
        manifest,
        plan_path=plan_path,
        max_parallel=max_parallel,
        dependency=dependency,
    )
    comment = submission_comment(validated, plan_sha256)
    command.insert(command.index("--parsable") + 1, f"--comment={comment}")
    return command


def parse_scheduler_array_ids(output: str, *, comment: str) -> set[int]:
    job_ids: set[int] = set()
    for raw_line in output.splitlines():
        fields = raw_line.strip().split("|")
        if len(fields) < 2 or fields[1].strip() != comment:
            continue
        match = re.fullmatch(r"([1-9][0-9]*)(?:[_.].*)?", fields[0].strip())
        if match is not None:
            job_ids.add(int(match.group(1)))
    return job_ids


def scheduler_matches(comment: str) -> tuple[set[int], dict[str, Any]]:
    squeue_command = ["squeue", "--noheader", "--format=%F|%k"]
    sacct_command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--starttime",
        "2026-08-01T00:00:00",
        "--format=JobID,Comment",
    ]
    squeue = subprocess.run(squeue_command, check=True, capture_output=True, text=True)
    sacct = subprocess.run(sacct_command, check=True, capture_output=True, text=True)
    squeue_ids = parse_scheduler_array_ids(squeue.stdout, comment=comment)
    sacct_ids = parse_scheduler_array_ids(sacct.stdout, comment=comment)
    matches = squeue_ids | sacct_ids
    evidence = {
        "squeue_command": squeue_command,
        "squeue_stdout_sha256": hashlib.sha256(squeue.stdout.encode()).hexdigest(),
        "squeue_array_job_ids": sorted(squeue_ids),
        "sacct_command": sacct_command,
        "sacct_stdout_sha256": hashlib.sha256(sacct.stdout.encode()).hexdigest(),
        "sacct_array_job_ids": sorted(sacct_ids),
        "matched_array_job_ids": sorted(matches),
    }
    return matches, evidence


def submission_intent(
    *, plan_sha256: str, plan_path: Path, validated: dict[str, Any], command: list[str], control_tmux: dict[str, str]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "eval_launch_manifest": base.file_identity(Path(validated["manifest_path"])),
        "eval_launch_manifest_sha256": validated["manifest_sha256"],
        "plan_sha256": plan_sha256,
        "plan": base.file_identity(plan_path),
        "control_tmux": control_tmux,
        "command": command,
        "failure_policy": "fail closed if no receipt exists; reconcile scheduler state before resubmission",
    }


def validate_submission_intent(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    observed = base.read_json_object(path)
    if observed != expected:
        raise ValueError("Gstar eval manifest already has a different immutable submission intent")
    return observed


def _validate_receipt(
    path: Path,
    *,
    plan_sha256: str,
    plan_path: Path,
    validated: dict[str, Any],
    command: list[str],
    control_tmux: dict[str, str],
) -> dict[str, Any]:
    receipt = base.read_json_object(path)
    if receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("study_id") != STUDY_ID:
        raise ValueError("Gstar eval receipt has the wrong study identity")
    job_id = receipt.get("array_job_id")
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1 or path.stem != str(job_id):
        raise ValueError("Gstar eval receipt filename differs from its job ID")
    expected = {
        "plan_sha256": plan_sha256,
        "plan": base.file_identity(plan_path),
        "submission_intent": base.file_identity(plan_path.parent.parent / SUBMISSION_INTENT_NAME),
        "eval_launch_manifest_sha256": validated["manifest_sha256"],
        "control_tmux": control_tmux,
        "command": command,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ValueError(f"Gstar eval receipt {field} differs")
    source = receipt.get("submission_source")
    stdout = receipt.get("sbatch_stdout")
    evidence = receipt.get("scheduler_evidence")
    if source == "sbatch_stdout":
        if not isinstance(stdout, str) or stdout.split(";", maxsplit=1)[0] != str(job_id) or evidence is not None:
            raise ValueError("Gstar eval receipt has invalid sbatch output")
    elif source == "scheduler_reconciliation":
        expected_keys = {
            "squeue_command",
            "squeue_stdout_sha256",
            "squeue_array_job_ids",
            "sacct_command",
            "sacct_stdout_sha256",
            "sacct_array_job_ids",
            "matched_array_job_ids",
        }
        if (
            stdout is not None
            or not isinstance(evidence, dict)
            or set(evidence) != expected_keys
            or evidence.get("matched_array_job_ids") != [job_id]
            or sorted(set(evidence.get("squeue_array_job_ids", [])) | set(evidence.get("sacct_array_job_ids", [])))
            != [job_id]
            or evidence.get("squeue_command") != ["squeue", "--noheader", "--format=%F|%k"]
            or evidence.get("sacct_command")
            != [
                "sacct",
                "--noheader",
                "--parsable2",
                "--allocations",
                "--starttime",
                "2026-08-01T00:00:00",
                "--format=JobID,Comment",
            ]
            or any(
                re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(field))) is None
                for field in ("squeue_stdout_sha256", "sacct_stdout_sha256")
            )
        ):
            raise ValueError("Gstar eval reconciled receipt has invalid scheduler evidence")
    else:
        raise ValueError("Gstar eval receipt has an invalid submission source")
    return receipt


def job_receipt(
    *,
    array_job_id: int,
    plan_sha256: str,
    plan_path: Path,
    validated: dict[str, Any],
    command: list[str],
    control_tmux: dict[str, str],
    submission_source: str,
    sbatch_stdout: str | None = None,
    scheduler_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "array_job_id": array_job_id,
        "plan_sha256": plan_sha256,
        "plan": base.file_identity(plan_path),
        "submission_intent": base.file_identity(plan_path.parent.parent / SUBMISSION_INTENT_NAME),
        "eval_launch_manifest_sha256": validated["manifest_sha256"],
        "control_tmux": control_tmux,
        "command": command,
        "submission_source": submission_source,
        "sbatch_stdout": sbatch_stdout,
        "scheduler_evidence": scheduler_evidence,
    }


def _existing_receipt(
    eval_root: Path,
    *,
    plan_sha256: str,
    plan_path: Path,
    validated: dict[str, Any],
    command: list[str],
    control_tmux: dict[str, str],
) -> dict[str, Any] | None:
    jobs_dir = eval_root / "submissions" / "jobs"
    if not jobs_dir.is_dir():
        return None
    paths = sorted(jobs_dir.glob("*.json"))
    if len(paths) > 1:
        raise ValueError("Multiple Gstar eval receipts exist")
    if not paths:
        return None
    receipt = _validate_receipt(
        paths[0],
        plan_sha256=plan_sha256,
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
    )
    return {**receipt, "receipt_path": str(paths[0])}


def submission_status(validated: dict[str, Any]) -> dict[str, Any]:
    eval_root = Path(validated["manifest"]["eval_root"])
    intent_path = eval_root / "submissions" / SUBMISSION_INTENT_NAME
    jobs_dir = eval_root / "submissions" / "jobs"
    receipt_paths = sorted(jobs_dir.glob("*.json")) if jobs_dir.is_dir() else []
    if not intent_path.exists():
        if receipt_paths:
            raise RuntimeError("Gstar eval receipt exists without its immutable submission intent")
        return {"state": "not_submitted", "submitted": False, "array_job_id": None}
    intent = base.read_json_object(intent_path)
    plan_record = intent.get("plan")
    if not isinstance(plan_record, dict) or not isinstance(plan_record.get("path"), str):
        raise ValueError("Gstar eval intent has no immutable plan identity")
    plan_path = Path(plan_record["path"])
    if base.file_identity(plan_path) != plan_record:
        raise ValueError("Gstar eval intent plan identity differs")
    plan = validate_submission_plan(plan_path, validated)
    payload = plan["plan"]
    command = submission_command(
        validated["manifest"],
        validated=validated,
        plan_path=plan_path,
        plan_sha256=plan["plan_sha256"],
        max_parallel=payload["max_parallel"],
        dependency=payload["dependency"],
    )
    control_tmux = {
        "socket": CONTROL_TMUX_SOCKET,
        "session": CONTROL_TMUX_SESSION,
        "window": CONTROL_TMUX_WINDOW,
    }
    expected_intent = submission_intent(
        plan_sha256=plan["plan_sha256"],
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
    )
    validate_submission_intent(intent_path, expected_intent)
    receipt = _existing_receipt(
        eval_root,
        plan_sha256=plan["plan_sha256"],
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
    )
    if receipt is None:
        return {"state": "intent_without_receipt", "submitted": False, "array_job_id": None}
    return {
        "state": "submitted",
        "submitted": True,
        "array_job_id": receipt["array_job_id"],
        "receipt_path": receipt["receipt_path"],
    }


def _reconcile_receipt(
    *,
    eval_root: Path,
    plan_sha256: str,
    plan_path: Path,
    validated: dict[str, Any],
    command: list[str],
    control_tmux: dict[str, str],
) -> dict[str, Any] | None:
    comment = submission_comment(validated, plan_sha256)
    matches, evidence = scheduler_matches(comment)
    if len(matches) > 1:
        raise RuntimeError(f"Gstar eval has multiple exact Slurm comment matches: {sorted(matches)}")
    if not matches:
        return None
    job_id = next(iter(matches))
    receipt = job_receipt(
        array_job_id=job_id,
        plan_sha256=plan_sha256,
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
        submission_source="scheduler_reconciliation",
        scheduler_evidence=evidence,
    )
    receipt_path = eval_root / "submissions" / "jobs" / f"{job_id}.json"
    base.write_json_once(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path)}


def submit(args: argparse.Namespace) -> dict[str, Any]:
    eval_root = args.eval_root.expanduser().resolve()
    validated = validate_eval_launch_manifest(eval_root / EVAL_LAUNCH_MANIFEST_NAME)
    manifest = validated["manifest"]
    readiness = base.checkpoint_readiness(manifest)
    placeholder = eval_root / "submissions" / "plans" / ("0" * 64 + ".json")
    dry_command = submission_command(
        manifest,
        validated=validated,
        plan_path=placeholder,
        plan_sha256="0" * 64,
        max_parallel=args.max_parallel,
        dependency=args.dependency,
    )
    if args.dry_run:
        return {
            "study_id": STUDY_ID,
            "evaluation_count": len(manifest["tasks"]),
            "checkpoint_readiness": readiness,
            "command_after_checkpoint_validation": shlex.join(dry_command),
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual submission requires --confirm-study-id {STUDY_ID}")
    control_tmux = base.require_control_tmux()
    plan, plan_sha256 = build_submission_plan(validated, max_parallel=args.max_parallel, dependency=args.dependency)
    plan_path = eval_root / "submissions" / "plans" / f"{plan_sha256}.json"
    command = submission_command(
        manifest,
        validated=validated,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        max_parallel=args.max_parallel,
        dependency=args.dependency,
    )
    submissions = eval_root / "submissions"
    submissions.mkdir(parents=True, exist_ok=True)
    with (submissions / SUBMISSION_LOCK_NAME).open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        base.write_json_once(plan_path, plan)
        validate_submission_plan(plan_path, validated)
        expected_intent = submission_intent(
            plan_sha256=plan_sha256,
            plan_path=plan_path,
            validated=validated,
            command=command,
            control_tmux=control_tmux,
        )
        intent_path = submissions / SUBMISSION_INTENT_NAME
        if intent_path.exists():
            validate_submission_intent(intent_path, expected_intent)
            receipt = _existing_receipt(
                eval_root,
                plan_sha256=plan_sha256,
                plan_path=plan_path,
                validated=validated,
                command=command,
                control_tmux=control_tmux,
            )
            if receipt:
                return {
                    "study_id": STUDY_ID,
                    "already_submitted": True,
                    "array_job_id": receipt["array_job_id"],
                    "receipt_path": receipt["receipt_path"],
                }
            receipt = _reconcile_receipt(
                eval_root=eval_root,
                plan_sha256=plan_sha256,
                plan_path=plan_path,
                validated=validated,
                command=command,
                control_tmux=control_tmux,
            )
            if receipt:
                return {
                    "study_id": STUDY_ID,
                    "already_submitted": True,
                    "reconciled": True,
                    "array_job_id": receipt["array_job_id"],
                    "receipt_path": receipt["receipt_path"],
                }
            raise RuntimeError(
                "Gstar eval intent exists without a receipt or exact scheduler match; retry reconcile later"
            )
        if _existing_receipt(
            eval_root,
            plan_sha256=plan_sha256,
            plan_path=plan_path,
            validated=validated,
            command=command,
            control_tmux=control_tmux,
        ):
            raise RuntimeError("Gstar eval receipt exists without its immutable intent")
        base.write_json_once(intent_path, expected_intent)
        (eval_root / "logs").mkdir(parents=True, exist_ok=True)
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        raw_output = result.stdout.strip()
        job_id = raw_output.split(";", maxsplit=1)[0]
        if not job_id.isdigit():
            raise ValueError(f"sbatch returned an invalid Gstar eval job ID: {result.stdout!r}")
        receipt = job_receipt(
            array_job_id=int(job_id),
            plan_sha256=plan_sha256,
            plan_path=plan_path,
            validated=validated,
            command=command,
            control_tmux=control_tmux,
            submission_source="sbatch_stdout",
            sbatch_stdout=raw_output,
        )
        receipt_path = eval_root / "submissions" / "jobs" / f"{job_id}.json"
        base.write_json_once(receipt_path, receipt)
        return {
            "study_id": STUDY_ID,
            "already_submitted": False,
            "array_job_id": int(job_id),
            "plan_sha256": plan_sha256,
            "receipt_path": str(receipt_path),
        }


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    eval_root = args.eval_root.expanduser().resolve()
    validated = validate_eval_launch_manifest(eval_root / EVAL_LAUNCH_MANIFEST_NAME)
    status = submission_status(validated)
    if args.dry_run:
        return {"study_id": STUDY_ID, "status": status, "scheduler_mutation": False}
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual reconciliation requires --confirm-study-id {STUDY_ID}")
    control_tmux = base.require_control_tmux()
    if status["state"] == "not_submitted":
        raise RuntimeError("Gstar eval has no submission intent to reconcile")
    if status["state"] == "submitted":
        return {"study_id": STUDY_ID, "status": status, "scheduler_mutation": False}
    submissions = eval_root / "submissions"
    with (submissions / SUBMISSION_LOCK_NAME).open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        intent = base.read_json_object(submissions / SUBMISSION_INTENT_NAME)
        if intent.get("control_tmux") != control_tmux:
            raise ValueError("Gstar eval submission intent belongs to a different control tmux")
        plan_path = Path(intent["plan"]["path"])
        plan = validate_submission_plan(plan_path, validated)
        payload = plan["plan"]
        command = submission_command(
            validated["manifest"],
            validated=validated,
            plan_path=plan_path,
            plan_sha256=plan["plan_sha256"],
            max_parallel=payload["max_parallel"],
            dependency=payload["dependency"],
        )
        expected_intent = submission_intent(
            plan_sha256=plan["plan_sha256"],
            plan_path=plan_path,
            validated=validated,
            command=command,
            control_tmux=control_tmux,
        )
        validate_submission_intent(submissions / SUBMISSION_INTENT_NAME, expected_intent)
        receipt = _reconcile_receipt(
            eval_root=eval_root,
            plan_sha256=plan["plan_sha256"],
            plan_path=plan_path,
            validated=validated,
            command=command,
            control_tmux=control_tmux,
        )
    return {
        "study_id": STUDY_ID,
        "reconciled": receipt is not None,
        "array_job_id": receipt["array_job_id"] if receipt else None,
        "scheduler_mutation": False,
        "status": submission_status(validated),
    }


def validate_runtime_submission(
    validated: dict[str, Any], validated_plan: dict[str, Any], *, array_job_id: int
) -> dict[str, Any]:
    manifest = validated["manifest"]
    eval_root = Path(manifest["eval_root"])
    plan_path = Path(validated_plan["path"])
    plan = validated_plan["plan"]
    command = submission_command(
        manifest,
        validated=validated,
        plan_path=plan_path,
        plan_sha256=validated_plan["plan_sha256"],
        max_parallel=plan["max_parallel"],
        dependency=plan["dependency"],
    )
    control_tmux = {
        "socket": CONTROL_TMUX_SOCKET,
        "session": CONTROL_TMUX_SESSION,
        "window": CONTROL_TMUX_WINDOW,
    }
    intent_path = eval_root / "submissions" / SUBMISSION_INTENT_NAME
    expected_intent = submission_intent(
        plan_sha256=validated_plan["plan_sha256"],
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
    )
    validate_submission_intent(intent_path, expected_intent)
    receipt_path = eval_root / "submissions" / "jobs" / f"{array_job_id}.json"
    receipt = _validate_receipt(
        receipt_path,
        plan_sha256=validated_plan["plan_sha256"],
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
    )
    if receipt["array_job_id"] != array_job_id:
        raise ValueError("Runtime Slurm array ID differs from the immutable Gstar eval receipt")
    return receipt


def _validated_task_inputs(
    *, eval_launch_manifest: Path, submission_plan: Path, task_index: int, array_job_id: int | None = None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_path = submission_plan.expanduser().resolve()
    plan = base.read_json_object(plan_path)
    plan_manifest = plan.get("eval_launch_manifest")
    if not isinstance(plan_manifest, dict) or not isinstance(plan_manifest.get("path"), str):
        raise ValueError("Gstar eval plan has no launch manifest identity")
    requested = eval_launch_manifest.expanduser().resolve()
    if requested != Path(plan_manifest["path"]).resolve() or base.file_identity(requested) != plan_manifest:
        raise ValueError("Runtime Gstar eval manifest differs from the plan")
    validated = validate_eval_launch_manifest(requested, runtime_task_index=task_index)
    validated_plan = validate_submission_plan(plan_path, validated, selected_task_index=task_index)
    if array_job_id is not None:
        validate_runtime_submission(validated, validated_plan, array_job_id=array_job_id)
    return validated, validated_plan, validated["manifest"]["tasks"][task_index]


def validate_task(args: argparse.Namespace) -> dict[str, Any]:
    validated, plan, task = _validated_task_inputs(
        eval_launch_manifest=args.eval_launch_manifest,
        submission_plan=args.submission_plan,
        task_index=args.task_index,
    )
    return {
        "study_id": STUDY_ID,
        "task_index": args.task_index,
        "eval_id": task["eval_id"],
        "eval_config": task["eval_config"]["path"],
        "eval_launch_manifest_sha256": validated["manifest_sha256"],
        "submission_plan_sha256": plan["plan_sha256"],
        "checkpoint_inventory_sha256": plan["plan"]["tasks"][args.task_index]["checkpoint"]["inventory_sha256"],
    }


def prepare_task(args: argparse.Namespace) -> dict[str, Any]:
    validated, plan, task = _validated_task_inputs(
        eval_launch_manifest=args.eval_launch_manifest,
        submission_plan=args.submission_plan,
        task_index=args.task_index,
        array_job_id=args.array_job_id,
    )
    manifest = validated["manifest"]
    eval_root = Path(manifest["eval_root"])
    source_root = Path(manifest["source"]["snapshot_path"])
    inference_path, eval_path = base.runtime_config_paths(
        eval_root, array_job_id=args.array_job_id, task_index=args.task_index
    )
    inference, evaluation = base.build_runtime_config_pair(
        task,
        task_index=args.task_index,
        array_job_id=args.array_job_id,
        eval_root=eval_root,
        source_root=source_root,
    )
    base.write_toml_once(inference_path, inference)
    base.write_toml_once(eval_path, evaluation)
    if base.read_toml(inference_path) != inference or base.read_toml(eval_path) != evaluation:
        raise ValueError("Gstar runtime configs differ after materialization")
    runtime_record = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "array_job_id": args.array_job_id,
        "task_index": args.task_index,
        "eval_id": task["eval_id"],
        "transport_port": base.runtime_port(args.array_job_id, args.task_index),
        "eval_launch_manifest": base.file_identity(Path(validated["manifest_path"])),
        "submission_plan": base.file_identity(Path(plan["path"])),
        "submission_plan_sha256": plan["plan_sha256"],
        "base_inference_config": task["inference_config"],
        "base_eval_config": task["eval_config"],
        "runtime_inference_config": base.file_identity(inference_path),
        "runtime_eval_config": base.file_identity(eval_path),
        "checkpoint_inventory_sha256": plan["plan"]["tasks"][args.task_index]["checkpoint"]["inventory_sha256"],
    }
    runtime_manifest = eval_path.parent / "runtime_manifest.json"
    base.write_json_once(runtime_manifest, runtime_record)
    return {
        "study_id": STUDY_ID,
        "task_index": args.task_index,
        "eval_id": task["eval_id"],
        "eval_config": str(eval_path),
        "runtime_manifest": str(runtime_manifest),
        "transport_port": runtime_record["transport_port"],
    }


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        result = materialize(args)
    elif args.command == "validate":
        validated = validate_eval_launch_manifest(args.eval_root / EVAL_LAUNCH_MANIFEST_NAME)
        result = {
            "study_id": STUDY_ID,
            "manifest_path": validated["manifest_path"],
            "manifest_sha256": validated["manifest_sha256"],
            "evaluation_count": len(validated["manifest"]["tasks"]),
        }
    elif args.command == "validate-task":
        result = validate_task(args)
        if args.print_config:
            print(result["eval_config"])
            return
    elif args.command == "prepare-task":
        result = prepare_task(args)
        if args.print_config:
            print(result["eval_config"])
            return
    elif args.command == "submit":
        result = submit(args)
    elif args.command == "reconcile":
        result = reconcile(args)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
