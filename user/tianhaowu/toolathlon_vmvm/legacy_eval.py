from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shlex
import statistics
import tarfile
import time
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

from harness import ToolathlonVMVMHarness, VMVMCommandFailed, VMVMCommandLost, make_harness_config
from proxy import Route, start_proxy, stop_proxy, write_proxy_summary

logger = logging.getLogger("toolathlon_official_vmvm")
HERE = Path(__file__).resolve().parent
RESULT_MARKER = "__TOOLATHLON_JSON__="


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _load_endpoint(section: dict[str, Any]) -> tuple[str, str, str]:
    info = json.loads(Path(section["info_path"]).expanduser().read_text())
    base_url = str(info["url"]).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return base_url, str(info.get("api_key") or "EMPTY"), str(section["model"])


def _probe_endpoint(base_url: str, api_key: str, model: str) -> None:
    request = urllib.request.Request(
        f"{base_url}/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        payload = json.load(response)
    models = {str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict)}
    if model not in models:
        raise ValueError(f"Endpoint does not advertise {model!r}: {sorted(models)}")


def _fingerprint(config: dict[str, Any]) -> str:
    payload = {
        "source": config["source"],
        "benchmark": config["benchmark"],
        "model": {
            key: value
            for key, value in config["model"].items()
            if key not in {"api_key", "api_key_env", "base_url", "base_url_env", "info_path"}
        },
        "official_service": config["official_service"],
        "runtime": config["runtime"],
        "reference": config["reference"],
        "runner": {
            name: _sha256(HERE / name)
            for name in ("legacy_eval.py", "legacy_worker.py", "harness.py", "proxy.py", "vmvm_backend.py")
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate(config: dict[str, Any]) -> None:
    benchmark = config["benchmark"]
    model = config["model"]
    service = config["official_service"]
    reference = config["reference"]
    if benchmark.get("suite") != "toolathlon-verified":
        raise ValueError("The official v1.3 service runner is pinned to Toolathlon-Verified")
    if int(benchmark["expected_tasks"]) != 108 or int(benchmark["num_trials"]) != 3:
        raise ValueError("Toolathlon-Verified leaderboard parity requires 108 tasks and three trials")
    if int(benchmark["max_steps"]) != 100:
        raise ValueError("Toolathlon-Verified uses a 100-step agent limit")
    if int(benchmark["task_timeout_seconds"]) != 5400:
        raise ValueError("Toolathlon-Verified uses a 5,400-second per-task timeout")
    if model["model"] != "Kimi-K2.6":
        raise ValueError("The requested parity model is Kimi-K2.6")
    if "temperature" in model or "top_p" in model:
        raise ValueError("Toolathlon-Verified leaves temperature and top_p at provider defaults")
    if int(model["max_tokens"]) != 65536:
        raise ValueError("Toolathlon-Verified uses max_tokens=65536")
    if not bool(model["thinking"]):
        raise ValueError("The Kimi K2.6 leaderboard run uses thinking mode")
    if int(config["runtime"]["workers"]) != 10:
        raise ValueError("The live official service limits submissions to 10 workers")
    if str(service["client_version"]) != "1.3" or str(service["ws_client_version"]) != "1.3":
        raise ValueError("Toolathlon-Verified requires client and WebSocket protocol 1.3")
    if int(service.get("max_trial_infrastructure_retries", 2)) < 0:
        raise ValueError("max_trial_infrastructure_retries must be nonnegative")
    expected = {
        "target_total_passes": 188,
        "target_any_passes": 78,
        "target_all_passes": 45,
        "pass_at_1_percent": 58.0,
        "pass_at_1_std_percent": 4.9,
        "pass_at_3_percent": 72.2,
        "pass_pow_3_percent": 41.7,
    }
    for key, value in expected.items():
        if reference[key] != value:
            raise ValueError(f"Verified leaderboard reference {key} must be {value}")


def _parse_marker(output: str) -> dict[str, Any]:
    lines = [line.removeprefix(RESULT_MARKER) for line in output.splitlines() if line.startswith(RESULT_MARKER)]
    if not lines:
        raise VMVMCommandFailed(f"VMVM command returned no result marker: {output[-4000:]}")
    payload = json.loads(lines[-1])
    if not isinstance(payload, dict):
        raise VMVMCommandFailed("VMVM result marker did not contain an object")
    return payload


def _remote_command(*arguments: str) -> str:
    command = [
        "uv",
        "run",
        "--project",
        "/workspace",
        "--no-sync",
        "python",
        "/opt/toolathlon/legacy_worker.py",
        *arguments,
    ]
    return " ".join(shlex.quote(argument) for argument in command)


def _run_remote(
    harness: ToolathlonVMVMHarness,
    command: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    result = harness.run_command(command, timeout=timeout)
    if result["exit_code"] < 0:
        raise VMVMCommandLost(
            "Official-service VMVM command lost transport: "
            f"error_type={result['error_type']} output={result['output'][-4000:]}"
        )
    return result


def _probe_remote_model(
    harness: ToolathlonVMVMHarness,
    model: str,
    *,
    attempts: int = 3,
    delay_seconds: float = 5,
) -> str:
    last_output = ""
    for attempt in range(1, attempts + 1):
        model_base_url = harness.ensure_model_tunnel() + "/model/v1"
        result = _run_remote(
            harness,
            _remote_command(
                "probe-model",
                "--model-base-url",
                model_base_url,
                "--api-key",
                "vmvm-proxy",
                "--model",
                model,
            ),
            timeout=60,
        )
        last_output = result["output"][-4000:]
        if result["exit_code"] == 0:
            _parse_marker(result["output"])
            current_base_url = harness.ensure_model_tunnel() + "/model/v1"
            if current_base_url == model_base_url:
                return model_base_url
            logger.warning("VMVM model tunnel changed during its liveness probe; probing the replacement")
        elif result["exit_code"] == 75:
            logger.warning(
                "VMVM model tunnel probe failed (%d/%d): %s",
                attempt,
                attempts,
                last_output[-2000:],
            )
        else:
            raise VMVMCommandFailed(f"Unrecoverable model tunnel probe failure: {last_output}")
        if attempt < attempts:
            time.sleep(delay_seconds)
    raise VMVMCommandLost(f"VMVM model tunnel failed {attempts} liveness probes: {last_output}")


def _start_harness(
    config: dict[str, Any],
    proxy_port: int,
) -> ToolathlonVMVMHarness:
    harness = ToolathlonVMVMHarness(
        make_harness_config(config["runtime"]),
        proxy_port,
        HERE / "worker.py",
        HERE / "local_tools.py",
        HERE / "tool_schemas.json",
    )
    try:
        harness.start()
        harness.transfer((HERE / "legacy_worker.py").read_bytes(), "/opt/toolathlon/legacy_worker.py")
    except VMVMCommandFailed:
        harness.close()
        raise
    except Exception as error:
        harness.close()
        raise VMVMCommandLost(f"Official-service VMVM startup failed: {error}") from error
    return harness


def _safe_extract(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"Archive member escapes output directory: {member.name}")
        archive.extractall(destination, filter="data")


def _proxy_requests_since(proxy_log_path: Path, state: dict[str, Any]) -> int | None:
    def count_requests(lines: Any) -> int:
        requests = 0
        for line in lines:
            if not line.strip():
                continue
            event = json.loads(line)
            if not str(event.get("path", "")).endswith("/models"):
                requests += 1
        return requests

    offset = state.get("proxy_log_offset")
    if offset is not None:
        with proxy_log_path.open("rb") as handle:
            handle.seek(int(offset))
            end_offset = state.get("proxy_log_end_offset")
            if end_offset is not None:
                length = int(end_offset) - int(offset)
                if length < 0:
                    raise ValueError("proxy_log_end_offset precedes proxy_log_offset")
                return count_requests(handle.read(length).splitlines())
            return count_requests(handle)

    submitted_at = state.get("submitted_at")
    if submitted_at is None or not proxy_log_path.exists():
        return None
    requests = 0
    finished_at = state.get("finished_at")
    with proxy_log_path.open() as handle:
        for line in handle:
            event = json.loads(line)
            timestamp = float(event.get("timestamp", 0))
            is_generation_request = not str(event.get("path", "")).endswith("/models")
            if (
                is_generation_request
                and timestamp >= float(submitted_at)
                and (finished_at is None or timestamp <= float(finished_at))
            ):
                requests += 1
    return requests


def _audit_trial(
    trial_dir: Path,
    expected_total: int,
    *,
    model_proxy_requests: int | None = None,
) -> dict[str, Any]:
    stats_path = trial_dir / "service_results" / "eval_stats.json"
    stats = json.loads(stats_path.read_text())
    status_breakdown = stats.get("status_breakdown", {})
    preprocess = status_breakdown.get("preprocess", {})
    running = status_breakdown.get("running", {})
    evaluation = status_breakdown.get("evaluation", {})
    total = int(stats.get("total_tasks", 0))
    passes = int(evaluation.get("pass_count", round(float(stats.get("average_success_rate", 0)) * total)))
    fails = int(evaluation.get("fail_count", max(0, total - passes)))
    nulls = int(evaluation.get("null_count", max(0, total - passes - fails)))
    pass_tasks = sorted(str(task) for task in evaluation.get("pass_tasks", []))
    fail_tasks = sorted(str(task) for task in evaluation.get("fail_tasks", []))
    null_tasks = sorted(str(task) for task in evaluation.get("null_tasks", []))
    if passes != len(pass_tasks):
        raise ValueError(f"Pass count/list mismatch in {stats_path}: {passes} != {len(pass_tasks)}")
    if fails != len(fail_tasks) or nulls != len(null_tasks):
        raise ValueError(f"Fail/null count mismatch in {stats_path}")
    task_ids = pass_tasks + fail_tasks + null_tasks
    if len(set(task_ids)) != total:
        raise ValueError(f"Task list mismatch in {stats_path}: {len(set(task_ids))} != {total}")
    report = {
        "source": "official_toolathlon_verified_service",
        "stats_path": str(stats_path),
        "total_tasks": total,
        "passes": passes,
        "fails": fails,
        "nulls": nulls,
        "pass_at_1_percent": 100 * passes / expected_total,
        "expected_total": expected_total,
        "pass_tasks": pass_tasks,
        "fail_tasks": fail_tasks,
        "null_tasks": null_tasks,
        "average_turns": float(stats.get("average_turns", 0)),
        "average_tool_calls": float(stats.get("average_tool_calls", 0)),
        "preprocess_done": int(preprocess.get("done_count", 0)),
        "preprocess_failed": int(preprocess.get("fail_count", 0)),
        "running_done": int(running.get("done_count", 0)),
        "running_failed": int(running.get("fail_count", 0)),
        "complete": total == expected_total and passes + fails + nulls == expected_total,
    }
    if model_proxy_requests is not None:
        report["model_proxy_requests"] = model_proxy_requests
    _write_json(trial_dir / "summary.json", report)
    return report


def _is_no_execution_trial(report: dict[str, Any]) -> bool:
    return (
        bool(report.get("complete"))
        and int(report["nulls"]) == int(report["expected_total"])
        and int(report["preprocess_done"]) > 0
        and int(report["running_done"]) == 0
        and int(report["running_failed"]) == int(report["preprocess_done"])
        and float(report["average_turns"]) <= 1
        and float(report["average_tool_calls"]) == 0
    )


def _next_trial_attempt(trial_dir: Path) -> int:
    marker = trial_dir / "attempt_archive.json"
    if marker.exists():
        return int(json.loads(marker.read_text())["attempt"])
    attempts_dir = trial_dir / "attempts"
    attempts = [
        int(path.name.removeprefix("attempt_"))
        for path in attempts_dir.glob("attempt_[0-9][0-9][0-9]")
        if path.is_dir()
    ]
    return max(attempts, default=0) + 1


def _archive_trial_attempt(trial_dir: Path, attempt: int) -> Path:
    marker = trial_dir / "attempt_archive.json"
    if marker.exists():
        marked_attempt = int(json.loads(marker.read_text())["attempt"])
        if marked_attempt != attempt:
            raise ValueError(f"Attempt archive marker is for {marked_attempt}, not {attempt}")
    else:
        _write_json(marker, {"attempt": attempt})
    destination = trial_dir / "attempts" / f"attempt_{attempt:03d}"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("service_state.json", "summary.json", "service_results.tar.gz", "service_results"):
        source = trial_dir / name
        if source.exists():
            target = destination / name
            if target.exists():
                raise ValueError(f"Both active and archived trial artifacts exist: {source}, {target}")
            os.replace(source, target)
    aggregate_summary = trial_dir.parent / "summary.json"
    if aggregate_summary.exists():
        archived_summary = destination / "aggregate_summary.json"
        if archived_summary.exists():
            raise ValueError(
                f"Both active and archived aggregate summaries exist: {aggregate_summary}, {archived_summary}"
            )
        os.replace(aggregate_summary, archived_summary)
    marker.unlink()
    return destination


def _reject_no_execution_trial(
    *,
    trial_dir: Path,
    state: dict[str, Any],
    report: dict[str, Any],
    max_retries: int,
) -> None:
    attempt = int(state.get("attempt") or _next_trial_attempt(trial_dir))
    state["attempt"] = attempt
    state.setdefault("finished_at", time.time())
    state["summary"] = report
    state["infrastructure_failure"] = "all runnable tasks failed before executing a tool"
    _write_json(trial_dir / "service_state.json", state)
    archive = _archive_trial_attempt(trial_dir, attempt)
    if attempt > max_retries:
        raise VMVMCommandFailed(f"Official trial exhausted {max_retries} infrastructure retries; preserved {archive}")
    raise VMVMCommandLost(
        f"Official trial produced no valid executions; preserved {archive} and will submit attempt {attempt + 1}"
    )


def _audit_trials(output_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    expected_tasks = int(config["benchmark"]["expected_tasks"])
    num_trials = int(config["benchmark"]["num_trials"])
    reports = [
        json.loads((output_dir / f"trial_{trial + 1:03d}" / "summary.json").read_text()) for trial in range(num_trials)
    ]
    if not all(report.get("complete") for report in reports):
        raise ValueError("At least one Verified trial is incomplete")

    task_sets = [set(report["pass_tasks"] + report["fail_tasks"] + report["null_tasks"]) for report in reports]
    if any(task_set != task_sets[0] for task_set in task_sets[1:]):
        raise ValueError("Verified trials do not contain the same task IDs")
    pass_sets = [set(report["pass_tasks"]) for report in reports]
    trial_passes = [int(report["passes"]) for report in reports]
    pass_rates = [100 * passes / expected_tasks for passes in trial_passes]
    total_passes = sum(trial_passes)
    any_passes = len(set.union(*pass_sets))
    all_passes = len(set.intersection(*pass_sets))
    reference = config["reference"]
    metrics = {
        "pass_at_1_percent": 100 * total_passes / (expected_tasks * num_trials),
        "pass_at_1_std_percent": statistics.pstdev(pass_rates),
        "pass_at_3_percent": 100 * any_passes / expected_tasks,
        "pass_pow_3_percent": 100 * all_passes / expected_tasks,
    }
    rounded = {key: round(value, 1) for key, value in metrics.items()}
    exact = (
        total_passes == int(reference["target_total_passes"])
        and any_passes == int(reference["target_any_passes"])
        and all_passes == int(reference["target_all_passes"])
        and rounded["pass_at_1_percent"] == float(reference["pass_at_1_percent"])
        and rounded["pass_at_1_std_percent"] == float(reference["pass_at_1_std_percent"])
        and rounded["pass_at_3_percent"] == float(reference["pass_at_3_percent"])
        and rounded["pass_pow_3_percent"] == float(reference["pass_pow_3_percent"])
    )
    report = {
        "source": "official_toolathlon_verified_service",
        "trials": reports,
        "trial_passes": trial_passes,
        "total_passes": total_passes,
        "any_passes": any_passes,
        "all_passes": all_passes,
        "metrics": metrics,
        "metrics_rounded_1dp": rounded,
        "reference": reference,
        "exact": exact,
    }
    _write_json(output_dir / "summary.json", report)
    return report


def _run_official_trial(
    *,
    config: dict[str, Any],
    fingerprint: str,
    harness: ToolathlonVMVMHarness,
    server_url: str,
    model: str,
    trial_index: int,
    output_dir: Path,
    proxy_log_path: Path,
) -> dict[str, Any]:
    service = config["official_service"]
    expected_tasks = int(config["benchmark"]["expected_tasks"])
    trial_number = trial_index + 1
    trial_name = f"trial_{trial_number:03d}"
    trial_dir = output_dir / trial_name
    trial_dir.mkdir(parents=True, exist_ok=True)
    archive_marker = trial_dir / "attempt_archive.json"
    if archive_marker.exists():
        archived_attempt = int(json.loads(archive_marker.read_text())["attempt"])
        archive = _archive_trial_attempt(trial_dir, archived_attempt)
        logger.warning("Finished interrupted official trial archival at %s", archive)
    state_path = trial_dir / "service_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    attempt = int(state.get("attempt") or _next_trial_attempt(trial_dir))
    max_trial_retries = int(service.get("max_trial_infrastructure_retries", 2))

    stats_path = trial_dir / "service_results" / "eval_stats.json"
    if stats_path.exists():
        report = _audit_trial(
            trial_dir,
            expected_tasks,
            model_proxy_requests=_proxy_requests_since(proxy_log_path, state),
        )
        if report.get("complete"):
            if _is_no_execution_trial(report):
                _reject_no_execution_trial(
                    trial_dir=trial_dir,
                    state=state,
                    report=report,
                    max_retries=max_trial_retries,
                )
            logger.info("Skipping completed Verified %s", trial_name)
            return report

    if state and state.get("config_fingerprint") != fingerprint:
        raise ValueError(f"Existing {trial_name} state has a different config fingerprint")

    model_tunnel_url: str | None = None
    if not state.get("job_id"):
        job_id = f"{service['job_id_prefix']}-trial-{trial_number}"
        if attempt > 1:
            job_id += f"-attempt-{attempt}"
        remote_request = f"/opt/toolathlon/{trial_name}_submit_request.json"
        deadline = time.monotonic() + int(service["wait_timeout_seconds"])
        while time.monotonic() <= deadline:
            _probe_remote_model(harness, model)
            status_result = _run_remote(
                harness,
                _remote_command("status", "--server-url", server_url),
                timeout=60,
            )
            if status_result["exit_code"] == 0:
                status_payload = _parse_marker(status_result["output"])
                if not bool(status_payload.get("busy")):
                    model_tunnel_url = _probe_remote_model(harness, model)
                    submit_request = {
                        "client_version": service["client_version"],
                        "mode": "private",
                        "base_url": model_tunnel_url,
                        "api_key": None,
                        "model_name": model,
                        "workers": int(config["runtime"]["workers"]),
                        "custom_job_id": job_id,
                        "skip_container_restart": False,
                        "provider": "unified",
                        "ws_client_version": service["ws_client_version"],
                        "model_params": {"max_tokens": int(config["model"]["max_tokens"])},
                    }
                    harness.transfer(
                        json.dumps(submit_request, indent=2, sort_keys=True).encode(),
                        remote_request,
                    )
                    confirmed_tunnel_url = _probe_remote_model(harness, model)
                    if confirmed_tunnel_url != model_tunnel_url:
                        logger.warning("VMVM model tunnel changed while preparing submission; retrying")
                        continue
                    proxy_log_offset = proxy_log_path.stat().st_size if proxy_log_path.exists() else 0
                    submit_result = _run_remote(
                        harness,
                        _remote_command(
                            "submit",
                            "--server-url",
                            server_url,
                            "--request",
                            remote_request,
                        ),
                        timeout=60,
                    )
                    if submit_result["exit_code"] == 0:
                        submit_payload = _parse_marker(submit_result["output"])
                        state = {
                            "config_fingerprint": fingerprint,
                            "trial": trial_number,
                            "attempt": attempt,
                            "job_id": str(submit_payload["job_id"]),
                            "client_id": str(submit_payload.get("client_id") or ""),
                            "submitted_at": time.time(),
                            "server_url": server_url,
                            "proxy_log_offset": proxy_log_offset,
                        }
                        _write_json(state_path, state)
                        logger.info(
                            "Submitted Verified trial %d/%d as %s",
                            trial_number,
                            int(config["benchmark"]["num_trials"]),
                            state["job_id"],
                        )
                        break
                    if submit_result["exit_code"] != 75:
                        raise VMVMCommandFailed(f"Verified submission failed: {submit_result['output'][-4000:]}")
            elif status_result["exit_code"] == 75:
                logger.warning("Verified service status check failed: %s", status_result["output"][-2000:])
            else:
                raise VMVMCommandFailed(
                    f"Unrecoverable Verified service status failure: {status_result['output'][-4000:]}"
                )
            logger.info("Verified service is busy; waiting for %s", trial_name)
            time.sleep(float(service["poll_interval_seconds"]))
        else:
            raise TimeoutError(f"Verified service did not become available for {trial_name}")

    model_tunnel_url = _probe_remote_model(harness, model)
    remote_output_dir = f"/opt/toolathlon/service_results/{trial_name}_attempt_{attempt:03d}"
    monitor_command = "TOOLATHLON_OPENAI_API_KEY=vmvm-proxy " + _remote_command(
        "monitor",
        "--server-url",
        server_url,
        "--job-id",
        str(state["job_id"]),
        "--model-base-url",
        model_tunnel_url,
        "--ws-proxy-port",
        str(service["ws_proxy_port"]),
        "--output-dir",
        remote_output_dir,
        "--timeout-seconds",
        str(service["evaluation_timeout_seconds"]),
    )
    monitor_result = _run_remote(
        harness,
        monitor_command,
        timeout=int(service["evaluation_timeout_seconds"]) + 300,
    )
    if monitor_result["exit_code"] != 0:
        raise VMVMCommandFailed(
            f"Official Toolathlon monitor failed for {trial_name}: {monitor_result['output'][-8000:]}"
        )

    remote_archive = f"/opt/toolathlon/{trial_name}_service_results.tar.gz"
    pack_result = _run_remote(
        harness,
        _remote_command(
            "pack",
            "--output-dir",
            remote_output_dir,
            "--archive",
            remote_archive,
        ),
        timeout=300,
    )
    if pack_result["exit_code"] != 0:
        raise VMVMCommandFailed(f"Could not pack official results for {trial_name}: {pack_result['output'][-4000:]}")
    archive_path = trial_dir / "service_results.tar.gz"
    archive_path.write_bytes(harness.read_file(remote_archive))
    _safe_extract(archive_path, trial_dir / "service_results")
    state["finished_at"] = time.time()
    state["proxy_log_end_offset"] = proxy_log_path.stat().st_size if proxy_log_path.exists() else 0
    report = _audit_trial(
        trial_dir,
        expected_tasks,
        model_proxy_requests=_proxy_requests_since(proxy_log_path, state),
    )
    state["summary"] = report
    _write_json(state_path, state)
    if not report["complete"]:
        raise ValueError(f"Verified {trial_name} returned incomplete results: {report}")
    if _is_no_execution_trial(report):
        _reject_no_execution_trial(
            trial_dir=trial_dir,
            state=state,
            report=report,
            max_retries=max_trial_retries,
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config_path = args.config.resolve()
    config = tomllib.loads(config_path.read_text())
    _validate(config)
    fingerprint = _fingerprint(config)
    service = config["official_service"]
    output_dir = (args.output_dir or Path(service["output_dir"])).expanduser().resolve()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "config": str(config_path),
                    "config_fingerprint": fingerprint,
                    "mode": "official-toolathlon-verified-service",
                    "model": config["model"]["model"],
                    "tasks": config["benchmark"]["expected_tasks"],
                    "trials": config["benchmark"]["num_trials"],
                    "workers": config["runtime"]["workers"],
                    "server_url": service["server_url"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    saved_config = output_dir / "config.toml"
    if saved_config.exists() and saved_config.read_bytes() != config_path.read_bytes():
        raise ValueError(f"Output directory contains a different config: {saved_config}")
    if not saved_config.exists():
        saved_config.write_bytes(config_path.read_bytes())

    base_url, api_key, model = _load_endpoint(config["model"])
    _probe_endpoint(base_url, api_key, model)
    server_url = str(service["server_url"]).rstrip("/")

    proxy_server, proxy_thread = start_proxy(
        Route("model", "/model", base_url, api_key),
        output_dir / "proxy_requests.jsonl",
        int(config["runtime"]["request_timeout_seconds"]),
    )
    harness: ToolathlonVMVMHarness | None = None
    try:
        for trial_index in range(int(config["benchmark"]["num_trials"])):
            vm_restarts = 0
            while True:
                try:
                    if harness is None:
                        harness = _start_harness(config, proxy_server.server_port)
                    _run_official_trial(
                        config=config,
                        fingerprint=fingerprint,
                        harness=harness,
                        server_url=server_url,
                        model=model,
                        trial_index=trial_index,
                        output_dir=output_dir,
                        proxy_log_path=output_dir / "proxy_requests.jsonl",
                    )
                    break
                except VMVMCommandLost as error:
                    vm_restarts += 1
                    if harness is not None:
                        harness.close()
                    harness = None
                    max_restarts = int(config["runtime"].get("max_vm_restarts", 20))
                    if vm_restarts > max_restarts:
                        raise VMVMCommandFailed(
                            f"Official-service VMVM restarts exhausted for trial {trial_index + 1}: {error}"
                        ) from error
                    logger.warning(
                        "Official-service VMVM lost for trial %d; recreating sandbox (%d/%d): %s",
                        trial_index + 1,
                        vm_restarts,
                        max_restarts,
                        error,
                    )
                    time.sleep(float(config["runtime"].get("vm_restart_delay_seconds", 10)))
        report = _audit_trials(output_dir, config)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["exact"] else 1
    finally:
        write_proxy_summary(proxy_server, output_dir / "proxy_summary.json")
        if harness is not None:
            harness.close()
        stop_proxy(proxy_server, proxy_thread)


if __name__ == "__main__":
    raise SystemExit(main())
