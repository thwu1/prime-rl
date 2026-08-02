#!/usr/bin/env python
"""Run one resumable iterative frontier-SFT track through SLURM."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
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
        "validation_accepted",
        "validation_prompt_stream_offset",
        "validation_interval_divisor",
        "validation_batch_size",
        "validation_micro_batch_size",
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
    if int(frontier["validation_accepted"]) < 1:
        raise ValueError("validation_accepted must be positive")
    if int(frontier["validation_prompt_stream_offset"]) < int(frontier["max_prompts"]):
        raise ValueError("validation_prompt_stream_offset must exceed the entire training prompt stream")
    if int(frontier["validation_interval_divisor"]) < 1:
        raise ValueError("validation_interval_divisor must be positive")
    if int(frontier["start_operation"]) > int(frontier["max_operation"]):
        raise ValueError("start_operation must be <= max_operation")
    maximum_eval_path = (
        Path(frontier["validation_data_dir"])
        / f"op{int(frontier['max_operation'])}-{int(frontier['examples_per_eval_operation'])}.jsonl"
    )
    if not maximum_eval_path.exists():
        generated_required = {
            "generated_validation_data_dir",
            "generated_eval_seed",
            "generator_op_max",
        }
        generated_missing = sorted(generated_required - frontier.keys())
        if generated_missing:
            raise ValueError(
                "The configured maximum operation is absent from validation_data_dir; "
                f"missing generated-evaluation fields: {generated_missing}"
            )
        if int(frontier["generator_op_max"]) < int(frontier["max_operation"]):
            raise ValueError("generator_op_max must cover max_operation")
    return frontier


def validate_evaluation_file(path: Path, operation: int, expected_rows: int) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != expected_rows:
        raise ValueError(f"Expected {expected_rows} evaluation rows in {path}, found {len(rows)}")
    if any(int(row["op"]) != operation for row in rows):
        raise ValueError(f"Evaluation file contains rows outside op{operation}: {path}")
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Evaluation file contains duplicate ids: {path}")


def evaluation_row_digest(row: dict[str, Any]) -> str:
    material = json.dumps(
        [row["problem"], row["question"], row["solution"]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


def generated_evaluation_sidecar(path: Path) -> Path:
    return path.with_suffix(".manifest.json")


def resolve_evaluation_file(frontier: dict[str, Any], operation: int) -> Path:
    filename = f"op{operation}-{int(frontier['examples_per_eval_operation'])}.jsonl"
    released_path = Path(frontier["validation_data_dir"]) / filename
    if released_path.exists():
        return released_path
    if "generated_validation_data_dir" not in frontier:
        raise FileNotFoundError(f"No evaluation data for op{operation}: {released_path}")
    generated_path = Path(frontier["generated_validation_data_dir"]) / filename
    if not generated_path.exists():
        raise FileNotFoundError(f"Generated evaluation data is not ready for op{operation}: {generated_path}")
    return generated_path


def evaluation_data_record(frontier: dict[str, Any], operation: int) -> dict[str, Any]:
    path = resolve_evaluation_file(frontier, operation)
    expected_rows = int(frontier["examples_per_eval_operation"])
    validate_evaluation_file(path, operation, expected_rows)
    generated_root = frontier.get("generated_validation_data_dir")
    generated = generated_root is not None and path.parent == Path(generated_root)
    record: dict[str, Any] = {
        "kind": "generated_extension" if generated else "released",
        "path": str(path.resolve()),
        "rows": expected_rows,
        "sha256": file_sha256(path),
    }
    if generated:
        sidecar = generated_evaluation_sidecar(path)
        if not sidecar.exists():
            raise FileNotFoundError(f"Generated evaluation manifest is missing: {sidecar}")
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        if manifest["evaluation_sha256"] != record["sha256"]:
            raise ValueError(f"Generated evaluation manifest hash mismatch: {sidecar}")
        record["manifest"] = str(sidecar.resolve())
    return record


def ensure_evaluation_data(frontier: dict[str, Any], operation: int) -> dict[str, Any]:
    filename = f"op{operation}-{int(frontier['examples_per_eval_operation'])}.jsonl"
    released_path = Path(frontier["validation_data_dir"]) / filename
    if released_path.exists():
        return evaluation_data_record(frontier, operation)

    generated_root = Path(frontier["generated_validation_data_dir"])
    generated_root.mkdir(parents=True, exist_ok=True)
    target = generated_root / filename
    lock_path = generated_root / f".op{operation}.lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if not target.exists():
            sources = generated_root / "sources"
            sources.mkdir(parents=True, exist_ok=True)
            source_dir = sources / f"op{operation}"
            if source_dir.exists():
                raise FileExistsError(f"Generated source exists without materialized evaluation file: {source_dir}")
            temporary_dir = Path(tempfile.mkdtemp(prefix=f"op{operation}.partial.", dir=sources))
            run(
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "user/tianhaowu/rsci/generate.py",
                    "--output-dir",
                    str(temporary_dir),
                    "--ops",
                    str(operation),
                    "--train-per-op",
                    "0",
                    "--validation-per-op",
                    str(frontier["examples_per_eval_operation"]),
                    "--test-per-op",
                    "0",
                    "--context-mixture",
                    str(frontier.get("generated_eval_context_mixture", "zoo=1,teacher=1,movie=1")),
                    "--mode-mixture",
                    str(frontier.get("generated_eval_mode_mixture", "forward=1,reverse=1")),
                    "--seed",
                    str(frontier["generated_eval_seed"]),
                    "--depth",
                    str(frontier.get("depth", 2)),
                    "--number-range",
                    str(frontier.get("number_range", 5)),
                    "--id-max-op",
                    str(frontier.get("id_max_op", 10)),
                    "--generator-op-max",
                    str(frontier["generator_op_max"]),
                ]
            )
            source_file = temporary_dir / "validation.jsonl"
            validate_evaluation_file(
                source_file,
                operation,
                int(frontier["examples_per_eval_operation"]),
            )
            temporary_dir.replace(source_dir)
            partial = target.with_suffix(target.suffix + ".partial")
            shutil.copy2(source_dir / "validation.jsonl", partial)
            partial.replace(target)
            source_manifest = source_dir / "manifest.json"
            manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
            write_json(
                generated_evaluation_sidecar(target),
                {
                    "kind": "generated_frontier_evaluation",
                    "operation": operation,
                    "rows": int(frontier["examples_per_eval_operation"]),
                    "evaluation_file": str(target.resolve()),
                    "evaluation_sha256": file_sha256(target),
                    "source_manifest": str(source_manifest.resolve()),
                    "source_manifest_sha256": file_sha256(source_manifest),
                    "generation": manifest["generation"],
                    "counts": manifest["counts"],
                    "attempts": manifest["attempts"],
                },
            )
    return evaluation_data_record(frontier, operation)


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
    evaluation_file = resolve_evaluation_file(frontier, operation)
    eval_config = {
        "data_dir": str(evaluation_file.parent),
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
    target_accepted: int,
    prompt_stream_offset: int,
) -> dict[str, Any]:
    eval_config = {
        "operation": operation,
        "filter_mode": str(frontier["filter_mode"]),
        "target_accepted": target_accepted,
        "max_prompts": int(frontier["max_prompts"]),
        "prompt_batch_size": int(frontier["prompt_batch_size"]),
        "prompt_seed": int(frontier["prompt_seed"]),
        "prompt_stream_offset": prompt_stream_offset,
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
    validation_dataset_dir: Path,
    model_dir: Path,
    max_steps: int,
) -> dict[str, Any]:
    warmup_steps = int(max_steps * float(frontier["warmup_ratio"]))
    validation_interval = max(1, max_steps // int(frontier["validation_interval_divisor"]))
    candidate_count = len(range(validation_interval, max_steps, validation_interval)) + 1
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
        "val": {
            "interval": validation_interval,
            "eval_on_start": False,
            "data": {
                "type": "sft",
                "name": str(validation_dataset_dir),
                "seq_len": int(frontier["seq_len"]),
                "batch_size": int(frontier["validation_batch_size"]),
                "micro_batch_size": int(frontier["validation_micro_batch_size"]),
                "pack_function": "cat",
                "shuffle": False,
                "seed": 0,
                "loss_mask": {"system": False, "user": False, "assistant": True, "tool": False},
            },
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
            "interval": validation_interval,
            "weights_only": True,
            "keep_last": candidate_count,
            "weights": {"save_sharded": True, "save_format": "safetensors"},
        },
        "deployment": {
            "type": "single_node",
            "num_gpus": int(frontier["world_size"]),
            "gpus_per_node": int(frontier["world_size"]),
        },
        "slurm": {
            "job_name": f"rsci-{frontier['track']}-op{operation}-sft-val",
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
            "entity": "ram",
            "name": f"frontier-{frontier['track']}-op{operation}",
            "offline": False,
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
    implementation_sha256 = {
        name: file_sha256(Path(__file__).with_name(name))
        for name in (
            "figure3_eval.py",
            "frontier_build_dataset.py",
            "frontier_collect.py",
            "frontier_loop.py",
            "frontier_select_checkpoint.py",
            "generate.py",
            "solution_graph.py",
        )
    }
    implementation_sha256["src/prime_rl/trainer/sft/train.py"] = file_sha256(
        Path(__file__).resolve().parents[3] / "src/prime_rl/trainer/sft/train.py"
    )
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
        "implementation_sha256": implementation_sha256,
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
    collection_name: str,
    target_accepted: int,
    prompt_stream_offset: int,
    poll_seconds: int,
) -> Path:
    config_dir = iteration_dir / "configs"
    output_dir = iteration_dir / collection_name
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        return manifest_path
    infer_path = config_dir / f"inference_{collection_name}.toml"
    collect_path = config_dir / f"{collection_name}.toml"
    write_toml_once(infer_path, inference_config(frontier, model, output_dir / "server"))
    write_toml_once(
        collect_path,
        collection_config(
            frontier,
            operation,
            model,
            infer_path,
            output_dir,
            target_accepted,
            prompt_stream_offset,
        ),
    )
    key = f"op{operation}.{collection_name}"
    job_suffix = "collect" if collection_name == "collection" else "valcollect"
    name = f"rsci-{frontier['track']}-o{operation}-{job_suffix}"
    log_path = iteration_dir / f"slurm-{collection_name}-%j.log"
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
                f"op{operation} {collection_name} retry",
                {"failed_job": job_id, "state": error.state, "next_attempt": attempts + 1},
            )
            new_attempt = True


def build_dataset(
    frontier: dict[str, Any],
    root: Path,
    operation: int,
    output_dir: Path,
    collection_name: str,
    examples_per_operation: int,
    batch_size: int,
    micro_batch_size: int,
) -> dict[str, Any]:
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
                str(examples_per_operation),
                "--collection-name",
                collection_name,
                "--seq-len",
                str(frontier["seq_len"]),
                "--world-size",
                str(frontier["world_size"]),
                "--batch-size",
                str(batch_size),
                "--micro-batch-size",
                str(micro_batch_size),
            ]
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def prompt_digests(path: Path) -> set[str]:
    return {
        str(json.loads(line)["content_sha256"])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def audit_held_out_collection(
    training_manifest_path: Path,
    validation_manifest_path: Path,
    expected_validation_offset: int,
    evaluation_data: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    if output_path.exists():
        return json.loads(output_path.read_text(encoding="utf-8"))
    training_manifest = json.loads(training_manifest_path.read_text(encoding="utf-8"))
    validation_manifest = json.loads(validation_manifest_path.read_text(encoding="utf-8"))
    for field in ("operation", "filter_mode", "samples_per_prompt", "sampling", "source_model"):
        if training_manifest[field] != validation_manifest[field]:
            raise ValueError(f"Held-out collection differs from training on {field}")

    with Path(training_manifest["config"]).open("rb") as handle:
        training_config = tomllib.load(handle)["eval"]
    with Path(validation_manifest["config"]).open("rb") as handle:
        validation_config = tomllib.load(handle)["eval"]
    distribution_fields = (
        "operation",
        "filter_mode",
        "prompt_seed",
        "number_range",
        "depth",
        "id_max_op",
        "samples_per_prompt",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stop",
        "skip_special_tokens",
        "seq_len",
        "model",
        "tokenizer",
        "generator_op_max",
    )
    for field in distribution_fields:
        if training_config.get(field) != validation_config.get(field):
            raise ValueError(f"Held-out collection config differs from training on {field}")
    if int(training_config.get("prompt_stream_offset", 0)) != 0:
        raise ValueError("Training collection must use prompt_stream_offset=0")
    if int(validation_config.get("prompt_stream_offset", 0)) != expected_validation_offset:
        raise ValueError("Held-out collection used an unexpected prompt stream offset")

    training_prompts_path = training_manifest_path.parent / "prompts.jsonl"
    validation_prompts_path = validation_manifest_path.parent / "prompts.jsonl"
    training_digests = prompt_digests(training_prompts_path)
    validation_digests = prompt_digests(validation_prompts_path)
    overlap = training_digests & validation_digests
    if overlap:
        raise ValueError(f"Training and held-out collections share {len(overlap)} prompts")
    payload = {
        "same_distribution_fields": list(distribution_fields),
        "training_manifest": str(training_manifest_path.resolve()),
        "validation_manifest": str(validation_manifest_path.resolve()),
        "training_prompt_stream_offset": 0,
        "validation_prompt_stream_offset": expected_validation_offset,
        "training_prompts": len(training_digests),
        "validation_prompts": len(validation_digests),
        "overlapping_prompt_digests": 0,
        "training_prompts_sha256": file_sha256(training_prompts_path),
        "validation_prompts_sha256": file_sha256(validation_prompts_path),
    }
    if evaluation_data["kind"] == "generated_extension":
        evaluation_path = Path(evaluation_data["path"])
        evaluation_rows = [
            json.loads(line) for line in evaluation_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        evaluation_digests = {evaluation_row_digest(row) for row in evaluation_rows}
        if len(evaluation_digests) != len(evaluation_rows):
            raise ValueError("Generated evaluation rows contain duplicate prompt digests")
        training_overlap = training_digests & evaluation_digests
        validation_overlap = validation_digests & evaluation_digests
        if training_overlap or validation_overlap:
            raise ValueError(
                "Generated evaluation prompts overlap collection prompts: "
                f"training={len(training_overlap)} validation={len(validation_overlap)}"
            )
        evaluation_manifest = json.loads(Path(evaluation_data["manifest"]).read_text(encoding="utf-8"))
        generation = evaluation_manifest["generation"]
        expected_generation = {
            "depth": training_config["depth"],
            "number_range": training_config["number_range"],
            "id_max_op": training_config["id_max_op"],
            "generator_op_max_override": training_config["generator_op_max"],
        }
        for field, expected in expected_generation.items():
            if generation[field] != expected:
                raise ValueError(f"Generated evaluation differs from collection on {field}")
        payload.update(
            {
                "evaluation_data": evaluation_data,
                "evaluation_prompts": len(evaluation_digests),
                "evaluation_overlapping_training_prompt_digests": 0,
                "evaluation_overlapping_validation_prompt_digests": 0,
            }
        )
    write_json(output_path, payload)
    return payload


def select_checkpoint(model_dir: Path, validation_manifest: Path, output_path: Path) -> dict[str, Any]:
    if not output_path.exists():
        run(
            [
                "uv",
                "run",
                "--no-sync",
                "user/tianhaowu/rsci/frontier_select_checkpoint.py",
                "--sft-output",
                str(model_dir),
                "--validation-manifest",
                str(validation_manifest),
                "--output",
                str(output_path),
            ]
        )
    return json.loads(output_path.read_text(encoding="utf-8"))


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
        evaluation_data = ensure_evaluation_data(frontier, operation)
        iteration["evaluation_data"] = evaluation_data
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
            frontier,
            state,
            state_path,
            iteration_dir,
            operation,
            teacher_model,
            "collection",
            int(frontier["target_accepted"]),
            0,
            poll_seconds,
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

        validation_collection_manifest_path = phase_collection(
            frontier,
            state,
            state_path,
            iteration_dir,
            operation,
            teacher_model,
            "validation_collection",
            int(frontier["validation_accepted"]),
            int(frontier["validation_prompt_stream_offset"]),
            poll_seconds,
        )
        validation_collection_manifest = json.loads(validation_collection_manifest_path.read_text(encoding="utf-8"))
        if int(validation_collection_manifest["accepted"]) != int(frontier["validation_accepted"]):
            raise ValueError(f"Validation collection did not produce exactly {frontier['validation_accepted']} traces")
        if int(validation_collection_manifest["prompt_stream_offset"]) != int(
            frontier["validation_prompt_stream_offset"]
        ):
            raise ValueError("Validation collection used the wrong prompt stream")
        held_out_audit_path = iteration_dir / "held_out_audit.json"
        held_out_audit = audit_held_out_collection(
            collection_manifest_path,
            validation_collection_manifest_path,
            int(frontier["validation_prompt_stream_offset"]),
            evaluation_data,
            held_out_audit_path,
        )
        record_validation_collection_status = not iteration.get("validation_collection_status_recorded", False)
        iteration["validation_collection_manifest"] = str(validation_collection_manifest_path)
        iteration["held_out_audit"] = str(held_out_audit_path)
        iteration["validation_collection_status_recorded"] = True
        write_json(state_path, state)
        if record_validation_collection_status:
            append_status(
                root,
                f"op{operation} held-out collection complete",
                {
                    "accepted": validation_collection_manifest["accepted"],
                    "prompts": validation_collection_manifest["prompts_generated"],
                    "generations": validation_collection_manifest["generations"],
                    "prompt_stream_offset": validation_collection_manifest["prompt_stream_offset"],
                    "overlapping_prompts": held_out_audit["overlapping_prompt_digests"],
                },
            )

        dataset_dir = iteration_dir / "cumulative_dataset"
        dataset_manifest = build_dataset(
            frontier,
            root,
            operation,
            dataset_dir,
            "collection",
            int(frontier["target_accepted"]),
            int(frontier["batch_size"]),
            int(frontier["micro_batch_size"]),
        )
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

        validation_dataset_dir = iteration_dir / "cumulative_validation_dataset"
        validation_dataset_manifest = build_dataset(
            frontier,
            root,
            operation,
            validation_dataset_dir,
            "validation_collection",
            int(frontier["validation_accepted"]),
            int(frontier["validation_batch_size"]),
            int(frontier["validation_micro_batch_size"]),
        )
        minimum_validation_tokens = (
            int(frontier["world_size"]) * int(frontier["validation_micro_batch_size"]) * int(frontier["seq_len"])
        )
        if int(validation_dataset_manifest["token_count_including_eos"]) < minimum_validation_tokens:
            raise ValueError(
                "Held-out dataset cannot fill one validation micro-batch on every rank: "
                f"{validation_dataset_manifest['token_count_including_eos']} < {minimum_validation_tokens} tokens"
            )
        record_validation_dataset_status = not iteration.get("validation_dataset_status_recorded", False)
        iteration["validation_dataset_manifest"] = str(validation_dataset_dir / "manifest.json")
        iteration["validation_dataset_status_recorded"] = True
        write_json(state_path, state)
        if record_validation_dataset_status:
            append_status(
                root,
                f"op{operation} cumulative held-out dataset ready",
                {
                    "rows": validation_dataset_manifest["rows"],
                    "operations": validation_dataset_manifest["operations"],
                },
            )

        model_dir = iteration_dir / "model_min_val"
        sft_path = write_versioned_toml(
            iteration_dir / "configs",
            "sft_min_val",
            sft_config(
                frontier,
                operation,
                dataset_dir,
                validation_dataset_dir,
                model_dir,
                max_steps,
            ),
        )
        stable_path = model_dir / "weights" / f"step_{max_steps}" / "STABLE"
        if not stable_path.exists():
            key = f"op{operation}.sft_min_val"
            name = f"rsci-{frontier['track']}-op{operation}-sft-val"
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

        selection_path = iteration_dir / "checkpoint_selection.json"
        selection = select_checkpoint(
            model_dir,
            validation_dataset_dir / "manifest.json",
            selection_path,
        )
        trained_model = str(selection["selected_checkpoint"])
        record_sft_status = not iteration.get("sft_status_recorded", False)
        iteration["trained_model"] = trained_model
        iteration["checkpoint_selection"] = str(selection_path)
        iteration["selected_step"] = int(selection["selected_step"])
        iteration["selected_validation_loss"] = float(selection["selected_validation_loss"])
        iteration["sft_status_recorded"] = True
        write_json(state_path, state)
        if record_sft_status:
            append_status(
                root,
                f"op{operation} SFT complete",
                {
                    "model": trained_model,
                    "optimizer_steps": max_steps,
                    "selected_step": selection["selected_step"],
                    "selected_validation_loss": selection["selected_validation_loss"],
                },
            )

        post_metrics_path = phase_eval(
            frontier,
            state,
            state_path,
            iteration_dir,
            operation,
            trained_model,
            "post_selected",
            poll_seconds,
        )
        iteration["post_selected_eval_metrics"] = str(post_metrics_path)
        post_metrics = json.loads(post_metrics_path.read_text(encoding="utf-8"))
        append_status(
            root,
            f"op{operation} iteration complete",
            {
                "accepted": collection_manifest["accepted"],
                "cumulative_rows": dataset_manifest["rows"],
                "optimizer_steps": max_steps,
                "model": trained_model,
                "selected_step": selection["selected_step"],
                "selected_validation_loss": selection["selected_validation_loss"],
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
            sft_config(
                frontier,
                operation,
                root / "validation" / "data",
                root / "validation" / "held_out_data",
                root / "validation" / "model",
                62,
            )
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
