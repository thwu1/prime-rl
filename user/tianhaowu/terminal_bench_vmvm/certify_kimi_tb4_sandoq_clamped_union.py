#!/usr/bin/env python3
"""Certify the 25 native + 27 resource-clamped Kimi TB4 Sandoq union."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import sys
import tomllib
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Sequence

import certify_kimi_tb4_miniswe246_union as native_cert
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as native_plan
import prepare_kimi_tb4_sandoq_clamped_recovery as recovery

SCHEMA_VERSION = 3
KIND = "direct-kimi-sandoq-tb4"
ADAPTER = "kimi-tb4-miniswe246-sandoq-clamped-union-v1"
CERTIFICATE = "certificate.json"
RESULTS = "results.jsonl"
NATIVE_TASKS = 25
CLAMPED_TASKS = 27
SUPPORTED_TASKS = NATIVE_TASKS + CLAMPED_TASKS
COMPOSE_UNSUPPORTED = 11
GPU_UNSUPPORTED = 3
UNSUPPORTED_TASKS = COMPOSE_UNSUPPORTED + GPU_UNSUPPORTED
TOTAL_TASKS = 66
MIN_PASSES = 7
MAX_ALL_TASK_PASS_RATE = 0.22
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ClampedUnionError(ValueError):
    """A lane or aggregate certificate failed closed."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise ClampedUnionError(code)
    raise ClampedUnionError(code) from error


def _canonical(value: Mapping[str, Any]) -> bytes:
    return split.canonical_json(value)


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _self_sha256() -> str:
    return _sha256(split.read_regular(Path(__file__), code="implementation_unreadable"))


def _artifact(path: Path, body: bytes) -> dict[str, int | str]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _read_plan(path: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    recovery.verify(path, expected_sha256)
    body = split.read_regular(path, code="recovery_plan_invalid", private=True)
    if _sha256(body) != expected_sha256:
        _fail("recovery_plan_invalid")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("recovery_plan_invalid", error)
    if not isinstance(value, dict) or _canonical(value) != body:
        _fail("recovery_plan_invalid")
    return value, body


def _selector_members(record: Mapping[str, Any]) -> tuple[str, ...]:
    path = Path(str(record.get("path", "")))
    body = split.read_regular(path, code="selector_invalid", private=True)
    if _artifact(path, body) != record:
        _fail("selector_invalid")
    try:
        members = tuple(body.decode().splitlines())
    except UnicodeDecodeError as error:
        _fail("selector_invalid", error)
    if len(members) != len(set(members)) or body != native_plan._selector_payload(members):
        _fail("selector_invalid")
    return members


def _fake_plan(
    *,
    lane: Mapping[str, Any],
    manifest: Mapping[str, Any],
    contracts: Mapping[str, Any],
    plan_sha256: str,
) -> dict[str, Any]:
    lane_value = dict(lane)
    lane_value.setdefault("resource_multiplier", 1.0)
    return {
        "source": {"manifest": dict(manifest)},
        "contracts": dict(contracts),
        "lanes": {native_plan.SANDOQ_ROLE: lane_value},
        "plan_sha256": plan_sha256,
    }


def _validate_clamped_config(config: Mapping[str, Any]) -> None:
    taskset = config.get("taskset")
    if (
        config.get("num_tasks") != CLAMPED_TASKS
        or config.get("max_concurrent") != recovery.CONCURRENCY
        or config.get("multiplex") != recovery.CONCURRENCY
        or not isinstance(taskset, dict)
        or taskset.get("enable_compose") is not False
        or taskset.get("resource_multiplier") != 1.0
        or taskset.get("resource_cpu_cap") != recovery.CPU_CAP
        or taskset.get("resource_memory_mb_cap") != recovery.MEMORY_MB_CAP
        or taskset.get("resource_storage_mb_cap") != recovery.STORAGE_MB_CAP
    ):
        _fail("clamped_resource_contract_invalid")


def _build_lane(
    *,
    label: str,
    run_dir: Path,
    lane: Mapping[str, Any],
    manifest: Mapping[str, Any],
    contracts: Mapping[str, Any],
    plan_sha256: str,
    members: Sequence[str],
    entries: Sequence[split.ManifestEntry],
    require_caps: bool,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    plan = _fake_plan(
        lane=lane,
        manifest=manifest,
        contracts=contracts,
        plan_sha256=plan_sha256,
    )
    run_dir = split._absolute_path(run_dir)
    with ExitStack() as stack:
        held = split._HeldArtifactSet.create()
        stack.callback(held.close)
        evidence = split._open_held_run_evidence(run_dir)
        stack.callback(evidence.close)
        router_lock = stack.enter_context(
            split._open_private_writer_lock(split._router_lock_path(evidence.files["eval_run_identity.json"].body))
        )
        writer_lock = stack.enter_context(split._open_private_writer_lock_at(evidence.directory, ".writer.lock"))
        for lock in (router_lock, writer_lock):
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                _fail("writer_active", error)
        identity, contracts, identity_sha256, invocation_sha256, slurm_job_id = native_cert._identity_contract(
            run_dir=run_dir,
            plan=plan,
            role=native_plan.SANDOQ_ROLE,
            members=members,
            run_evidence=evidence,
            held=held,
        )
        config_record = lane.get("config")
        if not isinstance(config_record, dict):
            _fail("lane_config_invalid")
        config_body = split.read_regular(
            Path(str(config_record.get("path", ""))),
            code="lane_config_invalid",
            private=True,
            held=held,
        )
        try:
            config = tomllib.loads(config_body.decode())
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            _fail("lane_config_invalid", error)
        if require_caps:
            _validate_clamped_config(config)
        verifier_modes = {entry.task_id: entry.verifier_mode for entry in entries}
        try:
            trace_audit, rows, results_artifact = split._audit_cpu_results(
                run_dir / RESULTS,
                members,
                verifier_modes,
                held,
            )
        except Exception as error:
            _fail("lane_trace_audit_failed", error)
        tool_execution = native_cert._tool_execution(rows)
        artifacts = split._run_artifacts(run_dir, results_artifact, evidence, held)
        selector_path = Path(str(lane["selector"]["path"]))
        artifacts["selector"] = split._artifact(selector_path, private=True, held=held)
        router_body, router_artifact, router_marker = split._validate_direct_router_receipt(
            run_dir / "direct_kimi_router_final.json",
            identity,
            minimum_chat_requests=len(members),
            identity_sha256=identity_sha256,
            invocation_identity_sha256=invocation_sha256,
            held=held,
        )
        if router_artifact["sha256"] != _sha256(router_body):
            _fail("router_receipt_changed")
        artifacts["router_receipt"] = router_artifact
        artifacts["router_receipt_commit"] = router_marker
        cleanup, cleanup_artifacts = split._validate_sandoq_cleanup(
            run_dir / "sandoq_cleanup_audit.json",
            run_dir,
            identity,
            identity_sha256,
            invocation_sha256,
            slurm_job_id,
            len(members),
            int(lane["concurrency"]),
            held,
        )
        artifacts.update(cleanup_artifacts)
        artifacts["provider_context"] = split._artifact(
            run_dir / "sandoq-provider-context.json",
            private=True,
            held=held,
        )
        if artifacts["provider_context"] != contracts["provider_context"]:
            _fail("provider_context_changed")
        split._revalidate_artifacts(artifacts)
        evidence.revalidate()
        held.revalidate()
        lane_value = {
            "label": label,
            "run_dir": str(run_dir),
            "task_count": len(members),
            "eval_run_identity_sha256": identity_sha256,
            "invocation_identity_sha256": invocation_sha256,
            "shared_contract": contracts["shared"],
            "trace_audit": trace_audit,
            "tool_execution": tool_execution,
            "cleanup": cleanup,
            "artifacts": artifacts,
        }
        return lane_value, rows


def _compose_unsupported_row(task_id: str, manifest_sha256: str) -> dict[str, Any]:
    expected_name = f"terminal-bench/{task_id}"
    message = (
        f"taskset setup: UnsupportedTaskError: {expected_name}: "
        "requires Compose services, which are unavailable in the qualified Sandoq Firecracker runtime"
    )
    return {
        "id": f"compose-unsupported-{_sha256((manifest_sha256 + chr(0) + task_id).encode())}",
        "task": {"name": expected_name},
        "is_completed": True,
        "stop_condition": "error",
        "nodes": [],
        "rewards": {},
        "metrics": {},
        "errors": [{"type": "TasksetError", "message": message, "traceback": message}],
    }


def _merge_rows(
    entries: Sequence[split.ManifestEntry],
    native_rows: Mapping[str, dict[str, Any]],
    clamped_rows: Mapping[str, dict[str, Any]],
    native_members: Sequence[str],
    clamped_members: Sequence[str],
    compose_members: Sequence[str],
    gpu_members: Sequence[str],
    manifest_sha256: str,
) -> tuple[bytes, int]:
    expected_groups = tuple(map(set, (native_members, clamped_members, compose_members, gpu_members)))
    if (
        set(native_rows) != expected_groups[0]
        or set(clamped_rows) != expected_groups[1]
        or any(expected_groups[left] & expected_groups[right] for left in range(4) for right in range(left + 1, 4))
        or set().union(*expected_groups) != {entry.task_id for entry in entries}
    ):
        _fail("union_coverage_invalid")
    merged: list[dict[str, Any]] = []
    trace_ids: set[str] = set()
    passes = 0
    compose = set(compose_members)
    gpu = set(gpu_members)
    for entry in entries:
        if entry.task_id in native_rows:
            row = native_rows[entry.task_id]
            passes += split._score(row)
        elif entry.task_id in clamped_rows:
            row = clamped_rows[entry.task_id]
            passes += split._score(row)
        elif entry.task_id in compose:
            row = _compose_unsupported_row(entry.task_id, manifest_sha256)
        elif entry.task_id in gpu:
            row = split._gpu_unsupported_row(entry.task_id, manifest_sha256)
        else:
            _fail("union_coverage_invalid")
        trace_id = row.get("id")
        if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
            _fail("merged_trace_id_invalid")
        trace_ids.add(trace_id)
        merged.append(row)
    if len(merged) != TOTAL_TASKS or len(trace_ids) != TOTAL_TASKS:
        _fail("union_coverage_invalid")
    return b"".join(_canonical(row) for row in merged), passes


def _validate_shared_contract(native: Mapping[str, Any], clamped: Mapping[str, Any]) -> None:
    native_shared = native.get("shared_contract")
    clamped_shared = clamped.get("shared_contract")
    if not isinstance(native_shared, dict) or not isinstance(clamped_shared, dict):
        _fail("lane_contract_mismatch")
    for key in (
        "model_contract",
        "harness",
        "deployment_contract",
        "provider_neutral_config_sha256",
        "timeout_contract",
    ):
        if native_shared.get(key) != clamped_shared.get(key):
            _fail("lane_contract_mismatch")
    for shared in (native_shared, clamped_shared):
        revisions = shared.get("source_revisions")
        if (
            not isinstance(revisions, dict)
            or revisions.get("verifiers_commit") != native_plan.VERIFIERS_COMMIT
            or not isinstance(revisions.get("prime_rl_commit"), str)
        ):
            _fail("lane_contract_mismatch")


def build_union(
    *,
    recovery_plan: Path,
    recovery_plan_sha256: str,
    native_run_dir: Path,
    clamped_run_dir: Path,
    output: Path,
    publish: bool,
) -> tuple[dict[str, Any], bytes]:
    plan, plan_body = _read_plan(recovery_plan, recovery_plan_sha256)
    source_plan_record = plan["source"]["union_plan"]
    source_plan_path = Path(str(source_plan_record["path"]))
    source_plan, source_plan_body, entries = recovery._load_source_plan(
        source_plan_path,
        str(source_plan_record["sha256"]),
    )
    if _artifact(source_plan_path, source_plan_body) != source_plan_record:
        _fail("source_plan_changed")
    native_lane = source_plan["lanes"][native_plan.SANDOQ_ROLE]
    native_members = _selector_members(native_lane["selector"])
    clamped_members, compose_members = recovery._members(source_plan, entries)
    gpu_members = split.derive_partition(entries).gpu_unsupported
    native, native_rows = _build_lane(
        label="native_sandoq",
        run_dir=native_run_dir,
        lane=native_lane,
        manifest=source_plan["source"]["manifest"],
        contracts=source_plan["contracts"],
        plan_sha256=str(source_plan_record["sha256"]),
        members=native_members,
        entries=entries,
        require_caps=False,
    )
    clamped, clamped_rows = _build_lane(
        label="clamped_sandoq",
        run_dir=clamped_run_dir,
        lane=plan["lane"],
        manifest=plan["source"]["resource_manifest"],
        contracts=source_plan["contracts"],
        plan_sha256=recovery_plan_sha256,
        members=clamped_members,
        entries=entries,
        require_caps=True,
    )
    _validate_shared_contract(native, clamped)
    manifest_sha256 = str(source_plan["source"]["manifest"]["sha256"])
    results_body, passes = _merge_rows(
        entries,
        native_rows,
        clamped_rows,
        native_members,
        clamped_members,
        compose_members,
        gpu_members,
        manifest_sha256,
    )
    all_task_pass_rate = passes / TOTAL_TASKS
    if passes < MIN_PASSES or all_task_pass_rate > MAX_ALL_TASK_PASS_RATE:
        _fail("tb4_score_outside_expected_range")
    results_path = output / RESULTS
    artifacts = {
        "results": _artifact(results_path, results_body),
        "recovery_plan": _artifact(recovery_plan, plan_body),
        "source_union_plan": _artifact(source_plan_path, source_plan_body),
        "native_results": dict(native["artifacts"]["results"]),
        "clamped_results": dict(clamped["artifacts"]["results"]),
    }
    deployment = native["shared_contract"]["deployment_contract"]
    policy = {
        "expected_tasks": TOTAL_TASKS,
        "expected_supported_tasks": SUPPORTED_TASKS,
        "minimum_passes": MIN_PASSES,
        "maximum_all_task_pass_rate": MAX_ALL_TASK_PASS_RATE,
        "rollouts_per_task": 1,
        "max_sequence_tokens": split.MAX_SEQUENCE_TOKENS,
        "provider_partition": {
            "native_sandoq": NATIVE_TASKS,
            "clamped_sandoq": CLAMPED_TASKS,
            "compose_unsupported": COMPOSE_UNSUPPORTED,
            "gpu_unsupported": GPU_UNSUPPORTED,
        },
        "resource_caps": plan["policy"]["resource_caps"],
        "harness": {"id": "mini-swe-agent", "version": native_plan.MINISWE_VERSION},
    }
    timeout_contract = native_cert._plan_timeout_contract(source_plan)
    if timeout_contract is not None:
        policy["timeouts"] = timeout_contract
    certificate: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "passed",
        "model": "Kimi-K3",
        "adapter": ADAPTER,
        "manifest_sha256": manifest_sha256,
        "results_sha256": _sha256(results_body),
        "endpoint_bundle_sha256": deployment["endpoint_bundle_sha256"],
        "source_spec_sha256": deployment["spec_sha256"],
        "deployment": {
            "endpoint_bundle_sha256": deployment["endpoint_bundle_sha256"],
            "source_spec_sha256": deployment["spec_sha256"],
            "worker_generation_sha256": deployment["worker_generation_sha256"],
        },
        "counts": {
            "observed_traces": TOTAL_TASKS,
            "supported_tasks": SUPPORTED_TASKS,
            "unsupported_tasks": UNSUPPORTED_TASKS,
            "compose_unsupported_tasks": COMPOSE_UNSUPPORTED,
            "gpu_unsupported_tasks": GPU_UNSUPPORTED,
            "supported_passes": passes,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "scores": {
            "supported_pass_rate": passes / SUPPORTED_TASKS,
            "all_task_pass_rate": all_task_pass_rate,
        },
        "policy": policy,
        "providers": {"native_sandoq": native, "clamped_sandoq": clamped},
        "trace_audit": {
            "cpu_traces": SUPPORTED_TASKS,
            "unsupported_outcomes": UNSUPPORTED_TASKS,
            "total_traces": TOTAL_TASKS,
            "model_io_turns": native["trace_audit"]["model_io_turns"] + clamped["trace_audit"]["model_io_turns"],
            "sampled_tokens": native["trace_audit"]["sampled_tokens"] + clamped["trace_audit"]["sampled_tokens"],
            "tool_observations": native["tool_execution"]["tool_observations"]
            + clamped["tool_execution"]["tool_observations"],
            "reasoning_required": True,
            "request_graph_match_required": True,
            "exact_provider_json_required": True,
            "trace_failures": 0,
        },
        "artifacts": artifacts,
        "implementation_sha256": _self_sha256(),
    }
    certificate["tb4_certificate_sha256"] = _sha256(_canonical(certificate))
    certificate_body = _canonical(certificate)
    if publish:
        split._publish_private_bundle(output, {RESULTS: results_body, CERTIFICATE: certificate_body})
    return certificate, certificate_body


def validate_certificate(path: Path, expected_sha256: str) -> dict[str, Any]:
    body = split.read_regular(path, code="clamped_union_certificate_invalid", private=True)
    if SHA256_RE.fullmatch(expected_sha256 or "") is None or _sha256(body) != expected_sha256:
        _fail("clamped_union_certificate_invalid")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("clamped_union_certificate_invalid", error)
    if (
        not isinstance(value, dict)
        or _canonical(value) != body
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != KIND
        or value.get("adapter") != ADAPTER
        or value.get("implementation_sha256") != _self_sha256()
    ):
        _fail("clamped_union_certificate_invalid")
    artifacts = value.get("artifacts")
    providers = value.get("providers")
    if not isinstance(artifacts, dict) or not isinstance(providers, dict):
        _fail("clamped_union_certificate_invalid")
    expected, expected_body = build_union(
        recovery_plan=Path(str(artifacts["recovery_plan"]["path"])),
        recovery_plan_sha256=str(artifacts["recovery_plan"]["sha256"]),
        native_run_dir=Path(str(providers["native_sandoq"]["run_dir"])),
        clamped_run_dir=Path(str(providers["clamped_sandoq"]["run_dir"])),
        output=path.parent,
        publish=False,
    )
    results = split.read_regular(path.parent / RESULTS, code="clamped_union_results_invalid", private=True)
    if expected_body != body or _sha256(results) != expected["results_sha256"]:
        _fail("clamped_union_certificate_changed")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--recovery-plan", type=Path, required=True)
    merge.add_argument("--recovery-plan-sha256", required=True)
    merge.add_argument("--native-run-dir", type=Path, required=True)
    merge.add_argument("--clamped-run-dir", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--certificate", type=Path, required=True)
    validate.add_argument("--certificate-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "merge":
            value, body = build_union(
                recovery_plan=args.recovery_plan,
                recovery_plan_sha256=args.recovery_plan_sha256,
                native_run_dir=args.native_run_dir,
                clamped_run_dir=args.clamped_run_dir,
                output=args.output,
                publish=True,
            )
            result = {
                "state": "passed",
                "supported_passes": value["counts"]["supported_passes"],
                "all_task_pass_rate": value["scores"]["all_task_pass_rate"],
                "certificate_sha256": _sha256(body),
            }
        else:
            value = validate_certificate(args.certificate, args.certificate_sha256)
            result = {
                "state": "passed",
                "supported_passes": value["counts"]["supported_passes"],
                "all_task_pass_rate": value["scores"]["all_task_pass_rate"],
                "certificate_sha256": args.certificate_sha256,
            }
    except (OSError, RuntimeError, ValueError):
        print(json.dumps({"code": "clamped_union_certificate_failed", "state": "blocked"}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
