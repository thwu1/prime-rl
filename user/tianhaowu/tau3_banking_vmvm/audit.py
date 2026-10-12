from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

SCORED_STATUSES = {"completed", "model_error", "model_timeout"}
ENDPOINT_LOCATION_KEYS = {
    "api_key",
    "api_key_env",
    "base_url",
    "base_url_env",
    "info_path",
    "port",
    "slurm_job_id",
    "slurm_job_id_env",
    "slurm_job_name",
    "sticky_session",
    "sticky_session_header",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            rows.append(value)
    return rows


def _semantic_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": config["source"],
        "benchmark": config["benchmark"],
        "policy": {key: value for key, value in config["policy"].items() if key not in ENDPOINT_LOCATION_KEYS},
        "user": {key: value for key, value in config["user"].items() if key not in ENDPOINT_LOCATION_KEYS},
        "judge": {key: value for key, value in config["judge"].items() if key not in ENDPOINT_LOCATION_KEYS},
        "retry": config["retry"],
    }


def _fingerprint(config: dict[str, Any]) -> str:
    payload = json.dumps(_semantic_config(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(values: Iterable[object]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _error_type(row: dict[str, Any]) -> str:
    error = row.get("error")
    if isinstance(error, dict):
        return str(error.get("type", "unknown"))
    return "none"


def _model_error_reason(row: dict[str, Any]) -> str:
    error = row.get("error")
    message = str(error.get("message", "")).lower() if isinstance(error, dict) else ""
    if "maximum context length" in message or "context_length_exceeded" in message:
        return "context_window_exceeded"
    if "must have either content or tool_calls" in message:
        return "empty_or_length_response"
    if "timed out" in message or "timeout" in message:
        return "timeout"
    return _error_type(row)


def _validate_configured_results(
    keyed: dict[tuple[str, int], dict[str, Any]],
    config: dict[str, Any],
    complete: bool,
) -> dict[str, Any]:
    benchmark = config["benchmark"]
    expected_task_count = int(benchmark["expected_tasks"])
    expected_trial_count = int(benchmark["num_trials"])
    expected_total = expected_task_count * expected_trial_count
    expected_trials = set(range(expected_trial_count))
    expected_fingerprint = _fingerprint(config)
    generator = random.Random(int(benchmark["seed"]))
    expected_seeds = {trial: generator.randint(0, 1_000_000) for trial in range(expected_trial_count)}

    for key, row in keyed.items():
        task_id, trial = key
        if trial not in expected_trials:
            raise ValueError(f"Unexpected trial index for {key}")
        if int(row["seed"]) != expected_seeds[trial]:
            raise ValueError(f"Wrong seed for {key}: {row['seed']} != {expected_seeds[trial]}")
        if row.get("config_fingerprint") != expected_fingerprint:
            raise ValueError(f"Config fingerprint mismatch for {key}")
        if row.get("source_commit") != config["source"]["commit"]:
            raise ValueError(f"Source commit mismatch for {key}")
        if not task_id.startswith("task_"):
            raise ValueError(f"Malformed task ID: {task_id}")

    task_sets: dict[int, set[str]] = defaultdict(set)
    trials_by_task: dict[str, set[int]] = defaultdict(set)
    for task_id, trial in keyed:
        task_sets[trial].add(task_id)
        trials_by_task[task_id].add(trial)

    if complete:
        if len(keyed) != expected_total:
            raise ValueError(f"Configured run has {len(keyed)} results, expected {expected_total}")
        if set(task_sets) != expected_trials:
            raise ValueError(f"Trial IDs differ from configured trials: {sorted(task_sets)}")
        reference_tasks = task_sets[0]
        if len(reference_tasks) != expected_task_count:
            raise ValueError(f"Trial 0 has {len(reference_tasks)} tasks, expected {expected_task_count}")
        for trial, task_ids in task_sets.items():
            if task_ids != reference_tasks:
                raise ValueError(f"Task coverage differs in trial {trial}")
        for task_id, trials in trials_by_task.items():
            if trials != expected_trials:
                raise ValueError(f"Trial coverage differs for {task_id}: {sorted(trials)}")

    return {
        "configured_expected_total": expected_total,
        "configured_task_count": expected_task_count,
        "configured_trial_count": expected_trial_count,
        "expected_seeds": {str(key): value for key, value in expected_seeds.items()},
        "expected_fingerprint": expected_fingerprint,
        "coverage_valid": complete,
    }


def summarize(
    results_path: Path,
    expected_total: int | None = None,
    expected_passes: int | None = None,
    config_path: Path | None = None,
    allow_config_subset: bool = False,
) -> dict[str, Any]:
    rows = load_jsonl(results_path)
    keyed: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["task_id"]), int(row["trial"]))
        if key in keyed:
            raise ValueError(f"Duplicate scored result for {key}")
        if row.get("status") not in SCORED_STATUSES:
            raise ValueError(f"Unscored status in results file for {key}: {row.get('status')}")
        reward = float(row.get("reward", 0.0))
        if reward not in {0.0, 1.0}:
            raise ValueError(f"Non-binary reward for {key}: {reward}")
        keyed[key] = row

    completed = len(keyed)
    passes = sum(float(row.get("reward", 0.0)) == 1.0 for row in keyed.values())
    fingerprints = {str(row.get("config_fingerprint")) for row in keyed.values()}
    source_commits = {str(row.get("source_commit")) for row in keyed.values()}
    if len(fingerprints) > 1:
        raise ValueError(f"Multiple config fingerprints in results: {sorted(fingerprints)}")
    if len(source_commits) > 1:
        raise ValueError(f"Multiple source commits in results: {sorted(source_commits)}")

    per_trial = Counter(int(row["trial"]) for row in keyed.values())
    summary: dict[str, Any] = {
        "schema_version": 2,
        "completed": completed,
        "passes": passes,
        "reward_sum": float(passes),
        "pass_rate": passes / completed if completed else None,
        "unique_tasks": len({task_id for task_id, _ in keyed}),
        "trial_ids": sorted({trial for _, trial in keyed}),
        "results_per_trial": {str(key): value for key, value in sorted(per_trial.items())},
        "status_counts": _counts(row.get("status") for row in keyed.values()),
        "termination_reason_counts": _counts(row.get("termination_reason", "none") for row in keyed.values()),
        "model_error_type_counts": _counts(
            _error_type(row) for row in keyed.values() if row.get("status") == "model_error"
        ),
        "model_error_reason_counts": _counts(
            _model_error_reason(row) for row in keyed.values() if row.get("status") == "model_error"
        ),
        "provider_retry_exhaustions": sum(
            bool((row.get("error") or {}).get("provider_retries_exhausted"))
            for row in keyed.values()
            if isinstance(row.get("error"), dict)
        ),
        "config_fingerprint": next(iter(fingerprints), None),
        "source_commit": next(iter(source_commits), None),
    }
    if expected_total is not None:
        summary["expected_total"] = expected_total
        summary["complete"] = completed == expected_total
    if expected_passes is not None:
        summary["expected_passes"] = expected_passes
        summary["passes_match"] = passes == expected_passes

    if config_path is not None:
        config = tomllib.loads(config_path.read_text())
        config_total = int(config["benchmark"]["expected_tasks"]) * int(config["benchmark"]["num_trials"])
        if expected_total is not None and expected_total != config_total and not allow_config_subset:
            raise ValueError(f"--expected-total {expected_total} differs from config total {config_total}")
        target_total = expected_total if expected_total is not None else config_total
        complete = completed == target_total
        summary.update(_validate_configured_results(keyed, config, complete and target_total == config_total))
        summary["complete"] = complete
    return summary


def _result_attempts(path: Path) -> dict[tuple[str, int], tuple[int, str]]:
    attempts: dict[tuple[str, int], tuple[int, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            key = (str(row["task_id"]), int(row["trial"]))
            attempts[key] = (int(row["attempt"]), str(row["status"]))
    return attempts


def _count_vmvm_transport_drops(rows: list[dict[str, Any]]) -> int:
    """Count increases in each worker's cumulative transport-drop counter."""
    previous_by_worker: dict[int, int] = {}
    total = 0
    for row in rows:
        worker = int(row["worker"])
        command = row.get("command")
        if not isinstance(command, dict):
            if row.get("status") == "vmvm_lost":
                previous_by_worker.pop(worker, None)
            continue

        current = int(command.get("transport_drops", 0))
        if current < 0:
            raise ValueError(f"Negative VMVM transport-drop count for worker {worker}")
        previous = previous_by_worker.get(worker, 0)
        total += current - previous if current >= previous else current
        previous_by_worker[worker] = current
    return total


def _audit_attempts(path: Path, results_path: Path, complete: bool) -> dict[str, Any]:
    rows = load_jsonl(path)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (str(row["task_id"]), int(row["trial"]))
        grouped[key].append(row)
        if row.get("status") == "retryable_error":
            raise ValueError(f"Provider failure triggered a whole-trial retry for {key}")

    result_attempts = _result_attempts(results_path)
    for key, trial_attempts in grouped.items():
        numbers = [int(row["attempt"]) for row in trial_attempts]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"Non-contiguous attempt sequence for {key}: {numbers}")
        for previous, current in zip(trial_attempts, trial_attempts[1:]):
            if previous.get("status") != "vmvm_lost":
                raise ValueError(
                    f"Attempt {current['attempt']} for {key} followed non-VMVM status {previous.get('status')}"
                )
        if key in result_attempts:
            result_attempt, result_status = result_attempts[key]
            last = trial_attempts[-1]
            if (int(last["attempt"]), str(last.get("status"))) != (result_attempt, result_status):
                raise ValueError(f"Final attempt does not match scored result for {key}")
        elif complete:
            raise ValueError(f"Attempt log has no scored result for {key}")

    missing_attempts = sorted(set(result_attempts) - set(grouped))
    if missing_attempts:
        raise ValueError(f"Scored results have no attempt record: {missing_attempts[:10]}")

    return {
        "records": len(rows),
        "status_counts": _counts(row.get("status") for row in rows),
        "attempt_number_counts": _counts(row.get("attempt") for row in rows),
        "retried_trial_attempts": sum(int(row.get("attempt", 1)) > 1 for row in rows),
        "retried_trials": sum(len(trial_attempts) > 1 for trial_attempts in grouped.values()),
        "whole_trial_retry_policy_valid": True,
        "vmvm_transport_drops": _count_vmvm_transport_drops(rows),
    }


def _same_number(actual: object, expected: object) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual) == float(expected)
    return actual == expected


def _expected_request(role: str, config: dict[str, Any]) -> dict[str, Any]:
    section = config[role]
    expected: dict[str, Any] = {
        "model": section["model"],
        "temperature": section["temperature"],
        "chat_template_kwargs": {section.get("thinking_template_key", "enable_thinking"): section["thinking"]},
    }
    for key in ("top_p", "max_tokens", "skip_special_tokens"):
        if section.get(key) is not None:
            expected[key] = section[key]
    return expected


def _audit_proxy(path: Path, config: dict[str, Any] | None) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    empty_successes: Counter[str] = Counter()
    empty_trials: dict[str, dict[str, Any]] = {}
    finish_reasons: Counter[str] = Counter()
    non_retryable_errors: Counter[str] = Counter()
    session_headers: Counter[str] = Counter()
    session_ids: set[str] = set()
    sticky_roles: set[str] = set()
    total = 0
    expected_seeds: dict[int, int] = {}
    if config is not None:
        generator = random.Random(int(config["benchmark"]["seed"]))
        expected_seeds = {
            trial: generator.randint(0, 1_000_000) for trial in range(int(config["benchmark"]["num_trials"]))
        }
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            total += 1
            role = str(event.get("role"))
            route = str(event.get("route"))
            status = int(event.get("status", 0))
            attempt = int(event.get("attempt", 0))
            if role not in {"policy", "user", "judge"} or route != role:
                raise ValueError(f"Invalid proxy role/route at {path}:{line_number}: {role}/{route}")
            if attempt < 1:
                raise ValueError(f"Missing proxy attempt at {path}:{line_number}")
            counts[f"{role}:{status}"] += 1
            if 400 <= status < 500 and status != 429:
                non_retryable_errors[f"{event.get('trial')}:attempt={attempt}"] += 1
            response = event.get("response") or {}
            finish_reason = str(response.get("finish_reason"))
            finish_reasons[f"{role}:{finish_reason}"] += 1
            if status == 200 and not response.get("has_content") and not response.get("tool_names"):
                empty_successes[role] += 1
                trial_key = str(event.get("trial"))
                empty_key = f"{trial_key}:{role}"
                empty_trial = empty_trials.setdefault(
                    empty_key,
                    {"role": role, "count": 0, "finish_reason_counts": {}},
                )
                empty_trial["count"] += 1
                reason = str(response.get("finish_reason"))
                reason_counts = empty_trial["finish_reason_counts"]
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            if config is None:
                continue
            request = event.get("request")
            if not isinstance(request, dict):
                raise ValueError(f"Missing audited request settings at {path}:{line_number}")
            trial_key = str(event.get("trial"))
            try:
                trial = int(trial_key.rsplit(".", maxsplit=1)[1])
            except (IndexError, ValueError) as error:
                raise ValueError(f"Malformed proxy trial key at {path}:{line_number}: {trial_key}") from error
            section = config[role]
            if "sticky_session" in section:
                sticky_roles.add(role)
                actual_header = event.get("session_header")
                actual_id = event.get("session_id")
                if section["sticky_session"]:
                    expected_header = str(section["sticky_session_header"]).lower()
                    expected_id = f"tau3-{trial_key}-{attempt}-{role}"
                    if actual_header != expected_header or actual_id != expected_id:
                        raise ValueError(
                            f"Proxy sticky-session mismatch at {path}:{line_number}: "
                            f"{actual_header}={actual_id!r}, expected {expected_header}={expected_id!r}"
                        )
                    session_headers[f"{role}:{actual_header}"] += 1
                    session_ids.add(str(actual_id))
                elif actual_header is not None or actual_id is not None:
                    raise ValueError(f"Unexpected sticky session at {path}:{line_number}")
            if role != "judge" and request.get("seed") != expected_seeds.get(trial):
                raise ValueError(
                    f"Proxy seed mismatch at {path}:{line_number}: {request.get('seed')} != {expected_seeds.get(trial)}"
                )
            if role == "judge" and "seed" in request and request["seed"] != expected_seeds.get(trial):
                raise ValueError(
                    f"Judge seed mismatch at {path}:{line_number}: {request.get('seed')} != {expected_seeds.get(trial)}"
                )
            for key, expected in _expected_request(role, config).items():
                if key not in request or not _same_number(request[key], expected):
                    raise ValueError(
                        f"Proxy protocol mismatch at {path}:{line_number} for {role}.{key}: "
                        f"{request.get(key)!r} != {expected!r}"
                    )
            for key in ("top_p", "max_tokens", "skip_special_tokens"):
                if config[role].get(key) is None and key in request:
                    raise ValueError(f"Unexpected {role}.{key} at {path}:{line_number}")

    repeated_non_retryable = {trial: count for trial, count in non_retryable_errors.items() if count > 1}
    if repeated_non_retryable:
        raise ValueError(f"Non-retryable provider errors were requested more than once: {repeated_non_retryable}")

    return {
        "records": total,
        "role_status_counts": dict(sorted(counts.items())),
        "empty_success_counts": dict(sorted(empty_successes.items())),
        "empty_success_trials": dict(sorted(empty_trials.items())),
        "finish_reason_counts": dict(sorted(finish_reasons.items())),
        "non_retryable_error_counts": dict(sorted(non_retryable_errors.items())),
        "session_header_counts": dict(sorted(session_headers.items())),
        "sticky_session_ids": len(session_ids),
        "sticky_session_roles": sorted(sticky_roles),
        "sticky_session_valid": bool(sticky_roles),
        "protocol_valid": config is not None,
    }


def write_summary(
    results_path: Path,
    summary_path: Path,
    expected_total: int | None = None,
    expected_passes: int | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    summary = summarize(results_path, expected_total, expected_passes, config_path)
    temporary = summary_path.with_suffix(summary_path.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, summary_path)
    return summary


def _existing_or_none(path: Path) -> Path | None:
    return path if path.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected-total", type=int)
    parser.add_argument("--expected-passes", type=int)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--attempts", type=Path)
    parser.add_argument("--proxy-audit", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    run_dir = args.results.resolve().parent
    config_path = args.config or _existing_or_none(run_dir / "config.toml")
    metadata_path = args.metadata or _existing_or_none(run_dir / "run_metadata.json")
    attempts_path = args.attempts or _existing_or_none(run_dir / "attempts.jsonl")
    proxy_path = args.proxy_audit or _existing_or_none(run_dir / "proxy_requests.jsonl")
    config = tomllib.loads(config_path.read_text()) if config_path else None
    metadata = json.loads(metadata_path.read_text()) if metadata_path else None
    metadata_expected_total = int(metadata["expected_total"]) if metadata else None
    if args.expected_total is not None and metadata_expected_total is not None:
        if args.expected_total != metadata_expected_total:
            raise ValueError("--expected-total differs from run metadata")
    target_total = args.expected_total if args.expected_total is not None else metadata_expected_total
    config_total = None
    if config is not None:
        config_total = int(config["benchmark"]["expected_tasks"]) * int(config["benchmark"]["num_trials"])
    allow_config_subset = config_total is not None and target_total is not None and target_total != config_total

    summary = summarize(
        args.results,
        target_total,
        args.expected_passes,
        config_path,
        allow_config_subset=allow_config_subset,
    )
    if metadata_path:
        assert metadata is not None
        if summary["config_fingerprint"] != metadata.get("config_fingerprint"):
            raise ValueError("Result and run-metadata fingerprints differ")
        if summary["source_commit"] != metadata.get("source_commit"):
            raise ValueError("Result and run-metadata source commits differ")
        if metadata.get("expected_total") != target_total:
            raise ValueError("Run-metadata expected total differs from audited total")
        archive = Path(metadata["source_archive"])
        if _file_sha256(archive) != metadata.get("source_archive_sha256"):
            raise ValueError("Run-metadata source archive checksum does not match the archive")
        fatal_errors = metadata.get("fatal_errors", [])
        if summary.get("complete") and fatal_errors:
            raise ValueError(f"Completed run records fatal errors: {fatal_errors}")
        summary["metadata"] = {
            "expected_total": metadata.get("expected_total"),
            "source_archive_sha256": metadata.get("source_archive_sha256"),
            "source_archive_verified": True,
            "fatal_errors": fatal_errors,
        }
    if attempts_path:
        summary["attempts"] = _audit_attempts(attempts_path, args.results, bool(summary.get("complete")))
    if proxy_path:
        summary["proxy"] = _audit_proxy(proxy_path, config)
    if args.summary:
        temporary = args.summary.with_suffix(args.summary.suffix + ".tmp")
        temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, args.summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("complete", True) and summary.get("passes_match", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
