#!/usr/bin/env python3
"""Publish a write-once, aggregate-only certificate for a trace smoke run."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audit_traces import (
    KIMI_K3_MAX_MODEL_IO_CONTRACT,
    _iter_traces,
    _read_expected_slugs,
    _summarize_traces,
)
from deployment_endpoint import (
    EndpointBindingError,
    load_deployment_endpoint,
    validate_endpoint_binding,
)
from eval_run_identity import load_eval_run_identity

SHA256_RE = re.compile(r"[0-9a-f]{64}")
SCHEMA_VERSION = 1
MAX_SEQUENCE_TOKENS = 262_144
EXPECTED_MODEL_IO_CONTRACT = {
    "provider_route": KIMI_K3_MAX_MODEL_IO_CONTRACT.provider_route,
    "request_model": KIMI_K3_MAX_MODEL_IO_CONTRACT.request_model,
    "response_model": KIMI_K3_MAX_MODEL_IO_CONTRACT.response_model,
    "request_reasoning_effort": KIMI_K3_MAX_MODEL_IO_CONTRACT.reasoning_effort,
    "request_chat_template_kwargs": dict(KIMI_K3_MAX_MODEL_IO_CONTRACT.chat_template_kwargs),
}


class SmokeCertificateError(ValueError):
    """The smoke run cannot be certified without weakening an invariant."""


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as cause:
        raise SmokeCertificateError(f"artifact_unreadable:{path.name}") from cause
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise SmokeCertificateError(f"artifact_changed:{path.name}")
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": _sha256_file(resolved)}


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as cause:
        raise SmokeCertificateError(f"{label}_invalid") from cause
    if not isinstance(value, dict):
        raise SmokeCertificateError(f"{label}_invalid")
    return value


def _validated_endpoint(identity: dict[str, Any]) -> dict[str, Any]:
    deployment = identity.get("deployment")
    contract = identity.get("contract")
    if not isinstance(deployment, dict) or not isinstance(contract, dict):
        raise SmokeCertificateError("eval_identity_endpoint_invalid")
    try:
        endpoint = validate_endpoint_binding(deployment.get("endpoint"))
        observed = load_deployment_endpoint(
            Path(endpoint["proxy_info"]["path"]),
            deployment_id=deployment["id"],
            expected_model=contract["model"],
            deployment_spec=Path(deployment["spec"]["path"]),
            expected_proxy_info_sha256=endpoint["proxy_info"]["sha256"],
        )
    except (EndpointBindingError, KeyError, TypeError) as cause:
        raise SmokeCertificateError("eval_identity_endpoint_invalid") from cause
    if observed.binding != endpoint:
        raise SmokeCertificateError("eval_identity_endpoint_mismatch")
    return endpoint


def _require_contract(identity: dict[str, Any]) -> None:
    if identity.get("role") != "smoke":
        raise SmokeCertificateError("eval_identity_role_invalid")
    contract = identity.get("contract")
    if not isinstance(contract, dict):
        raise SmokeCertificateError("eval_identity_contract_invalid")
    context = contract.get("context_tokens")
    thinking = contract.get("thinking")
    denylist = contract.get("outbound_body_denylist")
    sampling_max_tokens = contract.get("sampling_max_tokens")
    if (
        contract.get("model") != "Kimi-K3"
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort") != "max"
        or contract.get("capture_model_io") is not True
        or contract.get("retain_traces") is not False
        or isinstance(sampling_max_tokens, bool)
        or not isinstance(sampling_max_tokens, int)
        or not 0 < sampling_max_tokens <= MAX_SEQUENCE_TOKENS
        or not isinstance(context, dict)
        or any(context.get(key) != MAX_SEQUENCE_TOKENS for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"))
        or _canonical_json(thinking)
        != _canonical_json({"enable_thinking": True, "preserve_thinking": True})
        or not isinstance(denylist, list)
        or set(denylist) != {"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"}
    ):
        raise SmokeCertificateError("eval_identity_contract_invalid")


def _identity_artifact(identity: dict[str, Any], section: str, name: str) -> dict[str, str]:
    parent = identity.get(section)
    record = parent.get(name) if isinstance(parent, dict) else None
    if (
        not isinstance(record, dict)
        or not {"path", "sha256"}.issubset(record)
        or not isinstance(record.get("path"), str)
        or not isinstance(record.get("sha256"), str)
        or SHA256_RE.fullmatch(record["sha256"]) is None
    ):
        raise SmokeCertificateError(f"eval_identity_{section}_{name}_invalid")
    return {"path": str(Path(record["path"]).resolve(strict=True)), "sha256": record["sha256"]}


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as cause:
            raise SmokeCertificateError("checkpoint_unreadable") from cause
        if existing == encoded:
            return
        raise SmokeCertificateError("checkpoint_already_exists")

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fchmod(handle.fileno(), 0o444)
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as cause:
            raise SmokeCertificateError("checkpoint_already_exists") from cause
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def certify_smoke(
    run_dir: Path,
    *,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    expected_traces: int,
    identity_loader: Callable[..., dict[str, Any]] = load_eval_run_identity,
) -> dict[str, Any]:
    """Audit a completed smoke while holding its writer lock."""

    if SHA256_RE.fullmatch(expected_task_file_sha256) is None:
        raise SmokeCertificateError("expected_task_file_sha256_invalid")
    if isinstance(expected_traces, bool) or not isinstance(expected_traces, int) or expected_traces < 1:
        raise SmokeCertificateError("expected_traces_invalid")

    run_dir = run_dir.resolve(strict=True)
    lock_path = run_dir / ".writer.lock"
    try:
        lock = lock_path.open("rb")
    except OSError as cause:
        raise SmokeCertificateError("writer_lock_unreadable") from cause

    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as cause:
            raise SmokeCertificateError("writer_active") from cause

        identity_path = run_dir / "eval_run_identity.json"
        try:
            envelope = identity_loader(identity_path, verify_references=True)
        except (OSError, ValueError) as cause:
            raise SmokeCertificateError("eval_run_identity_invalid") from cause
        identity = envelope.get("identity")
        identity_sha256 = envelope.get("eval_run_identity_sha256")
        if not isinstance(identity, dict) or not isinstance(identity_sha256, str):
            raise SmokeCertificateError("eval_run_identity_invalid")
        _require_contract(identity)

        task_bytes = expected_task_file.resolve(strict=True).read_bytes()
        if _sha256_bytes(task_bytes) != expected_task_file_sha256:
            raise SmokeCertificateError("expected_task_file_hash_mismatch")
        expected_slugs = _read_expected_slugs(expected_task_file)
        if len(expected_slugs) != expected_traces:
            raise SmokeCertificateError("expected_task_count_mismatch")
        task_record = _identity_artifact(identity, "inputs", "task_file")
        if task_record["sha256"] != expected_task_file_sha256:
            raise SmokeCertificateError("eval_identity_task_hash_mismatch")
        identity_task_count = identity.get("inputs", {}).get("task_file", {}).get("count")
        if identity_task_count != expected_traces:
            raise SmokeCertificateError("eval_identity_task_count_mismatch")

        results_path = run_dir / "results.jsonl"
        before_results_sha256 = _sha256_file(results_path)
        summary, failed = _summarize_traces(
            _iter_traces(results_path),
            expected_slugs=expected_slugs,
            expected_count=expected_traces,
            rollouts_per_task=1,
            require_reasoning=True,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
            max_sequence_tokens=MAX_SEQUENCE_TOKENS,
        )
        if (
            failed
            or summary.get("model_io_turns", 0) < expected_traces
            or summary.get("sampled_tokens", 0) < 1
        ):
            raise SmokeCertificateError("trace_audit_failed")
        if _sha256_file(results_path) != before_results_sha256:
            raise SmokeCertificateError("results_changed_during_audit")

        deployment = identity.get("deployment")
        if not isinstance(deployment, dict):
            raise SmokeCertificateError("eval_identity_deployment_invalid")
        endpoint = _validated_endpoint(identity)
        execution = identity.get("execution")
        vmvm_environment = execution.get("vmvm_environment") if isinstance(execution, dict) else None
        deployment_id = deployment.get("id")
        spec = deployment.get("spec")
        if (
            not isinstance(deployment_id, str)
            or not deployment_id
            or not isinstance(spec, dict)
            or SHA256_RE.fullmatch(str(spec.get("sha256", ""))) is None
        ):
            raise SmokeCertificateError("eval_identity_deployment_invalid")
        execution_fields = {
            "rollout_concurrency": execution.get("rollout_concurrency") if isinstance(execution, dict) else None,
            "multiplex": execution.get("multiplex") if isinstance(execution, dict) else None,
            "http_max_connections": execution.get("http_max_connections") if isinstance(execution, dict) else None,
            "http_max_keepalive_connections": (
                execution.get("http_max_keepalive_connections") if isinstance(execution, dict) else None
            ),
            "lease_start_concurrency": (
                vmvm_environment.get("lease_start_concurrency") if isinstance(vmvm_environment, dict) else None
            ),
        }
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in execution_fields.values()
        ):
            raise SmokeCertificateError("eval_identity_execution_invalid")

        config_record = _identity_artifact(identity, "config", "resolved")
        manifest_record = _identity_artifact(identity, "inputs", "manifest")
        readiness_record = _identity_artifact(identity, "deployment", "readiness_checkpoint")
        readiness_payload = _read_json_object(Path(readiness_record["path"]), label="readiness_checkpoint")
        try:
            readiness_endpoint = validate_endpoint_binding(readiness_payload.get("endpoint"))
        except EndpointBindingError as cause:
            raise SmokeCertificateError("readiness_endpoint_invalid") from cause
        if readiness_endpoint != endpoint:
            raise SmokeCertificateError("readiness_endpoint_mismatch")
        artifacts = {
            "results": {"path": str(results_path), "sha256": before_results_sha256},
            "eval_run_identity": _artifact(identity_path),
            "config": config_record,
            "inputs_manifest": manifest_record,
            "provenance": _artifact(run_dir / "provenance.txt"),
            "readiness_checkpoint": readiness_record,
            "proxy_info": endpoint["proxy_info"],
        }
        for name, record in artifacts.items():
            if _sha256_file(Path(record["path"])) != record["sha256"]:
                raise SmokeCertificateError(f"artifact_hash_mismatch:{name}")

        certificate_body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "state": "passed",
            "ok": True,
            "eval_run_identity_sha256": identity_sha256,
            "deployment_id": deployment_id,
            "deployment_spec_sha256": spec["sha256"],
            "readiness_checkpoint_sha256": readiness_record["sha256"],
            "deployment": {
                "id": deployment_id,
                "spec_sha256": spec["sha256"],
            },
            "endpoint": endpoint,
            "qualified_execution": execution_fields,
            "audit_policy": {
                "expected_traces": expected_traces,
                "rollouts_per_task": 1,
                "require_reasoning": True,
                "require_model_io": True,
                "model_io_contract": EXPECTED_MODEL_IO_CONTRACT,
                "require_token_data": False,
                "require_logprobs": False,
                "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
            },
            "counts": {
                "traces": summary["traces"],
                "tasks": summary["tasks"],
                "sampled_tokens": summary["sampled_tokens"],
                "model_io_turns": summary["model_io_turns"],
                "trace_failures": summary["trace_failures"],
                "global_problems": len(summary["global_problems"]),
            },
            "artifacts": artifacts,
        }
        certificate = {
            **certificate_body,
            "smoke_checkpoint_sha256": _sha256_bytes(_canonical_json(certificate_body)),
        }
        _write_once(run_dir / "smoke_checkpoint.json", certificate)
        return certificate
    finally:
        lock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--expected-task-file", type=Path, required=True)
    parser.add_argument("--expected-task-file-sha256", required=True)
    parser.add_argument("--expected-traces", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        certificate = certify_smoke(
            args.run_dir,
            expected_task_file=args.expected_task_file,
            expected_task_file_sha256=args.expected_task_file_sha256,
            expected_traces=args.expected_traces,
        )
    except (OSError, ValueError) as error:
        print(f"smoke_checkpoint_error:{error}", file=sys.stderr)
        return 2
    checkpoint_path = (args.run_dir / "smoke_checkpoint.json").resolve()
    print(
        json.dumps(
            {
                "ok": True,
                "checkpoint": str(checkpoint_path),
                "checkpoint_file_sha256": _sha256_file(checkpoint_path),
                "smoke_certificate_sha256": certificate["smoke_checkpoint_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
