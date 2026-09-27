#!/usr/bin/env python3
"""Finalize one source-matched exact-transport Kimi TB4 small run."""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Sequence

import finalize_kimi_tb4_sandoq_small_full as ordinary
import finalize_kimi_tb4_sandoq_small_v4_recovery as recovery
import finalize_kimi_tb4_sandoq_small_v6_supersession as audit
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as plan_module

SCHEMA_VERSION = 1
KIND = ordinary.KIND
RESULTS = ordinary.RESULTS
CERTIFICATE = ordinary.CERTIFICATE
OUTPUT_NAME = "full-denominator"
TARGET_PASSES = 7
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")


class V7FinalizeError(ValueError):
    """The v7 run cannot be represented by a lossless fixed-denominator result."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise V7FinalizeError(code)
    raise V7FinalizeError(code) from error


def _verified_plan(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    body = split.read_regular(path, code="plan_invalid", private=True, held=held)
    if recovery._sha256(body) != expected_sha256:
        _fail("plan_invalid")
    try:
        value = json.loads(body)
        verified = plan_module.verify(path, expected_sha256, held=held, body=body)
    except Exception as error:
        _fail("plan_invalid", error)
    if not isinstance(value, dict):
        _fail("plan_invalid")
    return value, verified, ordinary._artifact_bytes(path, body)


def _router_transport_binding(
    router_body: bytes,
    proxy_audit: Mapping[str, Any],
    trace_audit: Mapping[str, Any],
) -> dict[str, Any]:
    return audit._exact_router_proxy_binding(router_body, proxy_audit, trace_audit)


def _validate_stock_identity(identity: Mapping[str, Any]) -> None:
    deployment = identity.get("deployment")
    router = deployment.get("router") if isinstance(deployment, Mapping) else None
    if (
        not isinstance(deployment, Mapping)
        or not isinstance(router, Mapping)
        or deployment.get("spec_sha256") != plan_module.STOCK_SOURCE_SPEC_SHA256
        or deployment.get("endpoint_bundle_sha256")
        != plan_module.STOCK_ENDPOINT_BUNDLE_SHA256
        or router.get("capacity_profile") != "sandoq-stock-single-c64-v1"
        or router.get("endpoint_identifier") != plan_module.STOCK_ENDPOINT_IDENTIFIER
        or router.get("worker_count") != 1
        or router.get("provider_concurrency") != 64
        or router.get("per_worker_capacity") != 64
    ):
        _fail("stock_identity_invalid")


def finalize(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    expected_revision: str,
    expected_slurm_job_id: str,
) -> dict[str, Any]:
    if (
        REVISION_RE.fullmatch(expected_revision or "") is None
        or re.fullmatch(r"[1-9][0-9]*", expected_slurm_job_id or "") is None
    ):
        _fail("source_identity_invalid")
    source_binding = audit._supersession_source_binding(expected_revision)
    execution_semantics = audit._execution_semantics_manifest(
        expected_revision,
        plan_module.VERIFIERS_COMMIT,
    )
    held = split._HeldArtifactSet.create()
    try:
        plan, verified, plan_artifact = _verified_plan(plan_path, plan_sha256, held)
        run_dir = split._absolute_path(run_dir)
        output = Path(str(verified["full_output_dir"]))
        if (
            str(run_dir) != verified["output_dir"]
            or output != run_dir / OUTPUT_NAME
            or output.exists()
            or output.is_symlink()
        ):
            _fail("output_or_run_directory_invalid")
        manifest_record = plan["source"]["manifest"]
        manifest_path = Path(str(manifest_record["path"]))
        manifest_body = split.read_regular(
            manifest_path,
            code="manifest_invalid",
            private=True,
            held=held,
        )
        if ordinary._artifact_bytes(manifest_path, manifest_body) != manifest_record:
            _fail("manifest_invalid")
        try:
            _manifest, entries = split.parse_manifest(
                manifest_body,
                str(manifest_record["sha256"]),
            )
            partition = union.derive_union_partition(entries)
        except Exception as error:
            _fail("manifest_invalid", error)
        verifier_modes = {entry.task_id: entry.verifier_mode for entry in entries}

        with ExitStack() as stack:
            evidence = split._open_held_run_evidence(run_dir)
            stack.callback(evidence.close)
            writer_lock = stack.enter_context(
                split._open_private_writer_lock_at(evidence.directory, ".writer.lock")
            )
            router_lock = stack.enter_context(
                split._open_private_writer_lock(
                    split._router_lock_path(evidence.files["eval_run_identity.json"].body)
                )
            )
            for lock in (writer_lock, router_lock):
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    _fail("run_active", error)

            supported = ordinary._selector_members(plan["lane"]["selector"], held)
            compose = ordinary._selector_members(plan["unsupported"]["compose"], held)
            gpu = ordinary._selector_members(plan["unsupported"]["gpu"], held)
            if (
                supported != partition.sandoq_firecracker
                or compose != partition.compose_required
                or gpu != partition.gpu_unsupported
            ):
                _fail("partition_invalid")
            identity, identity_sha256, invocation_sha256, slurm_job_id = (
                ordinary._identity_contract(
                    run_dir=run_dir,
                    evidence=evidence,
                    plan=plan,
                    expected_revision=expected_revision,
                    expected_verifiers_commit=plan_module.VERIFIERS_COMMIT,
                    held=held,
                )
            )
            if slurm_job_id != expected_slurm_job_id:
                _fail("run_identity_invalid")
            _validate_stock_identity(identity)

            results_body, results_artifact = split._read_regular_evidence(
                run_dir / RESULTS,
                code="provider_results_invalid",
                maximum_bytes=512 * 1024 * 1024,
                private=True,
                held=held,
            )
            trace_audit, rows = recovery._audit_supported_rows(
                results_body,
                supported,
                verifier_modes,
                allow_nontrainable_scored_rows=True,
                audit_error_model_io=True,
            )
            try:
                cleanup, cleanup_artifacts = split._validate_sandoq_cleanup(
                    run_dir / "sandoq_cleanup_audit.json",
                    run_dir,
                    identity,
                    identity_sha256,
                    invocation_sha256,
                    slurm_job_id,
                    plan_module.SUPPORTED_TASKS,
                    plan_module.CONCURRENCY,
                    held,
                )
                router_body, router_artifact, router_marker = (
                    split._validate_direct_router_receipt(
                        run_dir / "direct_kimi_router_final.json",
                        identity,
                        minimum_chat_requests=plan_module.SUPPORTED_TASKS,
                        identity_sha256=identity_sha256,
                        invocation_identity_sha256=invocation_sha256,
                        held=held,
                        allow_terminal_upstream_statuses=True,
                    )
                )
            except Exception as error:
                _fail("run_audit_failed", error)
            provider_context = audit._provider_context(
                run_dir / "sandoq-provider-context.json",
                held,
            )
            proxy_audit, proxy_artifacts = audit._buffered_proxy_directory_audit(
                run_dir / "control/buffered-proxy-stats",
                expected_records=plan_module.SUPPORTED_TASKS,
                expected_schema="logical-exact-once-v1",
                held=held,
            )
            buffered_proxy_audit = audit._exact_proxy_trace_binding(
                proxy_audit,
                trace_audit,
                expected_summary_records=plan_module.SUPPORTED_TASKS,
            )
            router_transport_binding = _router_transport_binding(
                router_body,
                buffered_proxy_audit,
                trace_audit,
            )
            results_output = audit._merge_rows(
                entries,
                rows,
                compose,
                gpu,
                str(manifest_record["sha256"]),
            )
            passes = int(trace_audit["passes"])
            gate_met = audit._gate_met(trace_audit)
            certificate = {
                "schema_version": SCHEMA_VERSION,
                "kind": KIND,
                "state": "finalized-with-explicit-error-zeroes",
                "certification_eligible": False,
                "official_comparable": False,
                "result_label": "resource-clamped-firecracker-small-diagnostic",
                "source_revision": expected_revision,
                "launch_plan_sha256": plan_sha256,
                "manifest_sha256": manifest_record["sha256"],
                "eval_run_identity_sha256": identity_sha256,
                "invocation_identity_sha256": invocation_sha256,
                "source_run": {
                    "slurm_job_id": slurm_job_id,
                    "source_revision": expected_revision,
                    "launch_plan": plan_artifact,
                    "results": results_artifact,
                    "results_mutated": False,
                },
                "supersession": {
                    "source": source_binding,
                    "reason": "fixed-denominator-exact-transport-v7",
                    "original_full_output": plan["full_output_dir"],
                    "model_attempts_preserved": True,
                },
                "counts": {
                    "denominator": split.TOTAL_TASKS,
                    "executed": plan_module.SUPPORTED_TASKS,
                    "compose_unsupported": plan_module.COMPOSE_UNSUPPORTED_TASKS,
                    "gpu_unsupported": plan_module.GPU_UNSUPPORTED_TASKS,
                    "passes": passes,
                    "failures": split.TOTAL_TASKS - passes,
                    "execution_error_zeroes": trace_audit["execution_error_zeroes"],
                },
                "scores": {
                    "executed_pass_rate": passes / plan_module.SUPPORTED_TASKS,
                    "all_task_pass_rate": passes / split.TOTAL_TASKS,
                },
                "gate": {"target_passes": TARGET_PASSES, "met": gate_met},
                "policy": plan["contracts"],
                "execution_semantics": execution_semantics,
                "buffered_proxy_audit": buffered_proxy_audit,
                "router_transport_binding": router_transport_binding,
                "trace_audit": trace_audit,
                "training_eligibility": {
                    "eligible_clean_scored_rows": trace_audit["clean_scored_rows"],
                    "excluded_error_rows": trace_audit["execution_error_zeroes"],
                    "excluded_trace_invalid_scored_rows": trace_audit[
                        "trace_invalid_scored_rows"
                    ],
                    "excluded_unsupported_rows": (
                        plan_module.COMPOSE_UNSUPPORTED_TASKS
                        + plan_module.GPU_UNSUPPORTED_TASKS
                    ),
                    "error_rows_are_trainable": False,
                    "trace_invalid_scored_rows_are_trainable": False,
                },
                "zero_model_recovery": {
                    "state": "not_attempted",
                    "eligible_rows": trace_audit["zero_model_error_zeroes"],
                    "recovered_rows": 0,
                    "source_row_set_sha256": trace_audit["zero_model_row_set_sha256"],
                    "model_attempts_preserved": True,
                    "requires_new_versioned_supersession_for_recovered_rows": True,
                },
                "cleanup": cleanup,
                "provider_context": provider_context,
                "router_receipt_sha256": recovery._sha256(router_body),
                "artifacts": {
                    "executed_results": results_artifact,
                    "buffered_proxy_summary_records": proxy_artifacts,
                    "router_receipt": router_artifact,
                    "router_receipt_commit": router_marker,
                    **cleanup_artifacts,
                },
                "results_sha256": recovery._sha256(results_output),
            }
            files = {
                RESULTS: results_output,
                CERTIFICATE: split.canonical_json(certificate),
            }
            evidence.revalidate()
            held.revalidate()
            split._publish_private_bundle(output, files)
            evidence.revalidate()
            held.revalidate()
    finally:
        held.close()
    return {
        "state": "finalized-with-explicit-error-zeroes",
        "denominator": split.TOTAL_TASKS,
        "passes": passes,
        "failures": split.TOTAL_TASKS - passes,
        "execution_error_zeroes": trace_audit["execution_error_zeroes"],
        "gate_met": gate_met,
        "all_task_pass_rate": passes / split.TOTAL_TASKS,
        "certification_eligible": False,
        "results_sha256": recovery._sha256(results_output),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-slurm-job-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            run_dir=args.run_dir,
            expected_revision=args.expected_revision,
            expected_slurm_job_id=args.expected_slurm_job_id,
        )
    except (OSError, RuntimeError, ValueError):
        print(
            '{"code":"kimi_tb4_sandoq_small_v7_finalize_failed","state":"blocked"}',
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
