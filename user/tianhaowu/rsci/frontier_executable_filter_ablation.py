#!/usr/bin/env python
"""Train and evaluate strict-filter traces that pass deterministic execution grading."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from frontier_loop import (
    RETRYABLE_STATES,
    SlurmJobError,
    append_status,
    evaluation_config,
    file_sha256,
    inference_config,
    load_frontier_config,
    now,
    sft_config,
    submit_eval,
    submit_sft,
    wait_for_job,
    write_json,
    write_toml_once,
)

SOURCE_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/strict-correct")
SOURCE_CONFIG = Path("user/tianhaowu/rsci/configs/frontier/strict_correct.toml")
OUTPUT_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/executable-filtered-strict")
ORIGINAL_METRICS = SOURCE_ROOT / "iterations/op28/post_selected_eval/metrics.json"
ORACLE_METRICS = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/"
    "oracle-matched-strict/iterations/op28/post_selected_eval/metrics.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", type=int, default=28)
    parser.add_argument("--poll-seconds", type=int, default=60)
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, cwd="/storage/home/tianhaowu/prime-rl", check=True)


def implementation_sha256() -> dict[str, str]:
    script_dir = Path(__file__).parent
    return {
        name: file_sha256(script_dir / name)
        for name in (
            "frontier_build_executable_dataset.py",
            "frontier_executable_filter_ablation.py",
            "frontier_select_checkpoint.py",
            "strict_trajectory_grader.py",
            "solution_graph.py",
        )
    }


def initialize_state(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    state_path = OUTPUT_ROOT / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["operation"] != args.operation:
            raise ValueError("Existing executable-filter state uses a different operation")
        current_implementation = implementation_sha256()
        if state["implementation_sha256"] != current_implementation:
            if (OUTPUT_ROOT / "cumulative_dataset/manifest.json").exists():
                raise ValueError("Implementation changed after executable-filter data materialization")
            state["implementation_sha256"] = current_implementation
            state["implementation_updated_at"] = now()
            write_json(state_path, state)
            append_status(
                OUTPUT_ROOT,
                "driver implementation updated before dataset materialization",
                {"implementation_updated_at": state["implementation_updated_at"]},
            )
        return state, state_path
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    state = {
        "track": "executable-filtered-strict",
        "operation": args.operation,
        "source_root": str(SOURCE_ROOT),
        "status": "building_datasets",
        "jobs": {},
        "created_at": now(),
        "implementation_sha256": implementation_sha256(),
    }
    write_json(state_path, state)
    append_status(OUTPUT_ROOT, "executable-filter ablation initialized", state)
    return state, state_path


def build_datasets(args: argparse.Namespace) -> tuple[Path, Path]:
    train_dir = OUTPUT_ROOT / "cumulative_dataset"
    validation_dir = OUTPUT_ROOT / "cumulative_validation_dataset"
    audit_path = OUTPUT_ROOT / "held_out_audit.json"
    if not audit_path.exists():
        run(
            [
                "uv",
                "run",
                "--no-sync",
                "user/tianhaowu/rsci/frontier_build_executable_dataset.py",
                "--source-root",
                str(SOURCE_ROOT),
                "--output-root",
                str(OUTPUT_ROOT),
                "--through-operation",
                str(args.operation),
            ]
        )
    return train_dir, validation_dir


def wait_with_retries(
    state: dict[str, Any],
    state_path: Path,
    key: str,
    submit,
    artifact: Path,
    poll_seconds: int,
    max_attempts: int = 3,
) -> int:
    new_attempt = False
    while True:
        job_id = submit(new_attempt)
        try:
            wait_for_job(job_id, artifact, poll_seconds)
            return job_id
        except SlurmJobError as error:
            attempts = len(state["jobs"][key].get("attempts", [state["jobs"][key]]))
            if error.state not in RETRYABLE_STATES or attempts >= max_attempts:
                raise
            append_status(
                OUTPUT_ROOT,
                f"{key} retry",
                {"failed_job": job_id, "state": error.state, "next_attempt": attempts + 1},
            )
            new_attempt = True


def metric_table(metrics: dict[str, Any]) -> dict[str, dict[str, float]]:
    return {metric: metrics[metric]["total"]["unbiased"] for metric in ("strict_graph", "answer_only")}


def write_comparison(clean_metrics_path: Path) -> Path:
    clean = metric_table(json.loads(clean_metrics_path.read_text(encoding="utf-8")))
    original = metric_table(json.loads(ORIGINAL_METRICS.read_text(encoding="utf-8")))
    oracle = metric_table(json.loads(ORACLE_METRICS.read_text(encoding="utf-8")))
    key = "pass@1"
    strict_value = original["strict_graph"][key]
    oracle_value = oracle["strict_graph"][key]
    clean_value = clean["strict_graph"][key]
    payload = {
        "benchmark": "OP28, identical 200 prompts x 128 rollouts",
        "original_strict_filter": original,
        "executable_filtered_strict": clean,
        "matched_canonical_oracle": oracle,
        "strict_pass_at_1": {
            "original": strict_value,
            "cleaned": clean_value,
            "oracle": oracle_value,
            "cleaned_minus_original": clean_value - strict_value,
            "oracle_minus_cleaned": oracle_value - clean_value,
            "fraction_of_oracle_gap_closed": (clean_value - strict_value) / (oracle_value - strict_value),
        },
    }
    path = OUTPUT_ROOT / "comparison.json"
    write_json(path, payload)
    return path


def main() -> None:
    args = parse_args()
    if args.operation != 28:
        raise ValueError("This ablation is fixed to the completed OP11–28 strict/oracle comparison")
    state, state_path = initialize_state(args)
    frontier = load_frontier_config(SOURCE_CONFIG)
    frontier = {**frontier, "track": "executable-filtered-strict", "experiment_root": str(OUTPUT_ROOT)}

    train_dir, validation_dir = build_datasets(args)
    train_manifest = json.loads((train_dir / "manifest.json").read_text(encoding="utf-8"))
    validation_manifest = json.loads((validation_dir / "manifest.json").read_text(encoding="utf-8"))
    max_steps = int(train_manifest["training_plan"]["optimizer_steps_for_one_epoch"])
    append_status(
        OUTPUT_ROOT,
        "executable-filtered datasets ready",
        {
            "training_rows": train_manifest["rows"],
            "training_removed_rows": train_manifest["removed_rows"],
            "validation_rows": validation_manifest["rows"],
            "validation_removed_rows": validation_manifest["removed_rows"],
            "optimizer_steps": max_steps,
        },
    )

    model_dir = OUTPUT_ROOT / "model_min_val"
    sft_path = OUTPUT_ROOT / "configs/sft.toml"
    sft_job_name = "rsci-executable-filtered-strict-op28-sft-val"
    config = sft_config(frontier, args.operation, train_dir, validation_dir, model_dir, max_steps)
    config["slurm"]["job_name"] = sft_job_name
    config["wandb"]["name"] = "frontier-executable-filtered-strict-op28"
    write_toml_once(sft_path, config)
    state.update(
        {
            "status": "sft",
            "train_manifest": str(train_dir / "manifest.json"),
            "validation_manifest": str(validation_dir / "manifest.json"),
            "max_steps": max_steps,
            "sft_config": str(sft_path),
        }
    )
    write_json(state_path, state)

    stable = model_dir / "weights" / f"step_{max_steps}" / "STABLE"
    wait_with_retries(
        state,
        state_path,
        "sft",
        lambda new_attempt: submit_sft(
            state,
            state_path,
            "sft",
            sft_job_name,
            sft_path,
            new_attempt,
        ),
        stable,
        args.poll_seconds,
    )
    selection_path = OUTPUT_ROOT / "checkpoint_selection.json"
    if not selection_path.exists():
        run(
            [
                "uv",
                "run",
                "--no-sync",
                "user/tianhaowu/rsci/frontier_select_checkpoint.py",
                "--sft-output",
                str(model_dir),
                "--validation-manifest",
                str(validation_dir / "manifest.json"),
                "--output",
                str(selection_path),
            ]
        )
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    state.update(
        {
            "checkpoint_selection": str(selection_path),
            "selected_checkpoint": selection["selected_checkpoint"],
            "selected_step": selection["selected_step"],
            "selected_validation_loss": selection["selected_validation_loss"],
            "status": "evaluation",
        }
    )
    write_json(state_path, state)
    append_status(
        OUTPUT_ROOT,
        "SFT complete and minimum-loss checkpoint selected",
        {
            "selected_step": selection["selected_step"],
            "selected_validation_loss": selection["selected_validation_loss"],
            "selected_checkpoint": selection["selected_checkpoint"],
        },
    )

    output_dir = OUTPUT_ROOT / "eval_op28"
    infer_path = OUTPUT_ROOT / "configs/inference_op28.toml"
    eval_path = OUTPUT_ROOT / "configs/eval_op28.toml"
    write_toml_once(infer_path, inference_config(frontier, selection["selected_checkpoint"], output_dir / "server"))
    write_toml_once(
        eval_path,
        evaluation_config(frontier, args.operation, selection["selected_checkpoint"], infer_path, output_dir),
    )
    metrics_path = output_dir / "metrics.json"
    wait_with_retries(
        state,
        state_path,
        "eval_op28",
        lambda new_attempt: submit_eval(
            state,
            state_path,
            "eval_op28",
            "rsci-executable-filtered-strict-op28-eval",
            eval_path,
            OUTPUT_ROOT / "slurm-eval-op28-%j.log",
            str(frontier.get("eval_time", "06:00:00")),
            new_attempt,
        ),
        metrics_path,
        args.poll_seconds,
    )
    comparison_path = write_comparison(metrics_path)
    state.update(
        {
            "status": "complete",
            "eval_op28_metrics": str(metrics_path),
            "comparison": str(comparison_path),
            "completed_at": now(),
        }
    )
    write_json(state_path, state)
    append_status(
        OUTPUT_ROOT,
        "ablation complete",
        {
            "selected_step": state["selected_step"],
            "selected_validation_loss": state["selected_validation_loss"],
            "metrics": str(metrics_path),
            "comparison": str(comparison_path),
        },
    )


if __name__ == "__main__":
    main()
