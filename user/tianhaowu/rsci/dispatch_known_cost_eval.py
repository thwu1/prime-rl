#!/usr/bin/env python3
"""Protected dispatcher for sealed known-cost checkpoint evaluation tasks."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import materialize_known_cost_postrun_authority as postrun_authority
import run_known_cost_eval_task as task_runner
import source_provenance

SCHEMA_VERSION = 1
STUDY_ID = task_runner.STUDY_ID
REQUIRED_QOS = "h100_ram_high"
MAX_TASKS_PER_INVOCATION = 5
MAX_LIVE_JOBS = 5
STATE_ROOT_BASE = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/dispatch/verifier-defect-known-cost-boundary-eval-v1")
SCRIPT_REPOSITORY_PATH = Path("user/tianhaowu/rsci/dispatch_known_cost_eval.py")
RUNNER_REPOSITORY_PATH = task_runner.SCRIPT_REPOSITORY_PATH
GLOBAL_INTENT_NAME = "global_dispatch_intent.json"
STATE_LOCK_NAME = "dispatch.lock"
STUDY_LOCK_NAME = ".study_dispatch.lock"
TASK_INTENT_NAME = "dispatch_intent.json"
SUBMISSION_RECEIPT_NAME = "submission_receipt.json"
TERMINAL_PROVENANCE_NAME = "terminal_provenance.json"
GLOBAL_ARTIFACT_TYPE = "rsci_known_cost_eval_global_dispatch_intent"
BATCH_ARTIFACT_TYPE = "rsci_known_cost_eval_dispatch_batch_intent"
TASK_ARTIFACT_TYPE = "rsci_known_cost_eval_task_dispatch_intent"
SUBMISSION_ARTIFACT_TYPE = "rsci_known_cost_eval_task_submission_receipt"
TERMINAL_PROVENANCE_ARTIFACT_TYPE = "rsci_known_cost_eval_terminal_provenance"
COMMENT_PREFIX = "rsci-kc-eval-v1-"
COMMENT_RE = re.compile(rf"{COMMENT_PREFIX}[0-9a-f]{{64}}")
JOB_ID_RE = re.compile(r"[1-9][0-9]*")
ATTEMPT_DIR_RE = re.compile(r"attempt_([0-9]{4})")
SBATCH_COMMAND_PREFIX = (
    "env",
    "-u",
    "SBATCH_OUTPUT",
    "-u",
    "SBATCH_ERROR",
    "sbatch",
    "--parsable",
)
SQUEUE_FORMAT = "%i|%1000k|%200j|%100a|%100q|%T"
SACCT_FORMAT = "JobIDRaw,Comment,JobName,Account,QOS,State"
TERMINAL_SACCT_FIELDS = (
    "JobIDRaw",
    "JobName",
    "State",
    "ExitCode",
    "Account",
    "QOS",
    "Comment",
    "Submit",
    "Start",
    "End",
    "ElapsedRaw",
)
VALIDATION_SACCT_FIELDS = (
    "JobIDRaw",
    "JobName",
    "State",
    "ExitCode",
    "Account",
    "QOS",
    "Comment",
)
VALIDATION_SACCT_FORMAT = "JobIDRaw%32,JobName%256,State%64,ExitCode%32,Account%128,QOS%128,Comment%256"
TERMINAL_SLURM_STATES = frozenset(
    {
        "BOOT_FAIL",
        "CANCELLED",
        "COMPLETED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "TIMEOUT",
    }
)
RUNNER_SCHEDULER_FIELDS = frozenset(
    {
        "job_id",
        "array_task_id",
        "comment",
        "job_name",
        "account",
        "qos",
        "submitted_batch_script_sha256",
    }
)
RECOVERED_SCHEDULER_FIELDS = RUNNER_SCHEDULER_FIELDS | {
    "terminal_state",
    "terminal_exit_code",
    "submit_time",
    "start_time",
    "end_time",
    "elapsed_seconds",
    "recovered_plan_status",
    "terminal_query",
}
TERMINAL_RECEIPT_BASE_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "plan_id",
        "plan_sha256",
        "task_id",
        "attempt",
        "predecessor_receipt_sha256",
        "config_bundle_sha256",
        "checkpoint_inventory_sha256",
        "result_root",
        "status",
        "started_at",
        "finished_at",
        "scheduler",
        "exit_code",
        "dispatch_intent",
        "runner",
    }
)


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def bytes_identity(path: Path, content: bytes) -> dict[str, Any]:
    return {
        "path": str(path.expanduser().resolve()),
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must use UTC")
    return parsed


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_read_only(path: Path, label: str) -> None:
    if stat.S_IMODE(path.expanduser().resolve().stat().st_mode) & 0o222:
        raise ValueError(f"{label} must be read-only: {path}")


def _write_bytes_once_atomic(path: Path, content: bytes, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists():
        if not resolved.is_file() or resolved.read_bytes() != content:
            raise FileExistsError(f"Refusing to replace a different immutable {label}: {resolved}")
        _require_read_only(resolved, label)
        return task_runner.file_identity(resolved)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=resolved.parent,
        prefix=f".{resolved.name}.",
        suffix=".partial",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        os.link(temporary, resolved)
        directory_descriptor = os.open(resolved.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    _require_read_only(resolved, label)
    return task_runner.file_identity(resolved)


def _write_json_once_atomic(path: Path, payload: dict[str, Any], label: str) -> dict[str, Any]:
    return _write_bytes_once_atomic(path, task_runner.canonical_json_bytes(payload), label)


def _execution_source_record(postrun_record: dict[str, Any]) -> dict[str, Any]:
    dispatcher_path = Path(__file__).resolve()
    source_root = task_runner._repository_root(dispatcher_path, SCRIPT_REPOSITORY_PATH)
    source_run_dir = source_root.parent
    provenance = source_provenance.verify_snapshot(
        source_run_dir,
        verify_imports=True,
        require_launch=False,
    )
    if Path(str(provenance["snapshot_path"])).resolve() != source_root:
        raise ValueError("Evaluation execution source snapshot differs from the dispatcher path")
    runner_path = source_root / RUNNER_REPOSITORY_PATH
    if not runner_path.is_file():
        raise FileNotFoundError(f"Pinned execution snapshot has no task runner: {runner_path}")
    record = {
        "run_dir": str(source_run_dir),
        "snapshot_path": str(source_root),
        "parent_commit_sha": provenance["parent_commit_sha"],
        "source_tree_sha256": provenance["source_tree_sha256"],
        "provenance_manifest": task_runner.file_identity(source_run_dir / source_provenance.MANIFEST_NAME),
        "dispatcher": {
            "repository_path": str(SCRIPT_REPOSITORY_PATH),
            **task_runner.file_identity(dispatcher_path),
        },
        "runner": {
            "repository_path": str(RUNNER_REPOSITORY_PATH),
            **task_runner.file_identity(runner_path),
        },
    }
    authority = postrun_record["authority"]
    postrun_authority.validate_recorded_implementation(
        authority,
        name="eval_dispatcher",
        implementation_path=dispatcher_path,
    )
    postrun_authority.validate_recorded_implementation(
        authority,
        name="eval_runner",
        implementation_path=runner_path,
    )
    pinned_source = _require_dict(authority.get("postrun_control_source"), "post-run control source")
    expected_source = {
        "snapshot_path": record["snapshot_path"],
        "parent_commit_sha": record["parent_commit_sha"],
        "source_tree_sha256": record["source_tree_sha256"],
        "manifest": record["provenance_manifest"],
    }
    observed_source = {
        "snapshot_path": pinned_source.get("snapshot_path"),
        "parent_commit_sha": pinned_source.get("parent_commit_sha"),
        "source_tree_sha256": pinned_source.get("source_tree_sha256"),
        "manifest": pinned_source.get("manifest"),
    }
    if observed_source != expected_source:
        raise ValueError("Evaluation execution source differs from the pre-RL post-run authority")
    return record


def required_state_root(plan: dict[str, Any]) -> Path:
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or task_runner.SHA256_RE.fullmatch(plan_id) is None:
        raise ValueError("Plan has an invalid content address")
    return (STATE_ROOT_BASE / plan_id).resolve()


def _launch_authority(
    plan_context: task_runner.PlanContext,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    launch_record = _require_dict(
        _require_dict(plan_context.plan.get("request"), "plan request").get("launch"),
        "plan launch record",
    )
    launch_identity = _require_dict(launch_record.get("submission_intent"), "plan launch intent identity")
    launch_path = Path(str(launch_identity.get("path", ""))).resolve()
    if task_runner.file_identity(launch_path) != launch_identity:
        raise ValueError("RL launch intent changed after evaluation planning")
    _require_read_only(launch_path, "RL launch intent")
    _, launch = task_runner.read_canonical_json(launch_path)
    policy = _require_dict(launch.get("dispatch_policy"), "RL launch dispatch policy")
    if policy.get("required_qos") != REQUIRED_QOS:
        raise ValueError("RL launch authority records a different protected H100 QoS")
    control_tmux = _require_dict(policy.get("required_control_tmux"), "recorded control tmux")
    if set(control_tmux) != {"socket", "session", "window"} or any(
        not isinstance(control_tmux[key], str) or not control_tmux[key] for key in control_tmux
    ):
        raise ValueError("Recorded control tmux contract is invalid")
    eligible_runs = launch.get("eligible_runs")
    if not isinstance(eligible_runs, list) or not eligible_runs:
        raise ValueError("RL launch intent has no eligible run inventory")
    accounts = set()
    for run in eligible_runs:
        projection = _require_dict(
            _require_dict(run.get("launcher_config_projection"), "launcher projection").get("projection"),
            "launcher projection payload",
        )
        slurm = _require_dict(projection.get("slurm"), "launcher Slurm projection")
        account = slurm.get("account")
        if not isinstance(account, str) or not account:
            raise ValueError("Eligible RL run has no sealed scheduler account")
        accounts.add(account)
    if len(accounts) != 1:
        raise ValueError("Eligible RL runs do not share one sealed scheduler account")
    return (
        launch_identity,
        launch,
        {
            "control_tmux": control_tmux,
            "account": accounts.pop(),
            "qos": REQUIRED_QOS,
        },
    )


def _postrun_authority(
    launch: dict[str, Any],
    launch_identity: dict[str, Any],
) -> dict[str, Any]:
    inputs = _require_dict(launch.get("inputs"), "RL launch inputs")
    run_root = Path(str(inputs.get("run_root"))).expanduser().resolve()
    record = postrun_authority.validate_authority(run_root / postrun_authority.AUTHORITY_NAME)
    bound_launch = _require_dict(
        record["authority"].get("initial_launch_authority"),
        "post-run initial launch authority",
    )
    if bound_launch.get("intent") != launch_identity:
        raise ValueError("Post-run authority and evaluation plan bind different RL launch intents")
    decision = _require_dict(launch.get("preregistered_decision"), "RL launch decision")
    for field in ("eligible_design", "eligible_arm_count", "eligible_arm_filenames"):
        if bound_launch.get(field) != decision.get(field):
            raise ValueError(f"Post-run authority and RL launch intent differ on {field}")
    return record


def authority_from_plan_context(plan_context: task_runner.PlanContext) -> dict[str, Any]:
    launch_identity, launch, scheduler = _launch_authority(plan_context)
    postrun = _postrun_authority(launch, launch_identity)
    execution_source = _execution_source_record(postrun)
    tasks = plan_context.plan.get("tasks")
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        raise ValueError("Plan task inventory is invalid")
    task_by_id = {str(task.get("task_id")): task for task in tasks}
    if len(task_by_id) != len(tasks) or "None" in task_by_id:
        raise ValueError("Plan task IDs are missing or duplicated")
    job_names = {task_id: scheduler_job_name(plan_context.plan, task_id) for task_id in task_by_id}
    if len(set(job_names.values())) != len(job_names):
        raise ValueError("Protected evaluation job names collide")
    return {
        "plan_context": plan_context,
        "plan_identity": task_runner.file_identity(plan_context.plan_path),
        "launch_intent": launch_identity,
        "postrun_authority": postrun["identity"],
        "execution_source": execution_source,
        "state_root": required_state_root(plan_context.plan),
        "task_by_id": task_by_id,
        "job_names": job_names,
        **scheduler,
    }


def load_authority(plan_path: Path) -> dict[str, Any]:
    return authority_from_plan_context(task_runner.inspect_plan(plan_path))


def validate_state_root(configured: Path, authority: dict[str, Any]) -> Path:
    if not configured.expanduser().is_absolute():
        raise ValueError("--state-root must be absolute")
    resolved = configured.expanduser().resolve()
    if resolved != authority["state_root"]:
        raise ValueError(f"--state-root must equal the plan-content address {authority['state_root']}")
    protected = (
        authority["plan_context"].plan_path,
        Path(authority["plan_context"].plan["plan_root"]),
        Path(authority["plan_context"].plan["eval_root"]),
        Path(authority["execution_source"]["run_dir"]),
    )
    for path in protected:
        path = path.resolve()
        if resolved == path or resolved.is_relative_to(path) or path.is_relative_to(resolved):
            raise ValueError(f"Dispatch state root overlaps protected study state: {path}")
    return resolved


def scheduler_job_name(plan: dict[str, Any], task_id: str) -> str:
    digest = canonical_json_sha256(
        {
            "domain": "rsci-known-cost-eval-job-name-v1",
            "plan_id": plan["plan_id"],
            "task_id": task_id,
        }
    )
    return f"rsci-kce-{digest[:20]}"


def _task_key(task_id: str) -> str:
    return hashlib.sha256(task_id.encode()).hexdigest()


def _attempt_paths(state_root: Path, task_id: str, attempt: int) -> dict[str, Path]:
    root = state_root / "tasks" / _task_key(task_id) / f"attempt_{attempt:04d}"
    return {
        "root": root,
        "intent": root / TASK_INTENT_NAME,
        "receipt": root / SUBMISSION_RECEIPT_NAME,
    }


def _shell(value: object) -> str:
    return shlex.quote(str(value))


def render_sbatch(
    *,
    authority: dict[str, Any],
    task: dict[str, Any],
    attempt: int,
    dispatch_intent_path: Path,
) -> bytes:
    task_id = str(task["task_id"])
    source = authority["execution_source"]
    log_path = authority["state_root"] / "logs" / f"{_task_key(task_id)}_attempt_{attempt:04d}_%j.log"
    lines = [
        "#!/usr/bin/env bash",
        f"#SBATCH --job-name={authority['job_names'][task_id]}",
        f"#SBATCH --qos={authority['qos']}",
        f"#SBATCH --account={authority['account']}",
        "#SBATCH --partition=h100",
        "#SBATCH --nodes=1",
        "#SBATCH --ntasks=1",
        "#SBATCH --gres=gpu:1",
        "#SBATCH --cpus-per-task=16",
        "#SBATCH --mem=64G",
        "#SBATCH --time=12:00:00",
        "#SBATCH --no-requeue",
        f"#SBATCH --output={log_path}",
        f"#SBATCH --error={log_path}",
        "",
        "set -euo pipefail",
        "",
        f"SOURCE_RUN_DIR={_shell(source['run_dir'])}",
        f"SOURCE_ROOT={_shell(source['snapshot_path'])}",
        'source "$SOURCE_ROOT/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh" "$SOURCE_RUN_DIR" >/dev/null',
        'cd "$RSCI_SOURCE_SNAPSHOT"',
        "export HF_HUB_OFFLINE=1",
        "export PYTHONDONTWRITEBYTECODE=1",
        "export UV_NO_SYNC=1",
        "",
        "exec uv run --no-sync python "
        + " ".join(
            (
                _shell(Path(source["snapshot_path"]) / RUNNER_REPOSITORY_PATH),
                "--plan",
                _shell(authority["plan_context"].plan_path),
                "--task-id",
                _shell(task_id),
                "--attempt",
                str(attempt),
                "--dispatch-intent",
                _shell(dispatch_intent_path),
            )
        ),
        "",
    ]
    return "\n".join(lines).encode()


def build_task_plan(authority: dict[str, Any], task: dict[str, Any], attempt: int) -> dict[str, Any]:
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    task_id = str(task["task_id"])
    paths = _attempt_paths(authority["state_root"], task_id, attempt)
    script_content = render_sbatch(
        authority=authority,
        task=task,
        attempt=attempt,
        dispatch_intent_path=paths["intent"],
    )
    script_hash = hashlib.sha256(script_content).hexdigest()
    script_path = paths["root"] / f"task_{script_hash}.sbatch"
    script_identity = bytes_identity(script_path, script_content)
    comment_material = {
        "domain": "rsci-known-cost-eval-protected-dispatch-v1",
        "plan_sha256": authority["plan_context"].plan_sha256,
        "task_id": task_id,
        "attempt": attempt,
        "config_bundle_sha256": task["config_bundle_sha256"],
        "checkpoint_inventory_sha256": task["checkpoint_inventory_sha256"],
        "postrun_authority_sha256": authority["postrun_authority"]["sha256"],
        "sbatch_sha256": script_hash,
        "runner_sha256": authority["execution_source"]["runner"]["sha256"],
        "dispatcher_sha256": authority["execution_source"]["dispatcher"]["sha256"],
        "account": authority["account"],
        "qos": authority["qos"],
    }
    comment = f"{COMMENT_PREFIX}{canonical_json_sha256(comment_material)}"
    if COMMENT_RE.fullmatch(comment) is None:
        raise RuntimeError("Derived protected evaluation comment is invalid")
    command = [
        *SBATCH_COMMAND_PREFIX,
        f"--comment={comment}",
        f"--qos={authority['qos']}",
        f"--account={authority['account']}",
        str(script_path),
    ]
    return {
        "task_id": task_id,
        "attempt": attempt,
        "config_bundle_sha256": task["config_bundle_sha256"],
        "checkpoint_inventory_sha256": task["checkpoint_inventory_sha256"],
        "result_root": task["result_root"],
        "paths": {name: str(path) for name, path in paths.items()},
        "sbatch": script_identity,
        "sbatch_content": script_content,
        "comment": comment,
        "command": command,
        "scheduler": {
            "job_name": authority["job_names"][task_id],
            "account": authority["account"],
            "qos": authority["qos"],
            "nodes": 1,
            "tasks": 1,
            "gpus": 1,
        },
        "submission_environment": {
            "set": {},
            "remove_all_sbatch_variables": True,
            "scheduler_overrides_are_explicit_cli_arguments": True,
        },
    }


def _execution_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("SBATCH_")}


def next_attempt(task: dict[str, Any]) -> int:
    receipt_dir = Path(str(task["receipt_dir"]))
    if not receipt_dir.exists():
        return 1
    attempts = []
    for path in receipt_dir.iterdir():
        match = task_runner.RECEIPT_NAME_RE.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Unexpected task receipt artifact: {path}")
        attempts.append(int(match.group(1)))
    attempts.sort()
    if attempts != list(range(1, len(attempts) + 1)):
        raise ValueError(f"Task receipt attempts are not contiguous: {task['task_id']}")
    return len(attempts) + 1


def select_tasks(authority: dict[str, Any], requested: list[str]) -> list[dict[str, Any]]:
    if not requested:
        raise ValueError("At least one explicit --task is required")
    if len(requested) > MAX_TASKS_PER_INVOCATION:
        raise ValueError(f"At most {MAX_TASKS_PER_INVOCATION} tasks may be dispatched per invocation")
    if len(requested) != len(set(requested)):
        raise ValueError("Duplicate --task values are forbidden")
    statuses = authority["plan_context"].plan.get("tasks")
    if not isinstance(statuses, list):
        raise ValueError("Plan task inventory is invalid")
    terminal = _task_terminal_statuses(authority["plan_context"].plan)
    selected = []
    for task_id in requested:
        task = authority["task_by_id"].get(task_id)
        if task is None:
            raise ValueError(f"Unknown task outside the immutable plan: {task_id}")
        if terminal.get(task_id) == "succeeded":
            raise ValueError(f"Task already has a succeeded terminal receipt: {task_id}")
        selected.append(task)
    return selected


def _task_terminal_statuses(plan: dict[str, Any]) -> dict[str, str]:
    statuses = {}
    for task in plan["tasks"]:
        attempt = next_attempt(task) - 1
        if attempt == 0:
            continue
        _, receipt = task_runner.read_canonical_json(Path(task["receipt_dir"]) / f"attempt_{attempt:04d}.json")
        status = receipt.get("status")
        if status not in task_runner.TERMINAL_STATUSES:
            raise ValueError(f"Task has a nonterminal plan receipt: {task['task_id']}")
        statuses[task["task_id"]] = status
    return statuses


def global_intent(authority: dict[str, Any], created_at: str) -> dict[str, Any]:
    _parse_utc(created_at, "global intent created_at")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": GLOBAL_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "state_root": str(authority["state_root"]),
        "plan": authority["plan_identity"],
        "launch_intent": authority["launch_intent"],
        "postrun_authority": authority["postrun_authority"],
        "execution_source": authority["execution_source"],
        "control_tmux": authority["control_tmux"],
        "scheduler_policy": {
            "account": authority["account"],
            "qos": authority["qos"],
            "max_tasks_per_invocation": MAX_TASKS_PER_INVOCATION,
            "max_live_jobs": MAX_LIVE_JOBS,
            "manual_sbatch_authorized": False,
            "explicit_cli_overrides": ["comment", "qos", "account"],
            "remove_all_sbatch_environment_variables": True,
        },
    }


def validate_global_intent(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    _require_read_only(path, "Global evaluation dispatch intent")
    _, observed = task_runner.read_canonical_json(path)
    expected = global_intent(authority, str(observed.get("created_at")))
    if observed != expected:
        raise ValueError("Global evaluation dispatch intent differs from the immutable authority")
    return observed


def batch_intent(
    *,
    global_path: Path,
    plans: list[dict[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    _parse_utc(created_at, "batch intent created_at")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": BATCH_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "global_dispatch_intent": task_runner.file_identity(global_path),
        "task_count": len(plans),
        "tasks": [
            {
                key: plan[key]
                for key in (
                    "task_id",
                    "attempt",
                    "config_bundle_sha256",
                    "checkpoint_inventory_sha256",
                    "comment",
                    "command",
                    "sbatch",
                )
            }
            for plan in plans
        ],
    }


def validate_batch_intent(path: Path, global_path: Path) -> dict[str, Any]:
    _require_read_only(path, "Evaluation dispatch batch intent")
    raw, observed = task_runner.read_canonical_json(path)
    if (
        path.stem
        != hashlib.sha256(
            json.dumps(
                observed,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
    ):
        raise ValueError("Evaluation batch intent filename differs from its canonical content address")
    if (
        observed.get("schema_version") != SCHEMA_VERSION
        or observed.get("artifact_type") != BATCH_ARTIFACT_TYPE
        or observed.get("study_id") != STUDY_ID
    ):
        raise ValueError("Evaluation dispatch batch intent has the wrong schema or study identity")
    _parse_utc(observed.get("created_at"), "batch intent created_at")
    if observed.get("global_dispatch_intent") != task_runner.file_identity(global_path):
        raise ValueError("Evaluation batch intent binds a different global intent")
    tasks = observed.get("tasks")
    if (
        not isinstance(tasks, list)
        or not tasks
        or observed.get("task_count") != len(tasks)
        or len(tasks) > MAX_TASKS_PER_INVOCATION
        or any(not isinstance(task, dict) for task in tasks)
    ):
        raise ValueError("Evaluation batch intent has an invalid task inventory")
    expected_fields = {
        "task_id",
        "attempt",
        "config_bundle_sha256",
        "checkpoint_inventory_sha256",
        "comment",
        "command",
        "sbatch",
    }
    if any(set(task) != expected_fields for task in tasks):
        raise ValueError("Evaluation batch intent task records have the wrong exact schema")
    task_attempts = [(task["task_id"], task["attempt"]) for task in tasks]
    if len(task_attempts) != len(set(task_attempts)):
        raise ValueError("Evaluation batch intent repeats a task attempt")
    if raw != task_runner.canonical_json_bytes(observed):
        raise RuntimeError("Evaluation batch intent changed while validating")
    return observed


def task_intent(
    *,
    authority: dict[str, Any],
    plan: dict[str, Any],
    global_path: Path,
    batch_path: Path,
    created_at: str,
) -> dict[str, Any]:
    _parse_utc(created_at, "task intent created_at")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": TASK_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "plan": authority["plan_identity"],
        "postrun_authority": authority["postrun_authority"],
        "global_dispatch_intent": task_runner.file_identity(global_path),
        "batch_dispatch_intent": task_runner.file_identity(batch_path),
        **{key: plan[key] for key in plan if key != "sbatch_content"},
        "execution_source": authority["execution_source"],
    }


def validate_task_intent(path: Path, authority: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    _require_read_only(path, "Task evaluation dispatch intent")
    _, observed = task_runner.read_canonical_json(path)
    global_identity = _require_dict(observed.get("global_dispatch_intent"), "task global intent identity")
    batch_identity = _require_dict(observed.get("batch_dispatch_intent"), "task batch intent identity")
    global_path = Path(str(global_identity.get("path", "")))
    batch_path = Path(str(batch_identity.get("path", "")))
    validate_global_intent(global_path, authority)
    batch = validate_batch_intent(batch_path, global_path)
    selected = [
        task for task in batch["tasks"] if task["task_id"] == plan["task_id"] and task["attempt"] == plan["attempt"]
    ]
    expected_batch_task = {
        key: plan[key]
        for key in (
            "task_id",
            "attempt",
            "config_bundle_sha256",
            "checkpoint_inventory_sha256",
            "comment",
            "command",
            "sbatch",
        )
    }
    if selected != [expected_batch_task]:
        raise ValueError("Task dispatch intent is absent from its immutable batch intent")
    expected = task_intent(
        authority=authority,
        plan=plan,
        global_path=global_path,
        batch_path=batch_path,
        created_at=str(observed.get("created_at")),
    )
    if observed != expected:
        raise ValueError(f"Task dispatch intent differs: {plan['task_id']} attempt {plan['attempt']}")
    return observed


def parse_scheduler_rows(output: str, *, source: str) -> list[dict[str, Any]]:
    records = []
    for line_number, raw_line in enumerate(output.splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = raw_line.split("|")
        if len(fields) < 6:
            raise ValueError(f"Malformed {source} scheduler row {line_number}: {raw_line!r}")
        job_id, comment, job_name, account, qos, state = (field.strip() for field in fields[:6])
        if JOB_ID_RE.fullmatch(job_id) is None:
            raise ValueError(f"Invalid {source} scheduler job ID: {job_id!r}")
        records.append(
            {
                "job_id": int(job_id),
                "comment": comment,
                "job_name": job_name,
                "account": account,
                "qos": qos,
                "state": state,
                "source": source,
            }
        )
    return records


def scheduler_snapshot(*, start_time: datetime, job_names: list[str]) -> dict[str, Any]:
    if not job_names or any(not name or "," in name for name in job_names):
        raise ValueError("Scheduler queries require explicit comma-free job names")
    name_filter = ",".join(sorted(set(job_names)))
    since = start_time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    squeue_command = ["squeue", "--noheader", "--name", name_filter, f"--format={SQUEUE_FORMAT}"]
    sacct_command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--name",
        name_filter,
        "--starttime",
        since,
        f"--format={SACCT_FORMAT}",
    ]
    squeue = subprocess.run(squeue_command, check=True, capture_output=True, text=True, timeout=60)
    sacct = subprocess.run(sacct_command, check=True, capture_output=True, text=True, timeout=60)
    records = parse_scheduler_rows(squeue.stdout, source="squeue")
    records.extend(parse_scheduler_rows(sacct.stdout, source="sacct"))
    return {
        "queried_at": _utc_now(),
        "start_time": since,
        "squeue_command": squeue_command,
        "squeue_stdout_sha256": hashlib.sha256(squeue.stdout.encode()).hexdigest(),
        "sacct_command": sacct_command,
        "sacct_stdout_sha256": hashlib.sha256(sacct.stdout.encode()).hexdigest(),
        "records": records,
    }


def study_live_snapshot() -> dict[str, Any]:
    command = ["squeue", "--noheader", f"--format={SQUEUE_FORMAT}"]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    records = [
        record
        for record in parse_scheduler_rows(completed.stdout, source="squeue")
        if record["comment"].startswith(COMMENT_PREFIX)
    ]
    return {
        "queried_at": _utc_now(),
        "squeue_command": command,
        "squeue_stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "records": records,
    }


def enforce_study_live_cap(
    authority: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    selected_new_count: int,
) -> dict[str, Any]:
    by_job_id = {}
    for record in snapshot["records"]:
        if record["qos"] != authority["qos"] or record["account"] != authority["account"]:
            raise ValueError(
                f"Known-cost evaluation comment appears under an unauthorized scheduler identity: {record['job_id']}"
            )
        prior = by_job_id.get(record["job_id"])
        if prior is not None and prior != record:
            raise ValueError(f"Study-wide live scheduler records disagree for job {record['job_id']}")
        by_job_id[record["job_id"]] = record
    projected = len(by_job_id) + selected_new_count
    if projected > MAX_LIVE_JOBS:
        raise RuntimeError(
            f"Study-wide evaluation cap exceeded: {len(by_job_id)} live + "
            f"{selected_new_count} selected > {MAX_LIVE_JOBS}"
        )
    return {
        "max_live_jobs": MAX_LIVE_JOBS,
        "live_count": len(by_job_id),
        "selected_new_count": selected_new_count,
        "projected_live_count": projected,
        "live_jobs": [
            {key: record[key] for key in ("job_id", "comment", "job_name", "account", "qos", "state")}
            for record in sorted(by_job_id.values(), key=lambda item: item["job_id"])
        ],
    }


def _is_terminal_state(state: str) -> bool:
    return state.split(maxsplit=1)[0].rstrip("+") in TERMINAL_SLURM_STATES


def recovered_plan_status(slurm_state: str) -> str:
    normalized = slurm_state.split(maxsplit=1)[0].rstrip("+")
    if normalized not in TERMINAL_SLURM_STATES:
        raise ValueError(f"Scheduler state is not terminal: {slurm_state}")
    if normalized == "PREEMPTED":
        return "preempted"
    if normalized == "CANCELLED":
        return "cancelled"
    return "failed"


def _validate_scheduler_record(record: dict[str, Any], plan: dict[str, Any]) -> None:
    scheduler = plan["scheduler"]
    if (
        record.get("comment") != plan["comment"]
        or record.get("job_name") != scheduler["job_name"]
        or record.get("account") != scheduler["account"]
        or record.get("qos") != scheduler["qos"]
    ):
        raise ValueError(f"Scheduler identity differs for {plan['task_id']} attempt {plan['attempt']}")


def _submitted_script_sha256(job_id: int) -> str:
    completed = subprocess.run(
        ["scontrol", "write", "batch_script", str(job_id), "-"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def _parse_terminal_allocation_stdout(stdout: str, job_id: int) -> dict[str, str]:
    rows = [line.split("|") for line in stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) < len(VALIDATION_SACCT_FIELDS):
        raise ValueError(f"sacct returned an ambiguous allocation record for job {job_id}")
    raw = {
        field: value.strip()
        for field, value in zip(
            VALIDATION_SACCT_FIELDS,
            rows[0][: len(VALIDATION_SACCT_FIELDS)],
            strict=True,
        )
    }
    if raw["JobIDRaw"] != str(job_id):
        raise ValueError(f"sacct returned a different allocation job ID for {job_id}")
    return {
        "job_id": raw["JobIDRaw"],
        "comment": raw["Comment"],
        "job_name": raw["JobName"],
        "account": raw["Account"],
        "qos": raw["QOS"],
        "state": raw["State"],
        "exit_code": raw["ExitCode"],
    }


def terminal_allocation_evidence(job_id: int, plan: dict[str, Any]) -> dict[str, Any]:
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError("Terminal allocation job ID is invalid")
    sacct_command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--jobs",
        str(job_id),
        f"--format={VALIDATION_SACCT_FORMAT}",
    ]
    completed = subprocess.run(
        sacct_command,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    record = _parse_terminal_allocation_stdout(completed.stdout, job_id)
    _validate_scheduler_record({**record, "job_id": job_id}, plan)
    submitted_script_command = ["scontrol", "write", "batch_script", str(job_id), "-"]
    submitted_script_sha256 = _submitted_script_sha256(job_id)
    if submitted_script_sha256 != plan["sbatch"]["sha256"]:
        raise ValueError(f"Submitted batch script differs for terminal job {job_id}")
    return {
        "queried_at": _utc_now(),
        "sacct_command": sacct_command,
        "sacct_stdout": completed.stdout,
        "sacct_stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "submitted_batch_script_command": submitted_script_command,
        "record": record,
        "submitted_batch_script_sha256": submitted_script_sha256,
    }


def verify_direct_job(job_id: int, plan: dict[str, Any]) -> dict[str, Any]:
    command = ["scontrol", "show", "job", str(job_id), "--oneliner"]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    fields = {}
    for name in ("Comment", "JobName", "Account", "QOS"):
        match = re.search(rf"(?:^|\s){name}=(\S+)", completed.stdout)
        if match is None:
            raise ValueError(f"scontrol output has no {name} for job {job_id}")
        fields[name] = match.group(1)
    record = {
        "job_id": job_id,
        "comment": fields["Comment"],
        "job_name": fields["JobName"],
        "account": fields["Account"],
        "qos": fields["QOS"],
    }
    _validate_scheduler_record(record, plan)
    script_sha256 = _submitted_script_sha256(job_id)
    if script_sha256 != plan["sbatch"]["sha256"]:
        raise ValueError(f"Submitted batch script differs for job {job_id}")
    return {
        "command": command,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "submitted_batch_script_sha256": script_sha256,
        "record": record,
    }


def terminal_scheduler_record(job_id: int, plan: dict[str, Any]) -> dict[str, Any]:
    squeue_command = ["squeue", "--noheader", "--jobs", str(job_id), f"--format={SQUEUE_FORMAT}"]
    squeue = subprocess.run(squeue_command, check=False, capture_output=True, text=True, timeout=60)
    if squeue.returncode != 0 and "Invalid job id specified" not in squeue.stderr:
        raise RuntimeError(f"squeue failed while terminalizing job {job_id}: {squeue.stderr.strip()}")
    live_rows = parse_scheduler_rows(squeue.stdout, source="squeue") if squeue.returncode == 0 else []
    if live_rows:
        raise RuntimeError(f"Cannot terminalize scheduler job {job_id} while it remains in squeue")

    sacct_command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--jobs",
        str(job_id),
        f"--format={','.join(TERMINAL_SACCT_FIELDS)}",
    ]
    sacct = subprocess.run(sacct_command, check=True, capture_output=True, text=True, timeout=60)
    rows = [line.split("|") for line in sacct.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) < len(TERMINAL_SACCT_FIELDS):
        raise ValueError(f"sacct returned an ambiguous terminal record for job {job_id}")
    record = dict(zip(TERMINAL_SACCT_FIELDS, rows[0][: len(TERMINAL_SACCT_FIELDS)], strict=True))
    if record["JobIDRaw"] != str(job_id):
        raise ValueError(f"sacct returned a different terminal job ID for {job_id}")
    normalized = {
        "job_id": job_id,
        "comment": record["Comment"] or plan["comment"],
        "job_name": record["JobName"],
        "account": record["Account"],
        "qos": record["QOS"],
    }
    _validate_scheduler_record(normalized, plan)
    status = recovered_plan_status(record["State"])
    return {
        "job_id": str(job_id),
        "array_task_id": None,
        "comment": plan["comment"],
        "job_name": plan["scheduler"]["job_name"],
        "account": plan["scheduler"]["account"],
        "qos": plan["scheduler"]["qos"],
        "submitted_batch_script_sha256": plan["sbatch"]["sha256"],
        "terminal_state": record["State"],
        "terminal_exit_code": record["ExitCode"],
        "submit_time": record["Submit"],
        "start_time": record["Start"],
        "end_time": record["End"],
        "elapsed_seconds": int(record["ElapsedRaw"]),
        "recovered_plan_status": status,
        "terminal_query": {
            "queried_at": _utc_now(),
            "squeue_command": squeue_command,
            "squeue_stdout_sha256": hashlib.sha256(squeue.stdout.encode()).hexdigest(),
            "sacct_command": sacct_command,
            "sacct_stdout_sha256": hashlib.sha256(sacct.stdout.encode()).hexdigest(),
        },
    }


def submission_receipt(
    *,
    plan: dict[str, Any],
    intent_path: Path,
    job_id: int,
    source: str,
    sbatch_stdout: str | None,
    scheduler_evidence: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError("Submission receipt job ID is invalid")
    if source not in {"sbatch_stdout", "scheduler_reconciliation"}:
        raise ValueError("Submission receipt source is invalid")
    if source == "sbatch_stdout":
        if not isinstance(sbatch_stdout, str) or sbatch_stdout.split(";", maxsplit=1)[0] != str(job_id):
            raise ValueError("Direct submission receipt has invalid sbatch stdout")
    elif sbatch_stdout is not None:
        raise ValueError("Reconciled receipt cannot record sbatch stdout")
    _validate_submission_evidence(
        source=source,
        evidence=scheduler_evidence,
        job_id=job_id,
        plan=plan,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": SUBMISSION_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "task_id": plan["task_id"],
        "attempt": plan["attempt"],
        "comment": plan["comment"],
        "command": plan["command"],
        "sbatch": plan["sbatch"],
        "dispatch_intent": task_runner.file_identity(intent_path),
        "job_id": job_id,
        "source": source,
        "sbatch_stdout": sbatch_stdout,
        "scheduler_evidence": scheduler_evidence,
    }


def _validate_direct_scheduler_evidence(
    evidence: dict[str, Any],
    *,
    job_id: int,
    plan: dict[str, Any],
) -> None:
    if set(evidence) != {"command", "stdout_sha256", "submitted_batch_script_sha256", "record"}:
        raise ValueError("Direct scheduler evidence has the wrong exact schema")
    if evidence["command"] != ["scontrol", "show", "job", str(job_id), "--oneliner"]:
        raise ValueError("Direct scheduler evidence records a different query")
    if task_runner.SHA256_RE.fullmatch(str(evidence["stdout_sha256"])) is None:
        raise ValueError("Direct scheduler stdout hash is invalid")
    if evidence["submitted_batch_script_sha256"] != plan["sbatch"]["sha256"]:
        raise ValueError("Direct scheduler evidence records a different submitted script")
    record = _require_dict(evidence["record"], "direct scheduler record")
    if record.get("job_id") != job_id:
        raise ValueError("Direct scheduler evidence records a different job ID")
    _validate_scheduler_record(record, plan)


def _validate_submission_evidence(
    *,
    source: str,
    evidence: dict[str, Any],
    job_id: int,
    plan: dict[str, Any],
) -> None:
    if source == "sbatch_stdout":
        _validate_direct_scheduler_evidence(evidence, job_id=job_id, plan=plan)
        return
    if set(evidence) != {"query", "exact_comment_matches", "direct_job"}:
        raise ValueError("Reconciliation scheduler evidence has the wrong exact schema")
    query = _require_dict(evidence["query"], "reconciliation scheduler query")
    expected_query_fields = {
        "queried_at",
        "start_time",
        "squeue_command",
        "squeue_stdout_sha256",
        "sacct_command",
        "sacct_stdout_sha256",
    }
    if set(query) != expected_query_fields:
        raise ValueError("Reconciliation scheduler query has the wrong exact schema")
    _parse_utc(query["queried_at"], "reconciliation queried_at")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(query["start_time"])) is None:
        raise ValueError("Reconciliation scheduler start time is invalid")
    if not isinstance(query["squeue_command"], list) or query["squeue_command"][:1] != ["squeue"]:
        raise ValueError("Reconciliation squeue command is invalid")
    if not isinstance(query["sacct_command"], list) or query["sacct_command"][:1] != ["sacct"]:
        raise ValueError("Reconciliation sacct command is invalid")
    for field in ("squeue_stdout_sha256", "sacct_stdout_sha256"):
        if task_runner.SHA256_RE.fullmatch(str(query[field])) is None:
            raise ValueError(f"Reconciliation {field} is invalid")
    matches = evidence["exact_comment_matches"]
    if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError("Reconciliation must record exactly one exact-comment scheduler match")
    if matches[0].get("job_id") != job_id:
        raise ValueError("Reconciliation scheduler match records a different job ID")
    _validate_scheduler_record(matches[0], plan)
    _validate_direct_scheduler_evidence(
        _require_dict(evidence["direct_job"], "reconciliation direct scheduler evidence"),
        job_id=job_id,
        plan=plan,
    )


def validate_submission_receipt(path: Path, plan: dict[str, Any], intent_path: Path) -> dict[str, Any]:
    _require_read_only(path, "Evaluation submission receipt")
    _, observed = task_runner.read_canonical_json(path)
    expected = submission_receipt(
        plan=plan,
        intent_path=intent_path,
        job_id=int(observed.get("job_id")),
        source=str(observed.get("source")),
        sbatch_stdout=observed.get("sbatch_stdout"),
        scheduler_evidence=_require_dict(observed.get("scheduler_evidence"), "scheduler evidence"),
    )
    if observed != expected:
        raise ValueError(f"Evaluation submission receipt differs: {path}")
    return observed


def state_status(authority: dict[str, Any]) -> dict[str, Any]:
    state_root = authority["state_root"]
    if not state_root.exists():
        return {
            "state": "pristine",
            "global_intent": None,
            "plans": [],
            "pending": [],
            "receipts": [],
            "script_only": [],
        }
    allowed = {STATE_LOCK_NAME, GLOBAL_INTENT_NAME, "batches", "tasks", "logs"}
    unexpected = sorted(path.name for path in state_root.iterdir() if path.name not in allowed)
    if unexpected:
        raise ValueError(f"Unexpected evaluation dispatch state artifacts: {unexpected}")
    global_path = state_root / GLOBAL_INTENT_NAME
    global_record = validate_global_intent(global_path, authority) if global_path.exists() else None
    batch_root = state_root / "batches"
    if batch_root.exists():
        if global_record is None:
            raise ValueError("Evaluation batch state exists without a global intent")
        for path in batch_root.iterdir():
            if not path.is_file() or path.suffix != ".json":
                raise ValueError(f"Unexpected evaluation batch state: {path}")
            validate_batch_intent(path, global_path)
    task_root = state_root / "tasks"
    plans = []
    pending = []
    receipts = []
    script_only = []
    key_to_task = {_task_key(task_id): task for task_id, task in authority["task_by_id"].items()}
    if task_root.exists():
        for task_dir in sorted(task_root.iterdir()):
            task = key_to_task.get(task_dir.name)
            if task is None or not task_dir.is_dir():
                raise ValueError(f"Unknown evaluation dispatch task directory: {task_dir}")
            for attempt_dir in sorted(task_dir.iterdir()):
                match = ATTEMPT_DIR_RE.fullmatch(attempt_dir.name)
                if match is None or not attempt_dir.is_dir():
                    raise ValueError(f"Unexpected evaluation attempt state: {attempt_dir}")
                attempt = int(match.group(1))
                plan = build_task_plan(authority, task, attempt)
                paths = {key: Path(value) for key, value in plan["paths"].items()}
                expected_script = Path(plan["sbatch"]["path"])
                allowed_names = {expected_script.name, TASK_INTENT_NAME, SUBMISSION_RECEIPT_NAME}
                unexpected_names = sorted(path.name for path in attempt_dir.iterdir() if path.name not in allowed_names)
                if unexpected_names:
                    raise ValueError(f"Unexpected evaluation attempt artifacts: {unexpected_names}")
                if not expected_script.is_file():
                    raise ValueError(f"Evaluation attempt state has no sealed batch script: {attempt_dir}")
                _require_read_only(expected_script, "Sealed evaluation batch script")
                if task_runner.file_identity(expected_script) != plan["sbatch"]:
                    raise ValueError(f"Sealed evaluation batch script changed: {expected_script}")
                if paths["intent"].exists():
                    if global_record is None:
                        raise ValueError("Task dispatch intent exists without a global intent")
                    validate_task_intent(paths["intent"], authority, plan)
                    plans.append(plan)
                    if paths["receipt"].exists():
                        receipt = validate_submission_receipt(paths["receipt"], plan, paths["intent"])
                        receipts.append({"plan": plan, "receipt": receipt})
                    else:
                        pending.append(plan)
                elif paths["receipt"].exists():
                    raise ValueError("Submission receipt exists without its task dispatch intent")
                else:
                    script_only.append(plan)
    if global_record is None and (plans or pending or receipts or script_only):
        raise ValueError("Evaluation dispatch task state exists without a global intent")
    state = "ambiguous_submission_pending_reconciliation" if pending else "ready"
    return {
        "state": state,
        "global_intent": global_record,
        "plans": plans,
        "pending": pending,
        "receipts": receipts,
        "script_only": script_only,
    }


def _merged_scheduler_records(snapshot: dict[str, Any]) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for record in snapshot["records"]:
        job_id = record["job_id"]
        current = merged.setdefault(
            job_id,
            {
                "job_id": job_id,
                "comment": "",
                "job_name": "",
                "account": "",
                "qos": "",
                "sources": set(),
                "states": set(),
            },
        )
        for field in ("comment", "job_name", "account", "qos"):
            if current[field] and record[field] and current[field] != record[field]:
                raise ValueError(f"Scheduler sources disagree for job {job_id} field {field}")
            if not current[field]:
                current[field] = record[field]
        current["sources"].add(record["source"])
        current["states"].add(record["state"])
    return merged


def enforce_live_cap(
    authority: dict[str, Any],
    status: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    selected_new_count: int,
) -> dict[str, Any]:
    plan_by_comment = {plan["comment"]: plan for plan in status["plans"]}
    plan_by_job_id = {item["receipt"]["job_id"]: item["plan"] for item in status["receipts"]}
    task_by_job_name = {authority["job_names"][task_id]: task_id for task_id in authority["task_by_id"]}
    merged = _merged_scheduler_records(snapshot)
    live = []
    seen_receipt_jobs = set()
    for job_id, record in merged.items():
        if record["job_name"] not in task_by_job_name:
            continue
        plan = plan_by_job_id.get(job_id) or plan_by_comment.get(record["comment"])
        if plan is None:
            raise ValueError(f"Scheduler contains an evaluation job with no immutable dispatch intent: {job_id}")
        if job_id in plan_by_job_id:
            seen_receipt_jobs.add(job_id)
        if not record["comment"]:
            record["comment"] = plan["comment"]
        normalized = {
            "job_id": job_id,
            "comment": record["comment"],
            "job_name": record["job_name"],
            "account": record["account"],
            "qos": record["qos"],
        }
        _validate_scheduler_record(normalized, plan)
        is_live = "squeue" in record["sources"] or any(not _is_terminal_state(state) for state in record["states"])
        if is_live:
            live.append(
                {
                    "job_id": job_id,
                    "task_id": plan["task_id"],
                    "attempt": plan["attempt"],
                    "states": sorted(record["states"]),
                    "sources": sorted(record["sources"]),
                }
            )
    missing = sorted(set(plan_by_job_id) - seen_receipt_jobs)
    if missing:
        raise RuntimeError(f"Cannot establish scheduler state for protected evaluation jobs: {missing}")
    projected = len(live) + selected_new_count
    if projected > MAX_LIVE_JOBS:
        raise RuntimeError(
            f"Study-wide evaluation cap exceeded: {len(live)} live + {selected_new_count} selected > {MAX_LIVE_JOBS}"
        )
    return {
        "max_live_jobs": MAX_LIVE_JOBS,
        "live_count": len(live),
        "selected_new_count": selected_new_count,
        "projected_live_count": projected,
        "live_jobs": live,
    }


def _scheduler_start(status: dict[str, Any]) -> datetime:
    if status["global_intent"] is None:
        return datetime.now(UTC) - timedelta(days=30)
    return _parse_utc(status["global_intent"]["created_at"], "global intent created_at") - timedelta(days=1)


def require_control_tmux(contract: dict[str, Any]) -> dict[str, str]:
    tmux_value = os.environ.get("TMUX")
    pane = os.environ.get("TMUX_PANE")
    if not tmux_value or not pane:
        raise ValueError("Actual evaluation dispatch must run inside the recorded control tmux")
    socket = tmux_value.split(",", maxsplit=1)[0]
    if socket != contract["socket"]:
        raise ValueError("Control tmux socket differs from the recorded authority")
    completed = subprocess.run(
        [
            "tmux",
            "-S",
            contract["socket"],
            "display-message",
            "-p",
            "-t",
            pane,
            "#{session_name}\t#{window_name}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    observed = completed.stdout.rstrip("\n").split("\t")
    if observed != [contract["session"], contract["window"]]:
        raise ValueError(f"Control tmux target differs: {observed!r}")
    return dict(contract)


def _ensure_global_intent(authority: dict[str, Any]) -> Path:
    path = authority["state_root"] / GLOBAL_INTENT_NAME
    if not path.exists():
        _write_json_once_atomic(path, global_intent(authority, _utc_now()), "global evaluation dispatch intent")
    validate_global_intent(path, authority)
    return path


def _batch_path(state_root: Path, payload: dict[str, Any]) -> Path:
    return state_root / "batches" / f"{canonical_json_sha256(payload)}.json"


def _submit_one(
    *,
    authority: dict[str, Any],
    plan: dict[str, Any],
    global_path: Path,
    batch_path: Path,
) -> dict[str, Any]:
    paths = {key: Path(value) for key, value in plan["paths"].items()}
    _write_bytes_once_atomic(
        Path(plan["sbatch"]["path"]),
        plan["sbatch_content"],
        "sealed evaluation batch script",
    )
    intent = task_intent(
        authority=authority,
        plan=plan,
        global_path=global_path,
        batch_path=batch_path,
        created_at=_utc_now(),
    )
    _write_json_once_atomic(paths["intent"], intent, "task evaluation dispatch intent")
    validate_task_intent(paths["intent"], authority, plan)
    if task_runner.file_identity(Path(plan["sbatch"]["path"])) != plan["sbatch"]:
        raise ValueError("Sealed evaluation batch script changed before submission")
    try:
        completed = subprocess.run(
            plan["command"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=_execution_environment(),
        )
    except Exception as error:
        raise RuntimeError(f"Ambiguous sbatch outcome for {plan['task_id']}; reconcile by exact comment") from error
    stdout = completed.stdout.strip()
    job_id_text = stdout.split(";", maxsplit=1)[0]
    if completed.returncode != 0 or JOB_ID_RE.fullmatch(job_id_text) is None:
        raise RuntimeError(
            f"Ambiguous sbatch outcome for {plan['task_id']}; returncode={completed.returncode}; "
            "reconcile by exact comment"
        )
    job_id = int(job_id_text)
    try:
        evidence = verify_direct_job(job_id, plan)
    except Exception as error:
        raise RuntimeError(
            f"Submitted evaluation job {job_id} could not be verified; reconcile by exact comment"
        ) from error
    receipt = submission_receipt(
        plan=plan,
        intent_path=paths["intent"],
        job_id=job_id,
        source="sbatch_stdout",
        sbatch_stdout=stdout,
        scheduler_evidence=evidence,
    )
    _write_json_once_atomic(paths["receipt"], receipt, "evaluation submission receipt")
    validate_submission_receipt(paths["receipt"], plan, paths["intent"])
    return receipt


def _dispatch_preview(
    authority: dict[str, Any],
    selected: list[dict[str, Any]],
    status: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if status["pending"]:
        raise RuntimeError("A prior evaluation submission is ambiguous; reconcile it before dispatch")
    selected_plans = []
    existing_by_key = {(plan["task_id"], plan["attempt"]): plan for plan in status["plans"] + status["script_only"]}
    for task in selected:
        attempt = next_attempt(task)
        plan = build_task_plan(authority, task, attempt)
        existing = existing_by_key.get((task["task_id"], attempt))
        if existing is not None and existing not in status["script_only"]:
            raise ValueError(f"Task attempt already has protected dispatch state: {task['task_id']}/{attempt}")
        if existing is not None and existing != plan:
            raise ValueError(f"Prepared evaluation script differs: {task['task_id']}/{attempt}")
        selected_plans.append(plan)
    snapshot = scheduler_snapshot(
        start_time=_scheduler_start(status),
        job_names=list(authority["job_names"].values()),
    )
    current_plan_live = enforce_live_cap(
        authority,
        status,
        snapshot,
        selected_new_count=0,
    )
    study_snapshot = study_live_snapshot()
    study_live = enforce_study_live_cap(
        authority,
        study_snapshot,
        selected_new_count=len(selected_plans),
    )
    for plan in selected_plans:
        matches = [
            record
            for record in snapshot["records"]
            if record["comment"] == plan["comment"] or record["job_name"] == plan["scheduler"]["job_name"]
        ]
        if matches:
            raise ValueError(f"Task already appears in scheduler state: {plan['task_id']}")
    return (
        selected_plans,
        snapshot,
        {
            "study": study_live,
            "current_plan": current_plan_live,
            "study_scheduler_snapshot": {key: value for key, value in study_snapshot.items() if key != "records"},
        },
    )


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    authority = load_authority(args.plan)
    validate_state_root(args.state_root, authority)
    selected = select_tasks(authority, args.task)
    status = state_status(authority)
    plans, snapshot, live = _dispatch_preview(authority, selected, status)
    preview = {
        "study_id": STUDY_ID,
        "plan": authority["plan_identity"],
        "state_root": str(authority["state_root"]),
        "tasks": [
            {key: plan[key] for key in ("task_id", "attempt", "comment", "command", "sbatch", "scheduler")}
            for plan in plans
        ],
        "live_cap": live,
        "scheduler_snapshot": {key: value for key, value in snapshot.items() if key != "records"},
        "scheduler_mutation": False,
    }
    if args.dry_run:
        return preview
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual dispatch requires --confirm-study-id {STUDY_ID}")
    require_control_tmux(authority["control_tmux"])
    authority["state_root"].mkdir(parents=True, exist_ok=True)
    (authority["state_root"] / "logs").mkdir(parents=True, exist_ok=True)
    lock_path = authority["state_root"] / STATE_LOCK_NAME
    study_lock_path = STATE_ROOT_BASE / STUDY_LOCK_NAME
    with study_lock_path.open("a", encoding="utf-8") as study_lock_handle:
        fcntl.flock(study_lock_handle, fcntl.LOCK_EX)
        with lock_path.open("a", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle, fcntl.LOCK_EX)
            authority = load_authority(args.plan)
            validate_state_root(args.state_root, authority)
            selected = select_tasks(authority, args.task)
            status = state_status(authority)
            plans, _, live = _dispatch_preview(authority, selected, status)
            global_path = _ensure_global_intent(authority)
            batch = batch_intent(global_path=global_path, plans=plans, created_at=_utc_now())
            batch_path = _batch_path(authority["state_root"], batch)
            _write_json_once_atomic(batch_path, batch, "evaluation dispatch batch intent")
            receipts = [
                _submit_one(
                    authority=authority,
                    plan=plan,
                    global_path=global_path,
                    batch_path=batch_path,
                )
                for plan in plans
            ]
    return {
        **preview,
        "live_cap": live,
        "scheduler_mutation": True,
        "submission_receipts": receipts,
    }


def _exact_comment_matches(snapshot: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    merged = _merged_scheduler_records(snapshot)
    matches = []
    for record in merged.values():
        if record["comment"] != plan["comment"]:
            continue
        normalized = {
            "job_id": record["job_id"],
            "comment": record["comment"],
            "job_name": record["job_name"],
            "account": record["account"],
            "qos": record["qos"],
        }
        _validate_scheduler_record(normalized, plan)
        matches.append(normalized)
    return sorted(matches, key=lambda record: record["job_id"])


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    authority = load_authority(args.plan)
    validate_state_root(args.state_root, authority)
    requested = set(args.task)
    if not requested or len(requested) > MAX_TASKS_PER_INVOCATION:
        raise ValueError(f"Reconcile requires one to {MAX_TASKS_PER_INVOCATION} explicit --task values")
    status = state_status(authority)
    pending_by_task = {plan["task_id"]: plan for plan in status["pending"]}
    if set(pending_by_task) != requested:
        raise ValueError("Reconcile task set must exactly equal the pending ambiguous task set")
    snapshot = scheduler_snapshot(
        start_time=_scheduler_start(status),
        job_names=list(authority["job_names"].values()),
    )
    reconciled = []
    for task_id in args.task:
        plan = pending_by_task[task_id]
        matches = _exact_comment_matches(snapshot, plan)
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one scheduler match for {task_id}, found {len(matches)}")
        reconciled.append({"plan": plan, "match": matches[0]})
    if args.dry_run:
        return {
            "study_id": STUDY_ID,
            "state_root": str(authority["state_root"]),
            "scheduler_mutation": False,
            "matches": reconciled,
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual reconciliation requires --confirm-study-id {STUDY_ID}")
    require_control_tmux(authority["control_tmux"])
    lock_path = authority["state_root"] / STATE_LOCK_NAME
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        authority = load_authority(args.plan)
        status = state_status(authority)
        pending_by_task = {plan["task_id"]: plan for plan in status["pending"]}
        if set(pending_by_task) != requested:
            raise ValueError("Pending evaluation state changed before reconciliation")
        snapshot = scheduler_snapshot(
            start_time=_scheduler_start(status),
            job_names=list(authority["job_names"].values()),
        )
        receipts = []
        for task_id in args.task:
            plan = pending_by_task[task_id]
            matches = _exact_comment_matches(snapshot, plan)
            if len(matches) != 1:
                raise RuntimeError(f"Expected exactly one scheduler match for {task_id}, found {len(matches)}")
            job_id = matches[0]["job_id"]
            evidence = verify_direct_job(job_id, plan)
            paths = {key: Path(value) for key, value in plan["paths"].items()}
            receipt = submission_receipt(
                plan=plan,
                intent_path=paths["intent"],
                job_id=job_id,
                source="scheduler_reconciliation",
                sbatch_stdout=None,
                scheduler_evidence={
                    "query": {key: value for key, value in snapshot.items() if key != "records"},
                    "exact_comment_matches": matches,
                    "direct_job": evidence,
                },
            )
            _write_json_once_atomic(paths["receipt"], receipt, "evaluation submission receipt")
            validate_submission_receipt(paths["receipt"], plan, paths["intent"])
            receipts.append(receipt)
    return {
        "study_id": STUDY_ID,
        "state_root": str(authority["state_root"]),
        "scheduler_mutation": False,
        "submission_receipts": receipts,
    }


def _recovery_candidates(
    authority: dict[str, Any],
    status: dict[str, Any],
    requested: list[str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if not requested or len(requested) > MAX_TASKS_PER_INVOCATION:
        raise ValueError(f"Terminalize requires one to {MAX_TASKS_PER_INVOCATION} explicit --task values")
    if len(requested) != len(set(requested)):
        raise ValueError("Terminalize task values must be unique")
    receipts_by_task: dict[str, list[dict[str, Any]]] = {}
    for item in status["receipts"]:
        receipts_by_task.setdefault(item["plan"]["task_id"], []).append(item)
    candidates = []
    for task_id in requested:
        task = authority["task_by_id"].get(task_id)
        if task is None:
            raise ValueError(f"Unknown task outside the immutable plan: {task_id}")
        submissions = receipts_by_task.get(task_id, [])
        if not submissions:
            raise ValueError(f"Task has no protected scheduler submission to terminalize: {task_id}")
        latest = max(submissions, key=lambda item: item["plan"]["attempt"])
        attempt = latest["plan"]["attempt"]
        expected_attempt = next_attempt(task)
        if attempt != expected_attempt:
            raise ValueError(f"Task does not have a missing terminal plan receipt at attempt {attempt}: {task_id}")
        receipt_path = Path(task["receipt_dir"]) / f"attempt_{attempt:04d}.json"
        if receipt_path.exists():
            raise ValueError(f"Task attempt already has a terminal plan receipt: {task_id}/{attempt}")
        candidates.append((task, latest))
    return candidates


def _canonical_slurm_time(value: str, fallback: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
        return f"{value}Z"
    return fallback


def recovered_terminal_receipt(
    *,
    authority: dict[str, Any],
    task: dict[str, Any],
    submission: dict[str, Any],
    terminal: dict[str, Any],
) -> tuple[task_runner.AttemptContext, dict[str, Any]]:
    plan = submission["plan"]
    receipt_path, predecessor_sha256 = task_runner.attempt_predecessor(task, plan["attempt"])
    intent_path = Path(plan["paths"]["intent"])
    _, dispatch_intent = task_runner.read_canonical_json(intent_path)
    fallback_start = str(dispatch_intent["created_at"])
    fallback_finish = _utc_now()
    started_at = _canonical_slurm_time(str(terminal["start_time"]), fallback_start)
    finished_at = _canonical_slurm_time(str(terminal["end_time"]), fallback_finish)
    if _parse_utc(finished_at, "terminal receipt finished_at") < _parse_utc(
        started_at,
        "terminal receipt started_at",
    ):
        finished_at = fallback_finish
    context = task_runner.AttemptContext(
        plan_context=authority["plan_context"],
        task=task,
        attempt=plan["attempt"],
        receipt_path=receipt_path,
        predecessor_receipt_sha256=predecessor_sha256,
        scheduler=terminal,
        dispatch_intent=task_runner.file_identity(intent_path),
    )
    status = str(terminal["recovered_plan_status"])
    if status == "succeeded":
        raise RuntimeError("Protected terminalization is forbidden from synthesizing success")
    exit_text = str(terminal["terminal_exit_code"]).split(":", maxsplit=1)[0]
    exit_code = int(exit_text) if exit_text.isdecimal() else None
    failure = (
        "protected scheduler terminalization after runner receipt absence: "
        f"state={terminal['terminal_state']} exit_code={terminal['terminal_exit_code']}"
    )
    receipt = task_runner.build_terminal_receipt(
        context,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        failure=failure,
    )
    receipt["terminalization"] = {
        "runner_terminal_receipt_observed": False,
        "scheduler_terminal_state_proved": True,
        "success_synthesis_allowed": False,
        "submission_receipt": task_runner.file_identity(Path(plan["paths"]["receipt"])),
    }
    return context, receipt


def terminalize(args: argparse.Namespace) -> dict[str, Any]:
    authority = load_authority(args.plan)
    validate_state_root(args.state_root, authority)
    status = state_status(authority)
    candidates = _recovery_candidates(authority, status, args.task)
    previews = []
    for task, submission in candidates:
        job_id = int(submission["receipt"]["job_id"])
        terminal = terminal_scheduler_record(job_id, submission["plan"])
        context, receipt = recovered_terminal_receipt(
            authority=authority,
            task=task,
            submission=submission,
            terminal=terminal,
        )
        previews.append(
            {
                "task_id": task["task_id"],
                "attempt": context.attempt,
                "receipt_path": str(context.receipt_path),
                "status": receipt["status"],
                "scheduler": terminal,
            }
        )
    if args.dry_run:
        return {
            "study_id": STUDY_ID,
            "state_root": str(authority["state_root"]),
            "scheduler_mutation": False,
            "receipt_mutation": False,
            "terminalizations": previews,
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual terminalization requires --confirm-study-id {STUDY_ID}")
    require_control_tmux(authority["control_tmux"])
    lock_path = authority["state_root"] / STATE_LOCK_NAME
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        authority = load_authority(args.plan)
        status = state_status(authority)
        candidates = _recovery_candidates(authority, status, args.task)
        identities = []
        for task, submission in candidates:
            terminal = terminal_scheduler_record(int(submission["receipt"]["job_id"]), submission["plan"])
            context, receipt = recovered_terminal_receipt(
                authority=authority,
                task=task,
                submission=submission,
                terminal=terminal,
            )
            identities.append(task_runner.write_terminal_receipt(context, receipt))
    return {
        "study_id": STUDY_ID,
        "state_root": str(authority["state_root"]),
        "scheduler_mutation": False,
        "receipt_mutation": True,
        "terminal_receipts": identities,
    }


def validate_runtime_dispatch(
    *,
    plan_context: task_runner.PlanContext,
    dispatch_intent_path: Path,
    task_id: str,
    attempt: int,
    scheduler_job_id: str,
) -> dict[str, Any]:
    authority = authority_from_plan_context(plan_context)
    task = authority["task_by_id"].get(task_id)
    if task is None:
        raise ValueError(f"Runtime task is absent from the immutable plan: {task_id}")
    plan = build_task_plan(authority, task, attempt)
    expected_path = Path(plan["paths"]["intent"])
    if dispatch_intent_path.expanduser().resolve() != expected_path:
        raise ValueError("Runtime dispatch intent path differs from the content-addressed state path")
    observed = validate_task_intent(expected_path, authority, plan)
    if JOB_ID_RE.fullmatch(scheduler_job_id) is None:
        raise ValueError("Runtime scheduler job ID is invalid")
    evidence = verify_direct_job(int(scheduler_job_id), plan)
    return {
        "dispatch_intent": task_runner.file_identity(expected_path),
        "dispatch_record": observed,
        "scheduler": {
            "job_id": scheduler_job_id,
            "array_task_id": None,
            "comment": plan["comment"],
            "job_name": plan["scheduler"]["job_name"],
            "account": plan["scheduler"]["account"],
            "qos": plan["scheduler"]["qos"],
            "submitted_batch_script_sha256": evidence["submitted_batch_script_sha256"],
        },
    }


def _immutable_dispatch_artifact_snapshot(state_root: Path) -> dict[str, dict[str, Any]]:
    if not state_root.exists():
        return {}
    records = {}
    for path in sorted(state_root.rglob("*")):
        relative = path.relative_to(state_root)
        if relative.parts[0] == "logs" or relative == Path(STATE_LOCK_NAME):
            continue
        if path.is_symlink():
            raise ValueError(f"Evaluation dispatch state contains a symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Evaluation dispatch state contains a non-file artifact: {path}")
        _require_read_only(path, "Immutable evaluation dispatch artifact")
        records[relative.as_posix()] = task_runner.file_identity(path)
    return records


def _terminal_receipt_snapshot(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for task in plan["tasks"]:
        receipt_dir = Path(str(task["receipt_dir"])).resolve()
        if not receipt_dir.exists():
            continue
        if not receipt_dir.is_dir() or receipt_dir.is_symlink():
            raise ValueError(f"Evaluation receipt path is not a plain directory: {receipt_dir}")
        for path in sorted(receipt_dir.iterdir()):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Evaluation receipt is not a plain file: {path}")
            if task_runner.RECEIPT_NAME_RE.fullmatch(path.name) is None:
                raise ValueError(f"Unexpected evaluation receipt artifact: {path}")
            _require_read_only(path, "Evaluation terminal receipt")
            records[str(path.resolve())] = task_runner.file_identity(path)
    return records


def _terminal_receipts(
    authority: dict[str, Any],
) -> list[tuple[dict[str, Any], Path, bytes, dict[str, Any]]]:
    context = authority["plan_context"]
    records = []
    for task in context.plan["tasks"]:
        task_id = str(task["task_id"])
        receipt_dir = Path(str(task["receipt_dir"])).resolve()
        if not receipt_dir.exists():
            continue
        attempts = []
        for path in sorted(receipt_dir.iterdir()):
            match = task_runner.RECEIPT_NAME_RE.fullmatch(path.name)
            if match is None:
                raise ValueError(f"Unexpected evaluation receipt artifact: {path}")
            attempts.append((int(match.group(1)), path))
        if [attempt for attempt, _ in attempts] != list(range(1, len(attempts) + 1)):
            raise ValueError(f"Evaluation receipt attempts are not contiguous: {task_id}")

        predecessor_sha256 = None
        predecessor_status = None
        for attempt, path in attempts:
            identity_before = task_runner.file_identity(path)
            raw, receipt = task_runner.read_canonical_json(path)
            if task_runner.file_identity(path) != identity_before:
                raise RuntimeError(f"Evaluation terminal receipt changed while reading: {path}")
            expected_common = {
                "schema_version": task_runner.SCHEMA_VERSION,
                "artifact_type": task_runner.RECEIPT_ARTIFACT_TYPE,
                "plan_id": context.plan["plan_id"],
                "plan_sha256": context.plan_sha256,
                "task_id": task_id,
                "attempt": attempt,
                "predecessor_receipt_sha256": predecessor_sha256,
                "config_bundle_sha256": task["config_bundle_sha256"],
                "checkpoint_inventory_sha256": task["checkpoint_inventory_sha256"],
                "result_root": task["result_root"],
            }
            for field, expected in expected_common.items():
                if receipt.get(field) != expected:
                    raise ValueError(f"Evaluation terminal receipt {field} differs: {path}")
            status = receipt.get("status")
            if status not in task_runner.TERMINAL_STATUSES:
                raise ValueError(f"Evaluation receipt status is not terminal: {path}")
            if predecessor_status == "succeeded":
                raise ValueError(f"Evaluation receipt follows a succeeded attempt: {path}")
            started_at = _parse_utc(receipt.get("started_at"), f"{path} started_at")
            finished_at = _parse_utc(receipt.get("finished_at"), f"{path} finished_at")
            if finished_at < started_at:
                raise ValueError(f"Evaluation receipt finishes before it starts: {path}")
            expected_fields = set(TERMINAL_RECEIPT_BASE_FIELDS)
            if status == "succeeded":
                expected_fields.add("shards")
                if receipt.get("exit_code") != 0 or not isinstance(receipt.get("shards"), list):
                    raise ValueError(f"Succeeded evaluation receipt has invalid result fields: {path}")
            else:
                expected_fields.add("failure")
                if "terminalization" in receipt:
                    expected_fields.add("terminalization")
                exit_code = receipt.get("exit_code")
                if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
                    raise ValueError(f"Unsuccessful evaluation receipt has an invalid exit code: {path}")
                if not isinstance(receipt.get("failure"), str) or not receipt["failure"]:
                    raise ValueError(f"Unsuccessful evaluation receipt has no failure: {path}")
            if set(receipt) != expected_fields:
                raise ValueError(f"Evaluation terminal receipt has the wrong exact schema: {path}")
            predecessor_sha256 = hashlib.sha256(raw).hexdigest()
            predecessor_status = str(status)
            records.append((task, path, raw, receipt))
    return records


def _validate_terminal_scheduler_identity(
    scheduler: dict[str, Any],
    *,
    plan: dict[str, Any],
    submission: dict[str, Any],
) -> str:
    submission_job_id = submission.get("job_id")
    if isinstance(submission_job_id, bool) or not isinstance(submission_job_id, int) or submission_job_id < 1:
        raise ValueError("Terminal attempt submission receipt has an invalid scheduler job ID")
    job_id = str(submission_job_id)
    if JOB_ID_RE.fullmatch(job_id) is None:
        raise ValueError("Terminal attempt submission receipt has an invalid scheduler job ID")
    expected = {
        "job_id": job_id,
        "array_task_id": None,
        "comment": plan["comment"],
        "job_name": plan["scheduler"]["job_name"],
        "account": plan["scheduler"]["account"],
        "qos": plan["scheduler"]["qos"],
        "submitted_batch_script_sha256": plan["sbatch"]["sha256"],
    }
    for field, value in expected.items():
        if scheduler.get(field) != value:
            raise ValueError(
                f"Terminal receipt scheduler {field} differs for {plan['task_id']} attempt {plan['attempt']}"
            )
    if submission["comment"] != plan["comment"] or submission["sbatch"] != plan["sbatch"]:
        raise ValueError("Submission receipt is not bound to the terminal receipt dispatch plan")
    return job_id


def _validate_terminal_query(query: dict[str, Any], job_id: str) -> datetime:
    expected_fields = {
        "queried_at",
        "squeue_command",
        "squeue_stdout_sha256",
        "sacct_command",
        "sacct_stdout_sha256",
    }
    if set(query) != expected_fields:
        raise ValueError("Recovered terminal scheduler query has the wrong exact schema")
    queried_at = _parse_utc(query["queried_at"], "terminal scheduler queried_at")
    expected_squeue = ["squeue", "--noheader", "--jobs", job_id, f"--format={SQUEUE_FORMAT}"]
    expected_sacct = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--jobs",
        job_id,
        f"--format={','.join(TERMINAL_SACCT_FIELDS)}",
    ]
    if query["squeue_command"] != expected_squeue or query["sacct_command"] != expected_sacct:
        raise ValueError("Recovered terminal scheduler query records a different exact job query")
    for field in ("squeue_stdout_sha256", "sacct_stdout_sha256"):
        if task_runner.SHA256_RE.fullmatch(str(query[field])) is None:
            raise ValueError(f"Recovered terminal scheduler query has an invalid {field}")
    return queried_at


def _validate_terminal_allocation_evidence(
    evidence: dict[str, Any],
    *,
    receipt: dict[str, Any],
    scheduler: dict[str, Any],
    plan: dict[str, Any],
    submission: dict[str, Any],
    job_id: str,
) -> None:
    expected_fields = {
        "queried_at",
        "sacct_command",
        "sacct_stdout",
        "sacct_stdout_sha256",
        "submitted_batch_script_command",
        "record",
        "submitted_batch_script_sha256",
    }
    if set(evidence) != expected_fields:
        raise ValueError("Terminal allocation evidence has the wrong exact schema")
    expected_sacct = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--jobs",
        job_id,
        f"--format={VALIDATION_SACCT_FORMAT}",
    ]
    expected_script_command = ["scontrol", "write", "batch_script", job_id, "-"]
    if evidence["sacct_command"] != expected_sacct:
        raise ValueError("Terminal allocation evidence records a different sacct query")
    if evidence["submitted_batch_script_command"] != expected_script_command:
        raise ValueError("Terminal allocation evidence records a different submitted-script query")
    _parse_utc(evidence["queried_at"], "terminal allocation queried_at")
    sacct_stdout = evidence["sacct_stdout"]
    if not isinstance(sacct_stdout, str):
        raise ValueError("Terminal allocation evidence has invalid sacct stdout")
    if (
        task_runner.SHA256_RE.fullmatch(str(evidence["sacct_stdout_sha256"])) is None
        or hashlib.sha256(sacct_stdout.encode()).hexdigest() != evidence["sacct_stdout_sha256"]
    ):
        raise ValueError("Terminal allocation evidence has an invalid sacct stdout hash")
    record = _require_dict(evidence.get("record"), "terminal allocation record")
    record_fields = {"job_id", "comment", "job_name", "account", "qos", "state", "exit_code"}
    if set(record) != record_fields or record.get("job_id") != job_id:
        raise ValueError("Terminal allocation record has the wrong exact identity")
    if _parse_terminal_allocation_stdout(sacct_stdout, int(job_id)) != record:
        raise ValueError("Terminal allocation record differs from captured sacct stdout")
    _validate_scheduler_record({**record, "job_id": int(job_id)}, plan)
    script_sha256 = evidence.get("submitted_batch_script_sha256")
    if script_sha256 != plan["sbatch"]["sha256"] or script_sha256 != submission["sbatch"]["sha256"]:
        raise ValueError("Terminal allocation submitted script differs from the immutable submission")
    state = record.get("state")
    exit_code = record.get("exit_code")
    if not isinstance(state, str) or not _is_terminal_state(state):
        raise ValueError(f"Scheduler allocation for job {job_id} is not terminal")
    if not isinstance(exit_code, str) or re.fullmatch(r"[0-9]+:[0-9]+", exit_code) is None:
        raise ValueError("Terminal allocation exit code is invalid")

    if "terminalization" in receipt:
        frozen_state = scheduler.get("terminal_state")
        normalized_state = state.split(maxsplit=1)[0].rstrip("+")
        normalized_frozen = frozen_state.split(maxsplit=1)[0].rstrip("+") if isinstance(frozen_state, str) else None
        if normalized_state != normalized_frozen or exit_code != scheduler.get("terminal_exit_code"):
            raise ValueError("Terminal allocation differs from the frozen recovery proof")
        return
    normalized_state = state.split(maxsplit=1)[0].rstrip("+")
    process_exit, signal_exit = (int(value) for value in exit_code.split(":", maxsplit=1))
    if receipt["status"] == "succeeded":
        if normalized_state != "COMPLETED" or (process_exit, signal_exit) != (0, 0):
            raise ValueError("Succeeded runner receipt lacks COMPLETED/0:0 terminal allocation proof")
        return
    if normalized_state == "COMPLETED" or (process_exit, signal_exit) == (0, 0):
        raise ValueError("Unsuccessful runner receipt lacks nonzero terminal allocation proof")
    if receipt["status"] != recovered_plan_status(state):
        raise ValueError("Runner receipt status differs from the terminal allocation state")


def _validate_recovered_terminal_receipt(
    receipt: dict[str, Any],
    *,
    scheduler: dict[str, Any],
    plan: dict[str, Any],
    submission_identity: dict[str, Any],
    task_intent: dict[str, Any],
    job_id: str,
) -> None:
    if receipt["status"] == "succeeded":
        raise ValueError("Protected scheduler terminalization cannot synthesize success")
    if set(scheduler) != RECOVERED_SCHEDULER_FIELDS:
        raise ValueError("Recovered terminal scheduler identity has the wrong exact schema")
    state = scheduler.get("terminal_state")
    expected_status = recovered_plan_status(state) if isinstance(state, str) else None
    if receipt["status"] != expected_status or scheduler.get("recovered_plan_status") != expected_status:
        raise ValueError("Recovered terminal status differs from the proved scheduler state")
    exit_code = scheduler.get("terminal_exit_code")
    if not isinstance(exit_code, str) or re.fullmatch(r"[0-9]+:[0-9]+", exit_code) is None:
        raise ValueError("Recovered terminal scheduler exit code is invalid")
    expected_exit_code = int(exit_code.split(":", maxsplit=1)[0])
    if receipt["exit_code"] != expected_exit_code:
        raise ValueError("Recovered terminal receipt exit code differs from scheduler proof")
    elapsed = scheduler.get("elapsed_seconds")
    if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed < 0:
        raise ValueError("Recovered terminal scheduler elapsed time is invalid")
    for field in ("submit_time", "start_time", "end_time"):
        if not isinstance(scheduler.get(field), str):
            raise ValueError(f"Recovered terminal scheduler {field} is not a string")
    queried_at = _validate_terminal_query(
        _require_dict(scheduler.get("terminal_query"), "terminal scheduler query"),
        job_id,
    )
    terminalization = _require_dict(receipt.get("terminalization"), "terminalization proof")
    expected_terminalization = {
        "runner_terminal_receipt_observed": False,
        "scheduler_terminal_state_proved": True,
        "success_synthesis_allowed": False,
        "submission_receipt": submission_identity,
    }
    if terminalization != expected_terminalization:
        raise ValueError("Recovered terminalization proof differs from the immutable submission")
    expected_failure = (
        f"protected scheduler terminalization after runner receipt absence: state={state} exit_code={exit_code}"
    )
    if receipt["failure"] != expected_failure:
        raise ValueError("Recovered terminal failure description differs from scheduler proof")

    started_at = _canonical_slurm_time(scheduler["start_time"], str(task_intent["created_at"]))
    if receipt["started_at"] != started_at:
        raise ValueError("Recovered terminal start time differs from scheduler proof")
    raw_finished_at = _canonical_slurm_time(scheduler["end_time"], receipt["finished_at"])
    if _parse_utc(raw_finished_at, "recovered terminal finished_at") >= _parse_utc(
        started_at,
        "recovered terminal started_at",
    ):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", scheduler["end_time"]):
            if receipt["finished_at"] != raw_finished_at:
                raise ValueError("Recovered terminal finish time differs from scheduler proof")
        elif _parse_utc(receipt["finished_at"], "recovered terminal fallback finished_at") < queried_at:
            raise ValueError("Recovered terminal fallback finish predates its scheduler query")
    elif _parse_utc(receipt["finished_at"], "recovered terminal fallback finished_at") < queried_at:
        raise ValueError("Recovered terminal fallback finish predates its scheduler query")


def validate_terminal_receipt_provenance(
    authority: dict[str, Any],
    *,
    terminal_allocations: dict[tuple[str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = authority["plan_context"]
    state_root = authority["state_root"]
    dispatch_snapshot_before = _immutable_dispatch_artifact_snapshot(state_root)
    terminal_snapshot_before = _terminal_receipt_snapshot(context.plan)
    status = state_status(authority)
    if status["global_intent"] is None:
        raise ValueError("Terminal evaluation receipts have no immutable global dispatch intent")
    if status["pending"] or status["script_only"]:
        raise ValueError("Terminal evaluation validation found incomplete protected dispatch state")

    submission_by_attempt = {}
    for item in status["receipts"]:
        plan = item["plan"]
        key = (str(plan["task_id"]), int(plan["attempt"]))
        if key in submission_by_attempt:
            raise ValueError(f"Duplicate protected submission for terminal attempt: {key}")
        submission_by_attempt[key] = item

    terminal_records = _terminal_receipts(authority)
    terminal_keys = {(str(receipt["task_id"]), int(receipt["attempt"])) for _, _, _, receipt in terminal_records}
    if terminal_keys != set(submission_by_attempt):
        missing_submissions = sorted(terminal_keys - set(submission_by_attempt))
        missing_terminals = sorted(set(submission_by_attempt) - terminal_keys)
        raise ValueError(
            "Terminal receipts and immutable submissions differ: "
            f"missing_submissions={missing_submissions}, missing_terminals={missing_terminals}"
        )

    global_path = state_root / GLOBAL_INTENT_NAME
    global_identity = task_runner.file_identity(global_path)
    expected_runner = _require_dict(authority["execution_source"].get("runner"), "execution runner")
    seen_job_ids = set()
    attempts = []
    task_statuses = {}
    runner_count = 0
    recovered_count = 0
    used_allocation_keys = set()
    for task, receipt_path, _, receipt in terminal_records:
        key = (str(receipt["task_id"]), int(receipt["attempt"]))
        item = submission_by_attempt[key]
        plan = item["plan"]
        submission = item["receipt"]
        intent_path = Path(plan["paths"]["intent"])
        submission_path = Path(plan["paths"]["receipt"])
        task_intent = validate_task_intent(intent_path, authority, plan)
        validate_submission_receipt(submission_path, plan, intent_path)
        intent_identity = task_runner.file_identity(intent_path)
        submission_identity = task_runner.file_identity(submission_path)
        if receipt.get("dispatch_intent") != intent_identity:
            raise ValueError(f"Terminal receipt binds a different task dispatch intent: {receipt_path}")
        if receipt.get("runner") != expected_runner:
            raise ValueError(f"Terminal receipt records a different pinned runner: {receipt_path}")
        scheduler = _require_dict(receipt.get("scheduler"), "terminal scheduler identity")
        job_id = _validate_terminal_scheduler_identity(
            scheduler,
            plan=plan,
            submission=submission,
        )
        if job_id in seen_job_ids:
            raise ValueError(f"Multiple terminal attempts claim scheduler job {job_id}")
        seen_job_ids.add(job_id)
        if terminal_allocations is None:
            allocation = terminal_allocation_evidence(int(job_id), plan)
        else:
            if key not in terminal_allocations:
                raise ValueError(f"Terminal provenance has no frozen allocation evidence for {key}")
            allocation = _require_dict(terminal_allocations[key], "frozen terminal allocation evidence")
            used_allocation_keys.add(key)
        _validate_terminal_allocation_evidence(
            allocation,
            receipt=receipt,
            scheduler=scheduler,
            plan=plan,
            submission=submission,
            job_id=job_id,
        )

        if "terminalization" in receipt:
            _validate_recovered_terminal_receipt(
                receipt,
                scheduler=scheduler,
                plan=plan,
                submission_identity=submission_identity,
                task_intent=task_intent,
                job_id=job_id,
            )
            provenance_kind = "scheduler_recovered_failure"
            recovered_count += 1
        else:
            if set(scheduler) != RUNNER_SCHEDULER_FIELDS:
                raise ValueError("Runner-produced terminal scheduler identity has the wrong exact schema")
            provenance_kind = "pinned_runner"
            runner_count += 1

        batch_identity = _require_dict(task_intent.get("batch_dispatch_intent"), "batch dispatch identity")
        if _require_dict(task_intent.get("global_dispatch_intent"), "global dispatch identity") != global_identity:
            raise ValueError("Terminal task dispatch binds a different global intent")
        attempts.append(
            {
                "task_id": key[0],
                "attempt": key[1],
                "status": receipt["status"],
                "provenance_kind": provenance_kind,
                "terminal_receipt": task_runner.file_identity(receipt_path),
                "task_dispatch_intent": intent_identity,
                "batch_dispatch_intent": batch_identity,
                "global_dispatch_intent": global_identity,
                "submission_receipt": submission_identity,
                "sealed_batch_script": plan["sbatch"],
                "job_id": job_id,
                "comment": plan["comment"],
                "job_name": plan["scheduler"]["job_name"],
                "account": plan["scheduler"]["account"],
                "qos": plan["scheduler"]["qos"],
                "submitted_batch_script_sha256": plan["sbatch"]["sha256"],
                "terminal_allocation": allocation,
            }
        )
        task_statuses[key[0]] = str(receipt["status"])

    if terminal_allocations is not None and used_allocation_keys != set(terminal_allocations):
        unexpected = sorted(set(terminal_allocations) - used_allocation_keys)
        raise ValueError(f"Terminal provenance has allocation evidence for unknown attempts: {unexpected}")

    dispatch_snapshot_after = _immutable_dispatch_artifact_snapshot(state_root)
    terminal_snapshot_after = _terminal_receipt_snapshot(context.plan)
    if dispatch_snapshot_after != dispatch_snapshot_before:
        raise RuntimeError("Immutable evaluation dispatch state changed during terminal validation")
    if terminal_snapshot_after != terminal_snapshot_before:
        raise RuntimeError("Evaluation terminal receipts changed during provenance validation")
    if task_runner.file_identity(context.plan_path) != authority["plan_identity"]:
        raise RuntimeError("Evaluation plan changed during terminal provenance validation")
    return {
        "command": "validate-terminals",
        "study_id": STUDY_ID,
        "plan": authority["plan_identity"],
        "state_root": str(state_root),
        "global_dispatch_intent": global_identity,
        "terminal_receipt_count": len(attempts),
        "runner_produced_receipt_count": runner_count,
        "scheduler_recovered_failure_count": recovered_count,
        "task_statuses": {task_id: task_statuses[task_id] for task_id in sorted(task_statuses)},
        "attempts": sorted(attempts, key=lambda item: (item["task_id"], item["attempt"])),
        "scheduler_mutation": False,
        "receipt_mutation": False,
    }


def terminal_provenance_path(authority: dict[str, Any]) -> Path:
    context = authority["plan_context"]
    plan_root = Path(str(context.plan.get("plan_root", ""))).expanduser().resolve()
    if context.plan_path.parent != plan_root:
        raise ValueError("Evaluation plan root differs from its immutable plan path")
    return plan_root / TERMINAL_PROVENANCE_NAME


def _require_terminal_provenance_final_status(
    authority: dict[str, Any],
    task_statuses: dict[str, str],
) -> None:
    expected_task_ids = set(authority["task_by_id"])
    if set(task_statuses) != expected_task_ids or any(status != "succeeded" for status in task_statuses.values()):
        raise ValueError("Terminal provenance requires every planned task's latest attempt to have succeeded")


def _terminal_provenance_payload(
    authority: dict[str, Any],
    summary: dict[str, Any],
    *,
    captured_at: str,
) -> dict[str, Any]:
    captured = _parse_utc(captured_at, "terminal provenance captured_at")
    context = authority["plan_context"]
    implementations = _require_dict(context.plan.get("implementations"), "evaluation implementations")
    planner = _require_dict(implementations.get("planner"), "evaluation planner")
    attempts = summary["attempts"]
    task_statuses = summary["task_statuses"]
    _require_terminal_provenance_final_status(authority, task_statuses)
    for attempt in attempts:
        allocation = _require_dict(attempt.get("terminal_allocation"), "terminal allocation evidence")
        queried_at = _parse_utc(allocation.get("queried_at"), "terminal allocation queried_at")
        if queried_at > captured:
            raise ValueError("Terminal allocation query postdates the provenance capture")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": TERMINAL_PROVENANCE_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "terminal_provenance_path": str(terminal_provenance_path(authority)),
        "captured_at": captured_at,
        "capture_mode": "single_live_scheduler_capture_then_offline_replay",
        "plan": summary["plan"],
        "plan_id": context.plan["plan_id"],
        "plan_sha256": context.plan_sha256,
        "authority": {
            "planner": planner,
            "launch_intent": authority["launch_intent"],
            "postrun_authority": authority["postrun_authority"],
            "execution_source": authority["execution_source"],
        },
        "state_root": summary["state_root"],
        "global_dispatch_intent": summary["global_dispatch_intent"],
        "terminal_receipt_count": summary["terminal_receipt_count"],
        "runner_produced_receipt_count": summary["runner_produced_receipt_count"],
        "scheduler_recovered_failure_count": summary["scheduler_recovered_failure_count"],
        "task_statuses": summary["task_statuses"],
        "attempts": attempts,
        "scheduler_capture": {
            "allocation_query_count": len(attempts),
            "submitted_batch_script_query_count": len(attempts),
            "captures_terminal_allocation_identity": True,
            "captures_terminal_allocation_stdout": True,
            "captures_submitted_batch_script_sha256": True,
            "all_planned_tasks_latest_status_succeeded": True,
            "ordinary_validation_requires_live_scheduler": False,
        },
        "scheduler_mutation": False,
        "receipt_mutation": False,
    }


def build_terminal_provenance(authority: dict[str, Any]) -> dict[str, Any]:
    _require_terminal_provenance_final_status(
        authority,
        _task_terminal_statuses(authority["plan_context"].plan),
    )
    summary = validate_terminal_receipt_provenance(authority)
    payload = _terminal_provenance_payload(authority, summary, captured_at=_utc_now())
    payload["payload_without_self_hash_sha256"] = canonical_json_sha256(payload)
    return payload


def _validate_terminal_provenance_self_hash(payload: dict[str, Any]) -> None:
    self_hash = payload.get("payload_without_self_hash_sha256")
    if not isinstance(self_hash, str) or task_runner.SHA256_RE.fullmatch(self_hash) is None:
        raise ValueError("Terminal provenance has an invalid self hash")
    unhashed = dict(payload)
    unhashed.pop("payload_without_self_hash_sha256")
    if canonical_json_sha256(unhashed) != self_hash:
        raise ValueError("Terminal provenance self hash differs")


def _live_recheck_terminal_allocations(
    authority: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> int:
    for attempt in attempts:
        task_id = str(attempt["task_id"])
        task = authority["task_by_id"].get(task_id)
        if task is None:
            raise ValueError(f"Terminal provenance has an unknown task: {task_id}")
        plan = build_task_plan(authority, task, int(attempt["attempt"]))
        observed = terminal_allocation_evidence(int(attempt["job_id"]), plan)
        frozen = _require_dict(attempt["terminal_allocation"], "frozen terminal allocation evidence")
        for field in ("sacct_command", "submitted_batch_script_command", "record", "submitted_batch_script_sha256"):
            if observed[field] != frozen[field]:
                raise ValueError(f"Live terminal allocation recheck differs for {task_id}: {field}")
    return len(attempts)


def validate_terminal_provenance_artifact(
    authority: dict[str, Any],
    *,
    live_recheck: bool = False,
) -> dict[str, Any]:
    path = terminal_provenance_path(authority)
    _require_read_only(path, "Evaluation terminal provenance")
    initial_identity = task_runner.file_identity(path)
    _, observed = task_runner.read_canonical_json(path)
    expected_fields = {
        "schema_version",
        "artifact_type",
        "study_id",
        "terminal_provenance_path",
        "captured_at",
        "capture_mode",
        "plan",
        "plan_id",
        "plan_sha256",
        "authority",
        "state_root",
        "global_dispatch_intent",
        "terminal_receipt_count",
        "runner_produced_receipt_count",
        "scheduler_recovered_failure_count",
        "task_statuses",
        "attempts",
        "scheduler_capture",
        "scheduler_mutation",
        "receipt_mutation",
        "payload_without_self_hash_sha256",
    }
    if set(observed) != expected_fields:
        raise ValueError("Terminal provenance has the wrong exact schema")
    if (
        observed["schema_version"] != SCHEMA_VERSION
        or observed["artifact_type"] != TERMINAL_PROVENANCE_ARTIFACT_TYPE
        or observed["study_id"] != STUDY_ID
        or observed["terminal_provenance_path"] != str(path)
    ):
        raise ValueError("Terminal provenance has the wrong artifact identity")
    _validate_terminal_provenance_self_hash(observed)
    raw_attempts = observed.get("attempts")
    if not isinstance(raw_attempts, list) or any(not isinstance(item, dict) for item in raw_attempts):
        raise ValueError("Terminal provenance attempts are invalid")
    allocations = {}
    for attempt in raw_attempts:
        task_id = str(attempt.get("task_id"))
        attempt_number = attempt.get("attempt")
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number < 1:
            raise ValueError("Terminal provenance attempt number is invalid")
        key = (task_id, attempt_number)
        if key in allocations:
            raise ValueError(f"Terminal provenance repeats attempt {key}")
        allocations[key] = _require_dict(attempt.get("terminal_allocation"), "terminal allocation evidence")
    summary = validate_terminal_receipt_provenance(authority, terminal_allocations=allocations)
    expected = _terminal_provenance_payload(authority, summary, captured_at=str(observed["captured_at"]))
    expected["payload_without_self_hash_sha256"] = canonical_json_sha256(expected)
    if observed != expected:
        raise ValueError("Terminal provenance differs from exact offline replay")
    recheck_count = _live_recheck_terminal_allocations(authority, raw_attempts) if live_recheck else 0
    if task_runner.file_identity(path) != initial_identity:
        raise RuntimeError("Terminal provenance changed during validation")
    return {
        "identity": initial_identity,
        "artifact": observed,
        "summary": summary,
        "live_scheduler_recheck_count": recheck_count,
    }


def _terminal_validation_output(validated: dict[str, Any], *, live_recheck: bool) -> dict[str, Any]:
    artifact = validated["artifact"]
    return {
        **validated["summary"],
        "terminal_provenance": validated["identity"],
        "terminal_provenance_payload_without_self_hash_sha256": artifact["payload_without_self_hash_sha256"],
        "live_scheduler_recheck_performed": live_recheck,
        "live_scheduler_recheck_count": validated["live_scheduler_recheck_count"],
    }


def materialize_terminals(args: argparse.Namespace) -> dict[str, Any]:
    authority = load_authority(args.plan)
    validate_state_root(args.state_root, authority)
    path = terminal_provenance_path(authority)
    if path.exists():
        validated = validate_terminal_provenance_artifact(authority)
        return {
            **_terminal_validation_output(validated, live_recheck=False),
            "command": "materialize-terminals",
            "already_materialized": True,
            "artifact_mutation": False,
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Terminal provenance materialization requires --confirm-study-id {STUDY_ID}")
    if not authority["state_root"].is_dir():
        raise FileNotFoundError("Protected evaluation dispatch state does not exist")
    lock_path = authority["state_root"] / STATE_LOCK_NAME
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        authority = load_authority(args.plan)
        validate_state_root(args.state_root, authority)
        path = terminal_provenance_path(authority)
        already_materialized = path.exists()
        if not already_materialized:
            payload = build_terminal_provenance(authority)
            _write_json_once_atomic(path, payload, "evaluation terminal provenance")
        validated = validate_terminal_provenance_artifact(authority)
    return {
        **_terminal_validation_output(validated, live_recheck=False),
        "command": "materialize-terminals",
        "already_materialized": already_materialized,
        "artifact_mutation": not already_materialized,
    }


def validate_terminals(args: argparse.Namespace) -> dict[str, Any]:
    authority = load_authority(args.plan)
    validated = validate_terminal_provenance_artifact(authority, live_recheck=args.live_recheck)
    return _terminal_validation_output(validated, live_recheck=args.live_recheck)


def status(args: argparse.Namespace) -> dict[str, Any]:
    authority = load_authority(args.plan)
    validate_state_root(args.state_root, authority)
    current = state_status(authority)
    snapshot = scheduler_snapshot(
        start_time=_scheduler_start(current),
        job_names=list(authority["job_names"].values()),
    )
    current_plan_live = enforce_live_cap(authority, current, snapshot, selected_new_count=0)
    study_snapshot = study_live_snapshot()
    study_live = enforce_study_live_cap(authority, study_snapshot, selected_new_count=0)
    return {
        "study_id": STUDY_ID,
        "plan": authority["plan_identity"],
        "state_root": str(authority["state_root"]),
        "state": current["state"],
        "pending": [plan["task_id"] for plan in current["pending"]],
        "submission_count": len(current["receipts"]),
        "live_cap": {
            "study": study_live,
            "current_plan": current_plan_live,
            "study_scheduler_snapshot": {key: value for key, value in study_snapshot.items() if key != "records"},
        },
        "scheduler_mutation": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--plan", type=Path, required=True)
    dispatch_parser.add_argument("--state-root", type=Path, required=True)
    dispatch_parser.add_argument("--task", action="append", required=True)
    dispatch_parser.add_argument("--confirm-study-id")
    dispatch_parser.add_argument("--dry-run", action="store_true")
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--plan", type=Path, required=True)
    reconcile_parser.add_argument("--state-root", type=Path, required=True)
    reconcile_parser.add_argument("--task", action="append", required=True)
    reconcile_parser.add_argument("--confirm-study-id")
    reconcile_parser.add_argument("--dry-run", action="store_true")
    terminalize_parser = subparsers.add_parser("terminalize")
    terminalize_parser.add_argument("--plan", type=Path, required=True)
    terminalize_parser.add_argument("--state-root", type=Path, required=True)
    terminalize_parser.add_argument("--task", action="append", required=True)
    terminalize_parser.add_argument("--confirm-study-id")
    terminalize_parser.add_argument("--dry-run", action="store_true")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--plan", type=Path, required=True)
    status_parser.add_argument("--state-root", type=Path, required=True)
    materialize_terminals_parser = subparsers.add_parser("materialize-terminals")
    materialize_terminals_parser.add_argument("--plan", type=Path, required=True)
    materialize_terminals_parser.add_argument("--state-root", type=Path, required=True)
    materialize_terminals_parser.add_argument("--confirm-study-id")
    validate_terminals_parser = subparsers.add_parser("validate-terminals")
    validate_terminals_parser.add_argument("--plan", type=Path, required=True)
    validate_terminals_parser.add_argument("--live-recheck", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "dispatch":
        result = dispatch(args)
    elif args.command == "reconcile":
        result = reconcile(args)
    elif args.command == "terminalize":
        result = terminalize(args)
    elif args.command == "status":
        result = status(args)
    elif args.command == "materialize-terminals":
        result = materialize_terminals(args)
    elif args.command == "validate-terminals":
        result = validate_terminals(args)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
