#!/usr/bin/env python3
"""Finalize immutable Kimi TB4 v9 with benchmark/SFT score separation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import finalize_kimi_tb4_sandoq_small_v8_supersession as engine

EXECUTION_SOURCE_REVISION = "820d5167443913ed5bb2b3d72e16de442caa696a"
EXECUTION_VERIFIERS_COMMIT = "36b0dff6c18affb3d40b7c46d5836381d568050b"
EXECUTION_PLAN_SHA256 = "234af70091d5d93c73a3fba82d7215c92ba2f56704507158a91e97f001b1be4e"
EXECUTION_SLURM_JOB_ID = "1608879"
OUTPUT_NAME = "full-denominator-supersession-v3"
SUPERSESSION_REASON = "fixed-denominator-v9-length-score-sft-separated-exec-transport-zero"
SUPERSESSION_SOURCE_FILES = (
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v10.py",
    *engine.SUPERSESSION_SOURCE_FILES,
)
SLURM_JOB_RE = re.compile(r"[1-9][0-9]*\Z")


class V10FinalizationError(ValueError):
    """The requested producer cannot be bound to the immutable v9 audit."""


def execution_contract(slurm_job_id: str) -> engine.ExecutionContract:
    if (
        not isinstance(slurm_job_id, str)
        or SLURM_JOB_RE.fullmatch(slurm_job_id) is None
        or slurm_job_id != EXECUTION_SLURM_JOB_ID
    ):
        raise V10FinalizationError("execution_slurm_job_id_invalid")
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
    )


def finalize(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    supersession_source_revision: str,
    execution_slurm_job_id: str,
) -> dict[str, Any]:
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
            '{"code":"kimi_tb4_sandoq_small_v10_finalization_failed","state":"blocked"}',
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
