import hashlib
import json
import sys
from pathlib import Path

import pytest
from audit_traces import (
    KIMI_K3_MAX_MODEL_IO_CONTRACT,
    _audit_trace,
    _captured_zero_reasoning_tool_turn,
    _iter_traces,
    _summarize_traces,
    _valid_tool_arguments,
    main,
)


def _trace(trace_id: str, slug: str, *, valid: bool = True) -> dict:
    node = {
        "sampled": True,
        "token_ids": [101, 102],
        "mask": [True, True],
        "logprobs": [-0.1, -0.2] if valid else [-0.1],
        "message": {
            "role": "assistant",
            "content": None,
            "reasoning_content": "reasoning",
            "tool_calls": None,
        },
        "usage": {"prompt_tokens": 100, "completion_tokens": 2},
        "finish_reason": "stop",
    }
    return {
        "id": trace_id,
        "task": {"slug": slug},
        "nodes": [node],
    }


def _transcript_trace(trace_id: str = "text", slug: str = "text-task") -> dict:
    return {
        "id": trace_id,
        "task": {"slug": slug},
        "nodes": [
            {
                "parent": None,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {
                    "role": "assistant",
                    "content": "retained response",
                    "reasoning_content": "retained reasoning",
                },
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            }
        ],
    }


def _digest(body: dict) -> str:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _request(*, tools: list | None = None, **extra: object) -> dict:
    return {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {
            "enable_thinking": True,
            "preserve_thinking": True,
        },
        "messages": [{"role": "user", "content": "inspect the workspace"}],
        "tools": tools
        if tools is not None
        else [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a command",
                    "parameters": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                    },
                },
            }
        ],
        **extra,
    }


def _exact_response(
    *,
    message: dict | None = None,
    finish_reason: str = "stop",
    usage: dict | None = None,
) -> dict:
    return {
        "id": "response-1",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": message
                or {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "reasoning",
                },
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 100,
            "completion_tokens": 2,
            "total_tokens": 102,
        },
    }


def _model_io(request: dict, *, response: dict | None = None) -> dict:
    response = response or _exact_response()
    return {
        "provider_route": "/chat/completions",
        "request": {"kind": "full", "sha256": _digest(request), "body": request},
        "response": {
            "kind": "exact_provider_json",
            "sha256": _digest(response),
            "body": response,
        },
    }


def _trace_with_model_io(trace_id: str = "model-io", slug: str = "model-io-task") -> dict:
    trace = _trace(trace_id, slug)
    trace["nodes"][0]["model_io"] = _model_io(_request())
    return trace


def test_iter_traces_opens_lazily_and_skips_blank_lines(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps(_trace("old", "old-task")))
    traces = _iter_traces(results)

    results.write_text(f"\n{json.dumps(_trace('new', 'new-task'))}\n\n")

    assert [trace["id"] for trace in traces] == ["new"]


def test_summarize_traces_preserves_validation_report() -> None:
    traces = (
        trace
        for trace in [
            _trace("duplicate", "task-a"),
            _trace("duplicate", "task-a", valid=False),
            _trace("third", "unexpected"),
        ]
    )

    summary, failed = _summarize_traces(
        traces,
        expected_slugs={"task-a", "missing"},
        expected_count=4,
        rollouts_per_task=1,
        require_reasoning=True,
        require_token_data=True,
    )

    assert failed is True
    assert summary == {
        "traces": 3,
        "tasks": 2,
        "sampled_tokens": 6,
        "trace_failures": 1,
        "global_problems": [
            "trace_count=3 expected=4",
            "duplicate_trace_ids",
            "missing_tasks=['missing'] count=1",
            "unexpected_tasks=['unexpected'] count=1",
            "wrong_rollout_multiplicity={'missing': 0, 'task-a': 2}",
        ],
        "failure_examples": [
            {
                "id": "duplicate",
                "task": "task-a",
                "problems": ["node_0_logprob_mismatch"],
            }
        ],
    }


def test_summarize_traces_retains_only_emitted_failure_examples() -> None:
    traces = (_trace(str(index), f"task-{index}", valid=False) for index in range(75))

    summary, failed = _summarize_traces(
        traces,
        expected_slugs=None,
        expected_count=None,
        rollouts_per_task=1,
        require_reasoning=True,
        require_token_data=True,
    )

    assert failed is True
    assert summary["trace_failures"] == 75
    assert len(summary["failure_examples"]) == 50


def test_aggregate_only_summary_omits_trace_and_task_identifiers() -> None:
    summary, failed = _summarize_traces(
        [
            _trace("private-trace", "private-task", valid=False),
            _trace("other-trace", "unexpected-task"),
        ],
        expected_slugs={"private-task", "missing-task"},
        expected_count=3,
        rollouts_per_task=1,
        require_reasoning=True,
        require_token_data=True,
        aggregate_only=True,
    )

    assert failed is True
    encoded = json.dumps(summary, sort_keys=True)
    assert "private-trace" not in encoded
    assert "private-task" not in encoded
    assert "missing-task" not in encoded
    assert "unexpected-task" not in encoded
    assert "failure_examples" not in summary
    assert summary["global_problems"] == [
        "trace_count=2 expected=3",
        "missing_tasks_count=1",
        "unexpected_tasks_count=1",
        "wrong_rollout_multiplicity_count=1",
    ]
    assert summary["problem_counts"] == {"node_logprob_mismatch": 1}


def test_audit_trace_validates_token_array_values() -> None:
    trace = _trace("typed", "typed-task")
    trace["nodes"][0].update(
        token_ids=[101, True],
        mask=[True, 1],
        logprobs=[float("nan")],
    )

    assert _audit_trace(trace, require_reasoning=True, require_token_data=True) == [
        "node_0_token_ids_not_ints",
        "node_0_mask_not_bools",
        "node_0_logprobs_not_finite_numbers",
    ]


def test_audit_trace_requires_complete_sampled_nodes_and_reasoning() -> None:
    trace = _trace("empty", "empty-task")
    trace["nodes"].append(
        {
            "parent": 0,
            "sampled": True,
            "token_ids": [],
            "mask": [],
            "logprobs": [],
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "  ",
                "tool_calls": None,
            },
        }
    )

    assert _audit_trace(trace, require_reasoning=True, require_token_data=True) == [
        "node_1_assistant_payload_empty",
        "node_1_sampled_token_ids_empty",
        "node_1_sampled_mask_empty",
        "node_1_reasoning_content_not_retained",
    ]
    assert _audit_trace(trace, require_reasoning=False, require_token_data=True) == [
        "node_1_assistant_payload_empty",
        "node_1_sampled_token_ids_empty",
        "node_1_sampled_mask_empty",
    ]
    assert _audit_trace(trace, require_reasoning=False, require_logprobs=True) == [
        "node_1_assistant_payload_empty",
        "node_1_sampled_token_ids_empty",
        "node_1_sampled_mask_empty",
        "node_1_sampled_logprobs_empty",
    ]


def test_audit_trace_accepts_exact_tokens_without_logprobs() -> None:
    trace = _trace("no-logprobs", "no-logprobs-task")
    trace["nodes"][0]["logprobs"] = []

    assert _audit_trace(trace, require_reasoning=True) == []
    assert _audit_trace(trace, require_reasoning=True, require_logprobs=True) == [
        "node_0_logprob_mismatch",
        "node_0_sampled_logprobs_empty",
    ]


def test_audit_trace_preserves_tool_call_and_result_payloads() -> None:
    trace = _trace("tools", "tools-task")
    trace["nodes"][0]["message"]["tool_calls"] = [{"id": "call-1", "name": "bash", "arguments": '{"cmd":"pwd"}'}]
    trace["nodes"].append(
        {
            "parent": 0,
            "sampled": False,
            "token_ids": [103],
            "mask": [False],
            "logprobs": [],
            "message": {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "bash",
                "content": "/workspace\n",
            },
        }
    )

    assert _audit_trace(trace, require_reasoning=True) == []

    trace["nodes"][1]["message"]["tool_call_id"] = "missing"
    assert _audit_trace(trace, require_reasoning=True) == ["node_1_tool_call_not_in_ancestors"]


def test_audit_trace_limits_each_reconstructed_branch() -> None:
    trace = _trace("branched", "branched-task")
    trace["nodes"] = [
        {
            "parent": None,
            "sampled": False,
            "token_ids": [1, 2, 3, 4],
            "mask": [False] * 4,
            "logprobs": [],
            "message": {"role": "user", "content": "prompt"},
        },
        {
            "parent": 0,
            "sampled": True,
            "token_ids": [5, 6, 7, 8],
            "mask": [True] * 4,
            "logprobs": [-0.1] * 4,
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "first branch",
                "tool_calls": None,
            },
        },
        {
            "parent": 0,
            "sampled": True,
            "token_ids": [9, 10, 11, 12, 13, 14, 15],
            "mask": [True] * 7,
            "logprobs": [-0.1] * 7,
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "second branch",
                "tool_calls": None,
            },
        },
    ]

    assert (
        _audit_trace(
            trace,
            require_reasoning=True,
            max_sequence_tokens=11,
            require_token_data=True,
        )
        == []
    )
    assert _audit_trace(
        trace,
        require_reasoning=True,
        max_sequence_tokens=10,
        require_token_data=True,
    ) == ["max_sequence_tokens=11 limit=10"]


def test_audit_trace_rejects_invalid_parent_graphs() -> None:
    trace = _trace("graph", "graph-task")
    trace["nodes"].extend(
        [
            {
                "parent": 2,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "tool", "tool_call_id": "call", "content": "result"},
            },
            {
                "parent": 1,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "tool", "tool_call_id": "call", "content": "result"},
            },
            {
                "parent": 99,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "tool", "tool_call_id": "call", "content": "result"},
            },
        ]
    )

    assert _audit_trace(trace, require_reasoning=True, require_token_data=True) == [
        "node_3_invalid_parent",
        "parent_cycle",
    ]


def test_audit_trace_handles_deep_parent_chain_without_recursion() -> None:
    trace = _trace("deep", "deep-task")
    trace["nodes"] = [
        {
            "parent": index - 1 if index else None,
            "sampled": index == 1_499,
            "token_ids": [index],
            "mask": [index == 1_499],
            "logprobs": [-0.1] if index == 1_499 else [],
            "message": (
                {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "last node",
                    "tool_calls": None,
                }
                if index == 1_499
                else {"role": "user", "content": f"prompt-{index}"}
            ),
        }
        for index in range(1_500)
    ]

    assert (
        _audit_trace(
            trace,
            require_reasoning=True,
            max_sequence_tokens=1_500,
            require_token_data=True,
        )
        == []
    )


def test_audit_trace_defaults_to_response_reasoning_and_usage() -> None:
    trace = _transcript_trace()

    assert _audit_trace(trace, require_reasoning=True) == []
    summary, failed = _summarize_traces(
        [trace],
        expected_slugs={"text-task"},
        expected_count=1,
        rollouts_per_task=1,
        require_reasoning=True,
    )

    assert failed is False
    assert summary["sampled_tokens"] == 20


def test_audit_trace_transcript_mode_rejects_missing_payload_and_usage() -> None:
    trace = _transcript_trace()
    trace["nodes"][0]["message"] = {
        "role": "assistant",
        "content": " ",
        "reasoning_content": " ",
    }
    trace["nodes"][0]["usage"] = None

    assert _audit_trace(trace, require_reasoning=True) == [
        "node_0_assistant_payload_empty",
        "node_0_reasoning_content_not_retained",
        "node_0_usage_not_retained",
    ]


@pytest.mark.parametrize(
    ("field", "character", "label"),
    [
        ("content", "!", "bang"),
        ("reasoning_content", "@", "at"),
    ],
)
def test_audit_trace_rejects_whitespace_separated_kda_corruption(
    field: str,
    character: str,
    label: str,
) -> None:
    trace = _transcript_trace()
    trace["nodes"][0]["message"][field] = f"{character} " * 64
    problem_field = "reasoning" if field == "reasoning_content" else field

    assert _audit_trace(trace, require_reasoning=True) == [f"node_0_repeated_{label}_in_{problem_field}"]


def test_audit_trace_repeated_character_check_avoids_false_positives_and_tool_results() -> None:
    trace = _transcript_trace()
    trace["nodes"][0]["message"]["reasoning_content"] = " ".join(["@"] * 63)
    trace["nodes"][0]["message"]["content"] = " ".join(f"user{index}@example.com" for index in range(64))
    trace["nodes"][0]["message"]["tool_calls"] = [{"id": "call-1", "name": "bash", "arguments": '{"cmd":"inspect"}'}]
    trace["nodes"].append(
        {
            "parent": 0,
            "sampled": False,
            "message": {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "bash",
                "content": " ".join(["@"] * 128),
            },
        }
    )

    assert _audit_trace(trace, require_reasoning=True) == []


def test_audit_trace_transcript_mode_validates_usage_cap() -> None:
    trace = _transcript_trace()
    trace["nodes"][0]["usage"] = {
        "prompt_tokens": 5,
        "cached_input_tokens": 4,
        "completion_tokens": 2,
    }

    assert _audit_trace(trace, require_reasoning=True, max_sequence_tokens=10) == [
        "node_0_usage_sequence_tokens=11 limit=10"
    ]
    trace["nodes"][0]["usage"]["prompt_tokens"] = True
    assert _audit_trace(trace, require_reasoning=True) == ["node_0_usage_invalid"]


def test_audit_trace_token_data_is_explicit_opt_in() -> None:
    trace = _transcript_trace()

    assert _audit_trace(trace, require_reasoning=True, require_token_data=True) == [
        "node_0_sampled_token_ids_empty",
        "node_0_sampled_mask_empty",
        "no_sampled_tokens",
    ]


def test_audit_trace_validates_complete_model_io_capture() -> None:
    trace = _trace_with_model_io()

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == []


def test_strict_kimi_contract_is_valid_and_implies_model_io() -> None:
    trace = _trace_with_model_io()

    assert (
        _audit_trace(
            trace,
            require_reasoning=True,
            model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
        )
        == []
    )

    trace["nodes"][0].pop("model_io")
    assert _audit_trace(
        trace,
        require_reasoning=True,
        require_model_io=False,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
    ) == ["node_0_model_io_missing", "no_model_io_tool_schemas"]


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        ("model", "different-model", "node_0_model_io_request_model_mismatch"),
        (
            "reasoning_effort",
            "low",
            "node_0_model_io_request_reasoning_effort_mismatch",
        ),
        (
            "chat_template_kwargs",
            {"enable_thinking": True, "preserve_thinking": True, "extra": True},
            "node_0_model_io_request_chat_template_kwargs_mismatch",
        ),
        (
            "chat_template_kwargs",
            {"enable_thinking": 1, "preserve_thinking": True},
            "node_0_model_io_request_chat_template_kwargs_mismatch",
        ),
    ],
)
def test_strict_kimi_contract_rejects_request_mismatch(
    field: str,
    value: object,
    problem: str,
) -> None:
    trace = _trace_with_model_io()
    request = trace["nodes"][0]["model_io"]["request"]
    request["body"][field] = value
    request["sha256"] = _digest(request["body"])

    assert _audit_trace(
        trace,
        require_reasoning=True,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
    ) == [problem]


def test_strict_kimi_contract_rejects_provider_route_mismatch() -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["model_io"]["provider_route"] = "/different"

    assert _audit_trace(
        trace,
        require_reasoning=True,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
    ) == ["node_0_model_io_provider_route_contract_mismatch"]


def test_strict_kimi_contract_checks_reconstructed_request_deltas() -> None:
    trace = _trace_with_model_io()
    second = _trace("second", "same-task")["nodes"][0]
    second["parent"] = 0
    reconstructed = {**_request(), "reasoning_effort": "low"}
    second["model_io"] = _model_io(reconstructed)
    second["model_io"]["request"] = {
        "kind": "delta",
        "sha256": _digest(reconstructed),
        "base_node": 0,
        "set_fields": {"reasoning_effort": "low"},
        "remove_fields": [],
        "append_fields": {},
    }
    trace["nodes"].append(second)

    assert _audit_trace(
        trace,
        require_reasoning=True,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
    ) == ["node_1_model_io_request_reasoning_effort_mismatch"]


def test_audit_trace_reconciles_exact_chat_response_semantics() -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["message"] = {
        "role": "assistant",
        "content": "answer",
        "reasoning_content": "preferred reasoning",
        "tool_calls": [{"id": "call-1", "name": "bash", "arguments": '{"cmd":"pwd"}'}],
    }
    trace["nodes"][0]["finish_reason"] = "tool_calls"
    trace["nodes"][0]["usage"] = {
        "prompt_tokens": 90,
        "completion_tokens": 10,
        "cached_input_tokens": 10,
        "reasoning_tokens": 4,
        "cost": 0.25,
    }
    response = _exact_response(
        message={
            "role": "assistant",
            "content": "answer",
            "reasoning": "preferred reasoning",
            "reasoning_content": "lower-precedence reasoning",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
                }
            ],
        },
        finish_reason="tool_calls",
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
            "prompt_tokens_details": {"cached_tokens": 10},
            "completion_tokens_details": {"reasoning_tokens": 4},
            "cost": 0.25,
        },
    )
    trace["nodes"][0]["model_io"]["response"] = {
        "kind": "exact_provider_json",
        "sha256": _digest(response),
        "body": response,
    }

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == []


def test_audit_trace_reconciles_normalized_stream_response_semantics() -> None:
    trace = _trace_with_model_io()
    normalized = {
        "id": "stream-response",
        "created": 1,
        "model": "Kimi-K3",
        "message": {
            "role": "assistant",
            "content": None,
            "reasoning_content": "reasoning",
            "tool_calls": None,
            "provider_state": None,
        },
        "finish_reason": "stop",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 2,
            "cached_input_tokens": None,
            "reasoning_tokens": None,
            "cost": None,
        },
        "tokens": None,
    }
    trace["nodes"][0]["model_io"]["response"] = {
        "kind": "normalized_stream_response",
        "sha256": _digest(normalized),
        "body": normalized,
    }

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == []


@pytest.mark.parametrize("kind", ["exact_provider_json", "normalized_stream_response"])
def test_strict_kimi_contract_rejects_response_model_mismatch(kind: str) -> None:
    trace = _trace_with_model_io()
    if kind == "exact_provider_json":
        response = trace["nodes"][0]["model_io"]["response"]
        response["body"]["model"] = "different-model"
    else:
        response = {
            "kind": "normalized_stream_response",
            "body": {
                "id": "stream-response",
                "created": 1,
                "model": "different-model",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "reasoning",
                    "tool_calls": None,
                    "provider_state": None,
                },
                "finish_reason": "stop",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 2,
                    "cached_input_tokens": None,
                    "reasoning_tokens": None,
                    "cost": None,
                },
                "tokens": None,
            },
        }
        trace["nodes"][0]["model_io"]["response"] = response
    response["sha256"] = _digest(response["body"])

    assert _audit_trace(
        trace,
        require_reasoning=True,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
    ) == ["node_0_model_io_response_model_mismatch"]


def test_strict_kimi_contract_aggregate_codes_never_echo_observed_values() -> None:
    trace = _trace_with_model_io()
    request = trace["nodes"][0]["model_io"]["request"]
    request["body"]["model"] = "private-observed-value"
    request["sha256"] = _digest(request["body"])

    summary, failed = _summarize_traces(
        [trace],
        expected_slugs=None,
        expected_count=1,
        rollouts_per_task=1,
        require_reasoning=True,
        aggregate_only=True,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
    )

    assert failed is True
    assert "private-observed-value" not in json.dumps(summary, sort_keys=True)
    assert summary["problem_counts"] == {"node_model_io_request_model_mismatch": 1}


def test_audit_trace_rejects_hash_valid_unrelated_provider_response() -> None:
    trace = _trace_with_model_io()
    unrelated = _exact_response(
        message={
            "role": "assistant",
            "content": "unrelated answer",
            "reasoning_content": "reasoning",
        }
    )
    trace["nodes"][0]["model_io"]["response"] = {
        "kind": "exact_provider_json",
        "sha256": _digest(unrelated),
        "body": unrelated,
    }

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == [
        "node_0_model_io_response_message_mismatch"
    ]


@pytest.mark.parametrize(
    ("field", "value", "problems"),
    [
        (
            "finish_reason",
            "length",
            [
                "node_0_finish_reason_invalid",
                "node_0_model_io_response_finish_reason_mismatch",
            ],
        ),
        (
            "usage",
            {"prompt_tokens": 100, "completion_tokens": 3},
            ["node_0_model_io_response_usage_mismatch"],
        ),
    ],
)
def test_audit_trace_rejects_response_metadata_mismatch(
    field: str,
    value: object,
    problems: list[str],
) -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0][field] = value

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == problems


def test_audit_trace_requires_captured_request_messages_to_match_graph_path() -> None:
    trace = _trace_with_model_io()
    sampled = trace["nodes"][0]
    sampled["parent"] = 0
    trace["nodes"] = [
        {
            "parent": None,
            "sampled": False,
            "token_ids": [],
            "mask": [],
            "logprobs": [],
            "message": {"role": "user", "content": "inspect the workspace"},
        },
        sampled,
    ]

    assert (
        _audit_trace(
            trace,
            require_reasoning=True,
            require_model_io=True,
            require_request_graph_match=True,
        )
        == []
    )

    request = sampled["model_io"]["request"]
    request["body"]["messages"] = [{"role": "user", "content": "wire-only context"}]
    request["sha256"] = _digest(request["body"])
    assert _audit_trace(
        trace,
        require_reasoning=True,
        require_model_io=True,
        require_request_graph_match=True,
    ) == ["node_1_model_io_request_messages_mismatch"]


def test_audit_trace_requires_exact_chat_completions_route() -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["model_io"]["provider_route"] = "/v1/chat/completions"

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == [
        "node_0_model_io_provider_route_invalid"
    ]


@pytest.mark.parametrize(
    ("arguments", "valid"),
    [
        ('{"command":"pwd"}', True),
        ('{"items":[1,false,""],"nested":{}}', True),
        ("[]", False),
        ("null", False),
        ('{"value":null}', False),
        ('{"value":NaN}', False),
        ('{"value":1e400}', False),
        ('{"value":1,"value":2}', False),
    ],
)
def test_tool_arguments_are_strict_finite_null_free_json_objects(arguments: str, valid: bool) -> None:
    assert _valid_tool_arguments(arguments) is valid


def test_audit_trace_rejects_unknown_finish_reason() -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["finish_reason"] = "content_filter"

    assert "node_0_finish_reason_invalid" in _audit_trace(trace, require_reasoning=True, require_model_io=True)


@pytest.mark.parametrize(
    "mutation",
    ["unknown_role", "unknown_message_key", "unknown_content_part", "unknown_tool_call_key"],
)
def test_audit_trace_rejects_lossy_graph_wire_message_shapes(mutation: str) -> None:
    trace = _trace_with_model_io()
    sampled = trace["nodes"][0]
    sampled["parent"] = 0
    graph_message: dict = {"role": "user", "content": "inspect the workspace"}
    trace["nodes"] = [
        {
            "parent": None,
            "sampled": False,
            "token_ids": [],
            "mask": [],
            "logprobs": [],
            "message": graph_message,
        },
        sampled,
    ]
    wire_message = sampled["model_io"]["request"]["body"]["messages"][0]
    if mutation == "unknown_role":
        wire_message["role"] = "developer"
    elif mutation == "unknown_message_key":
        wire_message["opaque"] = True
    elif mutation == "unknown_content_part":
        wire_message["content"] = [{"type": "input_text", "text": "inspect the workspace"}]
    else:
        graph_message.clear()
        graph_message.update(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "name": "bash", "arguments": "{}", "opaque": True}],
            }
        )
        wire_message.clear()
        wire_message.update(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": "{}"},
                    }
                ],
            }
        )
    request = sampled["model_io"]["request"]
    request["sha256"] = _digest(request["body"])

    problems = _audit_trace(
        trace,
        require_reasoning=True,
        require_model_io=True,
        require_request_graph_match=True,
    )

    assert "node_1_model_io_request_messages_invalid" in problems


def test_audit_trace_requires_model_io_on_every_sampled_turn() -> None:
    trace = _trace_with_model_io()
    second = _trace("second", "same-task")["nodes"][0]
    second["parent"] = 0
    trace["nodes"].append(second)

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == ["node_1_model_io_missing"]


def test_audit_trace_allows_provider_reported_zero_reasoning_tool_turn() -> None:
    trace = _trace_with_model_io()
    second = _trace("second", "same-task")["nodes"][0]
    second["parent"] = 0
    second["message"] = {
        "role": "assistant",
        "content": None,
        "reasoning_content": None,
        "tool_calls": [{"id": "call-2", "name": "bash", "arguments": '{"cmd":"pwd"}'}],
    }
    second["usage"]["reasoning_tokens"] = 0
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 2,
        "total_tokens": 102,
    }
    usage["completion_tokens_details"] = {"reasoning_tokens": 0}
    second["model_io"] = _model_io(
        _request(),
        response=_exact_response(
            message={
                "role": "assistant",
                "content": None,
                "reasoning": None,
                "tool_calls": [
                    {
                        "id": "call-2",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
                    }
                ],
            },
            usage=usage,
        ),
    )
    trace["nodes"].append(second)

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == []


def test_audit_trace_allows_hash_bound_explicit_empty_reasoning_tool_turn() -> None:
    trace = _trace_with_model_io()
    second = _trace("second", "same-task")["nodes"][0]
    second["parent"] = 0
    second["message"] = {
        "role": "assistant",
        "content": None,
        "reasoning_content": None,
        "tool_calls": [{"id": "call-2", "name": "bash", "arguments": '{"cmd":"pwd"}'}],
    }
    second["model_io"] = _model_io(
        _request(),
        response=_exact_response(
            message={
                "role": "assistant",
                "content": None,
                "reasoning": "",
                "tool_calls": [
                    {
                        "id": "call-2",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
                    }
                ],
            },
            usage={"prompt_tokens": 100, "completion_tokens": 2, "total_tokens": 102},
        ),
    )
    trace["nodes"].append(second)

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == []


@pytest.mark.parametrize(
    ("reasoning_tokens", "accepted"),
    [pytest.param(0, True, id="reported-zero"), pytest.param(None, False, id="counter-missing")],
)
def test_normalized_zero_reasoning_tool_turn_requires_reported_counter(
    reasoning_tokens: int | None,
    accepted: bool,
) -> None:
    trace = _trace_with_model_io()
    second = _trace("second", "same-task")["nodes"][0]
    second["parent"] = 0
    second["message"] = {
        "role": "assistant",
        "content": None,
        "reasoning_content": None,
        "tool_calls": [{"id": "call-2", "name": "bash", "arguments": '{"cmd":"pwd"}'}],
    }
    second["finish_reason"] = "tool_calls"
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 2,
        "cached_input_tokens": None,
        "cost": None,
    }
    if reasoning_tokens is not None:
        usage["reasoning_tokens"] = reasoning_tokens
        second["usage"]["reasoning_tokens"] = reasoning_tokens
    response = {
        "id": "normalized-zero-reasoning-tool",
        "created": 1,
        "model": "Kimi-K3",
        "message": {
            **second["message"],
            "provider_state": None,
        },
        "finish_reason": "tool_calls",
        "usage": usage,
        "tokens": None,
    }
    second["model_io"] = _model_io(_request())
    second["model_io"]["response"] = {
        "kind": "normalized_stream_response",
        "sha256": _digest(response),
        "body": response,
    }
    trace["nodes"].append(second)

    problems = _audit_trace(trace, require_reasoning=True, require_model_io=True)
    assert ("node_1_reasoning_content_not_retained" not in problems) is accepted


@pytest.mark.parametrize(
    "mutation",
    [
        "reasoning_absent",
        "reasoning_null",
        "thinking_disabled",
        "thinking_missing",
        "preserve_disabled",
        "preserve_missing",
        "top_level_reasoning_tokens",
        "tool_call_mismatch",
    ],
)
def test_audit_trace_rejects_ambiguous_empty_reasoning_tool_turn(mutation: str) -> None:
    trace = _trace_with_model_io()
    second = _trace("second", "same-task")["nodes"][0]
    second["parent"] = 0
    second["message"] = {
        "role": "assistant",
        "content": None,
        "reasoning_content": None,
        "tool_calls": [{"id": "call-2", "name": "bash", "arguments": '{"cmd":"pwd"}'}],
    }
    request = _request()
    provider_message = {
        "role": "assistant",
        "content": None,
        "reasoning": "",
        "tool_calls": [
            {
                "id": "call-2",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
            }
        ],
    }
    if mutation == "reasoning_absent":
        provider_message.pop("reasoning")
    elif mutation == "reasoning_null":
        provider_message["reasoning"] = None
    elif mutation == "thinking_disabled":
        request["chat_template_kwargs"]["enable_thinking"] = False
    elif mutation == "thinking_missing":
        request["chat_template_kwargs"].pop("enable_thinking")
    elif mutation == "preserve_disabled":
        request["chat_template_kwargs"]["preserve_thinking"] = False
    elif mutation == "preserve_missing":
        request["chat_template_kwargs"].pop("preserve_thinking")
    elif mutation == "tool_call_mismatch":
        provider_message["tool_calls"][0]["function"]["name"] = "different"
    usage = {"prompt_tokens": 100, "completion_tokens": 2, "total_tokens": 102}
    if mutation == "top_level_reasoning_tokens":
        usage["reasoning_tokens"] = 0
    second["model_io"] = _model_io(
        request,
        response=_exact_response(
            message=provider_message,
            usage=usage,
        ),
    )
    trace["nodes"].append(second)

    problems = _audit_trace(
        trace,
        require_reasoning=True,
        require_model_io=True,
    )
    assert "node_1_reasoning_content_not_retained" in problems
    if mutation == "tool_call_mismatch":
        assert "node_1_model_io_response_message_mismatch" in problems


@pytest.mark.parametrize("reasoning_tokens", [1, -1, True, 0.0, "0", None])
def test_zero_reasoning_tool_turn_rejects_nonzero_or_malformed_counter(
    reasoning_tokens: object,
) -> None:
    response = _exact_response(
        message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
                }
            ],
        },
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 2,
            "total_tokens": 102,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    )
    node = {"model_io": {"response": {"kind": "exact_provider_json", "body": response}}}
    node["model_io"]["response"]["sha256"] = _digest(response)

    assert _captured_zero_reasoning_tool_turn(node) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reasoning", "retained"),
        ("reasoning_content", {"malformed": True}),
        ("reasoning_details", "malformed"),
        ("provider_specific_fields", "malformed"),
        ("provider_specific_fields", {"reasoning_details": [{"text": "retained"}]}),
    ],
)
def test_zero_reasoning_tool_turn_rejects_provider_reasoning_or_malformed_fields(
    field: str,
    value: object,
) -> None:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
            }
        ],
        field: value,
    }
    response = _exact_response(
        message=message,
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 2,
            "total_tokens": 102,
        },
    )
    node = {"model_io": {"response": {"kind": "exact_provider_json", "body": response}}}
    node["model_io"]["response"]["sha256"] = _digest(response)

    assert _captured_zero_reasoning_tool_turn(node) is None


def test_audit_trace_requires_captured_reasoning_to_be_normalized() -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["message"]["reasoning_content"] = None
    trace["nodes"][0]["message"]["tool_calls"] = [{"id": "call-1", "name": "bash", "arguments": '{"cmd":"pwd"}'}]
    trace["nodes"][0]["usage"]["reasoning_tokens"] = 2
    response = _exact_response(
        message={
            "role": "assistant",
            "content": None,
            "reasoning": "provider reasoning",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
                }
            ],
        },
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 2,
            "total_tokens": 102,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    )
    trace["nodes"][0]["model_io"]["response"] = {
        "kind": "exact_provider_json",
        "sha256": _digest(response),
        "body": response,
    }

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == [
        "node_0_reasoning_content_not_retained",
        "no_sampled_reasoning_content",
        "node_0_model_io_response_message_mismatch",
    ]


def test_audit_trace_requires_some_reasoning_across_zero_reasoning_tool_turns() -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["message"] = {
        "role": "assistant",
        "content": None,
        "reasoning_content": None,
        "tool_calls": [{"id": "call-1", "name": "bash", "arguments": '{"cmd":"pwd"}'}],
    }
    trace["nodes"][0]["usage"]["reasoning_tokens"] = 0
    response = _exact_response(
        message={
            "role": "assistant",
            "content": None,
            "reasoning": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
                }
            ],
        },
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 2,
            "total_tokens": 102,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    )
    trace["nodes"][0]["model_io"]["response"] = {
        "kind": "exact_provider_json",
        "sha256": _digest(response),
        "body": response,
    }

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == ["no_sampled_reasoning_content"]


def test_audit_trace_reconstructs_and_hashes_model_request_deltas() -> None:
    trace = _trace_with_model_io()
    base_request = trace["nodes"][0]["model_io"]["request"]["body"]
    base_request["temperature"] = 0.6
    base_request["seed"] = 123
    trace["nodes"][0]["model_io"]["request"]["sha256"] = _digest(base_request)

    second_request = {
        **{key: value for key, value in base_request.items() if key != "seed"},
        "temperature": 0.7,
        "messages": [
            *base_request["messages"],
            {"role": "assistant", "content": "I need the shell."},
            {"role": "tool", "tool_call_id": "call-1", "content": "/workspace"},
        ],
    }
    second = _trace("second", "same-task")["nodes"][0]
    second["parent"] = 0
    second["model_io"] = _model_io(second_request)
    second["model_io"]["request"] = {
        "kind": "delta",
        "sha256": _digest(second_request),
        "base_node": 0,
        "set_fields": {"temperature": 0.7},
        "remove_fields": ["seed"],
        "append_fields": {"messages": second_request["messages"][1:]},
    }
    trace["nodes"].append(second)

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == []

    second["model_io"]["request"]["sha256"] = "0" * 64
    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == [
        "node_1_model_io_request_hash_mismatch"
    ]


def test_audit_trace_rejects_model_io_response_hash_corruption() -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["model_io"]["response"]["body"]["id"] = "tampered"

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == [
        "node_0_model_io_response_hash_mismatch"
    ]


@pytest.mark.parametrize(
    "malformed_request",
    [
        {"kind": "full", "sha256": "0" * 64, "body": [], "extra": True},
        {
            "kind": "delta",
            "sha256": "0" * 64,
            "base_node": 0,
            "set_fields": {"messages": []},
            "remove_fields": ["messages"],
            "append_fields": {},
        },
        {
            "kind": "delta",
            "sha256": "0" * 64,
            "base_node": 0,
            "set_fields": {},
            "remove_fields": [],
            "append_fields": {"messages": []},
        },
    ],
)
def test_audit_trace_rejects_malformed_model_requests(malformed_request: dict) -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["model_io"]["request"] = malformed_request

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == [
        "node_0_model_io_request_structure_invalid",
        "no_model_io_tool_schemas",
    ]


def test_audit_trace_rejects_malformed_model_response() -> None:
    trace = _trace_with_model_io()
    trace["nodes"][0]["model_io"]["response"] = {
        "kind": "unknown",
        "sha256": "not-a-hash",
        "body": [],
    }

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == [
        "node_0_model_io_response_structure_invalid"
    ]


def test_audit_trace_rejects_cyclic_and_nonancestor_model_request_deltas() -> None:
    cyclic = _trace_with_model_io("cycle")
    request = _request()
    cyclic["nodes"][0]["model_io"]["request"] = {
        "kind": "delta",
        "sha256": _digest(request),
        "base_node": 0,
        "set_fields": {},
        "remove_fields": [],
        "append_fields": {},
    }
    assert _audit_trace(cyclic, require_reasoning=True, require_model_io=True) == [
        "node_0_model_io_request_delta_cycle",
        "no_model_io_tool_schemas",
    ]

    nonancestor = _trace_with_model_io("nonancestor")
    second = _trace("second", "same-task")["nodes"][0]
    second["parent"] = None
    second["model_io"] = _model_io(request)
    second["model_io"]["request"] = {
        "kind": "delta",
        "sha256": _digest(request),
        "base_node": 0,
        "set_fields": {},
        "remove_fields": [],
        "append_fields": {},
    }
    nonancestor["nodes"].append(second)
    assert _audit_trace(nonancestor, require_reasoning=True, require_model_io=True) == [
        "node_1_model_io_request_delta_base_not_ancestor"
    ]


def test_audit_trace_handles_deep_model_request_delta_chain_without_recursion() -> None:
    trace = _trace_with_model_io("deep-model-io")
    initial_request = _request(turn=0)
    trace["nodes"][0]["model_io"] = _model_io(initial_request)
    for index in range(1, 1_100):
        current_request = _request(turn=index)
        node = _trace(f"turn-{index}", "same-task")["nodes"][0]
        node["parent"] = index - 1
        node["model_io"] = _model_io(current_request)
        node["model_io"]["request"] = {
            "kind": "delta",
            "sha256": _digest(current_request),
            "base_node": index - 1,
            "set_fields": {"turn": index},
            "remove_fields": [],
            "append_fields": {},
        }
        trace["nodes"].append(node)

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == []


def test_audit_trace_forbids_logprob_fields_in_reconstructed_requests() -> None:
    trace = _trace("forbidden", "forbidden-task")
    request = _request(
        logprobs=False,
        prompt_logprobs=0,
        return_token_ids=False,
        top_logprobs=0,
    )
    trace["nodes"][0]["model_io"] = _model_io(request)

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == [
        "node_0_model_io_forbidden_request_fields=['logprobs', 'prompt_logprobs', 'return_token_ids', 'top_logprobs']"
    ]


def test_audit_trace_requires_nonempty_tool_schema_in_model_requests() -> None:
    trace = _trace("no-tools", "no-tools-task")
    trace["nodes"][0]["model_io"] = _model_io(_request(tools=[]))

    assert _audit_trace(trace, require_reasoning=True, require_model_io=True) == ["no_model_io_tool_schemas"]


def test_summarize_traces_reports_model_io_turns_only_when_required() -> None:
    trace = _trace_with_model_io()

    summary, failed = _summarize_traces(
        [trace],
        expected_slugs=None,
        expected_count=1,
        rollouts_per_task=1,
        require_reasoning=True,
        require_model_io=True,
    )
    assert failed is False
    assert summary["model_io_turns"] == 1

    backward_compatible, failed = _summarize_traces(
        [trace],
        expected_slugs=None,
        expected_count=1,
        rollouts_per_task=1,
        require_reasoning=True,
    )
    assert failed is False
    assert "model_io_turns" not in backward_compatible


def test_main_requires_model_io_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(f"{json.dumps(_trace('trace', 'task'))}\n")
    monkeypatch.setattr(sys, "argv", ["audit_traces.py", str(results)])

    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["model_io_turns"] == 0
    assert summary["failure_examples"][0]["problems"] == [
        "node_0_model_io_missing",
        "no_model_io_tool_schemas",
    ]

    monkeypatch.setattr(sys, "argv", ["audit_traces.py", str(results), "--no-require-model-io"])
    main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["trace_failures"] == 0
    assert "model_io_turns" not in summary


def test_main_supports_strict_kimi_production_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(f"{json.dumps(_trace_with_model_io())}\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_traces.py",
            str(results),
            "--aggregate-only",
            "--no-require-model-io",
            "--model-io-contract",
            "kimi-k3-max",
        ],
    )

    main()

    summary = json.loads(capsys.readouterr().out)
    assert summary["trace_failures"] == 0
    assert summary["model_io_turns"] == 1
    assert "failure_examples" not in summary


def test_main_reports_malformed_json_line_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(f"{json.dumps(_trace('first', 'task'))}\n\n{{not json}}\n")
    monkeypatch.setattr(sys, "argv", ["audit_traces.py", str(results)])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert f"{results}: invalid JSON on line 3" in stderr
    assert "Traceback" not in stderr
