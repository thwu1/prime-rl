#!/usr/bin/env python
"""Reproduce Interplay Figure 3 pass@k evaluation with strict graph scoring."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import inspect
import json
import math
import re
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import solution_graph
from openai import AsyncOpenAI
from solution_graph import compare_solutions

PASS_AT_DEFAULT = [1, 2, 4, 8, 16, 32, 64, 128]
ANSWER_RE = re.compile(r"<answer>\s*([-+]?\d+(?:\.\d+)?)", re.IGNORECASE)
GOLD_ANSWER_RE = re.compile(r"Answer:\s*([-+]?\d+(?:\.\d+)?)")
GENERATION_MANIFEST_NAME = "generation_manifest.json"
GENERATION_COMPLETION_NAME = "generation_completion.json"
QUARANTINE_PENDING_NAME = "generation_quarantine.pending.json"
GENERATION_BUNDLE_ARTIFACTS = (
    GENERATION_MANIFEST_NAME,
    f"{GENERATION_MANIFEST_NAME}.partial",
    GENERATION_COMPLETION_NAME,
    f"{GENERATION_COMPLETION_NAME}.partial",
    "generations.jsonl",
    "strict_results.jsonl",
    "strict_results.jsonl.partial",
    "metrics.json",
    "metrics.json.partial",
)
GENERATION_CONTRACT_SCHEMA_VERSION = 2
INFERENCE_NONSEMANTIC_FIELDS = {
    "dry_run",
    "log",
    "output_dir",
    "server",
    "slurm",
    "weight_broadcast",
}
INFERENCE_TRANSPORT_FIELDS = {
    "backend_port",
    "decode_port",
    "decode_sidecar_port",
    "host",
    "port",
    "prefill_port",
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def model_identity(model_name: str) -> dict[str, Any]:
    configured_name = str(model_name)
    candidate = Path(configured_name).expanduser()
    if not candidate.exists():
        return {
            "configured_name": configured_name,
            "resolved_path": None,
            "file_inventory_sha256": None,
        }

    resolved = candidate.resolve()
    files = [resolved] if resolved.is_file() else sorted(path for path in resolved.rglob("*") if path.is_file())
    inventory = []
    for path in files:
        stat = path.stat()
        relative = path.name if resolved.is_file() else str(path.relative_to(resolved))
        entry: dict[str, Any] = {
            "path": relative,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": file_sha256(path),
        }
        inventory.append(entry)
    return {
        "configured_name": configured_name,
        "resolved_path": str(resolved),
        "file_count": len(inventory),
        "file_inventory_sha256": canonical_json_sha256(inventory),
    }


def implementation_identity() -> dict[str, str]:
    return {
        "figure3_eval.py": file_sha256(Path(__file__)),
        "solution_graph.py": file_sha256(Path(solution_graph.__file__)),
    }


def _model_names_match(left: str, right: str) -> bool:
    left_path = Path(left).expanduser()
    right_path = Path(right).expanduser()
    if left_path.exists() and right_path.exists():
        return left_path.resolve() == right_path.resolve()
    return left == right


def _strip_transport_fields(value: Any) -> None:
    if isinstance(value, dict):
        for field in tuple(value):
            if field in INFERENCE_TRANSPORT_FIELDS or field.endswith("_port"):
                value.pop(field)
            else:
                _strip_transport_fields(value[field])
    elif isinstance(value, list):
        for item in value:
            _strip_transport_fields(item)


def normalized_inference_config(config: dict[str, Any]) -> dict[str, Any]:
    configured_path = config.get("infer_config")
    if not isinstance(configured_path, str) or not configured_path:
        raise ValueError("Figure 3 eval config must define a non-empty infer_config path")
    inference_path = Path(configured_path).expanduser().resolve()
    if not inference_path.is_file():
        raise FileNotFoundError(f"Inference config does not exist: {inference_path}")
    with inference_path.open("rb") as handle:
        inference = tomllib.load(handle)

    model = inference.get("model")
    if not isinstance(model, dict):
        raise ValueError(f"Inference config has no [model] table: {inference_path}")
    inference_model = model.get("name")
    eval_model = config["eval"].get("model")
    if not isinstance(inference_model, str) or not isinstance(eval_model, str):
        raise ValueError("Eval and inference model names must be non-empty strings")
    if not _model_names_match(inference_model, eval_model):
        raise ValueError(
            f"Eval and inference configs reference different models: {eval_model!r} != {inference_model!r}"
        )

    normalized = copy.deepcopy(inference)
    for field in INFERENCE_NONSEMANTIC_FIELDS:
        normalized.pop(field, None)
    normalized_model = normalized["model"]
    normalized_model.pop("name", None)
    _strip_transport_fields(normalized)
    return normalized


def inference_generation_identity(config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalized_inference_config(config)
    return {
        "normalization": "prime-rl-inference-generation-v1",
        "normalized_config": normalized,
        "normalized_config_sha256": canonical_json_sha256(normalized),
    }


def generator_implementation_sha256() -> str:
    functions = (load_rows, compose_prompt, derive_request_seed, generate_one, generate)
    source = "\n\n".join(inspect.getsource(function) for function in functions)
    return hashlib.sha256(source.encode()).hexdigest()


def build_generation_manifest(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    hashes: dict[str, str],
) -> dict[str, Any]:
    eval_config = config["eval"]
    expected = int(eval_config["examples_per_operation"])
    data_dirs = data_dirs_by_operation(eval_config)
    datasets = [
        {
            "op": int(operation),
            "path": str((data_dirs[int(operation)] / f"op{operation}-{expected}.jsonl").expanduser().resolve()),
            "sha256": hashes[str(operation)],
        }
        for operation in eval_config["operations"]
    ]
    prompts = [
        {
            "op": int(row["op"]),
            "__idx": int(row["__idx"]),
            "id": str(row["id"]),
            "prompt_sha256": hashlib.sha256(compose_prompt(row).encode()).hexdigest(),
        }
        for row in rows
    ]
    sampling_fields = (
        "samples_per_prompt",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stop",
        "skip_special_tokens",
        "request_seed",
    )
    contract = {
        "model": model_identity(str(eval_config["model"])),
        "inference": inference_generation_identity(config),
        "datasets": datasets,
        "prompts": prompts,
        "prompt_sequence_sha256": canonical_json_sha256(prompts),
        "sampling": {
            **{field: eval_config.get(field) for field in sampling_fields},
            "request_seed_derivation": "sha256-v1(base_seed,op,id,row_index,sample_rank)",
        },
        "generator_implementation_sha256": generator_implementation_sha256(),
        "evaluator_scorer_implementation_sha256": implementation_identity(),
    }
    return {
        "schema_version": GENERATION_CONTRACT_SCHEMA_VERSION,
        "contract_sha256": canonical_json_sha256(contract),
        "contract": contract,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    eval_config = config["eval"]
    required = {
        "operations",
        "examples_per_operation",
        "output_dir",
        "model",
        "api_base_url",
        "samples_per_prompt",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stop",
        "skip_special_tokens",
        "request_timeout_seconds",
        "max_concurrent_prompts",
    }
    missing = sorted(required - eval_config.keys())
    if missing:
        raise ValueError(f"Missing Figure 3 eval config fields: {missing}")
    data_dirs_by_operation(eval_config)
    if eval_config["samples_per_prompt"] < 1:
        raise ValueError("eval.samples_per_prompt must be positive")
    if eval_config["max_tokens"] < 1:
        raise ValueError("eval.max_tokens must be positive")
    if eval_config["max_concurrent_prompts"] < 1:
        raise ValueError("eval.max_concurrent_prompts must be positive")
    request_seed = eval_config.get("request_seed")
    if request_seed is not None and (
        isinstance(request_seed, bool) or not isinstance(request_seed, int) or not 0 <= request_seed < 2**63
    ):
        raise ValueError("eval.request_seed must be an integer in [0, 2^63)")
    prompt_limit = eval_config.get("prompt_limit_per_operation")
    if prompt_limit is not None and not 1 <= int(prompt_limit) <= int(eval_config["examples_per_operation"]):
        raise ValueError("eval.prompt_limit_per_operation must be in [1, examples_per_operation]")
    pass_at = eval_config.get("pass_at", PASS_AT_DEFAULT)
    if any(k < 1 or k > eval_config["samples_per_prompt"] for k in pass_at):
        raise ValueError("Every eval.pass_at value must be in [1, samples_per_prompt]")
    operation_weights = eval_config.get("operation_weights")
    if operation_weights is not None:
        if len(operation_weights) != len(eval_config["operations"]):
            raise ValueError("eval.operation_weights must align with eval.operations")
        if any(weight <= 0 for weight in operation_weights):
            raise ValueError("eval.operation_weights values must be positive")
    normalized_inference_config(config)
    return config


def data_dirs_by_operation(eval_config: dict[str, Any]) -> dict[int, Path]:
    has_data_dir = "data_dir" in eval_config
    has_data_sources = "data_sources" in eval_config
    if has_data_dir == has_data_sources:
        raise ValueError("Configure exactly one of eval.data_dir or eval.data_sources")

    operations = [int(operation) for operation in eval_config["operations"]]
    if has_data_dir:
        data_dir = Path(eval_config["data_dir"])
        return {operation: data_dir for operation in operations}

    sources = eval_config["data_sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("eval.data_sources must be a non-empty list")

    ranges: list[tuple[int, int, Path]] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"eval.data_sources[{index}] must be a table")
        missing = sorted({"min_op", "max_op", "data_dir"} - source.keys())
        if missing:
            raise ValueError(f"eval.data_sources[{index}] is missing fields: {missing}")
        min_op = int(source["min_op"])
        max_op = int(source["max_op"])
        if min_op > max_op:
            raise ValueError(f"eval.data_sources[{index}] has min_op > max_op")
        ranges.append((min_op, max_op, Path(source["data_dir"])))

    ranges.sort(key=lambda item: (item[0], item[1]))
    for previous, current in zip(ranges, ranges[1:], strict=False):
        if current[0] <= previous[1]:
            raise ValueError(
                "eval.data_sources operation ranges overlap: "
                f"[{previous[0]}, {previous[1]}] and [{current[0]}, {current[1]}]"
            )

    resolved: dict[int, Path] = {}
    for operation in operations:
        matches = [data_dir for min_op, max_op, data_dir in ranges if min_op <= operation <= max_op]
        if not matches:
            raise ValueError(f"eval.data_sources do not cover configured operation {operation}")
        resolved[operation] = matches[0]
    return resolved


def compose_prompt(row: dict[str, Any]) -> str:
    problem = str(row["problem"]).strip()
    question = str(row["question"]).strip()
    return f"<question> {problem} {question} </question> <solution>"


def derive_request_seed(row: dict[str, Any], base_seed: int, sample_rank: int = 0) -> int:
    identity = f"{base_seed}:{row['op']}:{row['id']}:{row['__idx']}:{sample_rank}".encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % (2**63 - 1)


def load_rows(eval_config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    data_dirs = data_dirs_by_operation(eval_config)
    expected = int(eval_config["examples_per_operation"])
    rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for operation in eval_config["operations"]:
        path = data_dirs[int(operation)] / f"op{operation}-{expected}.jsonl"
        raw = path.read_bytes()
        hashes[str(operation)] = hashlib.sha256(raw).hexdigest()
        operation_rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        if len(operation_rows) != expected:
            raise ValueError(f"Expected {expected} rows in {path}, found {len(operation_rows)}")
        if "prompt_limit_per_operation" in eval_config:
            operation_rows = operation_rows[: int(eval_config["prompt_limit_per_operation"])]
        for index, row in enumerate(operation_rows):
            required = {"problem", "question", "solution", "op", "id", "template"}
            missing = sorted(required - row.keys())
            if missing:
                raise ValueError(f"{path} row {index} is missing fields: {missing}")
            if int(row["op"]) != int(operation):
                raise ValueError(f"{path} row {index} has op={row['op']}")
            row["__idx"] = index
            rows.append(row)
    keys = [(str(row["op"]), int(row["__idx"])) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Evaluation rows contain duplicate (op, row-index) keys")
    return rows, hashes


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def verify_generation_manifest(path: Path, expected: dict[str, Any]) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Generation resume manifest does not exist: {path}")
    observed = load_json_object(path)
    if canonical_json_sha256(observed) != canonical_json_sha256(expected):
        raise ValueError(
            "Generation resume manifest mismatch: "
            f"observed contract={observed.get('contract_sha256')!r}, "
            f"expected contract={expected['contract_sha256']!r}"
        )


def read_generation_records(
    path: Path,
    rows: list[dict[str, Any]],
    samples_per_prompt: int,
    *,
    require_complete: bool,
) -> tuple[list[dict[str, Any]], dict[tuple[str, int], set[int]]]:
    gold = {(str(row["op"]), int(row["__idx"])): row for row in rows}
    completed: dict[tuple[str, int], set[int]] = defaultdict(set)
    if not path.exists():
        if require_complete:
            raise FileNotFoundError(f"Generation file does not exist: {path}")
        return [], completed

    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"Generation record is not an object on {path}:{line_number}")
        required = {"op", "id", "__idx", "sample_rank", "gen_solution_answer"}
        missing = sorted(required - record.keys())
        if missing:
            raise ValueError(f"Generation record on {path}:{line_number} is missing fields: {missing}")
        for field in ("op", "__idx", "sample_rank"):
            if isinstance(record[field], bool) or not isinstance(record[field], int):
                raise ValueError(f"Generation {field} must be an integer on {path}:{line_number}")
        if not isinstance(record["id"], str):
            raise ValueError(f"Generation id must be a string on {path}:{line_number}")
        key = (str(record["op"]), record["__idx"])
        if key not in gold:
            raise ValueError(f"Unknown prompt key on {path}:{line_number}: {key}")
        expected_id = str(gold[key]["id"])
        if record["id"] != expected_id:
            raise ValueError(
                f"Generation id mismatch on {path}:{line_number} for {key}: "
                f"observed {record['id']!r}, expected {expected_id!r}"
            )
        rank = record["sample_rank"]
        if not 0 <= rank < samples_per_prompt:
            raise ValueError(f"Invalid sample rank on {path}:{line_number}: {rank}")
        if rank in completed[key]:
            raise ValueError(f"Duplicate sample rank for {key} on {path}:{line_number}: {rank}")
        completed[key].add(rank)
        records.append(record)

    if require_complete:
        expected_keys = set(gold)
        if set(completed) != expected_keys:
            missing_keys = sorted(expected_keys - completed.keys())[:10]
            raise ValueError(f"Generations are missing prompts; first missing keys: {missing_keys}")
        incomplete = {key: len(ranks) for key, ranks in completed.items() if len(ranks) != samples_per_prompt}
        if incomplete:
            raise ValueError(f"Prompts do not have {samples_per_prompt} samples: {dict(list(incomplete.items())[:10])}")
    records.sort(key=lambda record: (int(record["op"]), int(record["__idx"]), int(record["sample_rank"])))
    return records, completed


def load_existing(
    path: Path,
    rows: list[dict[str, Any]],
    samples_per_prompt: int,
) -> dict[tuple[str, int], set[int]]:
    _, completed = read_generation_records(
        path,
        rows,
        samples_per_prompt,
        require_complete=False,
    )
    return completed


def canonical_generation_content(
    path: Path,
    rows: list[dict[str, Any]],
    samples_per_prompt: int,
) -> tuple[str, list[dict[str, Any]]]:
    records, _ = read_generation_records(
        path,
        rows,
        samples_per_prompt,
        require_complete=True,
    )
    return canonical_json_sha256(records), records


def generation_completion_payload(
    output_dir: Path,
    manifest: dict[str, Any],
    canonical_generation_sha256: str,
    num_generations: int,
) -> dict[str, Any]:
    manifest_path = output_dir / GENERATION_MANIFEST_NAME
    return {
        "schema_version": 1,
        "contract_sha256": manifest["contract_sha256"],
        "generation_manifest_sha256": file_sha256(manifest_path),
        "generations_jsonl_sha256": file_sha256(output_dir / "generations.jsonl"),
        "canonical_generation_sha256": canonical_generation_sha256,
        "num_generations": num_generations,
    }


def verify_generation_completion(
    output_dir: Path,
    manifest: dict[str, Any],
    canonical_generation_sha256: str,
    num_generations: int,
) -> dict[str, Any]:
    completion_path = output_dir / GENERATION_COMPLETION_NAME
    if not completion_path.is_file():
        raise FileNotFoundError(f"Generation completion manifest does not exist: {completion_path}")
    expected = generation_completion_payload(
        output_dir,
        manifest,
        canonical_generation_sha256,
        num_generations,
    )
    observed = load_json_object(completion_path)
    if canonical_json_sha256(observed) != canonical_json_sha256(expected):
        raise ValueError(f"Generation completion manifest mismatch: {completion_path}")
    return expected


def verify_or_write_generation_completion(
    output_dir: Path,
    manifest: dict[str, Any],
    canonical_generation_sha256: str,
    num_generations: int,
) -> dict[str, Any]:
    completion_path = output_dir / GENERATION_COMPLETION_NAME
    expected = generation_completion_payload(
        output_dir,
        manifest,
        canonical_generation_sha256,
        num_generations,
    )
    if completion_path.is_file():
        return verify_generation_completion(
            output_dir,
            manifest,
            canonical_generation_sha256,
            num_generations,
        )
    else:
        write_json_atomic(completion_path, expected)
    return expected


def finish_pending_generation_quarantine(output_dir: Path) -> Path | None:
    pending_path = output_dir / QUARANTINE_PENDING_NAME
    if not pending_path.is_file():
        return None
    pending = load_json_object(pending_path)
    bundle_name = pending.get("bundle_name")
    artifacts = pending.get("artifact_sha256")
    if (
        pending.get("schema_version") != 1
        or not isinstance(bundle_name, str)
        or re.fullmatch(r"generation_bundle_[0-9a-f]{64}", bundle_name) is None
        or not isinstance(artifacts, dict)
        or not artifacts
    ):
        raise ValueError(f"Invalid pending generation quarantine: {pending_path}")
    if not set(artifacts).issubset(GENERATION_BUNDLE_ARTIFACTS):
        raise ValueError(f"Pending generation quarantine contains unknown artifacts: {pending_path}")

    target_dir = output_dir / "quarantine" / bundle_name
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, expected_sha256 in artifacts.items():
        if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
            raise ValueError(f"Invalid artifact hash for {name!r} in {pending_path}")
        source = output_dir / name
        target = target_dir / name
        if source.is_file():
            if file_sha256(source) != expected_sha256:
                raise ValueError(f"Generation artifact changed during quarantine: {source}")
            if target.is_file():
                if file_sha256(target) != expected_sha256:
                    raise FileExistsError(f"Conflicting quarantine artifact: {target}")
                source.unlink()
            else:
                source.replace(target)
        elif not target.is_file() or file_sha256(target) != expected_sha256:
            raise FileNotFoundError(f"Generation quarantine lost artifact: {name}")

    metadata_path = target_dir / "quarantine.json"
    if metadata_path.is_file():
        if canonical_json_sha256(load_json_object(metadata_path)) != canonical_json_sha256(pending):
            raise ValueError(f"Generation quarantine metadata mismatch: {metadata_path}")
    else:
        write_json_atomic(metadata_path, pending)
    pending_path.unlink()
    return target_dir


def quarantine_generation_bundle(
    output_dir: Path,
    expected_manifest: dict[str, Any],
    reason: str,
) -> Path:
    finish_pending_generation_quarantine(output_dir)
    artifacts = {
        name: file_sha256(output_dir / name) for name in GENERATION_BUNDLE_ARTIFACTS if (output_dir / name).is_file()
    }
    if not artifacts:
        raise FileNotFoundError(f"No stale generation artifacts to quarantine in {output_dir}")
    identity = {
        "artifact_sha256": artifacts,
        "expected_contract_sha256": expected_manifest["contract_sha256"],
        "reason": reason,
    }
    bundle_name = f"generation_bundle_{canonical_json_sha256(identity)}"
    pending = {
        "schema_version": 1,
        "bundle_name": bundle_name,
        **identity,
    }
    write_json_atomic(output_dir / QUARANTINE_PENDING_NAME, pending)
    target = finish_pending_generation_quarantine(output_dir)
    if target is None:
        raise RuntimeError("Generation quarantine did not produce a target directory")
    return target


def prepare_generation_resume(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    hashes: dict[str, str],
) -> dict[tuple[str, int], set[int]]:
    eval_config = config["eval"]
    output_dir = Path(eval_config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    finish_pending_generation_quarantine(output_dir)
    manifest_path = output_dir / GENERATION_MANIFEST_NAME
    generations_path = output_dir / "generations.jsonl"
    metrics_path = output_dir / "metrics.json"
    expected_manifest = build_generation_manifest(config, rows, hashes)

    if eval_config.get("overwrite", False):
        for name in GENERATION_BUNDLE_ARTIFACTS:
            (output_dir / name).unlink(missing_ok=True)
        (output_dir / f"{QUARANTINE_PENDING_NAME}.partial").unlink(missing_ok=True)
        write_json_atomic(manifest_path, expected_manifest)
        return defaultdict(set)
    if metrics_path.exists():
        raise FileExistsError(f"Completed evaluation already exists: {metrics_path}")

    root_artifacts = [name for name in GENERATION_BUNDLE_ARTIFACTS if (output_dir / name).is_file()]
    if not manifest_path.is_file():
        if root_artifacts:
            quarantine_generation_bundle(output_dir, expected_manifest, "generation resume manifest is missing")
        write_json_atomic(manifest_path, expected_manifest)
        return defaultdict(set)

    try:
        verify_generation_manifest(manifest_path, expected_manifest)
        completed = load_existing(generations_path, rows, int(eval_config["samples_per_prompt"]))
        completion_path = output_dir / GENERATION_COMPLETION_NAME
        if completion_path.is_file():
            digest, records = canonical_generation_content(
                generations_path,
                rows,
                int(eval_config["samples_per_prompt"]),
            )
            verify_or_write_generation_completion(output_dir, expected_manifest, digest, len(records))
    except (OSError, ValueError) as error:
        target = quarantine_generation_bundle(output_dir, expected_manifest, f"{type(error).__name__}: {error}")
        print(f"quarantined stale generation bundle at {target}", flush=True)
        write_json_atomic(manifest_path, expected_manifest)
        return defaultdict(set)
    return completed


async def generate_one(
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    row: dict[str, Any],
    missing_ranks: list[int],
    eval_config: dict[str, Any],
) -> list[dict[str, Any]]:
    records = []
    async with semaphore:
        for rank in missing_ranks:
            seeded_request: dict[str, int] = {}
            if "request_seed" in eval_config:
                seeded_request["seed"] = derive_request_seed(row, int(eval_config["request_seed"]), rank)
            response = await client.completions.create(
                model=eval_config["model"],
                prompt=compose_prompt(row),
                n=1,
                max_tokens=eval_config["max_tokens"],
                temperature=eval_config["temperature"],
                top_p=eval_config["top_p"],
                stop=eval_config["stop"],
                extra_body={
                    "skip_special_tokens": eval_config["skip_special_tokens"],
                    "top_k": eval_config["top_k"],
                },
                **seeded_request,
            )
            if len(response.choices) != 1:
                raise RuntimeError(
                    f"Server returned {len(response.choices)} samples for op={row['op']} "
                    f"id={row['id']} rank={rank}; expected 1"
                )
            choice = response.choices[0]
            records.append(
                {
                    "op": int(row["op"]),
                    "id": str(row["id"]),
                    "__idx": int(row["__idx"]),
                    "template": row["template"],
                    "mode": row.get("mode"),
                    "sample_rank": rank,
                    "finish_reason": choice.finish_reason,
                    "gen_solution_answer": choice.text.strip(),
                }
            )
    return records


async def generate(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    hashes: dict[str, str],
) -> None:
    eval_config = config["eval"]
    output_dir = Path(eval_config["output_dir"])
    generations_path = output_dir / "generations.jsonl"

    samples_per_prompt = int(eval_config["samples_per_prompt"])
    completed = prepare_generation_resume(config, rows, hashes)
    pending: list[tuple[dict[str, Any], list[int]]] = []
    all_ranks = set(range(samples_per_prompt))
    for row in rows:
        key = (str(row["op"]), int(row["__idx"]))
        missing_ranks = sorted(all_ranks - completed[key])
        if missing_ranks:
            pending.append((row, missing_ranks))
    if not pending:
        return

    client = AsyncOpenAI(
        base_url=eval_config["api_base_url"],
        api_key="unused",
        timeout=float(eval_config["request_timeout_seconds"]),
        max_retries=int(eval_config.get("max_retries", 2)),
    )
    semaphore = asyncio.Semaphore(int(eval_config["max_concurrent_prompts"]))
    tasks = [generate_one(client, semaphore, row, ranks, eval_config) for row, ranks in pending]
    mode = "a" if generations_path.exists() else "w"
    completed_prompts = len(rows) - len(pending)
    with generations_path.open(mode, encoding="utf-8") as handle:
        for task in asyncio.as_completed(tasks):
            records = await task
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            completed_prompts += 1
            if completed_prompts % 10 == 0 or completed_prompts == len(rows):
                print(f"generated {completed_prompts}/{len(rows)} prompts", flush=True)
    await client.close()


def extract_answer(text: str, pattern: re.Pattern[str]) -> float | None:
    match = pattern.search(text)
    return float(match.group(1)) if match else None


def strict_result_record(gold: dict[str, Any], generation: dict[str, Any]) -> dict[str, Any]:
    prediction = str(generation["gen_solution_answer"])
    report = compare_solutions(str(gold["solution"]), prediction)
    gold_answer = extract_answer(str(gold["solution"]), GOLD_ANSWER_RE)
    predicted_answer = extract_answer(prediction, ANSWER_RE)
    return {
        "op": int(generation["op"]),
        "id": str(generation["id"]),
        "__idx": int(generation["__idx"]),
        "template": generation.get("template"),
        "sample_rank": int(generation["sample_rank"]),
        "finish_reason": str(generation.get("finish_reason") or "unknown"),
        "perfect": bool(report["perfect"]),
        "answer_correct": gold_answer is not None and predicted_answer == gold_answer,
        "value_mismatch_count": len(report["value_mismatches"]),
        "dependency_mismatch_count": len(report["dependency_mismatches"]),
        "answer_mismatch": report["answer_mismatch"] is not None,
        "extra_nodes": len(report["extra_in_pred"]),
        "missing_nodes": len(report["missing_in_pred"]),
    }


def deterministic_strict_results(
    rows: list[dict[str, Any]],
    generation_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gold = {(str(row["op"]), int(row["__idx"])): row for row in rows}
    seen: set[tuple[str, int, int]] = set()
    results = []
    for generation in generation_records:
        prompt_key = (str(generation["op"]), int(generation["__idx"]))
        if prompt_key not in gold:
            raise ValueError(f"Unknown generation prompt key during strict rescoring: {prompt_key}")
        expected_id = str(gold[prompt_key]["id"])
        if str(generation["id"]) != expected_id:
            raise ValueError(
                f"Generation id mismatch during strict rescoring for {prompt_key}: "
                f"observed {generation['id']!r}, expected {expected_id!r}"
            )
        key = (*prompt_key, int(generation["sample_rank"]))
        if key in seen:
            raise ValueError(f"Duplicate generation during strict rescoring: {key}")
        seen.add(key)
        results.append(strict_result_record(gold[prompt_key], generation))
    return results


def verify_strict_results(
    path: Path,
    rows: list[dict[str, Any]],
    generation_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Strict result file does not exist: {path}")
    observed = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"Blank strict result record on {path}:{line_number}")
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"Strict result is not an object on {path}:{line_number}")
        observed.append(record)
    expected = deterministic_strict_results(rows, generation_records)
    if canonical_json_sha256(observed) != canonical_json_sha256(expected):
        mismatch = next(
            (
                index
                for index, (observed_record, expected_record) in enumerate(zip(observed, expected, strict=False))
                if canonical_json_sha256(observed_record) != canonical_json_sha256(expected_record)
            ),
            min(len(observed), len(expected)),
        )
        raise ValueError(
            f"Strict results do not match deterministic rescoring at record {mismatch}: "
            f"observed_count={len(observed)}, expected_count={len(expected)}"
        )
    return expected


def pass_at_k_unbiased(num_samples: int, num_correct: int, k: int) -> float:
    if num_correct == 0:
        return 0.0
    if num_samples - num_correct < k:
        return 1.0
    return 1.0 - math.comb(num_samples - num_correct, k) / math.comb(num_samples, k)


def aggregate_pass_at_k(
    outcomes: dict[tuple[str, int], dict[int, bool]],
    pass_at: list[int],
    operation_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    per_op: dict[str, dict[tuple[str, int], dict[int, bool]]] = defaultdict(dict)
    for key, ranks in outcomes.items():
        per_op[key[0]][key] = ranks

    def summarize(
        prompts: dict[tuple[str, int], dict[int, bool]],
        prompt_weights: dict[tuple[str, int], float] | None = None,
    ) -> dict[str, dict[str, float]]:
        weights = prompt_weights or {key: 1.0 for key in prompts}
        denominator = sum(weights.values())
        empirical: dict[str, float] = {}
        unbiased: dict[str, float] = {}
        for k in pass_at:
            empirical[f"pass@{k}"] = (
                sum(
                    weights[key] * any(correct for rank, correct in ranks.items() if rank < k)
                    for key, ranks in prompts.items()
                )
                / denominator
            )
            unbiased[f"pass@{k}"] = (
                sum(
                    weights[key] * pass_at_k_unbiased(len(ranks), sum(ranks.values()), k)
                    for key, ranks in prompts.items()
                )
                / denominator
            )
        return {"empirical": empirical, "unbiased": unbiased}

    result = {
        "total": summarize(outcomes),
        "per_op": {op: summarize(prompts) for op, prompts in sorted(per_op.items(), key=lambda item: int(item[0]))},
    }
    if operation_weights is not None:
        prompt_weights = {key: operation_weights[key[0]] / len(per_op[key[0]]) for key in outcomes}
        result["weighted_total"] = summarize(outcomes, prompt_weights)
        result["operation_weights"] = operation_weights
    return result


def score(config: dict[str, Any], rows: list[dict[str, Any]], hashes: dict[str, str]) -> dict[str, Any]:
    eval_config = config["eval"]
    output_dir = Path(eval_config["output_dir"])
    generations_path = output_dir / "generations.jsonl"
    strict_path = output_dir / "strict_results.jsonl"
    metrics_path = output_dir / "metrics.json"
    gold = {(str(row["op"]), int(row["__idx"])): row for row in rows}
    samples_per_prompt = int(eval_config["samples_per_prompt"])
    manifest = build_generation_manifest(config, rows, hashes)
    verify_generation_manifest(output_dir / GENERATION_MANIFEST_NAME, manifest)
    generation_digest, generation_records = canonical_generation_content(
        generations_path,
        rows,
        samples_per_prompt,
    )
    generation_completion = verify_or_write_generation_completion(
        output_dir,
        manifest,
        generation_digest,
        len(generation_records),
    )
    strict_outcomes: dict[tuple[str, int], dict[int, bool]] = defaultdict(dict)
    answer_outcomes: dict[tuple[str, int], dict[int, bool]] = defaultdict(dict)
    finish_reasons: Counter[str] = Counter()
    finish_reasons_by_op: dict[str, Counter[str]] = defaultdict(Counter)
    parse_failures = 0

    strict_records = deterministic_strict_results(rows, generation_records)
    strict_partial = strict_path.with_suffix(".jsonl.partial")
    with strict_partial.open("w", encoding="utf-8") as output:
        for record, strict_record in zip(generation_records, strict_records, strict=True):
            key = (str(record["op"]), int(record["__idx"]))
            rank = int(record["sample_rank"])
            if rank in strict_outcomes[key]:
                raise ValueError(f"Duplicate sample rank for {key}: {rank}")
            prediction = str(record["gen_solution_answer"])
            predicted_answer = extract_answer(prediction, ANSWER_RE)
            finish_reason = strict_record["finish_reason"]
            strict_outcomes[key][rank] = strict_record["perfect"]
            answer_outcomes[key][rank] = strict_record["answer_correct"]
            finish_reasons[finish_reason] += 1
            finish_reasons_by_op[key[0]][finish_reason] += 1
            if predicted_answer is None:
                parse_failures += 1
            output.write(json.dumps(strict_record, sort_keys=True) + "\n")

    expected_keys = set(gold)
    if set(strict_outcomes) != expected_keys:
        missing = sorted(expected_keys - strict_outcomes.keys())[:10]
        raise ValueError(f"Generations are missing prompts; first missing keys: {missing}")
    incomplete = {key: len(ranks) for key, ranks in strict_outcomes.items() if len(ranks) != samples_per_prompt}
    if incomplete:
        raise ValueError(f"Prompts do not have {samples_per_prompt} samples: {dict(list(incomplete.items())[:10])}")

    pass_at = [int(k) for k in eval_config.get("pass_at", PASS_AT_DEFAULT)]
    operation_weights = None
    if "operation_weights" in eval_config:
        operation_weights = {
            str(operation): float(weight)
            for operation, weight in zip(eval_config["operations"], eval_config["operation_weights"], strict=True)
        }
    dataset_source = (
        {"data_dir": eval_config["data_dir"]}
        if "data_dir" in eval_config
        else {"data_sources": eval_config["data_sources"]}
    )
    scorer_identity = implementation_identity()
    if manifest["contract"]["evaluator_scorer_implementation_sha256"] != scorer_identity:
        raise RuntimeError("Evaluator/scorer implementation changed during strict scoring")
    metrics = {
        "model": eval_config["model"],
        **dataset_source,
        "dataset_sha256_by_op": hashes,
        "operations": [int(op) for op in eval_config["operations"]],
        "num_prompts": len(rows),
        "samples_per_prompt": samples_per_prompt,
        "num_generations": len(rows) * samples_per_prompt,
        "strict_graph": aggregate_pass_at_k(strict_outcomes, pass_at, operation_weights),
        "answer_only": aggregate_pass_at_k(answer_outcomes, pass_at, operation_weights),
        "diagnostics": {
            "unparsed_predictions": parse_failures,
            "finish_reason_counts": dict(sorted(finish_reasons.items())),
            "finish_reason_counts_by_op": {
                op: dict(sorted(counts.items()))
                for op, counts in sorted(finish_reasons_by_op.items(), key=lambda item: int(item[0]))
            },
        },
        "sampling": {
            "temperature": eval_config["temperature"],
            "top_p": eval_config["top_p"],
            "top_k": eval_config["top_k"],
            "max_tokens": eval_config["max_tokens"],
            "stop": eval_config["stop"],
            "skip_special_tokens": eval_config["skip_special_tokens"],
            "request_seed": eval_config.get("request_seed"),
        },
        "generation_provenance": {
            **generation_completion,
            "generation_manifest": GENERATION_MANIFEST_NAME,
            "generation_completion": GENERATION_COMPLETION_NAME,
        },
        "strict_scoring_provenance": {
            "implementation_sha256": scorer_identity,
            "strict_results_sha256": file_sha256(strict_partial),
            "num_results": len(strict_records),
        },
        "implementation_sha256": scorer_identity,
    }
    metrics_partial = metrics_path.with_suffix(".json.partial")
    metrics_partial.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    strict_partial.replace(strict_path)
    metrics_partial.replace(metrics_path)
    return metrics


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    rows, hashes = load_rows(config["eval"])
    if args.validate_only:
        print(json.dumps({"config": str(args.config), "operations": config["eval"]["operations"], "rows": len(rows)}))
        return
    if not args.score_only:
        asyncio.run(generate(config, rows, hashes))
    print(json.dumps(score(config, rows, hashes), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
