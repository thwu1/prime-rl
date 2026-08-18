#!/usr/bin/env python3
"""Build and independently validate the known-cost boundary production preflight."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import materialize_known_cost_tagged_bank as tagged_bank
import orjson
import rsci_gsm_infinite as runtime
import verifiers as vf

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_boundary_preflight"
ANALYSIS_ID = "rsci-known-cost-boundary-production-preflight-v1"
BIT_VECTOR_DOMAIN = "rsci-known-cost-boundary-bit-vector-v1"
PHYSICAL_GROUP_SIZE = 128
GATE_PROBABILITY = 1 / 3
NEUTRAL_TAG_COUNT = 6
BEHAVIOR_TAX = 0.03
STRICT_REWARD_WEIGHT = 1.0
BLOCK_SEEDS = (20260808, 20260809, 20260810)
SELECTED_TAGS_BY_BLOCK = {
    20260808: (0, 1),
    20260809: (2, 3),
    20260810: (4, 5),
}
DOSES = (
    ("p0075", 0.0075),
    ("p0125", 0.0125),
    ("p0225", 0.0225),
    ("p0375", 0.0375),
)
TEMPLATES = (
    "crazy_zootopia",
    "movie_festival_awards",
    "teachers_in_school",
)
TAG_PREFIXES = tuple(f"<rsci_context_{index}>\n" for index in range(NEUTRAL_TAG_COUNT))
EXPECTED_BASE_CONFIG_SHA256 = "3c0de6727bbef8e80e34fa1c6f7ee7e1d582dad79fe18c046641b0e62682be91"
EXPECTED_COMMON_CONFIG_SHA256 = "f856832a0b38cf212582e1fc840dfdff6458041b6869ed60f61ab3da44e2a870"

RSCI_ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_CONFIG = RSCI_ROOT / "configs" / "rl" / "op10_40_strict_grpo_r128_defect_p00.toml"
DEFAULT_CONFIG_ROOT = RSCI_ROOT / "configs" / "rl" / "known_cost_boundary_v1"
DEFAULT_BANK_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/known-cost-boundary-v1")

PRE_RUN_COMMAND = (
    'source user/tianhaowu/rsci/scripts/activate_source_snapshot.sh "$OUTPUT_DIR"; '
    "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; "
    'INTERNAL_HOSTS=${HOSTNAMES_STR// /,}; export NO_PROXY="localhost,127.0.0.1,$INTERNAL_HOSTS"; '
    'export no_proxy="$NO_PROXY"; export VLLM_CACHE_ROOT="${SLURM_TMPDIR:-/tmp}/vllm-cache-${SLURM_JOB_ID}"'
)

EXPECTED_COMMON_CONFIG = {
    "max_steps": 3000,
    "ckpt": {"interval": 25, "keep_last": 4, "keep_interval": 25},
    "wandb": {"group": "verifier-defect-known-cost-boundary-v1"},
    "orchestrator": {
        "batch_size": 512,
        "rollouts_per_example": 128,
        "save_train_group_stats": True,
        "max_finalized_groups": 20000,
        "stop_when": {
            "min_steps": 1500,
            "min_finalized_groups": 12000,
            "step_multiple": 50,
        },
        "eval": {"interval": 3001, "skip_first_step": True},
    },
}


@dataclass(frozen=True)
class FileIdentity:
    path: str
    size_bytes: int
    sha256: str
    rows: int | None = None

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.rows is not None:
            value["rows"] = self.rows
        return value


@dataclass(frozen=True)
class ArmContract:
    filename: str
    seed: int
    condition: str
    run_label: str
    family: str
    nominal_rate: float
    behavior_tax: float
    gate_mode: str
    selected_tags: tuple[int, int]


@dataclass(frozen=True)
class BankRow:
    sample_id: str
    operation: int
    template: str
    neutral_tag_index: int


@dataclass(frozen=True)
class BankResult:
    report: dict[str, Any]
    rows: tuple[BankRow, ...]
    source_projection_sha256: str


class PackedBitVector:
    def __init__(self, bit_length: int) -> None:
        if isinstance(bit_length, bool) or not isinstance(bit_length, int) or bit_length < 0:
            raise ValueError("bit_length must be a non-negative integer")
        self.bit_length = bit_length
        self.content = bytearray((bit_length + 7) // 8)
        self.ones = 0

    def set(self, index: int) -> None:
        if not 0 <= index < self.bit_length:
            raise IndexError(index)
        mask = 1 << (7 - index % 8)
        byte_index = index // 8
        if self.content[byte_index] & mask:
            return
        self.content[byte_index] |= mask
        self.ones += 1

    def is_subset_of(self, other: PackedBitVector) -> bool:
        if self.bit_length != other.bit_length:
            return False
        return all(left & ~right == 0 for left, right in zip(self.content, other.content, strict=True))

    def record(self) -> dict[str, Any]:
        header = canonical_json_bytes(
            {
                "domain": BIT_VECTOR_DOMAIN,
                "bit_length": self.bit_length,
                "packing": "row-major, then rollout-slot ascending; MSB-first within each byte; zero tail padding",
            }
        )
        return {
            "bit_length": self.bit_length,
            "one_count": self.ones,
            "zero_count": self.bit_length - self.ones,
            "packed_size_bytes": len(self.content),
            "sha256": hashlib.sha256(header + b"\0" + self.content).hexdigest(),
        }


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_report_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def file_identity(path: Path, *, rows: int | None = None) -> FileIdentity:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    digest = hashlib.sha256()
    size = 0
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return FileIdentity(str(resolved), size, digest.hexdigest(), rows)


def _read_json_object(path: Path) -> tuple[bytes, dict[str, Any]]:
    content = path.expanduser().resolve().read_bytes()

    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON key {key!r} in {path}")
            value[key] = item
        return value

    value = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=no_duplicate_keys,
        parse_constant=lambda item: (_ for _ in ()).throw(ValueError(f"Non-finite JSON value {item} in {path}")),
    )
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return content, value


def _require_dict(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _load_toml(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    with resolved.open("rb") as handle:
        return tomllib.load(handle)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def arm_contracts() -> tuple[ArmContract, ...]:
    arms = []
    for seed in BLOCK_SEEDS:
        selected_tags = SELECTED_TAGS_BY_BLOCK[seed]
        arms.extend(
            [
                ArmContract(
                    f"b{seed}_clean.toml",
                    seed,
                    "clean",
                    "clean",
                    "clean",
                    0.0,
                    0.0,
                    "group",
                    selected_tags,
                ),
                ArmContract(
                    f"b{seed}_tax.toml",
                    seed,
                    "tax",
                    "tax",
                    "tax",
                    0.0,
                    BEHAVIOR_TAX,
                    "group",
                    selected_tags,
                ),
            ]
        )
        for dose_label, nominal_rate in DOSES:
            for family, gate_mode in (("g", "group"), ("t", "neutral_tag")):
                condition = f"{family}_{dose_label}"
                arms.append(
                    ArmContract(
                        f"b{seed}_{condition}.toml",
                        seed,
                        condition,
                        f"{family}-{dose_label}",
                        family,
                        nominal_rate,
                        BEHAVIOR_TAX,
                        gate_mode,
                        selected_tags,
                    )
                )
    return tuple(arms)


def _expected_train_environment(arm: ArmContract, bank_root: Path) -> dict[str, Any]:
    args: dict[str, Any] = {
        "dataset_path": str((bank_root / f"block-{arm.seed}" / "train.jsonl").resolve()),
        "min_op": 10,
        "max_op": 40,
        "require_unique_prompts": True,
        "false_positive_rate": arm.nominal_rate,
        "false_positive_scope": "answer_correct_strict_wrong",
        "false_negative_rate": 0.0,
        "defect_assignment": "behavior_group",
        "defect_draw_scope": "sample_slot",
        "defect_eligible_slot_count": PHYSICAL_GROUP_SIZE,
        "defect_gate_probability": GATE_PROBABILITY,
        "defect_neutral_tag_count": NEUTRAL_TAG_COUNT,
        "defect_reference_neutral_tags": list(arm.selected_tags),
        "behavior_tax_c0": arm.behavior_tax,
        "strict_reward_weight": STRICT_REWARD_WEIGHT,
        "defect_seed": arm.seed,
        "defect_gate_mode": arm.gate_mode,
    }
    if arm.gate_mode == "neutral_tag":
        args["defect_selected_neutral_tags"] = list(arm.selected_tags)
    return {
        "id": "rsci-gsm-infinite",
        "name": "op10-40-known-cost",
        "pool": {"type": "static", "num_workers": 16},
        "args": args,
    }


def _expected_overlay(arm: ArmContract, bank_root: Path) -> dict[str, Any]:
    output_dir = (
        Path("/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1")
        / f"block-{arm.seed}"
        / arm.run_label
    )
    seed_suffix = arm.seed % 100
    selected_label = f"tags-{arm.selected_tags[0]}-{arm.selected_tags[1]}"
    common_tags = [
        "gsm-infinite",
        "op10-40",
        "strict-target",
        "grpo",
        "r128",
        "known-cost-boundary-v1",
    ]
    if arm.family == "clean":
        condition_tags = ["tagged-clean"]
    elif arm.family == "tax":
        condition_tags = ["tagged-tax-only"]
    elif arm.family == "g":
        condition_tags = ["hidden-group", "g", arm.condition.removeprefix("g_"), "c003"]
    else:
        condition_tags = ["persistent-tag", "t", arm.condition.removeprefix("t_"), "c003"]
    tags = [
        *common_tags,
        *condition_tags[:2],
        "alpha1of3",
        *condition_tags[2:],
        selected_label,
        f"block-{arm.seed}",
        "paired-sample-slot",
        "train31k",
    ]
    return {
        "output_dir": str(output_dir),
        "slurm": {
            "job_name": f"rsci-kc1-b{seed_suffix:02d}-{arm.run_label}",
            "project_dir": str(output_dir / "source_snapshot"),
            "pre_run_command": PRE_RUN_COMMAND,
        },
        "wandb": {
            "name": f"known-cost-v1-b{arm.seed}-{arm.run_label}",
            "tags": tags,
        },
        "inference": {"seed": arm.seed},
        "orchestrator": {"train": {"env": [_expected_train_environment(arm, bank_root)]}},
    }


def _validate_base_contract(base: dict[str, Any], tokenizer_path: Path) -> None:
    tokenizer = tokenizer_path.expanduser().resolve()
    model = Path(_require_dict(base.get("model"), "base.model").get("name", "")).expanduser().resolve()
    configured_tokenizer = (
        Path(_require_dict(base.get("tokenizer"), "base.tokenizer").get("name", "")).expanduser().resolve()
    )
    if model != tokenizer or configured_tokenizer != tokenizer:
        raise ValueError("Explicit tokenizer must equal the frozen base model and tokenizer paths")
    if base.get("seq_len") != 2048:
        raise ValueError("Frozen base seq_len must equal 2048")
    if _require_dict(base.get("deployment"), "base.deployment") != {
        "type": "multi_node",
        "num_train_nodes": 1,
        "num_infer_nodes": 1,
        "num_infer_replicas": 4,
        "gpus_per_node": 8,
    }:
        raise ValueError("Frozen base deployment contract differs")
    trainer = _require_dict(base.get("trainer"), "base.trainer")
    if _require_dict(trainer.get("optim"), "base.trainer.optim") != {
        "type": "adamw",
        "lr": 1e-6,
        "weight_decay": 0.01,
        "max_norm": 1.0,
    }:
        raise ValueError("Frozen base optimizer contract differs")
    if _require_dict(trainer.get("scheduler"), "base.trainer.scheduler") != {"type": "constant"}:
        raise ValueError("Frozen base scheduler contract differs")
    orchestrator = _require_dict(base.get("orchestrator"), "base.orchestrator")
    if orchestrator.get("batch_size") != 512 or orchestrator.get("rollouts_per_example") != 128:
        raise ValueError("Frozen base batch/group contract differs")


def audit_launch_configs(
    base_config_path: Path,
    config_root: Path,
    bank_root: Path,
    tokenizer_path: Path,
) -> tuple[dict[str, Any], dict[str, FileIdentity], tuple[ArmContract, ...]]:
    base_config_path = base_config_path.expanduser().resolve()
    config_root = config_root.expanduser().resolve()
    bank_root = bank_root.expanduser().resolve()
    common_path = config_root / "common.toml"
    arms = arm_contracts()
    overlay_paths = sorted(config_root.glob("b*.toml"))
    if [path.name for path in overlay_paths] != sorted(arm.filename for arm in arms):
        raise ValueError("Known-cost overlay inventory differs from the frozen 30-arm contract")

    identities = {
        "base": file_identity(base_config_path),
        "common": file_identity(common_path),
    }
    if identities["base"].sha256 != EXPECTED_BASE_CONFIG_SHA256:
        raise ValueError("Frozen strict p00 base config SHA-256 differs")
    if identities["common"].sha256 != EXPECTED_COMMON_CONFIG_SHA256:
        raise ValueError("Frozen known-cost common config SHA-256 differs")
    base = _load_toml(base_config_path)
    common = _load_toml(common_path)
    _validate_base_contract(base, tokenizer_path)
    if common != EXPECTED_COMMON_CONFIG:
        raise ValueError("Known-cost common config differs from the exact frozen contract")

    arm_reports: dict[str, Any] = {}
    unique_runtime_ids: dict[str, set[str]] = {
        "output_dir": set(),
        "job_name": set(),
        "project_dir": set(),
        "wandb_name": set(),
    }
    for arm in arms:
        path = config_root / arm.filename
        overlay = _load_toml(path)
        expected_overlay = _expected_overlay(arm, bank_root)
        if overlay != expected_overlay:
            raise ValueError(f"{arm.filename} differs from its exact frozen overlay contract")
        resolved = deep_merge(deep_merge(base, common), overlay)
        resolved_orchestrator = _require_dict(resolved.get("orchestrator"), f"{arm.filename}.orchestrator")
        if resolved.get("max_steps") != 3000:
            raise ValueError(f"{arm.filename} resolved max_steps differs")
        if resolved.get("ckpt") != EXPECTED_COMMON_CONFIG["ckpt"]:
            raise ValueError(f"{arm.filename} resolved checkpoint contract differs")
        for key in ("batch_size", "rollouts_per_example", "save_train_group_stats", "max_finalized_groups"):
            if resolved_orchestrator.get(key) != EXPECTED_COMMON_CONFIG["orchestrator"][key]:
                raise ValueError(f"{arm.filename} resolved orchestrator.{key} differs")
        if resolved_orchestrator.get("stop_when") != EXPECTED_COMMON_CONFIG["orchestrator"]["stop_when"]:
            raise ValueError(f"{arm.filename} resolved joint-stop contract differs")
        train = _require_dict(resolved_orchestrator.get("train"), f"{arm.filename}.orchestrator.train")
        if train.get("env") != [_expected_train_environment(arm, bank_root)]:
            raise ValueError(f"{arm.filename} resolved train environment differs")

        identities[arm.filename] = file_identity(path)
        identity_values = {
            "output_dir": str(resolved["output_dir"]),
            "job_name": str(resolved["slurm"]["job_name"]),
            "project_dir": str(resolved["slurm"]["project_dir"]),
            "wandb_name": str(resolved["wandb"]["name"]),
        }
        for key, value in identity_values.items():
            if value in unique_runtime_ids[key]:
                raise ValueError(f"{arm.filename} repeats {key}={value!r}")
            unique_runtime_ids[key].add(value)
        arm_reports[arm.filename] = {
            "block_seed": arm.seed,
            "condition": arm.condition,
            "family": arm.family,
            "gate_mode": arm.gate_mode,
            "selected_tags": list(arm.selected_tags),
            "nominal_p": arm.nominal_rate,
            "conditional_q": arm.nominal_rate / GATE_PROBABILITY,
            "behavior_tax_c0": arm.behavior_tax,
            "strict_reward_weight": STRICT_REWARD_WEIGHT,
            "overlay_identity": identities[arm.filename].as_dict(),
            "resolved_config_sha256": canonical_json_sha256(resolved),
            **identity_values,
        }
    return (
        {
            "composition": "deep merge in order base, common, one overlay; lists replace wholesale",
            "base": identities["base"].as_dict(),
            "common": identities["common"].as_dict(),
            "arm_count": len(arms),
            "blocks": list(BLOCK_SEEDS),
            "arms": arm_reports,
        },
        identities,
        arms,
    )


def _validate_tokenizer_record(record: object, tokenizer_path: Path) -> dict[str, Any]:
    facts = _require_dict(record, "tag_tokenization")
    tokenizer = tokenizer_path.expanduser().resolve()
    if Path(str(facts.get("path"))).expanduser().resolve() != tokenizer:
        raise ValueError("Tagged-bank tokenizer path differs from the explicit tokenizer")
    prefixes = facts.get("prefixes")
    if not isinstance(prefixes, list) or len(prefixes) != NEUTRAL_TAG_COUNT:
        raise ValueError("Tagged-bank tokenizer record must contain exactly six prefixes")
    token_counts = []
    for index, (prefix_record, expected_text) in enumerate(zip(prefixes, TAG_PREFIXES, strict=True)):
        prefix = _require_dict(prefix_record, f"tag_tokenization.prefixes[{index}]")
        if prefix.get("index") != index or prefix.get("text") != expected_text:
            raise ValueError(f"Tokenizer prefix {index} differs from the literal tag contract")
        if prefix.get("utf8_sha256") != hashlib.sha256(expected_text.encode()).hexdigest():
            raise ValueError(f"Tokenizer prefix {index} UTF-8 hash differs")
        token_ids = prefix.get("token_ids")
        if not isinstance(token_ids, list) or any(
            isinstance(token_id, bool) or not isinstance(token_id, int) for token_id in token_ids
        ):
            raise ValueError(f"Tokenizer prefix {index} has invalid token ids")
        if prefix.get("token_count") != len(token_ids):
            raise ValueError(f"Tokenizer prefix {index} token count differs")
        token_counts.append(len(token_ids))
    if facts.get("equal_token_counts") is not True or len(set(token_counts)) != 1:
        raise ValueError("Known-cost prefixes do not have equal token counts")
    if facts.get("common_token_count") != token_counts[0]:
        raise ValueError("Known-cost common token count differs")

    artifact_records = facts.get("artifact_files")
    if not isinstance(artifact_records, list) or not artifact_records:
        raise ValueError("Tokenizer identity has no artifact files")
    verified_artifacts = []
    for raw_record in artifact_records:
        artifact_record = _require_dict(raw_record, "tag_tokenization.artifact_files[]")
        name = artifact_record.get("name")
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError("Tokenizer artifact name is invalid")
        identity = file_identity(tokenizer / name)
        if identity.sha256 != artifact_record.get("sha256") or identity.size_bytes != artifact_record.get("bytes"):
            raise ValueError(f"Tokenizer artifact identity differs: {name}")
        verified_artifacts.append(identity.as_dict())
    return {
        "path": str(tokenizer),
        "tokenizer_class": facts.get("tokenizer_class"),
        "vocab_size": facts.get("vocab_size"),
        "common_token_count": facts.get("common_token_count"),
        "prefixes": prefixes,
        "artifact_files": verified_artifacts,
        "artifact_inventory_sha256": canonical_json_sha256(verified_artifacts),
    }


def audit_tagged_bank(manifest_path: Path, tokenizer_path: Path, expected_seed: int) -> BankResult:
    manifest_path = manifest_path.expanduser().resolve()
    validated = tagged_bank.validate_tagged_bank(
        manifest_path=manifest_path,
        tokenizer_path=tokenizer_path.expanduser().resolve(),
    )
    manifest = _require_dict(validated.get("manifest"), "validated tagged-bank manifest")
    if manifest.get("block_seed") != expected_seed:
        raise ValueError(f"{manifest_path} has block seed {manifest.get('block_seed')}, expected {expected_seed}")
    if manifest.get("artifact_type") != "rsci_known_cost_neutral_tag_bank":
        raise ValueError(f"{manifest_path} has the wrong artifact type")
    output_record = _require_dict(manifest.get("output"), f"{manifest_path}.output")
    input_record = _require_dict(manifest.get("input"), f"{manifest_path}.input")
    output_path = Path(str(output_record.get("path"))).expanduser().resolve()
    if output_path != manifest_path.with_name("train.jsonl"):
        raise ValueError(f"{manifest_path} output path differs from its block train.jsonl")
    tokenizer = _validate_tokenizer_record(manifest.get("tag_tokenization"), tokenizer_path)

    ids: set[str] = set()
    prompt_hashes: set[bytes] = set()
    effective_prompt_hashes: set[bytes] = set()
    tag_counts: Counter[int] = Counter()
    stratum_counts: Counter[tuple[int, str, int]] = Counter()
    rows: list[BankRow] = []
    source_projection = hashlib.sha256()
    source_projection_size = 0
    output_digest = hashlib.sha256()
    output_size = 0
    with output_path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip() or not line.endswith(b"\n"):
                raise ValueError(f"{output_path}:{line_number} is not a nonblank newline-terminated JSONL record")
            output_digest.update(line)
            output_size += len(line)
            value = orjson.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{output_path}:{line_number} is not a JSON object")
            required = {"id", "op", "template", "prompt", "problem", "solution", "neutral_tag_index"}
            missing = sorted(required - value.keys())
            if missing:
                raise ValueError(f"{output_path}:{line_number} is missing fields: {missing}")
            sample_id = value["id"]
            operation = value["op"]
            template = value["template"]
            prompt = value["prompt"]
            tag_index = value["neutral_tag_index"]
            if not isinstance(sample_id, str) or not sample_id or sample_id in ids:
                raise ValueError(f"{output_path}:{line_number} has an invalid or duplicate sample id")
            if isinstance(operation, bool) or not isinstance(operation, int) or operation not in range(10, 41):
                raise ValueError(f"{output_path}:{line_number} has an invalid operation")
            if not isinstance(template, str) or template not in TEMPLATES:
                raise ValueError(f"{output_path}:{line_number} has an invalid template")
            if not isinstance(prompt, str) or not prompt:
                raise ValueError(f"{output_path}:{line_number} has an invalid prompt")
            if isinstance(tag_index, bool) or not isinstance(tag_index, int) or tag_index not in range(6):
                raise ValueError(f"{output_path}:{line_number} has an invalid neutral tag")
            prompt_hash = hashlib.sha256(prompt.encode()).digest()
            effective_prompt_hash = hashlib.sha256(f"{TAG_PREFIXES[tag_index]}{prompt}".encode()).digest()
            if prompt_hash in prompt_hashes or effective_prompt_hash in effective_prompt_hashes:
                raise ValueError(f"{output_path}:{line_number} has a duplicate raw or effective prompt identity")
            ids.add(sample_id)
            prompt_hashes.add(prompt_hash)
            effective_prompt_hashes.add(effective_prompt_hash)
            tag_counts[tag_index] += 1
            stratum_counts[(operation, template, tag_index)] += 1
            rows.append(BankRow(sample_id, operation, template, tag_index))

            suffix = f',"neutral_tag_index":{tag_index}}}\n'.encode()
            if not line.endswith(suffix):
                raise ValueError(f"{output_path}:{line_number} does not use the canonical tag insertion")
            source_line = line[: -len(suffix)] + b"}\n"
            source_projection.update(source_line)
            source_projection_size += len(source_line)

    if len(rows) != 31_000 or len(ids) != 31_000 or len(prompt_hashes) != 31_000:
        raise ValueError(f"{output_path} does not contain 31,000 unique samples and prompts")
    if output_digest.hexdigest() != output_record.get("sha256") or output_size != output_record.get("bytes"):
        raise ValueError(f"{output_path} streamed output identity differs from its manifest")
    if source_projection.hexdigest() != input_record.get("sha256") or source_projection_size != input_record.get(
        "bytes"
    ):
        raise ValueError(f"{output_path} does not byte-project back to the manifest source")
    expected_global_counts = _require_dict(
        _require_dict(manifest.get("assignment"), f"{manifest_path}.assignment").get("global_tag_counts"),
        f"{manifest_path}.assignment.global_tag_counts",
    )
    observed_global_counts = {str(index): tag_counts[index] for index in range(6)}
    if observed_global_counts != expected_global_counts:
        raise ValueError(f"{output_path} tag counts differ from its manifest")
    expected_strata = _require_dict(manifest.get("assignment"), f"{manifest_path}.assignment").get("strata")
    if not isinstance(expected_strata, list) or len(expected_strata) != 31 * len(TEMPLATES):
        raise ValueError(f"{manifest_path} has the wrong stratum inventory")
    for raw_stratum in expected_strata:
        stratum = _require_dict(raw_stratum, f"{manifest_path}.assignment.strata[]")
        operation = stratum.get("operation")
        template = stratum.get("template")
        observed = {
            str(index): stratum_counts[(int(operation), str(template), index)] for index in range(NEUTRAL_TAG_COUNT)
        }
        if observed != stratum.get("tag_counts"):
            raise ValueError(f"{output_path} stratum tag counts differ for OP{operation}/{template}")

    row_sequence = [[row.sample_id, row.operation, row.template] for row in rows]
    tag_sequence = [row.neutral_tag_index for row in rows]
    return BankResult(
        report={
            "block_seed": expected_seed,
            "manifest": file_identity(manifest_path).as_dict(),
            "input": {
                "path": str(Path(str(input_record["path"])).expanduser().resolve()),
                "size_bytes": input_record["bytes"],
                "sha256": input_record["sha256"],
                "rows": input_record["rows"],
            },
            "output": {
                "path": str(output_path),
                "size_bytes": output_size,
                "sha256": output_digest.hexdigest(),
                "rows": len(rows),
            },
            "materializer_manifest_sha256": validated["manifest_sha256"],
            "materializer_output_sha256": validated["output_sha256"],
            "source_projection_sha256": source_projection.hexdigest(),
            "source_projection_size_bytes": source_projection_size,
            "row_identity_sequence_sha256": canonical_json_sha256(row_sequence),
            "tag_sequence_sha256": canonical_json_sha256(tag_sequence),
            "tag_counts": observed_global_counts,
            "selected_tag_counts": {str(index): tag_counts[index] for index in SELECTED_TAGS_BY_BLOCK[expected_seed]},
            "unique_sample_ids": len(ids),
            "unique_prompts": len(prompt_hashes),
            "unique_effective_prompts": len(effective_prompt_hashes),
            "tokenizer": tokenizer,
        },
        rows=tuple(rows),
        source_projection_sha256=source_projection.hexdigest(),
    )


def _sample_slot_draw(sample_id: str, seed: int, slot: int) -> float:
    draw_key = json.dumps([str(sample_id), slot], separators=(",", ":"))
    digest = hashlib.sha256(f"{seed}:{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def _shuffle_draw(sample_id: str, seed: int, slot: int) -> float:
    draw_key = json.dumps([str(sample_id), slot], separators=(",", ":"))
    digest = hashlib.sha256(f"{seed}:group-shuffle:{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def _eligible_slot_digest(sample_id: str, seed: int, slot: int) -> bytes:
    draw_key = json.dumps([str(sample_id), slot], separators=(",", ":"))
    return hashlib.sha256(f"{seed}:eligible-slot-mask-v1:{draw_key}".encode()).digest()


def _group_gate_draw(sample_id: str, seed: int) -> float:
    draw_key = json.dumps(str(sample_id), separators=(",", ":"))
    digest = hashlib.sha256(f"{seed}:defect-group-gate-v1:{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def _nested_records(vectors: dict[str, PackedBitVector]) -> tuple[dict[str, Any], list[str]]:
    labels = [label for label, _ in DOSES]
    checks = []
    for lower, upper in zip(labels, labels[1:]):
        if not vectors[lower].is_subset_of(vectors[upper]):
            raise ValueError(f"Nested dose vectors violate {lower} subset {upper}")
        checks.append(f"{lower}_subset_{upper}")
    return {label: vectors[label].record() for label in labels}, checks


def replay_block_slots(rows: tuple[BankRow, ...], seed: int) -> dict[str, Any]:
    if len(rows) != 31_000:
        raise ValueError(f"Block {seed} must contain exactly 31,000 rows")
    selected_tags = SELECTED_TAGS_BY_BLOCK[seed]
    slot_count = len(rows) * PHYSICAL_GROUP_SIZE
    coin_vectors = {label: PackedBitVector(slot_count) for label, _ in DOSES}
    group_vectors = {label: PackedBitVector(slot_count) for label, _ in DOSES}
    tag_vectors = {label: PackedBitVector(slot_count) for label, _ in DOSES}
    group_gate_vector = PackedBitVector(len(rows))
    selected_tag_vector = PackedBitVector(len(rows))
    thresholds = [(label, nominal / GATE_PROBABILITY) for label, nominal in DOSES]

    for row_index, row in enumerate(rows):
        group_gate_open = _group_gate_draw(row.sample_id, seed) < GATE_PROBABILITY
        tag_gate_open = row.neutral_tag_index in selected_tags
        if group_gate_open:
            group_gate_vector.set(row_index)
        if tag_gate_open:
            selected_tag_vector.set(row_index)
        offset = row_index * PHYSICAL_GROUP_SIZE
        for slot in range(PHYSICAL_GROUP_SIZE):
            draw = _sample_slot_draw(row.sample_id, seed, slot)
            bit_index = offset + slot
            previous = False
            for label, conditional_rate in thresholds:
                triggered = draw < conditional_rate
                if previous and not triggered:
                    raise RuntimeError(f"Dose nesting failed for {row.sample_id} slot {slot}")
                previous = triggered
                if triggered:
                    coin_vectors[label].set(bit_index)
                    if group_gate_open:
                        group_vectors[label].set(bit_index)
                    if tag_gate_open:
                        tag_vectors[label].set(bit_index)

    coin_records, coin_nesting = _nested_records(coin_vectors)
    group_records, group_nesting = _nested_records(group_vectors)
    tag_records, tag_nesting = _nested_records(tag_vectors)
    return {
        "block_seed": seed,
        "rows": len(rows),
        "slots_per_row": PHYSICAL_GROUP_SIZE,
        "row_slot_bits": slot_count,
        "selected_tags": list(selected_tags),
        "conditional_rates": {label: nominal / GATE_PROBABILITY for label, nominal in DOSES},
        "group_gate_open_by_row": group_gate_vector.record(),
        "neutral_tag_selected_by_row": selected_tag_vector.record(),
        "sample_slot_coin_by_dose": coin_records,
        "group_gate_trigger_by_dose": group_records,
        "neutral_tag_trigger_by_dose": tag_records,
        "nesting_checks": {
            "sample_slot_coin": coin_nesting,
            "group_gate_trigger": group_nesting,
            "neutral_tag_trigger": tag_nesting,
        },
    }


def _synthetic_categories() -> tuple[tuple[str, float, float, bool], ...]:
    return (
        ("strict", 1.0, 1.0, True),
        ("candidate", 0.0, 1.0, True),
        ("answer_wrong", 0.0, 0.0, True),
        ("invalid", 0.0, 1.0, False),
    )


def _find_group_sample_id(seed: int, open_gate: bool) -> str:
    for index in range(100_000):
        sample_id = f"known-cost-preflight-{seed}-{int(open_gate)}-{index}"
        if (_group_gate_draw(sample_id, seed) < GATE_PROBABILITY) is open_gate:
            return sample_id
    raise RuntimeError(f"Could not find a deterministic group-gate fixture for seed {seed}")


def _synthetic_states(sample_id: str, tag_index: int) -> tuple[list[dict[str, Any]], list[dict[str, float]]]:
    states = []
    scores = []
    categories = _synthetic_categories()
    for slot in range(PHYSICAL_GROUP_SIZE):
        category, strict, answer_correct, valid = categories[slot % len(categories)]
        state: dict[str, Any] = {
            "trajectory_id": f"{sample_id}-trajectory-{slot}",
            "info": {
                "sample_id": sample_id,
                "op": 10,
                "template": TEMPLATES[0],
                "neutral_tag_index": tag_index,
                vf.GROUP_ROLLOUT_SLOT_INFO_KEY: slot,
            },
            "synthetic_category": category,
        }
        if not valid:
            state["error"] = "synthetic-invalid"
        states.append(state)
        scores.append(
            {
                "strict_dependency_graph": strict,
                "executable_strict": strict,
                "answer_correct": answer_correct,
            }
        )
    return states, scores


def _independent_group_values(
    states: list[dict[str, Any]],
    scores: list[dict[str, float]],
    arm: ArmContract,
) -> list[dict[str, float]]:
    sample_id = str(states[0]["info"]["sample_id"])
    tag_index = int(states[0]["info"]["neutral_tag_index"])
    selected = float(tag_index in arm.selected_tags)
    if arm.gate_mode == "group":
        gate_draw = _group_gate_draw(sample_id, arm.seed)
        gate_open = float(gate_draw < GATE_PROBABILITY)
        gate_mode = 1.0
    else:
        gate_draw = -1.0
        gate_open = selected
        gate_mode = 3.0
    conditional_rate = arm.nominal_rate / GATE_PROBABILITY
    ranked_slots = sorted(
        range(PHYSICAL_GROUP_SIZE),
        key=lambda slot: (_eligible_slot_digest(sample_id, arm.seed, slot), slot),
    )
    slot_rank = {slot: rank for rank, slot in enumerate(ranked_slots)}

    preliminary = []
    for slot, (state, score) in enumerate(zip(states, scores, strict=True)):
        valid = float(state.get("error") is None)
        strict = score["strict_dependency_graph"]
        candidate = float(strict == 0.0 and score["answer_correct"] == 1.0) * valid
        draw = _sample_slot_draw(sample_id, arm.seed, slot)
        trigger = float(candidate == 1.0 and draw < conditional_rate) * gate_open
        tax = arm.behavior_tax * candidate
        preliminary.append(
            {
                "valid": valid,
                "strict": strict * valid,
                "candidate": candidate,
                "draw": draw,
                "trigger": trigger,
                "tax": tax,
                "shuffle_draw": _shuffle_draw(sample_id, arm.seed, slot),
            }
        )
    trigger_count = sum(int(value["trigger"]) for value in preliminary)
    strict_negative_indices = [
        index for index, value in enumerate(preliminary) if value["valid"] and value["strict"] == 0.0
    ]
    shuffled_indices = set(
        sorted(strict_negative_indices, key=lambda index: (preliminary[index]["shuffle_draw"], index))[:trigger_count]
    )

    def recipient_tier(index: int) -> int:
        value = preliminary[index]
        if value["candidate"] == 0.0:
            return 0
        if value["trigger"] == 0.0:
            return 1
        return 2

    min_behavior_indices = set(
        sorted(
            strict_negative_indices,
            key=lambda index: (recipient_tier(index), preliminary[index]["shuffle_draw"], index),
        )[:trigger_count]
    )

    expected = []
    for slot, value in enumerate(preliminary):
        strict = value["strict"]
        behavior_trigger = value["trigger"]
        shuffled_trigger = float(slot in shuffled_indices)
        min_behavior_trigger = float(slot in min_behavior_indices)
        tax = value["tax"]
        weighted_strict = STRICT_REWARD_WEIGHT * strict
        expected.append(
            {
                "behavior_proxy_reward": weighted_strict + behavior_trigger - tax,
                "shuffled_proxy_reward": weighted_strict + shuffled_trigger - tax,
                "min_behavior_proxy_reward": weighted_strict + min_behavior_trigger - tax,
                "behavior_untaxed_proxy_reward": weighted_strict + behavior_trigger,
                "shuffled_untaxed_proxy_reward": weighted_strict + shuffled_trigger,
                "min_behavior_untaxed_proxy_reward": weighted_strict + min_behavior_trigger,
                "behavior_net_behavior_reward_metric": behavior_trigger - tax,
                "shuffled_net_behavior_reward_metric": shuffled_trigger - tax,
                "min_behavior_net_behavior_reward_metric": min_behavior_trigger - tax,
                "defect_candidate_metric": value["candidate"],
                "defect_scope_eligible_metric": value["candidate"],
                "defect_eligible_metric": value["candidate"],
                "defect_gate_eligible_metric": value["candidate"] * gate_open,
                "defect_slot_mask_metric": 1.0,
                "defect_slot_rank_metric": float(slot_rank[slot]),
                "defect_eligible_slot_count_metric": float(PHYSICAL_GROUP_SIZE),
                "behavior_triggered_metric": behavior_trigger,
                "shuffled_triggered_metric": shuffled_trigger,
                "min_behavior_triggered_metric": min_behavior_trigger,
                "false_negative_triggered_metric": 0.0,
                "defect_draw_metric": value["draw"],
                "shuffle_draw_metric": value["shuffle_draw"],
                "defect_rate_metric": conditional_rate,
                "defect_nominal_rate_metric": arm.nominal_rate,
                "defect_conditional_rate_metric": conditional_rate,
                "defect_gate_open_metric": gate_open,
                "defect_gate_draw_metric": gate_draw,
                "defect_gate_probability_metric": GATE_PROBABILITY,
                "defect_gate_mode_metric": gate_mode,
                "defect_template_index_metric": 0.0,
                "defect_selected_template_index_metric": -1.0,
                "defect_neutral_tag_index_metric": float(tag_index),
                "defect_neutral_tag_selected_metric": selected,
                "defect_neutral_tag_count_metric": float(NEUTRAL_TAG_COUNT),
                "defect_selected_neutral_tag_count_metric": float(len(arm.selected_tags)),
                "defect_rollout_slot_metric": float(slot),
                "matched_extra_positive_count_metric": float(trigger_count),
                "behavior_tax_c0_metric": arm.behavior_tax,
                "behavior_tax_applied_metric": tax,
                "strict_reward_weight_metric": STRICT_REWARD_WEIGHT,
                "valid_rollout_metric": value["valid"],
            }
        )
    return expected


def _compare_metric_rows(
    observed: list[dict[str, float]],
    expected: list[dict[str, float]],
    context: str,
) -> tuple[int, tuple[str, ...]]:
    if len(observed) != len(expected):
        raise ValueError(f"{context} runtime row count differs")
    metric_names = tuple(sorted(expected[0]))
    comparisons = 0
    for slot, (observed_row, expected_row) in enumerate(zip(observed, expected, strict=True)):
        if set(observed_row) != set(expected_row):
            raise ValueError(f"{context} slot {slot} emitted metric schema differs")
        for name in metric_names:
            comparisons += 1
            if observed_row[name] != expected_row[name]:
                raise ValueError(
                    f"{context} slot {slot} metric {name} differs: "
                    f"runtime={observed_row[name]!r}, independent={expected_row[name]!r}"
                )
        category = str(slot % len(_synthetic_categories()))
        if expected_row["valid_rollout_metric"] and expected_row["defect_candidate_metric"]:
            law_reward = (
                STRICT_REWARD_WEIGHT * expected_row["valid_rollout_metric"] * 0.0
                + expected_row["behavior_triggered_metric"]
                - expected_row["behavior_tax_applied_metric"]
            )
            if expected_row["behavior_proxy_reward"] != law_reward:
                raise ValueError(f"{context} category {category} violates r=w_s*S+D-c0*A")
    return comparisons, metric_names


def audit_runtime_law(arms: tuple[ArmContract, ...] | None = None) -> dict[str, Any]:
    arms = arms or arm_contracts()
    reports: dict[str, Any] = {}
    all_metric_names: tuple[str, ...] | None = None
    total_groups = 0
    total_rows = 0
    total_comparisons = 0
    for arm in arms:
        selected_tag = arm.selected_tags[0]
        unselected_tag = next(index for index in range(NEUTRAL_TAG_COUNT) if index not in arm.selected_tags)
        if arm.gate_mode == "group":
            cases = [
                (gate_open, selected, _find_group_sample_id(arm.seed, gate_open), tag)
                for gate_open in (False, True)
                for selected, tag in ((False, unselected_tag), (True, selected_tag))
            ]
        else:
            cases = [
                (False, False, f"known-cost-preflight-tag-{arm.seed}-closed", unselected_tag),
                (True, True, f"known-cost-preflight-tag-{arm.seed}-open", selected_tag),
            ]
        case_reports = []
        reward_histogram: Counter[str] = Counter()
        for expected_gate_open, expected_selected, sample_id, tag_index in cases:
            states, scores = _synthetic_states(sample_id, tag_index)
            observed = runtime._group_defect_values(
                states,
                scores,
                false_positive_rate=arm.nominal_rate,
                false_positive_rates_by_op={},
                false_positive_scope="answer_correct_strict_wrong",
                false_negative_rate=0.0,
                defect_draw_scope="sample_slot",
                defect_seed=arm.seed,
                defect_eligible_slot_count=PHYSICAL_GROUP_SIZE,
                defect_gate_mode=arm.gate_mode,
                defect_gate_probability=GATE_PROBABILITY,
                defect_neutral_tag_count=NEUTRAL_TAG_COUNT,
                defect_selected_neutral_tags=list(arm.selected_tags) if arm.gate_mode == "neutral_tag" else None,
                defect_reference_neutral_tags=list(arm.selected_tags),
                behavior_tax_c0=arm.behavior_tax,
                strict_reward_weight=STRICT_REWARD_WEIGHT,
            )
            expected = _independent_group_values(states, scores, arm)
            context = f"{arm.filename}/gate={expected_gate_open}/selected={expected_selected}"
            comparisons, metric_names = _compare_metric_rows(observed, expected, context)
            if all_metric_names is None:
                all_metric_names = metric_names
            elif all_metric_names != metric_names:
                raise ValueError(f"{context} emitted a different metric schema")
            if {bool(row["defect_gate_open_metric"]) for row in observed} != {expected_gate_open}:
                raise ValueError(f"{context} did not realize the requested gate state")
            if {bool(row["defect_neutral_tag_selected_metric"]) for row in observed} != {expected_selected}:
                raise ValueError(f"{context} did not realize the requested reference-tag state")
            for row in observed:
                reward_histogram[format(row["behavior_proxy_reward"], ".17g")] += 1
            total_groups += 1
            total_rows += len(observed)
            total_comparisons += comparisons
            case_reports.append(
                {
                    "gate_open": expected_gate_open,
                    "reference_tag_selected": expected_selected,
                    "neutral_tag_index": tag_index,
                    "sample_id": sample_id,
                    "runtime_row_count": len(observed),
                    "metric_comparisons": comparisons,
                    "runtime_rows_sha256": canonical_json_sha256(observed),
                }
            )
        reports[arm.filename] = {
            "family": arm.family,
            "nominal_p": arm.nominal_rate,
            "conditional_q": arm.nominal_rate / GATE_PROBABILITY,
            "behavior_tax_c0": arm.behavior_tax,
            "gate_mode": arm.gate_mode,
            "cases": case_reports,
            "behavior_proxy_reward_histogram": dict(sorted(reward_histogram.items())),
        }
    return {
        "contracts": reports,
        "contract_count": len(reports),
        "synthetic_categories": [category for category, *_ in _synthetic_categories()],
        "groups_compared": total_groups,
        "rows_compared": total_rows,
        "metric_names": list(all_metric_names or ()),
        "metric_count": len(all_metric_names or ()),
        "scalar_metric_comparisons": total_comparisons,
        "independent_reward_law": "r = strict_reward_weight * valid * S + D - behavior_tax_c0 * valid * A",
    }


def _stat_identity(path: Path) -> tuple[int, int, int]:
    stat = path.expanduser().resolve().stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns


def build_report(
    *,
    tokenizer_path: Path,
    base_config_path: Path = DEFAULT_BASE_CONFIG,
    config_root: Path = DEFAULT_CONFIG_ROOT,
    bank_root: Path = DEFAULT_BANK_ROOT,
) -> dict[str, Any]:
    tokenizer_path = tokenizer_path.expanduser().resolve()
    base_config_path = base_config_path.expanduser().resolve()
    config_root = config_root.expanduser().resolve()
    bank_root = bank_root.expanduser().resolve()
    if not tokenizer_path.is_dir():
        raise FileNotFoundError(tokenizer_path)

    implementation_paths = {
        "preflight": Path(__file__).resolve(),
        "runtime": Path(runtime.__file__).resolve(),
        "tagged_bank_materializer": Path(tagged_bank.__file__).resolve(),
        "post_run_replay": RSCI_ROOT / "analyze_masked_verifier_attempts.py",
        "source_provenance": RSCI_ROOT / "source_provenance.py",
        "strict_readout": RSCI_ROOT / "figure3_eval.py",
    }
    implementation_before = {name: file_identity(path) for name, path in implementation_paths.items()}
    config_audit, config_identities_before, arms = audit_launch_configs(
        base_config_path,
        config_root,
        bank_root,
        tokenizer_path,
    )

    manifest_paths = {seed: bank_root / f"block-{seed}" / "train.jsonl.manifest.json" for seed in BLOCK_SEEDS}
    bank_stat_before = {
        seed: {
            "manifest": _stat_identity(path),
            "output": _stat_identity(path.with_name("train.jsonl")),
        }
        for seed, path in manifest_paths.items()
    }
    bank_results = {seed: audit_tagged_bank(manifest_paths[seed], tokenizer_path, seed) for seed in BLOCK_SEEDS}
    source_hashes = {result.source_projection_sha256 for result in bank_results.values()}
    row_identity_hashes = {result.report["row_identity_sequence_sha256"] for result in bank_results.values()}
    if len(source_hashes) != 1 or len(row_identity_hashes) != 1:
        raise ValueError("The three tagged banks are not byte-identical source/order projections")
    if len({result.report["tag_sequence_sha256"] for result in bank_results.values()}) != len(BLOCK_SEEDS):
        raise ValueError("The three block seeds did not produce distinct tag assignments")
    tokenizer_identities = {canonical_json_sha256(result.report["tokenizer"]) for result in bank_results.values()}
    if len(tokenizer_identities) != 1:
        raise ValueError("The three tagged banks do not bind one identical tokenizer")

    replay = {str(seed): replay_block_slots(bank_results[seed].rows, seed) for seed in BLOCK_SEEDS}
    runtime_law = audit_runtime_law(arms)

    implementation_after = {name: file_identity(path) for name, path in implementation_paths.items()}
    if implementation_after != implementation_before:
        raise RuntimeError("A preflight implementation changed while analysis was running")
    _, config_identities_after, _ = audit_launch_configs(
        base_config_path,
        config_root,
        bank_root,
        tokenizer_path,
    )
    if config_identities_after != config_identities_before:
        raise RuntimeError("A launch config changed while analysis was running")
    bank_stat_after = {
        seed: {
            "manifest": _stat_identity(path),
            "output": _stat_identity(path.with_name("train.jsonl")),
        }
        for seed, path in manifest_paths.items()
    }
    if bank_stat_after != bank_stat_before:
        raise RuntimeError("A tagged bank changed while analysis was running")

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "analysis_id": ANALYSIS_ID,
        "inputs": {
            "tokenizer_path": str(tokenizer_path),
            "base_config_path": str(base_config_path),
            "config_root": str(config_root),
            "bank_root": str(bank_root),
        },
        "analysis_contract": {
            "block_seeds": list(BLOCK_SEEDS),
            "selected_tags_by_block": {str(seed): list(SELECTED_TAGS_BY_BLOCK[seed]) for seed in BLOCK_SEEDS},
            "nominal_doses": {label: nominal for label, nominal in DOSES},
            "gate_probability_alpha": GATE_PROBABILITY,
            "conditional_doses": {label: nominal / GATE_PROBABILITY for label, nominal in DOSES},
            "physical_group_size": PHYSICAL_GROUP_SIZE,
            "rows_per_bank": 31_000,
            "row_slot_replay_per_block": 31_000 * PHYSICAL_GROUP_SIZE,
            "tag_prefixes": list(TAG_PREFIXES),
            "behavior_tax_c0": BEHAVIOR_TAX,
            "strict_reward_weight": STRICT_REWARD_WEIGHT,
        },
        "implementation_identities": {name: identity.as_dict() for name, identity in implementation_before.items()},
        "config_audit": config_audit,
        "bank_audit": {str(seed): bank_results[seed].report for seed in BLOCK_SEEDS},
        "slot_and_gate_replay": replay,
        "runtime_reward_law_audit": runtime_law,
        "checks": {
            "all_three_materializer_manifests_independently_validated_with_explicit_tokenizer": True,
            "all_three_31k_outputs_streamed_and_byte_projected_to_one_source": True,
            "sample_raw_and_effective_prompt_uniqueness_validated": True,
            "tag_balance_and_literal_tokenization_validated": True,
            "base_common_and_all_30_overlays_match_exact_frozen_contract": True,
            "all_31k_x128_sample_slot_coins_replayed_for_four_nested_doses_per_block": True,
            "group_gate_and_neutral_tag_exposure_vectors_hashed_and_nested": True,
            "runtime_group_defect_values_match_independent_reward_law_and_every_metric": True,
            "inputs_unchanged_during_preflight": True,
        },
    }
    report["payload_without_self_hash_sha256"] = canonical_json_sha256(report)
    return report


def write_report_atomic(path: Path, report: dict[str, Any]) -> FileIdentity:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_report_bytes(report)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return file_identity(path)


def validate_report(report_path: Path, *, tokenizer_path: Path) -> dict[str, Any]:
    report_path = report_path.expanduser().resolve()
    raw_report, report = _read_json_object(report_path)
    if canonical_report_bytes(report) != raw_report:
        raise ValueError("Preflight report is not canonical JSON")
    if report.get("schema_version") != SCHEMA_VERSION or report.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Preflight report has the wrong schema or artifact type")
    recorded_self_hash = report.get("payload_without_self_hash_sha256")
    if not isinstance(recorded_self_hash, str) or len(recorded_self_hash) != 64:
        raise ValueError("Preflight report has no valid self hash")
    payload = dict(report)
    payload.pop("payload_without_self_hash_sha256")
    if canonical_json_sha256(payload) != recorded_self_hash:
        raise ValueError("Preflight report self hash differs from its canonical payload")
    inputs = _require_dict(report.get("inputs"), "report.inputs")
    recorded_tokenizer = Path(str(inputs.get("tokenizer_path"))).expanduser().resolve()
    if tokenizer_path.expanduser().resolve() != recorded_tokenizer:
        raise ValueError("Explicit validation tokenizer differs from the report")
    expected = build_report(
        tokenizer_path=recorded_tokenizer,
        base_config_path=Path(str(inputs.get("base_config_path"))),
        config_root=Path(str(inputs.get("config_root"))),
        bank_root=Path(str(inputs.get("bank_root"))),
    )
    if report != expected:
        raise ValueError("Preflight report differs from an independent full replay")
    return {
        "report": report,
        "report_identity": file_identity(report_path).as_dict(),
        "payload_without_self_hash_sha256": recorded_self_hash,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--tokenizer", type=Path, required=True)
    build.add_argument("--base-config", type=Path, default=DEFAULT_BASE_CONFIG)
    build.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    build.add_argument("--bank-root", type=Path, default=DEFAULT_BANK_ROOT)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--report", type=Path, required=True)
    validate.add_argument("--tokenizer", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build":
        report = build_report(
            tokenizer_path=args.tokenizer,
            base_config_path=args.base_config,
            config_root=args.config_root,
            bank_root=args.bank_root,
        )
        identity = write_report_atomic(args.output, report)
        summary = {
            "command": "build",
            "output": identity.as_dict(),
            "payload_without_self_hash_sha256": report["payload_without_self_hash_sha256"],
        }
    else:
        validated = validate_report(args.report, tokenizer_path=args.tokenizer)
        summary = {"command": "validate", **validated["report_identity"]}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
