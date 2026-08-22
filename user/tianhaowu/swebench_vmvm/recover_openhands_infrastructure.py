#!/usr/bin/env python3

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import tomllib
from contextlib import ExitStack
from pathlib import Path

FINISHED_STATUS = "ConversationExecutionStatus.FINISHED"
ERROR_STATUS = "ConversationExecutionStatus.ERROR"
INFRASTRUCTURE_ERRORS = {"ProviderError", "SandboxError", "TunnelError"}
VERIFIER_TIMEOUT_ERROR_TYPE = "TasksetError"
VERIFIER_TIMEOUT_ERROR_MESSAGE = "scoring timed out"
REQUIRED_RUN_FILES = (
    "config.toml",
    "implementation.sha256",
    "implementation.tar.gz",
    "implementation_revisions.txt",
    "models.json",
    "results.jsonl",
)
INFERENCE_PROVENANCE_FILES = (
    "inference_config.toml",
    "inference_launcher.sbatch",
    "inference_startup.log",
    "inference_slurm_job.txt",
)
RUNTIME_SOURCE_PREFIXES = (
    "deps/research-environments/environments/swebench_verified_v1/swebench_verified_v1/",
    "deps/verifiers/verifiers/v1/",
    "environments/vmvm_tb_v2/vmvm_tb_v2/",
    "user/tianhaowu/swebench_vmvm/openhands_sdk_harness/",
    "user/tianhaowu/swebench_vmvm/swebench_verified_vmvm/",
)
RUNTIME_SOURCE_FILES = {"user/tianhaowu/swebench_vmvm/swebench_vmvm_compat.py"}
RUNTIME_SOURCE_EXCLUDES = {"user/tianhaowu/swebench_vmvm/openhands_sdk_harness/audit.py"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a new OpenHands result directory by replacing infrastructure-contaminated "
            "rows with independently audited one-task results."
        )
    )
    parser.add_argument("base_dir", type=Path)
    parser.add_argument("--replacement-dir", action="append", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=500)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_sha256(row: dict[str, object]) -> str:
    payload = json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def implementation_contract(path: Path) -> tuple[str, dict[str, str]]:
    members: dict[str, str] = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.name in RUNTIME_SOURCE_EXCLUDES:
                continue
            selected = member.name in RUNTIME_SOURCE_FILES or member.name.startswith(RUNTIME_SOURCE_PREFIXES)
            if not selected:
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"could not read {member.name} from {path}")
            members[member.name] = hashlib.sha256(source.read()).hexdigest()
    if not members:
        raise ValueError(f"implementation archive contains no runtime sources: {path}")
    encoded = json.dumps(members, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest(), members


def run_files(run_dir: Path, *, require_inference: bool = False) -> dict[str, Path]:
    files = {name: run_dir / name for name in REQUIRED_RUN_FILES}
    if require_inference:
        files.update({name: run_dir / name for name in INFERENCE_PROVENANCE_FILES})
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise ValueError(f"run directory is missing required files: {missing}")
    return files


def lock_run(stack: ExitStack, run_dir: Path) -> None:
    lock = stack.enter_context((run_dir / ".writer.lock").open("a+b"))
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise SystemExit(f"an evaluator still owns {run_dir}") from error


def read_single_row(path: Path) -> dict[str, object]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"replacement results must contain exactly one row: {path}")
    return rows[0]


def task(row: dict[str, object]) -> dict[str, object]:
    value = row.get("task")
    if not isinstance(value, dict):
        raise ValueError(f"row {row.get('id')} has no task object")
    return value


def task_name(row: dict[str, object]) -> str:
    name = task(row).get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"row {row.get('id')} has no task name")
    return name


def openhands_metadata(row: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    info = row.get("info")
    sdk = info.get("openhands_sdk") if isinstance(info, dict) else None
    proxy = sdk.get("proxy") if isinstance(sdk, dict) else None
    if not isinstance(sdk, dict) or not isinstance(proxy, dict):
        raise ValueError(f"row {row.get('id')} has no OpenHands proxy metadata")
    return sdk, proxy


def expected_context_limit(row: dict[str, object]) -> bool:
    sdk, proxy = openhands_metadata(row)
    agent = sdk.get("agent")
    if not isinstance(agent, dict):
        return False
    exception = agent.get("exception")
    requests = proxy.get("requests")
    responses = proxy.get("responses")
    details = proxy.get("request_details")
    return (
        row.get("stop_condition") == "context_length"
        and agent.get("execution_status") == ERROR_STATUS
        and isinstance(exception, dict)
        and exception.get("type") == "ConversationRunError"
        and str(exception.get("message", "")).endswith("OpenAIException - rollout stopped: context_length")
        and isinstance(requests, int)
        and responses == requests - 1
        and proxy.get("http_errors") == 1
        and proxy.get("transport_errors") == 0
        and isinstance(details, list)
        and bool(details)
        and isinstance(details[-1], dict)
        and details[-1].get("status") == 400
    )


def infrastructure_contaminated(row: dict[str, object]) -> bool:
    errors = row.get("errors")
    if isinstance(errors, list) and any(
        isinstance(error, dict) and error.get("type") in INFRASTRUCTURE_ERRORS for error in errors
    ):
        return True
    _, proxy = openhands_metadata(row)
    transport_errors = proxy.get("transport_errors")
    http_errors = proxy.get("http_errors")
    has_transport_error = isinstance(transport_errors, int) and transport_errors > 0
    has_unexpected_http_error = isinstance(http_errors, int) and http_errors > 0 and not expected_context_limit(row)
    return has_transport_error or has_unexpected_http_error


def verifier_timed_out(row: dict[str, object]) -> bool:
    errors = row.get("errors")
    if not isinstance(errors, list) or len(errors) != 1:
        return False
    error = errors[0]
    return (
        isinstance(error, dict)
        and error.get("type") == VERIFIER_TIMEOUT_ERROR_TYPE
        and error.get("message") == VERIFIER_TIMEOUT_ERROR_MESSAGE
    )


def validate_same_trajectory_verifier_recovery(
    base: dict[str, object],
    replacement: dict[str, object],
) -> None:
    if base.get("id") != replacement.get("id") or base.get("nodes") != replacement.get("nodes"):
        raise ValueError("verifier recovery changed the model trajectory")
    base_info = base.get("info")
    replacement_info = replacement.get("info")
    if not isinstance(base_info, dict) or not isinstance(replacement_info, dict):
        raise ValueError("verifier recovery is missing result metadata")
    if base_info.get("swebench_candidate_patch") != replacement_info.get("swebench_candidate_patch"):
        raise ValueError("verifier recovery changed the candidate patch")
    recovery = replacement_info.get("swebench_verifier_recovery")
    if not isinstance(recovery, dict) or recovery.get("classification") != "same_trajectory_fresh_verifier":
        raise ValueError("replacement row is not a verifier-only recovery")
    if recovery.get("source_row_sha256") != row_sha256(base):
        raise ValueError("verifier recovery source-row hash does not match")


def verifier_recovery_provenance(
    run_dir: Path,
    row: dict[str, object],
    results_sha256: str,
) -> dict[str, str]:
    info = row.get("info")
    recovery = info.get("swebench_verifier_recovery") if isinstance(info, dict) else None
    if not isinstance(recovery, dict):
        return {}
    paths = {
        "verifier_recovery_manifest": run_dir / "swebench_verifier_recovery.json",
        "verifier_recovery_sources": run_dir / "verifier_recovery_sources.tar.gz",
        "verifier_recovery_source_checksums": run_dir / "verifier_recovery_sources.sha256",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError(f"verifier recovery is missing provenance artifacts: {missing}")
    manifest = json.loads(paths["verifier_recovery_manifest"].read_text())
    if manifest.get("source_trace_id") != row.get("id"):
        raise ValueError("verifier recovery manifest has the wrong trace ID")
    if manifest.get("output_results_sha256") != results_sha256:
        raise ValueError("verifier recovery manifest has the wrong results hash")
    if manifest.get("recovery") != recovery:
        raise ValueError("verifier recovery manifest disagrees with row metadata")
    if recovery.get("source_archive_sha256") != file_sha256(paths["verifier_recovery_sources"]):
        raise ValueError("verifier recovery source archive hash does not match")
    return {name: file_sha256(path) for name, path in paths.items()}


def validate_candidate_patch(row: dict[str, object]) -> None:
    info = row.get("info")
    candidate = info.get("swebench_candidate_patch") if isinstance(info, dict) else None
    if not isinstance(candidate, dict):
        raise ValueError(f"replacement row {row.get('id')} has no candidate-patch metadata")
    patch = candidate.get("patch")
    if not isinstance(patch, str):
        raise ValueError(f"replacement row {row.get('id')} has a non-string candidate patch")
    encoded = patch.encode()
    if candidate.get("bytes") != len(encoded):
        raise ValueError(f"replacement row {row.get('id')} has an invalid candidate-patch byte count")
    if candidate.get("sha256") != hashlib.sha256(encoded).hexdigest():
        raise ValueError(f"replacement row {row.get('id')} has an invalid candidate-patch hash")

    verifier = info.get("swebench_verifier")
    attempts = info.get("swebench_verifier_attempts")
    failures = info.get("swebench_verifier_failures")
    runtime = info.get("swebench_verifier_runtime")
    rewards = row.get("rewards")
    reward = rewards.get("solved") if isinstance(rewards, dict) else None
    if not isinstance(verifier, dict) or verifier.get("resolved") != bool(reward):
        raise ValueError(f"replacement row {row.get('id')} has inconsistent verifier metadata")
    if not isinstance(attempts, int) or attempts < 1 or not isinstance(failures, list):
        raise ValueError(f"replacement row {row.get('id')} has invalid verifier-attempt metadata")
    if not isinstance(runtime, str) or not runtime:
        raise ValueError(f"replacement row {row.get('id')} has no verifier runtime descriptor")


def validate_clean_replacement(row: dict[str, object]) -> None:
    if row.get("is_completed") is not True:
        raise ValueError(f"replacement row {row.get('id')} is not complete")
    if row.get("errors") != []:
        raise ValueError(f"replacement row {row.get('id')} contains serialized errors")
    rewards = row.get("rewards")
    reward = rewards.get("solved") if isinstance(rewards, dict) else None
    if isinstance(reward, bool) or reward not in (0, 0.0, 1, 1.0):
        raise ValueError(f"replacement row {row.get('id')} has invalid solved reward {reward!r}")

    sdk, proxy = openhands_metadata(row)
    agent = sdk.get("agent")
    if not isinstance(agent, dict):
        raise ValueError(f"replacement row {row.get('id')} has no OpenHands agent metadata")
    requests = proxy.get("requests")
    responses = proxy.get("responses")
    if not isinstance(requests, int) or not 1 <= requests <= 200:
        raise ValueError(f"replacement row {row.get('id')} has invalid request count {requests!r}")
    if proxy.get("http_errors") != 0 or proxy.get("transport_errors") != 0:
        raise ValueError(f"replacement row {row.get('id')} contains provider or transport errors")
    if responses != requests:
        raise ValueError(f"replacement row {row.get('id')} has inconsistent request accounting")
    clean_finished = agent.get("execution_status") == FINISHED_STATUS and agent.get("exception") is None
    clean_iteration_limit = (
        agent.get("execution_status") == ERROR_STATUS and agent.get("exception") is None and requests == 200
    )
    if not clean_finished and not clean_iteration_limit:
        raise ValueError(f"replacement row {row.get('id')} is not a clean OpenHands outcome")
    validate_candidate_patch(row)


def config_contract(path: Path) -> dict[str, object]:
    config = tomllib.loads(path.read_text())
    if config.get("taskset", {}).get("id") != "swebench-verified-vmvm":
        raise ValueError(f"config does not use swebench-verified-vmvm: {path}")
    if config.get("harness", {}).get("id") != "openhands_sdk_harness":
        raise ValueError(f"config does not use openhands_sdk_harness: {path}")

    taskset = copy.deepcopy(config["taskset"])
    taskset.pop("tasks", None)
    client = copy.deepcopy(config.get("client") or {})
    client.pop("base_url", None)
    return {
        "taskset": taskset,
        "harness": config["harness"],
        "timeout": config.get("timeout"),
        "retries": config.get("retries"),
        "max_turns": config.get("max_turns"),
        "max_input_tokens": config.get("max_input_tokens"),
        "max_output_tokens": config.get("max_output_tokens"),
        "max_total_tokens": config.get("max_total_tokens"),
        "model": config.get("model"),
        "client": client,
        "sampling": config.get("sampling"),
    }


def model_ids(path: Path) -> set[str]:
    payload = json.loads(path.read_text())
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError(f"invalid model response: {path}")
    identifiers = {entry.get("id") for entry in data if isinstance(entry, dict) and isinstance(entry.get("id"), str)}
    if not identifiers:
        raise ValueError(f"model response has no model IDs: {path}")
    return identifiers


def normalized_task(value: dict[str, object]) -> dict[str, object]:
    normalized = copy.deepcopy(value)
    normalized.pop("idx", None)
    return normalized


def compatible_openhands_metadata(base: dict[str, object], replacement: dict[str, object]) -> bool:
    base_sdk, base_proxy = openhands_metadata(base)
    replacement_sdk, replacement_proxy = openhands_metadata(replacement)
    keys = ("archive_manifest", "system_prompt_sha256", "instruction_sha256")
    return all(base_sdk.get(key) == replacement_sdk.get(key) for key in keys) and base_proxy.get(
        "official_recipe"
    ) == replacement_proxy.get("official_recipe")


def copy_run_files(source: Path, destination: Path) -> None:
    for path in source.iterdir():
        if path.name in {".writer.lock", "results.jsonl"} or path.name.endswith(".tmp"):
            continue
        if path.is_file():
            shutil.copy2(path, destination / path.name)


def write_inference_snapshot(directory: Path, output_dir: Path) -> None:
    names = list(INFERENCE_PROVENANCE_FILES)
    optional = directory / "inference_provenance_source.txt"
    if optional.is_file():
        names.append(optional.name)
    snapshot = directory / "inference_snapshot.sha256"
    with snapshot.open("w") as handle:
        for name in names:
            source = directory / name
            if not source.is_file():
                raise ValueError(f"missing inference provenance artifact: {source}")
            handle.write(f"{file_sha256(source)}  {output_dir / name}\n")
        handle.flush()
        os.fsync(handle.fileno())


def safe_directory_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def main() -> None:
    args = parse_args()
    base_dir = args.base_dir.resolve()
    replacement_dirs = [path.resolve() for path in args.replacement_dir]
    output_dir = args.output_dir.resolve()
    if args.expected_rows < 1:
        raise SystemExit("--expected-rows must be positive")
    if output_dir.exists():
        raise SystemExit(f"refusing to overwrite existing output directory: {output_dir}")
    if base_dir in replacement_dirs or len(set(replacement_dirs)) != len(replacement_dirs):
        raise SystemExit("base and replacement directories must be distinct")

    base_files = run_files(base_dir, require_inference=True)
    replacement_files = {run_dir: run_files(run_dir) for run_dir in replacement_dirs}
    base_contract = config_contract(base_files["config.toml"])
    base_models = model_ids(base_files["models.json"])
    base_runtime_sha256, base_runtime_sources = implementation_contract(base_files["implementation.tar.gz"])

    with ExitStack() as stack:
        lock_run(stack, base_dir)
        for run_dir in replacement_dirs:
            lock_run(stack, run_dir)

        replacements: dict[str, dict[str, object]] = {}
        replacement_provenance: dict[str, dict[str, object]] = {}
        for run_dir, files in replacement_files.items():
            if config_contract(files["config.toml"]) != base_contract:
                raise ValueError(f"replacement config contract differs from the base run: {run_dir}")
            if model_ids(files["models.json"]) != base_models:
                raise ValueError(f"replacement model response differs from the base run: {run_dir}")
            replacement_runtime_sha256, replacement_runtime_sources = implementation_contract(
                files["implementation.tar.gz"]
            )
            if replacement_runtime_sources != base_runtime_sources:
                raise ValueError(f"replacement runtime sources differ from the base run: {run_dir}")
            row = read_single_row(files["results.jsonl"])
            validate_clean_replacement(row)
            name = task_name(row)
            if name in replacements:
                raise ValueError(f"multiple replacement rows supplied for {name}")
            replacements[name] = row
            results_sha256 = file_sha256(files["results.jsonl"])
            replacement_provenance[name] = {
                "directory": str(run_dir),
                "results_sha256": results_sha256,
                "implementation_sha256_file": file_sha256(files["implementation.sha256"]),
                "implementation_archive_sha256": file_sha256(files["implementation.tar.gz"]),
                "implementation_revisions_sha256": file_sha256(files["implementation_revisions.txt"]),
                "models_sha256": file_sha256(files["models.json"]),
                "runtime_contract_sha256": replacement_runtime_sha256,
                "replacement_row_sha256": row_sha256(row),
                "replacement_trace_id": row.get("id"),
                **verifier_recovery_provenance(run_dir, row, results_sha256),
            }

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
        try:
            copy_run_files(base_dir, temporary_dir)
            write_inference_snapshot(temporary_dir, output_dir)
            recovery_sources = temporary_dir / "recovery_sources"
            recovery_sources.mkdir()
            for name, provenance in replacement_provenance.items():
                source_dir = Path(str(provenance["directory"]))
                destination = recovery_sources / safe_directory_name(name)
                destination.mkdir()
                copy_run_files(source_dir, destination)
                shutil.copy2(source_dir / "results.jsonl", destination / "results.jsonl")

            base_results_sha256 = file_sha256(base_files["results.jsonl"])
            seen_replacements: set[str] = set()
            trace_ids: set[str] = set()
            row_count = 0
            recovery_records = []
            output_results = temporary_dir / "results.jsonl"
            with base_files["results.jsonl"].open() as source, output_results.open("x") as destination:
                for line_number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    row_count += 1
                    base_row = json.loads(line)
                    name = task_name(base_row)
                    if name in replacements:
                        if name in seen_replacements:
                            raise ValueError(f"base results contain multiple rows for {name}")
                        is_verifier_recovery = verifier_timed_out(base_row)
                        if not infrastructure_contaminated(base_row) and not is_verifier_recovery:
                            raise ValueError(f"base row for {name} is not recoverable")
                        replacement = copy.deepcopy(replacements[name])
                        if normalized_task(task(base_row)) != normalized_task(task(replacement)):
                            raise ValueError(f"replacement task metadata differs from the base row for {name}")
                        if not compatible_openhands_metadata(base_row, replacement):
                            raise ValueError(f"replacement OpenHands recipe differs from the base row for {name}")
                        if is_verifier_recovery:
                            validate_same_trajectory_verifier_recovery(base_row, replacement)
                        replacement["task"] = copy.deepcopy(task(base_row))
                        info = replacement.get("info")
                        if not isinstance(info, dict):
                            raise ValueError(f"replacement row for {name} has no info object")
                        provenance = replacement_provenance[name]
                        info["openhands_infrastructure_recovery"] = {
                            "classification": (
                                "same_trajectory_fresh_verifier"
                                if is_verifier_recovery
                                else "clean_official_recipe_replacement"
                            ),
                            "base_results_sha256": base_results_sha256,
                            "base_row_sha256": row_sha256(base_row),
                            "base_trace_id": base_row.get("id"),
                            **provenance,
                        }
                        output_row = replacement
                        seen_replacements.add(name)
                        base_rewards = base_row.get("rewards")
                        replacement_rewards = replacement.get("rewards")
                        recovery_records.append(
                            {
                                "line": line_number,
                                "task_idx": task(base_row).get("idx"),
                                "task_name": name,
                                "base_trace_id": base_row.get("id"),
                                "replacement_trace_id": replacement.get("id"),
                                "base_reward": (base_rewards.get("solved") if isinstance(base_rewards, dict) else None),
                                "replacement_reward": (
                                    replacement_rewards.get("solved") if isinstance(replacement_rewards, dict) else None
                                ),
                            }
                        )
                    else:
                        output_row = base_row

                    trace_id = output_row.get("id")
                    if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
                        raise ValueError(f"duplicate or invalid output trace ID {trace_id!r}")
                    trace_ids.add(trace_id)
                    destination.write(json.dumps(output_row, ensure_ascii=False, separators=(",", ":")))
                    destination.write("\n")
                destination.flush()
                os.fsync(destination.fileno())

            missing = set(replacements) - seen_replacements
            if missing:
                raise ValueError(f"replacement tasks were not found in the base results: {sorted(missing)}")
            if row_count != args.expected_rows:
                raise ValueError(f"expected {args.expected_rows} base rows, found {row_count}")

            manifest = {
                "base_directory": str(base_dir),
                "base_results_sha256": base_results_sha256,
                "base_runtime_contract_sha256": base_runtime_sha256,
                "output_directory": str(output_dir),
                "output_results_sha256": file_sha256(output_results),
                "rows": row_count,
                "replacements": recovery_records,
                "replacement_sources": replacement_provenance,
            }
            manifest_path = temporary_dir / "openhands_infrastructure_recovery.json"
            with manifest_path.open("x") as handle:
                json.dump(manifest, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary_dir.replace(output_dir)
        except BaseException:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise

    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
