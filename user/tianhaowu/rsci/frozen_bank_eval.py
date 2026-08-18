#!/usr/bin/env python3
"""Collect and strictly score a deterministic frozen GSM-Infinite trajectory bank."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import solution_graph
from openai import AsyncOpenAI
from solution_graph import compare_solutions, numbers_match

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
COMPLETION_NAME = "completion.json"
PROGRESS_NAME = "progress.json"
PROMPTS_NAME = "prompts.jsonl"
GENERATIONS_NAME = "generations.jsonl"
STRICT_RESULTS_NAME = "strict_results.jsonl"
BATCH_DIR_NAME = "generation_batches"
INT64_MAX = 2**63 - 1
GENERATION_FIELDS = {
    "op",
    "id",
    "__idx",
    "template",
    "mode",
    "sample_rank",
    "finish_reason",
    "gen_solution_answer",
}
NONSEMANTIC_INFERENCE_FIELDS = {
    "dry_run",
    "log",
    "output_dir",
    "server",
    "slurm",
    "weight_broadcast",
}
TRANSPORT_FIELDS = {
    "backend_port",
    "decode_port",
    "decode_sidecar_port",
    "host",
    "port",
    "prefill_port",
}


@dataclass(frozen=True)
class BatchSpec:
    op: int
    row_index: int
    sample_id: str
    template: str | None
    mode: str | None
    prompt: str
    start_rank: int
    end_rank: int
    request_seed: int
    path: Path

    @property
    def size(self) -> int:
        return self.end_rank - self.start_rank

    @property
    def group_key(self) -> tuple[int, int]:
        return self.op, self.row_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validate-only", action="store_true")
    modes.add_argument("--score-only", action="store_true")
    modes.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object, *, indent: int | None = None) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
            separators=None if indent is not None else (",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value).rstrip(b"\n")).hexdigest()


def write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(content)
    partial.replace(path)


def write_json_atomic(path: Path, value: object) -> None:
    write_bytes_atomic(path, canonical_json_bytes(value, indent=2))


def install_expected_file(partial: Path, target: Path) -> None:
    if target.is_file():
        if partial.stat().st_size != target.stat().st_size or file_sha256(partial) != file_sha256(target):
            raise ValueError(f"Existing finalized artifact differs from deterministic reconstruction: {target}")
        partial.unlink()
    else:
        partial.replace(target)


def _strip_transport_fields(value: Any) -> None:
    if isinstance(value, dict):
        for field in tuple(value):
            if field in TRANSPORT_FIELDS or field.endswith("_port"):
                value.pop(field)
            else:
                _strip_transport_fields(value[field])
    elif isinstance(value, list):
        for item in value:
            _strip_transport_fields(item)


def normalized_inference_config(path: Path, expected_model: str) -> dict[str, Any]:
    with path.open("rb") as handle:
        inference = tomllib.load(handle)
    model = inference.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("name"), str):
        raise ValueError(f"Inference config has no model.name: {path}")
    configured_model = Path(model["name"]).expanduser()
    eval_model = Path(expected_model).expanduser()
    if configured_model.exists() and eval_model.exists():
        matches = configured_model.resolve() == eval_model.resolve()
    else:
        matches = str(configured_model) == str(eval_model)
    if not matches:
        raise ValueError(f"Eval and inference models differ: {eval_model} != {configured_model}")

    normalized = json.loads(json.dumps(inference))
    for field in NONSEMANTIC_INFERENCE_FIELDS:
        normalized.pop(field, None)
    normalized["model"].pop("name", None)
    _strip_transport_fields(normalized)
    return normalized


def model_identity(model_name: str) -> dict[str, Any]:
    model_path = Path(model_name).expanduser().resolve()
    if not model_path.exists():
        raise FileNotFoundError(model_path)
    files = [model_path] if model_path.is_file() else sorted(path for path in model_path.rglob("*") if path.is_file())
    inventory = []
    for path in files:
        relative = path.name if model_path.is_file() else path.relative_to(model_path).as_posix()
        inventory.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return {
        "configured_name": model_name,
        "resolved_path": str(model_path),
        "file_count": len(inventory),
        "size_bytes": sum(item["size_bytes"] for item in inventory),
        "inventory_sha256": canonical_json_sha256(inventory),
    }


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    if not isinstance(config.get("infer_config"), str) or not config["infer_config"]:
        raise ValueError("Config must define infer_config")
    eval_config = config.get("eval")
    if not isinstance(eval_config, dict):
        raise ValueError("Config must define [eval]")
    required = {
        "bank_id",
        "data_dir",
        "operations",
        "examples_per_operation",
        "output_dir",
        "model",
        "api_base_url",
        "samples_per_prompt",
        "request_batch_size",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "request_seed",
        "defect_seed",
        "stop",
        "skip_special_tokens",
        "request_timeout_seconds",
        "max_concurrent_prompts",
    }
    missing = sorted(required - eval_config.keys())
    if missing:
        raise ValueError(f"Frozen bank config is missing fields: {missing}")
    operations = eval_config["operations"]
    if (
        not isinstance(operations, list)
        or not operations
        or any(isinstance(op, bool) or not isinstance(op, int) or op < 1 for op in operations)
        or operations != sorted(set(operations))
    ):
        raise ValueError("eval.operations must be sorted unique positive integers")
    positive_int_fields = (
        "examples_per_operation",
        "samples_per_prompt",
        "request_batch_size",
        "max_tokens",
        "max_concurrent_prompts",
    )
    for field in positive_int_fields:
        value = eval_config[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"eval.{field} must be a positive integer")
    if eval_config["request_batch_size"] > eval_config["samples_per_prompt"]:
        raise ValueError("eval.request_batch_size cannot exceed eval.samples_per_prompt")
    for field in ("data_dir", "output_dir", "model", "api_base_url"):
        if not isinstance(eval_config[field], str) or not eval_config[field]:
            raise ValueError(f"eval.{field} must be a non-empty string")
    temperature = eval_config["temperature"]
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
        raise ValueError("eval.temperature must be finite")
    if temperature < 0:
        raise ValueError("eval.temperature cannot be negative")
    top_p = eval_config["top_p"]
    if isinstance(top_p, bool) or not isinstance(top_p, (int, float)) or not math.isfinite(top_p):
        raise ValueError("eval.top_p must be finite")
    if not 0 < top_p <= 1:
        raise ValueError("eval.top_p must be in (0, 1]")
    top_k = eval_config["top_k"]
    if isinstance(top_k, bool) or not isinstance(top_k, int) or (top_k != -1 and top_k < 1):
        raise ValueError("eval.top_k must be -1 or a positive integer")
    max_retries = eval_config.get("max_retries", 2)
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError("eval.max_retries must be a non-negative integer")
    for field in ("request_seed", "defect_seed"):
        value = eval_config[field]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= INT64_MAX:
            raise ValueError(f"eval.{field} must be an integer in [0, 2^63-1]")
    if not isinstance(eval_config["bank_id"], str) or not eval_config["bank_id"]:
        raise ValueError("eval.bank_id must be a non-empty string")
    if not isinstance(eval_config["stop"], list) or not all(isinstance(item, str) for item in eval_config["stop"]):
        raise ValueError("eval.stop must be a list of strings")
    if not isinstance(eval_config["skip_special_tokens"], bool):
        raise ValueError("eval.skip_special_tokens must be boolean")
    if (
        not math.isfinite(float(eval_config["request_timeout_seconds"]))
        or float(eval_config["request_timeout_seconds"]) <= 0
    ):
        raise ValueError("eval.request_timeout_seconds must be positive and finite")
    infer_path = Path(config["infer_config"]).expanduser()
    if not infer_path.is_absolute():
        candidates = (
            Path.cwd() / infer_path,
            Path(__file__).resolve().parents[3] / infer_path,
            path.parent / infer_path,
        )
        infer_path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), candidates[0])
    if not infer_path.is_file():
        raise FileNotFoundError(infer_path)
    config["infer_config"] = str(infer_path)
    normalized_inference_config(infer_path, str(eval_config["model"]))
    return config


def compose_prompt(row: dict[str, Any]) -> str:
    prompt = row.get("prompt")
    if prompt is None:
        prompt = f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question> <solution>"
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Prompt row {row.get('id')!r} has no usable prompt")
    return prompt


def load_rows(eval_config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data_dir = Path(eval_config["data_dir"]).expanduser().resolve()
    expected = int(eval_config["examples_per_operation"])
    rows: list[dict[str, Any]] = []
    datasets = []
    seen_ids = set()
    seen_prompts = set()
    for operation in eval_config["operations"]:
        path = data_dir / f"op{operation}-{expected}.jsonl"
        raw = path.read_bytes()
        operation_rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        if len(operation_rows) != expected:
            raise ValueError(f"Expected {expected} rows in {path}, found {len(operation_rows)}")
        for row_index, row in enumerate(operation_rows):
            if not isinstance(row, dict):
                raise ValueError(f"Dataset row is not an object: {path}:{row_index + 1}")
            required = {"id", "op", "problem", "question", "solution", "answer", "template", "mode"}
            missing = sorted(required - row.keys())
            if missing:
                raise ValueError(f"Dataset row {row_index} in {path} is missing fields: {missing}")
            if int(row["op"]) != operation:
                raise ValueError(f"Dataset row {row_index} in {path} has op={row['op']}")
            sample_id = str(row["id"])
            prompt = compose_prompt(row)
            if sample_id in seen_ids:
                raise ValueError(f"Frozen bank inputs contain duplicate id: {sample_id}")
            if prompt in seen_prompts:
                raise ValueError(f"Frozen bank inputs contain duplicate prompt: {sample_id}")
            seen_ids.add(sample_id)
            seen_prompts.add(prompt)
            row["__idx"] = row_index
            rows.append(row)
        datasets.append(
            {
                "op": operation,
                "path": str(path),
                "rows": len(operation_rows),
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return rows, datasets


def validate_prompt_view_manifest(
    path: Path,
    eval_config: dict[str, Any],
    datasets: list[dict[str, Any]],
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported prompt-view manifest: {path}")

    operations = list(eval_config["operations"])
    examples = int(eval_config["examples_per_operation"])
    expected_groups = len(operations) * examples
    protocol = payload.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError(f"Prompt-view manifest has no protocol: {path}")
    if protocol.get("operations") != operations:
        raise ValueError("Prompt-view manifest operations differ from the evaluation config")
    if protocol.get("prompts_per_operation") != examples:
        raise ValueError("Prompt-view manifest prompt count differs from the evaluation config")

    counts = payload.get("counts")
    expected_counts = {
        "operations": len(operations),
        "selected_prompts": expected_groups,
        "unique_selected_ids": expected_groups,
        "unique_selected_prompts": expected_groups,
        "heldout_id_overlap": 0,
        "heldout_prompt_overlap": 0,
    }
    if not isinstance(counts, dict) or any(counts.get(field) != value for field, value in expected_counts.items()):
        raise ValueError(f"Prompt-view manifest counts do not satisfy the frozen-bank contract: {path}")

    per_operation = payload.get("per_operation")
    if not isinstance(per_operation, dict) or set(per_operation) != {str(operation) for operation in operations}:
        raise ValueError(f"Prompt-view manifest operation inventory is invalid: {path}")
    for dataset in datasets:
        operation = int(dataset["op"])
        entry = per_operation[str(operation)]
        if not isinstance(entry, dict):
            raise ValueError(f"Prompt-view manifest OP{operation} entry is invalid")
        output = entry.get("output")
        expected_output = {
            "rows": int(dataset["rows"]),
            "size_bytes": int(dataset["size_bytes"]),
            "sha256": str(dataset["sha256"]),
        }
        if not isinstance(output, dict) or any(output.get(field) != value for field, value in expected_output.items()):
            raise ValueError(f"Prompt-view manifest OP{operation} output identity does not match its JSONL shard")
        output_path = output.get("path")
        if (
            not isinstance(output_path, str)
            or Path(output_path).expanduser().resolve() != Path(dataset["path"]).resolve()
        ):
            raise ValueError(f"Prompt-view manifest OP{operation} output path differs from its JSONL shard")
        heldout = entry.get("heldout")
        if not isinstance(heldout, dict) or heldout.get("id_overlap") != 0 or heldout.get("prompt_overlap") != 0:
            raise ValueError(f"Prompt-view manifest OP{operation} does not certify zero held-out overlap")


def prompt_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": int(row["op"]),
        "__idx": int(row["__idx"]),
        "id": str(row["id"]),
        "problem": str(row["problem"]),
        "question": str(row["question"]),
        "solution": str(row["solution"]),
        "answer": str(row["answer"]),
        "context": row.get("context"),
        "template": row.get("template"),
        "mode": row.get("mode"),
        "prompt": compose_prompt(row),
    }


def prompts_content(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(prompt_record(row)) for row in rows)


def derive_batch_seed(row: dict[str, Any], base_seed: int, start_rank: int, batch_size: int) -> int:
    if batch_size < 1 or batch_size > INT64_MAX:
        raise ValueError("batch_size must be in [1, 2^63-1]")
    material = json.dumps(
        [base_seed, int(row["op"]), str(row["id"]), start_rank],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    limit = INT64_MAX - batch_size + 1
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % limit


def batch_specs(rows: list[dict[str, Any]], eval_config: dict[str, Any]) -> list[BatchSpec]:
    output_dir = Path(eval_config["output_dir"]).expanduser().resolve()
    samples = int(eval_config["samples_per_prompt"])
    batch_size = int(eval_config["request_batch_size"])
    base_seed = int(eval_config["request_seed"])
    specs = []
    for row in rows:
        for start_rank in range(0, samples, batch_size):
            end_rank = min(start_rank + batch_size, samples)
            seed = derive_batch_seed(row, base_seed, start_rank, end_rank - start_rank)
            path = (
                output_dir
                / BATCH_DIR_NAME
                / f"op{int(row['op']):02d}"
                / f"row_{int(row['__idx']):04d}_r{start_rank:04d}_{end_rank:04d}.json"
            )
            specs.append(
                BatchSpec(
                    op=int(row["op"]),
                    row_index=int(row["__idx"]),
                    sample_id=str(row["id"]),
                    template=str(row["template"]) if row.get("template") is not None else None,
                    mode=str(row["mode"]) if row.get("mode") is not None else None,
                    prompt=compose_prompt(row),
                    start_rank=start_rank,
                    end_rank=end_rank,
                    request_seed=seed,
                    path=path,
                )
            )
    return specs


def implementation_identity() -> dict[str, str]:
    return {
        "frozen_bank_eval.py": file_sha256(Path(__file__)),
        "rsci_gsm_infinite.py": file_sha256(Path(__file__).with_name("rsci_gsm_infinite.py")),
        "solution_graph.py": file_sha256(Path(solution_graph.__file__)),
    }


def build_manifest(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    datasets: list[dict[str, Any]],
    specs: list[BatchSpec],
) -> dict[str, Any]:
    eval_config = config["eval"]
    data_dir = Path(eval_config["data_dir"]).expanduser().resolve()
    prompt_view_manifest = data_dir / "prompt_view_manifest.json"
    if not prompt_view_manifest.is_file():
        raise FileNotFoundError(prompt_view_manifest)
    validate_prompt_view_manifest(prompt_view_manifest, eval_config, datasets)
    prompt_bytes = prompts_content(rows)
    expected_trajectories = len(rows) * int(eval_config["samples_per_prompt"])
    normalized_inference = normalized_inference_config(
        Path(config["infer_config"]),
        str(eval_config["model"]),
    )
    contract = {
        "bank_id": str(eval_config["bank_id"]),
        "operations": list(eval_config["operations"]),
        "examples_per_operation": int(eval_config["examples_per_operation"]),
        "expected": {
            "groups": len(rows),
            "batches": len(specs),
            "trajectories": expected_trajectories,
        },
        "prompt_view": {
            "validation": "prompt-view-manifest-v1",
            "manifest_path": str(prompt_view_manifest),
            "manifest_size_bytes": prompt_view_manifest.stat().st_size,
            "manifest_sha256": file_sha256(prompt_view_manifest),
            "datasets": datasets,
            "prompt_sequence_sha256": canonical_json_sha256(
                [{"op": row["op"], "__idx": row["__idx"], "id": row["id"]} for row in rows]
            ),
        },
        "model": model_identity(str(eval_config["model"])),
        "inference": {
            "normalization": "frozen-bank-inference-v1",
            "normalized_config": normalized_inference,
            "normalized_config_sha256": canonical_json_sha256(normalized_inference),
        },
        "sampling": {
            "samples_per_prompt": int(eval_config["samples_per_prompt"]),
            "request_batch_size": int(eval_config["request_batch_size"]),
            "max_tokens": int(eval_config["max_tokens"]),
            "temperature": float(eval_config["temperature"]),
            "top_p": float(eval_config["top_p"]),
            "top_k": int(eval_config["top_k"]),
            "stop": list(eval_config["stop"]),
            "skip_special_tokens": bool(eval_config["skip_special_tokens"]),
            "request_seed": int(eval_config["request_seed"]),
            "seed_derivation": "sha256-v1([base_seed,op,id,batch_start]); vLLM child seed = parent + choice.index",
            "sample_rank_mapping": "batch_start + choice.index",
        },
        "scoring": {
            "strict": "released compare_solutions(...).perfect",
            "answer": "production answer_correct_metric with 1e-6 absolute tolerance",
            "candidate": "answer_correct and not strict_correct",
            "defect_seed": int(eval_config["defect_seed"]),
            "defect_draw": "sha256-v1(defect_seed,json([sample_id,sample_rank])) / 2^64",
            "implementation_sha256": implementation_identity(),
        },
        "runtime_packages": {
            "openai": importlib.metadata.version("openai"),
            "transformers": importlib.metadata.version("transformers"),
            "vllm": importlib.metadata.version("vllm"),
        },
        "artifacts": {
            "prompts": {"path": PROMPTS_NAME, "rows": len(rows), "ordering": "(op,__idx)"},
            "generations": {
                "path": GENERATIONS_NAME,
                "rows": expected_trajectories,
                "ordering": "(op,__idx,sample_rank)",
            },
            "strict_results": {
                "path": STRICT_RESULTS_NAME,
                "rows": expected_trajectories,
                "ordering": "(op,__idx,sample_rank)",
            },
        },
        "prompts_content": {
            "size_bytes": len(prompt_bytes),
            "sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_sha256": canonical_json_sha256(contract),
        "contract": contract,
    }


def expected_shard_metadata(spec: BatchSpec, contract_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_sha256": contract_sha256,
        "prompt": {"op": spec.op, "__idx": spec.row_index, "id": spec.sample_id},
        "rank_interval": {"start": spec.start_rank, "end": spec.end_rank},
        "request_seed": spec.request_seed,
        "seed_rule": "vLLM child seed = request_seed + choice.index",
    }


def validate_generation_record(record: object, spec: BatchSpec, expected_rank: int) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != GENERATION_FIELDS:
        fields = sorted(record) if isinstance(record, dict) else type(record).__name__
        raise ValueError(f"Invalid generation fields for {spec.path}: {fields}")
    expected = {
        "op": spec.op,
        "id": spec.sample_id,
        "__idx": spec.row_index,
        "template": spec.template,
        "mode": spec.mode,
        "sample_rank": expected_rank,
    }
    for field, value in expected.items():
        if record[field] != value or type(record[field]) is not type(value):
            raise ValueError(
                f"Generation {field} mismatch for {spec.path}: observed={record[field]!r}, expected={value!r}"
            )
    if record["finish_reason"] is not None and not isinstance(record["finish_reason"], str):
        raise ValueError(f"Generation finish_reason is invalid for {spec.path}")
    if not isinstance(record["gen_solution_answer"], str):
        raise ValueError(f"Generation text is invalid for {spec.path}")
    return record


def validate_shard_payload(payload: object, spec: BatchSpec, contract_sha256: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError(f"Batch shard is not an object: {spec.path}")
    expected_metadata = expected_shard_metadata(spec, contract_sha256)
    metadata = {field: payload.get(field) for field in expected_metadata}
    if metadata != expected_metadata:
        raise ValueError(f"Batch shard metadata mismatch: {spec.path}")
    if set(payload) != {*expected_metadata, "records"} or not isinstance(payload["records"], list):
        raise ValueError(f"Batch shard has invalid schema: {spec.path}")
    if len(payload["records"]) != spec.size:
        raise ValueError(f"Batch shard has {len(payload['records'])} records, expected {spec.size}: {spec.path}")
    return [
        validate_generation_record(record, spec, rank)
        for rank, record in zip(range(spec.start_rank, spec.end_rank), payload["records"], strict=True)
    ]


def load_shard(spec: BatchSpec, contract_sha256: str) -> list[dict[str, Any]]:
    payload = json.loads(spec.path.read_text(encoding="utf-8"))
    return validate_shard_payload(payload, spec, contract_sha256)


def records_from_choices(spec: BatchSpec, choices: Iterable[Any]) -> list[dict[str, Any]]:
    choices = list(choices)
    indices = [choice.index for choice in choices]
    if any(isinstance(index, bool) or not isinstance(index, int) for index in indices):
        raise ValueError(f"Server returned a non-integer choice index for {spec.group_key}")
    if sorted(indices) != list(range(spec.size)) or len(indices) != len(set(indices)):
        raise ValueError(
            f"Server choice indices for {spec.group_key} are {sorted(indices)}, expected {list(range(spec.size))}"
        )
    records = []
    for choice in sorted(choices, key=lambda item: item.index):
        rank = spec.start_rank + choice.index
        record = {
            "op": spec.op,
            "id": spec.sample_id,
            "__idx": spec.row_index,
            "template": spec.template,
            "mode": spec.mode,
            "sample_rank": rank,
            "finish_reason": choice.finish_reason,
            "gen_solution_answer": choice.text,
        }
        records.append(validate_generation_record(record, spec, rank))
    return records


async def request_batch(
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    spec: BatchSpec,
    eval_config: dict[str, Any],
    contract_sha256: str,
) -> tuple[BatchSpec, dict[str, Any]]:
    async with semaphore:
        response = await client.completions.create(
            model=eval_config["model"],
            prompt=spec.prompt,
            n=spec.size,
            max_tokens=int(eval_config["max_tokens"]),
            temperature=float(eval_config["temperature"]),
            top_p=float(eval_config["top_p"]),
            stop=eval_config["stop"],
            seed=spec.request_seed,
            extra_body={
                "skip_special_tokens": bool(eval_config["skip_special_tokens"]),
                "top_k": int(eval_config["top_k"]),
            },
        )
    records = records_from_choices(spec, response.choices)
    return spec, {**expected_shard_metadata(spec, contract_sha256), "records": records}


def progress_payload(
    *,
    manifest: dict[str, Any],
    status: str,
    specs: list[BatchSpec],
    completed_specs: set[Path],
    completed_records: int,
    started_at: float,
    initial_records: int,
) -> dict[str, Any]:
    batch_totals: dict[tuple[int, int], int] = {}
    batch_completed: dict[tuple[int, int], int] = {}
    for spec in specs:
        batch_totals[spec.group_key] = batch_totals.get(spec.group_key, 0) + 1
        if spec.path in completed_specs:
            batch_completed[spec.group_key] = batch_completed.get(spec.group_key, 0) + 1
    groups = sum(batch_completed.get(key, 0) == total for key, total in batch_totals.items())
    elapsed = max(0.0, time.monotonic() - started_at)
    generated_this_attempt = completed_records - initial_records
    throughput = generated_this_attempt / elapsed if elapsed > 0 else 0.0
    expected_records = int(manifest["contract"]["expected"]["trajectories"])
    eta = (expected_records - completed_records) / throughput if throughput > 0 else None
    return {
        "schema_version": SCHEMA_VERSION,
        "bank_id": manifest["contract"]["bank_id"],
        "contract_sha256": manifest["contract_sha256"],
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "expected": manifest["contract"]["expected"],
        "validated": {
            "batches": len(completed_specs),
            "groups": groups,
            "trajectories": completed_records,
        },
        "attempt": {
            "elapsed_seconds": elapsed,
            "new_trajectories": generated_this_attempt,
            "trajectories_per_second": throughput,
            "eta_seconds": eta,
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        },
    }


async def generate_batches(
    config: dict[str, Any],
    manifest: dict[str, Any],
    specs: list[BatchSpec],
) -> None:
    eval_config = config["eval"]
    output_dir = Path(eval_config["output_dir"]).expanduser().resolve()
    completed_specs = set()
    completed_records = 0
    missing = []
    for spec in specs:
        if spec.path.is_file():
            records = load_shard(spec, manifest["contract_sha256"])
            completed_specs.add(spec.path)
            completed_records += len(records)
        else:
            missing.append(spec)
    started_at = time.monotonic()
    initial_records = completed_records
    write_json_atomic(
        output_dir / PROGRESS_NAME,
        progress_payload(
            manifest=manifest,
            status="generating" if missing else "generated",
            specs=specs,
            completed_specs=completed_specs,
            completed_records=completed_records,
            started_at=started_at,
            initial_records=initial_records,
        ),
    )
    if not missing:
        return

    client = AsyncOpenAI(
        base_url=str(eval_config["api_base_url"]),
        api_key="unused",
        timeout=float(eval_config["request_timeout_seconds"]),
        max_retries=int(eval_config.get("max_retries", 2)),
    )
    semaphore = asyncio.Semaphore(int(eval_config["max_concurrent_prompts"]))
    tasks = [request_batch(client, semaphore, spec, eval_config, manifest["contract_sha256"]) for spec in missing]
    last_progress = time.monotonic()
    try:
        for completed_number, task in enumerate(asyncio.as_completed(tasks), start=1):
            spec, payload = await task
            content = canonical_json_bytes(payload, indent=2)
            if spec.path.is_file():
                if spec.path.read_bytes() != content:
                    raise ValueError(f"Concurrent batch artifact differs from generated payload: {spec.path}")
            else:
                write_bytes_atomic(spec.path, content)
            load_shard(spec, manifest["contract_sha256"])
            completed_specs.add(spec.path)
            completed_records += spec.size
            now = time.monotonic()
            if completed_number % 10 == 0 or now - last_progress >= 5 or completed_number == len(missing):
                write_json_atomic(
                    output_dir / PROGRESS_NAME,
                    progress_payload(
                        manifest=manifest,
                        status="generating" if completed_number < len(missing) else "generated",
                        specs=specs,
                        completed_specs=completed_specs,
                        completed_records=completed_records,
                        started_at=started_at,
                        initial_records=initial_records,
                    ),
                )
                last_progress = now
    finally:
        await client.close()


def consolidate_generations(manifest: dict[str, Any], specs: list[BatchSpec], output_dir: Path) -> Path:
    generations_path = output_dir / GENERATIONS_NAME
    partial = generations_path.with_suffix(".jsonl.partial")
    rows = 0
    with partial.open("wb") as output:
        for spec in specs:
            records = load_shard(spec, manifest["contract_sha256"])
            for record in records:
                output.write(canonical_json_bytes(record))
                rows += 1
    expected = int(manifest["contract"]["expected"]["trajectories"])
    if rows != expected:
        raise RuntimeError(f"Consolidated {rows} generations, expected {expected}")
    install_expected_file(partial, generations_path)
    return generations_path


def defect_draw(sample_id: str, sample_rank: int, defect_seed: int) -> tuple[int, float]:
    draw_key = json.dumps([sample_id, sample_rank], separators=(",", ":"))
    draw_u64 = int.from_bytes(hashlib.sha256(f"{defect_seed}:{draw_key}".encode()).digest()[:8], "big")
    return draw_u64, draw_u64 / 2**64


def strict_result_record(
    prompt: dict[str, Any],
    generation: dict[str, Any],
    defect_seed: int,
) -> dict[str, Any]:
    report = compare_solutions(str(prompt["solution"]), str(generation["gen_solution_answer"]))
    perfect = bool(report["perfect"])
    answer_mismatch = report["answer_mismatch"]
    if answer_mismatch is None:
        answer_correct = True
    else:
        _, predicted_answer = answer_mismatch
        answer_correct = numbers_match(float(prompt["answer"]), predicted_answer, tolerance=1e-6)
    candidate = bool(answer_correct and not perfect)
    draw_u64, draw = defect_draw(str(generation["id"]), int(generation["sample_rank"]), defect_seed)
    return {
        "op": int(generation["op"]),
        "id": str(generation["id"]),
        "__idx": int(generation["__idx"]),
        "sample_rank": int(generation["sample_rank"]),
        "template": generation.get("template"),
        "mode": generation.get("mode"),
        "finish_reason": generation.get("finish_reason"),
        "perfect": perfect,
        "answer_correct": answer_correct,
        "candidate": candidate,
        "value_mismatch_count": len(report["value_mismatches"]),
        "dependency_mismatch_count": len(report["dependency_mismatches"]),
        "answer_mismatch": report["answer_mismatch"] is not None,
        "extra_nodes": len(report["extra_in_pred"]),
        "missing_nodes": len(report["missing_in_pred"]),
        "defect_draw_u64": draw_u64,
        "defect_draw": draw,
    }


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank JSONL record at {path}:{line_number}")
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"JSONL record is not an object at {path}:{line_number}")
            yield record


def score_generations(
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    generations_path: Path,
    output_dir: Path,
) -> Path:
    strict_path = output_dir / STRICT_RESULTS_NAME
    partial = strict_path.with_suffix(".jsonl.partial")
    prompts = {(int(row["op"]), int(row["__idx"])): row for row in rows}
    expected_key: tuple[int, int, int] | None = None
    count = 0
    defect_seed = int(manifest["contract"]["scoring"]["defect_seed"])
    with partial.open("wb") as output:
        for generation in iter_jsonl(generations_path):
            key = (int(generation["op"]), int(generation["__idx"]), int(generation["sample_rank"]))
            if expected_key is not None and key <= expected_key:
                raise ValueError(f"Generations are not in canonical strict order at {key}")
            expected_key = key
            prompt_key = key[:2]
            prompt = prompts.get(prompt_key)
            if prompt is None or str(prompt["id"]) != str(generation["id"]):
                raise ValueError(f"Generation does not match prompt identity: {key}")
            output.write(canonical_json_bytes(strict_result_record(prompt, generation, defect_seed)))
            count += 1
    expected = int(manifest["contract"]["expected"]["trajectories"])
    if count != expected:
        raise RuntimeError(f"Strictly scored {count} generations, expected {expected}")
    install_expected_file(partial, strict_path)
    return strict_path


def artifact_identity(path: Path, expected_rows: int, ordering: str) -> dict[str, Any]:
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if not line.strip():
                raise ValueError(f"Blank artifact line in {path}")
            rows += 1
    if rows != expected_rows:
        raise ValueError(f"Artifact {path} has {rows} rows, expected {expected_rows}")
    return {
        "path": path.name,
        "rows": rows,
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "ordering": ordering,
    }


def batch_inventory(specs: list[BatchSpec], contract_sha256: str) -> dict[str, Any]:
    inventory = []
    trajectories = 0
    common_root = specs[0].path.parents[2] if specs else Path(".")
    for spec in specs:
        records = load_shard(spec, contract_sha256)
        trajectories += len(records)
        inventory.append(
            {
                "path": str(spec.path.relative_to(common_root)),
                "size_bytes": spec.path.stat().st_size,
                "sha256": file_sha256(spec.path),
                "rows": len(records),
            }
        )
    return {
        "count": len(inventory),
        "trajectories": trajectories,
        "inventory_sha256": canonical_json_sha256(inventory),
    }


def completion_payload(manifest: dict[str, Any], specs: list[BatchSpec], output_dir: Path) -> dict[str, Any]:
    expected = manifest["contract"]["expected"]
    artifacts = manifest["contract"]["artifacts"]
    shards = batch_inventory(specs, manifest["contract_sha256"])
    if shards["count"] != int(expected["batches"]) or shards["trajectories"] != int(expected["trajectories"]):
        raise RuntimeError(f"Batch inventory does not meet the completion contract: {shards}")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_sha256": manifest["contract_sha256"],
        "manifest": {
            "path": MANIFEST_NAME,
            "size_bytes": (output_dir / MANIFEST_NAME).stat().st_size,
            "sha256": file_sha256(output_dir / MANIFEST_NAME),
        },
        "artifacts": {
            "prompts": artifact_identity(
                output_dir / PROMPTS_NAME,
                int(expected["groups"]),
                artifacts["prompts"]["ordering"],
            ),
            "generations": artifact_identity(
                output_dir / GENERATIONS_NAME,
                int(expected["trajectories"]),
                artifacts["generations"]["ordering"],
            ),
            "strict_results": artifact_identity(
                output_dir / STRICT_RESULTS_NAME,
                int(expected["trajectories"]),
                artifacts["strict_results"]["ordering"],
            ),
        },
        "batch_shards": shards,
        "scoring": {"implementation_sha256": implementation_identity()},
    }


def write_or_verify_completion(manifest: dict[str, Any], specs: list[BatchSpec], output_dir: Path) -> dict[str, Any]:
    expected = completion_payload(manifest, specs, output_dir)
    path = output_dir / COMPLETION_NAME
    content = canonical_json_bytes(expected, indent=2)
    if path.is_file():
        if path.read_bytes() != content:
            raise ValueError(f"Completion manifest differs from verified artifacts: {path}")
    else:
        write_bytes_atomic(path, content)
    return expected


def prepare_inputs(
    config_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[BatchSpec], dict[str, Any]]:
    config = load_config(config_path)
    rows, datasets = load_rows(config["eval"])
    specs = batch_specs(rows, config["eval"])
    manifest = build_manifest(config, rows, datasets, specs)
    return config, rows, specs, manifest


def initialize_output(manifest: dict[str, Any], rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prompts_path = output_dir / PROMPTS_NAME
    expected_prompts = prompts_content(rows)
    if prompts_path.is_file():
        if prompts_path.read_bytes() != expected_prompts:
            raise ValueError(f"Existing prompt artifact differs from configured inputs: {prompts_path}")
    else:
        write_bytes_atomic(prompts_path, expected_prompts)
    manifest_path = output_dir / MANIFEST_NAME
    content = canonical_json_bytes(manifest, indent=2)
    if manifest_path.is_file():
        if manifest_path.read_bytes() != content:
            raise ValueError(f"Existing bank manifest differs from configured contract: {manifest_path}")
    else:
        write_bytes_atomic(manifest_path, content)


def verify_completion(manifest: dict[str, Any], specs: list[BatchSpec], output_dir: Path) -> dict[str, Any]:
    path = output_dir / COMPLETION_NAME
    if not path.is_file():
        raise FileNotFoundError(path)
    observed = json.loads(path.read_text(encoding="utf-8"))
    expected = completion_payload(manifest, specs, output_dir)
    if observed != expected or type(observed) is not type(expected):
        raise ValueError(f"Completion manifest does not match current artifacts: {path}")
    return expected


def main() -> None:
    args = parse_args()
    config, rows, specs, manifest = prepare_inputs(args.config.expanduser().resolve())
    output_dir = Path(config["eval"]["output_dir"]).expanduser().resolve()
    if args.validate_only:
        print(
            json.dumps(
                {
                    "bank_id": manifest["contract"]["bank_id"],
                    "contract_sha256": manifest["contract_sha256"],
                    "expected": manifest["contract"]["expected"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    initialize_output(manifest, rows, output_dir)
    if args.verify_only:
        print(json.dumps(verify_completion(manifest, specs, output_dir), indent=2, sort_keys=True))
        return
    if (output_dir / COMPLETION_NAME).is_file():
        print(json.dumps(verify_completion(manifest, specs, output_dir), indent=2, sort_keys=True))
        return
    if not args.score_only:
        asyncio.run(generate_batches(config, manifest, specs))
    elif any(not spec.path.is_file() for spec in specs):
        raise FileNotFoundError("--score-only requires every deterministic generation batch shard")

    completed_paths = {spec.path for spec in specs if spec.path.is_file()}
    completed_records = sum(spec.size for spec in specs if spec.path in completed_paths)
    started_at = time.monotonic()
    write_json_atomic(
        output_dir / PROGRESS_NAME,
        progress_payload(
            manifest=manifest,
            status="consolidating",
            specs=specs,
            completed_specs=completed_paths,
            completed_records=completed_records,
            started_at=started_at,
            initial_records=completed_records,
        ),
    )
    generations_path = consolidate_generations(manifest, specs, output_dir)
    write_json_atomic(
        output_dir / PROGRESS_NAME,
        progress_payload(
            manifest=manifest,
            status="scoring",
            specs=specs,
            completed_specs=completed_paths,
            completed_records=completed_records,
            started_at=started_at,
            initial_records=completed_records,
        ),
    )
    score_generations(manifest, rows, generations_path, output_dir)
    completion = write_or_verify_completion(manifest, specs, output_dir)
    write_json_atomic(
        output_dir / PROGRESS_NAME,
        progress_payload(
            manifest=manifest,
            status="complete",
            specs=specs,
            completed_specs=completed_paths,
            completed_records=completed_records,
            started_at=started_at,
            initial_records=completed_records,
        ),
    )
    print(json.dumps(completion, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
