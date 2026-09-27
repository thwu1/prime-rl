from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

import eval_run_identity as identity
import kimi_stock_small_shards as shards


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _private_file(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    path.chmod(0o600)
    return path


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _trace(trace_id: str, task: str, *, response_kind: str = "exact_provider_json") -> dict:
    request = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        "messages": [{"role": "user", "content": "synthetic"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a command",
                    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                },
            }
        ],
    }
    response = {
        "id": f"response-{trace_id}",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "done", "reasoning_content": "reasoning"},
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    return {
        "id": trace_id,
        "task": {"slug": task},
        "errors": [],
        "rewards": {"solved": 0},
        "is_completed": True,
        "stop_condition": "task_completed",
        "nodes": [
            {
                "parent": None,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "user", "content": "synthetic"},
            },
            {
                "parent": 0,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": response["choices"][0]["message"],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
                "finish_reason": "stop",
                "model_io": {
                    "provider_route": "/chat/completions",
                    "request": {"kind": "full", "sha256": _digest(request), "body": request},
                    "response": {"kind": response_kind, "sha256": _digest(response), "body": response},
                },
            },
        ],
    }


def test_shards_are_deterministic_balanced_and_exhaustive() -> None:
    members = tuple(f"opaque-{index:04d}" for index in range(shards.TOTAL_TASKS))
    first = shards._split_members(members)
    second = shards._split_members(members)

    assert first == second
    assert len(first) == 40
    assert [len(shard) for shard in first] == [*([63] * 19), *([62] * 21)]
    assert set().union(*map(set, first)) == set(members)
    assert sum(map(len, first)) == shards.TOTAL_TASKS


def test_base_config_is_exact_stock_small_c64_contract(tmp_path: Path) -> None:
    base, body, _path = shards._load_base()
    assert hashlib.sha256(body).hexdigest() == shards.BASE_CONFIG_SHA256
    rendered = shards._render_config(
        base,
        count=63,
        selector=tmp_path / "private.tasks.txt",
        selector_sha256="a" * 64,
        dataset=tmp_path / "dataset",
        image_manifest=tmp_path / "images.json",
    )
    config = tomllib.loads(rendered.decode())

    assert config["num_tasks"] == 63
    assert config["taskset"]["dataset_revision"] == "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
    assert config["max_concurrent"] == 64
    assert config["max_input_tokens"] == 262_144
    assert config["max_total_tokens"] == 262_144
    assert config["sampling"]["max_tokens"] == 32_768
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["client"]["timeout"] == 144_000
    assert config["harness"]["runtime"]["session_timeout"] == 144_000
    assert config["harness"]["runtime"]["provisioning_retries"] == 8
    assert config["timeout"]["rollout"] == 129_600
    assert config["harness"]["env"] == {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "1"}
    assert config["taskset"]["verifier_runtime_retries"] == 2
    assert config["taskset"]["retry_shared_verifier_scoring"] is True
    assert config["taskset"]["resource_cpu_cap"] == 1
    assert config["taskset"]["resource_memory_mb_cap"] == 2_048
    identity._validate_direct_kimi_production_config(config, identity.KIMI_PRODUCTION_ROLE)

    contracts = shards._contracts()
    assert contracts["model_attempts"] == 1
    assert contracts["model_retries"] == 0
    assert contracts["zero_model_resume_attempts"] == 0
    assert contracts["resume"]["model_bearing_retry"] is False
    assert contracts["resume"]["zero_model_rows"] == "uncertifiable-manual-recovery"
    assert contracts["resume"]["rollover_policy"] == "new-plan-required"
    assert contracts["prelaunch_gates"]["real_task_image_c64_soak"] == {
        "kind": "kimi-k3-stock-small-task-image-c64-soak",
        "task_count": 64,
        "concurrency": 64,
        "minimum_endpoint_remaining_seconds": 518_400,
        "model_calls": 0,
        "harness_invocations": 0,
    }
    assert contracts["verifier_recovery"] == {
        "mode": "same-post-agent-runtime-scoring-only",
        "retries": 2,
        "maximum_attempts": 3,
        "model_calls": 0,
        "infrastructure_errors_remain_errors": True,
    }


def test_small_production_config_rejects_a_second_model_attempt() -> None:
    config = shards._load_base()[0]
    config["num_tasks"] = 64
    config["harness"]["env"]["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = "2"
    with pytest.raises(identity.EvalIdentityError, match="direct_kimi_production_config_invalid"):
        identity._validate_direct_kimi_production_config(config, identity.KIMI_PRODUCTION_ROLE)


def test_exact_provider_audit_accepts_reasoning_and_rejects_normalized(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\nopaque-b\n")
    exact = _private_file(
        root / "exact.jsonl",
        b"".join(shards._canonical(_trace(f"trace-{index}", task)) for index, task in enumerate(("opaque-a", "opaque-b"))),
    )
    result = shards.audit_results(exact, selector)
    assert result["traces"] == 2
    assert result["zero_reward_traces"] == 2
    assert result["clean_model_io_turns"] == 2

    normalized = _private_file(
        root / "normalized.jsonl",
        shards._canonical(_trace("trace-a", "opaque-a", response_kind="normalized_stream_response"))
        + shards._canonical(_trace("trace-b", "opaque-b")),
    )
    with pytest.raises(shards.StockSmallError, match="model_bearing_trace_invalid"):
        shards.audit_results(normalized, selector)


def test_error_rows_remain_covered_without_model_payload_inspection(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    row = {
        "id": "trace-a",
        "task": {"slug": "opaque-a"},
        "errors": [{"category": "aggregate"}],
        "rewards": {},
        "nodes": [],
    }
    results = _private_file(root / "results.jsonl", shards._canonical(row))

    audit = shards.audit_results(results, selector)
    assert audit["traces"] == 1
    assert audit["error_traces"] == 1
    assert audit["zero_model_error_traces"] == 1
    assert audit["model_bearing_error_traces"] == 0


def test_model_bearing_error_trace_still_requires_lossless_reasoning(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    exact_row = _trace("trace-a", "opaque-a")
    exact_row["errors"] = [{"category": "aggregate"}]
    exact = _private_file(root / "exact-error.jsonl", shards._canonical(exact_row))

    audit = shards.audit_results(exact, selector)
    assert audit["error_traces"] == 1
    assert audit["model_bearing_error_traces"] == 1
    assert audit["audited_model_io_turns"] == 1
    assert audit["zero_model_error_traces"] == 0

    normalized_row = _trace("trace-b", "opaque-a", response_kind="normalized_stream_response")
    normalized_row["errors"] = [{"category": "aggregate"}]
    normalized = _private_file(root / "normalized-error.jsonl", shards._canonical(normalized_row))
    with pytest.raises(shards.StockSmallError, match="model_bearing_trace_invalid"):
        shards.audit_results(normalized, selector)


def test_zero_reward_infrastructure_stop_is_not_certifiable(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    row = _trace("trace-a", "opaque-a")
    row["stop_condition"] = "wall_clock_timeout"
    results = _private_file(root / "timed-out.jsonl", shards._canonical(row))

    with pytest.raises(shards.StockSmallError, match="model_bearing_trace_invalid"):
        shards.audit_results(results, selector)


def test_launcher_is_serial_c64_and_never_reuses_partial_attempts() -> None:
    body = (shards._workflow_dir() / "run_kimi_2499_stock_small_shard.sbatch").read_text()
    assert "#SBATCH --time=7-00:00:00" in body
    assert "minimum_job_remaining_seconds=475200" in body
    assert "squeue -h -j" in body
    assert "#SBATCH --array=0-39%1" in body
    assert "DIRECT_KIMI_ROLLOUT_CONCURRENCY=64" in body
    assert "--concurrency 64" in body
    assert 'output_dir="$shard_root/attempt-${SLURM_JOB_ID}"' in body
    assert "validate-completion" in body
    assert "DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS=0" in body
    assert "KIMI_ENDPOINT_MINIMUM_REMAINING_SECONDS=172800" in body
    assert "partial_attempt_requires_manual_recovery" in body
