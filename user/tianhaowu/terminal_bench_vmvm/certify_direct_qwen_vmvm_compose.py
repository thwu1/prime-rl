#!/usr/bin/env python3
"""Certify the private one-member VMVM Compose side of the Qwen union."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
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


_CLEANUP_RECEIPT_KEYS = {
    "schema_version",
    "kind",
    "runtime_instance_nonce",
    "cleanup_pass",
    "state",
    "attempted",
    "failures",
    "host_tunnel_count",
    "host_tunnels_closed",
    "network_firewall_present",
    "network_firewall_cleanup_completed",
    "session_present",
    "session_stop_completed",
    "fifo_present",
    "fifo_cleanup_completed",
    "compose_present",
    "compose_teardown_completed",
    "compose_directory_cleanup_completed",
    "container_present",
    "container_teardown_completed",
    "internal_network_present",
    "internal_network_teardown_completed",
    "ssh_master_stop_completed",
    "lease_process_was_alive",
    "lease_sigterm_sent",
    "lease_wait_completed",
    "lease_exit_code",
    "lease_sigkill_used",
    "release_on_exit_completed",
    "remote_deletion_verified",
    "eval_run_identity_sha256",
}
_LIFECYCLE_RECEIPT_KEYS = {
    "schema_version",
    "kind",
    "runtime_instance_nonce",
    "eval_run_identity_sha256",
}


def _integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _verifier_mode_from_results(results: Path) -> str:
    try:
        from audit_traces import _iter_traces

        traces = list(_iter_traces(results))
    except Exception as error:
        raise VmvmComposeCertificateError("vmvm_runtime_accounting_invalid") from error
    if len(traces) != VMVM_COUNT:
        raise VmvmComposeCertificateError("vmvm_runtime_accounting_invalid")
    trace = traces[0]
    info = trace.get("info")
    verifier = info.get("terminal_bench_verifier") if isinstance(info, dict) else None
    mode = verifier.get("mode") if isinstance(verifier, dict) else None
    attempts = verifier.get("attempts") if isinstance(verifier, dict) else None
    failures = verifier.get("infrastructure_failures") if isinstance(verifier, dict) else None
    if (
        mode not in {"shared", "separate"}
        or not _integer(attempts, minimum=1)
        or not isinstance(failures, list)
        or len(failures) != attempts - 1
        or any(not isinstance(item, str) or not item for item in failures)
    ):
        raise VmvmComposeCertificateError("vmvm_runtime_accounting_invalid")
    return mode


def _read_private_jsonl(
    path: Path,
    *,
    run_dir: Path,
    filename: str,
    code: str,
) -> list[dict[str, Any]]:
    expected = run_dir.resolve(strict=True) / "control" / filename
    if path != expected or path.is_symlink():
        raise VmvmComposeCertificateError(code)
    try:
        root_metadata = run_dir.lstat()
        parent_metadata = path.parent.lstat()
        file_metadata = path.lstat()
    except OSError as error:
        raise VmvmComposeCertificateError(code) from error
    if (
        run_dir != run_dir.resolve(strict=True)
        or run_dir.is_symlink()
        or path.parent != path.parent.resolve(strict=True)
        or path.parent.is_symlink()
        or not stat.S_ISDIR(root_metadata.st_mode)
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or not stat.S_ISREG(file_metadata.st_mode)
        or root_metadata.st_uid != os.getuid()
        or parent_metadata.st_uid != os.getuid()
        or file_metadata.st_uid != os.getuid()
        or stat.S_IMODE(root_metadata.st_mode) & 0o077
        or stat.S_IMODE(parent_metadata.st_mode) & 0o077
        or stat.S_IMODE(file_metadata.st_mode) != 0o600
        or file_metadata.st_nlink != 1
        or file_metadata.st_size > 1 << 20
    ):
        raise VmvmComposeCertificateError(code)
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            raw = bytearray()
            while chunk := os.read(descriptor, 1 << 16):
                raw.extend(chunk)
                if len(raw) > 1 << 20:
                    raise VmvmComposeCertificateError(code)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise VmvmComposeCertificateError(code) from error
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after) or identity(after) != identity(file_metadata):
        raise VmvmComposeCertificateError(f"{code}_changed")
    body = bytes(raw)
    if not body or not body.endswith(b"\n") or b"\r" in body:
        raise VmvmComposeCertificateError(code)
    values: list[dict[str, Any]] = []
    for line in body.splitlines():
        if not line:
            raise VmvmComposeCertificateError(code)
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VmvmComposeCertificateError(code) from error
        if not isinstance(value, dict):
            raise VmvmComposeCertificateError(code)
        values.append(value)
    return values


def _read_private_lifecycle_receipts(
    path: Path,
    *,
    run_dir: Path,
    expected_identity_sha256: str,
) -> frozenset[str]:
    values = _read_private_jsonl(
        path,
        run_dir=run_dir,
        filename="vmvm_runtime_lifecycle.jsonl",
        code="vmvm_lifecycle_receipt_invalid",
    )
    nonces: list[str] = []
    for value in values:
        nonce = value.get("runtime_instance_nonce")
        if (
            set(value) != _LIFECYCLE_RECEIPT_KEYS
            or value.get("schema_version") != 1
            or value.get("kind") != "vmvm-runtime-created"
            or re.fullmatch(r"[0-9a-f]{32}", str(nonce)) is None
            or value.get("eval_run_identity_sha256") != expected_identity_sha256
        ):
            raise VmvmComposeCertificateError("vmvm_lifecycle_receipt_invalid")
        nonces.append(str(nonce))
    if len(nonces) != len(set(nonces)):
        raise VmvmComposeCertificateError("vmvm_lifecycle_receipt_invalid")
    return frozenset(nonces)


def _read_private_cleanup_receipts(
    path: Path,
    *,
    run_dir: Path,
    expected_identity_sha256: str,
    expected_runtime_nonces: frozenset[str],
    verifier_mode: str,
) -> dict[str, Any]:
    records = _read_private_jsonl(
        path,
        run_dir=run_dir,
        filename="vmvm_cleanup_receipts.jsonl",
        code="vmvm_cleanup_receipt_invalid",
    )
    for value in records:
        if set(value) != _CLEANUP_RECEIPT_KEYS:
            raise VmvmComposeCertificateError("vmvm_cleanup_receipt_invalid")
        boolean_keys = {
            "network_firewall_present",
            "network_firewall_cleanup_completed",
            "session_present",
            "session_stop_completed",
            "fifo_present",
            "fifo_cleanup_completed",
            "compose_present",
            "compose_teardown_completed",
            "compose_directory_cleanup_completed",
            "container_present",
            "container_teardown_completed",
            "internal_network_present",
            "internal_network_teardown_completed",
            "ssh_master_stop_completed",
            "lease_process_was_alive",
            "lease_sigterm_sent",
            "lease_wait_completed",
            "lease_sigkill_used",
            "release_on_exit_completed",
            "remote_deletion_verified",
        }
        if (
            not _integer(value.get("schema_version"), minimum=1)
            or value.get("schema_version") != 1
            or value.get("kind") != "vmvm-runtime-cleanup"
            or re.fullmatch(r"[0-9a-f]{32}", str(value.get("runtime_instance_nonce", "")))
            is None
            or not _integer(value.get("cleanup_pass"), minimum=1)
            or value.get("state") != "passed"
            or value.get("eval_run_identity_sha256") != expected_identity_sha256
            or any(not isinstance(value.get(key), bool) for key in boolean_keys)
            or not _integer(value.get("attempted"), minimum=1)
            or value.get("attempted") != 1
            or not _integer(value.get("failures"))
            or value.get("failures") != 0
            or not _integer(value.get("host_tunnel_count"))
            or not _integer(value.get("host_tunnels_closed"))
            or value.get("host_tunnel_count") != 0
            or value.get("host_tunnels_closed") != 0
            or value.get("network_firewall_cleanup_completed") is not True
            or value.get("internal_network_teardown_completed") is not True
            or value.get("ssh_master_stop_completed") is not True
            or value.get("lease_process_was_alive") is not True
            or value.get("lease_sigterm_sent") is not True
            or value.get("lease_wait_completed") is not True
            or value.get("lease_sigkill_used") is not False
            or value.get("release_on_exit_completed") is not True
            or value.get("remote_deletion_verified") is not False
            or value.get("compose_teardown_completed") is not True
            or value.get("compose_directory_cleanup_completed") is not True
            or value.get("container_teardown_completed") is not True
            or value.get("session_stop_completed") is not True
            or value.get("fifo_cleanup_completed") is not True
            or not _integer(value.get("lease_exit_code"))
            or value.get("lease_exit_code") != 0
        ):
            raise VmvmComposeCertificateError("vmvm_cleanup_receipt_failed")
    by_runtime: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_runtime.setdefault(record["runtime_instance_nonce"], []).append(record)
    if frozenset(by_runtime) != expected_runtime_nonces or any(
        [record["cleanup_pass"] for record in runtime_records]
        != list(range(1, len(runtime_records) + 1))
        or not any(record["network_firewall_present"] for record in runtime_records)
        or not any(record["internal_network_present"] for record in runtime_records)
        or not any(
            record["session_present"] or record["fifo_present"]
            for record in runtime_records
        )
        for runtime_records in by_runtime.values()
    ):
        raise VmvmComposeCertificateError("vmvm_cleanup_receipt_count_invalid")
    compose_count = sum(
        any(record["compose_present"] is True for record in runtime_records)
        for runtime_records in by_runtime.values()
    )
    if compose_count != 1:
        raise VmvmComposeCertificateError("vmvm_cleanup_compose_count_invalid")
    return {
        "state": "passed",
        "runtime_instances": len(by_runtime),
        "cleanup_passes": len(records),
        "agent_runtime_instances": 1,
        "verifier_runtime_instances": len(by_runtime) - 1,
        "verifier_mode": verifier_mode,
        "compose_runtime_instances": compose_count,
        "local_cleanup_failures": 0,
        "release_on_exit_completed": len(by_runtime),
        "remote_deletion_verified": False,
    }


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
    private_output_root: Path,
    cleanup_receipt: Path,
    lifecycle_receipt: Path,
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
                private_output_root=private_output_root,
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
            or execution.get("cleanup_must_succeed") is not True
            or execution.get("cleanup_receipt_contract")
            != {
                "kind": "vacli-release-on-exit-v1",
                "receipt": "private-aggregate-jsonl",
                "release_on_exit_completed": True,
                "remote_deletion_verified": False,
            }
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
        verifier_mode = _verifier_mode_from_results(run_dir / "results.jsonl")
        runtime_nonces = _read_private_lifecycle_receipts(
            lifecycle_receipt,
            run_dir=run_dir,
            expected_identity_sha256=envelope["eval_run_identity_sha256"],
        )
        cleanup = _read_private_cleanup_receipts(
            cleanup_receipt,
            run_dir=run_dir,
            expected_identity_sha256=envelope["eval_run_identity_sha256"],
            expected_runtime_nonces=runtime_nonces,
            verifier_mode=verifier_mode,
        )
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
            "worker_manifest_sha256": envelope["identity"]["deployment"]["worker_manifest"]["sha256"],
            "worker_count": 24,
            "trace_audit": traces,
            "compose_proof": {
                "compose_count": 1,
                "network_policy": "both-phases-no-network",
                "runtime": "vmvm",
                "vmvm_tb_v2_sha256": envelope["identity"]["source"]["vmvm_tb_v2_sha256"],
            },
            "runtime_cleanup": cleanup,
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
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--cleanup-receipt", type=Path, required=True)
    parser.add_argument("--lifecycle-receipt", type=Path, required=True)
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
