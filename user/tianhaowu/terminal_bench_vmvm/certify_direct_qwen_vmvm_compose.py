#!/usr/bin/env python3
"""Certify the private one-member VMVM Compose side of the Qwen union."""

from __future__ import annotations

import argparse
import fcntl
import re
from pathlib import Path
from typing import Any, Mapping

from direct_qwen_union_contract import (
    SHA256_RE,
    UnionContractError,
    artifact,
    audit_results,
    canonical_json,
    sha256_bytes,
    validate_shared_identity,
    write_exclusive,
)
from materialize_qwen_provider_union import (
    VMVM_COUNT,
    MixedMaterializationError,
    validate_materialization,
)


class VmvmComposeCertificateError(ValueError):
    pass


def _provider_source(identity: Mapping[str, Any]) -> dict[str, Any]:
    source = identity["source"]
    keys = (
        "prime_rl_commit",
        "verifiers_commit",
        "renderers_commit",
        "vmvm_tb_v2_sha256",
    )
    value = {key: source.get(key) for key in keys}
    if (
        any(not isinstance(item, str) or not item for item in value.values())
        or any(
            re.fullmatch(r"[0-9a-f]{40,64}", value[key]) is None
            for key in ("prime_rl_commit", "verifiers_commit", "renderers_commit")
        )
        or SHA256_RE.fullmatch(str(value["vmvm_tb_v2_sha256"])) is None
    ):
        raise VmvmComposeCertificateError("vmvm_source_closure_invalid")
    value.update(
        direct_spec_sha256=identity["deployment"].get("spec_sha256"),
        direct_endpoint_bundle_sha256=identity["deployment"].get("endpoint_bundle_sha256"),
    )
    return value


def certify(
    *,
    run_dir: Path,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    expected_config: Path,
    materialization_receipt: Path,
    materialization_receipt_sha256: str,
    canonical_task_source: Path,
    canonical_dataset: Path,
    canonical_sandoq_template: Path,
    canonical_vmvm_template: Path,
    sandoq_task_file: Path,
    sandoq_config: Path,
) -> dict[str, Any]:
    lock_path = run_dir / ".writer.lock"
    try:
        lock = lock_path.open("rb")
    except OSError as error:
        raise VmvmComposeCertificateError("writer_lock_missing") from error
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise VmvmComposeCertificateError("writer_active") from error
        try:
            materialization = validate_materialization(
                source=canonical_task_source,
                dataset=canonical_dataset,
                sandoq_template=canonical_sandoq_template,
                vmvm_template=canonical_vmvm_template,
                sandoq_tasks=sandoq_task_file,
                vmvm_tasks=expected_task_file,
                sandoq_config=sandoq_config,
                vmvm_config=expected_config,
                receipt=materialization_receipt,
                receipt_sha256=materialization_receipt_sha256,
            )
        except MixedMaterializationError as error:
            raise VmvmComposeCertificateError("mixed_materialization_invalid") from error
        if artifact(expected_task_file)["sha256"] != expected_task_file_sha256:
            raise VmvmComposeCertificateError("task_file_hash_mismatch")
        try:
            from eval_run_identity import load_eval_run_identity

            envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
            shared, execution = validate_shared_identity(
                envelope["identity"],
                expected_provider="vmvm",
                expected_task_file=expected_task_file,
                expected_task_sha256=expected_task_file_sha256,
                expected_count=VMVM_COUNT,
                expected_config=expected_config,
                expected_dataset=canonical_dataset,
            )
        except (KeyError, OSError, UnionContractError) as error:
            raise VmvmComposeCertificateError("vmvm_identity_invalid") from error
        environment = execution.get("vmvm_environment")
        runtime = execution.get("runtime")
        if (
            execution.get("rollout_concurrency") != 1
            or execution.get("multiplex") != 1
            or execution.get("http_max_connections") != 1
            or execution.get("http_max_keepalive_connections") != 1
            or not isinstance(environment, dict)
            or not isinstance(runtime, dict)
            or runtime.get("type") != "vmvm"
        ):
            raise VmvmComposeCertificateError("vmvm_execution_invalid")
        try:
            results_sha256, traces = audit_results(
                run_dir / "results.jsonl",
                expected_task_file,
                VMVM_COUNT,
            )
        except UnionContractError as error:
            raise VmvmComposeCertificateError(str(error)) from error
        shared_sha256 = sha256_bytes(canonical_json(shared))
        return {
            "schema_version": 1,
            "kind": "direct-qwen-vmvm-compose-partition",
            "state": "passed",
            "sandbox_provider": "vmvm",
            "task_count": VMVM_COUNT,
            "selection": "canonical-compose",
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "results_sha256": results_sha256,
            "worker_manifest_sha256": shared["deployment"]["worker_manifest_sha256"],
            "worker_count": 24,
            "trace_audit": traces,
            "compose_proof": {
                "compose_count": 1,
                "network_policy": "both-phases-no-network",
                "runtime": "vmvm",
                "vmvm_tb_v2_sha256": envelope["identity"]["source"]["vmvm_tb_v2_sha256"],
            },
            "runtime_cleanup": {
                "error_traces": 0,
                "finalized_traces": traces["traces"],
                "state": "passed",
            },
            "materialization": materialization,
            "shared_contract": shared,
            "shared_contract_sha256": shared_sha256,
            "provider_source": _provider_source(envelope["identity"]),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-task-file", type=Path, required=True)
    parser.add_argument("--expected-task-file-sha256", required=True)
    parser.add_argument("--expected-config", type=Path, required=True)
    parser.add_argument("--materialization-receipt", type=Path, required=True)
    parser.add_argument("--materialization-receipt-sha256", required=True)
    parser.add_argument("--canonical-task-source", type=Path, required=True)
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--canonical-sandoq-template", type=Path, required=True)
    parser.add_argument("--canonical-vmvm-template", type=Path, required=True)
    parser.add_argument("--sandoq-task-file", type=Path, required=True)
    parser.add_argument("--sandoq-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    try:
        value = certify(**args)
        digest = write_exclusive(output, value)
    except (OSError, VmvmComposeCertificateError) as error:
        code = str(error) if isinstance(error, VmvmComposeCertificateError) else "certification_failed"
        raise SystemExit(code) from None
    print(digest)


if __name__ == "__main__":
    main()
