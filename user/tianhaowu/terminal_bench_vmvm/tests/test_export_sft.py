import copy
import fcntl
import hashlib
import json
import subprocess
from pathlib import Path

import direct_qwen_workers as direct_workers
import export_sft as exporter
import pytest
from audit_traces import _json_sha256
from datasets import load_dataset
from export_sft import (
    ExportError,
    ExportOptions,
    _split_for_task,
    export_sft,
    main,
)
from verifiers.v1.dialects.chat import message_to_wire
from verifiers.v1.types import AssistantMessage, ToolCall


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
        "object": "chat.completion",
        "created": 1,
        "model": "synthetic-model",
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


def _use_normalized_stream_responses(trace: dict) -> None:
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
            "id": exact["body"]["id"],
            "created": exact["body"]["created"],
            "model": exact["body"]["model"],
            "message": message,
            "finish_reason": choice["finish_reason"],
            "usage": copy.deepcopy(node["usage"]),
        }
        node["model_io"]["response"] = {
            "kind": "normalized_stream_response",
            "sha256": _json_sha256(body),
            "body": body,
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
        "task": {
            "idx": 0,
            "name": task_name,
            "prompt": "synthetic-question",
            "slug": task_name.rsplit("/", 1)[-1],
        },
        "nodes": nodes,
        "rewards": {"solved": reward},
        "metrics": {},
        "info": {},
        "is_completed": True,
        "stop_condition": "agent_completed",
        "errors": [],
        "timing": {},
    }


def _add_redundant_kimi_provider_fields(trace: dict) -> None:
    for node in trace["nodes"]:
        if node.get("sampled") is not True:
            continue
        response = node["model_io"]["response"]
        raw_message = response["body"]["choices"][0]["message"]
        reasoning = raw_message.pop("reasoning")
        raw_message["reasoning_content"] = reasoning
        raw_message["provider_specific_fields"] = {"reasoning": reasoning, "refusal": None}
        response["sha256"] = _json_sha256(response["body"])

    second_request = trace["nodes"][4]["model_io"]["request"]
    replayed_assistant = second_request["append_fields"]["messages"][0]
    replayed_assistant["provider_specific_fields"] = {
        "reasoning": replayed_assistant["reasoning_content"],
        "refusal": None,
    }
    first_request = trace["nodes"][2]["model_io"]["request"]["body"]
    second_request["sha256"] = _json_sha256(
        {
            **first_request,
            "messages": [
                *first_request["messages"],
                *second_request["append_fields"]["messages"],
            ],
        }
    )


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


def _selection_index_sha256(slugs: set[str], approved: list[str]) -> str:
    return hashlib.sha256(
        "".join(f"{index}\n" for index, slug in enumerate(sorted(approved)) if slug in slugs).encode()
    ).hexdigest()


def _write_exclusion_selection(
    results: Path,
    *,
    missing_or_errored: set[str],
    strict_invalid_pass: set[str],
) -> tuple[Path, str]:
    run = results.parent
    approved = [line for line in (run / "inputs/task_file.txt").read_text().splitlines() if line]
    order = {slug: index for index, slug in enumerate(sorted(approved))}
    union = missing_or_errored | strict_invalid_pass
    selection_dir = run.parent / "selection"
    selection_dir.mkdir()
    bodies = {
        "repair_tasks.txt": "".join(f"{slug}\n" for slug in sorted(union, key=order.__getitem__)).encode(),
        "repair_missing_or_errored_tasks.txt": "".join(
            f"{slug}\n" for slug in sorted(missing_or_errored, key=order.__getitem__)
        ).encode(),
        "repair_strict_invalid_pass_tasks.txt": "".join(
            f"{slug}\n" for slug in sorted(strict_invalid_pass, key=order.__getitem__)
        ).encode(),
    }
    for filename, body in bodies.items():
        path = selection_dir / filename
        path.write_bytes(body)
        path.chmod(0o600)
    repository = Path(exporter.__file__).resolve().parents[3]
    revision = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    submodules = {}
    for relative in exporter.REQUIRED_RUNTIME_SUBMODULES:
        record = subprocess.check_output(
            ["git", "-C", str(repository), "ls-tree", revision, "--", relative],
            text=True,
        ).strip()
        submodules[relative] = record.split()[2]
    source_names = {
        "config": "config.toml",
        "direct_workers": "direct_workers.json",
        "image_manifest": "inputs/image_manifest.json",
        "inputs_manifest": "inputs/manifest.json",
        "provenance": "provenance.txt",
        "results": "results.jsonl",
        "source_config": "inputs/source_config.toml",
        "task_file": "inputs/task_file.txt",
    }
    retry_bytes = "".join(f"{name}\n" for name in sorted(direct_workers.ROLLOUT_RETRY_POLICY)).encode()
    manifest = {
        "approval": {
            "approved_task_count": len(approved),
            "approved_task_file_sha256": _sha256(run / "inputs/task_file.txt"),
        },
        "code": {
            "exporter_sha256": _sha256(Path(exporter.__file__)),
            "materializer_sha256": _sha256(Path(exporter.__file__).with_name("materialize_qwen_repair.py")),
            "repository_revision": revision,
            "submodules": submodules,
        },
        "config": {
            "capture_model_io": True,
            "enable_thinking": True,
            "max_concurrent": direct_workers.MAX_DIRECT_CONCURRENCY,
            "max_total_tokens": 262_144,
            "preserve_thinking": True,
            "provider_concurrency": direct_workers.PRODUCTION_PROVIDER_CONCURRENCY,
            "retry_class_count": len(direct_workers.ROLLOUT_RETRY_POLICY),
            "retry_policy_sha256": hashlib.sha256(retry_bytes).hexdigest(),
            "sha256": "a" * 64,
            "template_sha256": "b" * 64,
        },
        "kind": exporter.REPAIR_SELECTION_KIND,
        "planner": {
            "approved_task_count": len(approved),
            "contract_verifiers_revision": direct_workers.ADMISSION_VERIFIERS_REVISION,
            "missing_or_errored_count": len(missing_or_errored),
            "module_sha256": direct_workers.ADMISSION_RESUME_MODULE_SHA256,
            "retained_count": len(approved) - len(missing_or_errored),
            "task_index_order_sha256": hashlib.sha256(
                "".join(f"{index}\0{slug}\n" for index, slug in enumerate(sorted(approved))).encode()
            ).hexdigest(),
        },
        "schema_version": exporter.REPAIR_SELECTION_SCHEMA_VERSION,
        "selection": {
            "approved_repair_count": len(union),
            "missing_or_errored_count": len(missing_or_errored),
            "missing_or_errored_indices_sha256": _selection_index_sha256(missing_or_errored, approved),
            "missing_or_errored_task_file_sha256": hashlib.sha256(
                bodies["repair_missing_or_errored_tasks.txt"]
            ).hexdigest(),
            "repair_union_indices_sha256": _selection_index_sha256(union, approved),
            "strict_invalid_pass_count": len(strict_invalid_pass),
            "strict_invalid_pass_indices_sha256": _selection_index_sha256(strict_invalid_pass, approved),
            "strict_invalid_pass_task_file_sha256": hashlib.sha256(
                bodies["repair_strict_invalid_pass_tasks.txt"]
            ).hexdigest(),
            "task_file_sha256": hashlib.sha256(bodies["repair_tasks.txt"]).hexdigest(),
        },
        "source": {
            "artifacts": {
                label: {
                    "sha256": _sha256(run / relative),
                    "size_bytes": (run / relative).stat().st_size,
                }
                for label, relative in source_names.items()
            },
            "routing_epoch": 3,
            "task_count": len(approved),
        },
    }
    manifest_path = selection_dir / "repair_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_path.chmod(0o600)
    return manifest_path, _sha256(manifest_path)


def _write_run(
    run_dir: Path,
    traces: list[dict],
    *,
    approved_slugs: list[str] | None = None,
    include_image_manifest: bool = True,
) -> Path:
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    source_config = inputs / "source_config.toml"
    task_file = inputs / "task_file.txt"
    image_manifest = inputs / "image_manifest.json"
    source_config.write_text("source = true\n")
    if approved_slugs is None:
        approved_slugs = sorted(
            {str(trace["task"].get("slug") or trace["task"]["name"]).rsplit("/", 1)[-1] for trace in traces}
        )
    task_file.write_text("".join(f"{slug}\n" for slug in approved_slugs))
    inputs_manifest = {
        "config": {"sha256": _sha256(source_config)},
        "task_file": {"sha256": _sha256(task_file)},
    }
    if include_image_manifest:
        image_manifest.write_text("{}\n")
        inputs_manifest["image_manifest"] = {
            "source": str(image_manifest.resolve()),
            "snapshot": str(image_manifest.resolve()),
            "sha256": _sha256(image_manifest),
        }
    (inputs / "manifest.json").write_text(json.dumps(inputs_manifest, sort_keys=True) + "\n")
    (run_dir / "provenance.txt").write_text("prime_rl=synthetic\n")
    image_config = (
        [
            f'image_manifest = "{image_manifest.resolve()}"',
            f'image_manifest_sha256 = "{_sha256(image_manifest)}"',
        ]
        if include_image_manifest
        else []
    )
    (run_dir / "config.toml").write_text(
        "\n".join(
            [
                'model = "synthetic-model"',
                f"num_tasks = {len(approved_slugs)}",
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
                'id = "terminal-bench-vmvm"',
                'dataset_revision = "dddddddddddddddddddddddddddddddddddddddd"',
                f'task_file_sha256 = "{_sha256(task_file)}"',
                *image_config,
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


def _options(
    results: Path,
    output: Path,
    *,
    selection: str = "all-outcomes",
    expected_count: int | None = None,
    routing_epoch_index: Path | None = None,
    exclusion_selection_manifest: Path | None = None,
    exclusion_selection_manifest_sha256: str | None = None,
    require_task_index_binding: bool = False,
    require_exact_provider_json: bool = False,
):
    return ExportOptions(
        results=results,
        output_dir=output,
        selection=selection,
        expected_count=expected_count,
        validation_permyriad=0,
        routing_epoch_index=routing_epoch_index,
        exclusion_selection_manifest=exclusion_selection_manifest,
        exclusion_selection_manifest_sha256=exclusion_selection_manifest_sha256,
        require_task_index_binding=require_task_index_binding,
        require_exact_provider_json=require_exact_provider_json,
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_routing_epoch_index(
    results: Path,
    epochs: list[int],
    *,
    current_epoch: int = 2,
    output_path: Path | None = None,
) -> Path:
    run_dir = results.parent
    assert current_epoch in {2, 3}
    assert all(epoch in range(1, current_epoch + 1) for epoch in epochs)
    (run_dir / ".direct_router.lock").touch()
    (run_dir / ".writer.lock").touch()
    rows = results.read_bytes().splitlines(keepends=True)
    assert len(rows) == len(epochs)
    epoch1_rows = [raw for raw, epoch in zip(rows, epochs, strict=True) if epoch == 1]
    epoch1_hashes = [hashlib.sha256(raw).hexdigest() for raw in epoch1_rows]
    epoch1_path = run_dir / "qwen_router_epoch1_rows.sha256"
    epoch1_path.write_text("".join(f"{digest}\n" for digest in epoch1_hashes))
    direct_workers_path = run_dir / "direct_workers.json"
    direct_workers_path.write_text("{}\n")
    source_provenance_sha256 = _sha256(run_dir / "provenance.txt")
    transition = {
        "schema_version": 1,
        "kind": "qwen-direct-router-policy-transition",
        "source": {
            "canonical_path": str((run_dir.parent / "epoch-one-source").resolve()),
            "slurm_job_id": "123",
            "prime_rl": "1" * 40,
            "verifiers": "2" * 40,
            "renderers": "3" * 40,
            "config_sha256": "4" * 64,
            "source_config_sha256": "a" * 64,
            "inputs_manifest_sha256": "5" * 64,
            "provenance_sha256": source_provenance_sha256,
            "results_sha256": "6" * 64,
            "results_size_bytes": sum(len(raw) for raw in epoch1_rows),
            "direct_workers_sha256": "7" * 64,
        },
        "resume_plan": {
            "retained_results_sha256": hashlib.sha256(b"".join(epoch1_rows)).hexdigest(),
            "retained_results_size_bytes": sum(len(raw) for raw in epoch1_rows),
            "retained_row_count": len(epoch1_rows),
            "owed_rollout_count": max(1, len(rows) - len(epoch1_rows)),
            "epoch1_row_hashes_sha256": _sha256(epoch1_path),
        },
        "from_router": {
            "manifest_schema_version": 1,
            "policy": "round_robin",
            "request_id_headers": [],
        },
        "to_router": {
            "manifest_schema_version": 2,
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "spec_sha256": "8" * 64,
            "endpoint_bundle_sha256": "9" * 64,
            "direct_workers_sha256": _sha256(direct_workers_path),
        },
        "child": {
            "canonical_path": str(run_dir.resolve()),
            "routing_epoch": 2,
            "config_sha256": _sha256(run_dir / "config.toml"),
            "source_config_sha256": _sha256(run_dir / "inputs" / "source_config.toml"),
            "inputs_manifest_sha256": _sha256(run_dir / "inputs" / "manifest.json"),
        },
    }
    transition_path = run_dir / "qwen_router_transition.json"
    transition_path.write_text(json.dumps(transition, sort_keys=True, separators=(",", ":")) + "\n")
    transition_sha256 = _sha256(transition_path)
    with (run_dir / "provenance.txt").open("a") as provenance:
        provenance.write(f"qwen_router_transition_sha256={transition_sha256}\n")
        if current_epoch == 3:
            epoch2_records = [
                {
                    "row_sha256": hashlib.sha256(raw).hexdigest(),
                    "routing_epoch": epoch,
                }
                for raw, epoch in zip(rows, epochs, strict=True)
                if epoch <= 2
            ]
            (run_dir / "qwen_router_epoch2_lineage.jsonl").write_text(
                "".join(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in epoch2_records)
            )
            admission_path = run_dir / "qwen_router_admission_transition.json"
            admission_path.write_text("{}\n")
            admission_transition_sha256 = _sha256(admission_path)
            provenance.write(f"qwen_router_admission_transition_sha256={admission_transition_sha256}\n")
        else:
            admission_transition_sha256 = None
        provenance.write(f"qwen_router_epoch={current_epoch}\n")
    records = [
        {
            "row": row,
            "row_sha256": hashlib.sha256(raw).hexdigest(),
            "routing_epoch": epoch,
        }
        for row, (raw, epoch) in enumerate(zip(rows, epochs, strict=True))
    ]
    header = {
        "schema_version": 1,
        "kind": "qwen-routing-epoch-index",
        "results_sha256": _sha256(results),
        "transition_sha256": transition_sha256,
        "admission_transition_sha256": admission_transition_sha256,
        "routing_epoch": current_epoch,
        "row_count": len(records),
    }
    index_path = output_path or run_dir / "qwen_router_epochs.jsonl"
    index_path.write_text(
        "".join(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n" for value in (header, *records))
    )
    return index_path


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
    assert second["messages"][2]["reasoning_content"] == "first-reasoning"
    assert second["messages"][2]["finish_reason"] == "tool_calls"
    assert second["messages"][-1]["trainable"] is True
    assert second["messages"][-1]["reasoning_content"] == "second-reasoning"
    assert second["target_finish_reason"] == "stop"
    assert second["transcript_fidelity"] == {
        "retained_assistant_reasoning_fields": 2,
        "retained_sampled_finish_reasons": 2,
        "source_assistant_reasoning_fields": 2,
        "source_sampled_finish_reasons": 2,
    }
    assert all(sum(message["trainable"] is True for message in row["messages"]) == 1 for row in rows)
    assert rows[0]["task_id"] != "synthetic-task"
    assert rows[0]["source_episode_id"] != "trace-pass"
    assert all("routing_epoch" not in row for row in rows)
    assert "routing_epochs" not in json.loads((output / "manifest.json").read_text())


def test_exports_redundant_kimi_provider_fields_without_losing_reasoning(tmp_path: Path) -> None:
    trace = _linear_trace()
    _add_redundant_kimi_provider_fields(trace)
    results = _write_run(tmp_path / "run", [trace])
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output, expected_count=1))

    rows = _read_jsonl(output / "train" / "train.jsonl")
    assert summary["rows"] == {"total": 2, "train": 2, "validation": 0}
    assert [row["messages"][-1]["reasoning_content"] for row in rows] == [
        "first-reasoning",
        "second-reasoning",
    ]
    assert rows[1]["messages"][2]["reasoning_content"] == "first-reasoning"
    assert "provider_specific_fields" not in json.dumps(rows, sort_keys=True)


@pytest.mark.parametrize(
    "provider_fields",
    [
        "malformed",
        {"reasoning": "first-reasoning"},
        {"reasoning": "first-reasoning", "refusal": None, "opaque": True},
        {"reasoning": {"text": "first-reasoning"}, "refusal": None},
        {"reasoning": "different-reasoning", "refusal": None},
        {"reasoning": "first-reasoning", "refusal": "blocked"},
    ],
)
def test_captured_response_rejects_nonredundant_kimi_provider_fields(provider_fields: object) -> None:
    trace = _linear_trace()
    _add_redundant_kimi_provider_fields(trace)
    node = trace["nodes"][2]
    response = node["model_io"]["response"]
    response["body"]["choices"][0]["message"]["provider_specific_fields"] = provider_fields
    response["sha256"] = _json_sha256(response["body"])

    with pytest.raises(ExportError, match="^captured_response_invalid$"):
        exporter._validate_captured_response(node)


def test_export_rejects_nonredundant_kimi_provider_fields_in_captured_response(tmp_path: Path) -> None:
    trace = _linear_trace()
    _add_redundant_kimi_provider_fields(trace)
    response = trace["nodes"][2]["model_io"]["response"]
    response["body"]["choices"][0]["message"]["provider_specific_fields"]["refusal"] = "blocked"
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^captured_response_invalid$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_export_rejects_nonredundant_kimi_provider_fields_in_replayed_request(tmp_path: Path) -> None:
    trace = _linear_trace()
    _add_redundant_kimi_provider_fields(trace)
    request = trace["nodes"][4]["model_io"]["request"]
    request["append_fields"]["messages"][0]["provider_specific_fields"]["reasoning"] = "different-reasoning"
    first_request = trace["nodes"][2]["model_io"]["request"]["body"]
    request["sha256"] = _json_sha256(
        {
            **first_request,
            "messages": [*first_request["messages"], *request["append_fields"]["messages"]],
        }
    )
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^trace_validation_failed$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_export_accepts_pinned_verifiers_exclude_none_assistant_serialization(tmp_path: Path) -> None:
    trace = _linear_trace()
    assistant = AssistantMessage(
        reasoning_content="first-reasoning",
        tool_calls=[ToolCall(id="call-1", name="terminal", arguments='{"command":"pwd"}')],
    )
    serialized = assistant.model_dump(mode="json", exclude_none=True)
    assert "content" not in serialized
    trace["nodes"][2]["message"] = serialized
    first_response = trace["nodes"][2]["model_io"]["response"]
    first_response["body"]["choices"][0]["message"].pop("content")
    first_response["sha256"] = _json_sha256(first_response["body"])

    wire = message_to_wire(assistant)
    assert wire["content"] is None
    second_request = trace["nodes"][4]["model_io"]["request"]
    second_request["append_fields"]["messages"][0] = wire
    second_request["sha256"] = _json_sha256(
        {
            **trace["nodes"][2]["model_io"]["request"]["body"],
            "messages": [
                *trace["nodes"][2]["model_io"]["request"]["body"]["messages"],
                *second_request["append_fields"]["messages"],
            ],
        }
    )
    results = _write_run(tmp_path / "run", [trace])
    output = tmp_path / "dataset"

    export_sft(_options(results, output))

    rows = _read_jsonl(output / "train" / "train.jsonl")
    assert rows[0]["messages"][-1]["content"] == ""
    assert rows[0]["messages"][-1]["reasoning_content"] == "first-reasoning"
    assert rows[0]["messages"][-1]["tool_calls"][0]["function"]["arguments"] == '{"command":"pwd"}'


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


def _remove_unproven_tool_reasoning(trace: dict) -> None:
    node = trace["nodes"][2]
    node["message"].pop("reasoning_content")
    response = node["model_io"]["response"]
    response["body"]["choices"][0]["message"].pop("reasoning")
    response["sha256"] = _json_sha256(response["body"])


def test_pass_only_excludes_untrainable_non_pass_before_strict_audit(tmp_path: Path) -> None:
    failed = _linear_trace("failed", reward=0, task_name="failed-task")
    _remove_unproven_tool_reasoning(failed)
    results = _write_run(
        tmp_path / "run",
        [
            _linear_trace("passed", reward=1, task_name="passed-task"),
            failed,
        ],
    )
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output, selection="pass-only", expected_count=2))

    manifest = json.loads((output / "manifest.json").read_text())
    assert summary["input_traces"] == 2
    assert summary["selected_traces"] == 1
    assert summary["rows"]["total"] == 2
    assert manifest["counts"]["scored_fail_traces"] == 1
    assert manifest["counts"]["selection_excluded_fail_traces"] == 1


@pytest.mark.parametrize(("selection", "reward"), [("pass-only", 1), ("all-outcomes", 0)])
def test_selected_untrainable_trace_still_fails_closed(tmp_path: Path, selection: str, reward: float) -> None:
    trace = _linear_trace(reward=reward)
    _remove_unproven_tool_reasoning(trace)
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^trace_validation_failed$"):
        export_sft(_options(results, tmp_path / "dataset", selection=selection))
    assert not (tmp_path / "dataset").exists()


def test_pass_only_still_validates_basic_non_pass_schema(tmp_path: Path) -> None:
    trace = _linear_trace(reward=0)
    trace["stop_condition"] = None
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^trace_stop_condition_invalid$"):
        export_sft(_options(results, tmp_path / "dataset", selection="pass-only"))
    assert not (tmp_path / "dataset").exists()


def test_error_rows_are_excluded_without_inspecting_error_payload(tmp_path: Path) -> None:
    error_trace = {
        "id": "error-trace",
        "task": {
            "idx": 1,
            "name": "error-task",
            "prompt": "private-marker",
            "slug": "error-task",
        },
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


def test_hash_valid_untrainable_raw_finish_reason_is_rejected(tmp_path: Path) -> None:
    trace = _linear_trace()
    response = trace["nodes"][2]["model_io"]["response"]
    response["body"]["choices"][0]["finish_reason"] = "length"
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^captured_response_finish_reason_mismatch$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_sampled_finish_reason_is_required(tmp_path: Path) -> None:
    trace = _linear_trace()
    trace["nodes"][2].pop("finish_reason")
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^captured_response_finish_reason_invalid$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_sampled_length_finish_reason_is_not_trainable(tmp_path: Path) -> None:
    trace = _linear_trace()
    node = trace["nodes"][2]
    node["finish_reason"] = "length"
    response = node["model_io"]["response"]
    response["body"]["choices"][0]["finish_reason"] = "length"
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^sampled_finish_reason_length$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_unknown_sampled_finish_reason_is_not_trainable(tmp_path: Path) -> None:
    trace = _linear_trace()
    node = trace["nodes"][2]
    node["finish_reason"] = "content_filter"
    response = node["model_io"]["response"]
    response["body"]["choices"][0]["finish_reason"] = "content_filter"
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^assistant_finish_reason_invalid$"):
        export_sft(_options(results, tmp_path / "dataset"))


@pytest.mark.parametrize("field", ["provider_state", "reasoning_details"])
@pytest.mark.parametrize("value", [{"opaque": "synthetic"}, []])
def test_unsupported_provider_reasoning_state_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    trace = _linear_trace()
    response = trace["nodes"][2]["model_io"]["response"]
    response["body"]["choices"][0]["message"][field] = value
    response["sha256"] = _json_sha256(response["body"])
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^unsupported_assistant_state$"):
        export_sft(_options(results, tmp_path / "dataset"))


@pytest.mark.parametrize("field", ["provider_state", "reasoning_details"])
def test_null_provider_reasoning_state_is_tolerated(tmp_path: Path, field: str) -> None:
    trace = _linear_trace()
    node = trace["nodes"][2]
    node["message"][field] = None
    response = node["model_io"]["response"]
    response["body"]["choices"][0]["message"][field] = None
    response["sha256"] = _json_sha256(response["body"])
    second_request = trace["nodes"][4]["model_io"]["request"]
    second_request["append_fields"]["messages"][0][field] = None
    second_request["sha256"] = _json_sha256(
        {
            **node["model_io"]["request"]["body"],
            "messages": [
                *node["model_io"]["request"]["body"]["messages"],
                *second_request["append_fields"]["messages"],
            ],
        }
    )
    results = _write_run(tmp_path / "run", [trace])

    summary = export_sft(_options(results, tmp_path / "dataset"))

    assert summary["rows"]["total"] == 2


@pytest.mark.parametrize("field", ["provider_state", "reasoning_details"])
def test_unsupported_provider_state_is_rejected_anywhere_in_selected_trace(tmp_path: Path, field: str) -> None:
    trace = _linear_trace()
    trace["nodes"][2][field] = {"opaque": "synthetic"}
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^unsupported_assistant_state$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_tool_schema_requires_explicit_function_type(tmp_path: Path) -> None:
    del tmp_path
    tool = _tool()
    tool.pop("type")

    with pytest.raises(ExportError, match="^tool_schema_invalid$"):
        exporter._normalize_tools([tool])


def test_tool_schema_rejects_ambiguous_json_null_padding() -> None:
    tool = _tool()
    tool["function"]["parameters"]["properties"]["command"]["default"] = None

    with pytest.raises(ExportError, match="^tool_schema_invalid$"):
        exporter._normalize_tools([tool])


def test_captured_request_messages_must_match_the_graph_path(tmp_path: Path) -> None:
    trace = _linear_trace()
    request = trace["nodes"][4]["model_io"]["request"]
    request["append_fields"]["messages"][-1]["content"] = "wire-only tool result"
    request["sha256"] = _json_sha256(
        {
            **trace["nodes"][2]["model_io"]["request"]["body"],
            "messages": [
                *trace["nodes"][2]["model_io"]["request"]["body"]["messages"],
                *request["append_fields"]["messages"],
            ],
        }
    )
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^trace_validation_failed$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_normalized_stream_responses_are_validated_and_exported(tmp_path: Path) -> None:
    trace = _linear_trace()
    _use_normalized_stream_responses(trace)
    results = _write_run(tmp_path / "run", [trace])
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output))

    assert summary["rows"]["total"] == 2


def test_exact_provider_json_requirement_rejects_normalized_stream_responses(tmp_path: Path) -> None:
    trace = _linear_trace()
    _use_normalized_stream_responses(trace)
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^normalized_stream_response_disallowed$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                require_exact_provider_json=True,
            )
        )


def test_exact_provider_json_requirement_is_hash_bound_in_manifest(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    output = tmp_path / "dataset"

    export_sft(_options(results, output, require_exact_provider_json=True))

    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["source_validation"] == {
        "max_sequence_tokens": 262_144,
        "require_exact_provider_json": True,
        "require_model_io": True,
        "require_reasoning": True,
        "require_request_graph_match": True,
    }


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
    second_request = trace["nodes"][4]["model_io"]["request"]
    second_request["append_fields"]["messages"][0]["tool_calls"][0]["function"]["arguments"] = "{"
    second_request["sha256"] = _json_sha256(
        {
            **node["model_io"]["request"]["body"],
            "messages": [
                *node["model_io"]["request"]["body"]["messages"],
                *second_request["append_fields"]["messages"],
            ],
        }
    )
    results = _write_run(tmp_path / "run", [trace])

    with pytest.raises(ExportError, match="^assistant_tool_arguments_not_json$"):
        export_sft(_options(results, tmp_path / "dataset"))


@pytest.mark.parametrize(
    "arguments",
    ["[]", "null", '{"value":null}', '{"value":NaN}', '{"value":1e400}', '{"value":1,"value":2}'],
)
def test_tool_arguments_require_strict_finite_null_free_json_object(arguments: str) -> None:
    with pytest.raises(ExportError, match="^assistant_tool_arguments_not_json$"):
        exporter._normalize_tool_call({"id": "call-1", "name": "terminal", "arguments": arguments})


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
    second_request = trace["nodes"][4]["model_io"]["request"]
    second_request["append_fields"]["messages"][0].pop("reasoning_content")
    second_request["sha256"] = _json_sha256(
        {
            **node["model_io"]["request"]["body"],
            "messages": [
                *node["model_io"]["request"]["body"]["messages"],
                *second_request["append_fields"]["messages"],
            ],
        }
    )
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
        exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "manifest.json",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["exporter"]["format_version"] == 3
    assert json.loads((first / "task-split.json").read_text())["format_version"] == 3
    assert manifest["target_rendering"] == exporter.TARGET_RENDERING_CONTRACT
    assert manifest["source_validation"] == {
        "max_sequence_tokens": 262_144,
        "require_exact_provider_json": False,
        "require_model_io": True,
        "require_reasoning": True,
        "require_request_graph_match": True,
    }
    assert (
        manifest["artifacts"][exporter.TARGET_RENDERING_CONTRACT_FILENAME]["sha256"]
        == exporter.TARGET_RENDERING_CONTRACT_SHA256
    )
    assert manifest["source_artifacts"]["results.jsonl"]["sha256"] == _sha256(results)
    assert manifest["source_artifacts"]["inputs/task_file.txt"]["sha256"] == _sha256(
        results.parent / "inputs" / "task_file.txt"
    )
    assert manifest["source_artifacts"]["inputs/image_manifest.json"]["sha256"] == _sha256(
        results.parent / "inputs" / "image_manifest.json"
    )


def test_export_accepts_fully_absent_optional_image_manifest(tmp_path: Path) -> None:
    results = _write_run(
        tmp_path / "run",
        [_linear_trace()],
        include_image_manifest=False,
    )
    output = tmp_path / "dataset"

    export_sft(_options(results, output))

    manifest = json.loads((output / "manifest.json").read_text())
    assert "inputs/image_manifest.json" not in manifest["source_artifacts"]


@pytest.mark.parametrize(
    "state",
    [
        "taskset_path_only",
        "taskset_digest_only",
        "manifest_only",
        "snapshot_only",
        "taskset_without_manifest",
        "manifest_snapshot_without_taskset",
    ],
)
def test_export_rejects_partial_or_unbound_optional_image_manifest(tmp_path: Path, state: str) -> None:
    results = _write_run(
        tmp_path / "run",
        [_linear_trace()],
        include_image_manifest=False,
    )
    run = results.parent
    snapshot = run / "inputs/image_manifest.json"
    manifest_path = run / "inputs/manifest.json"
    config = run / "config.toml"
    if state in {
        "taskset_path_only",
        "snapshot_only",
        "taskset_without_manifest",
        "manifest_snapshot_without_taskset",
    }:
        snapshot.write_text("{}\n")
    if state == "taskset_path_only":
        config.write_text(config.read_text() + f'image_manifest = "{snapshot.resolve()}"\n')
    elif state == "taskset_digest_only":
        config.write_text(config.read_text() + f'image_manifest_sha256 = "{"a" * 64}"\n')
    elif state == "taskset_without_manifest":
        config.write_text(
            config.read_text()
            + f'image_manifest = "{snapshot.resolve()}"\n'
            + f'image_manifest_sha256 = "{_sha256(snapshot)}"\n'
        )
    elif state in {"manifest_only", "manifest_snapshot_without_taskset"}:
        manifest = json.loads(manifest_path.read_text())
        manifest["image_manifest"] = {
            "source": str(snapshot),
            "snapshot": str(snapshot),
            "sha256": _sha256(snapshot) if snapshot.exists() else "a" * 64,
        }
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")

    with pytest.raises(ExportError, match="^image_manifest_binding_invalid$"):
        export_sft(_options(results, tmp_path / "dataset"))


@pytest.mark.parametrize(
    "state",
    [
        "config_digest_mismatch",
        "config_path_mismatch",
        "manifest_digest_mismatch",
        "manifest_path_mismatch",
        "manifest_record_partial",
        "dangling_snapshot",
    ],
)
def test_export_rejects_mismatched_or_dangling_optional_image_manifest(tmp_path: Path, state: str) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    run = results.parent
    snapshot = run / "inputs/image_manifest.json"
    manifest_path = run / "inputs/manifest.json"
    config = run / "config.toml"
    if state == "config_digest_mismatch":
        config.write_text(config.read_text().replace(_sha256(snapshot), "a" * 64))
    elif state == "config_path_mismatch":
        other = tmp_path / "other-images.json"
        other.write_text("{}\n")
        config.write_text(config.read_text().replace(str(snapshot.resolve()), str(other.resolve())))
    elif state in {"manifest_digest_mismatch", "manifest_path_mismatch", "manifest_record_partial"}:
        manifest = json.loads(manifest_path.read_text())
        if state == "manifest_digest_mismatch":
            manifest["image_manifest"]["sha256"] = "a" * 64
        elif state == "manifest_path_mismatch":
            other = tmp_path / "other-images.json"
            other.write_text("{}\n")
            manifest["image_manifest"]["snapshot"] = str(other.resolve())
        else:
            manifest["image_manifest"].pop("source")
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    else:
        snapshot.unlink()
        snapshot.symlink_to(run / "inputs/missing-image-manifest.json")

    with pytest.raises(ExportError, match="^image_manifest_binding_invalid$"):
        export_sft(_options(results, tmp_path / "dataset"))


def test_target_rendering_contract_is_immutable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    modified = tmp_path / exporter.TARGET_RENDERING_CONTRACT_FILENAME
    modified.write_bytes(exporter.TARGET_RENDERING_CONTRACT_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(exporter, "TARGET_RENDERING_CONTRACT_PATH", modified)

    with pytest.raises(ExportError, match="^target_rendering_contract_hash_mismatch$"):
        exporter._load_target_rendering_contract()


def test_routing_epoch_index_is_strictly_bound_and_propagated(tmp_path: Path) -> None:
    results = _write_run(
        tmp_path / "run",
        [
            _linear_trace("epoch-one", task_name="first-task"),
            _linear_trace("epoch-two", task_name="second-task"),
        ],
    )
    index_path = _write_routing_epoch_index(results, [2, 1])
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output, routing_epoch_index=index_path))

    rows = _read_jsonl(output / "train" / "train.jsonl")
    assert [row["routing_epoch"] for row in rows] == [2, 2, 1, 1]
    assert summary["routing_epoch_rows"] == {"1": 2, "2": 2}
    manifest = json.loads((output / "manifest.json").read_text())
    transition_path = results.parent / "qwen_router_transition.json"
    assert manifest["routing_epochs"] == {
        "current_epoch": 2,
        "emitted_rows": {"1": 2, "2": 2},
        "epoch1_row_hashes_sha256": _sha256(results.parent / "qwen_router_epoch1_rows.sha256"),
        "index_sha256": _sha256(index_path),
        "input_traces": {"1": 1, "2": 1},
        "results_sha256": _sha256(results),
        "row_mapping": "one unique SHA-256 mapping per physical results.jsonl row",
        "transition_sha256": _sha256(transition_path),
    }
    assert manifest["source_artifacts"]["qwen_router_epochs.jsonl"]["sha256"] == _sha256(index_path)
    assert manifest["source_artifacts"]["qwen_router_transition.json"]["sha256"] == _sha256(transition_path)
    assert manifest["source_artifacts"]["qwen_router_epoch1_rows.sha256"]["sha256"] == _sha256(
        results.parent / "qwen_router_epoch1_rows.sha256"
    )
    assert manifest["source_artifacts"]["direct_workers.json"]["sha256"] == _sha256(
        results.parent / "direct_workers.json"
    )


def test_schema3_routing_provenance_is_validated_bound_and_propagated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _write_run(
        tmp_path / "run",
        [
            _linear_trace("epoch-one", task_name="first-task"),
            _linear_trace("epoch-two", task_name="second-task"),
            _linear_trace("epoch-three", task_name="third-task"),
        ],
    )
    index_path = _write_routing_epoch_index(results, [1, 2, 3], current_epoch=3)
    manifest_path = results.parent / "direct_workers.json"
    audited: list[Path] = []

    def audit_run_directory(run_dir: Path) -> dict[str, object]:
        audited.append(run_dir)
        return {
            "routing_epoch": 3,
            "manifest_schema_version": direct_workers.ROUTER_MANIFEST_SCHEMA_VERSION,
            "manifest_sha256": _sha256(manifest_path),
        }

    monkeypatch.setattr(direct_workers, "audit_run_directory", audit_run_directory)
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output, routing_epoch_index=index_path))

    assert audited == [results.parent.resolve()]
    assert summary["routing_epoch_rows"] == {"1": 2, "2": 2, "3": 2}
    manifest = json.loads((output / "manifest.json").read_text())
    routing = manifest["routing_epochs"]
    assert routing["current_epoch"] == 3
    assert routing["input_traces"] == {"1": 1, "2": 1, "3": 1}
    assert routing["admission_transition_sha256"] == _sha256(results.parent / "qwen_router_admission_transition.json")
    assert routing["epoch2_lineage_sha256"] == _sha256(results.parent / "qwen_router_epoch2_lineage.jsonl")
    assert "qwen_router_admission_transition.json" in manifest["source_artifacts"]
    assert "qwen_router_epoch2_lineage.jsonl" in manifest["source_artifacts"]


def test_schema3_routing_provenance_and_lineage_drift_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _write_run(
        tmp_path / "run",
        [
            _linear_trace("epoch-one", task_name="first-task"),
            _linear_trace("epoch-two", task_name="second-task"),
            _linear_trace("epoch-three", task_name="third-task"),
        ],
    )
    index_path = _write_routing_epoch_index(results, [1, 2, 3], current_epoch=3)
    manifest_path = results.parent / "direct_workers.json"
    monkeypatch.setattr(
        direct_workers,
        "audit_run_directory",
        lambda _run_dir: {
            "routing_epoch": 3,
            "manifest_schema_version": direct_workers.ROUTER_MANIFEST_SCHEMA_VERSION,
            "manifest_sha256": _sha256(manifest_path),
        },
    )
    lines = [json.loads(line) for line in index_path.read_text().splitlines()]
    lines[2]["routing_epoch"] = 3
    index_path.write_text("".join(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n" for line in lines))

    with pytest.raises(ExportError, match="^routing_epoch_index_classification_mismatch$"):
        export_sft(_options(results, tmp_path / "lineage-drift", routing_epoch_index=index_path))

    fresh_results = _write_run(tmp_path / "audit-run", [_linear_trace()])
    fresh_index = _write_routing_epoch_index(fresh_results, [3], current_epoch=3)

    def reject_audit(_run_dir: Path) -> dict[str, object]:
        raise direct_workers.DirectWorkerError("direct_worker_manifest_admission_invalid")

    monkeypatch.setattr(direct_workers, "audit_run_directory", reject_audit)
    with pytest.raises(ExportError, match="^routing_schema3_provenance_invalid$"):
        export_sft(_options(fresh_results, tmp_path / "audit-drift", routing_epoch_index=fresh_index))


@pytest.mark.parametrize(
    ("drift", "error_code"),
    [
        ("results_hash", "routing_epoch_index_results_hash_mismatch"),
        ("transition_hash", "routing_transition_mismatch"),
        ("row_hash", "routing_epoch_index_row_hash_mismatch"),
        ("duplicate_row_hash", "routing_epoch_index_duplicate_row_hash"),
        ("row_count", "routing_epoch_index_header_invalid"),
        ("missing_row", "routing_epoch_index_row_count_mismatch"),
        ("row_number", "routing_epoch_index_record_invalid"),
        ("routing_epoch", "routing_epoch_index_record_invalid"),
        ("swapped_labels", "routing_epoch_index_classification_mismatch"),
        ("schema_type", "routing_epoch_index_header_invalid"),
        ("row_type", "routing_epoch_index_record_invalid"),
        ("epoch_type", "routing_epoch_index_record_invalid"),
    ],
)
def test_routing_epoch_index_drift_fails_closed(
    tmp_path: Path,
    drift: str,
    error_code: str,
) -> None:
    results = _write_run(
        tmp_path / "run",
        [
            _linear_trace("epoch-one", task_name="first-task"),
            _linear_trace("epoch-two", task_name="second-task"),
        ],
    )
    index_path = _write_routing_epoch_index(results, [1, 2])
    lines = [json.loads(line) for line in index_path.read_text().splitlines()]
    if drift == "results_hash":
        lines[0]["results_sha256"] = "0" * 64
    elif drift == "transition_hash":
        lines[0]["transition_sha256"] = "0" * 64
    elif drift == "row_hash":
        lines[2]["row_sha256"] = "0" * 64
    elif drift == "duplicate_row_hash":
        lines[2]["row_sha256"] = lines[1]["row_sha256"]
    elif drift == "row_count":
        lines[0]["row_count"] += 1
    elif drift == "missing_row":
        lines.pop()
        lines[0]["row_count"] -= 1
    elif drift == "row_number":
        lines[2]["row"] = 0
    elif drift == "routing_epoch":
        lines[2]["routing_epoch"] = 3
    elif drift == "swapped_labels":
        lines[1]["routing_epoch"], lines[2]["routing_epoch"] = (
            lines[2]["routing_epoch"],
            lines[1]["routing_epoch"],
        )
    elif drift == "schema_type":
        lines[0]["schema_version"] = True
    elif drift == "row_type":
        lines[1]["row"] = 0.0
    else:
        lines[1]["routing_epoch"] = 1.0
    index_path.write_text("".join(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n" for line in lines))

    with pytest.raises(ExportError, match=f"^{error_code}$"):
        export_sft(_options(results, tmp_path / "dataset", routing_epoch_index=index_path))


def test_routing_epoch_transition_and_provenance_drift_fail_closed(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    index_path = _write_routing_epoch_index(results, [1])
    transition_path = results.parent / "qwen_router_transition.json"
    transition_path.write_text(
        json.dumps(
            {"schema_version": 1, "kind": "qwen-direct-router-policy-transition", "drift": True},
            sort_keys=True,
        )
        + "\n"
    )

    with pytest.raises(ExportError, match="^routing_transition_mismatch$"):
        export_sft(_options(results, tmp_path / "transition-drift", routing_epoch_index=index_path))

    provenance_results = _write_run(tmp_path / "provenance-run", [_linear_trace()])
    provenance_index = _write_routing_epoch_index(provenance_results, [1])
    provenance = provenance_results.parent / "provenance.txt"
    provenance.write_text(provenance.read_text().replace("qwen_router_transition_sha256=", "stale_marker="))

    with pytest.raises(ExportError, match="^routing_transition_provenance_mismatch$"):
        export_sft(
            _options(
                provenance_results,
                tmp_path / "provenance-drift",
                routing_epoch_index=provenance_index,
            )
        )


def test_routing_epoch_index_validates_rows_excluded_for_errors(tmp_path: Path) -> None:
    error_trace = _linear_trace("errored", task_name="errored-task")
    error_trace["errors"] = [{"type": "Synthetic"}]
    results = _write_run(tmp_path / "run", [_linear_trace(), error_trace])
    index_path = _write_routing_epoch_index(results, [1, 2])
    lines = [json.loads(line) for line in index_path.read_text().splitlines()]
    lines[2]["row_sha256"] = "0" * 64
    index_path.write_text("".join(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n" for line in lines))

    with pytest.raises(ExportError, match="^routing_epoch_index_row_hash_mismatch$"):
        export_sft(_options(results, tmp_path / "dataset", routing_epoch_index=index_path))


def test_routing_epoch_index_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    index_path = _write_routing_epoch_index(results, [1])
    lines = index_path.read_text().splitlines()
    lines[0] = lines[0][:-1] + ',"row_count":1}'
    index_path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ExportError, match="^routing_epoch_index_header_invalid$"):
        export_sft(_options(results, tmp_path / "duplicate-key", routing_epoch_index=index_path))


def test_external_routing_epoch_index_is_bound_and_retained(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    external_index = _write_routing_epoch_index(
        results,
        [1],
        output_path=sidecars / "routing-index.jsonl",
    )
    original = external_index.read_bytes()
    lines = [json.loads(line) for line in original.splitlines()]
    lines[0]["results_sha256"] = "0" * 64
    external_index.write_text("".join(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n" for line in lines))
    with pytest.raises(ExportError, match="^routing_epoch_index_results_hash_mismatch$"):
        export_sft(_options(results, tmp_path / "tampered", routing_epoch_index=external_index))

    external_index.write_bytes(original)
    source_before = {
        path.relative_to(results.parent): path.read_bytes() for path in results.parent.rglob("*") if path.is_file()
    }
    output = tmp_path / "dataset"
    summary = export_sft(_options(results, output, routing_epoch_index=external_index))

    retained = output / "qwen_router_epochs.jsonl"
    assert retained.read_bytes() == original
    assert summary["output_sha256"]["routing_epoch_index"] == _sha256(retained)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["artifacts"]["qwen_router_epochs.jsonl"] == {
        "bytes": len(original),
        "sha256": _sha256(retained),
    }
    assert not (results.parent / "qwen_router_epochs.jsonl").exists()
    source_after = {
        path.relative_to(results.parent): path.read_bytes() for path in results.parent.rglob("*") if path.is_file()
    }
    assert source_after == source_before


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
        "target_finish_reason",
        "target_has_reasoning",
        "task_id",
        "tools",
        "transcript_fidelity",
    ]


def test_task_split_is_grouped_by_opaque_task_hash(tmp_path: Path) -> None:
    traces = [
        _linear_trace("rollout-a", task_name="shared-task"),
        _linear_trace("rollout-b", task_name="shared-task"),
    ]
    traces[1]["task"] = copy.deepcopy(traces[0]["task"])
    traces[1]["task"]["idx"] = 917
    traces[1]["task"]["prompt"] = "different synthetic metadata"
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
        b"terminal-bench-vmvm\0dddddddddddddddddddddddddddddddddddddddd\0shared-task"
    ).hexdigest()
    split = _split_for_task(task_hash, salt=options.split_salt, validation_permyriad=5000)
    other = "validation" if split == "train" else "train"
    assert len(_read_jsonl(output / split / "train.jsonl")) == 4
    assert _read_jsonl(output / other / "train.jsonl") == []
    emitted = _read_jsonl(output / split / "train.jsonl")
    assert {row["task_id"] for row in emitted} == {task_hash}


def test_unknown_task_slug_is_rejected_without_disclosure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_slug = "private-unknown-slug-marker"
    results = _write_run(
        tmp_path / "run",
        [_linear_trace(task_name=f"terminal-bench/{private_slug}")],
        approved_slugs=["approved-synthetic-task"],
    )

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
    assert private_slug not in captured.out
    assert private_slug not in captured.err
    assert json.loads(captured.err) == {"code": "trace_task_slug_not_approved", "status": "error"}


def test_task_identity_accepts_production_name_only_shape(tmp_path: Path) -> None:
    trace = _linear_trace(task_name="synthetic-task")
    trace["task"].pop("slug")
    results = _write_run(
        tmp_path / "run",
        [trace],
        approved_slugs=["synthetic-task"],
    )

    summary = export_sft(_options(results, tmp_path / "dataset", selection="pass-only"))
    assert summary["selected_traces"] == 1


@pytest.mark.parametrize("index", [None, 0])
def test_required_task_index_binding_rejects_missing_or_wrong_index(
    tmp_path: Path,
    index: int | None,
) -> None:
    trace = _linear_trace(task_name="synthetic-task")
    trace["task"] = {"name": "synthetic-suite/synthetic-task"}
    if index is not None:
        trace["task"]["idx"] = index
    results = _write_run(
        tmp_path / "run",
        [trace],
        approved_slugs=["synthetic-task", "other-task"],
    )

    with pytest.raises(ExportError, match="^trace_task_identity_mismatch$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                require_task_index_binding=True,
            )
        )


def test_required_task_index_binding_accepts_repair_evaluator_order(tmp_path: Path) -> None:
    trace = _linear_trace(task_name="synthetic-task")
    trace["task"] = {"idx": 1, "name": "synthetic-suite/synthetic-task"}
    results = _write_run(
        tmp_path / "run",
        [trace],
        approved_slugs=["synthetic-task", "other-task"],
    )

    summary = export_sft(
        _options(
            results,
            tmp_path / "dataset",
            selection="pass-only",
            require_task_index_binding=True,
        )
    )

    assert summary["selected_traces"] == 1


def test_required_task_index_binding_rejects_slug_only_identity(tmp_path: Path) -> None:
    trace = _linear_trace(task_name="synthetic-task")
    trace["task"] = {"idx": 1, "slug": "synthetic-task"}
    results = _write_run(
        tmp_path / "run",
        [trace],
        approved_slugs=["synthetic-task", "other-task"],
    )

    with pytest.raises(ExportError, match="^trace_task_name_invalid$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                require_task_index_binding=True,
            )
        )


def test_attested_exclusion_rejects_slug_only_identity(tmp_path: Path) -> None:
    approved = ["opaque-missing", "opaque-valid"]
    valid = _name_only_trace("trace-valid", "opaque-valid", 1)
    valid["task"] = {"idx": 1, "slug": "opaque-valid"}
    results = _write_run(tmp_path / "run", [valid], approved_slugs=approved)
    routing = _write_routing_epoch_index(results, [2])
    selection, digest = _write_exclusion_selection(
        results,
        missing_or_errored={"opaque-missing"},
        strict_invalid_pass=set(),
    )

    with pytest.raises(ExportError, match="^trace_task_name_invalid$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                expected_count=2,
                routing_epoch_index=routing,
                exclusion_selection_manifest=selection,
                exclusion_selection_manifest_sha256=digest,
            )
        )


def test_export_ignores_attested_malformed_final_fragment_and_hashes_full_source(
    tmp_path: Path,
) -> None:
    approved = ["opaque-missing", "opaque-valid"]
    valid = _name_only_trace("trace-valid", "opaque-valid", 1)
    results = _write_run(tmp_path / "run", [valid], approved_slugs=approved)
    routing = _write_routing_epoch_index(results, [2])
    results.write_bytes(results.read_bytes() + b'{"task":{"idx":0')
    index_rows = [json.loads(line) for line in routing.read_text().splitlines()]
    index_rows[0]["results_sha256"] = _sha256(results)
    routing.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in index_rows))
    selection, digest = _write_exclusion_selection(
        results,
        missing_or_errored={"opaque-missing"},
        strict_invalid_pass=set(),
    )
    source_before = results.read_bytes()

    summary = export_sft(
        _options(
            results,
            tmp_path / "dataset",
            selection="pass-only",
            expected_count=2,
            routing_epoch_index=routing,
            exclusion_selection_manifest=selection,
            exclusion_selection_manifest_sha256=digest,
        )
    )

    assert summary["input_traces"] == 1
    assert summary["exclusion"]["missing_tasks"] == 1
    manifest = json.loads((tmp_path / "dataset" / "manifest.json").read_text())
    assert manifest["source_artifacts"]["results.jsonl"] == {
        "bytes": len(source_before),
        "sha256": hashlib.sha256(source_before).hexdigest(),
    }
    assert results.read_bytes() == source_before


def test_export_retains_valid_unterminated_final_row(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    results.write_bytes(results.read_bytes().removesuffix(b"\n"))
    routing = _write_routing_epoch_index(results, [2])

    summary = export_sft(
        _options(
            results,
            tmp_path / "dataset",
            selection="pass-only",
            expected_count=1,
            routing_epoch_index=routing,
        )
    )

    assert summary["input_traces"] == 1
    assert summary["selected_traces"] == 1


def test_export_rejects_unattested_malformed_final_fragment(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    results.write_bytes(results.read_bytes() + b'{"task":{"idx":0')

    with pytest.raises(ExportError, match="^results_jsonl_unterminated$"):
        export_sft(_options(results, tmp_path / "dataset", selection="pass-only"))


@pytest.mark.parametrize(
    "tail",
    [
        b'{"task":\n',
        b'{"task":\n{"task":{"idx":0}}\n',
    ],
)
def test_export_rejects_complete_or_interior_malformed_content_even_with_exclusion(
    tmp_path: Path,
    tail: bytes,
) -> None:
    approved = ["opaque-missing", "opaque-valid"]
    valid = _name_only_trace("trace-valid", "opaque-valid", 1)
    results = _write_run(tmp_path / "run", [valid], approved_slugs=approved)
    results.write_bytes(results.read_bytes() + tail)
    routing = _write_routing_epoch_index(results, [2] * len(results.read_bytes().splitlines(keepends=True)))
    selection, digest = _write_exclusion_selection(
        results,
        missing_or_errored={"opaque-missing"},
        strict_invalid_pass=set(),
    )

    with pytest.raises(ExportError, match="^results_jsonl_invalid$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                expected_count=2,
                routing_epoch_index=routing,
                exclusion_selection_manifest=selection,
                exclusion_selection_manifest_sha256=digest,
            )
        )


def test_task_identity_rejects_mismatched_name_and_slug(tmp_path: Path) -> None:
    trace = _linear_trace(task_name="synthetic-task")
    trace["task"]["name"] = "suite/different-task"
    results = _write_run(tmp_path / "run", [trace], approved_slugs=["synthetic-task"])

    with pytest.raises(ExportError, match="^trace_task_identity_mismatch$"):
        export_sft(_options(results, tmp_path / "dataset", selection="pass-only"))


@pytest.mark.parametrize("invalid_name", [None, "", "synthetic-task/", "\x00synthetic-task", 7])
def test_task_identity_rejects_invalid_present_name_even_with_valid_slug(
    tmp_path: Path,
    invalid_name: object,
) -> None:
    trace = _linear_trace(task_name="synthetic-task")
    trace["task"]["name"] = invalid_name
    results = _write_run(tmp_path / "run", [trace], approved_slugs=["synthetic-task"])

    with pytest.raises(ExportError, match="^trace_task_name_invalid$"):
        export_sft(_options(results, tmp_path / "dataset", selection="pass-only"))


def test_attested_exclusion_cross_binds_name_to_evaluator_index(tmp_path: Path) -> None:
    approved = ["opaque-a", "opaque-b"]
    error = _name_only_trace("trace-error", "opaque-a", 1)
    error["errors"] = [{"type": "SyntheticError"}]
    valid = _name_only_trace("trace-valid", "opaque-b", 1)
    results = _write_run(tmp_path / "run", [error, valid], approved_slugs=approved)
    routing = _write_routing_epoch_index(results, [2, 2], current_epoch=2)
    selection, digest = _write_exclusion_selection(
        results,
        missing_or_errored={"opaque-a"},
        strict_invalid_pass=set(),
    )

    with pytest.raises(ExportError, match="^trace_task_identity_mismatch$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                expected_count=2,
                routing_epoch_index=routing,
                exclusion_selection_manifest=selection,
                exclusion_selection_manifest_sha256=digest,
            )
        )


def _name_only_trace(trace_id: str, slug: str, index: int, *, reward: float = 1.0) -> dict:
    trace = _linear_trace(trace_id=trace_id, reward=reward, task_name=slug)
    trace["task"] = {"idx": index, "name": f"synthetic-suite/{slug}"}
    return trace


def test_attested_exclusion_unions_errors_missing_and_multiple_strict_invalid_passes(
    tmp_path: Path,
) -> None:
    error_slug = "opaque-a7c3"
    fail_slug = "opaque-b8d4"
    invalid_cap_slug = "opaque-c9e5"
    invalid_io_slug = "opaque-d0f6"
    invalid_reasoning_slug = "opaque-e1a7"
    missing_slug = "opaque-f2b8"
    valid_slug = "opaque-03c9"
    approved = [
        error_slug,
        fail_slug,
        invalid_cap_slug,
        invalid_io_slug,
        invalid_reasoning_slug,
        missing_slug,
        valid_slug,
    ]
    index = {slug: position for position, slug in enumerate(sorted(approved))}
    error = _name_only_trace("trace-error", error_slug, index[error_slug])
    error["errors"] = [{"type": "SyntheticError"}]
    failed = _name_only_trace("trace-fail", fail_slug, index[fail_slug], reward=0.0)
    invalid_cap = _name_only_trace("trace-cap", invalid_cap_slug, index[invalid_cap_slug])
    cap_node = invalid_cap["nodes"][2]
    cap_node["usage"]["prompt_tokens"] = 262_144
    cap_response = cap_node["model_io"]["response"]
    cap_response["body"]["usage"]["prompt_tokens"] = 262_144
    cap_response["body"]["usage"]["total_tokens"] = 262_149
    cap_response["sha256"] = _json_sha256(cap_response["body"])
    invalid_io = _name_only_trace("trace-io", invalid_io_slug, index[invalid_io_slug])
    invalid_io["nodes"][2]["model_io"]["response"]["sha256"] = "0" * 64
    invalid_reasoning = _name_only_trace(
        "trace-reasoning",
        invalid_reasoning_slug,
        index[invalid_reasoning_slug],
    )
    invalid_reasoning["nodes"][2]["message"].pop("reasoning_content")
    valid = _name_only_trace("trace-valid", valid_slug, index[valid_slug])
    traces = [error, failed, invalid_cap, invalid_io, invalid_reasoning, valid]
    results = _write_run(tmp_path / "run", traces, approved_slugs=approved)
    routing = _write_routing_epoch_index(results, [2] * len(traces), current_epoch=2)
    selection, selection_sha256 = _write_exclusion_selection(
        results,
        missing_or_errored={error_slug, missing_slug},
        strict_invalid_pass={invalid_cap_slug, invalid_io_slug, invalid_reasoning_slug},
    )

    summary = export_sft(
        _options(
            results,
            tmp_path / "dataset",
            selection="pass-only",
            expected_count=len(approved),
            routing_epoch_index=routing,
            exclusion_selection_manifest=selection,
            exclusion_selection_manifest_sha256=selection_sha256,
        )
    )

    assert summary["approved_tasks"] == len(approved)
    assert summary["input_traces"] == len(traces)
    assert summary["selected_traces"] == 1
    assert summary["exclusion"] == {
        "excluded_present_traces": 4,
        "missing_tasks": 1,
        "missing_or_errored_count": 2,
        "selection_manifest_sha256": selection_sha256,
        "strict_invalid_pass_count": 3,
        "union_count": 5,
    }
    serialized = json.dumps(summary, sort_keys=True)
    assert all(slug not in serialized for slug in approved)


def test_attested_exclusion_rejects_selected_scored_failure(tmp_path: Path) -> None:
    approved = ["fail", "valid"]
    traces = [
        _name_only_trace("trace-fail", "fail", 0, reward=0.0),
        _name_only_trace("trace-valid", "valid", 1),
    ]
    results = _write_run(tmp_path / "run", traces, approved_slugs=approved)
    routing = _write_routing_epoch_index(results, [2, 2], current_epoch=2)
    selection, digest = _write_exclusion_selection(
        results,
        missing_or_errored=set(),
        strict_invalid_pass={"fail"},
    )

    with pytest.raises(ExportError, match="^exclusion_selection_category_mismatch$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                expected_count=2,
                routing_epoch_index=routing,
                exclusion_selection_manifest=selection,
                exclusion_selection_manifest_sha256=digest,
            )
        )


def test_attested_exclusion_rejects_selected_trainable_pass(tmp_path: Path) -> None:
    approved = ["selected", "valid"]
    traces = [
        _name_only_trace("trace-selected", "selected", 0),
        _name_only_trace("trace-valid", "valid", 1),
    ]
    results = _write_run(tmp_path / "run", traces, approved_slugs=approved)
    routing = _write_routing_epoch_index(results, [2, 2], current_epoch=2)
    selection, digest = _write_exclusion_selection(
        results,
        missing_or_errored=set(),
        strict_invalid_pass={"selected"},
    )

    with pytest.raises(ExportError, match="^exclusion_selection_category_mismatch$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                expected_count=2,
                routing_epoch_index=routing,
                exclusion_selection_manifest=selection,
                exclusion_selection_manifest_sha256=digest,
            )
        )


def test_attested_exclusion_does_not_hide_unselected_invalid_pass(tmp_path: Path) -> None:
    approved = ["error", "invalid", "valid"]
    error = _name_only_trace("trace-error", "error", 0)
    error["errors"] = [{"type": "SyntheticError"}]
    invalid = _name_only_trace("trace-invalid", "invalid", 1)
    invalid["nodes"][2].pop("model_io")
    valid = _name_only_trace("trace-valid", "valid", 2)
    results = _write_run(tmp_path / "run", [error, invalid, valid], approved_slugs=approved)
    routing = _write_routing_epoch_index(results, [2, 2, 2], current_epoch=2)
    selection, digest = _write_exclusion_selection(
        results,
        missing_or_errored={"error"},
        strict_invalid_pass=set(),
    )

    with pytest.raises(ExportError, match="^trace_validation_failed$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                expected_count=3,
                routing_epoch_index=routing,
                exclusion_selection_manifest=selection,
                exclusion_selection_manifest_sha256=digest,
            )
        )


def test_attested_exclusion_rejects_tampered_category_file(tmp_path: Path) -> None:
    approved = ["error", "valid"]
    error = _name_only_trace("trace-error", "error", 0)
    error["errors"] = [{"type": "SyntheticError"}]
    valid = _name_only_trace("trace-valid", "valid", 1)
    results = _write_run(tmp_path / "run", [error, valid], approved_slugs=approved)
    routing = _write_routing_epoch_index(results, [2, 2], current_epoch=2)
    selection, digest = _write_exclusion_selection(
        results,
        missing_or_errored={"error"},
        strict_invalid_pass=set(),
    )
    (selection.parent / "repair_missing_or_errored_tasks.txt").write_text("error\nvalid\n")
    (selection.parent / "repair_missing_or_errored_tasks.txt").chmod(0o600)

    with pytest.raises(ExportError, match="^exclusion_selection_contract_invalid$"):
        export_sft(
            _options(
                results,
                tmp_path / "dataset",
                selection="pass-only",
                expected_count=2,
                routing_epoch_index=routing,
                exclusion_selection_manifest=selection,
                exclusion_selection_manifest_sha256=digest,
            )
        )


def test_approved_task_list_rejects_duplicate_slugs(tmp_path: Path) -> None:
    results = _write_run(
        tmp_path / "run",
        [_linear_trace()],
        approved_slugs=["synthetic-task", "synthetic-task"],
    )

    with pytest.raises(ExportError, match="^approved_task_list_duplicates$"):
        export_sft(_options(results, tmp_path / "dataset", selection="pass-only"))


def test_approved_task_list_must_match_configured_task_count(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    config = results.parent / "config.toml"
    config.write_text(config.read_text().replace("num_tasks = 1", "num_tasks = 2"))

    with pytest.raises(ExportError, match="^approved_task_list_count_mismatch$"):
        export_sft(_options(results, tmp_path / "dataset", selection="pass-only"))


def test_active_writer_lock_blocks_export(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    lock_path = results.parent / ".writer.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ExportError, match="^source_run_is_active$"):
            export_sft(_options(results, tmp_path / "dataset"))


def test_active_direct_router_lock_blocks_epoch_index_export(tmp_path: Path) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    index_path = _write_routing_epoch_index(results, [1])
    with (results.parent / ".direct_router.lock").open("r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ExportError, match="^source_run_is_active$"):
            export_sft(_options(results, tmp_path / "dataset", routing_epoch_index=index_path))


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


def test_sandoq_export_propagates_identity_cleanup_and_preserves_reasoning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    with (results.parent / "config.toml").open("a") as config:
        config.write('[harness.runtime]\ntype = "sandoq"\n')
    artifact = exporter.sft_run_identity.IdentityArtifact(bytes=100, sha256="a" * 64)
    binding = exporter.sft_run_identity.SftRunIdentity(
        artifact=artifact,
        eval_run_identity_sha256="b" * 64,
        provider="sandoq",
        compatibility_sha256="c" * 64,
        provenance={
            "artifact": artifact.as_dict(),
            "compatibility": {},
            "compatibility_sha256": "c" * 64,
            "concurrency": {},
            "environment": {},
            "eval_run_identity_sha256": "b" * 64,
            "role": "qwen-direct",
            "runtime": {},
            "sandbox_provider": "sandoq",
            "schema_version": 1,
            "source": {},
        },
    )
    monkeypatch.setattr(
        exporter.sft_run_identity,
        "load_sft_run_identity",
        lambda *_args, **_kwargs: binding,
    )
    output = tmp_path / "dataset"

    summary = export_sft(_options(results, output, expected_count=1))

    manifest = json.loads((output / "manifest.json").read_text())
    rows = _read_jsonl(output / "train" / "train.jsonl")
    assert summary["sandbox_provider"] == "sandoq"
    assert "routing_epochs" not in manifest
    assert manifest["eval_run_identity"]["cleanup"] == {
        "cleanup_implied_successful_traces": 1,
        "excluded_error_traces": 0,
        "must_succeed": True,
        "selected_error_free_traces": 1,
        "semantics": "runtime teardown failure is captured as trace.error",
    }
    assert rows[-1]["messages"][-1]["reasoning_content"] == "second-reasoning"
    assert manifest["source_artifacts"]["eval_run_identity.json"] == artifact.as_dict()


def test_sandoq_export_rejects_vmvm_routing_epoch_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _write_run(tmp_path / "run", [_linear_trace()])
    with (results.parent / "config.toml").open("a") as config:
        config.write('[harness.runtime]\ntype = "sandoq"\n')
    index = _write_routing_epoch_index(results, [3], current_epoch=3)
    binding = exporter.sft_run_identity.SftRunIdentity(
        artifact=exporter.sft_run_identity.IdentityArtifact(bytes=1, sha256="a" * 64),
        eval_run_identity_sha256="b" * 64,
        provider="sandoq",
        compatibility_sha256="c" * 64,
        provenance={},
    )
    monkeypatch.setattr(
        exporter.sft_run_identity,
        "load_sft_run_identity",
        lambda *_args, **_kwargs: binding,
    )

    with pytest.raises(ExportError, match="^sandoq_routing_epoch_forbidden$"):
        export_sft(_options(results, tmp_path / "dataset", routing_epoch_index=index))


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


def test_exact_provider_json_cli_failure_is_redacted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    private_marker = "private-normalized-response-marker"
    trace = _linear_trace(task_name=private_marker)
    _use_normalized_stream_responses(trace)
    results = _write_run(tmp_path / "run", [trace])

    status = main(
        [
            str(results),
            "--output-dir",
            str(tmp_path / "dataset"),
            "--selection",
            "pass-only",
            "--require-exact-provider-json",
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert private_marker not in captured.out
    assert private_marker not in captured.err
    assert json.loads(captured.err) == {
        "code": "normalized_stream_response_disallowed",
        "status": "error",
    }
