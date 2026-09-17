import copy
import fcntl
import hashlib
import json
from pathlib import Path

import pytest
from audit_traces import _json_sha256
from datasets import load_dataset
from export_sft import ExportError, ExportOptions, _split_for_task, export_sft, main


def _tool(name: str = "terminal") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Run a synthetic command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }


def _response(
    *,
    content: str | None,
    reasoning: str,
    tool_calls: list[dict] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> dict:
    message = {
        "role": "assistant",
        "content": content,
        "reasoning": reasoning,
    }
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
            }
            for call in tool_calls
        ]
    return {
        "id": "synthetic-response",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _model_io(request: dict, response: dict, *, base_node: int | None = None, base: dict | None = None) -> dict:
    if base_node is None:
        captured_request = {
            "kind": "full",
            "sha256": _json_sha256(request),
            "body": request,
        }
    else:
        assert base is not None
        appended = request["messages"][len(base["messages"]) :]
        captured_request = {
            "kind": "delta",
            "sha256": _json_sha256(request),
            "base_node": base_node,
            "set_fields": {},
            "remove_fields": [],
            "append_fields": {"messages": appended},
        }
    return {
        "provider_route": "/chat/completions",
        "request": captured_request,
        "response": {
            "kind": "exact_provider_json",
            "sha256": _json_sha256(response),
            "body": response,
        },
    }


def _input_node(parent: int | None, role: str, content: str, **extra) -> dict:
    return {
        "parent": parent,
        "sampled": False,
        "token_ids": [],
        "mask": [],
        "logprobs": [],
        "message": {"role": role, "content": content, **extra},
    }


def _assistant_node(
    parent: int,
    *,
    content: str | None,
    reasoning: str,
    request: dict,
    base_node: int | None = None,
    base_request: dict | None = None,
    calls: list[dict] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> dict:
    response = _response(
        content=content,
        reasoning=reasoning,
        tool_calls=calls,
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    message = {
        "role": "assistant",
        "content": content,
        "reasoning_content": reasoning,
    }
    if calls:
        message["tool_calls"] = calls
    return {
        "parent": parent,
        "sampled": True,
        "token_ids": [],
        "mask": [],
        "logprobs": [],
        "finish_reason": finish_reason,
        "message": message,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
        "model_io": _model_io(
            request,
            response,
            base_node=base_node,
            base=base_request,
        ),
    }


def _linear_trace(trace_id: str = "trace-pass", *, reward: float = 1.0, task_name: str = "synthetic-task") -> dict:
    calls = [{"id": "call-1", "name": "terminal", "arguments": '{"command":"pwd"}'}]
    tools = [_tool()]
    first_request = {
        "model": "synthetic-model",
        "messages": [
            {"role": "system", "content": "synthetic-system"},
            {"role": "user", "content": "synthetic-question"},
        ],
        "tools": tools,
        "max_tokens": 100,
    }
    second_request = {
        **first_request,
        "messages": [
            *first_request["messages"],
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "first-reasoning",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "terminal", "arguments": '{"command":"pwd"}'},
                    }
                ],
            },
            {"role": "tool", "content": "synthetic-result", "tool_call_id": "call-1"},
        ],
    }
    nodes = [
        _input_node(None, "system", "synthetic-system"),
        _input_node(0, "user", "synthetic-question"),
        _assistant_node(
            1,
            content=None,
            reasoning="first-reasoning",
            calls=calls,
            finish_reason="tool_calls",
            request=first_request,
        ),
        _input_node(2, "tool", "synthetic-result", tool_call_id="call-1", name="terminal"),
        _assistant_node(
            3,
            content="synthetic-answer",
            reasoning="second-reasoning",
            request=second_request,
            base_node=2,
            base_request=first_request,
            prompt_tokens=20,
        ),
    ]
    return {
        "id": trace_id,
        "task": {"idx": 0, "name": task_name, "prompt": "synthetic-question"},
        "nodes": nodes,
        "rewards": {"solved": reward},
        "metrics": {},
        "info": {},
        "is_completed": True,
        "stop_condition": "agent_completed",
        "errors": [],
        "timing": {},
    }


def _branched_trace() -> dict:
    trace = _linear_trace("trace-branch")
    nodes = trace["nodes"]
    first_request = nodes[2]["model_io"]["request"]["body"]
    branch_request = {
        **first_request,
        "messages": [
            *first_request["messages"],
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "first-reasoning",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "terminal", "arguments": '{"command":"pwd"}'},
                    }
                ],
            },
            {"role": "tool", "content": "branch-result", "tool_call_id": "call-1"},
        ],
    }
    nodes.extend(
        [
            _input_node(2, "tool", "branch-result", tool_call_id="call-1", name="terminal"),
            _assistant_node(
                5,
                content="branch-answer",
                reasoning="branch-reasoning",
                request=branch_request,
                base_node=2,
                base_request=first_request,
                prompt_tokens=21,
            ),
        ]
    )
    return trace


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_run(run_dir: Path, traces: list[dict]) -> Path:
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    source_config = inputs / "source_config.toml"
    task_file = inputs / "task_file.txt"
    image_manifest = inputs / "image_manifest.json"
    source_config.write_text("source = true\n")
    task_file.write_text("opaque-synthetic-task\n")
    image_manifest.write_text("{}\n")
    inputs_manifest = {
        "config": {"sha256": _sha256(source_config)},
        "task_file": {"sha256": _sha256(task_file)},
        "image_manifest": {"sha256": _sha256(image_manifest)},
    }
    (inputs / "manifest.json").write_text(json.dumps(inputs_manifest, sort_keys=True) + "\n")
    (run_dir / "provenance.txt").write_text("prime_rl=synthetic\n")
    (run_dir / "config.toml").write_text(
        "\n".join(
            [
                'model = "synthetic-model"',
                "num_rollouts = 1",
                "max_input_tokens = 262144",
                "max_output_tokens = 262144",
                "max_total_tokens = 262144",
                "[client]",
                'type = "eval"',
                "capture_model_io = true",
                'outbound_body_denylist = ["logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"]',
                "[sampling.chat_template_kwargs]",
                "enable_thinking = true",
                "preserve_thinking = true",
                "[taskset]",
                f'task_file_sha256 = "{_sha256(task_file)}"',
                f'image_manifest_sha256 = "{_sha256(image_manifest)}"',
                "",
            ]
        )
    )
    results = run_dir / "results.jsonl"
    results.write_bytes(
        b"".join(
            json.dumps(trace, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for trace in traces
        )
    )
    return results


def _options(results: Path, output: Path, *, selection: str = "all-outcomes", expected_count: int | None = None):
    return ExportOptions(
        results=results,
        output_dir=output,
        selection=selection,
        expected_count=expected_count,
        validation_permyriad=0,
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_exports_one_row_per_unique_sampled_node_and_normalizes_messages(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output, expected_count=1))

    rows = _read_jsonl(output / "train" / "train.jsonl")
    assert summary["rows"] == {"total": 2, "train": 2, "validation": 0}
    assert len(rows) == 2
    first, second = rows
    assert first["messages"][-1]["content"] == ""
    assert first["messages"][-1]["reasoning_content"] == "first-reasoning"
    assert first["messages"][-1]["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "terminal", "arguments": '{"command":"pwd"}'},
        }
    ]
    assert second["messages"][2]["trainable"] is False
    assert "reasoning_content" not in second["messages"][2]
    assert second["messages"][-1]["trainable"] is True
    assert second["messages"][-1]["reasoning_content"] == "second-reasoning"
    assert all(sum(message["trainable"] is True for message in row["messages"]) == 1 for row in rows)
    assert rows[0]["task_id"] != "synthetic-task"
    assert rows[0]["source_episode_id"] != "trace-pass"


def test_branched_trace_does_not_duplicate_shared_prefix_targets(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_branched_trace()])
    output = tmp_path / "dataset"

    export_sft(_options(results, output))

    rows = _read_jsonl(output / "train" / "train.jsonl")
    assert len(rows) == 3
    assert [row["source_node_index"] for row in rows] == [2, 4, 6]
    assert [row["target_assistant_turn_index"] for row in rows] == [0, 1, 2]
    assert len({(row["source_episode_id"], row["source_node_index"]) for row in rows}) == 3


@pytest.mark.parametrize(
    ("selection", "expected_traces", "expected_rows"),
    [("pass-only", 1, 2), ("all-outcomes", 2, 4)],
)
def test_selection_is_explicit_and_deterministic(
    tmp_path: Path, selection: str, expected_traces: int, expected_rows: int
) -> None:
    results = _write_run(
        tmp_path / "run",
        [
            _linear_trace("pass", reward=1, task_name="pass-task"),
            _linear_trace("fail", reward=0, task_name="fail-task"),
        ],
    )
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output, selection=selection))

    assert summary["selected_traces"] == expected_traces
    assert summary["rows"]["total"] == expected_rows


def test_error_rows_are_excluded_without_inspecting_error_payload(tmp_path: Path) -> None:
    error_trace = {
        "id": "error-trace",
        "task": {"idx": 1, "name": "error-task", "prompt": "private-marker"},
        "nodes": [],
        "rewards": {},
        "is_completed": True,
        "stop_condition": "error",
        "errors": [{"type": "Synthetic", "message": "private-error-marker"}],
    }
    results = _write_run(tmp_path / "run", [_linear_trace(), error_trace])
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output, expected_count=2))

    assert summary["excluded_error_traces"] == 1
    assert summary["rows"]["total"] == 2
    assert "private-marker" not in json.dumps(summary)


@pytest.mark.parametrize("field", ["reasoning", "model_io", "usage", "response_hash"])
def test_strict_trace_validation_fails_closed(tmp_path: Path, field: str) -> None:
    trace = _linear_trace()
    node = trace["nodes"][2]
    if field == "reasoning":
        node["message"].pop("reasoning_content")
    elif field == "model_io":
        node.pop("model_io")
    elif field == "usage":
        node.pop("usage")
    else:
        node["model_io"]["response"]["sha256"] = "0" * 64
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^trace_validation_failed$"):
        export_sft(_options(results, tmp_path / "dataset"))
    assert not (tmp_path / "dataset").exists()


def test_captured_response_must_match_retained_reasoning(tmp_path: Path) -> None:
    trace = _linear_trace()
    response = trace["nodes"][2]["model_io"]["response"]
    response["body"]["choices"][0]["message"]["reasoning"] = "different-reasoning"
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^captured_response_reasoning_mismatch$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_normalized_stream_responses_are_validated_and_exported(tmp_path: Path) -> None:
    trace = _linear_trace()
    for node in trace["nodes"]:
        if node.get("sampled") is not True:
            continue
        exact = node["model_io"]["response"]
        choice = exact["body"]["choices"][0]
        raw_message = choice["message"]
        message = {
            "role": "assistant",
            "content": raw_message["content"],
            "reasoning_content": raw_message["reasoning"],
        }
        if raw_message.get("tool_calls"):
            message["tool_calls"] = [
                {
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "arguments": call["function"]["arguments"],
                }
                for call in raw_message["tool_calls"]
            ]
        body = {
            "message": message,
            "finish_reason": choice["finish_reason"],
            "usage": copy.deepcopy(node["usage"]),
        }
        node["model_io"]["response"] = {
            "kind": "normalized_stream_response",
            "sha256": _json_sha256(body),
            "body": body,
        }
    results = _write_run(tmp_path / "run", [trace])
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output))

    assert summary["rows"]["total"] == 2


@pytest.mark.parametrize(("field", "value"), [("reasoning_tokens", True), ("reasoning_tokens", 6)])
def test_captured_response_usage_counts_must_be_valid(tmp_path: Path, field: str, value: object) -> None:
    trace = _linear_trace()
    node = trace["nodes"][2]
    node["usage"][field] = value
    response = node["model_io"]["response"]
    response["body"]["usage"]["completion_tokens_details"] = {field: value}
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^captured_response_usage_invalid$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_tool_schema_must_be_stable_across_full_requests(tmp_path: Path) -> None:
    trace = _branched_trace()
    node = trace["nodes"][6]
    request = copy.deepcopy(node["model_io"]["request"])
    base_request = trace["nodes"][2]["model_io"]["request"]["body"]
    body = {
        **base_request,
        "tools": [_tool("different-tool")],
        "messages": [
            *base_request["messages"],
            {"role": "tool", "content": "branch-result", "tool_call_id": "call-1"},
        ],
    }
    request = {"kind": "full", "sha256": _json_sha256(body), "body": body}
    node["model_io"]["request"] = request
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^tool_schema_changed_within_trace$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_malformed_tool_arguments_are_rejected(tmp_path: Path) -> None:
    trace = _linear_trace()
    node = trace["nodes"][2]
    node["message"]["tool_calls"][0]["arguments"] = "{"
    response = node["model_io"]["response"]
    response["body"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{"
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^assistant_tool_arguments_not_json$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_authentic_zero_reasoning_tool_turn_is_preserved_without_synthesis(tmp_path: Path) -> None:
    trace = _linear_trace()
    node = trace["nodes"][2]
    node["message"].pop("reasoning_content")
    node["usage"]["reasoning_tokens"] = 0
    response = node["model_io"]["response"]
    response_message = response["body"]["choices"][0]["message"]
    response_message.pop("reasoning")
    response["body"]["usage"]["completion_tokens_details"] = {"reasoning_tokens": 0}
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])
    output = tmp_path / "dataset"

    export_sft(_options(results, output))

    first = _read_jsonl(output / "train" / "train.jsonl")[0]
    assert first["target_has_reasoning"] is False
    assert "reasoning_content" not in first["messages"][-1]


def test_export_is_byte_deterministic_and_records_provenance_hashes(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace(), _branched_trace()])
    first = tmp_path / "first"
    second = tmp_path / "second"

    export_sft(_options(results, first, expected_count=2))
    export_sft(_options(results, second, expected_count=2))

    for relative in (
        "train/train.jsonl",
        "validation/train.jsonl",
        "task-split.json",
        "manifest.json",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["source_artifacts"]["results.jsonl"]["sha256"] == _sha256(results)
    assert manifest["source_artifacts"]["inputs/task_file.txt"]["sha256"] == _sha256(
        results.parent / "inputs" / "task_file.txt"
    )
    assert manifest["source_artifacts"]["inputs/image_manifest.json"]["sha256"] == _sha256(
        results.parent / "inputs" / "image_manifest.json"
    )


def test_exported_split_is_loadable_by_huggingface_datasets(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    output = tmp_path / "dataset"
    export_sft(_options(results, output))

    dataset = load_dataset(str(output / "train"), split="train")

    assert len(dataset) == 2
    assert dataset.column_names == [
        "assistant_target_count",
        "history_reasoning_policy",
        "is_correct",
        "messages",
        "reward",
        "source_episode_id",
        "source_node_index",
        "source_split_row_index",
        "source_trace_index",
        "source_trajectory_assistant_turn_count",
        "target_assistant_message_index",
        "target_assistant_turn_index",
        "target_has_reasoning",
        "task_id",
        "tools",
    ]


def test_task_split_is_grouped_by_opaque_task_hash(tmp_path: Path) -> None:
    traces = [
        _linear_trace("rollout-a", task_name="shared-task"),
        _linear_trace("rollout-b", task_name="shared-task"),
    ]
    traces[1]["task"] = copy.deepcopy(traces[0]["task"])
    results = _write_run(tmp_path / "run", traces)
    output = tmp_path / "dataset"
    options = ExportOptions(
        results=results,
        output_dir=output,
        selection="pass-only",
        validation_permyriad=5000,
    )

    export_sft(options)

    task_hash = hashlib.sha256(
        json.dumps(traces[0]["task"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    split = _split_for_task(task_hash, salt=options.split_salt, validation_permyriad=5000)
    other = "validation" if split == "train" else "train"
    assert len(_read_jsonl(output / split / "train.jsonl")) == 4
    assert _read_jsonl(output / other / "train.jsonl") == []


def test_active_writer_lock_blocks_export(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    lock_path = results.parent / ".writer.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ExportError, match="^source_run_is_active$"):
            export_sft(_options(results, tmp_path / "dataset"))


def test_input_manifest_digest_mismatch_fails_before_output(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    (results.parent / "inputs" / "task_file.txt").write_text("changed\n")

    with pytest.raises(ExportError, match="^input_manifest_digest_mismatch$"):
        export_sft(_options(results, tmp_path / "dataset"))
    assert not (tmp_path / "dataset").exists()


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    output = tmp_path / "dataset"
    output.mkdir()
    marker = output / "marker"
    marker.write_text("keep")

    with pytest.raises(ExportError, match="^output_already_exists$"):
        export_sft(_options(results, output))
    assert marker.read_text() == "keep"


def test_cli_failure_is_redacted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    private_marker = "private-prompt-and-error-marker"
    trace = _linear_trace()
    trace["task"]["prompt"] = private_marker
    trace["nodes"][2]["message"].pop("reasoning_content")
    results = _write_run(tmp_path / "run", [trace])

    status = main(
        [
            str(results),
            "--output-dir",
            str(tmp_path / "dataset"),
            "--selection",
            "pass-only",
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert private_marker not in captured.out
    assert private_marker not in captured.err
    assert json.loads(captured.err) == {"code": "trace_validation_failed", "status": "error"}
