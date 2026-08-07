#!/usr/bin/env python3
"""Compare verifier-defect RL arms at matched optimizer and raw-exposure clocks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import orjson
from scipy.stats import binomtest

SCHEMA_VERSION = 2
REQUIRED_LABELS = ("p00", "p01", "p05")
EVAL_OPERATIONS = tuple(range(11, 46))
FRONTIER_OPERATIONS = tuple(range(15, 18))
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
MIXED_POLICY_RE = re.compile(
    r"\bEval heldout-op(?P<operation>\d+)-strict step (?P<step>\d+) "
    r"had mixed policy versions:\s*(?P<versions>\[[^]]*])"
)
EVAL_COMPLETE_RE = re.compile(
    r"\bEvaluated heldout-op(?P<operation>\d+)-strict \(Step (?P<step>\d+)\) "
    r"\| Policy v(?P<policy>\d+)\b"
)
BANDS = {
    "retention_op11_14": tuple(range(11, 15)),
    "frontier_op15_17": tuple(range(15, 18)),
    "bridge_op15_20": tuple(range(15, 21)),
    "hard_train_op21_40": tuple(range(21, 41)),
    "unseen_op41_45": tuple(range(41, 46)),
    "all_op11_45": tuple(range(11, 46)),
}


@dataclass(frozen=True)
class CheckpointScores:
    label: str
    step: int
    keys: tuple[tuple[int, int], ...]
    prompt_hashes: tuple[str, ...]
    scores: np.ndarray
    files: tuple[dict[str, Any], ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, metavar="LABEL=RUN_ROOT")
    parser.add_argument("--exposure-summary", type=Path, required=True)
    parser.add_argument("--optimizer-step", type=int, required=True)
    parser.add_argument("--expected-rows", type=int, default=200)
    parser.add_argument("--bootstrap-replicates", type=int, default=20_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260807)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    if args.optimizer_step < 0:
        raise ValueError("--optimizer-step must be non-negative")
    if args.expected_rows < 1:
        raise ValueError("--expected-rows must be positive")
    if args.bootstrap_replicates < 1:
        raise ValueError("--bootstrap-replicates must be positive")
    if args.bootstrap_seed < 0:
        raise ValueError("--bootstrap-seed must be non-negative")
    return args


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "size_bytes": stat.st_size, "sha256": file_sha256(path)}


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def parse_runs(values: list[str]) -> dict[str, Path]:
    runs: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        if not separator or not label or not raw_path:
            raise ValueError(f"Invalid --run {value!r}; expected LABEL=RUN_ROOT")
        if label in runs:
            raise ValueError(f"Duplicate run label: {label}")
        runs[label] = Path(raw_path).expanduser().resolve()
    if tuple(sorted(runs)) != REQUIRED_LABELS:
        raise ValueError(f"Runs must be exactly {REQUIRED_LABELS}, got {tuple(sorted(runs))}")
    return runs


def _run_layout_candidates(run_root: Path) -> tuple[Path, ...]:
    if run_root.name == "run_default":
        return (run_root, run_root.parent)
    return (run_root / "run_default", run_root)


def rollout_root(run_root: Path) -> Path:
    candidates = tuple(base / "rollouts" for base in _run_layout_candidates(run_root))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError(f"No rollout root under {run_root}")


def orchestrator_log_path(run_root: Path) -> Path:
    candidates = tuple(base / "logs" / "orchestrator.log" for base in _run_layout_candidates(run_root))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"No orchestrator log under {run_root}")


def audit_eval_policy_versions(
    run_root: Path,
    requested_steps: set[int],
    *,
    operations: tuple[int, ...] = EVAL_OPERATIONS,
) -> dict[str, Any]:
    if not requested_steps:
        raise ValueError("At least one evaluation step is required for the policy audit")
    if any(step < 0 for step in requested_steps):
        raise ValueError(f"Evaluation steps must be non-negative: {sorted(requested_steps)}")
    operation_set = set(operations)
    completions: dict[int, dict[int, int]] = {step: {} for step in requested_steps}
    mixed_versions: dict[int, dict[int, tuple[int, ...]]] = {step: {} for step in requested_steps}
    log_path = orchestrator_log_path(run_root)
    log_snapshot = log_path.read_bytes()
    selected_records: list[dict[str, Any]] = []
    for raw_line in log_snapshot.decode("utf-8").splitlines():
        line = ANSI_RE.sub("", raw_line)
        completion = EVAL_COMPLETE_RE.search(line)
        if completion is not None:
            step = int(completion.group("step"))
            if step in requested_steps:
                operation = int(completion.group("operation"))
                if operation not in operation_set:
                    raise ValueError(f"Unexpected held-out OP{operation} completion at step {step} in {log_path}")
                if operation in completions[step]:
                    raise ValueError(f"Duplicate held-out OP{operation} completion at step {step} in {log_path}")
                policy = int(completion.group("policy"))
                completions[step][operation] = policy
                selected_records.append(
                    {"kind": "completion", "step": step, "operation": operation, "policy_label": policy}
                )
        mixed = MIXED_POLICY_RE.search(line)
        if mixed is None:
            continue
        step = int(mixed.group("step"))
        if step not in requested_steps:
            continue
        operation = int(mixed.group("operation"))
        if operation not in operation_set:
            raise ValueError(f"Unexpected held-out OP{operation} policy warning at step {step} in {log_path}")
        if operation in mixed_versions[step]:
            raise ValueError(f"Duplicate held-out OP{operation} policy warning at step {step} in {log_path}")
        parsed_versions = json.loads(mixed.group("versions"))
        if (
            not isinstance(parsed_versions, list)
            or len(parsed_versions) < 2
            or any(isinstance(version, bool) or not isinstance(version, int) for version in parsed_versions)
            or parsed_versions != sorted(set(parsed_versions))
        ):
            raise ValueError(f"Invalid mixed policy versions at step {step} OP{operation}: {parsed_versions!r}")
        mixed_versions[step][operation] = tuple(parsed_versions)
        selected_records.append(
            {"kind": "mixed_policy", "step": step, "operation": operation, "versions": parsed_versions}
        )

    checkpoints = {}
    for step in sorted(requested_steps):
        observed_operations = set(completions[step])
        if observed_operations != operation_set:
            missing = sorted(operation_set - observed_operations)
            unexpected = sorted(observed_operations - operation_set)
            raise ValueError(
                f"Held-out evaluation completions differ at step {step} in {log_path}: "
                f"missing={missing}, unexpected={unexpected}"
            )
        if not set(mixed_versions[step]).issubset(operation_set):
            raise ValueError(f"Mixed-policy operations differ at step {step} in {log_path}")
        for operation, versions in mixed_versions[step].items():
            if completions[step][operation] != min(versions):
                raise ValueError(
                    f"Logged policy label is not the minimum mixed version at step {step} OP{operation}: "
                    f"label={completions[step][operation]}, versions={list(versions)}"
                )
        adjacent_versions = (step - 1, step, step + 1)
        adjacent_operations = sorted(
            operation for operation, versions in mixed_versions[step].items() if versions == adjacent_versions
        )
        completion_histogram = Counter(completions[step].values())
        version_set_histogram = Counter(mixed_versions[step].values())
        checkpoints[str(step)] = {
            "expected_operations": list(operations),
            "completed_operations": len(completions[step]),
            "completion_policy_label_histogram": {
                str(policy): count for policy, count in sorted(completion_histogram.items())
            },
            "completion_policy_label_semantics": (
                "The orchestrator logs the minimum policy version among surviving evaluation rows; "
                "this is not a row-level policy-version distribution."
            ),
            "mixed_policy_operations": len(mixed_versions[step]),
            "mixed_operation_ids": sorted(mixed_versions[step]),
            "non_mixed_operation_ids": sorted(operation_set - set(mixed_versions[step])),
            "mixed_version_set_histogram": {
                json.dumps(list(versions), separators=(",", ":")): count
                for versions, count in sorted(version_set_histogram.items())
            },
            "expected_adjacent_policy_versions": list(adjacent_versions),
            "operations_with_expected_adjacent_versions": adjacent_operations,
            "all_operations_mixed": set(mixed_versions[step]) == operation_set,
            "all_operations_have_expected_adjacent_versions": set(adjacent_operations) == operation_set,
        }
    return {
        "orchestrator_log_snapshot": {
            "path": str(log_path),
            "size_bytes": len(log_snapshot),
            "sha256": hashlib.sha256(log_snapshot).hexdigest(),
        },
        "selected_policy_records": {
            "count": len(selected_records),
            "canonical_sha256": canonical_json_sha256(
                sorted(
                    selected_records,
                    key=lambda record: (
                        record["step"],
                        record["operation"],
                        record["kind"],
                    ),
                )
            ),
        },
        "requested_steps": sorted(requested_steps),
        "checkpoints": checkpoints,
    }


def load_checkpoint(
    label: str,
    run_root: Path,
    step: int,
    *,
    operations: tuple[int, ...] = tuple(range(11, 46)),
    expected_rows: int = 200,
) -> CheckpointScores:
    step_dir = rollout_root(run_root) / f"step_{step}"
    keys: list[tuple[int, int]] = []
    prompt_hashes: list[str] = []
    scores: list[int] = []
    files = []
    for operation in operations:
        path = step_dir / f"eval_rollouts_heldout-op{operation}-strict.jsonl"
        files.append({"operation": operation, **file_identity(path)})
        observed: dict[int, tuple[str, int]] = {}
        with path.open("rb") as handle:
            for line_number, line in enumerate(handle, start=1):
                row = orjson.loads(line)
                task = row.get("task")
                metrics = row.get("metrics")
                rewards = row.get("rewards")
                if not isinstance(task, dict) or not isinstance(metrics, dict) or not isinstance(rewards, dict):
                    raise ValueError(f"Malformed evaluation row at {path}:{line_number}")
                index = task.get("idx")
                prompt = task.get("prompt")
                strict = metrics.get("strict_dependency_graph_reward")
                reward = rewards.get("reward")
                if isinstance(index, bool) or not isinstance(index, int) or not isinstance(prompt, str):
                    raise ValueError(f"Invalid prompt identity at {path}:{line_number}")
                if strict not in (0, 1, 0.0, 1.0) or float(reward) != float(strict):
                    raise ValueError(f"Evaluation is not clean binary strict reward at {path}:{line_number}")
                if index in observed:
                    raise ValueError(f"Duplicate prompt index {index} in {path}")
                observed[index] = (hashlib.sha256(prompt.encode()).hexdigest(), int(strict))
        if sorted(observed) != list(range(expected_rows)):
            raise ValueError(f"OP{operation} prompt indices differ at step {step} for {label}")
        for index in range(expected_rows):
            prompt_hash, strict = observed[index]
            keys.append((operation, index))
            prompt_hashes.append(prompt_hash)
            scores.append(strict)
    return CheckpointScores(
        label=label,
        step=step,
        keys=tuple(keys),
        prompt_hashes=tuple(prompt_hashes),
        scores=np.asarray(scores, dtype=np.int8),
        files=tuple(files),
    )


def validate_pairing(checkpoints: dict[str, CheckpointScores]) -> None:
    reference = checkpoints["p00"]
    for label, checkpoint in checkpoints.items():
        if checkpoint.keys != reference.keys:
            raise ValueError(f"Prompt keys differ between p00 and {label}")
        if checkpoint.prompt_hashes != reference.prompt_hashes:
            raise ValueError(f"Prompt texts differ between p00 and {label}")


def stratified_bootstrap_interval(
    differences: np.ndarray,
    operations: np.ndarray,
    band_operations: tuple[int, ...],
    *,
    replicates: int,
    seed: int,
) -> list[float]:
    rng = np.random.default_rng(seed)
    samples = np.zeros(replicates, dtype=np.float64)
    for operation in band_operations:
        operation_values = differences[operations == operation]
        draws = rng.integers(0, len(operation_values), size=(replicates, len(operation_values)))
        samples += operation_values[draws].mean(axis=1)
    samples *= 100.0 / len(band_operations)
    lower, upper = np.quantile(samples, (0.025, 0.975))
    return [float(lower), float(upper)]


def paired_band_contrast(
    control: CheckpointScores,
    treatment: CheckpointScores,
    band_operations: tuple[int, ...],
    *,
    bootstrap_replicates: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    operations = np.fromiter((operation for operation, _ in control.keys), dtype=np.int16)
    mask = np.isin(operations, band_operations)
    control_scores = control.scores[mask]
    treatment_scores = treatment.scores[mask]
    differences = treatment_scores.astype(np.int16) - control_scores.astype(np.int16)
    treatment_only = int(np.sum((treatment_scores == 1) & (control_scores == 0)))
    control_only = int(np.sum((treatment_scores == 0) & (control_scores == 1)))
    discordant = treatment_only + control_only
    p_value = float(binomtest(treatment_only, discordant, 0.5).pvalue) if discordant else 1.0
    return {
        "operations": list(band_operations),
        "prompts": int(mask.sum()),
        "control_correct": int(control_scores.sum()),
        "treatment_correct": int(treatment_scores.sum()),
        "control_percent": 100.0 * float(control_scores.mean()),
        "treatment_percent": 100.0 * float(treatment_scores.mean()),
        "paired_difference_treatment_minus_control_pp": 100.0 * float(differences.mean()),
        "paired_stratified_bootstrap_95_interval_pp": stratified_bootstrap_interval(
            differences,
            operations[mask],
            band_operations,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
        ),
        "discordant": {
            "treatment_only_correct": treatment_only,
            "control_only_correct": control_only,
            "total": discordant,
        },
        "exact_mcnemar_two_sided_p": p_value,
    }


def load_exposure_summary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("analysis_tier") != "descriptive-v2":
        raise ValueError("Exposure summary must be descriptive-v2")
    if payload.get("endpoint_selection") != "posthoc_common_support":
        raise ValueError("Exposure summary endpoint selection must be posthoc_common_support")
    runs = payload.get("runs")
    if not isinstance(runs, dict) or tuple(sorted(runs)) != REQUIRED_LABELS:
        raise ValueError("Exposure summary run labels differ")
    return payload


def _frontier_curve(summary: dict[str, Any], label: str) -> list[tuple[int, float]]:
    points = []
    for raw_point in summary["runs"][label]["curve"]:
        step = raw_point.get("step")
        value = raw_point.get("frontier_op15_17_percent")
        if isinstance(step, bool) or not isinstance(step, int) or step < 0:
            raise ValueError(f"Invalid optimizer step in exposure summary for {label}: {step!r}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"Invalid OP15-17 score in exposure summary for {label} step {step}: {value!r}")
        points.append((step, float(value)))
    if not points or points[0][0] != 0:
        raise ValueError(f"Exposure summary frontier curve for {label} must start at step 0")
    if any(left[0] >= right[0] for left, right in zip(points, points[1:], strict=False)):
        raise ValueError(f"Exposure summary frontier curve for {label} is not strictly increasing")
    return points


def _interpolate_curve(points: list[tuple[int, float]], target: int) -> float:
    if not points[0][0] <= target <= points[-1][0]:
        raise ValueError(f"Target {target} is outside curve interval [{points[0][0]}, {points[-1][0]}]")
    for index, (step, value) in enumerate(points):
        if step == target:
            return value
        if step > target:
            left_step, left_value = points[index - 1]
            fraction = (target - left_step) / (step - left_step)
            return left_value + fraction * (value - left_value)
    raise AssertionError("Curve interpolation did not return")


def _normalized_step_auc(points: list[tuple[int, float]], horizon: int) -> float:
    if horizon <= 0:
        raise ValueError("Optimizer-step AUC horizon must be positive")
    coordinates = [(step, value) for step, value in points if step < horizon]
    coordinates.append((horizon, _interpolate_curve(points, horizon)))
    area = math.fsum(
        (right_step - left_step) * (left_value + right_value) / 2.0
        for (left_step, left_value), (right_step, right_value) in zip(coordinates, coordinates[1:], strict=False)
    )
    return area / horizon


def _contrasts_from_control(values: dict[str, float]) -> dict[str, float]:
    return {f"{label}_minus_p00": values[label] - values["p00"] for label in ("p01", "p05")}


def frontier_curve_sensitivity(
    summary: dict[str, Any], optimizer_step: int, *, last_common_evals: int = 5
) -> dict[str, Any]:
    if last_common_evals < 1:
        raise ValueError("last_common_evals must be positive")
    curves = {label: _frontier_curve(summary, label) for label in REQUIRED_LABELS}
    auc_values = {label: _normalized_step_auc(curve, optimizer_step) for label, curve in curves.items()}
    step_maps = {label: dict(curve) for label, curve in curves.items()}
    common_steps = sorted(set.intersection(*(set(step_map) for step_map in step_maps.values())))
    common_steps = [step for step in common_steps if step <= optimizer_step]
    if len(common_steps) < last_common_evals:
        raise ValueError(
            f"Only {len(common_steps)} common frontier evaluations through step {optimizer_step}; "
            f"need {last_common_evals}"
        )
    tail_steps = common_steps[-last_common_evals:]
    tail_means = {
        label: math.fsum(step_maps[label][step] for step in tail_steps) / len(tail_steps) for label in REQUIRED_LABELS
    }
    raw_auc_values = {label: float(summary["runs"][label]["frontier_op15_17_auc_percent"]) for label in REQUIRED_LABELS}
    raw_interval = summary["common_log_proxy_exposure_interval"]
    return {
        "operations": list(FRONTIER_OPERATIONS),
        "optimizer_step_clock": {
            "horizon_step": optimizer_step,
            "normalized_trapezoid_auc_percent": auc_values,
            "contrasts_to_p00_pp": _contrasts_from_control(auc_values),
            "last_common_evaluation_steps": tail_steps,
            "mean_over_last_common_evaluations_percent": tail_means,
            "last_common_evaluation_contrasts_to_p00_pp": _contrasts_from_control(tail_means),
        },
        "log_proxy_exposure_clock": {
            "interval": [int(raw_interval[0]), int(raw_interval[1])],
            "normalized_trapezoid_auc_percent": raw_auc_values,
            "contrasts_to_p00_pp": _contrasts_from_control(raw_auc_values),
            "source": "frontier_op15_17_auc_percent from the supplied descriptive-v2 exposure summary",
        },
    }


def exposure_at_step(summary: dict[str, Any], label: str, step: int) -> int:
    points = [point for point in summary["runs"][label]["curve"] if point.get("step") == step]
    if len(points) != 1:
        raise ValueError(f"Exposure summary has {len(points)} points for {label} step {step}")
    return int(points[0]["E_log_proxy"])


def nearest_exposure_steps(summary: dict[str, Any]) -> tuple[int, dict[str, int], dict[str, int]]:
    interval = summary.get("common_log_proxy_exposure_interval")
    if not isinstance(interval, list) or len(interval) != 2:
        raise ValueError("Exposure summary has no common interval")
    target = int(interval[1])
    steps = {}
    exposures = {}
    for label in REQUIRED_LABELS:
        curve = summary["runs"][label]["curve"]
        point = min(curve, key=lambda item: (abs(int(item["E_log_proxy"]) - target), int(item["step"])))
        steps[label] = int(point["step"])
        exposures[label] = int(point["E_log_proxy"])
    return target, steps, exposures


def analyze_clock(
    name: str,
    run_roots: dict[str, Path],
    steps: dict[str, int],
    exposures: dict[str, int],
    *,
    target_log_proxy_exposure: int | None,
    expected_rows: int,
    bootstrap_replicates: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    checkpoints = {
        label: load_checkpoint(label, run_roots[label], steps[label], expected_rows=expected_rows)
        for label in REQUIRED_LABELS
    }
    validate_pairing(checkpoints)
    contrasts = {}
    for treatment_index, treatment in enumerate(("p01", "p05"), start=1):
        contrasts[f"{treatment}_minus_p00"] = {
            band: paired_band_contrast(
                checkpoints["p00"],
                checkpoints[treatment],
                operations,
                bootstrap_replicates=bootstrap_replicates,
                bootstrap_seed=bootstrap_seed + 1000 * treatment_index + band_index,
            )
            for band_index, (band, operations) in enumerate(BANDS.items())
        }
    exposure_range = [min(exposures.values()), max(exposures.values())]
    result = {
        "clock": name,
        "steps": steps,
        "log_proxy_exposures": exposures,
        "log_proxy_exposure_range": exposure_range,
        "log_proxy_exposure_range_width": exposure_range[1] - exposure_range[0],
        "prompt_sequence_sha256": canonical_json_sha256(
            [[*key, prompt_hash] for key, prompt_hash in zip(checkpoints["p00"].keys, checkpoints["p00"].prompt_hashes)]
        ),
        "checkpoint_files": {label: list(checkpoint.files) for label, checkpoint in checkpoints.items()},
        "contrasts": contrasts,
    }
    if target_log_proxy_exposure is not None:
        if target_log_proxy_exposure <= 0:
            raise ValueError("Raw-exposure target must be positive")
        signed_deviations = {label: exposure - target_log_proxy_exposure for label, exposure in exposures.items()}
        result["log_proxy_exposure_target_audit"] = {
            "target": target_log_proxy_exposure,
            "signed_deviation_by_arm": signed_deviations,
            "absolute_deviation_by_arm": {label: abs(value) for label, value in signed_deviations.items()},
            "relative_deviation_percent_by_arm": {
                label: 100.0 * value / target_log_proxy_exposure for label, value in signed_deviations.items()
            },
            "maximum_absolute_relative_deviation_percent": max(
                100.0 * abs(value) / target_log_proxy_exposure for value in signed_deviations.values()
            ),
            "exposure_range_width_over_target_percent": (
                100.0 * (exposure_range[1] - exposure_range[0]) / target_log_proxy_exposure
            ),
        }
    return result


def main() -> None:
    args = parse_args()
    run_roots = parse_runs(args.run)
    summary_path = args.exposure_summary.expanduser().resolve()
    summary = load_exposure_summary(summary_path)

    optimizer_steps = {label: args.optimizer_step for label in REQUIRED_LABELS}
    optimizer_exposures = {label: exposure_at_step(summary, label, args.optimizer_step) for label in REQUIRED_LABELS}
    target_exposure, raw_steps, raw_exposures = nearest_exposure_steps(summary)
    policy_audits = {
        label: audit_eval_policy_versions(run_roots[label], {args.optimizer_step, raw_steps[label]})
        for label in REQUIRED_LABELS
    }
    clocks = {
        "matched_optimizer_step": analyze_clock(
            "matched_optimizer_step",
            run_roots,
            optimizer_steps,
            optimizer_exposures,
            target_log_proxy_exposure=None,
            expected_rows=args.expected_rows,
            bootstrap_replicates=args.bootstrap_replicates,
            bootstrap_seed=args.bootstrap_seed,
        ),
        "nearest_common_log_proxy_exposure": analyze_clock(
            "nearest_common_log_proxy_exposure",
            run_roots,
            raw_steps,
            raw_exposures,
            target_log_proxy_exposure=target_exposure,
            expected_rows=args.expected_rows,
            bootstrap_replicates=args.bootstrap_replicates,
            bootstrap_seed=args.bootstrap_seed + 1_000_000,
        ),
    }
    selected_policy_audits = [
        checkpoint for audit in policy_audits.values() for checkpoint in audit["checkpoints"].values()
    ]
    all_selected_evaluations_mixed = all(checkpoint["all_operations_mixed"] for checkpoint in selected_policy_audits)
    all_selected_evaluations_adjacent = all(
        checkpoint["all_operations_have_expected_adjacent_versions"] for checkpoint in selected_policy_audits
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": "verifier_defect_main_v2_paired_clocks",
        "causal_claim_valid": False,
        "phase_transition_claim_valid": False,
        "run_roots": {label: str(path) for label, path in run_roots.items()},
        "optimizer_step_target": args.optimizer_step,
        "common_log_proxy_exposure_target": target_exposure,
        "endpoint_selection": summary["endpoint_selection"],
        "expected_rows_per_operation": args.expected_rows,
        "bootstrap": {
            "replicates": args.bootstrap_replicates,
            "seed": args.bootstrap_seed,
            "unit": "paired prompts, resampled independently within operation",
            "interval": "exploratory percentile interval without finite-population correction",
        },
        "exposure_summary": file_identity(summary_path),
        "implementation": file_identity(Path(__file__)),
        "evaluation_policy_audit": {
            "all_selected_evaluations_mixed_policy": all_selected_evaluations_mixed,
            "all_selected_evaluations_have_step_minus_one_step_step_plus_one_versions": (
                all_selected_evaluations_adjacent
            ),
            "runs": policy_audits,
        },
        "frontier_curve_sensitivity": frontier_curve_sensitivity(summary, args.optimizer_step),
        "inference_scope": {
            "training_runs_per_arm": 1,
            "prompt_pairing_conditions_on_realized_trained_policies": True,
            "bootstrap_and_mcnemar_cover_evaluation_prompt_uncertainty_only": True,
            "treatment_effect_uncertainty_estimable": False,
        },
        "clocks": clocks,
        "warnings": [
            "The raw-exposure clock is a periodic finalized-group log proxy, not exact policy exposure.",
            "The raw-exposure endpoint is a post-hoc nearest match on live common support; use the target-deviation audit and adjacent curve summaries.",
            "The three arms have one independent training run each (n=1 per arm); prompt pairing reduces evaluation noise only.",
            "The paired bootstrap intervals and exact McNemar p-values condition on the realized trained policies and do not quantify treatment-effect uncertainty.",
            "Exact McNemar p-values are descriptive, are not multiplicity-adjusted, and must not be read as experimental treatment significance.",
            (
                "Every selected held-out evaluation mixes policy versions; checkpoint contrasts are contrasts between logged policy mixtures."
                if all_selected_evaluations_mixed
                else "Some selected held-out evaluations mix policy versions; inspect the per-operation policy audit."
            ),
            "Neither three doses nor finite checkpoints establish a phase transition.",
        ],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output_json": str(args.output_json.resolve()),
                "optimizer_steps": optimizer_steps,
                "raw_steps": raw_steps,
                "raw_exposures": raw_exposures,
                "all_selected_evaluations_mixed_policy": all_selected_evaluations_mixed,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
