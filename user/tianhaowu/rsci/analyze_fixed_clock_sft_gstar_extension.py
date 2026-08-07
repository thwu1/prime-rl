#!/usr/bin/env python3
"""Discover and validate analysis cells for the fixed-clock Gstar extension."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import build_fixed_clock_sft_gstar_extension as gstar
import materialize_fixed_clock_sft_gstar_runs as runs
import materialize_fixed_clock_sft_runs as v2_runs

ANALYSIS_ID = "verifier_defect_fixed_clock_sft_gstar_analysis_v1"
SCHEMA_VERSION = 1
DEFAULT_EXTENSION_INDEX = gstar.DEFAULT_OUTPUT_DIR / "arm_index.json"
DEFAULT_PAIRED_LAUNCH_MANIFEST = runs.DEFAULT_PAIRED_LAUNCH_MANIFEST


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-index", type=Path, default=DEFAULT_EXTENSION_INDEX)
    parser.add_argument("--paired-launch-manifest", type=Path, default=DEFAULT_PAIRED_LAUNCH_MANIFEST)
    parser.add_argument("--launch-manifest", type=Path)
    parser.add_argument("--eval-launch-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def write_json_once(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if not path.is_file() or path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"Refusing to replace a different analysis registry: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(encoded, encoding="utf-8")
    partial.replace(path)


def build_registry(
    *,
    extension_index_path: Path,
    paired_launch_manifest_path: Path,
    launch_manifest_path: Path | None,
    eval_launch_manifest_path: Path | None = None,
) -> dict[str, Any]:
    extension_index_path = extension_index_path.expanduser().resolve()
    extension = gstar.validate_output(extension_index_path.parent, deep_selection_check=False)
    paired_launch_manifest_path = paired_launch_manifest_path.expanduser().resolve()
    paired = v2_runs.validate_launch_manifest(paired_launch_manifest_path)
    if paired["manifest"]["inputs"]["arm_index"]["sha256"] != extension["source_v2_index"]["sha256"]:
        raise ValueError("The analysis source launch is not paired to the extension's v2 index")
    paired_by_label = {arm["label"]: arm for arm in paired["manifest"]["arms"]}

    extension_launch: dict[str, Any] | None = None
    if launch_manifest_path is not None:
        validated = runs.validate_launch_manifest(launch_manifest_path)
        submission_status = runs.submission_status(validated)
        extension_launch = {
            "identity": v2_runs.file_identity(Path(validated["manifest_path"])),
            "manifest_sha256": validated["manifest_sha256"],
            "source_parent_commit_sha": validated["manifest"]["source"]["parent_commit_sha"],
            "submission_status": submission_status,
            "submitted": submission_status["submitted"],
        }
        launch_by_label = {arm["label"]: arm for arm in validated["manifest"]["arms"]}
    else:
        launch_by_label = {}

    evaluation_launch: dict[str, Any] | None = None
    if eval_launch_manifest_path is not None:
        import materialize_fixed_clock_sft_gstar_evals as evals

        eval_validated = evals.validate_eval_launch_manifest(eval_launch_manifest_path)
        if extension_launch is not None:
            training_identity = eval_validated["manifest"]["training_launch_manifest"]
            if training_identity["sha256"] != extension_launch["manifest_sha256"]:
                raise ValueError("Gstar evaluation launch belongs to a different training launch")
        evaluation_launch = {
            "identity": v2_runs.file_identity(Path(eval_validated["manifest_path"])),
            "manifest_sha256": eval_validated["manifest_sha256"],
            "evaluation_count": len(eval_validated["manifest"]["tasks"]),
            "common_step_evaluation_count": eval_validated["manifest"]["common_step_evaluation_count"],
            "distinct_final_evaluation_count": eval_validated["manifest"]["distinct_final_evaluation_count"],
            "evaluation_contract": eval_validated["manifest"]["evaluation_contract"],
            "submission_status": evals.submission_status(eval_validated),
        }

    cells: list[dict[str, Any]] = []
    readout_tasks: list[dict[str, Any]] = []
    for entry in extension["arms"]:
        source_labels = {
            "behavior": entry["source_behavior_label"],
            "shuffled": entry["source_shuffled_label"],
            "global": entry["source_global_label"],
        }
        if any(label not in paired_by_label for label in source_labels.values()):
            raise ValueError(f"Paired launch omits a comparison arm for {entry['label']}")
        schedule = {
            "max_steps": 64 if entry["clock"] == "fixed_m" else max(64, (2 * entry["rows"] + 31) // 32),
        }
        schedule["readout_steps"] = sorted({64, schedule["max_steps"]})
        launch_record = launch_by_label.get(entry["label"])
        if launch_manifest_path is not None and launch_record is None:
            raise ValueError(f"Extension launch omits {entry['label']}")
        cell = {
            "gstar_label": entry["label"],
            "seed": entry["selection_seed"],
            "clock": entry["clock"],
            "dose": entry["dose"],
            "dose_label": entry["dose_label"],
            "raw_prefix_trajectories": entry["raw_prefix_trajectories"],
            "candidate_a_quota": entry["candidate_a_quota"],
            "noncandidate_quota": entry["noncandidate_quota"],
            "hard_recipient_rows": entry["hard_recipient_rows"],
            "source_labels": source_labels,
            "contrasts": {
                "s_minus_gstar": {
                    "left": source_labels["shuffled"],
                    "right": entry["label"],
                    "matched": [
                        "observed prefix",
                        "total recipients",
                        "candidate-A recipients",
                        "noncandidate recipients",
                        "clean anchors",
                        "training schedule",
                    ],
                    "varied": "within-prompt versus separate-class global recipient allocation",
                },
                "gstar_minus_g": {
                    "left": entry["label"],
                    "right": source_labels["global"],
                    "matched": [
                        "observed prefix",
                        "total recipients",
                        "clean anchors",
                        "training schedule",
                    ],
                    "varied": "exact recipient candidate composition",
                },
                "b_minus_gstar": {
                    "left": source_labels["behavior"],
                    "right": entry["label"],
                    "matched": [
                        "observed prefix",
                        "total recipients",
                        "clean anchors",
                        "training schedule",
                    ],
                    "varied": "recipient behavior identity, prompt allocation, and candidate composition",
                },
            },
            "schedule": schedule,
            "extension_output_dir": launch_record["output_dir"] if launch_record is not None else None,
            "paired_v2_output_dirs": {
                assignment: paired_by_label[label]["output_dir"] for assignment, label in source_labels.items()
            },
        }
        cells.append(cell)
        for step in schedule["readout_steps"]:
            readout_tasks.append(
                {
                    "arm_label": entry["label"],
                    "step": step,
                    "target": "strict OP11-45 pass@1",
                    "comparison_labels": source_labels,
                }
            )

    fixed_m_cells = sum(cell["clock"] == "fixed_m" for cell in cells)
    fixed_raw_cells = sum(cell["clock"] == "fixed_raw" for cell in cells)
    if len(cells) != 15 or fixed_m_cells != 9 or fixed_raw_cells != 6:
        raise ValueError("Analysis registry does not contain the 9+6 canonical Gstar cells")
    cells.sort(key=lambda cell: cell["gstar_label"])
    readout_tasks.sort(key=lambda task: (task["arm_label"], task["step"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "study_id": gstar.STUDY_ID,
        "extension_index": v2_runs.file_identity(extension_index_path),
        "paired_v2_launch_manifest": v2_runs.file_identity(paired_launch_manifest_path),
        "paired_v2_launch_manifest_sha256": paired["manifest_sha256"],
        "extension_launch": extension_launch,
        "evaluation_launch": evaluation_launch,
        "implementation": v2_runs.file_identity(Path(__file__)),
        "cell_count": len(cells),
        "fixed_m_cell_count": fixed_m_cells,
        "fixed_raw_cell_count": fixed_raw_cells,
        "readout_task_count": len(readout_tasks),
        "readout_contract": {
            "metric": "strict pass@1",
            "operations": list(range(11, 46)),
            "prompts_per_operation": 200,
            "samples_per_prompt": 1,
            "defect_or_proxy_reward_used": False,
        },
        "cells": cells,
        "readout_tasks": readout_tasks,
    }


def main() -> None:
    args = parse_args()
    registry = build_registry(
        extension_index_path=args.extension_index,
        paired_launch_manifest_path=args.paired_launch_manifest,
        launch_manifest_path=args.launch_manifest,
        eval_launch_manifest_path=args.eval_launch_manifest,
    )
    if args.output is not None:
        write_json_once(args.output.expanduser().resolve(), registry)
    print(
        json.dumps(
            {
                "analysis_id": registry["analysis_id"],
                "cell_count": registry["cell_count"],
                "readout_task_count": registry["readout_task_count"],
                "output": str(args.output.expanduser().resolve()) if args.output is not None else None,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
