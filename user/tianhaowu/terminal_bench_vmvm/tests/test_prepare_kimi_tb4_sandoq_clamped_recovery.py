from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from types import SimpleNamespace

import prepare_kimi_tb4_sandoq_clamped_recovery as recovery
import pytest


def _private(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    os.chmod(path, 0o600)
    return path


def _row(index: int, *, model_bearing: bool = False) -> dict[str, object]:
    return {
        "task": {"idx": index},
        "errors": [{"type": "SandboxError"}],
        "nodes": ([{"message": {"role": "assistant", "content": "x"}}] if model_bearing else []),
        "rewards": {},
        "metrics": {},
        "info": {},
    }


def test_zero_model_abort_accepts_only_empty_traces(tmp_path: Path) -> None:
    body = b"".join(
        json.dumps(_row(index), separators=(",", ":")).encode() + b"\n"
        for index in (0, 1)
    )
    path = _private(tmp_path / "results.jsonl", body)
    observed, count = recovery._validate_zero_model_abort(path, 3)
    assert observed == body
    assert count == 2


def test_zero_model_abort_rejects_model_bearing_error(tmp_path: Path) -> None:
    body = json.dumps(_row(0, model_bearing=True), separators=(",", ":")).encode() + b"\n"
    path = _private(tmp_path / "results.jsonl", body)
    with pytest.raises(recovery.ClampedRecoveryError, match="aborted_run_not_zero_model_only"):
        recovery._validate_zero_model_abort(path, 1)


def test_members_exclude_compose_without_disclosing_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vmvm = tuple(f"remainder-{index}" for index in range(38))
    compose = vmvm[:11]
    baseline = SimpleNamespace(compose_required=compose)
    monkeypatch.setattr(recovery.split, "derive_partition", lambda _entries: baseline)
    selector_body = recovery.union._selector_payload(vmvm)
    selector = _private(tmp_path / "vmvm.tasks.txt", selector_body)
    plan = {
        "lanes": {
            recovery.union.VMVM_ROLE: {
                "selector": {
                    "path": str(selector),
                    "bytes": len(selector_body),
                    "sha256": hashlib.sha256(selector_body).hexdigest(),
                }
            }
        }
    }
    selected, unsupported = recovery._members(plan, ())
    assert len(selected) == 27
    assert len(unsupported) == 11
    assert set(selected).isdisjoint(unsupported)


@pytest.mark.parametrize("concurrency", [23, 24])
def test_expected_config_applies_qualified_resource_caps(tmp_path: Path, concurrency: int) -> None:
    source = {
        "num_tasks": 25,
        "max_concurrent": 24,
        "multiplex": 24,
        "client": {"max_connections": 24, "max_keepalive_connections": 24},
        "taskset": {
            "task_file": "/old",
            "task_file_sha256": "0" * 64,
            "enable_compose": False,
            "resource_multiplier": 1.0,
        },
    }
    source_body = recovery.union._render_toml(source)
    source_path = _private(tmp_path / "source.toml", source_body)
    plan = {
        "lanes": {
            recovery.union.SANDOQ_ROLE: {
                "config": {
                    "path": str(source_path),
                    "bytes": len(source_body),
                    "sha256": hashlib.sha256(source_body).hexdigest(),
                }
            }
        }
    }
    selector = tmp_path / recovery.SELECTOR
    rendered = recovery._expected_config(plan, selector, b"one\n", concurrency)
    config = tomllib.loads(rendered.decode())
    assert config["num_tasks"] == 27
    assert config["max_concurrent"] == concurrency
    assert config["taskset"]["resource_cpu_cap"] == 2
    assert config["taskset"]["resource_memory_mb_cap"] == 4096
    assert config["taskset"]["resource_storage_mb_cap"] == 10240
    assert config["taskset"]["task_file"] == str(selector)
