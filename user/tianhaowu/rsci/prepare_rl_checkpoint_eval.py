#!/usr/bin/env python
"""Materialize a frozen-checkpoint OP11-45 strict pass@1 evaluation."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

import tomli_w

REPO_ROOT = Path(__file__).resolve().parents[3]
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
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Local inference-server port (default: 8000).",
    )
    return parser.parse_args()


def write_toml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("wb") as handle:
        tomli_w.dump(payload, handle)
    partial.replace(path)


def resolve_model_path(run_dir: Path, step: int) -> Path:
    if step < 0:
        raise ValueError("step must be non-negative")

    if step == 0:
        trainer_config_path = run_dir / "configs" / "trainer.toml"
        if not trainer_config_path.is_file():
            raise FileNotFoundError(f"Resolved trainer config does not exist: {trainer_config_path}")
        with trainer_config_path.open("rb") as handle:
            trainer_config = tomllib.load(handle)
        model_name = trainer_config.get("model", {}).get("name")
        if not isinstance(model_name, str) or not model_name:
            raise ValueError(f"Resolved trainer config has no model.name: {trainer_config_path}")
        base_model = Path(model_name).expanduser().resolve()
        if not base_model.is_dir():
            raise FileNotFoundError(f"Resolved base model directory does not exist: {base_model}")
        return base_model

    checkpoint = run_dir / "weights" / f"step_{step}"
    if not checkpoint.is_dir():
        raise FileNotFoundError(f"Checkpoint directory does not exist: {checkpoint}")
    if not (checkpoint / "STABLE").is_file():
        raise RuntimeError(f"Checkpoint is not marked stable: {checkpoint}")
    return checkpoint


def materialize_eval_config(
    run_dir: Path,
    step: int,
    output_dir: Path | None = None,
    *,
    port: int = 8000,
) -> Path:
    run_dir = run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be in [1, 65535], got: {port}")
    model_path = resolve_model_path(run_dir, step)

    output_dir = (output_dir or run_dir / "evals" / "op11-45" / f"step_{step}").resolve()
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
            "port": port,
            "liveness_timeout_seconds": 30.0,
        },
        "model": {
            "name": str(model_path),
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
            "model": str(model_path),
            "api_base_url": f"http://127.0.0.1:{port}/v1",
            "samples_per_prompt": 1,
            "pass_at": [1],
            "max_tokens": 2048,
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "request_seed": 20260807,
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
    return eval_path


def main() -> None:
    args = parse_args()
    eval_path = materialize_eval_config(args.run_dir, args.step, args.output_dir, port=args.port)
    print(eval_path)


if __name__ == "__main__":
    main()
