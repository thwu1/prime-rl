#!/usr/bin/env python3
"""Reproduce the dual-clock and shipped-cohort verifier-defect audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analyze_verifier_curriculum_rotation import (
    ArmContract,
    FileSnapshot,
    GroupAggregate,
    Observation,
    canonical_json_sha256,
    load_arm_contract,
    load_dataset_operations,
    parse_rollout_file,
    reconstruct_groups,
    sha256_file,
    summarize_groups,
)

DEFAULT_CURRICULUM_SUMMARY = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/verifier-defect-curriculum-20260807-040522/summary.json"
)
DEFAULT_CURRICULUM_SHA256 = "263f20da309fdccc5f1a9916519ba6b4575f0183ea3f64c6e2a4991aedd770ea"
DEFAULT_DESCRIPTIVE_SUMMARY = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/verifier-defect-descriptive-20260807-0345/summary.json"
)
DEFAULT_DESCRIPTIVE_SHA256 = "df17bb608b32a569cdd072e3aaa9bc846e4b3d1ea15f7e55f0f08f122bc11cd5"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
GROUP_COUNT_RE = re.compile(r"\bgroups fin=(?P<groups>\d+)\b")
SUCCESS_STEP_RE = re.compile(r"\bSUCCESS\b.*\bStep (?P<step>\d+) \|")
EXPECTED_LABELS = ("p00", "p01", "p05")
EXPECTED_CURRICULUM_SCHEMA_VERSION = 1
EXPECTED_DESCRIPTIVE_TIER = "descriptive-v2"
EXPECTED_ESTIMAND = "saved_shipped_cohort_conditional"


@dataclass(frozen=True)
class FrozenArm:
    contract: ArmContract
    observations: tuple[Observation, ...]
    groups: tuple[GroupAggregate, ...]
    rollout_manifest_sha256: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curriculum-summary", type=Path, default=DEFAULT_CURRICULUM_SUMMARY)
    parser.add_argument("--curriculum-sha256", default=DEFAULT_CURRICULUM_SHA256)
    parser.add_argument("--descriptive-summary", type=Path, default=DEFAULT_DESCRIPTIVE_SUMMARY)
    parser.add_argument("--descriptive-sha256", default=DEFAULT_DESCRIPTIVE_SHA256)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _json_equivalent(left: Any, right: Any) -> bool:
    normalized_left = json.loads(json.dumps(left))
    normalized_right = json.loads(json.dumps(right))
    return canonical_json_sha256(normalized_left) == canonical_json_sha256(normalized_right)


def load_pinned_json(path: Path, expected_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = path.expanduser().resolve()
    actual_sha256 = sha256_file(resolved)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"SHA256 mismatch for {resolved}: expected {expected_sha256}, found {actual_sha256}")
    with resolved.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {resolved}")
    return payload, {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": actual_sha256,
    }


def validate_summaries(curriculum: dict[str, Any], descriptive: dict[str, Any]) -> None:
    _require(
        curriculum.get("schema_version") == EXPECTED_CURRICULUM_SCHEMA_VERSION,
        f"Curriculum schema_version must be {EXPECTED_CURRICULUM_SCHEMA_VERSION}",
    )
    _require(
        curriculum.get("estimand", {}).get("id") == EXPECTED_ESTIMAND,
        f"Curriculum estimand must be {EXPECTED_ESTIMAND}",
    )
    _require(descriptive.get("analysis_tier") == EXPECTED_DESCRIPTIVE_TIER, "Unexpected descriptive tier")
    _require(
        descriptive.get("exposure_source") == "latest_logged_groups_fin_times_configured_group_size",
        "Unexpected descriptive exposure source",
    )
    curriculum_labels = tuple(sorted(curriculum.get("arms", {})))
    descriptive_labels = tuple(sorted(descriptive.get("runs", {})))
    _require(curriculum_labels == EXPECTED_LABELS, f"Unexpected curriculum labels: {curriculum_labels}")
    _require(descriptive_labels == EXPECTED_LABELS, f"Unexpected descriptive labels: {descriptive_labels}")

    analysis = curriculum.get("analysis", {})
    group_size = analysis.get("group_size")
    common_start = analysis.get("common_step_start")
    common_end = analysis.get("common_step_end")
    _require(isinstance(group_size, int) and group_size > 0, "Curriculum group_size must be positive")
    _require(common_start == 0 and isinstance(common_end, int) and common_end >= 0, "Invalid common step range")

    interval = descriptive.get("common_log_proxy_exposure_interval")
    _require(
        isinstance(interval, list) and len(interval) == 2 and interval[0] == 0 and interval[1] > 0,
        "Invalid common log-proxy exposure interval",
    )
    for label in EXPECTED_LABELS:
        arm = curriculum["arms"][label]
        run = descriptive["runs"][label]
        _require(arm.get("label") == label, f"Curriculum label mismatch for {label}")
        _require(float(arm.get("probability")) >= 0.0, f"Invalid probability for {label}")
        _require(run.get("group_size") == group_size, f"Group-size mismatch for {label}")
        _require(Path(arm["run_dir"]).resolve() == Path(run["path"]).resolve(), f"Run-path mismatch for {label}")
        curve = run.get("curve")
        _require(isinstance(curve, list) and len(curve) >= 2, f"Missing descriptive curve for {label}")
        _require(curve[0].get("step") == 0 and curve[0].get("E_log_proxy") == 0, f"{label} curve must start at 0")
        for left, right in zip(curve, curve[1:], strict=False):
            _require(right["step"] > left["step"], f"{label} curve steps are not strictly increasing")
            _require(
                right["E_log_proxy"] > left["E_log_proxy"],
                f"{label} curve exposures are not strictly increasing",
            )
        _require(run.get("last_step") == curve[-1]["step"], f"last_step mismatch for {label}")
        _require(
            run.get("last_log_proxy_exposure") == curve[-1]["E_log_proxy"],
            f"last exposure mismatch for {label}",
        )


def interpolate_curve(curve: list[dict[str, Any]], x_key: str, y_key: str, target: float) -> float:
    if target < float(curve[0][x_key]) or target > float(curve[-1][x_key]):
        raise ValueError(f"Target {target} is outside [{curve[0][x_key]}, {curve[-1][x_key]}]")
    for left, right in zip(curve, curve[1:], strict=False):
        left_x = float(left[x_key])
        right_x = float(right[x_key])
        if target == left_x:
            return float(left[y_key])
        if left_x < target <= right_x:
            weight = (target - left_x) / (right_x - left_x)
            return float(left[y_key]) + weight * (float(right[y_key]) - float(left[y_key]))
    return float(curve[-1][y_key])


def normalized_trapezoid_auc(
    curve: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    end: float,
) -> float:
    if float(curve[0][x_key]) != 0.0 or end <= 0:
        raise ValueError("AUC curve must begin at zero and have a positive endpoint")
    endpoint_value = interpolate_curve(curve, x_key, y_key, end)
    points = [(float(row[x_key]), float(row[y_key])) for row in curve if float(row[x_key]) < end]
    points.append((float(end), endpoint_value))
    area = sum(
        (right_x - left_x) * (left_y + right_y) / 2.0
        for (left_x, left_y), (right_x, right_y) in zip(points, points[1:], strict=False)
    )
    return area / end


def dual_clock_summary(descriptive: dict[str, Any]) -> dict[str, Any]:
    common_exposure = int(descriptive["common_log_proxy_exposure_interval"][1])
    common_step = min(int(descriptive["runs"][label]["last_step"]) for label in EXPECTED_LABELS)
    arms = {}
    for label in EXPECTED_LABELS:
        run = descriptive["runs"][label]
        curve = run["curve"]
        exposure_frontier_auc = normalized_trapezoid_auc(
            curve,
            "E_log_proxy",
            "frontier_op15_17_percent",
            common_exposure,
        )
        exposure_retention_auc = normalized_trapezoid_auc(
            curve,
            "E_log_proxy",
            "retention_op11_12_percent",
            common_exposure,
        )
        _require(
            math.isclose(exposure_frontier_auc, run["frontier_op15_17_auc_percent"], abs_tol=1e-12),
            f"Stored frontier exposure-AUC mismatch for {label}",
        )
        _require(
            math.isclose(exposure_retention_auc, run["retention_op11_12_auc_percent"], abs_tol=1e-12),
            f"Stored retention exposure-AUC mismatch for {label}",
        )
        arms[label] = {
            "frontier_op15_17_exposure_auc_percent": exposure_frontier_auc,
            "frontier_op15_17_step_auc_percent": normalized_trapezoid_auc(
                curve,
                "step",
                "frontier_op15_17_percent",
                common_step,
            ),
            "retention_op11_12_exposure_auc_percent": exposure_retention_auc,
            "retention_op11_12_step_auc_percent": normalized_trapezoid_auc(
                curve,
                "step",
                "retention_op11_12_percent",
                common_step,
            ),
            "interpolated_updates_at_common_exposure": interpolate_curve(
                curve,
                "E_log_proxy",
                "step",
                common_exposure,
            ),
            "log_proxy_exposure_at_common_step": interpolate_curve(
                curve,
                "step",
                "E_log_proxy",
                common_step,
            ),
            "frontier_endpoint_at_common_exposure_percent": interpolate_curve(
                curve,
                "E_log_proxy",
                "frontier_op15_17_percent",
                common_exposure,
            ),
        }
    control = arms["p00"]
    for label, row in arms.items():
        row["frontier_exposure_auc_delta_vs_p00_percent"] = (
            row["frontier_op15_17_exposure_auc_percent"] - control["frontier_op15_17_exposure_auc_percent"]
        )
        row["frontier_step_auc_delta_vs_p00_percent"] = (
            row["frontier_op15_17_step_auc_percent"] - control["frontier_op15_17_step_auc_percent"]
        )
        row["updates_per_p00_update_at_common_exposure"] = (
            row["interpolated_updates_at_common_exposure"] / control["interpolated_updates_at_common_exposure"]
        )
    return {
        "common_log_proxy_exposure": common_exposure,
        "common_optimizer_step": common_step,
        "curve_interpolation": "piecewise_linear_between_periodic_complete_evaluations",
        "arms": arms,
    }


def conversion_composition(summary: dict[str, int], group_size: int) -> dict[str, Any]:
    raw_groups = int(summary["raw_complete_groups"])
    candidates = int(summary["candidate_rows"])
    strict = int(summary["strict_positive_rows"])
    answer_correct = strict + candidates
    return {
        "raw_complete_groups": raw_groups,
        "mixed_proxy_groups": int(summary["mixed_proxy_groups"]),
        "mixed_strict_groups": int(summary["mixed_strict_groups"]),
        "defect_only_groups": int(summary["defect_activated_groups"]),
        "candidate_rows": candidates,
        "strict_positive_rows": strict,
        "candidate_row_rate": candidates / (group_size * raw_groups) if raw_groups else None,
        "strict_row_rate": strict / (group_size * raw_groups) if raw_groups else None,
        "strict_share_of_answer_correct": strict / answer_correct if answer_correct else None,
        "mixed_proxy_group_rate": summary["mixed_proxy_groups"] / raw_groups if raw_groups else None,
        "mixed_strict_group_rate": summary["mixed_strict_groups"] / raw_groups if raw_groups else None,
        "defect_only_group_rate": summary["defect_activated_groups"] / raw_groups if raw_groups else None,
    }


def _window_names(curriculum: dict[str, Any]) -> dict[str, str]:
    window_size = int(curriculum["analysis"]["window_size"])
    middle_start = window_size
    middle_end = 2 * window_size - 1
    middle = f"steps_{middle_start:04d}_{middle_end:04d}"
    for label in EXPECTED_LABELS:
        _require(middle in curriculum["arms"][label]["windows"], f"Missing middle window for {label}")
    return {"early": "early", "middle": middle, "late": "late"}


def band_window_composition(curriculum: dict[str, Any]) -> dict[str, Any]:
    group_size = int(curriculum["analysis"]["group_size"])
    bands = [f"op{lower}_{upper}" for lower, upper in curriculum["analysis"]["primary_bands"]]
    source_windows = _window_names(curriculum)
    arms = {}
    for label in EXPECTED_LABELS:
        arm_output = {}
        for output_name, source_name in source_windows.items():
            window = curriculum["arms"][label]["windows"][source_name]
            band_output = {}
            for band in bands:
                band_output[band] = conversion_composition(window["bands"][band], group_size)
            arm_output[output_name] = {
                "step_start": window["step_start"],
                "step_end": window["step_end"],
                "bands": band_output,
            }
        arms[label] = arm_output
    return {
        "estimand": EXPECTED_ESTIMAND,
        "definition": "repeated_cross_sectional_answer_correct_composition_not_longitudinal_conversion",
        "arms": arms,
    }


def _manifest_snapshots(arm_summary: dict[str, Any], contract: ArmContract) -> list[FileSnapshot]:
    manifest = arm_summary["rollout_manifest"]
    rows = manifest["files"]
    _require(len(rows) == manifest["file_count"], f"Manifest file-count mismatch for {contract.label}")
    snapshots = []
    for expected_step, row in enumerate(rows):
        step = int(row["step"])
        _require(step == expected_step, f"Non-contiguous frozen manifest for {contract.label} at {step}")
        path = contract.rollout_dir / f"step_{step}" / "train_rollouts.jsonl"
        stat = path.stat()
        _require(stat.st_size == row["size_bytes"], f"Frozen file size changed: {path}")
        snapshots.append(FileSnapshot(step=step, path=path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns))
    return snapshots


def load_frozen_arm(
    label: str,
    curriculum: dict[str, Any],
    dataset_path: Path,
    dataset_operations: list[int],
) -> FrozenArm:
    arm_summary = curriculum["arms"][label]
    contract = load_arm_contract(label, Path(arm_summary["run_dir"]), dataset_path)
    _require(contract.config_sha256 == arm_summary["config"]["sha256"], f"Config hash mismatch for {label}")
    _require(contract.probability == float(arm_summary["probability"]), f"Probability mismatch for {label}")
    observations = []
    parsed_manifest = []
    explicit_totals = {
        key: 0 for key in ("proxy_metric_explicit", "candidate_metric_explicit", "trigger_metric_explicit")
    }
    for snapshot, expected in zip(
        _manifest_snapshots(arm_summary, contract), arm_summary["rollout_manifest"]["files"], strict=True
    ):
        rows, identity, explicit = parse_rollout_file(snapshot, contract, dataset_operations)
        _require(identity["sha256"] == expected["sha256"], f"Frozen rollout hash mismatch: {snapshot.path}")
        _require(identity["rows"] == expected["rows"], f"Frozen rollout row-count mismatch: {snapshot.path}")
        observations.extend(rows)
        parsed_manifest.append(
            {"step": identity["step"], "size_bytes": identity["size_bytes"], "sha256": identity["sha256"]}
        )
        for key, value in explicit.items():
            explicit_totals[key] += value

    _require(
        all(not observation.strict or observation.answer_correct for observation in observations),
        f"Strict reward does not imply answer correctness for {label}",
    )

    expected_manifest = arm_summary["rollout_manifest"]
    manifest_sha256 = canonical_json_sha256(parsed_manifest)
    _require(manifest_sha256 == expected_manifest["sha256"], f"Rollout manifest hash mismatch for {label}")
    _require(len(observations) == expected_manifest["row_count"], f"Rollout row total mismatch for {label}")
    _require(
        sum(row["size_bytes"] for row in parsed_manifest) == expected_manifest["size_bytes"],
        f"Size total mismatch for {label}",
    )
    for key, value in explicit_totals.items():
        _require(value == arm_summary["metric_provenance"][key], f"Metric provenance mismatch for {label}: {key}")

    groups, _, coverage = reconstruct_groups(observations, dataset_operations, contract.group_size)
    _require(
        _json_equivalent(coverage, arm_summary["group_coverage"]),
        f"Group reconstruction mismatch for {label}",
    )
    return FrozenArm(
        contract=contract,
        observations=tuple(observations),
        groups=tuple(groups),
        rollout_manifest_sha256=manifest_sha256,
    )


def validate_group_windows(
    curriculum: dict[str, Any],
    arms: dict[str, FrozenArm],
    dataset_operations: list[int],
) -> None:
    operations = list(range(min(dataset_operations), max(dataset_operations) + 1))
    for label, arm in arms.items():
        for source_name in _window_names(curriculum).values():
            expected = curriculum["arms"][label]["windows"][source_name]
            selected = [
                group
                for group in arm.groups
                if int(expected["step_start"]) <= group.anchor_step <= int(expected["step_end"])
            ]
            actual = summarize_groups(selected, operations)
            _require(actual["summary"] == expected["summary"], f"Window summary mismatch for {label}/{source_name}")
            _require(actual["bands"] == expected["bands"], f"Band summary mismatch for {label}/{source_name}")


def activation_diagnostic(
    groups: list[GroupAggregate] | tuple[GroupAggregate, ...], probability: float
) -> dict[str, Any]:
    eligible = [group for group in groups if group.strict_positive == 0 and group.candidate > 0]
    activated = [group for group in eligible if 0 < group.proxy_positive < group.saved_rows]
    if any(group.proxy_positive != group.trigger for group in eligible):
        raise ValueError("Strict-zero proxy positives and observed triggers disagree")
    expected = sum(
        1.0
        - (1.0 - probability) ** group.candidate
        - (probability**group.candidate if group.candidate == group.saved_rows else 0.0)
        for group in eligible
    )
    candidates = sum(group.candidate for group in groups)
    triggers = sum(group.trigger for group in groups)
    eligible_count = len(eligible)
    observed_count = len(activated)
    observed_rate = observed_count / eligible_count if eligible_count else None
    expected_rate = expected / eligible_count if eligible_count else None
    return {
        "eligible_zero_strict_candidate_groups": eligible_count,
        "observed_activated_groups": observed_count,
        "expected_mixed_proxy_groups_under_unconditional_bernoulli": expected,
        "observed_activation_rate": observed_rate,
        "expected_activation_rate_under_unconditional_bernoulli": expected_rate,
        "activation_rate_difference": (
            observed_rate - expected_rate if observed_rate is not None and expected_rate is not None else None
        ),
        "candidate_rows": candidates,
        "trigger_rows": triggers,
        "trigger_fraction_of_candidates": triggers / candidates if candidates else None,
    }


def saved_cohort_activation(
    curriculum: dict[str, Any],
    arms: dict[str, FrozenArm],
) -> dict[str, Any]:
    source_windows = _window_names(curriculum)
    diagnostics = {}
    for label, arm in arms.items():
        arm_output = {}
        selections = {"common": (0, int(curriculum["analysis"]["common_step_end"]))}
        for output_name, source_name in source_windows.items():
            window = curriculum["arms"][label]["windows"][source_name]
            selections[output_name] = (int(window["step_start"]), int(window["step_end"]))
        for name, (start, end) in selections.items():
            selected = [group for group in arm.groups if start <= group.anchor_step <= end]
            hard = [group for group in selected if 21 <= group.operation <= 40]
            arm_output[name] = {
                "step_start": start,
                "step_end": end,
                "all_operations": activation_diagnostic(selected, arm.contract.probability),
                "op21_40": activation_diagnostic(hard, arm.contract.probability),
            }
        diagnostics[label] = arm_output
    return {
        "estimand": EXPECTED_ESTIMAND,
        "unconditional_group_formula": "1-(1-p)^K-I[K=V]*p^K for strict-zero groups with K candidates",
        "conditioning_warning": (
            "Observed groups are conditional on saved shipped optimizer cohorts; zero-trainable batch attempts are absent."
        ),
        "arms": diagnostics,
    }


def parse_success_exposure_prefix(
    log_path: Path, max_step: int, group_size: int
) -> tuple[dict[int, int], dict[str, Any]]:
    latest_groups = 0
    previous_groups = 0
    exposures = {}
    digest = hashlib.sha256()
    size_bytes = 0
    found_cutoff = False
    with log_path.open("rb") as handle:
        for raw_line in handle:
            digest.update(raw_line)
            size_bytes += len(raw_line)
            line = ANSI_RE.sub("", raw_line.decode(errors="replace"))
            for match in GROUP_COUNT_RE.finditer(line):
                latest_groups = int(match.group("groups"))
                if latest_groups < previous_groups:
                    raise ValueError(f"Finalized-group counter decreased in {log_path}")
                previous_groups = latest_groups
            success = SUCCESS_STEP_RE.search(line)
            if success is None:
                continue
            step = int(success.group("step"))
            if step > max_step:
                raise ValueError(f"Encountered step {step} before cutoff step {max_step} in {log_path}")
            if step in exposures:
                raise ValueError(f"Duplicate success step {step} in {log_path}")
            exposures[step] = latest_groups * group_size
            if step == max_step:
                found_cutoff = True
                break
    if not found_cutoff:
        raise ValueError(f"No success record for cutoff step {max_step} in {log_path}")
    missing = sorted(set(range(max_step + 1)) - set(exposures))
    if missing:
        raise ValueError(f"Missing success steps through {max_step} in {log_path}: {missing[:20]}")
    return exposures, {
        "path": str(log_path.resolve()),
        "prefix_through_success_step": max_step,
        "prefix_size_bytes": size_bytes,
        "prefix_sha256": digest.hexdigest(),
        "exposure_source": "latest_logged_groups_fin_before_success_step_times_group_size",
    }


def _first_strict_row(
    arm: FrozenArm,
    dataset_operations: list[int],
    lower: int,
    upper: int,
    exposure_by_step: dict[int, int],
) -> dict[str, Any] | None:
    candidates = [
        observation
        for observation in arm.observations
        if observation.strict == 1 and lower <= dataset_operations[observation.task_idx] <= upper
    ]
    if not candidates:
        return None
    first = min(candidates, key=lambda observation: (observation.step, observation.task_idx))
    matching_groups = [
        group
        for group in arm.groups
        if group.task_idx == first.task_idx and group.first_step <= first.step <= group.last_step
    ]
    _require(len(matching_groups) == 1, f"Could not uniquely map first strict row for {arm.contract.label}")
    group = matching_groups[0]
    return {
        "first_strict_row_step": first.step,
        "operation": group.operation,
        "task_idx": group.task_idx,
        "group_anchor_step": group.anchor_step,
        "group_first_step": group.first_step,
        "group_last_step": group.last_step,
        "group_strict_positive_rows": group.strict_positive,
        "group_candidate_rows": group.candidate,
        "group_trigger_rows": group.trigger,
        "log_proxy_exposure_at_success_step": exposure_by_step[first.step],
    }


def first_strict_rows(
    curriculum: dict[str, Any],
    arms: dict[str, FrozenArm],
    dataset_operations: list[int],
) -> dict[str, Any]:
    output = {}
    group_size = int(curriculum["analysis"]["group_size"])
    for label, arm in arms.items():
        max_step = int(curriculum["arms"][label]["rollout_manifest"]["step_end"])
        log_path = Path(curriculum["arms"][label]["run_dir"]) / "logs" / "orchestrator.log"
        exposures, provenance = parse_success_exposure_prefix(log_path, max_step, group_size)
        output[label] = {
            "log_prefix": provenance,
            "op15_20": _first_strict_row(arm, dataset_operations, 15, 20, exposures),
            "op21_40": _first_strict_row(arm, dataset_operations, 21, 40, exposures),
        }
    return {
        "row_step_is_exact": True,
        "exposure_is_legacy_log_proxy": True,
        "arms": output,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    temporary.replace(destination)


def build_audit(
    curriculum: dict[str, Any],
    descriptive: dict[str, Any],
    curriculum_identity: dict[str, Any],
    descriptive_identity: dict[str, Any],
) -> dict[str, Any]:
    validate_summaries(curriculum, descriptive)
    dataset_path = Path(curriculum["dataset"]["path"])
    dataset_operations, dataset_identity = load_dataset_operations(dataset_path)
    for key in ("size_bytes", "sha256", "rows", "operation_counts"):
        _require(
            _json_equivalent(dataset_identity[key], curriculum["dataset"][key]),
            f"Dataset identity mismatch: {key}",
        )

    analyzer_identity = curriculum["analyzer"]
    _require(
        sha256_file(Path(analyzer_identity["path"])) == analyzer_identity["sha256"],
        "Curriculum analyzer implementation hash mismatch",
    )
    arms = {label: load_frozen_arm(label, curriculum, dataset_path, dataset_operations) for label in EXPECTED_LABELS}
    validate_group_windows(curriculum, arms, dataset_operations)
    return {
        "schema_version": 1,
        "analysis_id": "verifier_defect_threshold_dual_clock_v1",
        "inputs": {
            "curriculum_summary": curriculum_identity,
            "descriptive_summary": descriptive_identity,
            "curriculum_snapshot_at": curriculum["snapshot_at"],
            "dataset": dataset_identity,
            "rollout_manifest_sha256": {label: arm.rollout_manifest_sha256 for label, arm in arms.items()},
        },
        "dual_clock": dual_clock_summary(descriptive),
        "band_window_conversion_composition": band_window_composition(curriculum),
        "first_strict_rows": first_strict_rows(curriculum, arms, dataset_operations),
        "saved_cohort_activation_vs_bernoulli": saved_cohort_activation(curriculum, arms),
        "identifiability": {
            "exactly_observed": [
                "reward identities and trigger draws in saved rows",
                "composition of conservatively reconstructed exact-128 groups in saved shipped cohorts",
                "first saved strict-positive row and its legacy log-proxy exposure",
            ],
            "not_identified": [
                "population activation or nucleation hazard over all dispatched groups",
                "longitudinal conversion of a candidate trajectory into a strict trajectory",
                "recipient-specific causal effect of a false-positive update",
                "a phase transition from these one-seed three-arm traces",
            ],
        },
    }


def main() -> None:
    implementation_path = Path(__file__).resolve()
    implementation_sha256 = sha256_file(implementation_path)
    args = parse_args()
    curriculum, curriculum_identity = load_pinned_json(args.curriculum_summary, args.curriculum_sha256)
    descriptive, descriptive_identity = load_pinned_json(args.descriptive_summary, args.descriptive_sha256)
    payload = build_audit(curriculum, descriptive, curriculum_identity, descriptive_identity)
    final_implementation_sha256 = sha256_file(implementation_path)
    if final_implementation_sha256 != implementation_sha256:
        raise RuntimeError(
            "Audit implementation changed while the analysis was running: "
            f"{implementation_sha256} -> {final_implementation_sha256}"
        )
    payload["implementation"] = {
        "path": str(implementation_path),
        "sha256": implementation_sha256,
    }
    atomic_write_json(args.output, payload)
    print(args.output.expanduser().resolve())


if __name__ == "__main__":
    main()
