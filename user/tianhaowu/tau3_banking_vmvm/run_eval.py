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
import subprocess
import threading
import time
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assets import TAU2_COMMIT, load_task_ids, prepare_tau2_archive, sha256
from audit import SCORED_STATUSES, load_jsonl, write_summary
from harness import (
    Tau3VMVMHarness,
    VMVMCommandFailed,
    VMVMCommandLost,
    make_harness_config,
)
from proxy import Route, start_proxy, stop_proxy, write_proxy_summary

logger = logging.getLogger("tau3_banking_vmvm")
HERE = Path(__file__).resolve().parent
EMPTY_RESPONSE_RETRY_COMMIT = "60c2a0dbf974ea7533456a4706f837c3a6d14afc"


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Trial:
    task_id: str
    trial: int
    seed: int

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


def _load_info_endpoint(section: dict[str, Any], override_url: str | None = None) -> Endpoint:
    info: dict[str, Any] = {}
    if info_path := section.get("info_path"):
        info = json.loads(Path(info_path).expanduser().read_text())
    base_url = override_url or os.getenv(section.get("base_url_env", "")) or section.get("base_url") or info.get("url")
    if not base_url:
        raise ValueError(f"No endpoint URL configured for model {section.get('model')}")
    api_key = os.getenv(section.get("api_key_env", "")) or section.get("api_key") or info.get("api_key") or "EMPTY"
    model = section.get("model") or info.get("model")
    if not model:
        raise ValueError("Endpoint model is missing")
    return Endpoint(_normalize_base_url(str(base_url)), str(api_key), str(model))


def _slurm_job_node(job_id: str) -> str:
    result = subprocess.run(
        ["squeue", "-h", "-j", job_id, "-o", "%N"],
        check=True,
        capture_output=True,
        text=True,
    )
    nodelists = [line.strip() for line in result.stdout.splitlines() if line.strip() and line.strip() != "(null)"]
    if len(nodelists) != 1:
        raise ValueError(f"Expected one running allocation for Slurm job {job_id}, found {nodelists}")
    expanded = subprocess.run(
        ["scontrol", "show", "hostnames", nodelists[0]],
        check=True,
        capture_output=True,
        text=True,
    )
    nodes = [line.strip() for line in expanded.stdout.splitlines() if line.strip()]
    if not nodes:
        raise ValueError(f"Slurm job {job_id} has no allocated nodes")
    return nodes[0]


def _latest_slurm_job(job_name: str) -> str:
    result = subprocess.run(
        ["squeue", "-h", "-u", os.environ["USER"], "-n", job_name, "-t", "RUNNING", "-o", "%i"],
        check=True,
        capture_output=True,
        text=True,
    )
    job_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not job_ids:
        raise ValueError(f"No running Slurm job named {job_name!r}")
    return max(job_ids, key=int)


def _load_policy_endpoint(section: dict[str, Any], override_url: str | None, override_job_id: str | None) -> Endpoint:
    if override_url or os.getenv(section.get("base_url_env", "")) or section.get("base_url"):
        return _load_info_endpoint(section, override_url)
    job_id = override_job_id or os.getenv(section.get("slurm_job_id_env", "")) or section.get("slurm_job_id")
    if not job_id:
        job_id = _latest_slurm_job(section["slurm_job_name"])
    node = _slurm_job_node(str(job_id))
    return Endpoint(
        base_url=f"http://{node}:{int(section['port'])}",
        api_key=os.getenv(section.get("api_key_env", "")) or "EMPTY",
        model=section["model"],
    )


def _probe(endpoint: Endpoint) -> None:
    request = urllib.request.Request(
        endpoint.base_url + "/v1/models",
        headers={"Authorization": f"Bearer {endpoint.api_key}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        payload = json.load(response)
    model_ids = {str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict)}
    if endpoint.model not in model_ids:
        raise ValueError(f"Endpoint {endpoint.base_url} does not advertise {endpoint.model!r}: {sorted(model_ids)}")


def _semantic_config(config: dict[str, Any]) -> dict[str, Any]:
    endpoint_location_keys = {
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
    return {
        "source": config["source"],
        "benchmark": config["benchmark"],
        "policy": {key: value for key, value in config["policy"].items() if key not in endpoint_location_keys},
        "user": {key: value for key, value in config["user"].items() if key not in endpoint_location_keys},
        "judge": {key: value for key, value in config["judge"].items() if key not in endpoint_location_keys},
        "retry": config["retry"],
    }


def _fingerprint(config: dict[str, Any]) -> str:
    payload = json.dumps(_semantic_config(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_config(config: dict[str, Any]) -> None:
    if config["source"].get("empty_response_retry_commit") != EMPTY_RESPONSE_RETRY_COMMIT:
        raise ValueError(
            f"The empty-response retry behavior must reference NVIDIA Tau2 commit {EMPTY_RESPONSE_RETRY_COMMIT}"
        )
    benchmark = config["benchmark"]
    if benchmark["domain"] != "banking_knowledge":
        raise ValueError("This runner supports only the Tau3 banking_knowledge domain")
    if benchmark["retrieval_config"] != "bm25_grep":
        raise ValueError("The parity configuration requires bm25_grep retrieval")
    if int(benchmark["expected_tasks"]) != 97:
        raise ValueError("Tau3 Banking v1.0.1 must contain exactly 97 tasks")
    policy = config["policy"]
    if policy["model"] != "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16":
        raise ValueError("The parity policy must be NVIDIA Nemotron 3 Super 120B A12B BF16")
    if policy.get("thinking") is not True or policy.get("thinking_template_key") != "enable_thinking":
        raise ValueError("Nemotron parity requires enable_thinking=true")
    if policy.get("skip_special_tokens") is not False:
        raise ValueError("Nemotron parity requires skip_special_tokens=false")
    if int(policy.get("empty_response_attempts", 0)) != 5:
        raise ValueError("Nemotron parity requires five empty-response attempts")
    user = config["user"]
    if user["model"] != "Kimi-K2.6":
        raise ValueError("The requested user simulator is Kimi-K2.6")
    if user.get("thinking") is not False or user.get("thinking_template_key") != "thinking":
        raise ValueError("The requested Kimi user simulator must be non-thinking")
    if int(user.get("max_tokens", 0)) != 8192:
        raise ValueError("The requested Kimi user simulator token cap is 8192")
    if int(user.get("empty_response_attempts", 0)) != 30:
        raise ValueError("Kimi user parity requires 30 empty-response attempts")
    judge = config["judge"]
    if judge["model"] != "Kimi-K2.6":
        raise ValueError("The requested NL-assertion judge is Kimi-K2.6")
    if judge.get("thinking") is not True or judge.get("thinking_template_key") != "thinking":
        raise ValueError("The requested Kimi judge must use thinking mode")
    expected_session_headers = {
        "policy": "x-session-id",
        "user": "x-litellm-session-id",
        "judge": "x-litellm-session-id",
    }
    for role, expected_header in expected_session_headers.items():
        section = config[role]
        if section.get("sticky_session") is not True:
            raise ValueError(f"{role}.sticky_session must be true")
        actual_header = str(section.get("sticky_session_header", "")).lower()
        if actual_header != expected_header:
            raise ValueError(f"{role}.sticky_session_header must be {expected_header!r}, got {actual_header!r}")
    if float(config["retry"].get("provider_retry_delay_seconds", 0)) <= 0:
        raise ValueError("Provider retry delay must be positive")
    if float(config["retry"].get("proxy_recovery_timeout_seconds", 0)) <= 0:
        raise ValueError("Proxy recovery timeout must be positive")
    if int(config["retry"].get("max_vmvm_retries", -1)) < 0:
        raise ValueError("VMVM retry count must be nonnegative")
    if float(config["retry"].get("vmvm_retry_delay_seconds", 0)) <= 0:
        raise ValueError("VMVM retry delay must be positive")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(temporary, path)


def _completed_keys(results_path: Path, fingerprint: str) -> set[tuple[str, int]]:
    completed: set[tuple[str, int]] = set()
    for row in load_jsonl(results_path):
        if row.get("config_fingerprint") != fingerprint:
            raise ValueError(f"Existing result has a different config fingerprint: {row.get('config_fingerprint')}")
        if row.get("status") not in SCORED_STATUSES:
            raise ValueError(f"Unexpected status in results file: {row.get('status')}")
        key = (str(row["task_id"]), int(row["trial"]))
        if key in completed:
            raise ValueError(f"Duplicate result in {results_path}: {key}")
        completed.add(key)
    return completed


def _unfinished_attempt_counts(
    attempts_path: Path,
    completed: set[tuple[str, int]],
) -> dict[tuple[str, int], int]:
    histories: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in load_jsonl(attempts_path):
        key = (str(row["task_id"]), int(row["trial"]))
        if key not in completed:
            histories.setdefault(key, []).append(row)

    counts: dict[tuple[str, int], int] = {}
    for key, rows in histories.items():
        attempt_numbers = [int(row["attempt"]) for row in rows]
        if attempt_numbers != list(range(1, len(rows) + 1)):
            raise ValueError(f"Cannot resume non-contiguous attempts for {key}: {attempt_numbers}")
        statuses = [row.get("status") for row in rows]
        if any(status != "vmvm_lost" for status in statuses):
            raise ValueError(f"Cannot safely resume unscored non-VMVM attempts for {key}: {statuses}")
        counts[key] = len(rows)
    return counts


def _build_trials(task_ids: list[str], benchmark: dict[str, Any]) -> list[Trial]:
    generator = random.Random(int(benchmark["seed"]))
    seeds = [generator.randint(0, 1_000_000) for _ in range(int(benchmark["num_trials"]))]
    return [
        Trial(task_id=task_id, trial=trial, seed=seeds[trial])
        for trial in range(int(benchmark["num_trials"]))
        for task_id in task_ids
    ]


def _make_request(
    trial: Trial,
    config: dict[str, Any],
    policy: Endpoint,
    user: Endpoint,
    judge: Endpoint,
    fingerprint: str,
) -> dict[str, Any]:
    return {
        "task_id": trial.task_id,
        "trial": trial.trial,
        "seed": trial.seed,
        "source_commit": config["source"]["commit"],
        "config_fingerprint": fingerprint,
        "benchmark": config["benchmark"],
        "policy": config["policy"] | {"model": policy.model},
        "user": config["user"] | {"model": user.model},
        "judge": config["judge"] | {"model": judge.model},
        "retry": config["retry"],
    }


def _copy_run_config(config_path: Path, output_dir: Path) -> None:
    destination = output_dir / "config.toml"
    if destination.exists() and destination.read_bytes() != config_path.read_bytes():
        raise ValueError(f"Output directory already contains a different config: {destination}")
    if not destination.exists():
        shutil.copy2(config_path, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--policy-base-url")
    parser.add_argument("--policy-job-id")
    parser.add_argument("--task-id", action="append")
    parser.add_argument("--trial", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
    config_path = args.config.resolve()
    config = tomllib.loads(config_path.read_text())
    _validate_config(config)
    if config["source"]["commit"] != TAU2_COMMIT:
        raise ValueError(f"This harness is audited for Tau2 commit {TAU2_COMMIT}")
    fingerprint = _fingerprint(config)
    output_dir = (args.output_dir or Path(config["output_dir"])).expanduser().resolve()
    cache_dir = Path(config["source"]["cache_dir"]).expanduser().resolve()
    archive = prepare_tau2_archive(cache_dir)
    if sha256(archive) != json.loads(archive.with_suffix(archive.suffix + ".json").read_text())["slim_sha256"]:
        raise ValueError(f"Slim Tau2 archive checksum mismatch: {archive}")
    task_ids = load_task_ids(archive)
    expected_tasks = int(config["benchmark"]["expected_tasks"])
    if len(task_ids) != expected_tasks:
        raise ValueError(f"Expected {expected_tasks} banking tasks, found {len(task_ids)}")
    if args.task_id:
        unknown = set(args.task_id) - set(task_ids)
        if unknown:
            raise ValueError(f"Unknown banking task IDs: {sorted(unknown)}")
        task_ids = [task_id for task_id in task_ids if task_id in set(args.task_id)]
    if args.limit is not None:
        task_ids = task_ids[: args.limit]
    trials = _build_trials(task_ids, config["benchmark"])
    if args.trial is not None:
        trials = [trial for trial in trials if trial.trial == args.trial]

    if args.dry_run:
        print(
            json.dumps(
                {
                    "config": str(config_path),
                    "fingerprint": fingerprint,
                    "source_archive": str(archive),
                    "source_archive_sha256": sha256(archive),
                    "tasks": len(task_ids),
                    "trials": len(trials),
                    "workers": args.workers or config["runtime"]["workers"],
                    "first_trials": [trial.__dict__ for trial in trials[:5]],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    policy = _load_policy_endpoint(config["policy"], args.policy_base_url, args.policy_job_id)
    user = _load_info_endpoint(config["user"])
    judge = _load_info_endpoint(config["judge"])
    for endpoint in (policy, user, judge):
        _probe(endpoint)

    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_run_config(config_path, output_dir)
    results_path = output_dir / "results.jsonl"
    attempts_path = output_dir / "attempts.jsonl"
    proxy_audit_path = output_dir / "proxy_requests.jsonl"
    results = JsonlStore(results_path)
    attempts = JsonlStore(attempts_path)
    completed = _completed_keys(results_path, fingerprint)
    unfinished_attempt_counts = _unfinished_attempt_counts(attempts_path, completed)
    pending = [trial for trial in trials if trial.key not in completed]
    expected_total = len(trials)
    metadata = {
        "schema_version": 2,
        "config_fingerprint": fingerprint,
        "source_commit": TAU2_COMMIT,
        "source_archive": str(archive),
        "source_archive_sha256": sha256(archive),
        "policy": {"base_url": policy.base_url, "model": policy.model},
        "user": {"base_url": user.base_url, "model": user.model},
        "judge": {"base_url": judge.base_url, "model": judge.model},
        "task_count": len(task_ids),
        "task_ids": task_ids,
        "trial_ids": sorted({trial.trial for trial in trials}),
        "expected_total": expected_total,
        "resumed": len(completed),
        "resumed_vmvm_attempts": sum(unfinished_attempt_counts.values()),
        "started_at": time.time(),
    }
    _write_json(output_dir / "run_metadata.json", metadata)

    routes = [
        Route("policy", "/policy", policy.base_url, policy.api_key),
        Route("user", "/user", user.base_url, user.api_key),
        Route("judge", "/judge", judge.base_url, judge.api_key),
    ]
    proxy_server, proxy_thread = start_proxy(
        routes,
        proxy_audit_path,
        int(config["runtime"]["request_timeout_seconds"]),
    )
    work_queue: queue.Queue[Trial] = queue.Queue()
    for trial in pending:
        work_queue.put(trial)
    stop_event = threading.Event()
    fatal_errors: list[str] = []
    fatal_lock = threading.Lock()
    completed_counter = len(completed)
    counter_lock = threading.Lock()
    retry_config = config["retry"]
    harness_config = make_harness_config(config["runtime"])

    def worker_loop(worker_index: int) -> None:
        nonlocal completed_counter
        harness: Tau3VMVMHarness | None = None
        try:
            while not stop_event.is_set():
                try:
                    trial = work_queue.get_nowait()
                except queue.Empty:
                    return
                try:
                    max_attempts = int(retry_config["max_vmvm_retries"]) + 1
                    first_attempt = unfinished_attempt_counts.get(trial.key, 0) + 1
                    if first_attempt > max_attempts:
                        raise VMVMCommandFailed(f"VMVM retries already exhausted for {trial.key}")
                    for attempt_number in range(first_attempt, max_attempts + 1):
                        if stop_event.is_set():
                            return
                        try:
                            if harness is None:
                                harness = Tau3VMVMHarness(
                                    harness_config,
                                    proxy_server.server_port,
                                    archive,
                                    HERE / "worker.py",
                                    HERE / "pyproject.toml",
                                )
                                try:
                                    harness.start()
                                except VMVMCommandFailed:
                                    raise
                                except Exception as error:
                                    harness.close()
                                    harness = None
                                    raise VMVMCommandLost(f"VMVM startup failed: {error}") from error
                            request = _make_request(trial, config, policy, user, judge, fingerprint)
                            payload, command = harness.run_trial(request, attempt_number)
                            attempt_row = {
                                "worker": worker_index,
                                "attempt": attempt_number,
                                "task_id": trial.task_id,
                                "trial": trial.trial,
                                "status": payload.get("status"),
                                "error": payload.get("error"),
                                "command": command,
                                "time": time.time(),
                            }
                            attempts.append(attempt_row)
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
                                    "completed %d/%d %s trial=%d reward=%s status=%s",
                                    completed_counter,
                                    expected_total,
                                    trial.task_id,
                                    trial.trial,
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
                                raise VMVMCommandFailed(f"VMVM retries exhausted for {trial.key}: {error}") from error
                            time.sleep(float(retry_config["vmvm_retry_delay_seconds"]) * attempt_number)
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

    worker_count = min(int(args.workers or config["runtime"]["workers"]), max(1, len(pending)))
    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="tau3-vmvm"
        ) as executor:
            futures = [executor.submit(worker_loop, index) for index in range(worker_count)]
            for future in concurrent.futures.as_completed(futures):
                future.result()
    finally:
        write_proxy_summary(proxy_server, output_dir / "proxy_summary.json")
        stop_proxy(proxy_server, proxy_thread)

    summary = write_summary(results_path, output_dir / "summary.json", expected_total)
    metadata["finished_at"] = time.time()
    metadata["summary"] = summary
    metadata["fatal_errors"] = fatal_errors
    _write_json(output_dir / "run_metadata.json", metadata)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if fatal_errors:
        raise RuntimeError("; ".join(fatal_errors))
    if not summary["complete"]:
        raise RuntimeError(f"Evaluation incomplete: {summary['completed']}/{expected_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
