#!/usr/bin/env python3
"""Certify and merge the opaque Kimi TB4 MiniSWE 52/11/3 provider union."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
from direct_kimi_capacity import validate_capacity_certificate
from direct_kimi_router import C64_W2_CAPACITY_PROFILE
from direct_kimi_workers import load_saved_manifest, worker_generation_contract
from eval_run_identity import _validate_w2_smoke_checkpoint_provenance
from kimi_endpoint_load_gate import validate_load_gate
from kimi_endpoint_walltime_gate import VMVM_UNION_PROFILE, W2_PROFILE
from kimi_endpoint_walltime_gate import load_receipt as load_walltime_receipt
from kimi_sandoq_production import _validate_provider_context_snapshot
from kimi_tb4_w2_gate import validate_launch as validate_w2_launch

LANE_CERTIFICATE_KIND = "direct-kimi-tb4-miniswe246-provider-lane"
UNION_CERTIFICATE_KIND = "direct-kimi-sandoq-tb4"
UNION_CERTIFICATE_SCHEMA_VERSION = 2
MERGED_RESULTS = "results.jsonl"
UNION_CERTIFICATE = "certificate.json"
MIN_CPU_PASSES = 7
MIN_CPU_PASS_RATE = MIN_CPU_PASSES / union.CPU_TASKS
MAX_CPU_PASS_RATE = 0.22
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
OFFICIAL_SELECTOR = Path(__file__).resolve().parent / "configs/eval/tb4_qwen_a95b_miniswe.tasks.txt"


class UnionCertificationError(ValueError):
    """A sealed lane or union failed a content-blind certification check."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise UnionCertificationError(code)
    raise UnionCertificationError(code) from error


def _plan_timeout_contract(plan: dict[str, Any]) -> dict[str, int] | None:
    contracts = plan.get("contracts")
    timeout_contract = contracts.get("timeouts") if isinstance(contracts, dict) else None
    if timeout_contract is None:
        return None
    if timeout_contract not in (union.LEGACY_TIMEOUT_CONTRACT, union.TIMEOUT_CONTRACT):
        _fail("timeout_contract_invalid")
    return dict(timeout_contract)


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return split.canonical_json(value)


def _self_sha256() -> str:
    return _sha256(split.read_regular(Path(__file__), code="implementation_unreadable"))


def _load_plan(path: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes, tuple[split.ManifestEntry, ...]]:
    for role in (union.SANDOQ_ROLE, union.VMVM_ROLE):
        union.verify_launch_plan(path, expected_sha256, role)
    body = split.read_regular(path, code="launch_plan_invalid", private=True)
    if _sha256(body) != expected_sha256:
        _fail("launch_plan_invalid")
    try:
        value = json.loads(body)
        manifest_record = value["source"]["manifest"]
        manifest_path = Path(manifest_record["path"])
        manifest_body = split.read_regular(manifest_path, code="resource_manifest_invalid", private=True)
        _manifest, entries = split.parse_manifest(manifest_body, manifest_record["sha256"])
    except (KeyError, OSError, TypeError, ValueError) as error:
        _fail("launch_plan_invalid", error)
    if not isinstance(value, dict):
        _fail("launch_plan_invalid")
    return value, body, entries


def _lane_members(entries: Sequence[split.ManifestEntry], role: str) -> tuple[str, ...]:
    partition = union.derive_union_partition(entries)
    if role == union.SANDOQ_ROLE:
        return partition.sandoq_firecracker
    if role == union.VMVM_ROLE:
        return partition.vmvm_cpu
    _fail("lane_role_invalid")


def _lane_provider(role: str) -> str:
    if role == union.SANDOQ_ROLE:
        return "sandoq"
    if role == union.VMVM_ROLE:
        return "vmvm"
    _fail("lane_role_invalid")


def _artifact_from_plan(plan: Mapping[str, Any], role: str, name: str) -> tuple[Path, bytes, dict[str, Any]]:
    lane = plan.get("lanes", {}).get(role)
    record = lane.get(name) if isinstance(lane, dict) else None
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        _fail("launch_plan_invalid")
    path = Path(str(record["path"]))
    body = split.read_regular(path, code="launch_plan_artifact_invalid", private=True)
    if len(body) != record["bytes"] or _sha256(body) != record["sha256"]:
        _fail("launch_plan_artifact_invalid")
    return path, body, record


def _stable_deployment_contract(identity: Mapping[str, Any], held: split._HeldArtifactSet) -> dict[str, Any]:
    """Validate a lane deployment and return its provider-neutral model generation.

    The two lanes deliberately use different admission envelopes (Sandoq c64-w2
    and VMVM c24).  Those fields are compared separately as exact lane routing
    contracts; only loopback paths and admission-only fields are removed here.
    """

    try:
        deployment = split._deployment_contract(identity, held)
        manifest_path = Path(str(identity["deployment"]["worker_manifest"]["path"]))
        _manifest_body, manifest = load_saved_manifest(
            manifest_path,
            revalidate_live_source=False,
            held=held,
        )
        generation = worker_generation_contract(manifest, revalidate_live_source=False, held=held)
    except (KeyError, OSError, TypeError, ValueError) as error:
        _fail("deployment_binding_invalid", error)
    generation.pop("deployment_root", None)
    generation["schema_version"] = 0
    generation_router = generation.get("router")
    if not isinstance(generation_router, dict):
        _fail("deployment_binding_invalid")
    for key in (
        "capacity_profile",
        "endpoint_identifier",
        "per_worker_capacity",
        "max_concurrent_requests",
        "queue_size",
    ):
        generation_router.pop(key, None)
    neutral_router = dict(deployment["router"])
    for key in ("capacity_profile", "endpoint_identifier", "per_worker_capacity", "provider_concurrency"):
        neutral_router.pop(key, None)
    deployment["router"] = neutral_router
    deployment["worker_generation_sha256"] = _sha256(_canonical(generation))
    return deployment


def _tool_execution(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    observations = 0
    successful = 0
    nonzero = 0
    traces_with_tools = 0
    for row in rows.values():
        row_observations = 0
        nodes = row.get("nodes")
        if not isinstance(nodes, list):
            _fail("tool_exit_evidence_missing")
        for node in nodes:
            message = node.get("message") if isinstance(node, dict) else None
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            row_observations += 1
            observations += 1
            extra = message.get("extra")
            return_code = extra.get("returncode") if isinstance(extra, dict) else None
            content_value: object | None = None
            if isinstance(message.get("content"), str):
                try:
                    content_value = json.loads(message["content"])
                except json.JSONDecodeError:
                    content_value = None
            content_return_code = content_value.get("returncode") if isinstance(content_value, dict) else None
            candidates = [
                value
                for value in (return_code, content_return_code)
                if isinstance(value, int) and not isinstance(value, bool)
            ]
            if not candidates or len(set(candidates)) != 1:
                _fail("tool_exit_evidence_invalid")
            if candidates[0] == 0:
                successful += 1
            else:
                nonzero += 1
        if row_observations < 1:
            _fail("tool_exit_evidence_missing")
        traces_with_tools += 1
    if observations < len(rows) or successful + nonzero != observations or traces_with_tools != len(rows):
        _fail("tool_exit_evidence_invalid")
    return {
        "tool_observations": observations,
        "successful_tool_exits": successful,
        "nonzero_tool_exits": nonzero,
        "missing_tool_exits": 0,
        "traces_with_tool_exit_evidence": traces_with_tools,
    }


def _identity_contract(
    *,
    run_dir: Path,
    plan: Mapping[str, Any],
    role: str,
    members: Sequence[str],
    run_evidence: Any,
    held: Any,
    expected_revision: str,
) -> tuple[dict[str, Any], dict[str, Any], str, str, str]:
    try:
        envelope = split.load_eval_run_identity_bytes(
            run_evidence.files["eval_run_identity.json"].body,
            run_dir=run_dir,
            verify_references=True,
            verify_saved_provenance=False,
        )
        identity = envelope["identity"]
        identity_sha256 = envelope["eval_run_identity_sha256"]
    except Exception as error:
        _fail("run_identity_invalid", error)
    provider = _lane_provider(role)
    lane = plan["lanes"][role]
    selector_path, selector_body, selector_record = _artifact_from_plan(plan, role, "selector")
    config_path, config_body, config_record = _artifact_from_plan(plan, role, "config")
    try:
        config = tomllib.loads(config_body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        _fail("run_config_invalid", error)
    source = identity.get("source") if isinstance(identity, dict) else None
    execution = identity.get("execution") if isinstance(identity, dict) else None
    runtime = execution.get("runtime") if isinstance(execution, dict) else None
    environment = execution.get(f"{provider}_environment") if isinstance(execution, dict) else None
    task_file = identity.get("inputs", {}).get("task_file") if isinstance(identity, dict) else None
    config_identity = identity.get("config") if isinstance(identity, dict) else None
    source_config = config_identity.get("source") if isinstance(config_identity, dict) else None
    resolved = config_identity.get("resolved") if isinstance(config_identity, dict) else None
    contract = identity.get("contract") if isinstance(identity, dict) else None
    timeout_contract = _plan_timeout_contract(plan)
    request_timeout = (
        timeout_contract["request_seconds"] if timeout_contract is not None else union.LEGACY_REQUEST_TIMEOUT_SECONDS
    )
    expected_harness = {
        "id": "mini-swe-agent",
        "version": union.MINISWE_VERSION,
        "placement": "sandbox",
        "step_limit": 200,
        "request_timeout_seconds": request_timeout,
        "request_max_retries": 0,
    }
    if (
        not isinstance(identity, dict)
        or identity.get("role") != "kimi-direct-tb4"
        or not isinstance(source, dict)
        or source.get("sandbox_provider", "vmvm") != provider
        or source.get("prime_rl_commit") != expected_revision
        or source.get("verifiers_commit") != union.VERIFIERS_COMMIT
        or not isinstance(execution, dict)
        or execution.get("cleanup_must_succeed") is not True
        or any(
            execution.get(key) != lane["concurrency"]
            for key in (
                "rollout_concurrency",
                "multiplex",
                "http_max_connections",
                "http_max_keepalive_connections",
            )
        )
        or not isinstance(runtime, dict)
        or runtime.get("type") != provider
        or not isinstance(environment, dict)
        or not isinstance(task_file, dict)
        or task_file.get("sha256") != selector_record["sha256"]
        or task_file.get("count") != len(members)
        or not isinstance(source_config, dict)
        or source_config.get("sha256") != config_record["sha256"]
        or not isinstance(resolved, dict)
        or not isinstance(contract, dict)
        or contract.get("harness") != expected_harness
        or contract.get("model") != "Kimi-K3"
    ):
        _fail("run_identity_invalid")
    observed_selector = split.read_regular(selector_path, code="run_selector_invalid", private=True, held=held)
    if observed_selector != union._selector_payload(members) or observed_selector != selector_body:
        _fail("run_selector_invalid")
    task_snapshot = split.read_regular(
        Path(str(task_file["path"])),
        code="run_selector_invalid",
        private=True,
        held=held,
    )
    if task_snapshot != observed_selector:
        _fail("run_selector_invalid")
    if provider == "sandoq":
        if (
            runtime.get("mode") != "oci-runner"
            or runtime.get("network_access") is not True
            or runtime.get("host_tunnel") != "sandoq"
            or runtime.get("buffered_chat_completions") is not True
            or runtime.get("guest_tunnel_url") != "http://127.0.0.1:8485"
            or runtime.get("expected_environment") != "oci-runner-firecracker"
            or environment.get("environment") != "oci-runner-firecracker"
            or environment.get("task_network") != "public"
            or environment.get("provider_task_network") != "host"
            or environment.get("provider_profile_sha256") != union.PROVIDER_PROFILE_SHA256
            or environment.get("runtime_tunnel_receipt_sha256") != union.FULL_TUNNEL_RECEIPT_SHA256
            or environment.get("runtime_resource_receipt_sha256") != union.FULL_RESOURCE_RECEIPT_SHA256
            or environment.get("allow_dockerhub_fallback") is not False
        ):
            _fail("sandoq_runtime_contract_invalid")
        context_artifact = _validate_provider_context_snapshot(run_dir / "sandoq-provider-context.json")
        provider_context = context_artifact.as_dict()
    else:
        if runtime.get("type") != "vmvm" or config.get("taskset", {}).get("enable_compose") is not True:
            _fail("vmvm_runtime_contract_invalid")
        provider_context = None
    if config.get("taskset", {}).get("resource_multiplier") != lane["resource_multiplier"]:
        _fail("resource_multiplier_invalid")
    try:
        deployment = _stable_deployment_contract(identity, held)
        model_contract = split._model_contract(identity)
        invocation_sha256, slurm_job_id = split._run_invocation_binding(
            run_evidence.files["eval_invocations.jsonl"].body,
            run_evidence.files["provenance.txt"].body,
            identity_sha256,
        )
    except Exception as error:
        _fail("run_identity_invalid", error)
    revisions = {
        key: source.get(key)
        for key in (
            "prime_rl_commit",
            "prime_rl_tree_sha256",
            "verifiers_commit",
            "verifiers_tree_sha256",
            "renderers_commit",
            "renderers_tree_sha256",
        )
    }
    if any(not isinstance(value, str) or not value for value in revisions.values()):
        _fail("source_closure_invalid")
    shared = {
        "model_contract": model_contract,
        "harness": expected_harness,
        "deployment_contract": deployment,
        "provider_neutral_config_sha256": _sha256(_canonical(union._provider_neutral_config(config))),
        "source_revisions": revisions,
        "plan_sha256": plan["plan_sha256"] if "plan_sha256" in plan else None,
    }
    if timeout_contract is not None:
        shared["timeout_contract"] = timeout_contract
    return (
        identity,
        {
            "shared": shared,
            "provider_context": provider_context,
            "routing": json.loads(_canonical(identity["deployment"]["router"])),
        },
        identity_sha256,
        invocation_sha256,
        slurm_job_id,
    )


def _plan_with_digest(plan: dict[str, Any], plan_sha256: str) -> dict[str, Any]:
    value = dict(plan)
    value["plan_sha256"] = plan_sha256
    return value


def _build_lane_certificate(
    *,
    role: str,
    run_dir: Path,
    launch_plan: Path,
    launch_plan_sha256: str,
    expected_revision: str,
    capacity_receipt: Path | None = None,
    capacity_receipt_sha256: str | None = None,
    capacity_public_key: Path | None = None,
    capacity_public_key_sha256: str | None = None,
    publish_output: Path | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if REVISION_RE.fullmatch(expected_revision) is None:
        _fail("source_revision_invalid")
    plan_value, plan_body, entries = _load_plan(launch_plan, launch_plan_sha256)
    plan = _plan_with_digest(plan_value, launch_plan_sha256)
    members = _lane_members(entries, role)
    provider = _lane_provider(role)
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
        identity, contracts, identity_sha256, invocation_sha256, slurm_job_id = _identity_contract(
            run_dir=run_dir,
            plan=plan,
            role=role,
            members=members,
            run_evidence=evidence,
            held=held,
            expected_revision=expected_revision,
        )
        identity_deployment = identity.get("deployment")
        identity_router = identity_deployment.get("router") if isinstance(identity_deployment, dict) else None
        if (
            not isinstance(identity_deployment, dict)
            or not isinstance(identity_router, dict)
            or identity_router.get("capacity_profile") != C64_W2_CAPACITY_PROFILE
            or identity_router.get("endpoint_identifier") != "cpu-132-021_8103"
            or identity_router.get("provider_concurrency") != 64
            or identity_router.get("per_worker_capacity") != 2
            or identity_router.get("worker_count") != 24
            or identity_router.get("retries") != 0
        ):
            _fail("w2_router_contract_invalid")
        try:
            exact_deployment = split._deployment_contract(identity, held)
            _manifest_body, lane_manifest = load_saved_manifest(
                Path(identity_deployment["worker_manifest"]["path"]),
                revalidate_live_source=False,
                held=held,
            )
            smoke_payload = json.loads(
                split.read_regular(
                    Path(identity_deployment["smoke_checkpoint"]["path"]),
                    code="w2_smoke_invalid",
                    private=True,
                    held=held,
                )
            )
            if not _validate_w2_smoke_checkpoint_provenance(
                smoke_payload,
                lane_manifest,
                expected_revision=expected_revision,
                expected_tree_sha256=identity["source"]["prime_rl_tree_sha256"],
            ):
                _fail("w2_smoke_invalid")
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            _fail("w2_smoke_invalid", error)
        contracts["deployment"] = exact_deployment
        verifier_modes = {entry.task_id: entry.verifier_mode for entry in entries}
        try:
            trace_audit, rows, results_artifact = split._audit_cpu_results(
                run_dir / "results.jsonl", members, verifier_modes, held
            )
        except Exception as error:
            _fail("provider_trace_audit_failed", error)
        tool_execution = _tool_execution(rows)
        artifacts = split._run_artifacts(run_dir, results_artifact, evidence, held)
        selector_path, _selector_body, _selector_record = _artifact_from_plan(plan, role, "selector")
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
        identity_deployment = identity["deployment"]
        for name in (
            "smoke_checkpoint",
            "capacity_certificate",
            "capacity_gate_receipt",
            "endpoint_load_gate",
            "endpoint_walltime_gate",
        ):
            record = identity_deployment.get(name)
            if not isinstance(record, dict):
                _fail("w2_artifact_missing")
            observed = split._artifact(Path(str(record.get("path", ""))), private=True, held=held)
            if observed.get("sha256") != record.get("sha256"):
                _fail("w2_artifact_changed")
            artifacts[name] = observed
        try:
            load_walltime_receipt(
                Path(identity_deployment["endpoint_walltime_gate"]["path"]),
                manifest_sha256=identity_deployment["worker_manifest"]["sha256"],
                endpoint_bundle_sha256=identity_deployment["endpoint_bundle_sha256"],
                profile=W2_PROFILE if provider == "sandoq" else VMVM_UNION_PROFILE,
                minimum_remaining_seconds=96 * 60 * 60,
                task_count=len(members),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            _fail("w2_walltime_evidence_invalid", error)
        capacity_summary: dict[str, Any] | None = None
        if provider == "sandoq":
            cleanup, cleanup_artifacts = split._validate_sandoq_cleanup(
                run_dir / "sandoq_cleanup_audit.json",
                run_dir,
                identity,
                identity_sha256,
                invocation_sha256,
                slurm_job_id,
                len(members),
                int(plan["lanes"][role]["concurrency"]),
                held,
            )
            artifacts.update(cleanup_artifacts)
            artifacts["provider_context"] = split._artifact(
                run_dir / "sandoq-provider-context.json", private=True, held=held
            )
            if artifacts["provider_context"] != contracts["provider_context"]:
                _fail("provider_context_changed")
            try:
                capacity_payload = validate_capacity_certificate(
                    Path(identity_deployment["capacity_certificate"]["path"]),
                    expected_sha256=identity_deployment["capacity_certificate"]["sha256"],
                    required_concurrency=48,
                    expected_endpoint_identifier="cpu-132-021_8103",
                )
                expected_gate = validate_w2_launch(
                    certificate_path=Path(identity_deployment["capacity_certificate"]["path"]),
                    certificate_sha256=identity_deployment["capacity_certificate"]["sha256"],
                    manifest_path=Path(identity_deployment["worker_manifest"]["path"]),
                    manifest_sha256=identity_deployment["worker_manifest"]["sha256"],
                    selector=OFFICIAL_SELECTOR,
                    dataset_dir=Path(identity["dataset"]["path"]),
                    expected_revision=expected_revision,
                    sandoq_site=Path(identity["source"]["sandoq_site"]),
                    union_launch_plan=launch_plan,
                    union_launch_plan_sha256=launch_plan_sha256,
                )
                observed_gate = json.loads(
                    split.read_regular(
                        Path(identity_deployment["capacity_gate_receipt"]["path"]),
                        code="w2_gate_invalid",
                        private=True,
                        held=held,
                    )
                )
                if observed_gate != expected_gate:
                    _fail("w2_gate_invalid")
                validate_load_gate(
                    Path(identity_deployment["endpoint_load_gate"]["path"]),
                    expected_sha256=identity_deployment["endpoint_load_gate"]["sha256"],
                    manifest_sha256=identity_deployment["worker_manifest"]["sha256"],
                    endpoint_bundle_sha256=identity_deployment["endpoint_bundle_sha256"],
                )
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                _fail("w2_evidence_invalid", error)
            capacity_summary = {
                "provider": "sandoq",
                "qualification_scope": capacity_payload["qualification_scope"],
                "qualified_concurrency": capacity_payload["qualified_concurrency"],
                "receipt_sha256": identity_deployment["capacity_certificate"]["sha256"],
                "gate_sha256": identity_deployment["capacity_gate_receipt"]["sha256"],
                "load_gate_sha256": identity_deployment["endpoint_load_gate"]["sha256"],
            }
            if any(
                value is not None
                for value in (
                    capacity_receipt,
                    capacity_receipt_sha256,
                    capacity_public_key,
                    capacity_public_key_sha256,
                )
            ):
                _fail("unexpected_capacity_receipt")
        else:
            expected_runtime_count = len(members) + sum(verifier_modes[member] == "separate" for member in members)
            cleanup, cleanup_artifacts, nonces = split._validate_vmvm_cleanup(
                run_dir,
                identity_sha256,
                invocation_sha256,
                expected_runtime_count,
                held,
            )
            artifacts.update(cleanup_artifacts)
            if any(
                value is None
                for value in (
                    capacity_receipt,
                    capacity_receipt_sha256,
                    capacity_public_key,
                    capacity_public_key_sha256,
                )
            ):
                _fail("capacity_receipt_required")
            assert capacity_receipt is not None
            assert capacity_receipt_sha256 is not None
            assert capacity_public_key is not None
            assert capacity_public_key_sha256 is not None
            manifest_record = plan["source"]["manifest"]
            capacity, capacity_artifacts = split._capacity_payload(
                capacity_receipt,
                capacity_receipt_sha256,
                capacity_public_key,
                capacity_public_key_sha256,
                manifest_sha256=manifest_record["sha256"],
                selector_sha256=plan["lanes"][role]["selector"]["sha256"],
                identity=identity,
                identity_sha256=identity_sha256,
                invocation_identity_sha256=invocation_sha256,
                runtime_instance_nonces=nonces,
                held=held,
            )
            artifacts.update(capacity_artifacts)
            capacity_summary = {
                "provider": capacity["provider"],
                "resource_multiplier": capacity["resource_multiplier"],
                "measurement_method": capacity["measurement_method"],
                "measured_capacity": capacity["measured_capacity"],
                "invocation_identity_sha256": capacity["invocation_identity_sha256"],
                "public_key_sha256": capacity_public_key_sha256,
                "receipt_sha256": capacity_receipt_sha256,
            }
        certificate = {
            "schema_version": 1,
            "kind": LANE_CERTIFICATE_KIND,
            "state": "passed",
            "adapter": union.CERTIFIER_ADAPTER,
            "role": role,
            "sandbox_provider": provider,
            "task_count": len(members),
            "rollouts_per_task": 1,
            "launch_plan_sha256": launch_plan_sha256,
            "manifest_sha256": plan["source"]["manifest"]["sha256"],
            "partition_receipt_sha256": plan["source"]["partition_receipt"]["sha256"],
            "selector_sha256": plan["lanes"][role]["selector"]["sha256"],
            "eval_run_identity_sha256": identity_sha256,
            "invocation_identity_sha256": invocation_sha256,
            "run_dir": str(run_dir),
            "implementation_sha256": _self_sha256(),
            "source_revision": expected_revision,
            "worker_manifest_sha256": identity["deployment"]["worker_manifest"]["sha256"],
            "shared_contract": contracts["shared"],
            "deployment_contract": contracts["deployment"],
            "routing_contract": contracts["routing"],
            "trace_audit": trace_audit,
            "tool_execution": tool_execution,
            "cleanup": cleanup,
            "capacity": capacity_summary,
            "artifacts": artifacts,
        }
        split._revalidate_artifacts(artifacts)
        evidence.revalidate()
        held.revalidate()
        if publish_output is not None:
            split._write_private_once(publish_output, certificate)
            evidence.revalidate()
            held.revalidate()
        return certificate, rows


def certify_lane(**kwargs: Any) -> dict[str, Any]:
    certificate, _rows = _build_lane_certificate(**kwargs)
    return certificate


def _load_lane_certificate(
    *,
    path: Path,
    expected_sha256: str,
    expected_role: str,
    launch_plan: Path,
    launch_plan_sha256: str,
    expected_revision: str,
) -> tuple[dict[str, Any], bytes, dict[str, dict[str, Any]]]:
    try:
        value, body = split._load_bound_certificate(path, expected_sha256)
    except Exception as error:
        _fail("lane_certificate_invalid", error)
    if (
        value.get("kind") != LANE_CERTIFICATE_KIND
        or value.get("role") != expected_role
        or value.get("implementation_sha256") != _self_sha256()
        or value.get("launch_plan_sha256") != launch_plan_sha256
    ):
        _fail("lane_certificate_invalid")
    artifacts = value.get("artifacts")
    capacity_receipt = capacity_public_key = None
    capacity_receipt_sha256 = capacity_public_key_sha256 = None
    if expected_role == union.VMVM_ROLE:
        if not isinstance(artifacts, dict):
            _fail("lane_certificate_invalid")
        try:
            capacity_receipt = Path(artifacts["capacity_receipt"]["path"])
            capacity_receipt_sha256 = artifacts["capacity_receipt"]["sha256"]
            capacity_public_key = Path(artifacts["capacity_public_key"]["path"])
            capacity_public_key_sha256 = artifacts["capacity_public_key"]["sha256"]
        except (KeyError, TypeError) as error:
            _fail("lane_certificate_invalid", error)
    expected, rows = _build_lane_certificate(
        role=expected_role,
        run_dir=Path(str(value.get("run_dir", ""))),
        launch_plan=launch_plan,
        launch_plan_sha256=launch_plan_sha256,
        expected_revision=expected_revision,
        capacity_receipt=capacity_receipt,
        capacity_receipt_sha256=capacity_receipt_sha256,
        capacity_public_key=capacity_public_key,
        capacity_public_key_sha256=capacity_public_key_sha256,
    )
    if body != _canonical(expected):
        _fail("lane_certificate_evidence_mismatch")
    return value, body, rows


def _unsupported_row(task_id: str, manifest_sha256: str) -> dict[str, Any]:
    # This row is written only to the owner-only merged results artifact.
    return split._gpu_unsupported_row(task_id, manifest_sha256)


def _merge_rows(
    entries: Sequence[split.ManifestEntry],
    sandoq_rows: Mapping[str, dict[str, Any]],
    vmvm_rows: Mapping[str, dict[str, Any]],
    manifest_sha256: str,
) -> tuple[bytes, int]:
    partition = union.derive_union_partition(entries)
    if set(sandoq_rows) != set(partition.sandoq_firecracker) or set(vmvm_rows) != set(partition.vmvm_cpu):
        _fail("provider_coverage_invalid")
    merged: list[dict[str, Any]] = []
    passes = 0
    trace_ids: set[str] = set()
    gpu = set(partition.gpu_unsupported)
    for entry in entries:
        if entry.task_id in sandoq_rows:
            row = sandoq_rows[entry.task_id]
            passes += split._score(row)
        elif entry.task_id in vmvm_rows:
            row = vmvm_rows[entry.task_id]
            passes += split._score(row)
        elif entry.task_id in gpu:
            row = _unsupported_row(entry.task_id, manifest_sha256)
        else:
            _fail("provider_coverage_invalid")
        trace_id = row.get("id")
        if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
            _fail("merged_trace_id_invalid")
        trace_ids.add(trace_id)
        merged.append(row)
    if len(merged) != split.TOTAL_TASKS:
        _fail("provider_coverage_invalid")
    return b"".join(_canonical(row) for row in merged), passes


def _derived_union_fields(
    *,
    plan: Mapping[str, Any],
    sandoq: Mapping[str, Any],
    vmvm: Mapping[str, Any],
    passes: int,
    results_body: bytes,
) -> dict[str, Any]:
    cpu_pass_rate = passes / union.CPU_TASKS
    if passes < MIN_CPU_PASSES or not MIN_CPU_PASS_RATE <= cpu_pass_rate <= MAX_CPU_PASS_RATE:
        _fail("tb4_score_outside_expected_range")
    policy = {
        "expected_tasks": split.TOTAL_TASKS,
        "expected_supported_tasks": union.CPU_TASKS,
        "rollouts_per_task": 1,
        "max_sequence_tokens": split.MAX_SEQUENCE_TOKENS,
        "min_supported_pass_rate": MIN_CPU_PASS_RATE,
        "max_supported_pass_rate": MAX_CPU_PASS_RATE,
        "provider_partition": {
            union.SANDOQ_ROLE: union.SANDOQ_TASKS,
            union.VMVM_ROLE: union.VMVM_TASKS,
            union.GPU_ROLE: union.GPU_TASKS,
        },
        "harness": {"id": "mini-swe-agent", "version": union.MINISWE_VERSION},
        "tool_exit_evidence_required": True,
    }
    timeout_contract = _plan_timeout_contract(dict(plan))
    if timeout_contract is not None:
        policy["timeouts"] = timeout_contract
    return {
        "manifest_sha256": plan["source"]["manifest"]["sha256"],
        "results_sha256": _sha256(results_body),
        "deployment": {
            "endpoint_bundle_sha256": sandoq["shared_contract"]["deployment_contract"]["endpoint_bundle_sha256"],
            "source_spec_sha256": sandoq["shared_contract"]["deployment_contract"]["spec_sha256"],
            "worker_generation_sha256": sandoq["shared_contract"]["deployment_contract"]["worker_generation_sha256"],
        },
        "counts": {
            "observed_traces": split.TOTAL_TASKS,
            "supported_tasks": union.CPU_TASKS,
            "cpu_unsupported_tasks": union.GPU_TASKS,
            "supported_passes": passes,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "scores": {
            "supported_pass_rate": cpu_pass_rate,
            "all_task_pass_rate": passes / split.TOTAL_TASKS,
        },
        "policy": policy,
        "providers": {
            union.SANDOQ_ROLE: {
                "state": "passed",
                "task_count": union.SANDOQ_TASKS,
                "passes": sandoq["trace_audit"]["passes"],
                "cleanup_state": sandoq["cleanup"]["state"],
                "provider_profile_sha256": union.PROVIDER_PROFILE_SHA256,
                "runtime_tunnel_receipt_sha256": union.FULL_TUNNEL_RECEIPT_SHA256,
                "runtime_resource_receipt_sha256": union.FULL_RESOURCE_RECEIPT_SHA256,
            },
            union.VMVM_ROLE: {
                "state": "passed",
                "task_count": union.VMVM_TASKS,
                "passes": vmvm["trace_audit"]["passes"],
                "cleanup_state": vmvm["cleanup"]["state"],
                "capacity": vmvm["capacity"],
            },
        },
        "trace_audit": {
            "cpu_traces": union.CPU_TASKS,
            "unsupported_gpu_outcomes": union.GPU_TASKS,
            "total_traces": split.TOTAL_TASKS,
            "model_io_turns": sandoq["trace_audit"]["model_io_turns"] + vmvm["trace_audit"]["model_io_turns"],
            "sampled_tokens": sandoq["trace_audit"]["sampled_tokens"] + vmvm["trace_audit"]["sampled_tokens"],
            "tool_observations": sandoq["tool_execution"]["tool_observations"]
            + vmvm["tool_execution"]["tool_observations"],
            "successful_tool_exits": sandoq["tool_execution"]["successful_tool_exits"]
            + vmvm["tool_execution"]["successful_tool_exits"],
            "nonzero_tool_exits": sandoq["tool_execution"]["nonzero_tool_exits"]
            + vmvm["tool_execution"]["nonzero_tool_exits"],
            "missing_tool_exits": 0,
            "trace_failures": 0,
            "reasoning_required": True,
            "request_graph_match_required": True,
            "exact_provider_json_required": True,
        },
    }


def merge_certified_lanes(
    *,
    launch_plan: Path,
    launch_plan_sha256: str,
    sandoq_certificate: Path,
    sandoq_certificate_sha256: str,
    vmvm_certificate: Path,
    vmvm_certificate_sha256: str,
    output: Path,
    expected_revision: str,
) -> dict[str, Any]:
    if REVISION_RE.fullmatch(expected_revision) is None:
        _fail("source_revision_invalid")
    for path in (launch_plan, sandoq_certificate, vmvm_certificate):
        try:
            canonical = path.resolve(strict=True)
        except OSError as error:
            _fail("union_path_invalid", error)
        if not path.is_absolute() or canonical != path or path.is_symlink():
            _fail("union_path_invalid")
    try:
        output_parent = output.parent.resolve(strict=True)
    except OSError as error:
        _fail("union_path_invalid", error)
    if (
        not output.is_absolute()
        or output != Path(os.path.normpath(output))
        or output_parent != output.parent
        or output.exists()
        or output.is_symlink()
    ):
        _fail("union_path_invalid")
    plan, _plan_body, entries = _load_plan(launch_plan, launch_plan_sha256)
    sandoq, sandoq_body, sandoq_rows = _load_lane_certificate(
        path=sandoq_certificate,
        expected_sha256=sandoq_certificate_sha256,
        expected_role=union.SANDOQ_ROLE,
        launch_plan=launch_plan,
        launch_plan_sha256=launch_plan_sha256,
        expected_revision=expected_revision,
    )
    vmvm, vmvm_body, vmvm_rows = _load_lane_certificate(
        path=vmvm_certificate,
        expected_sha256=vmvm_certificate_sha256,
        expected_role=union.VMVM_ROLE,
        launch_plan=launch_plan,
        launch_plan_sha256=launch_plan_sha256,
        expected_revision=expected_revision,
    )
    if (
        sandoq["shared_contract"] != vmvm["shared_contract"]
        or sandoq["worker_manifest_sha256"] != vmvm["worker_manifest_sha256"]
        or sandoq["deployment_contract"] != vmvm["deployment_contract"]
        or sandoq["routing_contract"] != vmvm["routing_contract"]
        or sandoq["eval_run_identity_sha256"] == vmvm["eval_run_identity_sha256"]
        or sandoq["sandbox_provider"] != "sandoq"
        or vmvm["sandbox_provider"] != "vmvm"
        or vmvm.get("capacity", {}).get("provider") != "vmvm"
        or any(
            sandoq["artifacts"][name]["sha256"] != vmvm["artifacts"][name]["sha256"]
            for name in ("smoke_checkpoint", "capacity_certificate", "capacity_gate_receipt", "endpoint_load_gate")
        )
    ):
        _fail("provider_union_mismatch")
    manifest_sha256 = plan["source"]["manifest"]["sha256"]
    results_body, passes = _merge_rows(entries, sandoq_rows, vmvm_rows, manifest_sha256)
    cpu_pass_rate = passes / union.CPU_TASKS
    if passes < MIN_CPU_PASSES or not MIN_CPU_PASS_RATE <= cpu_pass_rate <= MAX_CPU_PASS_RATE:
        _fail("tb4_score_outside_expected_range")
    results_path = output / MERGED_RESULTS
    artifacts = {
        "results": {"path": str(results_path), "bytes": len(results_body), "sha256": _sha256(results_body)},
        "sandoq_lane_certificate": {
            "path": str(sandoq_certificate),
            "bytes": len(sandoq_body),
            "sha256": sandoq_certificate_sha256,
        },
        "vmvm_lane_certificate": {
            "path": str(vmvm_certificate),
            "bytes": len(vmvm_body),
            "sha256": vmvm_certificate_sha256,
        },
        "launch_plan": {
            "path": str(launch_plan),
            "bytes": launch_plan.stat().st_size,
            "sha256": launch_plan_sha256,
        },
        "partition_receipt": dict(plan["source"]["partition_receipt"]),
    }
    policy = {
        "expected_tasks": split.TOTAL_TASKS,
        "expected_supported_tasks": union.CPU_TASKS,
        "rollouts_per_task": 1,
        "max_sequence_tokens": split.MAX_SEQUENCE_TOKENS,
        "min_supported_pass_rate": MIN_CPU_PASS_RATE,
        "max_supported_pass_rate": MAX_CPU_PASS_RATE,
        "provider_partition": {
            union.SANDOQ_ROLE: union.SANDOQ_TASKS,
            union.VMVM_ROLE: union.VMVM_TASKS,
            union.GPU_ROLE: union.GPU_TASKS,
        },
        "harness": {"id": "mini-swe-agent", "version": union.MINISWE_VERSION},
        "tool_exit_evidence_required": True,
    }
    timeout_contract = _plan_timeout_contract(plan)
    if timeout_contract is not None:
        policy["timeouts"] = timeout_contract
    value: dict[str, Any] = {
        "schema_version": UNION_CERTIFICATE_SCHEMA_VERSION,
        "kind": UNION_CERTIFICATE_KIND,
        "state": "passed",
        "model": "Kimi-K3",
        "adapter": union.CERTIFIER_ADAPTER,
        "source_revision": expected_revision,
        "launch_plan_sha256": launch_plan_sha256,
        "manifest_sha256": manifest_sha256,
        "results_sha256": _sha256(results_body),
        "deployment": {
            "endpoint_bundle_sha256": sandoq["shared_contract"]["deployment_contract"]["endpoint_bundle_sha256"],
            "source_spec_sha256": sandoq["shared_contract"]["deployment_contract"]["spec_sha256"],
            "worker_generation_sha256": sandoq["shared_contract"]["deployment_contract"]["worker_generation_sha256"],
        },
        "counts": {
            "observed_traces": split.TOTAL_TASKS,
            "supported_tasks": union.CPU_TASKS,
            "cpu_unsupported_tasks": union.GPU_TASKS,
            "supported_passes": passes,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "scores": {
            "supported_pass_rate": cpu_pass_rate,
            "all_task_pass_rate": passes / split.TOTAL_TASKS,
        },
        "policy": policy,
        "providers": {
            union.SANDOQ_ROLE: {
                "state": "passed",
                "task_count": union.SANDOQ_TASKS,
                "passes": sandoq["trace_audit"]["passes"],
                "cleanup_state": sandoq["cleanup"]["state"],
                "provider_profile_sha256": union.PROVIDER_PROFILE_SHA256,
                "runtime_tunnel_receipt_sha256": union.FULL_TUNNEL_RECEIPT_SHA256,
                "runtime_resource_receipt_sha256": union.FULL_RESOURCE_RECEIPT_SHA256,
            },
            union.VMVM_ROLE: {
                "state": "passed",
                "task_count": union.VMVM_TASKS,
                "passes": vmvm["trace_audit"]["passes"],
                "cleanup_state": vmvm["cleanup"]["state"],
                "capacity": vmvm["capacity"],
            },
        },
        "trace_audit": {
            "cpu_traces": union.CPU_TASKS,
            "unsupported_gpu_outcomes": union.GPU_TASKS,
            "total_traces": split.TOTAL_TASKS,
            "model_io_turns": sandoq["trace_audit"]["model_io_turns"] + vmvm["trace_audit"]["model_io_turns"],
            "sampled_tokens": sandoq["trace_audit"]["sampled_tokens"] + vmvm["trace_audit"]["sampled_tokens"],
            "tool_observations": sandoq["tool_execution"]["tool_observations"]
            + vmvm["tool_execution"]["tool_observations"],
            "successful_tool_exits": sandoq["tool_execution"]["successful_tool_exits"]
            + vmvm["tool_execution"]["successful_tool_exits"],
            "nonzero_tool_exits": sandoq["tool_execution"]["nonzero_tool_exits"]
            + vmvm["tool_execution"]["nonzero_tool_exits"],
            "missing_tool_exits": 0,
            "trace_failures": 0,
            "reasoning_required": True,
            "request_graph_match_required": True,
            "exact_provider_json_required": True,
        },
        "artifacts": artifacts,
        "implementation_sha256": _self_sha256(),
    }
    value["tb4_certificate_sha256"] = _sha256(_canonical(value))
    split._publish_private_bundle(
        output,
        {MERGED_RESULTS: results_body, UNION_CERTIFICATE: _canonical(value)},
    )
    return {
        "state": "passed",
        "supported_passes": passes,
        "supported_tasks": union.CPU_TASKS,
        "all_tasks": split.TOTAL_TASKS,
        "certificate_sha256": _sha256(_canonical(value)),
    }


def validate_union_certificate(path: Path, expected_sha256: str) -> dict[str, Any]:
    body = split.read_regular(path, code="union_certificate_invalid", private=True)
    if SHA256_RE.fullmatch(expected_sha256 or "") is None or _sha256(body) != expected_sha256:
        _fail("union_certificate_invalid")
    try:
        value = json.loads(body)
        from kimi_sandoq_production import Artifact, _validate_tb4_miniswe_union_certificate

        validated, _artifact = _validate_tb4_miniswe_union_certificate(
            value,
            Artifact(str(path.resolve(strict=True)), len(body), expected_sha256),
        )
        artifacts = validated["artifacts"]
        plan_path = Path(artifacts["launch_plan"]["path"])
        plan_sha256 = artifacts["launch_plan"]["sha256"]
        plan, _plan_body, entries = _load_plan(plan_path, plan_sha256)
        source_revision = validated["source_revision"]
        sandoq, _sandoq_body, sandoq_rows = _load_lane_certificate(
            path=Path(artifacts["sandoq_lane_certificate"]["path"]),
            expected_sha256=artifacts["sandoq_lane_certificate"]["sha256"],
            expected_role=union.SANDOQ_ROLE,
            launch_plan=plan_path,
            launch_plan_sha256=plan_sha256,
            expected_revision=source_revision,
        )
        vmvm, _vmvm_body, vmvm_rows = _load_lane_certificate(
            path=Path(artifacts["vmvm_lane_certificate"]["path"]),
            expected_sha256=artifacts["vmvm_lane_certificate"]["sha256"],
            expected_role=union.VMVM_ROLE,
            launch_plan=plan_path,
            launch_plan_sha256=plan_sha256,
            expected_revision=source_revision,
        )
        results_body, passes = _merge_rows(
            entries,
            sandoq_rows,
            vmvm_rows,
            plan["source"]["manifest"]["sha256"],
        )
        observed_results = split.read_regular(
            Path(artifacts["results"]["path"]),
            code="union_results_invalid",
            maximum_bytes=512 * 1024 * 1024,
            private=True,
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        _fail("union_certificate_invalid", error)
    expected_derived = _derived_union_fields(
        plan=plan,
        sandoq=sandoq,
        vmvm=vmvm,
        passes=passes,
        results_body=results_body,
    )
    if (
        observed_results != results_body
        or artifacts["results"]["sha256"] != _sha256(results_body)
        or sandoq["shared_contract"] != vmvm["shared_contract"]
        or sandoq["worker_manifest_sha256"] != vmvm["worker_manifest_sha256"]
        or sandoq["deployment_contract"] != vmvm["deployment_contract"]
        or sandoq["routing_contract"] != vmvm["routing_contract"]
        or sandoq["eval_run_identity_sha256"] == vmvm["eval_run_identity_sha256"]
        or any(
            sandoq["artifacts"][name]["sha256"] != vmvm["artifacts"][name]["sha256"]
            for name in ("smoke_checkpoint", "capacity_certificate", "capacity_gate_receipt", "endpoint_load_gate")
        )
        or validated.get("launch_plan_sha256") != plan_sha256
        or artifacts.get("partition_receipt") != plan["source"]["partition_receipt"]
        or validated.get("implementation_sha256") != _self_sha256()
        or any(validated.get(key) != expected for key, expected in expected_derived.items())
    ):
        _fail("union_certificate_invalid")
    return validated


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    certify = commands.add_parser("certify-lane")
    certify.add_argument("--role", choices=(union.SANDOQ_ROLE, union.VMVM_ROLE), required=True)
    certify.add_argument("--run-dir", type=Path, required=True)
    certify.add_argument("--launch-plan", type=Path, required=True)
    certify.add_argument("--launch-plan-sha256", required=True)
    certify.add_argument("--expected-revision", required=True)
    certify.add_argument("--output", type=Path, required=True)
    certify.add_argument("--capacity-receipt", type=Path)
    certify.add_argument("--capacity-receipt-sha256")
    certify.add_argument("--capacity-public-key", type=Path)
    certify.add_argument("--capacity-public-key-sha256")
    merge = commands.add_parser("merge")
    merge.add_argument("--launch-plan", type=Path, required=True)
    merge.add_argument("--launch-plan-sha256", required=True)
    merge.add_argument("--expected-revision", required=True)
    merge.add_argument("--sandoq-certificate", type=Path, required=True)
    merge.add_argument("--sandoq-certificate-sha256", required=True)
    merge.add_argument("--vmvm-certificate", type=Path, required=True)
    merge.add_argument("--vmvm-certificate-sha256", required=True)
    merge.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "certify-lane":
            value = certify_lane(
                role=args.role,
                run_dir=args.run_dir,
                launch_plan=args.launch_plan,
                launch_plan_sha256=args.launch_plan_sha256,
                expected_revision=args.expected_revision,
                capacity_receipt=args.capacity_receipt,
                capacity_receipt_sha256=args.capacity_receipt_sha256,
                capacity_public_key=args.capacity_public_key,
                capacity_public_key_sha256=args.capacity_public_key_sha256,
                publish_output=args.output,
            )
            summary = {"state": "passed", "task_count": value["task_count"], "passes": value["trace_audit"]["passes"]}
        else:
            summary = merge_certified_lanes(
                launch_plan=args.launch_plan,
                launch_plan_sha256=args.launch_plan_sha256,
                sandoq_certificate=args.sandoq_certificate,
                sandoq_certificate_sha256=args.sandoq_certificate_sha256,
                vmvm_certificate=args.vmvm_certificate,
                vmvm_certificate_sha256=args.vmvm_certificate_sha256,
                output=args.output,
                expected_revision=args.expected_revision,
            )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        print("kimi_tb4_miniswe246_union_certification_failed", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
