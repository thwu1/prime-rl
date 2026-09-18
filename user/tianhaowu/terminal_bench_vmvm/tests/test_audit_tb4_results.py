from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from audit_tb4_results import (
    EXPECTED_UNSUPPORTED_TASKS,
    TB4AuditError,
    _expected_slugs,
    audit_results,
)


def _digest(body: dict) -> str:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _supported_trace(slug: str, *, solved: float = 0.0) -> dict:
    request = {
        "model": "Kimi-K3",
        "messages": [],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a command",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }
    response = {"choices": [{"message": {"reasoning_content": "reason", "content": "answer"}}]}
    return {
        "id": f"trace-{slug}",
        "task": {"slug": slug, "name": f"terminal-bench/{slug}", "resources": {}},
        "nodes": [
            {
                "parent": None,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "reason",
                },
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                "model_io": {
                    "provider_route": "/chat/completions",
                    "request": {"kind": "full", "sha256": _digest(request), "body": request},
                    "response": {
                        "kind": "exact_provider_json",
                        "sha256": _digest(response),
                        "body": response,
                    },
                },
            }
        ],
        "rewards": {"solved": solved},
        "metrics": {},
        "is_completed": True,
        "stop_condition": "agent_completed",
        "errors": [],
    }


def _unsupported_trace(slug: str) -> dict:
    message = (
        f"taskset setup: UnsupportedTaskError: terminal-bench/{slug}: "
        "requests GPU resources, but the current VMVM tenant is CPU-only"
    )
    return {
        "id": f"trace-{slug}",
        "task": {
            "slug": slug,
            "name": f"terminal-bench/{slug}",
            "resources": {"gpu": "1"},
        },
        "nodes": [],
        "rewards": {},
        "metrics": {},
        "is_completed": True,
        "stop_condition": "error",
        "errors": [{"type": "TasksetError", "message": message, "traceback": message}],
    }


def _fixture(tmp_path: Path, *, passes: int = 8) -> tuple[Path, Path, list[dict]]:
    dataset = tmp_path / "tasks"
    dataset.mkdir()
    supported = [f"task-{index:02d}" for index in range(63)]
    slugs = [*supported, *sorted(EXPECTED_UNSUPPORTED_TASKS)]
    for slug in slugs:
        task_dir = dataset / slug
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("")
        (task_dir / "instruction.md").write_text("")
    rows = [_supported_trace(slug, solved=float(index < passes)) for index, slug in enumerate(supported)]
    rows.extend(_unsupported_trace(slug) for slug in sorted(EXPECTED_UNSUPPORTED_TASKS))
    results = tmp_path / "results.jsonl"
    results.write_text("".join(f"{json.dumps(row)}\n" for row in rows))
    return dataset, results, rows


def test_accepts_exact_supported_and_gpu_unsupported_partition(tmp_path: Path) -> None:
    dataset, results, _ = _fixture(tmp_path, passes=8)

    summary, failed = audit_results(
        results,
        dataset_dir=dataset,
        min_supported_pass_rate=0.04,
        max_supported_pass_rate=0.22,
    )

    assert failed is False
    assert summary["ok"] is True
    assert summary["observed_traces"] == 66
    assert summary["supported_tasks"] == 63
    assert summary["supported_passes"] == 8
    assert summary["supported_pass_rate"] == pytest.approx(8 / 63)
    assert summary["all_task_pass_rate"] == pytest.approx(8 / 66)
    assert summary["observed_unsupported_tasks"] == sorted(EXPECTED_UNSUPPORTED_TASKS)
    assert summary["trace_failures"] == 0
    assert summary["global_problems"] == []
    assert summary["failure_examples"] == []


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        ("stop_condition", "agent_completed", "unsupported_trace_stop_condition_invalid"),
        ("nodes", [{}], "unsupported_trace_nodes_not_empty"),
        ("rewards", {"solved": 0.0}, "unsupported_trace_rewards_not_empty"),
    ],
)
def test_rejects_malformed_expected_unsupported_rows(
    tmp_path: Path,
    field: str,
    value: object,
    problem: str,
) -> None:
    dataset, results, rows = _fixture(tmp_path)
    row = next(item for item in rows if item["task"]["slug"] == "fp8-rmsnorm-gemm")
    row[field] = value
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    failure = next(item for item in summary["failure_examples"] if item["task"] == "fp8-rmsnorm-gemm")
    assert problem in failure["problems"]


def test_rejects_wrong_unsupported_error_message(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    row = next(item for item in rows if item["task"]["slug"] == "jax-speedrun-gpu")
    row["errors"][0]["message"] = "provider timeout"
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    failure = next(item for item in summary["failure_examples"] if item["task"] == "jax-speedrun-gpu")
    assert "unsupported_trace_error_message_invalid" in failure["problems"]


def test_rejects_missing_duplicate_and_unexpected_tasks(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[-1] = _supported_trace("unexpected")
    rows[1]["task"]["slug"] = rows[0]["task"]["slug"]
    rows[1]["task"]["name"] = rows[0]["task"]["name"]
    rows[1]["id"] = rows[0]["id"]
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    assert "duplicate_trace_ids" in summary["global_problems"]
    assert any(problem.startswith("missing_tasks=") for problem in summary["global_problems"])
    assert any(problem.startswith("unexpected_tasks=") for problem in summary["global_problems"])
    assert any(problem.startswith("wrong_rollout_multiplicity=") for problem in summary["global_problems"])


def test_rejects_supported_errors_and_semantic_corruption(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[0]["errors"] = [{"type": "ProviderError", "message": "500"}]
    rows[1]["nodes"][0]["message"]["reasoning_content"] = "@ " * 64
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    by_task = {item["task"]: item["problems"] for item in summary["failure_examples"]}
    assert "trace_has_errors" in by_task["task-00"]
    assert "node_0_repeated_at_in_reasoning" in by_task["task-01"]


def test_requires_model_io_on_every_supported_trace(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[0]["nodes"][0].pop("model_io")
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    failure = next(item for item in summary["failure_examples"] if item["task"] == "task-00")
    assert "node_0_model_io_missing" in failure["problems"]
    assert summary["supported_trace_failures"] == 1


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        ("is_completed", False, "supported_trace_not_completed"),
        ("stop_condition", None, "supported_trace_stop_condition_invalid"),
        ("stop_condition", "", "supported_trace_stop_condition_invalid"),
        ("stop_condition", "error", "supported_trace_stop_condition_invalid"),
    ],
)
def test_requires_supported_rows_to_be_completed_with_a_nonerror_stop(
    tmp_path: Path,
    field: str,
    value: object,
    problem: str,
) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[0][field] = value
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    failure = next(item for item in summary["failure_examples"] if item["task"] == "task-00")
    assert problem in failure["problems"]


def test_score_bounds_are_explicit_and_fail_closed(tmp_path: Path) -> None:
    dataset, results, _ = _fixture(tmp_path, passes=2)

    summary, failed = audit_results(
        results,
        dataset_dir=dataset,
        min_supported_pass_rate=0.04,
        max_supported_pass_rate=0.22,
    )

    assert failed is True
    assert summary["supported_passes"] == 2
    assert summary["supported_pass_rate"] == pytest.approx(2 / 63)
    assert summary["global_problems"] == [f"supported_pass_rate={2 / 63:.12g} below_min=0.04"]

    _, failed = audit_results(
        results,
        dataset_dir=dataset,
        max_supported_pass_rate=0.03,
    )
    assert failed is True


def test_task_file_must_name_exactly_the_dataset_tasks(tmp_path: Path) -> None:
    dataset, _, _ = _fixture(tmp_path)
    task_file = tmp_path / "tasks.txt"
    task_file.write_text("\n".join(sorted(path.name for path in dataset.iterdir())) + "\n")

    assert _expected_slugs(dataset, task_file) == {path.name for path in dataset.iterdir()}

    task_file.write_text("task-00\ntask-00\n")
    with pytest.raises(TB4AuditError, match="duplicate task slugs"):
        _expected_slugs(dataset, task_file)


def test_score_must_be_a_single_binary_solved_reward(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[0]["rewards"] = {"solved": 0.5}
    rows[1]["rewards"] = {"solved": 0.0, "extra": 1.0}
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    by_task = {item["task"]: item["problems"] for item in summary["failure_examples"]}
    assert "rewards_solved_not_binary" in by_task["task-00"]
    assert "rewards_solved_missing_or_extra" in by_task["task-01"]
    assert "scored_supported_tasks=61 expected=63" in summary["global_problems"]
