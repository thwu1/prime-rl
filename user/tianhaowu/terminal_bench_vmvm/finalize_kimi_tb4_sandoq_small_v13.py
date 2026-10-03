#!/usr/bin/env python3
"""Finalize the immutable v4 Kimi TB4 c16 execution with v13 policy."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import finalize_kimi_tb4_sandoq_small_v8_supersession as engine

EXECUTION_SOURCE_REVISION = "3a39b16535d4f77ba16336086441373756e29eda"
EXECUTION_VERIFIERS_COMMIT = "36b0dff6c18affb3d40b7c46d5836381d568050b"
EXECUTION_PLAN = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/"
    "kimi-tb4-small-v10-c16-plans-20260928/plan-p0-v4-3a39b165-r2/launch-plan.json"
)
EXECUTION_PLAN_SHA256 = "41fc96375ca18a1e1004a4b327953c25090df5539a80da347e85b2e6a00848b6"
EXECUTION_SLURM_JOB_ID = "1618064"
EXECUTION_PROJECT_ROOT = Path("/storage/home/tianhaowu/prime-kimi-tb4-v13-finalizer-1617454")
EXECUTION_RUN_DIR = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/"
    "tb4-kimi-stock1-c16-v10-p0-v4-3a39b165-r2-miniswe246-sandoq-firecracker-small"
)
STOCK_ENDPOINT_IDENTIFIER = "tianhaowu-kimi-k3-stock-rollout-20260928-v4"
STOCK_SOURCE_SPEC_SHA256 = "bf15fcaa7979bfef74dd58421ea7e68ef2166f424fc6043f1853d4f829c53f06"
STOCK_ENDPOINT_BUNDLE_SHA256 = "b09a14dc0fa6b67fea3987098eabb4b1660a3fdbbdc49988b8d063db028a8054"
OUTPUT_NAME = "full-denominator-supersession-v13"
SUPERSESSION_REASON = "fresh-epoch-v4-c16-exact-artifact-write-transport-policy-v13"
SUPERSESSION_SOURCE_FILES = (
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v13.py",
    "user/tianhaowu/terminal_bench_vmvm/run_finalize_kimi_tb4_sandoq_small_v13.sbatch",
    "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py",
    *engine.SUPERSESSION_SOURCE_FILES,
)
SLURM_JOB_RE = re.compile(r"[1-9][0-9]*\Z")


class V13FinalizationError(ValueError):
    """The requested producer is not the immutable v4 c16 execution."""


def execution_contract(slurm_job_id: str) -> engine.ExecutionContract:
    if (
        not isinstance(slurm_job_id, str)
        or SLURM_JOB_RE.fullmatch(slurm_job_id) is None
        or slurm_job_id != EXECUTION_SLURM_JOB_ID
    ):
        raise V13FinalizationError("execution_slurm_job_id_invalid")
    return engine.ExecutionContract(
        source_revision=EXECUTION_SOURCE_REVISION,
        verifiers_commit=EXECUTION_VERIFIERS_COMMIT,
        slurm_job_id=slurm_job_id,
        plan_sha256=EXECUTION_PLAN_SHA256,
        output_name=OUTPUT_NAME,
        supersession_reason=SUPERSESSION_REASON,
        supersession_source_files=SUPERSESSION_SOURCE_FILES,
        allow_exact_length_benchmark_passes=True,
        allow_post_agent_exec_transport_errors=True,
        allow_post_agent_artifact_write_transport_errors=True,
        plan_verifier="capacity-bound-v10",
        execution_project_root=str(EXECUTION_PROJECT_ROOT),
        supported_tasks=52,
        compose_unsupported_tasks=11,
        gpu_unsupported_tasks=3,
        concurrency=16,
        stock_endpoint_identifier=STOCK_ENDPOINT_IDENTIFIER,
        stock_source_spec_sha256=STOCK_SOURCE_SPEC_SHA256,
        stock_endpoint_bundle_sha256=STOCK_ENDPOINT_BUNDLE_SHA256,
        completion_marker_name="v10_execution_completion.json",
        require_persisted_verifier_artifacts=True,
    )


def finalize(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    supersession_source_revision: str,
    execution_slurm_job_id: str,
) -> dict[str, Any]:
    if plan_path != EXECUTION_PLAN or plan_sha256 != EXECUTION_PLAN_SHA256 or run_dir != EXECUTION_RUN_DIR:
        raise V13FinalizationError("execution_artifact_binding_invalid")
    return engine.finalize(
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        run_dir=run_dir,
        supersession_source_revision=supersession_source_revision,
        execution_contract=execution_contract(execution_slurm_job_id),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--supersession-source-revision", required=True)
    parser.add_argument("--execution-slurm-job-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            run_dir=args.run_dir,
            supersession_source_revision=args.supersession_source_revision,
            execution_slurm_job_id=args.execution_slurm_job_id,
        )
    except (OSError, RuntimeError, ValueError):
        print(
            '{"code":"kimi_tb4_sandoq_small_v13_finalization_failed","state":"blocked"}',
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
