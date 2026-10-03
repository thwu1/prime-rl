from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import queue
import random
import shutil
import statistics
import threading
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness import (
    ToolathlonVMVMHarness,
    VMVMCommandFailed,
    VMVMCommandLost,
    make_harness_config,
)
from proxy import Route, start_proxy, stop_proxy, write_proxy_summary

logger = logging.getLogger("toolathlon_vmvm")
HERE = Path(__file__).resolve().parent
SCORED_STATUSES = {"completed", "model_error", "model_timeout"}
RUNNER_FILES = ("run_eval.py", "harness.py", "proxy.py", "vmvm_backend.py", "worker.py", "local_tools.py")


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Trial:
    task: dict[str, Any]
    trial: int

    @property
    def task_id(self) -> str:
        return str(self.task["task_id"])

    @property
    def key(self) -> tuple[str, int]:
        return self.task_id, self.trial


class JsonlStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def append(self, row: dict[str, Any]) -> None:
        encoded = json.dumps(row, sort_keys=True, default=str) + "\n"
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())


def _normalize_base_url(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return normalized


def _load_endpoint(section: dict[str, Any], override_url: str | None) -> Endpoint:
    info: dict[str, Any] = {}
    if info_path := section.get("info_path"):
        info = json.loads(Path(info_path).expanduser().read_text())
    base_url = (
        override_url or os.getenv(str(section.get("base_url_env", ""))) or section.get("base_url") or info.get("url")
    )
    if not base_url:
        raise ValueError("No model endpoint URL configured")
    api_key = os.getenv(str(section.get("api_key_env", ""))) or section.get("api_key") or info.get("api_key") or "EMPTY"
    model = section.get("model") or info.get("model")
    if not model:
        raise ValueError("Endpoint model is missing")
    return Endpoint(_normalize_base_url(str(base_url)), str(api_key), str(model))


def _probe(endpoint: Endpoint, attempts: int, retry_delay: float) -> None:
    request = urllib.request.Request(
        endpoint.base_url + "/v1/models",
        headers={"Authorization": f"Bearer {endpoint.api_key}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            with opener.open(request, timeout=30) as response:
                payload = json.load(response)
            models = {str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict)}
            if endpoint.model not in models:
                raise ValueError(
                    f"Endpoint {endpoint.base_url} does not advertise {endpoint.model!r}: {sorted(models)}"
                )
            return
        except urllib.error.HTTPError as error:
            if 400 <= error.code < 500 and error.code not in {408, 409, 429}:
                raise
            last_error = error
        except (json.JSONDecodeError, OSError) as error:
            last_error = error
        if attempt < attempts:
            logger.warning(
                "Model endpoint probe failed (%d/%d): %s",
                attempt,
                attempts,
                last_error,
            )
            time.sleep(retry_delay)
    raise RuntimeError(f"Model endpoint probe failed after {attempts} attempts: {last_error}") from last_error


def _semantic_config(config: dict[str, Any]) -> dict[str, Any]:
    endpoint_keys = {"api_key", "api_key_env", "base_url", "base_url_env", "info_path"}
    return {
        "source": config["source"],
        "benchmark": config["benchmark"],
        "model": {key: value for key, value in config["model"].items() if key not in endpoint_keys},
        "service": config["service"],
        "runtime": {key: value for key, value in config["runtime"].items() if key not in {"workers"}},
        "retry": config["retry"],
    }


def _fingerprint(config: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "config": _semantic_config(config),
            "runner": {name: _sha256(HERE / name) for name in RUNNER_FILES},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_config(
    config: dict[str, Any],
    catalog: list[dict[str, Any]],
    schemas: list[dict[str, Any]],
    catalog_path: Path,
    schemas_path: Path,
) -> None:
    benchmark = config["benchmark"]
    suite = str(benchmark.get("suite", "toolathlon-original"))
    if int(benchmark["expected_tasks"]) != 108 or len(catalog) != 108:
        raise ValueError(f"Toolathlon must contain exactly 108 tasks, found {len(catalog)}")
    task_ids = [str(task["task_id"]) for task in catalog]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("The bundled Toolathlon catalog contains duplicate task IDs")
    source = config["source"]
    for key, path in (("task_catalog", catalog_path), ("tool_schemas", schemas_path)):
        expected = source.get(f"{key}_sha256")
        if expected is None:
            continue
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"Bundled {path.name} checksum mismatch: {actual} != {expected}")
    model = config["model"]
    model_name = str(model["model"])
    supported_models = {
        "Kimi-K2.6",
        "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16",
    }
    if model_name not in supported_models:
        raise ValueError(f"Unsupported Toolathlon model: {model_name}")
    if int(model.get("context_window", 0)) != 262144:
        raise ValueError("Toolathlon evaluation requires a 262,144-token context window")
    task_timeout = int(benchmark["task_timeout_seconds"])
    command_timeout = int(config["runtime"]["command_timeout_seconds"])
    if suite == "toolathlon-original":
        if bool(model.get("thinking")) is not True:
            raise ValueError("Historical Kimi-K2.6 parity requires thinking mode")
        if bool(model.get("parallel_tool_calls")) is not True:
            raise ValueError("Historical Toolathlon parity enables parallel tool calls")
        if int(config["runtime"]["workers"]) != 48:
            raise ValueError("The historical diagnostic uses concurrency 48")
        if str(source["commit"]) != "8a202af67a19eb677eef623563f685ebcedeb4c9":
            raise ValueError("The historical parity run is pinned to Toolathlon commit 8a202af")
        schema_names = [str(schema["name"]) for schema in schemas]
        if len(schemas) != 607 or len(set(schema_names)) != len(schema_names):
            raise ValueError("The bundled Toolathlon tool schema set must contain 607 unique tools")
        if int(benchmark.get("num_trials", 1)) != 1:
            raise ValueError("This pass@1 parity configuration requires one trial per task")
        if float(model["temperature"]) != 0.6 or float(model["top_p"]) != 1.0:
            raise ValueError("Historical Toolathlon parity requires temperature=0.6 and top_p=1.0")
        if int(model["max_tokens"]) != 8192:
            raise ValueError("Historical Toolathlon parity requires max_tokens=8192")
        if task_timeout != 2400 or command_timeout < task_timeout + 60:
            raise ValueError(
                "Historical Toolathlon parity requires a 2,400-second task timeout "
                "and at least 60 seconds for result cleanup"
            )
        if int(config["reference"]["target_passes"]) != 54:
            raise ValueError("The reported Kimi K2.6 target is exactly 54/108")
        return
    if suite != "toolathlon-verified-internal-v3":
        raise ValueError(f"Unsupported Toolathlon suite: {suite}")
    if int(config["runtime"]["workers"]) != 96:
        raise ValueError("The internal Toolathlon-Verified run uses concurrency 96")
    if benchmark.get("tool_source") not in {"live", "static"}:
        raise ValueError("The internal Verified run must select live or static tool schemas")
    num_trials = int(benchmark.get("num_trials", 0))
    if num_trials < 1:
        raise ValueError("Toolathlon-Verified requires at least one trial")
    if int(benchmark["max_steps"]) != 100:
        raise ValueError("Toolathlon-Verified uses a 100-step agent limit")
    if task_timeout != 5400 or command_timeout < task_timeout + 300:
        raise ValueError(
            "Toolathlon-Verified requires a 5,400-second task timeout and at least 300 seconds for result cleanup"
        )
    if "temperature" in model or "top_p" in model:
        raise ValueError("Toolathlon-Verified leaves temperature and top_p at provider defaults")
    if int(model["max_tokens"]) != 65536:
        raise ValueError("Toolathlon-Verified uses max_tokens=65536")
    if int(model.get("request_retries", 0)) != 10:
        raise ValueError("The official Toolathlon model provider retries failed model requests 10 times")
    if model_name == "Kimi-K2.6":
        if num_trials != 3:
            raise ValueError("Kimi K2.6 leaderboard parity requires three trials")
        if "thinking" in model or "thinking_template_key" in model:
            raise ValueError("Verified Kimi uses the endpoint-default thinking mode")
        if "parallel_tool_calls" in model:
            raise ValueError("Verified Kimi omits parallel_tool_calls from the model request")
        expected_reference = {
            "target_total_passes": 188,
            "target_any_passes": 78,
            "target_all_passes": 45,
            "pass_at_1_percent": 58.0,
            "pass_at_1_std_percent": 4.9,
            "pass_at_3_percent": 72.2,
            "pass_pow_3_percent": 41.7,
        }
        for key, value in expected_reference.items():
            if config.get("reference", {}).get(key) != value:
                raise ValueError(f"Verified leaderboard reference {key} must be {value}")
    else:
        if num_trials != 2:
            raise ValueError("The Nemotron Super evaluation is configured for two trials")
        if model.get("sticky_session") is not True:
            raise ValueError("Nemotron Super evaluation requires sticky sessions")
        if str(model.get("sticky_session_header", "")).strip().lower() != "x-session-id":
            raise ValueError("Nemotron Super sticky routing requires the 'x-session-id' header")
        if bool(model.get("thinking")) is not True:
            raise ValueError("Nemotron Super evaluation requires thinking mode")
        if bool(model.get("parallel_tool_calls")) is not True:
            raise ValueError("Nemotron Super evaluation enables parallel tool calls")
        if model.get("thinking_template_key") != "enable_thinking":
            raise ValueError("Nemotron Super uses the 'enable_thinking' chat-template key")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(temporary, path)


def _input_path(config: dict[str, Any], key: str, default: str) -> Path:
    path = Path(str(config["source"].get(key, default)))
    return path if path.is_absolute() else HERE / path


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected object at {path}:{line_number}")
            rows.append(row)
    return rows


def _completed_keys(path: Path, fingerprint: str) -> set[tuple[str, int]]:
    completed: set[tuple[str, int]] = set()
    for row in _load_jsonl(path):
        if row.get("config_fingerprint") != fingerprint:
            raise ValueError(f"Existing result has a different config fingerprint: {row.get('config_fingerprint')}")
        if row.get("status") not in SCORED_STATUSES:
            raise ValueError(f"Unexpected status in results file: {row.get('status')}")
        key = (str(row["task_id"]), int(row.get("trial", 0)))
        if key in completed:
            raise ValueError(f"Duplicate result in {path}: {key}")
        completed.add(key)
    return completed


def _unfinished_attempt_counts(
    path: Path,
    completed: set[tuple[str, int]],
) -> dict[tuple[str, int], int]:
    histories: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in _load_jsonl(path):
        key = (str(row["task_id"]), int(row.get("trial", 0)))
        if key not in completed:
            histories.setdefault(key, []).append(row)

    counts: dict[tuple[str, int], int] = {}
    for key, rows in histories.items():
        attempt_numbers = [int(row["attempt"]) for row in rows]
        if attempt_numbers != list(range(1, len(rows) + 1)):
            raise ValueError(f"Cannot resume non-contiguous attempts for {key}: {attempt_numbers}")
        statuses = [row.get("status") for row in rows]
        if any(status not in {"vmvm_lost", "retryable_error"} for status in statuses):
            raise ValueError(f"Cannot safely resume unfinished attempts for {key}: {statuses}")
        counts[key] = len(rows)
    return counts


def _summary(
    path: Path,
    expected_tasks: int,
    trial_indices: list[int],
    reference: dict[str, Any] | None,
) -> dict[str, Any]:
    rows = _load_jsonl(path)
    expected_total = expected_tasks * len(trial_indices)
    passed = sum(int(row.get("reward") == 1) for row in rows)
    failed = sum(int(row.get("reward") == 0) for row in rows)
    unscored = len(rows) - passed - failed
    score = passed / expected_total if expected_total else 0.0
    description_drift = sorted(
        str(row["task_id"]) for row in rows if row.get("service", {}).get("task_drift", {}).get("description_changed")
    )
    missing_historical_tools = {
        str(row["task_id"]): row["service"]["task_drift"]["missing_historical_tools"]
        for row in rows
        if row.get("service", {}).get("task_drift", {}).get("missing_historical_tools")
    }
    environment_compatible = not missing_historical_tools
    rows_by_trial = {trial: [row for row in rows if int(row.get("trial", 0)) == trial] for trial in trial_indices}
    trial_passes = [sum(int(row.get("reward") == 1) for row in rows_by_trial[trial]) for trial in trial_indices]
    trial_task_sets = [set(str(row["task_id"]) for row in rows_by_trial[trial]) for trial in trial_indices]
    complete = (
        len(rows) == expected_total
        and unscored == 0
        and all(len(task_set) == expected_tasks for task_set in trial_task_sets)
        and all(task_set == trial_task_sets[0] for task_set in trial_task_sets[1:])
    )
    report: dict[str, Any] = {
        "expected_total": expected_total,
        "completed": len(rows),
        "passed": passed,
        "failed": failed,
        "unscored": unscored,
        "pass_at_1": score,
        "pass_at_1_percent": 100 * score,
        "trial_passes": trial_passes,
        "exact_target": None,
        "exact_reproduction": None,
        "complete": complete,
        "environment_compatible": environment_compatible,
        "environment_drift": {
            "changed_descriptions": description_drift,
            "missing_historical_tools": missing_historical_tools,
        },
    }
    if reference is None:
        return report
    if len(trial_indices) == 1:
        target_passes = int(reference["target_passes"])
        exact_target = complete and passed == target_passes
        report.update(
            {
                "target_passes": target_passes,
                "target_percent": 100 * target_passes / expected_total,
                "exact_target": exact_target,
                "exact_reproduction": exact_target and environment_compatible,
            }
        )
        return report

    pass_sets = [
        {str(row["task_id"]) for row in rows_by_trial[trial] if row.get("reward") == 1} for trial in trial_indices
    ]
    any_passes = len(set.union(*pass_sets)) if pass_sets else 0
    all_passes = len(set.intersection(*pass_sets)) if pass_sets else 0
    pass_rates = [100 * count / expected_tasks for count in trial_passes]
    metrics = {
        "pass_at_1_percent": 100 * passed / expected_total,
        "pass_at_1_std_percent": statistics.pstdev(pass_rates),
        "pass_at_3_percent": 100 * any_passes / expected_tasks,
        "pass_pow_3_percent": 100 * all_passes / expected_tasks,
    }
    rounded = {key: round(value, 1) for key, value in metrics.items()}
    exact_target = (
        complete
        and passed == int(reference["target_total_passes"])
        and any_passes == int(reference["target_any_passes"])
        and all_passes == int(reference["target_all_passes"])
        and rounded["pass_at_1_percent"] == float(reference["pass_at_1_percent"])
        and rounded["pass_at_1_std_percent"] == float(reference["pass_at_1_std_percent"])
        and rounded["pass_at_3_percent"] == float(reference["pass_at_3_percent"])
        and rounded["pass_pow_3_percent"] == float(reference["pass_pow_3_percent"])
    )
    report.update(
        {
            "any_passes": any_passes,
            "all_passes": all_passes,
            "metrics": metrics,
            "metrics_rounded_1dp": rounded,
            "reference": reference,
            "exact_target": exact_target,
            "exact_reproduction": exact_target and environment_compatible,
        }
    )
    return report


def _copy_run_inputs(
    config_path: Path,
    output_dir: Path,
    catalog_path: Path,
    schemas_path: Path,
) -> None:
    inputs = [
        (config_path, "config.toml"),
        (catalog_path, catalog_path.name),
        (schemas_path, schemas_path.name),
    ]
    inputs.extend((HERE / name, name) for name in RUNNER_FILES)
    for source, name in inputs:
        destination = output_dir / name
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise ValueError(f"Output directory contains a different {name}: {destination}")
        if not destination.exists():
            shutil.copy2(source, destination)


def _make_request(
    trial: Trial,
    config: dict[str, Any],
    endpoint: Endpoint,
    fingerprint: str,
) -> dict[str, Any]:
    return {
        "task_id": trial.task_id,
        "task": trial.task,
        "trial": trial.trial,
        "config_fingerprint": fingerprint,
        "benchmark": config["benchmark"],
        "service": config["service"] | {"model_name": endpoint.model},
        "model": {"model": endpoint.model},
        "model_settings": {
            key: value
            for key, value in config["model"].items()
            if key not in {"api_key", "api_key_env", "base_url", "base_url_env", "info_path", "model"}
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--model-base-url")
    parser.add_argument("--task-id", action="append")
    parser.add_argument("--trial", action="append", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--extra-infrastructure-retries", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.extra_infrastructure_retries < 0:
        raise ValueError("--extra-infrastructure-retries must be nonnegative")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
    )
    config_path = args.config.resolve()
    config = tomllib.loads(config_path.read_text())
    catalog_path = _input_path(config, "task_catalog_file", "task_catalog.json")
    schemas_path = _input_path(config, "tool_schemas_file", "tool_schemas.json")
    catalog = json.loads(catalog_path.read_text())
    schemas = json.loads(schemas_path.read_text())
    if not isinstance(catalog, list):
        raise ValueError("task_catalog.json must contain a list")
    if not isinstance(schemas, list):
        raise ValueError("tool_schemas.json must contain a list")
    _validate_config(config, catalog, schemas, catalog_path, schemas_path)
    fingerprint = _fingerprint(config)
    selected = catalog
    if args.task_id:
        requested = set(args.task_id)
        known = {str(task["task_id"]) for task in catalog}
        if unknown := requested - known:
            raise ValueError(f"Unknown Toolathlon task IDs: {sorted(unknown)}")
        selected = [task for task in selected if str(task["task_id"]) in requested]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        selected = selected[: args.limit]
    num_trials = int(config["benchmark"]["num_trials"])
    trial_indices = list(range(num_trials))
    if args.trial:
        requested_trials = set(args.trial)
        invalid_trials = requested_trials - set(trial_indices)
        if invalid_trials:
            raise ValueError(f"Invalid trial indices: {sorted(invalid_trials)}")
        trial_indices = [trial for trial in trial_indices if trial in requested_trials]
    trials = [Trial(task=task, trial=trial) for trial in trial_indices for task in selected]
    worker_count = int(args.workers or config["runtime"]["workers"])
    max_infrastructure_attempts = (
        int(config["retry"]["max_infrastructure_retries"]) + 1 + args.extra_infrastructure_retries
    )
    full_run = len(selected) == int(config["benchmark"]["expected_tasks"]) and len(trial_indices) == num_trials
    configured_workers = int(config["runtime"]["workers"])
    if full_run and worker_count != configured_workers:
        raise ValueError(f"A full parity run must use exactly {configured_workers} workers")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "config": str(config_path),
                    "config_fingerprint": fingerprint,
                    "tasks": len(selected),
                    "trials": len(trials),
                    "workers": worker_count,
                    "max_infrastructure_attempts": max_infrastructure_attempts,
                    "task_ids": [trial.task_id for trial in trials[:10]],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    endpoint = _load_endpoint(config["model"], args.model_base_url)
    _probe(
        endpoint,
        max(1, int(config["model"].get("request_retries", 1))),
        float(config["model"].get("request_retry_delay_seconds", 10)),
    )
    output_dir = (args.output_dir or Path(config["output_dir"])).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_run_inputs(config_path, output_dir, catalog_path, schemas_path)
    snapshot_worker_path = output_dir / "worker.py"
    snapshot_local_tools_path = output_dir / "local_tools.py"
    snapshot_schemas_path = output_dir / "tool_schemas.json"
    results_path = output_dir / "results.jsonl"
    attempts_path = output_dir / "attempts.jsonl"
    results = JsonlStore(results_path)
    attempts = JsonlStore(attempts_path)
    completed = _completed_keys(results_path, fingerprint)
    unfinished_attempt_counts = _unfinished_attempt_counts(attempts_path, completed)
    pending = [trial for trial in trials if trial.key not in completed]
    expected_total = len(trials)
    metadata = {
        "schema_version": 1,
        "config_fingerprint": fingerprint,
        "source_commit": config["source"]["commit"],
        "runner": {name: _sha256(output_dir / name) for name in RUNNER_FILES},
        "model": {"base_url": endpoint.base_url, "model": endpoint.model},
        "task_count": len(selected),
        "expected_total": expected_total,
        "resumed": len(completed),
        "resumed_infrastructure_attempts": sum(unfinished_attempt_counts.values()),
        "workers": worker_count,
        "max_infrastructure_attempts": max_infrastructure_attempts,
        "extra_infrastructure_retries": args.extra_infrastructure_retries,
        "started_at": time.time(),
    }
    _write_json(output_dir / "run_metadata.json", metadata)

    proxy_server, proxy_thread = start_proxy(
        Route("model", "/model", endpoint.base_url, endpoint.api_key),
        output_dir / "proxy_requests.jsonl",
        int(config["runtime"]["request_timeout_seconds"]),
    )
    work_queue: queue.Queue[Trial] = queue.Queue()
    shuffled_pending = list(pending)
    random.Random(int(config["benchmark"]["dispatch_seed"])).shuffle(shuffled_pending)
    for trial in shuffled_pending:
        work_queue.put(trial)
    stop_event = threading.Event()
    fatal_errors: list[str] = []
    fatal_lock = threading.Lock()
    completed_counter = len(completed)
    counter_lock = threading.Lock()
    harness_config = make_harness_config(config["runtime"])
    retry_config = config["retry"]

    def worker_loop(worker_index: int) -> None:
        nonlocal completed_counter
        harness: ToolathlonVMVMHarness | None = None
        try:
            while not stop_event.is_set():
                try:
                    trial = work_queue.get_nowait()
                except queue.Empty:
                    return
                try:
                    max_attempts = max_infrastructure_attempts
                    first_attempt = unfinished_attempt_counts.get(trial.key, 0) + 1
                    if first_attempt > max_attempts:
                        message = f"Infrastructure retries already exhausted for {trial.key}"
                        with fatal_lock:
                            fatal_errors.append(message)
                        logger.error(message)
                        continue
                    for attempt_number in range(first_attempt, max_attempts + 1):
                        if stop_event.is_set():
                            return
                        try:
                            if harness is None:
                                harness = ToolathlonVMVMHarness(
                                    harness_config,
                                    proxy_server.server_port,
                                    snapshot_worker_path,
                                    snapshot_local_tools_path,
                                    snapshot_schemas_path,
                                )
                                try:
                                    harness.start()
                                except VMVMCommandFailed:
                                    raise
                                except Exception as error:
                                    harness.close()
                                    harness = None
                                    raise VMVMCommandLost(f"VMVM startup failed: {error}") from error
                            request = _make_request(trial, config, endpoint, fingerprint)
                            payload, command = harness.run_trial(request, attempt_number)
                            attempts.append(
                                {
                                    "worker": worker_index,
                                    "attempt": attempt_number,
                                    "task_id": trial.task_id,
                                    "trial": trial.trial,
                                    "status": payload.get("status"),
                                    "error": payload.get("error"),
                                    "command": command,
                                    "time": time.time(),
                                }
                            )
                            if payload.get("status") == "retryable_error":
                                if attempt_number == max_attempts:
                                    message = (
                                        f"Infrastructure retries exhausted for {trial.key}: {payload.get('error')}"
                                    )
                                    with fatal_lock:
                                        fatal_errors.append(message)
                                    logger.error(message)
                                    break
                                time.sleep(float(retry_config["retry_delay_seconds"]) * attempt_number)
                                continue
                            if payload.get("status") == "fatal_error":
                                raise VMVMCommandFailed(f"Fatal worker error for {trial.key}: {payload.get('error')}")
                            if payload.get("status") not in SCORED_STATUSES:
                                raise VMVMCommandFailed(
                                    f"Unknown worker status for {trial.key}: {payload.get('status')}"
                                )
                            payload["worker"] = worker_index
                            payload["attempt"] = attempt_number
                            payload["vmvm"] = harness.debugging_info()
                            results.append(payload)
                            with counter_lock:
                                completed_counter += 1
                                logger.info(
                                    "completed %d/%d %s reward=%s status=%s",
                                    completed_counter,
                                    expected_total,
                                    trial.task_id,
                                    payload.get("reward"),
                                    payload.get("status"),
                                )
                            break
                        except VMVMCommandLost as error:
                            attempts.append(
                                {
                                    "worker": worker_index,
                                    "attempt": attempt_number,
                                    "task_id": trial.task_id,
                                    "trial": trial.trial,
                                    "status": "vmvm_lost",
                                    "error": str(error),
                                    "time": time.time(),
                                }
                            )
                            if harness is not None:
                                harness.close()
                            harness = None
                            if attempt_number == max_attempts:
                                message = f"VMVM retries exhausted for {trial.key}: {error}"
                                with fatal_lock:
                                    fatal_errors.append(message)
                                logger.error(message)
                                break
                            time.sleep(float(retry_config["retry_delay_seconds"]) * attempt_number)
                        except VMVMCommandFailed as error:
                            attempts.append(
                                {
                                    "worker": worker_index,
                                    "attempt": attempt_number,
                                    "task_id": trial.task_id,
                                    "trial": trial.trial,
                                    "status": "fatal_harness_error",
                                    "error": str(error),
                                    "time": time.time(),
                                }
                            )
                            raise
                finally:
                    work_queue.task_done()
        except Exception as error:
            with fatal_lock:
                fatal_errors.append(f"worker {worker_index}: {type(error).__name__}: {error}")
            stop_event.set()
            logger.exception("worker %d failed", worker_index)
        finally:
            if harness is not None:
                harness.close()

    active_workers = min(worker_count, max(1, len(pending)))
    try:
        if pending:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=active_workers,
                thread_name_prefix="toolathlon-vmvm",
            ) as executor:
                futures = [executor.submit(worker_loop, worker_index) for worker_index in range(active_workers)]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
    finally:
        write_proxy_summary(proxy_server, output_dir / "proxy_summary.json")
        stop_proxy(proxy_server, proxy_thread)

    summary = _summary(
        results_path,
        len(selected),
        trial_indices,
        config.get("reference") if full_run else None,
    )
    _write_json(output_dir / "summary.json", summary)
    metadata["finished_at"] = time.time()
    metadata["summary"] = summary
    metadata["fatal_errors"] = fatal_errors
    _write_json(output_dir / "run_metadata.json", metadata)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if fatal_errors:
        raise RuntimeError("; ".join(fatal_errors))
    if not summary["complete"]:
        raise RuntimeError(f"Evaluation incomplete: {summary['completed']}/{expected_total}")
    if (
        full_run
        and config.get("reference", {}).get("require_exact_reproduction", False)
        and not summary["exact_reproduction"]
    ):
        raise RuntimeError(
            f"Toolathlon parity failed: score={summary['passed']}/{expected_total}, "
            f"environment_compatible={summary['environment_compatible']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
