#!/usr/bin/env python
"""Materialize a frozen-checkpoint OP11-45 strict pass@1 evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

import tomli_w

REPO_ROOT = Path("/storage/home/tianhaowu/prime-rl")
DATA_SOURCES = [
    {
        "min_op": 11,
        "max_op": 20,
        "data_dir": (
            "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
            "datasets--Interplay-LM-Reasoning--composition/snapshots/"
            "a09d5c14c02bfa339143fb00a93274d1a84aa31d/val"
        ),
    },
    {
        "min_op": 21,
        "max_op": 30,
        "data_dir": "/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/generated-eval-op21-30-v1",
    },
    {
        "min_op": 31,
        "max_op": 40,
        "data_dir": "/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/generated-eval-op31-40-v1",
    },
    {
        "min_op": 41,
        "max_op": 45,
        "data_dir": "/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k/eval",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("step", type=int)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Defaults to RUN_DIR/evals/op11-45/step_STEP.",
    )
    return parser.parse_args()


def write_toml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("wb") as handle:
        tomli_w.dump(payload, handle)
    partial.replace(path)


def main() -> None:
    args = parse_args()
    if args.step < 0:
        raise ValueError("step must be non-negative")

    run_dir = args.run_dir.expanduser().resolve()
    checkpoint = run_dir / "weights" / f"step_{args.step}"
    if not checkpoint.is_dir():
        raise FileNotFoundError(f"Checkpoint directory does not exist: {checkpoint}")
    if not (checkpoint / "STABLE").is_file():
        raise RuntimeError(f"Checkpoint is not marked stable: {checkpoint}")

    output_dir = (args.output_dir or run_dir / "evals" / "op11-45" / f"step_{args.step}").resolve()
    config_dir = output_dir / "configs"
    inference_path = config_dir / "inference.toml"
    eval_path = config_dir / "eval.toml"

    inference = {
        "output_dir": str(output_dir / "deployment"),
        "gpu_memory_utilization": 0.8,
        "enable_prefix_caching": True,
        "enable_fp32_lm_head": True,
        "api_server_count": 1,
        "data_parallel_size_local": 1,
        "seed": 0,
        "server": {
            "host": "0.0.0.0",
            "port": 8000,
            "liveness_timeout_seconds": 30.0,
        },
        "model": {
            "name": str(checkpoint),
            "dtype": "auto",
            "max_model_len": 2048,
            "enforce_eager": False,
            "trust_remote_code": False,
            "tool_call_parser": "None",
            "reasoning_parser": "None",
        },
        "parallel": {"tp": 1, "dp": 1},
        "deployment": {"type": "single_node", "gpus_per_node": 1},
        "vllm_extra": {"max_num_seqs": 256},
        "log": {
            "level": "info",
            "vf_level": "info",
            "json_logging": False,
            "log_data": False,
            "interval": 10.0,
        },
    }
    evaluation = {
        "infer_config": str(inference_path),
        "evaluator": str(REPO_ROOT / "user/tianhaowu/rsci/figure3_eval.py"),
        "eval": {
            "data_sources": DATA_SOURCES,
            "operations": list(range(11, 46)),
            "examples_per_operation": 200,
            "output_dir": str(output_dir),
            "model": str(checkpoint),
            "api_base_url": "http://127.0.0.1:8000/v1",
            "samples_per_prompt": 1,
            "pass_at": [1],
            "max_tokens": 2048,
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "stop": ["</answer>"],
            "skip_special_tokens": False,
            "request_timeout_seconds": 3600.0,
            "max_concurrent_prompts": 128,
            "max_retries": 2,
            "overwrite": False,
        },
    }
    write_toml(inference_path, inference)
    write_toml(eval_path, evaluation)
    print(eval_path)


if __name__ == "__main__":
    main()
