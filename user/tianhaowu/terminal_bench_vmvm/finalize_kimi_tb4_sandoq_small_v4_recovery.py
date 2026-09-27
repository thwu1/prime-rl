#!/usr/bin/env python3
"""Truthfully supersede the immutable v4 TB4 result after its capture-contract correction."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Sequence

import audit_traces
import finalize_kimi_tb4_sandoq_small_full as ordinary
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as plan_module

SCHEMA_VERSION = 1
KIND = "kimi-tb4-sandoq-small-v4-contract-recovery"
ORIGINAL_PLAN_SHA256 = "2ad797917023cca027b41d4a6d138abaefd52b38597793d11dc51981aed81ce0"
ORIGINAL_SOURCE_REVISION = "daaa4427b4a4b23359c6c4176953dff9188b07c7"
ORIGINAL_VERIFIERS_COMMIT = "d5e8b77ce20ce79b0b9ae0e5b416fffb74969b08"
ORIGINAL_SLURM_JOB_ID = "1597890"
ORIGINAL_RESPONSE_KIND = "normalized_stream_response"
CORRECTED_RESPONSE_KIND = "exact_provider_json"
ORIGINAL_BASE_CONFIG_SHA256 = "aa5737800031e79d560127cc025f5b379396767f46e81eaa0eb4f1dde02a7b08"
RESULTS = "results.jsonl"
CERTIFICATE = "certificate.json"
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
ALLOWED_ERROR_TYPES = frozenset(
    {
        "HarnessError",
        "InterceptionError",
        "ProviderError",
        "SandboxError",
        "TasksetError",
        "ToolsetError",
        "TunnelError",
        "UserError",
    }
)


class V4RecoveryError(ValueError):
    """The immutable source run cannot be represented by the recovery contract."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise V4RecoveryError(code)
    raise V4RecoveryError(code) from error


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _legacy_contracts() -> dict[str, Any]:
    contracts = copy.deepcopy(plan_module._contracts())
    contracts["model_io_response_kind"] = ORIGINAL_RESPONSE_KIND
    contracts["verifiers_commit"] = ORIGINAL_VERIFIERS_COMMIT
    contracts.pop("verifier_runtime_retries", None)
    contracts.pop("sandoq_provisioning_retries", None)
    return contracts


def _repository_binding(expected_revision: str) -> dict[str, str]:
    if REVISION_RE.fullmatch(expected_revision or "") is None:
        _fail("recovery_source_revision_invalid")
    project = Path(__file__).resolve(strict=True).parents[3]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        _fail("recovery_source_revision_invalid", error)
    if head != expected_revision or status:
        _fail("recovery_source_revision_invalid")
    return {"project_root": str(project), "revision": head}


def _verified_legacy_plan(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if expected_sha256 != ORIGINAL_PLAN_SHA256:
        _fail("original_plan_invalid")
    body = split.read_regular(path, code="original_plan_invalid", private=True, held=held)
    if _sha256(body) != expected_sha256:
        _fail("original_plan_invalid")
    try:
        plan = json.loads(body)
        source = plan.get("source") if isinstance(plan, dict) else None
        base_record = source.get("base_config") if isinstance(source, dict) else None
        profile_record = source.get("provider_profile") if isinstance(source, dict) else None
        if not isinstance(base_record, dict) or not isinstance(profile_record, dict):
            _fail("original_plan_invalid")

        def legacy_base(loader_held: split._HeldArtifactSet | None):
            base_path = Path(str(base_record.get("path"))).resolve(strict=True)
            base_body = plan_module._read(
                base_path,
                code="base_config_invalid",
                held=loader_held,
            )
            if _sha256(base_body) != ORIGINAL_BASE_CONFIG_SHA256:
                _fail("original_plan_invalid")
            try:
                base = tomllib.loads(base_body.decode())
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
                _fail("original_plan_invalid", error)
            return base, base_body, base_path

        def legacy_profile(loader_held: split._HeldArtifactSet | None):
            profile_path = Path(str(profile_record.get("path"))).resolve(strict=True)
            profile_body = plan_module._read(
                profile_path,
                code="provider_profile_invalid",
                held=loader_held,
            )
            if _sha256(profile_body) != plan_module.PROVIDER_PROFILE_SHA256:
                _fail("original_plan_invalid")
            return profile_body, profile_path

        verified = plan_module._verify_with_contracts(
            path,
            expected_sha256,
            expected_contracts=_legacy_contracts(),
            base_loader=legacy_base,
            provider_profile_loader=legacy_profile,
            require_smoke_format_attestation=False,
            held=held,
            body=body,
        )
    except Exception as error:
        _fail("original_plan_invalid", error)
    if not isinstance(plan, dict):
        _fail("original_plan_invalid")
    return plan, verified, {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _valid_error_objects(errors: object) -> tuple[str, ...]:
    if not isinstance(errors, list) or not errors:
        _fail("error_row_invalid")
    types: list[str] = []
    for error in errors:
        if (
            not isinstance(error, dict)
            or set(error) != {"message", "traceback", "type"}
            or error.get("type") not in ALLOWED_ERROR_TYPES
            or not isinstance(error.get("message"), str)
            or not error["message"]
            or not isinstance(error.get("traceback"), str)
        ):
            _fail("error_row_invalid")
        types.append(error["type"])
    return tuple(types)


def _model_turns(row: Mapping[str, Any]) -> int:
    nodes = row.get("nodes")
    if not isinstance(nodes, list):
        _fail("provider_trace_audit_failed")
    return sum(
        node.get("sampled") is True
        for node in nodes
        if isinstance(node, dict)
    )


def _derived_error_zero(row: Mapping[str, Any], *, zero_model: bool) -> dict[str, Any]:
    derived = copy.deepcopy(dict(row))
    source_sha256 = _sha256(split.canonical_json(row))
    info = derived.get("info")
    if not isinstance(info, dict):
        _fail("error_row_invalid")
    derived["rewards"] = {"solved": 0}
    derived["info"] = {
        **info,
        "diagnostic_evaluation_disposition": {
            "kind": "execution-error-counted-as-zero",
            "source_row_sha256": source_sha256,
            "trainable": False,
            "zero_model": zero_model,
        },
    }
    return derived


def _audit_supported_rows(
    body: bytes,
    expected_members: Sequence[str],
    verifier_modes: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        rows = [json.loads(line) for line in body.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("provider_results_invalid", error)
    expected = set(expected_members)
    if len(rows) != len(expected_members) or any(not isinstance(row, dict) for row in rows):
        _fail("provider_results_invalid")

    by_task: dict[str, dict[str, Any]] = {}
    trace_ids: set[str] = set()
    passes = 0
    clean_rows = 0
    clean_model_turns = 0
    clean_sampled_tokens = 0
    zero_model_errors = 0
    model_bearing_errors = 0
    error_types: Counter[str] = Counter()
    zero_model_row_hashes: list[str] = []
    error_row_hashes: list[str] = []
    observations: Counter[str] = Counter()

    for row in rows:
        try:
            task_id = split._task_slug(row)
        except Exception as error:
            _fail("provider_trace_audit_failed", error)
        trace_id = row.get("id")
        if (
            task_id not in expected
            or task_id in by_task
            or not isinstance(trace_id, str)
            or not trace_id
            or trace_id in trace_ids
            or row.get("is_completed") is not True
            or not isinstance(row.get("stop_condition"), str)
            or not row["stop_condition"].strip()
        ):
            _fail("provider_trace_audit_failed")
        trace_ids.add(trace_id)

        errors = row.get("errors")
        if errors:
            for error_type in _valid_error_objects(errors):
                error_types[error_type] += 1
            if row.get("rewards") != {} or row.get("metrics") != {}:
                _fail("error_row_invalid")
            turns = _model_turns(row)
            zero_model = turns == 0
            if zero_model:
                if row.get("nodes") != [] or row.get("info") != {}:
                    _fail("zero_model_error_row_invalid")
                zero_model_errors += 1
                zero_model_row_hashes.append(_sha256(split.canonical_json(row)))
            else:
                model_bearing_errors += 1
            error_row_hashes.append(_sha256(split.canonical_json(row)))
            by_task[task_id] = _derived_error_zero(row, zero_model=zero_model)
            continue

        if errors != []:
            _fail("provider_trace_audit_failed")
        info = row.get("info")
        verifier = info.get("terminal_bench_verifier") if isinstance(info, dict) else None
        if not isinstance(verifier, dict) or verifier.get("mode") != verifier_modes[task_id]:
            _fail("provider_trace_audit_failed")
        problems = audit_traces._audit_trace(
            row,
            require_reasoning=True,
            max_sequence_tokens=split.MAX_SEQUENCE_TOKENS,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            model_io_contract=audit_traces.KIMI_K3_MAX_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            observations=observations,
            require_exact_provider_json=True,
            require_clean_stop=True,
        )
        if problems:
            _fail("provider_trace_audit_failed")
        score = split._score(row)
        passes += score
        clean_rows += 1
        nodes = row["nodes"]
        clean_model_turns += sum(
            node.get("sampled") is True and node.get("model_io") is not None
            for node in nodes
            if isinstance(node, dict)
        )
        for node in nodes:
            if not isinstance(node, dict) or node.get("sampled") is not True:
                continue
            response = node.get("model_io", {}).get("response")
            if not isinstance(response, dict) or response.get("kind") != CORRECTED_RESPONSE_KIND:
                _fail("provider_trace_audit_failed")
            usage = node.get("usage")
            completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
            if isinstance(completion, bool) or not isinstance(completion, int) or completion < 0:
                _fail("provider_trace_audit_failed")
            clean_sampled_tokens += completion
        by_task[task_id] = row

    if set(by_task) != expected or clean_rows + zero_model_errors + model_bearing_errors != len(rows):
        _fail("provider_results_invalid")
    summary = {
        "source_rows": len(rows),
        "clean_scored_rows": clean_rows,
        "passes": passes,
        "scored_failures": clean_rows - passes,
        "execution_error_zeroes": zero_model_errors + model_bearing_errors,
        "zero_model_error_zeroes": zero_model_errors,
        "model_bearing_error_zeroes": model_bearing_errors,
        "clean_model_io_turns": clean_model_turns,
        "clean_sampled_tokens": clean_sampled_tokens,
        "clean_trace_failures": 0,
        "exact_provider_json_required": True,
        "request_graph_match_required": True,
        "reasoning_required": True,
        "provider_explicit_empty_reasoning_tool_turns": observations[
            "provider_explicit_empty_reasoning_tool_turns"
        ],
        "provider_reported_zero_reasoning_tool_turns": observations[
            "provider_reported_zero_reasoning_tool_turns"
        ],
        "error_type_counts": dict(sorted(error_types.items())),
        "error_row_set_sha256": _sha256(split.canonical_json(sorted(error_row_hashes))),
        "zero_model_row_set_sha256": _sha256(split.canonical_json(sorted(zero_model_row_hashes))),
    }
    return summary, by_task


def finalize(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    output: Path,
    recovery_source_revision: str,
) -> dict[str, Any]:
    source_binding = _repository_binding(recovery_source_revision)
    held = split._HeldArtifactSet.create()
    try:
        plan, verified, plan_artifact = _verified_legacy_plan(plan_path, plan_sha256, held)
        run_dir = split._absolute_path(run_dir)
        output = split._absolute_path(output)
        if str(run_dir) != verified["output_dir"] or output.exists() or output.is_symlink():
            _fail("output_or_run_directory_invalid")
        manifest_record = plan["source"]["manifest"]
        manifest_path = Path(manifest_record["path"])
        manifest_body = split.read_regular(
            manifest_path,
            code="manifest_invalid",
            private=True,
            held=held,
        )
        if ordinary._artifact_bytes(manifest_path, manifest_body) != manifest_record:
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
            identity, identity_sha256, invocation_sha256, slurm_job_id = ordinary._identity_contract(
                run_dir=run_dir,
                evidence=evidence,
                plan=plan,
                expected_revision=ORIGINAL_SOURCE_REVISION,
                expected_verifiers_commit=ORIGINAL_VERIFIERS_COMMIT,
                held=held,
            )
            if slurm_job_id != ORIGINAL_SLURM_JOB_ID:
                _fail("run_identity_invalid")

            results_body, results_artifact = split._read_regular_evidence(
                run_dir / RESULTS,
                code="provider_results_invalid",
                maximum_bytes=512 * 1024 * 1024,
                private=True,
                held=held,
            )
            trace_audit, rows = _audit_supported_rows(results_body, supported, verifier_modes)
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
            provider_context = ordinary._provider_context(run_dir / "sandoq-provider-context.json", held)

            merged: list[dict[str, Any]] = []
            trace_ids: set[str] = set()
            compose_set = set(compose)
            gpu_set = set(gpu)
            for entry in entries:
                if entry.task_id in rows:
                    row = rows[entry.task_id]
                elif entry.task_id in compose_set:
                    row = ordinary._unsupported_row(entry.task_id, manifest_record["sha256"], "compose")
                elif entry.task_id in gpu_set:
                    row = ordinary._unsupported_row(entry.task_id, manifest_record["sha256"], "gpu")
                else:
                    _fail("coverage_invalid")
                trace_id = row.get("id")
                if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
                    _fail("trace_identity_invalid")
                trace_ids.add(trace_id)
                merged.append(row)
            if len(merged) != split.TOTAL_TASKS:
                _fail("coverage_invalid")

            results_output = b"".join(split.canonical_json(row) for row in merged)
            passes = int(trace_audit["passes"])
            certificate = {
                "schema_version": SCHEMA_VERSION,
                "kind": KIND,
                "state": "finalized-with-explicit-error-zeroes",
                "certification_eligible": False,
                "official_comparable": False,
                "result_label": "resource-clamped-firecracker-small-diagnostic",
                "source_run": {
                    "slurm_job_id": ORIGINAL_SLURM_JOB_ID,
                    "source_revision": ORIGINAL_SOURCE_REVISION,
                    "launch_plan": plan_artifact,
                    "results": results_artifact,
                    "eval_run_identity_sha256": identity_sha256,
                    "invocation_identity_sha256": invocation_sha256,
                },
                "contract_supersession": {
                    "recovery_source": source_binding,
                    "original_declared_response_kind": ORIGINAL_RESPONSE_KIND,
                    "observed_and_required_response_kind": CORRECTED_RESPONSE_KIND,
                    "reason": "buffered-sandoq-nonstream-provider-boundary",
                    "source_results_mutated": False,
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
                "trace_audit": trace_audit,
                "training_eligibility": {
                    "eligible_clean_scored_rows": trace_audit["clean_scored_rows"],
                    "excluded_error_rows": trace_audit["execution_error_zeroes"],
                    "error_rows_are_trainable": False,
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
                "router_receipt_sha256": _sha256(router_body),
                "artifacts": {
                    "router_receipt": router_artifact,
                    "router_receipt_commit": router_marker,
                    **cleanup_artifacts,
                },
                "results_sha256": _sha256(results_output),
            }
            files = {RESULTS: results_output, CERTIFICATE: split.canonical_json(certificate)}
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
        "all_task_pass_rate": passes / split.TOTAL_TASKS,
        "certification_eligible": False,
        "results_sha256": _sha256(results_output),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recovery-source-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            run_dir=args.run_dir,
            output=args.output,
            recovery_source_revision=args.recovery_source_revision,
        )
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_tb4_sandoq_small_v4_recovery_failed","state":"blocked"}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
