#!/usr/bin/env python3
"""Run one plan-bound checkpoint-kernel task into an attempt-local candidate."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import materialize_known_cost_checkpoint_kernel_plan as plan_module
import materialize_known_cost_checkpoint_kernel_readiness as readiness_module
import probe_known_cost_checkpoint_kernel as checkpoint_probe

ATTEMPT_ID_RE = re.compile(r"[1-9][0-9]*")


def execution_binding(
    *,
    plan_path: Path,
    readiness_path: Path,
    task_id: str,
    attempt_id: str,
    candidate_path: Path,
    summary_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if ATTEMPT_ID_RE.fullmatch(attempt_id) is None:
        raise ValueError("attempt_id must be a positive decimal SLURM job ID")
    live_job_id = os.environ.get("SLURM_JOB_ID")
    if live_job_id != attempt_id:
        raise ValueError(f"Live SLURM_JOB_ID {live_job_id!r} differs from attempt {attempt_id}")
    plan_identity = plan_module.validate_plan(plan_path)
    readiness_identity = readiness_module.validate_readiness(readiness_path)
    _, plan = plan_module.read_canonical_json(plan_path)
    _, readiness = plan_module.read_canonical_json(readiness_path)
    if readiness.get("plan") != plan_identity or readiness.get("plan_id") != plan.get("plan_id"):
        raise ValueError("Readiness belongs to another plan")
    task = readiness.get("task")
    if not isinstance(task, dict) or task.get("task_id") != task_id:
        raise ValueError("Readiness belongs to another task")
    if readiness.get("task_spec_sha256") != plan_module.canonical_json_sha256(task):
        raise ValueError("Readiness task hash differs")
    plan_root = Path(str(plan_identity["path"])).parent
    expected_candidate = plan_root / "attempts" / task_id / attempt_id / "candidate.json"
    expected_summary = plan_root / "attempts" / task_id / attempt_id / "runner_summary.json"
    candidate_path = candidate_path.expanduser().resolve()
    summary_path = summary_path.expanduser().resolve()
    if candidate_path != expected_candidate:
        raise ValueError(f"Attempt candidate must be {expected_candidate}")
    if summary_path != expected_summary:
        raise ValueError(f"Attempt summary must be {expected_summary}")
    canonical_output = Path(str(readiness["paths"]["canonical_output"])).expanduser().resolve()
    if candidate_path.exists():
        raise FileExistsError(f"Attempt candidate already exists: {candidate_path}")
    if summary_path.exists():
        raise FileExistsError(f"Attempt runner summary already exists: {summary_path}")
    if canonical_output.exists():
        raise FileExistsError(f"Canonical result predates this attempt: {canonical_output}")
    slurm = {
        "job_id": attempt_id,
        "job_name": os.environ.get("SLURM_JOB_NAME"),
        "account": os.environ.get("SLURM_JOB_ACCOUNT"),
        "qos": os.environ.get("SLURM_JOB_QOS"),
        "node_list": os.environ.get("SLURM_JOB_NODELIST"),
        "submit_dir": os.environ.get("SLURM_SUBMIT_DIR"),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    if any(value in (None, "") for value in slurm.values()):
        raise ValueError(f"Incomplete SLURM execution environment: {slurm}")
    binding = {
        "plan": plan_identity,
        "plan_id": plan["plan_id"],
        "readiness": readiness_identity,
        "task_id": task_id,
        "task_spec_sha256": readiness["task_spec_sha256"],
        "attempt_id": attempt_id,
        "candidate_path": str(candidate_path),
        "runner_summary_path": str(summary_path),
        "canonical_output_path": str(canonical_output),
        "runner_implementation": checkpoint_probe.source_identity(Path(__file__)),
        "checkpoint_probe_implementation": checkpoint_probe.source_identity(Path(checkpoint_probe.__file__)),
        "slurm_environment": slurm,
        "argv": [str(Path(sys.executable).resolve()), *sys.argv],
    }
    return binding, task, readiness


def run_task(
    *,
    plan_path: Path,
    readiness_path: Path,
    task_id: str,
    attempt_id: str,
    candidate_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    binding, task, readiness = execution_binding(
        plan_path=plan_path,
        readiness_path=readiness_path,
        task_id=task_id,
        attempt_id=attempt_id,
        candidate_path=candidate_path,
        summary_path=summary_path,
    )
    source_probe = Path(str(readiness["probe_context"]["source_probe"]["directory"]))
    checkpoint = Path(str(task["model_path"]))
    receipt_value = task.get("completion_receipt_path")
    receipt = Path(str(receipt_value)) if receipt_value is not None else None
    analysis = checkpoint_probe.build_analysis(
        source_probe,
        checkpoint,
        receipt,
        int(task["checkpoint_step"]),
    )
    analysis["execution_binding"] = binding
    analysis["payload_without_self_hash_sha256"] = checkpoint_probe.canonical_json_sha256(
        {key: value for key, value in analysis.items() if key != "payload_without_self_hash_sha256"}
    )
    identity = checkpoint_probe.write_once(candidate_path, analysis)
    checkpoint_probe.validate(candidate_path)
    _, recorded = checkpoint_probe.read_canonical_json(candidate_path)
    if recorded.get("execution_binding") != binding:
        raise ValueError("Attempt candidate lost its plan execution binding")
    canonical_output = Path(str(binding["canonical_output_path"]))
    if canonical_output.exists():
        raise FileExistsError("Canonical output appeared during attempt execution")
    summary: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "rsci_known_cost_checkpoint_kernel_runner_summary",
        "candidate": identity,
        "candidate_sha256": identity["sha256"],
        "plan_id": binding["plan_id"],
        "task_id": task_id,
        "attempt_id": attempt_id,
        "already_complete": False,
        "canonical_output_published": False,
        "scheduler_mutation": False,
    }
    summary["payload_without_self_hash_sha256"] = checkpoint_probe.canonical_json_sha256(summary)
    summary_identity = checkpoint_probe.write_once(summary_path, summary)
    return {**summary, "runner_summary": summary_identity}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_task(
        plan_path=args.plan,
        readiness_path=args.readiness,
        task_id=args.task_id,
        attempt_id=args.attempt_id,
        candidate_path=args.candidate,
        summary_path=args.summary,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
