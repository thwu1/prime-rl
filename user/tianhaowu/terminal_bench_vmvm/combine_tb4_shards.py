#!/usr/bin/env python3
"""Validate and atomically combine the two fixed direct-worker TB4 shards."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import tomllib
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from audit_tb4_results import (
    DEFAULT_MAX_SEQUENCE_TOKENS,
    EXPECTED_TASK_COUNT,
    EXPECTED_UNSUPPORTED_TASKS,
    TB4AuditError,
    audit_results,
)
from audit_traces import TraceJSONLError, _task_slug

WORKFLOW_DIR = Path(__file__).resolve().parent
CONFIG_DIR = WORKFLOW_DIR / "configs" / "eval"
FORBIDDEN_REQUEST_FIELDS = frozenset({"logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"})
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ShardSpec:
    name: str
    endpoint: str
    config: Path
    task_file: Path
    task_file_sha256: str


SHARD_SPECS = (
    ShardSpec(
        name="a",
        endpoint="http://g3-138-137:32317/v1",
        config=CONFIG_DIR / "tb4_kimi_k3_direct_a.toml",
        task_file=CONFIG_DIR / "tb4_kimi_k3_direct_a.tasks.txt",
        task_file_sha256="d0f7c0297a82edf79f3e966ffd830fb418ea90c9faa7c4f3d288d5c7bacd1365",
    ),
    ShardSpec(
        name="b",
        endpoint="http://g3-146-243:32499/v1",
        config=CONFIG_DIR / "tb4_kimi_k3_direct_b.toml",
        task_file=CONFIG_DIR / "tb4_kimi_k3_direct_b.tasks.txt",
        task_file_sha256="485c1a038efc72a4eddf4928758c74d31827ebb7624108cee63e503df0fa02ec",
    ),
)


class CombineError(ValueError):
    """A shard is incomplete, inconsistent, or not the declared direct-worker run."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_tasks(path: Path) -> list[str]:
    tasks = [
        line.strip().split("\t", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(tasks) != len(set(tasks)):
        raise CombineError(f"{path}: duplicate task slugs")
    return tasks


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CombineError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise CombineError(f"{path}: expected a JSON object")
    return value


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CombineError(f"cannot read TOML {path}: {error}") from error


def _normalize_url(value: object) -> str:
    return str(value).rstrip("/")


def _validate_config(
    config: dict,
    spec: ShardSpec,
    *,
    task_file: Path | None,
    dataset_dir: Path,
) -> None:
    problems: list[str] = []
    expected_scalars = {
        "model": "Kimi-K3",
        "num_tasks": 33,
        "num_rollouts": 1,
        "max_concurrent": 16,
        "multiplex": 16,
        "max_input_tokens": 262144,
        "max_output_tokens": 262144,
        "max_total_tokens": 262144,
    }
    for key, expected in expected_scalars.items():
        if config.get(key) != expected:
            problems.append(f"{key}={config.get(key)!r} expected={expected!r}")

    client = config.get("client")
    if not isinstance(client, dict):
        problems.append("client_missing")
    else:
        if client.get("type") != "eval":
            problems.append("client.type_not_eval")
        if _normalize_url(client.get("base_url")) != spec.endpoint:
            problems.append("client.base_url_mismatch")
        if client.get("capture_model_io") is not True:
            problems.append("client.capture_model_io_not_true")
        if set(client.get("outbound_body_denylist") or []) != FORBIDDEN_REQUEST_FIELDS:
            problems.append("client.outbound_body_denylist_mismatch")
        if client.get("max_connections") != 16:
            problems.append("client.max_connections_not_16")
        if client.get("max_keepalive_connections") != 16:
            problems.append("client.max_keepalive_connections_not_16")

    sampling = config.get("sampling")
    if not isinstance(sampling, dict):
        problems.append("sampling_missing")
    elif FORBIDDEN_REQUEST_FIELDS.intersection(sampling):
        problems.append("sampling_requests_forbidden_token_metadata")

    taskset = config.get("taskset")
    if not isinstance(taskset, dict):
        problems.append("taskset_missing")
    else:
        if taskset.get("id") != "terminal-bench-vmvm":
            problems.append("taskset.id_mismatch")
        configured_dataset = Path(str(taskset.get("dataset_dir", ""))).resolve()
        if configured_dataset != dataset_dir:
            problems.append("taskset.dataset_dir_mismatch")
        if taskset.get("task_file_sha256") != spec.task_file_sha256:
            problems.append("taskset.task_file_sha256_mismatch")
        configured_task_file = taskset.get("task_file")
        if task_file is None:
            expected_task_file = str(spec.task_file.relative_to(WORKFLOW_DIR.parents[2]))
            if configured_task_file != expected_task_file:
                problems.append("taskset.source_task_file_mismatch")
        elif Path(str(configured_task_file)).resolve() != task_file:
            problems.append("taskset.snapshot_task_file_mismatch")

    harness = config.get("harness")
    if not isinstance(harness, dict):
        problems.append("harness_missing")
    else:
        env = harness.get("env")
        if not isinstance(env, dict) or env.get("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT") != "10":
            problems.append("harness_model_retry_policy_mismatch")

    retry = config.get("retries")
    rollout = retry.get("rollout") if isinstance(retry, dict) else None
    if not isinstance(rollout, dict):
        problems.append("rollout_retries_missing")
    elif rollout.get("max_retries") != 2 or set(rollout.get("include") or []) != {
        "ProviderError",
        "SandboxError",
        "TunnelError",
    }:
        problems.append("rollout_retries_mismatch")

    if problems:
        raise CombineError(f"{spec.name} config invalid: {', '.join(problems)}")


def _validate_snapshot_record(
    manifest: dict,
    name: str,
    expected_path: Path,
    *,
    expected_source: Path,
) -> str:
    record = manifest.get(name)
    if not isinstance(record, dict):
        raise CombineError(f"input manifest has no {name!r} record")
    snapshot = Path(str(record.get("snapshot", ""))).resolve()
    if snapshot != expected_path:
        raise CombineError(f"input manifest {name!r} snapshot mismatch: {snapshot} != {expected_path}")
    source = Path(str(record.get("source", ""))).resolve()
    if source != expected_source.resolve():
        raise CombineError(f"input manifest {name!r} source mismatch: {source} != {expected_source.resolve()}")
    observed = _sha256(expected_path)
    if record.get("sha256") != observed:
        raise CombineError(f"input manifest {name!r} SHA-256 mismatch")
    return observed


def _read_provenance(path: Path, expected_endpoint: str) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise CombineError(f"cannot read provenance {path}: {error}") from error
    lowered = "\n".join(lines).casefold()
    if any(secret in lowered for secret in ("api_key", "authorization", "bearer ")):
        raise CombineError(f"{path}: provenance appears to contain a credential")
    values: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key:
            raise CombineError(f"{path}: malformed provenance line")
        if key in values and key != "resume_slurm_job_id":
            raise CombineError(f"{path}: duplicate provenance key {key!r}")
        values[key] = value
    for key in ("prime_rl", "verifiers", "renderers"):
        if not COMMIT_RE.fullmatch(values.get(key, "")):
            raise CombineError(f"{path}: invalid or missing {key} commit")
    if _normalize_url(values.get("inference_base_url")) != expected_endpoint:
        raise CombineError(f"{path}: inference_base_url does not match the shard endpoint")
    if not values.get("slurm_job_id", "").isdigit():
        raise CombineError(f"{path}: invalid or missing slurm_job_id")
    return values


@contextmanager
def _hold_writer_lock(shard_dir: Path) -> Iterator[None]:
    lock_path = shard_dir / ".writer.lock"
    if not lock_path.is_file():
        raise CombineError(f"missing evaluator writer lock: {lock_path}")
    with lock_path.open("rb") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CombineError(f"evaluator is still writing {shard_dir}") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _scan_results(path: Path, expected_tasks: set[str]) -> tuple[str, set[str]]:
    digest = hashlib.sha256()
    tasks: Counter[str] = Counter()
    trace_ids: set[str] = set()
    try:
        with path.open("rb") as handle:
            for line_number, raw in enumerate(handle, start=1):
                digest.update(raw)
                if not raw.endswith(b"\n"):
                    raise CombineError(f"{path}:{line_number}: incomplete final JSONL row")
                if not raw.strip():
                    raise CombineError(f"{path}:{line_number}: blank JSONL row")
                try:
                    row = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise CombineError(f"{path}:{line_number}: invalid JSON: {error}") from error
                if not isinstance(row, dict):
                    raise CombineError(f"{path}:{line_number}: trace must be a JSON object")
                trace_id = row.get("id")
                if not isinstance(trace_id, str) or not trace_id:
                    raise CombineError(f"{path}:{line_number}: invalid trace id")
                if trace_id in trace_ids:
                    raise CombineError(f"{path}:{line_number}: duplicate trace id {trace_id!r}")
                trace_ids.add(trace_id)
                tasks[_task_slug(row)] += 1
    except OSError as error:
        raise CombineError(f"cannot read results {path}: {error}") from error

    if sum(tasks.values()) != len(expected_tasks):
        raise CombineError(f"{path}: trace_count={sum(tasks.values())} expected={len(expected_tasks)}")
    observed = set(tasks)
    if observed != expected_tasks:
        missing = sorted(expected_tasks - observed)
        extra = sorted(observed - expected_tasks)
        raise CombineError(f"{path}: task mismatch missing={missing!r} extra={extra!r}")
    wrong = {task: count for task, count in sorted(tasks.items()) if count != 1}
    if wrong:
        raise CombineError(f"{path}: wrong task multiplicity {wrong!r}")
    return digest.hexdigest(), trace_ids


def _copy_results(source: Path, output: BinaryIO) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def combine_shards(
    shard_dirs: tuple[Path, Path],
    *,
    output_dir: Path,
    dataset_dir: Path,
    min_supported_pass_rate: float = 0.04,
    max_supported_pass_rate: float = 0.22,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
) -> dict:
    shard_dirs = tuple(path.resolve() for path in shard_dirs)
    output_dir = output_dir.resolve()
    dataset_dir = dataset_dir.resolve()
    if shard_dirs[0] == shard_dirs[1]:
        raise CombineError("shard directories must be distinct")
    if output_dir.exists():
        raise CombineError(f"refusing to overwrite output directory: {output_dir}")
    if max_sequence_tokens < 1:
        raise CombineError("max_sequence_tokens must be positive")
    if not 0 <= min_supported_pass_rate <= max_supported_pass_rate <= 1:
        raise CombineError("score bounds must satisfy 0 <= min <= max <= 1")
    if not dataset_dir.is_dir():
        raise CombineError(f"dataset directory does not exist: {dataset_dir}")

    expected_by_name: dict[str, set[str]] = {}
    for spec in SHARD_SPECS:
        if _sha256(spec.task_file) != spec.task_file_sha256:
            raise CombineError(f"committed task-file SHA-256 mismatch for shard {spec.name}")
        tasks = set(_read_tasks(spec.task_file))
        if len(tasks) != EXPECTED_TASK_COUNT // 2:
            raise CombineError(f"shard {spec.name} must contain exactly 33 tasks")
        expected_by_name[spec.name] = tasks
    if expected_by_name["a"] & expected_by_name["b"]:
        raise CombineError("committed shard task files overlap")
    dataset_tasks = {
        path.name
        for path in dataset_dir.iterdir()
        if path.is_dir() and (path / "task.toml").is_file() and (path / "instruction.md").is_file()
    }
    combined_expected = expected_by_name["a"] | expected_by_name["b"]
    if len(dataset_tasks) != EXPECTED_TASK_COUNT or combined_expected != dataset_tasks:
        raise CombineError("committed shard union does not exactly match the 66-task dataset")
    if not EXPECTED_UNSUPPORTED_TASKS.issubset(combined_expected):
        raise CombineError("committed shards do not retain all GPU-unsupported tasks")

    shard_records: list[dict] = []
    all_trace_ids: set[str] = set()
    with ExitStack() as stack:
        for shard_dir in sorted(shard_dirs):
            stack.enter_context(_hold_writer_lock(shard_dir))

        provenance_commits: tuple[str, str, str] | None = None
        for spec, shard_dir in zip(SHARD_SPECS, shard_dirs, strict=True):
            results_path = shard_dir / "results.jsonl"
            saved_config_path = shard_dir / "config.toml"
            inputs_dir = shard_dir / "inputs"
            source_config_path = inputs_dir / "source_config.toml"
            task_snapshot_path = inputs_dir / "task_file.txt"
            input_manifest_path = inputs_dir / "manifest.json"
            provenance_path = shard_dir / "provenance.txt"
            for required in (
                results_path,
                saved_config_path,
                source_config_path,
                task_snapshot_path,
                input_manifest_path,
                provenance_path,
            ):
                if not required.is_file():
                    raise CombineError(f"shard {spec.name} missing required file: {required}")

            input_manifest = _read_json(input_manifest_path)
            _validate_snapshot_record(
                input_manifest,
                "config",
                source_config_path,
                expected_source=spec.config,
            )
            task_snapshot_sha = _validate_snapshot_record(
                input_manifest,
                "task_file",
                task_snapshot_path,
                expected_source=spec.task_file,
            )
            if task_snapshot_sha != spec.task_file_sha256:
                raise CombineError(f"shard {spec.name} task snapshot SHA-256 mismatch")
            if set(_read_tasks(task_snapshot_path)) != expected_by_name[spec.name]:
                raise CombineError(f"shard {spec.name} task snapshot content mismatch")
            _validate_config(
                _read_toml(source_config_path),
                spec,
                task_file=None,
                dataset_dir=dataset_dir,
            )
            _validate_config(
                _read_toml(saved_config_path),
                spec,
                task_file=task_snapshot_path,
                dataset_dir=dataset_dir,
            )

            provenance = _read_provenance(provenance_path, spec.endpoint)
            commits = (
                provenance["prime_rl"],
                provenance["verifiers"],
                provenance["renderers"],
            )
            if provenance_commits is None:
                provenance_commits = commits
            elif provenance_commits != commits:
                raise CombineError("shards were produced from different code revisions")

            results_sha, trace_ids = _scan_results(
                results_path,
                expected_by_name[spec.name],
            )
            if overlap := all_trace_ids & trace_ids:
                raise CombineError(f"duplicate trace IDs across shards: {sorted(overlap)[:5]!r}")
            all_trace_ids.update(trace_ids)
            shard_records.append(
                {
                    "name": spec.name,
                    "endpoint": spec.endpoint,
                    "results_path": str(results_path),
                    "results_sha256": results_sha,
                    "task_file_sha256": spec.task_file_sha256,
                    "trace_count": len(trace_ids),
                    "slurm_job_id": provenance["slurm_job_id"],
                    "provenance_sha256": _sha256(provenance_path),
                    "input_manifest_sha256": _sha256(input_manifest_path),
                    "saved_config_sha256": _sha256(saved_config_path),
                }
            )

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{output_dir.name}.tmp-",
                dir=output_dir.parent,
            )
        )
        try:
            combined_path = temporary_dir / "results.jsonl"
            with combined_path.open("xb") as output:
                for record, shard_dir in zip(shard_records, shard_dirs, strict=True):
                    copied_sha = _copy_results(shard_dir / "results.jsonl", output)
                    if copied_sha != record["results_sha256"]:
                        raise CombineError(f"shard {record['name']} results changed while combining")
                output.flush()
                os.fsync(output.fileno())

            try:
                summary, failed = audit_results(
                    combined_path,
                    dataset_dir=dataset_dir,
                    min_supported_pass_rate=min_supported_pass_rate,
                    max_supported_pass_rate=max_supported_pass_rate,
                    max_sequence_tokens=max_sequence_tokens,
                )
            except (OSError, TraceJSONLError, TB4AuditError) as error:
                raise CombineError(f"combined strict TB4 audit could not run: {error}") from error
            if failed:
                problems = summary.get("global_problems") or []
                raise CombineError(
                    "combined strict TB4 audit failed: "
                    f"global={problems!r} trace_failures={summary.get('trace_failures')}"
                )

            checkpoint_path = temporary_dir / "checkpoint.json"
            _write_json(checkpoint_path, summary)
            if provenance_commits is None:
                raise CombineError("no shard provenance was validated")
            manifest = {
                "schema_version": 1,
                "combined_results_sha256": _sha256(combined_path),
                "combined_trace_count": EXPECTED_TASK_COUNT,
                "dataset_dir": str(dataset_dir),
                "score_bounds": {
                    "min_supported_pass_rate": min_supported_pass_rate,
                    "max_supported_pass_rate": max_supported_pass_rate,
                },
                "max_sequence_tokens": max_sequence_tokens,
                "code_revisions": {
                    "prime_rl": provenance_commits[0],
                    "verifiers": provenance_commits[1],
                    "renderers": provenance_commits[2],
                },
                "shards": shard_records,
                "checkpoint_sha256": _sha256(checkpoint_path),
            }
            _write_json(temporary_dir / "merge_manifest.json", manifest)
            _fsync_directory(temporary_dir)
            os.replace(temporary_dir, output_dir)
            _fsync_directory(output_dir.parent)
        except BaseException:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise

    return manifest


def _rate(value: str) -> float:
    rate = float(value)
    if not math.isfinite(rate) or not 0 <= rate <= 1:
        raise argparse.ArgumentTypeError("must be a finite number between 0 and 1")
    return rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-a-dir", required=True, type=Path)
    parser.add_argument("--shard-b-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--min-supported-pass-rate", type=_rate, default=0.04)
    parser.add_argument("--max-supported-pass-rate", type=_rate, default=0.22)
    parser.add_argument(
        "--max-sequence-tokens",
        type=int,
        default=DEFAULT_MAX_SEQUENCE_TOKENS,
    )
    args = parser.parse_args()
    try:
        manifest = combine_shards(
            (args.shard_a_dir, args.shard_b_dir),
            output_dir=args.output_dir,
            dataset_dir=args.dataset_dir,
            min_supported_pass_rate=args.min_supported_pass_rate,
            max_supported_pass_rate=args.max_supported_pass_rate,
            max_sequence_tokens=args.max_sequence_tokens,
        )
    except (OSError, CombineError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
