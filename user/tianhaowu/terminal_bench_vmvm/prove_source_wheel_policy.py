#!/usr/bin/env python3
"""Discover and prove a private source-wheel policy with independent VMVM builds."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
from pathlib import Path

from terminal_bench_vmvm.source_wheel_proof import (
    MAX_CONCURRENT_ENTRIES,
    SourceWheelProofConfig,
    SourceWheelProofError,
    aggregate_failure,
    run_source_wheel_proof,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-input", type=Path, required=True)
    parser.add_argument("--discovery-input-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume-state-sha256")
    parser.add_argument("--max-concurrent-entries", type=int, default=2)
    parser.add_argument("--session-timeout", type=float, default=10_800)
    parser.add_argument("--tunnel-ready-timeout", type=float, default=120)
    parser.add_argument("--sshd-ready-timeout", type=float, default=180)
    parser.add_argument("--max-session-buffer-size", type=int, default=67_108_864)
    parser.add_argument("--tenant-id", default="async_2347641")
    parser.add_argument("--lease-ttl", default="60s")
    parser.add_argument("--vacli-lease-retries", type=int, required=True)
    parser.add_argument("--vacli-max-concurrent-leases", type=int, required=True)
    parser.add_argument("--vacli-max-pull-retries", type=int, required=True)
    parser.add_argument("--vacli-image-pull-timeout-seconds", type=int, required=True)
    parser.add_argument("--vacli-container-privileged", type=int, choices=(0, 1), required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--base-runtime-commit", required=True)
    parser.add_argument("--source-git-tree", required=True)
    parser.add_argument("--source-tree-sha256", required=True)
    parser.add_argument("--verifiers-commit", required=True)
    parser.add_argument("--renderers-commit", required=True)
    parser.add_argument("--pydantic-config-commit", required=True)
    parser.add_argument("--vmvm-tb-v2-sha256", required=True)
    parser.add_argument("--vacli-binary-sha256", required=True)
    parser.add_argument("--invocation-host", required=True)
    parser.add_argument("--slurm-job-id", required=True)
    args = parser.parse_args()
    if not 1 <= args.max_concurrent_entries <= MAX_CONCURRENT_ENTRIES:
        parser.error(f"--max-concurrent-entries must be between 1 and {MAX_CONCURRENT_ENTRIES}")
    return args


async def _run(config: SourceWheelProofConfig) -> dict[str, object]:
    current = asyncio.current_task()
    assert current is not None
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for caught in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(caught, current.cancel)
            installed.append(caught)
        except NotImplementedError:
            pass
    try:
        return await run_source_wheel_proof(config)
    finally:
        for caught in installed:
            loop.remove_signal_handler(caught)


def main() -> int:
    args = _parse_args()
    logging.disable(logging.CRITICAL)
    config = SourceWheelProofConfig(
        input_path=args.discovery_input,
        input_sha256=args.discovery_input_sha256,
        output_dir=args.output_dir,
        base_runtime_commit=args.base_runtime_commit,
        source_commit=args.source_commit,
        source_git_tree=args.source_git_tree,
        source_tree_sha256=args.source_tree_sha256,
        verifiers_commit=args.verifiers_commit,
        renderers_commit=args.renderers_commit,
        pydantic_config_commit=args.pydantic_config_commit,
        vmvm_tb_v2_sha256=args.vmvm_tb_v2_sha256,
        vacli_binary_sha256=args.vacli_binary_sha256,
        invocation_host=args.invocation_host,
        slurm_job_id=args.slurm_job_id,
        resume_state_sha256=args.resume_state_sha256,
        max_concurrent_entries=args.max_concurrent_entries,
        session_timeout=args.session_timeout,
        tunnel_ready_timeout=args.tunnel_ready_timeout,
        sshd_ready_timeout=args.sshd_ready_timeout,
        max_session_buffer_size=args.max_session_buffer_size,
        tenant_id=args.tenant_id,
        lease_ttl=args.lease_ttl,
        vacli_lease_retries=args.vacli_lease_retries,
        vacli_max_concurrent_leases=args.vacli_max_concurrent_leases,
        vacli_max_pull_retries=args.vacli_max_pull_retries,
        vacli_image_pull_timeout_seconds=args.vacli_image_pull_timeout_seconds,
        vacli_container_privileged=args.vacli_container_privileged,
    )
    try:
        result = asyncio.run(_run(config))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(json.dumps(aggregate_failure(args.output_dir, "cancelled"), sort_keys=True), flush=True)
        return 130
    except SourceWheelProofError as error:
        print(json.dumps(aggregate_failure(args.output_dir, error.code), sort_keys=True), flush=True)
        return 1
    except BaseException:
        print(json.dumps(aggregate_failure(args.output_dir, "unexpected_failure"), sort_keys=True), flush=True)
        return 1
    print(
        json.dumps(
            {
                "status": "complete",
                "counts": {
                    "entries": result["entries"],
                    "runtime_starts": result["runtime_starts"],
                    "peak_live_runtimes": result["peak_live_runtimes"],
                    "peak_concurrent_entries": result["peak_concurrent_entries"],
                },
                "hashes": {
                    "discovery_input_sha256": result["input_sha256"],
                    "policy_sha256": result["policy_sha256"],
                    "proof_sha256": result["proof_sha256"],
                    "state_sha256": result["state_sha256"],
                },
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
