from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import eval_run_identity as identity
import kimi_stock_small_shards as shards
import pytest


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


def _error(error_type: str = "HarnessError") -> dict[str, str]:
    value = {"message": "opaque", "type": error_type}
    if error_type != "ProviderError":
        value["traceback"] = ""
    return value


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
    assert "environment.timeout=3600" in config["harness"]["config_overrides"]
    assert config["harness"]["runtime"]["provisioning_retries"] == 8
    assert config["timeout"]["rollout"] == 129_600
    assert config["harness"]["env"] == {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"}
    assert config["taskset"]["verifier_runtime_retries"] == 2
    assert config["taskset"]["retry_shared_verifier_scoring"] is True
    assert config["taskset"]["resource_cpu_cap"] == 1
    assert config["taskset"]["resource_memory_mb_cap"] == 2_048
    identity._validate_direct_kimi_production_config(config, identity.KIMI_PRODUCTION_ROLE)

    contracts = shards._contracts()
    assert contracts["model_attempts"] == 1
    assert contracts["model_retries"] == 0
    assert contracts["guest_transport_retry_attempts"] == 10
    assert contracts["logical_request_upstream_attempts"] == 1
    assert contracts["zero_model_resume_attempts"] == 0
    assert contracts["model_bearing_errors_terminal"] is True
    assert contracts["model_bearing_error_schemas"] == {
        "HarnessError": ["message", "traceback", "type"],
        "ProviderError": ["message", "type"],
    }
    assert contracts["timeouts"]["shell_action_seconds"] == 3_600
    assert contracts["resume"]["model_bearing_retry"] is False
    assert contracts["resume"]["zero_model_rows"] == "uncertifiable-manual-recovery"
    assert contracts["resume"]["rollover_policy"] == "new-plan-required"
    assert contracts["prelaunch_gates"]["real_task_image_c64_soak"] == {
        "kind": "kimi-k3-stock-small-task-image-c64-soak",
        "task_count": 2_499,
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


def test_stock_small_identity_distinguishes_guest_replay_from_model_retry() -> None:
    config = shards._load_base()[0]
    config["num_tasks"] = 63
    config["client"]["headers"] = {}

    contract, _execution = identity._contract(
        config,
        "Kimi-K3",
        role=identity.KIMI_PRODUCTION_ROLE,
        sandbox_provider="sandoq",
    )

    assert config["client"]["max_retries"] == 0
    assert config["retries"]["rollout"]["max_retries"] == 0
    assert contract["harness"]["request_max_retries"] == 0
    assert contract["harness"]["guest_transport_retry_attempts"] == 10
    assert contract["harness"]["logical_request_upstream_attempts"] == 1


def test_small_production_config_rejects_a_second_model_attempt() -> None:
    config = shards._load_base()[0]
    config["num_tasks"] = 64
    config["harness"]["env"]["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = "2"
    with pytest.raises(identity.EvalIdentityError, match="direct_kimi_production_config_invalid"):
        identity._validate_direct_kimi_production_config(config, identity.KIMI_PRODUCTION_ROLE)


def test_small_production_config_rejects_rollout_sized_shell_actions() -> None:
    config = shards._load_base()[0]
    config["num_tasks"] = 64
    config["harness"]["config_overrides"][2] = "environment.timeout=129600"
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

    wrong_type = _trace("trace-c", "opaque-a")
    wrong_type["errors"] = [_error("SandboxError")]
    wrong_type["rewards"] = {}
    wrong_type["metrics"] = {}
    unsupported = _private_file(root / "wrong-error-type.jsonl", shards._canonical(wrong_type))
    with pytest.raises(shards.StockSmallError, match="model_bearing_error_type_invalid"):
        shards.audit_results(unsupported, selector)


def test_error_rows_remain_covered_without_model_payload_inspection(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    row = {
        "id": "trace-a",
        "task": {"slug": "opaque-a"},
        "errors": [_error("SandboxError")],
        "rewards": {},
        "metrics": {},
        "info": {},
        "is_completed": True,
        "stop_condition": "error",
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
    exact_row["errors"] = [_error()]
    exact_row["rewards"] = {}
    exact_row["metrics"] = {}
    exact = _private_file(root / "exact-error.jsonl", shards._canonical(exact_row))

    audit = shards.audit_results(exact, selector)
    assert audit["error_traces"] == 1
    assert audit["model_bearing_error_traces"] == 1
    assert audit["model_bearing_harness_error_traces"] == 1
    assert audit["model_bearing_provider_error_traces"] == 0
    assert audit["audited_model_io_turns"] == 1
    assert audit["zero_model_error_traces"] == 0

    normalized_row = _trace("trace-b", "opaque-a", response_kind="normalized_stream_response")
    normalized_row["errors"] = [_error()]
    normalized_row["rewards"] = {}
    normalized_row["metrics"] = {}
    normalized = _private_file(root / "normalized-error.jsonl", shards._canonical(normalized_row))
    with pytest.raises(shards.StockSmallError, match="model_bearing_trace_invalid"):
        shards.audit_results(normalized, selector)


def test_model_bearing_provider_error_requires_exact_on_disk_shape(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    row = _trace("trace-a", "opaque-a")
    row["errors"] = [_error("ProviderError")]
    row["rewards"] = {}
    row["metrics"] = {}
    row["stop_condition"] = "error"
    exact = _private_file(root / "provider-error.jsonl", shards._canonical(row))

    audit = shards.audit_results(exact, selector)
    assert audit["model_bearing_error_traces"] == 1
    assert audit["model_bearing_harness_error_traces"] == 0
    assert audit["model_bearing_provider_error_traces"] == 1

    row["errors"][0]["traceback"] = None
    invalid = _private_file(root / "provider-error-null.jsonl", shards._canonical(row))
    with pytest.raises(shards.StockSmallError, match="trace_errors_invalid"):
        shards.audit_results(invalid, selector)


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
    stage = (shards._workflow_dir() / "run_direct_kimi_sandoq_stage.sh").read_text()
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
    assert "Stock-small production forbids broad resume" in stage
    assert "--resume \"$output_dir\"" in stage


def _proxy_summary(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "requests": 1,
        "upstream_attempts": 1,
        "logical_requests": 1,
        "logical_upstream_attempts": 1,
        "anonymous_upstream_attempts": 0,
        "coalesced_requests": 0,
        "replayed_requests": 0,
        "expired_logical_retries": 0,
        "downstream_disconnects": 0,
        "conflicting_requests": 0,
        "inflight": 0,
        "streamed_requests": 1,
        "response_bytes": 100,
        "statuses": {"200": 1},
        "protocols": {"chat_completions": 1},
        "path_counts": {
            "/muse-code/models": 0,
            "/v1/chat/completions": 1,
            "/v1/responses": 0,
        },
        "error_count": 0,
        "unknown_path_requests": 0,
    }
    value.update(overrides)
    return value


def _proxy_log(*records: dict[str, object]) -> bytes:
    return b"".join(
        b"12:34:56 INFO sandoq: buffered model proxy summary "
        + json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
        for record in records
    )


def test_buffered_proxy_audit_requires_exact_once_and_retains_only_aggregates() -> None:
    first = _proxy_summary()
    second = _proxy_summary(requests=2, replayed_requests=1)
    value = shards._buffered_proxy_audit(_proxy_log(first, second))

    assert value["source_schema"] == "logical-exact-once-v1"
    assert value["summary_records"] == 2
    assert value["integer_totals"]["logical_requests"] == 2
    assert value["integer_totals"]["logical_upstream_attempts"] == 2
    assert value["integer_totals"]["replayed_requests"] == 1
    assert "response_bytes" not in json.dumps(value["mapping_totals"])


@pytest.mark.parametrize(
    "override",
    (
        {"logical_upstream_attempts": 2, "upstream_attempts": 2},
        {"anonymous_upstream_attempts": 1, "upstream_attempts": 2},
        {"conflicting_requests": 1, "requests": 2},
        {"expired_logical_retries": 1, "requests": 2},
    ),
)
def test_buffered_proxy_audit_rejects_non_exact_once_transport(
    override: dict[str, object],
) -> None:
    with pytest.raises(shards.StockSmallError, match="buffered_proxy_exact_once_invalid"):
        shards._buffered_proxy_audit(_proxy_log(_proxy_summary(**override)))


def test_transport_aggregation_is_shard_order_bound() -> None:
    first = shards._bind_proxy_audit_to_trace(
        shards._buffered_proxy_audit(_proxy_log(_proxy_summary())),
        audited_model_io_turns=1,
        maximum_terminal_gap=0,
    )
    second = shards._bind_proxy_audit_to_trace(
        shards._buffered_proxy_audit(
            _proxy_log(_proxy_summary(requests=2, coalesced_requests=1))
        ),
        audited_model_io_turns=1,
        maximum_terminal_gap=0,
    )
    aggregate = shards._aggregate_transport_audits([first, second])

    assert aggregate["summary_records"] == 2
    assert aggregate["integer_totals"]["logical_requests"] == 2
    assert aggregate["integer_totals"]["coalesced_requests"] == 1
    assert len(aggregate["shard_audit_set_sha256"]) == 64


def test_transport_trace_binding_accepts_one_typed_terminal_attempt_gap() -> None:
    audit = shards._buffered_proxy_audit(
        _proxy_log(_proxy_summary(statuses={"503": 1}))
    )
    bound = shards._bind_proxy_audit_to_trace(
        audit,
        audited_model_io_turns=0,
        maximum_terminal_gap=1,
    )

    assert bound["terminal_outcomes"]["failure_records"] == 1
    assert bound["trace_binding"]["terminal_attempt_gap"] == 1


def test_transport_trace_binding_rejects_untyped_missing_model_io() -> None:
    audit = shards._buffered_proxy_audit(_proxy_log(_proxy_summary()))
    with pytest.raises(shards.StockSmallError, match="buffered_proxy_trace_mismatch"):
        shards._bind_proxy_audit_to_trace(
            audit,
            audited_model_io_turns=0,
            maximum_terminal_gap=1,
        )


def test_tb4_provider_context_reopens_private_snapshot_and_binds_run_dir(
    tmp_path: Path,
) -> None:
    run = _private_dir(tmp_path / "run")
    snapshot = {
        "schema_version": 1,
        "kind": "sandoq-provider-context-snapshot",
        "state": "validated",
        "provider_environment": "oci-runner-firecracker-small",
        "effective_task_network": "public",
        "task_network": "host",
        "network_access": True,
        "allow_dockerhub_fallback": False,
        "provider_profile_sha256": shards.PROVIDER_PROFILE_SHA256,
        "provider_token_file_path_sha256": shards.PROVIDER_TOKEN_PATH_SHA256,
        "runtime_smoke_receipt_sha256": None,
        "provider_context_contract_sha256": "a" * 64,
    }
    path = _private_file(run / "sandoq-provider-context.json", shards._canonical(snapshot))
    value = {
        "artifact": shards._artifact(path, path.read_bytes()),
        "contract_sha256": "a" * 64,
    }

    assert (
        shards._validate_tb4_provider_context(
            value,
            executed_results={"path": str(run / "results.jsonl")},
            held=None,
        )
        == snapshot
    )
    with pytest.raises(shards.StockSmallError, match="tb4_gate_provider_context_invalid"):
        shards._validate_tb4_provider_context(
            value,
            executed_results={"path": str(tmp_path / "other/results.jsonl")},
            held=None,
        )
