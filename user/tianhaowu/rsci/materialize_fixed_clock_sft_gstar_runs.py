#!/usr/bin/env python3
"""Materialize and safely submit immutable fixed-clock Gstar SFT runs."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import build_fixed_clock_sft_gstar_extension as gstar
import materialize_fixed_clock_sft_runs as v2_runs

STUDY_ID = gstar.STUDY_ID
SCHEMA_VERSION = 1
COMMON_STEPS = 64
SEQ_LEN = 2_048
BATCH_SIZE = 32
MICRO_BATCH_SIZE = 4
CHECKPOINT_INTERVAL = 8
DEFAULT_EXTENSION_INDEX = gstar.DEFAULT_OUTPUT_DIR / "arm_index.json"
DEFAULT_PAIRED_LAUNCH_MANIFEST = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/sft/verifier-defect-fixed-clock-v2b/launch_manifest.json"
)
DEFAULT_BASE_MODEL = v2_runs.DEFAULT_MODEL
DEFAULT_LAUNCH_ROOT = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/sft/verifier-defect-fixed-clock-v3-extension-gstar-v1"
)
SCRIPT_REPO_PATH = Path("user/tianhaowu/rsci/materialize_fixed_clock_sft_gstar_runs.py")
BUILDER_REPO_PATH = Path("user/tianhaowu/rsci/build_fixed_clock_sft_gstar_extension.py")
ANALYZER_REPO_PATH = Path("user/tianhaowu/rsci/analyze_fixed_clock_sft_gstar_extension.py")
TEMPLATE_REPO_PATH = v2_runs.TEMPLATE_REPO_PATH
ACTIVATOR_REPO_PATH = v2_runs.ACTIVATOR_REPO_PATH
LAUNCH_MANIFEST_NAME = "launch_manifest.json"
SUBMISSIONS_DIR_NAME = "submissions"
SUBMISSION_INTENT_NAME = "submission_intent.json"
SUBMISSION_LEDGER_NAME = "submission_ledger.json"
SUBMISSION_LOCK_NAME = ".submission.lock"
PLAN_DIR_NAME = "plans"
DISPATCH_DIR_NAME = "dispatch_intents"
RECEIPT_DIR_NAME = "job_receipts"
CONTROL_TMUX_SOCKET = "/tmp/codex-rsci-control-20260806.sock"
CONTROL_TMUX_SESSION = "codex-rsci-control-20260806"
CONTROL_TMUX_WINDOW = "Launcher"
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

STATIC_SFT_CONTRACT = {
    "data.weight_column": "sft_weight",
    "data.seq_len": SEQ_LEN,
    "data.pack_function": "fixed_stack",
    "data.batch_size": BATCH_SIZE,
    "data.micro_batch_size": MICRO_BATCH_SIZE,
    "data.shuffle": True,
    "data.seed": 0,
    "loss_impl": "torch",
}

LAUNCH_TRAINING_CONTRACT = {
    **STATIC_SFT_CONTRACT,
    "optimizer": "adamw",
    "lr": 1e-4,
    "scheduler": "constant",
    "warmup_steps": 0,
    "common_readout_step": COMMON_STEPS,
    "fixed_m_max_steps": COMMON_STEPS,
    "fixed_raw_max_steps": "max(64, ceil(2 * rows / 32))",
    "checkpoint_interval": CHECKPOINT_INTERVAL,
    "checkpoint_policy": "weights-only eval snapshots every 8 steps plus final; retain all",
    "checkpoint_resumable": False,
    "failure_policy": "restart from step 0 in a fresh output directory; never resume from weights-only state",
    "gpus_per_arm": 1,
    "exclusive_node": False,
    "materialization_only": False,
    "submission_interface": "protected materializer subcommand only",
}

SUBMISSION_CONTRACT = {
    "supported": True,
    "direct_shell_submission_allowed": False,
    "required_confirmation": STUDY_ID,
    "control_tmux": {
        "socket": CONTROL_TMUX_SOCKET,
        "session": CONTROL_TMUX_SESSION,
        "window": CONTROL_TMUX_WINDOW,
    },
    "sanitized_environment_variables": list(SANITIZED_SBATCH_ENV_VARS),
    "command_transport": "subprocess argv without a shell",
    "state_machine": "immutable plan, global intent, per-arm dispatch intents and receipts, final ledger",
    "ambiguous_sbatch_policy": "fail closed; recover only one exact Slurm comment match via reconciliation",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--extension-index", type=Path, default=DEFAULT_EXTENSION_INDEX)
    materialize.add_argument("--paired-launch-manifest", type=Path, default=DEFAULT_PAIRED_LAUNCH_MANIFEST)
    materialize.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL)
    materialize.add_argument("--launch-root", type=Path, default=DEFAULT_LAUNCH_ROOT)
    materialize.add_argument("--source-run-dir", type=Path)
    materialize.add_argument("--dry-run", action="store_true")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--launch-root", type=Path, default=DEFAULT_LAUNCH_ROOT)

    validate_arm = subparsers.add_parser("validate-arm")
    validate_arm.add_argument("--launch-manifest", type=Path, required=True)
    validate_arm.add_argument("--arm-label", required=True)
    validate_arm.add_argument("--resolved-config", type=Path, required=True)

    submit = subparsers.add_parser("submit")
    submit.add_argument("--launch-root", type=Path, default=DEFAULT_LAUNCH_ROOT)
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--confirm-study-id")

    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--launch-root", type=Path, default=DEFAULT_LAUNCH_ROOT)
    reconcile.add_argument("--dry-run", action="store_true")
    reconcile.add_argument("--confirm-study-id")
    return parser.parse_args()


def max_steps_for_arm(arm: dict[str, Any]) -> int:
    if arm["metadata"]["clock"] != "fixed_raw":
        return COMMON_STEPS
    return max(COMMON_STEPS, (2 * arm["rows"] + BATCH_SIZE - 1) // BATCH_SIZE)


def two_pass_steps(arm: dict[str, Any]) -> int | None:
    if arm["metadata"]["clock"] != "fixed_raw":
        return None
    return (2 * arm["rows"] + BATCH_SIZE - 1) // BATCH_SIZE


def checkpoint_steps(max_steps: int) -> list[int]:
    steps = list(range(CHECKPOINT_INTERVAL, max_steps, CHECKPOINT_INTERVAL))
    steps.append(max_steps)
    return steps


def readout_steps(arm: dict[str, Any]) -> list[int]:
    return sorted({COMMON_STEPS, max_steps_for_arm(arm)})


def schedule_label(arm: dict[str, Any]) -> str:
    return "at_least_two_dataset_passes" if arm["metadata"]["clock"] == "fixed_raw" else "common_64_steps"


def _metadata(entry: dict[str, Any]) -> dict[str, Any]:
    omitted = {"label", "alias_of", "dataset_path", "manifest_path", "parquet_sha256", "rows"}
    return {key: value for key, value in entry.items() if key not in omitted}


def validate_study_inputs(
    extension_index_path: Path,
    paired_launch_manifest_path: Path,
    base_model: Path,
) -> dict[str, Any]:
    extension_index_path = extension_index_path.expanduser().resolve()
    extension_index = gstar.validate_output(extension_index_path.parent, deep_selection_check=False)
    if extension_index_path != extension_index_path.parent / "arm_index.json":
        raise ValueError("The extension index must be the canonical arm_index.json")
    source_v2_index = Path(extension_index["source_v2_index"]["path"]).resolve()
    v2_inputs = v2_runs.validate_study_inputs(source_v2_index, base_model)
    paired = v2_runs.validate_launch_manifest(paired_launch_manifest_path)
    paired_manifest = paired["manifest"]
    if paired_manifest["inputs"]["arm_index"]["sha256"] != extension_index["source_v2_index"]["sha256"]:
        raise ValueError("The paired v2 launch does not use the extension's source v2 index")
    if paired_manifest["inputs"]["base_model"]["sha256"] != v2_inputs["base_model"]["sha256"]:
        raise ValueError("The paired v2 launch does not use the same base-model directory")
    paired_arms = {arm["label"]: arm for arm in paired_manifest["arms"]}

    arms: list[dict[str, Any]] = []
    for entry in extension_index["arms"]:
        if entry.get("alias_of") is not None or entry.get("assignment") != gstar.ASSIGNMENT:
            raise ValueError(f"Extension arm {entry.get('label')} is not a canonical Gstar arm")
        for source_label_field in (
            "source_behavior_label",
            "source_shuffled_label",
            "source_global_label",
        ):
            source_label = entry[source_label_field]
            if source_label not in paired_arms:
                raise ValueError(f"Paired v2 launch omits {source_label}")
        dataset_path = Path(entry["dataset_path"]).resolve()
        manifest_path = Path(entry["manifest_path"]).resolve()
        parquet_path = dataset_path / "train-00000-of-00001.parquet"
        arm_manifest = gstar.read_json_object(manifest_path)
        metadata = _metadata(entry)
        if arm_manifest.get("arm") != {"label": entry["label"], **metadata}:
            raise ValueError(f"Extension arm metadata differs for {entry['label']}")
        rows = int(entry["rows"])
        if rows != gstar.ANCHOR_COUNT + int(entry["hard_recipient_rows"]):
            raise ValueError(f"Extension arm count differs for {entry['label']}")
        weight_mass = arm_manifest.get("assistant_weight_mass")
        if not isinstance(weight_mass, (int, float)) or not math.isclose(weight_mass, rows, abs_tol=1e-8):
            raise ValueError(f"Extension arm weight mass differs for {entry['label']}")
        arm = {
            "label": entry["label"],
            "metadata": metadata,
            "rows": rows,
            "dataset_path": str(dataset_path),
            "dataset_manifest": v2_runs.file_identity(manifest_path),
            "parquet": v2_runs.file_identity(parquet_path),
        }
        arm.update(
            {
                "max_steps": max_steps_for_arm(arm),
                "checkpoint_steps": checkpoint_steps(max_steps_for_arm(arm)),
                "readout_steps": readout_steps(arm),
                "two_pass_steps": two_pass_steps(arm),
                "schedule": schedule_label(arm),
                "paired_v2_runs": {
                    assignment: {
                        "label": source_label,
                        "output_dir": paired_arms[source_label]["output_dir"],
                        "resolved_config": paired_arms[source_label]["resolved_config"],
                        "sbatch": paired_arms[source_label]["sbatch"],
                    }
                    for assignment, source_label in (
                        ("behavior", entry["source_behavior_label"]),
                        ("shuffled", entry["source_shuffled_label"]),
                        ("global", entry["source_global_label"]),
                    )
                },
            }
        )
        expected_contract = {
            **STATIC_SFT_CONTRACT,
            "max_steps": arm["max_steps"],
            "ckpt.interval": CHECKPOINT_INTERVAL,
            "readout_steps": arm["readout_steps"],
            "two_pass_steps": arm["two_pass_steps"],
            "schedule": arm["schedule"],
        }
        if arm_manifest.get("sft_contract") != expected_contract:
            raise ValueError(f"Extension SFT contract differs for {entry['label']}")
        arms.append(arm)
    arms.sort(key=lambda arm: arm["label"])
    if len(arms) != 15 or [arm["label"] for arm in arms] != extension_index["distinct_training_arms"]:
        raise ValueError("Extension launch inputs do not contain exactly 15 ordered arms")
    return {
        "extension_index": v2_runs.file_identity(extension_index_path),
        "source_v2_index": v2_runs.file_identity(source_v2_index),
        "paired_v2_launch_manifest": v2_runs.file_identity(paired_launch_manifest_path.expanduser().resolve()),
        "paired_v2_launch_manifest_sha256": paired["manifest_sha256"],
        "bank_contract_sha256": extension_index["bank_contract_sha256"],
        "base_model": v2_inputs["base_model"],
        "frozen_bank_manifest": v2_inputs["frozen_bank_manifest"],
        "frozen_bank_model": v2_inputs["frozen_bank_model"],
        "chat_template": v2_inputs["chat_template"],
        "arms": arms,
    }


def active_source_state(source_run_dir: Path) -> v2_runs.SourceState:
    source = v2_runs.active_source_state(source_run_dir)
    expected = (source.root / SCRIPT_REPO_PATH).resolve()
    if Path(__file__).resolve() != expected:
        raise ValueError(f"Materialization must run from the pinned source snapshot: {expected}")
    for path in (
        source.root / BUILDER_REPO_PATH,
        source.root / ANALYZER_REPO_PATH,
        source.root / TEMPLATE_REPO_PATH,
        source.root / ACTIVATOR_REPO_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    return source


def _wandb_tags(arm: dict[str, Any]) -> list[str]:
    metadata = arm["metadata"]
    return [
        f"study:{STUDY_ID}",
        f"arm:{arm['label']}",
        f"clock:{metadata['clock']}",
        f"assignment:{metadata['assignment']}",
        f"dose:{metadata['dose_label']}",
        f"selection_seed:{metadata['selection_seed']}",
        f"schedule:{arm['schedule']}",
        f"max_steps:{arm['max_steps']}",
        f"rows:{arm['rows']}",
        f"candidate_a_quota:{metadata['candidate_a_quota']}",
        f"noncandidate_quota:{metadata['noncandidate_quota']}",
    ]


def launch_config(
    arm: dict[str, Any],
    *,
    launch_root: Path,
    source: v2_runs.SourceState,
    base_model: Path,
    chat_template: Path,
) -> dict[str, Any]:
    label = arm["label"]
    output_dir = launch_root / "runs" / label
    resolved_config = output_dir / "configs" / "sft.toml"
    launch_manifest = launch_root / LAUNCH_MANIFEST_NAME
    bootstrap = source.root / ACTIVATOR_REPO_PATH
    validation_command = "\n".join(
        (
            f"source {shlex.quote(str(bootstrap))} {shlex.quote(str(source.run_dir))}",
            "uv run --no-sync python "
            f"{shlex.quote(SCRIPT_REPO_PATH.as_posix())} validate-arm "
            f"--launch-manifest {shlex.quote(str(launch_manifest))} "
            f"--arm-label {shlex.quote(label)} "
            f"--resolved-config {shlex.quote(str(resolved_config))}",
        )
    )
    return {
        "output_dir": str(output_dir),
        "max_steps": arm["max_steps"],
        "loss_impl": "torch",
        "dist_timeout_seconds": 1_800,
        "model": {
            "name": str(base_model),
            "seq_len": SEQ_LEN,
            "impl": "hf",
            "attn": "flash_attention_2",
            "ep": 1,
            "cp": 1,
        },
        "tokenizer": {
            "name": str(base_model),
            "chat_template": str(chat_template),
        },
        "data": {
            "type": "sft",
            "name": arm["dataset_path"],
            "seq_len": SEQ_LEN,
            "batch_size": BATCH_SIZE,
            "micro_batch_size": MICRO_BATCH_SIZE,
            "pack_function": "fixed_stack",
            "shuffle": True,
            "seed": 0,
            "weight_column": "sft_weight",
            "loss_mask": {
                "system": False,
                "user": False,
                "assistant": True,
                "tool": False,
            },
        },
        "optim": {"type": "adamw", "lr": 1e-4},
        "scheduler": {"type": "constant"},
        "ckpt": {
            "interval": CHECKPOINT_INTERVAL,
            "weights_only": True,
            "keep_last": len(arm["checkpoint_steps"]),
            "weights": {"save_sharded": True, "save_format": "safetensors"},
        },
        "deployment": {"type": "single_node", "num_gpus": 1, "gpus_per_node": 1},
        "slurm": {
            "job_name": f"rsci-vd-gstar-{label}",
            "account": "ram",
            "partition": "h100",
            "time": "01:00:00",
            "project_dir": str(source.root),
            "template_path": str(source.root / TEMPLATE_REPO_PATH),
            "pre_run_command": validation_command,
            "sync_environment": False,
        },
        "wandb": {
            "project": "rsci",
            "entity": "ram",
            "name": f"vd-fixed-clock-sft-{arm['label']}",
            "group": STUDY_ID,
            "tags": _wandb_tags(arm),
            "offline": False,
        },
        "log": {"level": "info", "interval": 1.0, "ranks_filter": [0]},
    }


def _nested(config: dict[str, Any], *keys: str) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"Resolved config has no {'.'.join(keys)}")
        value = value[key]
    return value


def validate_resolved_config(
    config_path: Path,
    *,
    arm: dict[str, Any],
    output_dir: Path,
    base_model: Path,
    chat_template: Path,
) -> dict[str, Any]:
    config = v2_runs.read_toml(config_path)
    expected_values = {
        ("output_dir",): str(output_dir),
        ("max_steps",): arm["max_steps"],
        ("loss_impl",): "torch",
        ("model", "name"): str(base_model),
        ("model", "seq_len"): SEQ_LEN,
        ("tokenizer", "name"): str(base_model),
        ("tokenizer", "chat_template"): str(chat_template),
        ("data", "type"): "sft",
        ("data", "name"): arm["dataset_path"],
        ("data", "seq_len"): SEQ_LEN,
        ("data", "batch_size"): BATCH_SIZE,
        ("data", "micro_batch_size"): MICRO_BATCH_SIZE,
        ("data", "pack_function"): "fixed_stack",
        ("data", "shuffle"): True,
        ("data", "seed"): 0,
        ("data", "weight_column"): "sft_weight",
        ("optim", "type"): "adamw",
        ("optim", "lr"): 1e-4,
        ("scheduler", "type"): "constant",
        ("ckpt", "interval"): CHECKPOINT_INTERVAL,
        ("ckpt", "weights_only"): True,
        ("ckpt", "keep_last"): len(arm["checkpoint_steps"]),
        ("deployment", "type"): "single_node",
        ("deployment", "num_gpus"): 1,
        ("deployment", "gpus_per_node"): 1,
        ("wandb", "name"): f"vd-fixed-clock-sft-{arm['label']}",
        ("wandb", "group"): STUDY_ID,
        ("wandb", "tags"): _wandb_tags(arm),
    }
    for keys, expected in expected_values.items():
        observed = _nested(config, *keys)
        if observed != expected:
            raise ValueError(f"Resolved config {'.'.join(keys)}={observed!r}, expected {expected!r}")
    if "warmup_steps" in config.get("scheduler", {}):
        raise ValueError("Constant scheduler unexpectedly carries warmup_steps")
    if config.get("ckpt", {}).get("resume_step") is not None:
        raise ValueError("Weights-only Gstar runs must restart from step 0")
    if "val" in config:
        raise ValueError("Gstar SFT arms must not use an in-training validation set")
    return config


def validate_sbatch(path: Path, *, resolved_config: Path, arm_label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    script = path.read_text(encoding="utf-8")
    required = (
        "#SBATCH --nodes=1",
        "#SBATCH --ntasks-per-node=1",
        "#SBATCH --gres=gpu:1",
        "#SBATCH --cpus-per-task=8",
        "#SBATCH --mem=64G",
        f'uv run --no-sync sft @ "{resolved_config}"',
        "materialize_fixed_clock_sft_gstar_runs.py validate-arm",
        f"--arm-label {arm_label}",
    )
    for value in required:
        if value not in script:
            raise ValueError(f"Generated Gstar script lacks {value!r}: {path}")
    if "--exclusive" in script:
        raise ValueError(f"Generated Gstar script requests an exclusive node: {path}")


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    launch_root = args.launch_root.expanduser().resolve()
    source_run_dir = (args.source_run_dir or launch_root).expanduser().resolve()
    source = active_source_state(source_run_dir)
    if launch_root == source.root or source.root.parent != source.run_dir:
        raise ValueError("Source snapshot must be rooted under its run directory, separate from launch outputs")
    inputs = validate_study_inputs(args.extension_index, args.paired_launch_manifest, args.base_model)
    plan = {
        "study_id": STUDY_ID,
        "launch_root": str(launch_root),
        "source_run_dir": str(source.run_dir),
        "source_snapshot": str(source.root),
        "arm_count": len(inputs["arms"]),
        "gpu_count_per_arm": 1,
        "total_requested_gpus_if_all_run": len(inputs["arms"]),
        "submitted": False,
    }
    if args.dry_run:
        return plan
    manifest_path = launch_root / LAUNCH_MANIFEST_NAME
    if manifest_path.exists():
        validated = validate_launch_manifest(manifest_path)
        return {**plan, "manifest_sha256": validated["manifest_sha256"], "already_materialized": True}

    launch_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    base_model = Path(inputs["base_model"]["path"])
    chat_template = Path(inputs["chat_template"]["path"])
    for arm in inputs["arms"]:
        config = launch_config(
            arm,
            launch_root=launch_root,
            source=source,
            base_model=base_model,
            chat_template=chat_template,
        )
        label = arm["label"]
        launch_config_path = launch_root / "launch_configs" / f"{label}.toml"
        v2_runs.write_toml_once(launch_config_path, config)
        output_dir = launch_root / "runs" / label
        resolved_config_path = output_dir / "configs" / "sft.toml"
        sbatch_path = output_dir / "sft.sbatch"
        existing = (resolved_config_path.exists(), sbatch_path.exists())
        if existing == (False, False):
            v2_runs._run(
                ["uv", "run", "--no-sync", "sft", "@", str(launch_config_path), "--dry-run"],
                cwd=source.root,
            )
        elif existing != (True, True):
            raise ValueError(f"Arm {label} has a partial dry-run materialization")
        validate_resolved_config(
            resolved_config_path,
            arm=arm,
            output_dir=output_dir,
            base_model=base_model,
            chat_template=chat_template,
        )
        validate_sbatch(sbatch_path, resolved_config=resolved_config_path, arm_label=label)
        records.append(
            {
                **arm,
                "output_dir": str(output_dir),
                "launch_config": v2_runs.file_identity(launch_config_path),
                "resolved_config": v2_runs.file_identity(resolved_config_path),
                "sbatch": v2_runs.file_identity(sbatch_path),
                "wandb": {
                    "name": config["wandb"]["name"],
                    "group": config["wandb"]["group"],
                    "tags": config["wandb"]["tags"],
                },
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "launch_root": str(launch_root),
        "source_run_dir": str(source.run_dir),
        "source": {
            "snapshot_path": str(source.root),
            "parent_commit_sha": source.provenance["parent_commit_sha"],
            "source_tree_sha256": source.provenance["source_tree_sha256"],
            "provenance_manifest": v2_runs.file_identity(source.run_dir / "source_provenance.json"),
        },
        "inputs": {
            key: inputs[key]
            for key in (
                "extension_index",
                "source_v2_index",
                "paired_v2_launch_manifest",
                "paired_v2_launch_manifest_sha256",
                "bank_contract_sha256",
                "base_model",
                "frozen_bank_manifest",
                "frozen_bank_model",
                "chat_template",
            )
        },
        "implementation": v2_runs.file_identity(source.root / SCRIPT_REPO_PATH),
        "builder": v2_runs.file_identity(source.root / BUILDER_REPO_PATH),
        "analyzer": v2_runs.file_identity(source.root / ANALYZER_REPO_PATH),
        "template": v2_runs.file_identity(source.root / TEMPLATE_REPO_PATH),
        "activator": v2_runs.file_identity(source.root / ACTIVATOR_REPO_PATH),
        "training_contract": LAUNCH_TRAINING_CONTRACT,
        "submission": SUBMISSION_CONTRACT,
        "arm_count": len(records),
        "arms": records,
    }
    v2_runs.write_json_atomic(manifest_path, manifest)
    validated = validate_launch_manifest(manifest_path)
    return {**plan, "manifest_sha256": validated["manifest_sha256"], "already_materialized": False}


def _verify_file(identity: object, label: str) -> dict[str, Any]:
    if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
        raise ValueError(f"Launch manifest {label} has no file identity")
    current = v2_runs.file_identity(Path(identity["path"]))
    if current != identity:
        raise ValueError(f"Launch manifest {label} identity differs")
    return current


def validate_launch_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = gstar.read_json_object(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("study_id") != STUDY_ID:
        raise ValueError("Gstar launch manifest has the wrong schema or study identity")
    launch_root = Path(manifest.get("launch_root", "")).resolve()
    if manifest_path != launch_root / LAUNCH_MANIFEST_NAME:
        raise ValueError("Gstar launch manifest is not at its recorded root")
    if manifest.get("training_contract") != LAUNCH_TRAINING_CONTRACT:
        raise ValueError("Gstar launch training contract differs")
    if manifest.get("submission") != SUBMISSION_CONTRACT:
        raise ValueError("Gstar launch submission contract differs")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Gstar launch manifest has no inputs")
    for field in (
        "extension_index",
        "source_v2_index",
        "paired_v2_launch_manifest",
        "frozen_bank_manifest",
        "chat_template",
    ):
        _verify_file(inputs.get(field), f"inputs.{field}")
    if v2_runs.directory_identity(Path(inputs["base_model"]["path"])) != inputs.get("base_model"):
        raise ValueError("Gstar launch base-model directory differs")
    if v2_runs.frozen_bank_model_identity(Path(inputs["base_model"]["path"])) != inputs.get("frozen_bank_model"):
        raise ValueError("Gstar launch frozen-bank model identity differs")
    paired = v2_runs.validate_launch_manifest(Path(inputs["paired_v2_launch_manifest"]["path"]))
    if paired["manifest_sha256"] != inputs.get("paired_v2_launch_manifest_sha256"):
        raise ValueError("Paired v2 launch manifest hash differs")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("Gstar launch manifest has no source identity")
    source_run_dir = Path(manifest.get("source_run_dir", "")).resolve()
    source_snapshot = Path(source.get("snapshot_path", "")).resolve()
    if source_snapshot != (source_run_dir / "source_snapshot").resolve():
        raise ValueError("Gstar launch source snapshot is not rooted under its recorded source run")
    if re.fullmatch(r"[0-9a-f]{40}", str(source.get("parent_commit_sha"))) is None:
        raise ValueError("Gstar launch source commit is invalid")
    if re.fullmatch(r"[0-9a-f]{64}", str(source.get("source_tree_sha256"))) is None:
        raise ValueError("Gstar launch source-tree identity is invalid")
    expected_source_files = {
        "implementation": SCRIPT_REPO_PATH,
        "builder": BUILDER_REPO_PATH,
        "analyzer": ANALYZER_REPO_PATH,
        "template": TEMPLATE_REPO_PATH,
        "activator": ACTIVATOR_REPO_PATH,
    }
    for field, relative_path in expected_source_files.items():
        identity = _verify_file(manifest.get(field), field)
        if Path(identity["path"]).resolve() != (source_snapshot / relative_path).resolve():
            raise ValueError(f"Gstar launch {field} is not from the recorded source snapshot")
    provenance_identity = _verify_file(source.get("provenance_manifest"), "source.provenance_manifest")
    if Path(provenance_identity["path"]).resolve() != (source_run_dir / "source_provenance.json").resolve():
        raise ValueError("Gstar launch provenance manifest is not at the recorded source run")
    arms = manifest.get("arms")
    if not isinstance(arms, list) or len(arms) != 15 or manifest.get("arm_count") != 15:
        raise ValueError("Gstar launch manifest does not contain exactly 15 arms")
    labels = [arm.get("label") for arm in arms]
    extension_index_path = Path(inputs["extension_index"]["path"])
    extension_index = gstar.validate_output(extension_index_path.parent, deep_selection_check=False)
    paired_inputs = paired["manifest"]["inputs"]
    extension_source_v2 = extension_index.get("source_v2_index")
    launch_source_v2 = inputs.get("source_v2_index")
    source_v2_matches_extension = (
        isinstance(extension_source_v2, dict)
        and isinstance(launch_source_v2, dict)
        and Path(extension_source_v2.get("path", "")).resolve() == Path(launch_source_v2.get("path", "")).resolve()
        and extension_source_v2.get("size_bytes") == launch_source_v2.get("size_bytes")
        and extension_source_v2.get("sha256") == launch_source_v2.get("sha256")
    )
    if (
        not source_v2_matches_extension
        or inputs.get("bank_contract_sha256") != extension_index.get("bank_contract_sha256")
        or inputs.get("source_v2_index") != paired_inputs.get("arm_index")
        or inputs.get("base_model") != paired_inputs.get("base_model")
        or inputs.get("frozen_bank_manifest") != paired_inputs.get("frozen_bank_manifest")
        or inputs.get("frozen_bank_model") != paired_inputs.get("frozen_bank_model")
        or inputs.get("chat_template") != paired_inputs.get("chat_template")
    ):
        raise ValueError("Gstar launch inputs differ from the extension or paired v2 launch")
    if labels != sorted(labels) or labels != extension_index.get("distinct_training_arms"):
        raise ValueError("Gstar launch arm ordering differs from the extension index")
    extension_by_label = {entry["label"]: entry for entry in extension_index["arms"]}
    paired_by_label = {arm["label"]: arm for arm in paired["manifest"]["arms"]}
    base_model = Path(inputs["base_model"]["path"])
    chat_template = Path(inputs["chat_template"]["path"])
    for arm in arms:
        extension_entry = extension_by_label[arm["label"]]
        expected_metadata = _metadata(extension_entry)
        if (
            arm.get("metadata") != expected_metadata
            or arm.get("rows") != extension_entry["rows"]
            or Path(arm.get("dataset_path", "")).resolve() != Path(extension_entry["dataset_path"]).resolve()
            or arm.get("dataset_manifest") != v2_runs.file_identity(Path(extension_entry["manifest_path"]))
            or arm.get("parquet")
            != v2_runs.file_identity(Path(extension_entry["dataset_path"]) / "train-00000-of-00001.parquet")
        ):
            raise ValueError(f"Gstar launch arm {arm['label']} differs from the extension index")
        expected_paired_runs = {
            assignment: {
                "label": source_label,
                "output_dir": paired_by_label[source_label]["output_dir"],
                "resolved_config": paired_by_label[source_label]["resolved_config"],
                "sbatch": paired_by_label[source_label]["sbatch"],
            }
            for assignment, source_label in (
                ("behavior", expected_metadata["source_behavior_label"]),
                ("shuffled", expected_metadata["source_shuffled_label"]),
                ("global", expected_metadata["source_global_label"]),
            )
        }
        if arm.get("paired_v2_runs") != expected_paired_runs:
            raise ValueError(f"Gstar launch arm {arm['label']} has a different paired v2 run mapping")
        expected_schedule = {
            "max_steps": max_steps_for_arm(arm),
            "checkpoint_steps": checkpoint_steps(max_steps_for_arm(arm)),
            "readout_steps": readout_steps(arm),
            "two_pass_steps": two_pass_steps(arm),
            "schedule": schedule_label(arm),
        }
        for field, expected in expected_schedule.items():
            if arm.get(field) != expected:
                raise ValueError(f"Gstar launch arm {arm['label']} has an invalid {field}")
        for field in ("dataset_manifest", "parquet", "launch_config", "resolved_config", "sbatch"):
            _verify_file(arm.get(field), f"arms.{arm['label']}.{field}")
        output_dir = Path(arm["output_dir"])
        resolved_config = Path(arm["resolved_config"]["path"])
        validate_resolved_config(
            resolved_config,
            arm=arm,
            output_dir=output_dir,
            base_model=base_model,
            chat_template=chat_template,
        )
        validate_sbatch(Path(arm["sbatch"]["path"]), resolved_config=resolved_config, arm_label=arm["label"])
    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": v2_runs.file_sha256(manifest_path),
    }


def validate_one_arm(manifest_path: Path, arm_label: str, resolved_config: Path) -> dict[str, Any]:
    validated = validate_launch_manifest(manifest_path)
    arm = next((record for record in validated["manifest"]["arms"] if record["label"] == arm_label), None)
    if arm is None:
        raise ValueError(f"Unknown Gstar arm: {arm_label}")
    if resolved_config.expanduser().resolve() != Path(arm["resolved_config"]["path"]).resolve():
        raise ValueError(f"Runtime resolved config differs for {arm_label}")
    return {
        "study_id": STUDY_ID,
        "arm_label": arm_label,
        "launch_manifest_sha256": validated["manifest_sha256"],
        "resolved_config_sha256": arm["resolved_config"]["sha256"],
        "parquet_sha256": arm["parquet"]["sha256"],
    }


def write_json_once(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if not path.is_file() or path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"Refusing to replace a different immutable submission artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(encoded, encoding="utf-8")
    partial.replace(path)


def submission_comment(validated: dict[str, Any], arm: dict[str, Any]) -> str:
    material = {
        "study_id": STUDY_ID,
        "launch_manifest_sha256": validated["manifest_sha256"],
        "arm_label": arm["label"],
        "sbatch_sha256": arm["sbatch"]["sha256"],
    }
    return f"rsci-gstar-v1-{v2_runs.canonical_json_sha256(material)}"


def submission_command(arm: dict[str, Any], *, comment: str) -> list[str]:
    if re.fullmatch(r"rsci-gstar-v1-[0-9a-f]{64}", comment) is None:
        raise ValueError("Gstar submission comment is invalid")
    command = ["env"]
    for variable in SANITIZED_SBATCH_ENV_VARS:
        command.extend(("-u", variable))
    command.extend(("sbatch", "--parsable", f"--comment={comment}", arm["sbatch"]["path"]))
    return command


def build_submission_plan(validated: dict[str, Any]) -> tuple[dict[str, Any], str]:
    manifest = validated["manifest"]
    arms = []
    for index, arm in enumerate(manifest["arms"]):
        comment = submission_comment(validated, arm)
        arms.append(
            {
                "arm_index": index,
                "arm_label": arm["label"],
                "sbatch": arm["sbatch"],
                "comment": comment,
                "command": submission_command(arm, comment=comment),
            }
        )
    plan = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "launch_manifest": v2_runs.file_identity(Path(validated["manifest_path"])),
        "launch_manifest_sha256": validated["manifest_sha256"],
        "arm_count": len(arms),
        "arms": arms,
    }
    return plan, v2_runs.canonical_json_sha256(plan)


def validate_submission_plan(path: Path, validated: dict[str, Any]) -> dict[str, Any]:
    plan = gstar.read_json_object(path)
    expected, expected_sha256 = build_submission_plan(validated)
    if plan != expected or path.stem != expected_sha256:
        raise ValueError("Gstar submission plan differs from the launch manifest")
    return {"plan": plan, "plan_sha256": expected_sha256, "path": str(path)}


def require_control_tmux() -> dict[str, str]:
    tmux_value = os.environ.get("TMUX")
    if not tmux_value:
        raise ValueError("Actual Gstar SFT submission must run inside the control tmux session")
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


def _created_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_created_at_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Submission intent has no UTC creation timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Submission intent creation timestamp is not UTC")
    return parsed


def submission_intent(
    *,
    plan_path: Path,
    plan_sha256: str,
    validated: dict[str, Any],
    control_tmux: dict[str, str],
    created_at_utc: str,
) -> dict[str, Any]:
    _parse_created_at_utc(created_at_utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "created_at_utc": created_at_utc,
        "launch_manifest": v2_runs.file_identity(Path(validated["manifest_path"])),
        "launch_manifest_sha256": validated["manifest_sha256"],
        "plan": v2_runs.file_identity(plan_path),
        "plan_sha256": plan_sha256,
        "control_tmux": control_tmux,
        "failure_policy": (
            "write an arm dispatch intent before sbatch; if no receipt follows, never resubmit directly and "
            "recover only one exact Slurm comment match"
        ),
    }


def validate_submission_intent(
    path: Path,
    *,
    plan_path: Path,
    plan_sha256: str,
    validated: dict[str, Any],
) -> dict[str, Any]:
    observed = gstar.read_json_object(path)
    created_at_utc = observed.get("created_at_utc")
    expected = submission_intent(
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        validated=validated,
        control_tmux=SUBMISSION_CONTRACT["control_tmux"],
        created_at_utc=str(created_at_utc),
    )
    if observed != expected:
        raise ValueError("Gstar launch already has a different immutable submission intent")
    return observed


def dispatch_intent(
    *,
    arm_plan: dict[str, Any],
    plan_path: Path,
    plan_sha256: str,
    intent_path: Path,
    control_tmux: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "arm_index": arm_plan["arm_index"],
        "arm_label": arm_plan["arm_label"],
        "comment": arm_plan["comment"],
        "command": arm_plan["command"],
        "sbatch": arm_plan["sbatch"],
        "plan": v2_runs.file_identity(plan_path),
        "plan_sha256": plan_sha256,
        "submission_intent": v2_runs.file_identity(intent_path),
        "control_tmux": control_tmux,
    }


def validate_dispatch_intent(
    path: Path,
    *,
    arm_plan: dict[str, Any],
    plan_path: Path,
    plan_sha256: str,
    intent_path: Path,
    control_tmux: dict[str, str],
) -> dict[str, Any]:
    observed = gstar.read_json_object(path)
    expected = dispatch_intent(
        arm_plan=arm_plan,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        intent_path=intent_path,
        control_tmux=control_tmux,
    )
    if observed != expected:
        raise ValueError(f"Gstar arm {arm_plan['arm_label']} has a different immutable dispatch intent")
    return observed


def parse_scheduler_job_ids(output: str, *, comment: str) -> set[int]:
    job_ids: set[int] = set()
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split("|")
        job_id = fields[0].strip()
        observed_comment = fields[1].strip() if len(fields) > 1 else ""
        if job_id.isdigit() and observed_comment == comment:
            job_ids.add(int(job_id))
    return job_ids


def scheduler_matches(comment: str, *, created_at_utc: str) -> tuple[set[int], dict[str, Any]]:
    created = _parse_created_at_utc(created_at_utc)
    accounting_start = (created - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    squeue_command = ["squeue", "--noheader", "--format=%i|%k"]
    sacct_command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--starttime",
        accounting_start,
        "--format=JobIDRaw,Comment",
    ]
    squeue = subprocess.run(squeue_command, check=True, capture_output=True, text=True)
    sacct = subprocess.run(sacct_command, check=True, capture_output=True, text=True)
    squeue_ids = parse_scheduler_job_ids(squeue.stdout, comment=comment)
    sacct_ids = parse_scheduler_job_ids(sacct.stdout, comment=comment)
    matches = squeue_ids | sacct_ids
    evidence = {
        "squeue_command": squeue_command,
        "squeue_stdout_sha256": hashlib.sha256(squeue.stdout.encode()).hexdigest(),
        "squeue_job_ids": sorted(squeue_ids),
        "sacct_command": sacct_command,
        "sacct_stdout_sha256": hashlib.sha256(sacct.stdout.encode()).hexdigest(),
        "sacct_job_ids": sorted(sacct_ids),
        "matched_job_ids": sorted(matches),
    }
    return matches, evidence


def validate_scheduler_evidence(evidence: object, *, job_id: int) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("Reconciled Gstar receipt has no scheduler evidence")
    expected_keys = {
        "squeue_command",
        "squeue_stdout_sha256",
        "squeue_job_ids",
        "sacct_command",
        "sacct_stdout_sha256",
        "sacct_job_ids",
        "matched_job_ids",
    }
    if set(evidence) != expected_keys:
        raise ValueError("Reconciled Gstar scheduler evidence fields differ")
    if evidence["squeue_command"] != ["squeue", "--noheader", "--format=%i|%k"]:
        raise ValueError("Reconciled Gstar squeue command differs")
    sacct_command = evidence["sacct_command"]
    if (
        not isinstance(sacct_command, list)
        or len(sacct_command) != 7
        or sacct_command[:5] != ["sacct", "--noheader", "--parsable2", "--allocations", "--starttime"]
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(sacct_command[5])) is None
        or sacct_command[6:] != ["--format=JobIDRaw,Comment"]
    ):
        raise ValueError("Reconciled Gstar sacct command differs")
    for field in ("squeue_stdout_sha256", "sacct_stdout_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", str(evidence[field])) is None:
            raise ValueError(f"Reconciled Gstar {field} is not a SHA-256 digest")
    id_lists = []
    for field in ("squeue_job_ids", "sacct_job_ids", "matched_job_ids"):
        values = evidence[field]
        if (
            not isinstance(values, list)
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values)
            or values != sorted(set(values))
        ):
            raise ValueError(f"Reconciled Gstar {field} is invalid")
        id_lists.append(values)
    squeue_ids, sacct_ids, matched_ids = id_lists
    if sorted(set(squeue_ids) | set(sacct_ids)) != matched_ids or matched_ids != [job_id]:
        raise ValueError("Reconciled Gstar scheduler evidence does not prove one exact job")
    return evidence


def job_receipt(
    *,
    arm_plan: dict[str, Any],
    job_id: int,
    plan_path: Path,
    plan_sha256: str,
    intent_path: Path,
    dispatch_path: Path,
    control_tmux: dict[str, str],
    submission_source: str,
    sbatch_stdout: str | None = None,
    scheduler_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError("Gstar receipt job ID is invalid")
    if submission_source not in {"sbatch_stdout", "scheduler_reconciliation"}:
        raise ValueError("Gstar receipt submission source is invalid")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "arm_index": arm_plan["arm_index"],
        "arm_label": arm_plan["arm_label"],
        "job_id": job_id,
        "comment": arm_plan["comment"],
        "command": arm_plan["command"],
        "sbatch": arm_plan["sbatch"],
        "plan": v2_runs.file_identity(plan_path),
        "plan_sha256": plan_sha256,
        "submission_intent": v2_runs.file_identity(intent_path),
        "dispatch_intent": v2_runs.file_identity(dispatch_path),
        "control_tmux": control_tmux,
        "submission_source": submission_source,
        "sbatch_stdout": sbatch_stdout,
        "scheduler_evidence": scheduler_evidence,
    }
    if submission_source == "sbatch_stdout":
        if not isinstance(sbatch_stdout, str) or sbatch_stdout.split(";", maxsplit=1)[0] != str(job_id):
            raise ValueError("Gstar receipt has invalid sbatch output")
        if scheduler_evidence is not None:
            raise ValueError("Direct sbatch receipt unexpectedly has scheduler evidence")
    else:
        if sbatch_stdout is not None:
            raise ValueError("Reconciled Gstar receipt has invalid scheduler evidence")
        validate_scheduler_evidence(scheduler_evidence, job_id=job_id)
    return receipt


def validate_job_receipt(
    path: Path,
    *,
    arm_plan: dict[str, Any],
    plan_path: Path,
    plan_sha256: str,
    intent_path: Path,
    dispatch_path: Path,
    control_tmux: dict[str, str],
) -> dict[str, Any]:
    observed = gstar.read_json_object(path)
    expected = job_receipt(
        arm_plan=arm_plan,
        job_id=observed.get("job_id"),
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        intent_path=intent_path,
        dispatch_path=dispatch_path,
        control_tmux=control_tmux,
        submission_source=observed.get("submission_source"),
        sbatch_stdout=observed.get("sbatch_stdout"),
        scheduler_evidence=observed.get("scheduler_evidence"),
    )
    if observed != expected or path.name != f"{arm_plan['arm_label']}.json":
        raise ValueError(f"Gstar job receipt differs for {arm_plan['arm_label']}")
    return observed


def submission_ledger(
    *,
    validated: dict[str, Any],
    plan_path: Path,
    plan_sha256: str,
    intent_path: Path,
    control_tmux: dict[str, str],
    receipt_paths: dict[str, Path],
) -> dict[str, Any]:
    jobs = []
    for label in sorted(receipt_paths):
        path = receipt_paths[label]
        receipt = gstar.read_json_object(path)
        jobs.append({"arm_label": label, "job_id": receipt["job_id"], "receipt": v2_runs.file_identity(path)})
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "launch_manifest": v2_runs.file_identity(Path(validated["manifest_path"])),
        "launch_manifest_sha256": validated["manifest_sha256"],
        "plan": v2_runs.file_identity(plan_path),
        "plan_sha256": plan_sha256,
        "submission_intent": v2_runs.file_identity(intent_path),
        "control_tmux": control_tmux,
        "job_count": len(jobs),
        "jobs": jobs,
    }


def submission_status(validated: dict[str, Any]) -> dict[str, Any]:
    launch_root = Path(validated["manifest"]["launch_root"])
    submissions_dir = launch_root / SUBMISSIONS_DIR_NAME
    plan, plan_sha256 = build_submission_plan(validated)
    plan_path = submissions_dir / PLAN_DIR_NAME / f"{plan_sha256}.json"
    intent_path = submissions_dir / SUBMISSION_INTENT_NAME
    dispatch_dir = submissions_dir / DISPATCH_DIR_NAME
    receipt_dir = submissions_dir / RECEIPT_DIR_NAME
    ledger_path = submissions_dir / SUBMISSION_LEDGER_NAME
    existing_plans = sorted((submissions_dir / PLAN_DIR_NAME).glob("*.json"))
    if existing_plans and existing_plans != [plan_path]:
        raise ValueError("Gstar launch has an unexpected immutable submission plan")
    if plan_path.exists():
        validate_submission_plan(plan_path, validated)
    if not intent_path.exists():
        if any(path.exists() for path in (dispatch_dir, receipt_dir, ledger_path)):
            raise RuntimeError("Gstar submission artifacts exist without the global intent")
        return {
            "state": "not_submitted",
            "submitted": False,
            "jobs_queued": False,
            "receipt_count": 0,
            "job_ids": {},
            "plan_sha256": plan_sha256,
        }
    if not plan_path.is_file():
        raise RuntimeError("Gstar submission intent exists without its immutable plan")
    intent = validate_submission_intent(
        intent_path,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        validated=validated,
    )
    control_tmux = intent["control_tmux"]
    expected_labels = [arm["arm_label"] for arm in plan["arms"]]
    dispatch_paths = {path.stem: path for path in sorted(dispatch_dir.glob("*.json"))} if dispatch_dir.is_dir() else {}
    receipt_paths = {path.stem: path for path in sorted(receipt_dir.glob("*.json"))} if receipt_dir.is_dir() else {}
    if not set(dispatch_paths) <= set(expected_labels) or not set(receipt_paths) <= set(dispatch_paths):
        raise ValueError("Gstar launch has unexpected dispatch intents or job receipts")
    dispatched_indices = sorted(expected_labels.index(label) for label in dispatch_paths)
    if dispatched_indices != list(range(len(dispatched_indices))):
        raise ValueError("Gstar dispatch intents are not an ordered prefix of the submission plan")
    job_ids: dict[str, int] = {}
    plan_by_label = {arm["arm_label"]: arm for arm in plan["arms"]}
    for label, dispatch_path in dispatch_paths.items():
        arm_plan = plan_by_label[label]
        validate_dispatch_intent(
            dispatch_path,
            arm_plan=arm_plan,
            plan_path=plan_path,
            plan_sha256=plan_sha256,
            intent_path=intent_path,
            control_tmux=control_tmux,
        )
        if label in receipt_paths:
            receipt = validate_job_receipt(
                receipt_paths[label],
                arm_plan=arm_plan,
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                intent_path=intent_path,
                dispatch_path=dispatch_path,
                control_tmux=control_tmux,
            )
            job_ids[label] = receipt["job_id"]
    if len(set(job_ids.values())) != len(job_ids):
        raise ValueError("Gstar job receipts reuse a Slurm job ID across arms")
    all_receipts = len(receipt_paths) == len(plan["arms"])
    if ledger_path.exists():
        if not all_receipts:
            raise RuntimeError("Gstar final ledger exists before every immutable job receipt")
        expected_ledger = submission_ledger(
            validated=validated,
            plan_path=plan_path,
            plan_sha256=plan_sha256,
            intent_path=intent_path,
            control_tmux=control_tmux,
            receipt_paths=receipt_paths,
        )
        if gstar.read_json_object(ledger_path) != expected_ledger:
            raise ValueError("Gstar final submission ledger differs from its immutable receipts")
        state = "submitted"
    elif all_receipts:
        state = "receipts_complete_ledger_pending"
    elif len(dispatch_paths) > len(receipt_paths):
        state = "ambiguous_dispatch_pending_reconciliation"
    else:
        state = "submission_in_progress"
    return {
        "state": state,
        "submitted": state == "submitted",
        "jobs_queued": all_receipts,
        "receipt_count": len(receipt_paths),
        "job_ids": dict(sorted(job_ids.items())),
        "plan_sha256": plan_sha256,
        "intent_path": str(intent_path),
        "ledger_path": str(ledger_path) if ledger_path.exists() else None,
    }


def _finalize_ledger(validated: dict[str, Any]) -> dict[str, Any]:
    status = submission_status(validated)
    if status["receipt_count"] != len(validated["manifest"]["arms"]):
        return status
    launch_root = Path(validated["manifest"]["launch_root"])
    submissions_dir = launch_root / SUBMISSIONS_DIR_NAME
    plan, plan_sha256 = build_submission_plan(validated)
    plan_path = submissions_dir / PLAN_DIR_NAME / f"{plan_sha256}.json"
    intent_path = submissions_dir / SUBMISSION_INTENT_NAME
    intent = gstar.read_json_object(intent_path)
    receipt_paths = {path.stem: path for path in sorted((submissions_dir / RECEIPT_DIR_NAME).glob("*.json"))}
    ledger = submission_ledger(
        validated=validated,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        intent_path=intent_path,
        control_tmux=intent["control_tmux"],
        receipt_paths=receipt_paths,
    )
    write_json_once(submissions_dir / SUBMISSION_LEDGER_NAME, ledger)
    return submission_status(validated)


def _recover_dispatched_arm(
    *,
    arm_plan: dict[str, Any],
    plan_path: Path,
    plan_sha256: str,
    intent_path: Path,
    intent: dict[str, Any],
    dispatch_path: Path,
    receipt_path: Path,
) -> tuple[bool, dict[str, Any]]:
    matches, evidence = scheduler_matches(arm_plan["comment"], created_at_utc=intent["created_at_utc"])
    if len(matches) > 1:
        raise RuntimeError(
            f"Gstar arm {arm_plan['arm_label']} has multiple exact Slurm comment matches: {sorted(matches)}"
        )
    if not matches:
        return False, evidence
    job_id = next(iter(matches))
    receipt = job_receipt(
        arm_plan=arm_plan,
        job_id=job_id,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        intent_path=intent_path,
        dispatch_path=dispatch_path,
        control_tmux=intent["control_tmux"],
        submission_source="scheduler_reconciliation",
        scheduler_evidence=evidence,
    )
    write_json_once(receipt_path, receipt)
    return True, evidence


def submit(args: argparse.Namespace) -> dict[str, Any]:
    launch_root = args.launch_root.expanduser().resolve()
    validated = validate_launch_manifest(launch_root / LAUNCH_MANIFEST_NAME)
    plan, plan_sha256 = build_submission_plan(validated)
    current_status = submission_status(validated)
    if args.dry_run:
        return {
            "study_id": STUDY_ID,
            "launch_manifest_sha256": validated["manifest_sha256"],
            "plan_sha256": plan_sha256,
            "status": current_status,
            "commands": [shlex.join(arm["command"]) for arm in plan["arms"]],
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual submission requires --confirm-study-id {STUDY_ID}")
    control_tmux = require_control_tmux()
    submissions_dir = launch_root / SUBMISSIONS_DIR_NAME
    submissions_dir.mkdir(parents=True, exist_ok=True)
    lock_path = submissions_dir / SUBMISSION_LOCK_NAME
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        plan_path = submissions_dir / PLAN_DIR_NAME / f"{plan_sha256}.json"
        write_json_once(plan_path, plan)
        validate_submission_plan(plan_path, validated)
        intent_path = submissions_dir / SUBMISSION_INTENT_NAME
        if intent_path.exists():
            intent = validate_submission_intent(
                intent_path,
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                validated=validated,
            )
            if intent["control_tmux"] != control_tmux:
                raise ValueError("Existing Gstar submission intent belongs to a different control tmux")
        else:
            if current_status["state"] != "not_submitted":
                raise RuntimeError("Cannot create a Gstar submission intent over existing submission state")
            intent = submission_intent(
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                validated=validated,
                control_tmux=control_tmux,
                created_at_utc=_created_at_utc(),
            )
            write_json_once(intent_path, intent)
        dispatch_dir = submissions_dir / DISPATCH_DIR_NAME
        receipt_dir = submissions_dir / RECEIPT_DIR_NAME
        for arm_plan in plan["arms"]:
            label = arm_plan["arm_label"]
            dispatch_path = dispatch_dir / f"{label}.json"
            receipt_path = receipt_dir / f"{label}.json"
            if receipt_path.exists():
                validate_job_receipt(
                    receipt_path,
                    arm_plan=arm_plan,
                    plan_path=plan_path,
                    plan_sha256=plan_sha256,
                    intent_path=intent_path,
                    dispatch_path=dispatch_path,
                    control_tmux=control_tmux,
                )
                continue
            if dispatch_path.exists():
                validate_dispatch_intent(
                    dispatch_path,
                    arm_plan=arm_plan,
                    plan_path=plan_path,
                    plan_sha256=plan_sha256,
                    intent_path=intent_path,
                    control_tmux=control_tmux,
                )
                recovered, _ = _recover_dispatched_arm(
                    arm_plan=arm_plan,
                    plan_path=plan_path,
                    plan_sha256=plan_sha256,
                    intent_path=intent_path,
                    intent=intent,
                    dispatch_path=dispatch_path,
                    receipt_path=receipt_path,
                )
                if recovered:
                    continue
                raise RuntimeError(
                    f"Gstar arm {label} has a dispatch intent without a receipt or exact scheduler match; "
                    "retry reconciliation later and do not resubmit"
                )
            write_json_once(
                dispatch_path,
                dispatch_intent(
                    arm_plan=arm_plan,
                    plan_path=plan_path,
                    plan_sha256=plan_sha256,
                    intent_path=intent_path,
                    control_tmux=control_tmux,
                ),
            )
            result = subprocess.run(arm_plan["command"], check=True, capture_output=True, text=True)
            raw_output = result.stdout.strip()
            job_id_text = raw_output.split(";", maxsplit=1)[0]
            if not job_id_text.isdigit():
                raise ValueError(f"sbatch returned an invalid job ID for {label}: {result.stdout!r}")
            receipt = job_receipt(
                arm_plan=arm_plan,
                job_id=int(job_id_text),
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                intent_path=intent_path,
                dispatch_path=dispatch_path,
                control_tmux=control_tmux,
                submission_source="sbatch_stdout",
                sbatch_stdout=raw_output,
            )
            write_json_once(receipt_path, receipt)
        status = _finalize_ledger(validated)
    return {
        "study_id": STUDY_ID,
        "launch_manifest_sha256": validated["manifest_sha256"],
        "plan_sha256": plan_sha256,
        "status": status,
    }


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    launch_root = args.launch_root.expanduser().resolve()
    validated = validate_launch_manifest(launch_root / LAUNCH_MANIFEST_NAME)
    status = submission_status(validated)
    if args.dry_run:
        return {"study_id": STUDY_ID, "status": status, "scheduler_mutation": False}
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual reconciliation requires --confirm-study-id {STUDY_ID}")
    control_tmux = require_control_tmux()
    if status["state"] == "not_submitted":
        raise RuntimeError("Gstar launch has no submission intent to reconcile")
    submissions_dir = launch_root / SUBMISSIONS_DIR_NAME
    lock_path = submissions_dir / SUBMISSION_LOCK_NAME
    unresolved: list[str] = []
    recovered: dict[str, int] = {}
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        plan, plan_sha256 = build_submission_plan(validated)
        plan_path = submissions_dir / PLAN_DIR_NAME / f"{plan_sha256}.json"
        intent_path = submissions_dir / SUBMISSION_INTENT_NAME
        intent = validate_submission_intent(
            intent_path,
            plan_path=plan_path,
            plan_sha256=plan_sha256,
            validated=validated,
        )
        if intent["control_tmux"] != control_tmux:
            raise ValueError("Existing Gstar submission intent belongs to a different control tmux")
        for arm_plan in plan["arms"]:
            label = arm_plan["arm_label"]
            dispatch_path = submissions_dir / DISPATCH_DIR_NAME / f"{label}.json"
            receipt_path = submissions_dir / RECEIPT_DIR_NAME / f"{label}.json"
            if receipt_path.exists() or not dispatch_path.exists():
                continue
            validate_dispatch_intent(
                dispatch_path,
                arm_plan=arm_plan,
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                intent_path=intent_path,
                control_tmux=control_tmux,
            )
            found, _ = _recover_dispatched_arm(
                arm_plan=arm_plan,
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                intent_path=intent_path,
                intent=intent,
                dispatch_path=dispatch_path,
                receipt_path=receipt_path,
            )
            if found:
                recovered[label] = gstar.read_json_object(receipt_path)["job_id"]
            else:
                unresolved.append(label)
        status = _finalize_ledger(validated)
    return {
        "study_id": STUDY_ID,
        "recovered_job_ids": dict(sorted(recovered.items())),
        "unresolved_dispatches": unresolved,
        "scheduler_mutation": False,
        "status": status,
    }


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        result = materialize(args)
    elif args.command == "validate":
        validated = validate_launch_manifest(args.launch_root / LAUNCH_MANIFEST_NAME)
        result = {
            "study_id": STUDY_ID,
            "manifest_path": validated["manifest_path"],
            "manifest_sha256": validated["manifest_sha256"],
            "arm_count": len(validated["manifest"]["arms"]),
            "submission_status": submission_status(validated),
        }
    elif args.command == "validate-arm":
        result = validate_one_arm(args.launch_manifest, args.arm_label, args.resolved_config)
    elif args.command == "submit":
        result = submit(args)
    elif args.command == "reconcile":
        result = reconcile(args)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
