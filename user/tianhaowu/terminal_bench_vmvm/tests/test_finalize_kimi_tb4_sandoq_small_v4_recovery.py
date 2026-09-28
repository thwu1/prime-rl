from __future__ import annotations

import finalize_kimi_tb4_sandoq_small_v4_recovery as recovery
import pytest


def _row(task: str, *, reward: float | None, turns: int, error_type: str | None = None) -> dict:
    nodes = [
        {
            "sampled": True,
            "message": {"role": "assistant", "content": "done", "reasoning_content": "reasoning"},
            "model_io": {"response": {"kind": "exact_provider_json"}},
            "usage": {"completion_tokens": 3},
        }
        for _ in range(turns)
    ]
    error = (
        []
        if error_type is None
        else [{"type": error_type, "message": "redacted failure", "traceback": "redacted traceback"}]
    )
    return {
        "id": f"trace-{task}",
        "task": {"name": f"terminal-bench/{task}"},
        "is_completed": True,
        "stop_condition": "agent_completed" if error_type is None else "error",
        "nodes": nodes,
        "rewards": {} if reward is None else {"solved": reward},
        "metrics": {},
        "info": (
            {"terminal_bench_verifier": {"mode": "separate"}}
            if error_type is None
            else ({"terminal_bench_artifacts": {"sha256": "a" * 64}} if turns else {})
        ),
        "errors": error,
    }


def _body(*rows: dict) -> bytes:
    return b"".join(recovery.split.canonical_json(row) for row in rows)


def test_fixed_denominator_audit_keeps_clean_rows_and_marks_errors_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery.audit_traces, "_audit_trace", lambda *args, **kwargs: [])
    clean = _row("clean", reward=1.0, turns=1)
    zero_model = _row("zero", reward=None, turns=0, error_type="SandboxError")
    model_bearing = _row("bearing", reward=None, turns=2, error_type="HarnessError")

    summary, rows = recovery._audit_supported_rows(
        _body(clean, zero_model, model_bearing),
        ("clean", "zero", "bearing"),
        {"clean": "separate", "zero": "separate", "bearing": "separate"},
    )

    assert summary["passes"] == 1
    assert summary["clean_scored_rows"] == 1
    assert summary["zero_model_error_zeroes"] == 1
    assert summary["model_bearing_error_zeroes"] == 1
    assert summary["execution_error_zeroes"] == 2
    assert summary["error_type_counts"] == {"HarnessError": 1, "SandboxError": 1}
    assert rows["clean"] == clean
    assert rows["zero"]["rewards"] == {"solved": 0}
    assert rows["bearing"]["rewards"] == {"solved": 0}
    assert rows["zero"]["info"]["diagnostic_evaluation_disposition"]["zero_model"] is True
    assert rows["bearing"]["info"]["diagnostic_evaluation_disposition"]["trainable"] is False


def test_fixed_denominator_audit_rejects_malformed_or_scored_error_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery.audit_traces, "_audit_trace", lambda *args, **kwargs: [])
    scored_error = _row("bad", reward=None, turns=1, error_type="SandboxError")
    scored_error["rewards"] = {"solved": 0}
    with pytest.raises(recovery.V4RecoveryError, match="error_row_invalid"):
        recovery._audit_supported_rows(
            _body(scored_error),
            ("bad",),
            {"bad": "separate"},
        )

    malformed = _row("bad", reward=None, turns=1, error_type="SandboxError")
    malformed["errors"][0]["opaque"] = True
    with pytest.raises(recovery.V4RecoveryError, match="error_row_invalid"):
        recovery._audit_supported_rows(
            _body(malformed),
            ("bad",),
            {"bad": "separate"},
        )


def test_exact_length_policy_counts_benchmark_pass_but_excludes_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row("length", reward=1.0, turns=1)
    problems = [
        "node_0_finish_reason_invalid",
        "node_0_model_io_response_finish_reason_invalid",
    ]
    monkeypatch.setattr(recovery.audit_traces, "_audit_trace", lambda *args, **kwargs: problems)
    monkeypatch.setattr(
        recovery.audit_traces,
        "_exact_length_termination_nodes",
        lambda *args, **kwargs: (0,),
    )

    summary, rows = recovery._audit_supported_rows(
        _body(row),
        ("length",),
        {"length": "separate"},
        allow_nontrainable_scored_rows=True,
        allow_exact_length_benchmark_rows=True,
    )

    assert summary["passes"] == 1
    assert summary["benchmark_valid_passes"] == 1
    assert summary["trainable_passes"] == 0
    assert summary["benchmark_invalid_passing_rows"] == 0
    assert summary["exact_length_nontrainable_passing_rows"] == 1
    assert rows["length"]["info"]["diagnostic_evaluation_disposition"]["trainable"] is False
    assert rows["length"]["nodes"] == row["nodes"]


def test_exact_length_policy_rejects_every_unrecognized_trace_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row("bad", reward=1.0, turns=1)
    monkeypatch.setattr(
        recovery.audit_traces,
        "_audit_trace",
        lambda *args, **kwargs: ["node_0_model_io_response_message_mismatch"],
    )
    monkeypatch.setattr(
        recovery.audit_traces,
        "_exact_length_termination_nodes",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(recovery.V4RecoveryError, match="provider_trace_audit_failed"):
        recovery._audit_supported_rows(
            _body(row),
            ("bad",),
            {"bad": "separate"},
            allow_nontrainable_scored_rows=True,
            allow_exact_length_benchmark_rows=True,
        )


def test_legacy_contract_diff_is_only_truthful_v4_fields() -> None:
    legacy = recovery._legacy_contracts()
    assert legacy["model_io_response_kind"] == "normalized_stream_response"
    assert "verifier_runtime_retries" not in legacy
    assert "retry_shared_verifier_scoring" not in legacy
    assert "provisioning_retries" not in legacy
    current = recovery.plan_module._contracts()
    assert current["model_io_response_kind"] == "exact_provider_json"
    assert current["verifier_runtime_retries"] == 2
    assert current["retry_shared_verifier_scoring"] is True
    assert current["provisioning_retries"] == 8
