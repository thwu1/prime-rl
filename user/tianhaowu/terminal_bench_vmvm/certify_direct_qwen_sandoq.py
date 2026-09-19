#!/usr/bin/env python3
"""Certify a direct-Qwen Sandoq ramp stage using aggregate trace evidence."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path

from audit_traces import (
    QWEN3_A95B_MODEL_IO_CONTRACT,
    _iter_traces,
    _read_expected_slugs,
    _summarize_traces,
)
from eval_run_identity import load_eval_run_identity


class DirectSandoqCertificateError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(
    run_dir: Path,
    expected_task_file: Path,
    expected_task_file_sha256: str,
    expected_count: int,
) -> dict:
    lock_path = run_dir / ".writer.lock"
    with lock_path.open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DirectSandoqCertificateError("writer_active") from error
        envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
        identity = envelope["identity"]
        source = identity.get("source", {})
        execution = identity.get("execution", {})
        if (
            identity.get("role") != "qwen-direct"
            or source.get("sandbox_provider") != "sandoq"
            or execution.get("cleanup_must_succeed") is not True
            or execution.get("runtime", {}).get("type") != "sandoq"
        ):
            raise DirectSandoqCertificateError("sandoq_identity_required")
        task_bytes = expected_task_file.resolve(strict=True).read_bytes()
        if hashlib.sha256(task_bytes).hexdigest() != expected_task_file_sha256:
            raise DirectSandoqCertificateError("task_file_hash_mismatch")
        expected_slugs = _read_expected_slugs(expected_task_file)
        task_record = identity.get("inputs", {}).get("task_file", {})
        if (
            len(expected_slugs) != expected_count
            or task_record.get("sha256") != expected_task_file_sha256
            or task_record.get("count") != expected_count
        ):
            raise DirectSandoqCertificateError("task_selection_mismatch")
        results = run_dir / "results.jsonl"
        before = _sha256(results)
        summary, failed = _summarize_traces(
            _iter_traces(results),
            expected_slugs=expected_slugs,
            expected_count=expected_count,
            rollouts_per_task=1,
            require_reasoning=True,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            model_io_contract=QWEN3_A95B_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            max_sequence_tokens=262_144,
        )
        if failed or summary.get("model_io_turns", 0) < expected_count:
            raise DirectSandoqCertificateError("trace_audit_failed")
        if _sha256(results) != before:
            raise DirectSandoqCertificateError("results_changed_during_audit")
        return {
            "schema_version": 1,
            "kind": "direct-qwen-sandoq-ramp",
            "state": "passed",
            "stage_count": expected_count,
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "results_sha256": before,
            "task_file_sha256": expected_task_file_sha256,
            "sandbox_provider": "sandoq",
            "cleanup_must_succeed": True,
            "worker_manifest_sha256": identity["deployment"]["worker_manifest"]["sha256"],
        }


def _write_exclusive(path: Path, payload: dict) -> None:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-task-file", type=Path, required=True)
    parser.add_argument("--expected-task-file-sha256", required=True)
    parser.add_argument("--expected-count", type=int, choices=(2, 8, 24, 2500), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    certificate = certify(
        args.run_dir,
        args.expected_task_file,
        args.expected_task_file_sha256,
        args.expected_count,
    )
    _write_exclusive(args.output, certificate)
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
