#!/usr/bin/env python3
"""Export audited Verifiers v1 evaluation traces as a deterministic SFT dataset.

The exporter is intentionally non-interactive and redacted: stdout/stderr contain only
aggregate counts and stable error codes. Task identifiers, prompts, messages, tool payloads,
raw trace rows, and captured provider bodies are never logged.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import tomllib
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from audit_traces import DEFAULT_MAX_SEQUENCE_TOKENS, _audit_trace

FORMAT_VERSION = 1
SPLIT_BUCKETS = 10_000
DEFAULT_VALIDATION_PERMYRIAD = 500
DEFAULT_SPLIT_SALT = "terminal-bench-vmvm-sft-v1"
FORBIDDEN_REQUEST_FIELDS = frozenset({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"})
REQUIRED_RUN_ARTIFACTS = (
    "config.toml",
    "provenance.txt",
    "inputs/manifest.json",
    "inputs/source_config.toml",
    "inputs/task_file.txt",
    "inputs/image_manifest.json",
)

Selection = Literal["pass-only", "all-outcomes"]


class ExportError(RuntimeError):
    """A fail-closed export error represented by a non-sensitive stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FileArtifact:
    bytes: int
    sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {"bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class ExportOptions:
    results: Path
    output_dir: Path
    selection: Selection
    expected_count: int | None = None
    validation_permyriad: int = DEFAULT_VALIDATION_PERMYRIAD
    split_salt: str = DEFAULT_SPLIT_SALT
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS


class JSONLSink:
    """Exclusive JSONL writer that hashes the exact bytes it persists."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        self._file = os.fdopen(os.open(path, flags, 0o600), "wb")
        self._digest = hashlib.sha256()
        self.rows = 0
        self.bytes = 0

    def write(self, row: dict[str, Any]) -> None:
        try:
            encoded = (
                json.dumps(
                    row,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
        except (TypeError, ValueError) as error:
            raise ExportError("output_row_not_strict_json") from error
        self._file.write(encoded)
        self._digest.update(encoded)
        self.rows += 1
        self.bytes += len(encoded)

    def close(self) -> FileArtifact:
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        return FileArtifact(bytes=self.bytes, sha256=self._digest.hexdigest())


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ExportError("input_not_strict_json") from error


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _open_regular(path: Path):
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ExportError("source_artifact_open_failed") from error
    descriptor = os.fstat(fd)
    if not stat.S_ISREG(descriptor.st_mode):
        os.close(fd)
        raise ExportError("source_artifact_not_regular")
    return os.fdopen(fd, "rb"), descriptor


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def _read_stable_file(path: Path) -> tuple[bytes, FileArtifact]:
    source, before = _open_regular(path)
    try:
        body = source.read()
        after = os.fstat(source.fileno())
    finally:
        source.close()
    if not _same_file(before, after):
        raise ExportError("source_artifact_changed")
    return body, FileArtifact(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


@contextmanager
def _hold_source_writer_lock(run_dir: Path) -> Iterator[None]:
    """Take a nonblocking shared lock when the evaluator writer lock is present."""
    path = run_dir / ".writer.lock"
    if not os.path.lexists(path):
        yield
        return
    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ExportError("writer_lock_open_failed") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ExportError("writer_lock_not_regular")
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ExportError("source_run_is_active") from error
        after = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (
            after.st_dev,
            after.st_ino,
        ):
            raise ExportError("writer_lock_replaced")
        yield
    finally:
        os.close(fd)


def _parse_json_object(body: bytes, code: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportError(code) from error
    if not isinstance(value, dict):
        raise ExportError(code)
    return value


def _validate_run_provenance(run_dir: Path, max_sequence_tokens: int) -> tuple[dict[str, FileArtifact], dict[str, Any]]:
    bodies: dict[str, bytes] = {}
    artifacts: dict[str, FileArtifact] = {}
    for relative in REQUIRED_RUN_ARTIFACTS:
        body, artifact = _read_stable_file(run_dir / relative)
        bodies[relative] = body
        artifacts[relative] = artifact

    inputs_manifest = _parse_json_object(bodies["inputs/manifest.json"], "input_manifest_invalid")
    expected_snapshots = {
        "config": "inputs/source_config.toml",
        "task_file": "inputs/task_file.txt",
        "image_manifest": "inputs/image_manifest.json",
    }
    for key, relative in expected_snapshots.items():
        record = inputs_manifest.get(key)
        if not isinstance(record, dict) or record.get("sha256") != artifacts[relative].sha256:
            raise ExportError("input_manifest_digest_mismatch")

    try:
        config = tomllib.loads(bodies["config.toml"].decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ExportError("resolved_config_invalid") from error

    client = config.get("client")
    sampling = config.get("sampling")
    taskset = config.get("taskset")
    if not isinstance(client, dict) or client.get("type") != "eval":
        raise ExportError("resolved_config_client_invalid")
    if client.get("capture_model_io") is not True:
        raise ExportError("resolved_config_model_io_disabled")
    denylist = client.get("outbound_body_denylist")
    if not isinstance(denylist, list) or not FORBIDDEN_REQUEST_FIELDS.issubset(denylist):
        raise ExportError("resolved_config_forbidden_request_fields_not_denied")
    if not isinstance(sampling, dict):
        raise ExportError("resolved_config_sampling_invalid")
    chat_kwargs = sampling.get("chat_template_kwargs")
    if not isinstance(chat_kwargs, dict) or chat_kwargs.get("enable_thinking") is not True:
        raise ExportError("resolved_config_thinking_disabled")
    if chat_kwargs.get("preserve_thinking") is not True:
        raise ExportError("resolved_config_thinking_not_preserved")
    if not isinstance(taskset, dict):
        raise ExportError("resolved_config_taskset_invalid")
    if taskset.get("task_file_sha256") != artifacts["inputs/task_file.txt"].sha256:
        raise ExportError("resolved_config_task_digest_mismatch")
    if taskset.get("image_manifest_sha256") != artifacts["inputs/image_manifest.json"].sha256:
        raise ExportError("resolved_config_image_digest_mismatch")

    limits: dict[str, int] = {}
    for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= max_sequence_tokens:
            raise ExportError("resolved_config_token_limit_invalid")
        limits[key] = value
    model = config.get("model")
    if not isinstance(model, str) or not model:
        raise ExportError("resolved_config_model_invalid")
    num_rollouts = config.get("num_rollouts")
    if isinstance(num_rollouts, bool) or not isinstance(num_rollouts, int) or num_rollouts < 1:
        raise ExportError("resolved_config_rollout_count_invalid")
    return artifacts, {
        "capture_model_io": True,
        "model": model,
        "num_rollouts": num_rollouts,
        **limits,
    }


def _reasoning_text(message: Mapping[str, Any]) -> str | None:
    for key in ("reasoning", "reasoning_content"):
        value = message.get(key)
        if isinstance(value, str) and value:
            return value
    details = message.get("reasoning_details")
    if isinstance(details, list):
        parts = []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            value = detail.get("text") or detail.get("summary")
            if isinstance(value, str) and value:
                parts.append(value)
        return "\n".join(parts) or None
    return None


def _content_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not (isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)):
                raise ExportError("captured_response_content_invalid")
            parts.append(part["text"])
        return "".join(parts)
    raise ExportError("captured_response_content_invalid")


def _flat_tool_calls(calls: object, *, nested: bool) -> list[tuple[str, str, str]]:
    if calls is None:
        return []
    if not isinstance(calls, list):
        raise ExportError("captured_response_tool_calls_invalid")
    flattened: list[tuple[str, str, str]] = []
    for call in calls:
        if not isinstance(call, dict):
            raise ExportError("captured_response_tool_calls_invalid")
        if nested and call.get("type") != "function":
            raise ExportError("captured_response_tool_calls_invalid")
        function = call.get("function") if nested else call
        if not isinstance(function, dict):
            raise ExportError("captured_response_tool_calls_invalid")
        call_id = call.get("id")
        name = function.get("name")
        arguments = function.get("arguments")
        if not all(isinstance(value, str) for value in (call_id, name, arguments)):
            raise ExportError("captured_response_tool_calls_invalid")
        flattened.append((call_id, name, arguments))
    return flattened


def _validate_usage(node_usage: object, response_body: dict[str, Any], kind: str) -> None:
    if not isinstance(node_usage, dict):
        raise ExportError("captured_response_usage_missing")
    response_usage = response_body.get("usage")
    if not isinstance(response_usage, dict):
        raise ExportError("captured_response_usage_missing")

    def token_count(value: object, *, positive: bool = False) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or (positive and value == 0):
            raise ExportError("captured_response_usage_invalid")
        return value

    prompt = token_count(response_usage.get("prompt_tokens"))
    completion = token_count(response_usage.get("completion_tokens"), positive=True)
    if kind == "normalized_stream_response":
        expected = {"prompt_tokens": prompt, "completion_tokens": completion}
        cached = response_usage.get("cached_input_tokens")
        reasoning = response_usage.get("reasoning_tokens")
    else:
        prompt_details = response_usage.get("prompt_tokens_details")
        completion_details = response_usage.get("completion_tokens_details")
        cached = prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
        reasoning = completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else None
        expected = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
        }
    if cached is not None:
        cached = token_count(cached)
        if kind == "exact_provider_json":
            if cached > prompt:
                raise ExportError("captured_response_usage_invalid")
            expected["prompt_tokens"] = prompt - cached
        expected["cached_input_tokens"] = cached
    if reasoning is not None:
        reasoning = token_count(reasoning)
        if reasoning > completion:
            raise ExportError("captured_response_usage_invalid")
        expected["reasoning_tokens"] = reasoning
    observed = {
        key: node_usage.get(key)
        for key in ("prompt_tokens", "completion_tokens", "cached_input_tokens", "reasoning_tokens")
        if node_usage.get(key) is not None
    }
    for key, value in observed.items():
        token_count(value, positive=key == "completion_tokens")
    if observed != expected:
        raise ExportError("captured_response_usage_mismatch")


def _validate_captured_response(node: dict[str, Any]) -> None:
    model_io = node.get("model_io")
    response = model_io.get("response") if isinstance(model_io, dict) else None
    if not isinstance(response, dict) or not isinstance(response.get("body"), dict):
        raise ExportError("captured_response_invalid")
    kind = response.get("kind")
    body = response["body"]
    if kind == "exact_provider_json":
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ExportError("captured_response_invalid")
        raw_message = choices[0].get("message")
        raw_finish = choices[0].get("finish_reason")
        nested_calls = True
    elif kind == "normalized_stream_response":
        raw_message = body.get("message")
        raw_finish = body.get("finish_reason")
        nested_calls = False
    else:
        raise ExportError("captured_response_invalid")
    if not isinstance(raw_message, dict):
        raise ExportError("captured_response_invalid")
    if raw_message.get("role") != "assistant":
        raise ExportError("captured_response_invalid")

    message = node.get("message")
    if not isinstance(message, dict):
        raise ExportError("captured_response_message_mismatch")
    if _content_text(raw_message.get("content")) != _content_text(message.get("content")):
        raise ExportError("captured_response_message_mismatch")
    if (_reasoning_text(raw_message) or "") != (message.get("reasoning_content") or ""):
        raise ExportError("captured_response_reasoning_mismatch")
    if _flat_tool_calls(raw_message.get("tool_calls"), nested=nested_calls) != _flat_tool_calls(
        message.get("tool_calls"), nested=False
    ):
        raise ExportError("captured_response_tool_calls_mismatch")
    if raw_finish != node.get("finish_reason"):
        raise ExportError("captured_response_finish_reason_mismatch")
    _validate_usage(node.get("usage"), body, kind)


def _normalize_tool_call(call: object) -> dict[str, Any]:
    if not isinstance(call, dict):
        raise ExportError("assistant_tool_call_invalid")
    if isinstance(call.get("function"), dict):
        function = call["function"]
        call_type = call.get("type", "function")
    else:
        function = call
        call_type = "function"
    call_id = call.get("id")
    name = function.get("name")
    arguments = function.get("arguments")
    if (
        call_type != "function"
        or not isinstance(call_id, str)
        or not call_id
        or not isinstance(name, str)
        or not name
        or not isinstance(arguments, str)
    ):
        raise ExportError("assistant_tool_call_invalid")
    try:
        json.loads(arguments)
    except json.JSONDecodeError as error:
        raise ExportError("assistant_tool_arguments_not_json") from error
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _normalize_tools(tools: object) -> list[dict[str, Any]]:
    if not isinstance(tools, list) or not tools:
        raise ExportError("tool_schema_missing")
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type", "function") != "function":
            raise ExportError("tool_schema_invalid")
        function = tool.get("function")
        if not isinstance(function, dict):
            raise ExportError("tool_schema_invalid")
        name = function.get("name")
        description = function.get("description", "")
        parameters = function.get("parameters", {})
        strict = function.get("strict")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(description, str)
            or not isinstance(parameters, dict)
            or (strict is not None and not isinstance(strict, bool))
        ):
            raise ExportError("tool_schema_invalid")
        normalized.append(copy.deepcopy(tool))
    _canonical_json_bytes(normalized)
    return normalized


def _stable_trace_tools(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] | None = None
    selected_digest: str | None = None
    full_requests = 0
    for node in nodes:
        if node.get("sampled") is not True:
            continue
        model_io = node.get("model_io")
        request = model_io.get("request") if isinstance(model_io, dict) else None
        if not isinstance(request, dict):
            raise ExportError("model_request_missing")
        if request.get("kind") == "full":
            body = request.get("body")
            if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
                raise ExportError("full_model_request_invalid")
            tools = _normalize_tools(body.get("tools"))
            digest = _json_sha256(tools)
            if selected_digest is not None and digest != selected_digest:
                raise ExportError("tool_schema_changed_within_trace")
            selected = tools
            selected_digest = digest
            full_requests += 1
        elif request.get("kind") == "delta":
            changed = (
                set(request.get("set_fields") or {})
                | set(request.get("remove_fields") or [])
                | set(request.get("append_fields") or {})
            )
            if "tools" in changed:
                raise ExportError("tool_schema_changed_within_trace")
        else:
            raise ExportError("model_request_invalid")
    if full_requests == 0 or selected is None:
        raise ExportError("tool_schema_missing")
    return selected


def _root_path(nodes: list[dict[str, Any]], node_id: int) -> list[int]:
    path: list[int] = []
    seen: set[int] = set()
    current: int | None = node_id
    while current is not None:
        if (
            isinstance(current, bool)
            or not isinstance(current, int)
            or not 0 <= current < len(nodes)
            or current in seen
        ):
            raise ExportError("message_graph_invalid")
        seen.add(current)
        path.append(current)
        parent = nodes[current].get("parent")
        if parent is not None and (isinstance(parent, bool) or not isinstance(parent, int)):
            raise ExportError("message_graph_invalid")
        current = parent
    path.reverse()
    return path


def _normalize_message(message: object, *, target: bool) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise ExportError("message_invalid")
    role = message.get("role")
    content = message.get("content")
    if role not in {"system", "user", "assistant", "tool"}:
        raise ExportError("message_invalid")
    if role == "assistant":
        if content is not None and not isinstance(content, str):
            raise ExportError("message_content_invalid")
        normalized: dict[str, Any] = {
            "role": "assistant",
            "content": content or "",
            "trainable": target,
        }
        if target:
            reasoning = message.get("reasoning_content")
            if reasoning is not None:
                if not isinstance(reasoning, str) or not reasoning.strip():
                    raise ExportError("target_reasoning_invalid")
                normalized["reasoning_content"] = reasoning
        calls = message.get("tool_calls")
        if calls:
            if not isinstance(calls, list):
                raise ExportError("assistant_tool_call_invalid")
            normalized["tool_calls"] = [_normalize_tool_call(call) for call in calls]
        return normalized

    if not isinstance(content, str):
        raise ExportError("message_content_invalid")
    normalized = {"role": role, "content": content, "trainable": False}
    if role == "tool":
        call_id = message.get("tool_call_id")
        if not isinstance(call_id, str) or not call_id:
            raise ExportError("tool_message_invalid")
        normalized["tool_call_id"] = call_id
        name = message.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise ExportError("tool_message_invalid")
            normalized["name"] = name
    return normalized


def _target_rows(
    trace: dict[str, Any],
    *,
    source_trace_index: int,
    source_split_row_index: int,
    source_trace_sha256: str,
    task_sha256: str,
    reward: float,
    tools: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    raw_nodes = trace.get("nodes")
    if not isinstance(raw_nodes, list) or not all(isinstance(node, dict) for node in raw_nodes):
        raise ExportError("message_graph_invalid")
    nodes = list(raw_nodes)
    sampled_ids = [index for index, node in enumerate(nodes) if node.get("sampled") is True]
    for target_turn_index, node_id in enumerate(sampled_ids):
        messages = [
            _normalize_message(nodes[path_id].get("message"), target=path_id == node_id)
            for path_id in _root_path(nodes, node_id)
        ]
        if (
            not messages
            or messages[-1].get("role") != "assistant"
            or messages[-1].get("trainable") is not True
            or sum(message.get("trainable") is True for message in messages) != 1
        ):
            raise ExportError("target_message_invalid")
        yield {
            "assistant_target_count": 1,
            "history_reasoning_policy": "strip_all_prior_assistant_reasoning",
            "is_correct": reward > 0,
            "messages": messages,
            "reward": reward,
            "source_episode_id": source_trace_sha256,
            "source_node_index": node_id,
            "source_split_row_index": source_split_row_index,
            "source_trace_index": source_trace_index,
            "source_trajectory_assistant_turn_count": len(sampled_ids),
            "target_assistant_message_index": len(messages) - 1,
            "target_assistant_turn_index": target_turn_index,
            "target_has_reasoning": "reasoning_content" in messages[-1],
            "task_id": task_sha256,
            "tools": tools,
        }


def _trace_reward(trace: dict[str, Any]) -> float:
    rewards = trace.get("rewards")
    if not isinstance(rewards, dict) or not rewards:
        raise ExportError("trace_reward_missing")
    values = list(rewards.values())
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values
    ):
        raise ExportError("trace_reward_invalid")
    reward = float(sum(values))
    if reward not in {0.0, 1.0}:
        raise ExportError("trace_reward_not_binary")
    return reward


def _split_for_task(task_sha256: str, *, salt: str, validation_permyriad: int) -> str:
    digest = hashlib.sha256(f"{salt}\0{task_sha256}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % SPLIT_BUCKETS
    return "validation" if bucket < validation_permyriad else "train"


def _write_json(path: Path, value: object) -> FileArtifact:
    body = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    with os.fdopen(os.open(path, flags, 0o600), "wb") as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    return FileArtifact(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _validate_options(options: ExportOptions) -> None:
    if options.selection not in {"pass-only", "all-outcomes"}:
        raise ExportError("selection_invalid")
    if options.expected_count is not None and options.expected_count < 1:
        raise ExportError("expected_count_invalid")
    if not 0 <= options.validation_permyriad < SPLIT_BUCKETS:
        raise ExportError("validation_permyriad_invalid")
    if not options.split_salt:
        raise ExportError("split_salt_invalid")
    if options.max_sequence_tokens < 1:
        raise ExportError("max_sequence_tokens_invalid")
    if os.path.lexists(options.output_dir):
        raise ExportError("output_already_exists")
    try:
        if options.output_dir.resolve().is_relative_to(options.results.parent.resolve()):
            raise ExportError("output_inside_source_run")
    except OSError as error:
        raise ExportError("path_resolution_failed") from error


def export_sft(options: ExportOptions) -> dict[str, Any]:
    """Validate and atomically export one run; return only aggregate metadata."""
    _validate_options(options)
    run_dir = options.results.parent
    output_parent = options.output_dir.parent
    output_parent.mkdir(parents=True, exist_ok=True)

    with _hold_source_writer_lock(run_dir):
        source_artifacts, config_summary = _validate_run_provenance(run_dir, options.max_sequence_tokens)
        source, source_before = _open_regular(options.results)
        temporary = Path(tempfile.mkdtemp(prefix=f".{options.output_dir.name}.", dir=output_parent))
        published = False
        train_sink: JSONLSink | None = None
        validation_sink: JSONLSink | None = None
        try:
            train_sink = JSONLSink(temporary / "train" / "train.jsonl")
            validation_sink = JSONLSink(temporary / "validation" / "train.jsonl")
            sinks = {"train": train_sink, "validation": validation_sink}
            counts: Counter[str] = Counter()
            split_task_hashes: dict[str, set[str]] = {"train": set(), "validation": set()}
            split_trace_indices = {"train": 0, "validation": 0}
            seen_trace_ids: set[str] = set()
            seen_source_rows: set[str] = set()
            source_digest = hashlib.sha256()

            for source_trace_index, raw_line in enumerate(source):
                source_digest.update(raw_line)
                if not raw_line.endswith(b"\n"):
                    raise ExportError("results_jsonl_unterminated")
                if not raw_line.strip():
                    raise ExportError("results_jsonl_blank_line")
                try:
                    trace = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ExportError("results_jsonl_invalid") from error
                if not isinstance(trace, dict):
                    raise ExportError("trace_not_object")
                counts["input_traces"] += 1

                trace_id = trace.get("id")
                task = trace.get("task")
                if not isinstance(trace_id, str) or not trace_id or not isinstance(task, dict):
                    raise ExportError("trace_identity_invalid")
                trace_id_sha256 = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()
                if trace_id_sha256 in seen_trace_ids:
                    raise ExportError("duplicate_trace_id")
                seen_trace_ids.add(trace_id_sha256)
                source_trace_sha256 = hashlib.sha256(raw_line).hexdigest()
                if source_trace_sha256 in seen_source_rows:
                    raise ExportError("duplicate_trace_row")
                seen_source_rows.add(source_trace_sha256)
                task_sha256 = _json_sha256(task)

                errors = trace.get("errors")
                if not isinstance(errors, list):
                    raise ExportError("trace_errors_invalid")
                if errors:
                    counts["excluded_error_traces"] += 1
                    continue
                if trace.get("is_completed") is not True:
                    raise ExportError("trace_not_completed")
                reward = _trace_reward(trace)
                counts["scored_pass_traces" if reward > 0 else "scored_fail_traces"] += 1
                stop_condition = trace.get("stop_condition")
                if not isinstance(stop_condition, str) or not stop_condition:
                    raise ExportError("trace_stop_condition_invalid")

                problems = _audit_trace(
                    trace,
                    require_reasoning=True,
                    max_sequence_tokens=options.max_sequence_tokens,
                    require_token_data=False,
                    require_logprobs=False,
                    require_model_io=True,
                )
                if problems:
                    raise ExportError("trace_validation_failed")
                if options.selection == "pass-only" and reward == 0:
                    counts["selection_excluded_fail_traces"] += 1
                    continue

                raw_nodes = trace.get("nodes")
                if not isinstance(raw_nodes, list) or not all(isinstance(node, dict) for node in raw_nodes):
                    raise ExportError("message_graph_invalid")
                nodes = list(raw_nodes)
                for node in nodes:
                    if node.get("sampled") is True:
                        _validate_captured_response(node)
                tools = _stable_trace_tools(nodes)
                split = _split_for_task(
                    task_sha256,
                    salt=options.split_salt,
                    validation_permyriad=options.validation_permyriad,
                )
                split_task_hashes[split].add(task_sha256)
                source_split_row_index = split_trace_indices[split]
                emitted = 0
                for row in _target_rows(
                    trace,
                    source_trace_index=source_trace_index,
                    source_split_row_index=source_split_row_index,
                    source_trace_sha256=source_trace_sha256,
                    task_sha256=task_sha256,
                    reward=reward,
                    tools=tools,
                ):
                    sinks[split].write(row)
                    emitted += 1
                if emitted == 0:
                    raise ExportError("trace_has_no_sft_targets")
                counts["selected_traces"] += 1
                counts["selected_pass_traces" if reward > 0 else "selected_fail_traces"] += 1
                counts["emitted_rows"] += emitted
                counts[f"{split}_traces"] += 1
                counts[f"{split}_rows"] += emitted
                split_trace_indices[split] += 1

            source_after = os.fstat(source.fileno())
            if not _same_file(source_before, source_after):
                raise ExportError("results_jsonl_changed")
            if options.expected_count is not None and counts["input_traces"] != options.expected_count:
                raise ExportError("input_trace_count_mismatch")
            if counts["selected_traces"] == 0:
                raise ExportError("no_selected_traces")
            if split_task_hashes["train"] & split_task_hashes["validation"]:
                raise ExportError("task_split_overlap")

            train_artifact = train_sink.close()
            train_sink = None
            validation_artifact = validation_sink.close()
            validation_sink = None
            source_artifacts["results.jsonl"] = FileArtifact(
                bytes=source_after.st_size,
                sha256=source_digest.hexdigest(),
            )
            task_split = {
                "format_version": FORMAT_VERSION,
                "split_salt": options.split_salt,
                "validation_permyriad": options.validation_permyriad,
                "train_task_sha256": sorted(split_task_hashes["train"]),
                "validation_task_sha256": sorted(split_task_hashes["validation"]),
            }
            task_split_artifact = _write_json(temporary / "task-split.json", task_split)

            manifest = {
                "artifacts": {
                    "task-split.json": task_split_artifact.as_dict(),
                    "train/train.jsonl": train_artifact.as_dict(),
                    "validation/train.jsonl": validation_artifact.as_dict(),
                },
                "config": config_summary,
                "counts": dict(sorted(counts.items())),
                "exporter": {
                    "file_sha256": _read_stable_file(Path(__file__).resolve())[1].sha256,
                    "format_version": FORMAT_VERSION,
                },
                "format": {
                    "assistant_tool_calls": "OpenAI function-call objects",
                    "history_assistant_reasoning": "removed",
                    "loss_mask": "message.trainable; exactly one final assistant message is true",
                    "sample_unit": "one unique sampled assistant node with its root-to-node context",
                    "target": (
                        "authentic reasoning_content, content, and tool_calls; "
                        "the selected renderer supplies its stop token"
                    ),
                    "task_identity": "sha256 of canonical source task JSON",
                },
                "max_sequence_tokens": options.max_sequence_tokens,
                "selection": options.selection,
                "source_artifacts": {key: value.as_dict() for key, value in sorted(source_artifacts.items())},
                "split": {
                    "policy": "sha256(split_salt + NUL + task_sha256) modulo 10000",
                    "split_salt": options.split_salt,
                    "validation_permyriad": options.validation_permyriad,
                },
            }
            _write_json(temporary / "manifest.json", manifest)
            _fsync_dir(temporary / "train")
            _fsync_dir(temporary / "validation")
            _fsync_dir(temporary)
            if os.path.lexists(options.output_dir):
                raise ExportError("output_already_exists")
            os.replace(temporary, options.output_dir)
            _fsync_dir(output_parent)
            published = True
            return {
                "excluded_error_traces": counts["excluded_error_traces"],
                "input_traces": counts["input_traces"],
                "output_sha256": {
                    "manifest": _read_stable_file(options.output_dir / "manifest.json")[1].sha256,
                    "train": train_artifact.sha256,
                    "validation": validation_artifact.sha256,
                },
                "rows": {
                    "total": counts["emitted_rows"],
                    "train": counts["train_rows"],
                    "validation": counts["validation_rows"],
                },
                "selected_traces": counts["selected_traces"],
                "selection": options.selection,
                "status": "exported",
            }
        finally:
            source.close()
            for sink in (train_sink, validation_sink):
                if sink is not None and not sink._file.closed:
                    sink._file.close()
            if not published and temporary.exists():
                shutil.rmtree(temporary)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--selection", choices=("pass-only", "all-outcomes"), required=True)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--validation-permyriad", type=int, default=DEFAULT_VALIDATION_PERMYRIAD)
    parser.add_argument("--split-salt", default=DEFAULT_SPLIT_SALT)
    parser.add_argument("--max-sequence-tokens", type=int, default=DEFAULT_MAX_SEQUENCE_TOKENS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    options = ExportOptions(
        results=args.results,
        output_dir=args.output_dir,
        selection=args.selection,
        expected_count=args.expected_count,
        validation_permyriad=args.validation_permyriad,
        split_salt=args.split_salt,
        max_sequence_tokens=args.max_sequence_tokens,
    )
    try:
        summary = export_sft(options)
    except ExportError as error:
        print(json.dumps({"code": error.code, "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "internal_error", "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
