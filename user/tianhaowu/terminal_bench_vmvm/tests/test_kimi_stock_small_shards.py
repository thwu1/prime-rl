from __future__ import annotations

import copy
import hashlib
import inspect
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


def _shared_verifier_transport_error(trace_id: str, task: str) -> dict:
    row = _trace(trace_id, task)
    row["errors"] = [_error("SandboxError")]
    row["rewards"] = {}
    row["metrics"] = {}
    row["stop_condition"] = "agent_completed"
    row["info"] = {"terminal_bench_verifier": dict(shards.SHARED_VERIFIER_TERMINAL_TRANSPORT_DISPOSITION)}
    return row


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
    assert config["taskset"]["verifier_runtime_retries"] == 0
    assert config["taskset"]["retry_shared_verifier_scoring"] is False
    assert config["taskset"]["resource_cpu_cap"] == 1
    assert config["taskset"]["resource_memory_mb_cap"] == 2_048
    identity._validate_direct_kimi_production_config(config, identity.KIMI_PRODUCTION_ROLE)

    contracts = shards._contracts()
    assert contracts["model_attempts"] == 1
    assert contracts["model_retries"] == 0
    assert contracts["guest_transport_retry_attempts"] == 10
    assert contracts["logical_request_upstream_attempts"] == 1
    assert contracts["transport_evidence"] == {
        "schema": "logical-exact-once-v1",
        "source": "per-runtime-mode-0600-summary-records",
        "records_per_task": 1,
        "router_proxy_trace_binding_required": True,
        "terminal_provider_statuses": ["429", "5xx"],
        "proxy_exception_records": 0,
    }
    assert contracts["zero_model_resume_attempts"] == 0
    assert contracts["model_bearing_errors_terminal"] is True
    assert contracts["model_bearing_error_schemas"] == {
        "HarnessError": ["message", "traceback", "type"],
        "ProviderError": ["message", "type"],
        "SandboxError": ["message", "traceback", "type"],
    }
    assert contracts["shared_verifier_terminal_transport_disposition"] == (
        shards.SHARED_VERIFIER_TERMINAL_TRANSPORT_DISPOSITION
    )
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
        "mode": "same-post-agent-runtime-background-single-attempt",
        "retries": 0,
        "maximum_attempts": 1,
        "model_calls": 0,
        "infrastructure_errors_remain_errors": True,
        "posthoc_recovery": False,
    }
    assert shards.TB4_LANE_PRIME_FILES == (
        shards.tb4_transport.TB4_LANE_EXECUTION_FILES + shards.tb4_transport.V7_TB4_LANE_EXECUTION_FILES
    )


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
        b"".join(
            shards._canonical(_trace(f"trace-{index}", task)) for index, task in enumerate(("opaque-a", "opaque-b"))
        ),
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
    wrong_type["stop_condition"] = "error"
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

    row["stop_condition"] = "task_completed"
    invalid_stop = _private_file(root / "invalid-stop.jsonl", shards._canonical(row))
    with pytest.raises(shards.StockSmallError, match="trace_errors_invalid"):
        shards.audit_results(invalid_stop, selector)


def test_model_bearing_error_trace_still_requires_lossless_reasoning(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    exact_row = _trace("trace-a", "opaque-a")
    exact_row["errors"] = [_error()]
    exact_row["rewards"] = {}
    exact_row["metrics"] = {}
    exact_row["stop_condition"] = "error"
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
    normalized_row["stop_condition"] = "error"
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


@pytest.mark.parametrize("stop_condition", ("agent_completed", "max_total_tokens", "max_turns"))
def test_shared_verifier_transport_error_is_retained_but_nontrainable(
    tmp_path: Path,
    stop_condition: str,
) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    row = _shared_verifier_transport_error("trace-a", "opaque-a")
    row["stop_condition"] = stop_condition
    results = _private_file(root / "results.jsonl", shards._canonical(row))

    audit = shards.audit_results(results, selector)

    assert audit["traces"] == 1
    assert audit["error_traces"] == 1
    assert audit["model_bearing_error_traces"] == 1
    assert audit["model_bearing_shared_verifier_transport_error_traces"] == 1
    assert audit["model_bearing_harness_error_traces"] == 0
    assert audit["model_bearing_provider_error_traces"] == 0
    assert audit["zero_reward_traces"] == 0
    assert audit["positive_traces"] == 0


def test_shared_verifier_transport_error_requires_exact_host_disposition(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    missing = _shared_verifier_transport_error("trace-a", "opaque-a")
    missing["info"] = {}
    missing_results = _private_file(root / "missing.jsonl", shards._canonical(missing))
    with pytest.raises(shards.StockSmallError, match="trace_errors_invalid"):
        shards.audit_results(missing_results, selector)

    spoofed = _shared_verifier_transport_error("trace-b", "opaque-a")
    spoofed["info"]["terminal_bench_verifier"]["posthoc_recovery"] = True
    spoofed_results = _private_file(root / "spoofed.jsonl", shards._canonical(spoofed))
    with pytest.raises(shards.StockSmallError, match="trace_errors_invalid"):
        shards.audit_results(spoofed_results, selector)

    wrong_stop = _shared_verifier_transport_error("trace-stop", "opaque-a")
    wrong_stop["stop_condition"] = "error"
    wrong_stop_results = _private_file(root / "wrong-stop.jsonl", shards._canonical(wrong_stop))
    with pytest.raises(shards.StockSmallError, match="model_bearing_error_type_invalid"):
        shards.audit_results(wrong_stop_results, selector)

    fabricated_reward = _shared_verifier_transport_error("trace-c", "opaque-a")
    fabricated_reward["rewards"] = {"solved": 0}
    reward_results = _private_file(root / "reward.jsonl", shards._canonical(fabricated_reward))
    with pytest.raises(shards.StockSmallError, match="trace_errors_invalid"):
        shards.audit_results(reward_results, selector)


def test_shared_verifier_transport_row_cannot_complete_partial_shard(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\nopaque-b\n")
    row = _shared_verifier_transport_error("trace-a", "opaque-a")
    results = _private_file(root / "partial.jsonl", shards._canonical(row))

    with pytest.raises(shards.StockSmallError, match="trace_coverage_invalid"):
        shards.audit_results(results, selector)


@pytest.mark.parametrize("error_type", ("HarnessError", "ProviderError"))
def test_model_bearing_error_rejects_duplicate_terminal_errors(
    tmp_path: Path,
    error_type: str,
) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    row = _trace("trace-a", "opaque-a")
    row["errors"] = [_error(error_type), _error(error_type)]
    row["rewards"] = {}
    row["metrics"] = {}
    row["stop_condition"] = "error"
    results = _private_file(root / "duplicate-errors.jsonl", shards._canonical(row))

    with pytest.raises(shards.StockSmallError, match="trace_errors_invalid"):
        shards.audit_results(results, selector)


def test_zero_model_provider_error_rejects_duplicate_terminal_errors(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    selector = _private_file(root / "selector.txt", b"opaque-a\n")
    row = {
        "id": "trace-a",
        "task": {"slug": "opaque-a"},
        "errors": [_error("ProviderError"), _error("ProviderError")],
        "rewards": {},
        "metrics": {},
        "info": {},
        "is_completed": True,
        "stop_condition": "error",
        "nodes": [],
    }
    results = _private_file(root / "duplicate-zero-model-errors.jsonl", shards._canonical(row))

    with pytest.raises(shards.StockSmallError, match="trace_errors_invalid"):
        shards.audit_results(results, selector)


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
    assert "--allow-terminal-upstream-statuses" in body
    assert "36b0dff6c18affb3d40b7c46d5836381d568050b" in body
    assert 'exec 8>"$generation_dir/.direct_router.lock"' in body
    assert body.index("flock -n 8") < body.index('direct_kimi_router.py"')
    assert body.index("flock -u 8") < body.index('kimi_stock_small_shards.py" certify-shard')
    assert "Stock-small production forbids broad resume" in stage
    assert '|| "$role" == kimi-direct-mobius' in stage
    assert 'export SANDOQ_BUFFERED_STATS_DIR="$buffered_stats_dir"' in stage
    assert '--resume "$output_dir"' in stage


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
    second = _proxy_summary(
        requests=2,
        replayed_requests=1,
        streamed_requests=2,
        protocols={"chat_completions": 2},
        path_counts={
            "/muse-code/models": 0,
            "/v1/chat/completions": 2,
            "/v1/responses": 0,
        },
    )
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
        source_model_io_turns=1,
        clean_model_io_turns=1,
        validated_error_model_io_turns=0,
        maximum_terminal_gap=0,
        expected_summary_records=1,
    )
    second = shards._bind_proxy_audit_to_trace(
        shards._buffered_proxy_audit(
            _proxy_log(
                _proxy_summary(
                    requests=2,
                    coalesced_requests=1,
                    streamed_requests=2,
                    protocols={"chat_completions": 2},
                    path_counts={
                        "/muse-code/models": 0,
                        "/v1/chat/completions": 2,
                        "/v1/responses": 0,
                    },
                )
            )
        ),
        source_model_io_turns=1,
        clean_model_io_turns=1,
        validated_error_model_io_turns=0,
        maximum_terminal_gap=0,
        expected_summary_records=1,
    )
    aggregate = shards._aggregate_transport_audits([first, second])

    assert aggregate["summary_records"] == 2
    assert aggregate["integer_totals"]["logical_requests"] == 2
    assert aggregate["integer_totals"]["coalesced_requests"] == 1
    assert aggregate["trace_binding"]["source_model_io_turns"] == 2
    assert aggregate["trace_binding"]["validated_model_io_turns"] == 2
    assert len(aggregate["shard_audit_set_sha256"]) == 64


def test_transport_trace_binding_accepts_one_typed_terminal_attempt_gap() -> None:
    audit = shards._buffered_proxy_audit(_proxy_log(_proxy_summary(statuses={"503": 1})))
    bound = shards._bind_proxy_audit_to_trace(
        audit,
        source_model_io_turns=0,
        clean_model_io_turns=0,
        validated_error_model_io_turns=0,
        maximum_terminal_gap=1,
        expected_summary_records=1,
    )

    assert bound["terminal_outcomes"]["failure_records"] == 1
    assert bound["trace_binding"]["terminal_attempt_gap"] == 1


def test_transport_trace_binding_rejects_untyped_missing_model_io() -> None:
    audit = shards._buffered_proxy_audit(_proxy_log(_proxy_summary()))
    with pytest.raises(shards.StockSmallError, match="buffered_proxy_trace_mismatch"):
        shards._bind_proxy_audit_to_trace(
            audit,
            source_model_io_turns=0,
            clean_model_io_turns=0,
            validated_error_model_io_turns=0,
            maximum_terminal_gap=1,
            expected_summary_records=1,
        )


def test_transport_trace_binding_rejects_wrong_durable_record_count() -> None:
    audit = shards._buffered_proxy_audit(_proxy_log(_proxy_summary()))
    with pytest.raises(shards.StockSmallError, match="buffered_proxy_trace_mismatch"):
        shards._bind_proxy_audit_to_trace(
            audit,
            source_model_io_turns=1,
            clean_model_io_turns=1,
            validated_error_model_io_turns=0,
            maximum_terminal_gap=0,
            expected_summary_records=2,
        )


def test_router_transport_binding_exactly_reconciles_terminal_provider_status() -> None:
    audit = shards._buffered_proxy_audit(_proxy_log(_proxy_summary(statuses={"503": 1})))
    bound = shards._bind_proxy_audit_to_trace(
        audit,
        source_model_io_turns=0,
        clean_model_io_turns=0,
        validated_error_model_io_turns=0,
        maximum_terminal_gap=1,
        expected_summary_records=1,
    )
    router = shards._canonical(
        {
            "chat_requests": 1,
            "upstream_failures": 0,
            "upstream_http_429": 0,
            "upstream_http_5xx": 1,
        }
    )

    binding = shards._bind_router_to_transport(
        router,
        bound,
        provider_error_rows=1,
    )
    assert binding["router_chat_requests"] == 1
    assert binding["proxy_non_2xx_upstream_responses"] == 1
    assert binding["provider_error_rows"] == 1

    with pytest.raises(shards.StockSmallError, match="router_transport_binding_invalid"):
        shards._bind_router_to_transport(router, bound, provider_error_rows=0)


def test_router_transport_aggregation_is_exact_and_order_bound() -> None:
    first = {
        "schema_version": 1,
        "state": "passed",
        "router_chat_requests": 2,
        "proxy_logical_requests": 2,
        "proxy_logical_upstream_attempts": 2,
        "router_upstream_http_429": 0,
        "router_upstream_http_5xx": 1,
        "proxy_non_2xx_upstream_responses": 1,
        "proxy_exception_records": 0,
        "provider_error_rows": 1,
    }
    second = {**first, "router_upstream_http_5xx": 0, "proxy_non_2xx_upstream_responses": 0, "provider_error_rows": 0}
    aggregate = shards._aggregate_router_transport_bindings([first, second])

    assert aggregate["shards"] == 2
    assert aggregate["router_chat_requests"] == 4
    assert aggregate["provider_error_rows"] == 1
    assert len(aggregate["shard_binding_set_sha256"]) == 64

    invalid = {**first, "proxy_exception_records": 1}
    with pytest.raises(shards.StockSmallError, match="router_transport_binding_invalid"):
        shards._aggregate_router_transport_bindings([invalid])


def test_stock_cleanup_binds_partial_wave_to_full_c64_pool(tmp_path: Path) -> None:
    run = _private_dir(tmp_path / "run")
    control = _private_dir(run / "control")
    raw = shards._canonical({"schema_version": 1, "state": "passed"})
    events = shards._canonical(
        {
            "schema_version": 2,
            "record_type": "pool_event",
            "event": "pool_drained",
            "slurm_job_id": "123",
        }
    )
    wal = shards._canonical({"schema_version": 2, "event": "outer_deleted", "slurm_job_id": "123"})
    raw_path = _private_file(run / "pool_cleanup_audit.json", raw)
    event_path = _private_file(run / "pool_events.jsonl", events)
    wal_path = _private_file(control / "sandoq-pool.wal.jsonl", wal)
    counts = {
        "recorded_outer_sessions": 64,
        "verified_http_404": 64,
        "already_absent": 0,
        "deleted_and_verified": 64,
        "assignments_acquired": 62,
        "assignment_release_rows": 62,
        "assignment_cancellation_rows": 0,
        "cleanup_gateway_retry_count": 0,
        "assignments_cleanup_verified": 62,
        "assignment_event_order_high_water": 62,
        "assignment_measured_high_water": 62,
        "outer_sessions_created": 64,
        "outer_sessions_deleted": 64,
        "outer_session_high_water": 64,
        "pool_drain_deleted": 0,
        "gateway_close_warnings": 0,
        "recovered_poisoned_assignments": 0,
        "failures": 0,
    }
    receipt = {
        "schema_version": 1,
        "kind": "sandoq-pool-cleanup",
        "state": "passed",
        **counts,
        "raw_audit_sha256": hashlib.sha256(raw).hexdigest(),
        "pool_event_log_sha256": hashlib.sha256(events).hexdigest(),
        "pool_wal_sha256": hashlib.sha256(wal).hexdigest(),
        "pool_drain_sha256": "d" * 64,
    }
    receipt_path = _private_file(run / "sandoq_cleanup_audit.json", shards._canonical(receipt))
    run_identity = {
        "execution": {
            "sandoq_environment": {
                "pool_event_log": str(event_path),
                "pool_wal": str(wal_path),
            }
        }
    }
    held = shards.split._HeldArtifactSet.create()
    try:
        summary, artifacts = shards._validate_stock_small_cleanup(
            receipt_path,
            run,
            run_identity,
            "a" * 64,
            "b" * 64,
            "123",
            62,
            held,
        )
    finally:
        held.close()

    assert summary["assignment_measured_high_water"] == 62
    assert artifacts["cleanup_raw_audit"] == shards._artifact(raw_path, raw)


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


def test_tb4_gate_variant_keeps_v7_v8_closed_and_enables_exact_v12_v13_v14_supersession() -> None:
    v7 = shards._tb4_gate_variant(
        {
            "schema_version": 1,
            "supersession": {"reason": "fixed-denominator-exact-transport-v7"},
        }
    )
    assert v7["allow_post_agent_verifier_sandbox_errors"] is False
    assert v7["extra_certificate_keys"] == frozenset()
    assert v7["supersession_source_paths"] == shards.tb4_transport.SUPERSESSION_SOURCE_FILES
    assert "execution_contract" not in v7

    v8 = shards._tb4_gate_variant(
        {
            "schema_version": 2,
            "supersession": {"reason": shards.tb4_v8.SUPERSESSION_REASON},
        }
    )
    assert v8["allow_post_agent_verifier_sandbox_errors"] is True
    assert v8["distinct_supersession_source_revision"] is True
    assert v8["extra_certificate_keys"] == frozenset(
        {
            "post_agent_verifier_error_policy",
            "pre_model_sandoq_provisioning_error_policy",
            "sandoq_assignment_lifecycle",
        }
    )
    assert v8["extra_count_keys"] == frozenset(
        {
            "post_agent_verifier_sandbox_error_zeroes",
            "pre_model_sandoq_provisioning_error_zeroes",
        }
    )
    assert v8["audit_pre_model_sandoq_provisioning_errors"] is True
    assert v8["supersession_source_paths"] == shards.tb4_v8.SUPERSESSION_SOURCE_FILES
    assert "execution_contract" not in v8

    v12 = shards._tb4_gate_variant(
        {
            "schema_version": 2,
            "supersession": {"reason": shards.tb4_v12.SUPERSESSION_REASON},
        }
    )
    assert v12["execution_contract"] == shards.tb4_v12.execution_contract(shards.tb4_v12.EXECUTION_SLURM_JOB_ID)
    assert v12["execution_contract"].source_revision == shards.tb4_v12.EXECUTION_SOURCE_REVISION
    assert v12["execution_contract"].plan_sha256 == shards.tb4_v12.EXECUTION_PLAN_SHA256
    assert v12["execution_contract"].stock_endpoint_identifier == shards.tb4_v12.STOCK_ENDPOINT_IDENTIFIER
    assert v12["execution_contract"].stock_source_spec_sha256 == shards.tb4_v12.STOCK_SOURCE_SPEC_SHA256
    assert v12["execution_contract"].stock_endpoint_bundle_sha256 == shards.tb4_v12.STOCK_ENDPOINT_BUNDLE_SHA256
    assert v12["extra_certificate_keys"] == frozenset(
        {
            "exact_length_benchmark_policy",
            "execution_completion",
            "persisted_verifier_artifacts",
            "post_agent_verifier_error_policy",
            "pre_model_sandoq_provisioning_error_policy",
            "sandoq_assignment_lifecycle",
        }
    )
    assert v12["extra_artifact_keys"] == frozenset({"execution_completion"})
    assert v12["extra_count_keys"] == frozenset(
        {
            "benchmark_scored_failures",
            "benchmark_scored_rows",
            "benchmark_valid_nontrainable_passes",
            "infrastructure_zeroes",
            "post_agent_verifier_artifact_write_transport_zeroes",
            "post_agent_verifier_exec_transport_zeroes",
            "post_agent_verifier_sandbox_error_zeroes",
            "pre_model_sandoq_provisioning_error_zeroes",
            "provider_scored_passes",
            "trainable_passes",
        }
    )
    assert v12["extra_training_keys"] == frozenset(
        {
            "eligible_clean_passes",
            "excluded_post_agent_verifier_artifact_write_transport_rows",
            "excluded_post_agent_verifier_sandbox_error_rows",
            "excluded_pre_model_sandoq_provisioning_error_rows",
            "post_agent_verifier_artifact_write_transport_rows_are_trainable",
            "post_agent_verifier_sandbox_error_rows_are_trainable",
            "pre_model_sandoq_provisioning_error_rows_are_trainable",
        }
    )
    assert v12["allow_exact_length_benchmark_rows"] is True
    assert v12["allow_post_agent_exec_transport_errors"] is True
    assert v12["allow_post_agent_artifact_write_transport_errors"] is True
    assert v12["require_persisted_verifier_artifacts"] is True
    assert "execution_plan" not in v12
    assert "execution_run_dir" not in v12
    assert v12["supersession_source_paths"] == shards.tb4_v12.SUPERSESSION_SOURCE_FILES
    assert v12["expected_supersession_source_revision"] == "aa3ebebec140261a437f538ffcb8b9b913974057"
    assert v12["expected_supersession_source_revision"] == shards.TB4_V12_SUPERSESSION_SOURCE_REVISION

    v13 = shards._tb4_gate_variant(
        {
            "schema_version": 2,
            "supersession": {"reason": shards.tb4_v13.SUPERSESSION_REASON},
        }
    )
    assert v13["execution_contract"] == shards.tb4_v13.execution_contract(shards.tb4_v13.EXECUTION_SLURM_JOB_ID)
    assert v13["execution_contract"].source_revision == "3a39b16535d4f77ba16336086441373756e29eda"
    assert v13["execution_contract"].slurm_job_id == "1618064"
    assert v13["execution_contract"].plan_sha256 == shards.tb4_v13.EXECUTION_PLAN_SHA256
    assert v13["execution_contract"].stock_endpoint_identifier == shards.tb4_v13.STOCK_ENDPOINT_IDENTIFIER
    assert v13["execution_contract"].stock_source_spec_sha256 == shards.tb4_v13.STOCK_SOURCE_SPEC_SHA256
    assert v13["execution_contract"].stock_endpoint_bundle_sha256 == shards.tb4_v13.STOCK_ENDPOINT_BUNDLE_SHA256
    assert v13["execution_plan"] == shards.tb4_v13.EXECUTION_PLAN
    assert v13["execution_run_dir"] == shards.tb4_v13.EXECUTION_RUN_DIR
    assert v13["supersession_source_paths"] == shards.tb4_v13.SUPERSESSION_SOURCE_FILES
    assert v13["expected_supersession_source_revision"] == "eecb29f549e94984722806bc72bc02ea9d06db63"
    assert v13["expected_supersession_source_revision"] == shards.TB4_V13_SUPERSESSION_SOURCE_REVISION
    assert v13["production_supersession_source_variant_files"] == shards.TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_FILES
    assert (
        v13["production_supersession_source_variant_pair_sha256"]
        == shards.TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256
    )
    policy_binding_keys = set(v12) - {
        "reason",
        "execution_contract",
        "supersession_source_paths",
        "expected_supersession_source_revision",
        "production_shared_variant_files",
        "production_lane_variant_files",
        "production_sandoq_variant_files",
        "production_variant_pair_sha256",
    }
    assert {key: v13[key] for key in policy_binding_keys} == {key: v12[key] for key in policy_binding_keys}

    v14 = shards._tb4_gate_variant(
        {
            "schema_version": 2,
            "supersession": {"reason": shards.tb4_v14.SUPERSESSION_REASON},
        }
    )
    assert v14["execution_contract"] == shards.tb4_v14.execution_contract(shards.tb4_v14.EXECUTION_SLURM_JOB_ID)
    assert v14["execution_contract"].source_revision == "3a39b16535d4f77ba16336086441373756e29eda"
    assert v14["execution_contract"].slurm_job_id == "1618064"
    assert v14["execution_contract"].plan_sha256 == shards.tb4_v14.EXECUTION_PLAN_SHA256
    assert v14["execution_contract"].allow_pre_ready_managed_shell_provisioning_failures is True
    assert v14["execution_plan"] == shards.tb4_v14.EXECUTION_PLAN
    assert v14["execution_run_dir"] == shards.tb4_v14.EXECUTION_RUN_DIR
    assert v14["supersession_source_paths"] == shards.tb4_v14.SUPERSESSION_SOURCE_FILES
    assert v14["expected_supersession_source_revision"] == "5d78c4ee12f8350637956b3d683e557db465fd49"
    assert v14["expected_supersession_source_revision"] == shards.TB4_V14_SUPERSESSION_SOURCE_REVISION
    assert v14["allow_pre_ready_managed_shell_provisioning_failures"] is True
    assert v13.get("allow_pre_ready_managed_shell_provisioning_failures", False) is False
    v14_policy_binding_keys = set(v14) - {
        "reason",
        "execution_contract",
        "supersession_source_paths",
        "expected_supersession_source_revision",
        "production_shared_variant_files",
        "production_lane_variant_files",
        "production_sandoq_variant_files",
        "production_variant_pair_sha256",
        "allow_pre_ready_managed_shell_provisioning_failures",
    }
    assert {key: v14[key] for key in v14_policy_binding_keys} == {key: v13[key] for key in v14_policy_binding_keys}

    for value in (
        {"schema_version": 1, "supersession": {"reason": shards.tb4_v8.SUPERSESSION_REASON}},
        {"schema_version": 2, "supersession": {"reason": "fixed-denominator-exact-transport-v7"}},
        {"schema_version": 1, "supersession": {"reason": shards.tb4_v12.SUPERSESSION_REASON}},
        {"schema_version": 1, "supersession": {"reason": shards.tb4_v13.SUPERSESSION_REASON}},
        {"schema_version": 1, "supersession": {"reason": shards.tb4_v14.SUPERSESSION_REASON}},
        {
            "schema_version": 2,
            "supersession": {"reason": "fresh-epoch-c16-persisted-verifier-artifacts-v11"},
        },
        {"schema_version": 2, "supersession": {"reason": "unknown"}},
    ):
        with pytest.raises(shards.StockSmallError, match="tb4_gate_invalid"):
            shards._tb4_gate_variant(value)


def test_tb4_production_variant_pair_exactly_binds_shared_verifier_resilience() -> None:
    root = Path(shards.__file__).resolve().parents[3]
    production_revision = "9714d9fd699beb106e32b5d0fe35519a12db5bee"
    shared_paths = shards.TB4_PRODUCTION_SHARED_VARIANT_FILES
    lane_paths = shards.TB4_PRODUCTION_LANE_VARIANT_FILES
    assert shared_paths == {
        "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py",
    }
    assert shared_paths.isdisjoint(lane_paths)
    assert shared_paths | lane_paths == shards.TB4_PRODUCTION_VARIANT_FILES
    assert shared_paths < set(shards.TB4_SHARED_PRIME_FILES)
    assert lane_paths <= set(shards.TB4_LANE_PRIME_FILES)

    production_shared = shards._git_file_hashes(root, production_revision, tuple(shared_paths))
    execution_shared = shards._git_file_hashes(root, shards.tb4_v8.EXECUTION_SOURCE_REVISION, tuple(shared_paths))
    production_lane = shards._git_file_hashes(root, production_revision, tuple(lane_paths))
    execution_lane = shards._git_file_hashes(root, shards.tb4_v8.EXECUTION_SOURCE_REVISION, tuple(lane_paths))
    pairs = {
        **{
            path: {"production": production_shared[path], "tb4": execution_shared[path]}
            for path in sorted(shared_paths)
        },
        **{path: {"production": production_lane[path], "tb4": execution_lane[path]} for path in sorted(lane_paths)},
    }
    assert shards._sha256(shards._canonical(pairs)) == shards.TB4_PRODUCTION_VARIANT_PAIR_SHA256
    changed = copy.deepcopy(pairs)
    changed[next(iter(shared_paths))]["production"] = "0" * 64
    assert shards._sha256(shards._canonical(changed)) != shards.TB4_PRODUCTION_VARIANT_PAIR_SHA256


def test_tb4_v12_production_variant_pair_exactly_binds_reviewed_source_delta() -> None:
    root = Path(shards.__file__).resolve().parents[3]
    production_revision = shards._git(root, "rev-parse", "HEAD")
    assert shards.tb4_v12.EXECUTION_SOURCE_REVISION == "307c569f376429cdbf8b7233e5999a3c28df577a"
    assert shards.TB4_V12_SUPERSESSION_SOURCE_REVISION == "aa3ebebec140261a437f538ffcb8b9b913974057"
    assert len(
        {
            shards.tb4_v12.EXECUTION_SOURCE_REVISION,
            shards.TB4_V12_SUPERSESSION_SOURCE_REVISION,
            production_revision,
        }
    ) == 3
    shared_paths = shards.TB4_V12_PRODUCTION_SHARED_VARIANT_FILES
    lane_paths = shards.TB4_V12_PRODUCTION_LANE_VARIANT_FILES
    sandoq_paths = shards.TB4_V12_PRODUCTION_SANDOQ_VARIANT_FILES
    assert shared_paths == {
        "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py",
    }
    assert lane_paths == {
        "user/tianhaowu/terminal_bench_vmvm/eval_run_identity.py",
    }
    assert sandoq_paths == {
        "extensions/sandoq/sandoq_provider/oci_client.py",
        "extensions/sandoq/sandoq_provider/tests/test_oci_client_security.py",
    }
    execution_revision = shards.tb4_v12.EXECUTION_SOURCE_REVISION
    pairs = {
        **{
            path: {
                "production": shards._git_file_hashes(root, production_revision, (path,))[path],
                "tb4": shards._git_file_hashes(root, execution_revision, (path,))[path],
            }
            for path in sorted(shared_paths | lane_paths | sandoq_paths)
        },
    }
    assert shards._sha256(shards._canonical(pairs)) == shards.TB4_V12_PRODUCTION_VARIANT_PAIR_SHA256
    changed = copy.deepcopy(pairs)
    changed[next(iter(shared_paths))]["production"] = "0" * 64
    assert shards._sha256(shards._canonical(changed)) != shards.TB4_V12_PRODUCTION_VARIANT_PAIR_SHA256


def test_tb4_v12_supersession_source_binds_submitted_aa3_certifier() -> None:
    root = Path(shards.__file__).resolve().parents[3]
    source_revision = shards.TB4_V12_SUPERSESSION_SOURCE_REVISION
    source_paths = shards.tb4_v12.SUPERSESSION_SOURCE_FILES
    source_files = shards._git_file_hashes(root, source_revision, source_paths)
    production_revision = shards._git(root, "rev-parse", "HEAD")
    production_files = shards._git_file_hashes(root, production_revision, source_paths)
    variant_files = shards.TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_FILES
    assert {path for path in source_paths if source_files[path] != production_files[path]} == variant_files
    pairs = {path: {"production": production_files[path], "tb4": source_files[path]} for path in sorted(variant_files)}
    assert shards._sha256(shards._canonical(pairs)) == shards.TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256
    value = {
        "project_root": "/storage/home/tianhaowu/prime-kimi-tb4-v12-certifier-1612350",
        "revision": source_revision,
        "hash_kind": "raw-file-sha256",
        "files": source_files,
        "file_set_sha256": shards._sha256(shards._canonical(source_files)),
    }
    result = shards._validate_tb4_supersession_source(
        value,
        tb4_root=root,
        production_root=root,
        certificate_revision=shards.tb4_v12.EXECUTION_SOURCE_REVISION,
        source_paths=source_paths,
        distinct_source_revision=True,
        expected_source_revision=source_revision,
        production_variant_files=variant_files,
        production_variant_pair_sha256=shards.TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256,
    )
    assert result["source_revision"] == source_revision
    assert result["production_variant_pair_sha256"] == shards.TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256

    changed = {**value, "revision": "eee438556236abb5e186621bdda15e6141763590"}
    with pytest.raises(shards.StockSmallError, match="tb4_supersession_source_invalid"):
        shards._validate_tb4_supersession_source(
            changed,
            tb4_root=root,
            production_root=root,
            certificate_revision=shards.tb4_v12.EXECUTION_SOURCE_REVISION,
            source_paths=source_paths,
            distinct_source_revision=True,
            expected_source_revision=source_revision,
            production_variant_files=variant_files,
            production_variant_pair_sha256=shards.TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256,
        )
    with pytest.raises(shards.StockSmallError, match="tb4_supersession_source_invalid"):
        shards._validate_tb4_supersession_source(
            value,
            tb4_root=root,
            production_root=root,
            certificate_revision=shards.tb4_v12.EXECUTION_SOURCE_REVISION,
            source_paths=source_paths,
            distinct_source_revision=True,
            expected_source_revision=source_revision,
            production_variant_files=variant_files,
            production_variant_pair_sha256="0" * 64,
        )


def test_tb4_v12_execution_semantics_accept_exact_pair_and_reject_tamper_or_unknown_revision() -> None:
    root = Path(shards.__file__).resolve().parents[3]
    contract = shards.tb4_v12.execution_contract(shards.tb4_v12.EXECUTION_SLURM_JOB_ID)
    semantics = shards.tb4_transport._execution_semantics_manifest(
        contract.source_revision,
        contract.verifiers_commit,
    )
    variant = shards._tb4_gate_variant(
        {
            "schema_version": 2,
            "supersession": {"reason": shards.tb4_v12.SUPERSESSION_REASON},
        }
    )
    result = shards._validate_tb4_execution_semantics(
        semantics,
        tb4_root=root,
        production_root=root,
        certificate_revision=contract.source_revision,
        verifiers_revision=contract.verifiers_commit,
        production_shared_variant_files=variant["production_shared_variant_files"],
        production_lane_variant_files=variant["production_lane_variant_files"],
        production_sandoq_variant_files=variant["production_sandoq_variant_files"],
        production_variant_pair_sha256=variant["production_variant_pair_sha256"],
    )
    assert result["production_variant_pair_sha256"] == shards.TB4_V12_PRODUCTION_VARIANT_PAIR_SHA256

    with pytest.raises(shards.StockSmallError, match="tb4_lane_specific_semantics_changed"):
        shards._validate_tb4_execution_semantics(
            semantics,
            tb4_root=root,
            production_root=root,
            certificate_revision=contract.source_revision,
            verifiers_revision=contract.verifiers_commit,
            production_shared_variant_files=variant["production_shared_variant_files"],
            production_lane_variant_files=variant["production_lane_variant_files"],
            production_sandoq_variant_files=variant["production_sandoq_variant_files"],
            production_variant_pair_sha256="0" * 64,
        )
    with pytest.raises(shards.StockSmallError, match="tb4_execution_semantics_invalid"):
        shards._validate_tb4_execution_semantics(
            semantics,
            tb4_root=root,
            production_root=root,
            certificate_revision="f" * 40,
            verifiers_revision=contract.verifiers_commit,
            production_shared_variant_files=variant["production_shared_variant_files"],
            production_lane_variant_files=variant["production_lane_variant_files"],
            production_sandoq_variant_files=variant["production_sandoq_variant_files"],
            production_variant_pair_sha256=variant["production_variant_pair_sha256"],
        )


def test_tb4_v13_source_execution_and_empty_variant_are_exact_and_tamper_closed() -> None:
    root = Path(shards.__file__).resolve().parents[3]
    contract = shards.tb4_v13.execution_contract(shards.tb4_v13.EXECUTION_SLURM_JOB_ID)
    variant = shards._tb4_gate_variant(
        {
            "schema_version": 2,
            "supersession": {"reason": shards.tb4_v13.SUPERSESSION_REASON},
        }
    )
    assert variant["production_shared_variant_files"] == frozenset()
    assert variant["production_lane_variant_files"] == frozenset()
    assert variant["production_sandoq_variant_files"] == frozenset()
    assert shards._sha256(shards._canonical({})) == shards.TB4_V13_PRODUCTION_VARIANT_PAIR_SHA256

    source_revision = shards.TB4_V13_SUPERSESSION_SOURCE_REVISION
    source_paths = shards.tb4_v13.SUPERSESSION_SOURCE_FILES
    source_files = shards._git_file_hashes(root, source_revision, source_paths)
    production_revision = shards._git(root, "rev-parse", "HEAD")
    production_files = shards._git_file_hashes(root, production_revision, source_paths)
    source_variant_files = variant["production_supersession_source_variant_files"]
    assert {path for path in source_paths if source_files[path] != production_files[path]} == source_variant_files
    source_variant_pairs = {
        path: {"production": production_files[path], "tb4": source_files[path]} for path in sorted(source_variant_files)
    }
    assert (
        shards._sha256(shards._canonical(source_variant_pairs))
        == variant["production_supersession_source_variant_pair_sha256"]
    )
    source = {
        "project_root": "/storage/home/tianhaowu/prime-kimi-tb4-v13-certifier-1618064",
        "revision": source_revision,
        "hash_kind": "raw-file-sha256",
        "files": source_files,
        "file_set_sha256": shards._sha256(shards._canonical(source_files)),
    }
    assert (
        shards._validate_tb4_supersession_source(
            source,
            tb4_root=root,
            production_root=root,
            certificate_revision=contract.source_revision,
            source_paths=source_paths,
            distinct_source_revision=True,
            expected_source_revision=source_revision,
            production_variant_files=source_variant_files,
            production_variant_pair_sha256=variant["production_supersession_source_variant_pair_sha256"],
        )["production_variant_pair_sha256"]
        == shards.TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256
    )
    with pytest.raises(shards.StockSmallError, match="tb4_supersession_source_invalid"):
        shards._validate_tb4_supersession_source(
            {**source, "revision": contract.source_revision},
            tb4_root=root,
            production_root=root,
            certificate_revision=contract.source_revision,
            source_paths=source_paths,
            distinct_source_revision=True,
            expected_source_revision=source_revision,
            production_variant_files=source_variant_files,
            production_variant_pair_sha256=variant["production_supersession_source_variant_pair_sha256"],
        )

    semantics = shards.tb4_transport._execution_semantics_manifest(
        contract.source_revision,
        contract.verifiers_commit,
    )
    result = shards._validate_tb4_execution_semantics(
        semantics,
        tb4_root=root,
        production_root=root,
        certificate_revision=contract.source_revision,
        verifiers_revision=contract.verifiers_commit,
        production_shared_variant_files=variant["production_shared_variant_files"],
        production_lane_variant_files=variant["production_lane_variant_files"],
        production_sandoq_variant_files=variant["production_sandoq_variant_files"],
        production_variant_pair_sha256=variant["production_variant_pair_sha256"],
    )
    assert result["production_variant_pair_sha256"] == shards.TB4_V13_PRODUCTION_VARIANT_PAIR_SHA256
    with pytest.raises(shards.StockSmallError, match="tb4_lane_specific_semantics_changed"):
        shards._validate_tb4_execution_semantics(
            semantics,
            tb4_root=root,
            production_root=root,
            certificate_revision=contract.source_revision,
            verifiers_revision=contract.verifiers_commit,
            production_shared_variant_files=variant["production_shared_variant_files"],
            production_lane_variant_files=variant["production_lane_variant_files"],
            production_sandoq_variant_files=variant["production_sandoq_variant_files"],
            production_variant_pair_sha256="0" * 64,
        )
    with pytest.raises(shards.StockSmallError, match="tb4_execution_semantics_invalid"):
        shards._validate_tb4_execution_semantics(
            semantics,
            tb4_root=root,
            production_root=root,
            certificate_revision="f" * 40,
            verifiers_revision=contract.verifiers_commit,
            production_shared_variant_files=variant["production_shared_variant_files"],
            production_lane_variant_files=variant["production_lane_variant_files"],
            production_sandoq_variant_files=variant["production_sandoq_variant_files"],
            production_variant_pair_sha256=variant["production_variant_pair_sha256"],
        )


def test_tb4_v14_source_execution_and_empty_variant_are_exact_and_tamper_closed() -> None:
    root = Path(shards.__file__).resolve().parents[3]
    contract = shards.tb4_v14.execution_contract(shards.tb4_v14.EXECUTION_SLURM_JOB_ID)
    variant = shards._tb4_gate_variant(
        {
            "schema_version": 2,
            "supersession": {"reason": shards.tb4_v14.SUPERSESSION_REASON},
        }
    )
    assert variant["production_shared_variant_files"] == frozenset()
    assert variant["production_lane_variant_files"] == frozenset()
    assert variant["production_sandoq_variant_files"] == frozenset()
    assert shards._sha256(shards._canonical({})) == shards.TB4_V14_PRODUCTION_VARIANT_PAIR_SHA256

    source_revision = shards.TB4_V14_SUPERSESSION_SOURCE_REVISION
    source_paths = shards.tb4_v14.SUPERSESSION_SOURCE_FILES
    source_files = shards._git_file_hashes(root, source_revision, source_paths)
    production_revision = shards._git(root, "rev-parse", "HEAD")
    assert source_files == shards._git_file_hashes(root, production_revision, source_paths)
    source = {
        "project_root": "/storage/home/tianhaowu/prime-kimi-tb4-v14-lifecycle-1618064",
        "revision": source_revision,
        "hash_kind": "raw-file-sha256",
        "files": source_files,
        "file_set_sha256": shards._sha256(shards._canonical(source_files)),
    }
    assert (
        shards._validate_tb4_supersession_source(
            source,
            tb4_root=root,
            production_root=root,
            certificate_revision=contract.source_revision,
            source_paths=source_paths,
            distinct_source_revision=True,
            expected_source_revision=source_revision,
        )["source_revision"]
        == source_revision
    )
    with pytest.raises(shards.StockSmallError, match="tb4_supersession_source_invalid"):
        shards._validate_tb4_supersession_source(
            {**source, "revision": contract.source_revision},
            tb4_root=root,
            production_root=root,
            certificate_revision=contract.source_revision,
            source_paths=source_paths,
            distinct_source_revision=True,
            expected_source_revision=source_revision,
        )

    semantics = shards.tb4_transport._execution_semantics_manifest(
        contract.source_revision,
        contract.verifiers_commit,
    )
    result = shards._validate_tb4_execution_semantics(
        semantics,
        tb4_root=root,
        production_root=root,
        certificate_revision=contract.source_revision,
        verifiers_revision=contract.verifiers_commit,
        production_shared_variant_files=variant["production_shared_variant_files"],
        production_lane_variant_files=variant["production_lane_variant_files"],
        production_sandoq_variant_files=variant["production_sandoq_variant_files"],
        production_variant_pair_sha256=variant["production_variant_pair_sha256"],
    )
    assert result["production_variant_pair_sha256"] == shards.TB4_V14_PRODUCTION_VARIANT_PAIR_SHA256
    with pytest.raises(shards.StockSmallError, match="tb4_lane_specific_semantics_changed"):
        shards._validate_tb4_execution_semantics(
            semantics,
            tb4_root=root,
            production_root=root,
            certificate_revision=contract.source_revision,
            verifiers_revision=contract.verifiers_commit,
            production_shared_variant_files=variant["production_shared_variant_files"],
            production_lane_variant_files=variant["production_lane_variant_files"],
            production_sandoq_variant_files=variant["production_sandoq_variant_files"],
            production_variant_pair_sha256="0" * 64,
        )
    with pytest.raises(shards.StockSmallError, match="tb4_execution_semantics_invalid"):
        shards._validate_tb4_execution_semantics(
            semantics,
            tb4_root=root,
            production_root=root,
            certificate_revision="f" * 40,
            verifiers_revision=contract.verifiers_commit,
            production_shared_variant_files=variant["production_shared_variant_files"],
            production_lane_variant_files=variant["production_lane_variant_files"],
            production_sandoq_variant_files=variant["production_sandoq_variant_files"],
            production_variant_pair_sha256=variant["production_variant_pair_sha256"],
        )


def test_tb4_v8_supersession_source_can_be_distinct_but_is_file_exact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    production = tmp_path / "production"
    source.mkdir()
    production.mkdir()
    source_revision = "b" * 40
    certificate_revision = "a" * 40
    paths = ("one.py", "two.py")
    files = {"one.py": "1" * 64, "two.py": "2" * 64}

    monkeypatch.setattr(
        shards,
        "_git",
        lambda root, *args: source_revision if root == source else "c" * 40,
    )
    monkeypatch.setattr(shards, "_git_file_hashes", lambda *_args, **_kwargs: files)
    value = {
        "project_root": str(source),
        "revision": source_revision,
        "hash_kind": "raw-file-sha256",
        "files": files,
        "file_set_sha256": shards._sha256(shards._canonical(files)),
    }

    result = shards._validate_tb4_supersession_source(
        value,
        tb4_root=tmp_path / "execution",
        production_root=production,
        certificate_revision=certificate_revision,
        source_paths=paths,
        distinct_source_revision=True,
    )
    assert result["source_revision"] == source_revision

    with pytest.raises(shards.StockSmallError, match="tb4_supersession_source_invalid"):
        shards._validate_tb4_supersession_source(
            value,
            tb4_root=tmp_path / "execution",
            production_root=production,
            certificate_revision=certificate_revision,
            source_paths=paths,
            distinct_source_revision=True,
            expected_source_revision="d" * 40,
        )

    changed = copy.deepcopy(value)
    changed["files"]["one.py"] = "3" * 64
    with pytest.raises(shards.StockSmallError, match="tb4_supersession_source_invalid"):
        shards._validate_tb4_supersession_source(
            changed,
            tb4_root=tmp_path / "execution",
            production_root=production,
            certificate_revision=certificate_revision,
            source_paths=paths,
            distinct_source_revision=True,
        )


def test_tb4_gate_reaudits_v8_error_policy_lifecycle_and_training_exclusion() -> None:
    source = inspect.getsource(shards._validate_tb4_gate_locked)
    assert "allow_post_agent_verifier_sandbox_errors=variant[" in source
    assert '"allow_post_agent_verifier_sandbox_errors"' in source
    assert "post_agent_verifier_attempts=(" in source
    assert "audit_pre_model_sandoq_provisioning_errors=variant.get(" in source
    assert "sandoq_provisioning_attempts=(" in source
    assert "tb4_v8._post_agent_verifier_policy(trace_audit)" in source
    assert "allow_pre_ready_managed_shell_provisioning_failures = variant.get(" in source
    assert "tb4_v8._pre_model_sandoq_provisioning_policy(" in source
    assert "tb4_v8._validated_task_images(decoded_launch_plan, held)" in source
    assert "tb4_v8._assignment_lifecycle_audit(" in source
    assert "task_images=task_images" in source
    assert 'counts.get("post_agent_verifier_sandbox_error_zeroes")' in source
    assert 'counts.get("pre_model_sandoq_provisioning_error_zeroes")' in source
    assert '"excluded_post_agent_verifier_sandbox_error_rows"' in source
    assert '"excluded_pre_model_sandoq_provisioning_error_rows"' in source
    assert '"post_agent_verifier_sandbox_error_rows_are_trainable": False' in source


def test_tb4_gate_reaudits_v12_artifact_write_and_sft_eligibility() -> None:
    source = inspect.getsource(shards._validate_tb4_gate_locked)
    artifact_source = inspect.getsource(shards._validate_tb4_v12_artifact_claims)
    claim_source = inspect.getsource(shards._validate_tb4_v12_trace_claims)
    assert "tb4_v8._verified_execution_plan(" in source
    assert "tb4_v8._execution_identity_contract(" in source
    assert '"allow_exact_length_benchmark_rows"' in source
    assert '"allow_post_agent_exec_transport_errors"' in source
    assert '"allow_post_agent_artifact_write_transport_errors"' in source
    assert '"require_persisted_verifier_artifacts"' in source
    assert "_validate_tb4_v12_artifact_claims(" in source
    assert "_validate_tb4_v12_trace_claims(" in source
    assert "tb4_v8._execution_completion_audit(" in artifact_source
    assert "tb4_v8._persisted_verifier_artifact_audit(" in artifact_source
    assert "tb4_v8._exact_length_benchmark_policy(trace_audit)" in claim_source
    assert '"post_agent_verifier_artifact_write_transport_zeroes"' in claim_source
    assert '"excluded_post_agent_verifier_artifact_write_transport_rows"' in claim_source
    assert '"post_agent_verifier_artifact_write_transport_rows_are_trainable": False' in claim_source
    assert 'trace_audit.get("benchmark_valid_passes")' in claim_source
    assert 'trace_audit.get("benchmark_invalid_passing_rows")' in claim_source


def test_tb4_v12_trace_claims_are_exact_and_tamper_closed() -> None:
    trace_audit = {
        "passes": 9,
        "benchmark_valid_passes": 9,
        "trainable_passes": 8,
        "benchmark_invalid_passing_rows": 0,
        "scored_rows": 50,
        "scored_failures": 41,
        "trace_invalid_scored_rows": 1,
        "trace_invalid_passing_rows": 1,
        "model_bearing_error_zeroes": 1,
        "execution_error_zeroes": 2,
        "exact_length_nontrainable_scored_rows": 1,
        "exact_length_nontrainable_passing_rows": 1,
        "exact_length_nontrainable_nodes": 1,
        "exact_length_nontrainable_row_set_sha256": "a" * 64,
        "exact_length_error_zero_rows": 1,
        "exact_length_error_zero_nodes": 1,
        "exact_length_error_zero_row_set_sha256": "b" * 64,
        "post_agent_verifier_exec_transport_error_zeroes": 1,
        "post_agent_verifier_artifact_write_transport_error_zeroes": 1,
    }
    base_training = {
        "eligible_clean_scored_rows": 49,
        "excluded_error_rows": 2,
        "excluded_post_agent_verifier_sandbox_error_rows": 2,
        "excluded_pre_model_sandoq_provisioning_error_rows": 0,
        "excluded_trace_invalid_scored_rows": 1,
        "excluded_unsupported_rows": 14,
        "error_rows_are_trainable": False,
        "post_agent_verifier_sandbox_error_rows_are_trainable": False,
        "pre_model_sandoq_provisioning_error_rows_are_trainable": False,
        "trace_invalid_scored_rows_are_trainable": False,
    }
    expected_training = {
        **base_training,
        "eligible_clean_passes": 8,
        "excluded_post_agent_verifier_artifact_write_transport_rows": 1,
        "post_agent_verifier_artifact_write_transport_rows_are_trainable": False,
    }
    counts = {
        "provider_scored_passes": 9,
        "benchmark_scored_rows": 50,
        "benchmark_scored_failures": 41,
        "trainable_passes": 8,
        "benchmark_valid_nontrainable_passes": 1,
        "infrastructure_zeroes": 2,
        "post_agent_verifier_exec_transport_zeroes": 1,
        "post_agent_verifier_artifact_write_transport_zeroes": 1,
    }
    value = {"exact_length_benchmark_policy": shards.tb4_v8._exact_length_benchmark_policy(trace_audit)}

    assert shards._validate_tb4_v12_trace_claims(
        value,
        counts,
        expected_training,
        trace_audit,
        base_training,
    ) == (expected_training, 9, 0)

    tampered_counts = {**counts, "post_agent_verifier_artifact_write_transport_zeroes": 2}
    with pytest.raises(shards.StockSmallError, match="tb4_gate_v12_claims_invalid"):
        shards._validate_tb4_v12_trace_claims(
            value,
            tampered_counts,
            expected_training,
            trace_audit,
            base_training,
        )
    tampered_training = {
        **expected_training,
        "post_agent_verifier_artifact_write_transport_rows_are_trainable": True,
    }
    with pytest.raises(shards.StockSmallError, match="tb4_gate_v12_claims_invalid"):
        shards._validate_tb4_v12_trace_claims(
            value,
            counts,
            tampered_training,
            trace_audit,
            base_training,
        )
    tampered_policy = copy.deepcopy(value)
    tampered_policy["exact_length_benchmark_policy"]["trainable"] = True
    with pytest.raises(shards.StockSmallError, match="tb4_gate_v12_claims_invalid"):
        shards._validate_tb4_v12_trace_claims(
            tampered_policy,
            counts,
            expected_training,
            trace_audit,
            base_training,
        )


def test_tb4_v12_completion_and_persisted_artifact_claims_are_tamper_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    completion = {"state": "completed-awaiting-v11-certification"}
    completion_artifact = {"path": "/private/completion.json", "bytes": 1, "sha256": "a" * 64}
    persisted = {"state": "reopened-and-verified", "rows": 52}
    monkeypatch.setattr(
        shards.tb4_v8,
        "_execution_completion_audit",
        lambda *_args, **_kwargs: (completion, completion_artifact),
    )
    monkeypatch.setattr(
        shards.tb4_v8,
        "_persisted_verifier_artifact_audit",
        lambda *_args, **_kwargs: persisted,
    )
    value = {
        "execution_completion": completion,
        "persisted_verifier_artifacts": persisted,
    }
    artifacts = {"execution_completion": completion_artifact}
    contract = shards.tb4_v12.execution_contract(shards.tb4_v12.EXECUTION_SLURM_JOB_ID)
    shards._validate_tb4_v12_artifact_claims(
        value,
        artifacts,
        results_body=b"",
        run_dir=tmp_path,
        execution_contract=contract,
        held=None,
    )
    for changed_value, changed_artifacts in (
        ({**value, "execution_completion": {"state": "changed"}}, artifacts),
        ({**value, "persisted_verifier_artifacts": {"state": "changed"}}, artifacts),
        (value, {"execution_completion": {**completion_artifact, "sha256": "b" * 64}}),
    ):
        with pytest.raises(shards.StockSmallError, match="tb4_gate_v12_artifacts_invalid"):
            shards._validate_tb4_v12_artifact_claims(
                changed_value,
                changed_artifacts,
                results_body=b"",
                run_dir=tmp_path,
                execution_contract=contract,
                held=None,
            )
