#!/usr/bin/env python
"""Run the base OP11–14 answer-filtered harmonic-SFT sweep and OP15–18 evaluation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from frontier_loop import (
    RETRYABLE_STATES,
    SlurmJobError,
    append_status,
    file_sha256,
    inference_config,
    now,
    submit_eval,
    wait_for_job,
    write_json,
    write_toml_once,
)

ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/harmonic-sft/base-op11-14-answer")
BASE_CONFIG = Path("user/tianhaowu/rsci/configs/harmonic/base_op11_14_answer.toml")
BASE_MODEL = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
    "models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/"
    "4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base"
)
EVAL_DATA = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
    "datasets--Interplay-LM-Reasoning--composition/snapshots/"
    "a09d5c14c02bfa339143fb00a93274d1a84aa31d/val"
)
VARIANTS = {
    "baseline": None,
    "k4": Path("user/tianhaowu/rsci/configs/harmonic/k4.toml"),
    "k8": Path("user/tianhaowu/rsci/configs/harmonic/k8.toml"),
    "k16": Path("user/tianhaowu/rsci/configs/harmonic/k16.toml"),
    "k32": Path("user/tianhaowu/rsci/configs/harmonic/k32.toml"),
    "k64": Path("user/tianhaowu/rsci/configs/harmonic/k64.toml"),
}
JOB_ID_RE = re.compile(r"Submitted batch job (\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=int, default=60)
    return parser.parse_args()


def run(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd="/storage/home/tianhaowu/prime-rl",
        check=True,
        capture_output=True,
        text=True,
    )
    return f"{result.stdout}\n{result.stderr}".strip()


def implementation_sha256() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    paths = {
        "harmonic_build_dataset.py": Path(__file__).with_name("harmonic_build_dataset.py"),
        "harmonic_sft_ablation.py": Path(__file__),
        "frontier_select_checkpoint.py": Path(__file__).with_name("frontier_select_checkpoint.py"),
        "figure3_eval.py": Path(__file__).with_name("figure3_eval.py"),
        "trainer_sft_data.py": repo_root / "src/prime_rl/trainer/sft/data.py",
        "trainer_sft_loss.py": repo_root / "src/prime_rl/trainer/sft/loss.py",
        "trainer_sft_train.py": repo_root / "src/prime_rl/trainer/sft/train.py",
        "sft_config.py": repo_root / "packages/prime-rl-configs/src/prime_rl/configs/sft.py",
    }
    return {name: file_sha256(path) for name, path in paths.items()}


def load_or_initialize_state() -> tuple[dict[str, Any], Path]:
    state_path = ROOT / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["implementation_sha256"] != implementation_sha256():
            raise ValueError("Harmonic ablation implementation changed after launch")
        return state, state_path
    state = {
        "experiment": "base-op11-14-answer-harmonic-sft",
        "status": "sft",
        "created_at": now(),
        "base_model": str(BASE_MODEL),
        "training_operations": [11, 12, 13, 14],
        "evaluation_operations": [15, 16, 17, 18],
        "samples_per_prompt": 128,
        "max_steps": 248,
        "validation_interval": 8,
        "jobs": {},
        "variants": {},
        "implementation_sha256": implementation_sha256(),
    }
    write_json(state_path, state)
    append_status(ROOT, "harmonic SFT ablation initialized", state)
    return state, state_path


def prepare_sft(variant: str, overlay: Path | None) -> Path:
    output_dir = ROOT / "runs" / variant
    script = output_dir / "sft.sbatch"
    if script.exists():
        return script
    command = ["uv", "run", "--no-sync", "sft", "@", str(BASE_CONFIG)]
    if overlay is not None:
        command.extend(["@", str(overlay)])
    command.append("--dry-run")
    run(command)
    if not script.exists():
        raise FileNotFoundError(f"SFT dry-run did not create {script}")
    return script


def submit_sft_variant(
    state: dict[str, Any],
    state_path: Path,
    variant: str,
    overlay: Path | None,
) -> int:
    key = f"sft.{variant}"
    if key in state["jobs"]:
        return int(state["jobs"][key]["job_id"])
    script = prepare_sft(variant, overlay)
    output = run(["sbatch", str(script)])
    match = JOB_ID_RE.search(output)
    if match is None:
        raise RuntimeError(f"Could not parse SFT job id from: {output}")
    job_id = int(match.group(1))
    state["jobs"][key] = {
        "job_id": job_id,
        "job_name": f"rsci-harmonic-{variant}-op11-14",
        "submitted_at": now(),
        "script": str(script),
    }
    state["variants"][variant] = {
        "overlay": str(overlay) if overlay is not None else None,
        "sft_output": str(ROOT / "runs" / variant),
    }
    write_json(state_path, state)
    return job_id


def select_checkpoint(variant: str) -> dict[str, Any]:
    run_dir = ROOT / "runs" / variant
    selection_path = run_dir / "checkpoint_selection.json"
    if not selection_path.exists():
        run(
            [
                "uv",
                "run",
                "--no-sync",
                "user/tianhaowu/rsci/frontier_select_checkpoint.py",
                "--sft-output",
                str(run_dir),
                "--validation-manifest",
                str(ROOT / "data/validation/manifest.json"),
                "--output",
                str(selection_path),
            ]
        )
    return json.loads(selection_path.read_text(encoding="utf-8"))


def write_eval_configs(name: str, model: str) -> Path:
    output_dir = ROOT / "eval" / name
    config_dir = ROOT / "configs" / "eval"
    infer_path = config_dir / f"inference_{name}.toml"
    eval_path = config_dir / f"eval_{name}.toml"
    frontier = {
        "world_size": 8,
        "seq_len": 2048,
        "gpu_memory_utilization": 0.8,
        "max_num_seqs": 256,
    }
    write_toml_once(infer_path, inference_config(frontier, model, output_dir / "server"))
    write_toml_once(
        eval_path,
        {
            "infer_config": str(infer_path),
            "evaluator": "user/tianhaowu/rsci/figure3_eval.py",
            "eval": {
                "data_dir": str(EVAL_DATA),
                "operations": [15, 16, 17, 18],
                "examples_per_operation": 200,
                "output_dir": str(output_dir),
                "model": model,
                "api_base_url": "http://127.0.0.1:8000/v1",
                "samples_per_prompt": 128,
                "pass_at": [1, 2, 4, 8, 16, 32, 64, 128],
                "max_tokens": 2048,
                "temperature": 0.7,
                "top_p": 1.0,
                "top_k": -1,
                "stop": ["</answer>"],
                "skip_special_tokens": False,
                "request_timeout_seconds": 3600.0,
                "max_concurrent_prompts": 16,
                "max_retries": 2,
                "overwrite": False,
            },
        },
    )
    return eval_path


def wait_eval_with_retries(
    state: dict[str, Any],
    state_path: Path,
    name: str,
    eval_path: Path,
    poll_seconds: int,
) -> Path:
    key = f"eval.{name}"
    metrics = ROOT / "eval" / name / "metrics.json"
    new_attempt = False
    while True:
        job_id = submit_eval(
            state,
            state_path,
            key,
            f"rsci-harmonic-{name}-op15-18-eval",
            eval_path,
            ROOT / f"slurm-eval-{name}-%j.log",
            "06:00:00",
            new_attempt,
        )
        try:
            wait_for_job(job_id, metrics, poll_seconds)
            return metrics
        except SlurmJobError as error:
            attempts = len(state["jobs"][key].get("attempts", [state["jobs"][key]]))
            if error.state not in RETRYABLE_STATES or attempts >= 3:
                raise
            new_attempt = True


def metric_table(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        metric: {
            "total": metrics[metric]["total"]["unbiased"],
            "per_op": {
                operation: values["unbiased"] for operation, values in metrics[metric]["per_op"].items()
            },
        }
        for metric in ("answer_only", "strict_graph")
    }


def write_comparison(metric_paths: dict[str, Path]) -> Path:
    metrics = {
        name: metric_table(json.loads(path.read_text(encoding="utf-8"))) for name, path in metric_paths.items()
    }
    baseline = metrics["baseline"]
    deltas = {
        name: {
            metric: {
                key: values[metric]["total"][key] - baseline[metric]["total"][key]
                for key in baseline[metric]["total"]
            }
            for metric in ("answer_only", "strict_graph")
        }
        for name, values in metrics.items()
        if name.startswith("k")
    }
    path = ROOT / "comparison.json"
    write_json(
        path,
        {
            "protocol": {
                "training_operations": [11, 12, 13, 14],
                "evaluation_operations": [15, 16, 17, 18],
                "training_filter": "final-answer correct",
                "rollouts_per_problem": 128,
                "problems_per_eval_operation": 200,
                "sft_steps": 248,
                "validation_and_checkpoint_interval": 8,
            },
            "metrics": metrics,
            "harmonic_minus_unweighted_sft": deltas,
        },
    )
    return path


def main() -> None:
    args = parse_args()
    state, state_path = load_or_initialize_state()
    dataset_manifest = ROOT / "data/manifest.json"
    if not dataset_manifest.exists():
        raise FileNotFoundError(f"Missing harmonic dataset: {dataset_manifest}")

    sft_jobs = {
        variant: submit_sft_variant(state, state_path, variant, overlay)
        for variant, overlay in VARIANTS.items()
    }
    for variant, job_id in sft_jobs.items():
        wait_for_job(job_id, ROOT / "runs" / variant / "weights/step_248/STABLE", args.poll_seconds)
        selection = select_checkpoint(variant)
        state["variants"][variant].update(
            {
                "checkpoint_selection": str(ROOT / "runs" / variant / "checkpoint_selection.json"),
                "selected_checkpoint": selection["selected_checkpoint"],
                "selected_step": selection["selected_step"],
                "selected_validation_loss": selection["selected_validation_loss"],
            }
        )
        write_json(state_path, state)
        append_status(
            ROOT,
            f"{variant} SFT complete",
            {
                "job_id": job_id,
                "selected_step": selection["selected_step"],
                "selected_validation_loss": selection["selected_validation_loss"],
            },
        )

    state["status"] = "evaluation"
    write_json(state_path, state)
    models = {"base": str(BASE_MODEL)} | {
        variant: str(values["selected_checkpoint"]) for variant, values in state["variants"].items()
    }
    eval_configs = {name: write_eval_configs(name, model) for name, model in models.items()}
    for name, eval_path in eval_configs.items():
        key = f"eval.{name}"
        if key not in state["jobs"]:
            submit_eval(
                state,
                state_path,
                key,
                f"rsci-harmonic-{name}-op15-18-eval",
                eval_path,
                ROOT / f"slurm-eval-{name}-%j.log",
                "06:00:00",
            )
    metric_paths = {
        name: wait_eval_with_retries(state, state_path, name, eval_path, args.poll_seconds)
        for name, eval_path in eval_configs.items()
    }
    comparison = write_comparison(metric_paths)
    state.update(
        {
            "status": "complete",
            "evaluation_metrics": {name: str(path) for name, path in metric_paths.items()},
            "comparison": str(comparison),
            "completed_at": now(),
        }
    )
    write_json(state_path, state)
    append_status(ROOT, "harmonic SFT ablation complete", {"comparison": str(comparison)})


if __name__ == "__main__":
    main()
