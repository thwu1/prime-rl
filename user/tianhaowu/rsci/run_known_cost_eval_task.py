#!/usr/bin/env python3
"""Execute one sealed known-cost evaluation task and write its terminal receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STUDY_ID = "verifier-defect-known-cost-boundary-v1"
PLAN_ARTIFACT_TYPE = "rsci_known_cost_checkpoint_eval_plan"
RECEIPT_ARTIFACT_TYPE = "rsci_known_cost_eval_attempt_receipt"
SCRIPT_REPOSITORY_PATH = Path("user/tianhaowu/rsci/run_known_cost_eval_task.py")
PLANNER_REPOSITORY_PATH = Path("user/tianhaowu/rsci/materialize_known_cost_eval_plan.py")
PROMOTED_PLANNER_REPOSITORY_PATH = Path("user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py")
PLANNER_IMPLEMENTATION_IDS = {
    PLANNER_REPOSITORY_PATH: "rsci-known-cost-checkpoint-eval-plan-v1",
    PROMOTED_PLANNER_REPOSITORY_PATH: "rsci-known-cost-promoted-checkpoint-eval-plan-v1",
}
DISPATCHER_REPOSITORY_PATH = Path("user/tianhaowu/rsci/dispatch_known_cost_eval.py")
SUCCESS_ARTIFACT_NAMES = (
    "generation_manifest.json",
    "generation_completion.json",
    "generations.jsonl",
    "strict_results.jsonl",
    "metrics.json",
)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "preempted"})
RECEIPT_NAME_RE = re.compile(r"attempt_([0-9]{4})\.json")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
RUNTIME_PYTHON_PATHS = (
    "user/tianhaowu/rsci/source_runtime",
    "src",
    "packages/prime-rl-configs/src",
    "deps/pydantic-config/src",
    "deps/renderers",
    "deps/verifiers",
    "user/tianhaowu/rsci",
)
INFERENCE_READY_TIMEOUT_SECONDS = 15 * 60
INFERENCE_READY_POLL_SECONDS = 2.0
PROCESS_TERMINATION_TIMEOUT_SECONDS = 30.0
HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGUSR1)


@dataclass(frozen=True)
class PlanContext:
    plan: dict[str, Any]
    plan_path: Path
    plan_sha256: str
    source_root: Path
    pinned_environment: dict[str, str]


@dataclass(frozen=True)
class AttemptContext:
    plan_context: PlanContext
    task: dict[str, Any]
    attempt: int
    receipt_path: Path
    predecessor_receipt_sha256: str | None
    scheduler: dict[str, Any]
    dispatch_intent: dict[str, Any]


class TerminationRequested(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"received signal {signal.Signals(signum).name}")
        self.signum = signum


class ManagedProcesses:
    def __init__(self) -> None:
        self.inference: subprocess.Popen[bytes] | None = None
        self.evaluator: subprocess.Popen[bytes] | None = None

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes] | None) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

    def cleanup(self) -> None:
        self._terminate(self.evaluator)
        self.evaluator = None
        self._terminate(self.inference)
        self.inference = None


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def _require_read_only(path: Path, label: str) -> None:
    if stat.S_IMODE(path.expanduser().resolve().stat().st_mode) & 0o222:
        raise ValueError(f"{label} must be read-only: {path}")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _reject_nonfinite_constant(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def read_canonical_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    raw = resolved.read_bytes()
    value = json.loads(
        raw.decode(),
        object_pairs_hook=_object_without_duplicate_keys,
        parse_constant=_reject_nonfinite_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {resolved}")
    if raw != canonical_json_bytes(value):
        raise ValueError(f"JSON artifact is not canonical: {resolved}")
    return raw, value


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _repository_root(path: Path, repository_path: Path) -> Path:
    resolved = path.expanduser().resolve()
    parts = repository_path.parts
    if len(resolved.parts) < len(parts) or resolved.parts[-len(parts) :] != parts:
        raise ValueError(f"Path is not the recorded repository path {repository_path}: {resolved}")
    return resolved.parents[len(parts) - 1]


def _pinned_environment(source_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "RSCI_SOURCE_SNAPSHOT": str(source_root),
            "UV_NO_SYNC": "1",
            "PYTHONPATH": os.pathsep.join(str(source_root / path) for path in RUNTIME_PYTHON_PATHS),
        }
    )
    shared_environment = source_root / ".venv"
    if not shared_environment.exists():
        raise FileNotFoundError(f"Pinned source snapshot has no shared environment: {shared_environment}")
    environment["UV_PROJECT_ENVIRONMENT"] = str(shared_environment.resolve())
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment.pop(name, None)
    return environment


def _planner_repository_path(plan: dict[str, Any], planner: dict[str, Any]) -> Path:
    repository_path = planner.get("repository_path")
    matches = [path for path in PLANNER_IMPLEMENTATION_IDS if repository_path == str(path)]
    if len(matches) != 1:
        raise ValueError("Known-cost evaluation plan records an unauthorized planner repository path")
    path = matches[0]
    if plan.get("implementation_id") != PLANNER_IMPLEMENTATION_IDS[path]:
        raise ValueError("Known-cost evaluation plan implementation ID differs from its exact planner contract")
    return path


def _identity_fields(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if set(value) < {"path", "size_bytes", "sha256"}:
        raise ValueError(f"{label} has an incomplete file identity")
    return {key: value[key] for key in ("path", "size_bytes", "sha256")}


def _validate_planner_source_authority(
    plan: dict[str, Any],
    planner: dict[str, Any],
    planner_repository_path: Path,
    source_root: Path,
) -> None:
    request = plan.get("request")
    if not isinstance(request, dict):
        raise ValueError("Known-cost evaluation plan has no authority-bearing request")
    if planner_repository_path == PLANNER_REPOSITORY_PATH:
        launch = request.get("launch")
        if not isinstance(launch, dict):
            raise ValueError("Historical evaluation plan has no launch authority")
        authority_identity = _identity_fields(launch.get("submission_intent"), "launch intent identity")
        authority_path = Path(str(authority_identity["path"])).expanduser().resolve()
        _require_read_only(authority_path, "Historical launch intent")
        if file_identity(authority_path) != authority_identity:
            raise ValueError("Historical launch intent changed after evaluation planning")
        _, authority = read_canonical_json(authority_path)
        source = authority.get("control_plane_source")
        implementation_name = "eval_planner"
    else:
        authority_identity = _identity_fields(
            request.get("promoted_eval_authority"),
            "promoted evaluation authority identity",
        )
        authority_path = Path(str(authority_identity["path"])).expanduser().resolve()
        _require_read_only(authority_path, "Promoted evaluation authority")
        if file_identity(authority_path) != authority_identity:
            raise ValueError("Promoted evaluation authority changed after evaluation planning")
        _, promoted_authority = read_canonical_json(authority_path)
        chain = promoted_authority.get("authority_chain")
        if not isinstance(chain, dict):
            raise ValueError("Promoted evaluation authority has no authority chain")
        postrun_identity = _identity_fields(chain.get("postrun_authority"), "post-run authority identity")
        postrun_path = Path(str(postrun_identity["path"])).expanduser().resolve()
        _require_read_only(postrun_path, "Post-run authority")
        if file_identity(postrun_path) != postrun_identity:
            raise ValueError("Post-run authority changed after promoted evaluation planning")
        _, authority = read_canonical_json(postrun_path)
        source = authority.get("postrun_control_source")
        implementation_name = "promoted_eval_authority"
    if not isinstance(source, dict) or not isinstance(source.get("implementations"), dict):
        raise ValueError("Planner authority has no pinned source implementation inventory")
    snapshot_path = Path(str(source.get("snapshot_path"))).expanduser().resolve()
    if snapshot_path != source_root:
        raise ValueError("Recorded planner path is outside its authority-pinned source snapshot")
    expected = _identity_fields(
        source["implementations"].get(implementation_name),
        f"authority-pinned {implementation_name}",
    )
    if _identity_fields(planner, "plan planner") != expected:
        raise ValueError("Evaluation plan planner differs from its authority-pinned implementation")
    if Path(str(planner["path"])).resolve() != source_root / planner_repository_path:
        raise ValueError("Evaluation planner path does not occupy its exact repository location in the snapshot")


def inspect_plan(plan_path: Path) -> PlanContext:
    resolved = plan_path.expanduser().resolve()
    _require_read_only(resolved, "Known-cost evaluation plan")
    raw, plan = read_canonical_json(resolved)
    initial_identity = file_identity(resolved)
    if (
        plan.get("schema_version") != SCHEMA_VERSION
        or plan.get("artifact_type") != PLAN_ARTIFACT_TYPE
        or plan.get("study_id") != STUDY_ID
    ):
        raise ValueError("Known-cost evaluation plan has the wrong schema, artifact, or study identity")
    if plan.get("plan_path") != str(resolved):
        raise ValueError("Known-cost evaluation plan is not at its recorded path")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or SHA256_RE.fullmatch(plan_id) is None:
        raise ValueError("Known-cost evaluation plan has an invalid plan_id")

    implementations = plan.get("implementations")
    if not isinstance(implementations, dict) or not isinstance(implementations.get("planner"), dict):
        raise ValueError("Known-cost evaluation plan has no pinned planner identity")
    planner = implementations["planner"]
    planner_repository_path = _planner_repository_path(plan, planner)
    planner_path = Path(str(planner.get("path", ""))).expanduser().resolve()
    source_root = _repository_root(planner_path, planner_repository_path)
    _validate_planner_source_authority(plan, planner, planner_repository_path, source_root)
    _require_read_only(planner_path, "Pinned evaluation planner")
    planner_identity = {key: planner[key] for key in ("path", "size_bytes", "sha256")}
    if file_identity(planner_path) != planner_identity:
        raise ValueError("Pinned evaluation planner bytes changed")
    environment = _pinned_environment(source_root)
    command = [
        "uv",
        "run",
        "--no-sync",
        "python",
        str(planner_path),
        "validate",
        "--plan",
        str(resolved),
    ]
    completed = subprocess.run(
        command,
        cwd=source_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60 * 60,
    )
    summary = json.loads(completed.stdout)
    plan_sha256 = bytes_sha256(raw)
    expected_summary = {
        "command": "validate",
        "plan_id": plan_id,
        "plan_path": str(resolved),
        "plan_sha256": plan_sha256,
    }
    for field, expected in expected_summary.items():
        if summary.get(field) != expected:
            raise ValueError(f"Pinned plan validator returned a different {field}")
    final_raw, final_plan = read_canonical_json(resolved)
    if final_raw != raw or final_plan != plan or file_identity(resolved) != initial_identity:
        raise RuntimeError("Known-cost evaluation plan changed while its recorded validator ran")
    if file_identity(planner_path) != planner_identity:
        raise RuntimeError("Pinned evaluation planner changed while validating its plan")
    return PlanContext(plan, resolved, plan_sha256, source_root, environment)


def directory_identity(path: Path, *, require_stable: bool) -> dict[str, Any]:
    configured = path.expanduser()
    if not configured.is_absolute():
        raise ValueError(f"Model path must be absolute: {configured}")
    resolved = configured.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    if require_stable and not (resolved / "STABLE").is_file():
        raise ValueError(f"Model directory has no STABLE marker: {resolved}")
    if not (resolved / "config.json").is_file():
        raise ValueError(f"Model directory has no config.json: {resolved}")
    paths = sorted(
        (candidate for candidate in resolved.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(resolved).as_posix(),
    )
    if not paths or not any(candidate.suffix == ".safetensors" for candidate in paths):
        raise ValueError(f"Model directory has no safetensors weights: {resolved}")
    inventory = []
    for candidate in paths:
        entry: dict[str, Any] = {
            "path": candidate.relative_to(resolved).as_posix(),
            "size_bytes": candidate.stat().st_size,
            "sha256": file_sha256(candidate),
        }
        if candidate.is_symlink():
            entry["symlink_target"] = os.readlink(candidate)
        inventory.append(entry)
    encoded = json.dumps(inventory, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return {
        "path": str(configured),
        "resolved_path": str(resolved),
        "file_count": len(inventory),
        "size_bytes": sum(item["size_bytes"] for item in inventory),
        "inventory": inventory,
        "inventory_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
    }


def select_task(plan: dict[str, Any], task_id: str) -> dict[str, Any]:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        raise ValueError("Known-cost evaluation plan has an invalid task inventory")
    matches = [task for task in tasks if task.get("task_id") == task_id]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one task_id {task_id!r}, found {len(matches)}")
    return matches[0]


def _model_for_task(plan: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    models = plan.get("models")
    if not isinstance(models, list) or any(not isinstance(model, dict) for model in models):
        raise ValueError("Known-cost evaluation plan has an invalid model inventory")
    matches = [model for model in models if model.get("model_key") == task.get("model_key")]
    if len(matches) != 1:
        raise ValueError(f"Task {task.get('task_id')} does not select exactly one checkpoint model")
    return matches[0]


def validate_task_contract(plan_context: PlanContext, task: dict[str, Any]) -> None:
    plan = plan_context.plan
    if task.get("receipt_dir") != str(Path(plan["plan_root"]) / "receipts" / str(task["task_id"])):
        raise ValueError("Task receipt directory differs from the plan contract")
    inference_identity = task.get("inference_config")
    if not isinstance(inference_identity, dict):
        raise ValueError("Task has no inference config identity")
    inference_path = Path(str(inference_identity.get("path", ""))).resolve()
    if file_identity(inference_path) != inference_identity:
        raise ValueError("Task inference config bytes changed")
    with inference_path.open("rb") as handle:
        inference = tomllib.load(handle)
    if inference.get("model", {}).get("name") != task.get("model_path"):
        raise ValueError("Task inference model differs from the checkpoint path")
    if inference.get("server", {}).get("port") != task.get("transport_port"):
        raise ValueError("Task inference transport port differs")
    if inference.get("deployment") != {"type": "single_node", "gpus_per_node": 1}:
        raise ValueError("Task inference deployment is not one GPU on one node")

    shards = task.get("shards")
    if not isinstance(shards, list) or len(shards) != 7:
        raise ValueError("Known-cost evaluation task must contain exactly seven shards")
    evaluator_identity = plan.get("implementations", {}).get("evaluator")
    if not isinstance(evaluator_identity, dict):
        raise ValueError("Plan has no evaluator identity")
    evaluator_path = Path(str(evaluator_identity.get("path", ""))).resolve()
    expected_evaluator_identity = {key: evaluator_identity[key] for key in ("path", "size_bytes", "sha256")}
    if file_identity(evaluator_path) != expected_evaluator_identity:
        raise ValueError("Pinned evaluator bytes changed")
    for shard in shards:
        identity = shard.get("eval_config")
        if not isinstance(identity, dict) or file_identity(Path(str(identity.get("path", "")))) != identity:
            raise ValueError(f"Task shard config bytes changed: {shard.get('shard_id')}")
        with Path(identity["path"]).open("rb") as handle:
            evaluation = tomllib.load(handle)
        if evaluation.get("infer_config") != str(inference_path):
            raise ValueError(f"Task shard selects a different inference config: {shard.get('shard_id')}")
        if evaluation.get("evaluator") != str(evaluator_path):
            raise ValueError(f"Task shard selects a different evaluator: {shard.get('shard_id')}")
        eval_config = evaluation.get("eval", {})
        if eval_config.get("model") != task.get("model_path"):
            raise ValueError(f"Task shard selects a different checkpoint: {shard.get('shard_id')}")
        if eval_config.get("output_dir") != shard.get("output_dir"):
            raise ValueError(f"Task shard output root differs: {shard.get('shard_id')}")
        expected_url = f"http://127.0.0.1:{task['transport_port']}/v1"
        if eval_config.get("api_base_url") != expected_url:
            raise ValueError(f"Task shard transport endpoint differs: {shard.get('shard_id')}")

    model = _model_for_task(plan, task)
    occurrences = model.get("occurrences")
    if not isinstance(occurrences, list) or not occurrences:
        raise ValueError("Task checkpoint has no clock occurrence")
    require_stable = any(occurrence.get("step") != 0 for occurrence in occurrences)
    current_checkpoint = directory_identity(Path(str(task["model_path"])), require_stable=require_stable)
    if current_checkpoint != model.get("checkpoint"):
        raise ValueError(f"Task checkpoint bytes changed: {task['task_id']}")
    if current_checkpoint["inventory_sha256"] != task.get("checkpoint_inventory_sha256"):
        raise ValueError(f"Task checkpoint inventory digest differs: {task['task_id']}")


def attempt_predecessor(task: dict[str, Any], attempt: int) -> tuple[Path, str | None]:
    _require_positive_int(attempt, "attempt")
    receipt_dir = Path(str(task["receipt_dir"])).resolve()
    paths: list[tuple[int, Path]] = []
    if receipt_dir.exists():
        if not receipt_dir.is_dir():
            raise ValueError(f"Task receipt path is not a directory: {receipt_dir}")
        for path in receipt_dir.iterdir():
            match = RECEIPT_NAME_RE.fullmatch(path.name)
            if match is None:
                raise ValueError(f"Unexpected task receipt artifact: {path}")
            paths.append((int(match.group(1)), path))
    paths.sort()
    if [number for number, _ in paths] != list(range(1, len(paths) + 1)):
        raise ValueError(f"Task receipt attempts are not contiguous: {task['task_id']}")
    if attempt != len(paths) + 1:
        raise ValueError(f"Attempt {attempt} is not the next contiguous attempt {len(paths) + 1}")
    predecessor_sha256 = None
    if paths:
        predecessor_raw, predecessor = read_canonical_json(paths[-1][1])
        if predecessor.get("status") == "succeeded":
            raise ValueError(f"Task already succeeded: {task['task_id']}")
        predecessor_sha256 = bytes_sha256(predecessor_raw)
    return receipt_dir / f"attempt_{attempt:04d}.json", predecessor_sha256


def scheduler_environment_identity() -> dict[str, Any]:
    job_id = os.environ.get("SLURM_JOB_ID")
    if not isinstance(job_id, str) or not job_id.isdecimal() or int(job_id) < 1:
        raise ValueError("SLURM_JOB_ID must identify the protected scheduler job")
    array_value = os.environ.get("SLURM_ARRAY_TASK_ID")
    array_task_id = None
    if array_value is not None:
        if not array_value.isdecimal():
            raise ValueError("SLURM_ARRAY_TASK_ID is invalid")
        array_task_id = int(array_value)
    return {"job_id": job_id, "array_task_id": array_task_id}


def build_attempt_context(
    *,
    plan_path: Path,
    task_id: str,
    attempt: int,
    dispatch_intent_path: Path,
) -> AttemptContext:
    plan_context = inspect_plan(plan_path)
    task = select_task(plan_context.plan, task_id)
    validate_task_contract(plan_context, task)
    receipt_path, predecessor_sha256 = attempt_predecessor(task, attempt)
    scheduler_environment = scheduler_environment_identity()

    import dispatch_known_cost_eval as dispatch

    runtime = dispatch.validate_runtime_dispatch(
        plan_context=plan_context,
        dispatch_intent_path=dispatch_intent_path,
        task_id=task_id,
        attempt=attempt,
        scheduler_job_id=scheduler_environment["job_id"],
    )
    scheduler = runtime["scheduler"]
    scheduler["array_task_id"] = scheduler_environment["array_task_id"]
    return AttemptContext(
        plan_context=plan_context,
        task=task,
        attempt=attempt,
        receipt_path=receipt_path,
        predecessor_receipt_sha256=predecessor_sha256,
        scheduler=scheduler,
        dispatch_intent=runtime["dispatch_intent"],
    )


def _health_url(task: dict[str, Any]) -> str:
    return f"http://127.0.0.1:{task['transport_port']}/health"


def _health_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return int(response.status)
    except (OSError, urllib.error.URLError):
        return None


def _tail(path: Path, lines: int = 200) -> str:
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def start_inference(context: AttemptContext, processes: ManagedProcesses, runtime_dir: Path) -> Path:
    task = context.task
    health_url = _health_url(task)
    if _health_status(health_url) == 200:
        raise RuntimeError(f"Transport port is already served before protected inference launch: {health_url}")
    inference_path = Path(task["inference_config"]["path"])
    server_log = runtime_dir / "server.log"
    server_log.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(context.plan_context.pinned_environment)
    cache_root = Path(os.environ.get("SLURM_TMPDIR", "/tmp")) / (
        f"rsci-known-cost-eval-{context.scheduler['job_id']}-{context.attempt}"
    )
    cache_root.mkdir(parents=True, exist_ok=True)
    environment["VLLM_CACHE_ROOT"] = str(cache_root)
    log_handle = server_log.open("ab")
    try:
        processes.inference = subprocess.Popen(
            ["uv", "run", "--no-sync", "inference", "@", str(inference_path)],
            cwd=context.plan_context.source_root,
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    deadline = time.monotonic() + INFERENCE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _health_status(health_url) == 200:
            return server_log
        if processes.inference.poll() is not None:
            raise RuntimeError(
                f"Inference exited with code {processes.inference.returncode} before health: {_tail(server_log)}"
            )
        time.sleep(INFERENCE_READY_POLL_SECONDS)
    raise TimeoutError(f"Inference did not become healthy within {INFERENCE_READY_TIMEOUT_SECONDS} seconds")


_PINNED_SHARD_VALIDATOR = """
import json
import sys
from pathlib import Path

import materialize_known_cost_eval_plan as plan

_, manifest = plan.read_json_object(Path(sys.argv[1]), require_canonical=True)
matches = [task for task in manifest["tasks"] if task["task_id"] == sys.argv[2]]
if len(matches) != 1:
    raise ValueError("task lookup is ambiguous")
shards = [shard for shard in matches[0]["shards"] if shard["shard_id"] == sys.argv[3]]
if len(shards) != 1:
    raise ValueError("shard lookup is ambiguous")
plan._validate_completed_shard(shards[0])
print(json.dumps({"task_id": sys.argv[2], "shard_id": sys.argv[3], "validated": True}, sort_keys=True))
""".strip()


def validate_completed_shard(plan_context: PlanContext, task_id: str, shard_id: str) -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "python",
            "-c",
            _PINNED_SHARD_VALIDATOR,
            str(plan_context.plan_path),
            task_id,
            shard_id,
        ],
        cwd=plan_context.source_root,
        env=plan_context.pinned_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60 * 60,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"Pinned validation failed for {task_id}/{shard_id}: {completed.stderr.strip() or completed.stdout.strip()}"
        )


def shard_is_complete(plan_context: PlanContext, task_id: str, shard_id: str) -> bool:
    try:
        validate_completed_shard(plan_context, task_id, shard_id)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return True


def run_evaluator_shard(
    context: AttemptContext,
    shard: dict[str, Any],
    processes: ManagedProcesses,
    runtime_dir: Path,
) -> None:
    task_id = str(context.task["task_id"])
    shard_id = str(shard["shard_id"])
    if shard_is_complete(context.plan_context, task_id, shard_id):
        return
    eval_path = Path(shard["eval_config"]["path"])
    with eval_path.open("rb") as handle:
        evaluation = tomllib.load(handle)
    evaluator_path = Path(evaluation["evaluator"])
    shard_log = runtime_dir / f"evaluator_{shard_id}.log"
    log_handle = shard_log.open("ab")
    try:
        processes.evaluator = subprocess.Popen(
            ["uv", "run", "--no-sync", str(evaluator_path), str(eval_path)],
            cwd=context.plan_context.source_root,
            env=context.plan_context.pinned_environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    returncode = processes.evaluator.wait()
    processes.evaluator = None
    if returncode != 0:
        raise RuntimeError(f"Evaluator failed for {task_id}/{shard_id} with code {returncode}: {_tail(shard_log)}")
    validate_completed_shard(context.plan_context, task_id, shard_id)


def success_shard_inventory(context: AttemptContext) -> list[dict[str, Any]]:
    records = []
    for shard in context.task["shards"]:
        validate_completed_shard(context.plan_context, context.task["task_id"], shard["shard_id"])
        output_dir = Path(shard["output_dir"])
        records.append(
            {
                "shard_id": shard["shard_id"],
                "output_dir": shard["output_dir"],
                "artifacts": {name: file_identity(output_dir / name) for name in SUCCESS_ARTIFACT_NAMES},
            }
        )
    return records


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_terminal_receipt(
    context: AttemptContext,
    *,
    status: str,
    started_at: str,
    finished_at: str,
    exit_code: int | None,
    failure: str | None = None,
    shards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"Unsupported terminal receipt status: {status}")
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECEIPT_ARTIFACT_TYPE,
        "plan_id": context.plan_context.plan["plan_id"],
        "plan_sha256": context.plan_context.plan_sha256,
        "task_id": context.task["task_id"],
        "attempt": context.attempt,
        "predecessor_receipt_sha256": context.predecessor_receipt_sha256,
        "config_bundle_sha256": context.task["config_bundle_sha256"],
        "checkpoint_inventory_sha256": context.task["checkpoint_inventory_sha256"],
        "result_root": context.task["result_root"],
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "scheduler": context.scheduler,
        "exit_code": exit_code,
        "dispatch_intent": context.dispatch_intent,
        "runner": {
            "repository_path": str(SCRIPT_REPOSITORY_PATH),
            **file_identity(Path(__file__)),
        },
    }
    if status == "succeeded":
        if exit_code != 0 or failure is not None or shards is None:
            raise ValueError("Succeeded receipt requires exit_code=0 and a shard inventory")
        receipt["shards"] = shards
    else:
        if not isinstance(failure, str) or not failure:
            raise ValueError("Unsuccessful receipt requires a failure description")
        receipt["failure"] = failure
    return receipt


def write_terminal_receipt(context: AttemptContext, receipt: dict[str, Any]) -> dict[str, Any]:
    path = context.receipt_path
    content = canonical_json_bytes(receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to replace an existing evaluation receipt: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        os.link(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    _require_read_only(path, "Evaluation attempt receipt")
    inspect_plan(context.plan_context.plan_path)
    return file_identity(path)


def _scheduler_signal_state(job_id: str) -> str | None:
    completed = subprocess.run(
        ["scontrol", "show", "job", "--oneliner", job_id],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return None
    match = re.search(r"(?:^|\s)JobState=(\S+)", completed.stdout)
    return match.group(1).split("+", maxsplit=1)[0] if match is not None else None


def termination_status(error: TerminationRequested, job_id: str) -> str:
    state = _scheduler_signal_state(job_id)
    if state == "PREEMPTED":
        return "preempted"
    if state == "CANCELLED":
        return "cancelled"
    if error.signum == signal.SIGUSR1:
        return "preempted"
    return "cancelled"


def _install_signal_handlers() -> dict[int, Any]:
    previous = {signum: signal.getsignal(signum) for signum in HANDLED_SIGNALS}

    def terminate(signum: int, _frame: object) -> None:
        raise TerminationRequested(signum)

    for signum in HANDLED_SIGNALS:
        signal.signal(signum, terminate)
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def execute_attempt(context: AttemptContext) -> dict[str, Any]:
    started_at = _utc_now()
    runtime_dir = Path(context.task["result_root"]) / "runtime" / f"attempt_{context.attempt:04d}"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    processes = ManagedProcesses()
    previous_handlers = _install_signal_handlers()
    status = "failed"
    exit_code: int | None = 1
    failure: str | None = None
    shards: list[dict[str, Any]] | None = None
    try:
        start_inference(context, processes, runtime_dir)
        for shard in context.task["shards"]:
            run_evaluator_shard(context, shard, processes, runtime_dir)
        validate_task_contract(context.plan_context, context.task)
        shards = success_shard_inventory(context)
        status = "succeeded"
        exit_code = 0
    except TerminationRequested as error:
        status = termination_status(error, context.scheduler["job_id"])
        exit_code = 128 + error.signum
        failure = str(error)
    except KeyboardInterrupt as error:
        status = "cancelled"
        exit_code = 130
        failure = f"{type(error).__name__}: interrupted"
    except Exception as error:
        status = "failed"
        exit_code = 1
        failure = f"{type(error).__name__}: {error}"
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
    try:
        processes.cleanup()
        receipt = build_terminal_receipt(
            context,
            status=status,
            started_at=started_at,
            finished_at=_utc_now(),
            exit_code=exit_code,
            failure=failure,
            shards=shards,
        )
        identity = write_terminal_receipt(context, receipt)
    finally:
        _restore_signal_handlers(previous_handlers)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    return {"status": status, "exit_code": exit_code, "receipt": identity}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--dispatch-intent", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    context = build_attempt_context(
        plan_path=args.plan,
        task_id=args.task_id,
        attempt=args.attempt,
        dispatch_intent_path=args.dispatch_intent,
    )
    result = execute_attempt(context)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(result["exit_code"])


if __name__ == "__main__":
    main()
