from __future__ import annotations

import json
from types import SimpleNamespace

import certify_kimi_tb4_sandoq_clamped_union as certifier
import pytest


def _row(task_id: str, score: int) -> dict[str, object]:
    return {
        "id": f"trace-{task_id}",
        "task": {"name": f"terminal-bench/{task_id}"},
        "rewards": {"solved": score},
    }


def test_merge_rows_preserves_denominator_and_counts_passes() -> None:
    native = tuple(f"native-{index}" for index in range(certifier.NATIVE_TASKS))
    clamped = tuple(f"clamped-{index}" for index in range(certifier.CLAMPED_TASKS))
    compose = tuple(f"compose-{index}" for index in range(certifier.COMPOSE_UNSUPPORTED))
    gpu = tuple(f"gpu-{index}" for index in range(certifier.GPU_UNSUPPORTED))
    ordered = native + clamped + compose + gpu
    entries = tuple(SimpleNamespace(task_id=task_id) for task_id in ordered)
    native_rows = {task_id: _row(task_id, int(index < 4)) for index, task_id in enumerate(native)}
    clamped_rows = {task_id: _row(task_id, int(index < 3)) for index, task_id in enumerate(clamped)}
    body, passes = certifier._merge_rows(
        entries,
        native_rows,
        clamped_rows,
        native,
        clamped,
        compose,
        gpu,
        "a" * 64,
    )
    rows = [json.loads(line) for line in body.splitlines()]
    assert len(rows) == certifier.TOTAL_TASKS
    assert passes == certifier.MIN_PASSES
    assert sum(row["stop_condition"] == "error" for row in rows if "stop_condition" in row) == 14


def test_merge_rows_rejects_overlap() -> None:
    entries = (SimpleNamespace(task_id="same"),)
    with pytest.raises(certifier.ClampedUnionError, match="union_coverage_invalid"):
        certifier._merge_rows(
            entries,
            {"same": _row("same", 0)},
            {"same": _row("same", 0)},
            ("same",),
            ("same",),
            (),
            (),
            "a" * 64,
        )


@pytest.mark.parametrize("concurrency", [23, 24])
def test_clamped_config_requires_exact_caps(concurrency: int) -> None:
    config = {
        "num_tasks": 27,
        "max_concurrent": concurrency,
        "multiplex": concurrency,
        "taskset": {
            "enable_compose": False,
            "resource_multiplier": 1.0,
            "resource_cpu_cap": 2,
            "resource_memory_mb_cap": 4096,
            "resource_storage_mb_cap": 10240,
        },
    }
    certifier._validate_clamped_config(config, concurrency)
    config["taskset"]["resource_memory_mb_cap"] = 8192
    with pytest.raises(certifier.ClampedUnionError, match="clamped_resource_contract_invalid"):
        certifier._validate_clamped_config(config, concurrency)
