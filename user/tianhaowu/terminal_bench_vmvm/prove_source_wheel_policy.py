#!/usr/bin/env python3
"""Discover and prove a private source-wheel policy with independent VMVM builds."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sys
from pathlib import Path
from types import ModuleType

MAX_CONCURRENT_ENTRIES = 3
REQUIRED_DISCOVERY_ENTRIES = 9
RUNTIMES_PER_ENTRY = 3
SHA256_RE = re.compile(r"[0-9a-f]{64}")
DIAGNOSTIC_FAILURE_COUNT_NAMES = (
    "entries_checked",
    "candidate_failures",
    "successful_entries",
    "runtime_starts",
    "peak_live_runtimes",
    "peak_concurrent_entries",
)


def empty_diagnostic_failure(code: str) -> dict[str, object]:
    return {
        "status": "failed",
        "error_code": code,
        "counts": {name: 0 for name in DIAGNOSTIC_FAILURE_COUNT_NAMES},
    }


def _require_bootstrap() -> None:
    attestation = os.environ.get("SOURCE_WHEEL_PROOF_BOOTSTRAP_ATTESTATION_SHA256", "")
    if not (
        SHA256_RE.fullmatch(attestation)
        and sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.no_user_site
        and sys.flags.safe_path
        and sys.dont_write_bytecode
        and "site" not in sys.modules
        and "sitecustomize" not in sys.modules
        and "usercustomize" not in sys.modules
    ):
        summary = {"status": "failed", "error_code": "bootstrap_required"}
        if "--candidate-diagnostics-only" in sys.argv[1:]:
            summary = empty_diagnostic_failure("bootstrap_required")
        print(json.dumps(summary, sort_keys=True))
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-input", type=Path, required=True)
    parser.add_argument("--discovery-input-sha256", required=True)
    parser.add_argument("--expected-entry-count", type=int, required=True)
    parser.add_argument("--expected-missing-evidence-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume-state-sha256")
    parser.add_argument("--candidate-diagnostics-only", action="store_true")
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
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--canonical-launcher-path", type=Path, required=True)
    parser.add_argument("--executed-launcher-path", type=Path, required=True)
    parser.add_argument("--uv-path", type=Path, required=True)
    parser.add_argument("--python-path", type=Path, required=True)
    parser.add_argument("--python-stdlib-path", type=Path, required=True)
    parser.add_argument("--site-packages-path", type=Path, required=True)
    parser.add_argument("--vacli-path", type=Path, required=True)
    parser.add_argument("--launcher-sha256", required=True)
    parser.add_argument("--uv-sha256", required=True)
    parser.add_argument("--python-sha256", required=True)
    parser.add_argument("--python-runtime-manifest-sha256", required=True)
    parser.add_argument("--site-packages-manifest-sha256", required=True)
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


async def _run(config: object, proof_module: ModuleType) -> dict[str, object]:
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
        return await proof_module.run_source_wheel_proof(config)
    finally:
        for caught in installed:
            loop.remove_signal_handler(caught)


def diagnostic_public_summary(
    result: object,
    candidate_error_codes: object | None = None,
) -> dict[str, object]:
    if not isinstance(result, dict) or result.get("diagnostic_only") is not True:
        raise ValueError("invalid diagnostic result")
    if candidate_error_codes is None:
        from terminal_bench_vmvm.source_wheels import SOURCE_WHEEL_CANDIDATE_ERROR_CODES

        candidate_error_codes = SOURCE_WHEEL_CANDIDATE_ERROR_CODES
    if not isinstance(candidate_error_codes, frozenset) or not all(
        isinstance(code, str) for code in candidate_error_codes
    ):
        raise ValueError("invalid diagnostic error-code allowlist")
    count_names = {
        "entries_checked",
        "candidate_failures",
        "successful_entries",
        "runtime_starts",
        "peak_live_runtimes",
        "peak_concurrent_entries",
    }
    counts = {name: result.get(name) for name in count_names}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("invalid diagnostic counts")
    entries_checked = counts["entries_checked"]
    candidate_failures = counts["candidate_failures"]
    successful_entries = counts["successful_entries"]
    runtime_starts = counts["runtime_starts"]
    peak_live_runtimes = counts["peak_live_runtimes"]
    peak_concurrent_entries = counts["peak_concurrent_entries"]
    if (
        entries_checked != REQUIRED_DISCOVERY_ENTRIES
        or candidate_failures + successful_entries != entries_checked
        or runtime_starts != entries_checked * RUNTIMES_PER_ENTRY
        or not 1 <= peak_concurrent_entries <= MAX_CONCURRENT_ENTRIES
        or not 1 <= peak_live_runtimes <= peak_concurrent_entries * RUNTIMES_PER_ENTRY
        or peak_live_runtimes > runtime_starts
    ):
        raise ValueError("infeasible diagnostic counts")
    failure_counts = result.get("failure_counts")
    if (
        not isinstance(failure_counts, dict)
        or any(
            not isinstance(code, str) or code not in candidate_error_codes or type(count) is not int or count < 1
            for code, count in failure_counts.items()
        )
        or sum(failure_counts.values()) != candidate_failures
    ):
        raise ValueError("invalid diagnostic failure counts")
    return {
        "status": "diagnostic_complete",
        "counts": counts,
        "failure_counts": dict(sorted(failure_counts.items())),
    }


def failure_public_summary(args: argparse.Namespace, proof_module: ModuleType, code: str) -> dict[str, object]:
    if args.candidate_diagnostics_only:
        return proof_module.aggregate_diagnostic_failure(args.output_dir, code)
    return proof_module.aggregate_failure(args.output_dir, code)


def print_failure_public_summary(args: argparse.Namespace, proof_module: ModuleType, code: str) -> None:
    if not args.candidate_diagnostics_only:
        print(json.dumps(failure_public_summary(args, proof_module, code), sort_keys=True), flush=True)
        return
    try:
        payload = json.dumps(failure_public_summary(args, proof_module, code), sort_keys=True)
    except BaseException:
        payload = json.dumps(empty_diagnostic_failure("unexpected_failure"), sort_keys=True)
    print(payload, flush=True)


def print_diagnostic_public_summary(result: object, proof_module: ModuleType) -> bool:
    try:
        summary = diagnostic_public_summary(result, proof_module.SOURCE_WHEEL_CANDIDATE_ERROR_CODES)
        payload = json.dumps(summary, sort_keys=True)
    except BaseException:
        payload = json.dumps(empty_diagnostic_failure("unexpected_failure"), sort_keys=True)
        print(payload, flush=True)
        return False
    print(payload, flush=True)
    return True


def main() -> int:
    _require_bootstrap()
    import terminal_bench_vmvm.source_wheel_proof as proof_module

    args = _parse_args()
    logging.disable(logging.CRITICAL)
    config = proof_module.SourceWheelProofConfig(
        input_path=args.discovery_input,
        input_sha256=args.discovery_input_sha256,
        output_dir=args.output_dir,
        expected_entry_count=args.expected_entry_count,
        expected_missing_evidence_sha256=args.expected_missing_evidence_sha256,
        project_dir=args.project_dir,
        canonical_launcher_path=args.canonical_launcher_path,
        executed_launcher_path=args.executed_launcher_path,
        uv_path=args.uv_path,
        python_path=args.python_path,
        python_stdlib_path=args.python_stdlib_path,
        site_packages_path=args.site_packages_path,
        vacli_path=args.vacli_path,
        launcher_sha256=args.launcher_sha256,
        uv_sha256=args.uv_sha256,
        python_sha256=args.python_sha256,
        python_runtime_manifest_sha256=args.python_runtime_manifest_sha256,
        site_packages_manifest_sha256=args.site_packages_manifest_sha256,
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
        candidate_diagnostics_only=args.candidate_diagnostics_only,
    )
    try:
        result = asyncio.run(_run(config, proof_module))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print_failure_public_summary(args, proof_module, "cancelled")
        return 130
    except proof_module.SourceWheelProofError as error:
        print_failure_public_summary(args, proof_module, error.code)
        return 1
    except BaseException:
        print_failure_public_summary(args, proof_module, "unexpected_failure")
        return 1
    if args.candidate_diagnostics_only:
        return 0 if print_diagnostic_public_summary(result, proof_module) else 1
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
                    "missing_evidence_sha256": result["missing_evidence_sha256"],
                    "policy_sha256": result["policy_sha256"],
                    "proof_sha256": result["proof_sha256"],
                    "finalization_sha256": result["finalization_sha256"],
                    "post_validation_sha256": result["post_validation_sha256"],
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
