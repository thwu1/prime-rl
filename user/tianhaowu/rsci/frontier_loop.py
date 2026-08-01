#!/usr/bin/env python
"""Run one resumable iterative frontier-SFT track through SLURM."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import re
import subprocess
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomli_w
from prepare_sft_data import CHAT_TEMPLATE

JOB_ID_RE = re.compile(r"Submitted batch job (\d+)")
ACTIVE_STATES = {
    "CONFIGURING",
    "COMPLETING",
    "PENDING",
    "REQUEUED",
    "RESIZING",
    "RUNNING",
    "SUSPENDED",
}
SUCCESS_STATE = "COMPLETED"
RETRYABLE_STATES = {"BOOT_FAIL", "COMPLETED", "FAILED", "NODE_FAIL", "PREEMPTED", "TIMEOUT"}


class SlurmJobError(RuntimeError):
    def __init__(self, job_id: int, state: str, artifact: Path) -> None:
        super().__init__(f"SLURM job {job_id} ended in {state} before producing {artifact}")
        self.state = state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_toml_once(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".partial").open("wb") as handle:
        tomli_w.dump(payload, handle)
    partial = path.with_suffix(path.suffix + ".partial")
    if path.exists() and path.read_bytes() != partial.read_bytes():
        partial.unlink()
        raise ValueError(f"Refusing to change an existing resolved config: {path}")
    partial.replace(path)


def write_versioned_toml(config_dir: Path, stem: str, payload: dict[str, Any]) -> Path:
    serialized = tomli_w.dumps(payload).encode()
    version = 1
    while True:
        suffix = "" if version == 1 else f"_retry{version}"
        path = config_dir / f"{stem}{suffix}.toml"
        if path.exists():
            if path.read_bytes() == serialized:
                return path
            version += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".partial")
        partial.write_bytes(serialized)
        partial.replace(path)
        return path


def append_status(root: Path, heading: str, fields: dict[str, Any]) -> None:
    path = root / "STATUS.md"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {now()} — {heading}\n\n")
        for key, value in fields.items():
            handle.write(f"- {key}: `{value}`\n")


def load_frontier_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    frontier = config["frontier"]
    required = {
        "track",
        "filter_mode",
        "gate_metric",
        "experiment_root",
        "base_model",
        "tokenizer",
        "validation_data_dir",
        "start_operation",
        "max_operation",
        "stop_pass1",
        "examples_per_eval_operation",
        "target_accepted",
        "max_prompts",
        "prompt_batch_size",
        "prompt_seed",
        "samples_per_prompt",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "seq_len",
        "world_size",
        "batch_size",
        "micro_batch_size",
        "learning_rate",
        "weight_decay",
        "warmup_ratio",
        "min_learning_rate",
    }
    missing = sorted(required - frontier.keys())
    if missing:
        raise ValueError(f"Missing frontier config fields: {missing}")
    if frontier["filter_mode"] not in {"answer", "strict"}:
        raise ValueError("frontier.filter_mode must be answer or strict")
    if frontier["gate_metric"] not in {"answer_only", "strict_graph"}:
        raise ValueError("frontier.gate_metric must be answer_only or strict_graph")
    expected_gate = "answer_only" if frontier["filter_mode"] == "answer" else "strict_graph"
    if frontier["gate_metric"] != expected_gate:
        raise ValueError(f"filter_mode={frontier['filter_mode']} requires gate_metric={expected_gate}")
    if int(frontier["samples_per_prompt"]) != 128:
        raise ValueError("The frontier protocol requires samples_per_prompt=128")
    if int(frontier["start_operation"]) > int(frontier["max_operation"]):
        raise ValueError("start_operation must be <= max_operation")
    return frontier


def inference_config(frontier: dict[str, Any], model: str, output_dir: Path) -> dict[str, Any]:
    return {
        "output_dir": str(output_dir),
        "gpu_memory_utilization": float(frontier.get("gpu_memory_utilization", 0.8)),
        "enable_prefix_caching": True,
        "enable_fp32_lm_head": True,
        "api_server_count": int(frontier["world_size"]),
        "data_parallel_size_local": int(frontier["world_size"]),
        "seed": 0,
        "server": {"host": "0.0.0.0", "port": 8000, "liveness_timeout_seconds": 30.0},
        "model": {
            "name": model,
            "dtype": "auto",
            "max_model_len": int(frontier["seq_len"]),
            "enforce_eager": False,
            "trust_remote_code": False,
            "tool_call_parser": "None",
            "reasoning_parser": "None",
        },
        "parallel": {"tp": 1, "dp": int(frontier["world_size"])},
        "deployment": {"type": "single_node", "gpus_per_node": int(frontier["world_size"])},
        "vllm_extra": {"max_num_seqs": int(frontier.get("max_num_seqs", 256))},
        "log": {
            "level": "info",
            "vf_level": "info",
            "json_logging": False,
            "log_data": False,
            "interval": 10.0,
        },
    }


def evaluation_config(
    frontier: dict[str, Any],
    operation: int,
    model: str,
    infer_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    eval_config = {
        "data_dir": str(frontier["validation_data_dir"]),
        "operations": [operation],
        "examples_per_operation": int(frontier["examples_per_eval_operation"]),
        "output_dir": str(output_dir),
        "model": model,
        "api_base_url": "http://127.0.0.1:8000/v1",
        "samples_per_prompt": int(frontier["samples_per_prompt"]),
        "pass_at": [1, 2, 4, 8, 16, 32, 64, 128],
        "max_tokens": int(frontier["max_tokens"]),
        "temperature": float(frontier["temperature"]),
        "top_p": float(frontier["top_p"]),
        "top_k": int(frontier["top_k"]),
        "stop": ["</answer>"],
        "skip_special_tokens": False,
        "request_timeout_seconds": float(frontier.get("request_timeout_seconds", 3600.0)),
        "max_concurrent_prompts": int(frontier.get("max_concurrent_prompts", 16)),
        "max_retries": int(frontier.get("max_retries", 2)),
        "overwrite": False,
    }
    if "prompt_limit_per_operation" in frontier:
        eval_config["prompt_limit_per_operation"] = int(frontier["prompt_limit_per_operation"])
    return {
        "infer_config": str(infer_path),
        "evaluator": "user/tianhaowu/rsci/figure3_eval.py",
        "eval": eval_config,
    }


def collection_config(
    frontier: dict[str, Any],
    operation: int,
    model: str,
    infer_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    eval_config = {
        "operation": operation,
        "filter_mode": str(frontier["filter_mode"]),
        "target_accepted": int(frontier["target_accepted"]),
        "max_prompts": int(frontier["max_prompts"]),
        "prompt_batch_size": int(frontier["prompt_batch_size"]),
        "prompt_seed": int(frontier["prompt_seed"]),
        "number_range": int(frontier.get("number_range", 5)),
        "depth": int(frontier.get("depth", 2)),
        "id_max_op": int(frontier.get("id_max_op", 10)),
        "output_dir": str(output_dir),
        "model": model,
        "tokenizer": str(frontier["tokenizer"]),
        "api_base_url": "http://127.0.0.1:8000/v1",
        "samples_per_prompt": int(frontier["samples_per_prompt"]),
        "max_tokens": int(frontier["max_tokens"]),
        "temperature": float(frontier["temperature"]),
        "top_p": float(frontier["top_p"]),
        "top_k": int(frontier["top_k"]),
        "stop": ["</answer>"],
        "skip_special_tokens": False,
        "request_timeout_seconds": float(frontier.get("request_timeout_seconds", 3600.0)),
        "max_concurrent_prompts": int(frontier.get("max_concurrent_prompts", 16)),
        "max_retries": int(frontier.get("max_retries", 2)),
        "seq_len": int(frontier["seq_len"]),
    }
    if "generator_op_max" in frontier:
        eval_config["generator_op_max"] = int(frontier["generator_op_max"])
    return {
        "infer_config": str(infer_path),
        "evaluator": "user/tianhaowu/rsci/frontier_collect.py",
        "eval": eval_config,
    }


def sft_config(
    frontier: dict[str, Any],
    operation: int,
    dataset_dir: Path,
    model_dir: Path,
    max_steps: int,
) -> dict[str, Any]:
    warmup_steps = int(max_steps * float(frontier["warmup_ratio"]))
    return {
        "output_dir": str(model_dir),
        "max_steps": max_steps,
        "loss_impl": "torch",
        "dist_timeout_seconds": 1800,
        "model": {
            "name": str(frontier["base_model"]),
            "seq_len": int(frontier["seq_len"]),
            "impl": "hf",
            "attn": "flash_attention_2",
            "ep": 1,
            "cp": 1,
        },
        "tokenizer": {"name": str(frontier["tokenizer"]), "chat_template": CHAT_TEMPLATE},
        "data": {
            "type": "sft",
            "name": str(dataset_dir),
            "seq_len": int(frontier["seq_len"]),
            "batch_size": int(frontier["batch_size"]),
            "micro_batch_size": int(frontier["micro_batch_size"]),
            "pack_function": "cat",
            "shuffle": True,
            "seed": 0,
            "loss_mask": {"system": False, "user": False, "assistant": True, "tool": False},
        },
        "optim": {
            "type": "adamw",
            "lr": float(frontier["learning_rate"]),
            "weight_decay": float(frontier["weight_decay"]),
            "max_norm": 1.0,
            "betas1": 0.9,
            "betas2": 0.999,
        },
        "scheduler": {
            "type": "cosine",
            "warmup_steps": warmup_steps,
            "min_lr": float(frontier["min_learning_rate"]),
        },
        "ckpt": {
            "interval": max_steps,
            "weights_only": True,
            "keep_last": 1,
            "weights": {"save_sharded": True, "save_format": "safetensors"},
        },
        "deployment": {
            "type": "single_node",
            "num_gpus": int(frontier["world_size"]),
            "gpus_per_node": int(frontier["world_size"]),
        },
        "slurm": {
            "job_name": f"rsci-{frontier['track']}-op{operation}-sft",
            "account": str(frontier.get("slurm_account", "ram")),
            "partition": str(frontier.get("slurm_partition", "h100")),
            "time": str(frontier.get("sft_time", "04:00:00")),
            "project_dir": "/storage/home/tianhaowu/prime-rl",
            "template_path": (
                "/storage/home/tianhaowu/prime-rl/user/tianhaowu/rsci/templates/single_node_sft_offline.sbatch.j2"
            ),
        },
        "wandb": {
            "project": "rsci",
            "name": f"frontier-{frontier['track']}-op{operation}",
            "offline": True,
        },
        "log": {"level": "info", "interval": 10.0, "ranks_filter": [0]},
    }


def run(command: list[str]) -> str:
    result = subprocess.run(command, cwd="/storage/home/tianhaowu/prime-rl", capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )
    return f"{result.stdout}\n{result.stderr}".strip()


def find_active_job(name: str) -> int | None:
    output = run(["squeue", "--noheader", "--name", name, "--format=%A"])
    ids = {int(line.strip()) for line in output.splitlines() if line.strip()}
    if len(ids) > 1:
        raise RuntimeError(f"Multiple active jobs named {name}: {sorted(ids)}")
    return next(iter(ids), None)


def submit_eval(
    state: dict[str, Any],
    state_path: Path,
    key: str,
    name: str,
    config_path: Path,
    log_path: Path,
    time_limit: str,
    new_attempt: bool = False,
) -> int:
    if key in state["jobs"] and not new_attempt:
        return int(state["jobs"][key]["job_id"])
    active = find_active_job(name)
    if active is None:
        output = run(
            [
                "sbatch",
                f"--job-name={name}",
                f"--time={time_limit}",
                f"--output={log_path}",
                "user/tianhaowu/rsci/scripts/run_eval.sbatch",
                str(config_path),
            ]
        )
        match = JOB_ID_RE.search(output)
        if match is None:
            raise RuntimeError(f"Could not parse SLURM job id from: {output}")
        active = int(match.group(1))
    attempt = {"job_id": active, "job_name": name, "submitted_at": now()}
    if key not in state["jobs"]:
        state["jobs"][key] = {**attempt, "attempts": [attempt]}
    else:
        entry = state["jobs"][key]
        if "attempts" not in entry:
            entry["attempts"] = [{field: entry[field] for field in ("job_id", "job_name", "submitted_at")}]
        entry.update(attempt)
        entry["attempts"].append(attempt)
    write_json(state_path, state)
    return active


def submit_sft(
    state: dict[str, Any],
    state_path: Path,
    key: str,
    name: str,
    config_path: Path,
    new_attempt: bool = False,
) -> int:
    if key in state["jobs"] and not new_attempt:
        return int(state["jobs"][key]["job_id"])
    active = find_active_job(name)
    if active is None:
        output = run(["bash", "user/tianhaowu/rsci/scripts/run_sft.sh", str(config_path)])
        match = JOB_ID_RE.search(output)
        if match is None:
            raise RuntimeError(f"Could not parse SLURM job id from: {output}")
        active = int(match.group(1))
    attempt = {
        "job_id": active,
        "job_name": name,
        "submitted_at": now(),
        "config": str(config_path),
    }
    if key not in state["jobs"]:
        state["jobs"][key] = {**attempt, "attempts": [attempt]}
    else:
        entry = state["jobs"][key]
        if "attempts" not in entry:
            entry["attempts"] = [{field: entry[field] for field in ("job_id", "job_name", "submitted_at")}]
        entry.update(attempt)
        entry["attempts"].append(attempt)
    write_json(state_path, state)
    return active


def slurm_state(job_id: int) -> str:
    queued = run(["squeue", "--noheader", "--jobs", str(job_id), "--format=%T"])
    queue_states = [line.strip().upper() for line in queued.splitlines() if line.strip()]
    if queue_states:
        return queue_states[0]
    accounting = run(["sacct", "--noheader", "-X", "--jobs", str(job_id), "--format=State"])
    states = [line.strip().split()[0].split("+")[0].upper() for line in accounting.splitlines() if line.strip()]
    return states[0] if states else "UNKNOWN"


def wait_for_job(job_id: int, artifact: Path, poll_seconds: int) -> None:
    while True:
        state = slurm_state(job_id)
        print(f"{now()} job={job_id} state={state} artifact={artifact.exists()}", flush=True)
        if artifact.exists() and state not in ACTIVE_STATES:
            return
        if state == SUCCESS_STATE:
            raise SlurmJobError(job_id, state, artifact)
        if state not in ACTIVE_STATES and state != "UNKNOWN":
            raise SlurmJobError(job_id, state, artifact)
        time.sleep(poll_seconds)


def eval_attempt_count(state: dict[str, Any], key: str) -> int:
    entry = state["jobs"][key]
    return len(entry.get("attempts", [entry]))


def initialize_state(frontier: dict[str, Any], config_path: Path, root: Path) -> dict[str, Any]:
    state_path = root / "state.json"
    config_sha256 = file_sha256(config_path)
    write_toml_once(root / "frontier.toml", {"frontier": frontier})
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["source_config"] != str(config_path.resolve()):
            raise ValueError("Existing state was created from another frontier config")
        recorded_hash = state.get("source_config_sha256")
        if recorded_hash is not None and recorded_hash != config_sha256:
            raise ValueError("Frontier config changed after the track was initialized")
        if recorded_hash is None:
            state["source_config_sha256"] = config_sha256
            write_json(state_path, state)
        return state
    state = {
        "track": frontier["track"],
        "filter_mode": frontier["filter_mode"],
        "gate_metric": frontier["gate_metric"],
        "source_config": str(config_path.resolve()),
        "source_config_sha256": config_sha256,
        "status": "running",
        "current_operation": int(frontier["start_operation"]),
        "jobs": {},
        "iterations": {},
        "created_at": now(),
        "implementation_sha256": {
            name: file_sha256(Path(__file__).with_name(name))
            for name in (
                "figure3_eval.py",
                "frontier_build_dataset.py",
                "frontier_collect.py",
                "frontier_loop.py",
                "generate.py",
                "solution_graph.py",
            )
        },
    }
    write_json(state_path, state)
    append_status(root, "track initialized", {"track": frontier["track"], "operation": state["current_operation"]})
    return state


def phase_eval(
    frontier: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    iteration_dir: Path,
    operation: int,
    model: str,
    phase: str,
    poll_seconds: int,
) -> Path:
    config_dir = iteration_dir / "configs"
    output_dir = iteration_dir / f"{phase}_eval"
    infer_path = config_dir / f"inference_{phase}.toml"
    eval_path = config_dir / f"eval_{phase}.toml"
    write_toml_once(infer_path, inference_config(frontier, model, output_dir / "server"))
    write_toml_once(eval_path, evaluation_config(frontier, operation, model, infer_path, output_dir))
    metrics_path = output_dir / "metrics.json"
    if (
        phase == "pre"
        and operation == int(frontier["start_operation"])
        and "initial_eval_metrics" in frontier
        and not metrics_path.exists()
    ):
        source_path = Path(frontier["initial_eval_metrics"])
        source = json.loads(source_path.read_text(encoding="utf-8"))
        if source["model"] != model:
            raise ValueError("Initial evaluation source uses a different model")
        if operation not in source["operations"]:
            raise ValueError(f"Initial evaluation source does not contain op{operation}")
        if source["num_prompts"] % len(source["operations"]):
            raise ValueError("Initial evaluation source has unequal or unknown per-operation counts")
        source_prompts_per_operation = source["num_prompts"] // len(source["operations"])
        if source_prompts_per_operation != int(frontier["examples_per_eval_operation"]):
            raise ValueError("Initial evaluation source has a different examples_per_eval_operation")
        if "prompt_limit_per_operation" in frontier:
            raise ValueError("Initial evaluation reuse cannot be combined with a prompt limit")
        expected_sampling = evaluation_config(frontier, operation, model, infer_path, output_dir)["eval"]
        if source["samples_per_prompt"] != expected_sampling["samples_per_prompt"]:
            raise ValueError("Initial evaluation source has a different samples_per_prompt")
        for key in ("max_tokens", "temperature", "top_p", "top_k", "stop", "skip_special_tokens"):
            if source["sampling"].get(key) != expected_sampling[key]:
                raise ValueError(f"Initial evaluation source has a different {key}")
        reused = copy.deepcopy(source)
        reused["operations"] = [operation]
        reused["num_prompts"] = int(frontier.get("prompt_limit_per_operation", frontier["examples_per_eval_operation"]))
        reused["num_generations"] = reused["num_prompts"] * int(frontier["samples_per_prompt"])
        reused["dataset_sha256_by_op"] = {str(operation): source["dataset_sha256_by_op"][str(operation)]}
        for metric in ("strict_graph", "answer_only"):
            operation_metric = source[metric]["per_op"][str(operation)]
            reused[metric] = {"total": operation_metric, "per_op": {str(operation): operation_metric}}
        reused["diagnostics"] = {
            "unparsed_predictions": None,
            "reused_source_diagnostics": source["diagnostics"],
        }
        reused["provenance"] = {"reused_from": str(source_path.resolve())}
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(metrics_path, reused)
    if metrics_path.exists():
        return metrics_path
    key = f"op{operation}.{phase}_eval"
    name = f"rsci-{frontier['track']}-o{operation}-{phase}"
    log_path = iteration_dir / f"slurm-{phase}-eval-%j.log"
    new_attempt = False
    while True:
        job_id = submit_eval(
            state,
            state_path,
            key,
            name,
            eval_path,
            log_path,
            str(frontier.get("eval_time", "06:00:00")),
            new_attempt,
        )
        try:
            wait_for_job(job_id, metrics_path, poll_seconds)
            return metrics_path
        except SlurmJobError as error:
            attempts = eval_attempt_count(state, key)
            if error.state not in RETRYABLE_STATES or attempts >= int(frontier.get("max_eval_attempts", 3)):
                raise
            append_status(
                Path(frontier["experiment_root"]),
                f"op{operation} {phase} evaluation retry",
                {"failed_job": job_id, "state": error.state, "next_attempt": attempts + 1},
            )
            new_attempt = True


def phase_collection(
    frontier: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    iteration_dir: Path,
    operation: int,
    model: str,
    poll_seconds: int,
) -> Path:
    config_dir = iteration_dir / "configs"
    output_dir = iteration_dir / "collection"
    infer_path = config_dir / "inference_collection.toml"
    collect_path = config_dir / "collection.toml"
    write_toml_once(infer_path, inference_config(frontier, model, output_dir / "server"))
    write_toml_once(collect_path, collection_config(frontier, operation, model, infer_path, output_dir))
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        return manifest_path
    key = f"op{operation}.collection"
    name = f"rsci-{frontier['track']}-o{operation}-collect"
    log_path = iteration_dir / "slurm-collection-%j.log"
    new_attempt = False
    while True:
        job_id = submit_eval(
            state,
            state_path,
            key,
            name,
            collect_path,
            log_path,
            str(frontier.get("collection_time", "12:00:00")),
            new_attempt,
        )
        try:
            wait_for_job(job_id, manifest_path, poll_seconds)
            return manifest_path
        except SlurmJobError as error:
            attempts = eval_attempt_count(state, key)
            if error.state not in RETRYABLE_STATES or attempts >= int(frontier.get("max_collection_attempts", 20)):
                raise
            append_status(
                Path(frontier["experiment_root"]),
                f"op{operation} collection retry",
                {"failed_job": job_id, "state": error.state, "next_attempt": attempts + 1},
            )
            new_attempt = True


def build_dataset(frontier: dict[str, Any], root: Path, operation: int, output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        run(
            [
                "uv",
                "run",
                "--no-sync",
                "user/tianhaowu/rsci/frontier_build_dataset.py",
                "--track-root",
                str(root),
                "--output-dir",
                str(output_dir),
                "--start-operation",
                str(frontier["start_operation"]),
                "--through-operation",
                str(operation),
                "--examples-per-operation",
                str(frontier["target_accepted"]),
                "--seq-len",
                str(frontier["seq_len"]),
                "--world-size",
                str(frontier["world_size"]),
                "--batch-size",
                str(frontier["batch_size"]),
                "--micro-batch-size",
                str(frontier["micro_batch_size"]),
            ]
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def execute(config_path: Path, poll_seconds: int) -> None:
    frontier = load_frontier_config(config_path)
    root = Path(frontier["experiment_root"])
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "state.json"
    state = initialize_state(frontier, config_path, root)
    if state["status"] != "running":
        print(json.dumps(state, indent=2, sort_keys=True))
        return

    while int(state["current_operation"]) <= int(frontier["max_operation"]):
        operation = int(state["current_operation"])
        iteration_dir = root / "iterations" / f"op{operation}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        iteration = state["iterations"].setdefault(str(operation), {})
        if operation == int(frontier["start_operation"]):
            teacher_model = str(frontier["base_model"])
        else:
            teacher_model = str(state["iterations"][str(operation - 1)]["trained_model"])
        iteration["teacher_model"] = teacher_model
        write_json(state_path, state)

        pre_metrics_path = phase_eval(
            frontier, state, state_path, iteration_dir, operation, teacher_model, "pre", poll_seconds
        )
        pre_metrics = json.loads(pre_metrics_path.read_text(encoding="utf-8"))
        pass1 = float(pre_metrics[str(frontier["gate_metric"])]["total"]["unbiased"]["pass@1"])
        record_pre_status = not iteration.get("pre_status_recorded", False)
        iteration["pre_eval_metrics"] = str(pre_metrics_path)
        iteration["gate_pass1"] = pass1
        iteration["pre_status_recorded"] = True
        write_json(state_path, state)
        if record_pre_status:
            append_status(
                root,
                f"op{operation} pre-evaluation complete",
                {"teacher": teacher_model, "gate_metric": frontier["gate_metric"], "pass@1": pass1},
            )
        if pass1 <= float(frontier["stop_pass1"]):
            state["status"] = "stopped_at_frontier"
            state["stop_operation"] = operation
            state["stop_pass1"] = pass1
            state["completed_at"] = now()
            write_json(state_path, state)
            append_status(root, "track stopped", {"operation": operation, "pass@1": pass1})
            return

        collection_manifest_path = phase_collection(
            frontier, state, state_path, iteration_dir, operation, teacher_model, poll_seconds
        )
        collection_manifest = json.loads(collection_manifest_path.read_text(encoding="utf-8"))
        if int(collection_manifest["accepted"]) != int(frontier["target_accepted"]):
            raise ValueError(f"Collection did not produce exactly {frontier['target_accepted']} traces")
        record_collection_status = not iteration.get("collection_status_recorded", False)
        iteration["collection_manifest"] = str(collection_manifest_path)
        iteration["collection_status_recorded"] = True
        write_json(state_path, state)
        if record_collection_status:
            append_status(
                root,
                f"op{operation} collection complete",
                {
                    "accepted": collection_manifest["accepted"],
                    "prompts": collection_manifest["prompts_generated"],
                    "generations": collection_manifest["generations"],
                    "accepted_answer": collection_manifest["accepted_answer"],
                    "accepted_strict": collection_manifest["accepted_strict"],
                },
            )

        dataset_dir = iteration_dir / "cumulative_dataset"
        dataset_manifest = build_dataset(frontier, root, operation, dataset_dir)
        max_steps = int(dataset_manifest["training_plan"]["optimizer_steps_for_one_epoch"])
        record_dataset_status = not iteration.get("dataset_status_recorded", False)
        iteration["dataset_manifest"] = str(dataset_dir / "manifest.json")
        iteration["max_steps"] = max_steps
        iteration["dataset_status_recorded"] = True
        write_json(state_path, state)
        if record_dataset_status:
            append_status(
                root,
                f"op{operation} cumulative dataset ready",
                {"rows": dataset_manifest["rows"], "operations": dataset_manifest["operations"], "steps": max_steps},
            )

        model_dir = iteration_dir / "model"
        sft_path = write_versioned_toml(
            iteration_dir / "configs",
            "sft",
            sft_config(frontier, operation, dataset_dir, model_dir, max_steps),
        )
        stable_path = model_dir / "weights" / f"step_{max_steps}" / "STABLE"
        if not stable_path.exists():
            key = f"op{operation}.sft"
            name = f"rsci-{frontier['track']}-op{operation}-sft"
            new_attempt = False
            while True:
                job_id = submit_sft(state, state_path, key, name, sft_path, new_attempt)
                try:
                    wait_for_job(job_id, stable_path, poll_seconds)
                    break
                except SlurmJobError as error:
                    attempts = eval_attempt_count(state, key)
                    if error.state not in RETRYABLE_STATES or attempts >= int(frontier.get("max_sft_attempts", 3)):
                        raise
                    append_status(
                        root,
                        f"op{operation} SFT retry",
                        {"failed_job": job_id, "state": error.state, "next_attempt": attempts + 1},
                    )
                    new_attempt = True
        trained_model = str(stable_path.parent)
        record_sft_status = not iteration.get("sft_status_recorded", False)
        iteration["trained_model"] = trained_model
        iteration["sft_status_recorded"] = True
        write_json(state_path, state)
        if record_sft_status:
            append_status(
                root,
                f"op{operation} SFT complete",
                {"model": trained_model, "optimizer_steps": max_steps},
            )

        post_metrics_path = phase_eval(
            frontier, state, state_path, iteration_dir, operation, trained_model, "post", poll_seconds
        )
        iteration["post_eval_metrics"] = str(post_metrics_path)
        post_metrics = json.loads(post_metrics_path.read_text(encoding="utf-8"))
        append_status(
            root,
            f"op{operation} iteration complete",
            {
                "accepted": collection_manifest["accepted"],
                "cumulative_rows": dataset_manifest["rows"],
                "optimizer_steps": max_steps,
                "model": trained_model,
                "post_answer_pass@1": post_metrics["answer_only"]["total"]["unbiased"]["pass@1"],
                "post_strict_pass@1": post_metrics["strict_graph"]["total"]["unbiased"]["pass@1"],
            },
        )
        state["current_operation"] = operation + 1
        write_json(state_path, state)

    state["status"] = "max_operation_exhausted"
    state["completed_at"] = now()
    write_json(state_path, state)
    append_status(root, "maximum configured operation exhausted", {"max_operation": frontier["max_operation"]})


def main() -> None:
    args = parse_args()
    if args.poll_seconds < 1:
        raise ValueError("poll-seconds must be positive")
    config_path = args.config.resolve()
    frontier = load_frontier_config(config_path)
    if args.validate_only:
        from figure3_eval import load_rows

        from prime_rl.configs.inference import InferenceConfig
        from prime_rl.configs.sft import SFTConfig

        operation = int(frontier["start_operation"])
        root = Path(frontier["experiment_root"])
        InferenceConfig.model_validate(
            inference_config(frontier, str(frontier["base_model"]), root / "validation" / "server")
        )
        eval_payload = evaluation_config(
            frontier,
            operation,
            str(frontier["base_model"]),
            root / "validation" / "inference.toml",
            root / "validation" / "eval",
        )
        rows, _ = load_rows(eval_payload["eval"])
        SFTConfig.model_validate(
            sft_config(frontier, operation, root / "validation" / "data", root / "validation" / "model", 62)
        )
        print(
            json.dumps(
                {"config": str(config_path), "track": frontier["track"], "validation_rows": len(rows), "valid": True}
            )
        )
        return
    root = Path(frontier["experiment_root"])
    root.mkdir(parents=True, exist_ok=True)
    lock_handle = (root / "watcher.lock").open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"Another watcher already holds {root / 'watcher.lock'}")
        return
    try:
        execute(config_path, args.poll_seconds)
    except Exception as error:
        failure_path = root / "FAILURE.json"
        write_json(failure_path, {"failed_at": now(), "error_type": type(error).__name__, "error": str(error)})
        append_status(root, "watcher failed", {"error_type": type(error).__name__, "error": str(error)})
        raise


if __name__ == "__main__":
    main()
