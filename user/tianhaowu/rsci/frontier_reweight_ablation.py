#!/usr/bin/env python
"""Run a fixed-data exponential-replay SFT ablation and evaluate OP25/OP26."""

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
OUTPUT_PARENT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-reweight-ablation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-decay", type=float, required=True, choices=(0.9, 0.95))
    parser.add_argument("--operation", type=int, default=25)
    parser.add_argument("--resample-seed", type=int, default=20260802)
    parser.add_argument("--poll-seconds", type=int, default=60)
    return parser.parse_args()


def decay_tag(replay_decay: float) -> str:
    return f"{replay_decay:.2f}".replace(".", "")


def run(command: list[str]) -> None:
    subprocess.run(command, cwd="/storage/home/tianhaowu/prime-rl", check=True)


def load_or_initialize_state(root: Path, args: argparse.Namespace, track: str) -> dict[str, Any]:
    state_path = root / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        expected = {"track": track, "operation": args.operation, "replay_decay": args.replay_decay}
        for field, value in expected.items():
            if state[field] != value:
                raise ValueError(f"Existing ablation state differs on {field}")
        return state
    state = {
        "track": track,
        "operation": args.operation,
        "replay_decay": args.replay_decay,
        "resample_seed": args.resample_seed,
        "source_root": str(SOURCE_ROOT),
        "status": "building_datasets",
        "jobs": {},
        "created_at": now(),
        "implementation_sha256": {
            "frontier_build_reweighted_dataset.py": file_sha256(
                Path(__file__).with_name("frontier_build_reweighted_dataset.py")
            ),
            "frontier_reweight_ablation.py": file_sha256(Path(__file__)),
            "frontier_select_checkpoint.py": file_sha256(Path(__file__).with_name("frontier_select_checkpoint.py")),
            "src/prime_rl/trainer/sft/train.py": file_sha256(
                Path(__file__).resolve().parents[3] / "src/prime_rl/trainer/sft/train.py"
            ),
        },
    }
    root.mkdir(parents=True, exist_ok=True)
    write_json(state_path, state)
    append_status(root, "ablation initialized", state)
    return state


def build_dataset(
    root: Path,
    args: argparse.Namespace,
    collection_name: str,
    examples_per_operation: int,
    batch_size: int,
    micro_batch_size: int,
) -> Path:
    name = "train" if collection_name == "collection" else "validation"
    output_dir = root / f"reweighted_{name}_dataset"
    manifest = output_dir / "manifest.json"
    if manifest.exists():
        return output_dir
    run(
        [
            "uv",
            "run",
            "--no-sync",
            "user/tianhaowu/rsci/frontier_build_reweighted_dataset.py",
            "--track-root",
            str(SOURCE_ROOT),
            "--output-dir",
            str(output_dir),
            "--start-operation",
            "11",
            "--through-operation",
            str(args.operation),
            "--examples-per-operation",
            str(examples_per_operation),
            "--collection-name",
            collection_name,
            "--replay-decay",
            str(args.replay_decay),
            "--resample-seed",
            str(args.resample_seed),
            "--seq-len",
            "2048",
            "--world-size",
            "8",
            "--batch-size",
            str(batch_size),
            "--micro-batch-size",
            str(micro_batch_size),
        ]
    )
    return output_dir


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
            new_attempt = True


def main() -> None:
    args = parse_args()
    tag = decay_tag(args.replay_decay)
    track = f"strict-exp-decay-{tag}"
    root = OUTPUT_PARENT / f"op{args.operation}-lambda-{args.replay_decay:.2f}"
    state_path = root / "state.json"
    state = load_or_initialize_state(root, args, track)
    frontier = load_frontier_config(SOURCE_CONFIG)
    frontier = {**frontier, "track": track, "experiment_root": str(root)}

    train_dir = build_dataset(root, args, "collection", 50_000, 256, 4)
    validation_dir = build_dataset(root, args, "validation_collection", 5_000, 32, 4)
    source_state = json.loads((SOURCE_ROOT / "state.json").read_text(encoding="utf-8"))
    baseline_steps = int(source_state["iterations"][str(args.operation)]["max_steps"])
    model_dir = root / "model_min_val"
    sft_path = root / "configs" / "sft.toml"
    sft_job_name = f"rsci-{track}-sft"
    config = sft_config(frontier, args.operation, train_dir, validation_dir, model_dir, baseline_steps)
    config["slurm"]["job_name"] = sft_job_name
    config["wandb"]["name"] = f"frontier-{track}-op{args.operation}"
    write_toml_once(sft_path, config)
    state.update(
        {
            "status": "sft",
            "train_manifest": str(train_dir / "manifest.json"),
            "validation_manifest": str(validation_dir / "manifest.json"),
            "baseline_max_steps": baseline_steps,
            "sft_config": str(sft_path),
        }
    )
    write_json(state_path, state)

    stable = model_dir / "weights" / f"step_{baseline_steps}" / "STABLE"
    sft_key = "sft"
    wait_with_retries(
        state,
        state_path,
        sft_key,
        lambda new_attempt: submit_sft(state, state_path, sft_key, sft_job_name, sft_path, new_attempt),
        stable,
        args.poll_seconds,
    )
    selection_path = root / "checkpoint_selection.json"
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
    state["checkpoint_selection"] = str(selection_path)
    state["selected_checkpoint"] = selection["selected_checkpoint"]
    state["selected_step"] = selection["selected_step"]
    state["selected_validation_loss"] = selection["selected_validation_loss"]
    write_json(state_path, state)

    for operation in (args.operation, args.operation + 1):
        output_dir = root / f"eval_op{operation}"
        infer_path = root / "configs" / f"inference_op{operation}.toml"
        eval_path = root / "configs" / f"eval_op{operation}.toml"
        write_toml_once(infer_path, inference_config(frontier, selection["selected_checkpoint"], output_dir / "server"))
        write_toml_once(
            eval_path,
            evaluation_config(frontier, operation, selection["selected_checkpoint"], infer_path, output_dir),
        )
        metrics = output_dir / "metrics.json"
        key = f"eval_op{operation}"
        wait_with_retries(
            state,
            state_path,
            key,
            lambda new_attempt, operation=operation, eval_path=eval_path: submit_eval(
                state,
                state_path,
                key,
                f"rsci-{track}-o{operation}-eval",
                eval_path,
                root / f"slurm-eval-op{operation}-%j.log",
                str(frontier.get("eval_time", "06:00:00")),
                new_attempt,
            ),
            metrics,
            args.poll_seconds,
        )
        state[f"eval_op{operation}_metrics"] = str(metrics)
        write_json(state_path, state)

    state["status"] = "complete"
    state["completed_at"] = now()
    write_json(state_path, state)
    append_status(
        root,
        "ablation complete",
        {
            "selected_step": state["selected_step"],
            "selected_validation_loss": state["selected_validation_loss"],
            "op25_metrics": state[f"eval_op{args.operation}_metrics"],
            "op26_metrics": state[f"eval_op{args.operation + 1}_metrics"],
        },
    )


if __name__ == "__main__":
    main()
