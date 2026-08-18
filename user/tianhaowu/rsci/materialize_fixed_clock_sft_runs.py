#!/usr/bin/env python3
"""Materialize, validate, and submit the fixed-clock verifier-defect SFT arms."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w

STUDY_ID = "verifier_defect_fixed_clock_sft_v2"
SCHEMA_VERSION = 2
EXPECTED_SELECTION_SEEDS = (20260805, 20260806, 20260807)
EXPECTED_DOSES = ("1/400", "1/200", "1/100")
EXPECTED_BANK_OPERATIONS = (10, 11, 12, *range(15, 41))
EXPECTED_ANCHOR_OPERATIONS = (10, 11, 12)
EXPECTED_TREATMENT_OPERATIONS = tuple(range(21, 41))
EXPECTED_EXAMPLES_PER_OPERATION = 1_000
EXPECTED_SAMPLES_PER_PROMPT = 128
COMMON_STEPS = 64
SEQ_LEN = 2_048
BATCH_SIZE = 32
MICRO_BATCH_SIZE = 4
CHECKPOINT_INTERVAL = 8
DEFAULT_MODEL = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
    "models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/"
    "4861bd030e6fb92d94be3a1cecab89c2fac4b94a/"
    "id2-10_0.2easy_0.3medium_0.5hard/base"
)
DEFAULT_ARM_INDEX = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/"
    "frozen-base-op10-12-op15-40-r128-v1/fixed-clock-sft-v2/arm_index.json"
)
DEFAULT_LAUNCH_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/sft/verifier-defect-fixed-clock-v2")
SCRIPT_REPO_PATH = Path("user/tianhaowu/rsci/materialize_fixed_clock_sft_runs.py")
TEMPLATE_REPO_PATH = Path("user/tianhaowu/rsci/templates/single_gpu_sft_offline.sbatch.j2")
ACTIVATOR_REPO_PATH = Path("user/tianhaowu/rsci/scripts/activate_source_snapshot_sft.sh")
LAUNCH_MANIFEST_NAME = "launch_manifest.json"
SUBMISSION_NAME = "submission.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
CONTROL_TMUX_SOCKET = "/tmp/codex-rsci-control-20260806.sock"
CONTROL_TMUX_SESSION = "codex-rsci-control-20260806"
CONTROL_TMUX_WINDOW = "Launcher"

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
    "fixed_m_and_anchor_max_steps": COMMON_STEPS,
    "fixed_raw_max_steps": "max(64, ceil(2 * rows / 32))",
    "checkpoint_interval": CHECKPOINT_INTERVAL,
    "checkpoint_policy": "weights-only eval snapshots every 8 steps plus final; retain all",
    "checkpoint_resumable": False,
    "failure_policy": "restart from step 0 in a fresh output directory; never resume from weights-only state",
    "gpus_per_arm": 1,
    "exclusive_node": False,
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
    materialize.add_argument("--arm-index", type=Path, default=DEFAULT_ARM_INDEX)
    materialize.add_argument("--base-model", type=Path, default=DEFAULT_MODEL)
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


def _digest_field(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def file_identity(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError(f"Input file path must be absolute: {path}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def directory_identity(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError(f"Input directory path must be absolute: {path}")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    digest = hashlib.sha256(b"rsci-input-directory-v1\0")
    file_count = 0
    size_bytes = 0
    for entry in sorted(resolved.rglob("*"), key=lambda item: item.relative_to(resolved).as_posix()):
        relative = entry.relative_to(resolved).as_posix()
        if entry.is_symlink():
            target = entry.resolve()
            if not target.is_file():
                raise ValueError(f"Model directory contains a non-file symlink: {entry}")
        elif entry.is_dir():
            continue
        elif entry.is_file():
            target = entry
        else:
            raise ValueError(f"Unsupported model-directory entry: {entry}")
        content_digest = file_sha256(target)
        size = target.stat().st_size
        _digest_field(digest, relative.encode())
        _digest_field(digest, str(size).encode())
        _digest_field(digest, content_digest.encode())
        file_count += 1
        size_bytes += size
    if file_count == 0:
        raise ValueError(f"Model directory contains no files: {resolved}")
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "file_count": file_count,
        "size_bytes": size_bytes,
        "sha256": digest.hexdigest(),
    }


def frozen_bank_model_identity(path: Path) -> dict[str, Any]:
    configured = path.expanduser()
    resolved = configured.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    inventory = []
    for item in sorted(candidate for candidate in resolved.rglob("*") if candidate.is_file()):
        inventory.append(
            {
                "path": item.relative_to(resolved).as_posix(),
                "size_bytes": item.stat().st_size,
                "sha256": file_sha256(item),
            }
        )
    if not inventory:
        raise ValueError(f"Base-model directory contains no files: {resolved}")
    return {
        "configured_name": str(configured),
        "resolved_path": str(resolved),
        "file_count": len(inventory),
        "size_bytes": sum(item["size_bytes"] for item in inventory),
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


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def write_toml_once(path: Path, payload: dict[str, Any]) -> None:
    encoded = tomli_w.dumps(payload).encode()
    if path.exists():
        if not path.is_file() or path.read_bytes() != encoded:
            raise ValueError(f"Refusing to replace a different launch config: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(encoded)
    partial.replace(path)


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} is not a SHA-256 digest")
    return value


def max_steps_for_arm(arm: dict[str, Any]) -> int:
    if arm["metadata"]["clock"] != "fixed_raw":
        return COMMON_STEPS
    return max(COMMON_STEPS, two_pass_steps(arm))


def two_pass_steps(arm: dict[str, Any]) -> int | None:
    if arm["metadata"]["clock"] != "fixed_raw":
        return None
    return (2 * arm["rows"] + BATCH_SIZE - 1) // BATCH_SIZE


def readout_steps(arm: dict[str, Any]) -> list[int]:
    return sorted({COMMON_STEPS, max_steps_for_arm(arm)})


def checkpoint_steps(max_steps: int) -> list[int]:
    steps = list(range(CHECKPOINT_INTERVAL, max_steps, CHECKPOINT_INTERVAL))
    steps.append(max_steps)
    return steps


def schedule_label(arm: dict[str, Any]) -> str:
    return "at_least_two_dataset_passes" if arm["metadata"]["clock"] == "fixed_raw" else "common_64_steps"


def _verify_recorded_file(record: object, path: Path, label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"{label} is not an identity object")
    identity = file_identity(path)
    recorded_path = record.get("path")
    if not isinstance(recorded_path, str) or Path(recorded_path).expanduser().resolve() != path.resolve():
        raise ValueError(f"{label} path differs from {path}")
    for field in ("size_bytes", "sha256"):
        if record.get(field) != identity[field]:
            raise ValueError(f"{label}.{field} differs from the current file")
    return identity


def validate_study_inputs(arm_index_path: Path, base_model: Path) -> dict[str, Any]:
    arm_index_path = arm_index_path.expanduser().resolve()
    base_model = base_model.expanduser()
    index = read_json_object(arm_index_path)
    if index.get("schema_version") != SCHEMA_VERSION or index.get("study_id") != STUDY_ID:
        raise ValueError("Arm index has the wrong schema or study identity")
    bank_contract_sha256 = _require_sha256(index.get("bank_contract_sha256"), "bank_contract_sha256")
    protocol = index.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError("Arm index has no protocol object")
    expected_protocol = {
        "bank_operations": list(EXPECTED_BANK_OPERATIONS),
        "anchor_operations": list(EXPECTED_ANCHOR_OPERATIONS),
        "treatment_operations": list(EXPECTED_TREATMENT_OPERATIONS),
        "examples_per_operation": EXPECTED_EXAMPLES_PER_OPERATION,
        "samples_per_prompt": EXPECTED_SAMPLES_PER_PROMPT,
        "selection_seeds": list(EXPECTED_SELECTION_SEEDS),
        "doses": list(EXPECTED_DOSES),
        "target_count": 512,
        "anchor_count": 512,
        "selection_hash_domain": "rsci-fixed-clock-sft-v2",
    }
    for field, expected in expected_protocol.items():
        if protocol.get(field) != expected:
            raise ValueError(f"Arm-index protocol {field}={protocol.get(field)!r}, expected {expected!r}")
    strict_dead_contract = protocol.get("strict_dead_contract")
    expected_treatment_rows = EXPECTED_EXAMPLES_PER_OPERATION * EXPECTED_SAMPLES_PER_PROMPT
    expected_strict_dead_fields = {
        "required": True,
        "definition": "every frozen trajectory in every treatment operation has strict perfect=false",
        "operations": list(EXPECTED_TREATMENT_OPERATIONS),
        "rows_per_operation": expected_treatment_rows,
        "strict_positive_counts_by_op": {str(operation): 0 for operation in EXPECTED_TREATMENT_OPERATIONS},
        "verified_rows_by_op": {str(operation): expected_treatment_rows for operation in EXPECTED_TREATMENT_OPERATIONS},
    }
    if not isinstance(strict_dead_contract, dict) or any(
        strict_dead_contract.get(field) != expected for field, expected in expected_strict_dead_fields.items()
    ):
        raise ValueError("Arm-index strict-dead treatment contract is missing or differs")
    candidate_counts_by_op = strict_dead_contract.get("candidate_counts_by_op")
    expected_operation_keys = {str(operation) for operation in EXPECTED_TREATMENT_OPERATIONS}
    if (
        not isinstance(candidate_counts_by_op, dict)
        or set(candidate_counts_by_op) != expected_operation_keys
        or any(
            isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= expected_treatment_rows
            for count in candidate_counts_by_op.values()
        )
    ):
        raise ValueError("Arm-index strict-dead candidate counts are invalid")
    if set(strict_dead_contract) != {*expected_strict_dead_fields, "candidate_counts_by_op"}:
        raise ValueError("Arm-index strict-dead treatment contract has unexpected fields")
    expected_arm_count_contract = {
        "assignments": ["behavior", "shuffled", "global", "iid"],
        "bsg_canonical_specs_per_seed": 5,
        "iid_canonical_specs_per_seed": 3,
        "distinct_training_arms": 55,
        "minimum_dose_aliases": 9,
        "arm_index_entries": 64,
    }
    if protocol.get("arm_count_contract") != expected_arm_count_contract:
        raise ValueError("Arm-index arm-count contract differs")

    distinct = index.get("distinct_training_arms")
    if not isinstance(distinct, list) or not distinct:
        raise ValueError("Arm index has no distinct training arms")
    if any(not isinstance(label, str) or re.fullmatch(r"[a-z0-9_]+", label) is None for label in distinct):
        raise ValueError("Arm-index distinct training arms contain an invalid label")
    if len(set(distinct)) != len(distinct) or "c0_anchor" not in distinct:
        raise ValueError("Arm-index distinct training arms are duplicated or omit c0_anchor")
    canonical_labels = set(distinct)
    entries = index.get("arms")
    if not isinstance(entries, list) or len(entries) < len(canonical_labels):
        raise ValueError("Arm index has fewer entries than distinct training arms")
    if any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Arm index contains a non-object arm entry")
    by_label = {entry.get("label"): entry for entry in entries}
    if None in by_label or len(by_label) != len(entries):
        raise ValueError("Arm index contains missing or duplicate labels")
    alias_labels = set(by_label) - canonical_labels

    tokenizer = index.get("tokenizer")
    if not isinstance(tokenizer, dict):
        raise ValueError("Arm index has no tokenizer identity")
    configured_tokenizer = tokenizer.get("configured_path")
    if not isinstance(configured_tokenizer, str):
        raise ValueError("Arm index tokenizer has no configured path")
    if Path(configured_tokenizer).expanduser().resolve() != base_model.resolve():
        raise ValueError("Configured base model differs from the tokenizer/model used to build the datasets")
    model_identity = directory_identity(base_model)
    bank_inputs = index.get("inputs")
    if not isinstance(bank_inputs, dict):
        raise ValueError("Arm index has no frozen-bank input identities")
    bank_manifest_record = bank_inputs.get("manifest")
    if not isinstance(bank_manifest_record, dict) or not isinstance(bank_manifest_record.get("path"), str):
        raise ValueError("Arm index has no frozen-bank manifest identity")
    bank_manifest_path = Path(bank_manifest_record["path"]).expanduser().resolve()
    bank_manifest_identity = _verify_recorded_file(
        bank_manifest_record,
        bank_manifest_path,
        "inputs.manifest",
    )
    bank_manifest = read_json_object(bank_manifest_path)
    bank_contract = bank_manifest.get("contract")
    if (
        not isinstance(bank_contract, dict)
        or bank_manifest.get("contract_sha256") != canonical_json_sha256(bank_contract)
        or bank_manifest.get("contract_sha256") != bank_contract_sha256
    ):
        raise ValueError("Frozen-bank manifest contract identity differs")
    bank_model = bank_contract.get("model")
    current_bank_model = frozen_bank_model_identity(base_model)
    if bank_model != current_bank_model:
        raise ValueError("Base-model bytes differ from the model frozen into the rollout bank")
    chat_record = tokenizer.get("chat_template")
    if not isinstance(chat_record, dict) or not isinstance(chat_record.get("path"), str):
        raise ValueError("Arm index has no chat-template identity")
    chat_template_path = Path(chat_record["path"]).expanduser().resolve()
    chat_template_identity = _verify_recorded_file(chat_record, chat_template_path, "tokenizer.chat_template")

    canonical_arms: list[dict[str, Any]] = []
    for label in sorted(canonical_labels):
        entry = by_label[label]
        if entry.get("alias_of") is not None:
            raise ValueError(f"Distinct arm {label} unexpectedly aliases another arm")
        dataset_path_value = entry.get("dataset_path")
        manifest_path_value = entry.get("manifest_path")
        if not isinstance(dataset_path_value, str) or not isinstance(manifest_path_value, str):
            raise ValueError(f"Arm {label} has invalid dataset/manifest paths")
        dataset_path = Path(dataset_path_value).expanduser().resolve()
        manifest_path = Path(manifest_path_value).expanduser().resolve()
        if manifest_path != dataset_path / "manifest.json":
            raise ValueError(f"Arm {label} manifest is not inside its dataset directory")
        parquet_path = dataset_path / "train-00000-of-00001.parquet"
        arm_manifest = read_json_object(manifest_path)
        if arm_manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Arm {label} manifest has the wrong schema")
        if arm_manifest.get("bank_contract_sha256") != bank_contract_sha256:
            raise ValueError(f"Arm {label} has a different bank contract")
        if arm_manifest.get("strict_dead_contract") != strict_dead_contract:
            raise ValueError(f"Arm {label} has a different strict-dead treatment contract")
        if arm_manifest.get("tokenizer") != tokenizer:
            raise ValueError(f"Arm {label} tokenizer identity differs from the arm index")
        manifest_arm = arm_manifest.get("arm")
        if not isinstance(manifest_arm, dict) or manifest_arm.get("label") != label:
            raise ValueError(f"Arm {label} manifest metadata differs")
        metadata = {
            field: value
            for field, value in entry.items()
            if field
            not in {
                "label",
                "alias_of",
                "dataset_path",
                "manifest_path",
                "parquet_sha256",
                "rows",
            }
        }
        if manifest_arm != {"label": label, **metadata}:
            raise ValueError(f"Arm {label} manifest metadata differs from arm_index.json")
        if metadata.get("clock") not in {"anchor_only", "fixed_m", "fixed_raw"}:
            raise ValueError(f"Arm {label} has an invalid clock")
        if metadata.get("assignment") not in {"clean", "behavior", "shuffled", "global", "iid"}:
            raise ValueError(f"Arm {label} has an invalid assignment")
        rows = entry.get("rows")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1 or arm_manifest.get("rows") != rows:
            raise ValueError(f"Arm {label} has an invalid row count")
        weight_mass = arm_manifest.get("assistant_weight_mass")
        if not isinstance(weight_mass, (int, float)) or not math.isclose(weight_mass, rows, abs_tol=1e-8):
            raise ValueError(f"Arm {label} assistant-weight mass is not one unit per example")
        max_tokens = arm_manifest.get("max_model_input_tokens")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 0 < max_tokens <= SEQ_LEN:
            raise ValueError(f"Arm {label} contains an invalid rendered sequence length")
        parquet_identity = file_identity(parquet_path)
        parquet_sha256 = _require_sha256(entry.get("parquet_sha256"), f"arms.{label}.parquet_sha256")
        if parquet_identity["sha256"] != parquet_sha256:
            raise ValueError(f"Arm {label} parquet bytes differ from arm_index.json")
        _verify_recorded_file(arm_manifest.get("parquet"), parquet_path, f"arms.{label}.parquet")
        arm = {
            "label": label,
            "metadata": metadata,
            "rows": rows,
            "dataset_path": str(dataset_path),
            "dataset_manifest": file_identity(manifest_path),
            "parquet": parquet_identity,
        }
        expected_sft_contract = {
            **STATIC_SFT_CONTRACT,
            "max_steps": max_steps_for_arm(arm),
            "ckpt.interval": CHECKPOINT_INTERVAL,
            "readout_steps": readout_steps(arm),
            "two_pass_steps": two_pass_steps(arm),
            "schedule": schedule_label(arm),
        }
        if arm_manifest.get("sft_contract") != expected_sft_contract:
            raise ValueError(f"Arm {label} SFT contract differs from its row-count schedule")
        arm.update(
            {
                "max_steps": max_steps_for_arm(arm),
                "checkpoint_steps": checkpoint_steps(max_steps_for_arm(arm)),
                "readout_steps": readout_steps(arm),
                "two_pass_steps": two_pass_steps(arm),
                "schedule": schedule_label(arm),
            }
        )
        canonical_arms.append(arm)

    assignments = ("behavior", "shuffled", "global")
    expected_dimensions = (
        {
            (seed, "fixed_m", dose, assignment)
            for seed in EXPECTED_SELECTION_SEEDS
            for dose in EXPECTED_DOSES
            for assignment in assignments
        }
        | {
            (seed, "fixed_raw", dose, assignment)
            for seed in EXPECTED_SELECTION_SEEDS
            for dose in EXPECTED_DOSES[1:]
            for assignment in assignments
        }
        | {(seed, "fixed_raw", dose, "iid") for seed in EXPECTED_SELECTION_SEEDS for dose in EXPECTED_DOSES}
    )
    observed_dimensions = {
        (
            arm["metadata"]["selection_seed"],
            arm["metadata"]["clock"],
            arm["metadata"]["dose"],
            arm["metadata"]["assignment"],
        )
        for arm in canonical_arms
        if arm["label"] != "c0_anchor"
    }
    if observed_dimensions != expected_dimensions or len(observed_dimensions) != len(canonical_arms) - 1:
        raise ValueError("Distinct arms do not cover every predeclared seed/clock/dose/assignment cell")
    anchor_arm = next(arm for arm in canonical_arms if arm["label"] == "c0_anchor")
    if (
        anchor_arm["rows"] != protocol["anchor_count"]
        or anchor_arm["metadata"]["clock"] != "anchor_only"
        or anchor_arm["metadata"]["assignment"] != "clean"
        or anchor_arm["metadata"]["dose"] != "0/1"
    ):
        raise ValueError("Anchor-only arm differs from the predeclared clean control")
    expected_fixed_m_rows = protocol["anchor_count"] + protocol["target_count"]
    if any(arm["rows"] != expected_fixed_m_rows for arm in canonical_arms if arm["metadata"]["clock"] == "fixed_m"):
        raise ValueError("Fixed-M arms do not contain anchor_count + target_count rows")
    arms_by_dimension = {
        (
            arm["metadata"]["selection_seed"],
            arm["metadata"]["clock"],
            arm["metadata"]["dose"],
            arm["metadata"]["assignment"],
        ): arm
        for arm in canonical_arms
        if arm["label"] != "c0_anchor"
    }
    for seed in EXPECTED_SELECTION_SEEDS:
        expected_raw_prefix = arms_by_dimension[(seed, "fixed_m", EXPECTED_DOSES[0], "behavior")]["metadata"].get(
            "raw_prefix_trajectories"
        )
        raw_prefixes = {
            arms_by_dimension[(seed, "fixed_raw", dose, "iid")]["metadata"].get("raw_prefix_trajectories")
            for dose in EXPECTED_DOSES
        }
        raw_prefixes.update(
            arms_by_dimension[(seed, "fixed_raw", dose, assignment)]["metadata"].get("raw_prefix_trajectories")
            for dose in EXPECTED_DOSES[1:]
            for assignment in assignments
        )
        if raw_prefixes != {expected_raw_prefix}:
            raise ValueError(f"Fixed-raw arms for seed {seed} do not share the minimum-dose behavior prefix")
        for dose in EXPECTED_DOSES:
            iid_arm = arms_by_dimension[(seed, "fixed_raw", dose, "iid")]
            metadata = iid_arm["metadata"]
            treatment_rows = iid_arm["rows"] - protocol["anchor_count"]
            eligible_rows = metadata.get("iid_eligible_rows")
            realized_rate = metadata.get("iid_realized_rate")
            paired_behavior_count = (
                protocol["target_count"]
                if dose == EXPECTED_DOSES[0]
                else arms_by_dimension[(seed, "fixed_raw", dose, "behavior")]["rows"] - protocol["anchor_count"]
            )
            if (
                isinstance(eligible_rows, bool)
                or not isinstance(eligible_rows, int)
                or eligible_rows < treatment_rows
                or not isinstance(realized_rate, (int, float))
                or not math.isclose(realized_rate, treatment_rows / eligible_rows, abs_tol=1e-15)
                or metadata.get("candidate_overlap") != paired_behavior_count
            ):
                raise ValueError(f"IID arm for seed={seed}, dose={dose} violates its nominal-p contract")

    observed_alias_dimensions = set()
    for alias_label in sorted(alias_labels):
        alias = by_label[alias_label]
        canonical_label = alias.get("alias_of")
        if not isinstance(canonical_label, str) or canonical_label not in canonical_labels:
            raise ValueError(f"Alias {alias_label} does not point to a distinct training arm")
        canonical = by_label[canonical_label]
        for field in ("dataset_path", "manifest_path", "parquet_sha256", "rows"):
            if alias.get(field) != canonical.get(field):
                raise ValueError(f"Alias {alias_label} differs from {canonical_label} in {field}")
        dimension = (
            alias.get("selection_seed"),
            alias.get("clock"),
            alias.get("dose"),
            alias.get("assignment"),
        )
        observed_alias_dimensions.add(dimension)
        if (
            canonical.get("selection_seed"),
            canonical.get("clock"),
            canonical.get("dose"),
            canonical.get("assignment"),
        ) != (dimension[0], "fixed_m", dimension[2], dimension[3]):
            raise ValueError(f"Alias {alias_label} does not target its matched fixed-M arm")
    expected_alias_dimensions = {
        (seed, "fixed_raw", EXPECTED_DOSES[0], assignment)
        for seed in EXPECTED_SELECTION_SEEDS
        for assignment in assignments
    }
    if observed_alias_dimensions != expected_alias_dimensions or len(alias_labels) != len(expected_alias_dimensions):
        raise ValueError("Arm index does not contain every predeclared minimum-dose byte alias")

    return {
        "arm_index": file_identity(arm_index_path),
        "bank_contract_sha256": bank_contract_sha256,
        "base_model": model_identity,
        "frozen_bank_manifest": bank_manifest_identity,
        "frozen_bank_model": current_bank_model,
        "chat_template": chat_template_identity,
        "arms": canonical_arms,
    }


def active_source_state(source_run_dir: Path) -> SourceState:
    source_run_dir = source_run_dir.expanduser().resolve()
    from source_provenance import verify_snapshot

    provenance = verify_snapshot(source_run_dir, require_launch=False)
    source_root = Path(provenance["snapshot_path"]).resolve()
    expected_script = (source_root / SCRIPT_REPO_PATH).resolve()
    if Path(__file__).resolve() != expected_script:
        raise ValueError(
            "Materialization must run from the pinned source snapshot; source "
            f"{source_root / ACTIVATOR_REPO_PATH} first"
        )
    if os.environ.get("RSCI_SOURCE_SNAPSHOT") != str(source_root):
        raise ValueError("Pinned SFT source activation is missing from the current environment")
    for path in (source_root / TEMPLATE_REPO_PATH, source_root / ACTIVATOR_REPO_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    return SourceState(source_run_dir, source_root, provenance)


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
    ]


def launch_config(
    arm: dict[str, Any],
    *,
    launch_root: Path,
    source: SourceState,
    base_model: Path,
    chat_template: Path,
) -> dict[str, Any]:
    label = arm["label"]
    max_steps = arm["max_steps"]
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
        "max_steps": max_steps,
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
        "optim": {
            "type": "adamw",
            "lr": 1e-4,
        },
        "scheduler": {"type": "constant"},
        "ckpt": {
            "interval": CHECKPOINT_INTERVAL,
            "weights_only": True,
            "keep_last": len(arm["checkpoint_steps"]),
            "weights": {
                "save_sharded": True,
                "save_format": "safetensors",
            },
        },
        "deployment": {
            "type": "single_node",
            "num_gpus": 1,
            "gpus_per_node": 1,
        },
        "slurm": {
            "job_name": f"rsci-vd-fcsft-{label}",
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
            "name": f"vd-fixed-clock-sft-{label}",
            "group": STUDY_ID,
            "tags": _wandb_tags(arm),
            "offline": False,
        },
        "log": {
            "level": "info",
            "interval": 1.0,
            "ranks_filter": [0],
        },
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
    config = read_toml(config_path)
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
        raise ValueError("Weights-only fixed-clock runs must restart from step 0, never resume")
    if "val" in config:
        raise ValueError("Fixed-clock SFT arms must not use an in-training validation set")
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
        "validate-arm",
        f"--arm-label {arm_label}",
    )
    for value in required:
        if value not in script:
            raise ValueError(f"Generated SFT script lacks required text {value!r}: {path}")
    if "--exclusive" in script:
        raise ValueError(f"Generated SFT script requests an exclusive node: {path}")


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    launch_root = args.launch_root.expanduser().resolve()
    source_run_dir = (args.source_run_dir or launch_root).expanduser().resolve()
    source = active_source_state(source_run_dir)
    inputs = validate_study_inputs(args.arm_index, args.base_model)
    if launch_root == source.root or source.root.parent != source.run_dir:
        raise ValueError("Source snapshot must be rooted under the source run directory, separate from launch outputs")
    plan = {
        "study_id": STUDY_ID,
        "launch_root": str(launch_root),
        "source_run_dir": str(source.run_dir),
        "source_snapshot": str(source.root),
        "arm_count": len(inputs["arms"]),
        "gpu_count_per_arm": 1,
        "total_requested_gpus_if_all_run": len(inputs["arms"]),
    }
    if args.dry_run:
        return plan

    manifest_path = launch_root / LAUNCH_MANIFEST_NAME
    if manifest_path.exists():
        validated = validate_launch_manifest(manifest_path)
        return {**plan, "manifest_sha256": validated["manifest_sha256"], "already_materialized": True}
    launch_root.mkdir(parents=True, exist_ok=True)
    arms_by_label = {arm["label"]: arm for arm in inputs["arms"]}
    records: list[dict[str, Any]] = []
    base_model = Path(inputs["base_model"]["path"])
    chat_template = Path(inputs["chat_template"]["path"])
    for label in sorted(arms_by_label):
        arm = arms_by_label[label]
        config = launch_config(
            arm,
            launch_root=launch_root,
            source=source,
            base_model=base_model,
            chat_template=chat_template,
        )
        launch_config_path = launch_root / "launch_configs" / f"{label}.toml"
        write_toml_once(launch_config_path, config)
        output_dir = launch_root / "runs" / label
        resolved_config_path = output_dir / "configs" / "sft.toml"
        sbatch_path = output_dir / "sft.sbatch"
        existing = (resolved_config_path.exists(), sbatch_path.exists())
        if existing == (False, False):
            _run(
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "sft",
                    "@",
                    str(launch_config_path),
                    "--dry-run",
                ],
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
                "launch_config": file_identity(launch_config_path),
                "resolved_config": file_identity(resolved_config_path),
                "sbatch": file_identity(sbatch_path),
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
            "provenance_manifest": file_identity(source.run_dir / "source_provenance.json"),
        },
        "inputs": {
            key: inputs[key]
            for key in (
                "arm_index",
                "bank_contract_sha256",
                "base_model",
                "frozen_bank_manifest",
                "frozen_bank_model",
                "chat_template",
            )
        },
        "implementation": file_identity(source.root / SCRIPT_REPO_PATH),
        "template": file_identity(source.root / TEMPLATE_REPO_PATH),
        "activator": file_identity(source.root / ACTIVATOR_REPO_PATH),
        "training_contract": LAUNCH_TRAINING_CONTRACT,
        "arm_count": len(records),
        "arms": records,
    }
    write_json_atomic(manifest_path, manifest)
    validated = validate_launch_manifest(manifest_path)
    return {**plan, "manifest_sha256": validated["manifest_sha256"], "already_materialized": False}


def _verify_identity(identity: object, label: str) -> dict[str, Any]:
    if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
        raise ValueError(f"Launch manifest {label} has no file identity")
    current = file_identity(Path(identity["path"]))
    if current != identity:
        raise ValueError(f"Launch manifest {label} identity differs")
    return current


def _verify_directory_identity(identity: object, label: str) -> dict[str, Any]:
    if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
        raise ValueError(f"Launch manifest {label} has no directory identity")
    current = directory_identity(Path(identity["path"]))
    if current != identity:
        raise ValueError(f"Launch manifest {label} directory identity differs")
    return current


def validate_launch_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = read_json_object(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("study_id") != STUDY_ID:
        raise ValueError("Launch manifest has the wrong schema or study identity")
    launch_root = Path(manifest.get("launch_root", "")).resolve()
    if manifest_path != launch_root / LAUNCH_MANIFEST_NAME:
        raise ValueError("Launch manifest is not at the recorded launch root")
    arms = manifest.get("arms")
    if not isinstance(arms, list) or not arms or manifest.get("arm_count") != len(arms):
        raise ValueError("Launch manifest has an invalid arm list")
    if manifest.get("training_contract") != LAUNCH_TRAINING_CONTRACT:
        raise ValueError("Launch manifest training contract differs")
    labels = [arm.get("label") for arm in arms if isinstance(arm, dict)]
    if len(labels) != len(arms) or labels != sorted(labels) or len(set(labels)) != len(labels):
        raise ValueError("Launch manifest arm ordering/labels are invalid")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Launch manifest has no input identities")
    _verify_identity(inputs.get("arm_index"), "inputs.arm_index")
    arm_index = read_json_object(Path(inputs["arm_index"]["path"]))
    if labels != sorted(arm_index.get("distinct_training_arms", [])):
        raise ValueError("Launch manifest arms differ from arm_index.json")
    _verify_directory_identity(inputs.get("base_model"), "inputs.base_model")
    _verify_identity(inputs.get("frozen_bank_manifest"), "inputs.frozen_bank_manifest")
    if frozen_bank_model_identity(Path(inputs["base_model"]["path"])) != inputs.get("frozen_bank_model"):
        raise ValueError("Launch manifest frozen-bank model identity differs")
    _verify_identity(inputs.get("chat_template"), "inputs.chat_template")
    _verify_identity(manifest.get("implementation"), "implementation")
    _verify_identity(manifest.get("template"), "template")
    _verify_identity(manifest.get("activator"), "activator")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("Launch manifest has no source identity")
    _require_sha256(source.get("source_tree_sha256"), "source.source_tree_sha256")
    _verify_identity(source.get("provenance_manifest"), "source.provenance_manifest")
    base_model = Path(inputs["base_model"]["path"])
    chat_template = Path(inputs["chat_template"]["path"])
    for arm in arms:
        expected_schedule = {
            "max_steps": max_steps_for_arm(arm),
            "checkpoint_steps": checkpoint_steps(max_steps_for_arm(arm)),
            "readout_steps": readout_steps(arm),
            "two_pass_steps": two_pass_steps(arm),
            "schedule": schedule_label(arm),
        }
        for field, expected in expected_schedule.items():
            if arm.get(field) != expected:
                raise ValueError(f"Launch manifest arm {arm['label']} has an invalid {field}")
        for field in ("dataset_manifest", "parquet", "launch_config", "resolved_config", "sbatch"):
            _verify_identity(arm.get(field), f"arms.{arm['label']}.{field}")
        resolved_config = Path(arm["resolved_config"]["path"])
        output_dir = Path(arm["output_dir"])
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
        "manifest_sha256": file_sha256(manifest_path),
    }


def validate_one_arm(manifest_path: Path, arm_label: str, resolved_config: Path) -> dict[str, Any]:
    validated = validate_launch_manifest(manifest_path)
    manifest = validated["manifest"]
    arm = next((record for record in manifest["arms"] if record["label"] == arm_label), None)
    if arm is None:
        raise ValueError(f"Unknown fixed-clock SFT arm: {arm_label}")
    if resolved_config.expanduser().resolve() != Path(arm["resolved_config"]["path"]).resolve():
        raise ValueError(f"Runtime resolved config differs for arm {arm_label}")
    return {
        "study_id": STUDY_ID,
        "arm_label": arm_label,
        "launch_manifest_sha256": validated["manifest_sha256"],
        "resolved_config_sha256": arm["resolved_config"]["sha256"],
        "parquet_sha256": arm["parquet"]["sha256"],
    }


def submission_commands(manifest: dict[str, Any]) -> list[list[str]]:
    return [
        [
            "env",
            "-u",
            "SBATCH_OUTPUT",
            "-u",
            "SBATCH_ERROR",
            "sbatch",
            "--parsable",
            arm["sbatch"]["path"],
        ]
        for arm in manifest["arms"]
    ]


def require_control_tmux() -> dict[str, str]:
    tmux_value = os.environ.get("TMUX")
    if not tmux_value:
        raise ValueError("Actual fixed-clock SFT submission must run inside the control tmux session")
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


def submit(args: argparse.Namespace) -> dict[str, Any]:
    launch_root = args.launch_root.expanduser().resolve()
    validated = validate_launch_manifest(launch_root / LAUNCH_MANIFEST_NAME)
    manifest = validated["manifest"]
    commands = submission_commands(manifest)
    if args.dry_run:
        return {
            "study_id": STUDY_ID,
            "launch_manifest_sha256": validated["manifest_sha256"],
            "commands": [shlex.join(command) for command in commands],
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual submission requires --confirm-study-id {STUDY_ID}")
    control_tmux = require_control_tmux()
    submission_path = launch_root / SUBMISSION_NAME
    if submission_path.exists():
        submission = read_json_object(submission_path)
        if submission.get("launch_manifest_sha256") != validated["manifest_sha256"]:
            raise ValueError("Existing submission ledger belongs to a different launch manifest")
    else:
        submission = {
            "schema_version": SCHEMA_VERSION,
            "study_id": STUDY_ID,
            "launch_manifest_sha256": validated["manifest_sha256"],
            "control_tmux": control_tmux,
            "jobs": {},
        }
    jobs = submission.get("jobs")
    if not isinstance(jobs, dict):
        raise ValueError("Submission ledger has no jobs object")
    if submission.get("control_tmux") != control_tmux:
        raise ValueError("Existing submission ledger belongs to a different control tmux target")
    for arm, command in zip(manifest["arms"], commands, strict=True):
        label = arm["label"]
        if label in jobs:
            continue
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        job_id = result.stdout.strip().split(";", maxsplit=1)[0]
        if not job_id.isdigit():
            raise ValueError(f"sbatch returned an invalid job id for {label}: {result.stdout!r}")
        jobs[label] = {
            "job_id": int(job_id),
            "sbatch_sha256": arm["sbatch"]["sha256"],
        }
        write_json_atomic(submission_path, submission)
    return {
        "study_id": STUDY_ID,
        "launch_manifest_sha256": validated["manifest_sha256"],
        "submitted_jobs": len(jobs),
        "submission_path": str(submission_path),
    }


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        result = materialize(args)
    elif args.command == "validate":
        result = validate_launch_manifest(args.launch_root / LAUNCH_MANIFEST_NAME)
        result = {
            "study_id": STUDY_ID,
            "manifest_path": result["manifest_path"],
            "manifest_sha256": result["manifest_sha256"],
            "arm_count": len(result["manifest"]["arms"]),
        }
    elif args.command == "validate-arm":
        result = validate_one_arm(args.launch_manifest, args.arm_label, args.resolved_config)
    elif args.command == "submit":
        result = submit(args)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
