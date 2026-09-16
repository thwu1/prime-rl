import json
import sys
from pathlib import Path

import pytest
from audit_traces import _audit_trace, _iter_traces, _summarize_traces, main


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
    trace["nodes"][0]["message"]["tool_calls"] = [
        {"id": "call-1", "name": "bash", "arguments": '{"cmd":"pwd"}'}
    ]
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
    assert _audit_trace(trace, require_reasoning=True) == [
        "node_1_tool_call_not_in_ancestors"
    ]


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
