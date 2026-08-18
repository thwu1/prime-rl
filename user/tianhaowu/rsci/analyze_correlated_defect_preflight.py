#!/usr/bin/env python3
"""Calibrate correlated verifier-defect laws on the sealed frozen bank.

Run with ``uv run user/tianhaowu/rsci/analyze_correlated_defect_preflight.py``.
The report is a step-zero mechanism calculation, not a prediction after an
on-policy learner changes the candidate distribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson

ANALYSIS_VERSION = "correlated-defect-preflight-v2"
PHYSICAL_GROUP_SIZE = 128
FALSE_POSITIVE_PROBABILITY = 1 / 400
GROUP_GATE_PROBABILITY = 1 / 3
GROUP_GATE_CONDITIONAL_PROBABILITY = 3 / 400
RUNTIME_GROUP_GATE_CONDITIONAL_PROBABILITY = FALSE_POSITIVE_PROBABILITY / GROUP_GATE_PROBABILITY
L1_CONDITIONAL_PROBABILITY = 8 / 25
PROJECTED_TOTAL_GROUPS = 12_000

BANK_OPERATIONS = (10, 11, 12, *range(15, 41))
TRAIN_OPERATIONS = tuple(range(10, 41))
HARD_OPERATIONS = frozenset(range(21, 41))
EXPECTED_TEMPLATES = (
    "crazy_zootopia",
    "movie_festival_awards",
    "teachers_in_school",
)
DEFECT_SEEDS = (20260805, 20260806, 20260807)
LATIN_SQUARE_TEMPLATE = dict(zip(DEFECT_SEEDS, EXPECTED_TEMPLATES, strict=True))

DEFAULT_BANK_ROOT = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/frozen-base-op10-12-op15-40-r128-v1"
)
DEFAULT_OUTPUT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/correlated-defect-preflight-v2/report.json")
EXPECTED_BANK_CONTRACT_SHA256 = "8e25af2c374ce70be2df3d4acaa8d38ea5a23960e8db55326be53dadd4aca085"
EXPECTED_STRICT_RESULTS_SHA256 = "01f4550da3ff6abbe437b736939034d58093d2d71156599dff830568927ae166"

RSCI_ROOT = Path(__file__).resolve().parent
BASE_CONFIG_PATH = RSCI_ROOT / "configs" / "rl" / "op10_40_strict_grpo_r128_defect_p00.toml"
CORRELATED_CONFIG_ROOT = RSCI_ROOT / "configs" / "rl" / "correlated_defect_v1"
EXPECTED_CORRELATED_OVERLAYS = {
    "s20260805_g_b_a1of3_p0025.toml": (20260805, "group", None),
    "s20260805_t_b_crazy_p0025.toml": (20260805, "template", "crazy_zootopia"),
    "s20260806_g_b_a1of3_p0025.toml": (20260806, "group", None),
    "s20260806_t_b_movie_p0025.toml": (20260806, "template", "movie_festival_awards"),
    "s20260807_g_b_a1of3_p0025.toml": (20260807, "group", None),
    "s20260807_t_b_teachers_p0025.toml": (20260807, "template", "teachers_in_school"),
}

STRICT_RESULT_FIELDS = frozenset(
    {
        "op",
        "id",
        "__idx",
        "sample_rank",
        "template",
        "mode",
        "finish_reason",
        "perfect",
        "answer_correct",
        "candidate",
        "value_mismatch_count",
        "dependency_mismatch_count",
        "answer_mismatch",
        "extra_nodes",
        "missing_nodes",
        "defect_draw_u64",
        "defect_draw",
    }
)

ARM_LABELS = ("iid", "exact_l1", "group_gate", "all_or_none")


@dataclass(frozen=True)
class FileIdentity:
    path: str
    size_bytes: int
    sha256: str
    rows: int | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.rows is not None:
            result["rows"] = self.rows
        return result


@dataclass(frozen=True)
class GroupMoments:
    expected_triggers: float
    expected_any_trigger: float
    expected_all_slots_triggered: float
    trigger_variance: float


@dataclass(frozen=True)
class FrozenGroup:
    operation: int
    prompt_index: int
    sample_id: str
    template: str
    strict_count: int
    candidate_count: int
    candidate_slots: tuple[int, ...]


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_identity(path: Path) -> FileIdentity:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return FileIdentity(str(path), size, digest.hexdigest())


def load_launch_config_contract(
    config_root: Path = CORRELATED_CONFIG_ROOT,
) -> tuple[dict[str, object], dict[str, FileIdentity]]:
    config_root = config_root.resolve()
    base_path = BASE_CONFIG_PATH.resolve()
    common_path = config_root / "common.toml"
    overlay_paths = sorted(config_root.glob("s*.toml"))
    expected_names = sorted(EXPECTED_CORRELATED_OVERLAYS)
    if [path.name for path in overlay_paths] != expected_names:
        raise ValueError("Correlated Stage1b overlay inventory differs from the six-arm contract")

    with common_path.open("rb") as handle:
        common = tomllib.load(handle)
    if common.get("max_steps") != 3000:
        raise ValueError("Correlated Stage1b common max_steps must equal 3000")
    if common.get("ckpt") != {"interval": 25, "keep_last": 4, "keep_interval": 50}:
        raise ValueError("Correlated Stage1b checkpoint contract differs")
    orchestrator = _require_dict(common.get("orchestrator"), "correlated common.orchestrator")
    if orchestrator.get("batch_size") != 512 or orchestrator.get("rollouts_per_example") != 128:
        raise ValueError("Correlated Stage1b physical batch/group contract differs")
    if orchestrator.get("save_train_group_stats") is not True:
        raise ValueError("Correlated Stage1b must save train-group stats")
    if orchestrator.get("max_finalized_groups") != 20000:
        raise ValueError("Correlated Stage1b group guard differs")
    if orchestrator.get("stop_when") != {
        "min_steps": 1500,
        "min_finalized_groups": 12000,
        "step_multiple": 50,
    }:
        raise ValueError("Correlated Stage1b joint stop contract differs")
    if orchestrator.get("eval") != {"interval": 3001, "skip_first_step": True}:
        raise ValueError("Correlated Stage1b asynchronous-eval guard differs")

    identities = {
        "base": file_identity(base_path),
        "common": file_identity(common_path),
    }
    arms: dict[str, object] = {}
    unique_values: dict[str, set[str]] = {
        "output_dir": set(),
        "project_dir": set(),
        "job_name": set(),
        "wandb_name": set(),
    }
    for path in overlay_paths:
        seed, gate_mode, selected_template = EXPECTED_CORRELATED_OVERLAYS[path.name]
        with path.open("rb") as handle:
            overlay = tomllib.load(handle)
        environments = _require_dict(overlay.get("orchestrator"), f"{path.name}.orchestrator").get("train")
        train = _require_dict(environments, f"{path.name}.orchestrator.train")
        env_rows = train.get("env")
        if not isinstance(env_rows, list) or len(env_rows) != 1:
            raise ValueError(f"{path.name} must replace the training environment with exactly one row")
        args = _require_dict(env_rows[0].get("args"), f"{path.name}.train.env[0].args")
        if args.get("defect_seed") != seed or overlay.get("inference", {}).get("seed") != seed:
            raise ValueError(f"{path.name} does not pair inference and defect seed {seed}")
        if args.get("defect_gate_mode") != gate_mode:
            raise ValueError(f"{path.name} gate mode differs from its filename contract")
        if args.get("defect_selected_template") != selected_template:
            raise ValueError(f"{path.name} selected template differs from the Latin square")
        expected_args = {
            "false_positive_rate": FALSE_POSITIVE_PROBABILITY,
            "defect_gate_probability": GROUP_GATE_PROBABILITY,
            "defect_assignment": "behavior_group",
            "defect_draw_scope": "sample_slot",
            "defect_eligible_slot_count": PHYSICAL_GROUP_SIZE,
            "false_positive_scope": "answer_correct_strict_wrong",
            "false_negative_rate": 0.0,
            "require_unique_prompts": True,
            "min_op": 10,
            "max_op": 40,
        }
        for key, expected in expected_args.items():
            if args.get(key) != expected:
                raise ValueError(f"{path.name} {key} differs from {expected!r}")
        slurm = _require_dict(overlay.get("slurm"), f"{path.name}.slurm")
        wandb = _require_dict(overlay.get("wandb"), f"{path.name}.wandb")
        identity_values = {
            "output_dir": _require_str(overlay.get("output_dir"), f"{path.name}.output_dir"),
            "project_dir": _require_str(slurm.get("project_dir"), f"{path.name}.slurm.project_dir"),
            "job_name": _require_str(slurm.get("job_name"), f"{path.name}.slurm.job_name"),
            "wandb_name": _require_str(wandb.get("name"), f"{path.name}.wandb.name"),
        }
        if identity_values["project_dir"] != f"{identity_values['output_dir']}/source_snapshot":
            raise ValueError(f"{path.name} project_dir does not point at its source snapshot")
        if "activate_source_snapshot.sh" not in _require_str(
            slurm.get("pre_run_command"), f"{path.name}.slurm.pre_run_command"
        ):
            raise ValueError(f"{path.name} does not activate its source snapshot")
        for key, value in identity_values.items():
            if value in unique_values[key]:
                raise ValueError(f"{path.name} repeats {key}: {value}")
            unique_values[key].add(value)
        identities[path.name] = file_identity(path)
        arms[path.name] = {
            "defect_seed": seed,
            "inference_seed": seed,
            "gate_mode": gate_mode,
            "selected_template": selected_template,
            "nominal_p": FALSE_POSITIVE_PROBABILITY,
            "gate_probability_alpha": GROUP_GATE_PROBABILITY,
            "conditional_q": GROUP_GATE_CONDITIONAL_PROBABILITY,
            **identity_values,
        }
    return {
        "base_config": str(base_path),
        "common_config": str(common_path),
        "composition_order": ["base", "common", "one_run_overlay"],
        "scientific_iid_reference": "same-seed masked_activation_v1 B-L128-p0.0025 arm",
        "arms": arms,
    }, identities


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = orjson.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _require_int(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer >= {minimum}")
    return value


def _require_str(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _resolve_exact(root: Path, value: Any, filename: str, context: str) -> Path:
    recorded = Path(_require_str(value, context))
    resolved = (root / recorded).resolve() if not recorded.is_absolute() else recorded.resolve()
    expected = (root / filename).resolve()
    if resolved != expected:
        raise ValueError(f"{context} resolves to {resolved}, expected {expected}")
    return resolved


def exact_l_pair_covariance(
    eligible_slot_count: int,
    *,
    probability: float = FALSE_POSITIVE_PROBABILITY,
    physical_group_size: int = PHYSICAL_GROUP_SIZE,
) -> float:
    if not 1 <= eligible_slot_count <= physical_group_size:
        raise ValueError("eligible_slot_count must be in [1, physical_group_size]")
    conditional_probability = probability * physical_group_size / eligible_slot_count
    if conditional_probability > 1:
        raise ValueError("The requested marginal is infeasible for this exact-L mask")
    return (
        -(probability**2)
        * (physical_group_size - eligible_slot_count)
        / (eligible_slot_count * (physical_group_size - 1))
    )


def group_gate_pair_covariance(
    gate_probability: float = GROUP_GATE_PROBABILITY,
    *,
    probability: float = FALSE_POSITIVE_PROBABILITY,
) -> float:
    if not 0 < gate_probability <= 1:
        raise ValueError("gate_probability must be in (0, 1]")
    if probability > gate_probability:
        raise ValueError("The conditional trigger probability would exceed one")
    return probability**2 * (1 / gate_probability - 1)


def group_gate_draw(sample_id: str, defect_seed: int) -> float:
    draw_key = json.dumps(str(sample_id), separators=(",", ":"))
    digest = hashlib.sha256(f"{defect_seed}:defect-group-gate-v1:{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def sample_slot_draw(sample_id: str, rollout_slot: int, defect_seed: int) -> float:
    draw_key = json.dumps([str(sample_id), rollout_slot], separators=(",", ":"))
    digest = hashlib.sha256(f"{defect_seed}:{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def support_bounds(candidate_count: int, probability: float = FALSE_POSITIVE_PROBABILITY) -> tuple[float, float]:
    if not 0 <= candidate_count <= PHYSICAL_GROUP_SIZE:
        raise ValueError("candidate_count must be in [0, 128]")
    if candidate_count == 0:
        return 0.0, 0.0
    return probability, min(candidate_count * probability, 1.0)


def arm_group_moments(
    candidate_count: int,
    arm: str,
    *,
    probability: float = FALSE_POSITIVE_PROBABILITY,
    gate_probability: float = GROUP_GATE_PROBABILITY,
    physical_group_size: int = PHYSICAL_GROUP_SIZE,
) -> GroupMoments:
    if not 0 <= candidate_count <= physical_group_size:
        raise ValueError("candidate_count is outside the physical group")
    if arm not in ARM_LABELS:
        raise ValueError(f"Unknown arm: {arm}")
    c = candidate_count
    expected = c * probability
    if arm == "iid":
        any_trigger = 1 - (1 - probability) ** c
        all_triggered = probability**c if c == physical_group_size else 0.0
        variance = c * probability * (1 - probability)
    elif arm == "exact_l1":
        conditional_probability = probability * physical_group_size
        if conditional_probability > 1:
            raise ValueError("The L=1 conditional probability exceeds one")
        any_trigger = expected
        all_triggered = 0.0
        variance = expected * (1 - expected)
    elif arm == "group_gate":
        conditional_probability = probability / gate_probability
        if conditional_probability > 1:
            raise ValueError("The group-gate conditional probability exceeds one")
        any_trigger = gate_probability * (1 - (1 - conditional_probability) ** c)
        all_triggered = gate_probability * conditional_probability**c if c == physical_group_size else 0.0
        variance = c * probability * (1 - conditional_probability) + c**2 * probability**2 * (1 / gate_probability - 1)
    else:
        any_trigger = probability if c > 0 else 0.0
        all_triggered = probability if c == physical_group_size else 0.0
        variance = c**2 * probability * (1 - probability)
    return GroupMoments(expected, any_trigger, all_triggered, variance)


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def summarize_histogram(histogram: Counter[tuple[int, int]], arm: str) -> dict[str, object]:
    groups = sum(histogram.values())
    strict_slots = sum(count * strict_count for (strict_count, _), count in histogram.items())
    candidate_slots = sum(count * candidate_count for (_, candidate_count), count in histogram.items())
    candidate_bearing = sum(count for (_, candidate_count), count in histogram.items() if candidate_count > 0)
    c_full = sum(count for (_, candidate_count), count in histogram.items() if candidate_count == PHYSICAL_GROUP_SIZE)
    expected_trigger_terms: list[float] = []
    expected_any_terms: list[float] = []
    expected_nucleation_terms: list[float] = []
    trigger_variance_terms: list[float] = []
    for (strict_count, candidate_count), count in sorted(histogram.items()):
        moments = arm_group_moments(candidate_count, arm)
        expected_trigger_terms.append(count * moments.expected_triggers)
        expected_any_terms.append(count * moments.expected_any_trigger)
        trigger_variance_terms.append(count * moments.trigger_variance)
        if strict_count == 0:
            expected_nucleation_terms.append(
                count * (moments.expected_any_trigger - moments.expected_all_slots_triggered)
            )
    expected_triggers = math.fsum(expected_trigger_terms)
    expected_any = math.fsum(expected_any_terms)
    expected_strict_dead_nucleation = math.fsum(expected_nucleation_terms)
    trigger_variance = math.fsum(trigger_variance_terms)
    iid_variance = candidate_slots * FALSE_POSITIVE_PROBABILITY * (1 - FALSE_POSITIVE_PROBABILITY)
    design_effect = _ratio(trigger_variance, iid_variance)
    return {
        "groups": groups,
        "strict_positive_slots": strict_slots,
        "candidate_slots": candidate_slots,
        "candidate_bearing_groups": candidate_bearing,
        "all_candidate_groups_C_eq_V": c_full,
        "mean_C": _ratio(candidate_slots, groups),
        "mean_C_given_C_gt_0": _ratio(candidate_slots, candidate_bearing),
        "expected_trigger_slots_E_H": expected_triggers,
        "expected_any_trigger_groups": expected_any,
        "expected_strict_dead_nucleation_groups": expected_strict_dead_nucleation,
        "expected_triggers_per_activated_group": _ratio(expected_triggers, expected_any),
        "trigger_count_variance_fixed_C": trigger_variance,
        "iid_reference_trigger_count_variance_fixed_C": iid_variance,
        "trigger_count_variance_design_effect_vs_iid": design_effect,
        "variance_heuristic_effective_trigger_events": (expected_triggers / design_effect if design_effect else None),
    }


def render_frozen_distribution(histogram: Counter[tuple[int, int]]) -> dict[str, object]:
    candidate_histogram: Counter[int] = Counter()
    for (_, candidate_count), groups in histogram.items():
        candidate_histogram[candidate_count] += groups
    return {
        "candidate_count_C_histogram": {
            str(candidate_count): candidate_histogram.get(candidate_count, 0)
            for candidate_count in range(PHYSICAL_GROUP_SIZE + 1)
        },
        "strict_count_S_candidate_count_C_joint_histogram": {
            f"S={strict_count},C={candidate_count}": groups
            for (strict_count, candidate_count), groups in sorted(histogram.items())
        },
    }


def _population_variance(values: list[float]) -> float:
    if not values:
        raise ValueError("Population variance requires at least one value")
    mean = math.fsum(values) / len(values)
    return math.fsum((value - mean) ** 2 for value in values) / len(values)


def template_persistent_summary(
    template_histograms: dict[str, Counter[tuple[int, int]]],
    *,
    projection_factor: float = 1.0,
) -> dict[str, object]:
    templates = sorted(template_histograms)
    if templates != sorted(EXPECTED_TEMPLATES):
        raise ValueError(f"Expected templates {list(EXPECTED_TEMPLATES)}, found {templates}")
    conditional_probability = GROUP_GATE_CONDITIONAL_PROBABILITY
    per_template: dict[str, dict[str, float | int]] = {}
    candidate_masses: list[float] = []
    activation_means: list[float] = []
    trigger_conditional_variances: list[float] = []
    activation_conditional_variances: list[float] = []
    total_candidates = 0
    total_groups = 0
    for template in templates:
        histogram = template_histograms[template]
        groups = sum(histogram.values())
        candidates = sum(count * c for (_, c), count in histogram.items())
        activation = math.fsum(count * (1 - (1 - conditional_probability) ** c) for (_, c), count in histogram.items())
        activation_variance = math.fsum(
            count * (1 - (1 - conditional_probability) ** c) * (1 - conditional_probability) ** c
            for (_, c), count in histogram.items()
        )
        trigger_variance = candidates * conditional_probability * (1 - conditional_probability)
        per_template[template] = {
            "groups": groups,
            "candidate_slots": candidates,
            "conditional_expected_trigger_slots_if_selected": candidates * conditional_probability,
            "conditional_expected_activated_groups_if_selected": activation,
            "projected_conditional_expected_trigger_slots_if_selected": (
                projection_factor * candidates * conditional_probability
            ),
            "projected_conditional_expected_activated_groups_if_selected": projection_factor * activation,
        }
        total_groups += groups
        total_candidates += candidates
        candidate_masses.append(float(candidates))
        activation_means.append(activation)
        trigger_conditional_variances.append(trigger_variance)
        activation_conditional_variances.append(activation_variance)

    expected_triggers = math.fsum(candidate_masses) * FALSE_POSITIVE_PROBABILITY
    expected_activation = math.fsum(activation_means) / len(templates)
    trigger_variance = math.fsum(trigger_conditional_variances) / len(
        templates
    ) + conditional_probability**2 * _population_variance(candidate_masses)
    activation_variance = math.fsum(activation_conditional_variances) / len(templates) + _population_variance(
        activation_means
    )
    iid_variance = total_candidates * FALSE_POSITIVE_PROBABILITY * (1 - FALSE_POSITIVE_PROBABILITY)
    projected_expected_triggers = projection_factor * expected_triggers
    projected_trigger_variance = projection_factor * math.fsum(trigger_conditional_variances) / len(
        templates
    ) + projection_factor**2 * conditional_probability**2 * _population_variance(candidate_masses)
    projected_iid_variance = projection_factor * iid_variance
    projected_design_effect = _ratio(projected_trigger_variance, projected_iid_variance)
    return {
        "assignment": (
            "Select exactly one of the three templates uniformly per training seed; use each template once "
            "across a three-seed Latin square. Candidate coins are independent at q=3/400 in the selected "
            "template and zero otherwise."
        ),
        "marginal_probability_over_randomized_template_assignment": FALSE_POSITIVE_PROBABILITY,
        "conditional_probability_in_selected_template": conditional_probability,
        "same_template_pair_covariance_including_across_groups": group_gate_pair_covariance(),
        "different_template_pair_covariance_exact_one_assignment": -(FALSE_POSITIVE_PROBABILITY**2),
        "groups": total_groups,
        "candidate_slots": total_candidates,
        "expected_trigger_slots_E_H": expected_triggers,
        "expected_any_trigger_groups": expected_activation,
        "trigger_count_variance_over_template_assignment_and_candidate_coins": trigger_variance,
        "trigger_count_variance_design_effect_vs_iid": _ratio(trigger_variance, iid_variance),
        "variance_heuristic_effective_trigger_events": (
            expected_triggers / (trigger_variance / iid_variance) if trigger_variance else None
        ),
        "activation_count_variance_over_template_assignment_and_candidate_coins": activation_variance,
        "per_selected_template": per_template,
        "projected_proportional_hard_subset": {
            "projection_factor": projection_factor,
            "expected_trigger_slots_E_H": projected_expected_triggers,
            "expected_any_trigger_groups": projection_factor * expected_activation,
            "trigger_count_variance": projected_trigger_variance,
            "iid_reference_trigger_count_variance": projected_iid_variance,
            "trigger_count_variance_design_effect_vs_iid": projected_design_effect,
            "variance_heuristic_effective_trigger_events": (
                projected_expected_triggers / projected_design_effect if projected_design_effect else None
            ),
            "activation_count_variance": (
                projection_factor * math.fsum(activation_conditional_variances) / len(templates)
                + projection_factor**2 * _population_variance(activation_means)
            ),
        },
    }


def realized_seed_gate_exposure(
    hard_groups: tuple[FrozenGroup, ...],
    *,
    projection_factor: float,
) -> dict[str, object]:
    if not hard_groups:
        raise ValueError("Realized gate exposure requires at least one hard group")
    if len({group.sample_id for group in hard_groups}) != len(hard_groups):
        raise ValueError("Frozen hard groups must have unique sample ids")
    if any(group.strict_count != 0 for group in hard_groups):
        raise ValueError("Realized gate exposure requires a strict-dead hard bank")
    for group in hard_groups:
        if len(group.candidate_slots) != group.candidate_count:
            raise ValueError("Frozen hard-group candidate slots do not match candidate_count")
        if len(set(group.candidate_slots)) != len(group.candidate_slots) or any(
            slot < 0 or slot >= PHYSICAL_GROUP_SIZE for slot in group.candidate_slots
        ):
            raise ValueError("Frozen hard-group candidate slots must be unique values in [0, 128)")
    total_groups = len(hard_groups)
    total_candidates = sum(group.candidate_count for group in hard_groups)
    marginal_trigger_target = total_candidates * FALSE_POSITIVE_PROBABILITY
    randomized_activation_target = math.fsum(
        GROUP_GATE_PROBABILITY * (1 - (1 - GROUP_GATE_CONDITIONAL_PROBABILITY) ** group.candidate_count)
        for group in hard_groups
    )
    randomized_nucleation_target = math.fsum(
        GROUP_GATE_PROBABILITY
        * (
            1
            - (1 - GROUP_GATE_CONDITIONAL_PROBABILITY) ** group.candidate_count
            - (
                GROUP_GATE_CONDITIONAL_PROBABILITY**group.candidate_count
                if group.candidate_count == PHYSICAL_GROUP_SIZE
                else 0.0
            )
        )
        for group in hard_groups
    )
    balance_margin = [0.90, 1.10]

    def summarize(open_groups: list[FrozenGroup], defect_seed: int) -> dict[str, object]:
        open_candidates = sum(group.candidate_count for group in open_groups)
        expected_triggers = open_candidates * GROUP_GATE_CONDITIONAL_PROBABILITY
        expected_any = math.fsum(
            1 - (1 - GROUP_GATE_CONDITIONAL_PROBABILITY) ** group.candidate_count for group in open_groups
        )
        expected_nucleation = math.fsum(
            1
            - (1 - GROUP_GATE_CONDITIONAL_PROBABILITY) ** group.candidate_count
            - (
                GROUP_GATE_CONDITIONAL_PROBABILITY**group.candidate_count
                if group.candidate_count == PHYSICAL_GROUP_SIZE
                else 0.0
            )
            for group in open_groups
        )
        realized_by_group = [
            sum(
                sample_slot_draw(group.sample_id, slot, defect_seed) < RUNTIME_GROUP_GATE_CONDITIONAL_PROBABILITY
                for slot in group.candidate_slots
            )
            for group in open_groups
        ]
        realized_triggers = sum(realized_by_group)
        realized_activations = sum(trigger_count > 0 for trigger_count in realized_by_group)
        realized_nucleations = sum(0 < trigger_count < PHYSICAL_GROUP_SIZE for trigger_count in realized_by_group)
        ratios = {
            "gate_open_group_count_over_one_third_target": _ratio(len(open_groups), total_groups / 3),
            "gate_open_candidate_mass_over_one_third_target": _ratio(open_candidates, total_candidates / 3),
            "expected_H_over_Cp_marginal_target": _ratio(expected_triggers, marginal_trigger_target),
            "expected_H_gt_0_over_randomized_law_target": _ratio(expected_any, randomized_activation_target),
            "expected_nucleations_over_randomized_law_target": _ratio(
                expected_nucleation, randomized_nucleation_target
            ),
        }
        balance_pass = all(
            value is not None and balance_margin[0] <= value <= balance_margin[1] for value in ratios.values()
        )
        return {
            "gate_open_groups": len(open_groups),
            "gate_open_group_fraction": len(open_groups) / total_groups,
            "gate_open_candidate_slots": open_candidates,
            "expected_trigger_slots_E_H_at_q": expected_triggers,
            "expected_any_trigger_groups_H_gt_0_at_q": expected_any,
            "expected_strict_dead_nucleation_groups_at_q": expected_nucleation,
            "expected_triggers_per_activated_group": _ratio(expected_triggers, expected_any),
            "realized_trigger_slots_H": realized_triggers,
            "realized_any_trigger_groups_H_gt_0": realized_activations,
            "realized_strict_dead_nucleation_groups": realized_nucleations,
            "realized_triggers_per_activated_group": _ratio(realized_triggers, realized_activations),
            "open_sample_id_set_sha256": canonical_json_sha256(sorted(group.sample_id for group in open_groups)),
            "expected_exposure_target_ratios": ratios,
            "expected_exposure_prelaunch_balance_margin": balance_margin,
            "expected_exposure_prelaunch_balance_pass": balance_pass,
            "projected_proportional_12k_op10_40_hard_contribution": {
                "projection_factor": projection_factor,
                "gate_open_groups": projection_factor * len(open_groups),
                "gate_open_candidate_slots": projection_factor * open_candidates,
                "expected_trigger_slots_E_H_at_q": projection_factor * expected_triggers,
                "expected_any_trigger_groups_H_gt_0_at_q": projection_factor * expected_any,
                "expected_strict_dead_nucleation_groups_at_q": projection_factor * expected_nucleation,
            },
        }

    per_seed: dict[str, object] = {}
    pooled_realized = {
        "group_gate_G": Counter[str](),
        "template_gate_T": Counter[str](),
    }
    for seed in DEFECT_SEEDS:
        selected_template = LATIN_SQUARE_TEMPLATE[seed]
        group_gate_open = [
            group for group in hard_groups if group_gate_draw(group.sample_id, seed) < GROUP_GATE_PROBABILITY
        ]
        template_gate_open = [group for group in hard_groups if group.template == selected_template]
        group_summary = summarize(group_gate_open, seed)
        template_summary = summarize(template_gate_open, seed)
        paired_ratios = {
            "G_over_T_gate_open_candidate_mass": _ratio(
                float(group_summary["gate_open_candidate_slots"]),
                float(template_summary["gate_open_candidate_slots"]),
            ),
            "G_over_T_expected_H": _ratio(
                float(group_summary["expected_trigger_slots_E_H_at_q"]),
                float(template_summary["expected_trigger_slots_E_H_at_q"]),
            ),
            "G_over_T_expected_H_gt_0": _ratio(
                float(group_summary["expected_any_trigger_groups_H_gt_0_at_q"]),
                float(template_summary["expected_any_trigger_groups_H_gt_0_at_q"]),
            ),
            "G_over_T_expected_nucleations": _ratio(
                float(group_summary["expected_strict_dead_nucleation_groups_at_q"]),
                float(template_summary["expected_strict_dead_nucleation_groups_at_q"]),
            ),
        }
        paired_realized_ratios = {
            "G_over_T_realized_H": _ratio(
                float(group_summary["realized_trigger_slots_H"]),
                float(template_summary["realized_trigger_slots_H"]),
            ),
            "G_over_T_realized_H_gt_0": _ratio(
                float(group_summary["realized_any_trigger_groups_H_gt_0"]),
                float(template_summary["realized_any_trigger_groups_H_gt_0"]),
            ),
            "G_over_T_realized_nucleations": _ratio(
                float(group_summary["realized_strict_dead_nucleation_groups"]),
                float(template_summary["realized_strict_dead_nucleation_groups"]),
            ),
        }
        for label, summary in (
            ("group_gate_G", group_summary),
            ("template_gate_T", template_summary),
        ):
            for field in (
                "realized_trigger_slots_H",
                "realized_any_trigger_groups_H_gt_0",
                "realized_strict_dead_nucleation_groups",
            ):
                pooled_realized[label][field] += int(summary[field])
        per_seed[str(seed)] = {
            "selected_template": selected_template,
            "group_gate_G": group_summary,
            "template_gate_T": template_summary,
            "paired_G_over_T_expected_exposure_ratios": paired_ratios,
            "paired_G_over_T_realized_ratios": paired_realized_ratios,
            "paired_expected_exposure_prelaunch_balance_margin": balance_margin,
            "paired_expected_exposure_prelaunch_balance_pass": all(
                value is not None and balance_margin[0] <= value <= balance_margin[1]
                for value in paired_ratios.values()
            ),
        }
    pooled_g = pooled_realized["group_gate_G"]
    pooled_t = pooled_realized["template_gate_T"]
    pooled_realized_report = {
        "group_gate_G": dict(pooled_g),
        "template_gate_T": dict(pooled_t),
        "G_over_T_realized_ratios": {
            "H": _ratio(pooled_g["realized_trigger_slots_H"], pooled_t["realized_trigger_slots_H"]),
            "H_gt_0": _ratio(
                pooled_g["realized_any_trigger_groups_H_gt_0"],
                pooled_t["realized_any_trigger_groups_H_gt_0"],
            ),
            "strict_dead_nucleations": _ratio(
                pooled_g["realized_strict_dead_nucleation_groups"],
                pooled_t["realized_strict_dead_nucleation_groups"],
            ),
        },
    }
    return {
        "hash_rule": "SHA-256(seed:defect-group-gate-v1:json(sample_id)); first 8 bytes / 2**64 < 1/3",
        "sample_slot_coin_hash_rule": ("SHA-256(seed:json([sample_id,rollout_slot])); first 8 bytes / 2**64 < p/alpha"),
        "template_assignment": {str(seed): LATIN_SQUARE_TEMPLATE[seed] for seed in DEFECT_SEEDS},
        "conditional_candidate_probability_q": GROUP_GATE_CONDITIONAL_PROBABILITY,
        "runtime_float_conditional_candidate_probability_q": RUNTIME_GROUP_GATE_CONDITIONAL_PROBABILITY,
        "frozen_hard_targets": {
            "groups": total_groups,
            "candidate_slots": total_candidates,
            "one_third_group_target": total_groups / 3,
            "one_third_candidate_mass_target": total_candidates / 3,
            "Cp_marginal_trigger_target": marginal_trigger_target,
            "randomized_law_expected_H_gt_0_target": randomized_activation_target,
            "randomized_law_expected_nucleation_target": randomized_nucleation_target,
        },
        "balance_diagnostic": (
            "The prelaunch [0.90,1.10] gate applies only to fixed-gate conditional expectations. Deterministic "
            "sample-slot coin realizations are reported separately and do not change that gate. This is not a "
            "seed-selection rule; failed arms must be reported and seeds must not be retuned."
        ),
        "balance_gate_basis": "conditional_expectation_given_fixed_gates",
        "per_seed": per_seed,
        "pooled_realized_coin_replay": pooled_realized_report,
        "all_seed_expected_exposure_balance_pass": all(
            bool(seed_summary["group_gate_G"]["expected_exposure_prelaunch_balance_pass"])
            and bool(seed_summary["template_gate_T"]["expected_exposure_prelaunch_balance_pass"])
            and bool(seed_summary["paired_expected_exposure_prelaunch_balance_pass"])
            for seed_summary in per_seed.values()
        ),
    }


def _validate_contract(
    root: Path,
    *,
    expected_contract_sha256: str | None,
) -> tuple[dict[str, Any], dict[str, Any], FileIdentity, FileIdentity, int]:
    manifest_path = root / "manifest.json"
    completion_path = root / "completion.json"
    manifest = _read_json_object(manifest_path)
    completion = _read_json_object(completion_path)
    if manifest.get("schema_version") != 1 or completion.get("schema_version") != 1:
        raise ValueError("Bank manifest and completion schema_version must both equal 1")
    contract_sha256 = _require_str(manifest.get("contract_sha256"), "manifest.contract_sha256")
    if expected_contract_sha256 is not None and contract_sha256 != expected_contract_sha256:
        raise ValueError(f"Bank contract SHA-256 is {contract_sha256}, expected {expected_contract_sha256}")
    if completion.get("contract_sha256") != contract_sha256:
        raise ValueError("Bank manifest and completion contract SHA-256 values differ")
    contract = _require_dict(manifest.get("contract"), "manifest.contract")
    if canonical_json_sha256(contract) != contract_sha256:
        raise ValueError("manifest.contract_sha256 does not match its canonical contract")
    if contract.get("operations") != list(BANK_OPERATIONS):
        raise ValueError("Frozen-bank operations differ from the Stage1b contract")
    examples_per_operation = _require_int(contract.get("examples_per_operation"), "examples_per_operation", minimum=1)
    sampling = _require_dict(contract.get("sampling"), "manifest.contract.sampling")
    if sampling.get("samples_per_prompt") != PHYSICAL_GROUP_SIZE:
        raise ValueError("Frozen-bank physical group size differs from 128")
    scoring = _require_dict(contract.get("scoring"), "manifest.contract.scoring")
    if scoring.get("candidate") != "answer_correct and not strict_correct":
        raise ValueError("Frozen-bank candidate definition differs")

    manifest_identity = file_identity(manifest_path)
    completion_identity = file_identity(completion_path)
    completion_manifest = _require_dict(completion.get("manifest"), "completion.manifest")
    _resolve_exact(root, completion_manifest.get("path"), "manifest.json", "completion.manifest.path")
    if completion_manifest.get("size_bytes") != manifest_identity.size_bytes:
        raise ValueError("completion.manifest.size_bytes does not match manifest.json")
    if completion_manifest.get("sha256") != manifest_identity.sha256:
        raise ValueError("completion.manifest.sha256 does not match manifest.json")
    return manifest, completion, manifest_identity, completion_identity, examples_per_operation


def _validate_row(row: object, *, line_number: int) -> tuple[int, int, int, str, str, int]:
    context = f"strict_results.jsonl:{line_number}"
    if not isinstance(row, dict) or set(row) != STRICT_RESULT_FIELDS:
        fields = sorted(row) if isinstance(row, dict) else type(row).__name__
        raise ValueError(f"{context}: strict-result fields differ: {fields}")
    operation = _require_int(row.get("op"), f"{context}.op")
    prompt_index = _require_int(row.get("__idx"), f"{context}.__idx")
    sample_rank = _require_int(row.get("sample_rank"), f"{context}.sample_rank")
    sample_id = _require_str(row.get("id"), f"{context}.id")
    template = _require_str(row.get("template"), f"{context}.template")
    for field_name in ("perfect", "answer_correct", "candidate"):
        if not isinstance(row.get(field_name), bool):
            raise ValueError(f"{context}.{field_name} must be boolean")
    expected_candidate = bool(row["answer_correct"] and not row["perfect"])
    if row["candidate"] != expected_candidate:
        raise ValueError(f"{context}: candidate != answer_correct and not perfect")
    return operation, prompt_index, sample_rank, sample_id, template, int(row["perfect"])


def _scan_strict_results(
    path: Path,
    *,
    completion: dict[str, Any],
    examples_per_operation: int,
    expected_strict_sha256: str | None,
) -> tuple[
    FileIdentity,
    Counter[tuple[int, int]],
    Counter[tuple[int, int]],
    dict[str, Counter[tuple[int, int]]],
    tuple[FrozenGroup, ...],
]:
    path = path.resolve()
    completion_artifacts = _require_dict(completion.get("artifacts"), "completion.artifacts")
    strict_record = _require_dict(completion_artifacts.get("strict_results"), "completion.artifacts.strict_results")
    _resolve_exact(path.parent, strict_record.get("path"), path.name, "strict_results.path")
    expected_rows = len(BANK_OPERATIONS) * examples_per_operation * PHYSICAL_GROUP_SIZE
    if strict_record.get("rows") != expected_rows:
        raise ValueError("completion strict-results row count differs from the bank contract")
    if strict_record.get("ordering") != "(op,__idx,sample_rank)":
        raise ValueError("completion strict-results ordering contract differs")
    recorded_sha256 = _require_str(strict_record.get("sha256"), "strict_results.sha256")
    if expected_strict_sha256 is not None and recorded_sha256 != expected_strict_sha256:
        raise ValueError(f"Recorded strict-results SHA-256 is {recorded_sha256}, expected {expected_strict_sha256}")

    all_histogram: Counter[tuple[int, int]] = Counter()
    hard_histogram: Counter[tuple[int, int]] = Counter()
    hard_template_histograms: dict[str, Counter[tuple[int, int]]] = defaultdict(Counter)
    hard_groups: list[FrozenGroup] = []
    digest = hashlib.sha256()
    size = 0
    rows = 0
    current_key: tuple[int, int] | None = None
    group_operation = -1
    group_prompt_index = -1
    group_sample_id = ""
    group_template = ""
    group_rows = 0
    group_strict = 0
    group_candidates = 0
    group_candidate_slots: list[int] = []

    def finish_group() -> None:
        nonlocal group_rows
        if current_key is None:
            return
        if group_rows != PHYSICAL_GROUP_SIZE:
            raise ValueError(f"Group {current_key} has {group_rows} rows, expected 128")
        entry = (group_strict, group_candidates)
        all_histogram[entry] += 1
        if group_operation in HARD_OPERATIONS:
            hard_histogram[entry] += 1
            hard_template_histograms[group_template][entry] += 1
            hard_groups.append(
                FrozenGroup(
                    operation=group_operation,
                    prompt_index=group_prompt_index,
                    sample_id=group_sample_id,
                    template=group_template,
                    strict_count=group_strict,
                    candidate_count=group_candidates,
                    candidate_slots=tuple(group_candidate_slots),
                )
            )

    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank JSONL records are not allowed")
            digest.update(line)
            size += len(line)
            rows += 1
            row = orjson.loads(line)
            operation, prompt_index, sample_rank, sample_id, template, perfect = _validate_row(
                row, line_number=line_number
            )
            key = (operation, prompt_index)
            if key != current_key:
                finish_group()
                current_key = key
                group_operation = operation
                group_prompt_index = prompt_index
                group_sample_id = sample_id
                group_template = template
                group_rows = 0
                group_strict = 0
                group_candidates = 0
                group_candidate_slots.clear()
                expected_group_number = BANK_OPERATIONS.index(operation) * examples_per_operation + prompt_index
                if expected_group_number != sum(all_histogram.values()):
                    raise ValueError(f"Group {key} is out of contracted operation/index order")
            if operation != group_operation or prompt_index != group_prompt_index:
                raise RuntimeError("Internal group state mismatch")
            if sample_id != group_sample_id or template != group_template:
                raise ValueError(f"Group {key} changes sample id or template within the group")
            if sample_rank != group_rows:
                raise ValueError(f"Group {key} rank {sample_rank} appears at position {group_rows}")
            group_rows += 1
            group_strict += perfect
            group_candidates += int(bool(row["candidate"]))
            if row["candidate"]:
                group_candidate_slots.append(sample_rank)
    finish_group()

    identity = FileIdentity(str(path), size, digest.hexdigest(), rows)
    if rows != expected_rows:
        raise ValueError(f"strict_results contains {rows} rows, expected {expected_rows}")
    if strict_record.get("size_bytes") != size:
        raise ValueError("completion strict-results size does not match the scanned file")
    if recorded_sha256 != identity.sha256:
        raise ValueError("completion strict-results SHA-256 does not match the scanned file")
    if sum(all_histogram.values()) != len(BANK_OPERATIONS) * examples_per_operation:
        raise ValueError("Frozen-bank group count differs from the contract")
    if sum(count * strict for (strict, _), count in hard_histogram.items()) != 0:
        raise ValueError("OP21-40 is not strict-dead in the frozen bank")
    if sorted(hard_template_histograms) != sorted(EXPECTED_TEMPLATES):
        raise ValueError("Frozen-bank template inventory differs from the Stage1b contract")
    return identity, all_histogram, hard_histogram, dict(hard_template_histograms), tuple(hard_groups)


def _scaled_summary(summary: dict[str, object], factor: float) -> dict[str, object]:
    design_effect = summary["trigger_count_variance_design_effect_vs_iid"]
    if design_effect is not None and not isinstance(design_effect, (int, float)):
        raise TypeError("design effect must be numeric")
    expected_triggers = float(summary["expected_trigger_slots_E_H"]) * factor
    return {
        "projection_factor": factor,
        "projected_groups": float(summary["groups"]) * factor,
        "expected_trigger_slots_E_H": expected_triggers,
        "expected_any_trigger_groups": float(summary["expected_any_trigger_groups"]) * factor,
        "expected_strict_dead_nucleation_groups": (float(summary["expected_strict_dead_nucleation_groups"]) * factor),
        "trigger_count_variance_fixed_C": float(summary["trigger_count_variance_fixed_C"]) * factor,
        "iid_reference_trigger_count_variance_fixed_C": (
            float(summary["iid_reference_trigger_count_variance_fixed_C"]) * factor
        ),
        "trigger_count_variance_design_effect_vs_iid": design_effect,
        "variance_heuristic_effective_trigger_events": (
            expected_triggers / float(design_effect) if design_effect else None
        ),
    }


def analyze(
    bank_root: Path,
    *,
    projected_total_groups: int = PROJECTED_TOTAL_GROUPS,
    expected_contract_sha256: str | None = EXPECTED_BANK_CONTRACT_SHA256,
    expected_strict_sha256: str | None = EXPECTED_STRICT_RESULTS_SHA256,
) -> dict[str, object]:
    if projected_total_groups <= 0:
        raise ValueError("projected_total_groups must be positive")
    bank_root = bank_root.expanduser().resolve()
    implementation_paths = {
        "analyzer": Path(__file__).resolve(),
        "runtime_environment": RSCI_ROOT / "rsci_gsm_infinite.py",
        "live_attempt_replay_analyzer": RSCI_ROOT / "analyze_masked_verifier_attempts.py",
    }
    implementations_before = {name: file_identity(path) for name, path in implementation_paths.items()}
    launch_config_contract, launch_config_identities_before = load_launch_config_contract()
    launch_config_contract_sha256 = canonical_json_sha256(launch_config_contract)
    manifest, completion, manifest_identity, completion_identity, examples_per_operation = _validate_contract(
        bank_root,
        expected_contract_sha256=expected_contract_sha256,
    )
    strict_identity, all_histogram, hard_histogram, hard_template_histograms, hard_groups = _scan_strict_results(
        bank_root / "strict_results.jsonl",
        completion=completion,
        examples_per_operation=examples_per_operation,
        expected_strict_sha256=expected_strict_sha256,
    )

    all_summaries = {arm: summarize_histogram(all_histogram, arm) for arm in ARM_LABELS}
    hard_summaries = {arm: summarize_histogram(hard_histogram, arm) for arm in ARM_LABELS}
    projection_factor = projected_total_groups / (len(TRAIN_OPERATIONS) * examples_per_operation)
    projected_hard = {arm: _scaled_summary(summary, projection_factor) for arm, summary in hard_summaries.items()}
    template_summary = template_persistent_summary(
        hard_template_histograms,
        projection_factor=projection_factor,
    )
    realized_seed_exposure = realized_seed_gate_exposure(
        hard_groups,
        projection_factor=projection_factor,
    )

    analysis_contract = {
        "physical_group_size_V": PHYSICAL_GROUP_SIZE,
        "candidate_definition": "answer_correct and not strict_correct",
        "per_candidate_marginal_p": FALSE_POSITIVE_PROBABILITY,
        "per_candidate_marginal_p_exact": "1/400",
        "arms": {
            "iid": "Independent Bernoulli(p) candidate triggers.",
            "exact_l1": (
                "Select one uniformly ranked physical slot and trigger it with q=128p=8/25 if it is a candidate."
            ),
            "group_gate": (
                "Independent group gate Bernoulli(alpha=1/3); within an open gate, candidate triggers are "
                "independent Bernoulli(q=3p=3/400)."
            ),
            "template_persistent": (
                "Select exactly one of three visible templates per seed and use q=3/400 on its candidates; "
                "Latin-square selected templates across three seeds."
            ),
            "all_or_none": "One shared Bernoulli(p) group coin triggers every candidate in the group.",
        },
        "activation_definition": "At least one defect trigger H>0.",
        "strict_dead_nucleation_definition": "S=0 and 0<H<V; all-positive groups are not update-producing.",
        "variance_design_effect": (
            "Var(sum H) divided by the iid fixed-C reference sum(C*p*(1-p)). The resulting effective-event "
            "count is a reward-count calibration heuristic, not a number of independent trained policies."
        ),
        "launch_config_contract_sha256": launch_config_contract_sha256,
        "expected_exposure_balance_margin": [0.90, 1.10],
        "realized_coin_replay_role": "reported mechanism diagnostic; not a seed, rate, or inclusion gate",
        "projection": {
            "requested_total_op10_40_groups": projected_total_groups,
            "sampling_assumption": (
                "Operation-balanced sampling over the 31 OP10-40 tasks with the frozen OP21-40 C distribution "
                "representative within each hard operation. Every frozen hard group statistic is multiplied by "
                "projected_total_groups/(31*examples_per_operation). This is a proportional expectation, not an "
                "exact dispatch-prefix replay; it excludes policy feedback, finalization order, and sampling variance."
            ),
            "expected_op21_40_groups": projected_total_groups * len(HARD_OPERATIONS) / len(TRAIN_OPERATIONS),
            "projection_factor_from_20k_frozen_hard_bank": projection_factor,
        },
    }
    report: dict[str, object] = {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_contract": analysis_contract,
        "analysis_contract_sha256": canonical_json_sha256(analysis_contract),
        "launch_config_contract": launch_config_contract,
        "launch_config_contract_sha256": launch_config_contract_sha256,
        "provenance": {
            "bank_contract_sha256": manifest["contract_sha256"],
            "inputs": {
                "bank_manifest": manifest_identity.as_dict(),
                "bank_completion": completion_identity.as_dict(),
                "bank_strict_results": strict_identity.as_dict(),
            },
            "implementations": {name: identity.as_dict() for name, identity in implementations_before.items()},
            "launch_configs": {name: identity.as_dict() for name, identity in launch_config_identities_before.items()},
            "python_version": sys.version,
            "orjson_version": orjson.__version__,
        },
        "integrity": {
            "bank_contract_canonical_hash_validated": True,
            "completion_manifest_identity_validated": True,
            "strict_results_completion_size_rows_hash_validated": True,
            "strict_result_exact_schema_candidate_identity_and_order_validated": True,
            "op21_40_strict_dead_validated": True,
            "templates_exactly_three_and_named_validated": True,
            "runtime_replay_and_six_arm_launch_contract_hash_bound": True,
            "realized_seed_gate_exposure_replayed": True,
            "bank_counts": {
                "groups": sum(all_histogram.values()),
                "trajectories": strict_identity.rows,
                "candidate_slots": sum(count * c for (_, c), count in all_histogram.items()),
                "strict_positive_slots": sum(count * s for (s, _), count in all_histogram.items()),
                "hard_groups": sum(hard_histogram.values()),
                "hard_candidate_slots": sum(count * c for (_, c), count in hard_histogram.items()),
            },
        },
        "activation_support_bounds": {
            "activation_bounds_for_C_gt_0": "p <= P(H>0|C) <= min(C*p,1)",
            "lower_bound_attained_by": "all_or_none",
            "upper_bound_attained_by_at_this_p_and_V": "exact_l1 because C*p <= 0.32",
            "pair_covariances": {
                "iid": 0.0,
                "exact_l1": exact_l_pair_covariance(1),
                "group_gate_same_group": group_gate_pair_covariance(),
                "all_or_none_same_group": FALSE_POSITIVE_PROBABILITY * (1 - FALSE_POSITIVE_PROBABILITY),
                "template_persistent_same_template_including_across_groups": group_gate_pair_covariance(),
                "template_persistent_different_templates_exact_one_assignment": -(FALSE_POSITIVE_PROBABILITY**2),
            },
        },
        "frozen_bank": {
            "distributions": {
                "all_identified_operations": render_frozen_distribution(all_histogram),
                "op21_40_strict_dead": render_frozen_distribution(hard_histogram),
            },
            "all_identified_operations": all_summaries,
            "op21_40_strict_dead": hard_summaries,
            "template_persistent_op21_40": template_summary,
            "realized_stage1b_gate_exposure_op21_40": realized_seed_exposure,
        },
        "projected_12k_op10_40_hard_contribution": {
            "independent_group_laws": projected_hard,
            "template_persistent": template_summary["projected_proportional_hard_subset"],
        },
        "interpretation_limits": [
            "The frozen C distribution is one temperature-0.7 base-policy draw on training prompts.",
            "Future C is a treatment-dependent mediator; the preflight does not predict on-policy feedback.",
            "Template marginals are exact over randomized one-of-three assignment and the three-seed Latin square, "
            "not homogeneous within a realized template-persistent run.",
            "The projected 12k values assume proportional operation/template representation and are not an exact "
            "asynchronous finalized-attempt prefix.",
        ],
    }
    implementations_after = {name: file_identity(path) for name, path in implementation_paths.items()}
    if implementations_after != implementations_before:
        raise RuntimeError("An analysis or runtime implementation changed while the preflight was running")
    _, launch_config_identities_after = load_launch_config_contract()
    if launch_config_identities_after != launch_config_identities_before:
        raise RuntimeError("A launch config changed while the preflight was running")
    if file_identity(bank_root / "manifest.json") != manifest_identity:
        raise RuntimeError("manifest.json changed while the preflight was running")
    if file_identity(bank_root / "completion.json") != completion_identity:
        raise RuntimeError("completion.json changed while the preflight was running")
    report["payload_without_self_hash_sha256"] = canonical_json_sha256(report)
    return report


def write_json_atomic(path: Path, payload: object) -> FileIdentity:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True).encode() + b"\n"
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
    finally:
        temporary.unlink(missing_ok=True)
    return file_identity(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank-root", type=Path, default=DEFAULT_BANK_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--projected-total-groups", type=int, default=PROJECTED_TOTAL_GROUPS)
    parser.add_argument("--expected-bank-contract-sha256", default=EXPECTED_BANK_CONTRACT_SHA256)
    parser.add_argument("--expected-strict-results-sha256", default=EXPECTED_STRICT_RESULTS_SHA256)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = analyze(
        args.bank_root,
        projected_total_groups=args.projected_total_groups,
        expected_contract_sha256=args.expected_bank_contract_sha256,
        expected_strict_sha256=args.expected_strict_results_sha256,
    )
    identity = write_json_atomic(args.output, report)
    print(json.dumps({"output": identity.as_dict()}, sort_keys=True))


if __name__ == "__main__":
    main()
