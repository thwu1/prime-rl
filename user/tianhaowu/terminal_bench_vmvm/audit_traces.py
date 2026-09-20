#!/usr/bin/env python3
"""Fail closed when rollout traces are unsuitable as retained training transcripts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from openai.types.chat import ChatCompletion
from verifiers.v1.dialects.chat import response_from_wire
from verifiers.v1.types import AssistantMessage, Response, Usage

DEFAULT_MAX_SEQUENCE_TOKENS = 262_144
FORBIDDEN_MODEL_REQUEST_FIELDS = frozenset({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"})
REPEATED_KDA_CHARACTER_THRESHOLD = 64
_SHA256_HEX_CHARS = frozenset("0123456789abcdef")
TRAINABLE_FINISH_REASONS = frozenset({"stop", "tool_calls"})


@dataclass(frozen=True, slots=True)
class CapturedModelIOContract:
    """Immutable expected semantics for every captured provider exchange."""

    provider_route: str
    request_model: str
    response_model: str
    reasoning_effort: str | None
    chat_template_kwargs: tuple[tuple[str, bool], ...]


KIMI_K3_MAX_MODEL_IO_CONTRACT = CapturedModelIOContract(
    provider_route="/chat/completions",
    request_model="Kimi-K3",
    response_model="Kimi-K3",
    reasoning_effort="max",
    chat_template_kwargs=(
        ("enable_thinking", True),
        ("preserve_thinking", True),
    ),
)
QWEN3_A95B_MODEL_IO_CONTRACT = CapturedModelIOContract(
    provider_route="/chat/completions",
    request_model="Qwen3.8-2.4T-A95B",
    response_model="Qwen3.8-2.4T-A95B",
    reasoning_effort="high",
    chat_template_kwargs=(
        ("enable_thinking", True),
        ("preserve_thinking", True),
    ),
)
QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT = CapturedModelIOContract(
    provider_route="/chat/completions",
    request_model="Qwen3.8-2.4T-A95B",
    response_model="Qwen3.8-2.4T-A95B",
    reasoning_effort=None,
    chat_template_kwargs=(
        ("enable_thinking", True),
        ("preserve_thinking", True),
    ),
)
QWEN3_A95B_MODEL_IO_CONTRACT_ID = "qwen3-a95b"
QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT_ID = "qwen3-a95b-epoch3"
QWEN3_A95B_REPAIRED_SFT_MODEL_IO_CONTRACT_ID = "qwen3-a95b-epoch3-source+qwen3-a95b-repair"
MODEL_IO_CONTRACTS = {
    "kimi-k3-max": KIMI_K3_MAX_MODEL_IO_CONTRACT,
    QWEN3_A95B_MODEL_IO_CONTRACT_ID: QWEN3_A95B_MODEL_IO_CONTRACT,
    QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT_ID: QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT,
}


def model_io_contract_value(contract: CapturedModelIOContract) -> dict[str, object]:
    return {
        "chat_template_kwargs": dict(contract.chat_template_kwargs),
        "provider_route": contract.provider_route,
        "reasoning_effort": {
            "presence": "forbidden" if contract.reasoning_effort is None else "required",
            "value": contract.reasoning_effort,
        },
        "request_model": contract.request_model,
        "response_model": contract.response_model,
    }


def model_io_contract_sha256(contract: CapturedModelIOContract) -> str:
    body = json.dumps(
        model_io_contract_value(contract),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def qwen_repair_trace_contracts_value() -> dict[str, dict[str, str]]:
    return {
        "repair": {
            "id": QWEN3_A95B_MODEL_IO_CONTRACT_ID,
            "sha256": model_io_contract_sha256(QWEN3_A95B_MODEL_IO_CONTRACT),
        },
        "source": {
            "id": QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT_ID,
            "sha256": model_io_contract_sha256(QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT),
        },
    }


class TraceJSONLError(ValueError):
    """A results JSONL record could not be decoded as a trace object."""


def _task_slug(trace: dict) -> str:
    task = trace.get("task") or {}
    if not isinstance(task, dict):
        return ""
    return task.get("slug") or str(task.get("name", "")).rsplit("/", 1)[-1]


def _valid_content(value: object) -> bool:
    if isinstance(value, str):
        return True
    if not isinstance(value, list):
        return False
    for part in value:
        if not isinstance(part, dict):
            return False
        if part.get("type") == "text":
            if not isinstance(part.get("text"), str):
                return False
        elif part.get("type") == "image_url":
            image_url = part.get("image_url")
            if not isinstance(image_url, dict) or not isinstance(image_url.get("url"), str):
                return False
        else:
            return False
    return True


def _valid_tool_arguments(value: object) -> bool:
    if not isinstance(value, str):
        return False

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError):
        return False

    def valid_json_value(item: object) -> bool:
        if item is None:
            return False
        if isinstance(item, float):
            return math.isfinite(item)
        if isinstance(item, dict):
            return all(valid_json_value(child) for child in item.values())
        if isinstance(item, list):
            return all(valid_json_value(child) for child in item)
        return isinstance(item, (bool, int, str))

    return isinstance(parsed, dict) and valid_json_value(parsed)


def _has_whitespace_separated_run(text: str, character: str, threshold: int) -> bool:
    """Detect a repeated character separated by whitespace, without joining unrelated text."""
    pattern = rf"{re.escape(character)}(?:\s*{re.escape(character)}){{{threshold - 1},}}"
    return re.search(pattern, text) is not None


def _message_problems(node: dict, index: int) -> list[str]:
    problems: list[str] = []
    message = node.get("message")
    if not isinstance(message, dict):
        return [f"node_{index}_message_missing"]
    role = message.get("role")
    if role not in {"system", "user", "assistant", "tool"}:
        return [f"node_{index}_message_role_invalid"]
    allowed_keys = {
        "system": {"role", "content"},
        "user": {"role", "content"},
        "assistant": {
            "role",
            "content",
            "provider_state",
            "reasoning_content",
            "reasoning_details",
            "tool_calls",
        },
        "tool": {"role", "content", "tool_call_id", "name"},
    }[role]
    required_keys = {"role"} if role == "assistant" else {"role", "content"}
    if not required_keys.issubset(message) or not set(message).issubset(allowed_keys):
        problems.append(f"node_{index}_message_keys_invalid")
    if node.get("sampled") is True and role != "assistant":
        problems.append(f"node_{index}_sampled_message_not_assistant")

    if role in {"system", "user", "tool"} and not _valid_content(message.get("content")):
        problems.append(f"node_{index}_{role}_content_invalid")
    if role == "tool":
        if not isinstance(message.get("tool_call_id"), str) or not message["tool_call_id"]:
            problems.append(f"node_{index}_tool_call_id_missing")
        name = message.get("name")
        if name is not None and not isinstance(name, str):
            problems.append(f"node_{index}_tool_name_invalid")
    if role == "assistant":
        content = message.get("content")
        reasoning = message.get("reasoning_content")
        tool_calls = message.get("tool_calls")
        if any(message.get(field) is not None for field in ("provider_state", "reasoning_details")):
            problems.append(f"node_{index}_unsupported_assistant_state")
        if content is not None and not isinstance(content, str):
            problems.append(f"node_{index}_assistant_content_invalid")
        if reasoning is not None and not isinstance(reasoning, str):
            problems.append(f"node_{index}_reasoning_content_invalid")
        if tool_calls is not None and not isinstance(tool_calls, list):
            problems.append(f"node_{index}_tool_calls_invalid")
        elif isinstance(tool_calls, list):
            seen_call_ids: set[str] = set()
            for call_index, call in enumerate(tool_calls):
                if not isinstance(call, dict):
                    problems.append(f"node_{index}_tool_call_{call_index}_not_an_object")
                    continue
                if set(call) != {"id", "name", "arguments"}:
                    problems.append(f"node_{index}_tool_call_{call_index}_keys_invalid")
                for field in ("id", "name", "arguments"):
                    value = call.get(field)
                    if not isinstance(value, str) or (field != "arguments" and not value):
                        problems.append(f"node_{index}_tool_call_{call_index}_{field}_invalid")
                if not _valid_tool_arguments(call.get("arguments")):
                    problems.append(f"node_{index}_tool_call_{call_index}_arguments_json_invalid")
                call_id = call.get("id")
                if isinstance(call_id, str) and call_id:
                    if call_id in seen_call_ids:
                        problems.append(f"node_{index}_tool_call_id_duplicate")
                    seen_call_ids.add(call_id)
        if not (
            (isinstance(content, str) and content.strip())
            or (isinstance(reasoning, str) and reasoning.strip())
            or (isinstance(tool_calls, list) and tool_calls)
        ):
            problems.append(f"node_{index}_assistant_payload_empty")
        if node.get("sampled") is True:
            finish_reason = node.get("finish_reason")
            if finish_reason is not None and finish_reason not in TRAINABLE_FINISH_REASONS:
                problems.append(f"node_{index}_finish_reason_invalid")
            repeated_characters = {"@": "at", "!": "bang"}
            for field_name, text in (("content", content), ("reasoning", reasoning)):
                if not isinstance(text, str):
                    continue
                for character, label in repeated_characters.items():
                    if _has_whitespace_separated_run(text, character, REPEATED_KDA_CHARACTER_THRESHOLD):
                        problems.append(f"node_{index}_repeated_{label}_in_{field_name}")
    return problems


def _ancestor_has_tool_call(nodes: list, index: int, tool_call_id: str) -> bool:
    parent = nodes[index].get("parent")
    seen: set[int] = set()
    while isinstance(parent, int) and not isinstance(parent, bool) and parent not in seen:
        if not 0 <= parent < len(nodes):
            return False
        seen.add(parent)
        ancestor = nodes[parent]
        if not isinstance(ancestor, dict):
            return False
        message = ancestor.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("id") == tool_call_id:
                    return True
        parent = ancestor.get("parent")
    return False


def _max_branch_tokens(nodes: list) -> tuple[int, list[int], bool]:
    """Return the longest root-to-node token path and graph integrity failures."""
    token_counts = [
        len(node.get("token_ids", [])) if isinstance(node, dict) and isinstance(node.get("token_ids"), list) else 0
        for node in nodes
    ]
    path_lengths: list[int | None] = [None] * len(nodes)
    resolved = [False] * len(nodes)
    invalid_parents: set[int] = set()
    parent_cycle = False

    for start in range(len(nodes)):
        if resolved[start]:
            continue
        trail: list[int] = []
        trail_members: set[int] = set()
        current = start
        prefix_length: int | None
        while True:
            if resolved[current]:
                prefix_length = path_lengths[current]
                break
            if current in trail_members:
                parent_cycle = True
                prefix_length = None
                break
            trail.append(current)
            trail_members.add(current)

            node = nodes[current]
            parent = node.get("parent") if isinstance(node, dict) else None
            if parent is None:
                prefix_length = 0
                break
            if isinstance(parent, bool) or not isinstance(parent, int) or not 0 <= parent < len(nodes):
                invalid_parents.add(current)
                prefix_length = None
                break
            current = parent

        for index in reversed(trail):
            if prefix_length is not None:
                prefix_length += token_counts[index]
            path_lengths[index] = prefix_length
            resolved[index] = True

    return max((length or 0 for length in path_lengths), default=0), sorted(invalid_parents), parent_cycle


def _usage_tokens(node: dict) -> tuple[int, int] | None:
    """Return provider-reported (sequence, completion) tokens for one sampled node."""
    usage = node.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    cached = usage.get("cached_input_tokens")
    if (
        isinstance(prompt, bool)
        or not isinstance(prompt, int)
        or prompt < 0
        or isinstance(completion, bool)
        or not isinstance(completion, int)
        or completion <= 0
        or (cached is not None and (isinstance(cached, bool) or not isinstance(cached, int) or cached < 0))
    ):
        return None
    return prompt + (cached or 0) + completion, completion


def _is_json_value(value: object) -> bool:
    """Whether a value has strict, finite JSON semantics."""
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _json_sha256(body: dict) -> str:
    """Match the verifier's deterministic hash of parsed provider JSON."""
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in _SHA256_HEX_CHARS for character in value)


def _valid_model_request(request: object) -> bool:
    if not isinstance(request, dict):
        return False
    kind = request.get("kind")
    if kind == "full":
        return (
            set(request) == {"kind", "sha256", "body"}
            and _valid_sha256(request.get("sha256"))
            and isinstance(request.get("body"), dict)
            and _is_json_value(request["body"])
        )
    if kind != "delta" or set(request) != {
        "kind",
        "sha256",
        "base_node",
        "set_fields",
        "remove_fields",
        "append_fields",
    }:
        return False

    base_node = request.get("base_node")
    set_fields = request.get("set_fields")
    remove_fields = request.get("remove_fields")
    append_fields = request.get("append_fields")
    if (
        not _valid_sha256(request.get("sha256"))
        or isinstance(base_node, bool)
        or not isinstance(base_node, int)
        or base_node < 0
        or not isinstance(set_fields, dict)
        or not _is_json_value(set_fields)
        or not isinstance(remove_fields, list)
        or any(not isinstance(key, str) for key in remove_fields)
        or len(remove_fields) != len(set(remove_fields))
        or not isinstance(append_fields, dict)
        or any(
            not isinstance(key, str) or not isinstance(values, list) or not values or not _is_json_value(values)
            for key, values in append_fields.items()
        )
    ):
        return False
    removed = set(remove_fields)
    set_keys = set(set_fields)
    append_keys = set(append_fields)
    return not ((removed & set_keys) | (removed & append_keys) | (set_keys & append_keys))


def _valid_model_response(response: object) -> bool:
    return (
        isinstance(response, dict)
        and set(response) == {"kind", "sha256", "body"}
        and response.get("kind") in {"exact_provider_json", "normalized_stream_response"}
        and _valid_sha256(response.get("sha256"))
        and isinstance(response.get("body"), dict)
        and _is_json_value(response["body"])
    )


def _valid_redundant_provider_specific_fields(message: object) -> bool:
    """Accept only LiteLLM's lossless duplicate of Kimi reasoning metadata."""
    if not isinstance(message, dict):
        return False
    if "provider_specific_fields" not in message:
        return True

    provider_fields = message["provider_specific_fields"]
    if (
        not isinstance(provider_fields, dict)
        or set(provider_fields) != {"reasoning", "refusal"}
        or provider_fields["refusal"] is not None
    ):
        return False
    provider_reasoning = provider_fields["reasoning"]
    if provider_reasoning is not None and not isinstance(provider_reasoning, str):
        return False

    direct_reasoning_fields = [field for field in ("reasoning", "reasoning_content") if field in message]
    if len(direct_reasoning_fields) > 1:
        return False
    direct_reasoning = message[direct_reasoning_fields[0]] if direct_reasoning_fields else None
    return (direct_reasoning is None or isinstance(direct_reasoning, str)) and (provider_reasoning == direct_reasoning)


def _response_node_problems(
    node: dict,
    index: int,
    response: dict,
    model_io_contract: CapturedModelIOContract | None,
) -> list[str]:
    """Reparse captured response semantics exactly as Verifiers did before graph commit."""
    body = response["body"]
    if response["kind"] == "exact_provider_json":
        choices = body.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            return [f"node_{index}_model_io_response_semantics_invalid"]
        raw_finish_reason = choices[0].get("finish_reason")
        if not _valid_redundant_provider_specific_fields(choices[0].get("message")):
            return [f"node_{index}_model_io_response_semantics_invalid"]
    else:
        raw_finish_reason = body.get("finish_reason")
    if raw_finish_reason not in TRAINABLE_FINISH_REASONS:
        return [f"node_{index}_model_io_response_finish_reason_invalid"]

    try:
        node_message_body = node.get("message")
        if isinstance(node_message_body, dict) and node_message_body.get("reasoning_details") is None:
            node_message_body = dict(node_message_body)
            node_message_body.pop("reasoning_details", None)
        if response["kind"] == "exact_provider_json":
            parsed = response_from_wire(ChatCompletion.model_validate(body))
        else:
            parsed = Response.model_validate(body)
        node_message = AssistantMessage.model_validate(node_message_body)
        node_usage = Usage.model_validate(node["usage"]) if node.get("usage") is not None else None
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return [f"node_{index}_model_io_response_semantics_invalid"]

    problems: list[str] = []
    if parsed.message.model_dump(mode="json") != node_message.model_dump(mode="json"):
        problems.append(f"node_{index}_model_io_response_message_mismatch")
    if parsed.finish_reason != node.get("finish_reason"):
        problems.append(f"node_{index}_model_io_response_finish_reason_mismatch")
    parsed_usage = parsed.usage.model_dump(mode="json") if parsed.usage is not None else None
    normalized_node_usage = node_usage.model_dump(mode="json") if node_usage is not None else None
    if parsed_usage != normalized_node_usage:
        problems.append(f"node_{index}_model_io_response_usage_mismatch")
    if model_io_contract is not None and parsed.model != model_io_contract.response_model:
        problems.append(f"node_{index}_model_io_response_model_mismatch")
    return problems


def _captured_zero_reasoning_tool_turn(
    node: dict,
    request_body: dict | None = None,
) -> str | None:
    """Classify a hash-bound tool turn that proves no reasoning was exposed."""
    model_io = node.get("model_io")
    if not isinstance(model_io, dict):
        return None
    response = model_io.get("response")
    if not _valid_model_response(response) or _json_sha256(response["body"]) != response["sha256"]:
        return None

    body = response["body"]
    reasoning_token_values: list[object] = []
    if response["kind"] == "exact_provider_json":
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return None
        message = choices[0].get("message")
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return None
        completion_details = usage.get("completion_tokens_details")
        if completion_details is not None and not isinstance(completion_details, dict):
            return None
        # Verifiers reads exact chat-completion reasoning usage only from the
        # nested details object. Do not let an ignored top-level extra certify
        # a turn that the captured/flattened usage considers unknown.
        if "reasoning_tokens" in usage:
            return None
        if isinstance(completion_details, dict) and "reasoning_tokens" in completion_details:
            reasoning_token_values.append(completion_details["reasoning_tokens"])
    else:
        message = body.get("message")
        usage = body.get("usage")
        if not isinstance(usage, dict) or "reasoning_tokens" not in usage:
            return None
        reasoning_token_values.append(usage["reasoning_tokens"])

    if any(not isinstance(value, int) or isinstance(value, bool) or value != 0 for value in reasoning_token_values):
        return None
    provider_reported_zero = bool(reasoning_token_values)

    if not isinstance(message, dict):
        return None
    if not _valid_redundant_provider_specific_fields(message):
        return None
    reasoning_values: list[object] = []
    reasoning_details_values: list[object] = []
    explicit_empty_reasoning = False
    for field in ("reasoning", "reasoning_content"):
        if field in message:
            value = message[field]
            reasoning_values.append(value)
            explicit_empty_reasoning |= isinstance(value, str) and not value.strip()
    if "reasoning_details" in message:
        value = message["reasoning_details"]
        reasoning_details_values.append(value)
        explicit_empty_reasoning |= value == []
    provider_fields = message.get("provider_specific_fields")
    if provider_fields is not None:
        if not isinstance(provider_fields, dict):
            return None
        for field in ("reasoning", "reasoning_content"):
            if field in provider_fields:
                value = provider_fields[field]
                reasoning_values.append(value)
                explicit_empty_reasoning |= isinstance(value, str) and not value.strip()
        if "reasoning_details" in provider_fields:
            value = provider_fields["reasoning_details"]
            reasoning_details_values.append(value)
            explicit_empty_reasoning |= value == []
    if any(value is not None and (not isinstance(value, str) or value.strip()) for value in reasoning_values):
        return None
    if any(value is not None and (not isinstance(value, list) or value) for value in reasoning_details_values):
        return None

    provider_calls = message.get("tool_calls")
    flattened_message = node.get("message")
    flattened_calls = flattened_message.get("tool_calls") if isinstance(flattened_message, dict) else None
    if not isinstance(provider_calls, list) or not provider_calls or not isinstance(flattened_calls, list):
        return None

    normalized_provider_calls: list[tuple[str, str, str]] = []
    for call in provider_calls:
        if not isinstance(call, dict) or not isinstance(call.get("id"), str):
            return None
        if response["kind"] == "exact_provider_json":
            function = call.get("function")
            if not isinstance(function, dict):
                return None
            name = function.get("name")
            arguments = function.get("arguments")
        else:
            name = call.get("name")
            arguments = call.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, str):
            return None
        normalized_provider_calls.append((call["id"], name, arguments))

    normalized_flattened_calls: list[tuple[str, str, str]] = []
    for call in flattened_calls:
        if (
            not isinstance(call, dict)
            or not isinstance(call.get("id"), str)
            or not isinstance(call.get("name"), str)
            or not isinstance(call.get("arguments"), str)
        ):
            return None
        normalized_flattened_calls.append((call["id"], call["name"], call["arguments"]))
    if normalized_provider_calls != normalized_flattened_calls:
        return None

    if provider_reported_zero:
        return "provider_reported_zero"
    if response["kind"] != "exact_provider_json" or not explicit_empty_reasoning:
        return None
    template = request_body.get("chat_template_kwargs") if isinstance(request_body, dict) else None
    if (
        isinstance(template, dict)
        and template.get("enable_thinking") is True
        and template.get("preserve_thinking") is True
    ):
        return "provider_explicit_empty"
    return None


def _model_io_base_is_ancestor(nodes: list, node_id: int, base_node: int) -> bool:
    parent = nodes[node_id].get("parent")
    seen: set[int] = set()
    while parent is not None:
        if isinstance(parent, bool) or not isinstance(parent, int) or not 0 <= parent < len(nodes):
            return False
        if parent == base_node:
            return True
        if parent in seen:
            return False
        seen.add(parent)
        ancestor = nodes[parent]
        if not isinstance(ancestor, dict):
            return False
        parent = ancestor.get("parent")
    return False


def _prompt_content(value: object) -> object:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ValueError("content")
    normalized: list[dict] = []
    for part in value:
        if not isinstance(part, dict):
            raise ValueError("content")
        if part.get("type") == "text" and set(part) == {"type", "text"} and isinstance(part.get("text"), str):
            normalized.append({"type": "text", "text": part["text"]})
            continue
        image_url = part.get("image_url")
        if (
            part.get("type") == "image_url"
            and set(part) == {"type", "image_url"}
            and isinstance(image_url, dict)
            and set(image_url) == {"url"}
            and isinstance(image_url.get("url"), str)
        ):
            normalized.append({"type": "image_url", "image_url": {"url": image_url["url"]}})
            continue
        raise ValueError("content")
    return normalized


def _prompt_tool_calls(value: object, *, wire: bool) -> list[dict] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("tool_calls")
    normalized: list[dict] = []
    for call in value:
        if not isinstance(call, dict):
            raise ValueError("tool_calls")
        if wire:
            if set(call) != {"id", "type", "function"} or call.get("type") != "function":
                raise ValueError("tool_calls")
            function = call.get("function")
            if not isinstance(function, dict) or set(function) != {"name", "arguments"}:
                raise ValueError("tool_calls")
        else:
            if set(call) != {"id", "name", "arguments"}:
                raise ValueError("tool_calls")
            function = call
        call_id = call.get("id")
        name = function.get("name")
        arguments = function.get("arguments")
        if (
            not isinstance(call_id, str)
            or not call_id
            or not isinstance(name, str)
            or not name
            or not _valid_tool_arguments(arguments)
        ):
            raise ValueError("tool_calls")
        normalized.append({"id": call_id, "name": name, "arguments": arguments})
    return normalized


def _prompt_messages(messages: object, *, wire: bool) -> list[dict]:
    if not isinstance(messages, list):
        raise ValueError("messages")
    tool_names: dict[str, str] = {}
    normalized: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("message")
        role = message.get("role")
        if role in {"system", "user"}:
            if set(message) != {"role", "content"}:
                raise ValueError("message")
            normalized.append({"role": role, "content": _prompt_content(message["content"])})
            continue
        if role == "tool":
            if not {"role", "content", "tool_call_id"}.issubset(message) or not set(message).issubset(
                {"role", "content", "tool_call_id", "name"}
            ):
                raise ValueError("message")
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                raise ValueError("message")
            name = message.get("name")
            if name is None:
                name = tool_names.get(call_id)
            if name is not None and (not isinstance(name, str) or not name):
                raise ValueError("message")
            normalized.append(
                {
                    "role": "tool",
                    "content": _prompt_content(message["content"]),
                    "tool_call_id": call_id,
                    "name": name,
                }
            )
            continue
        if role != "assistant":
            raise ValueError("message")
        allowed = {
            "role",
            "content",
            "provider_state",
            "reasoning_details",
            "tool_calls",
            "reasoning_content",
        }
        if wire:
            allowed.add("reasoning")
            allowed.add("provider_specific_fields")
        if "role" not in message or not set(message).issubset(allowed):
            raise ValueError("message")
        if wire and "reasoning" in message and "reasoning_content" in message:
            raise ValueError("message")
        if wire and not _valid_redundant_provider_specific_fields(message):
            raise ValueError("message")
        if any(message.get(field) is not None for field in ("provider_state", "reasoning_details")):
            raise ValueError("message")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("message")
        normalized_message = {"role": "assistant", "content": content}
        reasoning_field = "reasoning" if wire and "reasoning" in message else "reasoning_content"
        if reasoning_field in message:
            reasoning = message[reasoning_field]
            if reasoning is not None and not isinstance(reasoning, str):
                raise ValueError("message")
            normalized_message["reasoning_content"] = reasoning
        calls = None
        if "tool_calls" in message:
            calls = _prompt_tool_calls(message["tool_calls"], wire=wire)
            normalized_message["tool_calls"] = calls
        normalized.append(normalized_message)
        for call in calls or []:
            if call["id"] in tool_names:
                raise ValueError("tool_calls")
            tool_names[call["id"]] = call["name"]
    return normalized


def _graph_prompt_messages(nodes: list, node_id: int) -> list[dict] | None:
    """Return the exhaustively validated root-to-parent messages."""
    path: list[int] = []
    seen: set[int] = set()
    current = nodes[node_id].get("parent")
    while current is not None:
        if (
            isinstance(current, bool)
            or not isinstance(current, int)
            or not 0 <= current < len(nodes)
            or current in seen
        ):
            return None
        seen.add(current)
        path.append(current)
        ancestor = nodes[current]
        if not isinstance(ancestor, dict):
            return None
        current = ancestor.get("parent")
    path.reverse()

    try:
        return _prompt_messages([nodes[path_id].get("message") for path_id in path], wire=False)
    except ValueError:
        return None


def _request_graph_message_problem(nodes: list, node_id: int, request_body: dict) -> str | None:
    """Prove the persisted graph prompt matches the provider-visible chat request."""
    try:
        request_messages = _prompt_messages(request_body.get("messages"), wire=True)
    except ValueError:
        return "model_io_request_messages_invalid"
    graph_messages = _graph_prompt_messages(nodes, node_id)
    if graph_messages is None:
        return "model_io_request_messages_invalid"
    if request_messages != graph_messages:
        return "model_io_request_messages_mismatch"
    return None


class _ModelIOReconstructionError(ValueError):
    """A structurally valid request delta could not be safely reconstructed."""


def _audit_model_io(
    nodes: list,
    model_io_contract: CapturedModelIOContract | None = None,
    *,
    require_request_graph_match: bool = False,
    require_exact_provider_json: bool = False,
) -> tuple[list[str], int, dict[int, dict]]:
    """Validate and reconstruct all sampled-turn provider captures."""
    problems: list[str] = []
    sampled_ids: list[int] = []
    valid_requests: dict[int, dict] = {}
    model_io_turns = 0

    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        sampled = node.get("sampled") is True
        model_io = node.get("model_io")
        if not sampled:
            if model_io is not None:
                problems.append(f"node_{index}_model_io_on_non_sampled_node")
            continue
        sampled_ids.append(index)
        if model_io is None:
            problems.append(f"node_{index}_model_io_missing")
            continue
        model_io_turns += 1
        if not isinstance(model_io, dict) or set(model_io) != {"provider_route", "request", "response"}:
            problems.append(f"node_{index}_model_io_structure_invalid")
            continue

        provider_route = model_io.get("provider_route")
        if not isinstance(provider_route, str) or not provider_route.startswith("/"):
            problems.append(f"node_{index}_model_io_provider_route_invalid")
        elif model_io_contract is not None and provider_route != model_io_contract.provider_route:
            problems.append(f"node_{index}_model_io_provider_route_contract_mismatch")
        elif provider_route != "/chat/completions":
            problems.append(f"node_{index}_model_io_provider_route_invalid")
        request = model_io.get("request")
        if not _valid_model_request(request):
            problems.append(f"node_{index}_model_io_request_structure_invalid")
        else:
            valid_requests[index] = request
        response = model_io.get("response")
        if not _valid_model_response(response):
            problems.append(f"node_{index}_model_io_response_structure_invalid")
        else:
            if require_exact_provider_json and response["kind"] != "exact_provider_json":
                problems.append("normalized_stream_response_disallowed")
            if _json_sha256(response["body"]) != response["sha256"]:
                problems.append(f"node_{index}_model_io_response_hash_mismatch")
            else:
                problems.extend(_response_node_problems(node, index, response, model_io_contract))

    memo: dict[int, dict] = {}

    def reconstruct(node_id: int) -> dict:
        if node_id in memo:
            return copy.deepcopy(memo[node_id])
        chain: list[int] = []
        chain_members: set[int] = set()
        current_id = node_id
        while current_id not in memo:
            if current_id in chain_members:
                raise _ModelIOReconstructionError("request_delta_cycle")
            request = valid_requests.get(current_id)
            if request is None:
                raise _ModelIOReconstructionError("request_chain_invalid")
            chain.append(current_id)
            chain_members.add(current_id)
            if request["kind"] == "full":
                break
            base_node = request["base_node"]
            if base_node in chain_members:
                raise _ModelIOReconstructionError("request_delta_cycle")
            if base_node >= current_id or base_node >= len(nodes):
                raise _ModelIOReconstructionError("request_delta_base_not_prior")
            base = nodes[base_node]
            if not isinstance(base, dict) or base.get("sampled") is not True:
                raise _ModelIOReconstructionError("request_delta_base_not_sampled")
            if not _model_io_base_is_ancestor(nodes, current_id, base_node):
                raise _ModelIOReconstructionError("request_delta_base_not_ancestor")
            current_id = base_node

        body = copy.deepcopy(memo[current_id]) if current_id in memo else None
        for current_id in reversed(chain):
            request = valid_requests[current_id]
            if request["kind"] == "full":
                body = copy.deepcopy(request["body"])
            else:
                if body is None:  # defensive: every delta chain must terminate at a full or memoized request
                    raise _ModelIOReconstructionError("request_chain_invalid")
                for key in request["remove_fields"]:
                    body.pop(key, None)
                for key, value in request["set_fields"].items():
                    body[key] = copy.deepcopy(value)
                for key, suffix in request["append_fields"].items():
                    previous = body.get(key)
                    if not isinstance(previous, list):
                        raise _ModelIOReconstructionError("request_delta_append_target_not_list")
                    body[key] = [*previous, *copy.deepcopy(suffix)]
            if _json_sha256(body) != request["sha256"]:
                raise _ModelIOReconstructionError("request_hash_mismatch")
            memo[current_id] = copy.deepcopy(body)
        return copy.deepcopy(memo[node_id])

    found_tool_schemas = False
    for node_id in sampled_ids:
        if node_id not in valid_requests:
            continue
        try:
            request_body = reconstruct(node_id)
        except _ModelIOReconstructionError as error:
            problems.append(f"node_{node_id}_model_io_{error}")
            continue
        if forbidden := sorted(FORBIDDEN_MODEL_REQUEST_FIELDS & request_body.keys()):
            problems.append(f"node_{node_id}_model_io_forbidden_request_fields={forbidden!r}")
        if model_io_contract is not None:
            if request_body.get("model") != model_io_contract.request_model:
                problems.append(f"node_{node_id}_model_io_request_model_mismatch")
            if (
                model_io_contract.reasoning_effort is None
                and "reasoning_effort" in request_body
            ) or (
                model_io_contract.reasoning_effort is not None
                and request_body.get("reasoning_effort") != model_io_contract.reasoning_effort
            ):
                problems.append(f"node_{node_id}_model_io_request_reasoning_effort_mismatch")
            observed_thinking = request_body.get("chat_template_kwargs")
            expected_thinking = dict(model_io_contract.chat_template_kwargs)
            if (
                not isinstance(observed_thinking, dict)
                or set(observed_thinking) != set(expected_thinking)
                or any(
                    observed_thinking[key] is not expected_value
                    for key, expected_value in model_io_contract.chat_template_kwargs
                )
            ):
                problems.append(f"node_{node_id}_model_io_request_chat_template_kwargs_mismatch")
        model_io = nodes[node_id].get("model_io")
        if (
            require_request_graph_match
            and isinstance(model_io, dict)
            and model_io.get("provider_route") == "/chat/completions"
        ):
            if message_problem := _request_graph_message_problem(nodes, node_id, request_body):
                problems.append(f"node_{node_id}_{message_problem}")
        tools = request_body.get("tools")
        if isinstance(tools, list) and tools and all(isinstance(tool, dict) and tool for tool in tools):
            found_tool_schemas = True

    if sampled_ids and not found_tool_schemas:
        problems.append("no_model_io_tool_schemas")
    return problems, model_io_turns, memo


def _audit_trace(
    trace: dict,
    require_reasoning: bool,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
    require_token_data: bool = False,
    require_logprobs: bool = False,
    require_model_io: bool = False,
    model_io_contract: CapturedModelIOContract | None = None,
    require_request_graph_match: bool = False,
    observations: Counter[str] | None = None,
    require_exact_provider_json: bool = False,
) -> list[str]:
    # Requiring logprobs necessarily opts into exact token-array validation.
    require_token_data = require_token_data or require_logprobs
    require_model_io = (
        require_model_io or model_io_contract is not None or require_request_graph_match or require_exact_provider_json
    )
    problems: list[str] = []
    if trace.get("errors"):
        problems.append("trace_has_errors")
    nodes = trace.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return [*problems, "no_message_nodes"]

    model_io_problems: list[str] = []
    reconstructed_requests: dict[int, dict] = {}
    if require_model_io:
        model_io_problems, _model_io_turns, reconstructed_requests = _audit_model_io(
            nodes,
            model_io_contract,
            require_request_graph_match=require_request_graph_match,
            require_exact_provider_json=require_exact_provider_json,
        )

    max_branch_tokens, invalid_parents, parent_cycle = _max_branch_tokens(nodes)

    sampled_node_count = 0
    sampled_reasoning_count = 0
    sampled_tokens = 0
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            problems.append(f"node_{index}_not_an_object")
            continue

        problems.extend(_message_problems(node, index))

        is_sampled = node.get("sampled") is True
        reasoning_not_retained = False
        if is_sampled:
            sampled_node_count += 1
            message = node.get("message")
            reasoning = message.get("reasoning_content") if isinstance(message, dict) else None
            if isinstance(reasoning, str) and reasoning.strip():
                sampled_reasoning_count += 1
            elif require_reasoning:
                zero_reasoning_evidence = (
                    _captured_zero_reasoning_tool_turn(node, reconstructed_requests.get(index))
                    if require_model_io
                    else None
                )
                if zero_reasoning_evidence is None:
                    reasoning_not_retained = True
                elif observations is not None:
                    observations[f"{zero_reasoning_evidence}_reasoning_tool_turns"] += 1
        if not require_token_data:
            if is_sampled:
                if reasoning_not_retained:
                    problems.append(f"node_{index}_reasoning_content_not_retained")
                usage = node.get("usage")
                usage_tokens = _usage_tokens(node)
                if usage is None:
                    problems.append(f"node_{index}_usage_not_retained")
                elif usage_tokens is None:
                    problems.append(f"node_{index}_usage_invalid")
                elif usage_tokens[0] > max_sequence_tokens:
                    problems.append(f"node_{index}_usage_sequence_tokens={usage_tokens[0]} limit={max_sequence_tokens}")
            continue
        token_ids = node.get("token_ids")
        mask = node.get("mask")
        logprobs = node.get("logprobs")
        if not isinstance(token_ids, list) or not isinstance(mask, list) or not isinstance(logprobs, list):
            problems.append(f"node_{index}_missing_token_arrays")
            if is_sampled:
                if not token_ids:
                    problems.append(f"node_{index}_sampled_token_ids_empty")
                if not mask:
                    problems.append(f"node_{index}_sampled_mask_empty")
                if require_logprobs and not logprobs:
                    problems.append(f"node_{index}_sampled_logprobs_empty")
                if reasoning_not_retained:
                    problems.append(f"node_{index}_reasoning_content_not_retained")
            continue
        if any(isinstance(value, bool) or not isinstance(value, int) for value in token_ids):
            problems.append(f"node_{index}_token_ids_not_ints")
        if any(not isinstance(value, bool) for value in mask):
            problems.append(f"node_{index}_mask_not_bools")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            for value in logprobs
        ):
            problems.append(f"node_{index}_logprobs_not_finite_numbers")
        if len(token_ids) != len(mask):
            problems.append(f"node_{index}_token_mask_mismatch")
        expected_logprobs = sum(value is True for value in mask)
        valid_logprob_lengths = {expected_logprobs} if require_logprobs else {0, expected_logprobs}
        if len(logprobs) not in valid_logprob_lengths:
            problems.append(f"node_{index}_logprob_mismatch")
        if is_sampled:
            if not token_ids:
                problems.append(f"node_{index}_sampled_token_ids_empty")
            if not mask:
                problems.append(f"node_{index}_sampled_mask_empty")
            if require_logprobs and not logprobs:
                problems.append(f"node_{index}_sampled_logprobs_empty")
            sampled_tokens += expected_logprobs
            if reasoning_not_retained:
                problems.append(f"node_{index}_reasoning_content_not_retained")
    if sampled_node_count == 0:
        problems.append("no_sampled_assistant_nodes")
    if require_reasoning and require_model_io and sampled_node_count and sampled_reasoning_count == 0:
        problems.append("no_sampled_reasoning_content")
    if require_token_data and sampled_tokens == 0:
        problems.append("no_sampled_tokens")

    if require_model_io:
        problems.extend(model_io_problems)

    if not invalid_parents and not parent_cycle:
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            message = node.get("message")
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            tool_call_id = message.get("tool_call_id")
            if (
                isinstance(tool_call_id, str)
                and tool_call_id
                and not _ancestor_has_tool_call(nodes, index, tool_call_id)
            ):
                problems.append(f"node_{index}_tool_call_not_in_ancestors")
    problems.extend(f"node_{index}_invalid_parent" for index in invalid_parents)
    if parent_cycle:
        problems.append("parent_cycle")
    if require_token_data and max_branch_tokens > max_sequence_tokens:
        problems.append(f"max_sequence_tokens={max_branch_tokens} limit={max_sequence_tokens}")
    return problems


def _iter_traces(results: Path) -> Iterator[dict]:
    """Yield non-empty JSONL records without retaining the input file."""
    with results.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    trace = json.loads(line)
                except json.JSONDecodeError as error:
                    raise TraceJSONLError(f"{results}: invalid JSON on line {line_number}: {error.msg}") from None
                if not isinstance(trace, dict):
                    raise TraceJSONLError(f"{results}: invalid trace on line {line_number}: expected a JSON object")
                yield trace


def _read_expected_slugs(task_file: Path) -> set[str]:
    with task_file.open(encoding="utf-8") as handle:
        return {line.strip().split("\t", 1)[0] for line in handle if line.strip() and not line.lstrip().startswith("#")}


def _summarize_traces(
    traces: Iterable[dict],
    *,
    expected_slugs: set[str] | None,
    expected_count: int | None,
    rollouts_per_task: int,
    require_reasoning: bool,
    require_logprobs: bool = False,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
    require_token_data: bool = False,
    require_model_io: bool = False,
    aggregate_only: bool = False,
    model_io_contract: CapturedModelIOContract | None = None,
    require_request_graph_match: bool = False,
    require_exact_provider_json: bool = False,
) -> tuple[dict, bool]:
    require_token_data = require_token_data or require_logprobs
    require_model_io = (
        require_model_io or model_io_contract is not None or require_request_graph_match or require_exact_provider_json
    )
    trace_count = 0
    sampled_tokens = 0
    model_io_turns = 0
    reasoning_observations: Counter[str] = Counter()
    trace_failure_count = 0
    failure_examples: list[dict] = []
    problem_counts: Counter[str] = Counter()
    seen_ids: set[object] = set()
    duplicate_trace_ids = False
    per_task: Counter[str] = Counter()

    for trace in traces:
        trace_count += 1
        trace_id = trace.get("id")
        if trace_id in seen_ids:
            duplicate_trace_ids = True
        else:
            seen_ids.add(trace_id)

        slug = _task_slug(trace)
        per_task[slug] += 1
        problems = _audit_trace(
            trace,
            require_reasoning,
            max_sequence_tokens,
            require_token_data=require_token_data,
            require_logprobs=require_logprobs,
            require_model_io=require_model_io,
            model_io_contract=model_io_contract,
            require_request_graph_match=require_request_graph_match,
            require_exact_provider_json=require_exact_provider_json,
            observations=reasoning_observations,
        )
        if problems:
            trace_failure_count += 1
            problem_counts.update(re.sub(r"^node_[0-9]+_", "node_", problem).split("=", 1)[0] for problem in problems)
            if not aggregate_only and len(failure_examples) < 50:
                failure_examples.append({"id": trace_id, "task": slug, "problems": problems})

        nodes = trace.get("nodes")
        if require_model_io and isinstance(nodes, list):
            model_io_turns += sum(
                node.get("sampled") is True and node.get("model_io") is not None
                for node in nodes
                if isinstance(node, dict)
            )
        if isinstance(nodes, list) and require_token_data:
            sampled_tokens += sum(
                sum(value is True for value in mask)
                for node in nodes
                if isinstance(node, dict) and isinstance((mask := node.get("mask")), list)
            )
        elif isinstance(nodes, list):
            sampled_tokens += sum(
                usage_tokens[1]
                for node in nodes
                if isinstance(node, dict)
                and node.get("sampled") is True
                and (usage_tokens := _usage_tokens(node)) is not None
            )

    global_problems = []
    if expected_count is not None and trace_count != expected_count:
        global_problems.append(f"trace_count={trace_count} expected={expected_count}")
    if duplicate_trace_ids:
        global_problems.append("duplicate_trace_ids")
    if expected_slugs is not None:
        observed = set(per_task)
        if missing := sorted(expected_slugs - observed):
            if aggregate_only:
                global_problems.append(f"missing_tasks_count={len(missing)}")
            else:
                global_problems.append(f"missing_tasks={missing[:20]!r} count={len(missing)}")
        if extra := sorted(observed - expected_slugs):
            if aggregate_only:
                global_problems.append(f"unexpected_tasks_count={len(extra)}")
            else:
                global_problems.append(f"unexpected_tasks={extra[:20]!r} count={len(extra)}")
        wrong_multiplicity = {
            slug: per_task.get(slug, 0) for slug in expected_slugs if per_task.get(slug, 0) != rollouts_per_task
        }
        if wrong_multiplicity:
            if aggregate_only:
                global_problems.append(f"wrong_rollout_multiplicity_count={len(wrong_multiplicity)}")
            else:
                global_problems.append(
                    f"wrong_rollout_multiplicity={dict(list(sorted(wrong_multiplicity.items()))[:20])!r}"
                )

    summary = {
        "traces": trace_count,
        "tasks": len(per_task),
        "sampled_tokens": sampled_tokens,
        "trace_failures": trace_failure_count,
        "global_problems": global_problems,
    }
    if aggregate_only:
        summary["problem_counts"] = dict(sorted(problem_counts.items()))
    else:
        summary["failure_examples"] = failure_examples
    if require_model_io:
        summary["model_io_turns"] = model_io_turns
    if require_model_io and require_reasoning:
        summary["provider_reported_zero_reasoning_tool_turns"] = reasoning_observations[
            "provider_reported_zero_reasoning_tool_turns"
        ]
        summary["provider_explicit_empty_reasoning_tool_turns"] = reasoning_observations[
            "provider_explicit_empty_reasoning_tool_turns"
        ]
    return summary, bool(trace_failure_count or global_problems)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected-task-file", type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--rollouts-per-task", type=int, default=1)
    parser.add_argument("--require-reasoning", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--require-model-io",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="require and integrity-check exact provider request/response capture for every sampled turn",
    )
    parser.add_argument(
        "--require-request-graph-match",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="require each captured chat request's messages to match the persisted graph prompt path",
    )
    parser.add_argument(
        "--require-exact-provider-json",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="reject normalized streaming responses that do not retain the exact provider JSON",
    )
    parser.add_argument(
        "--require-token-data",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "require exact token IDs and masks instead of the default response/reasoning transcript with provider usage"
        ),
    )
    parser.add_argument(
        "--require-logprobs",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="also require one finite logprob per sampled token (implies --require-token-data)",
    )
    parser.add_argument(
        "--max-sequence-tokens",
        type=int,
        default=DEFAULT_MAX_SEQUENCE_TOKENS,
        help="fail traces with any reconstructed branch longer than this (default: %(default)s)",
    )
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="omit trace IDs, task identifiers, and failure examples from output",
    )
    parser.add_argument(
        "--model-io-contract",
        choices=tuple(MODEL_IO_CONTRACTS),
        help="require every captured exchange to satisfy this immutable production contract",
    )
    args = parser.parse_args()

    if args.max_sequence_tokens < 1:
        parser.error("--max-sequence-tokens must be positive")

    expected_slugs = None
    if args.expected_task_file:
        expected_slugs = _read_expected_slugs(args.expected_task_file)
    expected_count = args.expected_count
    if expected_count is None and expected_slugs is not None:
        expected_count = len(expected_slugs) * args.rollouts_per_task

    try:
        summary, failed = _summarize_traces(
            _iter_traces(args.results),
            expected_slugs=expected_slugs,
            expected_count=expected_count,
            rollouts_per_task=args.rollouts_per_task,
            require_reasoning=args.require_reasoning,
            max_sequence_tokens=args.max_sequence_tokens,
            require_token_data=args.require_token_data,
            require_logprobs=args.require_logprobs,
            require_model_io=args.require_model_io,
            aggregate_only=args.aggregate_only,
            model_io_contract=MODEL_IO_CONTRACTS.get(args.model_io_contract),
            require_request_graph_match=args.require_request_graph_match and args.require_model_io,
            require_exact_provider_json=args.require_exact_provider_json,
        )
    except TraceJSONLError as error:
        parser.error(str(error))
    print(json.dumps(summary, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
