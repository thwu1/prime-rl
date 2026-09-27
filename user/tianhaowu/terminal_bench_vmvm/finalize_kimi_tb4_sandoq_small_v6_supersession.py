#!/usr/bin/env python3
"""Publish a fixed-denominator supersession for the immutable Kimi TB4 v6 run."""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Sequence

import finalize_kimi_tb4_sandoq_small_full as ordinary
import finalize_kimi_tb4_sandoq_small_v4_recovery as recovery
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as plan_module

SCHEMA_VERSION = 1
KIND = ordinary.KIND
EXECUTION_SOURCE_REVISION = "734fac07d92f75820892dd984b74f76707eb9b63"
EXECUTION_VERIFIERS_COMMIT = "f11bf7cec1ca16ecadf7c88046f6a4a660af2031"
EXECUTION_SLURM_JOB_ID = "1601096"
EXECUTION_PLAN_SHA256 = "f0b9c5df4c99b9d175f990f470a5d8872e846a68fec28c58159aabf0c4c4dab9"
OUTPUT_NAME = "full-denominator-supersession-v1"
TARGET_PASSES = 7
RESULTS = ordinary.RESULTS
CERTIFICATE = ordinary.CERTIFICATE
PRIME_SHARED_EXECUTION_FILES = (
    "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py",
    "user/tianhaowu/terminal_bench_vmvm/audit_traces.py",
    "user/tianhaowu/terminal_bench_vmvm/run_eval_with_zero_model_resume.sh",
    "user/tianhaowu/terminal_bench_vmvm/assess_zero_model_resume.py",
    "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/sandoq_provider_context.py",
    "user/tianhaowu/terminal_bench_vmvm/direct_kimi_router.py",
)
TB4_LANE_EXECUTION_FILES = (
    "user/tianhaowu/terminal_bench_vmvm/eval_run_identity.py",
    "user/tianhaowu/terminal_bench_vmvm/direct_kimi_workers.py",
    "user/tianhaowu/terminal_bench_vmvm/prepare_kimi_tb4_sandoq_small_full.py",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_full.py",
    "user/tianhaowu/terminal_bench_vmvm/run_direct_kimi_sandoq_stage.sh",
    "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/"
    "run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch",
    "user/tianhaowu/terminal_bench_vmvm/run_kimi_tb4_miniswe246_sandoq_stock_single_full.sbatch",
    "user/tianhaowu/terminal_bench_vmvm/run_kimi_tb4_miniswe246_sandoq_small_full.sbatch",
    "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/"
    "tb4_kimi_k3_miniswe246_sandoq_firecracker_small_full.base.toml",
)
SUPERSESSION_SOURCE_FILES = (
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v6_supersession.py",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v4_recovery.py",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_full.py",
    "user/tianhaowu/terminal_bench_vmvm/kimi_tb4_provider_split.py",
    "user/tianhaowu/terminal_bench_vmvm/prepare_kimi_tb4_sandoq_small_full.py",
    "user/tianhaowu/terminal_bench_vmvm/audit_traces.py",
)
SANDOQ_EXTENSION_PREFIX = "extensions/sandoq/sandoq_provider"
VERIFIERS_EXECUTION_FILES = (
    "verifiers/v1/env.py",
    "verifiers/v1/runtimes/sandoq.py",
    "verifiers/v1/harnesses/mini_swe_agent/harness.py",
    "verifiers/v1/harnesses/mini_swe_agent/program.py",
)
PROVIDER_TOKEN_PATH_SHA256 = "19f886485a27dd272af667283ebeb57293a08723782af6c4bc83a05dca6dedc0"
PROXY_SUMMARY_MARKER = b"sandoq: buffered model proxy summary "
PROXY_SUMMARY_PREFIX_RE = re.compile(rb"[0-9]{2}:[0-9]{2}:[0-9]{2} +INFO \Z")
PROXY_SUMMARY_INTEGER_FIELDS = (
    "requests",
    "upstream_attempts",
    "coalesced_requests",
    "replayed_requests",
    "downstream_disconnects",
    "conflicting_requests",
    "inflight",
    "streamed_requests",
    "response_bytes",
    "error_count",
    "unknown_path_requests",
)
PROXY_SUMMARY_MAPPING_FIELDS = ("statuses", "protocols", "path_counts")
PROXY_SUMMARY_EXACT_ONCE_FIELDS = (
    "logical_requests",
    "logical_upstream_attempts",
    "anonymous_upstream_attempts",
    "expired_logical_retries",
)
PROXY_SUMMARY_SCHEMAS = {
    "legacy": frozenset(PROXY_SUMMARY_INTEGER_FIELDS + PROXY_SUMMARY_MAPPING_FIELDS),
    "logical-exact-once-v1": frozenset(
        PROXY_SUMMARY_INTEGER_FIELDS
        + PROXY_SUMMARY_MAPPING_FIELDS
        + PROXY_SUMMARY_EXACT_ONCE_FIELDS
    ),
}


class V6SupersessionError(ValueError):
    """The immutable v6 run cannot be represented by this supersession."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise V6SupersessionError(code)
    raise V6SupersessionError(code) from error


def _verified_plan(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if expected_sha256 != EXECUTION_PLAN_SHA256:
        _fail("execution_plan_invalid")
    body = split.read_regular(path, code="execution_plan_invalid", private=True, held=held)
    if recovery._sha256(body) != expected_sha256:
        _fail("execution_plan_invalid")
    try:
        plan = json.loads(body)
        verified = plan_module.verify(path, expected_sha256, held=held, body=body)
    except Exception as error:
        _fail("execution_plan_invalid", error)
    if not isinstance(plan, dict):
        _fail("execution_plan_invalid")
    return plan, verified, ordinary._artifact_bytes(path, body)


def _git_output(repository: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        _fail("execution_semantics_invalid", error)


def _git_file_hashes(
    repository: Path,
    revision: str,
    paths: Sequence[str],
) -> dict[str, str]:
    if not paths or len(paths) != len(set(paths)):
        _fail("execution_semantics_invalid")
    values: dict[str, str] = {}
    for path in sorted(paths):
        if not path or path.startswith("/") or ".." in Path(path).parts:
            _fail("execution_semantics_invalid")
        values[path] = recovery._sha256(_git_output(repository, "show", f"{revision}:{path}"))
    return values


def _execution_semantics_manifest() -> dict[str, Any]:
    project = Path(__file__).resolve(strict=True).parents[3]
    extension_paths = tuple(
        line.decode()
        for line in _git_output(
            project,
            "ls-tree",
            "-r",
            "--name-only",
            EXECUTION_SOURCE_REVISION,
            "--",
            SANDOQ_EXTENSION_PREFIX,
        ).splitlines()
        if line
    )
    if not extension_paths or any(
        not path.startswith(SANDOQ_EXTENSION_PREFIX + "/") for path in extension_paths
    ):
        _fail("execution_semantics_invalid")
    shared_files = _git_file_hashes(
        project,
        EXECUTION_SOURCE_REVISION,
        PRIME_SHARED_EXECUTION_FILES,
    )
    lane_files = _git_file_hashes(
        project,
        EXECUTION_SOURCE_REVISION,
        TB4_LANE_EXECUTION_FILES,
    )
    extension_files = _git_file_hashes(project, EXECUTION_SOURCE_REVISION, extension_paths)
    verifiers_repository = project / "deps/verifiers"
    verifier_files = _git_file_hashes(
        verifiers_repository,
        EXECUTION_VERIFIERS_COMMIT,
        VERIFIERS_EXECUTION_FILES,
    )
    return {
        "schema_version": 1,
        "hash_kind": "raw-file-sha256",
        "source_revision": EXECUTION_SOURCE_REVISION,
        "prime_rl_shared_files": shared_files,
        "prime_rl_shared_file_set_sha256": recovery._sha256(split.canonical_json(shared_files)),
        "tb4_lane_files": lane_files,
        "tb4_lane_file_set_sha256": recovery._sha256(split.canonical_json(lane_files)),
        "sandoq_extension": {
            "path": SANDOQ_EXTENSION_PREFIX,
            "files": extension_files,
            "file_set_sha256": recovery._sha256(split.canonical_json(extension_files)),
        },
        "verifiers": {
            "commit": EXECUTION_VERIFIERS_COMMIT,
            "files": verifier_files,
            "file_set_sha256": recovery._sha256(split.canonical_json(verifier_files)),
        },
    }


def _supersession_source_binding(expected_revision: str) -> dict[str, Any]:
    binding = recovery._repository_binding(expected_revision)
    project = Path(str(binding["project_root"]))
    try:
        status = subprocess.run(
            ["git", "-C", str(project), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        _fail("supersession_source_invalid", error)
    if status:
        _fail("supersession_source_invalid")
    source_files = _git_file_hashes(project, expected_revision, SUPERSESSION_SOURCE_FILES)
    for path, expected_sha256 in source_files.items():
        candidate = project / path
        try:
            body = candidate.read_bytes()
        except OSError as error:
            _fail("supersession_source_invalid", error)
        if recovery._sha256(body) != expected_sha256:
            _fail("supersession_source_invalid")
    return {
        **binding,
        "hash_kind": "raw-file-sha256",
        "files": source_files,
        "file_set_sha256": recovery._sha256(split.canonical_json(source_files)),
    }


def _provider_context(path: Path, held: split._HeldArtifactSet) -> dict[str, Any]:
    body = split.read_regular(path, code="provider_context_invalid", private=True, held=held)
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("provider_context_invalid", error)
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "provider_environment",
        "effective_task_network",
        "task_network",
        "network_access",
        "allow_dockerhub_fallback",
        "provider_profile_sha256",
        "provider_token_file_path_sha256",
        "runtime_smoke_receipt_sha256",
        "provider_context_contract_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-provider-context-snapshot"
        or value.get("state") != "validated"
        or value.get("provider_environment") != "oci-runner-firecracker-small"
        or value.get("effective_task_network") != "public"
        or value.get("task_network") != "host"
        or value.get("network_access") is not True
        or value.get("allow_dockerhub_fallback") is not False
        or value.get("provider_profile_sha256") != plan_module.PROVIDER_PROFILE_SHA256
        or value.get("provider_token_file_path_sha256") != PROVIDER_TOKEN_PATH_SHA256
        or value.get("runtime_smoke_receipt_sha256") is not None
        or plan_module.SHA256_RE.fullmatch(
            str(value.get("provider_context_contract_sha256", ""))
        )
        is None
    ):
        _fail("provider_context_invalid")
    return {
        "artifact": ordinary._artifact_bytes(path, body),
        "contract_sha256": value["provider_context_contract_sha256"],
    }


def _nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _counter_mapping(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and all(isinstance(key, str) and key for key in value)
        and all(_nonnegative_integer(count) for count in value.values())
    )


def _buffered_proxy_audit(body: bytes, *, expected_schema: str) -> dict[str, Any]:
    expected_keys = PROXY_SUMMARY_SCHEMAS.get(expected_schema)
    if expected_keys is None:
        _fail("buffered_proxy_audit_invalid")
    records: list[dict[str, Any]] = []
    for line in body.splitlines():
        marker_offset = line.find(PROXY_SUMMARY_MARKER)
        if marker_offset < 0:
            continue
        if (
            line.count(PROXY_SUMMARY_MARKER) != 1
            or PROXY_SUMMARY_PREFIX_RE.fullmatch(line[:marker_offset]) is None
        ):
            _fail("buffered_proxy_audit_invalid")
        try:
            value = json.loads(line[marker_offset + len(PROXY_SUMMARY_MARKER) :])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            _fail("buffered_proxy_audit_invalid", error)
        if (
            not isinstance(value, dict)
            or set(value) != expected_keys
            or any(
                not _nonnegative_integer(value.get(field))
                for field in PROXY_SUMMARY_INTEGER_FIELDS
            )
            or any(
                not _counter_mapping(value.get(field))
                for field in PROXY_SUMMARY_MAPPING_FIELDS
            )
            or set(value["path_counts"])
            != {"/muse-code/models", "/v1/chat/completions", "/v1/responses"}
            or not set(value["protocols"]).issubset({"chat_completions", "responses"})
            or any(re.fullmatch(r"[1-5][0-9]{2}", key) is None for key in value["statuses"])
            or value["inflight"] != 0
        ):
            _fail("buffered_proxy_audit_invalid")
        if expected_schema == "logical-exact-once-v1":
            if any(
                not _nonnegative_integer(value.get(field))
                for field in PROXY_SUMMARY_EXACT_ONCE_FIELDS
            ) or (
                value["logical_upstream_attempts"] != value["logical_requests"]
                or value["anonymous_upstream_attempts"] != 0
                or value["conflicting_requests"] != 0
                or value["expired_logical_retries"] != 0
                or value["upstream_attempts"] != value["logical_upstream_attempts"]
            ):
                _fail("buffered_proxy_exact_once_invalid")
        records.append(value)
    if not records:
        _fail("buffered_proxy_audit_invalid")

    integer_fields = list(PROXY_SUMMARY_INTEGER_FIELDS)
    if expected_schema == "logical-exact-once-v1":
        integer_fields.extend(PROXY_SUMMARY_EXACT_ONCE_FIELDS)
    integer_totals = {
        field: sum(record[field] for record in records) for field in integer_fields
    }
    mapping_totals: dict[str, dict[str, int]] = {}
    for field in PROXY_SUMMARY_MAPPING_FIELDS:
        keys = sorted({key for record in records for key in record[field]})
        mapping_totals[field] = {
            key: sum(record[field].get(key, 0) for record in records) for key in keys
        }
    return {
        "schema_version": 1,
        "source_schema": expected_schema,
        "summary_records": len(records),
        "exact_once_counters_required": expected_schema == "logical-exact-once-v1",
        "integer_totals": integer_totals,
        "mapping_totals": mapping_totals,
        "record_set_sha256": recovery._sha256(split.canonical_json(records)),
    }


def _gate_met(trace_audit: Mapping[str, Any]) -> bool:
    passes = trace_audit.get("passes")
    invalid_passes = trace_audit.get("trace_invalid_passing_rows")
    if (
        not _nonnegative_integer(passes)
        or not _nonnegative_integer(invalid_passes)
        or passes > plan_module.SUPPORTED_TASKS
        or invalid_passes > passes
    ):
        _fail("gate_inputs_invalid")
    return passes >= TARGET_PASSES and invalid_passes == 0


def _merge_rows(
    entries: Sequence[Any],
    rows: Mapping[str, dict[str, Any]],
    compose: Sequence[str],
    gpu: Sequence[str],
    manifest_sha256: str,
) -> bytes:
    merged: list[dict[str, Any]] = []
    trace_ids: set[str] = set()
    compose_set = set(compose)
    gpu_set = set(gpu)
    for entry in entries:
        if entry.task_id in rows:
            row = rows[entry.task_id]
        elif entry.task_id in compose_set:
            row = ordinary._unsupported_row(entry.task_id, manifest_sha256, "compose")
        elif entry.task_id in gpu_set:
            row = ordinary._unsupported_row(entry.task_id, manifest_sha256, "gpu")
        else:
            _fail("coverage_invalid")
        trace_id = row.get("id")
        if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
            _fail("trace_identity_invalid")
        trace_ids.add(trace_id)
        merged.append(row)
    if len(merged) != split.TOTAL_TASKS:
        _fail("coverage_invalid")
    return b"".join(split.canonical_json(row) for row in merged)


def finalize(
    *,
    plan_path: Path,
    plan_sha256: str,
    run_dir: Path,
    output: Path,
    supersession_source_revision: str,
) -> dict[str, Any]:
    source_binding = _supersession_source_binding(supersession_source_revision)
    execution_semantics = _execution_semantics_manifest()
    held = split._HeldArtifactSet.create()
    try:
        plan, verified, plan_artifact = _verified_plan(plan_path, plan_sha256, held)
        run_dir = split._absolute_path(run_dir)
        output = split._absolute_path(output)
        if (
            str(run_dir) != verified["output_dir"]
            or output != run_dir / OUTPUT_NAME
            or output.exists()
            or output.is_symlink()
        ):
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
                expected_revision=EXECUTION_SOURCE_REVISION,
                expected_verifiers_commit=EXECUTION_VERIFIERS_COMMIT,
                held=held,
            )
            if slurm_job_id != EXECUTION_SLURM_JOB_ID:
                _fail("run_identity_invalid")

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
            provider_context = _provider_context(
                run_dir / "sandoq-provider-context.json",
                held,
            )
            evaluator_log_body, evaluator_log_artifact = split._read_regular_evidence(
                run_dir / "control/evaluator.private.log",
                code="buffered_proxy_log_invalid",
                maximum_bytes=512 * 1024 * 1024,
                private=True,
                held=held,
            )
            buffered_proxy_audit = _buffered_proxy_audit(
                evaluator_log_body,
                expected_schema="legacy",
            )
            results_output = _merge_rows(
                entries,
                rows,
                compose,
                gpu,
                manifest_record["sha256"],
            )
            passes = int(trace_audit["passes"])
            certificate = {
                "schema_version": SCHEMA_VERSION,
                "kind": KIND,
                "state": "finalized-with-explicit-error-zeroes",
                "certification_eligible": False,
                "official_comparable": False,
                "result_label": "resource-clamped-firecracker-small-diagnostic",
                "source_revision": EXECUTION_SOURCE_REVISION,
                "launch_plan_sha256": plan_sha256,
                "manifest_sha256": manifest_record["sha256"],
                "eval_run_identity_sha256": identity_sha256,
                "invocation_identity_sha256": invocation_sha256,
                "source_run": {
                    "slurm_job_id": EXECUTION_SLURM_JOB_ID,
                    "source_revision": EXECUTION_SOURCE_REVISION,
                    "launch_plan": plan_artifact,
                    "results": results_artifact,
                    "results_mutated": False,
                },
                "supersession": {
                    "source": source_binding,
                    "reason": "fixed-denominator-execution-errors-count-as-zero",
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
                "gate": {
                    "target_passes": TARGET_PASSES,
                    "met": _gate_met(trace_audit),
                },
                "policy": plan["contracts"],
                "execution_semantics": execution_semantics,
                "buffered_proxy_audit": buffered_proxy_audit,
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
                    "evaluator_private_log": evaluator_log_artifact,
                    "router_receipt": router_artifact,
                    "router_receipt_commit": router_marker,
                    **cleanup_artifacts,
                },
                "results_sha256": recovery._sha256(results_output),
            }
            files = {RESULTS: results_output, CERTIFICATE: split.canonical_json(certificate)}
            evidence.revalidate()
            held.revalidate()
            split._publish_private_bundle(output, files)
    finally:
        held.close()
    return {
        "state": "finalized-with-explicit-error-zeroes",
        "denominator": split.TOTAL_TASKS,
        "passes": passes,
        "failures": split.TOTAL_TASKS - passes,
        "execution_error_zeroes": trace_audit["execution_error_zeroes"],
        "gate_met": _gate_met(trace_audit),
        "all_task_pass_rate": passes / split.TOTAL_TASKS,
        "certification_eligible": False,
        "results_sha256": recovery._sha256(results_output),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--supersession-source-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            run_dir=args.run_dir,
            output=args.output,
            supersession_source_revision=args.supersession_source_revision,
        )
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_tb4_sandoq_small_v6_supersession_failed","state":"blocked"}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
