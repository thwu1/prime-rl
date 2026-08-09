#!/usr/bin/env python3
"""Materialize and validate isolated step-4000 verifier-withdrawal forks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import orjson

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_defect_withdrawal_seed_manifest"
MANIFEST_NAME = "withdrawal_seed_manifest.json"
SELF_HASH_FIELD = "payload_without_self_hash_sha256"
SOURCE_STEP = 4000
FINAL_STEP = 4375
INFERENCE_SEED = 20260811
CHECKPOINT_INTERVAL = 25
DESTINATION_KEEP_LAST = 4
DESTINATION_KEEP_INTERVAL = 250
EVALUATION_INTERVAL = 125
TRAIN_SOURCE_MAX_EPOCHS = 1
PRODUCTION_OPERATIONS = tuple(range(11, 46))
PRODUCTION_ROWS_PER_OPERATION = 200
MODEL_PATH = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
    "models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/"
    "4861bd030e6fb92d94be3a1cecab89c2fac4b94a/"
    "id2-10_0.2easy_0.3medium_0.5hard/base"
)
SOURCE_TRAIN_DATASET_PATH = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k/train.jsonl")
CONTINUATION_TRAIN_DATASET_PATH = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/defect-withdrawal-v1/unseen-gradient-step4000/train.jsonl"
)
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_ROOT = Path("user/tianhaowu/rsci/configs/rl")
COMMON_CONFIG = CONFIG_ROOT / "defect_withdrawal_v1/common_step4000_smoke.toml"
IMPLEMENTATION_PATH = Path("user/tianhaowu/rsci/materialize_defect_withdrawal_forks.py")


@dataclass(frozen=True)
class BandExpectation:
    first_operation: int
    last_operation: int
    strict: int
    behavior_a: int
    answer_wrong: int

    @property
    def label(self) -> str:
        return f"op{self.first_operation}_{self.last_operation}"


@dataclass(frozen=True)
class EvaluationSpec:
    operations: tuple[int, ...]
    rows_per_operation: int
    expected_bands: tuple[BandExpectation, ...]


@dataclass(frozen=True)
class ArmSpec:
    name: str
    source_label: str
    source_root: Path
    output_root: Path
    base_config: Path
    common_config: Path
    arm_config: Path
    source_false_positive_rate: float
    continuation_false_positive_rate: float
    job_name: str
    source_training_dataset_path: Path
    continuation_training_dataset_path: Path
    evaluation: EvaluationSpec
    trainer_shard_count: int


P05_EVALUATION = EvaluationSpec(
    operations=PRODUCTION_OPERATIONS,
    rows_per_operation=PRODUCTION_ROWS_PER_OPERATION,
    expected_bands=(
        BandExpectation(11, 20, 354, 554, 1092),
        BandExpectation(21, 40, 26, 603, 3371),
        BandExpectation(41, 45, 0, 169, 831),
    ),
)
P00_EVALUATION = EvaluationSpec(
    operations=PRODUCTION_OPERATIONS,
    rows_per_operation=PRODUCTION_ROWS_PER_OPERATION,
    expected_bands=(
        BandExpectation(11, 20, 535, 589, 876),
        BandExpectation(21, 40, 50, 447, 3503),
        BandExpectation(41, 45, 0, 94, 906),
    ),
)


def _source_root(rate: str) -> Path:
    return Path(f"/checkpoint/ram-h100-2/tianhaowu/rsci/rl/base-op10-40-strict-r128-defect-answer-{rate}-eval11-45-v2")


def _output_root(name: str) -> Path:
    return Path(
        f"/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-withdrawal-v1/{name.replace('_', '-')}-s4000-smoke"
    )


ARMS = {
    "p05_on": ArmSpec(
        name="p05_on",
        source_label="p05",
        source_root=_source_root("p05"),
        output_root=_output_root("p05_on"),
        base_config=CONFIG_ROOT / "op10_40_strict_grpo_r128_defect_p05.toml",
        common_config=COMMON_CONFIG,
        arm_config=CONFIG_ROOT / "defect_withdrawal_v1/p05_on.toml",
        source_false_positive_rate=0.05,
        continuation_false_positive_rate=0.05,
        job_name="rsci-vd-withdraw-p05-on",
        source_training_dataset_path=SOURCE_TRAIN_DATASET_PATH,
        continuation_training_dataset_path=CONTINUATION_TRAIN_DATASET_PATH,
        evaluation=P05_EVALUATION,
        trainer_shard_count=8,
    ),
    "p05_off": ArmSpec(
        name="p05_off",
        source_label="p05",
        source_root=_source_root("p05"),
        output_root=_output_root("p05_off"),
        base_config=CONFIG_ROOT / "op10_40_strict_grpo_r128_defect_p05.toml",
        common_config=COMMON_CONFIG,
        arm_config=CONFIG_ROOT / "defect_withdrawal_v1/p05_off.toml",
        source_false_positive_rate=0.05,
        continuation_false_positive_rate=0.0,
        job_name="rsci-vd-withdraw-p05-off",
        source_training_dataset_path=SOURCE_TRAIN_DATASET_PATH,
        continuation_training_dataset_path=CONTINUATION_TRAIN_DATASET_PATH,
        evaluation=P05_EVALUATION,
        trainer_shard_count=8,
    ),
    "p00_clean": ArmSpec(
        name="p00_clean",
        source_label="p00",
        source_root=_source_root("p00"),
        output_root=_output_root("p00_clean"),
        base_config=CONFIG_ROOT / "op10_40_strict_grpo_r128_defect_p00.toml",
        common_config=COMMON_CONFIG,
        arm_config=CONFIG_ROOT / "defect_withdrawal_v1/p00_clean.toml",
        source_false_positive_rate=0.0,
        continuation_false_positive_rate=0.0,
        job_name="rsci-vd-withdraw-p00-clean",
        source_training_dataset_path=SOURCE_TRAIN_DATASET_PATH,
        continuation_training_dataset_path=CONTINUATION_TRAIN_DATASET_PATH,
        evaluation=P00_EVALUATION,
        trainer_shard_count=8,
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--arm", required=True, choices=sorted(ARMS))
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument("--require-pristine", action="store_true")
    return parser.parse_args()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(_canonical_json_bytes(value))


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Missing config field {'.'.join(keys)}")
        current = current[key]
    return current


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if isinstance(expected, float):
        if (
            isinstance(actual, bool)
            or not isinstance(actual, (int, float))
            or not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1e-15)
        ):
            raise ValueError(f"{label} must be {expected!r}, found {actual!r}")
        return
    if actual != expected:
        raise ValueError(f"{label} must be {expected!r}, found {actual!r}")


def _file_identity(path: Path, root: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _absolute_file_identity(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    resolved = expanded.resolve()
    if expanded.is_symlink() or not resolved.is_file():
        raise ValueError(f"Expected a regular file: {resolved}")
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _find_dataset_binding(value: Any, dataset_path: str, dataset_sha256: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        recorded_path = value.get("path", value.get("resolved_path"))
        if recorded_path == dataset_path and value.get("sha256") == dataset_sha256:
            return value
        for child in value.values():
            binding = _find_dataset_binding(child, dataset_path, dataset_sha256)
            if binding is not None:
                return binding
    elif isinstance(value, list):
        for child in value:
            binding = _find_dataset_binding(child, dataset_path, dataset_sha256)
            if binding is not None:
                return binding
    return None


def training_dataset_identity(path: Path) -> dict[str, Any]:
    dataset = _absolute_file_identity(path)
    manifest_path = Path(f"{path}.manifest.json")
    manifest = _absolute_file_identity(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    binding = _find_dataset_binding(payload, dataset["path"], dataset["sha256"])
    if binding is None:
        raise ValueError(f"Adjacent dataset manifest does not bind {dataset['path']} and its SHA-256")
    return {
        "dataset": dataset,
        "adjacent_manifest": manifest,
        "manifest_dataset_binding": binding,
    }


def _tree_identity(root: Path) -> list[dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Expected a regular directory: {root}")
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f"Seed component may not contain symlinks: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Seed component contains a special file: {path}")
        files.append(_file_identity(path, root))
    if not files:
        raise ValueError(f"Seed component is empty: {root}")
    return files


def _config_identities(repo_root: Path, spec: ArmSpec) -> list[dict[str, Any]]:
    records = []
    for relative in (spec.base_config, spec.common_config, spec.arm_config):
        pure = PurePosixPath(relative.as_posix())
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Unsafe repository-relative config path: {relative}")
        path = repo_root / relative
        record = _file_identity(path, repo_root)
        records.append(record)
    return records


def _validate_training_environment(
    orchestrator: dict[str, Any],
    false_positive_rate: float,
    dataset_path: Path,
    *,
    label: str,
    require_explicit_defect_contract: bool = False,
) -> None:
    envs = _nested(orchestrator, "train", "env")
    if not isinstance(envs, list) or len(envs) != 1 or not isinstance(envs[0], dict):
        raise ValueError(f"{label}.train.env must contain exactly one environment")
    env = envs[0]
    _require_equal(env.get("id"), "rsci-gsm-infinite", f"{label}.train.env.id")
    _require_equal(env.get("name"), "op10-40-strict", f"{label}.train.env.name")
    if "group_size" in env:
        _require_equal(env["group_size"], 128, f"{label}.train.env.group_size")
    args = env.get("args")
    if not isinstance(args, dict):
        raise ValueError(f"{label}.train.env.args must be an object")
    expected = {
        "dataset_path": str(dataset_path),
        "min_op": 10,
        "max_op": 40,
        "require_unique_prompts": True,
        "false_positive_rate": false_positive_rate,
        "defect_seed": 20260805,
    }
    for key, value in expected.items():
        _require_equal(args.get(key), value, f"{label}.train.env.args.{key}")
    defect_contract = {
        "false_positive_rates_by_op": {},
        "false_positive_scope": "answer_correct_strict_wrong",
        "false_negative_rate": 0.0,
        "defect_draw_scope": "trajectory",
        "defect_assignment": "individual",
        "defect_gate_mode": "none",
        "defect_gate_probability": 1.0,
        "behavior_tax_c0": 0.0,
        "strict_reward_weight": 1.0,
    }
    for key, value in defect_contract.items():
        if require_explicit_defect_contract or key in args:
            _require_equal(args.get(key), value, f"{label}.train.env.args.{key}")


def _validate_eval_environments(orchestrator: dict[str, Any], interval: int, *, label: str) -> None:
    evaluation = orchestrator.get("eval")
    if not isinstance(evaluation, dict):
        raise ValueError(f"{label}.eval must be an object")
    _require_equal(evaluation.get("interval"), interval, f"{label}.eval.interval")
    envs = evaluation.get("env")
    if not isinstance(envs, list) or len(envs) != len(PRODUCTION_OPERATIONS):
        raise ValueError(f"{label}.eval.env must contain exactly 35 environments")
    observed_operations = []
    for env in envs:
        if not isinstance(env, dict):
            raise ValueError(f"{label}.eval.env contains a non-object")
        args = env.get("args")
        if not isinstance(args, dict):
            raise ValueError(f"{label}.eval.env.args must be an object")
        operation = args.get("min_op")
        if isinstance(operation, bool) or not isinstance(operation, int):
            raise ValueError(f"{label}.eval.env has an invalid min_op")
        observed_operations.append(operation)
        _require_equal(args.get("max_op"), operation, f"{label}.eval OP{operation} max_op")
        _require_equal(env.get("id"), "rsci-gsm-infinite", f"{label}.eval OP{operation} id")
        _require_equal(env.get("name"), f"heldout-op{operation}-strict", f"{label}.eval OP{operation} name")
        if "interval" in env:
            _require_equal(env["interval"], interval, f"{label}.eval OP{operation} interval")
    if observed_operations != list(PRODUCTION_OPERATIONS):
        raise ValueError(f"{label}.eval operations differ: {observed_operations}")


def validate_source_configs(spec: ArmSpec) -> list[dict[str, Any]]:
    config_dir = spec.source_root / "configs"
    expected_names = {"trainer.toml", "orchestrator.toml", "inference.toml"}
    observed_names = {path.name for path in config_dir.glob("*.toml")}
    if observed_names != expected_names:
        raise ValueError(f"Unexpected source config set: {sorted(observed_names)}")
    trainer = _load_toml(config_dir / "trainer.toml")
    orchestrator = _load_toml(config_dir / "orchestrator.toml")
    inference = _load_toml(config_dir / "inference.toml")

    _require_equal(trainer.get("output_dir"), str(spec.source_root), "source trainer.output_dir")
    _require_equal(trainer.get("max_steps"), 10000, "source trainer.max_steps")
    _require_equal(_nested(trainer, "model", "name"), str(MODEL_PATH), "source trainer.model.name")
    _require_equal(_nested(trainer, "model", "seq_len"), 2048, "source trainer.model.seq_len")
    _require_equal(_nested(trainer, "optim", "type"), "adamw", "source trainer.optim.type")
    _require_equal(_nested(trainer, "optim", "lr"), 1e-6, "source trainer.optim.lr")
    _require_equal(_nested(trainer, "scheduler", "type"), "constant", "source trainer.scheduler.type")
    _require_equal(_nested(trainer, "ckpt", "interval"), CHECKPOINT_INTERVAL, "source trainer.ckpt.interval")
    _require_equal(_nested(trainer, "ckpt", "keep_last"), 4, "source trainer.ckpt.keep_last")
    _require_equal(_nested(trainer, "ckpt", "keep_interval"), 100, "source trainer.ckpt.keep_interval")
    for key in ("weights_only", "skip_progress", "skip_scheduler", "skip_dataloader", "skip_optimizer"):
        _require_equal(_nested(trainer, "ckpt", key), False, f"source trainer.ckpt.{key}")

    _require_equal(
        orchestrator.get("output_dir"), str(spec.source_root / "run_default"), "source orchestrator.output_dir"
    )
    _require_equal(orchestrator.get("max_steps"), 10000, "source orchestrator.max_steps")
    _require_equal(orchestrator.get("batch_size"), 512, "source orchestrator.batch_size")
    _require_equal(orchestrator.get("group_size"), 128, "source orchestrator.group_size")
    _require_equal(orchestrator.get("seq_len"), 2048, "source orchestrator.seq_len")
    _require_equal(
        _nested(orchestrator, "student", "model", "name"), str(MODEL_PATH), "source orchestrator.student.model.name"
    )
    _validate_training_environment(
        orchestrator,
        spec.source_false_positive_rate,
        spec.source_training_dataset_path,
        label="source orchestrator",
    )
    _require_equal(_nested(orchestrator, "ckpt", "interval"), CHECKPOINT_INTERVAL, "source orchestrator.ckpt.interval")
    _require_equal(_nested(orchestrator, "ckpt", "keep_last"), 4, "source orchestrator.ckpt.keep_last")
    _require_equal(_nested(orchestrator, "ckpt", "keep_interval"), 100, "source orchestrator.ckpt.keep_interval")
    _validate_eval_environments(orchestrator, 25, label="source orchestrator")

    _require_equal(_nested(inference, "model", "name"), str(MODEL_PATH), "source inference.model.name")
    _require_equal(_nested(inference, "model", "max_model_len"), 2048, "source inference.model.max_model_len")
    return [_file_identity(config_dir / name, spec.source_root) for name in sorted(expected_names)]


def validate_input_config_contract(spec: ArmSpec, repo_root: Path) -> None:
    base = _load_toml(repo_root / spec.base_config)
    common = _load_toml(repo_root / spec.common_config)
    arm = _load_toml(repo_root / spec.arm_config)

    _require_equal(base.get("output_dir"), str(spec.source_root), "base output_dir")
    _require_equal(base.get("max_steps"), 10000, "base max_steps")
    _require_equal(base.get("seq_len"), 2048, "base seq_len")
    _require_equal(_nested(base, "model", "name"), str(MODEL_PATH), "base model.name")
    _require_equal(_nested(base, "trainer", "optim", "lr"), 1e-6, "base trainer.optim.lr")
    _require_equal(_nested(base, "trainer", "scheduler", "type"), "constant", "base trainer.scheduler.type")
    _require_equal(_nested(base, "orchestrator", "rollouts_per_example"), 128, "base rollouts_per_example")
    _require_equal(_nested(base, "ckpt", "interval"), CHECKPOINT_INTERVAL, "base ckpt.interval")
    _require_equal(_nested(base, "ckpt", "keep_last"), 4, "base ckpt.keep_last")
    _require_equal(_nested(base, "ckpt", "keep_interval"), 100, "base ckpt.keep_interval")
    _validate_training_environment(
        _nested(base, "orchestrator"),
        spec.source_false_positive_rate,
        spec.source_training_dataset_path,
        label="base orchestrator",
    )
    _validate_eval_environments(_nested(base, "orchestrator"), 25, label="base orchestrator")

    _require_equal(common.get("max_steps"), FINAL_STEP, "common max_steps")
    _require_equal(_nested(common, "ckpt", "resume_step"), SOURCE_STEP, "common ckpt.resume_step")
    _require_equal(_nested(common, "ckpt", "interval"), CHECKPOINT_INTERVAL, "common ckpt.interval")
    _require_equal(_nested(common, "ckpt", "keep_last"), DESTINATION_KEEP_LAST, "common ckpt.keep_last")
    _require_equal(
        _nested(common, "ckpt", "keep_interval"),
        DESTINATION_KEEP_INTERVAL,
        "common ckpt.keep_interval",
    )
    if "output_dir" in _nested(common, "ckpt"):
        raise ValueError("common ckpt.output_dir must be absent for an isolated fork")
    _require_equal(
        _nested(common, "orchestrator", "save_train_group_stats"),
        True,
        "common orchestrator.save_train_group_stats",
    )
    _require_equal(
        _nested(common, "orchestrator", "train_source_max_epochs"),
        TRAIN_SOURCE_MAX_EPOCHS,
        "common orchestrator.train_source_max_epochs",
    )
    _require_equal(
        _nested(common, "orchestrator", "eval", "interval"),
        EVALUATION_INTERVAL,
        "common orchestrator.eval.interval",
    )
    _require_equal(_nested(common, "inference", "seed"), INFERENCE_SEED, "common inference.seed")

    _require_equal(arm.get("output_dir"), str(spec.output_root), "arm output_dir")
    _require_equal(_nested(arm, "slurm", "job_name"), spec.job_name, "arm slurm.job_name")
    _require_equal(
        _nested(arm, "slurm", "project_dir"),
        str(spec.output_root / "source_snapshot"),
        "arm slurm.project_dir",
    )
    _validate_training_environment(
        _nested(arm, "orchestrator"),
        spec.continuation_false_positive_rate,
        spec.continuation_training_dataset_path,
        label="arm orchestrator",
        require_explicit_defect_contract=True,
    )


def validate_resolved_config_contract(spec: ArmSpec) -> list[dict[str, Any]]:
    config_dir = spec.output_root / "configs"
    expected_names = {"trainer.toml", "orchestrator.toml", "inference.toml"}
    observed_names = {path.name for path in config_dir.glob("*.toml")}
    if observed_names != expected_names:
        raise ValueError(f"Unexpected resolved config set: {sorted(observed_names)}")
    trainer = _load_toml(config_dir / "trainer.toml")
    orchestrator = _load_toml(config_dir / "orchestrator.toml")
    inference = _load_toml(config_dir / "inference.toml")

    _require_equal(trainer.get("output_dir"), str(spec.output_root), "resolved trainer.output_dir")
    _require_equal(trainer.get("max_steps"), FINAL_STEP, "resolved trainer.max_steps")
    _require_equal(_nested(trainer, "model", "name"), str(MODEL_PATH), "resolved trainer.model.name")
    _require_equal(_nested(trainer, "optim", "lr"), 1e-6, "resolved trainer.optim.lr")
    _require_equal(_nested(trainer, "scheduler", "type"), "constant", "resolved trainer.scheduler.type")
    checkpoint = _nested(trainer, "ckpt")
    _require_equal(checkpoint.get("resume_step"), SOURCE_STEP, "resolved trainer.ckpt.resume_step")
    _require_equal(checkpoint.get("interval"), CHECKPOINT_INTERVAL, "resolved trainer.ckpt.interval")
    _require_equal(checkpoint.get("keep_last"), DESTINATION_KEEP_LAST, "resolved trainer.ckpt.keep_last")
    _require_equal(
        checkpoint.get("keep_interval"),
        DESTINATION_KEEP_INTERVAL,
        "resolved trainer.ckpt.keep_interval",
    )
    if checkpoint.get("output_dir") is not None:
        raise ValueError("resolved trainer.ckpt.output_dir must be absent")
    for key in ("weights_only", "skip_progress", "skip_scheduler", "skip_dataloader", "skip_optimizer"):
        _require_equal(checkpoint.get(key), False, f"resolved trainer.ckpt.{key}")

    _require_equal(
        orchestrator.get("output_dir"), str(spec.output_root / "run_default"), "resolved orchestrator.output_dir"
    )
    _require_equal(orchestrator.get("max_steps"), FINAL_STEP, "resolved orchestrator.max_steps")
    _require_equal(orchestrator.get("group_size"), 128, "resolved orchestrator.group_size")
    _require_equal(orchestrator.get("save_train_group_stats"), True, "resolved orchestrator.save_train_group_stats")
    _require_equal(
        orchestrator.get("train_source_max_epochs"),
        TRAIN_SOURCE_MAX_EPOCHS,
        "resolved orchestrator.train_source_max_epochs",
    )
    _require_equal(
        orchestrator.get("max_consecutive_zero_trainable_batches"),
        500,
        "resolved orchestrator.max_consecutive_zero_trainable_batches",
    )
    if "max_finalized_groups" in orchestrator or "stop_when" in orchestrator:
        raise ValueError("resolved orchestrator must not use a finalized-group stop condition")
    _validate_training_environment(
        orchestrator,
        spec.continuation_false_positive_rate,
        spec.continuation_training_dataset_path,
        label="resolved orchestrator",
        require_explicit_defect_contract=True,
    )
    orchestrator_checkpoint = _nested(orchestrator, "ckpt")
    _require_equal(orchestrator_checkpoint.get("resume_step"), SOURCE_STEP, "resolved orchestrator.ckpt.resume_step")
    _require_equal(orchestrator_checkpoint.get("interval"), CHECKPOINT_INTERVAL, "resolved orchestrator.ckpt.interval")
    _require_equal(
        orchestrator_checkpoint.get("keep_last"),
        DESTINATION_KEEP_LAST,
        "resolved orchestrator.ckpt.keep_last",
    )
    _require_equal(
        orchestrator_checkpoint.get("keep_interval"),
        DESTINATION_KEEP_INTERVAL,
        "resolved orchestrator.ckpt.keep_interval",
    )
    if "output_dir" in orchestrator_checkpoint:
        raise ValueError("resolved orchestrator.ckpt.output_dir must be absent")
    _require_equal(
        orchestrator_checkpoint.get("skip_progress"),
        False,
        "resolved orchestrator.ckpt.skip_progress",
    )
    _validate_eval_environments(orchestrator, EVALUATION_INTERVAL, label="resolved orchestrator")

    _require_equal(inference.get("seed"), INFERENCE_SEED, "resolved inference.seed")
    _require_equal(_nested(inference, "model", "name"), str(MODEL_PATH), "resolved inference.model.name")
    return [_file_identity(config_dir / name, spec.output_root) for name in sorted(expected_names)]


def _validate_dcp_records(
    path: Path,
    files: list[dict[str, Any]],
    *,
    expected_shard_count: int,
) -> dict[str, Any]:
    from torch.distributed.checkpoint import FileSystemReader

    relative_paths = [record["relative_path"] for record in files]
    if ".metadata" not in relative_paths:
        raise FileNotFoundError(f"DCP metadata is missing: {path / '.metadata'}")
    shards = [name for name in relative_paths if name != ".metadata"]
    if not shards or any(re.fullmatch(r"__[0-9]+_0\.distcp", name) is None for name in shards):
        raise ValueError(f"DCP checkpoint has an unexpected shard set: {shards}")
    indices = sorted(int(re.fullmatch(r"__([0-9]+)_0\.distcp", name).group(1)) for name in shards)
    expected_indices = list(range(expected_shard_count))
    if indices != expected_indices:
        raise ValueError(f"DCP shard indices differ: {indices} != {expected_indices}")
    metadata = FileSystemReader(path).read_metadata()
    state_keys = sorted(metadata.state_dict_metadata)
    required_prefixes = ("app.model.", "app.optimizers.", "app.scheduler.", "app.progress.")
    missing_prefixes = [prefix for prefix in required_prefixes if not any(key.startswith(prefix) for key in state_keys)]
    if missing_prefixes:
        raise ValueError(f"DCP state metadata lacks required key families: {missing_prefixes}")
    progress_keys = [key for key in state_keys if key.startswith("app.progress.")]
    expected_progress_keys = ["app.progress.step", "app.progress.total_samples", "app.progress.total_tokens"]
    if progress_keys != expected_progress_keys:
        raise ValueError(f"DCP progress keys differ: {progress_keys}")
    storage_paths = sorted({str(record.relative_path) for record in metadata.storage_data.values()})
    if storage_paths != sorted(shards):
        raise ValueError(f"DCP metadata storage paths differ: {storage_paths} != {sorted(shards)}")
    return {
        "state_key_count": len(state_keys),
        "state_keys_sha256": canonical_json_sha256(state_keys),
        "storage_record_count": len(metadata.storage_data),
        "storage_paths": storage_paths,
    }


def validate_dcp_checkpoint(path: Path, *, expected_shard_count: int = 8) -> None:
    _validate_dcp_records(path, _tree_identity(path), expected_shard_count=expected_shard_count)


def load_progress(path: Path) -> dict[str, int]:
    import torch

    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict) or set(payload) != {"progress"}:
        raise ValueError(f"Unexpected orchestrator progress payload: {path}")
    progress = payload["progress"]
    result = {}
    for field in ("step", "total_tokens", "total_samples", "total_problems"):
        value = getattr(progress, field, None)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Invalid progress.{field} in {path}: {value!r}")
        result[field] = value
    if result["step"] != SOURCE_STEP:
        raise ValueError(f"Progress step must be {SOURCE_STEP}, found {result['step']}")
    return result


def _validate_stable_weight_records(path: Path, files: list[dict[str, Any]]) -> None:
    relative_paths = {record["relative_path"] for record in files}
    required = {"STABLE", "config.json", "model.safetensors"}
    if not required.issubset(relative_paths):
        raise FileNotFoundError(f"Stable weight directory is missing {sorted(required - relative_paths)}")
    if (path / "STABLE").stat().st_size != 0:
        raise ValueError(f"STABLE sentinel must be empty: {path / 'STABLE'}")
    config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not config:
        raise ValueError(f"Invalid model config: {path / 'config.json'}")
    if (path / "model.safetensors").stat().st_size == 0:
        raise ValueError(f"Model weights are empty: {path / 'model.safetensors'}")


def validate_stable_weights(path: Path) -> None:
    _validate_stable_weight_records(path, _tree_identity(path))


def inspect_evaluations(source_root: Path, evaluation: EvaluationSpec) -> dict[str, Any]:
    step_dir = source_root / "run_default" / "rollouts" / f"step_{SOURCE_STEP}"
    by_operation: dict[int, dict[str, int]] = {}
    files = []
    for operation in evaluation.operations:
        path = step_dir / f"eval_rollouts_heldout-op{operation}-strict.jsonl"
        files.append(_file_identity(path, source_root))
        counts = {"strict": 0, "behavior_a": 0, "answer_wrong": 0}
        indices: set[int] = set()
        rows = 0
        with path.open("rb") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise ValueError(f"Blank evaluation row at {path}:{line_number}")
                row = orjson.loads(line)
                if row.get("is_completed") is not True or row.get("errors") != []:
                    raise ValueError(f"Incomplete or errored evaluation row at {path}:{line_number}")
                task = row.get("task")
                metrics = row.get("metrics")
                rewards = row.get("rewards")
                if not isinstance(task, dict) or not isinstance(metrics, dict) or not isinstance(rewards, dict):
                    raise ValueError(f"Malformed evaluation row at {path}:{line_number}")
                index = task.get("idx")
                if isinstance(index, bool) or not isinstance(index, int) or index in indices:
                    raise ValueError(f"Invalid or duplicate task index at {path}:{line_number}")
                indices.add(index)
                strict = metrics.get("strict_dependency_graph_reward")
                answer = metrics.get("answer_correct_metric")
                reward = rewards.get("reward")
                if strict not in (0, 1, 0.0, 1.0) or answer not in (0, 1, 0.0, 1.0):
                    raise ValueError(f"Non-binary evaluation metric at {path}:{line_number}")
                if isinstance(reward, bool) or not isinstance(reward, (int, float)) or float(reward) != float(strict):
                    raise ValueError(f"Evaluation reward is not clean strict reward at {path}:{line_number}")
                strict_value = bool(strict)
                answer_value = bool(answer)
                if strict_value and not answer_value:
                    raise ValueError(f"Strict success lacks a correct answer at {path}:{line_number}")
                category = "strict" if strict_value else "behavior_a" if answer_value else "answer_wrong"
                counts[category] += 1
                rows += 1
        if rows != evaluation.rows_per_operation:
            raise ValueError(f"Expected {evaluation.rows_per_operation} rows in {path}, found {rows}")
        if sorted(indices) != list(range(evaluation.rows_per_operation)):
            raise ValueError(f"Task indices are not 0..{evaluation.rows_per_operation - 1} in {path}")
        by_operation[operation] = counts

    bands = {}
    for expected in evaluation.expected_bands:
        operations = list(range(expected.first_operation, expected.last_operation + 1))
        if any(operation not in by_operation for operation in operations):
            raise ValueError(f"Qualification band {expected.label} is outside the evaluation operation set")
        observed = {
            category: sum(by_operation[operation][category] for operation in operations)
            for category in ("strict", "behavior_a", "answer_wrong")
        }
        required = {
            "strict": expected.strict,
            "behavior_a": expected.behavior_a,
            "answer_wrong": expected.answer_wrong,
        }
        if observed != required:
            raise ValueError(f"Qualification counts for {expected.label} differ: {observed} != {required}")
        bands[expected.label] = observed

    totals = {
        category: sum(counts[category] for counts in by_operation.values())
        for category in ("strict", "behavior_a", "answer_wrong")
    }
    return {
        "step": SOURCE_STEP,
        "operations": list(evaluation.operations),
        "rows_per_operation": evaluation.rows_per_operation,
        "files": files,
        "counts_by_operation": {str(key): value for key, value in sorted(by_operation.items())},
        "qualification_bands": bands,
        "total_counts": totals,
    }


def _component_paths(root: Path) -> dict[str, Path]:
    return {
        "trainer_dcp": root / "checkpoints" / f"step_{SOURCE_STEP}" / "trainer",
        "orchestrator_progress": root / "run_default" / "checkpoints" / f"step_{SOURCE_STEP}" / "orchestrator",
        "stable_weights": root / "weights" / f"step_{SOURCE_STEP}",
    }


def _validate_seed_components(root: Path, *, trainer_shard_count: int) -> dict[str, Any]:
    components = _component_paths(root)
    identities = {name: _tree_identity(path) for name, path in components.items()}
    dcp_metadata = _validate_dcp_records(
        components["trainer_dcp"],
        identities["trainer_dcp"],
        expected_shard_count=trainer_shard_count,
    )
    progress_path = components["orchestrator_progress"] / "progress.pt"
    progress_files = identities["orchestrator_progress"]
    if [record["relative_path"] for record in progress_files] != ["progress.pt"]:
        raise ValueError(
            f"Orchestrator checkpoint must contain only progress.pt: {components['orchestrator_progress']}"
        )
    progress = load_progress(progress_path)
    _validate_stable_weight_records(components["stable_weights"], identities["stable_weights"])
    records = {
        name: {
            "relative_path": path.relative_to(root).as_posix(),
            "files": identities[name],
        }
        for name, path in components.items()
    }
    records["trainer_dcp"]["metadata"] = dcp_metadata
    return records | {"progress": progress}


def _copy_seed_components(source_root: Path, destination_root: Path) -> None:
    source_components = _component_paths(source_root)
    destination_components = _component_paths(destination_root)
    for name in ("trainer_dcp", "stable_weights"):
        destination_components[name].parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_components[name], destination_components[name], copy_function=shutil.copy2)
    destination_components["orchestrator_progress"].mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        source_components["orchestrator_progress"] / "progress.pt",
        destination_components["orchestrator_progress"] / "progress.pt",
    )


def _assert_independent_copies(
    source_root: Path,
    destination_root: Path,
    component_records: dict[str, Any],
) -> None:
    for name, source_component in _component_paths(source_root).items():
        destination_component = _component_paths(destination_root)[name]
        record = component_records.get(name)
        if not isinstance(record, dict) or not isinstance(record.get("files"), list):
            raise ValueError(f"Missing component records for {name}")
        for source_record in record["files"]:
            relative = Path(source_record["relative_path"])
            source_file = source_component / relative
            destination_file = destination_component / relative
            if os.path.samefile(source_file, destination_file):
                raise ValueError(f"Copied seed file is a hardlink to its source: {destination_file}")


def _manifest_payload(spec: ArmSpec, repo_root: Path) -> dict[str, Any]:
    source_configs = validate_source_configs(spec)
    validate_input_config_contract(spec, repo_root)
    source_components = _validate_seed_components(
        spec.source_root,
        trainer_shard_count=spec.trainer_shard_count,
    )
    evaluation = inspect_evaluations(spec.source_root, spec.evaluation)
    return {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "arm": spec.name,
        "source_label": spec.source_label,
        "source_step": SOURCE_STEP,
        "final_step": FINAL_STEP,
        "copy_contract": {
            "method": "shutil.copy2",
            "independent_regular_files": True,
            "hardlinks_forbidden": True,
            "broadcasts_copied": False,
        },
        "implementation": _file_identity(repo_root / IMPLEMENTATION_PATH, repo_root),
        "source": {
            "root": str(spec.source_root),
            "false_positive_rate": spec.source_false_positive_rate,
            "historical_rl_sbatch": _file_identity(spec.source_root / "rl.sbatch", spec.source_root),
            "configs": source_configs,
            "components": {key: value for key, value in source_components.items() if key != "progress"},
            "progress": source_components["progress"],
            "evaluation": evaluation,
        },
        "destination": {
            "root": str(spec.output_root),
            "false_positive_rate": spec.continuation_false_positive_rate,
            "training_dataset": training_dataset_identity(spec.continuation_training_dataset_path),
            "components": None,
            "config_inputs": _config_identities(repo_root, spec),
            "resolved_config_contract": {
                "resume_step": SOURCE_STEP,
                "max_steps": FINAL_STEP,
                "inference_seed": INFERENCE_SEED,
                "checkpoint_output_dir": None,
                "checkpoint_interval": CHECKPOINT_INTERVAL,
                "checkpoint_keep_last": DESTINATION_KEEP_LAST,
                "checkpoint_keep_interval": DESTINATION_KEEP_INTERVAL,
                "evaluation_interval": EVALUATION_INTERVAL,
                "evaluation_operations": list(PRODUCTION_OPERATIONS),
                "train_source_max_epochs": TRAIN_SOURCE_MAX_EPOCHS,
            },
        },
    }


def materialize_fork(spec: ArmSpec, *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    destination = spec.output_root.expanduser().resolve()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to overwrite withdrawal fork: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _manifest_payload(spec, repo_root)
    staging = destination.parent / f".{destination.name}.seed-staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        _copy_seed_components(spec.source_root, staging)
        destination_components = _validate_seed_components(
            staging,
            trainer_shard_count=spec.trainer_shard_count,
        )
        payload["destination"]["components"] = {
            key: value for key, value in destination_components.items() if key != "progress"
        }
        if payload["destination"]["components"] != payload["source"]["components"]:
            raise ValueError("Copied seed component hashes differ from their source")
        if destination_components["progress"] != payload["source"]["progress"]:
            raise ValueError("Copied orchestrator progress differs from its source")
        _assert_independent_copies(spec.source_root, staging, payload["source"]["components"])
        payload[SELF_HASH_FIELD] = canonical_json_sha256(payload)
        _write_json(staging / MANIFEST_NAME, payload)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return payload


def _read_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular manifest file: {path}")
    raw = path.read_bytes()

    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON key in {path}: {key!r}")
            value[key] = item
        return value

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    if not isinstance(value, dict) or raw != _canonical_json_bytes(value):
        raise ValueError(f"Manifest is not a canonical JSON object: {path}")
    recorded = value.get(SELF_HASH_FIELD)
    unhashed = dict(value)
    unhashed.pop(SELF_HASH_FIELD, None)
    if recorded != canonical_json_sha256(unhashed):
        raise ValueError(f"Withdrawal seed manifest self hash differs: {path}")
    if value.get("artifact_type") != ARTIFACT_TYPE or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unexpected withdrawal seed manifest type or schema: {path}")
    return value


def _validate_manifest_file_records(root: Path, records: list[dict[str, Any]], label: str) -> None:
    for record in records:
        relative = record.get("relative_path")
        if not isinstance(relative, str):
            raise ValueError(f"{label} has an invalid relative path record")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"{label} contains an unsafe relative path: {relative}")
        observed = _file_identity(root / Path(*pure.parts), root)
        if observed != record:
            raise ValueError(f"{label} file identity changed: {root / Path(*pure.parts)}")


def _expected_pristine_paths(root: Path, manifest: dict[str, Any]) -> tuple[set[Path], set[Path]]:
    allowed_files = {
        Path(MANIFEST_NAME),
        Path("source_provenance.json"),
        Path("source_provenance.lock"),
        Path("source_environment.freeze.txt"),
        Path("rl.sbatch"),
        Path("STATUS.md"),
        Path("configs/trainer.toml"),
        Path("configs/orchestrator.toml"),
        Path("configs/inference.toml"),
    }
    for component in manifest["destination"]["components"].values():
        component_root = Path(component["relative_path"])
        for file_record in component["files"]:
            allowed_files.add(component_root / file_record["relative_path"])
    allowed_dirs = {Path("."), Path("source_snapshot")}
    for file_path in allowed_files:
        allowed_dirs.update(file_path.parents)
    return allowed_files, allowed_dirs


def validate_pristine_destination(root: Path, manifest: dict[str, Any]) -> None:
    allowed_files, allowed_dirs = _expected_pristine_paths(root, manifest)
    for path in root.iterdir():
        relative = path.relative_to(root)
        if relative == Path("source_snapshot"):
            if path.is_symlink() or not path.is_dir():
                raise ValueError(f"source_snapshot is not a regular directory: {path}")
            continue
        if path.is_symlink():
            raise ValueError(f"Unexpected pre-submission symlink: {path}")
        if path.is_file():
            if relative not in allowed_files:
                raise ValueError(f"Unexpected pre-submission file: {path}")
            continue
        if not path.is_dir() or relative not in allowed_dirs:
            raise ValueError(f"Unexpected pre-submission artifact: {path}")
        for descendant in path.rglob("*"):
            descendant_relative = descendant.relative_to(root)
            if descendant.is_symlink():
                raise ValueError(f"Unexpected pre-submission symlink: {descendant}")
            if descendant.is_dir():
                if descendant_relative not in allowed_dirs:
                    raise ValueError(f"Unexpected pre-submission directory: {descendant}")
            elif descendant.is_file():
                if descendant_relative not in allowed_files:
                    raise ValueError(f"Unexpected pre-submission file: {descendant}")
            else:
                raise ValueError(f"Unexpected pre-submission special file: {descendant}")


def validate_materialized_fork(
    manifest_path: Path,
    *,
    spec: ArmSpec,
    repo_root: Path = REPO_ROOT,
    require_resolved_configs: bool = True,
    require_pristine: bool = False,
) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = _read_manifest(manifest_path)
    root = spec.output_root.expanduser().resolve()
    if manifest_path != root / MANIFEST_NAME:
        raise ValueError(f"Manifest must be at {root / MANIFEST_NAME}")
    if manifest.get("arm") != spec.name or manifest.get("source_label") != spec.source_label:
        raise ValueError("Manifest arm identity differs from the requested arm")
    if manifest.get("source_step") != SOURCE_STEP or manifest.get("final_step") != FINAL_STEP:
        raise ValueError("Manifest checkpoint contract changed")
    source = manifest.get("source")
    destination = manifest.get("destination")
    if not isinstance(source, dict) or not isinstance(destination, dict):
        raise ValueError("Manifest source or destination is not an object")
    _require_equal(source.get("root"), str(spec.source_root), "manifest source.root")
    _require_equal(destination.get("root"), str(root), "manifest destination.root")
    _require_equal(source.get("false_positive_rate"), spec.source_false_positive_rate, "manifest source rate")
    _require_equal(
        destination.get("false_positive_rate"),
        spec.continuation_false_positive_rate,
        "manifest continuation rate",
    )

    observed_source_configs = validate_source_configs(spec)
    if source.get("configs") != observed_source_configs:
        raise ValueError("Source config identities changed")
    if source.get("historical_rl_sbatch") != _file_identity(spec.source_root / "rl.sbatch", spec.source_root):
        raise ValueError("Historical source rl.sbatch identity changed")
    validate_input_config_contract(spec, repo_root)
    if manifest.get("implementation") != _file_identity(repo_root / IMPLEMENTATION_PATH, repo_root):
        raise ValueError("Materializer implementation identity changed")
    observed_inputs = _config_identities(repo_root, spec)
    if destination.get("config_inputs") != observed_inputs:
        raise ValueError("Config input identities changed")
    if destination.get("training_dataset") != training_dataset_identity(spec.continuation_training_dataset_path):
        raise ValueError("Continuation training dataset identity changed")

    observed_source_components = _validate_seed_components(
        spec.source_root,
        trainer_shard_count=spec.trainer_shard_count,
    )
    observed_destination_components = _validate_seed_components(
        root,
        trainer_shard_count=spec.trainer_shard_count,
    )
    source_component_records = {key: value for key, value in observed_source_components.items() if key != "progress"}
    destination_component_records = {
        key: value for key, value in observed_destination_components.items() if key != "progress"
    }
    if source.get("components") != source_component_records:
        raise ValueError("Source component hashes changed")
    if destination.get("components") != destination_component_records:
        raise ValueError("Destination component hashes changed")
    source_progress = observed_source_components["progress"]
    destination_progress = observed_destination_components["progress"]
    if source.get("progress") != source_progress or source_progress != destination_progress:
        raise ValueError("Source or destination progress differs from the manifest")
    _assert_independent_copies(spec.source_root, root, source_component_records)

    evaluation = inspect_evaluations(spec.source_root, spec.evaluation)
    if source.get("evaluation") != evaluation:
        raise ValueError("Source evaluation qualification changed")
    resolved_configs = validate_resolved_config_contract(spec) if require_resolved_configs else None
    if require_pristine:
        if not require_resolved_configs:
            raise ValueError("Pristine validation requires resolved configs")
        validate_pristine_destination(root, manifest)
    return {
        "manifest": str(manifest_path),
        "arm": spec.name,
        "source_step": SOURCE_STEP,
        "final_step": FINAL_STEP,
        "resolved_configs": resolved_configs,
        "pristine": require_pristine,
        "payload_without_self_hash_sha256": manifest[SELF_HASH_FIELD],
    }


def _spec_from_manifest(path: Path) -> ArmSpec:
    manifest = _read_manifest(path)
    arm = manifest.get("arm")
    if arm not in ARMS:
        raise ValueError(f"Unknown production withdrawal arm in manifest: {arm!r}")
    return ARMS[arm]


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        result = materialize_fork(ARMS[args.arm])
    else:
        spec = _spec_from_manifest(args.manifest.expanduser().resolve())
        result = validate_materialized_fork(
            args.manifest,
            spec=spec,
            require_resolved_configs=True,
            require_pristine=args.require_pristine,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
