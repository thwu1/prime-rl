#!/usr/bin/env python3
"""Audit the 52-row small-Firecracker run and publish a private 66-row result."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Sequence

import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as plan_module
from direct_kimi_router import C64_W2_CAPACITY_PROFILE, STOCK_SINGLE_C64_CAPACITY_PROFILE
from eval_run_identity import load_eval_run_identity_bytes

SCHEMA_VERSION = 1
KIND = "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic"
RESULTS = "results.jsonl"
CERTIFICATE = "certificate.json"
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")


class SmallDiagnosticFinalizeError(ValueError):
    """The diagnostic run or its immutable evidence failed closed."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise SmallDiagnosticFinalizeError(code)
    raise SmallDiagnosticFinalizeError(code) from error


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _artifact(path: Path, *, private: bool, held: split._HeldArtifactSet) -> dict[str, Any]:
    try:
        return split._artifact(path, private=private, held=held)
    except Exception as error:
        _fail("artifact_invalid", error)


def _selector_members(record: Mapping[str, Any], held: split._HeldArtifactSet) -> tuple[str, ...]:
    try:
        path = Path(str(record["path"]))
        body = split.read_regular(path, code="selector_invalid", private=True, held=held)
    except Exception as error:
        _fail("selector_invalid", error)
    if record != {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}:
        _fail("selector_invalid")
    try:
        members = tuple(body.decode().splitlines())
    except UnicodeDecodeError as error:
        _fail("selector_invalid", error)
    if len(members) != len(set(members)) or body != union._selector_payload(members):
        _fail("selector_invalid")
    return members


def _unsupported_row(task_id: str, manifest_sha256: str, reason: str) -> dict[str, Any]:
    message = f"provider unsupported: {reason}"
    return {
        "id": f"unsupported-{_sha256((manifest_sha256 + chr(0) + reason + chr(0) + task_id).encode())}",
        "task": {"name": f"terminal-bench/{task_id}"},
        "is_completed": True,
        "stop_condition": "unsupported",
        "nodes": [],
        "rewards": {"solved": 0},
        "metrics": {},
        "info": {"provider_outcome": reason},
        "errors": [{"type": "UnsupportedTaskError", "message": message, "traceback": message}],
    }


def _provider_context(path: Path, held: split._HeldArtifactSet) -> dict[str, Any]:
    body = split.read_regular(path, code="provider_context_invalid", private=True, held=held)
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("provider_context_invalid", error)
    if (
        not isinstance(value, dict)
        or value.get("kind") != "sandoq-provider-context-snapshot"
        or value.get("state") != "validated"
        or value.get("provider_environment") != "oci-runner-firecracker-small"
        or value.get("effective_task_network") != "public"
        or value.get("task_network") != "host"
        or value.get("network_access") is not True
        or value.get("allow_dockerhub_fallback") is not False
        or value.get("provider_profile_sha256") != plan_module.PROVIDER_PROFILE_SHA256
    ):
        _fail("provider_context_invalid")
    return {"artifact": _artifact(path, private=True, held=held), "contract_sha256": value.get("provider_context_contract_sha256")}


def _identity_contract(
    *,
    run_dir: Path,
    evidence: split._HeldRunEvidence,
    plan: Mapping[str, Any],
    expected_revision: str,
    expected_verifiers_commit: str = plan_module.VERIFIERS_COMMIT,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], str, str, str]:
    try:
        envelope = load_eval_run_identity_bytes(
            evidence.files["eval_run_identity.json"].body,
            run_dir=run_dir,
            verify_references=True,
            verify_saved_provenance=False,
        )
        identity = envelope["identity"]
        identity_sha256 = envelope["eval_run_identity_sha256"]
        invocation_sha256, slurm_job_id = split._run_invocation_binding(
            evidence.files["eval_invocations.jsonl"].body,
            evidence.files["provenance.txt"].body,
            identity_sha256,
            expected_role="kimi-direct-tb4-small-diagnostic",
        )
    except Exception as error:
        _fail("run_identity_invalid", error)
    source = identity.get("source")
    config = identity.get("config")
    inputs = identity.get("inputs")
    execution = identity.get("execution")
    runtime = execution.get("runtime") if isinstance(execution, dict) else None
    environment = execution.get("sandoq_environment") if isinstance(execution, dict) else None
    deployment = identity.get("deployment")
    router = deployment.get("router") if isinstance(deployment, dict) else None
    stock_single = (
        isinstance(router, dict) and router.get("capacity_profile") == STOCK_SINGLE_C64_CAPACITY_PROFILE
    )
    contract = identity.get("contract")
    harness = contract.get("harness") if isinstance(contract, dict) else None
    lane = plan["lane"]
    if (
        identity.get("role") != "kimi-direct-tb4-small-diagnostic"
        or not isinstance(source, dict)
        or source.get("sandbox_provider") != "sandoq"
        or source.get("prime_rl_commit") != expected_revision
        or source.get("verifiers_commit") != expected_verifiers_commit
        or not isinstance(config, dict)
        or config.get("source", {}).get("sha256") != lane["config"]["sha256"]
        or not isinstance(inputs, dict)
        or inputs.get("task_file", {}).get("sha256") != lane["selector"]["sha256"]
        or inputs.get("task_file", {}).get("count") != plan_module.SUPPORTED_TASKS
        or not isinstance(execution, dict)
        or any(
            execution.get(key) != plan_module.CONCURRENCY
            for key in ("rollout_concurrency", "multiplex", "http_max_connections", "http_max_keepalive_connections")
        )
        or execution.get("cleanup_must_succeed") is not True
        or not isinstance(runtime, dict)
        or runtime.get("type") != "sandoq"
        or runtime.get("expected_environment") != "oci-runner-firecracker-small"
        or runtime.get("session_timeout") != union.SESSION_TIMEOUT_SECONDS
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "sandoq"
        or runtime.get("buffered_chat_completions") is not True
        or not isinstance(environment, dict)
        or environment.get("environment") != "oci-runner-firecracker-small"
        or environment.get("provider_profile_sha256") != plan_module.PROVIDER_PROFILE_SHA256
        or environment.get("task_network") != "public"
        or environment.get("provider_task_network") != "host"
        or environment.get("pool_size") != plan_module.CONCURRENCY
        or not isinstance(deployment, dict)
        or not isinstance(router, dict)
        or router.get("capacity_profile")
        not in {C64_W2_CAPACITY_PROFILE, STOCK_SINGLE_C64_CAPACITY_PROFILE}
        or router.get("endpoint_identifier")
        != ("tianhaowu-kimi-k3-stock-eval-20260927" if stock_single else "cpu-132-021_8103")
        or router.get("policy") != "consistent_hash"
        or router.get("provider_concurrency") != 64
        or router.get("per_worker_capacity") != (64 if stock_single else 2)
        or router.get("worker_count") != (1 if stock_single else 24)
        or router.get("retries") != 0
        or not isinstance(contract, dict)
        or contract.get("model") != "Kimi-K3"
        or harness
        != {
            "id": "mini-swe-agent",
            "version": union.MINISWE_VERSION,
            "placement": "sandbox",
            "step_limit": 200,
            "request_timeout_seconds": union.REQUEST_TIMEOUT_SECONDS,
            "request_max_retries": 0,
        }
    ):
        _fail("run_identity_invalid")
    return identity, identity_sha256, invocation_sha256, slurm_job_id


def _verified_plan(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], dict[str, Any]]:
    body = split.read_regular(path, code="plan_invalid", private=True, held=held)
    if _sha256(body) != expected_sha256:
        _fail("plan_invalid")
    try:
        plan = json.loads(body)
        verified = plan_module.verify(path, expected_sha256, held=held, body=body)
    except Exception as error:
        _fail("plan_invalid", error)
    if not isinstance(plan, dict):
        _fail("plan_invalid")
    return plan, verified


def _finalize_with_held(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    expected_revision: str,
    held: split._HeldArtifactSet,
) -> dict[str, Any]:
    if REVISION_RE.fullmatch(expected_revision or "") is None:
        _fail("source_revision_invalid")
    plan, verified = _verified_plan(plan_path, plan_sha256, held)
    run_dir = split._absolute_path(run_dir)
    if str(run_dir) != verified["output_dir"]:
        _fail("run_directory_invalid")
    output = Path(verified["full_output_dir"])
    if output.exists() or output.is_symlink():
        _fail("output_not_fresh")
    manifest_record = plan["source"]["manifest"]
    manifest_path = Path(manifest_record["path"])
    manifest_body = split.read_regular(
        manifest_path,
        code="manifest_invalid",
        private=True,
        held=held,
    )
    if _artifact_bytes(manifest_path, manifest_body) != manifest_record:
        _fail("manifest_invalid")
    try:
        _manifest, entries = split.parse_manifest(manifest_body, manifest_record["sha256"])
        partition = union.derive_union_partition(entries)
    except Exception as error:
        _fail("manifest_invalid", error)
    verifier_modes = {entry.task_id: entry.verifier_mode for entry in entries}
    with ExitStack() as stack:
        evidence = split._open_held_run_evidence(run_dir)
        stack.callback(evidence.close)
        writer_lock = stack.enter_context(split._open_private_writer_lock_at(evidence.directory, ".writer.lock"))
        router_lock = stack.enter_context(split._open_private_writer_lock(split._router_lock_path(evidence.files["eval_run_identity.json"].body)))
        for lock in (writer_lock, router_lock):
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                _fail("run_active", error)
        supported = _selector_members(plan["lane"]["selector"], held)
        compose = _selector_members(plan["unsupported"]["compose"], held)
        gpu = _selector_members(plan["unsupported"]["gpu"], held)
        if (
            supported != partition.sandoq_firecracker
            or compose != partition.compose_required
            or gpu != partition.gpu_unsupported
        ):
            _fail("partition_invalid")
        identity, identity_sha256, invocation_sha256, slurm_job_id = _identity_contract(
            run_dir=run_dir,
            evidence=evidence,
            plan=plan,
            expected_revision=expected_revision,
            held=held,
        )
        try:
            trace_audit, rows, results_artifact = split._audit_cpu_results(
                run_dir / "results.jsonl",
                supported,
                verifier_modes,
                held,
                require_exact_provider_json=True,
                required_response_kind="exact_provider_json",
            )
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
            router_body, router_artifact, router_marker = split._validate_direct_router_receipt(
                run_dir / "direct_kimi_router_final.json",
                identity,
                minimum_chat_requests=plan_module.SUPPORTED_TASKS,
                identity_sha256=identity_sha256,
                invocation_identity_sha256=invocation_sha256,
                held=held,
            )
        except Exception as error:
            _fail("run_audit_failed", error)
        merged: list[dict[str, Any]] = []
        trace_ids: set[str] = set()
        compose_set = set(compose)
        gpu_set = set(gpu)
        passes = 0
        for entry in entries:
            if entry.task_id in rows:
                row = rows[entry.task_id]
                passes += split._score(row)
            elif entry.task_id in compose_set:
                row = _unsupported_row(entry.task_id, manifest_record["sha256"], "compose")
            elif entry.task_id in gpu_set:
                row = _unsupported_row(entry.task_id, manifest_record["sha256"], "gpu")
            else:
                _fail("coverage_invalid")
            trace_id = row.get("id")
            if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
                _fail("trace_identity_invalid")
            trace_ids.add(trace_id)
            merged.append(row)
        if len(merged) != split.TOTAL_TASKS:
            _fail("coverage_invalid")
        results_body = b"".join(split.canonical_json(row) for row in merged)
        provider_context = _provider_context(run_dir / "sandoq-provider-context.json", held)
        certificate = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "state": "passed",
            "certification_eligible": False,
            "official_comparable": False,
            "result_label": "resource-clamped-firecracker-small-diagnostic",
            "source_revision": expected_revision,
            "launch_plan_sha256": plan_sha256,
            "manifest_sha256": manifest_record["sha256"],
            "eval_run_identity_sha256": identity_sha256,
            "invocation_identity_sha256": invocation_sha256,
            "counts": {
                "denominator": split.TOTAL_TASKS,
                "executed": plan_module.SUPPORTED_TASKS,
                "compose_unsupported": plan_module.COMPOSE_UNSUPPORTED_TASKS,
                "gpu_unsupported": plan_module.GPU_UNSUPPORTED_TASKS,
                "passes": passes,
                "failures": split.TOTAL_TASKS - passes,
            },
            "scores": {
                "executed_pass_rate": passes / plan_module.SUPPORTED_TASKS,
                "all_task_pass_rate": passes / split.TOTAL_TASKS,
            },
            "policy": plan["contracts"],
            "trace_audit": trace_audit,
            "cleanup": cleanup,
            "router_receipt_sha256": _sha256(router_body),
            "provider_context": provider_context,
            "artifacts": {
                "executed_results": results_artifact,
                "router_receipt": router_artifact,
                "router_receipt_commit": router_marker,
                **cleanup_artifacts,
            },
            "results_sha256": _sha256(results_body),
        }
        files = {RESULTS: results_body, CERTIFICATE: split.canonical_json(certificate)}
        try:
            evidence.revalidate()
            held.revalidate()
            split._publish_private_bundle(output, files)
        except Exception as error:
            _fail("publication_failed", error)
        evidence.revalidate()
        held.revalidate()
    return {
        "state": "passed",
        "denominator": split.TOTAL_TASKS,
        "executed": plan_module.SUPPORTED_TASKS,
        "unsupported": plan_module.COMPOSE_UNSUPPORTED_TASKS + plan_module.GPU_UNSUPPORTED_TASKS,
        "passes": passes,
        "all_task_pass_rate": passes / split.TOTAL_TASKS,
        "certification_eligible": False,
        "results_sha256": _sha256(results_body),
    }


def finalize(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    expected_revision: str,
) -> dict[str, Any]:
    held = split._HeldArtifactSet.create()
    try:
        return _finalize_with_held(
            plan_path=plan_path,
            plan_sha256=plan_sha256,
            run_dir=run_dir,
            expected_revision=expected_revision,
            held=held,
        )
    finally:
        held.close()


def _artifact_bytes(path: Path, body: bytes) -> dict[str, Any]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            run_dir=args.run_dir,
            expected_revision=args.expected_revision,
        )
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_tb4_sandoq_small_full_finalize_failed","state":"blocked"}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
