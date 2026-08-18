#!/usr/bin/env python3
"""Materialize and guard strict OP11-45 evaluations for fixed-clock SFT readouts."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w
from prepare_rl_checkpoint_eval import DATA_SOURCES

TRAINING_STUDY_ID = "verifier_defect_fixed_clock_sft_v2"
STUDY_ID = "verifier_defect_fixed_clock_sft_eval_v1"
SCHEMA_VERSION = 1
EXPECTED_TRAINING_ARMS = 55
EXPECTED_COMMON_EVALUATIONS = 55
EXPECTED_FINAL_EVALUATIONS = 27
EXPECTED_EVALUATIONS = EXPECTED_COMMON_EVALUATIONS + EXPECTED_FINAL_EVALUATIONS
COMMON_STEP = 64
OPERATIONS = tuple(range(11, 46))
EXAMPLES_PER_OPERATION = 200
EXPECTED_PROMPTS = len(OPERATIONS) * EXAMPLES_PER_OPERATION
SAMPLES_PER_PROMPT = 1
DEFAULT_MAX_PARALLEL = 8
PORT_BASE = 20_000
PORT_SPAN = 20_000
SHA256_RE = re.compile(r"[0-9a-f]{64}")
DEPENDENCY_RE = re.compile(r"[A-Za-z0-9_:+?,-]+")

DEFAULT_TRAINING_LAUNCH_MANIFEST = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/sft/verifier-defect-fixed-clock-v2/launch_manifest.json"
)
DEFAULT_EVAL_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-fixed-clock-sft-v1")
EVAL_LAUNCH_MANIFEST_NAME = "eval_launch_manifest.json"
SUBMISSION_INTENT_NAME = "submission_intent.json"
SUBMISSION_LOCK_NAME = "submission.lock"

SANITIZED_SBATCH_ENV_VARS = (
    "SBATCH_ACCOUNT",
    "SBATCH_ARRAY_INX",
    "SBATCH_CPUS_PER_TASK",
    "SBATCH_DEPENDENCY",
    "SBATCH_ERROR",
    "SBATCH_EXCLUSIVE",
    "SBATCH_GPUS",
    "SBATCH_GPUS_PER_NODE",
    "SBATCH_GPUS_PER_TASK",
    "SBATCH_GRES",
    "SBATCH_MEM",
    "SBATCH_MEM_PER_CPU",
    "SBATCH_MEM_PER_GPU",
    "SBATCH_MEM_PER_NODE",
    "SBATCH_NODES",
    "SBATCH_NTASKS",
    "SBATCH_NTASKS_PER_NODE",
    "SBATCH_OUTPUT",
    "SBATCH_OVERSUBSCRIBE",
    "SBATCH_PARTITION",
    "SBATCH_QOS",
    "SBATCH_TIME",
    "SBATCH_TIMELIMIT",
)

SCRIPT_REPO_PATH = Path("user/tianhaowu/rsci/materialize_fixed_clock_sft_evals.py")
TEMPLATE_REPO_PATH = Path("user/tianhaowu/rsci/templates/fixed_clock_sft_eval_array.sbatch")
ACTIVATOR_REPO_PATH = Path("user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh")
RUN_EVAL_REPO_PATH = Path("user/tianhaowu/rsci/scripts/run_eval.sh")
SCORER_REPO_PATH = Path("user/tianhaowu/rsci/figure3_eval.py")
SOLUTION_GRAPH_REPO_PATH = Path("user/tianhaowu/rsci/solution_graph.py")
PREPARE_REPO_PATH = Path("user/tianhaowu/rsci/prepare_rl_checkpoint_eval.py")

CONTROL_TMUX_SOCKET = "/tmp/codex-rsci-control-20260806.sock"
CONTROL_TMUX_SESSION = "codex-rsci-control-20260806"
CONTROL_TMUX_WINDOW = "Launcher"

EVALUATION_CONTRACT = {
    "target": "clean released-strict dependency-graph correctness",
    "operations": list(OPERATIONS),
    "examples_per_operation": EXAMPLES_PER_OPERATION,
    "samples_per_prompt": SAMPLES_PER_PROMPT,
    "pass_at": [1],
    "expected_prompts_per_evaluation": EXPECTED_PROMPTS,
    "max_tokens": 2_048,
    "temperature": 0.7,
    "top_p": 1.0,
    "top_k": -1,
    "request_seed": 20260807,
    "stop": ["</answer>"],
    "skip_special_tokens": False,
    "scorer": "figure3_eval.py deterministic released dependency-graph scorer",
    "reward_channel": "none; evaluation never invokes training proxy or verifier-defect reward",
    "readouts": "step 64 for every canonical training arm and its declared distinct final step when >64",
    "gpu_count_per_task": 1,
    "exclusive_node": False,
    "max_parallel_cap": DEFAULT_MAX_PARALLEL,
    "transport_port": "derived at runtime from Slurm array job ID and task index",
    "submission_guard": "one immutable intent per evaluation launch manifest",
}


@dataclass(frozen=True)
class SourceState:
    run_dir: Path
    root: Path
    provenance: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize = subparsers.add_parser("materialize")
    materialize.add_argument(
        "--training-launch-manifest",
        type=Path,
        default=DEFAULT_TRAINING_LAUNCH_MANIFEST,
    )
    materialize.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    materialize.add_argument("--source-run-dir", type=Path)
    materialize.add_argument("--dry-run", action="store_true")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)

    validate_task_parser = subparsers.add_parser("validate-task")
    validate_task_parser.add_argument("--eval-launch-manifest", type=Path, required=True)
    validate_task_parser.add_argument("--submission-plan", type=Path, required=True)
    validate_task_parser.add_argument("--task-index", type=int, required=True)
    validate_task_parser.add_argument("--print-config", action="store_true")

    prepare_task_parser = subparsers.add_parser("prepare-task")
    prepare_task_parser.add_argument("--eval-launch-manifest", type=Path, required=True)
    prepare_task_parser.add_argument("--submission-plan", type=Path, required=True)
    prepare_task_parser.add_argument("--task-index", type=int, required=True)
    prepare_task_parser.add_argument("--array-job-id", type=int, required=True)
    prepare_task_parser.add_argument("--print-config", action="store_true")

    submit = subparsers.add_parser("submit")
    submit.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    submit.add_argument("--max-parallel", type=int, default=DEFAULT_MAX_PARALLEL)
    submit.add_argument("--dependency")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--confirm-study-id")
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    configured = path.expanduser()
    if not configured.is_absolute():
        raise ValueError(f"Input file path must be absolute: {configured}")
    resolved = configured.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(configured),
        "resolved_path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def checkpoint_identity(path: Path) -> dict[str, Any]:
    configured = path.expanduser()
    if not configured.is_absolute():
        raise ValueError(f"Checkpoint path must be absolute: {configured}")
    resolved = configured.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    if not (resolved / "STABLE").is_file():
        raise ValueError(f"Checkpoint has no STABLE marker: {resolved}")
    if not (resolved / "config.json").is_file():
        raise ValueError(f"Checkpoint has no config.json: {resolved}")
    files = sorted(path for path in resolved.rglob("*") if path.is_file())
    if not any(path.suffix == ".safetensors" for path in files):
        raise ValueError(f"Checkpoint has no safetensors weights: {resolved}")
    if any(path.is_symlink() for path in files):
        raise ValueError(f"Checkpoint contains a symlink: {resolved}")
    inventory = [
        {
            "path": path.relative_to(resolved).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }
        for path in files
    ]
    return {
        "path": str(configured),
        "resolved_path": str(resolved),
        "file_count": len(inventory),
        "size_bytes": sum(item["size_bytes"] for item in inventory),
        "inventory": inventory,
        "inventory_sha256": canonical_json_sha256(inventory),
    }


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as handle:
        return tomllib.load(handle)


def write_json_once(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if not path.is_file() or path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"Refusing to replace a different immutable JSON artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(encoded, encoding="utf-8")
    partial.replace(path)


def write_toml_once(path: Path, payload: dict[str, Any]) -> None:
    encoded = tomli_w.dumps(payload).encode()
    if path.exists():
        if not path.is_file() or path.read_bytes() != encoded:
            raise ValueError(f"Refusing to replace a different immutable TOML config: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(encoded)
    partial.replace(path)


def _verify_file_identity(identity: object, label: str) -> dict[str, Any]:
    if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
        raise ValueError(f"{label} has no file identity")
    current = file_identity(Path(identity["path"]))
    if current != identity:
        raise ValueError(f"{label} identity differs")
    return current


def _validate_dependency(dependency: str | None) -> None:
    if dependency is not None and DEPENDENCY_RE.fullmatch(dependency) is None:
        raise ValueError(f"Invalid Slurm dependency expression: {dependency!r}")


def _validate_max_parallel(max_parallel: int) -> None:
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int):
        raise ValueError("max_parallel must be an integer")
    if not 1 <= max_parallel <= DEFAULT_MAX_PARALLEL:
        raise ValueError(f"max_parallel must be in [1, {DEFAULT_MAX_PARALLEL}]")


def active_source_state(source_run_dir: Path) -> SourceState:
    source_run_dir = source_run_dir.expanduser().resolve()
    from source_provenance import verify_snapshot

    provenance = verify_snapshot(source_run_dir, require_launch=False)
    source_root = Path(provenance["snapshot_path"]).resolve()
    if Path(__file__).resolve() != (source_root / SCRIPT_REPO_PATH).resolve():
        raise ValueError(
            "Evaluation materialization must run from the pinned source snapshot; source "
            f"{source_root / ACTIVATOR_REPO_PATH} first"
        )
    if os.environ.get("RSCI_SOURCE_SNAPSHOT") != str(source_root):
        raise ValueError("Pinned evaluation source activation is missing from the current environment")
    required = (
        TEMPLATE_REPO_PATH,
        ACTIVATOR_REPO_PATH,
        RUN_EVAL_REPO_PATH,
        SCORER_REPO_PATH,
        SOLUTION_GRAPH_REPO_PATH,
        PREPARE_REPO_PATH,
    )
    for relative in required:
        if not (source_root / relative).is_file():
            raise FileNotFoundError(source_root / relative)
    return SourceState(source_run_dir, source_root, provenance)


def validate_template(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    required = (
        "#SBATCH --nodes=1",
        "#SBATCH --gres=gpu:1",
        "#SBATCH --cpus-per-task=16",
        "#SBATCH --mem=64G",
        "#SBATCH --time=04:00:00",
        "prepare-task",
        "--array-job-id",
        "activate_source_snapshot_eval.sh",
        "user/tianhaowu/rsci/scripts/run_eval.sh",
    )
    for value in required:
        if value not in text:
            raise ValueError(f"Evaluation array template lacks required text {value!r}: {path}")
    if "--exclusive" in text:
        raise ValueError(f"Evaluation array template requests an exclusive node: {path}")


def validate_training_launch_manifest(path: Path) -> dict[str, Any]:
    from materialize_fixed_clock_sft_runs import validate_launch_manifest

    return validate_launch_manifest(path)


def discover_evaluations(training_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if training_manifest.get("study_id") != TRAINING_STUDY_ID:
        raise ValueError("Training launch manifest has the wrong study identity")
    arms = training_manifest.get("arms")
    if not isinstance(arms, list) or len(arms) != EXPECTED_TRAINING_ARMS:
        raise ValueError(f"Training launch manifest must contain {EXPECTED_TRAINING_ARMS} canonical arms")
    labels = [arm.get("label") for arm in arms if isinstance(arm, dict)]
    if len(labels) != len(arms) or labels != sorted(labels) or len(set(labels)) != len(labels):
        raise ValueError("Training arm labels are missing, duplicated, or unsorted")
    launch_root = Path(str(training_manifest.get("launch_root", ""))).expanduser().resolve()
    tasks: list[dict[str, Any]] = []
    for arm in arms:
        label = arm["label"]
        output_dir = Path(str(arm.get("output_dir", ""))).expanduser().resolve()
        if output_dir != launch_root / "runs" / label:
            raise ValueError(f"Training output path differs for arm {label}")
        max_steps = arm.get("max_steps")
        readouts = arm.get("readout_steps")
        checkpoints = arm.get("checkpoint_steps")
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < COMMON_STEP:
            raise ValueError(f"Training arm {label} has invalid max_steps")
        expected_readouts = [COMMON_STEP] if max_steps == COMMON_STEP else [COMMON_STEP, max_steps]
        if readouts != expected_readouts:
            raise ValueError(
                f"Training arm {label} readouts {readouts!r} differ from the declared common/final contract "
                f"{expected_readouts!r}"
            )
        if not isinstance(checkpoints, list) or any(step not in checkpoints for step in expected_readouts):
            raise ValueError(f"Training arm {label} does not retain every declared readout checkpoint")
        for step in expected_readouts:
            task = {
                "eval_id": f"{label}__step_{step}",
                "arm_label": label,
                "step": step,
                "readout": "common" if step == COMMON_STEP else "final",
                "model_path": str(output_dir / "weights" / f"step_{step}"),
                "training_output_dir": str(output_dir),
                "training_resolved_config": arm.get("resolved_config"),
                "training_sbatch": arm.get("sbatch"),
                "arm_contract_sha256": canonical_json_sha256(
                    {
                        "label": label,
                        "metadata": arm.get("metadata"),
                        "rows": arm.get("rows"),
                        "schedule": arm.get("schedule"),
                        "max_steps": max_steps,
                        "checkpoint_steps": checkpoints,
                        "readout_steps": readouts,
                    }
                ),
            }
            tasks.append(task)
    tasks.sort(key=lambda task: (task["arm_label"], task["step"]))
    for task_index, task in enumerate(tasks):
        task["task_index"] = task_index
    common_count = sum(task["readout"] == "common" for task in tasks)
    final_count = sum(task["readout"] == "final" for task in tasks)
    if (len(tasks), common_count, final_count) != (
        EXPECTED_EVALUATIONS,
        EXPECTED_COMMON_EVALUATIONS,
        EXPECTED_FINAL_EVALUATIONS,
    ):
        raise ValueError(
            "Declared evaluation grid differs: "
            f"tasks/common/final={(len(tasks), common_count, final_count)!r}, expected "
            f"{(EXPECTED_EVALUATIONS, EXPECTED_COMMON_EVALUATIONS, EXPECTED_FINAL_EVALUATIONS)!r}"
        )
    return tasks


def evaluation_input_state() -> dict[str, Any]:
    from figure3_eval import compose_prompt, data_dirs_by_operation, load_rows

    eval_fields = {
        "data_sources": copy.deepcopy(DATA_SOURCES),
        "operations": list(OPERATIONS),
        "examples_per_operation": EXAMPLES_PER_OPERATION,
    }
    rows, hashes = load_rows(eval_fields)
    if len(rows) != EXPECTED_PROMPTS:
        raise ValueError(f"Held-out prompt count differs: {len(rows)} != {EXPECTED_PROMPTS}")
    data_dirs = data_dirs_by_operation(eval_fields)
    datasets = []
    for operation in OPERATIONS:
        path = (data_dirs[operation] / f"op{operation}-{EXAMPLES_PER_OPERATION}.jsonl").expanduser().resolve()
        identity = file_identity(path)
        if identity["sha256"] != hashes[str(operation)]:
            raise RuntimeError(f"Dataset hash changed while loading OP{operation}")
        datasets.append({"operation": operation, **identity})
    prompt_sequence = [
        {
            "operation": int(row["op"]),
            "index": int(row["__idx"]),
            "id": str(row["id"]),
            "prompt_sha256": hashlib.sha256(compose_prompt(row).encode()).hexdigest(),
        }
        for row in rows
    ]
    return {
        "data_sources": copy.deepcopy(DATA_SOURCES),
        "datasets": datasets,
        "prompt_count": len(rows),
        "prompt_sequence_sha256": canonical_json_sha256(prompt_sequence),
    }


def build_config_pair(
    task: dict[str, Any],
    *,
    task_index: int,
    eval_root: Path,
    source_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if task.get("task_index") != task_index:
        raise ValueError(f"Task index mismatch: {task.get('task_index')!r} != {task_index}")
    port = PORT_BASE + task_index
    if not 1 <= port <= 65535:
        raise ValueError(f"Derived inference port is invalid: {port}")
    output_dir = eval_root / "results" / task["arm_label"] / f"step_{task['step']}"
    config_dir = eval_root / "configs" / task["eval_id"]
    inference_path = config_dir / "inference.toml"
    model_path = task["model_path"]
    inference = {
        "output_dir": str(output_dir / "deployment"),
        "gpu_memory_utilization": 0.8,
        "enable_prefix_caching": True,
        "enable_fp32_lm_head": True,
        "api_server_count": 1,
        "data_parallel_size_local": 1,
        "seed": 0,
        "server": {
            "host": "0.0.0.0",
            "port": port,
            "liveness_timeout_seconds": 30.0,
        },
        "model": {
            "name": model_path,
            "dtype": "auto",
            "max_model_len": 2_048,
            "enforce_eager": False,
            "trust_remote_code": False,
            "tool_call_parser": "None",
            "reasoning_parser": "None",
        },
        "parallel": {"tp": 1, "dp": 1},
        "deployment": {"type": "single_node", "gpus_per_node": 1},
        "vllm_extra": {"max_num_seqs": 256},
        "log": {
            "level": "info",
            "vf_level": "info",
            "json_logging": False,
            "log_data": False,
            "interval": 10.0,
        },
    }
    evaluation = {
        "infer_config": str(inference_path),
        "evaluator": str(source_root / SCORER_REPO_PATH),
        "eval": {
            "data_sources": copy.deepcopy(DATA_SOURCES),
            "operations": list(OPERATIONS),
            "examples_per_operation": EXAMPLES_PER_OPERATION,
            "output_dir": str(output_dir),
            "model": model_path,
            "api_base_url": f"http://127.0.0.1:{port}/v1",
            "samples_per_prompt": SAMPLES_PER_PROMPT,
            "pass_at": [1],
            "max_tokens": 2_048,
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "request_seed": 20260807,
            "stop": ["</answer>"],
            "skip_special_tokens": False,
            "request_timeout_seconds": 3_600.0,
            "max_concurrent_prompts": 128,
            "max_retries": 2,
            "overwrite": False,
        },
    }
    return inference, evaluation


def runtime_port(array_job_id: int, task_index: int) -> int:
    if isinstance(array_job_id, bool) or not isinstance(array_job_id, int) or array_job_id < 1:
        raise ValueError("array_job_id must be a positive integer")
    if isinstance(task_index, bool) or not isinstance(task_index, int) or task_index < 0:
        raise ValueError("task_index must be a non-negative integer")
    return PORT_BASE + (array_job_id * 37 + task_index) % PORT_SPAN


def runtime_config_paths(eval_root: Path, *, array_job_id: int, task_index: int) -> tuple[Path, Path]:
    runtime_dir = eval_root / "runtime" / f"job_{array_job_id}" / f"task_{task_index}"
    return runtime_dir / "inference.toml", runtime_dir / "eval.toml"


def build_runtime_config_pair(
    task: dict[str, Any],
    *,
    task_index: int,
    array_job_id: int,
    eval_root: Path,
    source_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    inference, evaluation = build_config_pair(
        task,
        task_index=task_index,
        eval_root=eval_root,
        source_root=source_root,
    )
    inference_path, _ = runtime_config_paths(
        eval_root,
        array_job_id=array_job_id,
        task_index=task_index,
    )
    port = runtime_port(array_job_id, task_index)
    inference["server"]["port"] = port
    evaluation["infer_config"] = str(inference_path)
    evaluation["eval"]["api_base_url"] = f"http://127.0.0.1:{port}/v1"
    return inference, evaluation


def validate_config_pair(
    task: dict[str, Any],
    *,
    task_index: int,
    eval_root: Path,
    source_root: Path,
    inference_path: Path,
    eval_path: Path,
) -> None:
    expected_inference, expected_eval = build_config_pair(
        task,
        task_index=task_index,
        eval_root=eval_root,
        source_root=source_root,
    )
    if read_toml(inference_path) != expected_inference:
        raise ValueError(f"Inference config differs from the strict evaluation contract: {inference_path}")
    if read_toml(eval_path) != expected_eval:
        raise ValueError(f"Eval config differs from the strict evaluation contract: {eval_path}")
    from figure3_eval import load_config

    loaded = load_config(eval_path)
    eval_config = loaded["eval"]
    if eval_config["samples_per_prompt"] != 1 or eval_config["pass_at"] != [1]:
        raise ValueError(f"Evaluation is not pass@1: {eval_path}")
    forbidden_keys = {"reward", "proxy_reward", "defect", "false_positive_rate", "false_negative_rate"}
    if forbidden_keys & set(eval_config):
        raise ValueError(f"Evaluation config contains a training reward field: {eval_path}")


def _source_record(source: SourceState) -> dict[str, Any]:
    return {
        "run_dir": str(source.run_dir),
        "snapshot_path": str(source.root),
        "parent_commit_sha": source.provenance["parent_commit_sha"],
        "source_tree_sha256": source.provenance["source_tree_sha256"],
        "provenance_manifest": file_identity(source.run_dir / "source_provenance.json"),
    }


def validate_existing_training_identity(
    existing_manifest: dict[str, Any],
    *,
    requested_identity: dict[str, Any],
    requested_sha256: str,
) -> None:
    if (
        existing_manifest.get("training_launch_manifest") != requested_identity
        or existing_manifest.get("training_launch_manifest_sha256") != requested_sha256
    ):
        raise ValueError("Existing evaluation root belongs to a different training launch manifest")


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    eval_root = args.eval_root.expanduser().resolve()
    source_run_dir = (args.source_run_dir or eval_root).expanduser().resolve()
    source = active_source_state(source_run_dir)
    training = validate_training_launch_manifest(args.training_launch_manifest.expanduser().resolve())
    training_manifest = training["manifest"]
    tasks = discover_evaluations(training_manifest)
    inputs = evaluation_input_state()
    plan = {
        "study_id": STUDY_ID,
        "eval_root": str(eval_root),
        "training_arms": len(training_manifest["arms"]),
        "evaluation_count": len(tasks),
        "common_step_evaluations": sum(task["readout"] == "common" for task in tasks),
        "distinct_final_evaluations": sum(task["readout"] == "final" for task in tasks),
        "prompts_per_evaluation": EXPECTED_PROMPTS,
        "total_generations": len(tasks) * EXPECTED_PROMPTS,
        "gpus_per_task": 1,
        "default_max_parallel": DEFAULT_MAX_PARALLEL,
    }
    if args.dry_run:
        return plan
    if source.root.parent != source.run_dir or eval_root != source.run_dir:
        raise ValueError("The evaluation source snapshot must be rooted at eval_root/source_snapshot")
    manifest_path = eval_root / EVAL_LAUNCH_MANIFEST_NAME
    if manifest_path.exists():
        validated = validate_eval_launch_manifest(manifest_path)
        requested_training_identity = file_identity(Path(training["manifest_path"]))
        validate_existing_training_identity(
            validated["manifest"],
            requested_identity=requested_training_identity,
            requested_sha256=training["manifest_sha256"],
        )
        return {**plan, "manifest_sha256": validated["manifest_sha256"], "already_materialized": True}

    eval_root.mkdir(parents=True, exist_ok=True)
    task_records = []
    for task in tasks:
        task_index = task["task_index"]
        config_dir = eval_root / "configs" / task["eval_id"]
        inference_path = config_dir / "inference.toml"
        eval_path = config_dir / "eval.toml"
        inference, evaluation = build_config_pair(
            task,
            task_index=task_index,
            eval_root=eval_root,
            source_root=source.root,
        )
        write_toml_once(inference_path, inference)
        write_toml_once(eval_path, evaluation)
        validate_config_pair(
            task,
            task_index=task_index,
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
                "inference_config": file_identity(inference_path),
                "eval_config": file_identity(eval_path),
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "eval_root": str(eval_root),
        "source": _source_record(source),
        "training_launch_manifest": file_identity(Path(training["manifest_path"])),
        "training_launch_manifest_sha256": training["manifest_sha256"],
        "evaluation_contract": EVALUATION_CONTRACT,
        "evaluation_inputs": inputs,
        "implementation": file_identity(source.root / SCRIPT_REPO_PATH),
        "array_template": file_identity(source.root / TEMPLATE_REPO_PATH),
        "activator": file_identity(source.root / ACTIVATOR_REPO_PATH),
        "run_eval": file_identity(source.root / RUN_EVAL_REPO_PATH),
        "scorer": file_identity(source.root / SCORER_REPO_PATH),
        "solution_graph": file_identity(source.root / SOLUTION_GRAPH_REPO_PATH),
        "prepare_reference": file_identity(source.root / PREPARE_REPO_PATH),
        "training_arm_count": len(training_manifest["arms"]),
        "evaluation_count": len(task_records),
        "common_step_evaluation_count": sum(task["readout"] == "common" for task in task_records),
        "distinct_final_evaluation_count": sum(task["readout"] == "final" for task in task_records),
        "tasks": task_records,
    }
    write_json_once(manifest_path, manifest)
    validated = validate_eval_launch_manifest(manifest_path)
    return {**plan, "manifest_sha256": validated["manifest_sha256"], "already_materialized": False}


def _validate_source_record(source: object) -> SourceState:
    if not isinstance(source, dict):
        raise ValueError("Evaluation launch manifest has no source record")
    run_dir = Path(str(source.get("run_dir", ""))).expanduser().resolve()
    from source_provenance import verify_snapshot

    provenance = verify_snapshot(run_dir, require_launch=False)
    root = Path(provenance["snapshot_path"]).resolve()
    expected = {
        "run_dir": str(run_dir),
        "snapshot_path": str(root),
        "parent_commit_sha": provenance["parent_commit_sha"],
        "source_tree_sha256": provenance["source_tree_sha256"],
        "provenance_manifest": file_identity(run_dir / "source_provenance.json"),
    }
    if source != expected:
        raise ValueError("Evaluation source record differs from pinned provenance")
    return SourceState(run_dir, root, provenance)


def _validate_manifest_header(manifest_path: Path) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    manifest = read_json_object(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("study_id") != STUDY_ID:
        raise ValueError("Evaluation launch manifest has the wrong schema or study identity")
    eval_root = Path(str(manifest.get("eval_root", ""))).expanduser().resolve()
    if manifest_path.resolve() != eval_root / EVAL_LAUNCH_MANIFEST_NAME:
        raise ValueError("Evaluation launch manifest is not at its recorded root")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or manifest.get("evaluation_count") != len(tasks):
        raise ValueError("Evaluation launch manifest has an invalid task list")
    if len(tasks) != EXPECTED_EVALUATIONS:
        raise ValueError(f"Evaluation launch manifest must contain {EXPECTED_EVALUATIONS} tasks")
    if [task.get("task_index") for task in tasks if isinstance(task, dict)] != list(range(len(tasks))):
        raise ValueError("Evaluation task indices are not contiguous and ordered")
    eval_ids = [task.get("eval_id") for task in tasks]
    if len(set(eval_ids)) != len(tasks) or any(not isinstance(eval_id, str) for eval_id in eval_ids):
        raise ValueError("Evaluation task IDs are missing or duplicated")
    if manifest.get("evaluation_contract") != EVALUATION_CONTRACT:
        raise ValueError("Evaluation scientific contract differs")
    expected_counts = {
        "training_arm_count": EXPECTED_TRAINING_ARMS,
        "evaluation_count": EXPECTED_EVALUATIONS,
        "common_step_evaluation_count": EXPECTED_COMMON_EVALUATIONS,
        "distinct_final_evaluation_count": EXPECTED_FINAL_EVALUATIONS,
    }
    for field, expected in expected_counts.items():
        if manifest.get(field) != expected:
            raise ValueError(f"Evaluation launch manifest {field} differs: {manifest.get(field)!r}")
    return manifest, eval_root, tasks


def _validate_shared_inputs(manifest: dict[str, Any], source: SourceState) -> None:
    for field in (
        "implementation",
        "array_template",
        "activator",
        "run_eval",
        "scorer",
        "solution_graph",
        "prepare_reference",
        "training_launch_manifest",
    ):
        _verify_file_identity(manifest.get(field), field)
    expected_paths = {
        "implementation": source.root / SCRIPT_REPO_PATH,
        "array_template": source.root / TEMPLATE_REPO_PATH,
        "activator": source.root / ACTIVATOR_REPO_PATH,
        "run_eval": source.root / RUN_EVAL_REPO_PATH,
        "scorer": source.root / SCORER_REPO_PATH,
        "solution_graph": source.root / SOLUTION_GRAPH_REPO_PATH,
        "prepare_reference": source.root / PREPARE_REPO_PATH,
    }
    for field, expected in expected_paths.items():
        if Path(manifest[field]["path"]).resolve() != expected.resolve():
            raise ValueError(f"Evaluation launch manifest {field} path differs")
    validate_template(Path(manifest["array_template"]["path"]))
    current_inputs = evaluation_input_state()
    if manifest.get("evaluation_inputs") != current_inputs:
        raise ValueError("Held-out OP11-45 prompt inputs changed after materialization")


def validate_eval_launch_manifest(manifest_path: Path, *, runtime_task_index: int | None = None) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest, eval_root, tasks = _validate_manifest_header(manifest_path)
    source = _validate_source_record(manifest.get("source"))
    _validate_shared_inputs(manifest, source)
    training_identity = manifest["training_launch_manifest"]
    if manifest.get("training_launch_manifest_sha256") != training_identity["sha256"]:
        raise ValueError("Training launch manifest hash fields disagree")

    if runtime_task_index is None:
        training = validate_training_launch_manifest(Path(training_identity["path"]))
        if training["manifest_sha256"] != manifest["training_launch_manifest_sha256"]:
            raise ValueError("Training launch manifest changed after evaluator materialization")
        discovered = discover_evaluations(training["manifest"])
        selected_indices = range(len(tasks))
    else:
        if not 0 <= runtime_task_index < len(tasks):
            raise ValueError(f"Task index is outside [0, {len(tasks)}): {runtime_task_index}")
        discovered = None
        selected_indices = (runtime_task_index,)

    for index in selected_indices:
        task = tasks[index]
        if discovered is not None:
            scientific_fields = set(discovered[index])
            if {field: task.get(field) for field in scientific_fields} != discovered[index]:
                raise ValueError(f"Evaluation task {index} differs from the training readout declaration")
        for field in ("training_resolved_config", "training_sbatch", "inference_config", "eval_config"):
            _verify_file_identity(task.get(field), f"tasks.{index}.{field}")
        validate_config_pair(
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
        "manifest_sha256": file_sha256(manifest_path),
    }


def checkpoint_readiness(manifest: dict[str, Any]) -> dict[str, int]:
    stable = 0
    missing = 0
    for task in manifest["tasks"]:
        model_path = Path(task["model_path"])
        if model_path.is_dir() and (model_path / "STABLE").is_file():
            stable += 1
        else:
            missing += 1
    return {"stable": stable, "missing": missing}


def build_submission_plan(
    validated: dict[str, Any],
    *,
    max_parallel: int,
    dependency: str | None,
) -> tuple[dict[str, Any], str]:
    _validate_max_parallel(max_parallel)
    _validate_dependency(dependency)
    manifest = validated["manifest"]
    tasks = []
    for task in manifest["tasks"]:
        tasks.append(
            {
                "task_index": task["task_index"],
                "eval_id": task["eval_id"],
                "arm_label": task["arm_label"],
                "step": task["step"],
                "eval_config_sha256": task["eval_config"]["sha256"],
                "checkpoint": checkpoint_identity(Path(task["model_path"])),
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "eval_launch_manifest": file_identity(Path(validated["manifest_path"])),
        "max_parallel": max_parallel,
        "dependency": dependency,
        "array_spec": f"0-{len(tasks) - 1}%{max_parallel}",
        "task_count": len(tasks),
        "tasks": tasks,
    }
    return payload, canonical_json_sha256(payload)


def validate_submission_plan(
    path: Path,
    validated: dict[str, Any],
    *,
    selected_task_index: int | None = None,
) -> dict[str, Any]:
    path = path.expanduser().resolve()
    plan = read_json_object(path)
    plan_sha256 = canonical_json_sha256(plan)
    if path.stem != plan_sha256 or SHA256_RE.fullmatch(path.stem) is None:
        raise ValueError("Submission plan filename does not match its canonical SHA-256")
    if plan.get("schema_version") != SCHEMA_VERSION or plan.get("study_id") != STUDY_ID:
        raise ValueError("Submission plan has the wrong schema or study identity")
    if plan.get("eval_launch_manifest") != file_identity(Path(validated["manifest_path"])):
        raise ValueError("Submission plan belongs to a different evaluation launch manifest")
    tasks = plan.get("tasks")
    manifest_tasks = validated["manifest"]["tasks"]
    if not isinstance(tasks, list) or plan.get("task_count") != len(tasks) or len(tasks) != len(manifest_tasks):
        raise ValueError("Submission plan has an invalid task list")
    max_parallel = plan.get("max_parallel")
    _validate_max_parallel(max_parallel)
    dependency = plan.get("dependency")
    if dependency is not None and not isinstance(dependency, str):
        raise ValueError("Submission plan dependency must be a string or null")
    _validate_dependency(dependency)
    expected_array = f"0-{len(tasks) - 1}%{max_parallel}"
    if plan.get("array_spec") != expected_array:
        raise ValueError("Submission plan array specification differs")
    indices = range(len(tasks)) if selected_task_index is None else (selected_task_index,)
    for index in indices:
        if not 0 <= index < len(tasks):
            raise ValueError(f"Submission task index is outside [0, {len(tasks)}): {index}")
        task = tasks[index]
        manifest_task = manifest_tasks[index]
        expected_fields = {
            "task_index": index,
            "eval_id": manifest_task["eval_id"],
            "arm_label": manifest_task["arm_label"],
            "step": manifest_task["step"],
            "eval_config_sha256": manifest_task["eval_config"]["sha256"],
        }
        if any(task.get(field) != expected for field, expected in expected_fields.items()):
            raise ValueError(f"Submission plan task {index} differs from the evaluation manifest")
        current_checkpoint = checkpoint_identity(Path(manifest_task["model_path"]))
        if task.get("checkpoint") != current_checkpoint:
            raise ValueError(f"Checkpoint bytes changed for task {index}")
    return {"plan": plan, "plan_sha256": plan_sha256, "path": str(path)}


def submission_command(
    manifest: dict[str, Any],
    *,
    plan_path: Path,
    max_parallel: int,
    dependency: str | None,
) -> list[str]:
    _validate_max_parallel(max_parallel)
    _validate_dependency(dependency)
    task_count = len(manifest["tasks"])
    eval_root = Path(manifest["eval_root"])
    command = ["env"]
    for variable in SANITIZED_SBATCH_ENV_VARS:
        command.extend(("-u", variable))
    command.extend(
        (
            "sbatch",
            "--parsable",
            "--oversubscribe",
            f"--array=0-{task_count - 1}%{max_parallel}",
            f"--output={eval_root / 'logs' / 'job_%A_%a.log'}",
            f"--error={eval_root / 'logs' / 'job_%A_%a.log'}",
        )
    )
    if dependency is not None:
        command.append(f"--dependency={dependency}")
    command.extend(
        (
            manifest["array_template"]["path"],
            str(eval_root / EVAL_LAUNCH_MANIFEST_NAME),
            str(plan_path),
            manifest["source"]["run_dir"],
        )
    )
    return command


def require_control_tmux() -> dict[str, str]:
    tmux_value = os.environ.get("TMUX")
    if not tmux_value:
        raise ValueError("Actual fixed-clock SFT evaluation submission must run inside the control tmux session")
    socket = tmux_value.split(",", maxsplit=1)[0]
    if socket != CONTROL_TMUX_SOCKET:
        raise ValueError(f"Control tmux socket differs: {socket!r} != {CONTROL_TMUX_SOCKET!r}")
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        raise ValueError("Control tmux submission requires TMUX_PANE")
    result = subprocess.run(
        [
            "tmux",
            "-S",
            CONTROL_TMUX_SOCKET,
            "display-message",
            "-p",
            "-t",
            pane,
            "#{session_name}\t#{window_name}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = result.stdout.rstrip("\n").split("\t")
    expected = [CONTROL_TMUX_SESSION, CONTROL_TMUX_WINDOW]
    if observed != expected:
        raise ValueError(f"Control tmux target differs: {observed!r} != {expected!r}")
    return {
        "socket": CONTROL_TMUX_SOCKET,
        "session": CONTROL_TMUX_SESSION,
        "window": CONTROL_TMUX_WINDOW,
    }


def _validate_receipt(
    path: Path,
    *,
    plan_sha256: str,
    plan_path: Path,
    validated: dict[str, Any],
    command: list[str],
    control_tmux: dict[str, str],
) -> dict[str, Any]:
    receipt = read_json_object(path)
    if receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("study_id") != STUDY_ID:
        raise ValueError(f"Submission receipt has the wrong schema or study identity: {path}")
    job_id = receipt.get("array_job_id")
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1 or path.stem != str(job_id):
        raise ValueError(f"Submission receipt filename differs from its job ID: {path}")
    expected = {
        "plan_sha256": plan_sha256,
        "plan": file_identity(plan_path),
        "submission_intent": file_identity(plan_path.parent.parent / SUBMISSION_INTENT_NAME),
        "eval_launch_manifest_sha256": validated["manifest_sha256"],
        "control_tmux": control_tmux,
        "command": command,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ValueError(f"Submission receipt {field} differs: {path}")
    stdout = receipt.get("sbatch_stdout")
    if not isinstance(stdout, str) or stdout.split(";", maxsplit=1)[0] != str(job_id):
        raise ValueError(f"Submission receipt has invalid sbatch output: {path}")
    return receipt


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
    receipt_paths = sorted(jobs_dir.glob("*.json"))
    if len(receipt_paths) > 1:
        raise ValueError("Multiple immutable job receipts exist for one evaluation manifest")
    if not receipt_paths:
        return None
    path = receipt_paths[0]
    receipt = read_json_object(path)
    if receipt.get("plan_sha256") != plan_sha256:
        raise ValueError("Evaluation manifest already has a job receipt for a different submission plan")
    receipt = _validate_receipt(
        path,
        plan_sha256=plan_sha256,
        plan_path=plan_path,
        validated=validated,
        command=command,
        control_tmux=control_tmux,
    )
    return {**receipt, "receipt_path": str(path)}


def submission_intent(
    *,
    plan_sha256: str,
    plan_path: Path,
    validated: dict[str, Any],
    command: list[str],
    control_tmux: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "eval_launch_manifest": file_identity(Path(validated["manifest_path"])),
        "eval_launch_manifest_sha256": validated["manifest_sha256"],
        "plan_sha256": plan_sha256,
        "plan": file_identity(plan_path),
        "control_tmux": control_tmux,
        "command": command,
        "failure_policy": (
            "fail closed if no receipt exists; reconcile scheduler state before any explicit resubmission"
        ),
    }


def validate_submission_intent(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    observed = read_json_object(path)
    if observed != expected:
        raise ValueError("Evaluation manifest already has a different immutable submission intent")
    return observed


def submit(args: argparse.Namespace) -> dict[str, Any]:
    eval_root = args.eval_root.expanduser().resolve()
    validated = validate_eval_launch_manifest(eval_root / EVAL_LAUNCH_MANIFEST_NAME)
    manifest = validated["manifest"]
    readiness = checkpoint_readiness(manifest)
    placeholder_plan = eval_root / "submissions" / "plans" / ("0" * 64 + ".json")
    dry_command = submission_command(
        manifest,
        plan_path=placeholder_plan,
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
    control_tmux = require_control_tmux()
    plan, plan_sha256 = build_submission_plan(
        validated,
        max_parallel=args.max_parallel,
        dependency=args.dependency,
    )
    plan_path = eval_root / "submissions" / "plans" / f"{plan_sha256}.json"
    command = submission_command(
        manifest,
        plan_path=plan_path,
        max_parallel=args.max_parallel,
        dependency=args.dependency,
    )
    submissions_dir = eval_root / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)
    lock_path = submissions_dir / SUBMISSION_LOCK_NAME
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        write_json_once(plan_path, plan)
        validate_submission_plan(plan_path, validated)
        expected_intent = submission_intent(
            plan_sha256=plan_sha256,
            plan_path=plan_path,
            validated=validated,
            command=command,
            control_tmux=control_tmux,
        )
        intent_path = submissions_dir / SUBMISSION_INTENT_NAME
        if intent_path.exists():
            validate_submission_intent(intent_path, expected_intent)
            if receipt := _existing_receipt(
                eval_root,
                plan_sha256=plan_sha256,
                plan_path=plan_path,
                validated=validated,
                command=command,
                control_tmux=control_tmux,
            ):
                return {
                    "study_id": STUDY_ID,
                    "already_submitted": True,
                    "array_job_id": receipt["array_job_id"],
                    "receipt_path": receipt["receipt_path"],
                }
            raise RuntimeError(
                "Submission intent exists without a job receipt; reconcile Slurm state before resubmission"
            )
        if _existing_receipt(
            eval_root,
            plan_sha256=plan_sha256,
            plan_path=plan_path,
            validated=validated,
            command=command,
            control_tmux=control_tmux,
        ):
            raise RuntimeError("Job receipt exists without its immutable submission intent")
        write_json_once(intent_path, expected_intent)
        (eval_root / "logs").mkdir(parents=True, exist_ok=True)
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        raw_output = result.stdout.strip()
        job_id = raw_output.split(";", maxsplit=1)[0]
        if not job_id.isdigit():
            raise ValueError(f"sbatch returned an invalid array job ID: {result.stdout!r}")
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "study_id": STUDY_ID,
            "array_job_id": int(job_id),
            "plan_sha256": plan_sha256,
            "plan": file_identity(plan_path),
            "submission_intent": file_identity(intent_path),
            "eval_launch_manifest_sha256": validated["manifest_sha256"],
            "control_tmux": control_tmux,
            "command": command,
            "sbatch_stdout": raw_output,
        }
        receipt_path = eval_root / "submissions" / "jobs" / f"{job_id}.json"
        write_json_once(receipt_path, receipt)
        return {
            "study_id": STUDY_ID,
            "already_submitted": False,
            "array_job_id": int(job_id),
            "plan_sha256": plan_sha256,
            "receipt_path": str(receipt_path),
        }


def _validated_task_inputs(
    *,
    eval_launch_manifest: Path,
    submission_plan: Path,
    task_index: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_path = submission_plan.expanduser().resolve()
    plan = read_json_object(plan_path)
    plan_manifest = plan.get("eval_launch_manifest")
    if not isinstance(plan_manifest, dict) or not isinstance(plan_manifest.get("path"), str):
        raise ValueError("Submission plan has no evaluation launch manifest identity")
    requested_manifest = eval_launch_manifest.expanduser().resolve()
    if requested_manifest != Path(plan_manifest["path"]).resolve():
        raise ValueError("Runtime evaluation manifest differs from the submission plan")
    if file_identity(requested_manifest) != plan_manifest:
        raise ValueError("Runtime evaluation manifest bytes differ from the submission plan")
    validated = validate_eval_launch_manifest(requested_manifest, runtime_task_index=task_index)
    validated_plan = validate_submission_plan(
        plan_path,
        validated,
        selected_task_index=task_index,
    )
    task = validated["manifest"]["tasks"][task_index]
    return validated, validated_plan, task


def validate_task(args: argparse.Namespace) -> dict[str, Any]:
    validated, validated_plan, task = _validated_task_inputs(
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
        "submission_plan_sha256": validated_plan["plan_sha256"],
        "checkpoint_inventory_sha256": validated_plan["plan"]["tasks"][args.task_index]["checkpoint"][
            "inventory_sha256"
        ],
    }


def prepare_task(args: argparse.Namespace) -> dict[str, Any]:
    validated, validated_plan, task = _validated_task_inputs(
        eval_launch_manifest=args.eval_launch_manifest,
        submission_plan=args.submission_plan,
        task_index=args.task_index,
    )
    manifest = validated["manifest"]
    eval_root = Path(manifest["eval_root"])
    source_root = Path(manifest["source"]["snapshot_path"])
    inference_path, eval_path = runtime_config_paths(
        eval_root,
        array_job_id=args.array_job_id,
        task_index=args.task_index,
    )
    inference, evaluation = build_runtime_config_pair(
        task,
        task_index=args.task_index,
        array_job_id=args.array_job_id,
        eval_root=eval_root,
        source_root=source_root,
    )
    write_toml_once(inference_path, inference)
    write_toml_once(eval_path, evaluation)
    if read_toml(inference_path) != inference or read_toml(eval_path) != evaluation:
        raise ValueError("Runtime transport configs differ after materialization")
    runtime_record = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "array_job_id": args.array_job_id,
        "task_index": args.task_index,
        "eval_id": task["eval_id"],
        "transport_port": runtime_port(args.array_job_id, args.task_index),
        "eval_launch_manifest": file_identity(Path(validated["manifest_path"])),
        "submission_plan": file_identity(Path(validated_plan["path"])),
        "submission_plan_sha256": validated_plan["plan_sha256"],
        "base_inference_config": task["inference_config"],
        "base_eval_config": task["eval_config"],
        "runtime_inference_config": file_identity(inference_path),
        "runtime_eval_config": file_identity(eval_path),
        "checkpoint_inventory_sha256": validated_plan["plan"]["tasks"][args.task_index]["checkpoint"][
            "inventory_sha256"
        ],
    }
    runtime_manifest_path = eval_path.parent / "runtime_manifest.json"
    write_json_once(runtime_manifest_path, runtime_record)
    return {
        "study_id": STUDY_ID,
        "task_index": args.task_index,
        "eval_id": task["eval_id"],
        "eval_config": str(eval_path),
        "runtime_manifest": str(runtime_manifest_path),
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
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
