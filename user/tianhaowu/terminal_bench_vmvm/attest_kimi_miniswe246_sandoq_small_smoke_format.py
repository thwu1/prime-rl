#!/usr/bin/env python3
"""Publish an aggregate-only exact-response attestation for the immutable stock smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = 3
KIND = "kimi-tb4-miniswe246-sandoq-firecracker-small-smoke-format"
SOURCE_RECEIPT_SHA256 = "cfa6b1cf195b1c49ac3f2884223b183b7a726eca32a7218cdcc243d58e590ee7"
SOURCE_RAW_TRACE_SHA256 = "c30a3b59a836443fab04cd169d301abdfefb5126806f87281a26dfd30c240636"
SOURCE_JOB_ID = "1605262"
SOURCE_REVISION = "96a469f0b924dcd5dd89b226294f025576f887a8"
ENDPOINT_IDENTIFIER = "tianhaowu-kimi-k3-stock-eval-20260927"
EXPECTED_CALLS = 3


class SmokeFormatError(ValueError):
    """The immutable smoke evidence does not prove the exact-response contract."""


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _read_private(path: Path, *, expected_sha256: str, maximum_bytes: int) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size > maximum_bytes
        ):
            raise SmokeFormatError("source_artifact_invalid")
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > maximum_bytes:
                raise SmokeFormatError("source_artifact_invalid")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    visible = os.stat(path, follow_symlinks=False)
    identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_nlink, value.st_size)
    if identity(before) != identity(after) or identity(after) != identity(visible):
        raise SmokeFormatError("source_artifact_changed")
    raw = bytes(body)
    if _sha256(raw) != expected_sha256:
        raise SmokeFormatError("source_artifact_invalid")
    return raw


def _tool_semantics(calls: object, *, nested: bool) -> list[tuple[str, str, str]]:
    if not isinstance(calls, list):
        raise SmokeFormatError("tool_calls_invalid")
    result: list[tuple[str, str, str]] = []
    for call in calls:
        if not isinstance(call, dict):
            raise SmokeFormatError("tool_calls_invalid")
        function = call.get("function") if nested else call
        if not isinstance(function, dict):
            raise SmokeFormatError("tool_calls_invalid")
        call_id = call.get("id")
        name = function.get("name")
        arguments = function.get("arguments")
        if not all(isinstance(value, str) and value for value in (call_id, name, arguments)):
            raise SmokeFormatError("tool_calls_invalid")
        result.append((call_id, name, arguments))
    return result


def attest(*, receipt: Path, raw_trace: Path, output: Path) -> dict[str, Any]:
    receipt = receipt.resolve(strict=True)
    raw_trace = raw_trace.resolve(strict=True)
    output = Path(os.path.abspath(output))
    if output.exists() or output.is_symlink():
        raise SmokeFormatError("output_not_fresh")
    receipt_body = _read_private(
        receipt,
        expected_sha256=SOURCE_RECEIPT_SHA256,
        maximum_bytes=2 * 1024 * 1024,
    )
    trace_body = _read_private(
        raw_trace,
        expected_sha256=SOURCE_RAW_TRACE_SHA256,
        maximum_bytes=64 * 1024 * 1024,
    )
    try:
        receipt_value = json.loads(receipt_body)
        trace = json.loads(trace_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SmokeFormatError("source_artifact_invalid") from error
    deployment = receipt_value.get("deployment") if isinstance(receipt_value, dict) else None
    router = deployment.get("router") if isinstance(deployment, dict) else None
    transport = receipt_value.get("transport") if isinstance(receipt_value, dict) else None
    summary = transport.get("summary") if isinstance(transport, dict) else None
    totals = summary.get("integer_totals") if isinstance(summary, dict) else None
    if (
        not isinstance(receipt_value, dict)
        or receipt_value.get("schema_version") != 3
        or receipt_value.get("status") != "diagnostic_passed"
        or receipt_value.get("model_calls") != EXPECTED_CALLS
        or receipt_value.get("reasoning_content_retained") is not True
        or receipt_value.get("shell_execution") is not True
        or receipt_value.get("cleanup") is not True
        or not isinstance(deployment, dict)
        or deployment.get("slurm_job_id") != SOURCE_JOB_ID
        or deployment.get("source_revision") != SOURCE_REVISION
        or not isinstance(router, dict)
        or router.get("endpoint_identifier") != ENDPOINT_IDENTIFIER
        or not isinstance(summary, dict)
        or summary.get("source_schema") != "logical-exact-once-v1"
        or summary.get("summary_records") != 1
        or summary.get("exact_once_counters_required") is not True
        or not isinstance(totals, dict)
        or any(
            totals.get(key) != EXPECTED_CALLS
            for key in (
                "requests",
                "upstream_attempts",
                "logical_requests",
                "logical_upstream_attempts",
                "streamed_requests",
            )
        )
        or any(
            totals.get(key) != 0
            for key in (
                "anonymous_upstream_attempts",
                "coalesced_requests",
                "replayed_requests",
                "expired_logical_retries",
                "downstream_disconnects",
                "conflicting_requests",
                "inflight",
                "error_count",
                "unknown_path_requests",
            )
        )
    ):
        raise SmokeFormatError("source_receipt_invalid")
    if not isinstance(trace, dict) or set(trace) != {
        "model_requests",
        "model_responses",
        "program_stderr",
        "program_stdout",
        "schema_version",
        "trajectory",
    }:
        raise SmokeFormatError("raw_trace_invalid")
    requests = trace.get("model_requests")
    responses = trace.get("model_responses")
    trajectory = trace.get("trajectory")
    messages = trajectory.get("messages") if isinstance(trajectory, dict) else None
    assistants = (
        [message for message in messages if isinstance(message, dict) and message.get("role") == "assistant"]
        if isinstance(messages, list)
        else []
    )
    if (
        trace.get("schema_version") != 1
        or not isinstance(requests, list)
        or not isinstance(responses, list)
        or len(requests) != EXPECTED_CALLS
        or len(responses) != EXPECTED_CALLS
        or len(assistants) != EXPECTED_CALLS
        or not isinstance(trajectory, dict)
        or trajectory.get("trajectory_format") != "mini-swe-agent-1.1"
    ):
        raise SmokeFormatError("raw_trace_invalid")

    response_digests: list[str] = []
    request_digests: list[str] = []
    reasoning_nonblank = 0
    tool_call_turns = 0
    tool_calls_total = 0
    for index, (request, response, assistant) in enumerate(zip(requests, responses, assistants, strict=True)):
        if (
            not isinstance(request, dict)
            or request.get("model") != "Kimi-K3"
            or request.get("stream") is not False
            or request.get("reasoning_effort") != "max"
            or request.get("chat_template_kwargs")
            != {"enable_thinking": True, "preserve_thinking": True}
            or request.get("max_tokens") != 512
            or request.get("parallel_tool_calls") is not False
        ):
            raise SmokeFormatError("request_contract_invalid")
        if not isinstance(response, dict):
            raise SmokeFormatError("response_contract_invalid")
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise SmokeFormatError("response_contract_invalid")
        message = choices[0].get("message")
        if (
            not isinstance(message, dict)
            or set(message) != {"content", "reasoning", "role", "tool_calls"}
            or message.get("role") != "assistant"
            or "reasoning_content" in message
            or not isinstance(message.get("reasoning"), str)
            or not message["reasoning"]
            or message.get("reasoning") != assistant.get("reasoning_content")
            or message.get("content") != assistant.get("content")
        ):
            raise SmokeFormatError("response_contract_invalid")
        provider_calls = _tool_semantics(message.get("tool_calls"), nested=True)
        trajectory_calls = _tool_semantics(assistant.get("tool_calls"), nested=True)
        if provider_calls != trajectory_calls or not provider_calls:
            raise SmokeFormatError("response_contract_invalid")
        usage = response.get("usage")
        if (
            not isinstance(usage, dict)
            or not isinstance(usage.get("prompt_tokens"), int)
            or not isinstance(usage.get("completion_tokens"), int)
            or usage["prompt_tokens"] < 0
            or usage["completion_tokens"] < 1
        ):
            raise SmokeFormatError("response_contract_invalid")
        reasoning_nonblank += 1
        tool_call_turns += 1
        tool_calls_total += len(provider_calls)
        request_digests.append(_sha256(_canonical_json(request)))
        response_digests.append(_sha256(_canonical_json(response)))

    attestation = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "passed",
        "source": {
            "slurm_job_id": SOURCE_JOB_ID,
            "source_revision": SOURCE_REVISION,
            "receipt": {"path": str(receipt), "bytes": len(receipt_body), "sha256": _sha256(receipt_body)},
            "raw_trace": {"path": str(raw_trace), "bytes": len(trace_body), "sha256": _sha256(trace_body)},
        },
        "capture": {
            "response_kind": "exact_provider_json",
            "model_calls": EXPECTED_CALLS,
            "nonstream_provider_requests": EXPECTED_CALLS,
            "reasoning_nonblank": reasoning_nonblank,
            "reasoning_exact_parity": EXPECTED_CALLS,
            "tool_call_turns": tool_call_turns,
            "tool_calls_total": tool_calls_total,
            "tool_call_exact_semantic_parity": EXPECTED_CALLS,
            "request_digest_set_sha256": _sha256(_canonical_json(sorted(request_digests))),
            "response_digest_set_sha256": _sha256(_canonical_json(sorted(response_digests))),
            "raw_provider_field": "reasoning",
            "canonical_trajectory_field": "reasoning_content",
        },
    }
    payload = _canonical_json(attestation)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        output,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written < 1:
                raise SmokeFormatError("output_write_failed")
            remaining = remaining[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"state": "passed", "attestation_sha256": _sha256(payload), **attestation["capture"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--raw-trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = attest(receipt=args.receipt, raw_trace=args.raw_trace, output=args.output)
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_small_smoke_format_attestation_failed","state":"blocked"}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
